"""Tests for provider-neutral process supervision (PROCESS SUPERVISION V1).

Only short-lived local Python helper subprocesses are used (never a real
Claude/Codex). Waiting is always a bounded poll against a deadline.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_multiworker as mw
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_process_supervision as sup
from scripts.ai import runner_providers as providers

WINDOWS = sys.platform == "win32"
SLEEP_FOREVER = [sys.executable, "-c", "import time; time.sleep(120)"]
# Parent that starts a grandchild (inherits the pipes), records its pid, sleeps.
SPAWN_TREE = (
    "import subprocess, sys, time;"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
    "open(sys.argv[1], 'w').write(str(p.pid));"
    "time.sleep(120)"
)
# Parent that starts a detached grandchild (no shared pipes) and exits at once.
SPAWN_DETACHED_AND_EXIT = (
    "import subprocess, sys;"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],"
    " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL);"
    "open(sys.argv[1], 'w').write(str(p.pid))"
)


def wait_until(predicate, timeout=20.0, interval=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def read_pid(path: Path):
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def pid_running(pid: int) -> bool:
    """Actual RUNNING state of a pid, not mere existence of a process object.

    Windows keeps a terminated process' pid resolvable while any handle to it
    is still open, so an existence check stays positive after death. The exit
    state of a freshly opened handle is what distinguishes the two. (Production
    confirmation never relies on this: it uses the owned Popen handle, the Job
    Object accounting and exit codes.)"""
    if not WINDOWS:
        return mw._pid_alive(pid) is not False
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: cannot prove it is gone
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # inconclusive is never "gone"
        return code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def pid_gone(pid: int) -> bool:
    return not pid_running(pid)


class SupervisionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        # These cases exercise lifecycle behaviour of bare helpers (some without
        # an evidence target or with a barrier-less containment). They run in
        # the explicit non-production mode; the production default is covered
        # by ProductionDurabilityTests, which does NOT derive from this class.
        patcher = mock.patch.object(sup, "_DEFAULT_REQUIRE_DURABLE_IDENTITY", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_bg(self, argv, control, *, timeout=120, stdin=None, provider="claude"):
        """Runs run_supervised in a thread; guarantees cleanup."""
        box = {}

        def target():
            box["outcome"] = sup.run_supervised(
                argv, self.tmp, stdin, timeout, provider=provider, control=control,
                grace_seconds=1.0, force_wait_seconds=15.0,
            )

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        def cleanup():
            control.request_cancel("TEST_CLEANUP")
            thread.join(60)

        self.addCleanup(cleanup)
        return thread, box

    def running(self, control) -> bool:
        process = control.process
        return process is not None and process.pid is not None and process.evidence.get("status") == sup.STATUS_RUNNING

    def new_control(self, name="a", attempt=1, write_json=None):
        return sup.ExecutionControl(
            worker_id=name, attempt=attempt, evidence_path=self.tmp / "process" / f"{name}-{attempt}.json",
            write_json=write_json,
        )


class CompletionAndCaptureTests(SupervisionCase):
    def test_normal_completion_captures_identity_and_evidence(self):  # 1, 2
        outcome = sup.run_supervised(
            [sys.executable, "-c", "print('hello')"], self.tmp, None, 30, provider="codex",
        )
        self.assertEqual(outcome.returncode, 0)
        self.assertFalse(outcome.timed_out or outcome.interrupted)
        self.assertEqual(outcome.stdout.strip(), b"hello")
        ev = outcome.evidence
        self.assertEqual(ev["status"], sup.STATUS_EXITED)
        self.assertTrue(ev["confirmed_dead"])
        self.assertEqual(ev["exit_code"], 0)
        self.assertEqual(ev["graceful_outcome"], sup.GRACEFUL_ALREADY_EXITED)
        self.assertEqual(ev["forced_outcome"], sup.FORCED_NOT_REQUIRED)
        identity = ev["identity"]
        self.assertIsInstance(identity["pid"], int)
        self.assertEqual(identity["provider"], "codex")
        self.assertEqual(identity["platform"], sys.platform)
        self.assertEqual(identity["runner_pid"], os.getpid())
        self.assertTrue(identity["started_at"])
        self.assertTrue(identity["descendants_controlled"])
        expected = sup.MODE_WINDOWS_JOB if WINDOWS else sup.MODE_POSIX_GROUP
        self.assertEqual(identity["containment_mode"], expected)
        self.assertTrue(ev["ended_at"])

    def test_stdout_stderr_stdin_utf8_and_exit_code_preserved(self):  # 3
        code = (
            "import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(d);"
            "sys.stderr.buffer.write('err-\\u00e9'.encode('utf-8')); sys.exit(3)"
        )
        payload = "prompt ünïcode — \r\n".encode("utf-8")
        outcome = sup.run_supervised([sys.executable, "-c", code], self.tmp, payload, 30)
        self.assertEqual(outcome.stdout, payload)
        self.assertEqual(outcome.stderr.decode("utf-8"), "err-é")
        self.assertEqual(outcome.returncode, 3)
        self.assertEqual(outcome.evidence["exit_code"], 3)

    def test_descendants_left_behind_after_normal_exit_are_swept(self):
        pidfile = self.tmp / "grandchild.pid"
        outcome = sup.run_supervised(
            [sys.executable, "-c", SPAWN_DETACHED_AND_EXIT, str(pidfile)], self.tmp, None, 30,
        )
        self.assertEqual(outcome.returncode, 0)
        grandchild = read_pid(pidfile)
        self.assertIsNotNone(grandchild)
        self.assertTrue(wait_until(lambda: pid_gone(grandchild)), "owned descendant outlived the execution")
        self.assertTrue(outcome.evidence["confirmed_dead"])
        self.assertTrue(outcome.evidence.get("descendants_swept_after_exit"))


class TerminationTests(SupervisionCase):
    def test_confirmed_dead_implies_os_reports_pid_gone_with_no_extra_wait(self):
        outcome = sup.run_supervised(
            SLEEP_FOREVER, self.tmp, None, 1.0, provider="claude", grace_seconds=1.0, force_wait_seconds=15.0,
        )
        self.assertTrue(outcome.evidence["confirmed_dead"])
        self.assertNotIn("termination_unresolved", outcome.evidence)
        self.assertTrue(pid_gone(outcome.evidence["identity"]["pid"]),
                        "confirmed_dead persisted while the OS still reports the pid alive")

    def test_undead_child_is_never_reported_confirmed_dead_and_is_recorded_unresolved(self):
        class Refusing(sup.ProcessContainment):
            mode = "TEST_REFUSING"

            def force_terminate(self, proc):
                return False  # OS "refuses": nothing owned gets killed by the containment

            def is_empty(self, proc):
                return False

        sp = sup.SupervisedProcess(
            SLEEP_FOREVER, self.tmp, provider="claude", containment=Refusing(),
            grace_seconds=0.1, force_wait_seconds=0.3,
        )
        sp.start()
        self.addCleanup(lambda: (sp._proc.kill(), sp._proc.wait(10)))
        result = sp.terminate("TEST")
        self.assertFalse(result.confirmed_dead)
        self.assertFalse(sp.confirmed_dead)
        self.assertIs(sp.evidence["termination_unresolved"], True)
        self.assertEqual(sp.evidence["status"], sup.STATUS_UNRESOLVED)

    def test_timeout_terminates_owned_child_and_confirms_death(self):  # 4
        started = time.monotonic()
        outcome = sup.run_supervised(
            SLEEP_FOREVER, self.tmp, None, 1.0, provider="claude", grace_seconds=1.0, force_wait_seconds=15.0,
        )
        self.assertTrue(outcome.timed_out)
        self.assertFalse(outcome.interrupted)
        self.assertLess(time.monotonic() - started, 60)
        ev = outcome.evidence
        self.assertTrue(ev["confirmed_dead"])
        self.assertEqual(ev["termination_reason"], "TIMEOUT")
        self.assertTrue(ev["termination_requested_at"])
        self.assertEqual(ev["status"], sup.STATUS_TERMINATED)
        self.assertIsNotNone(outcome.returncode)
        self.assertIn(ev["graceful_outcome"], {
            sup.GRACEFUL_EXITED, sup.GRACEFUL_TIMEOUT, sup.GRACEFUL_UNAVAILABLE,
        })

    def test_timeout_also_terminates_descendants(self):  # 4
        pidfile = self.tmp / "gc.pid"
        control = self.new_control()
        thread, box = self.run_bg(
            [sys.executable, "-c", SPAWN_TREE, str(pidfile)], control, timeout=6.0,
        )
        self.assertTrue(wait_until(lambda: read_pid(pidfile) is not None), "helper never started its child")
        grandchild = read_pid(pidfile)
        thread.join(60)
        self.assertFalse(thread.is_alive())
        self.assertTrue(box["outcome"].timed_out)
        self.assertTrue(box["outcome"].evidence["confirmed_dead"])
        self.assertTrue(wait_until(lambda: pid_gone(grandchild)), "descendant survived the timeout")

    def test_forced_cancellation_terminates_owned_tree(self):  # 5
        pidfile = self.tmp / "gc.pid"
        control = self.new_control()
        thread, box = self.run_bg([sys.executable, "-c", SPAWN_TREE, str(pidfile)], control)
        self.assertTrue(wait_until(lambda: read_pid(pidfile) is not None and self.running(control)))
        grandchild = read_pid(pidfile)
        control.request_cancel("FORCED_SHUTDOWN")
        thread.join(60)
        self.assertFalse(thread.is_alive())
        outcome = box["outcome"]
        self.assertTrue(outcome.interrupted)
        self.assertFalse(outcome.timed_out)
        self.assertEqual(outcome.evidence["termination_reason"], "FORCED_SHUTDOWN")
        self.assertTrue(outcome.evidence["confirmed_dead"])
        self.assertTrue(wait_until(lambda: pid_gone(grandchild)))
        self.assertEqual(control.resolution(), (True, "PROCESS_CONFIRMED_DEAD"))

    def test_cancel_before_launch_never_starts_a_process(self):
        control = self.new_control()
        control.request_cancel("EARLY")
        outcome = sup.run_supervised(SLEEP_FOREVER, self.tmp, None, 30, control=control)
        self.assertTrue(outcome.interrupted)
        self.assertIsNone(outcome.returncode)
        self.assertIsNone(control.process)
        self.assertEqual(control.resolution(), (True, "NO_PROCESS_STARTED_AND_LAUNCH_BLOCKED"))
        self.assertFalse((self.tmp / "process").exists())

    def test_terminate_on_already_exited_process_is_idempotent(self):  # 6
        sp = sup.SupervisedProcess([sys.executable, "-c", "pass"], self.tmp, provider="claude")
        sp.start()
        sp.run(None, 30)
        result = sp.terminate("LATE")
        self.assertTrue(result.confirmed_dead)
        self.assertEqual(result.graceful_outcome, sup.GRACEFUL_ALREADY_EXITED)
        self.assertEqual(result.forced_outcome, sup.FORCED_NOT_REQUIRED)
        self.assertIs(sp.terminate("AGAIN"), result)

    def test_repeated_terminate_is_safe_and_returns_first_result(self):  # 7
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, provider="claude", grace_seconds=1.0)
        sp.start()
        self.addCleanup(lambda: sp._close_pipes(sp._proc))
        first = sp.terminate("ONE")
        second = sp.terminate("TWO")
        self.assertTrue(first.confirmed_dead)
        self.assertIs(first, second)
        self.assertEqual(sp.evidence["termination_reason"], "ONE")
        self.assertIsNotNone(sp._proc.poll())

    def test_terminate_from_another_thread_matches_worker_thread(self):
        control = self.new_control()
        thread, box = self.run_bg(SLEEP_FOREVER, control)
        self.assertTrue(wait_until(lambda: self.running(control)))
        result = control.terminate_now("FORCED_SHUTDOWN")
        self.assertTrue(result.confirmed_dead)
        thread.join(60)
        self.assertTrue(box["outcome"].evidence["confirmed_dead"])

    def test_unrelated_process_is_never_terminated(self):  # 8
        import subprocess

        bystander = subprocess.Popen(SLEEP_FOREVER, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait(30)))
        outcome = sup.run_supervised(SLEEP_FOREVER, self.tmp, None, 0.5, grace_seconds=0.5, force_wait_seconds=15.0)
        self.assertTrue(outcome.timed_out)
        self.assertIsNone(bystander.poll())


class IsolationAndEvidenceTests(SupervisionCase):
    def test_two_concurrent_supervised_processes_are_isolated(self):  # 9, 10
        a, b = self.new_control("A"), self.new_control("B")
        thread_a, box_a = self.run_bg(SLEEP_FOREVER, a, provider="claude")
        thread_b, box_b = self.run_bg(SLEEP_FOREVER, b, provider="codex")
        self.assertTrue(wait_until(lambda: self.running(a) and self.running(b)))
        self.assertNotEqual(a.process.pid, b.process.pid)
        self.assertIsNot(a.process, b.process)
        b_proc = b.process._proc

        a.request_cancel("FORCED_SHUTDOWN")
        thread_a.join(60)
        self.assertFalse(thread_a.is_alive())
        self.assertTrue(box_a["outcome"].interrupted)
        self.assertTrue(box_a["outcome"].evidence["confirmed_dead"])
        # B is untouched: still running, never cancelled, not terminated.
        self.assertIsNone(b_proc.poll())
        self.assertFalse(b.cancelled)
        self.assertIsNone(b.process.evidence["termination_requested_at"])
        self.assertEqual(b.resolution(), (False, "PROCESS_LIVENESS_UNCONFIRMED"))

        b.request_cancel("FORCED_SHUTDOWN")
        thread_b.join(60)
        self.assertTrue(box_b["outcome"].evidence["confirmed_dead"])

    def test_evidence_is_written_per_attempt_and_early(self):  # 11
        seen = {}
        lock = threading.Lock()

        def recorder(path, payload):
            with lock:
                seen.setdefault(str(path), []).append((payload["status"], (payload.get("identity") or {}).get("pid")))
            sup._default_write_json(path, payload)

        one = self.new_control("w", attempt=1, write_json=recorder)
        two = self.new_control("w", attempt=2, write_json=recorder)
        secret = "TOP-SECRET-PROMPT-TEXT"
        for control in (one, two):
            outcome = sup.run_supervised(
                [sys.executable, "-c", "import sys; sys.stdin.read()", "--token=ARG-SECRET"], self.tmp,
                secret.encode("utf-8"), 30, provider="claude", control=control,
            )
            self.assertTrue(outcome.evidence["confirmed_dead"])
        self.assertEqual(len(seen), 2)
        for control, attempt in ((one, 1), (two, 2)):
            statuses = seen[str(control.evidence_path)]
            # Intent is durable before the process exists; the pid follows
            # before the child is allowed to run.
            self.assertEqual(statuses[0], (sup.STATUS_LAUNCHING, None))
            self.assertEqual(statuses[1][0], sup.STATUS_RUNNING)
            self.assertIsInstance(statuses[1][1], int)
            self.assertEqual(statuses[-1][0], sup.STATUS_EXITED)
            raw = control.evidence_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self.assertEqual((data["worker_id"], data["attempt"]), ("w", attempt))
            self.assertTrue(data["confirmed_dead"])
            self.assertNotIn(secret, raw)
            self.assertNotIn("ARG-SECRET", raw)
            self.assertNotIn("argv", data)

    def test_no_global_process_singleton_in_module(self):
        source = Path(sup.__file__).read_text(encoding="utf-8")
        for token in ("CURRENT_PROCESS", "_current_process", "global "):
            self.assertNotIn(token, source)


class ContainmentTests(SupervisionCase):
    def test_containment_selection_is_platform_safe(self):  # 17
        self.assertIsInstance(sup.create_containment(platform_name="linux"), sup.PosixGroupContainment)
        self.assertIsInstance(sup.create_containment(platform_name="darwin"), sup.PosixGroupContainment)
        if WINDOWS:
            self.assertIsInstance(sup.create_containment(platform_name="win32"), sup.WindowsJobContainment)
        if os.name != "posix":
            with self.assertRaises(sup.ContainmentUnavailableError):
                sup.create_containment(platform_name="plan9")
            self.assertIsInstance(
                sup.create_containment(platform_name="plan9", allow_degraded=True), sup.PidOnlyContainment,
            )

    def test_containment_failure_fails_closed_and_leaves_nothing_running(self):  # 17
        class Refusing(sup.ProcessContainment):
            mode = "TEST_REFUSING"

            def adopt(self, proc):
                self.child = proc
                raise sup.ContainmentUnavailableError("job assignment refused")

        containment = Refusing()
        control = self.new_control()
        outcome = sup.run_supervised(SLEEP_FOREVER, self.tmp, None, 30, control=control, containment=containment)
        self.assertIsNone(outcome.returncode)
        self.assertIn(b"refused to start", outcome.stderr)
        self.assertEqual(outcome.evidence["status"], sup.STATUS_LAUNCH_FAILED)
        self.assertIn("job assignment refused", outcome.evidence["launch_error"])
        self.assertTrue(wait_until(lambda: containment.child.poll() is not None), "uncontained child left running")
        self.assertTrue(control.process.confirmed_dead)

    def test_degraded_mode_is_explicit_in_evidence(self):  # 17
        outcome = sup.run_supervised(
            [sys.executable, "-c", "pass"], self.tmp, None, 30, containment=sup.PidOnlyContainment(),
        )
        identity = outcome.evidence["identity"]
        self.assertEqual(identity["containment_mode"], sup.MODE_DEGRADED)
        self.assertFalse(identity["descendants_controlled"])

    @unittest.skipUnless(WINDOWS, "Windows Job Object behaviour")
    def test_windows_job_object_ownership_and_kill_on_close(self):  # 17
        pidfile = self.tmp / "gc.pid"
        sp = sup.SupervisedProcess(
            [sys.executable, "-c", SPAWN_TREE, str(pidfile)], self.tmp, provider="claude", force_wait_seconds=15.0,
        )
        sp.start()
        self.addCleanup(lambda: (sp.terminate("CLEANUP"), sp._close_pipes(sp._proc)))
        self.assertEqual(sp.identity.containment_mode, sup.MODE_WINDOWS_JOB)
        self.assertTrue(sp.identity.job_id)
        self.assertTrue(wait_until(lambda: read_pid(pidfile) is not None), "child never ran after resume")
        grandchild = read_pid(pidfile)
        # Parent + grandchild (a venv launcher stub may add more): all in the job.
        self.assertGreaterEqual(sp._containment._active_processes(), 2)
        # Parent-death semantics: when the last handle to the job disappears
        # (exactly what the kernel does if the Runner dies) KILL_ON_JOB_CLOSE
        # terminates every process in it, descendants included.
        sp._containment.close()
        self.assertTrue(wait_until(lambda: sp._proc.poll() is not None), "direct child survived job close")
        self.assertTrue(wait_until(lambda: pid_gone(grandchild)), "descendant survived job close")

    @unittest.skipIf(WINDOWS, "POSIX process group behaviour")
    def test_posix_group_ownership_recorded(self):  # 17
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, provider="claude", grace_seconds=1.0)
        sp.start()
        self.addCleanup(lambda: sp._close_pipes(sp._proc))
        self.assertEqual(sp.identity.process_group, sp.pid)
        self.assertEqual(sp.identity.session, sp.pid)
        self.assertNotEqual(os.getpgid(sp.pid), os.getpgid(os.getpid()))
        self.assertTrue(sp.terminate("TEST").confirmed_dead)


class _CountingContainment(sup.PidOnlyContainment):
    """Degraded containment that records how often its resources were closed."""

    def __init__(self):
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


class CommunicationFailureTests(SupervisionCase):  # FIX2 2
    def _sp(self, containment=None, write_json=None):
        sp = sup.SupervisedProcess(
            SLEEP_FOREVER, self.tmp, provider="claude", containment=containment, grace_seconds=1.0,
            force_wait_seconds=15.0, evidence_path=self.tmp / "process" / "a-1.json", write_json=write_json,
        )
        sp.start()
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        return sp

    def _run_failing(self, sp, exc, *, patch_terminate=None):
        stack = [mock.patch.object(sup._OwnedPopen, "communicate", side_effect=exc)]
        if patch_terminate is not None:
            stack.append(mock.patch.object(sup.SupervisedProcess, "terminate", side_effect=patch_terminate))
        with stack[0]:
            if patch_terminate is None:
                with self.assertRaises(type(exc)) as ctx:
                    sp.run(None, 30)
            else:
                with stack[1], self.assertRaises(type(exc)) as ctx:
                    sp.run(None, 30)
        self.assertIs(ctx.exception, exc)  # the ORIGINAL failure propagates, not swallowed or replaced
        return ctx.exception

    def test_communicate_oserror_terminates_the_owned_real_process(self):  # FIX2 3
        sp = self._sp()
        pid = sp.pid
        self._run_failing(sp, OSError("pipe broke"))
        self.assertTrue(wait_until(lambda: pid_gone(pid)), "provider left alive after communicate() failed")
        self.assertIsNotNone(sp._proc.poll())

    def test_communication_exception_closes_containment(self):  # FIX2 4
        containment = _CountingContainment()
        sp = self._sp(containment)
        self._run_failing(sp, OSError("pipe broke"))
        self.assertEqual(containment.closes, 1)
        if WINDOWS:
            real = self._sp()
            self._run_failing(real, OSError("pipe broke"))
            self.assertIsNone(real._containment._job, "Job Object left open after a communication failure")

    def test_communication_exception_finalizes_non_running_evidence(self):  # FIX2 5
        sp = self._sp()
        self._run_failing(sp, OSError("pipe broke"))
        for evidence in (sp.evidence, json.loads((self.tmp / "process" / "a-1.json").read_text(encoding="utf-8"))):
            self.assertNotEqual(evidence["status"], sup.STATUS_RUNNING)
            self.assertEqual(evidence["status"], sup.STATUS_TERMINATED)
            self.assertTrue(evidence["confirmed_dead"])
            self.assertEqual(evidence["termination_reason"], "COMMUNICATION_FAILURE:OSError")
            self.assertIsNotNone(evidence["ended_at"])

    def test_failing_cancel_callback_also_ends_in_owned_cleanup(self):  # FIX2 3
        sp = self._sp()
        boom = RuntimeError("cancel probe broke")

        def cancelled():
            raise boom

        with self.assertRaises(RuntimeError) as ctx:
            sp.run(None, 30, cancelled=cancelled)
        self.assertIs(ctx.exception, boom)
        self.assertTrue(sp.confirmed_dead)
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)))

    def test_broken_termination_path_falls_back_to_direct_owned_kill(self):  # FIX2 3
        sp = self._sp()
        pid = sp.pid
        original = OSError("pipe broke")
        self._run_failing(sp, original, patch_terminate=RuntimeError("terminate itself broke"))
        self.assertTrue(wait_until(lambda: pid_gone(pid)))
        self.assertEqual(sp.evidence["status"], sup.STATUS_TERMINATED)
        self.assertTrue(sp.evidence["confirmed_dead"])
        self.assertEqual(sp.evidence["termination_error"], "RuntimeError")

    def test_run_supervised_never_returns_control_with_a_live_provider(self):  # FIX2 3
        control = self.new_control()
        with mock.patch.object(sup._OwnedPopen, "communicate", side_effect=OSError("pipe broke")):
            with self.assertRaises(OSError):
                sup.run_supervised(SLEEP_FOREVER, self.tmp, None, 30, control=control,
                                   grace_seconds=1.0, force_wait_seconds=15.0)
        self.assertTrue(control.process.confirmed_dead)
        self.assertTrue(wait_until(lambda: pid_gone(control.process.pid)))


class DurableIdentityTests(SupervisionCase):  # FIX2 11
    def _flaky_writer(self):
        calls = []

        def write(path, payload):
            calls.append(payload["status"])
            if len(calls) == 2:  # 1: launch intent, 2: process identity
                raise OSError("disk full")
            sup._default_write_json(path, payload)

        return write, calls

    def test_identity_persistence_failure_terminates_the_owned_provider(self):
        write, calls = self._flaky_writer()
        sp = sup.SupervisedProcess(
            SLEEP_FOREVER, self.tmp, provider="claude", evidence_path=self.tmp / "ev.json", write_json=write,
            force_wait_seconds=15.0,
        )
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        with self.assertRaises(OSError):
            sp.start()
        self.assertTrue(sp.started)
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)), "provider left running without durable identity")
        self.assertEqual(sp.evidence["status"], sup.STATUS_LAUNCH_FAILED)
        self.assertTrue(sp.evidence["confirmed_dead"])
        self.assertEqual(json.loads((self.tmp / "ev.json").read_text(encoding="utf-8"))["status"], sup.STATUS_LAUNCH_FAILED)

    @unittest.skipUnless(WINDOWS, "suspended launch")
    def test_windows_provider_is_never_resumed_when_identity_cannot_be_persisted(self):
        marker = self.tmp / "ran.txt"
        write, _ = self._flaky_writer()
        sp = sup.SupervisedProcess(
            [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write('ran')", str(marker)], self.tmp,
            provider="claude", evidence_path=self.tmp / "ev.json", write_json=write, force_wait_seconds=15.0,
        )
        with self.assertRaises(OSError):
            sp.start()
        self.assertIsNotNone(sp._proc.poll())
        self.assertFalse(marker.exists(), "provider code ran although its identity was never durable")

    def test_run_supervised_propagates_identity_failure_with_nothing_left_running(self):
        write, _ = self._flaky_writer()
        control = self.new_control(write_json=write)
        with self.assertRaises(OSError):
            sup.run_supervised(SLEEP_FOREVER, self.tmp, None, 30, control=control, force_wait_seconds=15.0)
        self.assertTrue(control.process.confirmed_dead)
        self.assertTrue(wait_until(lambda: pid_gone(control.process.pid)))

    def test_evidence_never_carries_secrets_on_the_failure_path(self):
        write, _ = self._flaky_writer()
        sp = sup.SupervisedProcess(
            [sys.executable, "-c", "import time; time.sleep(120)", "--token=ARG-SECRET"], self.tmp,
            evidence_path=self.tmp / "ev.json", write_json=write, force_wait_seconds=15.0,
            env={**os.environ, "API_KEY": "ENV-SECRET"},
        )
        with self.assertRaises(OSError):
            sp.start()
        raw = (self.tmp / "ev.json").read_text(encoding="utf-8")
        self.assertNotIn("ARG-SECRET", raw)
        self.assertNotIn("ENV-SECRET", raw)


@unittest.skipUnless(WINDOWS, "Windows Job Object behaviour")
class WindowsLaunchFailureTests(SupervisionCase):  # FIX2 9
    def _launch_with_adopt_failure(self, exc):
        real_adopt = sup.WindowsJobContainment.adopt

        def adopt_then_fail(containment, proc):
            real_adopt(containment, proc)  # Job Object allocated AND child assigned...
            raise exc  # ...then the adoption step blows up

        containment = sup.WindowsJobContainment()
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, provider="claude", containment=containment,
                                   evidence_path=self.tmp / "ev.json", force_wait_seconds=15.0)
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        with mock.patch.object(sup.WindowsJobContainment, "adopt", adopt_then_fail):
            with self.assertRaises(type(exc)) as ctx:
                sp.start()
        self.assertIs(ctx.exception, exc)
        return sp, containment

    def test_exception_after_job_allocation_closes_the_job_and_finalizes_evidence(self):
        sp, containment = self._launch_with_adopt_failure(RuntimeError("adoption exploded"))
        self.assertIsNone(containment._job, "Job Object handle leaked")
        self.assertIsNotNone(sp._proc.poll())
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)))
        self.assertEqual(sp.evidence["status"], sup.STATUS_LAUNCH_FAILED)
        self.assertTrue(sp.evidence["confirmed_dead"])
        self.assertIn("adoption exploded", sp.evidence["launch_error"])

    def test_resume_failure_closes_the_job(self):
        containment = sup.WindowsJobContainment()
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, containment=containment, force_wait_seconds=15.0)
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        with mock.patch.object(sup.WindowsJobContainment, "release_child", side_effect=OSError("resume broke")):
            with self.assertRaises(OSError):
                sp.start()
        self.assertIsNone(containment._job)
        self.assertIsNotNone(sp._proc.poll())
        self.assertTrue(sp.confirmed_dead)

    def test_unconfirmed_death_keeps_the_job_for_a_later_terminate_and_never_claims_dead(self):
        containment = sup.WindowsJobContainment()
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, containment=containment, force_wait_seconds=0.3)
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        real_adopt = sup.WindowsJobContainment.adopt

        def adopt_then_fail(c, proc):
            real_adopt(c, proc)
            raise RuntimeError("boom")

        with mock.patch.object(sup.WindowsJobContainment, "adopt", adopt_then_fail), \
                mock.patch.object(sup.WindowsJobContainment, "is_empty", return_value=False), \
                mock.patch.object(sup.WindowsJobContainment, "force_terminate", return_value=False):
            with self.assertRaises(RuntimeError):
                sp.start()
        self.assertFalse(sp.evidence["confirmed_dead"])
        self.assertEqual(sp.evidence["status"], sup.STATUS_UNRESOLVED)
        self.assertTrue(sp.evidence["termination_unresolved"])
        self.assertIsNotNone(containment._job)  # still reachable for a retry
        self.assertTrue(sp.terminate("RETRY").confirmed_dead)  # unpatched: the retry really kills and closes
        self.assertIsNone(containment._job)


class HandleOwnershipTests(SupervisionCase):  # FIX2 8, 10
    class _Handle:
        def __init__(self):
            self.closes = 0

        def Close(self):
            self.closes += 1

    class _FakePopen:
        def __init__(self):
            self._handle = HandleOwnershipTests._Handle()
            self.returncode = None
            self.inside = threading.Event()
            self.release = threading.Event()

        def poll(self):
            self.inside.set()
            assert self.release.wait(10), "test never released the in-flight poll"
            return self.returncode

    def test_handle_close_is_deferred_until_the_in_flight_call_returns(self):  # FIX2 8
        fake = self._FakePopen()
        owned = sup._OwnedPopen(fake)
        worker = threading.Thread(target=owned.poll, daemon=True)
        worker.start()
        self.assertTrue(fake.inside.wait(10))
        fake.returncode = 0  # death recorded while the worker is still inside Popen
        owned.release_handle()
        self.assertEqual(fake._handle.closes, 0, "handle closed under a thread that is still using it")
        fake.release.set()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(fake._handle.closes, 1)
        owned.release_handle()
        owned.release_handle()
        self.assertEqual(fake._handle.closes, 1)  # idempotent

    def test_handle_is_never_closed_before_death_is_recorded(self):  # FIX2 8
        fake = self._FakePopen()
        owned = sup._OwnedPopen(fake)
        owned.release_handle()
        self.assertEqual(fake._handle.closes, 0)
        fake.returncode = 0
        owned.release_handle()
        self.assertEqual(fake._handle.closes, 1)

    @unittest.skipUnless(WINDOWS, "native Windows process handle")
    def test_concurrent_wait_and_terminate_cannot_hit_an_invalid_handle(self):  # FIX2 8
        import _winapi

        sp = sup.SupervisedProcess(
            [sys.executable, "-c", "import time; time.sleep(0.3)"], self.tmp, provider="claude", force_wait_seconds=15.0,
        )
        sp.start()
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        proc = sp._proc
        handle = proc._handle
        inside, release = threading.Event(), threading.Event()
        who, errors = {}, []
        real = _winapi.GetExitCodeProcess

        def held(h):
            # The worker is parked exactly where Popen reads the exit code.
            if threading.current_thread() is who.get("worker"):
                inside.set()
                release.wait(20)
            return real(h)

        def wait_worker():
            try:
                proc.wait(timeout=30)
            except OSError as exc:  # WinError 6 before the fix
                errors.append(exc)

        who["worker"] = threading.Thread(target=wait_worker, daemon=True)
        with mock.patch.object(_winapi, "GetExitCodeProcess", held):
            who["worker"].start()
            self.assertTrue(inside.wait(20), "worker never reached GetExitCodeProcess")
            result = sp.terminate("RACE")  # terminator finalizes while the waiter is inside the handle
            self.assertTrue(result.confirmed_dead)
            self.assertFalse(getattr(handle, "closed", False), "process handle closed under the waiter")
            release.set()
            who["worker"].join(20)
        self.assertFalse(who["worker"].is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(getattr(handle, "closed", True), "deferred close never happened")

    def test_native_cleanup_is_idempotent(self):  # FIX2 10
        containment = _CountingContainment()
        sp = sup.SupervisedProcess([sys.executable, "-c", "pass"], self.tmp, containment=containment)
        sp.start()
        sp.run(None, 30)
        first = sp.terminate("ONE")
        for _ in range(3):
            self.assertIs(sp.terminate("AGAIN"), first)
            sp._proc.release_handle()
            sp._finalize_evidence(exited_normally=True)
        self.assertTrue(first.confirmed_dead)
        self.assertEqual(sp.evidence["status"], sup.STATUS_EXITED)

    @unittest.skipUnless(WINDOWS, "Job Object handle")
    def test_windows_native_cleanup_is_idempotent(self):  # FIX2 10
        sp = sup.SupervisedProcess([sys.executable, "-c", "pass"], self.tmp, force_wait_seconds=15.0)
        sp.start()
        sp.run(None, 30)
        for _ in range(3):
            sp._containment.close()
            sp._proc.release_handle()
            self.assertTrue(sp.terminate("AGAIN").confirmed_dead)
        self.assertIsNone(sp._containment._job)
        self.assertTrue(getattr(sp._proc._handle, "closed", True))


class ContainmentRecoveryTests(SupervisionCase):  # FIX2 6, 7
    def test_unknown_or_degraded_containment_never_proves_descendants_gone(self):
        for identity in ({}, {"containment_mode": sup.MODE_DEGRADED}, {"containment_mode": "SOMETHING_ELSE"}):
            gone, detail = sup.assess_recorded_containment(identity, pid_alive=lambda pid: False)
            self.assertFalse(gone, identity)
            self.assertEqual(detail, "CONTAINMENT_CANNOT_PROVE_DESCENDANTS_GONE")

    def test_group_states_map_conservatively(self):
        identity = {"containment_mode": sup.MODE_POSIX_GROUP, "process_group": 4321, "pid": 4321}
        expected = {
            True: (True, "PROCESS_GROUP_EMPTY"),
            False: (False, "PROCESS_GROUP_MAY_STILL_CONTAIN_PROCESSES"),
            None: (False, "PROCESS_GROUP_PROBE_INCONCLUSIVE"),
        }
        for state, outcome in expected.items():
            self.assertEqual(
                sup.assess_recorded_containment(identity, pid_alive=lambda pid: False, group_probe=lambda g: state),
                outcome,
            )
        self.assertEqual(
            sup.assess_recorded_containment(
                {"containment_mode": sup.MODE_POSIX_GROUP, "pid": 4321}, pid_alive=lambda pid: False,
            ),
            (False, "NO_PROCESS_GROUP_RECORDED"),
        )

    def test_probe_rejects_unusable_group_ids(self):
        for bad in (None, True, "12", 0, 1, -5):
            self.assertIsNone(sup.probe_posix_group(bad), bad)

    @unittest.skipIf(WINDOWS, "POSIX process group behaviour")
    def test_posix_dead_leader_with_surviving_child_is_not_resolved(self):  # FIX2 6
        import subprocess

        pidfile = self.tmp / "gc.pid"
        leader = subprocess.Popen(
            [sys.executable, "-c", SPAWN_DETACHED_AND_EXIT, str(pidfile)], start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        grandchild = None
        try:
            leader.wait(30)  # the direct leader is gone...
            self.assertTrue(wait_until(lambda: read_pid(pidfile) is not None))
            grandchild = read_pid(pidfile)
            identity = {"containment_mode": sup.MODE_POSIX_GROUP, "process_group": leader.pid, "pid": leader.pid}
            self.assertTrue(pid_gone(leader.pid))
            self.assertIs(sup.probe_posix_group(leader.pid), False)  # ...but its group still holds a process
            gone, detail = sup.assess_recorded_containment(identity, pid_alive=mw._pid_alive)
            self.assertFalse(gone)
            self.assertEqual(detail, "PROCESS_GROUP_MAY_STILL_CONTAIN_PROCESSES")
            self.assertIsNone(os.kill(grandchild, 0), "assessment must not have disturbed the survivor")
        finally:
            if grandchild is not None:
                try:
                    os.kill(grandchild, 9)
                except OSError:
                    pass
        self.assertTrue(wait_until(lambda: sup.probe_posix_group(leader.pid) is True))
        self.assertEqual(
            sup.assess_recorded_containment(identity, pid_alive=mw._pid_alive), (True, "PROCESS_GROUP_EMPTY"),
        )

    @unittest.skipUnless(WINDOWS, "Windows Job Object recovery")
    def test_windows_job_recovery_requires_a_dead_owner_and_a_dead_child(self):
        import subprocess

        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait(30)
        done._handle.Close()  # an open Popen handle would keep the dead pid "alive" to the probe
        live =subprocess.Popen(SLEEP_FOREVER, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (live.kill(), live.wait(30)))

        def identity(owner, child):
            return {"containment_mode": sup.MODE_WINDOWS_JOB, "runner_pid": owner, "pid": child}

        probe = mw._pid_alive
        self.assertTrue(wait_until(lambda: pid_gone(done.pid)))
        self.assertEqual(sup.assess_recorded_containment(identity(done.pid, done.pid), pid_alive=probe)[0], True)
        self.assertEqual(sup.assess_recorded_containment(identity(live.pid, done.pid), pid_alive=probe),
                         (False, "JOB_OWNER_MAY_STILL_BE_RUNNING"))
        self.assertEqual(sup.assess_recorded_containment(identity(done.pid, live.pid), pid_alive=probe),
                         (False, "JOB_CHILD_MAY_STILL_BE_RUNNING"))
        self.assertEqual(sup.assess_recorded_containment(identity(os.getpid(), done.pid), pid_alive=probe),
                         (False, "JOB_HANDLE_HELD_BY_THIS_PROCESS"))
        self.assertEqual(sup.assess_recorded_containment(identity(None, done.pid), pid_alive=probe),
                         (False, "JOB_OWNER_NOT_RECORDED"))
        self.assertEqual(sup.assess_recorded_containment(identity(done.pid, done.pid), pid_alive=lambda pid: None),
                         (False, "JOB_OWNER_MAY_STILL_BE_RUNNING"))


class WorkerIndependenceTests(SupervisionCase):  # FIX2 12, 13
    def _start(self, provider):
        sp = sup.SupervisedProcess(SLEEP_FOREVER, self.tmp, provider=provider, grace_seconds=1.0, force_wait_seconds=15.0)
        sp.start()
        self.addCleanup(lambda: sp.terminate("TEST_CLEANUP"))
        return sp

    def test_terminating_worker_a_leaves_worker_b_and_a_bystander_alive(self):
        import subprocess

        bystander = subprocess.Popen(SLEEP_FOREVER, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait(30)))
        a, b = self._start("claude"), self._start("codex")
        self.assertTrue(a.terminate("A_ONLY").confirmed_dead)
        self.assertTrue(wait_until(lambda: pid_gone(a.pid)))
        self.assertIsNone(b._proc.poll(), "worker B was affected by terminating A")
        self.assertFalse(b.confirmed_dead)
        self.assertIsNone(bystander.poll(), "an unrelated process was touched")

    def test_communication_failure_in_a_leaves_b_and_a_bystander_alive(self):
        import subprocess

        bystander = subprocess.Popen(SLEEP_FOREVER, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait(30)))
        a, b = self._start("claude"), self._start("codex")
        with mock.patch.object(sup._OwnedPopen, "communicate", side_effect=OSError("A broke")):
            with self.assertRaises(OSError):
                a.run(None, 30)
        self.assertTrue(a.confirmed_dead)
        self.assertIsNone(b._proc.poll())
        self.assertIsNone(bystander.poll())


class _ProbeBreakingContainment(_CountingContainment):
    """Degraded containment whose emptiness probe can be made to raise."""

    broken = True

    def is_empty(self, proc):
        if self.broken:
            raise RuntimeError("containment probe broke")
        return super().is_empty(proc)


class _CloseBreakingContainment(_CountingContainment):
    """Containment whose close() can be made to raise (after real death)."""

    broken = True

    def close(self) -> None:
        if self.broken:
            raise RuntimeError("containment close broke")
        super().close()


class SecondaryCleanupTests(SupervisionCase):  # FIX3 4
    def _sp(self, containment):
        sp = sup.SupervisedProcess(
            SLEEP_FOREVER, self.tmp, provider="claude", containment=containment, grace_seconds=0.5,
            force_wait_seconds=0.5, evidence_path=self.tmp / "process" / "a-1.json",
        )
        sp.start()
        self.addCleanup(lambda: (setattr(containment, "broken", False), sp.terminate("TEST_CLEANUP")))
        return sp

    def _disk(self):
        return json.loads((self.tmp / "process" / "a-1.json").read_text(encoding="utf-8"))

    def test_secondary_probe_exception_preserves_the_original_error(self):  # 10
        containment = _ProbeBreakingContainment()
        sp = self._sp(containment)
        original = OSError("pipe broke")
        with mock.patch.object(sup._OwnedPopen, "communicate", side_effect=original):
            with self.assertRaises(OSError) as ctx:
                sp.run(None, 30)
        self.assertIs(ctx.exception, original)  # not replaced by the probe's RuntimeError
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)), "owned child survived")
        for evidence in (sp.evidence, self._disk()):
            self.assertNotEqual(evidence["status"], sup.STATUS_TERMINATING)
            self.assertEqual(evidence["status"], sup.STATUS_UNRESOLVED)
            self.assertFalse(evidence["confirmed_dead"], "probe failure must never yield confirmed_dead")
            self.assertIs(evidence["termination_unresolved"], True)
            self.assertTrue(any("containment_probe" in e for e in evidence["cleanup_errors"]))
        self.assertEqual(containment.closes, 0, "resources released although emptiness was never proven")
        self.assertFalse(sp.confirmed_dead)

    def test_cleanup_is_idempotent_and_a_later_clean_probe_resolves_it(self):  # 12
        containment = _ProbeBreakingContainment()
        sp = self._sp(containment)
        with mock.patch.object(sup._OwnedPopen, "communicate", side_effect=OSError("pipe broke")):
            with self.assertRaises(OSError):
                sp.run(None, 30)
        containment.broken = False
        first = sp.terminate("RETRY")
        self.assertTrue(first.confirmed_dead)
        self.assertEqual(containment.closes, 1)
        for _ in range(3):
            self.assertIs(sp.terminate("AGAIN"), first)
            sp._proc.release_handle()
            sp._finalize_evidence(exited_normally=True)
        self.assertEqual(containment.closes, 1)
        self.assertEqual(self._disk()["status"], sup.STATUS_TERMINATED)
        self.assertNotIn("termination_unresolved", sp.evidence)

    def test_secondary_cleanup_failure_records_unresolved_lifecycle(self):  # 11
        containment = _CloseBreakingContainment()
        sp = self._sp(containment)
        result = sp.terminate("TEST")
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)))
        self.assertFalse(result.confirmed_dead, "unreleased resources must not read as a clean death")
        self.assertFalse(sp.confirmed_dead)
        self.assertEqual(sp.evidence["status"], sup.STATUS_UNRESOLVED)
        self.assertIs(sp.evidence["termination_unresolved"], True)
        self.assertTrue(any("containment_close" in e for e in sp.evidence["cleanup_errors"]))
        self.assertEqual(self._disk()["status"], sup.STATUS_UNRESOLVED)
        containment.broken = False  # retry really finishes the cleanup
        self.assertTrue(sp.terminate("RETRY").confirmed_dead)
        self.assertEqual(containment.closes, 1)
        self.assertEqual(sp.evidence["status"], sup.STATUS_TERMINATED)

    def test_failing_settle_path_never_replaces_the_original_error(self):  # 10, 11
        containment = _CountingContainment()
        sp = self._sp(containment)
        original = OSError("pipe broke")
        with mock.patch.object(sup._OwnedPopen, "communicate", side_effect=original), \
                mock.patch.object(sup.SupervisedProcess, "terminate", side_effect=RuntimeError("terminate broke")), \
                mock.patch.object(sup.SupervisedProcess, "_kill_owned", side_effect=RuntimeError("cleanup broke")):
            with self.assertRaises(OSError) as ctx:
                sp.run(None, 30)
        self.assertIs(ctx.exception, original)
        self.assertFalse(sp.confirmed_dead)
        self.assertEqual(sp.evidence["status"], sup.STATUS_UNRESOLVED)
        self.assertTrue(any("cleanup broke" in e for e in sp.evidence["cleanup_errors"]))
        self.assertTrue(sp.terminate("RETRY").confirmed_dead)  # nothing was lost: a later retry can finish


class ProductionDurabilityTests(unittest.TestCase):  # FIX3 3 (production default: NOT patched)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.marker = self.tmp / "provider-ran.txt"
        self.code = "import sys; open(sys.argv[1], 'w').write('ran')"

    def argv(self):
        return [sys.executable, "-c", self.code, str(self.marker)]

    def test_default_is_durable(self):
        self.assertIs(sup._DEFAULT_REQUIRE_DURABLE_IDENTITY, True)

    def test_run_supervised_without_control_fails_closed(self):  # 8
        outcome = sup.run_supervised(self.argv(), self.tmp, None, 30, provider="claude")
        self.assertIsNone(outcome.returncode)
        self.assertIn(b"durable evidence target", outcome.stderr)
        self.assertTrue(outcome.evidence["durable_identity_refused"])
        self.assertEqual(outcome.evidence["status"], sup.STATUS_LAUNCH_FAILED)
        self.assertFalse(self.marker.exists())

    def test_run_supervised_with_control_lacking_evidence_target_fails_closed(self):  # 8
        control = sup.ExecutionControl(worker_id="w", attempt=1)
        outcome = sup.run_supervised(self.argv(), self.tmp, None, 30, control=control)
        self.assertIsNone(outcome.returncode)
        self.assertTrue(outcome.evidence["durable_identity_refused"])
        self.assertIsNone(control.process)
        self.assertFalse(control.needs_wait(), "refused launch left the control 'launching'")
        self.assertFalse(self.marker.exists())

    def test_supervised_process_without_target_never_starts(self):  # 8
        sp = sup.SupervisedProcess(self.argv(), self.tmp, provider="claude")
        with self.assertRaises(sup.DurableIdentityUnavailableError):
            sp.start()
        self.assertFalse(sp.started)
        self.assertEqual(sp.evidence["status"], sup.STATUS_LAUNCH_FAILED)
        self.assertFalse(self.marker.exists())

    def test_containment_without_start_barrier_is_refused(self):  # 8
        containment = _CountingContainment()
        sp = sup.SupervisedProcess(
            self.argv(), self.tmp, containment=containment, evidence_path=self.tmp / "ev.json",
        )
        with self.assertRaises(sup.DurableIdentityUnavailableError):
            sp.start()
        self.assertFalse(sp.started)
        self.assertEqual(containment.closes, 1)
        self.assertFalse(self.marker.exists())

    def test_explicit_non_production_mode_is_opt_in_per_call(self):
        outcome = sup.run_supervised(self.argv(), self.tmp, None, 30, require_durable_identity=False)
        self.assertEqual(outcome.returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_managed_run_persists_identity_before_the_provider_runs(self):  # 9
        order = []
        marker = self.marker

        def recorder(path, payload):
            if (payload.get("identity") or {}).get("pid") is not None and payload["status"] == sup.STATUS_RUNNING:
                order.append(("identity_persisted", marker.exists()))
            sup._default_write_json(path, payload)

        control = sup.ExecutionControl(worker_id="w", attempt=1, evidence_path=self.tmp / "p" / "a.json",
                                       write_json=recorder)
        outcome = sup.run_supervised(self.argv(), self.tmp, None, 30, provider="claude", control=control)
        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(order, [("identity_persisted", False)])  # provider had not run yet
        self.assertTrue(marker.exists())
        self.assertTrue(outcome.evidence["confirmed_dead"])

    def test_identity_persistence_failure_never_runs_provider_business_logic(self):  # 9
        calls = []

        def write(path, payload):
            calls.append(payload["status"])
            if len(calls) == 2:  # 1: launch intent, 2: identity
                raise OSError("disk full")
            sup._default_write_json(path, payload)

        sp = sup.SupervisedProcess(
            self.argv(), self.tmp, provider="claude", evidence_path=self.tmp / "ev.json", write_json=write,
            force_wait_seconds=15.0,
        )
        with self.assertRaises(OSError):
            sp.start()
        self.assertTrue(sp.started)
        self.assertTrue(wait_until(lambda: pid_gone(sp.pid)), "provider left running without durable identity")
        self.assertTrue(sp.confirmed_dead)
        time.sleep(0.3)  # give a hypothetical escaped provider time to write its marker
        self.assertFalse(self.marker.exists(), "provider code ran although its identity was never durable")

    @unittest.skipIf(WINDOWS, "POSIX start barrier")
    def test_posix_barrier_never_releases_provider_without_the_release_byte(self):  # 9
        import subprocess

        containment = sup.PosixGroupContainment()
        proc = subprocess.Popen(
            containment.launch_argv(self.argv()), cwd=str(self.tmp), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **containment.popen_kwargs(),
        )
        containment.adopt(proc)
        time.sleep(0.3)
        self.assertIsNone(proc.poll(), "bootstrap must wait at the barrier")
        self.assertFalse(self.marker.exists())
        containment.close()  # Runner failure/death: EOF, no release
        self.assertEqual(proc.wait(30), 125)
        self.assertFalse(self.marker.exists())

    @unittest.skipIf(WINDOWS, "POSIX start barrier")
    def test_posix_barrier_execs_the_provider_in_place_after_release(self):
        sp = sup.SupervisedProcess(
            self.argv(), self.tmp, provider="claude", evidence_path=self.tmp / "ev.json", force_wait_seconds=15.0,
        )
        sp.start()
        outcome = sp.run(None, 30)
        self.assertEqual(outcome.returncode, 0)
        self.assertTrue(self.marker.exists())
        identity = json.loads((self.tmp / "ev.json").read_text(encoding="utf-8"))["identity"]
        self.assertEqual(identity["pid"], sp.pid)  # same pid before and after exec
        self.assertEqual(identity["process_group"], sp.pid)


class WindowsLivenessSemanticsTests(unittest.TestCase):  # FIX3 5
    @unittest.skipUnless(WINDOWS, "Windows pid/handle semantics")
    def test_terminated_process_with_open_handle_is_not_running(self):
        import subprocess

        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        self.addCleanup(lambda: (proc.kill() if proc.poll() is None else None, proc.wait(30)))
        proc.wait(30)
        # The owned handle is still open: the process OBJECT exists, but it is not RUNNING.
        self.assertFalse(pid_running(proc.pid))
        self.assertTrue(pid_gone(proc.pid))

    def test_a_running_process_is_reported_running(self):
        import subprocess

        proc = subprocess.Popen(SLEEP_FOREVER, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.kill(), proc.wait(30)))
        self.assertTrue(pid_running(proc.pid))
        self.assertFalse(pid_gone(proc.pid))

    def test_owned_handle_evidence_is_what_confirms_death(self):
        sp = sup.SupervisedProcess(
            [sys.executable, "-c", "pass"], Path(tempfile.gettempdir()), provider="claude",
            require_durable_identity=False, force_wait_seconds=15.0,
        )
        sp.start()
        sp.run(None, 30)
        self.assertTrue(sp.confirmed_dead)
        self.assertIsNotNone(sp._proc.returncode)  # exit state from the owned Popen, not a pid lookup


class NoBroadKillTests(unittest.TestCase):
    FORBIDDEN = ("taskkill", "pkill", "killall", "wmic", "psutil", "process_iter", "/IM", "Get-Process", "tasklist")

    def test_no_broad_process_kill_in_runner_modules(self):  # 18
        for module in (sup, providers, rp):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for token in self.FORBIDDEN:
                self.assertNotIn(token, source, f"{module.__name__} contains {token!r}")

    def test_termination_only_targets_owned_handles(self):  # 18
        source = Path(sup.__file__).read_text(encoding="utf-8")
        # POSIX signalling is scoped to the group this execution created.
        self.assertEqual(source.count("os.killpg("), 2)
        self.assertIn("self._pgid", source)
        # No signal is ever sent to a pid that is not this execution's child.
        self.assertNotIn("os.kill(pid", source)


if __name__ == "__main__":
    unittest.main()

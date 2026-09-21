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


def pid_gone(pid: int) -> bool:
    return mw._pid_alive(pid) is False


class SupervisionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

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

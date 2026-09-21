"""Provider-neutral process supervision for the governed Runner (PROCESS SUPERVISION V1).

A provider CLI (Claude, Codex, ...) is launched as a *supervised process*:

    Runner -> worker -> SupervisedProcess -> known identity
                                          -> known ownership (containment)
                                          -> controlled descendants
                                          -> graceful termination request
                                          -> bounded wait
                                          -> forced termination of the OWNED containment
                                          -> confirmed death

Nothing here enumerates or kills processes by name or machine-wide. A process
is only ever signalled/terminated through the containment object created for
that one execution (a Windows Job Object, or a POSIX process group/session),
or through the direct child handle `subprocess.Popen` gave us. Every
`SupervisedProcess` owns its own state; there is no module-level "current
process".

Containment guarantees (what is and is NOT promised)
----------------------------------------------------
Windows (`WINDOWS_JOB_OBJECT`): the child is created suspended, assigned to a
fresh anonymous Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, and only
then resumed, so no descendant can be spawned outside the job. Descendants
join the job automatically (breakaway is not permitted). Guarantees:
  * `TerminateJobObject` kills the provider and every descendant still in the
    job; `ActiveProcesses == 0` is the confirmation of death.
  * If the Runner process dies for ANY reason (crash, kill, power loss of the
    process), the kernel closes the Runner's job handle and, because of
    KILL_ON_JOB_CLOSE, terminates every process in the job. This is the
    parent-death guarantee. It requires that no other process holds a handle
    to the job (we never make the handle inheritable or duplicate it).
NOT guaranteed on Windows: processes that were never in the job (there are
none by construction unless job assignment failed, which fails closed), a
descendant that outlives a *graceful* console event (the forced phase sweeps
the job regardless), and machine-level events (power loss/OS crash - nothing
survives those anyway). CTRL_BREAK is best-effort: it needs a console.

POSIX (`POSIX_PROCESS_GROUP`): the child is started in its own session
(`start_new_session=True`), so pgid == sid == pid and `killpg` reaches every
descendant that stayed in that group. NOT guaranteed on POSIX: descendants
that call `setsid()/setpgid()` escape the group; and there is NO parent-death
guarantee (if the Runner is SIGKILLed the group keeps running; a later Runner
sees the durable evidence and stays conservative instead of killing by pid).

Degraded (`DEGRADED_PID_ONLY`): only used when the caller explicitly allows it
(`allow_degraded=True`). Only the direct child can be terminated; descendants
are NOT controlled and the evidence says so (`descendants_controlled=false`).
The default is fail-closed: if containment cannot be established the provider
is not started.

Evidence never contains prompts, argv, environment or credentials.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

EVIDENCE_SCHEMA_VERSION = 1

MODE_WINDOWS_JOB = "WINDOWS_JOB_OBJECT"
MODE_POSIX_GROUP = "POSIX_PROCESS_GROUP"
MODE_DEGRADED = "DEGRADED_PID_ONLY"

DEFAULT_GRACE_SECONDS = 5.0
DEFAULT_FORCE_WAIT_SECONDS = 10.0
DEFAULT_POLL_SECONDS = 0.1

# Lifecycle statuses recorded in the evidence file.
STATUS_LAUNCHING = "LAUNCHING"
STATUS_RUNNING = "RUNNING"
STATUS_TERMINATING = "TERMINATING"
STATUS_EXITED = "EXITED"
STATUS_TERMINATED = "TERMINATED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_LAUNCH_FAILED = "LAUNCH_FAILED"

GRACEFUL_NOT_ATTEMPTED = "NOT_ATTEMPTED"
GRACEFUL_ALREADY_EXITED = "ALREADY_EXITED"
GRACEFUL_EXITED = "EXITED_AFTER_SIGNAL"
GRACEFUL_TIMEOUT = "TIMEOUT_AFTER_SIGNAL"
GRACEFUL_UNAVAILABLE = "SIGNAL_UNAVAILABLE"

FORCED_NOT_REQUIRED = "NOT_REQUIRED"
FORCED_TERMINATED = "TERMINATED"
FORCED_FAILED = "FAILED"


class ContainmentUnavailableError(Exception):
    """Containment could not be established; the provider was NOT left running."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_write_json(path: Path, payload: dict) -> None:
    """Fallback atomic writer (tmp + fsync + replace). The Runner pipeline
    injects `claude_queue._atomic_write_json` instead so the repository's own
    atomic-write convention is what actually runs in production."""
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class ProcessIdentity:
    """Who the process is and why the Runner may terminate it."""
    pid: Optional[int]
    provider: Optional[str]
    started_at: Optional[str]
    platform: str
    containment_mode: str
    runner_pid: int = field(default_factory=os.getpid)
    process_group: Optional[int] = None
    session: Optional[int] = None
    job_id: Optional[str] = None
    descendants_controlled: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TerminationResult:
    requested_at: Optional[str]
    reason: Optional[str]
    graceful_outcome: str
    forced_outcome: str
    exit_code: Optional[int]
    ended_at: Optional[str]
    confirmed_dead: bool
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SupervisionOutcome:
    returncode: Optional[int]
    stdout: bytes
    stderr: bytes
    timed_out: bool
    interrupted: bool
    duration_seconds: float
    evidence: dict


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

class ProcessContainment:
    """Ownership boundary for ONE supervised execution."""

    mode = ""
    descendants_controlled = False

    def popen_kwargs(self) -> dict:
        return {}

    def adopt(self, proc: subprocess.Popen) -> None:
        """Bring the freshly created child under containment. Raises
        ContainmentUnavailableError (after making sure nothing runs) when it
        cannot."""

    def release_child(self, proc: subprocess.Popen) -> None:
        """Called after `adopt` succeeded; lets a suspended child run."""

    def request_graceful(self, proc: subprocess.Popen) -> bool:
        """Asks the owned process(es) to stop. True when a request was sent."""
        return False

    def force_terminate(self, proc: subprocess.Popen) -> bool:
        """Kills every owned process. True when the OS accepted the request."""
        return False

    def is_empty(self, proc: subprocess.Popen) -> bool:
        """True when no owned process is left running."""
        return proc.poll() is not None

    def ownership(self, proc: subprocess.Popen) -> dict:
        return {}

    def close(self) -> None:
        """Releases OS handles. Only called once death is confirmed."""


class PidOnlyContainment(ProcessContainment):
    """Explicitly degraded: direct child only, descendants NOT controlled."""

    mode = MODE_DEGRADED
    descendants_controlled = False

    def request_graceful(self, proc) -> bool:
        try:
            proc.terminate()
            return True
        except OSError:
            return False

    def force_terminate(self, proc) -> bool:
        try:
            proc.kill()
            return True
        except OSError:
            return proc.poll() is not None


class PosixGroupContainment(ProcessContainment):
    mode = MODE_POSIX_GROUP
    descendants_controlled = True

    def __init__(self):
        self._pgid: Optional[int] = None

    def popen_kwargs(self) -> dict:
        return {"start_new_session": True}

    def adopt(self, proc) -> None:
        # start_new_session makes the child its own session AND group leader.
        self._pgid = proc.pid

    def _killpg(self, sig) -> bool:
        if self._pgid is None:
            return False
        try:
            os.killpg(self._pgid, sig)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return False

    def request_graceful(self, proc) -> bool:
        return self._killpg(signal.SIGTERM)

    def force_terminate(self, proc) -> bool:
        sent = self._killpg(signal.SIGKILL)
        if not sent and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                return False
        return True

    def is_empty(self, proc) -> bool:
        if proc.poll() is None:
            return False
        if self._pgid is None:
            return True
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def ownership(self, proc) -> dict:
        return {"process_group": self._pgid, "session": self._pgid}


if sys.platform == "win32":  # pragma: no branch - platform-specific block
    import ctypes
    from ctypes import wintypes

    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_SUSPENDED = 0x00000004
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectBasicAccountingInformation = 1
    _JobObjectExtendedLimitInformation = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    def _kernel32():
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        k32.QueryInformationJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = wintypes.BOOL
        return k32

    def _nt_resume_process(handle) -> bool:
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        return ntdll.NtResumeProcess(handle) == 0


class WindowsJobContainment(ProcessContainment):
    """Job Object with KILL_ON_JOB_CLOSE (see module docstring for guarantees)."""

    mode = MODE_WINDOWS_JOB
    descendants_controlled = True

    def __init__(self):
        if sys.platform != "win32":  # pragma: no cover - guarded by the factory
            raise ContainmentUnavailableError("Windows Job Objects are only available on Windows")
        self._k32 = _kernel32()
        self._job = None
        self.job_id = uuid.uuid4().hex

    def popen_kwargs(self) -> dict:
        # New process group: gives CTRL_BREAK a target that is exactly this
        # child. Suspended: it is contained before it can run or spawn.
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED}

    def _fail(self, proc, message: str):
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - best effort: never leave the suspended child behind
            pass
        self.close()
        raise ContainmentUnavailableError(message)

    def adopt(self, proc) -> None:
        k32 = self._k32
        job = k32.CreateJobObjectW(None, None)
        if not job:
            self._fail(proc, f"CreateJobObject failed (winerror={ctypes.get_last_error()})")
        self._job = job
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self._fail(proc, f"SetInformationJobObject(KILL_ON_JOB_CLOSE) failed (winerror={ctypes.get_last_error()})")
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            self._fail(proc, f"AssignProcessToJobObject failed (winerror={ctypes.get_last_error()})")

    def release_child(self, proc) -> None:
        if not _nt_resume_process(int(proc._handle)):
            self._fail(proc, "NtResumeProcess failed; provider not started")

    def request_graceful(self, proc) -> bool:
        if proc.poll() is not None:
            return False
        try:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)  # targets only this child's process group
            return True
        except (OSError, ValueError):
            return False  # e.g. Runner has no console: the forced phase handles it

    def force_terminate(self, proc) -> bool:
        if not self._job:
            return False
        return bool(self._k32.TerminateJobObject(self._job, 1))

    def _active_processes(self) -> Optional[int]:
        if not self._job:
            return 0
        info = _BASIC_ACCOUNTING()
        if not self._k32.QueryInformationJobObject(
            self._job, _JobObjectBasicAccountingInformation, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return None
        return int(info.ActiveProcesses)

    def is_empty(self, proc) -> bool:
        active = self._active_processes()
        return proc.poll() is not None and active == 0

    def ownership(self, proc) -> dict:
        return {"job_id": self.job_id}

    def close(self) -> None:
        job, self._job = self._job, None
        if job:
            self._k32.CloseHandle(job)


def create_containment(*, allow_degraded: bool = False, platform_name: Optional[str] = None) -> ProcessContainment:
    """Best available containment for the platform. `platform_name` exists so
    the selection is testable on any OS."""
    name = platform_name or sys.platform
    if name == "win32":
        return WindowsJobContainment()
    if name.startswith(("linux", "darwin", "freebsd", "openbsd", "netbsd")) or os.name == "posix":
        return PosixGroupContainment()
    if allow_degraded:
        return PidOnlyContainment()
    raise ContainmentUnavailableError(f"no process containment available for platform {name!r}")


# ---------------------------------------------------------------------------
# Supervised process
# ---------------------------------------------------------------------------

class SupervisedProcess:
    """One provider process for one worker attempt. Thread-safe termination."""

    def __init__(
        self,
        argv: list,
        cwd,
        *,
        provider: Optional[str] = None,
        env: Optional[dict] = None,
        containment: Optional[ProcessContainment] = None,
        allow_degraded: bool = False,
        evidence_path=None,
        write_json: Optional[Callable] = None,
        grace_seconds: Optional[float] = None,
        force_wait_seconds: Optional[float] = None,
        extra_evidence: Optional[dict] = None,
    ):
        self._argv = list(argv)
        self._cwd = str(cwd)
        self._env = env
        self.provider = provider
        self._allow_degraded = allow_degraded
        self._containment = containment
        self._evidence_path = Path(evidence_path) if evidence_path else None
        self._write_json = write_json or _default_write_json
        # Defaults are read at call time so they can be tuned (tests, ops).
        self.grace_seconds = DEFAULT_GRACE_SECONDS if grace_seconds is None else grace_seconds
        self.force_wait_seconds = DEFAULT_FORCE_WAIT_SECONDS if force_wait_seconds is None else force_wait_seconds
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._termination: Optional[TerminationResult] = None
        self._term_requested_at: Optional[str] = None
        self.identity: Optional[ProcessIdentity] = None
        self.evidence: dict = {
            "schema_version": EVIDENCE_SCHEMA_VERSION, "status": STATUS_LAUNCHING,
            "provider": provider, "platform": sys.platform, "runner_pid": os.getpid(),
            "launch_requested_at": _utc_iso(), "identity": None,
            "termination_requested_at": None, "termination_reason": None,
            "graceful_outcome": None, "forced_outcome": None,
            "exit_code": None, "ended_at": None, "confirmed_dead": False,
            **(extra_evidence or {}),
        }

    # -- properties ---------------------------------------------------------

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    @property
    def started(self) -> bool:
        return self._proc is not None

    @property
    def confirmed_dead(self) -> bool:
        return bool(self.evidence.get("confirmed_dead"))

    @property
    def containment_mode(self) -> Optional[str]:
        return self._containment.mode if self._containment is not None else None

    # -- evidence -----------------------------------------------------------

    def _persist(self, *, required: bool = False) -> None:
        if self._evidence_path is None:
            return
        try:
            self._write_json(self._evidence_path, dict(self.evidence))
        except Exception as exc:  # noqa: BLE001
            if required:
                raise
            self.evidence["evidence_write_error"] = f"{type(exc).__name__}: {exc}"

    # -- launch -------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._proc is not None:
                raise RuntimeError("supervised process already started")
            # Intent is durable BEFORE the OS process exists: a crash between
            # here and the pid record is visible to recovery as "may have run".
            self._persist(required=True)
            try:
                containment = self._containment or create_containment(allow_degraded=self._allow_degraded)
            except ContainmentUnavailableError as exc:
                self._launch_failed(exc)
                raise
            self._containment = containment
            self.evidence["containment_mode"] = containment.mode
            try:
                proc = subprocess.Popen(
                    self._argv, cwd=self._cwd, env=self._env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    **containment.popen_kwargs(),
                )
            except BaseException as exc:
                containment.close()
                self._launch_failed(exc)
                raise
            self._proc = proc
            try:
                containment.adopt(proc)
                self.identity = ProcessIdentity(
                    pid=proc.pid, provider=self.provider, started_at=_utc_iso(), platform=sys.platform,
                    containment_mode=containment.mode, descendants_controlled=containment.descendants_controlled,
                    **{k: v for k, v in containment.ownership(proc).items()
                       if k in ("process_group", "session", "job_id")},
                )
                self.evidence.update(identity=self.identity.as_dict(), status=STATUS_RUNNING)
                # Identity durable BEFORE the child is allowed to run (Windows:
                # it is still suspended here; POSIX: it just started).
                self._persist()
                containment.release_child(proc)
            except ContainmentUnavailableError as exc:
                dead = self._reap_after_failed_containment(proc)
                self._launch_failed(exc, confirmed_dead=dead)
                raise
            except BaseException:
                self._emergency_kill(proc)
                raise

    def _launch_failed(self, exc: BaseException, *, confirmed_dead: bool = True) -> None:
        """`confirmed_dead=True` is only valid when no OS process exists (the
        launch itself failed) or the emergency kill proved the child dead."""
        self.evidence.update(
            status=STATUS_LAUNCH_FAILED if confirmed_dead else STATUS_UNRESOLVED,
            ended_at=_utc_iso() if confirmed_dead else None, confirmed_dead=confirmed_dead,
            launch_error=f"{type(exc).__name__}: {exc}",
        )
        if not confirmed_dead:
            self.evidence["termination_unresolved"] = True
            self.evidence["termination_unresolved_detail"] = "LAUNCH_FAILED_CHILD_DEATH_NOT_ESTABLISHED"
        self._persist()

    def _reap_after_failed_containment(self, proc) -> bool:
        # The child was never confirmed contained: it must not keep running.
        return self._emergency_kill(proc)

    def _emergency_kill(self, proc) -> bool:
        """Kills the owned child and returns True only if its death was
        actually established (the owned handle reports an exit code)."""
        try:
            if self._containment is not None:
                self._containment.force_terminate(proc)
            proc.kill()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._close_pipes(proc)
        dead = proc.poll() is not None
        if dead:
            self._release_process_handle(proc)
        return dead

    @staticmethod
    def _release_process_handle(proc) -> None:
        """Deterministically closes the owned Windows process handle once the
        exit code is recorded. While it is open the kernel process object (and
        so an OpenProcess(pid) probe) outlives the process. Never called before
        death is proven: Popen's own poll/wait/kill no longer touch the handle
        once `returncode` is set."""
        if proc.returncode is None:
            return
        handle = getattr(proc, "_handle", None)
        close = getattr(handle, "Close", None)
        if close is not None:
            try:
                close()
            except OSError:
                pass

    # -- run / communicate --------------------------------------------------

    def run(
        self, stdin_bytes: Optional[bytes], timeout_seconds: float, *,
        cancelled: Optional[Callable[[], Optional[str]]] = None, poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> SupervisionOutcome:
        """Feeds stdin, captures stdout/stderr, enforces the timeout and
        honours cancellation. Never returns while the owned process is alive
        unless death could not be confirmed (recorded in the evidence)."""
        proc = self._proc
        if proc is None:
            raise RuntimeError("start() must be called before run()")
        started = time.monotonic()
        deadline = started + timeout_seconds
        out = err = b""
        timed_out = interrupted = False
        term_reason: Optional[str] = None
        first = True
        communicated = False
        try:
            while True:
                reason = cancelled() if cancelled else None
                if reason:
                    interrupted, term_reason = True, reason
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out, term_reason = True, "TIMEOUT"
                    break
                try:
                    out, err = proc.communicate(input=(stdin_bytes or b"") if first else None,
                                                timeout=min(poll_seconds, remaining))
                    communicated = True
                    break
                except subprocess.TimeoutExpired as exc:
                    first = False
                    out, err = exc.output or b"", exc.stderr or b""
        except KeyboardInterrupt:
            interrupted, term_reason = True, "KEYBOARD_INTERRUPT"

        if term_reason is None and self._term_requested_at is not None:
            # Another thread (ExecutionControl.terminate_now) already ended the process.
            interrupted, term_reason = True, self.evidence.get("termination_reason")
        if term_reason is not None:
            self.terminate(term_reason)
            if not communicated:
                out, err = self._drain(proc, out, err)
        else:
            # Normal completion: the provider exited. Descendants it left
            # behind are still owned by this execution and must not outlive it.
            self.terminate("PROCESS_COMPLETED_SWEEP", completed=True)
        self._close_pipes(proc)
        self._finalize_evidence(exited_normally=term_reason is None)
        return SupervisionOutcome(
            returncode=proc.returncode, stdout=out or b"", stderr=err or b"", timed_out=timed_out,
            interrupted=interrupted, duration_seconds=time.monotonic() - started, evidence=dict(self.evidence),
        )

    def _drain(self, proc, out: bytes, err: bytes) -> tuple:
        try:
            return proc.communicate(timeout=max(self.force_wait_seconds, 1.0))
        except subprocess.TimeoutExpired as exc:
            return (exc.output or out or b""), (exc.stderr or err or b"")
        except (ValueError, OSError):
            return out, err

    @staticmethod
    def _close_pipes(proc) -> None:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except (OSError, ValueError):
                pass

    # -- termination --------------------------------------------------------

    def terminate(self, reason: str = "REQUESTED", *, completed: bool = False) -> TerminationResult:
        """Graceful request -> bounded wait -> forced termination of the OWNED
        containment -> confirmation. Idempotent and thread-safe; a second call
        after confirmed death returns the first result unchanged."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return TerminationResult(None, reason, GRACEFUL_NOT_ATTEMPTED, FORCED_NOT_REQUIRED,
                                         None, None, True, ["process never started"])
            if self._termination is not None and self._termination.confirmed_dead:
                return self._termination
            containment = self._containment
            notes: list = []
            if not completed and self._term_requested_at is None:
                self._term_requested_at = _utc_iso()
                self.evidence.update(
                    status=STATUS_TERMINATING, termination_requested_at=self._term_requested_at,
                    termination_reason=reason,
                )
                self._persist()

            graceful = GRACEFUL_NOT_ATTEMPTED
            forced = FORCED_NOT_REQUIRED
            if proc.poll() is not None:
                graceful = GRACEFUL_ALREADY_EXITED
            else:
                if containment.request_graceful(proc):
                    try:
                        proc.wait(timeout=self.grace_seconds)
                        graceful = GRACEFUL_EXITED
                    except subprocess.TimeoutExpired:
                        graceful = GRACEFUL_TIMEOUT
                else:
                    graceful = GRACEFUL_UNAVAILABLE

            if proc.poll() is not None:
                # The direct child is gone; give the OS a moment to report the
                # containment empty before deciding descendants need a sweep.
                grace_deadline = time.monotonic() + 0.3
                while not containment.is_empty(proc) and time.monotonic() < grace_deadline:
                    time.sleep(0.02)
            if proc.poll() is None or not containment.is_empty(proc):
                accepted = containment.force_terminate(proc)
                forced = FORCED_TERMINATED if accepted else FORCED_FAILED
                if not accepted:
                    notes.append("containment refused forced termination")
                if proc.poll() is None:
                    try:
                        proc.kill()  # direct child handle we own, in addition to the containment
                    except OSError:
                        pass

            confirmed = self._confirm(proc, containment)
            if not confirmed:
                notes.append("death not confirmed within the bounded wait; treat as UNRESOLVED")
            if confirmed:
                containment.close()
                self._release_process_handle(proc)
            result = TerminationResult(
                requested_at=self._term_requested_at, reason=reason if not completed else None,
                graceful_outcome=graceful, forced_outcome=forced, exit_code=proc.poll(),
                ended_at=_utc_iso() if confirmed else None, confirmed_dead=confirmed, notes=notes,
            )
            self._termination = result
            self.evidence.update(
                graceful_outcome=graceful, forced_outcome=forced, exit_code=proc.poll(),
                confirmed_dead=confirmed, ended_at=result.ended_at,
                status=(STATUS_TERMINATED if self._term_requested_at else STATUS_EXITED) if confirmed else STATUS_UNRESOLVED,
            )
            if not confirmed:
                # Fail closed: death was NOT established, so nothing downstream
                # may assume it (WRITE leases stay held).
                self.evidence["termination_unresolved"] = True
                self.evidence["termination_unresolved_detail"] = "DEATH_NOT_ESTABLISHED_WITHIN_BOUNDED_WAIT"
            else:
                self.evidence.pop("termination_unresolved", None)
                self.evidence.pop("termination_unresolved_detail", None)
            if completed and forced == FORCED_TERMINATED:
                self.evidence["descendants_swept_after_exit"] = True
            self._persist()
            return result

    def _confirm(self, proc, containment) -> bool:
        deadline = time.monotonic() + self.force_wait_seconds
        while True:
            if proc.poll() is not None and containment.is_empty(proc):
                return True
            if time.monotonic() >= deadline:
                return False
            try:
                proc.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.02)

    def _finalize_evidence(self, *, exited_normally: bool) -> None:
        with self._lock:
            if self._proc is not None and self.evidence.get("exit_code") is None:
                self.evidence["exit_code"] = self._proc.poll()
            self._persist()


# ---------------------------------------------------------------------------
# Execution control (per worker attempt; NEVER shared between workers)
# ---------------------------------------------------------------------------

class ExecutionControl:
    """Cancellation channel + durable-evidence target for exactly one worker
    attempt. The orchestrator keeps one per running worker; the provider
    transport consults it. Cancelling one control cannot reach another
    worker's process: a control only ever references its own SupervisedProcess.
    """

    def __init__(self, *, worker_id: Optional[str] = None, attempt: Optional[int] = None,
                 evidence_path=None, write_json: Optional[Callable] = None):
        self.worker_id = worker_id
        self.attempt = attempt
        self.evidence_path = Path(evidence_path) if evidence_path else None
        self.write_json = write_json
        self._lock = threading.Lock()
        self._cancel_reason: Optional[str] = None
        self._launching = False
        self._process: Optional[SupervisedProcess] = None
        self._launch_refused = False

    @property
    def cancel_reason(self) -> Optional[str]:
        return self._cancel_reason

    @property
    def cancelled(self) -> bool:
        return self._cancel_reason is not None

    @property
    def process(self) -> Optional[SupervisedProcess]:
        return self._process

    def request_cancel(self, reason: str = "CANCELLED") -> None:
        """Non-blocking. The supervising worker thread performs the actual
        termination sequence when it observes the request; a launch that has
        not begun yet is refused."""
        with self._lock:
            if self._cancel_reason is None:
                self._cancel_reason = reason

    def begin_launch(self) -> bool:
        """False when cancellation already happened: the provider must not start."""
        with self._lock:
            if self._cancel_reason is not None:
                self._launch_refused = True
                return False
            self._launching = True
            return True

    def attach(self, process: SupervisedProcess) -> None:
        with self._lock:
            self._process = process

    def end_launch(self) -> None:
        with self._lock:
            self._launching = False

    def resolution(self) -> tuple:
        """(resolved, detail). Resolved means the Runner can say no provider
        process owned by this attempt is still running - or that none can ever
        start (cancelled before launch)."""
        with self._lock:
            process, launching = self._process, self._launching
        if launching:
            return False, "PROVIDER_LAUNCH_IN_PROGRESS"
        if process is None:
            if self._cancel_reason is not None:
                return True, "NO_PROCESS_STARTED_AND_LAUNCH_BLOCKED"
            return False, "NO_PROCESS_ATTACHED_YET"
        if process.confirmed_dead:
            return True, "PROCESS_CONFIRMED_DEAD"
        return False, "PROCESS_LIVENESS_UNCONFIRMED"

    def needs_wait(self) -> bool:
        """True while a provider process of this attempt is launching or not
        yet confirmed dead. False once cancellation blocks any launch and no
        process exists - nothing to wait for."""
        with self._lock:
            process, launching = self._process, self._launching
        return launching or (process is not None and not process.confirmed_dead)

    def settled_after_return(self) -> bool:
        """Valid once the worker thread has returned (no launch can still
        happen): True when no process was started or it is confirmed dead."""
        process = self._process
        return process is None or process.confirmed_dead

    def terminate_now(self, reason: str = "FORCED_SHUTDOWN") -> Optional[TerminationResult]:
        """Direct termination of THIS attempt's process from another thread
        (fallback when the worker thread does not react in time)."""
        process = self._process
        return process.terminate(reason) if process is not None else None

    def snapshot(self) -> dict:
        process = self._process
        resolved, detail = self.resolution()
        return {
            "worker_id": self.worker_id, "attempt": self.attempt, "cancel_reason": self._cancel_reason,
            "resolved": resolved, "detail": detail,
            "process": dict(process.evidence) if process is not None else None,
        }


def run_supervised(
    argv: list, cwd, stdin_bytes: Optional[bytes], timeout_seconds: float, *,
    provider: Optional[str] = None, env: Optional[dict] = None,
    control: Optional[ExecutionControl] = None, allow_degraded: bool = False,
    containment: Optional[ProcessContainment] = None, grace_seconds: Optional[float] = None,
    force_wait_seconds: Optional[float] = None, poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> SupervisionOutcome:
    """Runs one provider process under supervision. Returns an outcome with
    `interrupted=True` (and no process started) when `control` was cancelled
    before launch."""
    started = time.monotonic()
    if control is not None and not control.begin_launch():
        return SupervisionOutcome(
            None, b"", b"", False, True, 0.0,
            {"schema_version": EVIDENCE_SCHEMA_VERSION, "status": "NOT_STARTED", "provider": provider,
             "confirmed_dead": True, "termination_reason": control.cancel_reason},
        )
    sp = SupervisedProcess(
        argv, cwd, provider=provider, env=env, containment=containment, allow_degraded=allow_degraded,
        evidence_path=control.evidence_path if control else None,
        write_json=control.write_json if control else None,
        grace_seconds=grace_seconds, force_wait_seconds=force_wait_seconds,
        extra_evidence={"worker_id": control.worker_id, "attempt": control.attempt} if control else None,
    )
    try:
        if control is not None:
            control.attach(sp)
        try:
            sp.start()
        finally:
            if control is not None:
                control.end_launch()
        return sp.run(
            stdin_bytes, timeout_seconds, poll_seconds=poll_seconds,
            cancelled=(lambda: control.cancel_reason) if control is not None else None,
        )
    except ContainmentUnavailableError as exc:
        return SupervisionOutcome(
            None, b"", f"process supervision refused to start the provider: {exc}".encode("utf-8"),
            False, False, time.monotonic() - started, dict(sp.evidence),
        )

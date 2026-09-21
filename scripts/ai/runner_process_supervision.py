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
    job, but it is only a termination REQUEST. `ActiveProcesses == 0` is NOT
    proof of death: a process leaves the job's accounting while it is exiting,
    before its process object is signaled. Death is confirmed only by
    `force_terminate_and_confirm`, which first seals the job against new
    members (ACTIVE_PROCESS limit 1), then holds SYNCHRONIZE handles to the
    members it enumerates (JobObjectBasicProcessIdList) and requires each to
    be signaled. Residual limit: a member that was already exiting and left
    the enumeration before the post-seal capture never yields a handle, and
    the Job API offers no historical identity. True therefore means every
    identity-captured member is signaled (plus direct child dead, job list
    and accounting empty, no probe failure, within the bound); it does NOT
    claim every process ever associated with the job was identity-proven.
  * If the Runner process dies for ANY reason (crash, kill, power loss of the
    process), the kernel closes the Runner's job handle and, because of
    KILL_ON_JOB_CLOSE, terminates every process in the job. This is the
    parent-death guarantee. It requires that no other process holds a handle
    to the job (we never make the handle inheritable or duplicate it).
  * What KILL_ON_JOB_CLOSE does NOT give the Runner: a synchronous answer. The
    kernel initiates termination of the job's processes when the last handle
    closes, but the processes vanish asynchronously and the (anonymous) job
    cannot be re-opened afterwards, so a later Runner cannot query it. Recovery
    therefore only calls the job gone when (a) an identity record exists (it is
    persisted only AFTER job assignment succeeded and BEFORE the child is
    resumed), (b) the recorded owner Runner pid is demonstrably not running
    (its handle table is gone, hence the job handle is closed) and (c) the
    recorded direct child pid is not running. A pid that is still running, or
    that cannot be probed, is UNRESOLVED (pids can be reused: this only ever
    errs towards refusing).
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
Recovery after Runner death is ASSESSMENT ONLY: the recorded process group is
probed with signal 0 (which delivers nothing). A group that still exists, that
cannot be probed, or that belongs to another user is UNRESOLVED; only an
absent group is RESOLVED. The direct leader being gone proves nothing about its
descendants, and persisted numeric ids are never used to kill anything.

Degraded (`DEGRADED_PID_ONLY`): only used when the caller explicitly allows it
(`allow_degraded=True`). Only the direct child can be terminated; descendants
are NOT controlled and the evidence says so (`descendants_controlled=false`).
The default is fail-closed: if containment cannot be established the provider
is not started.

Durable identity boundary (production requirement)
--------------------------------------------------
Runner-managed execution never runs provider code before its ownership
evidence is durable. A supervised process without an evidence target, or on a
containment that has no start barrier, is REFUSED (fail closed) unless the
caller passes `require_durable_identity=False`, a non-production switch that
the Runner path never sets. The barrier is:
  * Windows: the child is created suspended and resumed only after the identity
    record is persisted.
  * POSIX: the child is a tiny bootstrap (no `preexec_fn`, which is unsafe in a
    multithreaded Runner) that blocks on an inherited pipe and only `exec`s the
    provider once the parent has persisted the identity and released it; EOF
    without release (Runner failure/death) makes it exit without ever running
    provider code.

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


# Production default: provider execution requires durable process identity.
# Only tests/standalone helpers may turn it off, explicitly, per call.
_DEFAULT_REQUIRE_DURABLE_IDENTITY = True

# POSIX start barrier. argv[1] is the inherited pipe fd, argv[2:] the provider
# command. Provider code cannot run before the parent writes the release byte.
_POSIX_BOOTSTRAP = (
    "import os, sys\n"
    "fd = int(sys.argv[1])\n"
    "try:\n"
    "    released = os.read(fd, 1) == b'1'\n"
    "except OSError:\n"
    "    released = False\n"
    "if not released:\n"
    "    os._exit(125)\n"
    "os.close(fd)\n"
    "cmd = sys.argv[2:]\n"
    "try:\n"
    "    os.execvp(cmd[0], cmd)\n"
    "except OSError as exc:\n"
    "    sys.stderr.write('cannot execute provider: %s\\n' % exc)\n"
    "    os._exit(127)\n"
)


class ContainmentUnavailableError(Exception):
    """Containment could not be established; the provider was NOT left running."""


class ContainmentProbeError(Exception):
    """The containment emptiness probe kept failing until the confirmation deadline."""


class DurableIdentityUnavailableError(ContainmentUnavailableError):
    """Durable ownership evidence cannot be guaranteed; the provider was NOT started."""


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
# Owned Popen handle
# ---------------------------------------------------------------------------

class _OwnedPopen:
    """Single owner of one Popen and its native process handle.

    Every wait/poll/communicate/kill goes through `_call`, which counts the
    threads currently inside Popen. The native handle is only closed by
    `release_handle` once the exit code is recorded AND no thread is inside
    Popen; otherwise the close is deferred to the last thread leaving. Once
    `returncode` is set Popen no longer touches the handle, so a thread that
    enters after the close cannot use it. Idempotent."""

    def __init__(self, popen: subprocess.Popen):
        self._popen = popen
        self._guard = threading.Lock()
        self._users = 0
        self._close_pending = False
        self._closed = False

    def _call(self, name: str, *args, **kwargs):
        with self._guard:
            self._users += 1
        try:
            return getattr(self._popen, name)(*args, **kwargs)
        finally:
            with self._guard:
                self._users -= 1
                if self._users == 0 and self._close_pending:
                    self._close_locked()

    def _close_locked(self) -> None:
        if self._popen.returncode is None:
            return  # death not recorded: the handle is still needed
        self._close_pending = False
        if self._closed:
            return
        self._closed = True
        close = getattr(getattr(self._popen, "_handle", None), "Close", None)
        if close is not None:
            try:
                close()
            except OSError:
                pass

    def release_handle(self) -> None:
        """Closes the native handle now, or as soon as the last in-flight
        Popen call returns. No-op until the exit code is recorded."""
        with self._guard:
            if self._popen.returncode is None:
                return
            if self._users:
                self._close_pending = True
                return
            self._close_locked()

    def poll(self):
        return self._call("poll")

    def wait(self, timeout=None):
        return self._call("wait", timeout=timeout)

    def communicate(self, input=None, timeout=None):
        return self._call("communicate", input=input, timeout=timeout)

    def kill(self):
        return self._call("kill")

    def terminate(self):
        return self._call("terminate")

    pid = property(lambda self: self._popen.pid)
    returncode = property(lambda self: self._popen.returncode)
    stdin = property(lambda self: self._popen.stdin)
    stdout = property(lambda self: self._popen.stdout)
    stderr = property(lambda self: self._popen.stderr)
    _handle = property(lambda self: self._popen._handle)


# ---------------------------------------------------------------------------
# Recovery assessment (read-only)
# ---------------------------------------------------------------------------

def probe_posix_group(pgid) -> Optional[bool]:
    """True: no process is left in the group. False: it may still contain
    processes (including one owned by another user). None: inconclusive.
    Signal 0 only checks existence; nothing is ever delivered."""
    probe = getattr(os, "killpg", None)
    if probe is None or isinstance(pgid, bool) or not isinstance(pgid, int) or pgid <= 1:
        return None
    try:
        probe(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return None
    return False


def assess_recorded_containment(identity: dict, *, pid_alive: Callable, group_probe: Callable = probe_posix_group) -> tuple:
    """Can the containment recorded by a dead Runner be shown to be empty?
    Returns (gone, detail); anything not demonstrated is (False, ...). Never
    signals or terminates anything."""
    mode = identity.get("containment_mode")
    if mode == MODE_POSIX_GROUP:
        pgid = identity.get("process_group")
        if pgid is None:
            return False, "NO_PROCESS_GROUP_RECORDED"
        state = group_probe(pgid)
        if state is True:
            return True, "PROCESS_GROUP_EMPTY"
        if state is False:
            return False, "PROCESS_GROUP_MAY_STILL_CONTAIN_PROCESSES"
        return False, "PROCESS_GROUP_PROBE_INCONCLUSIVE"
    if mode == MODE_WINDOWS_JOB:
        if sys.platform != "win32":
            return False, "JOB_OBJECT_NOT_ASSESSABLE_ON_THIS_PLATFORM"
        owner = identity.get("runner_pid")
        if isinstance(owner, bool) or not isinstance(owner, int):
            return False, "JOB_OWNER_NOT_RECORDED"
        if owner == os.getpid():
            return False, "JOB_HANDLE_HELD_BY_THIS_PROCESS"
        if pid_alive(owner) is not False:
            return False, "JOB_OWNER_MAY_STILL_BE_RUNNING"
        if pid_alive(identity.get("pid")) is not False:
            return False, "JOB_CHILD_MAY_STILL_BE_RUNNING"
        return True, "JOB_OWNER_DEAD_KILL_ON_CLOSE_APPLIED"
    return False, "CONTAINMENT_CANNOT_PROVE_DESCENDANTS_GONE"


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

class ProcessContainment:
    """Ownership boundary for ONE supervised execution."""

    mode = ""
    descendants_controlled = False
    # True when the child cannot run provider code until `release_child`.
    has_start_barrier = False

    def launch_argv(self, argv: list) -> list:
        """Command actually spawned (a containment may wrap it to add a start barrier)."""
        return list(argv)

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
        """Kills every owned process. True when the OS accepted the request.
        This is a termination REQUEST only: it says nothing about death. Use
        `force_terminate_and_confirm` when death must be established."""
        return False

    def force_terminate_and_confirm(self, proc: subprocess.Popen, timeout_seconds: float) -> bool:
        """THE canonical death contract: requests forced termination of the
        owned containment, then waits at most `timeout_seconds` and returns True
        only when the direct process and every contained process are proven
        dead. False on timeout, ambiguity or probe failure (fail closed).
        Raises ContainmentProbeError only when the last emptiness probe kept
        failing until the deadline."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        self.force_terminate(proc)  # a request; death is established below
        if proc.poll() is None:
            try:
                proc.kill()  # the direct child handle we own, in addition to the containment
            except OSError:
                pass
        probe_error: Optional[BaseException] = None
        while True:
            try:
                if self.is_empty(proc):
                    return True
                probe_error = None
            except Exception as exc:  # noqa: BLE001 - inconclusive probe: not empty
                probe_error = exc
            if time.monotonic() >= deadline:
                break
            try:
                proc.wait(timeout=max(0.0, min(0.05, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            except Exception:  # noqa: BLE001 - inconclusive, keep bounded polling
                pass
            time.sleep(0.02)
        if probe_error is not None:
            raise ContainmentProbeError(f"{type(probe_error).__name__}: {probe_error}") from probe_error
        return False

    def is_empty(self, proc: subprocess.Popen) -> bool:
        """OBSERVATIONAL snapshot: True when no owned process is seen running.
        It is not proof of death on every platform (see WindowsJobContainment);
        anything that must be sure uses `force_terminate_and_confirm`."""
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
    has_start_barrier = True

    def __init__(self):
        self._pgid: Optional[int] = None
        self._barrier_r: Optional[int] = None
        self._barrier_w: Optional[int] = None

    def launch_argv(self, argv: list) -> list:
        self._close_barrier()
        self._barrier_r, self._barrier_w = os.pipe()
        return [sys.executable, "-I", "-S", "-c", _POSIX_BOOTSTRAP, str(self._barrier_r), *argv]

    def popen_kwargs(self) -> dict:
        kwargs: dict = {"start_new_session": True}
        if self._barrier_r is not None:
            kwargs["pass_fds"] = (self._barrier_r,)
        return kwargs

    def _close_fd(self, name: str) -> None:
        fd = getattr(self, name)
        setattr(self, name, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def _close_barrier(self) -> None:
        self._close_fd("_barrier_r")
        self._close_fd("_barrier_w")

    def adopt(self, proc) -> None:
        # start_new_session makes the child its own session AND group leader.
        self._pgid = proc.pid
        self._close_fd("_barrier_r")  # the child holds its own copy

    def release_child(self, proc) -> None:
        fd = self._barrier_w
        if fd is None:
            raise ContainmentUnavailableError("start barrier missing; provider not started")
        try:
            os.write(fd, b"1")
        except OSError as exc:
            raise ContainmentUnavailableError(f"start barrier release failed: {exc}; provider not started")
        finally:
            self._close_fd("_barrier_w")

    def close(self) -> None:
        # EOF on the barrier makes a still-waiting bootstrap exit without exec.
        self._close_barrier()

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
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _SEAL_ACTIVE_PROCESS_LIMIT = 1
    _JobObjectBasicAccountingInformation = 1
    _JobObjectExtendedLimitInformation = 9
    _JobObjectBasicProcessIdList = 3
    _SYNCHRONIZE = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_OBJECT_0 = 0
    _ERROR_INVALID_PARAMETER = 87
    _ERROR_MORE_DATA = 234
    _PID_LIST_HEADER_BYTES = 8  # NumberOfAssignedProcesses + NumberOfProcessIdsInList (2 x DWORD)

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
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)]
        k32.IsProcessInJob.restype = wintypes.BOOL
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
    has_start_barrier = True  # created suspended, resumed only after identity is durable

    def __init__(self):
        if sys.platform != "win32":  # pragma: no cover - guarded by the factory
            raise ContainmentUnavailableError("Windows Job Objects are only available on Windows")
        self._k32 = _kernel32()
        self._job = None
        self.job_id = uuid.uuid4().hex
        self.last_confirmation_detail: Optional[str] = None

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
        """TerminateJobObject: a termination REQUEST. Accepted != dead."""
        if not self._job:
            return False
        return bool(self._k32.TerminateJobObject(self._job, 1))

    # -- strong death confirmation -------------------------------------------

    def _last_error(self) -> int:
        return ctypes.get_last_error()

    def _close_native(self, handle) -> None:
        try:
            self._k32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - a failing close must not mask the confirmation outcome
            pass

    def _query_member_pids(self) -> Optional[list]:
        """PIDs currently assigned to the job (JobObjectBasicProcessIdList), or
        None when the list cannot be established completely. The list is
        variable sized: the buffer grows and the query is repeated until
        NumberOfProcessIdsInList covers NumberOfAssignedProcesses."""
        if not self._job:
            return []
        slot = ctypes.sizeof(ctypes.c_size_t)
        capacity = 64
        for _ in range(8):
            size = _PID_LIST_HEADER_BYTES + capacity * slot
            buf = (ctypes.c_ubyte * size)()
            ok = self._k32.QueryInformationJobObject(self._job, _JobObjectBasicProcessIdList, buf, size, None)
            header = (wintypes.DWORD * 2).from_buffer(buf)
            assigned, listed = int(header[0]), int(header[1])
            if not ok:
                if self._last_error() != _ERROR_MORE_DATA:
                    return None
                capacity = max(capacity * 2, assigned + 16)
                continue
            if listed < assigned or listed > capacity:
                capacity = max(capacity * 2, assigned + 16)  # truncated/inconsistent: re-query
                continue
            ids = (ctypes.c_size_t * listed).from_buffer(buf, _PID_LIST_HEADER_BYTES)
            return [int(pid) for pid in ids]
        return None

    def _open_member(self, pid: int):
        """(handle, None) to track the member, (None, "gone") when it is safely
        gone, (None, "unknown") when that cannot be concluded. The handle is
        closed here unless it is handed back."""
        k32 = self._k32
        handle = k32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # No such pid: it was in the job list a moment ago, and a live
            # process cannot lose its pid, so it is gone. Anything else
            # (e.g. access denied) proves nothing.
            return None, ("gone" if self._last_error() == _ERROR_INVALID_PARAMETER else "unknown")
        keep = False
        try:
            in_job = wintypes.BOOL()
            if not k32.IsProcessInJob(handle, self._job, ctypes.byref(in_job)):
                return None, "unknown"
            if not in_job.value and k32.WaitForSingleObject(handle, 0) == _WAIT_OBJECT_0:
                return None, "gone"  # signaled: this process object is dead (whoever it is)
            # Still unsignaled, in the job or not (a member leaves the job's
            # accounting while exiting): it must be waited on. If this pid was
            # reused by a stranger the wait times out and we fail closed.
            keep = True
            return handle, None
        finally:
            if not keep:
                self._close_native(handle)

    def _refresh_members(self, tracked: dict):
        """Re-queries the job and retains a handle for every member not yet
        tracked. Returns (pids, ambiguous); pids None means the query failed."""
        pids = self._query_member_pids()
        if pids is None:
            return None, True
        ambiguous = False
        for pid in pids:
            if pid in tracked:
                continue
            handle, state = self._open_member(pid)
            if handle is not None:
                tracked[pid] = handle
            elif state == "unknown":
                ambiguous = True
        return pids, ambiguous

    def _first_unsignaled(self, tracked: dict):
        for handle in tracked.values():
            if self._k32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0:
                return handle
        return None

    def _query_limits(self):
        info = _EXTENDED_LIMIT()
        if not self._k32.QueryInformationJobObject(
            self._job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return None
        return info

    def _seal_job(self) -> bool:
        """Closes the job to new members with JOB_OBJECT_LIMIT_ACTIVE_PROCESS.

        A process that would exceed the limit is terminated by the kernel and
        its association fails, so with the limit at 1 no process can join while
        any member is alive (a joiner needs count 0, and only a live member can
        create one). Every other limit flag/value, KILL_ON_JOB_CLOSE included,
        is copied from the queried state; an existing limit that is already
        that strict (<= the seal value) is left untouched, never raised. The
        seal is never relaxed. Failure to query, set or verify is False."""
        try:
            before = self._query_limits()
            if before is None:
                return False
            flags = int(before.BasicLimitInformation.LimitFlags)
            if not (flags & _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                    and int(before.BasicLimitInformation.ActiveProcessLimit) <= _SEAL_ACTIVE_PROCESS_LIMIT):
                before.BasicLimitInformation.LimitFlags = flags | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                before.BasicLimitInformation.ActiveProcessLimit = _SEAL_ACTIVE_PROCESS_LIMIT
                if not self._k32.SetInformationJobObject(
                    self._job, _JobObjectExtendedLimitInformation, ctypes.byref(before), ctypes.sizeof(before)
                ):
                    return False
            after = self._query_limits()  # verify: the barrier is effective and nothing else was lost
            if after is None:
                return False
            after_flags = int(after.BasicLimitInformation.LimitFlags)
            return bool(
                after_flags & _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                and int(after.BasicLimitInformation.ActiveProcessLimit) <= _SEAL_ACTIVE_PROCESS_LIMIT
                and (after_flags & flags) == flags
            )
        except Exception:  # noqa: BLE001 - fail closed
            return False

    def force_terminate_and_confirm(self, proc, timeout_seconds: float) -> bool:
        """Strong bounded confirmation using the Job Object itself.

        The job is sealed against new members (`_seal_job`), member handles are
        then captured BEFORE the termination request (identity safe: a held
        handle keeps its pid from being reused), the job is
        terminated, and the job is re-queried until the deadline as a second
        line of defence. True only when: the job lists no
        member, every captured member process object is signaled, the direct
        process is dead and the accounting snapshot agrees. Anything else -
        timeout, query failure, unopenable member, exception - is False. Every
        native handle opened here is closed before returning.

        Scope of True: no new process can join after the seal; every
        identity-safe member captured here is signaled. A member that had
        already begun exiting and vanished from the enumeration before the
        capture cannot be held (no historical identity in the Job API), so
        that one case is not identity-proven."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        self.last_confirmation_detail = None
        tracked: dict = {}
        try:
            if not self._job:
                # No job means nothing was ever assigned (or it was already
                # released after confirmed death): only the direct child remains.
                try:
                    proc.kill()
                except OSError:
                    pass
                return self._direct_dead_by(proc, deadline)
            # Identity-critical: after TerminateJobObject a member can leave the
            # job's accounting before its process object is signaled, so only
            # handles captured HERE can prove those members dead. A failed or
            # ambiguous capture is sticky: later clean snapshots cannot repair it.
            # The seal comes FIRST: once it is effective no process can join the
            # job, so the capture that follows enumerates a membership that can
            # only shrink. (Snapshot-then-seal would leave a snapshot/seal race.)
            sealed = self._seal_job()
            pre_pids, pre_ambiguous = self._refresh_members(tracked) if sealed else (None, True)
            capture_complete = sealed and pre_pids is not None and not pre_ambiguous
            self.force_terminate(proc)  # still requested for safety
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            if not capture_complete:
                self.last_confirmation_detail = (
                    "JOB_SEAL_FAILED" if not sealed
                    else "PRE_TERMINATION_MEMBER_QUERY_FAILED" if pre_pids is None
                    else "PRE_TERMINATION_MEMBER_IDENTITY_AMBIGUOUS"
                )
                return False
            while True:
                pids, ambiguous = self._refresh_members(tracked)
                pending = self._first_unsignaled(tracked)
                if pids is None:
                    self.last_confirmation_detail = "JOB_MEMBER_QUERY_FAILED"
                elif pids or ambiguous:
                    self.last_confirmation_detail = "JOB_STILL_LISTS_MEMBERS_OR_MEMBER_UNOPENABLE"
                elif pending is not None:
                    self.last_confirmation_detail = "MEMBER_PROCESS_OBJECT_NOT_SIGNALED"
                elif proc.poll() is None:
                    self.last_confirmation_detail = "DIRECT_PROCESS_NOT_DEAD"
                elif not self.is_empty(proc):
                    self.last_confirmation_detail = "ACCOUNTING_REPORTS_ACTIVE_PROCESSES"
                else:
                    self.last_confirmation_detail = None
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                if pending is not None:
                    self._k32.WaitForSingleObject(pending, int(min(remaining, 0.05) * 1000))
                else:
                    time.sleep(min(remaining, 0.01))
        except Exception as exc:  # noqa: BLE001 - fail closed; handles are closed below
            self.last_confirmation_detail = f"CONFIRMATION_ERROR:{type(exc).__name__}: {exc}"
            return False
        finally:
            handles, tracked = list(tracked.values()), {}
            for handle in handles:
                self._close_native(handle)

    @staticmethod
    def _direct_dead_by(proc, deadline: float) -> bool:
        while True:
            if proc.poll() is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                proc.wait(timeout=min(remaining, 0.05))
            except subprocess.TimeoutExpired:
                pass

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
        """OBSERVATIONAL snapshot (direct exit + ActiveProcesses == 0). A member
        can already be out of the accounting while its process object is still
        unsignaled, so this is NOT proof of death; use `force_terminate_and_confirm`."""
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
        require_durable_identity: Optional[bool] = None,
    ):
        self._require_durable = (
            _DEFAULT_REQUIRE_DURABLE_IDENTITY if require_durable_identity is None else bool(require_durable_identity)
        )
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
            if self._require_durable and self._evidence_path is None:
                # Configuration/safety failure, not a reason to silently
                # disable persistence: no provider process is created.
                error = DurableIdentityUnavailableError(
                    "no durable evidence target: refusing to run a provider without recoverable identity")
                self._launch_failed(error)
                raise error
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
            if self._require_durable and not containment.has_start_barrier:
                containment.close()
                error = DurableIdentityUnavailableError(
                    f"containment {containment.mode!r} has no pre-execution barrier: refusing to run the provider")
                self._launch_failed(error)
                raise error
            try:
                proc = subprocess.Popen(
                    containment.launch_argv(self._argv), cwd=self._cwd, env=self._env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    **containment.popen_kwargs(),
                )
            except BaseException as exc:
                containment.close()
                self._launch_failed(exc)
                raise
            self._proc = proc = _OwnedPopen(proc)
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
                # still suspended here; POSIX: the bootstrap is blocked on the
                # start barrier and has not exec'd the provider). If it cannot
                # be made durable the process is not left running without a
                # recoverable owner and provider code never runs: fail closed.
                self._persist(required=True)
                containment.release_child(proc)
            except BaseException as exc:
                # Every failure after the OS process exists ends here: kill the
                # owned child/containment, close native resources, finalise.
                confirmed = self._kill_owned(proc)
                self._launch_failed(exc, confirmed_dead=confirmed)
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
        else:
            self.evidence.pop("termination_unresolved", None)
            self.evidence.pop("termination_unresolved_detail", None)
        self._persist()

    def _kill_owned(self, proc) -> bool:
        """Kills the owned child and its containment (never anything else),
        waits a bounded time and returns True only if the death of both was
        established. Native resources are closed only on confirmation; an
        unconfirmed job stays open so a later terminate() can still reach it
        (and closing it on Runner exit kills it anyway)."""
        containment = self._containment
        if containment is not None:
            confirmed = self._force_and_confirm(proc, containment)
        else:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - best effort, death is checked below
                pass
            confirmed = self._safe_poll(proc) is not None
        self._close_pipes(proc)
        if confirmed:
            confirmed = self._release_resources(proc, containment)
        return confirmed

    # -- secondary cleanup safety -------------------------------------------

    def _note_cleanup_error(self, stage: str, exc: BaseException) -> None:
        """A secondary probe/cleanup failure never replaces the primary error
        and never counts as proof of death: it is recorded and the lifecycle
        stays (or becomes) unresolved until a later attempt really confirms."""
        errors = self.evidence.setdefault("cleanup_errors", [])
        entry = f"{stage}: {type(exc).__name__}: {exc}"
        if not errors or errors[-1] != entry:  # a probe polled in a loop must not flood the evidence
            errors.append(entry)
        self.evidence["termination_unresolved"] = True
        self.evidence["termination_unresolved_detail"] = "CLEANUP_OR_PROBE_FAILED"

    def _safe_poll(self, proc):
        try:
            return proc.poll()
        except Exception as exc:  # noqa: BLE001 - probe failure is not evidence of death
            self._note_cleanup_error("poll", exc)
            return None

    def _force_and_confirm(self, proc, containment) -> bool:
        """The ONLY forced-death path: the containment's canonical
        `force_terminate_and_confirm`. Its answer is authoritative; a weaker
        emptiness probe is never consulted to overturn a False."""
        try:
            return bool(containment.force_terminate_and_confirm(proc, self.force_wait_seconds))
        except ContainmentProbeError as exc:
            self._note_cleanup_error("containment_probe", exc)
        except Exception as exc:  # noqa: BLE001 - fail closed: death not established
            self._note_cleanup_error("force_terminate", exc)
        return False

    def _probe_empty(self, proc, containment) -> bool:
        try:
            return bool(containment.is_empty(proc))
        except Exception as exc:  # noqa: BLE001 - inconclusive probe: not empty
            self._note_cleanup_error("containment_probe", exc)
            return False

    def _release_resources(self, proc, containment) -> bool:
        """Closes containment + native handle after confirmed death. Both are
        attempted and idempotent; if either fails the lifecycle is NOT
        reported as cleanly finished (a later terminate() retries)."""
        released = True
        steps = [("handle_release", proc.release_handle)]
        if containment is not None:
            steps.insert(0, ("containment_close", containment.close))
        for stage, action in steps:
            try:
                action()
            except Exception as exc:  # noqa: BLE001
                self._note_cleanup_error(stage, exc)
                released = False
        return released

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
        failure: Optional[BaseException] = None
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
        except BaseException as exc:  # noqa: BLE001 - communicate/read/write/cancel-callback failure
            # Execution control is lost, but the provider is already running:
            # it is terminated below (owned containment only) before the
            # original failure is re-raised.
            failure = exc
            term_reason = f"COMMUNICATION_FAILURE:{type(exc).__name__}"

        try:
            if term_reason is None and self._term_requested_at is not None:
                # Another thread (ExecutionControl.terminate_now) already ended the process.
                interrupted, term_reason = True, self.evidence.get("termination_reason")
            if term_reason is not None:
                self.terminate(term_reason)
                if not communicated and failure is None:
                    out, err = self._drain(proc, out, err)
            else:
                # Normal completion: the provider exited. Descendants it left
                # behind are still owned by this execution and must not outlive it.
                self.terminate("PROCESS_COMPLETED_SWEEP", completed=True)
        except BaseException as exc:  # noqa: BLE001 - the termination path itself broke
            try:
                self._settle_after_broken_termination(proc, exc)
            except Exception as cleanup_exc:  # noqa: BLE001 - never replaces the primary failure
                self._mark_unresolved_after_cleanup_failure(cleanup_exc)
            if failure is None:
                failure = exc
        finally:
            self._close_pipes(proc)
            try:
                self._finalize_evidence(exited_normally=term_reason is None)
            except Exception as cleanup_exc:  # noqa: BLE001
                self._mark_unresolved_after_cleanup_failure(cleanup_exc)
        if failure is not None:
            raise failure
        return SupervisionOutcome(
            returncode=proc.returncode, stdout=out or b"", stderr=err or b"", timed_out=timed_out,
            interrupted=interrupted, duration_seconds=time.monotonic() - started, evidence=dict(self.evidence),
        )

    def _settle_after_broken_termination(self, proc, cause: BaseException) -> None:
        """terminate() itself raised: kill the owned containment directly and
        record an honest, non-RUNNING state."""
        with self._lock:
            confirmed = self._kill_owned(proc)
            self.evidence.update(
                status=STATUS_TERMINATED if confirmed else STATUS_UNRESOLVED, confirmed_dead=confirmed,
                exit_code=self._safe_poll(proc), ended_at=_utc_iso() if confirmed else None,
                termination_error=type(cause).__name__,
            )
            if confirmed:
                self.evidence.pop("termination_unresolved", None)
                self.evidence.pop("termination_unresolved_detail", None)
            else:
                self.evidence["termination_unresolved"] = True
                self.evidence["termination_unresolved_detail"] = "TERMINATION_PATH_FAILED_DEATH_NOT_ESTABLISHED"

    def _mark_unresolved_after_cleanup_failure(self, exc: BaseException) -> None:
        """The cleanup path itself raised: keep the original error primary,
        record this one and downgrade (never upgrade) the lifecycle."""
        with self._lock:
            self._note_cleanup_error("cleanup", exc)
            if not (self._termination is not None and self._termination.confirmed_dead):
                self.evidence.update(status=STATUS_UNRESOLVED, confirmed_dead=False)
            try:
                self._persist()
            except Exception:  # noqa: BLE001 - _persist swallows non-required errors; belt and braces
                pass

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
            if self._safe_poll(proc) is not None:
                graceful = GRACEFUL_ALREADY_EXITED
            else:
                try:
                    requested = containment.request_graceful(proc)
                except Exception as exc:  # noqa: BLE001 - forced phase still follows
                    self._note_cleanup_error("graceful_request", exc)
                    requested = False
                if requested:
                    try:
                        proc.wait(timeout=self.grace_seconds)
                        graceful = GRACEFUL_EXITED
                    except subprocess.TimeoutExpired:
                        graceful = GRACEFUL_TIMEOUT
                else:
                    graceful = GRACEFUL_UNAVAILABLE

            if self._safe_poll(proc) is not None:
                # The direct child is gone; give the OS a moment to report the
                # containment empty before deciding descendants need a sweep.
                grace_deadline = time.monotonic() + 0.3
                while not self._probe_empty(proc, containment) and time.monotonic() < grace_deadline:
                    time.sleep(0.02)
            forced_confirmed: Optional[bool] = None
            if self._safe_poll(proc) is None or not self._probe_empty(proc, containment):
                forced_confirmed = self._force_and_confirm(proc, containment)
                forced = FORCED_TERMINATED if forced_confirmed else FORCED_FAILED
                if not forced_confirmed:
                    notes.append("forced termination did not establish death")

            # After a forced phase the canonical primitive is the only authority.
            confirmed = forced_confirmed if forced_confirmed is not None else self._confirm(proc, containment)
            if not confirmed:
                notes.append("death not confirmed within the bounded wait; treat as UNRESOLVED")
            if confirmed:
                # Deferred while another thread is inside Popen; a failing
                # close keeps the lifecycle unresolved and is retried later.
                confirmed = self._release_resources(proc, containment)
                if not confirmed:
                    notes.append("death observed but resource release failed; treat as UNRESOLVED")
            exit_code = self._safe_poll(proc)
            result = TerminationResult(
                requested_at=self._term_requested_at, reason=reason if not completed else None,
                graceful_outcome=graceful, forced_outcome=forced, exit_code=exit_code,
                ended_at=_utc_iso() if confirmed else None, confirmed_dead=confirmed, notes=notes,
            )
            self._termination = result
            self.evidence.update(
                graceful_outcome=graceful, forced_outcome=forced, exit_code=exit_code,
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
            if self._safe_poll(proc) is not None and self._probe_empty(proc, containment):
                return True
            if time.monotonic() >= deadline:
                return False
            try:
                proc.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
            except Exception as exc:  # noqa: BLE001 - inconclusive, keep bounded polling
                self._note_cleanup_error("wait", exc)
            time.sleep(0.02)

    def _finalize_evidence(self, *, exited_normally: bool) -> None:
        with self._lock:
            if self._proc is not None and self.evidence.get("exit_code") is None:
                self.evidence["exit_code"] = self._safe_poll(self._proc)
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
    require_durable_identity: Optional[bool] = None,
) -> SupervisionOutcome:
    """Runs one provider process under supervision. Returns an outcome with
    `interrupted=True` (and no process started) when `control` was cancelled
    before launch.

    Durable ownership evidence is REQUIRED by default: without an evidence
    target (a `control` carrying `evidence_path`) the provider is not started
    and a fail-closed outcome is returned. `require_durable_identity=False` is
    a non-production switch for standalone helpers/tests; the Runner never
    passes it."""
    started = time.monotonic()
    required = _DEFAULT_REQUIRE_DURABLE_IDENTITY if require_durable_identity is None else bool(require_durable_identity)
    if control is not None and not control.begin_launch():
        return SupervisionOutcome(
            None, b"", b"", False, True, 0.0,
            {"schema_version": EVIDENCE_SCHEMA_VERSION, "status": "NOT_STARTED", "provider": provider,
             "confirmed_dead": True, "termination_reason": control.cancel_reason},
        )
    if required and (control is None or control.evidence_path is None):
        if control is not None:
            control.end_launch()
        message = "no durable evidence target: refusing to run a provider without recoverable identity"
        return SupervisionOutcome(
            None, b"", f"process supervision refused to start the provider: {message}".encode("utf-8"),
            False, False, 0.0,
            {"schema_version": EVIDENCE_SCHEMA_VERSION, "status": STATUS_LAUNCH_FAILED, "provider": provider,
             "confirmed_dead": True, "launch_error": f"DurableIdentityUnavailableError: {message}",
             "durable_identity_refused": True},
        )
    sp = SupervisedProcess(
        argv, cwd, provider=provider, env=env, containment=containment, allow_degraded=allow_degraded,
        evidence_path=control.evidence_path if control else None,
        write_json=control.write_json if control else None,
        grace_seconds=grace_seconds, force_wait_seconds=force_wait_seconds,
        extra_evidence={"worker_id": control.worker_id, "attempt": control.attempt} if control else None,
        require_durable_identity=required,
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
        _settle_unconfirmed(sp)
        return SupervisionOutcome(
            None, b"", f"process supervision refused to start the provider: {exc}".encode("utf-8"),
            False, False, time.monotonic() - started, dict(sp.evidence),
        )
    except BaseException:
        # Never hand control back while an owned provider may still run.
        _settle_unconfirmed(sp)
        raise


def _settle_unconfirmed(sp: SupervisedProcess) -> None:
    if sp.started and not sp.confirmed_dead:
        try:
            sp.terminate("SUPERVISION_ABORTED")
        except Exception:  # noqa: BLE001 - evidence already says UNRESOLVED; the original error propagates
            pass

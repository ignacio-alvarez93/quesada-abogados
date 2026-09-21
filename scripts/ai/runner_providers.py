"""Provider-neutral execution foundation for the governed Runner (V2 multiprovider V1).

Runner core (`claude_runner.py`) owns work orders, worktree isolation,
governance (branch/dirty/write-scope guards), evidence, the result model and
verdict semantics. A *provider* owns only how one specific agent CLI/API is
invoked and interpreted:

* invocation syntax and prompt transport;
* provider/model identity and version;
* capability -> tool mapping;
* permission/governance flag translation;
* stdout/stderr interpretation;
* provider-specific metadata.

Core resolves a provider exclusively through `resolve_provider()` /
`ProviderRegistry`; it never branches on a provider id. Providers are
stateless factories' products: `resolve_provider()` returns a fresh instance
per call, and nothing in this module keeps per-run state, so worker A ->
claude -> worktree A and worker B -> codex -> worktree B can run
concurrently.

Two orthogonal statuses are normalized here (never conflated):

* PROCESS_STATUS - did the provider process itself complete cleanly;
* WORK_STATUS    - what the Work Order's own outcome claims (SUCCESS /
  PARTIAL / BLOCKED / FAILED, or UNVERIFIED when no verdict contract
  applies). Process exit code 0 never implies WORK_STATUS SUCCESS when the
  Work Order exposes a `VERDICT=` contract.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

MODE_READ_ONLY = "read-only"
MODE_WRITE = "write"


# ---------------------------------------------------------------------------
# Normalized statuses and capabilities
# ---------------------------------------------------------------------------

class Capability(str, Enum):
    READ_FILES = "READ_FILES"
    SEARCH_FILES = "SEARCH_FILES"
    EDIT_FILES = "EDIT_FILES"
    WRITE_FILES = "WRITE_FILES"
    SHELL = "SHELL"
    TEST_EXECUTION = "TEST_EXECUTION"
    STRUCTURED_RESULT = "STRUCTURED_RESULT"


class ProcessStatus(str, Enum):
    OK = "OK"
    NONZERO_EXIT = "NONZERO_EXIT"
    TIMED_OUT = "TIMED_OUT"
    INTERRUPTED = "INTERRUPTED"
    PROVIDER_REPORTED_ERROR = "PROVIDER_REPORTED_ERROR"


class WorkStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    # No verdict contract applied and none was reported: the process ran
    # cleanly but the work outcome was never asserted. Explicitly NOT SUCCESS.
    UNVERIFIED = "UNVERIFIED"
    # A verdict was required but absent/malformed/ambiguous.
    INVALID_VERDICT = "INVALID_VERDICT"


class ProviderError(Exception):
    """Base for provider resolution failures; `code` is machine-readable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UnknownProviderError(ProviderError):
    def __init__(self, provider_id: str, known: list):
        super().__init__(
            "PROVIDER_UNKNOWN",
            f"Unknown provider {provider_id!r}; registered providers: {', '.join(sorted(known)) or '<none>'}",
        )
        self.provider_id = provider_id


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderProbe:
    """Read-only availability probe. Never mutates anything, never touches
    credentials."""
    provider_id: str
    available: bool
    executable: Optional[str] = None
    version: Optional[str] = None
    reason: Optional[str] = None

    @property
    def label(self) -> str:
        return "AVAILABLE" if self.available else "UNAVAILABLE"


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str = MODE_READ_ONLY
    # Governance allows shell-class tools only when explicitly True. The
    # Runner's current governed modes never grant it (see claude_runner).
    allow_shell: bool = False


@dataclass(frozen=True)
class Invocation:
    """A fully specified, transport-safe process invocation.

    `argv` is a list (never a shell string, so no quoting/expansion applies)
    and never contains the prompt: the prompt travels in `stdin_bytes` (UTF-8,
    byte-exact, no newline translation) so a variadic flag such as `--tools`
    cannot swallow it and arbitrarily long/multiline/quoted text is
    transported unchanged. `cwd` is the explicit, verified worktree."""
    provider_id: str
    argv: list
    cwd: Path
    stdin_bytes: Optional[bytes]
    prompt_transport: str = "stdin"
    metadata: dict = field(default_factory=dict)


@dataclass
class ProcessOutcome:
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    interrupted: bool
    duration_seconds: float


@dataclass
class NormalizedResult:
    process_status: ProcessStatus
    work_status: WorkStatus
    verdict_raw: Optional[str] = None
    verdict_source: str = "none"
    verdict_required: bool = False
    verdict_candidates: list = field(default_factory=list)
    result_text: Optional[str] = None
    provider_metadata: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "process_status": self.process_status.value,
            "work_status": self.work_status.value,
            "verdict_raw": self.verdict_raw,
            "verdict_source": self.verdict_source,
            "verdict_required": self.verdict_required,
            "verdict_candidates": list(self.verdict_candidates),
            "provider_metadata": dict(self.provider_metadata),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Verdict parsing (provider-neutral)
# ---------------------------------------------------------------------------

_VERDICT_CONTRACT_RE = re.compile(r"\bVERDICT\s*=")
# Line-anchored so prose mentioning "VERDICT=" mid-sentence (e.g. an echoed
# instruction "VERDICT must be VERDICT=X or VERDICT=Y") is not read as a result.
_VERDICT_LINE_RE = re.compile(r"^[ \t>*_`#-]*VERDICT[ \t]*=[ \t]*(?P<value>[^\r\n]*?)[ \t*_`]*$", re.MULTILINE)

_STATUS_SEVERITY = {
    WorkStatus.FAILED: 3,
    WorkStatus.BLOCKED: 2,
    WorkStatus.PARTIAL: 1,
    WorkStatus.SUCCESS: 0,
}


def work_order_requires_verdict(work_order_text: str) -> bool:
    """A Work Order 'exposes a structured VERDICT field' when it names a
    `VERDICT=` contract anywhere in its text."""
    return bool(_VERDICT_CONTRACT_RE.search(work_order_text or ""))


def classify_verdict_value(value: str) -> Optional[WorkStatus]:
    """Maps one `VERDICT=<value>` value to a WorkStatus, or None if the value
    is not recognizable. Negative markers dominate positive ones, so
    `X_NOT_READY` / `X_BLOCKED:reason` never read as SUCCESS."""
    token = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
    if not token or token in {"X", "VALUE", "STATUS"}:
        return None
    words = set(token.split("_"))
    if words & {"BLOCKED", "BLOCKER"}:
        return WorkStatus.BLOCKED
    if words & {"FAILED", "FAIL", "FAILURE", "ERROR", "REJECTED"} or "NOT" in words:
        return WorkStatus.FAILED
    if words & {"PARTIAL", "PARTIALLY", "INCOMPLETE"}:
        return WorkStatus.PARTIAL
    if words & {"READY", "COMPLETED", "COMPLETE", "SUCCESS", "SUCCEEDED", "PASS", "PASSED", "OK", "DONE"}:
        return WorkStatus.SUCCESS
    return None


def extract_verdict(result_text: Optional[str]) -> tuple:
    """Returns (WorkStatus|None, raw_line_value|None, candidates, note).

    Fail-safe on ambiguity: when several line-anchored verdicts disagree the
    most severe one wins, so a stray/early BLOCKED is never overridden into
    SUCCESS. An unrecognizable verdict yields (None, raw, ...)."""
    if not result_text:
        return None, None, [], "no result text to search for a verdict"
    candidates = []
    for match in _VERDICT_LINE_RE.finditer(result_text):
        value = match.group("value").strip()
        status = classify_verdict_value(value)
        candidates.append({"value": value, "status": status.value if status else None})
    if not candidates:
        return None, None, [], "no line-anchored VERDICT= found"
    recognized = [
        (WorkStatus(c["status"]), c["value"]) for c in candidates if c["status"] is not None
    ]
    if not recognized:
        return None, candidates[-1]["value"], candidates, "VERDICT= present but value not recognized"
    worst = max(recognized, key=lambda pair: _STATUS_SEVERITY[pair[0]])
    note = None
    if len({status for status, _ in recognized}) > 1:
        note = "conflicting VERDICT lines; most severe taken (fail-safe)"
    return worst[0], worst[1], candidates, note


def normalize_outcome(
    *,
    outcome: ProcessOutcome,
    provider_reported_error: bool,
    result_text: Optional[str],
    verdict_required: bool,
    provider_metadata: Optional[dict] = None,
) -> NormalizedResult:
    """Provider-neutral PROCESS_STATUS / WORK_STATUS derivation.

    WORK_STATUS is never derived from the return code alone: a clean process
    with a BLOCKED verdict is BLOCKED; a clean process with a required but
    missing/unparseable verdict is INVALID_VERDICT; a clean process with no
    verdict contract is UNVERIFIED (never SUCCESS by itself)."""
    metadata = dict(provider_metadata or {})
    if outcome.timed_out:
        process_status = ProcessStatus.TIMED_OUT
    elif outcome.interrupted:
        process_status = ProcessStatus.INTERRUPTED
    elif outcome.returncode != 0:
        process_status = ProcessStatus.NONZERO_EXIT
    elif provider_reported_error:
        process_status = ProcessStatus.PROVIDER_REPORTED_ERROR
    else:
        process_status = ProcessStatus.OK

    if process_status is not ProcessStatus.OK:
        return NormalizedResult(
            process_status=process_status, work_status=WorkStatus.FAILED,
            verdict_required=verdict_required, result_text=result_text,
            provider_metadata=metadata,
            notes=[f"process status {process_status.value}; work outcome cannot be trusted"],
        )

    status, raw, candidates, note = extract_verdict(result_text)
    notes = [note] if note else []
    if status is not None:
        return NormalizedResult(
            process_status=process_status, work_status=status, verdict_raw=raw,
            verdict_source="result_text", verdict_required=verdict_required,
            verdict_candidates=candidates, result_text=result_text,
            provider_metadata=metadata, notes=notes,
        )
    if verdict_required:
        return NormalizedResult(
            process_status=process_status, work_status=WorkStatus.INVALID_VERDICT,
            verdict_raw=raw, verdict_source="none", verdict_required=True,
            verdict_candidates=candidates, result_text=result_text,
            provider_metadata=metadata,
            notes=notes + ["Work Order requires a VERDICT= but none usable was reported"],
        )
    return NormalizedResult(
        process_status=process_status, work_status=WorkStatus.UNVERIFIED,
        verdict_raw=raw, verdict_source="none", verdict_required=False,
        verdict_candidates=candidates, result_text=result_text,
        provider_metadata=metadata,
        notes=notes + ["no verdict contract; process completed cleanly, work outcome not asserted"],
    )


# ---------------------------------------------------------------------------
# Process transport
# ---------------------------------------------------------------------------

def run_process(argv: list, cwd: Path, stdin_bytes: Optional[bytes], timeout_seconds: int) -> ProcessOutcome:
    """Generic, provider-neutral process transport.

    * argv list, `shell=False`: no shell quoting or expansion can corrupt it.
    * stdin is always explicitly a pipe carrying `stdin_bytes` (or closed
      empty), never inherited, so no TTY is ever involved or awaited.
    * bytes in/out with explicit UTF-8: no platform newline translation."""
    import time

    start = time.monotonic()
    proc = subprocess.Popen(
        argv, cwd=str(cwd),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def _decode(data: Optional[bytes]) -> str:
        return (data or b"").decode("utf-8", errors="replace")

    try:
        out, err = proc.communicate(input=stdin_bytes or b"", timeout=timeout_seconds)
        return ProcessOutcome(proc.returncode, _decode(out), _decode(err), False, False, time.monotonic() - start)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return ProcessOutcome(proc.returncode, _decode(out), _decode(err), True, False, time.monotonic() - start)
    except KeyboardInterrupt:
        proc.kill()
        out, err = proc.communicate()
        return ProcessOutcome(proc.returncode, _decode(out), _decode(err), False, True, time.monotonic() - start)


def probe_executable_version(executable: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=timeout)
        return (result.stdout.strip() or result.stderr.strip()) or "<empty>"
    except Exception as exc:  # environment-dependent
        return f"<unavailable: {exc}>"


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------

class Provider(ABC):
    """Contract every execution provider implements."""

    provider_id: str = ""
    display_name: str = ""
    # Runner state name reported when this provider is unavailable, kept only
    # so a pre-existing provider preserves its historical failure state;
    # None means the neutral PROVIDER_UNAVAILABLE.
    legacy_unavailable_state: Optional[str] = None

    @abstractmethod
    def probe(self) -> ProviderProbe:
        """Read-only availability/version check."""

    @abstractmethod
    def capabilities(self, policy: ExecutionPolicy) -> frozenset:
        """Capabilities actually deliverable under `policy` (honest mapping)."""

    def models(self) -> Optional[list]:
        """Model ids when the provider can expose them reliably, else None."""
        return None

    @abstractmethod
    def build_invocation(
        self, *, executable: str, cwd: Path, prompt_text: str,
        policy: ExecutionPolicy, model: Optional[str] = None,
    ) -> Invocation:
        """Builds the invocation: argv, explicit cwd, prompt transport, and
        the tool/permission translation of `policy`."""

    def execute(self, invocation: Invocation, timeout_seconds: int, transport: Optional[Callable] = None) -> ProcessOutcome:
        """Runs the invocation. `transport(argv, cwd, stdin_bytes, timeout)`
        may be injected (tests, remote workers); default is `run_process`."""
        return (transport or run_process)(invocation.argv, invocation.cwd, invocation.stdin_bytes, timeout_seconds)

    @abstractmethod
    def normalize_result(
        self, outcome: ProcessOutcome, *, verdict_required: bool
    ) -> NormalizedResult:
        """Interprets provider stdout/stderr into the neutral result model."""

    def metadata(self, probe: ProviderProbe) -> dict:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "version": probe.version,
            "executable": probe.executable,
        }

    def legacy_metadata(self, probe: ProviderProbe) -> dict:
        """Top-level metadata.json keys a provider must keep emitting for
        pre-multiprovider consumers (none by default)."""
        return {}

    def is_transient_failure(self, runner_state: str, error_text: str) -> bool:
        """True only when this adapter can establish that a failed attempt
        was a transient provider/network/rate-limit condition worth a
        governed retry. The orchestrator core never guesses: the default is
        False (no automatic retry)."""
        return False


# Provider-neutral transient-condition vocabulary shared by adapters that can
# read their CLI's stderr/error text (rate limits, overload, network, 5xx).
TRANSIENT_ERROR_RE = re.compile(
    r"rate[ _-]?limit|too many requests|429|overloaded|50[234]|"
    r"service unavailable|temporar(?:y|ily) unavailable|econnreset|etimedout|"
    r"connection (?:reset|refused|aborted)|network (?:error|is unreachable)|"
    r"socket hang up|try again",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

class PreflightVerdict(str, Enum):
    PASS = "PASS"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    WORKTREE_BINDING_FAILED = "WORKTREE_BINDING_FAILED"


@dataclass
class PreflightReport:
    verdict: PreflightVerdict
    provider_id: str
    provider_status: str
    provider_version: Optional[str]
    worktree_path: str
    branch: Optional[str]
    head: Optional[str]
    dirty: Optional[bool]
    requested_capabilities: list
    provider_capabilities: list
    missing_capabilities: list
    prompt_chars: int
    prompt_bytes: int
    execution_policy: dict
    reason: Optional[str] = None

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data["verdict"] = self.verdict.value
        return data


def required_capabilities(policy: ExecutionPolicy, explicit: tuple = ()) -> frozenset:
    """Capabilities a run under `policy` needs: read/search always; editing
    and writing in write mode; plus any the Work Order explicitly requests
    (by capability name). A `VERDICT=` contract is deliberately NOT a
    capability requirement: verdicts are parsed from result text, which every
    provider can produce. Unknown explicit names are kept as raw strings so
    they surface as missing rather than being silently dropped."""
    caps: set = {Capability.READ_FILES, Capability.SEARCH_FILES}
    if policy.mode == MODE_WRITE:
        caps |= {Capability.EDIT_FILES, Capability.WRITE_FILES}
    for name in explicit:
        try:
            caps.add(Capability(str(name).strip().upper()))
        except ValueError:
            caps.add(str(name))
    return frozenset(caps)


def _git_toplevel(path: Path) -> Optional[str]:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return str(Path(result.stdout.strip()).resolve())
    except OSError:
        return None


def _git_head(path: Path) -> Optional[str]:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def verify_worktree_binding(requested: Path, cwd: Path, expected_head: Optional[str] = None) -> Optional[str]:
    """Proves the process cwd IS the requested worktree: `cwd` resolves to
    the same directory as `requested`, both belong to the same git worktree
    (same toplevel), and - when given - that worktree's HEAD is the one the
    Runner snapshotted. This prevents a provider shell from starting in
    another checkout. Read-only; returns an error string or None."""
    try:
        requested_r, cwd_r = requested.resolve(), cwd.resolve()
    except OSError as exc:
        return f"cannot resolve worktree path: {exc}"
    if not requested_r.is_dir():
        return f"worktree path is not a directory: {requested_r}"
    if requested_r != cwd_r:
        return f"process cwd {cwd_r} is not the requested worktree {requested_r}"
    top_requested, top_cwd = _git_toplevel(requested_r), _git_toplevel(cwd_r)
    if top_requested is None:
        return f"not inside a git worktree: {requested_r}"
    if top_requested != top_cwd:
        return f"cwd worktree {top_cwd} differs from requested worktree {top_requested}"
    if expected_head is not None and _git_head(cwd_r) != expected_head:
        return "worktree HEAD does not match the snapshotted HEAD"
    return None


def _cap_name(cap) -> str:
    return cap.value if isinstance(cap, Capability) else str(cap)


def run_preflight(
    *, provider: Provider, probe: ProviderProbe, repo: Path, invocation: Optional[Invocation],
    prompt_text: str, policy: ExecutionPolicy, branch: Optional[str], head: Optional[str],
    dirty: Optional[bool], explicit_capabilities: tuple = (),
) -> PreflightReport:
    """Read-only preflight: records provider/worktree/capability facts and
    decides PASS or a specific pre-execution refusal. Mutates nothing."""
    requested = required_capabilities(policy, explicit_capabilities)
    provided = provider.capabilities(policy) if probe.available else frozenset()
    missing = sorted(_cap_name(c) for c in requested - provided)

    binding_error = verify_worktree_binding(repo, invocation.cwd if invocation else repo, head)
    verdict = PreflightVerdict.PASS
    reason = None
    if not probe.available:
        verdict, reason = PreflightVerdict.PROVIDER_UNAVAILABLE, probe.reason or "provider unavailable"
    elif binding_error:
        verdict, reason = PreflightVerdict.WORKTREE_BINDING_FAILED, binding_error
    elif missing:
        verdict = PreflightVerdict.CAPABILITY_MISMATCH
        reason = f"provider {provider.provider_id!r} cannot supply required capabilities: {', '.join(missing)}"

    return PreflightReport(
        verdict=verdict, provider_id=provider.provider_id, provider_status=probe.label,
        provider_version=probe.version, worktree_path=str(repo.resolve()),
        branch=branch, head=head, dirty=dirty,
        requested_capabilities=sorted(_cap_name(c) for c in requested),
        provider_capabilities=sorted(c.value for c in provided),
        missing_capabilities=missing,
        prompt_chars=len(prompt_text), prompt_bytes=len(prompt_text.encode("utf-8")),
        execution_policy={"mode": policy.mode, "allow_shell": policy.allow_shell},
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """Maps provider ids to factories. Holds factories only - every `create`
    returns a new provider instance, so there is no shared per-run state."""

    def __init__(self):
        self._factories: dict = {}

    def register(self, provider_id: str, factory: Callable[[], Provider]) -> None:
        if not provider_id or provider_id != provider_id.strip().lower():
            raise ValueError(f"provider id must be non-empty lowercase: {provider_id!r}")
        if provider_id in self._factories:
            raise ValueError(f"provider {provider_id!r} already registered")
        self._factories[provider_id] = factory

    def ids(self) -> list:
        return sorted(self._factories)

    def create(self, provider_id: Optional[str]) -> Provider:
        key = (provider_id or DEFAULT_PROVIDER_ID).strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            raise UnknownProviderError(str(provider_id), self.ids())
        return factory()


DEFAULT_PROVIDER_ID = "claude"


# ---------------------------------------------------------------------------
# Claude adapter
# ---------------------------------------------------------------------------

CLAUDE_READ_ONLY_TOOLS = "Read,Grep,Glob"
CLAUDE_WRITE_TOOLS = "Read,Grep,Glob,Edit,Write,NotebookEdit"


class ClaudeProvider(Provider):
    """Claude Code CLI adapter. Flags are exactly those verified against the
    installed CLI in claude_runner's history; behavior is unchanged."""

    provider_id = "claude"
    display_name = "Claude Code CLI"
    legacy_unavailable_state = "CLAUDE_ERROR"

    def locate_executable(self) -> Optional[str]:
        return shutil.which("claude")

    def probe(self) -> ProviderProbe:
        exe = self.locate_executable()
        if not exe:
            return ProviderProbe(self.provider_id, False, reason="claude CLI executable not found on PATH")
        return ProviderProbe(self.provider_id, True, executable=exe, version=probe_executable_version(exe))

    def legacy_metadata(self, probe: ProviderProbe) -> dict:
        return {"claude_cli_version": probe.version}

    def is_transient_failure(self, runner_state: str, error_text: str) -> bool:
        return runner_state == "CLAUDE_ERROR" and bool(TRANSIENT_ERROR_RE.search(error_text or ""))

    def capabilities(self, policy: ExecutionPolicy) -> frozenset:
        caps = {Capability.READ_FILES, Capability.SEARCH_FILES, Capability.STRUCTURED_RESULT}
        if policy.mode == MODE_WRITE:
            caps |= {Capability.EDIT_FILES, Capability.WRITE_FILES}
        # Shell is representable (Bash tool) but only when governance allows.
        if policy.allow_shell:
            caps |= {Capability.SHELL, Capability.TEST_EXECUTION}
        return frozenset(caps)

    def build_invocation(self, *, executable, cwd, prompt_text, policy, model=None) -> Invocation:
        if policy.mode not in {MODE_READ_ONLY, MODE_WRITE}:
            raise ValueError(
                f"unsupported execution mode {policy.mode!r}; "
                f"expected {MODE_READ_ONLY!r} or {MODE_WRITE!r}"
            )
        tools = CLAUDE_WRITE_TOOLS if policy.mode == MODE_WRITE else CLAUDE_READ_ONLY_TOOLS
        if policy.allow_shell:
            tools += ",Bash"
        # See claude_runner history: dontAsk silently no-ops writes, so write
        # mode uses acceptEdits; --restricted + --permission-prompts none
        # keep settings/git/tool-config writes auto-denied.
        permission_mode = "acceptEdits" if policy.mode == MODE_WRITE else "dontAsk"
        argv = [
            executable, "--print", "--output-format", "json",
            "--tools", tools, "--restricted",
            "--permission-mode", permission_mode,
            "--permission-prompts", "none",
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
        ]
        if model:
            argv += ["--model", model]
        # The prompt is NOT in argv: `--tools` is variadic and would swallow a
        # trailing positional prompt. It travels on stdin, byte-exact.
        return Invocation(
            provider_id=self.provider_id, argv=argv, cwd=cwd,
            stdin_bytes=prompt_text.encode("utf-8"),
            metadata={"tools": tools, "permission_mode": permission_mode},
        )

    def normalize_result(self, outcome: ProcessOutcome, *, verdict_required: bool) -> NormalizedResult:
        parsed = parse_json_stdout(outcome.stdout)
        provider_error = bool(parsed.get("parsed") and isinstance(parsed["cli_result"], dict)
                              and parsed["cli_result"].get("is_error"))
        result_text = None
        meta = {}
        if parsed.get("parsed") and isinstance(parsed["cli_result"], dict):
            cli = parsed["cli_result"]
            if isinstance(cli.get("result"), str):
                result_text = cli["result"]
            denials = cli.get("permission_denials")
            if denials:
                meta["permission_denials"] = len(denials)
        return normalize_outcome(
            outcome=outcome, provider_reported_error=provider_error,
            result_text=result_text, verdict_required=verdict_required,
            provider_metadata=meta,
        )


def parse_json_stdout(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        return {"parsed": False, "reason": "empty stdout"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"parsed": False, "reason": f"stdout is not valid JSON: {exc}", "raw_excerpt": text[:2000]}
    return {"parsed": True, "cli_result": data}


# ---------------------------------------------------------------------------
# Codex / OpenAI adapter (CLI: `codex exec`)
# ---------------------------------------------------------------------------

class CodexProvider(Provider):
    """OpenAI Codex CLI adapter (`codex exec`, prompt on stdin via `-`).

    Written against the documented `codex exec` non-interactive surface
    (`--sandbox`, `--cd`, `--skip-git-repo-check`, `-`), NOT verified against
    a locally installed build: when `codex` is absent the probe reports
    UNAVAILABLE and nothing is executed. Execution correctness must be
    smoke-tested once the CLI is installed."""

    provider_id = "codex"
    display_name = "OpenAI Codex CLI"

    def locate_executable(self) -> Optional[str]:
        return shutil.which("codex")

    def is_transient_failure(self, runner_state: str, error_text: str) -> bool:
        return runner_state == "CLAUDE_ERROR" and bool(TRANSIENT_ERROR_RE.search(error_text or ""))

    def probe(self) -> ProviderProbe:
        exe = self.locate_executable()
        if not exe:
            return ProviderProbe(self.provider_id, False, reason="codex CLI executable not found on PATH")
        return ProviderProbe(self.provider_id, True, executable=exe, version=probe_executable_version(exe))

    def capabilities(self, policy: ExecutionPolicy) -> frozenset:
        # Codex's sandbox modes map: read-only -> read/search; workspace-write
        # -> edit/write plus sandboxed shell. Sandboxed shell is inherent to
        # codex, but SHELL is only *granted* when governance allows it.
        caps = {Capability.READ_FILES, Capability.SEARCH_FILES}
        if policy.mode == MODE_WRITE:
            caps |= {Capability.EDIT_FILES, Capability.WRITE_FILES}
        if policy.allow_shell:
            caps |= {Capability.SHELL, Capability.TEST_EXECUTION}
        # STRUCTURED_RESULT is deliberately not claimed: verdicts are parsed
        # from free text, and no JSON result envelope has been verified.
        return frozenset(caps)

    def build_invocation(self, *, executable, cwd, prompt_text, policy, model=None) -> Invocation:
        if policy.mode not in {MODE_READ_ONLY, MODE_WRITE}:
            raise ValueError(f"unsupported execution mode {policy.mode!r}")
        sandbox = "workspace-write" if policy.mode == MODE_WRITE else "read-only"
        argv = [executable, "exec", "--sandbox", sandbox, "--cd", str(cwd)]
        if model:
            argv += ["--model", model]
        argv.append("-")  # read the prompt from stdin
        return Invocation(
            provider_id=self.provider_id, argv=argv, cwd=cwd,
            stdin_bytes=prompt_text.encode("utf-8"), metadata={"sandbox": sandbox},
        )

    def normalize_result(self, outcome: ProcessOutcome, *, verdict_required: bool) -> NormalizedResult:
        return normalize_outcome(
            outcome=outcome, provider_reported_error=False,
            result_text=outcome.stdout, verdict_required=verdict_required,
        )


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------

def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(ClaudeProvider.provider_id, ClaudeProvider)
    registry.register(CodexProvider.provider_id, CodexProvider)
    return registry


_DEFAULT_REGISTRY = build_default_registry()


def resolve_provider(provider_id: Optional[str], registry: Optional[ProviderRegistry] = None) -> Provider:
    return (registry or _DEFAULT_REGISTRY).create(provider_id)


def registered_provider_ids(registry: Optional[ProviderRegistry] = None) -> list:
    return (registry or _DEFAULT_REGISTRY).ids()

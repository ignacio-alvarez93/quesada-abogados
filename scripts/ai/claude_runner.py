"""Governed Claude Runner (V1 core): read-only by default, write opt-in.

Executes exactly one Work Order in one fresh, non-interactive Claude CLI
invocation, captures auditable evidence under an ignored runtime
directory, and fails safe if the target repository is mutated outside
what the active execution mode authorizes.

Governance: docs/resolutions/20260912_resolucion_modelo_direccion_tecnica_y_
ejecucion_claude.md and CLAUDE.md define the execution model this runner
implements.

Execution modes:

* read-only (default, RUNNER-1B): tools restricted to Read,Grep,Glob.
  Any repository mutation detected after the run is FAILED_SAFETY. This
  behavior is unchanged from RUNNER-1B and must never be the write path.
* write (RUNNER-1C/1E, opt-in via --mode write): tools additionally
  include Edit,Write,NotebookEdit so the model may edit files.
  Bash/PowerShell/REPL and other command-running tools are never granted
  in either mode, so git mutation commands (commit, push, merge, reset,
  clean, branch switch/delete, --resume) remain structurally unreachable
  regardless of prompt content. Write mode additionally enforces, before
  invocation: a branch guard (refuses main/master/develop and detached
  HEAD); a write-scope guard (RUNNER-1E: requires at least one explicit
  --authorize-path repository-relative path or glob, normalized and
  validated against the repository root - absolute paths, '..'
  traversal, and empty scopes are rejected; a write-mode run with no
  authorized scope is refused before Claude is ever invoked); and a
  dirty-working-tree guard (RUNNER-1F: write mode fails closed and refuses
  ANY dirty working tree, unconditionally, before Claude is ever invoked.
  --allow-dirty is accepted by the CLI parser only for backward
  compatibility and has no effect: passing it does not permit a dirty
  tree. This replaces RUNNER-1E's narrower dirty-scope-overlap check,
  which could not detect a further runner-caused edit to a pre-existing
  dirty path outside the authorized scope, since such an edit leaves the
  same porcelain status line before and after the run. Runner V2.1 R21-B
  adds the ONE governed exception: an explicit --resume-from pointing at a
  prior write-mode attempt's own work_product.json, validated by
  evaluate_resume against the current worktree/branch/HEAD/process
  liveness/authorized-scope before it is honored - a dirty tree with no
  --resume-from, or a resume that fails any of those checks, is still
  refused exactly as before, with nothing ever reset or deleted). After
  invocation, a branch/HEAD change is always FAILED_SAFETY in write mode
  (commits and branch switches are never authorized); every runner-caused
  changed path (created, modified, deleted, renamed or staged) is checked
  against the authorized scope, and any path outside it is FAILED_SAFETY
  too - the offending files are preserved for inspection, never reverted.
  Working-tree changes that stay inside the authorized scope are the
  expected/authorized effect of write mode and are reported, not treated
  as a safety violation.

One Work Order is always exactly one fresh non-interactive invocation:
this runner never passes the Claude CLI's OWN --resume/-c/--continue
session flag in either mode (unrelated to this module's --resume-from,
which resumes a dirty WORKTREE across separate governed attempts, never a
Claude conversation), and never runs git reset, git clean, broad restore,
or any destructive cleanup itself.

CLI invocation shape: the flags used below were verified directly against
the actually installed Claude CLI (`claude --version` -> 2.1.272) via
`claude --help` and live probe invocations. No flag is invented; every
flag passed to the CLI is one that `claude --help` documents on the
installed build.

Governed checkpoint (Runner V2.1 R21-E): `execute_work_order` itself still
never touches git beyond reading it. `create_checkpoint` is a separate,
explicitly-invoked utility that commits EXACTLY a completed write-mode
attempt's own already-governed `work_product.json` paths - never a merge,
push or PR - for an orchestrator (`runner_pipeline`) whose manifest opted a
worker into `checkpoint_policy=ON_SUCCESS`. It is never called implicitly.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import platform
import posixpath
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# Provider abstraction (multiprovider V1). Same dual-import convention as
# claude_queue/claude_multiworker: package path first, sibling fallback when
# this file is run directly as a script.
try:
    from scripts.ai import runner_providers as providers
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import runner_providers as providers  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# States and exit codes
# ---------------------------------------------------------------------------

class RunState(str, Enum):
    SUCCESS = "SUCCESS"
    CLAUDE_ERROR = "CLAUDE_ERROR"
    TIMEOUT = "TIMEOUT"
    INTERRUPTED = "INTERRUPTED"
    INVALID_REPOSITORY = "INVALID_REPOSITORY"
    INVALID_WORK_ORDER = "INVALID_WORK_ORDER"
    FAILED_SAFETY = "FAILED_SAFETY"
    BRANCH_GUARD_REFUSED = "BRANCH_GUARD_REFUSED"
    DIRTY_TREE_REFUSED = "DIRTY_TREE_REFUSED"
    WRITE_SCOPE_REQUIRED = "WRITE_SCOPE_REQUIRED"
    WRITE_SCOPE_INVALID = "WRITE_SCOPE_INVALID"
    # Runner V2.1 R21-B: an explicit --resume-from token was supplied but
    # failed governed-resume provenance validation (see evaluate_resume).
    # The dirty tree is still refused, exactly as DIRTY_TREE_REFUSED would,
    # but under a distinct state so evidence/tests can tell "no resume was
    # requested" apart from "resume was requested and its provenance could
    # not be proven".
    RESUME_REFUSED = "RESUME_REFUSED"
    # Multiprovider V1: WORK_STATUS outcomes for a cleanly-completed process.
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    WORK_FAILED = "WORK_FAILED"
    VERDICT_INVALID = "VERDICT_INVALID"
    # Multiprovider V1: pre-execution refusals.
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    WORKTREE_BINDING_FAILED = "WORKTREE_BINDING_FAILED"


# Exit code 2 is reserved for argparse's own usage-error path (malformed
# CLI invocation of the runner itself, e.g. a missing required argument or
# an invalid --timeout-seconds) and is never assigned here, so it never
# collides with one of the states below.
EXIT_CODES = {
    RunState.SUCCESS: 0,
    RunState.CLAUDE_ERROR: 3,
    RunState.TIMEOUT: 4,
    RunState.INTERRUPTED: 5,
    RunState.BLOCKED: 6,
    RunState.PARTIAL: 7,
    RunState.WORK_FAILED: 8,
    RunState.VERDICT_INVALID: 9,
    RunState.INVALID_REPOSITORY: 10,
    RunState.INVALID_WORK_ORDER: 11,
    RunState.PROVIDER_UNKNOWN: 12,
    RunState.PROVIDER_UNAVAILABLE: 13,
    RunState.CAPABILITY_MISMATCH: 14,
    RunState.WORKTREE_BINDING_FAILED: 15,
    RunState.FAILED_SAFETY: 20,
    RunState.BRANCH_GUARD_REFUSED: 21,
    RunState.DIRTY_TREE_REFUSED: 22,
    RunState.WRITE_SCOPE_REQUIRED: 23,
    RunState.WRITE_SCOPE_INVALID: 24,
    RunState.RESUME_REFUSED: 25,
}

DEFAULT_TIMEOUT_SECONDS = 900
MAX_WORK_ORDER_CHARS = 200_000
RUNTIME_SUBDIR = Path("runtime") / "claude_runner" / "runs"

MODE_READ_ONLY = "read-only"
MODE_WRITE = "write"

# Branches write mode refuses to run against, regardless of --allow-dirty.
# Ordinary development happens on feature/*; write mode must never be used
# directly on an integration or stable branch (docs/resolutions/
# 20260912_..._ejecucion_claude.md section XIII; CLAUDE.md section 6).
PROTECTED_BRANCHES = {"main", "master", "develop"}

# Explicit read-only tool allowlist: no Bash/PowerShell/Edit/Write/
# NotebookEdit/WebFetch/Task, so the model has no mechanism to mutate the
# repository even if instructed to. Combined with --restricted (defense
# in depth: also strips code-running tools and ignores project-level
# .claude settings/hooks that could otherwise run arbitrary commands) and
# --permission-prompts none (anything that would still need approval is
# auto-denied rather than hanging a non-interactive run).
READ_ONLY_TOOLS = providers.CLAUDE_READ_ONLY_TOOLS

# Write-mode tool allowlist: adds file-editing tools only. Bash/PowerShell/
# REPL and other command-running tools are deliberately never included in
# either mode, so no git mutation command (commit/push/merge/reset/clean/
# branch switch or delete) is reachable through the tool surface at all,
# regardless of prompt content. --restricted additionally requires human/
# configured-handler approval to write settings, git or tool-configuration
# files even when Edit/Write are granted; combined with
# --permission-prompts none, any such attempt is auto-denied rather than
# silently allowed.
WRITE_TOOLS = providers.CLAUDE_WRITE_TOOLS


class RunnerError(Exception):
    """Raised for pre-invocation validation failures with a known RunState."""

    def __init__(self, state: RunState, message: str):
        super().__init__(message)
        self.state = state
        self.message = message


# ---------------------------------------------------------------------------
# Programmatic execution API (RUNNER-1.5B)
# ---------------------------------------------------------------------------
#
# WorkOrderRequest/WorkOrderResult are the public contract for executing one
# Work Order programmatically (e.g. from a future claude_queue.py), deliberately
# independent of argparse.Namespace: the CLI (main()) builds one of these from
# parsed arguments and is otherwise a thin adapter over execute_work_order().

@dataclass
class WorkOrderRequest:
    repo: str
    work_order: str
    mode: str = MODE_READ_ONLY
    authorize_path: Optional[list] = None
    allow_dirty: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    model: Optional[str] = None
    run_root: Optional[str] = None
    label: Optional[str] = None
    # Provider id resolved through the provider registry. None = the default
    # provider ("claude"), preserving the pre-multiprovider behavior.
    provider: Optional[str] = None
    # None = auto (a Work Order that names a `VERDICT=` contract requires a
    # usable verdict); True/False force it.
    require_verdict: Optional[bool] = None
    # Extra provider-neutral capability names (e.g. "SHELL") the Work Order
    # needs beyond what its execution mode implies; unmet => preflight refusal.
    required_capabilities: Optional[list] = None
    # Per-attempt process-supervision channel (runner_process_supervision.
    # ExecutionControl) supplied by the orchestrator: cancellation plus the
    # durable process-evidence target. None for direct CLI runs.
    execution_control: Optional[object] = None
    # Runner V2.1 R21-B: provenance metadata recorded on this attempt's
    # WORK_PRODUCT_MODEL (see `_build_work_product_record`), supplied by an
    # orchestrator that knows it (e.g. runner_pipeline). Purely descriptive -
    # None for a direct CLI run - and never used in any safety decision.
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    attempt: Optional[int] = None
    # Runner V2.1 R21-B: explicit, governed resume. Path to a prior write-
    # mode run's `work_product.json` (see `evaluate_resume`). Only takes
    # effect when write mode's dirty-tree guard would otherwise refuse a
    # dirty tree; every check in `evaluate_resume` must pass or the run is
    # refused as RESUME_REFUSED. None (default) preserves RUNNER-1F exactly:
    # any dirty tree is refused unconditionally.
    resume_from: Optional[str] = None


@dataclass
class WorkOrderResult:
    state: RunState
    exit_code: int
    run_id: Optional[str]
    evidence_dir: Optional[Path]
    error_message: Optional[str] = None
    # Normalized WORK_STATUS (see runner_providers.WorkStatus) when a
    # provider actually ran; None for pre-execution refusals.
    work_status: Optional[str] = None
    # Secret-free provider availability classification (see
    # runner_provider_availability) for a provider-side failure; None otherwise.
    provider_condition: Optional[dict] = None
    # Runner V2.1 R21-A: whether every evidence artifact the runner attempted
    # to persist for this run was actually written. This is independent of
    # `state`/`work_status` - a provider that completed successfully can still
    # leave EVIDENCE incomplete (disk/permission/race failure writing the
    # run's artifacts), and that must never be reported as WORK_FAILED.
    evidence_complete: bool = True
    # Secret-free description of what evidence writing failed, when
    # `evidence_complete` is False; None otherwise.
    evidence_error: Optional[str] = None
    # Runner V2.1 R21-B: True when this attempt recorded a work-product
    # checkpoint (`<evidence_dir>/work_product.json`) a future attempt can
    # pass as `--resume-from`/`WorkOrderRequest.resume_from`. Always False
    # for a pre-execution refusal or a read-only run.
    work_product_present: bool = False


# ---------------------------------------------------------------------------
# Git snapshot / safety comparison
# ---------------------------------------------------------------------------

@dataclass
class GitSnapshot:
    branch: str
    head: str
    porcelain_status: str
    raw_text: str
    captured_at: str


@dataclass
class SafetyCheck:
    repository_mutated: bool
    branch_changed: bool
    head_changed: bool
    status_changed: bool
    notes: list = field(default_factory=list)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def is_git_worktree(repo: Path) -> bool:
    result = _run_git(repo, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def capture_git_snapshot(repo: Path) -> GitSnapshot:
    branch_result = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head_result = _run_git(repo, "rev-parse", "HEAD")
    # --untracked-files=all: without it, git collapses a wholly-untracked
    # directory into a single "?? dir/" line instead of listing the files
    # inside it, which would make write-scope enforcement (RUNNER-1E)
    # unable to tell whether an authorized subtree's *contents* stayed
    # inside it or an unrelated file also landed in that new directory.
    status_result = _run_git(repo, "status", "--porcelain=v1", "--branch", "--untracked-files=all")

    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "<unknown>"
    head = head_result.stdout.strip() if head_result.returncode == 0 else "<unknown>"
    porcelain = status_result.stdout if status_result.returncode == 0 else "<unavailable>"
    captured_at = datetime.now(timezone.utc).isoformat()

    raw_text = (
        f"captured_at: {captured_at}\n"
        f"branch: {branch}\n"
        f"head: {head}\n"
        f"---- git status --porcelain=v1 --branch ----\n"
        f"{porcelain}"
    )
    return GitSnapshot(
        branch=branch,
        head=head,
        porcelain_status=porcelain,
        raw_text=raw_text,
        captured_at=captured_at,
    )


def compare_git_snapshots(before: GitSnapshot, after: GitSnapshot) -> SafetyCheck:
    branch_changed = before.branch != after.branch
    head_changed = before.head != after.head
    status_changed = before.porcelain_status != after.porcelain_status

    notes = []
    if branch_changed:
        notes.append(f"branch changed: {before.branch!r} -> {after.branch!r}")
    if head_changed:
        notes.append(f"HEAD changed: {before.head!r} -> {after.head!r}")
    if status_changed:
        notes.append("working tree / index status changed (tracked or untracked files)")

    return SafetyCheck(
        repository_mutated=branch_changed or head_changed or status_changed,
        branch_changed=branch_changed,
        head_changed=head_changed,
        status_changed=status_changed,
        notes=notes,
    )


def parse_porcelain_lines(porcelain_status: str) -> list:
    """Returns the `git status --porcelain=v1 --branch` entry lines, i.e.
    every line except the leading `## <branch>` header and blank lines.
    Kept as raw lines (not split into status/path) so rename entries
    (`R  old -> new`) and unusual paths compare and serialize exactly."""
    return [
        line for line in porcelain_status.splitlines()
        if line.strip() and not line.startswith("##")
    ]


def compute_changed_paths_after_run(before: GitSnapshot, after: GitSnapshot) -> list:
    """Lines present in `after` status but not in `before` status: the
    working-tree/index changes attributable to the run itself, excluding
    any pre-existing dirty paths that were already there (read-only mode
    has no dirty-tree guard; write mode requires a clean tree, so this
    only differs from `after`'s full line set in read-only mode)."""
    before_lines = set(parse_porcelain_lines(before.porcelain_status))
    after_lines = parse_porcelain_lines(after.porcelain_status)
    return [line for line in after_lines if line not in before_lines]


def _unquote_porcelain_path(raw_path: str) -> str:
    """`git status --porcelain` wraps a path in double quotes (with C-style
    escapes) when it contains unusual characters. Stripping the surrounding
    quotes is best-effort - it is only used to compare a path against the
    authorized scope, never to address the filesystem."""
    path = raw_path.strip()
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    return path


def extract_paths_from_porcelain_line(line: str) -> list:
    """Returns the repository-relative path(s) named by one
    `git status --porcelain=v1` entry line. A rename/copy line
    (`R  old -> new` / `C  old -> new`) names two paths; every other line
    names exactly one. Format is fixed-width: two status characters, one
    space, then the path (see `git help status`)."""
    if len(line) < 4:
        return []
    rest = line[3:]
    if " -> " in rest:
        old_path, _, new_path = rest.partition(" -> ")
        return [_unquote_porcelain_path(old_path), _unquote_porcelain_path(new_path)]
    return [_unquote_porcelain_path(rest)]


def path_is_authorized(path: str, authorized_scopes: list) -> bool:
    """True if `path` (repository-relative) falls inside one of
    `authorized_scopes`. A scope authorizes: itself exactly; anything
    under it as a directory subtree (`scope/...`); or, if it contains a
    glob metacharacter, anything `fnmatch` matches against it. `fnmatch`
    does not treat `/` specially, so a glob scope like `src/*.py` matches
    recursively under `src/`, not only its direct children - deliberately
    conservative in the direction of what counts as authorized, never in
    what counts as safe, since callers still require exact-or-subtree
    match for anything not carrying a glob character."""
    normalized_path = path.strip().replace("\\", "/")
    normalized_path = _unquote_porcelain_path(normalized_path)
    for scope in authorized_scopes:
        if scope == ".":
            return True
        if normalized_path == scope or normalized_path.startswith(scope + "/"):
            return True
        if any(ch in scope for ch in "*?[") and fnmatch.fnmatchcase(normalized_path, scope):
            return True
    return False


def classify_changed_paths(changed_paths_after_run: list, authorized_scopes: list) -> tuple:
    """Splits runner-caused porcelain lines into (authorized, unauthorized)
    against `authorized_scopes`. A rename/copy line is authorized only if
    BOTH the old and new path are in scope, so moving a file from an
    authorized location to an unauthorized one (or vice versa) is flagged
    rather than silently accepted."""
    authorized = []
    unauthorized = []
    for line in changed_paths_after_run:
        paths = extract_paths_from_porcelain_line(line)
        if paths and all(path_is_authorized(p, authorized_scopes) for p in paths):
            authorized.append(line)
        else:
            unauthorized.append(line)
    return authorized, unauthorized


# ---------------------------------------------------------------------------
# Write-mode governance: branch guard, dirty-tree policy, safety verdict
# ---------------------------------------------------------------------------

@dataclass
class BranchGuardDecision:
    decision: str  # "ALLOWED" | "REFUSED_PROTECTED_BRANCH" | "REFUSED_DETACHED_HEAD"
    branch: str
    reason: Optional[str] = None


def evaluate_branch_guard(snapshot: GitSnapshot) -> BranchGuardDecision:
    # `git rev-parse --abbrev-ref HEAD` prints the literal string "HEAD"
    # when the checkout is detached (no branch to abbreviate to).
    if snapshot.branch == "HEAD":
        return BranchGuardDecision(
            decision="REFUSED_DETACHED_HEAD",
            branch=snapshot.branch,
            reason="Write mode refuses a detached HEAD checkout.",
        )
    if snapshot.branch in PROTECTED_BRANCHES:
        return BranchGuardDecision(
            decision="REFUSED_PROTECTED_BRANCH",
            branch=snapshot.branch,
            reason=f"Write mode refuses protected branch {snapshot.branch!r}.",
        )
    return BranchGuardDecision(decision="ALLOWED", branch=snapshot.branch)


@dataclass
class DirtyTreeDecision:
    decision: str  # "ALLOWED_CLEAN" | "ALLOWED_RESUMED" | "REFUSED_DIRTY"
    preexisting_dirty_paths: list = field(default_factory=list)


def evaluate_dirty_tree(snapshot: GitSnapshot) -> DirtyTreeDecision:
    """RUNNER-1F: write mode fails closed on ANY dirty working tree,
    unconditionally - there is no flag that permits a dirty tree. A
    pre-existing dirty path's porcelain status line does not change if the
    runner edits it further, so an unauthorized further edit to such a
    path could otherwise evade unauthorized-path detection entirely; V1
    closes this by never invoking Claude against a dirty tree at all.

    Runner V2.1 R21-B: this function's verdict is unchanged and is exactly
    what still applies whenever no explicit `--resume-from` token is
    supplied. A governed resume is evaluated separately by `evaluate_resume`
    and, when it validates, produces its own `ALLOWED_RESUMED` decision
    instead of calling this function at all - see `execute_work_order`."""
    dirty_lines = parse_porcelain_lines(snapshot.porcelain_status)
    if not dirty_lines:
        return DirtyTreeDecision(decision="ALLOWED_CLEAN", preexisting_dirty_paths=[])
    return DirtyTreeDecision(decision="REFUSED_DIRTY", preexisting_dirty_paths=dirty_lines)


# ---------------------------------------------------------------------------
# Write-mode governance: work-product preservation + governed resume (R21-B)
# ---------------------------------------------------------------------------
#
# Observed problem this closes: a write-mode run can produce useful,
# authorized partial work and then stop before completing (provider quota,
# timeout, orchestrator death) - the work stays safely on disk, but the next
# attempt sees a dirty tree and RUNNER-1F refuses it unconditionally, with no
# way to tell "unknown preexisting dirty tree" apart from "work product this
# very governed pipeline produced". The model below lets Runner represent the
# latter explicitly and resume into it, WITHOUT weakening RUNNER-1F for a
# first execution or for any tree whose provenance cannot be proven.

# Schema for both `work_product.json` (written by a completed write-mode
# attempt, see `_build_work_product_record`) and the `--resume-from` record
# an operator/orchestrator later points back at it. Bumping this is a
# breaking change: an older/newer record is refused, never guessed at.
WORK_PRODUCT_SCHEMA_VERSION = 1

# Runner V2.1 R21-B-FIX1: the fixed, deterministic set of evidence artifact
# filenames a governed write-mode attempt writes beneath its OWN run
# directory (see `execute_work_order`/`_write_pre_invocation_failure_evidence`).
# This set is never provider- or user-influenced - Runner alone controls it -
# so it is the exact provenance basis for recognizing a NEXT attempt's own
# dirty-tree lines as RUNNER_OWNED_EVIDENCE rather than UNKNOWN_DIRTY_PATH.
RUNNER_EVIDENCE_ARTIFACT_FILENAMES = (
    "git_before.txt",
    "git_after.txt",
    "prompt.txt",
    "stdout.txt",
    "stderr.txt",
    "metadata.json",
    "preflight.json",
    "result.json",
    "work_product.json",
)


def _runner_owned_evidence_lines(run_dir: Path, repo: Path) -> list:
    """The exact `git status --porcelain=v1` lines a resuming attempt should
    expect for THIS run's own evidence artifacts - i.e. exact path
    provenance, never a directory-prefix exemption (see R21-B-FIX1 SAFETY
    RULE: no `runtime/**` ignore). Every artifact above is untracked by
    construction (Runner never `git add`s its own evidence), so the status
    is always `??`. Empty when `run_dir` is not inside `repo` (an operator
    `--run-root` override outside the worktree leaves nothing for git to
    see, and therefore nothing to prove)."""
    try:
        rel_dir = run_dir.relative_to(repo)
    except ValueError:
        return []
    rel_posix = rel_dir.as_posix()
    return [f"?? {rel_posix}/{name}" for name in RUNNER_EVIDENCE_ARTIFACT_FILENAMES]


def _build_work_product_record(
    *,
    run_dir: Path,
    repo: Path,
    provider: "providers.Provider",
    request: WorkOrderRequest,
    git_before: GitSnapshot,
    authorized_scopes: list,
    authorized_changed_paths: list,
    state: RunState,
    outcome: "providers.ProcessOutcome",
    recorded_at: datetime,
) -> dict:
    """The durable, inspectable record of one write-mode attempt's
    authorized-in-scope, safety-clean partial work: `work_product_present`
    (REQUIRED MODEL) made concrete. `base_head`/`branch` are what the NEXT
    attempt's `evaluate_resume` must still see unchanged - write mode never
    commits, so any difference means the ground truth moved and provenance
    can no longer be proven. `process_confirmed_stopped` reuses the same
    process-lifecycle evidence `normalize_outcome` already relies on
    (`providers.process_lifecycle_unresolved`), so a resume can never treat
    a provider process that might still be running as safely stopped.

    Runner V2.1 R21-B-FIX1: `runner_owned_paths` (RUNNER_OWNED_EVIDENCE) is
    the exact-path provenance for THIS attempt's OWN evidence artifacts
    (see `_runner_owned_evidence_lines`), kept strictly separate from
    `authorized_changed_paths` (PROVIDER_WORK_PRODUCT). A resuming attempt's
    dirty tree is recognized only from the union of these two exact sets -
    never from a directory-prefix exemption."""
    return {
        "schema_version": WORK_PRODUCT_SCHEMA_VERSION,
        "run_id": run_dir.name,
        "pipeline_id": request.pipeline_id,
        "worker_id": request.worker_id,
        "attempt": request.attempt,
        "provider": provider.provider_id,
        "worktree": str(repo),
        "branch": git_before.branch,
        "base_head": git_before.head,
        "authorized_scopes": list(authorized_scopes),
        "authorized_changed_paths": list(authorized_changed_paths),
        "recorded_at_utc": recorded_at.isoformat(),
        "process_confirmed_stopped": not providers.process_lifecycle_unresolved(outcome),
        "state": state.value,
        "incomplete": state is not RunState.SUCCESS,
        "reason_incomplete": None if state is RunState.SUCCESS else state.value,
        "evidence_dir": str(run_dir),
        "runner_evidence_dir": str(run_dir),
        "runner_owned_paths": _runner_owned_evidence_lines(run_dir, repo),
    }


@dataclass
class ResumeDecision:
    decision: str
    # "NOT_REQUESTED" | "NOT_NEEDED_CLEAN_TREE" | "ALLOWED_RESUMED" |
    # "REFUSED_RECORD_UNREADABLE" | "REFUSED_RECORD_MALFORMED" |
    # "REFUSED_SCHEMA_VERSION" | "REFUSED_WORKTREE_MISMATCH" |
    # "REFUSED_BRANCH_MISMATCH" | "REFUSED_HEAD_MISMATCH" |
    # "REFUSED_PROCESS_NOT_CONFIRMED_STOPPED" |
    # "REFUSED_UNRECOGNIZED_DIRTY_PATH" | "REFUSED_DIRTY_PATH_OUT_OF_SCOPE"
    reason: Optional[str] = None
    record_path: Optional[str] = None
    record: Optional[dict] = None


def load_work_product_record(path: Path) -> tuple:
    """Returns (record, None) or (None, error_reason). Never raises: a
    resume attempt with an unreadable/malformed record must refuse, not
    crash the run before evidence can even be written."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"work product record could not be read: {type(exc).__name__}: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"work product record is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "work product record must be a JSON object"
    return data, None


def evaluate_resume(
    resume_from: str, repo: Path, git_before: GitSnapshot, authorized_scopes: list,
) -> ResumeDecision:
    """Runner V2.1 R21-B: validates an explicit `--resume-from` token (a
    prior write-mode attempt's `work_product.json`) against the CURRENT
    repository state before write mode may proceed past a dirty tree.
    EVERY check below must pass or resume is refused and the dirty tree
    fails closed exactly as RUNNER-1F always has (see SAFETY RULES #4/#5
    in the R21-B Work Order this implements). Nothing here reads or
    changes a single file: it only compares already-captured porcelain
    lines and the record's own claims, so a refusal can never itself be
    the thing that mutates the tree, and an ALLOWED_RESUMED verdict never
    resets/deletes anything - the tree is left exactly as found."""
    record_path = Path(resume_from)
    record, error = load_work_product_record(record_path)
    if error is not None:
        return ResumeDecision(decision="REFUSED_RECORD_UNREADABLE", reason=error, record_path=str(record_path))

    if record.get("schema_version") != WORK_PRODUCT_SCHEMA_VERSION:
        return ResumeDecision(
            decision="REFUSED_SCHEMA_VERSION",
            reason=(
                f"work product schema_version {record.get('schema_version')!r} is not supported "
                f"(expected {WORK_PRODUCT_SCHEMA_VERSION})"
            ),
            record=record, record_path=str(record_path),
        )

    recorded_paths = record.get("authorized_changed_paths")
    if not isinstance(recorded_paths, list) or not all(isinstance(p, str) for p in recorded_paths):
        return ResumeDecision(
            decision="REFUSED_RECORD_MALFORMED",
            reason="work product authorized_changed_paths must be a list of strings",
            record=record, record_path=str(record_path),
        )

    # Runner V2.1 R21-B-FIX1: RUNNER_OWNED_EVIDENCE provenance, kept strictly
    # separate from PROVIDER_WORK_PRODUCT above. `None`/absent (an older or
    # hand-built record) means "this record proves no Runner-owned paths",
    # never "trust anything" - it degrades to the pre-FIX1 behavior, not to
    # a wildcard.
    runner_owned_paths = record.get("runner_owned_paths")
    if runner_owned_paths is None:
        runner_owned_paths = []
    if not isinstance(runner_owned_paths, list) or not all(isinstance(p, str) for p in runner_owned_paths):
        return ResumeDecision(
            decision="REFUSED_RECORD_MALFORMED",
            reason="work product runner_owned_paths must be a list of strings",
            record=record, record_path=str(record_path),
        )

    # Same worktree.
    if record.get("worktree") != str(repo):
        return ResumeDecision(
            decision="REFUSED_WORKTREE_MISMATCH",
            reason=f"work product worktree {record.get('worktree')!r} does not match {str(repo)!r}",
            record=record, record_path=str(record_path),
        )
    # Expected branch.
    if record.get("branch") != git_before.branch:
        return ResumeDecision(
            decision="REFUSED_BRANCH_MISMATCH",
            reason=f"work product branch {record.get('branch')!r} does not match current branch {git_before.branch!r}",
            record=record, record_path=str(record_path),
        )
    # Expected HEAD/base relationship: write mode never commits, so the
    # prior attempt's base_head must still BE the current HEAD, bit for bit.
    if record.get("base_head") != git_before.head:
        return ResumeDecision(
            decision="REFUSED_HEAD_MISMATCH",
            reason=f"work product base_head {record.get('base_head')!r} does not match current HEAD {git_before.head!r}",
            record=record, record_path=str(record_path),
        )
    # Prior process confirmed stopped.
    if record.get("process_confirmed_stopped") is not True:
        return ResumeDecision(
            decision="REFUSED_PROCESS_NOT_CONFIRMED_STOPPED",
            reason=(
                "work product does not record its prior provider process as confirmed stopped; "
                "resuming could overlap a write still in progress"
            ),
            record=record, record_path=str(record_path),
        )

    recorded_set = set(recorded_paths)
    runner_owned_set = set(runner_owned_paths)
    current_dirty_lines = parse_porcelain_lines(git_before.porcelain_status)

    # Runner V2.1 R21-B-FIX1: known_resume_dirty_paths = PROVIDER_WORK_PRODUCT
    # (`recorded_set`) + exact-proven RUNNER_OWNED_EVIDENCE (`runner_owned_set`).
    # A line proven Runner-owned is set aside here - it is Runner's OWN
    # bookkeeping, never provider work, so it is exempt from the "currently
    # authorized scope" check below (that check is about provider write
    # scope, which never applies to Runner's own evidence directory).
    provider_dirty_lines = [line for line in current_dirty_lines if line not in runner_owned_set]

    # Dirty paths belong to the known prior work product.
    unrecognized = [line for line in provider_dirty_lines if line not in recorded_set]
    if unrecognized:
        return ResumeDecision(
            decision="REFUSED_UNRECOGNIZED_DIRTY_PATH",
            reason=(
                "dirty path(s) present that are not part of the recorded prior work product: "
                + "; ".join(unrecognized)
            ),
            record=record, record_path=str(record_path),
        )
    # Dirty paths remain inside the CURRENTLY authorized scope (not just the
    # scope recorded at capture time, which the operator could have widened
    # or narrowed for this resume invocation).
    out_of_scope = [
        line for line in provider_dirty_lines
        if not all(path_is_authorized(p, authorized_scopes) for p in extract_paths_from_porcelain_line(line))
    ]
    if out_of_scope:
        return ResumeDecision(
            decision="REFUSED_DIRTY_PATH_OUT_OF_SCOPE",
            reason=(
                "dirty path(s) from the prior work product fall outside the currently authorized scope: "
                + "; ".join(out_of_scope)
            ),
            record=record, record_path=str(record_path),
        )
    return ResumeDecision(decision="ALLOWED_RESUMED", record=record, record_path=str(record_path))


# ---------------------------------------------------------------------------
# Write-mode governance: authorized write scope (RUNNER-1E)
# ---------------------------------------------------------------------------

@dataclass
class WriteScopeDecision:
    decision: str  # "ALLOWED" | "REFUSED_MISSING_SCOPE" | "REFUSED_INVALID_SCOPE"
    authorized_scopes: list = field(default_factory=list)
    reason: Optional[str] = None


def normalize_authorized_scope(raw: str) -> str:
    """Normalizes one --authorize-path value to a repository-relative,
    forward-slash path or glob. Raises ValueError for anything empty,
    absolute (POSIX '/...' or a Windows drive letter), or containing a
    literal '..' segment. A normalized scope that passes these checks
    cannot resolve outside the repository root by construction, since it
    is always interpreted relative to that root and never carries a
    traversal segment."""
    if raw is None or not raw.strip():
        raise ValueError("authorized scope must not be empty")
    candidate = raw.strip().replace("\\", "/")
    if candidate.startswith("/"):
        raise ValueError(f"authorized scope must be repository-relative, not absolute: {raw!r}")
    if len(candidate) >= 2 and candidate[1] == ":":
        raise ValueError(f"authorized scope must be repository-relative, not absolute: {raw!r}")
    if ".." in candidate.split("/"):
        raise ValueError(f"authorized scope must not contain parent-directory traversal ('..'): {raw!r}")
    normalized = posixpath.normpath(candidate)
    if normalized in (".", ""):
        raise ValueError(f"authorized scope must not be empty: {raw!r}")
    return normalized


def evaluate_write_scope(raw_scopes: Optional[list]) -> WriteScopeDecision:
    """Write mode must fail closed before Claude is ever invoked when no
    authorized scope was supplied, and equally closed when a supplied
    scope is malformed - a malformed scope is refused as a whole rather
    than silently dropped, since silently narrowing the requested scope
    could authorize less (or more, via a typo) than the operator meant."""
    if not raw_scopes:
        return WriteScopeDecision(
            decision="REFUSED_MISSING_SCOPE",
            authorized_scopes=[],
            reason=(
                "Write mode requires at least one --authorize-path "
                "repository-relative path or glob; none was supplied."
            ),
        )
    normalized_scopes = []
    for raw in raw_scopes:
        try:
            normalized_scopes.append(normalize_authorized_scope(raw))
        except ValueError as exc:
            return WriteScopeDecision(
                decision="REFUSED_INVALID_SCOPE",
                authorized_scopes=[],
                reason=str(exc),
            )
    return WriteScopeDecision(decision="ALLOWED", authorized_scopes=normalized_scopes)


@dataclass
class WriteSafetyVerdict:
    verdict: str  # "SAFE" | "FAILED_SAFETY"
    reasons: list = field(default_factory=list)


def evaluate_write_mode_safety(
    safety: SafetyCheck, unauthorized_changed_paths: Optional[list] = None
) -> WriteSafetyVerdict:
    """In write mode, working-tree file changes are the expected/
    authorized effect of the run and are NOT a safety violation on their
    own, PROVIDED every changed path is inside the authorized write scope
    (RUNNER-1E; `unauthorized_changed_paths` carries whatever fell
    outside it - omitted or empty means none did). A branch change or a
    HEAD change always is: no tool granted in write mode can create a
    commit or switch a branch, so either one happening means something
    escaped the intended tool/permission boundary."""
    reasons = []
    if safety.branch_changed:
        reasons.append("branch changed during write-mode run; branch switches are never authorized")
    if safety.head_changed:
        reasons.append("HEAD changed during write-mode run; commits are never authorized")
    if unauthorized_changed_paths:
        reasons.append(
            "changed path(s) outside the authorized write scope: "
            + "; ".join(unauthorized_changed_paths)
        )
    return WriteSafetyVerdict(verdict="FAILED_SAFETY" if reasons else "SAFE", reasons=reasons)


# ---------------------------------------------------------------------------
# Governed checkpoint (Runner V2.1 R21-E)
# ---------------------------------------------------------------------------
#
# `execute_work_order` itself still never mutates git (see its module
# docstring): this is a separate, explicitly-invoked utility an orchestrator
# (`runner_pipeline`) may call AFTER a write-mode attempt already completed
# SUCCESS, and only when that orchestrator's manifest opted a worker into a
# checkpoint contract. It commits EXACTLY the paths a completed attempt's own
# `work_product.json` already proved authorized-in-scope and safety-clean -
# never anything wider, never a merge, never a push, never a PR - so a
# dependent worker can start on a clean tree without unsafe manual
# intervention between governed workers.

CHECKPOINT_POLICY_ON_SUCCESS = "ON_SUCCESS"
CHECKPOINT_POLICIES = frozenset({CHECKPOINT_POLICY_ON_SUCCESS})
CHECKPOINT_COMMIT_PREFIX = "runner-checkpoint(wip):"

# Decisions that leave the checkpoint contract satisfied (either a commit was
# made, or there was provably nothing to checkpoint). Every other decision
# string is a refusal: nothing was committed and the worktree is unchanged.
CHECKPOINT_OK_DECISIONS = frozenset({"CREATED", "SKIPPED_NO_WORK_PRODUCT"})


@dataclass
class CheckpointResult:
    decision: str
    commit_hash: Optional[str] = None
    reason: Optional[str] = None
    committed_paths: list = field(default_factory=list)
    message: Optional[str] = None


def build_checkpoint_message(
    *, pipeline_id: Optional[str], worker_id: Optional[str], attempt: Optional[int],
    provider_id: Optional[str], base_head: Optional[str],
) -> str:
    """Deterministic for identical inputs - never includes a timestamp or
    any other non-reproducible value."""
    return (
        f"{CHECKPOINT_COMMIT_PREFIX} {pipeline_id}/{worker_id} attempt={attempt} provider={provider_id}\n"
        "\n"
        "Runner V2.1 governed checkpoint (checkpoint_policy=ON_SUCCESS).\n"
        f"base_head={base_head}\n"
    )


def create_checkpoint(
    *, repo: Path, work_product: dict,
    pipeline_id: Optional[str] = None, worker_id: Optional[str] = None,
    attempt: Optional[int] = None, provider_id: Optional[str] = None,
) -> CheckpointResult:
    """Turns one completed write-mode attempt's already-governed work
    product into exactly one durable WIP commit. Every check below must
    pass, in order, or the checkpoint is refused and NOTHING is committed -
    on any refusal the worktree is left exactly as `work_product` described
    it (any partial `git add` is unstaged again), never reset, never
    cleaned. Trusts nothing beyond what `work_product` itself already
    proved and what is independently re-verified here against the CURRENT
    repository state; it never re-derives authorization from scratch."""
    repo = Path(repo)
    authorized_lines = work_product.get("authorized_changed_paths")
    if not isinstance(authorized_lines, list) or not all(isinstance(p, str) for p in authorized_lines):
        return CheckpointResult(
            decision="REFUSED_WORK_PRODUCT_MALFORMED",
            reason="work product authorized_changed_paths must be a list of strings",
        )
    if not authorized_lines:
        return CheckpointResult(
            decision="SKIPPED_NO_WORK_PRODUCT",
            reason="work product recorded no authorized changed paths; nothing to checkpoint",
        )
    if work_product.get("process_confirmed_stopped") is not True:
        return CheckpointResult(
            decision="REFUSED_PROCESS_NOT_CONFIRMED_STOPPED",
            reason="work product does not record its provider process as confirmed stopped",
        )

    runner_owned_lines = work_product.get("runner_owned_paths")
    runner_owned_set = set(runner_owned_lines) if isinstance(runner_owned_lines, list) else set()
    authorized_set = set(authorized_lines)

    snapshot = capture_git_snapshot(repo)
    if snapshot.branch != work_product.get("branch"):
        return CheckpointResult(
            decision="REFUSED_BRANCH_CHANGED",
            reason=f"branch is {snapshot.branch!r}, expected {work_product.get('branch')!r}",
        )
    if snapshot.head != work_product.get("base_head"):
        return CheckpointResult(
            decision="REFUSED_HEAD_CHANGED",
            reason=f"HEAD is {snapshot.head!r}, expected {work_product.get('base_head')!r}",
        )

    current_lines = parse_porcelain_lines(snapshot.porcelain_status)
    provider_lines = [line for line in current_lines if line not in runner_owned_set]
    unknown = [line for line in provider_lines if line not in authorized_set]
    if unknown:
        return CheckpointResult(
            decision="REFUSED_UNKNOWN_DIRTY_PATH",
            reason="dirty path(s) present that are not part of the recorded work product: " + "; ".join(unknown),
        )
    missing = [line for line in authorized_lines if line not in provider_lines]
    if missing:
        return CheckpointResult(
            decision="REFUSED_WORK_PRODUCT_PATH_MISSING",
            reason="recorded work-product path(s) are no longer dirty: " + "; ".join(missing),
        )

    pathspecs = sorted({p for line in authorized_lines for p in extract_paths_from_porcelain_line(line)})
    if not pathspecs:
        return CheckpointResult(
            decision="SKIPPED_NO_WORK_PRODUCT", reason="work product named no concrete paths",
        )

    add_result = _run_git(repo, "add", "--", *pathspecs)
    if add_result.returncode != 0:
        return CheckpointResult(
            decision="REFUSED_STAGE_FAILED",
            reason=(add_result.stderr or add_result.stdout).strip()[:2000],
        )

    check_cached = _run_git(repo, "diff", "--cached", "--check", "--", *pathspecs)
    check_unstaged = _run_git(repo, "diff", "--check", "--", *pathspecs)
    if check_cached.returncode != 0 or check_unstaged.returncode != 0:
        _run_git(repo, "reset", "--", *pathspecs)
        detail = (check_cached.stdout + check_unstaged.stdout).strip()[:2000]
        return CheckpointResult(
            decision="REFUSED_DIFF_CHECK_FAILED", reason=detail or "git diff --check reported issues",
        )

    post_add_snapshot = capture_git_snapshot(repo)
    post_lines = [line for line in parse_porcelain_lines(post_add_snapshot.porcelain_status) if line not in runner_owned_set]
    post_paths = {p for line in post_lines for p in extract_paths_from_porcelain_line(line)}
    if post_paths != set(pathspecs) or any(len(line) >= 2 and line[1] != " " for line in post_lines):
        _run_git(repo, "reset", "--", *pathspecs)
        return CheckpointResult(
            decision="REFUSED_UNEXPECTED_STAGED_STATE",
            reason="staged/index state does not match exactly the authorized, fully-staged work-product paths",
        )

    message = build_checkpoint_message(
        pipeline_id=pipeline_id, worker_id=worker_id, attempt=attempt,
        provider_id=provider_id, base_head=work_product.get("base_head"),
    )
    commit_result = _run_git(
        repo, "-c", "user.name=Runner Checkpoint", "-c", "user.email=runner-checkpoint@local",
        "commit", "--no-verify", "-m", message,
    )
    if commit_result.returncode != 0:
        _run_git(repo, "reset", "--", *pathspecs)
        return CheckpointResult(
            decision="REFUSED_COMMIT_FAILED",
            reason=(commit_result.stderr or commit_result.stdout).strip()[:2000],
        )

    commit_hash = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    final_snapshot = capture_git_snapshot(repo)
    final_lines = [line for line in parse_porcelain_lines(final_snapshot.porcelain_status) if line not in runner_owned_set]
    if final_lines:
        # Should be unreachable given every check above, but this invariant is
        # load-bearing: a checkpoint is never reported CREATED unless the
        # worktree is actually clean (module docstring: "resulting worktree
        # is clean" is a hard requirement, not a best-effort one).
        return CheckpointResult(
            decision="REFUSED_WORKTREE_NOT_CLEAN_AFTER_COMMIT", commit_hash=commit_hash,
            reason="worktree not clean after checkpoint commit",
        )

    return CheckpointResult(decision="CREATED", commit_hash=commit_hash, committed_paths=pathspecs, message=message)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_repository_path(repo_arg: str) -> Path:
    repo = Path(repo_arg).resolve()
    if not repo.exists() or not repo.is_dir():
        raise RunnerError(
            RunState.INVALID_REPOSITORY,
            f"Repository path does not exist or is not a directory: {repo}",
        )
    return repo


def validate_git_worktree(repo: Path) -> None:
    if not is_git_worktree(repo):
        raise RunnerError(
            RunState.INVALID_REPOSITORY,
            f"Repository path is not inside a Git work tree: {repo}",
        )


def validate_work_order(path_arg: str) -> tuple:
    wo_path = Path(path_arg).resolve()
    if not wo_path.exists() or not wo_path.is_file():
        raise RunnerError(
            RunState.INVALID_WORK_ORDER,
            f"Work Order file does not exist: {wo_path}",
        )
    try:
        text = wo_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise RunnerError(
            RunState.INVALID_WORK_ORDER,
            f"Work Order file could not be read as UTF-8 text: {exc}",
        )
    if not text.strip():
        raise RunnerError(
            RunState.INVALID_WORK_ORDER,
            f"Work Order file is empty: {wo_path}",
        )
    if len(text) > MAX_WORK_ORDER_CHARS:
        raise RunnerError(
            RunState.INVALID_WORK_ORDER,
            f"Work Order file exceeds {MAX_WORK_ORDER_CHARS} characters ({len(text)})",
        )
    return wo_path, text


def get_claude_executable() -> str:
    exe = providers.ClaudeProvider().locate_executable()
    if not exe:
        raise RunnerError(RunState.CLAUDE_ERROR, "claude CLI executable not found on PATH")
    return exe


def get_claude_version(executable: str) -> str:
    return providers.probe_executable_version(executable)


# ---------------------------------------------------------------------------
# CLI command construction and invocation
# ---------------------------------------------------------------------------
#
# Claude-specific construction lives in providers.ClaudeProvider; the names
# below remain as the stable, backward-compatible public surface.

def build_cli_command(claude_executable: str, model: Optional[str] = None, mode: str = MODE_READ_ONLY) -> list:
    invocation = providers.ClaudeProvider().build_invocation(
        executable=claude_executable, cwd=Path("."), prompt_text="",
        policy=providers.ExecutionPolicy(mode=mode), model=model,
    )
    return invocation.argv


ProcessOutcome = providers.ProcessOutcome


def invoke_claude(
    cmd: list, cwd: Path, prompt_text: str, timeout_seconds: int,
    provider_id: Optional[str] = None, control=None,
) -> ProcessOutcome:
    """Process transport used for EVERY provider (the name is historical and
    is kept because callers/tests substitute it). argv list, shell=False,
    explicit stdin pipe carrying the UTF-8 prompt bytes. The process runs
    under supervision; `control` is the per-attempt cancellation/evidence
    channel."""
    return providers.run_process(
        cmd, cwd, prompt_text.encode("utf-8"), timeout_seconds, provider_id=provider_id, control=control,
    )


_SUPERVISED_INVOKE = invoke_claude


def _transport_for(provider_id: str, control):
    """Per-execution transport. Substituted `invoke_claude` doubles (tests)
    keep their historical 4-argument contract; only the real supervised
    implementation receives the provider id and the execution control."""
    def transport(argv: list, cwd: Path, stdin_bytes: Optional[bytes], timeout_seconds: int) -> ProcessOutcome:
        extra = {"provider_id": provider_id, "control": control} if invoke_claude is _SUPERVISED_INVOKE else {}
        return invoke_claude(
            argv, cwd=cwd, prompt_text=(stdin_bytes or b"").decode("utf-8"),
            timeout_seconds=timeout_seconds, **extra,
        )
    return transport


def _process_transport(argv: list, cwd: Path, stdin_bytes: Optional[bytes], timeout_seconds: int) -> ProcessOutcome:
    return _transport_for("", None)(argv, cwd, stdin_bytes, timeout_seconds)


parse_cli_result = providers.parse_json_stdout


_WORK_STATUS_STATES = {
    providers.WorkStatus.SUCCESS: RunState.SUCCESS,
    providers.WorkStatus.UNVERIFIED: RunState.SUCCESS,
    providers.WorkStatus.BLOCKED: RunState.BLOCKED,
    providers.WorkStatus.PARTIAL: RunState.PARTIAL,
    providers.WorkStatus.FAILED: RunState.WORK_FAILED,
    providers.WorkStatus.INVALID_VERDICT: RunState.VERDICT_INVALID,
}


def classify_state(
    outcome: ProcessOutcome,
    safety: SafetyCheck,
    parsed_result: dict,
    mode: str = MODE_READ_ONLY,
    has_unauthorized_changes: bool = False,
    normalized: Optional["providers.NormalizedResult"] = None,
) -> RunState:
    # Safety takes priority over everything else. In read-only mode (the
    # RUNNER-1B contract, unchanged) ANY repository mutation is unsafe. In
    # write mode, working-tree file changes inside the authorized scope
    # are the authorized effect of the run; a branch or HEAD change
    # (never reachable through the granted tools), or any changed path
    # outside the authorized scope (RUNNER-1E), is unsafe.
    if mode == MODE_WRITE:
        if safety.branch_changed or safety.head_changed or has_unauthorized_changes:
            return RunState.FAILED_SAFETY
    elif safety.repository_mutated:
        return RunState.FAILED_SAFETY
    if outcome.timed_out:
        return RunState.TIMEOUT
    if outcome.interrupted:
        return RunState.INTERRUPTED
    if outcome.returncode != 0:
        return RunState.CLAUDE_ERROR
    if parsed_result.get("parsed") and parsed_result["cli_result"].get("is_error"):
        return RunState.CLAUDE_ERROR
    if normalized is not None:
        # A clean process is not a successful Work Order: WORK_STATUS decides.
        # UNVERIFIED (no verdict contract) keeps the pre-multiprovider
        # SUCCESS state; it is recorded as UNVERIFIED in the evidence.
        return _WORK_STATUS_STATES[normalized.work_status]
    return RunState.SUCCESS


# ---------------------------------------------------------------------------
# Run directory / evidence
# ---------------------------------------------------------------------------

# Runner V2.1 R21-A-FIX1: the run directory's OWN leaf name must stay
# bounded regardless of how long a caller-supplied `label` is (e.g. a
# pipeline orchestrator concatenates pipeline_id + worker_id, either of
# which may be up to 64 characters) - Windows MAX_PATH is 260 without the
# long-path policy enabled, and the leaf name is nested under other path
# segments this function does not control. A short, fixed-width digest is
# used instead of (truncated) raw label text so distinct long labels
# sharing a common prefix can never collide on the same leaf name.
_LABEL_DIGEST_CHARS = 10


def create_run_dir(repo: Path, run_root_arg: Optional[str], label: Optional[str]) -> Path:
    if run_root_arg:
        base = Path(run_root_arg).resolve()
    else:
        base = repo / RUNTIME_SUBDIR
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    name_parts = [timestamp, suffix]
    if label:
        digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:_LABEL_DIGEST_CHARS]
        name_parts.append(digest)
    run_dir = base / "_".join(name_parts)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _base_metadata(
    *,
    run_dir: Path,
    repo: Path,
    request: WorkOrderRequest,
    git_before: GitSnapshot,
    git_after: GitSnapshot,
    provider: "providers.Provider",
    probe: "providers.ProviderProbe",
    run_started_at: datetime,
    run_ended_at: datetime,
    duration_seconds: float,
    cli_command: Optional[list],
    process_returncode: Optional[int],
    timed_out: bool,
    interrupted: bool,
    state: RunState,
    execution_mode: str,
    branch_guard: Optional[dict] = None,
    write_scope: Optional[dict] = None,
    dirty_tree_policy: Optional[dict] = None,
    resume: Optional[dict] = None,
    work_product: Optional[dict] = None,
    changed_paths_after_run: Optional[list] = None,
    authorized_changed_paths: Optional[list] = None,
    unauthorized_changed_paths: Optional[list] = None,
    safety_verdict: Optional[dict] = None,
    preflight: Optional[dict] = None,
    normalized_result: Optional[dict] = None,
    safety_baseline_excludes_runner_evidence: bool = False,
) -> dict:
    return {
        **provider.legacy_metadata(probe),
        "provider": provider.metadata(probe),
        "preflight": preflight,
        "normalized_result": normalized_result,
        "run_id": run_dir.name,
        # Runner V2.1 R21-A-FIX1: the caller-supplied label (e.g. a pipeline
        # orchestrator's "<pipeline_id>-<worker_id>") is never embedded raw
        # into the run directory's leaf name (see `create_run_dir`); it is
        # preserved here, untruncated, for traceability.
        "label": request.label,
        "started_at_utc": run_started_at.isoformat(),
        "ended_at_utc": run_ended_at.isoformat(),
        "duration_seconds": duration_seconds,
        "repository": {
            "requested_path": request.repo,
            "resolved_path": str(repo),
            "branch_before": git_before.branch,
            "head_before": git_before.head,
            "branch_after": git_after.branch,
            "head_after": git_after.head,
        },
        "work_order_path": request.work_order,
        "timeout_seconds": request.timeout_seconds,
        "model": request.model,
        "cli_command": cli_command,
        "python_version": sys.version,
        "platform": platform.platform(),
        "process_returncode": process_returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "state": state.value,
        "exit_code": EXIT_CODES[state],
        "scope": "WRITE_V1" if execution_mode == MODE_WRITE else "READ_ONLY_V1",
        "execution_mode": execution_mode,
        "branch_guard": branch_guard,
        "write_scope": write_scope,
        "dirty_tree_policy": dirty_tree_policy,
        "preexisting_dirty_paths": (dirty_tree_policy or {}).get("preexisting_dirty_paths") if dirty_tree_policy else None,
        # Runner V2.1 R21-B: governed-resume decision (see `evaluate_resume`)
        # and, when this attempt itself left authorized in-scope changes
        # behind, the WORK_PRODUCT_MODEL record for a future resume to
        # validate against. `work_product_present` makes the REQUIRED MODEL's
        # boolean directly queryable without inspecting the nested object.
        "resume": resume,
        "work_product_present": work_product is not None,
        "work_product": work_product,
        "changed_paths_after_run": changed_paths_after_run,
        "authorized_changed_paths": authorized_changed_paths,
        "unauthorized_changed_paths": unauthorized_changed_paths,
        "safety_verdict": safety_verdict,
        # Runner V2.1 R21-A-FIX1: True once the provider has actually run,
        # proving the post-run mutation comparison used a baseline captured
        # AFTER Runner's own pre-invocation evidence bookkeeping (so that
        # bookkeeping is excluded from `safety_verdict`/`changed_paths_after_run`
        # above) rather than the earlier, truthful `git_before.txt` snapshot.
        "safety_baseline_excludes_runner_evidence": safety_baseline_excludes_runner_evidence,
    }


def _write_evidence_text(path: Path, content: str, errors: list) -> None:
    """Best-effort evidence write: a secondary evidence-artifact failure is
    recorded (secret-free: exception type/path name/message only, never
    provider output) instead of raising, so it can never overwrite an
    already-completed provider result with an uncaught exception."""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")


def _write_evidence_json(path: Path, payload: dict, errors: list) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")


def _write_pre_invocation_failure_evidence(
    *,
    run_dir: Path,
    repo: Path,
    request: WorkOrderRequest,
    exc: RunnerError,
    git_before: GitSnapshot,
    git_after: GitSnapshot,
    provider: "providers.Provider",
    probe: "providers.ProviderProbe",
    run_started_at: datetime,
    mode: str,
    branch_guard: Optional[BranchGuardDecision] = None,
    write_scope: Optional[WriteScopeDecision] = None,
    dirty_tree_policy: Optional[DirtyTreeDecision] = None,
    resume: Optional[ResumeDecision] = None,
    preflight: Optional[dict] = None,
) -> None:
    (run_dir / "prompt.txt").write_text(
        "<not available: repository/Work Order/governance validation failed before invocation>\n",
        encoding="utf-8",
    )
    (run_dir / "stdout.txt").write_text("", encoding="utf-8")
    (run_dir / "stderr.txt").write_text("", encoding="utf-8")
    (run_dir / "git_before.txt").write_text(git_before.raw_text, encoding="utf-8")
    (run_dir / "git_after.txt").write_text(git_after.raw_text, encoding="utf-8")

    branch_guard_dict = asdict(branch_guard) if branch_guard else None
    write_scope_dict = asdict(write_scope) if write_scope else None
    dirty_tree_dict = asdict(dirty_tree_policy) if dirty_tree_policy else None
    resume_dict = asdict(resume) if resume else None

    run_ended_at = datetime.now(timezone.utc)
    metadata = _base_metadata(
        run_dir=run_dir,
        repo=repo,
        request=request,
        git_before=git_before,
        git_after=git_after,
        provider=provider,
        probe=probe,
        run_started_at=run_started_at,
        run_ended_at=run_ended_at,
        duration_seconds=0.0,
        cli_command=None,
        process_returncode=None,
        timed_out=False,
        interrupted=False,
        state=exc.state,
        execution_mode=mode,
        branch_guard=branch_guard_dict,
        write_scope=write_scope_dict,
        dirty_tree_policy=dirty_tree_dict,
        resume=resume_dict,
        changed_paths_after_run=None,
        authorized_changed_paths=None,
        unauthorized_changed_paths=None,
        safety_verdict=None,
        preflight=preflight,
    )
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result_payload = {
        "state": exc.state.value,
        "error": exc.message,
        "cli_output": {"parsed": False, "reason": "provider was not invoked"},
        "provider": provider.metadata(probe),
        "preflight": preflight,
        "work_status": None,
        "safety_check": None,
        "execution_mode": mode,
        "branch_guard": branch_guard_dict,
        "write_scope": write_scope_dict,
        "dirty_tree_policy": dirty_tree_dict,
        "preexisting_dirty_paths": dirty_tree_dict.get("preexisting_dirty_paths") if dirty_tree_dict else None,
        "resume": resume_dict,
        "changed_paths_after_run": None,
        "authorized_changed_paths": None,
        "unauthorized_changed_paths": None,
        "safety_verdict": None,
    }
    (run_dir / "result.json").write_text(
        json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from exc
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value!r}")
    return ivalue


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_runner",
        description=(
            "Governed Claude Runner V1 core. Executes exactly one Work "
            "Order in one fresh, non-interactive Claude CLI invocation "
            "against an explicit Git repository/worktree and captures "
            "auditable evidence. Read-only (--mode read-only) is the "
            "default; write mode (--mode write) is an explicit opt-in "
            "that additionally enforces a branch guard, a required "
            "authorized write scope (--authorize-path), and a clean-"
            "working-tree requirement before invocation (any dirty tree "
            "is refused unconditionally; --allow-dirty is unsupported)."
        ),
    )
    parser.add_argument(
        "--repo", required=True,
        help="Path to the target Git repository/worktree root.",
    )
    parser.add_argument(
        "--work-order", required=True,
        help="Path to a UTF-8 text file containing the Work Order prompt.",
    )
    parser.add_argument(
        "--mode", choices=[MODE_READ_ONLY, MODE_WRITE], default=MODE_READ_ONLY,
        help=(
            "Execution mode (default: %(default)s). 'write' grants "
            "Edit/Write/NotebookEdit in addition to Read/Grep/Glob and "
            "enforces the branch guard and dirty-tree guard below. Never "
            "grants Bash/PowerShell or any other command-running tool, so "
            "git mutation commands remain unreachable in both modes."
        ),
    )
    parser.add_argument(
        "--authorize-path", dest="authorize_path", action="append", default=None,
        metavar="PATH_OR_GLOB",
        help=(
            "Required with --mode write, repeatable: a Work Order-"
            "authorized repository-relative file/directory path or glob "
            "(e.g. 'scripts/ai/claude_runner.py' or 'scripts/ai/**'). "
            "Write mode refuses to invoke Claude at all if none is given. "
            "Absolute paths and '..' segments are rejected. After the "
            "run, every changed path is checked against the authorized "
            "scope(s); anything outside is FAILED_SAFETY."
        ),
    )
    parser.add_argument(
        "--provider", default=None, metavar="PROVIDER_ID",
        help=(
            "Execution provider id from the provider registry "
            f"(registered: {', '.join(providers.registered_provider_ids())}; "
            f"default: {providers.DEFAULT_PROVIDER_ID}). Unknown ids are "
            "refused before any execution."
        ),
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", default=False,
        help=(
            "UNSUPPORTED for write execution and has no effect: write mode "
            "(RUNNER-1F) always refuses any dirty working tree before "
            "Claude is invoked, because a pre-existing dirty path's "
            "porcelain status line cannot reveal a further runner-caused "
            "edit to that same path. This flag is accepted only so "
            "existing invocations do not fail to parse; passing it does "
            "not permit a dirty tree. The only way past a dirty tree is "
            "the explicit, validated --resume-from below."
        ),
    )
    parser.add_argument(
        "--resume-from", dest="resume_from", default=None, metavar="WORK_PRODUCT_JSON",
        help=(
            "Runner V2.1 R21-B, write mode only: path to a prior write-mode "
            "attempt's work_product.json (written next to that attempt's "
            "own evidence whenever it left authorized, in-scope changes "
            "behind). Takes effect only if the working tree is CURRENTLY "
            "dirty; every dirty path must then be both recorded in that "
            "work product and inside --authorize-path, branch/HEAD must be "
            "unchanged since it was recorded, and it must record its prior "
            "provider process as confirmed stopped. Any mismatch refuses "
            "the run as RESUME_REFUSED - a genuinely unrelated dirty tree, "
            "or one with no --resume-from at all, is refused exactly as "
            "RUNNER-1F has always refused it; nothing is ever reset or "
            "deleted either way."
        ),
    )
    parser.add_argument(
        "--timeout-seconds", type=_positive_int, default=DEFAULT_TIMEOUT_SECONDS,
        help="Wall-clock timeout for the single Claude CLI invocation (default: %(default)s).",
    )
    parser.add_argument(
        "--model", default=None,
        help="Optional model override passed through to the Claude CLI.",
    )
    parser.add_argument(
        "--run-root", default=None,
        help="Override the run directory root (default: <repo>/runtime/claude_runner/runs).",
    )
    parser.add_argument(
        "--label", default=None,
        help="Optional short label appended to the run directory name.",
    )
    return parser


def execute_work_order(request: WorkOrderRequest) -> WorkOrderResult:
    """Programmatic execution API (RUNNER-1.5B): runs exactly one Work Order
    through the same governed path `main()` drives, without shelling out or
    duplicating any Runner safety logic. Every invariant enforced by V1
    (read-only default, branch/dirty-tree/write-scope guards, FAILED_SAFETY
    precedence, no auto-revert, deterministic evidence) applies identically
    here; `main()` is a thin CLI adapter over this function."""
    mode = request.mode

    run_started_at = datetime.now(timezone.utc)

    try:
        repo = validate_repository_path(request.repo)
    except RunnerError as exc:
        return WorkOrderResult(
            state=exc.state, exit_code=EXIT_CODES[exc.state],
            run_id=None, evidence_dir=None, error_message=exc.message,
        )

    # Providers are resolved ONLY through the registry; core never branches
    # on a provider id. A fresh instance per call keeps workers independent.
    try:
        provider = providers.resolve_provider(request.provider)
    except providers.ProviderError as exc:
        state = RunState.PROVIDER_UNKNOWN
        return WorkOrderResult(
            state=state, exit_code=EXIT_CODES[state],
            run_id=None, evidence_dir=None, error_message=exc.message,
        )

    probe = provider.probe()
    if not probe.available:
        state = RunState(provider.legacy_unavailable_state or RunState.PROVIDER_UNAVAILABLE.value)
        return WorkOrderResult(
            state=state, exit_code=EXIT_CODES[state], run_id=None, evidence_dir=None,
            error_message=f"provider {provider.provider_id!r} {probe.label}: {probe.reason}",
        )

    try:
        validate_git_worktree(repo)
    except RunnerError as exc:
        run_dir = create_run_dir(repo, request.run_root, request.label)
        git_snap = capture_git_snapshot(repo)
        _write_pre_invocation_failure_evidence(
            run_dir=run_dir, repo=repo, request=request, exc=exc,
            git_before=git_snap, git_after=git_snap,
            provider=provider, probe=probe, run_started_at=run_started_at,
            mode=mode,
        )
        return WorkOrderResult(
            state=exc.state, exit_code=EXIT_CODES[exc.state],
            run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
        )

    git_before = capture_git_snapshot(repo)

    # Write-mode governance gate: evaluated (and enforced) BEFORE the Work
    # Order file is even read, so a refusal never depends on Work Order
    # content. Not applicable in read-only mode, which preserves the
    # RUNNER-1B contract unchanged.
    branch_guard_decision: Optional[BranchGuardDecision] = None
    write_scope_decision: Optional[WriteScopeDecision] = None
    dirty_tree_decision: Optional[DirtyTreeDecision] = None
    resume_decision: Optional[ResumeDecision] = None
    if mode == MODE_WRITE:
        branch_guard_decision = evaluate_branch_guard(git_before)

        if branch_guard_decision.decision != "ALLOWED":
            exc = RunnerError(RunState.BRANCH_GUARD_REFUSED, branch_guard_decision.reason)
            git_after = capture_git_snapshot(repo)
            run_dir = create_run_dir(repo, request.run_root, request.label)
            _write_pre_invocation_failure_evidence(
                run_dir=run_dir, repo=repo, request=request, exc=exc,
                git_before=git_before, git_after=git_after,
                provider=provider, probe=probe, run_started_at=run_started_at,
                mode=mode, branch_guard=branch_guard_decision,
            )
            return WorkOrderResult(
                state=exc.state, exit_code=EXIT_CODES[exc.state],
                run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
            )

        # Runner V2.1 R21-B: an explicit --resume-from token is only ever
        # even considered when the tree is ACTUALLY dirty (nothing to
        # resume into otherwise) - it reorders the two guards below (write
        # scope must be known before a dirty path can be checked against
        # it) but changes nothing else: with no --resume-from, or with one
        # that fails `evaluate_resume`, a dirty tree is refused exactly as
        # RUNNER-1F has always refused it, with no reset/delete either way.
        dirty_lines = parse_porcelain_lines(git_before.porcelain_status)
        if dirty_lines and request.resume_from:
            write_scope_decision = evaluate_write_scope(request.authorize_path)

            if write_scope_decision.decision != "ALLOWED":
                scope_state = (
                    RunState.WRITE_SCOPE_REQUIRED
                    if write_scope_decision.decision == "REFUSED_MISSING_SCOPE"
                    else RunState.WRITE_SCOPE_INVALID
                )
                exc = RunnerError(scope_state, write_scope_decision.reason)
                git_after = capture_git_snapshot(repo)
                run_dir = create_run_dir(repo, request.run_root, request.label)
                _write_pre_invocation_failure_evidence(
                    run_dir=run_dir, repo=repo, request=request, exc=exc,
                    git_before=git_before, git_after=git_after,
                    provider=provider, probe=probe, run_started_at=run_started_at,
                    mode=mode, branch_guard=branch_guard_decision, write_scope=write_scope_decision,
                )
                return WorkOrderResult(
                    state=exc.state, exit_code=EXIT_CODES[exc.state],
                    run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
                )

            resume_decision = evaluate_resume(
                request.resume_from, repo, git_before, write_scope_decision.authorized_scopes,
            )
            if resume_decision.decision == "ALLOWED_RESUMED":
                dirty_tree_decision = DirtyTreeDecision(decision="ALLOWED_RESUMED", preexisting_dirty_paths=dirty_lines)
            else:
                exc = RunnerError(
                    RunState.RESUME_REFUSED,
                    f"Explicit resume was requested but refused ({resume_decision.decision}): "
                    f"{resume_decision.reason} The dirty working tree is refused exactly as it would be "
                    "without --resume-from; nothing was reset or deleted.",
                )
                git_after = capture_git_snapshot(repo)
                run_dir = create_run_dir(repo, request.run_root, request.label)
                _write_pre_invocation_failure_evidence(
                    run_dir=run_dir, repo=repo, request=request, exc=exc,
                    git_before=git_before, git_after=git_after,
                    provider=provider, probe=probe, run_started_at=run_started_at,
                    mode=mode, branch_guard=branch_guard_decision, write_scope=write_scope_decision,
                    resume=resume_decision,
                )
                return WorkOrderResult(
                    state=exc.state, exit_code=EXIT_CODES[exc.state],
                    run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
                )
        else:
            # Dirty-tree guard runs before the write-scope guard: a dirty tree
            # is refused unconditionally regardless of scope or --allow-dirty
            # (RUNNER-1F), so this ordering does not weaken the scope
            # requirement below (invocation still never happens without a
            # valid scope) while it keeps the dirty-tree refusal reason
            # primary when both conditions hold.
            dirty_tree_decision = evaluate_dirty_tree(git_before)

            if dirty_tree_decision.decision == "REFUSED_DIRTY":
                exc = RunnerError(
                    RunState.DIRTY_TREE_REFUSED,
                    "Write mode requires a clean working tree; RUNNER-1F removed "
                    "--allow-dirty as an operational escape hatch, so a dirty tree "
                    "is always refused before Claude is invoked unless an explicit, "
                    "governed --resume-from token validates it "
                    f"({len(dirty_tree_decision.preexisting_dirty_paths)} dirty path(s)).",
                )
                git_after = capture_git_snapshot(repo)
                run_dir = create_run_dir(repo, request.run_root, request.label)
                _write_pre_invocation_failure_evidence(
                    run_dir=run_dir, repo=repo, request=request, exc=exc,
                    git_before=git_before, git_after=git_after,
                    provider=provider, probe=probe, run_started_at=run_started_at,
                    mode=mode, branch_guard=branch_guard_decision,
                    dirty_tree_policy=dirty_tree_decision,
                )
                return WorkOrderResult(
                    state=exc.state, exit_code=EXIT_CODES[exc.state],
                    run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
                )

            write_scope_decision = evaluate_write_scope(request.authorize_path)

            if write_scope_decision.decision != "ALLOWED":
                scope_state = (
                    RunState.WRITE_SCOPE_REQUIRED
                    if write_scope_decision.decision == "REFUSED_MISSING_SCOPE"
                    else RunState.WRITE_SCOPE_INVALID
                )
                exc = RunnerError(scope_state, write_scope_decision.reason)
                git_after = capture_git_snapshot(repo)
                run_dir = create_run_dir(repo, request.run_root, request.label)
                _write_pre_invocation_failure_evidence(
                    run_dir=run_dir, repo=repo, request=request, exc=exc,
                    git_before=git_before, git_after=git_after,
                    provider=provider, probe=probe, run_started_at=run_started_at,
                    mode=mode, branch_guard=branch_guard_decision, write_scope=write_scope_decision,
                    dirty_tree_policy=dirty_tree_decision,
                )
                return WorkOrderResult(
                    state=exc.state, exit_code=EXIT_CODES[exc.state],
                    run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
                )

        if resume_decision is None:
            resume_decision = ResumeDecision(
                decision="NOT_REQUESTED" if not request.resume_from else "NOT_NEEDED_CLEAN_TREE",
            )

    try:
        work_order_path, prompt_text = validate_work_order(request.work_order)
    except RunnerError as exc:
        git_after = capture_git_snapshot(repo)
        run_dir = create_run_dir(repo, request.run_root, request.label)
        _write_pre_invocation_failure_evidence(
            run_dir=run_dir, repo=repo, request=request, exc=exc,
            git_before=git_before, git_after=git_after,
            provider=provider, probe=probe, run_started_at=run_started_at,
            mode=mode, branch_guard=branch_guard_decision, write_scope=write_scope_decision,
            dirty_tree_policy=dirty_tree_decision, resume=resume_decision,
        )
        return WorkOrderResult(
            state=exc.state, exit_code=EXIT_CODES[exc.state],
            run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
        )

    verdict_required = (
        request.require_verdict
        if request.require_verdict is not None
        else providers.work_order_requires_verdict(prompt_text)
    )
    policy = providers.ExecutionPolicy(mode=mode, allow_shell=False)

    # Read-only preflight: provider/worktree/capability/prompt facts are
    # recorded and any mismatch is refused BEFORE the provider runs. The
    # invocation is built here (pure) so the exact cwd is what gets proven.
    invocation = provider.build_invocation(
        executable=probe.executable, cwd=repo, prompt_text=prompt_text,
        policy=policy, model=request.model,
    )
    preflight = providers.run_preflight(
        provider=provider, probe=probe, repo=repo, invocation=invocation,
        prompt_text=prompt_text, policy=policy, branch=git_before.branch,
        head=git_before.head, dirty=bool(parse_porcelain_lines(git_before.porcelain_status)),
        explicit_capabilities=tuple(request.required_capabilities or ()),
    )
    preflight_dict = preflight.as_dict()
    if preflight.verdict is not providers.PreflightVerdict.PASS:
        exc = RunnerError(RunState(preflight.verdict.value), preflight.reason)
        git_after = capture_git_snapshot(repo)
        run_dir = create_run_dir(repo, request.run_root, request.label)
        _write_pre_invocation_failure_evidence(
            run_dir=run_dir, repo=repo, request=request, exc=exc,
            git_before=git_before, git_after=git_after,
            provider=provider, probe=probe, run_started_at=run_started_at,
            mode=mode, branch_guard=branch_guard_decision, write_scope=write_scope_decision,
            dirty_tree_policy=dirty_tree_decision, resume=resume_decision, preflight=preflight_dict,
        )
        return WorkOrderResult(
            state=exc.state, exit_code=EXIT_CODES[exc.state],
            run_id=run_dir.name, evidence_dir=run_dir, error_message=exc.message,
        )

    # The evidence run directory and the pre-execution git snapshot are
    # created/persisted deterministically HERE, before the provider is ever
    # invoked (Runner V2.1 R21-A). A provider process result must never be
    # discarded because a LATER (post-execution) evidence-write step failed:
    # by the time the provider can produce any output, `git_before.txt`
    # already exists on disk.
    run_dir = create_run_dir(repo, request.run_root, request.label)
    evidence_errors: list = []
    _write_evidence_text(run_dir / "git_before.txt", git_before.raw_text, evidence_errors)

    # Runner V2.1 R21-A-FIX1: `git_before` above is captured before this
    # function creates ANY filesystem artifact and is what `git_before.txt`
    # records - the truthful pre-provider audit snapshot. It must NOT be
    # used as the baseline for the post-run mutation comparison below,
    # because the evidence run directory it is normally nested under (and
    # `git_before.txt` itself) are Runner-owned bookkeeping created between
    # that snapshot and now; comparing against `git_before` would attribute
    # Runner's own writes to the provider. `git_safety_baseline` is
    # captured only now, AFTER every Runner-owned pre-invocation write
    # above, so it already reflects that bookkeeping and the comparison
    # below isolates exactly what the provider process itself changed.
    git_safety_baseline = capture_git_snapshot(repo)

    # Nothing below writes into the repository until AFTER git_after is
    # captured: the safety window must cover only what the invoked provider
    # process itself did, never the runner's own evidence bookkeeping.
    cmd = invocation.argv
    outcome = provider.execute(
        invocation, request.timeout_seconds,
        transport=_transport_for(provider.provider_id, request.execution_control),
    )

    git_after = capture_git_snapshot(repo)

    safety = compare_git_snapshots(git_safety_baseline, git_after)
    parsed_result = parse_cli_result(outcome.stdout)
    normalized = provider.normalize_result(outcome, verdict_required=verdict_required)

    changed_paths_after_run = compute_changed_paths_after_run(git_safety_baseline, git_after)
    authorized_changed_paths: Optional[list] = None
    unauthorized_changed_paths: Optional[list] = None
    if mode == MODE_WRITE:
        authorized_changed_paths, unauthorized_changed_paths = classify_changed_paths(
            changed_paths_after_run, write_scope_decision.authorized_scopes
        )
        safety_verdict = asdict(evaluate_write_mode_safety(safety, unauthorized_changed_paths))
    else:
        safety_verdict = {
            "verdict": "FAILED_SAFETY" if safety.repository_mutated else "SAFE",
            "reasons": list(safety.notes),
        }

    state = classify_state(
        outcome, safety, parsed_result, mode=mode,
        has_unauthorized_changes=bool(unauthorized_changed_paths),
        normalized=normalized,
    )
    run_ended_at = datetime.now(timezone.utc)

    # Availability classification (quota / auth / transient / execution) is
    # read only after the supervised provider process has fully returned, and
    # only for a provider-side failure. It is secret-free by construction.
    provider_condition = None
    if state == RunState.CLAUDE_ERROR:
        provider_condition = provider.classify_failure(
            stdout=outcome.stdout, stderr=outcome.stderr,
        ).as_dict()

    branch_guard_dict = asdict(branch_guard_decision) if branch_guard_decision else None
    write_scope_dict = asdict(write_scope_decision) if write_scope_decision else None
    dirty_tree_dict = asdict(dirty_tree_decision) if dirty_tree_decision else None
    resume_dict = asdict(resume_decision) if resume_decision else None

    # Runner V2.1 R21-B: WORK_PRODUCT_MODEL. Recorded only for a write-mode
    # attempt that is safety-clean (never for a FAILED_SAFETY run: a branch/
    # HEAD change or an out-of-scope path is a governance violation, not a
    # checkpoint worth resuming into) and only when it actually left
    # authorized in-scope changes behind - a run that never touched the
    # tree has nothing to preserve. This is independent of WORK_STATUS:
    # SUCCESS, PARTIAL, and an availability/transient CLAUDE_ERROR (the
    # observed-problem scenario: quota exhausted mid-run) all qualify, so
    # partial work from an attempt that did not complete is preserved and
    # made resumable exactly like completed work is.
    work_product: Optional[dict] = None
    if mode == MODE_WRITE and safety_verdict.get("verdict") == "SAFE" and authorized_changed_paths:
        work_product = _build_work_product_record(
            run_dir=run_dir, repo=repo, provider=provider, request=request,
            git_before=git_before, authorized_scopes=write_scope_decision.authorized_scopes,
            authorized_changed_paths=authorized_changed_paths, state=state, outcome=outcome,
            recorded_at=run_ended_at,
        )
        _write_evidence_json(run_dir / "work_product.json", work_product, evidence_errors)

    _write_evidence_text(run_dir / "prompt.txt", prompt_text, evidence_errors)
    _write_evidence_text(run_dir / "stdout.txt", outcome.stdout, evidence_errors)
    _write_evidence_text(run_dir / "stderr.txt", outcome.stderr, evidence_errors)
    _write_evidence_text(run_dir / "git_after.txt", git_after.raw_text, evidence_errors)

    metadata = _base_metadata(
        run_dir=run_dir,
        repo=repo,
        request=request,
        git_before=git_before,
        git_after=git_after,
        provider=provider,
        probe=probe,
        run_started_at=run_started_at,
        run_ended_at=run_ended_at,
        duration_seconds=outcome.duration_seconds,
        cli_command=cmd,
        process_returncode=outcome.returncode,
        timed_out=outcome.timed_out,
        interrupted=outcome.interrupted,
        state=state,
        execution_mode=mode,
        branch_guard=branch_guard_dict,
        write_scope=write_scope_dict,
        dirty_tree_policy=dirty_tree_dict,
        resume=resume_dict,
        work_product=work_product,
        changed_paths_after_run=changed_paths_after_run,
        authorized_changed_paths=authorized_changed_paths,
        unauthorized_changed_paths=unauthorized_changed_paths,
        safety_verdict=safety_verdict,
        preflight=preflight_dict,
        normalized_result=normalized.as_dict(),
        safety_baseline_excludes_runner_evidence=True,
    )
    if outcome.supervision is not None:
        metadata["process_supervision"] = outcome.supervision
    if provider_condition is not None:
        metadata["provider_condition"] = provider_condition
    # Evidence-completeness so far, as known at the time each artifact is
    # written; the authoritative, fully-accounted value is returned on
    # `WorkOrderResult.evidence_complete`/`evidence_error` below.
    metadata["evidence_complete"] = not evidence_errors
    metadata["evidence_errors"] = list(evidence_errors)
    _write_evidence_json(run_dir / "metadata.json", metadata, evidence_errors)
    _write_evidence_json(run_dir / "preflight.json", preflight_dict, evidence_errors)

    result_payload = {
        "state": state.value,
        "provider": provider.metadata(probe),
        "preflight": preflight_dict,
        "work_status": normalized.work_status.value,
        "normalized_result": normalized.as_dict(),
        "cli_output": parsed_result,
        "safety_check": {
            "repository_mutated": safety.repository_mutated,
            "branch_changed": safety.branch_changed,
            "head_changed": safety.head_changed,
            "status_changed": safety.status_changed,
            "notes": safety.notes,
        },
        "execution_mode": mode,
        "branch_guard": branch_guard_dict,
        "write_scope": write_scope_dict,
        "dirty_tree_policy": dirty_tree_dict,
        "preexisting_dirty_paths": dirty_tree_dict.get("preexisting_dirty_paths") if dirty_tree_dict else None,
        "resume": resume_dict,
        "work_product_present": work_product is not None,
        "work_product": work_product,
        "changed_paths_after_run": changed_paths_after_run,
        "authorized_changed_paths": authorized_changed_paths,
        "unauthorized_changed_paths": unauthorized_changed_paths,
        "safety_verdict": safety_verdict,
    }
    if provider_condition is not None:
        result_payload["provider_condition"] = provider_condition
    result_payload["evidence_complete"] = not evidence_errors
    result_payload["evidence_errors"] = list(evidence_errors)
    _write_evidence_json(run_dir / "result.json", result_payload, evidence_errors)

    evidence_complete = not evidence_errors
    evidence_error = "; ".join(evidence_errors) if evidence_errors else None

    return WorkOrderResult(
        state=state, exit_code=EXIT_CODES[state],
        run_id=run_dir.name, evidence_dir=run_dir, error_message=None,
        work_status=normalized.work_status.value, provider_condition=provider_condition,
        evidence_complete=evidence_complete, evidence_error=evidence_error,
        work_product_present=work_product is not None,
    )


def _request_from_args(args: argparse.Namespace) -> WorkOrderRequest:
    return WorkOrderRequest(
        repo=args.repo,
        work_order=args.work_order,
        mode=args.mode,
        authorize_path=args.authorize_path,
        allow_dirty=args.allow_dirty,
        timeout_seconds=args.timeout_seconds,
        model=args.model,
        run_root=args.run_root,
        label=args.label,
        provider=args.provider,
        resume_from=args.resume_from,
    )


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    request = _request_from_args(args)

    result = execute_work_order(request)

    if result.error_message is not None:
        print(f"error: {result.error_message}", file=sys.stderr)
        if result.evidence_dir is not None:
            print(f"evidence_dir={result.evidence_dir}", file=sys.stderr)
    else:
        print(f"run_id={result.run_id} state={result.state.value} exit_code={result.exit_code}")
        print(f"evidence_dir={result.evidence_dir}")

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())

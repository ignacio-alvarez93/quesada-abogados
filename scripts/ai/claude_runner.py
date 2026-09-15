"""Governed read-only Claude Runner (V1 core).

Executes exactly one Work Order in one fresh, non-interactive Claude CLI
invocation constrained to read-only tools, captures auditable evidence
under an ignored runtime directory, and fails safe (FAILED_SAFETY) if the
target repository is mutated despite the read-only constraint.

Governance: docs/resolutions/20260912_resolucion_modelo_direccion_tecnica_y_
ejecucion_claude.md and CLAUDE.md define the execution model this runner
implements. This slice (RUNNER-1B-READONLY-IMPLEMENTATION) is read-only
only: it never edits, commits, pushes, merges, creates branches, or resumes
a prior session. Write-capable execution requires separate authorization.

CLI invocation shape: the flags used below were verified directly against
the actually installed Claude CLI (`claude --version` -> 2.1.272) via
`claude --help` and live probe invocations, because no prior RUNNER-1A
discovery artifact exists anywhere in this repository's history or
branches. No flag is invented; every flag passed to the CLI is one that
`claude --help` documents on the installed build.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


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


# Exit code 2 is reserved for argparse's own usage-error path (malformed
# CLI invocation of the runner itself, e.g. a missing required argument or
# an invalid --timeout-seconds) and is never assigned here, so it never
# collides with one of the states below.
EXIT_CODES = {
    RunState.SUCCESS: 0,
    RunState.CLAUDE_ERROR: 3,
    RunState.TIMEOUT: 4,
    RunState.INTERRUPTED: 5,
    RunState.INVALID_REPOSITORY: 10,
    RunState.INVALID_WORK_ORDER: 11,
    RunState.FAILED_SAFETY: 20,
}

DEFAULT_TIMEOUT_SECONDS = 900
MAX_WORK_ORDER_CHARS = 200_000
RUNTIME_SUBDIR = Path("runtime") / "claude_runner" / "runs"

# Explicit read-only tool allowlist: no Bash/PowerShell/Edit/Write/
# NotebookEdit/WebFetch/Task, so the model has no mechanism to mutate the
# repository even if instructed to. Combined with --restricted (defense
# in depth: also strips code-running tools and ignores project-level
# .claude settings/hooks that could otherwise run arbitrary commands) and
# --permission-prompts none (anything that would still need approval is
# auto-denied rather than hanging a non-interactive run).
READ_ONLY_TOOLS = "Read,Grep,Glob"


class RunnerError(Exception):
    """Raised for pre-invocation validation failures with a known RunState."""

    def __init__(self, state: RunState, message: str):
        super().__init__(message)
        self.state = state
        self.message = message


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
    status_result = _run_git(repo, "status", "--porcelain=v1", "--branch")

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
    exe = shutil.which("claude")
    if not exe:
        raise RunnerError(RunState.CLAUDE_ERROR, "claude CLI executable not found on PATH")
    return exe


def get_claude_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=30
        )
        return (result.stdout.strip() or result.stderr.strip()) or "<empty>"
    except Exception as exc:  # pragma: no cover - defensive, environment-dependent
        return f"<unavailable: {exc}>"


# ---------------------------------------------------------------------------
# CLI command construction and invocation
# ---------------------------------------------------------------------------

def build_cli_command(claude_executable: str, model: Optional[str] = None) -> list:
    cmd = [
        claude_executable,
        "--print",
        "--output-format", "json",
        "--tools", READ_ONLY_TOOLS,
        "--restricted",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]
    return cmd


@dataclass
class ProcessOutcome:
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    interrupted: bool
    duration_seconds: float


def invoke_claude(cmd: list, cwd: Path, prompt_text: str, timeout_seconds: int) -> ProcessOutcome:
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout_seconds)
        return ProcessOutcome(
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            interrupted=False,
            duration_seconds=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return ProcessOutcome(
            returncode=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=True,
            interrupted=False,
            duration_seconds=time.monotonic() - start,
        )
    except KeyboardInterrupt:
        proc.kill()
        stdout, stderr = proc.communicate()
        return ProcessOutcome(
            returncode=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=False,
            interrupted=True,
            duration_seconds=time.monotonic() - start,
        )


def parse_cli_result(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        return {"parsed": False, "reason": "empty stdout"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "parsed": False,
            "reason": f"stdout is not valid JSON: {exc}",
            "raw_excerpt": text[:2000],
        }
    return {"parsed": True, "cli_result": data}


def classify_state(outcome: ProcessOutcome, safety: SafetyCheck, parsed_result: dict) -> RunState:
    # Safety takes priority over everything else: a read-only run that
    # mutated the repository is never SUCCESS, even if the CLI itself
    # reported success.
    if safety.repository_mutated:
        return RunState.FAILED_SAFETY
    if outcome.timed_out:
        return RunState.TIMEOUT
    if outcome.interrupted:
        return RunState.INTERRUPTED
    if outcome.returncode != 0:
        return RunState.CLAUDE_ERROR
    if parsed_result.get("parsed") and parsed_result["cli_result"].get("is_error"):
        return RunState.CLAUDE_ERROR
    return RunState.SUCCESS


# ---------------------------------------------------------------------------
# Run directory / evidence
# ---------------------------------------------------------------------------

def create_run_dir(repo: Path, run_root_arg: Optional[str], label: Optional[str]) -> Path:
    if run_root_arg:
        base = Path(run_root_arg).resolve()
    else:
        base = repo / RUNTIME_SUBDIR
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    name_parts = [timestamp, suffix]
    if label:
        safe_label = "".join(c if (c.isalnum() or c in "-_") else "_" for c in label)[:40]
        if safe_label:
            name_parts.append(safe_label)
    run_dir = base / "_".join(name_parts)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _base_metadata(
    *,
    run_dir: Path,
    repo: Path,
    args: argparse.Namespace,
    git_before: GitSnapshot,
    git_after: GitSnapshot,
    claude_executable: Optional[str],
    run_started_at: datetime,
    run_ended_at: datetime,
    duration_seconds: float,
    cli_command: Optional[list],
    process_returncode: Optional[int],
    timed_out: bool,
    interrupted: bool,
    state: RunState,
) -> dict:
    return {
        "run_id": run_dir.name,
        "started_at_utc": run_started_at.isoformat(),
        "ended_at_utc": run_ended_at.isoformat(),
        "duration_seconds": duration_seconds,
        "repository": {
            "requested_path": args.repo,
            "resolved_path": str(repo),
            "branch_before": git_before.branch,
            "head_before": git_before.head,
            "branch_after": git_after.branch,
            "head_after": git_after.head,
        },
        "work_order_path": args.work_order,
        "timeout_seconds": args.timeout_seconds,
        "model": args.model,
        "cli_command": cli_command,
        "claude_cli_version": get_claude_version(claude_executable) if claude_executable else None,
        "python_version": sys.version,
        "platform": platform.platform(),
        "process_returncode": process_returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "state": state.value,
        "exit_code": EXIT_CODES[state],
        "scope": "READ_ONLY_V1",
    }


def _write_pre_invocation_failure_evidence(
    *,
    run_dir: Path,
    repo: Path,
    args: argparse.Namespace,
    exc: RunnerError,
    git_before: GitSnapshot,
    git_after: GitSnapshot,
    claude_executable: Optional[str],
    run_started_at: datetime,
) -> None:
    (run_dir / "prompt.txt").write_text(
        "<not available: repository/Work Order validation failed before invocation>\n",
        encoding="utf-8",
    )
    (run_dir / "stdout.txt").write_text("", encoding="utf-8")
    (run_dir / "stderr.txt").write_text("", encoding="utf-8")
    (run_dir / "git_before.txt").write_text(git_before.raw_text, encoding="utf-8")
    (run_dir / "git_after.txt").write_text(git_after.raw_text, encoding="utf-8")

    run_ended_at = datetime.now(timezone.utc)
    metadata = _base_metadata(
        run_dir=run_dir,
        repo=repo,
        args=args,
        git_before=git_before,
        git_after=git_after,
        claude_executable=claude_executable,
        run_started_at=run_started_at,
        run_ended_at=run_ended_at,
        duration_seconds=0.0,
        cli_command=None,
        process_returncode=None,
        timed_out=False,
        interrupted=False,
        state=exc.state,
    )
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result_payload = {
        "state": exc.state.value,
        "error": exc.message,
        "cli_output": {"parsed": False, "reason": "Claude CLI was not invoked"},
        "safety_check": None,
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
            "Governed read-only Claude Runner V1 core. Executes exactly one "
            "Work Order in one fresh, non-interactive, read-only-constrained "
            "Claude CLI invocation against an explicit Git repository/"
            "worktree and captures auditable evidence. Write-capable "
            "execution is out of scope for this slice."
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


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    run_started_at = datetime.now(timezone.utc)

    try:
        repo = validate_repository_path(args.repo)
    except RunnerError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_CODES[exc.state]

    try:
        claude_executable = get_claude_executable()
    except RunnerError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_CODES[exc.state]

    try:
        validate_git_worktree(repo)
    except RunnerError as exc:
        run_dir = create_run_dir(repo, args.run_root, args.label)
        git_snap = capture_git_snapshot(repo)
        _write_pre_invocation_failure_evidence(
            run_dir=run_dir, repo=repo, args=args, exc=exc,
            git_before=git_snap, git_after=git_snap,
            claude_executable=claude_executable, run_started_at=run_started_at,
        )
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"evidence_dir={run_dir}", file=sys.stderr)
        return EXIT_CODES[exc.state]

    git_before = capture_git_snapshot(repo)

    try:
        work_order_path, prompt_text = validate_work_order(args.work_order)
    except RunnerError as exc:
        git_after = capture_git_snapshot(repo)
        run_dir = create_run_dir(repo, args.run_root, args.label)
        _write_pre_invocation_failure_evidence(
            run_dir=run_dir, repo=repo, args=args, exc=exc,
            git_before=git_before, git_after=git_after,
            claude_executable=claude_executable, run_started_at=run_started_at,
        )
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"evidence_dir={run_dir}", file=sys.stderr)
        return EXIT_CODES[exc.state]

    # Nothing below writes into the repository until AFTER git_after is
    # captured: the safety window must cover only what the invoked Claude
    # CLI process itself did, never the runner's own evidence bookkeeping.
    cmd = build_cli_command(claude_executable, model=args.model)
    outcome = invoke_claude(cmd, cwd=repo, prompt_text=prompt_text, timeout_seconds=args.timeout_seconds)

    git_after = capture_git_snapshot(repo)

    safety = compare_git_snapshots(git_before, git_after)
    parsed_result = parse_cli_result(outcome.stdout)
    state = classify_state(outcome, safety, parsed_result)
    run_ended_at = datetime.now(timezone.utc)

    run_dir = create_run_dir(repo, args.run_root, args.label)
    (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    (run_dir / "stdout.txt").write_text(outcome.stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(outcome.stderr, encoding="utf-8")
    (run_dir / "git_before.txt").write_text(git_before.raw_text, encoding="utf-8")
    (run_dir / "git_after.txt").write_text(git_after.raw_text, encoding="utf-8")

    metadata = _base_metadata(
        run_dir=run_dir,
        repo=repo,
        args=args,
        git_before=git_before,
        git_after=git_after,
        claude_executable=claude_executable,
        run_started_at=run_started_at,
        run_ended_at=run_ended_at,
        duration_seconds=outcome.duration_seconds,
        cli_command=cmd,
        process_returncode=outcome.returncode,
        timed_out=outcome.timed_out,
        interrupted=outcome.interrupted,
        state=state,
    )
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result_payload = {
        "state": state.value,
        "cli_output": parsed_result,
        "safety_check": {
            "repository_mutated": safety.repository_mutated,
            "branch_changed": safety.branch_changed,
            "head_changed": safety.head_changed,
            "status_changed": safety.status_changed,
            "notes": safety.notes,
        },
    }
    (run_dir / "result.json").write_text(
        json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"run_id={run_dir.name} state={state.value} exit_code={EXIT_CODES[state]}")
    print(f"evidence_dir={run_dir}")
    return EXIT_CODES[state]


if __name__ == "__main__":
    sys.exit(main())

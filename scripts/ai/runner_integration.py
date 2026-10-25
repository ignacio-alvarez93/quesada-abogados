"""FCP-1B-CORE: read-only canonical-base and integration-candidate assessment.

Answers ONE question, without changing anything: "is this governed feature
worktree a plausible candidate for integration into the canonical base, and
if not, why not?" It never fetches, merges, rebases, resets, checks out,
commits, pushes or refreshes a ref, and it never decides integration on its
own: the best possible outcome is ELIGIBLE_PENDING_APPROVAL, which still
requires an explicit human approval and a future promotion stage (FCP-3)
that must revalidate everything recorded here.

Canonical base
--------------
The integration branch is `develop` on remote `origin`, addressed ONLY by
its fully-qualified tracking ref `refs/remotes/origin/develop` - abbreviated
names are never resolved. A local tracking ref proves nothing about the
remote's current state (nothing here fetches), so the base is VERIFIED only
when the HOST supplies an attested commit SHA for the remote branch and it
equals the local tracking ref exactly. The local `refs/heads/develop` is
reported for information only and is never an authority. An optional
expected remote URL must equal `remote.origin.url` byte for byte, with no
`url.<base>.insteadOf` rewrite applying to it.

Candidate
---------
`inspect_candidate` holds the SAME per-worktree write lease Runner's
pipeline uses (`runner_pipeline.DirLease` over `worktree_lease_dir`, same
`lease_root` semantics), non-blocking, for the whole inspection, and
releases it in `finally`; it is never a second ownership system. Inside the
lease it captures an initial snapshot, collects identity/status/topology/
relation facts, captures a final snapshot and reports any drift.

Git access
----------
Every git process is started through `runner_git.run` (hooks, fsmonitor,
external diff/textconv and content filters are neutralized or refused
there), with `--no-replace-objects` on every call and an environment that
disables optional index locks/refreshes, replace objects, lazy fetching and
terminal prompts, and drops variables that would redirect git to another
repository. Only an explicit allowlist of read-only subcommands is ever
issued (see `_READ_SUBCOMMANDS`). Unknown, contradictory or failed reads
fail closed.

Classification
--------------
`classify_integration` is a pure function with a fixed precedence (see
`CLASSIFICATION_PRECEDENCE`). Path overlap is a conservative, path-level
signal only - it is NOT semantic conflict detection or resolution. The
assessment fingerprint is a deterministic digest of trusted, canonical
fields; it is not an authorization token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

try:
    from scripts.ai import claude_multiworker as mw
    from scripts.ai import claude_runner
    from scripts.ai import runner_factory_ledger as flog
    from scripts.ai import runner_git
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_multiworker as mw  # type: ignore[no-redef]
    import claude_runner  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]
    import runner_git  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]


INTEGRATION_REMOTE = "origin"
INTEGRATION_BRANCH = "develop"
TRACKING_REF = f"refs/remotes/{INTEGRATION_REMOTE}/{INTEGRATION_BRANCH}"
LOCAL_BRANCH_REF = f"refs/heads/{INTEGRATION_BRANCH}"
FINGERPRINT_SCHEMA = "fcp1b-integration-assessment-v1"

# Canonical base statuses. Only BASE_VERIFIED is verified.
BASE_VERIFIED = "BASE_VERIFIED"
BASE_UNREADABLE = "BASE_UNREADABLE"
BASE_UNSAFE_REPOSITORY = "BASE_UNSAFE_REPOSITORY"
BASE_MISSING = "BASE_MISSING"
BASE_AMBIGUOUS = "BASE_AMBIGUOUS"
BASE_REMOTE_URL_MISMATCH = "BASE_REMOTE_URL_MISMATCH"
BASE_UNATTESTED = "BASE_UNATTESTED"
BASE_INVALID_ATTESTATION = "BASE_INVALID_ATTESTATION"
BASE_STALE = "BASE_STALE"
BASE_MISMATCHED = "BASE_MISMATCHED"

# Informational relation of the local integration branch to the tracking ref.
RELATION_EQUAL = "EQUAL"
RELATION_AHEAD = "AHEAD"
RELATION_BEHIND = "BEHIND"
RELATION_DIVERGED = "DIVERGED"
RELATION_MISSING = "MISSING"
RELATION_UNKNOWN = "UNKNOWN"

# Evidence binding statuses.
EVIDENCE_BOUND = "BOUND"
EVIDENCE_MISSING_STATUS = "MISSING"
EVIDENCE_INVALID = "INVALID"
EVIDENCE_STALE = "STALE"

# The existing Director contract (fabric_director._classify_decision) that a
# bound evidence record must carry: a host-audit-ready, SAFE, complete run.
EVIDENCE_REQUIRED_DECISION_CODE = "READY_FOR_HOST_AUDIT"
EVIDENCE_REQUIRED_SAFETY_VERDICT = "SAFE"

UNSAFE_WORKTREE = "UNSAFE_WORKTREE"
OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
DIRTY_WORKTREE = "DIRTY_WORKTREE"
BASE_UNVERIFIED = "BASE_UNVERIFIED"
DRIFT_DURING_ASSESSMENT = "DRIFT_DURING_ASSESSMENT"
UNAUTHORIZED_CHANGED_PATHS = "UNAUTHORIZED_CHANGED_PATHS"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
NOTHING_TO_INTEGRATE = "NOTHING_TO_INTEGRATE"
NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
STALE_BASE = "STALE_BASE"
ELIGIBLE_PENDING_APPROVAL = "ELIGIBLE_PENDING_APPROVAL"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

CLASSIFICATION_PRECEDENCE = (
    UNSAFE_WORKTREE,
    OWNERSHIP_CONFLICT,
    DIRTY_WORKTREE,
    BASE_UNVERIFIED,
    DRIFT_DURING_ASSESSMENT,
    UNAUTHORIZED_CHANGED_PATHS,
    EVIDENCE_MISSING,
    NOTHING_TO_INTEGRATE,
    NEEDS_RECONCILIATION,
    STALE_BASE,
    ELIGIBLE_PENDING_APPROVAL,
    REVIEW_REQUIRED,
)

# The only git subcommands this module ever issues (runner_git's own filter
# preflight additionally runs config/ls-files/check-attr). None of them
# talks to a remote or writes refs, the index or the working tree.
# `ls-files` (FCP-4D-02) is read by runner_worktree_retirement as `-v -z`.
_READ_SUBCOMMANDS = frozenset({
    "rev-parse", "for-each-ref", "symbolic-ref", "config", "cat-file",
    "merge-base", "rev-list", "diff", "status", "worktree", "ls-files",
})
_WORKTREE_READ_ACTIONS = frozenset({"list"})

# Variables that would make git operate on a different repository, index,
# object store or replace/graft/shallow source than the one inspected.
_REDIRECTING_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
    "GIT_REPLACE_REF_BASE", "GIT_GRAFT_FILE", "GIT_SHALLOW_FILE", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
)
_HARDENED_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",       # status never refreshes/rewrites the index
    "GIT_NO_REPLACE_OBJECTS": "1",   # belt and braces with --no-replace-objects
    "GIT_NO_LAZY_FETCH": "1",        # partial clones never fetch missing objects
    "GIT_TERMINAL_PROMPT": "0",
}

_SHA_PATTERNS = {"sha1": re.compile(r"[0-9a-f]{40}"), "sha256": re.compile(r"[0-9a-f]{64}")}


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalBase:
    """Read-only resolution of the canonical integration base. `verified`
    is True only for BASE_VERIFIED: the host-attested remote SHA equals the
    local fully-qualified tracking ref."""

    status: str
    verified: bool
    reason_codes: tuple = ()
    remote: str = INTEGRATION_REMOTE
    branch: str = INTEGRATION_BRANCH
    tracking_ref: str = TRACKING_REF
    tracking_sha: Optional[str] = None
    attested_sha: Optional[str] = None
    object_format: Optional[str] = None
    repository_top: Optional[str] = None
    common_dir: Optional[str] = None
    remote_url: Optional[str] = None
    expected_remote_url: Optional[str] = None
    remote_url_matches: Optional[bool] = None
    ambiguous_refs: tuple = ()
    # Informational only - never an authority for the base.
    local_branch_ref: str = LOCAL_BRANCH_REF
    local_branch_sha: Optional[str] = None
    local_branch_relation: str = RELATION_UNKNOWN
    read_errors: tuple = ()


@dataclass(frozen=True)
class IntegrationCandidate:
    """Read-only facts about one candidate worktree, collected under the
    Runner worktree lease. Changed paths are `(status, path)` pairs from a
    rename-free diff, so a rename is always a `D` old path plus an `A` new
    path."""

    requested_path: str
    worktree_top: Optional[str] = None
    worktree_key: Optional[str] = None
    git_dir: Optional[str] = None
    common_dir: Optional[str] = None
    object_format: Optional[str] = None
    head_ref: Optional[str] = None
    branch: Optional[str] = None
    head_sha: Optional[str] = None
    detached: Optional[bool] = None
    protected_branch: Optional[bool] = None
    clean: Optional[bool] = None
    staged_paths: tuple = ()
    unstaged_paths: tuple = ()
    untracked_paths: tuple = ()
    unmerged_paths: tuple = ()
    shallow: Optional[bool] = None
    grafts_present: Optional[bool] = None
    replace_refs: tuple = ()
    partial_clone: Optional[bool] = None
    duplicate_checkouts: tuple = ()
    lease_dir: Optional[str] = None
    lease_acquired: bool = False
    lease_holder: tuple = ()
    lease_error: Optional[str] = None
    ledger_checked: bool = False
    ledger_error: Optional[str] = None
    active_workers: tuple = ()
    base_tracking_sha: Optional[str] = None
    merge_bases: tuple = ()
    ahead: Optional[int] = None
    behind: Optional[int] = None
    changed_paths: tuple = ()
    base_changed_paths: tuple = ()
    overlapping_paths: tuple = ()
    authorized_scopes: tuple = ()
    scope_error: Optional[str] = None
    authorized_changed_paths: tuple = ()
    unauthorized_changed_paths: tuple = ()
    drift_reasons: tuple = ()
    read_errors: tuple = ()


@dataclass(frozen=True)
class EvidenceBinding:
    """Whether host-supplied structured run evidence binds to EXACTLY this
    candidate (same HEAD commit, branch ref and - if given - worktree) and
    records a host-audit-ready, SAFE, complete run."""

    status: str
    reason_codes: tuple = ()
    run_id: Optional[str] = None
    decision_code: Optional[str] = None
    safety_verdict: Optional[str] = None
    evidence_complete: Optional[bool] = None
    head_sha: Optional[str] = None
    branch_ref: Optional[str] = None
    worktree_key: Optional[str] = None


@dataclass(frozen=True)
class IntegrationAssessment:
    """Outcome of `classify_integration`. `eligible` is True only for
    ELIGIBLE_PENDING_APPROVAL and `human_approval_required` is always True.
    `fingerprint` identifies the assessed inputs; it authorizes nothing and
    any promotion stage must revalidate them."""

    classification: str
    eligible: bool
    human_approval_required: bool
    reason_codes: tuple
    fingerprint: str
    base: CanonicalBase
    candidate: IntegrationCandidate
    evidence: EvidenceBinding


# ---------------------------------------------------------------------------
# Governed read-only git access
# ---------------------------------------------------------------------------

class _GitReadError(Exception):
    def __init__(self, what: str, detail: str):
        super().__init__(f"{what}: {detail}" if detail else what)
        self.what = what


def _git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECTING_ENV}
    env.update(_HARDENED_ENV)
    return env


def _decode(raw) -> str:
    return raw.decode("utf-8", "surrogateescape") if isinstance(raw, bytes) else (raw or "")


def _git(repo, *args, ok=(0,)):
    """One governed, read-only git call. Returns (returncode, stdout).
    Raises _GitReadError for an exit code outside `ok` or a spawn failure."""
    if not args or args[0] not in _READ_SUBCOMMANDS:
        raise ValueError(f"runner_integration never issues git {args[:1]!r}")
    if args[0] == "worktree" and (len(args) < 2 or args[1] not in _WORKTREE_READ_ACTIONS):
        raise ValueError(f"runner_integration never issues git worktree {args[1:2]!r}")
    what = "git " + " ".join(args[:2])
    try:
        result = runner_git.run(
            repo, ["--no-replace-objects", *args], capture_output=True, env=_git_env(),
        )
    except (OSError, ValueError) as exc:
        raise _GitReadError(what, str(exc))
    if result.returncode not in ok:
        raise _GitReadError(what, f"exit {result.returncode}: {_decode(result.stderr).strip()}")
    return result.returncode, _decode(result.stdout)


def _is_sha(value, object_format: Optional[str]) -> bool:
    pattern = _SHA_PATTERNS.get(object_format or "")
    return isinstance(value, str) and pattern is not None and pattern.fullmatch(value) is not None


def _repo_identity(repo) -> dict:
    _, out = _git(
        repo, "rev-parse", "--path-format=absolute", "--show-toplevel", "--absolute-git-dir",
        "--git-common-dir", "--is-inside-work-tree", "--is-bare-repository",
        "--is-shallow-repository", "--show-object-format",
    )
    lines = out.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != 7:
        raise _GitReadError("git rev-parse", "unexpected repository identity output")
    top, git_dir, common_dir, inside, bare, shallow, fmt = lines
    if inside != "true" or bare != "false":
        raise _GitReadError("git rev-parse", "not a non-bare working tree")
    if shallow not in ("true", "false") or fmt not in _SHA_PATTERNS:
        raise _GitReadError("git rev-parse", "unrecognized shallow flag or object format")
    return {
        "top": str(Path(top).resolve()),
        "git_dir": str(Path(git_dir).resolve()),
        "common_dir": str(Path(common_dir).resolve()),
        "shallow": shallow == "true",
        "object_format": fmt,
    }


def _list_refs(repo) -> dict:
    """{refname: (objectname, objecttype, symref)} for every ref. Matching is
    done here on exact fully-qualified names, never through git's pattern or
    abbreviation rules."""
    _, out = _git(repo, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)")
    refs = {}
    for line in out.split("\n"):
        if not line:
            continue
        fields = line.split("\0")
        if len(fields) != 4:
            raise _GitReadError("git for-each-ref", "unexpected ref listing format")
        refs[fields[0]] = (fields[1], fields[2], fields[3])
    return refs


def _config_values(repo, pattern: str) -> list:
    """[(key, value)] for every effective config entry whose canonical key
    matches `pattern`; [] when none."""
    code, out = _git(repo, "config", "-z", "--get-regexp", pattern, ok=(0, 1))
    if code == 1:
        return []
    entries = []
    for entry in out.split("\0"):
        if entry:
            key, sep, value = entry.partition("\n")
            entries.append((key, value if sep else "true"))
    return entries


def _partial_clone(repo) -> bool:
    for key, value in _config_values(repo, r"^(extensions\.partialclone|remote\..*\.promisor)$"):
        if key == "extensions.partialclone" or value.strip().lower() not in ("false", "no", "off", "0", ""):
            return True
    return False


def _grafts_present(identity: dict) -> bool:
    return any((Path(identity[d]) / "info" / "grafts").exists() for d in ("git_dir", "common_dir"))


def _rev_count(repo, left: str, right: str) -> tuple:
    """(left-only, right-only) commit counts for `left...right`."""
    _, out = _git(repo, "rev-list", "--left-right", "--count", f"{left}...{right}", "--")
    parts = out.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise _GitReadError("git rev-list", "unexpected count output")
    return int(parts[0]), int(parts[1])


def _merge_bases(repo, a: str, b: str, object_format: str) -> tuple:
    code, out = _git(repo, "merge-base", "--all", a, b, ok=(0, 1))
    bases = tuple(sorted(line for line in out.split() if line))
    if code == 1 and bases:
        raise _GitReadError("git merge-base", "contradictory exit status")
    if not all(_is_sha(s, object_format) for s in bases):
        raise _GitReadError("git merge-base", "unexpected merge-base output")
    return bases


def _changed_paths(repo, old: str, new: str) -> tuple:
    """Sorted (status, path) pairs between two commits. --no-renames makes a
    rename a deletion plus an addition, so both paths are scope-checked."""
    _, out = _git(
        repo, "diff", "--name-status", "-z", "--no-renames", "--no-relative", "--ignore-submodules=none",
        old, new, "--",
    )
    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise _GitReadError("git diff", "unexpected name-status output")
    pairs = {(fields[i + 1], fields[i]) for i in range(0, len(fields), 2)}
    return tuple((status, path) for path, status in sorted(pairs))


def _relation(ahead_only: int, behind_only: int) -> str:
    if ahead_only and behind_only:
        return RELATION_DIVERGED
    if ahead_only:
        return RELATION_AHEAD
    if behind_only:
        return RELATION_BEHIND
    return RELATION_EQUAL


# ---------------------------------------------------------------------------
# Canonical base
# ---------------------------------------------------------------------------

# Every ref git would consider for the short name "origin/develop"
# (gitrevisions(7) rule order), besides the tracking ref itself.
_SHORT_NAME = f"{INTEGRATION_REMOTE}/{INTEGRATION_BRANCH}"
_SHORT_NAME_COMPETITORS = (
    f"refs/{_SHORT_NAME}", f"refs/tags/{_SHORT_NAME}", f"refs/heads/{_SHORT_NAME}",
    f"refs/remotes/{_SHORT_NAME}/HEAD",
)


def resolve_canonical_base(
    repo, *, attested_sha: Optional[str], expected_remote_url: Optional[str] = None,
) -> CanonicalBase:
    """Resolves the canonical base from local refs only - never fetches or
    refreshes anything. `attested_sha` is the host-attested commit of the
    remote `develop`; without it the base can never be VERIFIED."""
    fields = {"attested_sha": attested_sha if isinstance(attested_sha, str) else None,
              "expected_remote_url": expected_remote_url}
    try:
        identity = _repo_identity(repo)
        fields.update(repository_top=identity["top"], common_dir=identity["common_dir"],
                      object_format=identity["object_format"])
        fmt = identity["object_format"]
        if identity["shallow"] or _grafts_present(identity) or _partial_clone(repo):
            return CanonicalBase(status=BASE_UNSAFE_REPOSITORY, verified=False,
                                 reason_codes=(BASE_UNSAFE_REPOSITORY,), **fields)
        refs = _list_refs(repo)
        if any(name.startswith("refs/replace/") for name in refs):
            return CanonicalBase(status=BASE_UNSAFE_REPOSITORY, verified=False,
                                 reason_codes=(BASE_UNSAFE_REPOSITORY,), **fields)

        reasons = []
        tracking = refs.get(TRACKING_REF)
        tracking_sha = None
        if tracking is None:
            reasons.append(BASE_MISSING)
        elif tracking[2] or tracking[1] != "commit" or not _is_sha(tracking[0], fmt):
            # A symbolic or non-commit tracking ref is contradictory.
            reasons.append(BASE_AMBIGUOUS)
        else:
            tracking_sha = tracking[0]
        fields["tracking_sha"] = tracking_sha

        ambiguous = [name for name in _SHORT_NAME_COMPETITORS if name in refs]
        for root in {identity["git_dir"], identity["common_dir"]}:
            if (Path(root) / INTEGRATION_REMOTE / INTEGRATION_BRANCH).exists():
                ambiguous.append(f"$GIT_DIR/{_SHORT_NAME}")
        fields["ambiguous_refs"] = tuple(sorted(set(ambiguous)))
        if ambiguous and BASE_AMBIGUOUS not in reasons:
            reasons.append(BASE_AMBIGUOUS)

        urls = [v for _, v in _config_values(repo, rf"^remote\.{INTEGRATION_REMOTE}\.url$")]
        if len(urls) > 1:
            fields["remote_url"] = None
            reasons.append(BASE_AMBIGUOUS)
        else:
            fields["remote_url"] = urls[0] if urls else None
        if expected_remote_url is not None:
            url = fields["remote_url"]
            rewritten = url is not None and any(
                url.startswith(prefix)
                for key, prefix in _config_values(repo, r"^url\..*\.insteadof$") if prefix
            )
            matches = url is not None and not rewritten and url == expected_remote_url
            fields["remote_url_matches"] = matches
            if not matches:
                reasons.append(BASE_REMOTE_URL_MISMATCH)

        local = refs.get(LOCAL_BRANCH_REF)
        if local is None:
            fields["local_branch_relation"] = RELATION_MISSING
        elif _is_sha(local[0], fmt) and local[1] == "commit" and not local[2]:
            fields["local_branch_sha"] = local[0]
            if tracking_sha:
                fields["local_branch_relation"] = _relation(*_rev_count(repo, local[0], tracking_sha))

        if attested_sha is None:
            reasons.append(BASE_UNATTESTED)
        elif not _is_sha(attested_sha, fmt):
            reasons.append(BASE_INVALID_ATTESTATION)
        elif tracking_sha and attested_sha != tracking_sha:
            code, out = _git(repo, "cat-file", "-t", attested_sha, ok=(0, 1, 128))
            stale = False
            if code == 0 and out.strip() == "commit":
                code, _ = _git(repo, "merge-base", "--is-ancestor", tracking_sha, attested_sha, ok=(0, 1))
                stale = code == 0
            reasons.append(BASE_STALE if stale else BASE_MISMATCHED)
    except _GitReadError as exc:
        return CanonicalBase(status=BASE_UNREADABLE, verified=False, reason_codes=(BASE_UNREADABLE,),
                             read_errors=(str(exc),), **fields)

    status = reasons[0] if reasons else BASE_VERIFIED
    return CanonicalBase(status=status, verified=not reasons, reason_codes=tuple(dict.fromkeys(reasons)), **fields)


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Snapshot:
    head_ref: Optional[str]
    head_sha: Optional[str]
    refs: tuple
    status: str
    shallow: bool
    grafts: bool


def _head(repo, object_format: str) -> tuple:
    code, out = _git(repo, "symbolic-ref", "-q", "HEAD", ok=(0, 1))
    head_ref = out.strip() if code == 0 else None
    if head_ref is not None and not head_ref.startswith("refs/heads/"):
        raise _GitReadError("git symbolic-ref", f"HEAD points outside refs/heads/: {head_ref!r}")
    code, out = _git(repo, "rev-parse", "-q", "--verify", "HEAD^{commit}", ok=(0, 1))
    head_sha = out.strip() if code == 0 else None
    if head_sha is not None and not _is_sha(head_sha, object_format):
        raise _GitReadError("git rev-parse", "unexpected HEAD output")
    return head_ref, head_sha


def _status(repo) -> str:
    # Same porcelain shape as claude_runner.capture_git_snapshot, so its
    # parse/dirty-tree helpers apply unchanged.
    _, out = _git(repo, "status", "--porcelain=v1", "--branch", "--untracked-files=all", "--ignore-submodules=none")
    return out


def _snapshot(repo, identity: dict) -> _Snapshot:
    head_ref, head_sha = _head(repo, identity["object_format"])
    watched = {TRACKING_REF, LOCAL_BRANCH_REF, head_ref}
    refs = _list_refs(repo)
    relevant = tuple(sorted(
        (name, value) for name, value in refs.items() if name in watched or name.startswith("refs/replace/")
    ))
    shallow = _repo_identity(repo)["shallow"]
    return _Snapshot(head_ref, head_sha, relevant, _status(repo), shallow, _grafts_present(identity))


def _drift(initial: _Snapshot, final: _Snapshot, base_sha: Optional[str]) -> tuple:
    reasons = []
    if (initial.head_ref, initial.head_sha) != (final.head_ref, final.head_sha):
        reasons.append("HEAD_DRIFT")
    tracking = lambda snap: dict(snap.refs).get(TRACKING_REF, (None,))[0]  # noqa: E731
    if tracking(initial) != base_sha or tracking(final) != base_sha:
        reasons.append("BASE_REF_DRIFT")
    if initial.refs != final.refs:
        reasons.append("REF_DRIFT")
    if initial.status != final.status:
        reasons.append("STATUS_DRIFT")
    if (initial.shallow, initial.grafts) != (final.shallow, final.grafts):
        reasons.append("TOPOLOGY_DRIFT")
    return tuple(reasons)


def _worktree_entries(repo) -> list:
    _, out = _git(repo, "worktree", "list", "--porcelain", "-z")
    entries, current = [], {}
    for field in out.split("\0"):
        if field == "":
            if current:
                entries.append(current)
            current = {}
            continue
        key, _, value = field.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    if not entries or any("worktree" not in e for e in entries):
        raise _GitReadError("git worktree list", "unexpected worktree listing")
    return entries


def _status_paths(porcelain: str) -> dict:
    groups = {"staged": set(), "unstaged": set(), "untracked": set(), "unmerged": set()}
    for line in claude_runner.parse_porcelain_lines(porcelain):
        x, y = line[0], line[1]
        paths = claude_runner.extract_paths_from_porcelain_line(line)
        if x == "?" and y == "?":
            groups["untracked"].update(paths)
        elif x == "U" or y == "U" or (x, y) in (("A", "A"), ("D", "D")):
            groups["unmerged"].update(paths)
        else:
            if x not in (" ", "?", "!"):
                groups["staged"].update(paths)
            if y not in (" ", "?", "!"):
                groups["unstaged"].update(paths)
    return {k: tuple(sorted(v)) for k, v in groups.items()}


def _active_workers(ledger_root, worktree_key: str, branch: Optional[str]) -> tuple:
    root = Path(ledger_root)
    if not root.is_dir():
        raise _GitReadError("factory ledger", f"ledger root is not a directory: {root}")
    events, skipped = flog.read_events(root)
    if skipped:
        raise _GitReadError("factory ledger", f"{skipped} unreadable ledger line(s)")
    active = []
    for worker in flog.factory_status(events)["active_workers"]:
        same_worktree = False
        if isinstance(worker.get("worktree"), str) and worker["worktree"].strip():
            try:
                same_worktree = mw.canonical_target_key(worker["worktree"]) == worktree_key
            except mw.MultiworkerError:
                same_worktree = False
        same_branch = branch is not None and worker.get("branch") == branch
        if same_worktree or same_branch:
            active.append((str(worker.get("pipeline_id")), str(worker.get("worker_id"))))
    return tuple(sorted(active))


def _collect_details(repo, identity: dict, base: CanonicalBase, facts: dict, authorized_scopes: tuple) -> None:
    """Fills `facts` with every candidate fact gathered inside the lease.
    Separated from `inspect_candidate` only so tests can inject mid-
    assessment drift."""
    fmt = identity["object_format"]
    head_ref, head_sha = _head(repo, fmt)
    branch = head_ref[len("refs/heads/"):] if head_ref else None
    facts.update(head_ref=head_ref, branch=branch, head_sha=head_sha, detached=head_ref is None)
    guard = claude_runner.evaluate_branch_guard(claude_runner.GitSnapshot(
        branch=branch if branch is not None else "HEAD", head=head_sha or "", porcelain_status="",
        raw_text="", captured_at="",
    ))
    facts["protected_branch"] = guard.decision == "REFUSED_PROTECTED_BRANCH"

    refs = _list_refs(repo)
    if head_ref is not None and head_sha is not None:
        branch_entry = refs.get(head_ref)
        if branch_entry is None or branch_entry[0] != head_sha or branch_entry[2]:
            raise _GitReadError("git for-each-ref", f"{head_ref} does not resolve to HEAD")
    facts["replace_refs"] = tuple(sorted(n for n in refs if n.startswith("refs/replace/")))

    porcelain = _status(repo)
    dirty = claude_runner.evaluate_dirty_tree(claude_runner.GitSnapshot(
        branch=branch or "HEAD", head=head_sha or "", porcelain_status=porcelain, raw_text="", captured_at="",
    ))
    groups = _status_paths(porcelain)
    facts.update(
        clean=dirty.decision == "ALLOWED_CLEAN", staged_paths=groups["staged"],
        unstaged_paths=groups["unstaged"], untracked_paths=groups["untracked"],
        unmerged_paths=groups["unmerged"],
    )

    own_key = facts["worktree_key"]
    registered, duplicates = False, []
    for entry in _worktree_entries(repo):
        key = mw.canonical_target_key(entry["worktree"])
        if key == own_key:
            registered = True
        elif head_ref is not None and entry.get("branch") == head_ref:
            duplicates.append(str(Path(entry["worktree"])))
    if not registered:
        raise _GitReadError("git worktree list", "candidate worktree is not registered")
    facts["duplicate_checkouts"] = tuple(sorted(duplicates))

    hazardous = facts["shallow"] or facts["grafts_present"] or facts["replace_refs"] or facts["partial_clone"]
    base_sha = base.tracking_sha
    facts["base_tracking_sha"] = base_sha
    if hazardous or head_sha is None or not _is_sha(base_sha, fmt):
        # Ancestry is untrustworthy (or, for a partial clone, could trigger
        # object fetches): no relation facts are produced at all.
        return

    merge_bases = _merge_bases(repo, base_sha, head_sha, fmt)
    behind, ahead = _rev_count(repo, base_sha, head_sha)
    if len(merge_bases) == 1:
        changed = _changed_paths(repo, merge_bases[0], head_sha)
        base_changed = _changed_paths(repo, merge_bases[0], base_sha)
        overlap = sorted({p for _, p in changed} & {p for _, p in base_changed})
    else:
        # Unrelated or criss-cross histories: every path that differs is
        # conservatively treated as overlapping.
        changed = _changed_paths(repo, base_sha, head_sha)
        base_changed = ()
        overlap = sorted({p for _, p in changed})
    facts.update(merge_bases=merge_bases, ahead=ahead, behind=behind, changed_paths=changed,
                 base_changed_paths=base_changed, overlapping_paths=tuple(overlap))

    scope = claude_runner.evaluate_write_scope(list(authorized_scopes))
    paths = sorted({p for _, p in changed})
    if scope.decision != "ALLOWED":
        facts["scope_error"] = scope.reason or scope.decision
        facts["unauthorized_changed_paths"] = tuple(paths)
    else:
        facts["authorized_scopes"] = tuple(scope.authorized_scopes)
        facts["authorized_changed_paths"] = tuple(
            p for p in paths if claude_runner.path_is_authorized(p, scope.authorized_scopes))
        facts["unauthorized_changed_paths"] = tuple(
            p for p in paths if not claude_runner.path_is_authorized(p, scope.authorized_scopes))


def inspect_candidate(
    worktree, base: CanonicalBase, *, authorized_scopes, ledger_root=None, lease_root=None,
) -> IntegrationCandidate:
    """Read-only inspection of `worktree` relative to `base`, performed
    entirely under the Runner worktree lease (non-blocking; released in
    `finally`). A busy lease is reported, never waited for."""
    facts: dict = {"requested_path": str(worktree), "authorized_scopes": tuple(authorized_scopes or ())}
    errors = []
    try:
        identity = _repo_identity(worktree)
        # Known before any object is read, so a partial clone is never
        # traversed (see _collect_details).
        facts["partial_clone"] = _partial_clone(worktree)
    except _GitReadError as exc:
        return IntegrationCandidate(read_errors=(str(exc),), **facts)
    top = identity["top"]
    facts.update(
        worktree_top=top, worktree_key=mw.canonical_target_key(top), git_dir=identity["git_dir"],
        common_dir=identity["common_dir"], object_format=identity["object_format"],
        shallow=identity["shallow"], grafts_present=_grafts_present(identity),
    )

    try:
        lease = pipeline.DirLease(pipeline.worktree_lease_dir(Path(top), lease_root))
    except (pipeline.PipelineError, OSError) as exc:
        return IntegrationCandidate(lease_error=str(exc), **facts)
    facts["lease_dir"] = str(lease.directory)
    now = datetime.now(timezone.utc).isoformat()
    try:
        try:
            acquired = lease.try_acquire({
                "pipeline_id": None, "worker_id": None, "purpose": "INTEGRATION_ASSESSMENT",
                "pid": os.getpid(), "hostname": socket.gethostname(), "started_at_utc": now,
                "last_heartbeat_utc": now, "worktree": top,
            })
        except OSError as exc:
            return IntegrationCandidate(lease_error=str(exc), **facts)
        if not acquired:
            holder = lease.holder() or {}
            facts["lease_holder"] = tuple(sorted((str(k), str(v)) for k, v in holder.items()))
            return IntegrationCandidate(**facts)

        facts["lease_acquired"] = True
        try:
            initial = _snapshot(worktree, identity)
            _collect_details(worktree, identity, base, facts, facts["authorized_scopes"])
            if ledger_root is not None:
                try:
                    facts["active_workers"] = _active_workers(ledger_root, facts["worktree_key"], facts.get("branch"))
                except _GitReadError as exc:
                    facts["ledger_error"] = str(exc)
                facts["ledger_checked"] = True
            final = _snapshot(worktree, identity)
            facts["drift_reasons"] = _drift(initial, final, base.tracking_sha)
            if final.head_sha != facts.get("head_sha") or final.head_ref != facts.get("head_ref"):
                facts["drift_reasons"] = tuple(dict.fromkeys(facts["drift_reasons"] + ("HEAD_DRIFT",)))
        except (_GitReadError, mw.MultiworkerError) as exc:
            errors.append(str(exc))
    finally:
        # try_acquire may already hold the OS lock when writing its identity
        # fails, so release covers acquisition too; it is a no-op for a lease
        # that was never acquired (e.g. one held by another owner).
        lease.release()
    return IntegrationCandidate(read_errors=tuple(errors), **facts)


# ---------------------------------------------------------------------------
# Evidence and classification (pure)
# ---------------------------------------------------------------------------

def _bind_evidence(evidence: Optional[Mapping], candidate: IntegrationCandidate) -> EvidenceBinding:
    if evidence is None:
        return EvidenceBinding(status=EVIDENCE_MISSING_STATUS, reason_codes=("EVIDENCE_MISSING",))
    if not isinstance(evidence, Mapping):
        return EvidenceBinding(status=EVIDENCE_INVALID, reason_codes=("EVIDENCE_INVALID",))

    def text(key):
        value = evidence.get(key)
        return value if isinstance(value, str) else None

    complete = evidence.get("evidence_complete")
    fields = dict(
        run_id=text("run_id"), decision_code=text("decision_code"), safety_verdict=text("safety_verdict"),
        evidence_complete=complete if isinstance(complete, bool) else None,
        head_sha=text("head_sha"), branch_ref=text("branch_ref"), worktree_key=None,
    )
    invalid = []
    if not fields["run_id"]:
        invalid.append("EVIDENCE_RUN_ID_INVALID")
    if fields["decision_code"] != EVIDENCE_REQUIRED_DECISION_CODE:
        invalid.append("EVIDENCE_NOT_READY_FOR_HOST_AUDIT")
    if fields["safety_verdict"] != EVIDENCE_REQUIRED_SAFETY_VERDICT:
        invalid.append("EVIDENCE_NOT_SAFE")
    if complete is not True:
        invalid.append("EVIDENCE_INCOMPLETE")
    if not _is_sha(fields["head_sha"], candidate.object_format):
        invalid.append("EVIDENCE_HEAD_INVALID")
    if not (fields["branch_ref"] or "").startswith("refs/heads/"):
        invalid.append("EVIDENCE_BRANCH_REF_INVALID")
    worktree = evidence.get("worktree")
    if worktree is not None:
        try:
            fields["worktree_key"] = mw.canonical_target_key(worktree)
        except mw.MultiworkerError:
            invalid.append("EVIDENCE_WORKTREE_INVALID")
    if invalid:
        return EvidenceBinding(status=EVIDENCE_INVALID, reason_codes=("EVIDENCE_INVALID", *invalid), **fields)

    stale = []
    if fields["head_sha"] != candidate.head_sha:
        stale.append("EVIDENCE_HEAD_MISMATCH")
    if fields["branch_ref"] != candidate.head_ref:
        stale.append("EVIDENCE_BRANCH_MISMATCH")
    if fields["worktree_key"] is not None and fields["worktree_key"] != candidate.worktree_key:
        stale.append("EVIDENCE_WORKTREE_MISMATCH")
    if stale:
        return EvidenceBinding(status=EVIDENCE_STALE, reason_codes=("EVIDENCE_STALE", *stale), **fields)
    return EvidenceBinding(status=EVIDENCE_BOUND, **fields)


def _findings(base: CanonicalBase, c: IntegrationCandidate, evidence: EvidenceBinding) -> dict:
    found = {name: [] for name in CLASSIFICATION_PRECEDENCE}

    unsafe = found[UNSAFE_WORKTREE]
    if c.read_errors or c.worktree_top is None:
        unsafe.append("GIT_READ_FAILED")
    if c.lease_acquired and not c.read_errors:
        if c.head_sha is None:
            unsafe.append("UNBORN_HEAD")
        if c.detached:
            unsafe.append("DETACHED_HEAD")
        if c.protected_branch:
            unsafe.append("PROTECTED_BRANCH")
        if c.replace_refs:
            unsafe.append("REPLACE_REFS_PRESENT")
    if c.partial_clone:
        unsafe.append("PARTIAL_CLONE")
    if c.shallow:
        unsafe.append("SHALLOW_REPOSITORY")
    if c.grafts_present:
        unsafe.append("GRAFTS_PRESENT")

    owner = found[OWNERSHIP_CONFLICT]
    if c.worktree_top is not None and not c.lease_acquired:
        owner.append("LEASE_UNAVAILABLE" if c.lease_error else "WORKTREE_LEASE_HELD")
    if c.duplicate_checkouts:
        owner.append("DUPLICATE_BRANCH_CHECKOUT")
    if c.active_workers:
        owner.append("ACTIVE_WORKER")
    if c.ledger_error:
        owner.append("LEDGER_UNREADABLE")

    dirty = found[DIRTY_WORKTREE]
    if c.staged_paths:
        dirty.append("STAGED_CHANGES")
    if c.unstaged_paths:
        dirty.append("UNSTAGED_CHANGES")
    if c.untracked_paths:
        dirty.append("UNTRACKED_FILES")
    if c.unmerged_paths:
        dirty.append("UNMERGED_PATHS")
    if c.clean is False and not dirty:
        dirty.append("DIRTY_UNCLASSIFIED")

    if not base.verified:
        found[BASE_UNVERIFIED].extend(base.reason_codes or (base.status,))
    if base.common_dir is not None and c.common_dir is not None and base.common_dir != c.common_dir:
        found[BASE_UNVERIFIED].append("BASE_REPOSITORY_MISMATCH")

    drift = found[DRIFT_DURING_ASSESSMENT]
    drift.extend(c.drift_reasons)
    if c.lease_acquired and c.base_tracking_sha != base.tracking_sha:
        drift.append("CANDIDATE_BASE_MISMATCH")

    if c.unauthorized_changed_paths:
        found[UNAUTHORIZED_CHANGED_PATHS].append("UNAUTHORIZED_PATHS")
    if c.scope_error:
        found[UNAUTHORIZED_CHANGED_PATHS].append("SCOPE_INVALID")

    if evidence.status != EVIDENCE_BOUND:
        found[EVIDENCE_MISSING].extend(evidence.reason_codes)

    if c.ahead == 0:
        found[NOTHING_TO_INTEGRATE].append("NO_COMMITS_AHEAD")
    if c.ahead is not None:
        if not c.merge_bases:
            found[NEEDS_RECONCILIATION].append("UNRELATED_HISTORIES")
        elif len(c.merge_bases) > 1:
            found[NEEDS_RECONCILIATION].append("MULTIPLE_MERGE_BASES")
        if c.behind and c.overlapping_paths:
            found[NEEDS_RECONCILIATION].append("OVERLAPPING_CHANGES")
        if c.behind and not found[NEEDS_RECONCILIATION]:
            found[STALE_BASE].append("BASE_ADVANCED")
    return found


def _unproven_safety_facts(base: CanonicalBase, c: IntegrationCandidate) -> tuple:
    """Reason codes for every mandatory safety fact NOT explicitly known to
    hold its safe value. `_findings` only reports facts known to be bad; an
    unknown (None) or contradictory fact is caught here, so it can never
    become positive eligibility."""
    head_known = (
        _is_sha(c.head_sha, c.object_format) and isinstance(c.head_ref, str)
        and c.head_ref.startswith("refs/heads/") and c.detached is False
    )
    checks = (
        ("UNPROVEN_BASE_VERIFIED", base.verified is True and base.status == BASE_VERIFIED),
        ("UNPROVEN_LEASE", c.lease_acquired is True and c.lease_error is None),
        ("UNPROVEN_READS", not c.read_errors and c.worktree_top is not None and c.worktree_key is not None),
        ("UNPROVEN_CLEAN", c.clean is True),
        ("UNPROVEN_HEAD", head_known),
        ("UNPROVEN_UNPROTECTED_BRANCH", c.protected_branch is False),
        ("UNPROVEN_NOT_SHALLOW", c.shallow is False),
        ("UNPROVEN_NO_GRAFTS", c.grafts_present is False),
        ("UNPROVEN_NOT_PARTIAL_CLONE", c.partial_clone is False),
        ("UNPROVEN_CANDIDATE_BASE", c.base_tracking_sha is not None and c.base_tracking_sha == base.tracking_sha),
        ("UNPROVEN_SCOPE", c.scope_error is None and bool(c.authorized_scopes)),
    )
    return tuple(code for code, safe in checks if not safe)


def _fingerprint(base: CanonicalBase, c: IntegrationCandidate, evidence: EvidenceBinding,
                 classification: str, reasons: tuple) -> str:
    payload = {
        "schema": FINGERPRINT_SCHEMA,
        "base": {
            "remote": base.remote, "branch": base.branch, "tracking_ref": base.tracking_ref,
            "tracking_sha": base.tracking_sha, "attested_sha": base.attested_sha, "status": base.status,
            "object_format": base.object_format, "expected_remote_url": base.expected_remote_url,
            "remote_url_matches": base.remote_url_matches,
        },
        "candidate": {
            "worktree_key": c.worktree_key, "head_ref": c.head_ref, "head_sha": c.head_sha,
            "base_tracking_sha": c.base_tracking_sha, "merge_bases": list(c.merge_bases),
            "ahead": c.ahead, "behind": c.behind,
            "changed_paths": [list(p) for p in c.changed_paths],
            "base_changed_paths": [list(p) for p in c.base_changed_paths],
            "overlapping_paths": list(c.overlapping_paths),
            "authorized_scopes": sorted(c.authorized_scopes),
            "unauthorized_changed_paths": list(c.unauthorized_changed_paths),
        },
        "evidence": {"status": evidence.status, "run_id": evidence.run_id, "head_sha": evidence.head_sha,
                     "branch_ref": evidence.branch_ref},
        "classification": classification,
        "reason_codes": list(reasons),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_integration(
    base: CanonicalBase, candidate: IntegrationCandidate, evidence: Optional[Mapping] = None,
) -> IntegrationAssessment:
    """Pure, fail-closed classification with the fixed precedence of
    CLASSIFICATION_PRECEDENCE. `evidence` is host-supplied structured run
    evidence: run_id, decision_code, safety_verdict, evidence_complete,
    head_sha, branch_ref and optionally worktree."""
    binding = _bind_evidence(evidence, candidate)
    found = _findings(base, candidate, binding)
    classification = next((name for name in CLASSIFICATION_PRECEDENCE if found[name]), None)
    if classification is None:
        relation_known = bool(candidate.ahead and candidate.behind == 0 and len(candidate.merge_bases) == 1)
        unproven = _unproven_safety_facts(base, candidate)
        classification = ELIGIBLE_PENDING_APPROVAL if relation_known and not unproven else REVIEW_REQUIRED
        if not relation_known:
            found[REVIEW_REQUIRED].append("UNKNOWN_RELATION")
        found[REVIEW_REQUIRED].extend(unproven)
    reasons = tuple(dict.fromkeys(code for name in CLASSIFICATION_PRECEDENCE for code in found[name]))
    return IntegrationAssessment(
        classification=classification,
        eligible=classification == ELIGIBLE_PENDING_APPROVAL,
        human_approval_required=True,
        reason_codes=reasons,
        fingerprint=_fingerprint(base, candidate, binding, classification, reasons),
        base=base, candidate=candidate, evidence=binding,
    )


def assess_integration(
    worktree, *, attested_sha: Optional[str], authorized_scopes, expected_remote_url: Optional[str] = None,
    evidence: Optional[Mapping] = None, ledger_root=None, lease_root=None,
) -> IntegrationAssessment:
    """Convenience composition of the three read-only steps."""
    base = resolve_canonical_base(worktree, attested_sha=attested_sha, expected_remote_url=expected_remote_url)
    candidate = inspect_candidate(
        worktree, base, authorized_scopes=authorized_scopes, ledger_root=ledger_root, lease_root=lease_root,
    )
    return classify_integration(base, candidate, evidence)

"""FCP-4D-02: read-only worktree retirement ASSESSMENT.

Answers ONE question, without changing anything: "for each registered
worktree, what local evidence argues against retiring it, and is that
evidence complete?" It is NOT retirement, eligibility certification,
authorization or cleanup. It never prunes, removes, moves, locks, unlocks,
checks out, resets, commits, fetches, writes a report or rewrites anything.
Every record and the report carry `human_review_required=True`,
`authorizes_action=False` and `deletion_authorized=False`; the mildest
classification, CANDIDATE_FOR_HUMAN_REVIEW, is ONLY an informational
shortlist for a human - never permission, never an input to cleanup and
never evidence that no remote, promotion or external work exists.

Sources (all reused, none duplicated)
--------------------------------------
* FCP-4C inventory: `runner_worktree_inventory.inventory_worktrees` is
  called exactly twice (before and after the supplemental reads). Records
  are matched by canonical worktree key; a record missing from either
  inventory, or whose inventory fingerprint changed, is
  INSUFFICIENT_EVIDENCE - never omitted. The original inventory
  classification, reason codes and advisories are reused verbatim and can
  only be made stricter, never improved.
* Git: every read goes through `runner_integration._git` (hooks,
  fsmonitor, external diff/textconv and content filters neutralized or
  refused, optional locks disabled, redirecting environment dropped, a
  read-only subcommand allowlist). This module never starts a process.
* Queue: `claude_queue.list_items` over EXPLICITLY declared queue roots
  only - no folder discovery. Whether the declared roots are the complete
  known set is a host claim (`queue_roots_complete`), recorded verbatim; it
  is required for a CANDIDATE but proves nothing about external queues.
* Factory ledger: `runner_factory_ledger.read_events`, with the same
  fail-closed readability rule as the inventory. The SQLite HostLedger is
  never imported (it can write on construction).

Supplemental checks (only for records the inventory found
IDLE_CLEAN_UNBOUND): ignored files (`git status --ignored`, never their
contents; `runtime/claude_runner/**`, `.env*`, `*.db*` and `database/**`
are BLOCKED, any other ignored file REVIEW_REQUIRED, more than
MAX_IGNORED_ENTRIES entries INSUFFICIENT_EVIDENCE), paused Git operations
in the per-worktree Git dir, hidden index flags (`git ls-files -v`:
skip-worktree / assume-unchanged hide changes from status, so cleanliness
of those paths is unproven), worktree-local refs, local-only and unique
commits (only when the topology is trustworthy: no shallow, grafts,
replace refs or partial clone), the self worktree and overlap with any
governed root. Queue items, ledger history and inventory advisories are
matched for every record.

Classification
--------------
`classify_retirement` is pure, with the fixed precedence
BLOCKED > INSUFFICIENT_EVIDENCE > REVIEW_REQUIRED >
CANDIDATE_FOR_HUMAN_REVIEW. `reason_codes` lists every finding in that
order (never dropped), `advisories` non-blocking observations and
`limitations` what one local view can never establish. A CANDIDATE needs
two COMPLETE inventories with identical record fingerprints, every
supplemental fact proven clean, no ignored files, no hidden index flags,
declared queue roots with an explicit completeness claim, and readable
queues and ledger. No branch name, merge state, `ahead == 0`, age or
module closure is ever consulted to upgrade a record.

Known residual limitations
--------------------------
* P1 (inherited, FCP-4C): the inventory lease probe briefly holds the OS
  lock of an existing free `queue.lock` and `claude_queue.QueueLock`
  rewrites its diagnostic bytes (pid/host/timestamp) while doing so. The
  assessment is therefore NOT byte-perfect read-only for such files.
  Nothing else - business data, refs, index, config, `lease.json` - is
  written; a change of the per-worktree index/HEAD observed across the
  supplemental reads fails the record closed (GIT_ADMIN_STATE_CHANGED).
* D3 (deferred): Git subprocesses inherit runner_git's unbounded
  execution (no timeout); a hung Git blocks the assessment. The ignored
  listing is produced by Git in full before it is bounded here, so a huge
  ignored tree costs time and memory (only MAX_IGNORED_ENTRIES paths are
  retained; every path is still screened for sensitive names).
* Point-in-time: anything that starts after the second inventory is not
  seen. Even a declared-complete queue set cannot show that no other
  queue, remote branch, promotion or module closure depends on a worktree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_multiworker as mw
    from scripts.ai import claude_queue as queue
    from scripts.ai import runner_factory_ledger as flog
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_worktree_inventory as inv
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_multiworker as mw  # type: ignore[no-redef]
    import claude_queue as queue  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_worktree_inventory as inv  # type: ignore[no-redef]


SCHEMA = "fcp4d02-worktree-retirement-assessment-v1"

REPORT_COMPLETE = "COMPLETE"
REPORT_FAILED_CLOSED = "FAILED_CLOSED"

BLOCKED = "BLOCKED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
CANDIDATE_FOR_HUMAN_REVIEW = "CANDIDATE_FOR_HUMAN_REVIEW"

CLASSIFICATION_PRECEDENCE = (BLOCKED, INSUFFICIENT_EVIDENCE, REVIEW_REQUIRED, CANDIDATE_FOR_HUMAN_REVIEW)

MAX_IGNORED_ENTRIES = 500

# Inventory classification -> the retirement class it forces. IDLE is
# absent on purpose: it only opens the supplemental assessment.
INVENTORY_MAPPING = {
    inv.UNSAFE: INSUFFICIENT_EVIDENCE,
    inv.RECOVERY_PENDING: BLOCKED,
    inv.ACTIVE_LEASED: BLOCKED,
    inv.ACTIVE_PIPELINE: BLOCKED,
    inv.OWNERSHIP_INCONSISTENT: BLOCKED,
    inv.MISSING_PATH: BLOCKED,
    inv.PROTECTED: BLOCKED,
    inv.GIT_LOCKED: BLOCKED,
    inv.DIRTY: BLOCKED,
    inv.DETACHED: BLOCKED,
}

# What a single local, read-only view can never establish.
LIMITATIONS = (
    "REMOTE_STATE_NOT_LOCALLY_PROVABLE",
    "PROMOTION_STATE_NOT_LOCALLY_PROVABLE",
    "MODULE_CLOSURE_NOT_LOCALLY_PROVABLE",
    "HOST_LEDGER_NOT_CONSULTED",
    "EXTERNAL_QUEUES_NOT_LOCALLY_PROVABLE",
    "POINT_IN_TIME_SNAPSHOT",
    "LEASE_PROBE_MAY_REWRITE_QUEUE_LOCK_DIAGNOSTIC_BYTES",
    "GIT_CALLS_HAVE_NO_TIMEOUT",
)

# Per-worktree Git dir entries that mean an operation is paused mid-way.
_PAUSED_MARKERS = (
    ("rebase-merge", "PAUSED_REBASE"),
    ("rebase-apply", "PAUSED_REBASE_APPLY"),
    ("MERGE_HEAD", "PAUSED_MERGE"),
    ("CHERRY_PICK_HEAD", "PAUSED_CHERRY_PICK"),
    ("REVERT_HEAD", "PAUSED_REVERT"),
    ("BISECT_LOG", "PAUSED_BISECT"),
    ("sequencer", "PAUSED_SEQUENCER"),
)

# Refs git keeps per worktree (gitglossary "per-worktree ref").
_WORKTREE_LOCAL_REF_PREFIXES = ("refs/worktree/", "refs/bisect/", "refs/rewritten/")

_TERMINAL_QUEUE_STATES = frozenset({
    queue.QueueState.SUCCEEDED.value, queue.QueueState.FAILED.value, queue.QueueState.FAILED_SAFETY.value,
})

_HEADS = "refs/heads/"


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetirementFacts:
    """Every fact `classify_retirement` judges, for one worktree key. A
    None/False "proven" fact is unproven and can never yield a CANDIDATE."""

    worktree_key: str
    path: str
    # Inventory (first/second call) - reused verbatim.
    first_inventory_status: Optional[str] = None
    second_inventory_status: Optional[str] = None
    in_first_inventory: bool = False
    in_second_inventory: bool = False
    inventory_classification: Optional[str] = None
    second_inventory_classification: Optional[str] = None
    inventory_reason_codes: tuple = ()
    inventory_advisories: tuple = ()
    inventory_lease_state: Optional[str] = None
    first_record_fingerprint: Optional[str] = None
    second_record_fingerprint: Optional[str] = None
    # Self / governed roots.
    self_worktree_known: bool = False
    is_self_worktree: bool = False
    governed_roots_resolved: bool = False
    overlapping_roots: tuple = ()
    # Supplemental Git reads (idle records only).
    supplemental_checked: bool = False
    supplemental_errors: tuple = ()
    supplemental_status_entries: tuple = ()
    ignored_count: Optional[int] = None
    ignored_paths: tuple = ()
    ignored_sensitive: tuple = ()
    paused_operations: tuple = ()
    paused_probe_ok: bool = False
    index_flags_proven: bool = False
    skip_worktree_paths: tuple = ()
    assume_unchanged_paths: tuple = ()
    head_ref_consistent: bool = False
    worktree_local_refs: tuple = ()
    topology_hazards: tuple = ()
    topology_proven: bool = False
    local_only_commits: Optional[int] = None
    unique_commits: Optional[int] = None
    git_admin_state_changed: bool = False
    # Queue.
    queue_roots_declared: bool = False
    queue_roots_complete_claim: bool = False
    queue_errors: tuple = ()
    queue_items: tuple = ()
    queue_drift: bool = False
    # Factory ledger.
    ledger_error: Optional[str] = None
    ledger_work_products: tuple = ()
    ledger_history: tuple = ()
    ledger_drift: bool = False


@dataclass(frozen=True)
class WorktreeRetirementAssessment:
    """Outcome of `classify_retirement` for one worktree. Informational
    only: it never authorizes any action on the worktree."""

    worktree_key: str
    path: str
    classification: str
    reason_codes: tuple
    advisories: tuple
    limitations: tuple
    facts: RetirementFacts
    human_review_required: bool = True
    authorizes_action: bool = False
    deletion_authorized: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class RetirementReport:
    """Whole-repository assessment. COMPLETE only when both inventories
    were COMPLETE and every declared source was read; otherwise
    FAILED_CLOSED (every record still reported). Never authorizes."""

    schema: str
    status: str
    requested_path: str
    repository_top: Optional[str]
    common_dir: Optional[str]
    state_root: str
    ledger_root: str
    lease_root: Optional[str]
    queue_roots: tuple
    queue_roots_complete_claim: bool
    self_worktree: Optional[str]
    governed_roots: tuple
    first_inventory_status: Optional[str]
    second_inventory_status: Optional[str]
    first_inventory_fingerprint: Optional[str]
    second_inventory_fingerprint: Optional[str]
    global_errors: tuple
    records: tuple
    counts: tuple
    classification_precedence: tuple = CLASSIFICATION_PRECEDENCE
    limitations: tuple = LIMITATIONS
    human_review_required: bool = True
    authorizes_action: bool = False
    deletion_authorized: bool = False
    fingerprint: str = ""


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _sensitive_codes(path: str) -> tuple:
    """Codes for an ignored path that must never be treated as disposable.
    Case-insensitive and anywhere in the path (stricter than the patterns)."""
    parts = [p.casefold() for p in re.split(r"[\\/]", path) if p]
    codes = []
    if any(a == "runtime" and b == "claude_runner" for a, b in zip(parts, parts[1:])):
        codes.append("IGNORED_RUNNER_RUNTIME")
    if any(p.startswith(".env") for p in parts):
        codes.append("IGNORED_SECRET_ENV")
    if parts and ".db" in parts[-1]:
        codes.append("IGNORED_DATABASE_FILE")
    if "database" in parts[:-1]:
        codes.append("IGNORED_DATABASE_DIR")
    return tuple(codes)


def _findings(f: RetirementFacts) -> tuple:
    found = {name: [] for name in CLASSIFICATION_PRECEDENCE}
    advisories = []
    blocked, insufficient, review = found[BLOCKED], found[INSUFFICIENT_EVIDENCE], found[REVIEW_REQUIRED]

    # Inventory: reused verbatim, never improved.
    for status in (f.first_inventory_status, f.second_inventory_status):
        if status != inv.INVENTORY_COMPLETE:
            insufficient.append("INVENTORY_NOT_COMPLETE")
    if not f.in_first_inventory:
        insufficient.append("RECORD_ABSENT_FROM_FIRST_INVENTORY")
    if not f.in_second_inventory:
        insufficient.append("RECORD_ABSENT_FROM_SECOND_INVENTORY")
    if f.in_first_inventory and f.in_second_inventory and f.first_record_fingerprint != f.second_record_fingerprint:
        insufficient.append("RECORD_FINGERPRINT_CHANGED")
    for classification in (f.inventory_classification, f.second_inventory_classification):
        if classification is None:
            continue
        forced = INVENTORY_MAPPING.get(classification)
        if forced is not None:
            found[forced].append(f"INVENTORY_{classification}")
        elif classification != inv.IDLE_CLEAN_UNBOUND:
            insufficient.append("INVENTORY_CLASSIFICATION_UNKNOWN")
    for code in f.inventory_reason_codes:
        target = INVENTORY_MAPPING.get(f.inventory_classification, INSUFFICIENT_EVIDENCE)
        found[target].append(f"INVENTORY:{code}")
    for code in f.inventory_advisories:
        if code == "LEASE_IDENTITY_RESIDUE":
            review.append("LEASE_DIAGNOSTIC_RESIDUE")
        elif code == "TERMINAL_PIPELINE_HISTORY":
            review.append("PIPELINE_HISTORY")
        else:
            review.append(f"INVENTORY_ADVISORY:{code}")
    if f.inventory_lease_state == inv.LEASE_FREE:
        # The lock file exists, so the lease was taken before (history).
        review.append("LEASE_LOCK_FILE_PRESENT")

    # Self / governed roots.
    if not f.self_worktree_known:
        insufficient.append("SELF_WORKTREE_UNKNOWN")
    if f.is_self_worktree:
        blocked.append("SELF_WORKTREE")
    if not f.governed_roots_resolved:
        insufficient.append("GOVERNED_ROOT_UNRESOLVABLE")
    if f.overlapping_roots:
        blocked.append("GOVERNED_ROOT_OVERLAP")

    # Supplemental Git facts.
    if f.supplemental_errors:
        insufficient.append("SUPPLEMENTAL_READ_FAILED")
    if f.supplemental_status_entries:
        insufficient.append("SUPPLEMENTAL_STATUS_NOT_CLEAN")
    if f.git_admin_state_changed:
        insufficient.append("GIT_ADMIN_STATE_CHANGED")
    for _code_path in f.ignored_sensitive:
        blocked.append(_code_path[0])
    if f.ignored_count:
        review.append("IGNORED_FILES_PRESENT")
        if f.ignored_count > MAX_IGNORED_ENTRIES:
            insufficient.append("IGNORED_ENUMERATION_OVERFLOW")
    for _marker, code in f.paused_operations:
        blocked.append(code)
    if f.skip_worktree_paths:
        insufficient.append("HIDDEN_INDEX_SKIP_WORKTREE")
    if f.assume_unchanged_paths:
        insufficient.append("HIDDEN_INDEX_ASSUME_UNCHANGED")
    if f.topology_hazards:
        insufficient.append("UNTRUSTWORTHY_TOPOLOGY")
    if f.worktree_local_refs:
        review.append("WORKTREE_LOCAL_REFS")
    if f.local_only_commits:
        review.append("LOCAL_ONLY_COMMITS")
    if f.unique_commits:
        review.append("UNIQUE_LOCAL_COMMITS")
    if f.local_only_commits == 0:
        advisories.append("NO_LOCAL_ONLY_COMMITS_IS_NOT_REMOTE_PROOF")

    # Queue.
    if not f.queue_roots_declared:
        insufficient.append("QUEUE_ROOTS_NOT_DECLARED")
    elif not f.queue_roots_complete_claim:
        insufficient.append("QUEUE_ROOTS_NOT_DECLARED_COMPLETE")
    insufficient.extend(f.queue_errors)
    if f.queue_drift:
        insufficient.append("QUEUE_STATE_DRIFT")
    for _root, _item, state, checkpoints in f.queue_items:
        if state not in _TERMINAL_QUEUE_STATES:
            blocked.append("QUEUE_ITEM_ACTIVE")
        else:
            review.append("QUEUE_ITEM_TERMINAL_HISTORY")
        if checkpoints:
            review.append("QUEUE_ITEM_CHECKPOINTS")

    # Factory ledger.
    if f.ledger_error is not None:
        insufficient.append("LEDGER_UNREADABLE")
    if f.ledger_drift:
        insufficient.append("LEDGER_DRIFT")
    if f.ledger_work_products:
        review.append("LEDGER_WORK_PRODUCT")
    if f.ledger_history:
        review.append("LEDGER_HISTORY")
    return found, tuple(dict.fromkeys(advisories))


def _unproven(f: RetirementFacts) -> tuple:
    """Every candidate requirement whose fact is UNKNOWN (not known-bad:
    `_findings` reports those). An unknown fact can never be a CANDIDATE.
    The supplemental facts are only required of inventory-idle records;
    any other inventory class is already BLOCKED/INSUFFICIENT by mapping."""
    checks = [
        ("UNPROVEN_INVENTORIES", f.first_inventory_status == inv.INVENTORY_COMPLETE
         and f.second_inventory_status == inv.INVENTORY_COMPLETE and f.in_first_inventory
         and f.in_second_inventory and f.first_record_fingerprint is not None
         and f.first_record_fingerprint == f.second_record_fingerprint),
        ("UNPROVEN_INVENTORY_CLASSIFICATION", f.inventory_classification is not None
         and f.second_inventory_classification is not None),
        ("UNPROVEN_SELF_AND_ROOTS", f.self_worktree_known and f.governed_roots_resolved),
        ("UNPROVEN_QUEUES", f.queue_roots_declared and f.queue_roots_complete_claim and not f.queue_errors),
        ("UNPROVEN_LEDGER", f.ledger_error is None),
    ]
    if f.inventory_classification == inv.IDLE_CLEAN_UNBOUND:
        checks += [
            ("UNPROVEN_SUPPLEMENTAL", f.supplemental_checked and not f.supplemental_errors
             and not f.git_admin_state_changed),
            ("UNPROVEN_IGNORED", f.ignored_count is not None),
            ("UNPROVEN_NO_PAUSED_OPERATION", f.paused_probe_ok),
            ("UNPROVEN_INDEX_FLAGS", f.index_flags_proven),
            ("UNPROVEN_HEAD_REF", f.head_ref_consistent),
            ("UNPROVEN_TOPOLOGY", f.topology_proven),
            ("UNPROVEN_COMMITS", f.local_only_commits is not None and f.unique_commits is not None),
        ]
    return tuple(code for code, ok in checks if not ok)


def _digest(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def classify_retirement(facts: RetirementFacts) -> WorktreeRetirementAssessment:
    """Pure, fail-closed classification with the fixed precedence of
    CLASSIFICATION_PRECEDENCE. Never authorizes anything."""
    found, advisories = _findings(facts)
    # Unproven requirements are always recorded, so a missing proof can
    # never hide behind a milder (REVIEW_REQUIRED) finding.
    found[INSUFFICIENT_EVIDENCE].extend(_unproven(facts))
    classification = next(
        (name for name in CLASSIFICATION_PRECEDENCE[:-1] if found[name]), CANDIDATE_FOR_HUMAN_REVIEW,
    )
    reasons = tuple(dict.fromkeys(code for name in CLASSIFICATION_PRECEDENCE for code in found[name]))
    fingerprint = _digest({
        "schema": SCHEMA, "classification": classification, "reason_codes": list(reasons),
        "advisories": list(advisories),
        "facts": {k: _jsonable(v) for k, v in facts.__dict__.items()},
    })
    return WorktreeRetirementAssessment(
        worktree_key=facts.worktree_key, path=facts.path, classification=classification,
        reason_codes=reasons, advisories=advisories, limitations=LIMITATIONS, facts=facts,
        fingerprint=fingerprint,
    )


# ---------------------------------------------------------------------------
# Read-only sources
# ---------------------------------------------------------------------------

def _key(path) -> Optional[str]:
    try:
        return mw.canonical_target_key(str(path))
    except mw.MultiworkerError:
        return None


def _overlaps(a: str, b: str) -> bool:
    pa, pb = Path(a), Path(b)
    return pa == pb or pa in pb.parents or pb in pa.parents


def _read_queues(queue_roots: tuple) -> tuple:
    """({worktree_key: [(root, item_id, state, checkpoints)]}, [(code,
    detail)]). A missing, unreadable or corrupt root, or an item whose
    target cannot be resolved, is a global error (it could target any
    worktree). `list_items` itself fails closed on any corrupt item.
    QUEUE_ROOT_MISSING also covers a root that exists but is not reachable
    as a directory (e.g. a Windows path beyond MAX_PATH without long-path
    support): either way nothing in it was seen."""
    by_key: dict = {}
    errors = []
    for root in queue_roots:
        path = Path(root)
        try:
            if not path.is_dir():
                errors.append(("QUEUE_ROOT_MISSING", f"{root}: not a directory"))
                continue
            items = queue.list_items(path)
        except (queue.QueueError, OSError, ValueError) as exc:
            errors.append(("QUEUE_ROOT_UNREADABLE", f"{root}: {type(exc).__name__}: {exc}"))
            continue
        for item in items:
            key = _key(item.repository_path)
            if key is None:
                errors.append(("QUEUE_ITEM_TARGET_UNRESOLVABLE", f"{root}: {item.item_id}"))
                continue
            by_key.setdefault(key, []).append(
                (str(root), item.item_id, str(item.state), len(item.checkpoints or ())),
            )
    return {k: tuple(sorted(v)) for k, v in by_key.items()}, errors


def _read_ledger(ledger_root) -> tuple:
    """(events, error). Same fail-closed rule as the inventory: a missing
    root, an unreadable/undecodable file or ANY skipped line is an error."""
    root = Path(ledger_root)
    events_path = root / flog.EVENTS_FILENAME
    try:
        if not root.is_dir():
            return [], f"ledger root is not a directory: {root}"
        if events_path.exists():
            events_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    events, skipped = flog.read_events(root)
    if skipped:
        return [], f"{skipped} unreadable ledger line(s)"
    return events, None


def _ledger_for(events: list, key: str, branch: Optional[str]) -> tuple:
    """(work_products, history): sorted (event_type, pipeline_id, worker_id)
    of every ledger event bound to this worktree by path or branch."""
    work, history = set(), set()
    for event in events:
        target = event.get("worktree")
        same_worktree = isinstance(target, str) and target.strip() and _key(target) == key
        same_branch = branch is not None and event.get("branch") in (branch, _HEADS + branch)
        if not (same_worktree or same_branch):
            continue
        entry = (str(event.get("event_type")), str(event.get("pipeline_id")), str(event.get("worker_id")))
        (work if event.get("event_type") == flog.WORK_PRODUCT_CREATED else history).add(entry)
    return tuple(sorted(work)), tuple(sorted(history))


def _admin_state(git_dir: str) -> tuple:
    """Size/mtime of the per-worktree index and HEAD bytes: any change
    across the supplemental reads means the worktree is not quiescent."""
    state = []
    for name in ("index", "HEAD"):
        path = Path(git_dir) / name
        try:
            st = path.stat()
            state.append((name, st.st_size, st.st_mtime_ns))
        except FileNotFoundError:
            state.append((name, None, None))
    return tuple(state)


def _parse_status_z(out: str) -> tuple:
    """(ignored_paths, other_entries) of `status --porcelain=v1 -z`."""
    ignored, other = [], []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("## "):
            continue
        xy, path = entry[:2], entry[3:]
        if xy == "!!":
            ignored.append(path)
        else:
            other.append(entry)
            if xy[0] in "RC":
                i += 1  # the rename/copy source path
    return ignored, other


def _supplemental(record, facts: dict) -> None:
    """Fills supplemental facts for one inventory-idle record, reading
    only through `runner_integration._git` and per-worktree Git dir
    metadata. Raises ri._GitReadError/OSError on any failed read."""
    path, git_dir = record.worktree_top, record.git_dir
    admin_before = _admin_state(git_dir)

    _, out = ri._git(path, "status", "--porcelain=v1", "-z", "--ignored=traditional",
                     "--untracked-files=all", "--ignore-submodules=none")
    ignored, other = _parse_status_z(out)
    ignored = sorted(set(ignored))
    sensitive = tuple((code, p) for p in ignored for code in _sensitive_codes(p))
    facts.update(supplemental_status_entries=tuple(sorted(other))[:MAX_IGNORED_ENTRIES],
                 ignored_count=len(ignored), ignored_paths=tuple(ignored[:MAX_IGNORED_ENTRIES]),
                 ignored_sensitive=sensitive)

    facts["paused_operations"] = tuple(
        (marker, code) for marker, code in _PAUSED_MARKERS if os.path.lexists(Path(git_dir) / marker)
    )
    facts["paused_probe_ok"] = True

    _, out = ri._git(path, "ls-files", "-v", "-z")
    skip, assume = [], []
    for entry in out.split("\0"):
        if not entry:
            continue
        tag, sep, name = entry[:1], entry[1:2], entry[2:]
        if sep != " " or tag not in ("H", "S", "h", "s"):
            raise ri._GitReadError("git ls-files", f"unexpected index entry tag {tag!r}")
        if tag in ("S", "s"):
            skip.append(name)
        if tag in ("h", "s"):
            assume.append(name)
    facts.update(skip_worktree_paths=tuple(sorted(skip)), assume_unchanged_paths=tuple(sorted(assume)),
                 index_flags_proven=True)

    identity = ri._repo_identity(path)
    refs = ri._list_refs(path)
    head_ref, head_sha = record.head_ref, record.head_sha
    entry = refs.get(head_ref)
    facts["head_ref_consistent"] = bool(
        entry is not None and entry[0] == head_sha and entry[1] == "commit" and not entry[2]
        and ri._head(path, identity["object_format"]) == (head_ref, head_sha)
    )
    facts["worktree_local_refs"] = tuple(sorted(
        name for name in refs if name.startswith(_WORKTREE_LOCAL_REF_PREFIXES)
    ))
    hazards = []
    if identity["shallow"]:
        hazards.append("SHALLOW")
    if ri._grafts_present(identity):
        hazards.append("GRAFTS")
    if any(name.startswith("refs/replace/") for name in refs):
        hazards.append("REPLACE_REFS")
    if ri._partial_clone(path):
        hazards.append("PARTIAL_CLONE")
    facts.update(topology_hazards=tuple(hazards), topology_proven=not hazards)

    if not hazards and facts["head_ref_consistent"]:
        # Local-only is NOT remote proof: tracking refs are never refreshed.
        facts["local_only_commits"] = _count(path, head_sha, "--not", "--remotes")
        facts["unique_commits"] = _count(
            path, head_sha, "--not", f"--exclude={head_ref}", "--glob=refs/heads/*", "--tags", "--remotes",
        )

    if _admin_state(git_dir) != admin_before:
        facts["git_admin_state_changed"] = True


def _count(path: str, *args) -> int:
    _, out = ri._git(path, "rev-list", "--count", *args, "--")
    out = out.strip()
    if not out.isdigit():
        raise ri._GitReadError("git rev-list", "unexpected count output")
    return int(out)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _safe_inventory(repository, state_root, ledger_root, lease_root):
    """(inventory or None, error). The inventory fails closed by itself;
    anything it raises is an internal error and fails the report closed."""
    try:
        return inv.inventory_worktrees(repository, state_root=state_root, ledger_root=ledger_root,
                                       lease_root=lease_root), None
    except Exception as exc:  # fail closed: never a candidate on an internal error
        return None, f"INVENTORY_RAISED: {type(exc).__name__}: {exc}"


def _counts(records: tuple) -> tuple:
    return tuple((name, sum(1 for r in records if r.classification == name)) for name in CLASSIFICATION_PRECEDENCE)


def assess_worktree_retirement(
    repository, *, state_root, ledger_root, lease_root=None, queue_roots=(), queue_roots_complete=False,
    self_worktree, governed_roots=(),
) -> RetirementReport:
    """Read-only retirement assessment of every worktree registered for
    the repository `repository` belongs to. `queue_roots` are the ONLY
    queues consulted; `queue_roots_complete` is the host's claim that they
    are the complete known set (recorded verbatim, never a proof).
    `self_worktree` and `governed_roots` (plus the state, ledger, lease and
    queue roots) are never CANDIDATEs, nor is anything overlapping them."""
    requested = str(repository)
    queue_roots = tuple(str(q) for q in queue_roots)
    governed_roots = tuple(str(g) for g in governed_roots)
    claim = queue_roots_complete is True
    global_errors = []

    first, error = _safe_inventory(requested, state_root, ledger_root, lease_root)
    if error:
        global_errors.append(error)

    self_key = _key(self_worktree) if self_worktree is not None else None
    root_specs = [("state_root", state_root), ("ledger_root", ledger_root)]
    root_specs += [("lease_root", lease_root)] if lease_root is not None else []
    root_specs += [("queue_root", q) for q in queue_roots] + [("governed_root", g) for g in governed_roots]
    root_keys, roots_resolved = [], True
    for kind, root in root_specs:
        key = _key(root)
        if key is None:
            roots_resolved = False
        else:
            root_keys.append((kind, key))
    if self_key is not None:
        root_keys.append(("self_worktree", self_key))

    queues_before, queue_errors = _read_queues(queue_roots)
    events_before, ledger_error = _read_ledger(ledger_root)

    first_records = {r.worktree_key: r for r in (first.records if first else ())}
    supplemental: dict = {}
    for key, record in first_records.items():
        if record.classification != inv.IDLE_CLEAN_UNBOUND:
            continue
        facts = {"supplemental_checked": True}
        try:
            _supplemental(record, facts)
        except (ri._GitReadError, OSError, ValueError, TypeError) as exc:
            facts["supplemental_errors"] = (f"{type(exc).__name__}: {exc}",)
        supplemental[key] = facts

    second, error = _safe_inventory(requested, state_root, ledger_root, lease_root)
    if error:
        global_errors.append(error)
    queues_after, queue_errors_after = _read_queues(queue_roots)
    events_after, ledger_error_after = _read_ledger(ledger_root)
    queue_errors = list(dict.fromkeys(queue_errors + queue_errors_after))
    queue_codes = tuple(dict.fromkeys(code for code, _ in queue_errors))
    ledger_error = ledger_error or ledger_error_after
    global_errors.extend(f"{code}: {detail}" for code, detail in queue_errors)
    if ledger_error:
        global_errors.append(f"LEDGER_UNREADABLE: {ledger_error}")
    if not roots_resolved:
        global_errors.append("GOVERNED_ROOT_UNRESOLVABLE")
    if self_key is None:
        global_errors.append("SELF_WORKTREE_UNKNOWN")

    second_records = {r.worktree_key: r for r in (second.records if second else ())}
    assessments = []
    for key in sorted(set(first_records) | set(second_records)):
        a, b = first_records.get(key), second_records.get(key)
        record = a or b
        branch = record.head_ref or record.listed_branch
        branch = branch[len(_HEADS):] if branch and branch.startswith(_HEADS) else None
        work_before, hist_before = _ledger_for(events_before, key, branch)
        work, hist = _ledger_for(events_after, key, branch)
        # The self worktree itself is SELF_WORKTREE; anything nested in or
        # enclosing it (or any other governed root) is an overlap.
        overlapping = tuple(sorted({
            (kind, rk) for kind, rk in root_keys
            if _overlaps(rk, key) and not (kind == "self_worktree" and rk == key)
        }))
        facts = {
            "worktree_key": key, "path": record.path,
            "first_inventory_status": first.status if first else None,
            "second_inventory_status": second.status if second else None,
            "in_first_inventory": a is not None, "in_second_inventory": b is not None,
            "inventory_classification": a.classification if a else None,
            "second_inventory_classification": b.classification if b else None,
            "inventory_reason_codes": tuple(record.reason_codes),
            "inventory_advisories": tuple(record.advisories),
            "inventory_lease_state": record.lease_state,
            "first_record_fingerprint": a.fingerprint if a else None,
            "second_record_fingerprint": b.fingerprint if b else None,
            "self_worktree_known": self_key is not None, "is_self_worktree": self_key == key,
            "governed_roots_resolved": roots_resolved, "overlapping_roots": overlapping,
            "queue_roots_declared": bool(queue_roots), "queue_roots_complete_claim": claim,
            "queue_errors": queue_codes, "queue_items": queues_after.get(key, ()),
            "queue_drift": queues_before.get(key, ()) != queues_after.get(key, ()),
            "ledger_error": ledger_error, "ledger_work_products": work, "ledger_history": hist,
            "ledger_drift": (work_before, hist_before) != (work, hist),
        }
        facts.update(supplemental.get(key, {}))
        assessments.append(classify_retirement(RetirementFacts(**facts)))

    main_key = first.records[0].worktree_key if first and first.records else None
    records = tuple(sorted(assessments, key=lambda r: (r.worktree_key != main_key, r.worktree_key)))
    for inventory in (first, second):
        if inventory is not None and not inventory.complete:
            global_errors.extend(f"INVENTORY: {e}" for e in inventory.global_errors)
    global_errors = tuple(dict.fromkeys(global_errors))
    complete = (first is not None and first.complete and second is not None and second.complete
                and not global_errors)
    status = REPORT_COMPLETE if complete else REPORT_FAILED_CLOSED
    identity = first or second
    fields = {
        "schema": SCHEMA, "status": status, "requested_path": requested,
        "repository_top": identity.repository_top if identity else None,
        "common_dir": identity.common_dir if identity else None,
        "state_root": str(state_root), "ledger_root": str(ledger_root),
        "lease_root": None if lease_root is None else str(lease_root),
        "queue_roots": queue_roots, "queue_roots_complete_claim": claim,
        "self_worktree": None if self_worktree is None else str(self_worktree),
        "governed_roots": governed_roots,
        "first_inventory_status": first.status if first else None,
        "second_inventory_status": second.status if second else None,
        "first_inventory_fingerprint": first.fingerprint if first else None,
        "second_inventory_fingerprint": second.fingerprint if second else None,
        "global_errors": global_errors, "records": records, "counts": _counts(records),
    }
    fingerprint = _digest({
        "schema": SCHEMA, "status": status, "common_dir": _key(fields["common_dir"]) if fields["common_dir"] else None,
        "queue_roots": sorted(filter(None, (_key(q) for q in queue_roots))), "queue_roots_complete_claim": claim,
        "global_errors": list(global_errors), "records": [r.fingerprint for r in records],
    })
    return RetirementReport(**fields, fingerprint=fingerprint)

"""FCP-3B-2A: read-only GitHub PR promotion gate (NON-AUTHORIZING).

Canonical promotion is GitHub Pull Request -> CI -> explicit human decision
-> governed host execution. This module only checks that ONE pull request
looks consistent with ONE FCP-3B-1 promotion intent and its fresh
revalidation, so a human can review it. It never merges, approves, comments,
pushes, fetches, writes refs or files, opens network connections, runs
processes or reads Git itself, and keeps no durable state. The FCP-3B-1
`FAST_FORWARD_CANDIDATE_TO_DEVELOP` action stays a description: nothing here
turns it into a merge permission.

Binding (`PrGateContext`)
-------------------------
The PR is identified by the canonical repository (`CANONICAL_REPOSITORY`),
an explicit host-chosen PR number, base ref `develop`, and the base SHA,
head branch and head SHA copied from a self-consistent FCP-3B-1 intent,
plus the intent and validation fingerprints. No URL, label or caller branch
string is ever used as identity.

Evaluation
----------
`evaluate_pr_gate` (pure) checks a caller-supplied `PullRequestSnapshot`
against that binding: open, non-draft, unmerged, same-repository head, base
`develop`, head/base/develop-tip SHAs unchanged, the complete changed-file
set (explicit counts and pagination, every path and rename source inside the
intent's authorized scopes) and the required check runs: the four named
Fabric CI jobs (`REQUIRED_CI_JOBS`), each exactly once, bound to the GitHub
Actions app, the Fabric CI workflow file, the `pull_request` event, this PR,
the head SHA and ONE workflow run, completed with `success`; plus every
check the base branch policy requires. A missing, incomplete or unmodeled
branch policy yields POLICY_NOT_PROVEN, never readiness.

The validation must be a genuine-looking FRESH_FCP3A_READ match of the same
intent (exact type, fingerprint, invariants and reason codes re-checked with
the FCP-3B-1 functions). The pure path cannot prove that the validation or
the snapshot were produced freshly by the host, and says so
(PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN, PR_GATE_SOURCE_FRESHNESS_NOT_PROVEN).

`read_pr_gate` performs exactly one FCP-3B-1 `revalidate_promotion_intent`
(itself one FCP-3A read) and then at most one call of each method of a
host-supplied read-only `PullRequestMetadataProvider`, passing only plain
identifiers. The provider is a host trust boundary: this module cannot
authenticate it (PR_GATE_SOURCE_NOT_AUTHENTICATED) and the reads are not
atomic with each other or with any later action.

Every result has `human_approval_required=True`, `authorizes_action=False`,
`execution_allowed=False`, `source_authenticated=False` and
`human_decision_present=False`. `candidate_reviewable=True` only means "the
PR metadata appears consistent for a human decision"; it is not mergeability,
not approval and not permission. Fingerprints are SHA-256 identity digests
of canonical JSON, never proof of origin or consent. An authenticated human
approval source, expiry/revocation, replay control, race-safe execution with
expected head SHA, API permissions, postconditions and audit belong to the
separately reviewed FCP-3B-2B contract.
"""

from __future__ import annotations

import dataclasses
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

try:
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_promotion as rp
    from scripts.ai import runner_promotion_authorization as rpa
    from scripts.ai import runner_reconciliation as rr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_promotion as rp  # type: ignore[no-redef]
    import runner_promotion_authorization as rpa  # type: ignore[no-redef]
    import runner_reconciliation as rr  # type: ignore[no-redef]


SNAPSHOT_SCHEMA = "fcp3b2a-pr-snapshot-v1"
CONTEXT_SCHEMA = "fcp3b2a-pr-gate-context-v1"
RESULT_SCHEMA = "fcp3b2a-pr-gate-result-v1"

# The one repository and target a PR may be bound to.
CANONICAL_REPOSITORY = "ignacio-alvarez93/quesada-abogados"
BASE_BRANCH = ri.INTEGRATION_BRANCH

# The required Fabric CI jobs (`name:` of each job in CI_WORKFLOW_PATH) and
# what each check run must be bound to.
REQUIRED_CI_JOBS = (
    "Fabric regression / Windows / Python 3.11",
    "FCP-2B reconciliation / Windows / Python 3.11",
    "FCP-3A promotion preflight / Windows / Python 3.11",
    "FCP-3B-1 promotion intent / Windows / Python 3.11",
)
CI_APP_SLUG = "github-actions"
CI_WORKFLOW_NAME = "Fabric CI"
CI_WORKFLOW_PATH = ".github/workflows/fabric-ci.yml"
CI_EVENT = "pull_request"

# Provider-neutral vocabularies (GitHub REST values). Anything else is unknown.
PR_STATES = ("open", "closed")
FILE_STATUSES = ("added", "modified", "removed", "renamed", "copied", "changed", "unchanged")
CHECK_STATUSES = ("queued", "in_progress", "completed", "waiting", "requested", "pending")
CHECK_CONCLUSIONS = ("success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required",
                     "stale", "startup_failure")
# Branch rule types whose meaning is compatible with this gate; any other
# rule may impose a condition this gate cannot see.
MODELED_POLICY_RULES = ("deletion", "non_fast_forward", "pull_request", "required_linear_history",
                        "required_status_checks")

MAX_PR_NUMBER = 2 ** 31 - 1
MAX_ID = 2 ** 63 - 1
MAX_CHANGED_FILES = 3000   # GitHub lists at most this many files of one PR
MAX_PAGE_SIZE = 100

# Classifications.
REJECTED = "REJECTED"
POLICY_NOT_PROVEN = "POLICY_NOT_PROVEN"
REVIEWABLE_UNVERIFIED_SNAPSHOT = "REVIEWABLE_UNVERIFIED_SNAPSHOT"
REVIEWABLE_HOST_READ = "REVIEWABLE_HOST_READ"
CLASSIFICATIONS = (REJECTED, POLICY_NOT_PROVEN, REVIEWABLE_UNVERIFIED_SNAPSHOT, REVIEWABLE_HOST_READ)

# Modes.
MODE_SUPPLIED_SNAPSHOT = "SUPPLIED_SNAPSHOT"
MODE_HOST_PROVIDER_READ = "HOST_PROVIDER_READ"

# Reason codes: binding to FCP-3B-1.
PR_GATE_INTENT_INVALID = "PR_GATE_INTENT_INVALID"
PR_GATE_VALIDATION_MALFORMED = "PR_GATE_VALIDATION_MALFORMED"
PR_GATE_VALIDATION_TAMPERED = "PR_GATE_VALIDATION_TAMPERED"
PR_GATE_VALIDATION_NOT_FRESH_MODE = "PR_GATE_VALIDATION_NOT_FRESH_MODE"
PR_GATE_VALIDATION_NOT_VALID = "PR_GATE_VALIDATION_NOT_VALID"
PR_GATE_VALIDATION_INTENT_MISMATCH = "PR_GATE_VALIDATION_INTENT_MISMATCH"
PR_GATE_PR_NUMBER_INVALID = "PR_GATE_PR_NUMBER_INVALID"
# PR metadata.
PR_GATE_PR_MISSING = "PR_GATE_PR_MISSING"
PR_GATE_SNAPSHOT_MALFORMED = "PR_GATE_SNAPSHOT_MALFORMED"
PR_GATE_PR_NUMBER_MISMATCH = "PR_GATE_PR_NUMBER_MISMATCH"
PR_GATE_REPOSITORY_MISMATCH = "PR_GATE_REPOSITORY_MISMATCH"
PR_GATE_FORK_OR_FOREIGN_HEAD = "PR_GATE_FORK_OR_FOREIGN_HEAD"
PR_GATE_PR_STATE_UNKNOWN = "PR_GATE_PR_STATE_UNKNOWN"
PR_GATE_PR_CLOSED = "PR_GATE_PR_CLOSED"
PR_GATE_PR_MERGED = "PR_GATE_PR_MERGED"
PR_GATE_PR_DRAFT = "PR_GATE_PR_DRAFT"
PR_GATE_PR_INCONSISTENT = "PR_GATE_PR_INCONSISTENT"
PR_GATE_BASE_REF_INVALID = "PR_GATE_BASE_REF_INVALID"
PR_GATE_HEAD_REF_MISMATCH = "PR_GATE_HEAD_REF_MISMATCH"
PR_GATE_SHA_INVALID = "PR_GATE_SHA_INVALID"
PR_GATE_STALE_HEAD = "PR_GATE_STALE_HEAD"
PR_GATE_STALE_BASE = "PR_GATE_STALE_BASE"
# Changed files.
PR_GATE_FILES_INCOMPLETE = "PR_GATE_FILES_INCOMPLETE"
PR_GATE_FILES_MISSING = "PR_GATE_FILES_MISSING"
PR_GATE_FILE_STATUS_UNKNOWN = "PR_GATE_FILE_STATUS_UNKNOWN"
PR_GATE_PATH_INVALID = "PR_GATE_PATH_INVALID"
PR_GATE_PATH_ANOMALY = "PR_GATE_PATH_ANOMALY"
PR_GATE_PATH_OUT_OF_SCOPE = "PR_GATE_PATH_OUT_OF_SCOPE"
# Checks.
PR_GATE_CHECKS_INCOMPLETE = "PR_GATE_CHECKS_INCOMPLETE"
PR_GATE_CHECK_STATUS_UNKNOWN = "PR_GATE_CHECK_STATUS_UNKNOWN"
PR_GATE_CHECK_HEAD_MISMATCH = "PR_GATE_CHECK_HEAD_MISMATCH"
PR_GATE_CHECK_MISSING = "PR_GATE_CHECK_MISSING"
PR_GATE_CHECK_DUPLICATE = "PR_GATE_CHECK_DUPLICATE"
PR_GATE_CHECK_PENDING = "PR_GATE_CHECK_PENDING"
PR_GATE_CHECK_FAILED = "PR_GATE_CHECK_FAILED"
PR_GATE_CHECK_CANCELLED = "PR_GATE_CHECK_CANCELLED"
PR_GATE_CHECK_SKIPPED = "PR_GATE_CHECK_SKIPPED"
PR_GATE_CHECK_NOT_SUCCESS = "PR_GATE_CHECK_NOT_SUCCESS"
PR_GATE_CHECK_BINDING_MISMATCH = "PR_GATE_CHECK_BINDING_MISMATCH"
PR_GATE_CHECK_EVENT_MISMATCH = "PR_GATE_CHECK_EVENT_MISMATCH"
PR_GATE_CHECK_RUN_CONFLICT = "PR_GATE_CHECK_RUN_CONFLICT"
# Branch policy.
PR_GATE_POLICY_NOT_PROVEN = "PR_GATE_POLICY_NOT_PROVEN"
PR_GATE_POLICY_RULE_UNMODELED = "PR_GATE_POLICY_RULE_UNMODELED"
# Host read / internal.
PR_GATE_PROVIDER_READ_FAILED = "PR_GATE_PROVIDER_READ_FAILED"
PR_GATE_EVALUATION_FAILED = "PR_GATE_EVALUATION_FAILED"
# Positive and always-present codes.
PR_GATE_METADATA_CONSISTENT = "PR_GATE_METADATA_CONSISTENT"
PR_GATE_SOURCE_FRESHNESS_NOT_PROVEN = "PR_GATE_SOURCE_FRESHNESS_NOT_PROVEN"
PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN = "PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN"
PR_GATE_HOST_PROVIDER_READ = "PR_GATE_HOST_PROVIDER_READ"
PR_GATE_FRESH_REVALIDATION_IN_CALL = "PR_GATE_FRESH_REVALIDATION_IN_CALL"
PR_GATE_SOURCE_NOT_AUTHENTICATED = "PR_GATE_SOURCE_NOT_AUTHENTICATED"
PR_GATE_HUMAN_DECISION_MISSING = "PR_GATE_HUMAN_DECISION_MISSING"
PR_GATE_HUMAN_APPROVAL_REQUIRED = "PR_GATE_HUMAN_APPROVAL_REQUIRED"
PR_GATE_NOT_MERGE_READINESS = "PR_GATE_NOT_MERGE_READINESS"
PR_GATE_NOT_AUTHORIZATION = "PR_GATE_NOT_AUTHORIZATION"

_MODE_CODES = {
    MODE_SUPPLIED_SNAPSHOT: (PR_GATE_SOURCE_FRESHNESS_NOT_PROVEN, PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN),
    MODE_HOST_PROVIDER_READ: (PR_GATE_HOST_PROVIDER_READ, PR_GATE_FRESH_REVALIDATION_IN_CALL),
}
_ALWAYS = (PR_GATE_SOURCE_NOT_AUTHENTICATED, PR_GATE_HUMAN_DECISION_MISSING, PR_GATE_HUMAN_APPROVAL_REQUIRED,
           PR_GATE_NOT_MERGE_READINESS, PR_GATE_NOT_AUTHORIZATION)
_REVIEWABLE = {MODE_SUPPLIED_SNAPSHOT: REVIEWABLE_UNVERIFIED_SNAPSHOT, MODE_HOST_PROVIDER_READ: REVIEWABLE_HOST_READ}

# The exact reason codes of a FCP-3B-1 fresh-read match.
_FRESH_MATCH_REASONS = (
    rpa.INTENT_MATCHES_FRESH_READINESS, rpa.INTENT_FRESH_FCP3A_READ, rpa.INTENT_VALIDATION_NOT_APPROVAL,
    rpa.INTENT_HUMAN_APPROVAL_REQUIRED, rpa.INTENT_NOT_AUTHORIZATION,
)
_CONCLUSION_CODES = {
    "success": None, "failure": PR_GATE_CHECK_FAILED, "timed_out": PR_GATE_CHECK_FAILED,
    "startup_failure": PR_GATE_CHECK_FAILED, "action_required": PR_GATE_CHECK_FAILED,
    "cancelled": PR_GATE_CHECK_CANCELLED, "skipped": PR_GATE_CHECK_SKIPPED,
    "neutral": PR_GATE_CHECK_NOT_SUCCESS, "stale": PR_GATE_CHECK_NOT_SUCCESS,
}
_MOVED_STATUSES = ("renamed", "copied")
_ANOMALOUS_STATUSES = ("changed", "unchanged")   # type change (symlink/submodule) or no-op: not modeled
_PATH_BAD_CHARS = frozenset('\\:"*?[]<>|')
_PATH_BAD_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"))
_GIT_SHORT_NAME = re.compile(r"git~[0-9]+", re.IGNORECASE)
_HEADS = "refs/heads/"


# ---------------------------------------------------------------------------
# Provider-neutral PR facts (immutable, untrusted input)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PullRequestMetadata:
    """One PR as read from the host. `base_branch_sha` is the CURRENT tip of
    the base branch, read separately from the PR's own `base_sha`."""

    repository: str
    number: int
    state: str
    merged: bool
    draft: bool
    base_repository: str
    base_ref: str
    base_sha: str
    head_repository: str
    head_ref: str
    head_sha: str
    base_branch_sha: str
    changed_files: int


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    previous_path: Optional[str] = None


@dataclass(frozen=True)
class ChangedFileListing:
    """The complete changed-file set: every page, with explicit counts."""

    files: tuple
    reported_total: int
    page_size: int
    pages_fetched: int
    complete: bool


@dataclass(frozen=True)
class CheckRun:
    name: str
    check_run_id: int
    head_sha: str
    status: str
    conclusion: Optional[str]
    app_slug: str
    workflow_name: Optional[str]
    workflow_path: Optional[str]
    workflow_run_id: Optional[int]
    event: Optional[str]
    pull_request_numbers: tuple


@dataclass(frozen=True)
class BranchPolicy:
    """The rules that apply to the base branch. `complete` is the host's
    statement that every applicable rule is listed."""

    base_ref: str
    rule_types: tuple
    required_check_names: tuple
    complete: bool


@dataclass(frozen=True)
class RequiredCheckListing:
    """Every check run of the head SHA (explicit count) and the base branch
    policy (None when the host could not read it)."""

    policy: Optional[BranchPolicy]
    runs: tuple
    reported_total: int
    complete: bool


@dataclass(frozen=True)
class PullRequestSnapshot:
    pull_request: Optional[PullRequestMetadata]
    changed_files: ChangedFileListing
    checks: RequiredCheckListing
    schema: str = SNAPSHOT_SCHEMA


class PullRequestMetadataProvider(Protocol):
    """Host-supplied, read-only. Receives only plain identifiers; it is never
    given, and must not hold, write authority. Each method is called at most
    once per `read_pr_gate`. This module cannot authenticate what it returns."""

    def read_pull_request(self, repository: str, number: int) -> Optional[PullRequestMetadata]: ...

    def read_changed_files(self, repository: str, number: int) -> ChangedFileListing: ...

    def read_required_checks(self, repository: str, base_ref: str, head_sha: str) -> RequiredCheckListing: ...


_SNAPSHOT_TYPES = (PullRequestSnapshot, PullRequestMetadata, ChangedFileListing, ChangedFile,
                   RequiredCheckListing, CheckRun, BranchPolicy)


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrGateContext:
    """The ONE PR an evaluation is bound to, derived from a verified intent
    and validation plus the host-chosen PR number. Identity, not consent."""

    repository: str
    pr_number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    authorized_scopes: tuple
    intent_fingerprint: str
    validation_fingerprint: str
    fingerprint: str
    schema: str = CONTEXT_SCHEMA


@dataclass(frozen=True)
class PrGateResult:
    """Read-only gate outcome. `candidate_reviewable=True` only means the PR
    metadata appears consistent for a human decision; it never authorizes or
    allows any action."""

    classification: str
    candidate_reviewable: bool
    reason_codes: tuple
    fingerprint: str
    mode: str
    context: Optional[PrGateContext]
    snapshot_fingerprint: Optional[str]
    changed_path_count: int
    out_of_scope_path_count: int
    check_run_count: int
    required_checks: tuple
    satisfied_checks: tuple
    ci_workflow_run_id: Optional[int]
    policy_proven: bool
    source_freshness_proven: bool
    source_authenticated: bool = False
    human_decision_present: bool = False
    human_approval_required: bool = True
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = RESULT_SCHEMA


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

def _payload(value) -> dict:
    return {f.name: rr._canonical(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name != "fingerprint"}


def context_fingerprint(context: PrGateContext) -> str:
    """Recomputes the canonical context fingerprint (identity, not consent)."""
    return rr._digest(_payload(context))


def result_fingerprint(result: PrGateResult) -> str:
    """Recomputes the canonical result fingerprint (identity, not consent)."""
    return rr._digest(_payload(result))


def snapshot_fingerprint(snapshot: PullRequestSnapshot) -> str:
    """Canonical digest of a snapshot's content (not of its origin)."""
    return rr._digest(rr._canonical(snapshot))


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------

def _plain(value) -> bool:
    """Exact built-in scalars, tuples of them and the exact snapshot types
    only: overridden comparisons cannot subvert any check."""
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is tuple:
        return all(_plain(v) for v in value)
    return type(value) in _SNAPSHOT_TYPES and all(_plain(getattr(value, f.name)) for f in dataclasses.fields(value))


def _int(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _unique_texts(values) -> bool:
    return type(values) is tuple and all(rpa._text(v) for v in values) and len(set(values)) == len(values)


def _sha_format(sha) -> Optional[str]:
    return next((f for f in ri._SHA_PATTERNS if ri._is_sha(sha, f)), None)


def _intent_errors(intent) -> list:
    codes = rpa._intent_errors(intent)
    return [PR_GATE_INTENT_INVALID, *codes] if codes else []


def _validation_errors(validation, intent) -> list:
    """`validation` must be a FCP-3B-1 fresh-read match of exactly `intent`.
    Its digest is unkeyed: a caller can recreate a consistent one, so the
    pure path never claims its provenance."""
    if type(validation) is not rpa.PromotionIntentValidation or not rpa._all_plain(validation):
        return [PR_GATE_VALIDATION_MALFORMED]
    try:
        tampered = validation.fingerprint != rpa.validation_fingerprint(validation)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        tampered = True
    if tampered or validation.schema != rpa.VALIDATION_SCHEMA or validation.human_approval_required is not True \
            or validation.authorizes_action is not False or validation.execution_allowed is not False:
        return [PR_GATE_VALIDATION_TAMPERED]
    errors = []
    if validation.mode != rpa.MODE_FRESH_FCP3A_READ:
        errors.append(PR_GATE_VALIDATION_NOT_FRESH_MODE)
    if validation.valid is not True or validation.outcome != rpa.MATCHES_PROPOSAL:
        errors.append(PR_GATE_VALIDATION_NOT_VALID)
    if not errors and (validation.reason_codes != _FRESH_MATCH_REASONS or validation.mismatched_fields != ()
                       or validation.fresh_readiness_classification != rp.AWAITING_HUMAN_APPROVAL):
        errors.append(PR_GATE_VALIDATION_TAMPERED)  # self-consistent digest, impossible content
    if validation.intent_fingerprint != intent.fingerprint \
            or validation.fresh_readiness_fingerprint != intent.readiness_fingerprint:
        errors.append(PR_GATE_VALIDATION_INTENT_MISMATCH)
    return errors


def _context(intent, validation, pr_number: int) -> PrGateContext:
    draft = PrGateContext(
        repository=CANONICAL_REPOSITORY, pr_number=pr_number, base_ref=BASE_BRANCH, base_sha=intent.base_sha,
        head_ref=intent.head_ref[len(_HEADS):], head_sha=intent.head_sha, authorized_scopes=intent.authorized_scopes,
        intent_fingerprint=intent.fingerprint, validation_fingerprint=validation.fingerprint, fingerprint="",
    )
    return dataclasses.replace(draft, fingerprint=context_fingerprint(draft))


def _pr_errors(pr, ctx: PrGateContext, fmt: str) -> list:
    if pr is None:
        return [PR_GATE_PR_MISSING]
    if type(pr) is not PullRequestMetadata:
        return [PR_GATE_SNAPSHOT_MALFORMED]
    errors = []
    if not _int(pr.number, 1, MAX_PR_NUMBER) or pr.number != ctx.pr_number:
        errors.append(PR_GATE_PR_NUMBER_MISMATCH)
    if pr.repository != ctx.repository or pr.base_repository != ctx.repository:
        errors.append(PR_GATE_REPOSITORY_MISMATCH)
    if pr.head_repository != ctx.repository:
        errors.append(PR_GATE_FORK_OR_FOREIGN_HEAD)
    if pr.state not in PR_STATES or type(pr.merged) is not bool or type(pr.draft) is not bool:
        errors.append(PR_GATE_PR_STATE_UNKNOWN)
    else:
        if pr.state == "closed":
            errors.append(PR_GATE_PR_CLOSED)
        if pr.merged:
            errors.append(PR_GATE_PR_MERGED)
            if pr.state == "open":
                errors.append(PR_GATE_PR_INCONSISTENT)
        if pr.draft:
            errors.append(PR_GATE_PR_DRAFT)
    if pr.base_ref != ctx.base_ref:
        errors.append(PR_GATE_BASE_REF_INVALID)
    if pr.head_ref != ctx.head_ref:
        errors.append(PR_GATE_HEAD_REF_MISMATCH)
    if not all(ri._is_sha(s, fmt) for s in (pr.base_sha, pr.head_sha, pr.base_branch_sha)):
        return errors + [PR_GATE_SHA_INVALID]
    if pr.head_sha != ctx.head_sha:
        errors.append(PR_GATE_STALE_HEAD)
    if pr.base_sha != ctx.base_sha or pr.base_branch_sha != ctx.base_sha:
        errors.append(PR_GATE_STALE_BASE)
    return errors


def _path_ok(path) -> bool:
    """Conservative: NFC, printable, no Windows-special or glob characters,
    no empty / dot / trailing-dot-or-space segment, no `.git` component."""
    if not rpa._text(path) or len(path) > 4096 or unicodedata.normalize("NFC", path) != path:
        return False
    if _PATH_BAD_CHARS & set(path) or any(unicodedata.category(ch) in _PATH_BAD_CATEGORIES for ch in path):
        return False
    return all(seg and seg.strip() == seg and not seg.endswith(".") and seg.casefold() != ".git"
               and not _GIT_SHORT_NAME.fullmatch(seg) for seg in path.split("/"))


def _in_scope(path: str, scopes: tuple) -> bool:
    """Exact path-segment subtree semantics (scopes are FCP-1 canonical)."""
    return any(path == scope or path.startswith(scope + "/") for scope in scopes)


def _file_findings(listing, pr, ctx: PrGateContext):
    """(errors, changed_path_count, out_of_scope_path_count)."""
    if type(listing) is not ChangedFileListing or type(listing.files) is not tuple \
            or not all(type(f) is ChangedFile for f in listing.files):
        return [PR_GATE_SNAPSHOT_MALFORMED], 0, 0
    files = listing.files
    count = len(files)
    pr_total = pr.changed_files if type(pr) is PullRequestMetadata else None
    pages_ok = _int(listing.page_size, 1, MAX_PAGE_SIZE) and _int(listing.pages_fetched, 1, MAX_CHANGED_FILES) \
        and listing.pages_fetched == max(1, -(-count // listing.page_size))
    errors = []
    if listing.complete is not True or not pages_ok or not _int(listing.reported_total, 0, MAX_CHANGED_FILES) \
            or listing.reported_total != count or type(pr_total) is not int or pr_total != count:
        errors.append(PR_GATE_FILES_INCOMPLETE)
    if count == 0:
        errors.append(PR_GATE_FILES_MISSING)
    seen, out_of_scope = set(), 0
    for f in files:
        paths = (f.path,) if f.previous_path is None else (f.path, f.previous_path)
        if not all(_path_ok(p) for p in paths):
            errors.append(PR_GATE_PATH_INVALID)
            continue
        if f.status not in FILE_STATUSES:
            errors.append(PR_GATE_FILE_STATUS_UNKNOWN)
        elif f.status in _ANOMALOUS_STATUSES or (f.status in _MOVED_STATUSES) != (f.previous_path is not None) \
                or f.previous_path == f.path or f.path in seen:
            errors.append(PR_GATE_PATH_ANOMALY)
        seen.add(f.path)
        # A rename or copy is in scope only if BOTH its source and target are.
        if not all(_in_scope(p, ctx.authorized_scopes) for p in paths):
            out_of_scope += 1
    if out_of_scope:
        errors.append(PR_GATE_PATH_OUT_OF_SCOPE)
    return errors, count, out_of_scope


def _run_shape_ok(check) -> bool:
    return type(check) is CheckRun and rpa._text(check.name) and _int(check.check_run_id, 1, MAX_ID) \
        and type(check.head_sha) is str and type(check.status) is str \
        and (check.conclusion is None or type(check.conclusion) is str) and rpa._text(check.app_slug) \
        and all(v is None or rpa._text(v) for v in (check.workflow_name, check.workflow_path, check.event)) \
        and (check.workflow_run_id is None or _int(check.workflow_run_id, 1, MAX_ID)) \
        and type(check.pull_request_numbers) is tuple \
        and all(_int(n, 1, MAX_PR_NUMBER) for n in check.pull_request_numbers)


def _run_state(check) -> Optional[str]:
    """None for completed success, otherwise the stable code."""
    if check.status not in CHECK_STATUSES \
            or (check.conclusion is not None and check.conclusion not in CHECK_CONCLUSIONS):
        return PR_GATE_CHECK_STATUS_UNKNOWN
    if check.status != "completed":
        return PR_GATE_CHECK_PENDING if check.conclusion is None else PR_GATE_CHECK_STATUS_UNKNOWN
    if check.conclusion is None:
        return PR_GATE_CHECK_STATUS_UNKNOWN
    return _CONCLUSION_CODES[check.conclusion]


def _policy_findings(policy):
    """(errors, policy_codes, extra required check names)."""
    if policy is None:
        return [], [PR_GATE_POLICY_NOT_PROVEN], ()
    if type(policy) is not BranchPolicy or not _unique_texts(policy.rule_types) \
            or not _unique_texts(policy.required_check_names) or type(policy.complete) is not bool:
        return [PR_GATE_SNAPSHOT_MALFORMED], [], ()
    codes = []
    if set(policy.rule_types) - set(MODELED_POLICY_RULES):
        codes.append(PR_GATE_POLICY_RULE_UNMODELED)
    if policy.complete is not True or policy.base_ref != BASE_BRANCH or codes \
            or ("required_status_checks" in policy.rule_types) != bool(policy.required_check_names):
        codes.append(PR_GATE_POLICY_NOT_PROVEN)
    extra = tuple(sorted(n for n in policy.required_check_names if n not in REQUIRED_CI_JOBS))
    return [], codes, extra


def _check_findings(listing, ctx: PrGateContext, fmt: str) -> dict:
    found = dict(errors=[], policy=[], required=REQUIRED_CI_JOBS, satisfied=(), run_count=0, ci_run_id=None)
    if type(listing) is not RequiredCheckListing or type(listing.runs) is not tuple \
            or not all(_run_shape_ok(r) for r in listing.runs):
        found["errors"] = [PR_GATE_SNAPSHOT_MALFORMED]
        return found
    runs = listing.runs
    errors = []
    if listing.complete is not True or not _int(listing.reported_total, 0, MAX_ID) \
            or listing.reported_total != len(runs):
        errors.append(PR_GATE_CHECKS_INCOMPLETE)
    if any(not ri._is_sha(r.head_sha, fmt) or r.head_sha != ctx.head_sha for r in runs):
        errors.append(PR_GATE_CHECK_HEAD_MISMATCH)
    if any(_run_state(r) == PR_GATE_CHECK_STATUS_UNKNOWN for r in runs):
        errors.append(PR_GATE_CHECK_STATUS_UNKNOWN)
    if len({r.check_run_id for r in runs}) != len(runs):
        errors.append(PR_GATE_CHECK_DUPLICATE)
    policy_errors, policy_codes, extra = _policy_findings(listing.policy)
    errors += policy_errors
    required = REQUIRED_CI_JOBS + extra
    satisfied, ci_run_ids = [], set()
    for name in required:
        matching = [r for r in runs if r.name == name]
        if len(matching) != 1:
            errors.append(PR_GATE_CHECK_MISSING if not matching else PR_GATE_CHECK_DUPLICATE)
            continue
        check = matching[0]
        problems = [code for code in (_run_state(check),) if code]
        if check.head_sha != ctx.head_sha:
            problems.append(PR_GATE_CHECK_HEAD_MISMATCH)
        if name in REQUIRED_CI_JOBS:
            # Green is never inferred from the workflow: each job's own run
            # must be bound to the Fabric CI workflow of THIS pull request.
            if check.app_slug != CI_APP_SLUG or check.workflow_name != CI_WORKFLOW_NAME \
                    or check.workflow_path != CI_WORKFLOW_PATH or check.workflow_run_id is None \
                    or ctx.pr_number not in check.pull_request_numbers:
                problems.append(PR_GATE_CHECK_BINDING_MISMATCH)
            if check.event != CI_EVENT:
                problems.append(PR_GATE_CHECK_EVENT_MISMATCH)
            ci_run_ids.add(check.workflow_run_id)
        errors += problems
        if not problems:
            satisfied.append(name)
    if len(ci_run_ids) > 1:
        errors.append(PR_GATE_CHECK_RUN_CONFLICT)
    ci_run_id = next(iter(ci_run_ids)) if len(ci_run_ids) == 1 else None
    found.update(errors=errors, policy=policy_codes, required=required, satisfied=tuple(satisfied),
                 run_count=len(runs), ci_run_id=ci_run_id if type(ci_run_id) is int else None,
                 policy_proven=not policy_errors and not policy_codes)
    return found


def _snapshot_findings(snapshot, ctx: PrGateContext) -> dict:
    found = dict(errors=[], policy=[], required=REQUIRED_CI_JOBS, satisfied=(), run_count=0, ci_run_id=None,
                 changed=0, out_of_scope=0)
    if snapshot is None:
        found["errors"] = [PR_GATE_PR_MISSING]
        return found
    if type(snapshot) is not PullRequestSnapshot or not _plain(snapshot) or snapshot.schema != SNAPSHOT_SCHEMA:
        found["errors"] = [PR_GATE_SNAPSHOT_MALFORMED]
        return found
    fmt = _sha_format(ctx.head_sha)
    pr_errors = _pr_errors(snapshot.pull_request, ctx, fmt)
    file_errors, changed, out_of_scope = _file_findings(snapshot.changed_files, snapshot.pull_request, ctx)
    found.update(_check_findings(snapshot.checks, ctx, fmt))
    found.update(errors=pr_errors + file_errors + found["errors"], changed=changed, out_of_scope=out_of_scope)
    return found


def _result(mode: str, context=None, errors=(), snapshot=None, found=None) -> PrGateResult:
    found = found or {}
    errors = list(dict.fromkeys(errors))
    policy = list(dict.fromkeys(found.get("policy", ())))
    if errors or context is None:
        classification = REJECTED
    elif policy:
        classification = POLICY_NOT_PROVEN
    else:
        classification = _REVIEWABLE[mode]
    reviewable = classification == _REVIEWABLE[mode]
    reasons = errors + policy + ([PR_GATE_METADATA_CONSISTENT] if reviewable else []) \
        + list(_MODE_CODES[mode]) + list(_ALWAYS)
    snap_fp = snapshot_fingerprint(snapshot) if type(snapshot) is PullRequestSnapshot and _plain(snapshot) else None
    draft = PrGateResult(
        classification=classification, candidate_reviewable=reviewable,
        reason_codes=tuple(dict.fromkeys(reasons)), fingerprint="", mode=mode, context=context,
        snapshot_fingerprint=snap_fp, changed_path_count=found.get("changed", 0),
        out_of_scope_path_count=found.get("out_of_scope", 0), check_run_count=found.get("run_count", 0),
        required_checks=found.get("required", REQUIRED_CI_JOBS), satisfied_checks=found.get("satisfied", ()),
        ci_workflow_run_id=found.get("ci_run_id"), policy_proven=found.get("policy_proven", False) is True,
        source_freshness_proven=mode == MODE_HOST_PROVIDER_READ,
    )
    return dataclasses.replace(draft, fingerprint=result_fingerprint(draft))


def _bind(intent, validation, pr_number):
    """(context, errors): the context exists only if everything binds."""
    errors = [] if _int(pr_number, 1, MAX_PR_NUMBER) else [PR_GATE_PR_NUMBER_INVALID]
    intent_errors = _intent_errors(intent)
    if intent_errors:
        return None, errors + intent_errors
    errors += _validation_errors(validation, intent)
    return (None if errors else _context(intent, validation, pr_number)), errors


def _evaluate(intent, validation, snapshot, pr_number, mode: str) -> PrGateResult:
    context, errors = _bind(intent, validation, pr_number)
    if context is None:
        return _result(mode, None, errors, snapshot)
    found = _snapshot_findings(snapshot, context)
    return _result(mode, context, found["errors"], snapshot, found)


def evaluate_pr_gate(intent, validation, pr_snapshot, *, pr_number) -> PrGateResult:
    """Pure, fail-closed: does `pr_snapshot` describe PR `pr_number` of the
    canonical repository consistently with `intent` and its fresh FCP-3B-1
    `validation`? Never raises. The snapshot and validation are caller
    supplied (freshness and provenance not proven); nothing is authorized."""
    try:
        return _evaluate(intent, validation, pr_snapshot, pr_number, MODE_SUPPLIED_SNAPSHOT)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _result(MODE_SUPPLIED_SNAPSHOT, None, [PR_GATE_EVALUATION_FAILED])


# ---------------------------------------------------------------------------
# Host read (one FCP-3B-1 revalidation, at most one provider read per kind)
# ---------------------------------------------------------------------------

def _read_snapshot(provider, context: PrGateContext):
    """(snapshot, failed). Stops at the first failing read; each method is
    called at most once, with plain identifiers taken from the context."""
    reads = (
        ("read_pull_request", (context.repository, context.pr_number)),
        ("read_changed_files", (context.repository, context.pr_number)),
        ("read_required_checks", (context.repository, context.base_ref, context.head_sha)),
    )
    values = []
    for method, args in reads:
        try:
            values.append(getattr(provider, method)(*args))
        except Exception:  # noqa: BLE001 - no provider detail is exposed
            return None, True
    return PullRequestSnapshot(pull_request=values[0], changed_files=values[1], checks=values[2]), False


def read_pr_gate(
    intent, provider, worktree, *, pr_number, attested_sha: Optional[str], authorized_scopes,
    expected_remote_url: Optional[str] = None, evidence=None, ledger_root=None, lease_root=None,
    max_paths: int = rr.MAX_PATHS,
) -> PrGateResult:
    """Read-only host evaluation: exactly one FCP-3B-1
    `revalidate_promotion_intent` (inputs forwarded unchanged) and, only if
    it is a valid fresh match, at most one call of each provider method.
    FCP-3A input refusals propagate unchanged; any other failure is a
    REJECTED result. The provider is not authenticated here and the reads are
    not atomic; nothing is authorized."""
    try:
        refused = ([] if _int(pr_number, 1, MAX_PR_NUMBER) else [PR_GATE_PR_NUMBER_INVALID]) + _intent_errors(intent)
    except Exception:  # noqa: BLE001
        refused = [PR_GATE_EVALUATION_FAILED]
    if refused:  # nothing is read for an unbindable request
        return _result(MODE_HOST_PROVIDER_READ, None, refused)
    validation = rpa.revalidate_promotion_intent(
        intent, worktree, attested_sha=attested_sha, authorized_scopes=authorized_scopes,
        expected_remote_url=expected_remote_url, evidence=evidence, ledger_root=ledger_root,
        lease_root=lease_root, max_paths=max_paths,
    )
    try:
        context, errors = _bind(intent, validation, pr_number)
        if context is None:
            return _result(MODE_HOST_PROVIDER_READ, None, errors)
        snapshot, failed = _read_snapshot(provider, context)
        if failed:
            return _result(MODE_HOST_PROVIDER_READ, context, [PR_GATE_PROVIDER_READ_FAILED])
        found = _snapshot_findings(snapshot, context)
        return _result(MODE_HOST_PROVIDER_READ, context, found["errors"], snapshot, found)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _result(MODE_HOST_PROVIDER_READ, None, [PR_GATE_EVALUATION_FAILED])

"""FCP-3B-2B1: human decision evidence and authorization boundary (NON-EXECUTABLE).

Canonical promotion is GitHub Pull Request -> seven Fabric CI jobs green ->
independent human authorization -> execution by a governed host, never a
direct push or ref update to `develop`. This module is the first slice of
FCP-3B-2B: it checks whether the GitHub review events of ONE pull request,
already found reviewable by the FCP-3B-2A gate, LOOK like a consistent,
current, favorable human review. It never merges, approves, comments, pushes,
fetches, writes refs or files, opens network connections, runs processes,
reads Git, reads the environment or keeps durable state. It closes neither
FCP-3B-2B nor FCP-3.

Decision identity (`HumanDecisionIdentity`)
-------------------------------------------
Bound to the canonical repository, PR number, base ref and SHA, head ref and
SHA, FCP-3B-1 intent and validation fingerprints and the FCP-3B-2A context
and result fingerprints. Every value is copied from a `PrGateResult` whose
fingerprints, invariants and exact reason codes are recomputed here, and
whose context is re-derived from the supplied FCP-3B-1 intent and validation
with the gate's own binding (`runner_promotion_pr_gate._bind`). A gate that
is not reviewable, has an unproven policy, does not show the seven required
jobs (plus every policy check) satisfied by one CI run, or was altered is
REJECTED. No URL or title is identity. Gate digests are unkeyed: a caller can
rebuild a byte-identical gate, so its provenance and freshness are never
claimed (HAUTH_GATE_PROVENANCE_NOT_PROVEN, HAUTH_GATE_FRESHNESS_NOT_PROVEN).

Review evidence (`ReviewEventSequence`)
---------------------------------------
GitHub pull request reviews in listing order, with explicit pagination, the
PR's current head SHA, its author id, the head commit author id when known
and the instant of the read. Rejected (REJECTED): missing, malformed or
incomplete listings, duplicate ids, unordered or invalid timestamps (only
`YYYY-MM-DDTHH:MM:SSZ`), timestamps after the read or a read in the future,
a read older than MAX_SNAPSHOT_AGE_SECONDS, a moved PR head, events of
another repository or PR, unknown states (including PENDING), invalid or
inconsistent actors, decisive reviews of non-human actors and approvals by
the PR author or the known head commit author.

The latest DECISIVE review per reviewer counts (APPROVED, CHANGES_REQUESTED,
DISMISSED); COMMENTED never grants nor revokes, as on GitHub. Only a latest
APPROVED review on the current head SHA counts. A later CHANGES_REQUESTED or
DISMISSED review annuls an earlier approval, and a dismissed review never
revives an older one (stricter than GitHub, never looser). Any blocking
reviewer or no current approval is REVIEW_NOT_FAVORABLE. Whether a "User"
account is operated by a human, and who wrote the head commit when the host
does not say, are not provable from these data (HAUTH_HUMANITY_UNPROVEN,
HAUTH_COMMIT_AUTHOR_UNPROVEN).

Three planes, kept apart
------------------------
a) `review_evidence_consistent`: the review data look structurally sound.
b) `authenticated_human_command_present` / `human_command_authenticated`:
   ALWAYS False here. No authenticated human command source exists yet.
c) `authorizes_action` / `execution_allowed`: ALWAYS False.
No comment, reviewer, GitHub approval, CI result, fingerprint, token or nonce
chosen by a caller or provider authorizes anything, and no input claims
approval, trust or a signature.

Evaluation
----------
`evaluate_human_decision_evidence` (pure) checks a caller-supplied sequence
(REVIEW_CONSISTENT_UNVERIFIED at best, `source_unverified=True`).
`read_human_decision_evidence` makes at most one call of a host-supplied
read-only `ReviewEventProvider`, passing only the repository and PR number;
the read is not authenticated by this module (REVIEW_READ_UNAUTHENTICATED at
best) and a provider failure is REJECTED. Nothing received is mutated.
Fingerprints are SHA-256 digests of canonical JSON for identity and
accidental-integrity checks only, never authentication or signature.

Requirements for the future executor (NOT implemented, NOT a permission)
------------------------------------------------------------------------
A separately reviewed, privileged host executor may act only if it proves,
itself, all of `FUTURE_EXECUTOR_REQUIREMENTS`:
- an authenticated identity of the human Director, independent of the
  Runner, Claude, Codex or any provider (which hold no keys and no remote
  write permission);
- an authorization specific to ONE PR + head SHA + base ref/SHA + action,
  with a short expiry, a revocation check and a single-use consumption
  ledger, consumed under a lock/lease;
- a fresh verification immediately before the operation: this evidence,
  the FCP-3B-2A gate and protected CI (the seven Fabric CI jobs and every
  check the branch policy requires) on the exact head SHA;
- the operation only through the GitHub Pull Request Merge API with the
  expected head SHA, under branch protection or the merge queue;
- post-confirmation that the PR is merged and `develop` holds the expected
  new commit, recording races and uncertain states for audit.
If the host cannot prove every capability it must BLOCK. It must never fall
back to direct Git writes. This module's results are never such proof.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol

try:
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_promotion_authorization as rpa
    from scripts.ai import runner_promotion_pr_gate as rpg
    from scripts.ai import runner_reconciliation as rr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_promotion_authorization as rpa  # type: ignore[no-redef]
    import runner_promotion_pr_gate as rpg  # type: ignore[no-redef]
    import runner_reconciliation as rr  # type: ignore[no-redef]


EVENT_SCHEMA = "fcp3b2b1-review-event-v1"
SEQUENCE_SCHEMA = "fcp3b2b1-review-sequence-v1"
IDENTITY_SCHEMA = "fcp3b2b1-decision-identity-v1"
RESULT_SCHEMA = "fcp3b2b1-human-decision-evaluation-v1"

# GitHub review states. Anything else (PENDING included) is unknown.
APPROVED = "APPROVED"
CHANGES_REQUESTED = "CHANGES_REQUESTED"
DISMISSED = "DISMISSED"
COMMENTED = "COMMENTED"
REVIEW_STATES = (APPROVED, CHANGES_REQUESTED, DISMISSED, COMMENTED)
DECISIVE_STATES = (APPROVED, CHANGES_REQUESTED, DISMISSED)

# GitHub account types; only a "User" without a bot login may be human.
ACTOR_TYPES = ("User", "Bot", "Organization", "Mannequin")
HUMAN_ACTOR_TYPE = "User"

MAX_ID = rpg.MAX_ID
MAX_REVIEWS = 10000
MAX_PAGE_SIZE = 100
MAX_SNAPSHOT_AGE_SECONDS = 300

# Classifications.
REJECTED = "REJECTED"
REVIEW_NOT_FAVORABLE = "REVIEW_NOT_FAVORABLE"
REVIEW_CONSISTENT_UNVERIFIED = "REVIEW_CONSISTENT_UNVERIFIED"
REVIEW_READ_UNAUTHENTICATED = "REVIEW_READ_UNAUTHENTICATED"
CLASSIFICATIONS = (REJECTED, REVIEW_NOT_FAVORABLE, REVIEW_CONSISTENT_UNVERIFIED, REVIEW_READ_UNAUTHENTICATED)

# Modes.
MODE_SUPPLIED_SNAPSHOT = "SUPPLIED_SNAPSHOT"
MODE_HOST_PROVIDER_READ = "HOST_PROVIDER_READ"

# Reason codes: binding to FCP-3B-2A / FCP-3B-1.
HAUTH_PR_NUMBER_INVALID = "HAUTH_PR_NUMBER_INVALID"
HAUTH_PR_NUMBER_MISMATCH = "HAUTH_PR_NUMBER_MISMATCH"
HAUTH_GATE_MALFORMED = "HAUTH_GATE_MALFORMED"
HAUTH_GATE_TAMPERED = "HAUTH_GATE_TAMPERED"
HAUTH_GATE_CONTEXT_MISSING = "HAUTH_GATE_CONTEXT_MISSING"
HAUTH_GATE_CONTEXT_TAMPERED = "HAUTH_GATE_CONTEXT_TAMPERED"
HAUTH_GATE_NOT_REVIEWABLE = "HAUTH_GATE_NOT_REVIEWABLE"
HAUTH_GATE_POLICY_NOT_PROVEN = "HAUTH_GATE_POLICY_NOT_PROVEN"
HAUTH_GATE_CHECKS_NOT_PROVEN = "HAUTH_GATE_CHECKS_NOT_PROVEN"
HAUTH_GATE_BINDING_MISMATCH = "HAUTH_GATE_BINDING_MISMATCH"
HAUTH_CLOCK_INVALID = "HAUTH_CLOCK_INVALID"
# Review evidence.
HAUTH_REVIEWS_MISSING = "HAUTH_REVIEWS_MISSING"
HAUTH_REVIEWS_MALFORMED = "HAUTH_REVIEWS_MALFORMED"
HAUTH_REVIEWS_INCOMPLETE = "HAUTH_REVIEWS_INCOMPLETE"
HAUTH_REVIEW_BINDING_MISMATCH = "HAUTH_REVIEW_BINDING_MISMATCH"
HAUTH_REVIEW_SHA_INVALID = "HAUTH_REVIEW_SHA_INVALID"
HAUTH_REVIEW_PR_HEAD_MOVED = "HAUTH_REVIEW_PR_HEAD_MOVED"
HAUTH_REVIEW_DUPLICATE_ID = "HAUTH_REVIEW_DUPLICATE_ID"
HAUTH_REVIEW_ORDER_INVALID = "HAUTH_REVIEW_ORDER_INVALID"
HAUTH_REVIEW_TIMESTAMP_INVALID = "HAUTH_REVIEW_TIMESTAMP_INVALID"
HAUTH_REVIEW_TIMESTAMP_FUTURE = "HAUTH_REVIEW_TIMESTAMP_FUTURE"
HAUTH_REVIEW_SNAPSHOT_STALE = "HAUTH_REVIEW_SNAPSHOT_STALE"
HAUTH_REVIEW_STATE_UNKNOWN = "HAUTH_REVIEW_STATE_UNKNOWN"
HAUTH_REVIEW_ACTOR_INVALID = "HAUTH_REVIEW_ACTOR_INVALID"
HAUTH_REVIEW_ACTOR_INCONSISTENT = "HAUTH_REVIEW_ACTOR_INCONSISTENT"
HAUTH_REVIEW_ACTOR_NOT_HUMAN = "HAUTH_REVIEW_ACTOR_NOT_HUMAN"
HAUTH_REVIEW_SELF_APPROVAL = "HAUTH_REVIEW_SELF_APPROVAL"
# Decision (consistent evidence, not favorable) and notes.
HAUTH_NO_CURRENT_APPROVAL = "HAUTH_NO_CURRENT_APPROVAL"
HAUTH_CHANGES_REQUESTED = "HAUTH_CHANGES_REQUESTED"
HAUTH_APPROVAL_STALE_COMMIT = "HAUTH_APPROVAL_STALE_COMMIT"
HAUTH_APPROVAL_DISMISSED = "HAUTH_APPROVAL_DISMISSED"
HAUTH_COMMIT_AUTHOR_UNPROVEN = "HAUTH_COMMIT_AUTHOR_UNPROVEN"
# Host read / internal.
HAUTH_PROVIDER_READ_FAILED = "HAUTH_PROVIDER_READ_FAILED"
HAUTH_EVALUATION_FAILED = "HAUTH_EVALUATION_FAILED"
# Positive and always-present codes.
HAUTH_REVIEW_EVIDENCE_CONSISTENT = "HAUTH_REVIEW_EVIDENCE_CONSISTENT"
HAUTH_REVIEW_APPEARS_FAVORABLE = "HAUTH_REVIEW_APPEARS_FAVORABLE"
HAUTH_SOURCE_UNVERIFIED_SNAPSHOT = "HAUTH_SOURCE_UNVERIFIED_SNAPSHOT"
HAUTH_HOST_PROVIDER_READ_UNAUTHENTICATED = "HAUTH_HOST_PROVIDER_READ_UNAUTHENTICATED"
HAUTH_SOURCE_NOT_AUTHENTICATED = "HAUTH_SOURCE_NOT_AUTHENTICATED"
HAUTH_GATE_PROVENANCE_NOT_PROVEN = "HAUTH_GATE_PROVENANCE_NOT_PROVEN"
HAUTH_GATE_FRESHNESS_NOT_PROVEN = "HAUTH_GATE_FRESHNESS_NOT_PROVEN"
HAUTH_HUMANITY_UNPROVEN = "HAUTH_HUMANITY_UNPROVEN"
HAUTH_HUMAN_COMMAND_NOT_AUTHENTICATED = "HAUTH_HUMAN_COMMAND_NOT_AUTHENTICATED"
HAUTH_HUMAN_AUTHORIZATION_REQUIRED = "HAUTH_HUMAN_AUTHORIZATION_REQUIRED"
HAUTH_EXECUTOR_CONTRACT_UNMET = "HAUTH_EXECUTOR_CONTRACT_UNMET"
HAUTH_NOT_AUTHORIZATION = "HAUTH_NOT_AUTHORIZATION"

_MODE_CODES = {
    MODE_SUPPLIED_SNAPSHOT: (HAUTH_SOURCE_UNVERIFIED_SNAPSHOT,),
    MODE_HOST_PROVIDER_READ: (HAUTH_HOST_PROVIDER_READ_UNAUTHENTICATED,),
}
_ALWAYS = (HAUTH_SOURCE_NOT_AUTHENTICATED, HAUTH_GATE_PROVENANCE_NOT_PROVEN, HAUTH_GATE_FRESHNESS_NOT_PROVEN,
           HAUTH_HUMANITY_UNPROVEN, HAUTH_HUMAN_COMMAND_NOT_AUTHENTICATED, HAUTH_HUMAN_AUTHORIZATION_REQUIRED,
           HAUTH_EXECUTOR_CONTRACT_UNMET, HAUTH_NOT_AUTHORIZATION)
_FAVORABLE = {MODE_SUPPLIED_SNAPSHOT: REVIEW_CONSISTENT_UNVERIFIED,
              MODE_HOST_PROVIDER_READ: REVIEW_READ_UNAUTHENTICATED}

# What a future executor must prove itself (module docstring). Every result
# lists all of them as unmet: this module proves none.
FUTURE_EXECUTOR_REQUIREMENTS = (
    "EXEC_REQ_AUTHENTICATED_HUMAN_DIRECTOR",
    "EXEC_REQ_AUTHORIZATION_BOUND_TO_PR_HEAD_BASE_ACTION",
    "EXEC_REQ_SHORT_EXPIRY",
    "EXEC_REQ_REVOCATION_CHECK",
    "EXEC_REQ_SINGLE_USE_CONSUMPTION_LEDGER",
    "EXEC_REQ_LOCK_OR_LEASE",
    "EXEC_REQ_FRESH_VERIFICATION_BEFORE_OPERATION",
    "EXEC_REQ_PROTECTED_CI_ALL_REQUIRED_CHECKS",
    "EXEC_REQ_PR_MERGE_API_WITH_EXPECTED_HEAD_SHA",
    "EXEC_REQ_BRANCH_PROTECTION_OR_MERGE_QUEUE",
    "EXEC_REQ_POSTCONDITION_PR_MERGED_AND_DEVELOP_ADVANCED",
    "EXEC_REQ_RACE_AND_UNCERTAIN_STATE_AUDIT",
    "EXEC_REQ_NO_DIRECT_GIT_WRITE",
)

# Audit dispositions (one per review event, in listing order).
AUDIT_COUNTED_APPROVAL = "COUNTED_APPROVAL"
AUDIT_STALE_COMMIT_APPROVAL = "STALE_COMMIT_APPROVAL"
AUDIT_BLOCKING_CHANGES_REQUESTED = "BLOCKING_CHANGES_REQUESTED"
AUDIT_DISMISSED = "DISMISSED"
AUDIT_SUPERSEDED = "SUPERSEDED"
AUDIT_NON_DECISIVE_COMMENT = "NON_DECISIVE_COMMENT"
AUDIT_IGNORED_NON_HUMAN = "IGNORED_NON_HUMAN"
AUDIT_SELF_APPROVAL = "SELF_APPROVAL"

_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
_BOT_SUFFIX = "[bot]"


# ---------------------------------------------------------------------------
# GitHub review facts (immutable, untrusted input)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewEvent:
    """One submitted GitHub pull request review, as listed by the host.
    Identity is the numeric actor id; the login is only cross-checked."""

    review_id: int
    repository: str
    pr_number: int
    actor_id: int
    actor_login: str
    actor_type: str
    state: str
    commit_sha: str
    submitted_at: str
    schema: str = EVENT_SCHEMA


@dataclass(frozen=True)
class ReviewEventSequence:
    """Every review of one PR in listing order, with explicit pagination.
    `pr_head_sha` is the PR head read together with the reviews,
    `head_commit_author_id` the GitHub id of the head commit author (None
    when unknown) and `observed_at` the instant of the read."""

    repository: str
    pr_number: int
    pr_head_sha: str
    pr_author_id: int
    head_commit_author_id: Optional[int]
    events: tuple
    reported_total: int
    page_size: int
    pages_fetched: int
    complete: bool
    observed_at: str
    schema: str = SEQUENCE_SCHEMA


class ReviewEventProvider(Protocol):
    """Host-supplied, read-only. Receives only the repository and PR number;
    it is never given, and must not hold, write authority. Called at most
    once per `read_human_decision_evidence`. Not authenticated here."""

    def read_review_events(self, repository: str, number: int) -> ReviewEventSequence: ...


_REVIEW_TYPES = (ReviewEventSequence, ReviewEvent)
_GATE_TYPES = (rpg.PrGateResult, rpg.PrGateContext)


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HumanDecisionIdentity:
    """The ONE PR, head and base a decision would concern, copied from a
    re-verified FCP-3B-2A gate. Identity, not consent."""

    repository: str
    pr_number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    intent_fingerprint: str
    validation_fingerprint: str
    gate_context_fingerprint: str
    gate_result_fingerprint: str
    fingerprint: str
    schema: str = IDENTITY_SCHEMA


@dataclass(frozen=True)
class ReviewAuditEntry:
    """How one review event was treated. Ids and states only, no text."""

    review_id: int
    actor_id: int
    state: str
    on_head_commit: bool
    submitted_at: str
    disposition: str


@dataclass(frozen=True)
class HumanDecisionEvaluation:
    """Review-evidence outcome. Even a favorable classification is only the
    appearance of a current human review: it never authenticates a human
    command and never authorizes or allows any action."""

    classification: str
    reason_codes: tuple
    fingerprint: str
    mode: str
    identity: Optional[HumanDecisionIdentity]
    review_sequence_fingerprint: Optional[str]
    review_event_count: int
    reviewer_count: int
    current_approver_ids: tuple
    blocking_reviewer_ids: tuple
    stale_approval_count: int
    audit_trail: tuple
    review_evidence_consistent: bool
    review_decision_appears_favorable: bool
    executor_requirements_unmet: tuple = FUTURE_EXECUTOR_REQUIREMENTS
    source_unverified: bool = True
    source_authenticated: bool = False
    authenticated_human_command_present: bool = False
    human_command_authenticated: bool = False
    human_authorization_required: bool = True
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = RESULT_SCHEMA


# ---------------------------------------------------------------------------
# Fingerprints (identity and accidental integrity; never authentication)
# ---------------------------------------------------------------------------

def _payload(value) -> dict:
    return {f.name: rr._canonical(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name != "fingerprint"}


def identity_fingerprint(identity: HumanDecisionIdentity) -> str:
    """Recomputes the canonical decision identity fingerprint."""
    return rr._digest(_payload(identity))


def evaluation_fingerprint(evaluation: HumanDecisionEvaluation) -> str:
    """Recomputes the canonical evaluation fingerprint."""
    return rr._digest(_payload(evaluation))


def review_event_fingerprint(event: ReviewEvent) -> str:
    """Canonical digest of one review event's content (not of its origin)."""
    return rr._digest(rr._canonical(event))


def review_sequence_fingerprint(sequence: ReviewEventSequence) -> str:
    """Canonical digest of a review sequence's content (not of its origin)."""
    return rr._digest(rr._canonical(sequence))


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------

def _plain(value, types) -> bool:
    """Exact built-in scalars, tuples of them and the exact given types only:
    overridden comparisons cannot subvert any check."""
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is tuple:
        return all(_plain(v, types) for v in value)
    return type(value) in types and all(_plain(getattr(value, f.name), types) for f in dataclasses.fields(value))


def _int(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _digest_ok(value) -> bool:
    return type(value) is str and rpa._DIGEST_RE.fullmatch(value) is not None


def _timestamp(value) -> Optional[datetime]:
    """UTC instant of a strict `YYYY-MM-DDTHH:MM:SSZ` string, else None."""
    if type(value) is not str or not _TIMESTAMP_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clock_ok(now) -> bool:
    return type(now) is datetime and now.tzinfo is not None and now.utcoffset() == timedelta(0)


def _checks_proven(gate) -> bool:
    """The seven Fabric CI jobs first, then the sorted policy extras, every one
    satisfied, by one CI workflow run."""
    required, jobs = gate.required_checks, rpg.REQUIRED_CI_JOBS
    if type(required) is not tuple or not all(rpa._text(n) for n in required):
        return False
    extra = required[len(jobs):]
    return required[:len(jobs)] == jobs and extra == tuple(sorted(set(extra))) and not set(extra) & set(jobs) \
        and gate.satisfied_checks == required and _int(gate.ci_workflow_run_id, 1, MAX_ID)


def _gate_errors(gate) -> list:
    """`gate` must be an unaltered, reviewable FCP-3B-2A result. Its digests
    are unkeyed: only impossible or inconsistent content is detectable."""
    if type(gate) is not rpg.PrGateResult or not _plain(gate, _GATE_TYPES):
        return [HAUTH_GATE_MALFORMED]
    try:
        tampered = gate.fingerprint != rpg.result_fingerprint(gate)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        tampered = True
    if tampered or gate.schema != rpg.RESULT_SCHEMA or gate.mode not in rpg._REVIEWABLE \
            or gate.human_approval_required is not True or gate.authorizes_action is not False \
            or gate.execution_allowed is not False or gate.source_authenticated is not False \
            or gate.human_decision_present is not False:
        return [HAUTH_GATE_TAMPERED]
    context = gate.context
    if context is None:
        return [HAUTH_GATE_NOT_REVIEWABLE, HAUTH_GATE_CONTEXT_MISSING]
    if type(context) is not rpg.PrGateContext:
        return [HAUTH_GATE_MALFORMED]
    try:
        context_tampered = context.fingerprint != rpg.context_fingerprint(context)
    except Exception:  # noqa: BLE001
        context_tampered = True
    if context_tampered or context.schema != rpg.CONTEXT_SCHEMA:
        return [HAUTH_GATE_CONTEXT_TAMPERED]
    errors = []
    if gate.classification != rpg._REVIEWABLE[gate.mode] or gate.candidate_reviewable is not True:
        errors.append(HAUTH_GATE_NOT_REVIEWABLE)
    if gate.policy_proven is not True:
        errors.append(HAUTH_GATE_POLICY_NOT_PROVEN)
    if not _checks_proven(gate):
        errors.append(HAUTH_GATE_CHECKS_NOT_PROVEN)
    if errors:
        return errors
    # A self-consistent digest over content the gate never produces.
    expected_reasons = (rpg.PR_GATE_METADATA_CONSISTENT, *rpg._MODE_CODES[gate.mode], *rpg._ALWAYS)
    if gate.reason_codes != expected_reasons \
            or gate.source_freshness_proven is not (gate.mode == rpg.MODE_HOST_PROVIDER_READ) \
            or gate.out_of_scope_path_count != 0 or not _int(gate.changed_path_count, 1, rpg.MAX_CHANGED_FILES) \
            or not _int(gate.check_run_count, len(gate.required_checks), MAX_ID) \
            or not _digest_ok(gate.snapshot_fingerprint):
        return [HAUTH_GATE_TAMPERED]
    return []


def _identity(gate) -> HumanDecisionIdentity:
    c = gate.context
    draft = HumanDecisionIdentity(
        repository=c.repository, pr_number=c.pr_number, base_ref=c.base_ref, base_sha=c.base_sha,
        head_ref=c.head_ref, head_sha=c.head_sha, intent_fingerprint=c.intent_fingerprint,
        validation_fingerprint=c.validation_fingerprint, gate_context_fingerprint=c.fingerprint,
        gate_result_fingerprint=gate.fingerprint, fingerprint="",
    )
    return dataclasses.replace(draft, fingerprint=identity_fingerprint(draft))


def _bind(gate, intent, validation, pr_number):
    """(identity, errors): the identity exists only if the gate is sound and
    its context is exactly the one the FCP-3B-2A binding derives from
    `intent`, `validation` and the host-chosen `pr_number`."""
    if not _int(pr_number, 1, rpg.MAX_PR_NUMBER):
        return None, [HAUTH_PR_NUMBER_INVALID]
    errors = _gate_errors(gate)
    if errors:
        return None, errors
    if gate.context.pr_number != pr_number:
        return None, [HAUTH_PR_NUMBER_MISMATCH]
    expected, bind_errors = rpg._bind(intent, validation, pr_number)
    if bind_errors or type(expected) is not rpg.PrGateContext or expected != gate.context:
        return None, [HAUTH_GATE_BINDING_MISMATCH, *bind_errors]
    return _identity(gate), []


def _is_human(event) -> bool:
    return event.actor_type == HUMAN_ACTOR_TYPE and not event.actor_login.endswith(_BOT_SUFFIX)


def _event_errors(event, identity, fmt) -> list:
    errors = []
    if not _int(event.review_id, 1, MAX_ID) or event.schema != EVENT_SCHEMA:
        errors.append(HAUTH_REVIEWS_MALFORMED)
    if event.repository != identity.repository or type(event.pr_number) is not int \
            or event.pr_number != identity.pr_number:
        errors.append(HAUTH_REVIEW_BINDING_MISMATCH)
    if not _int(event.actor_id, 1, MAX_ID) or type(event.actor_login) is not str \
            or not _LOGIN_RE.fullmatch(event.actor_login) or event.actor_type not in ACTOR_TYPES:
        errors.append(HAUTH_REVIEW_ACTOR_INVALID)
    if event.state not in REVIEW_STATES:
        errors.append(HAUTH_REVIEW_STATE_UNKNOWN)
    if not ri._is_sha(event.commit_sha, fmt):
        errors.append(HAUTH_REVIEW_SHA_INVALID)
    if _timestamp(event.submitted_at) is None:
        errors.append(HAUTH_REVIEW_TIMESTAMP_INVALID)
    return errors


def _sequence_errors(seq, identity, fmt, now) -> list:
    errors = []
    if seq.repository != identity.repository or type(seq.pr_number) is not int \
            or seq.pr_number != identity.pr_number:
        errors.append(HAUTH_REVIEW_BINDING_MISMATCH)
    if not ri._is_sha(seq.pr_head_sha, fmt):
        errors.append(HAUTH_REVIEW_SHA_INVALID)
    elif seq.pr_head_sha != identity.head_sha:
        errors.append(HAUTH_REVIEW_PR_HEAD_MOVED)
    if not _int(seq.pr_author_id, 1, MAX_ID) \
            or not (seq.head_commit_author_id is None or _int(seq.head_commit_author_id, 1, MAX_ID)):
        errors.append(HAUTH_REVIEW_ACTOR_INVALID)
    count = len(seq.events)
    pages_ok = _int(seq.page_size, 1, MAX_PAGE_SIZE) and _int(seq.pages_fetched, 1, MAX_REVIEWS) \
        and seq.pages_fetched == max(1, -(-count // seq.page_size))
    if seq.complete is not True or not pages_ok or not _int(seq.reported_total, 0, MAX_REVIEWS) \
            or seq.reported_total != count:
        errors.append(HAUTH_REVIEWS_INCOMPLETE)
    observed = _timestamp(seq.observed_at)
    if observed is None:
        errors.append(HAUTH_REVIEW_TIMESTAMP_INVALID)
    elif observed > now:
        errors.append(HAUTH_REVIEW_TIMESTAMP_FUTURE)
    elif now - observed > timedelta(seconds=MAX_SNAPSHOT_AGE_SECONDS):
        errors.append(HAUTH_REVIEW_SNAPSHOT_STALE)
    return errors


def _consistency_errors(events, observed) -> list:
    """Ids, order, timestamps and actor identities across well-formed events."""
    errors = []
    if len({e.review_id for e in events}) != len(events):
        errors.append(HAUTH_REVIEW_DUPLICATE_ID)
    instants = [_timestamp(e.submitted_at) for e in events]
    if any(a > b for a, b in zip(instants, instants[1:])):
        errors.append(HAUTH_REVIEW_ORDER_INVALID)
    if observed is not None and any(t > observed for t in instants):
        errors.append(HAUTH_REVIEW_TIMESTAMP_FUTURE)
    logins, ids = {}, {}
    for e in events:
        login = e.actor_login.casefold()
        if logins.setdefault(e.actor_id, login) != login or ids.setdefault(login, e.actor_id) != e.actor_id:
            errors.append(HAUTH_REVIEW_ACTOR_INCONSISTENT)
            break
    return errors


def _decide(seq, identity) -> dict:
    """Latest decisive review per human reviewer, plus the audit trail."""
    authors = {seq.pr_author_id} | ({seq.head_commit_author_id} if seq.head_commit_author_id is not None else set())
    errors, notes, dispositions, latest = [], [], {}, {}
    for index, e in enumerate(seq.events):
        if not _is_human(e):
            dispositions[index] = AUDIT_IGNORED_NON_HUMAN
            if e.state != COMMENTED:
                errors.append(HAUTH_REVIEW_ACTOR_NOT_HUMAN)
        elif e.state == APPROVED and e.actor_id in authors:
            dispositions[index] = AUDIT_SELF_APPROVAL
            errors.append(HAUTH_REVIEW_SELF_APPROVAL)
        elif e.state == COMMENTED:
            dispositions[index] = AUDIT_NON_DECISIVE_COMMENT
        else:
            if e.actor_id in latest:
                dispositions[latest[e.actor_id]] = AUDIT_SUPERSEDED
            latest[e.actor_id] = index
    approvers, blockers, stale = [], [], 0
    for actor, index in latest.items():
        e = seq.events[index]
        if e.state == APPROVED and e.commit_sha == identity.head_sha:
            dispositions[index] = AUDIT_COUNTED_APPROVAL
            approvers.append(actor)
        elif e.state == APPROVED:
            dispositions[index] = AUDIT_STALE_COMMIT_APPROVAL
            stale += 1
        elif e.state == CHANGES_REQUESTED:
            dispositions[index] = AUDIT_BLOCKING_CHANGES_REQUESTED
            blockers.append(actor)
        else:
            dispositions[index] = AUDIT_DISMISSED
    decision = []
    if blockers:
        decision.append(HAUTH_CHANGES_REQUESTED)
    if not approvers:
        decision.append(HAUTH_NO_CURRENT_APPROVAL)
    if stale:
        notes.append(HAUTH_APPROVAL_STALE_COMMIT)
    if any(d == AUDIT_DISMISSED for d in dispositions.values()):
        notes.append(HAUTH_APPROVAL_DISMISSED)
    audit = tuple(ReviewAuditEntry(
        review_id=e.review_id, actor_id=e.actor_id, state=e.state, on_head_commit=e.commit_sha == identity.head_sha,
        submitted_at=e.submitted_at, disposition=dispositions[i]) for i, e in enumerate(seq.events))
    return dict(errors=errors, decision=decision, notes=notes, reviewers=len(latest),
                approvers=tuple(sorted(approvers)), blockers=tuple(sorted(blockers)), stale=stale, audit=audit)


def _review_findings(seq, identity, now) -> dict:
    found = dict(errors=[], decision=[], notes=[], seq_fp=None, count=0, reviewers=0, approvers=(), blockers=(),
                 stale=0, audit=())
    if seq is None:
        found["errors"] = [HAUTH_REVIEWS_MISSING]
        return found
    if type(seq) is not ReviewEventSequence or not _plain(seq, _REVIEW_TYPES) or seq.schema != SEQUENCE_SCHEMA \
            or type(seq.events) is not tuple or not all(type(e) is ReviewEvent for e in seq.events):
        found["errors"] = [HAUTH_REVIEWS_MALFORMED]
        return found
    fmt = rpg._sha_format(identity.head_sha)
    found.update(seq_fp=review_sequence_fingerprint(seq), count=len(seq.events))
    errors = _sequence_errors(seq, identity, fmt, now)
    event_errors = [code for e in seq.events for code in _event_errors(e, identity, fmt)]
    if seq.head_commit_author_id is None:
        found["notes"] = [HAUTH_COMMIT_AUTHOR_UNPROVEN]
    if event_errors or HAUTH_REVIEW_ACTOR_INVALID in errors:
        found["errors"] = errors + event_errors  # nothing about the decision is derived
        return found
    errors += _consistency_errors(seq.events, _timestamp(seq.observed_at))
    decided = _decide(seq, identity)
    found.update(errors=errors + decided["errors"], decision=decided["decision"],
                 notes=found["notes"] + decided["notes"], reviewers=decided["reviewers"],
                 approvers=decided["approvers"], blockers=decided["blockers"], stale=decided["stale"],
                 audit=decided["audit"])
    return found


def _result(mode: str, identity=None, errors=(), found=None) -> HumanDecisionEvaluation:
    found = found or {}
    errors = list(dict.fromkeys(errors))
    decision = list(dict.fromkeys(found.get("decision", ())))
    if errors or identity is None:
        classification = REJECTED
    elif decision:
        classification = REVIEW_NOT_FAVORABLE
    else:
        classification = _FAVORABLE[mode]
    consistent = classification != REJECTED
    favorable = classification == _FAVORABLE[mode]
    reasons = errors + decision + list(found.get("notes", ())) \
        + ([HAUTH_REVIEW_EVIDENCE_CONSISTENT] if consistent else []) \
        + ([HAUTH_REVIEW_APPEARS_FAVORABLE] if favorable else []) + list(_MODE_CODES[mode]) + list(_ALWAYS)
    draft = HumanDecisionEvaluation(
        classification=classification, reason_codes=tuple(dict.fromkeys(reasons)), fingerprint="", mode=mode,
        identity=identity, review_sequence_fingerprint=found.get("seq_fp"),
        review_event_count=found.get("count", 0), reviewer_count=found.get("reviewers", 0),
        current_approver_ids=found.get("approvers", ()), blocking_reviewer_ids=found.get("blockers", ()),
        stale_approval_count=found.get("stale", 0), audit_trail=found.get("audit", ()),
        review_evidence_consistent=consistent, review_decision_appears_favorable=favorable,
    )
    return dataclasses.replace(draft, fingerprint=evaluation_fingerprint(draft))


def _evaluate(gate, intent, validation, sequence, pr_number, now, mode: str) -> HumanDecisionEvaluation:
    if not _clock_ok(now):
        return _result(mode, None, [HAUTH_CLOCK_INVALID])
    identity, errors = _bind(gate, intent, validation, pr_number)
    if identity is None:
        return _result(mode, None, errors)
    found = _review_findings(sequence, identity, now)
    return _result(mode, identity, found["errors"], found)


def evaluate_human_decision_evidence(gate_result, intent, validation, review_sequence, *, pr_number,
                                     now) -> HumanDecisionEvaluation:
    """Pure, fail-closed: do the caller-supplied GitHub reviews of PR
    `pr_number` look like a current, favorable human review of exactly the
    head bound by `gate_result` (re-verified against `intent` and
    `validation`)? `now` is an aware UTC instant. Never raises. The source is
    unverified and nothing is authorized."""
    try:
        return _evaluate(gate_result, intent, validation, review_sequence, pr_number, now, MODE_SUPPLIED_SNAPSHOT)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _result(MODE_SUPPLIED_SNAPSHOT, None, [HAUTH_EVALUATION_FAILED])


def read_human_decision_evidence(gate_result, intent, validation, provider, *, pr_number,
                                 now: Optional[datetime] = None) -> HumanDecisionEvaluation:
    """Read-only host variant: the gate binding is re-verified first and,
    only if it holds, `provider.read_review_events(repository, pr_number)` is
    called once. `now` defaults to the system UTC clock read AFTER the
    provider returns, so the read instant is never in the future. A provider
    failure is REJECTED without detail. The read is not authenticated here
    and nothing is authorized."""
    try:
        if now is not None and not _clock_ok(now):
            return _result(MODE_HOST_PROVIDER_READ, None, [HAUTH_CLOCK_INVALID])
        identity, errors = _bind(gate_result, intent, validation, pr_number)
        if identity is None:  # nothing is read for an unbindable request
            return _result(MODE_HOST_PROVIDER_READ, None, errors)
        try:
            sequence = provider.read_review_events(identity.repository, identity.pr_number)
        except Exception:  # noqa: BLE001 - no provider detail is exposed
            return _result(MODE_HOST_PROVIDER_READ, identity, [HAUTH_PROVIDER_READ_FAILED])
        now = datetime.now(timezone.utc) if now is None else now
        if not _clock_ok(now):
            return _result(MODE_HOST_PROVIDER_READ, identity, [HAUTH_CLOCK_INVALID])
        found = _review_findings(sequence, identity, now)
        return _result(MODE_HOST_PROVIDER_READ, identity, found["errors"], found)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _result(MODE_HOST_PROVIDER_READ, None, [HAUTH_EVALUATION_FAILED])

"""FCP-3B-2B2 (core): governed promotion executor state machine (NOT LIVE).

Canonical promotion is GitHub Pull Request -> eight Fabric CI jobs green ->
independent human authorization -> execution by a governed host, never a
direct push or ref update to `develop`. This module is the first, deliberately
incomplete slice of FCP-3B-2B2: a host-driven orchestrator of ONE attempt to
merge ONE pull request through the GitHub Pull Request Merge API, written
against injected ports. It is NOT the privileged adapter, holds no backend,
and is NOT capable of promoting anything in production
(`PRODUCTION_PROMOTION_CAPABLE = False`). It never runs processes, reads Git
or the environment, opens network connections, reads authorization files,
holds tokens or keys, or writes files or refs. It closes neither FCP-3B-2B2
nor FCP-3.

Request (`PromotionExecutionRequest`), plane (a): structural eligibility
-----------------------------------------------------------------------
`prepare_execution_request` (pure) binds the canonical repository, the PR
number, `develop`, the base and head SHAs, the FCP-3B-1 intent and validation
fingerprints, the FCP-3B-2A gate context/result fingerprints and the
FCP-3B-2B1 decision identity and review evaluation, to the ONE explicit
action `MERGE_GITHUB_PR` with merge method `merge`. Every bound object is
re-verified with the previous modules' own functions; the request embeds them
so the executor re-derives the request and refuses any difference. The
`idempotency_key` (= operation id) is a digest of the whole identity, computed
here, never supplied. The FCP-3B-1 descriptive fast-forward action is never
treated as this action or as any permission. A request is only structurally
eligible: it carries no approval, trust flag, signature, HMAC or nonce, and no
favorable gate, review or fingerprint ever satisfies planes (b) or (c).

Planes kept apart
-----------------
a) structural eligibility: the request re-derives exactly, then a FRESH host
   read re-evaluated with `runner_promotion_pr_gate.evaluate_pr_gate` and
   `runner_promotion_human_authorization.evaluate_human_decision_evidence`
   (eight Fabric CI jobs, policy checks, reviews), effective branch protection
   and the current `develop` tip.
b) a human command verified by the independent host (`HostCommandVerdict`),
   bound to the operation id, PR, base, head and action, with a short expiry
   and checked again (revocation) immediately before the operation.
c) a transient operation permit (`OperationPermit`) issued by the host for
   the single-use reservation, with a shorter expiry.
d) remote confirmation after the operation (`PostMergeObservation`): PR
   merged, merge commit equal to the reported one, `develop` at that commit
   and the merge commit's parents exactly (base SHA, head SHA).

Order inside the host's single trust boundary (`TrustedPromotionHost`)
---------------------------------------------------------------------
lease -> human command -> preflight read -> single-use reservation -> permit
-> final command check + final read (must equal the preflight facts) ->
consumption -> ONE merge call with the expected head SHA -> postcondition
read; then the reservation is finalized and the lease released on every path
where they were obtained. The reservation is consumed BEFORE the merge, so a
crash can never permit a replay; a refused attempt burns its reservation and
needs a new human command.

The GitHub merge API's `sha` only protects the HEAD, not the base. The base
race is closed only by required strict (up-to-date) status checks and
verified after the fact through the merge commit parents; a merge queue is
not modeled by this core and is refused. Drift of HEAD, base, checks or
reviews between the reads refuses the attempt.

States (`STATES`) and outcomes
------------------------------
PREPARED -> RESERVED -> MERGE_ATTEMPTED are intermediate; every outcome ends
in AUTHORIZATION_REFUSED, PRECONDITION_REFUSED, FAILED_SAFE,
MERGED_VERIFIED or UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION. A timeout, a
port failure or an unrecognized answer after the merge call is UNCERTAIN,
never retried; an explicit rejection (403/405/409/422) or a call the port
reports as not sent is FAILED_SAFE unless the postcondition contradicts it.
Nothing ever falls back to a direct write on `develop`. A PR found already
merged is reported as observed (`observed_already_merged`), never as a merge
of this attempt. Reason codes are stable constants; port exceptions are never
inspected or recorded.

Modes
-----
`simulate_promotion` drives the state machine against in-memory ports that
declare `host_kind = HOST_KIND_IN_MEMORY_SIMULATION`; its outcomes are always
`SIMULATED`. The marker only prevents accidentally passing a non-simulation
host; it is not a defense against a malicious host. Ports supplied by code
are not an authenticated identity. `execute_promotion` is the production
entry: with no audited privileged host binding it refuses deterministically
(`PRODUCTION_BLOCKED`) without accepting or calling any port. There is no
activation switch: `LIVE_AUTHORIZED` is declared but no code path produces
it. Activation requires a separate, independently audited host Work Order
proving `PRODUCTION_ACTIVATION_REQUIREMENTS`.

Fingerprints are SHA-256 digests of canonical JSON for identity, audit and
accidental-integrity checks only, never authentication or signature.
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
    from scripts.ai import runner_promotion_human_authorization as rha
    from scripts.ai import runner_promotion_pr_gate as rpg
    from scripts.ai import runner_reconciliation as rr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_promotion_authorization as rpa  # type: ignore[no-redef]
    import runner_promotion_human_authorization as rha  # type: ignore[no-redef]
    import runner_promotion_pr_gate as rpg  # type: ignore[no-redef]
    import runner_reconciliation as rr  # type: ignore[no-redef]


REQUEST_SCHEMA = "fcp3b2b2-execution-request-v1"
OUTCOME_SCHEMA = "fcp3b2b2-execution-outcome-v1"
IDEMPOTENCY_SCHEMA = "fcp3b2b2-idempotency-v1"
LEASE_SCHEMA = "fcp3b2b2-lease-grant-v1"
COMMAND_SCHEMA = "fcp3b2b2-host-command-verdict-v1"
RESERVATION_SCHEMA = "fcp3b2b2-reservation-receipt-v1"
CONSUMPTION_SCHEMA = "fcp3b2b2-consumption-receipt-v1"
PERMIT_SCHEMA = "fcp3b2b2-operation-permit-v1"
PROTECTION_SCHEMA = "fcp3b2b2-branch-protection-v1"
FRESH_STATE_SCHEMA = "fcp3b2b2-fresh-state-v1"
MERGE_RESPONSE_SCHEMA = "fcp3b2b2-merge-response-v1"
POST_SCHEMA = "fcp3b2b2-post-merge-observation-v1"

# The ONE action this executor may ever attempt, and how.
ACTION_MERGE_GITHUB_PR = "MERGE_GITHUB_PR"
EXECUTION_ACTIONS = (ACTION_MERGE_GITHUB_PR,)
MERGE_METHOD = "merge"   # keeps the reviewed head SHA as the second parent

PRODUCTION_PROMOTION_CAPABLE = False
HOST_KIND_IN_MEMORY_SIMULATION = "IN_MEMORY_SIMULATION"

# Execution modes. LIVE_AUTHORIZED is never produced by this module.
MODE_SIMULATED = "SIMULATED"
MODE_LIVE_AUTHORIZED = "LIVE_AUTHORIZED"
MODE_PRODUCTION_BLOCKED = "PRODUCTION_BLOCKED"
EXECUTION_MODES = (MODE_SIMULATED, MODE_LIVE_AUTHORIZED, MODE_PRODUCTION_BLOCKED)

# States of one attempt.
PREPARED = "PREPARED"
AUTHORIZATION_REFUSED = "AUTHORIZATION_REFUSED"
PRECONDITION_REFUSED = "PRECONDITION_REFUSED"
RESERVED = "RESERVED"
MERGE_ATTEMPTED = "MERGE_ATTEMPTED"
MERGED_VERIFIED = "MERGED_VERIFIED"
UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION = "UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION"
FAILED_SAFE = "FAILED_SAFE"
STATES = (PREPARED, AUTHORIZATION_REFUSED, PRECONDITION_REFUSED, RESERVED, MERGE_ATTEMPTED, MERGED_VERIFIED,
          UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, FAILED_SAFE)
TERMINAL_STATES = (AUTHORIZATION_REFUSED, PRECONDITION_REFUSED, MERGED_VERIFIED,
                   UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, FAILED_SAFE)
_START = None
TRANSITIONS = {
    _START: (PREPARED, AUTHORIZATION_REFUSED, PRECONDITION_REFUSED),
    PREPARED: (AUTHORIZATION_REFUSED, PRECONDITION_REFUSED, RESERVED),
    RESERVED: (AUTHORIZATION_REFUSED, PRECONDITION_REFUSED, FAILED_SAFE, MERGE_ATTEMPTED),
    MERGE_ATTEMPTED: (MERGED_VERIFIED, UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, FAILED_SAFE),
}

# Host answer vocabularies.
COMMAND_VERIFIED = "COMMAND_VERIFIED"
COMMAND_ABSENT = "COMMAND_ABSENT"
COMMAND_EXPIRED = "COMMAND_EXPIRED"
COMMAND_REVOKED = "COMMAND_REVOKED"
COMMAND_REJECTED = "COMMAND_REJECTED"
COMMAND_STATUSES = (COMMAND_VERIFIED, COMMAND_ABSENT, COMMAND_EXPIRED, COMMAND_REVOKED, COMMAND_REJECTED)
RESERVATION_CREATED = "RESERVATION_CREATED"
RESERVATION_ALREADY_RESERVED = "RESERVATION_ALREADY_RESERVED"
RESERVATION_ALREADY_CONSUMED = "RESERVATION_ALREADY_CONSUMED"
RESERVATION_STATUSES = (RESERVATION_CREATED, RESERVATION_ALREADY_RESERVED, RESERVATION_ALREADY_CONSUMED)
CONSUMED = "CONSUMED"
CONSUMPTION_REFUSED = "CONSUMPTION_REFUSED"
CONSUMPTION_STATUSES = (CONSUMED, CONSUMPTION_REFUSED)
MERGE_MERGED = "MERGED"
MERGE_REJECTED_HEAD_MISMATCH = "REJECTED_HEAD_MISMATCH"
MERGE_REJECTED_CONFLICT = "REJECTED_CONFLICT"
MERGE_REJECTED_UNPROCESSABLE = "REJECTED_UNPROCESSABLE"
MERGE_REJECTED_NOT_MERGEABLE = "REJECTED_NOT_MERGEABLE"
MERGE_REJECTED_FORBIDDEN = "REJECTED_FORBIDDEN"
MERGE_NOT_SENT = "NOT_SENT"
MERGE_TIMEOUT_AFTER_SEND = "TIMEOUT_AFTER_SEND"
# Each merge status and the only HTTP status it may carry.
MERGE_STATUSES = {
    MERGE_MERGED: 200, MERGE_REJECTED_HEAD_MISMATCH: 409, MERGE_REJECTED_CONFLICT: 409,
    MERGE_REJECTED_UNPROCESSABLE: 422, MERGE_REJECTED_NOT_MERGEABLE: 405, MERGE_REJECTED_FORBIDDEN: 403,
    MERGE_NOT_SENT: None, MERGE_TIMEOUT_AFTER_SEND: None,
}

MAX_LEASE_SECONDS = 600
MAX_COMMAND_TTL_SECONDS = 900
MAX_PERMIT_TTL_SECONDS = 120

# Steps of the audit trail, in the only order they may occur.
STEP_VALIDATE_REQUEST = "VALIDATE_REQUEST"
STEP_ACQUIRE_LEASE = "ACQUIRE_LEASE"
STEP_VERIFY_COMMAND = "VERIFY_COMMAND"
STEP_PREFLIGHT_READ = "PREFLIGHT_READ"
STEP_RESERVE = "RESERVE_SINGLE_USE"
STEP_ISSUE_PERMIT = "ISSUE_PERMIT"
STEP_FINAL_COMMAND_CHECK = "FINAL_COMMAND_CHECK"
STEP_FINAL_READ = "FINAL_READ"
STEP_CONSUME = "CONSUME_SINGLE_USE"
STEP_MERGE = "MERGE_PULL_REQUEST"
STEP_POSTCONDITION_READ = "POSTCONDITION_READ"
STEP_FINALIZE_RESERVATION = "FINALIZE_RESERVATION"
STEP_RELEASE_LEASE = "RELEASE_LEASE"
STEP_OK = "OK"

# Reason codes: request (plane a).
EXEC_REQUEST_MALFORMED = "EXEC_REQUEST_MALFORMED"
EXEC_REQUEST_TAMPERED = "EXEC_REQUEST_TAMPERED"
EXEC_REQUEST_GATE_BINDING_INVALID = "EXEC_REQUEST_GATE_BINDING_INVALID"
EXEC_REQUEST_EVALUATION_MALFORMED = "EXEC_REQUEST_EVALUATION_MALFORMED"
EXEC_REQUEST_EVALUATION_TAMPERED = "EXEC_REQUEST_EVALUATION_TAMPERED"
EXEC_REQUEST_EVALUATION_NOT_FAVORABLE = "EXEC_REQUEST_EVALUATION_NOT_FAVORABLE"
EXEC_REQUEST_EVALUATION_BINDING_MISMATCH = "EXEC_REQUEST_EVALUATION_BINDING_MISMATCH"
# Host presence.
EXEC_TRUSTED_HOST_ABSENT = "EXEC_TRUSTED_HOST_ABSENT"
EXEC_TRUSTED_HOST_NOT_AVAILABLE = "EXEC_TRUSTED_HOST_NOT_AVAILABLE"
EXEC_PRODUCTION_ADAPTER_NOT_IMPLEMENTED = "EXEC_PRODUCTION_ADAPTER_NOT_IMPLEMENTED"
EXEC_HOST_PORT_FAILED = "EXEC_HOST_PORT_FAILED"
EXEC_CLOCK_INVALID = "EXEC_CLOCK_INVALID"
# Lease.
EXEC_LEASE_UNAVAILABLE = "EXEC_LEASE_UNAVAILABLE"
EXEC_LEASE_INVALID = "EXEC_LEASE_INVALID"
EXEC_LEASE_EXPIRED = "EXEC_LEASE_EXPIRED"
EXEC_LEASE_RELEASE_FAILED = "EXEC_LEASE_RELEASE_FAILED"
# Human command (plane b).
EXEC_COMMAND_MALFORMED = "EXEC_COMMAND_MALFORMED"
EXEC_COMMAND_ABSENT = "EXEC_COMMAND_ABSENT"
EXEC_COMMAND_NOT_AUTHENTICATED = "EXEC_COMMAND_NOT_AUTHENTICATED"
EXEC_COMMAND_EXPIRED = "EXEC_COMMAND_EXPIRED"
EXEC_COMMAND_REVOKED = "EXEC_COMMAND_REVOKED"
EXEC_COMMAND_BINDING_MISMATCH = "EXEC_COMMAND_BINDING_MISMATCH"
EXEC_COMMAND_TIMESTAMP_INVALID = "EXEC_COMMAND_TIMESTAMP_INVALID"
EXEC_COMMAND_TTL_TOO_LONG = "EXEC_COMMAND_TTL_TOO_LONG"
EXEC_COMMAND_CHANGED = "EXEC_COMMAND_CHANGED"
# Fresh state (plane a, fresh).
EXEC_FRESH_STATE_MALFORMED = "EXEC_FRESH_STATE_MALFORMED"
EXEC_FRESH_BINDING_MISMATCH = "EXEC_FRESH_BINDING_MISMATCH"
EXEC_FRESH_GATE_NOT_REVIEWABLE = "EXEC_FRESH_GATE_NOT_REVIEWABLE"
EXEC_FRESH_REVIEWS_NOT_FAVORABLE = "EXEC_FRESH_REVIEWS_NOT_FAVORABLE"
EXEC_PR_ALREADY_MERGED_OBSERVED = "EXEC_PR_ALREADY_MERGED_OBSERVED"
EXEC_BASE_DRIFT = "EXEC_BASE_DRIFT"
EXEC_STATE_CHANGED_DURING_PREFLIGHT = "EXEC_STATE_CHANGED_DURING_PREFLIGHT"
EXEC_PROTECTION_UNKNOWN = "EXEC_PROTECTION_UNKNOWN"
EXEC_PROTECTION_MALFORMED = "EXEC_PROTECTION_MALFORMED"
EXEC_PROTECTION_REVIEWS_NOT_REQUIRED = "EXEC_PROTECTION_REVIEWS_NOT_REQUIRED"
EXEC_PROTECTION_STALE_REVIEWS_KEPT = "EXEC_PROTECTION_STALE_REVIEWS_KEPT"
EXEC_PROTECTION_CHECKS_NOT_REQUIRED = "EXEC_PROTECTION_CHECKS_NOT_REQUIRED"
EXEC_PROTECTION_INCONSISTENT = "EXEC_PROTECTION_INCONSISTENT"
EXEC_PROTECTION_NOT_STRICT = "EXEC_PROTECTION_NOT_STRICT"
EXEC_PROTECTION_ADMIN_BYPASS = "EXEC_PROTECTION_ADMIN_BYPASS"
EXEC_PROTECTION_REWRITE_ALLOWED = "EXEC_PROTECTION_REWRITE_ALLOWED"
EXEC_MERGE_QUEUE_NOT_SUPPORTED = "EXEC_MERGE_QUEUE_NOT_SUPPORTED"
EXEC_MERGE_METHOD_FORBIDDEN_BY_POLICY = "EXEC_MERGE_METHOD_FORBIDDEN_BY_POLICY"
# Single use and permit (plane c).
EXEC_RESERVATION_MALFORMED = "EXEC_RESERVATION_MALFORMED"
EXEC_RESERVATION_BINDING_MISMATCH = "EXEC_RESERVATION_BINDING_MISMATCH"
EXEC_RESERVATION_DUPLICATE = "EXEC_RESERVATION_DUPLICATE"
EXEC_REPLAY_DETECTED = "EXEC_REPLAY_DETECTED"
EXEC_PERMIT_MALFORMED = "EXEC_PERMIT_MALFORMED"
EXEC_PERMIT_BINDING_MISMATCH = "EXEC_PERMIT_BINDING_MISMATCH"
EXEC_PERMIT_EXPIRED = "EXEC_PERMIT_EXPIRED"
EXEC_PERMIT_TTL_TOO_LONG = "EXEC_PERMIT_TTL_TOO_LONG"
EXEC_CONSUMPTION_FAILED = "EXEC_CONSUMPTION_FAILED"
EXEC_LEDGER_FINALIZE_FAILED = "EXEC_LEDGER_FINALIZE_FAILED"
# Merge and postcondition (plane d).
EXEC_MERGE_OUTCOME_UNKNOWN = "EXEC_MERGE_OUTCOME_UNKNOWN"
EXEC_MERGE_NOT_SENT = "EXEC_MERGE_NOT_SENT"
EXEC_MERGE_REJECTED_HEAD_MISMATCH = "EXEC_MERGE_REJECTED_HEAD_MISMATCH"
EXEC_MERGE_REJECTED_CONFLICT = "EXEC_MERGE_REJECTED_CONFLICT"
EXEC_MERGE_REJECTED_UNPROCESSABLE = "EXEC_MERGE_REJECTED_UNPROCESSABLE"
EXEC_MERGE_REJECTED_NOT_MERGEABLE = "EXEC_MERGE_REJECTED_NOT_MERGEABLE"
EXEC_MERGE_REJECTED_FORBIDDEN = "EXEC_MERGE_REJECTED_FORBIDDEN"
EXEC_POSTCONDITION_UNREAD = "EXEC_POSTCONDITION_UNREAD"
EXEC_POSTCONDITION_CONTRADICTS = "EXEC_POSTCONDITION_CONTRADICTS"
EXEC_POST_BASE_DRIFT = "EXEC_POST_BASE_DRIFT"
EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED = "EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED"
EXEC_MERGED_VERIFIED_SIMULATED = "EXEC_MERGED_VERIFIED_SIMULATED"
EXEC_NO_RETRY_AFTER_UNCERTAINTY = "EXEC_NO_RETRY_AFTER_UNCERTAINTY"
EXEC_INTERNAL_FAILURE = "EXEC_INTERNAL_FAILURE"
# Always-present codes.
EXEC_SIMULATED_NOT_REAL_MERGE = "EXEC_SIMULATED_NOT_REAL_MERGE"
EXEC_PRODUCTION_PROMOTION_DISABLED = "EXEC_PRODUCTION_PROMOTION_DISABLED"
EXEC_HOST_IDENTITY_NOT_AUTHENTICATED = "EXEC_HOST_IDENTITY_NOT_AUTHENTICATED"
EXEC_FINGERPRINT_NOT_AUTHENTICATION = "EXEC_FINGERPRINT_NOT_AUTHENTICATION"

_MODE_CODES = {
    MODE_SIMULATED: (EXEC_SIMULATED_NOT_REAL_MERGE,),
    MODE_PRODUCTION_BLOCKED: (EXEC_TRUSTED_HOST_NOT_AVAILABLE, EXEC_PRODUCTION_ADAPTER_NOT_IMPLEMENTED),
}
_ALWAYS = (EXEC_PRODUCTION_PROMOTION_DISABLED, EXEC_HOST_IDENTITY_NOT_AUTHENTICATED,
           EXEC_FINGERPRINT_NOT_AUTHENTICATION)
_REJECTION_CODES = {
    MERGE_REJECTED_HEAD_MISMATCH: EXEC_MERGE_REJECTED_HEAD_MISMATCH, MERGE_REJECTED_CONFLICT: EXEC_MERGE_REJECTED_CONFLICT,
    MERGE_REJECTED_UNPROCESSABLE: EXEC_MERGE_REJECTED_UNPROCESSABLE,
    MERGE_REJECTED_NOT_MERGEABLE: EXEC_MERGE_REJECTED_NOT_MERGEABLE,
    MERGE_REJECTED_FORBIDDEN: EXEC_MERGE_REJECTED_FORBIDDEN, MERGE_NOT_SENT: EXEC_MERGE_NOT_SENT,
}
_COMMAND_CODES = {COMMAND_ABSENT: EXEC_COMMAND_ABSENT, COMMAND_EXPIRED: EXEC_COMMAND_EXPIRED,
                  COMMAND_REVOKED: EXEC_COMMAND_REVOKED, COMMAND_REJECTED: EXEC_COMMAND_NOT_AUTHENTICATED}
_REQUEST_REFUSALS = (EXEC_REQUEST_MALFORMED, EXEC_REQUEST_TAMPERED)
_CODE_PREFIXES = ("EXEC_", "PR_GATE_", "HAUTH_", "INTENT_")

# Everything a future privileged host must prove before any live operation.
PRODUCTION_ACTIVATION_REQUIREMENTS = rha.FUTURE_EXECUTOR_REQUIREMENTS + (
    "EXEC_REQ_AUDITED_PRIVILEGED_HOST_ADAPTER",
    "EXEC_REQ_PERSISTENT_SINGLE_USE_LEDGER",
    "EXEC_REQ_INDEPENDENT_SECURITY_AUDIT",
    "EXEC_REQ_INTEGRATION_TESTS_AGAINST_PROTECTED_REPOSITORY",
)

# Opaque host ids: no whitespace, no underscore (GitHub token formats use one).
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,127}")
_FAVORABLE_NOTES = (rha.HAUTH_COMMIT_AUTHOR_UNPROVEN, rha.HAUTH_APPROVAL_STALE_COMMIT, rha.HAUTH_APPROVAL_DISMISSED)
_FAILED = object()   # sentinel: a host port raised; no detail is kept


# ---------------------------------------------------------------------------
# Request (plane a)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionExecutionRequest:
    """ONE structurally eligible attempt, re-derived exactly from the embedded
    FCP-3B-1/2A/2B1 objects. Identity, not consent: it never authorizes."""

    action: str
    merge_method: str
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
    decision_identity_fingerprint: str
    review_evaluation_fingerprint: str
    review_sequence_fingerprint: str
    current_approver_ids: tuple
    idempotency_key: str
    intent: rpa.PromotionIntent
    validation: rpa.PromotionIntentValidation
    gate_result: rpg.PrGateResult
    review_evaluation: rha.HumanDecisionEvaluation
    fingerprint: str
    human_command_present: bool = False
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = REQUEST_SCHEMA


class PromotionExecutionRefused(ValueError):
    """`prepare_execution_request` refused its input. Carries only stable
    reason codes, never input values."""

    def __init__(self, reason_codes):
        self.reason_codes = tuple(dict.fromkeys(reason_codes))
        super().__init__(", ".join(self.reason_codes))


# ---------------------------------------------------------------------------
# Host facts (immutable, produced by the host; untrusted by this module)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeaseGrant:
    """Exclusive ownership of `resource` (repository:develop) for the
    operation. The host should back it with the Runner's DirLease or an
    equivalent OS-level lock."""

    lease_id: str
    operation_id: str
    resource: str
    acquired_at: str
    expires_at: str
    schema: str = LEASE_SCHEMA


@dataclass(frozen=True)
class HostCommandVerdict:
    """The host's verdict on an authenticated human Director command for
    exactly this operation. In this delivery every verdict comes from a fake."""

    status: str
    command_id: str
    operation_id: str
    action: str
    repository: str
    pr_number: int
    base_sha: str
    head_sha: str
    director_id: int
    issued_at: str
    expires_at: str
    schema: str = COMMAND_SCHEMA


@dataclass(frozen=True)
class ReservationReceipt:
    status: str
    reservation_id: str
    operation_id: str
    command_id: str
    schema: str = RESERVATION_SCHEMA


@dataclass(frozen=True)
class ConsumptionReceipt:
    status: str
    reservation_id: str
    operation_id: str
    schema: str = CONSUMPTION_SCHEMA


@dataclass(frozen=True)
class OperationPermit:
    """Transient permit for ONE consumption of ONE reservation."""

    permit_id: str
    operation_id: str
    reservation_id: str
    command_id: str
    action: str
    head_sha: str
    base_sha: str
    issued_at: str
    expires_at: str
    schema: str = PERMIT_SCHEMA


@dataclass(frozen=True)
class BranchProtectionState:
    """Effective protection of `develop` as read by the host."""

    repository: str
    base_ref: str
    complete: bool
    pull_request_required: bool
    required_approving_review_count: int
    dismiss_stale_reviews: bool
    required_check_names: tuple
    strict_up_to_date: bool
    enforce_admins: bool
    allow_force_pushes: bool
    allow_deletions: bool
    merge_queue_required: bool
    schema: str = PROTECTION_SCHEMA


@dataclass(frozen=True)
class FreshPromotionState:
    """One fresh host read: PR metadata, files and checks (FCP-3B-2A shape),
    reviews (FCP-3B-2B1 shape), branch protection and the `develop` tip."""

    repository: str
    pr_number: int
    pr_snapshot: rpg.PullRequestSnapshot
    review_sequence: rha.ReviewEventSequence
    protection: Optional[BranchProtectionState]
    develop_tip_sha: str
    schema: str = FRESH_STATE_SCHEMA


@dataclass(frozen=True)
class MergeResponse:
    """The port's classification of the Merge PR API answer. `NOT_SENT` is the
    port's statement that no request left the host."""

    status: str
    http_status: Optional[int]
    merge_commit_sha: Optional[str]
    schema: str = MERGE_RESPONSE_SCHEMA


@dataclass(frozen=True)
class PostMergeObservation:
    """PR and `develop` read after the merge call. GitHub fills
    `merge_commit_sha` for open PRs too; it only counts when `merged`."""

    repository: str
    pr_number: int
    state: str
    merged: bool
    head_sha: str
    merge_commit_sha: Optional[str]
    merge_commit_parents: tuple
    develop_tip_sha: str
    schema: str = POST_SCHEMA


_HOST_TYPES = (LeaseGrant, HostCommandVerdict, ReservationReceipt, ConsumptionReceipt, OperationPermit,
               BranchProtectionState, MergeResponse, PostMergeObservation)
_FRESH_TYPES = (FreshPromotionState, BranchProtectionState, rha.ReviewEventSequence, rha.ReviewEvent) \
    + rpg._SNAPSHOT_TYPES
_REQUEST_TYPES = (PromotionExecutionRequest, rpa.PromotionIntent, rpa.PromotionIntentValidation, rpg.PrGateResult,
                  rpg.PrGateContext, rha.HumanDecisionEvaluation, rha.HumanDecisionIdentity, rha.ReviewAuditEntry)


# ---------------------------------------------------------------------------
# Host contract (one trust boundary; NOT implemented here)
# ---------------------------------------------------------------------------

class LeasePort(Protocol):
    def acquire_lease(self, operation_id: str, resource: str) -> Optional[LeaseGrant]: ...

    def release_lease(self, lease_id: str) -> None: ...


class HumanCommandPort(Protocol):
    """Authenticates the human Director independently of the Runner and of
    every provider, and checks expiry and revocation."""

    def verify_human_command(self, operation_id: str, repository: str, pr_number: int, base_sha: str,
                             head_sha: str, action: str) -> HostCommandVerdict: ...


class SingleUseLedgerPort(Protocol):
    """Persistent single-use reservation and consumption ledger."""

    def reserve_single_use(self, operation_id: str, command_id: str) -> ReservationReceipt: ...

    def issue_operation_permit(self, operation_id: str, reservation_id: str, command_id: str) -> OperationPermit: ...

    def consume_single_use(self, reservation_id: str) -> ConsumptionReceipt: ...

    def finalize_reservation(self, reservation_id: str, final_state: str) -> None: ...


class GitHubPromotionPort(Protocol):
    """Fresh reads and the ONE write: the Merge PR API with the expected head
    SHA. No other write (no ref update, no push) exists in this contract."""

    def read_fresh_state(self, repository: str, pr_number: int) -> FreshPromotionState: ...

    def merge_pull_request(self, repository: str, pr_number: int, expected_head_sha: str, merge_method: str,
                           permit_id: str) -> MergeResponse: ...

    def read_postcondition(self, repository: str, pr_number: int) -> PostMergeObservation: ...


class TrustedPromotionHost(LeasePort, HumanCommandPort, SingleUseLedgerPort, GitHubPromotionPort, Protocol):
    """Every port, served by ONE privileged host trust boundary. `host_kind`
    is a class attribute; only HOST_KIND_IN_MEMORY_SIMULATION is accepted."""

    host_kind: str


# ---------------------------------------------------------------------------
# Outcome (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionStep:
    """One audited step: its name and `OK` or a stable reason code."""

    step: str
    result: str


@dataclass(frozen=True)
class PromotionExecutionOutcome:
    """The result of ONE attempt. In this delivery `execution_mode` is never
    LIVE_AUTHORIZED: even MERGED_VERIFIED is a simulation against fakes."""

    state: str
    reason_codes: tuple
    fingerprint: str
    execution_mode: str
    operation_id: Optional[str]
    request_fingerprint: Optional[str]
    repository: Optional[str]
    pr_number: Optional[int]
    base_sha: Optional[str]
    head_sha: Optional[str]
    action: Optional[str]
    lease_id: Optional[str]
    command_id: Optional[str]
    reservation_id: Optional[str]
    permit_id: Optional[str]
    merge_call_count: int
    merge_response_status: Optional[str]
    merge_commit_sha: Optional[str]
    observed_develop_tip_sha: Optional[str]
    observed_already_merged: bool
    merge_performed_by_this_attempt: bool
    structural_eligibility_passed: bool
    host_command_check_passed: bool
    operation_permit_check_passed: bool
    remote_postcondition_confirmed: bool
    human_reconciliation_required: bool
    state_trace: tuple
    step_trace: tuple
    executor_requirements_unmet: tuple = PRODUCTION_ACTIVATION_REQUIREMENTS
    human_command_authenticated: bool = False
    retry_allowed: bool = False
    live_authorized: bool = False
    production_capable: bool = False
    schema: str = OUTCOME_SCHEMA


# ---------------------------------------------------------------------------
# Fingerprints (identity and audit; never authentication)
# ---------------------------------------------------------------------------

def _payload(value) -> dict:
    return {f.name: rr._canonical(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name != "fingerprint"}


def request_fingerprint(request: PromotionExecutionRequest) -> str:
    """Recomputes the canonical request fingerprint."""
    return rr._digest(_payload(request))


def outcome_fingerprint(outcome: PromotionExecutionOutcome) -> str:
    """Recomputes the canonical outcome fingerprint (audit, not authentication)."""
    return rr._digest(_payload(outcome))


def _idempotency_key(fields: dict) -> str:
    return rr._digest({"schema": IDEMPOTENCY_SCHEMA, **fields})


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------

def _plain(value, types) -> bool:
    """Exact built-in scalars, tuples of them and the exact given types only."""
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is tuple:
        return all(_plain(v, types) for v in value)
    return type(value) in types and all(_plain(getattr(value, f.name), types) for f in dataclasses.fields(value))


def _host_value_ok(value, cls, schema) -> bool:
    return type(value) is cls and _plain(value, _HOST_TYPES) and value.schema == schema


def _id_ok(value) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None


def _window(start, end, now, max_seconds):
    """None if `start <= now < end` and the window is at most `max_seconds`,
    else 'timestamp', 'ttl' or 'expired'."""
    issued, expires = rha._timestamp(start), rha._timestamp(end)
    if issued is None or expires is None or expires <= issued or issued > now:
        return "timestamp"
    if expires - issued > timedelta(seconds=max_seconds):
        return "ttl"
    return "expired" if now >= expires else None


def _evaluation_errors(ev, identity) -> list:
    """`ev` must be an unaltered, favorable FCP-3B-2B1 evaluation of exactly
    `identity`, with every never-authorizing flag at its default."""
    if type(ev) is not rha.HumanDecisionEvaluation or not _plain(ev, _REQUEST_TYPES):
        return [EXEC_REQUEST_EVALUATION_MALFORMED]
    try:
        tampered = ev.fingerprint != rha.evaluation_fingerprint(ev)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        tampered = True
    flags = (ev.source_unverified, ev.source_authenticated, ev.authenticated_human_command_present,
             ev.human_command_authenticated, ev.human_authorization_required, ev.authorizes_action,
             ev.execution_allowed)
    if tampered or ev.schema != rha.RESULT_SCHEMA or flags != (True, False, False, False, True, False, False) \
            or ev.executor_requirements_unmet != rha.FUTURE_EXECUTOR_REQUIREMENTS or ev.mode not in rha._FAVORABLE:
        return [EXEC_REQUEST_EVALUATION_TAMPERED]
    if ev.classification != rha._FAVORABLE[ev.mode] or ev.review_decision_appears_favorable is not True \
            or not ev.current_approver_ids or ev.blocking_reviewer_ids != ():
        return [EXEC_REQUEST_EVALUATION_NOT_FAVORABLE]
    required = {rha.HAUTH_REVIEW_EVIDENCE_CONSISTENT, rha.HAUTH_REVIEW_APPEARS_FAVORABLE,
                *rha._MODE_CODES[ev.mode], *rha._ALWAYS}
    if not required <= set(ev.reason_codes) <= required | set(_FAVORABLE_NOTES) \
            or not rpa._DIGEST_RE.fullmatch(ev.review_sequence_fingerprint or ""):
        return [EXEC_REQUEST_EVALUATION_TAMPERED]
    if ev.identity != identity:
        return [EXEC_REQUEST_EVALUATION_BINDING_MISMATCH]
    return []


def _build_request(gate_result, intent, validation, review_evaluation, pr_number) -> PromotionExecutionRequest:
    identity, errors = rha._bind(gate_result, intent, validation, pr_number)
    if identity is None:
        raise PromotionExecutionRefused([EXEC_REQUEST_GATE_BINDING_INVALID, *errors])
    errors = _evaluation_errors(review_evaluation, identity)
    if errors:
        raise PromotionExecutionRefused(errors)
    bound = dict(
        action=ACTION_MERGE_GITHUB_PR, merge_method=MERGE_METHOD, repository=identity.repository,
        pr_number=identity.pr_number, base_ref=identity.base_ref, base_sha=identity.base_sha,
        head_ref=identity.head_ref, head_sha=identity.head_sha, intent_fingerprint=identity.intent_fingerprint,
        validation_fingerprint=identity.validation_fingerprint,
        gate_context_fingerprint=identity.gate_context_fingerprint,
        gate_result_fingerprint=identity.gate_result_fingerprint, decision_identity_fingerprint=identity.fingerprint,
        review_evaluation_fingerprint=review_evaluation.fingerprint,
        review_sequence_fingerprint=review_evaluation.review_sequence_fingerprint,
        current_approver_ids=review_evaluation.current_approver_ids,
    )
    draft = PromotionExecutionRequest(
        **bound, idempotency_key=_idempotency_key(bound), intent=intent, validation=validation,
        gate_result=gate_result, review_evaluation=review_evaluation, fingerprint="",
    )
    return dataclasses.replace(draft, fingerprint=request_fingerprint(draft))


def prepare_execution_request(gate_result, intent, validation, review_evaluation, *,
                              pr_number) -> PromotionExecutionRequest:
    """Pure, plane (a) only: the request for PR `pr_number` bound to a
    reviewable FCP-3B-2A gate (re-derived from `intent` and `validation`) and
    a favorable FCP-3B-2B1 evaluation of exactly that gate. Raises
    `PromotionExecutionRefused` (stable codes) otherwise. Authorizes nothing."""
    try:
        return _build_request(gate_result, intent, validation, review_evaluation, pr_number)
    except PromotionExecutionRefused:
        raise
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        raise PromotionExecutionRefused([EXEC_REQUEST_MALFORMED]) from None


def _request_errors(request) -> list:
    """The request must re-derive exactly from its embedded evidence."""
    if type(request) is not PromotionExecutionRequest or not _plain(request, _REQUEST_TYPES) \
            or request.schema != REQUEST_SCHEMA:
        return [EXEC_REQUEST_MALFORMED]
    try:
        expected = _build_request(request.gate_result, request.intent, request.validation,
                                  request.review_evaluation, request.pr_number)
    except PromotionExecutionRefused as exc:
        return [EXEC_REQUEST_TAMPERED, *exc.reason_codes]
    except Exception:  # noqa: BLE001
        return [EXEC_REQUEST_MALFORMED]
    return [] if expected == request else [EXEC_REQUEST_TAMPERED]


def _lease_errors(grant, request, now) -> list:
    if not _host_value_ok(grant, LeaseGrant, LEASE_SCHEMA) or not _id_ok(grant.lease_id) \
            or grant.operation_id != request.idempotency_key or grant.resource != _lease_resource(request):
        return [EXEC_LEASE_INVALID]
    problem = _window(grant.acquired_at, grant.expires_at, now, MAX_LEASE_SECONDS)
    return [] if problem is None else [EXEC_LEASE_EXPIRED if problem == "expired" else EXEC_LEASE_INVALID]


def _lease_resource(request) -> str:
    return f"{request.repository}:{request.base_ref}"


def _command_errors(verdict, request, now) -> list:
    if not _host_value_ok(verdict, HostCommandVerdict, COMMAND_SCHEMA) or verdict.status not in COMMAND_STATUSES:
        return [EXEC_COMMAND_MALFORMED]
    if verdict.status != COMMAND_VERIFIED:
        return [_COMMAND_CODES[verdict.status]]
    errors = []
    if not _id_ok(verdict.command_id) or not rha._int(verdict.director_id, 1, rha.MAX_ID):
        errors.append(EXEC_COMMAND_MALFORMED)
    if (verdict.operation_id, verdict.action, verdict.repository, verdict.pr_number, verdict.base_sha,
            verdict.head_sha) != (request.idempotency_key, request.action, request.repository, request.pr_number,
                                  request.base_sha, request.head_sha) or type(verdict.pr_number) is not int:
        errors.append(EXEC_COMMAND_BINDING_MISMATCH)
    problem = _window(verdict.issued_at, verdict.expires_at, now, MAX_COMMAND_TTL_SECONDS)
    if problem:
        errors.append({"timestamp": EXEC_COMMAND_TIMESTAMP_INVALID, "ttl": EXEC_COMMAND_TTL_TOO_LONG,
                       "expired": EXEC_COMMAND_EXPIRED}[problem])
    return errors


def _reservation_errors(receipt, request, command_id) -> list:
    if not _host_value_ok(receipt, ReservationReceipt, RESERVATION_SCHEMA) \
            or receipt.status not in RESERVATION_STATUSES or not _id_ok(receipt.reservation_id):
        return [EXEC_RESERVATION_MALFORMED]
    if receipt.status == RESERVATION_ALREADY_CONSUMED:
        return [EXEC_REPLAY_DETECTED]
    if receipt.status == RESERVATION_ALREADY_RESERVED:
        return [EXEC_RESERVATION_DUPLICATE]
    if receipt.operation_id != request.idempotency_key or receipt.command_id != command_id:
        return [EXEC_RESERVATION_BINDING_MISMATCH]
    return []


def _permit_errors(permit, request, reservation_id, command_id, now) -> list:
    if not _host_value_ok(permit, OperationPermit, PERMIT_SCHEMA) or not _id_ok(permit.permit_id):
        return [EXEC_PERMIT_MALFORMED]
    errors = []
    if (permit.operation_id, permit.reservation_id, permit.command_id, permit.action, permit.head_sha,
            permit.base_sha) != (request.idempotency_key, reservation_id, command_id, request.action,
                                 request.head_sha, request.base_sha):
        errors.append(EXEC_PERMIT_BINDING_MISMATCH)
    problem = _window(permit.issued_at, permit.expires_at, now, MAX_PERMIT_TTL_SECONDS)
    if problem:
        errors.append(EXEC_PERMIT_TTL_TOO_LONG if problem == "ttl" else EXEC_PERMIT_EXPIRED)
    return errors


def _consumption_errors(receipt, request, reservation_id) -> list:
    if not _host_value_ok(receipt, ConsumptionReceipt, CONSUMPTION_SCHEMA) or receipt.status != CONSUMED \
            or receipt.reservation_id != reservation_id or receipt.operation_id != request.idempotency_key:
        return [EXEC_CONSUMPTION_FAILED]
    return []


def _protection_errors(protection, request, gate) -> list:
    if protection is None:
        return [EXEC_PROTECTION_UNKNOWN]
    if type(protection) is not BranchProtectionState or protection.schema != PROTECTION_SCHEMA \
            or not all(type(getattr(protection, n)) is bool for n in (
                "complete", "pull_request_required", "dismiss_stale_reviews", "strict_up_to_date",
                "enforce_admins", "allow_force_pushes", "allow_deletions", "merge_queue_required")) \
            or not rha._int(protection.required_approving_review_count, 0, 100) \
            or not rpg._unique_texts(protection.required_check_names):
        return [EXEC_PROTECTION_MALFORMED]
    if protection.complete is not True or protection.repository != request.repository \
            or protection.base_ref != request.base_ref:
        return [EXEC_PROTECTION_UNKNOWN]
    errors = []
    if not protection.pull_request_required or protection.required_approving_review_count < 1:
        errors.append(EXEC_PROTECTION_REVIEWS_NOT_REQUIRED)
    if not protection.dismiss_stale_reviews:
        errors.append(EXEC_PROTECTION_STALE_REVIEWS_KEPT)
    if not set(rpg.REQUIRED_CI_JOBS) <= set(protection.required_check_names):
        errors.append(EXEC_PROTECTION_CHECKS_NOT_REQUIRED)
    elif gate is not None and set(protection.required_check_names) != set(gate.required_checks):
        errors.append(EXEC_PROTECTION_INCONSISTENT)   # two host reads disagree about the policy
    if not protection.strict_up_to_date:
        errors.append(EXEC_PROTECTION_NOT_STRICT)
    if not protection.enforce_admins:
        errors.append(EXEC_PROTECTION_ADMIN_BYPASS)
    if protection.allow_force_pushes or protection.allow_deletions:
        errors.append(EXEC_PROTECTION_REWRITE_ALLOWED)
    if protection.merge_queue_required:
        errors.append(EXEC_MERGE_QUEUE_NOT_SUPPORTED)
    return errors


def _gate_codes(result, always) -> list:
    return [c for c in result.reason_codes if c not in always]


def _fresh_findings(request, state, now) -> dict:
    """Plane (a), fresh: the previous modules re-evaluate the host read."""
    found = dict(errors=[], digest=None, already_merged=False)
    if type(state) is not FreshPromotionState or not _plain(state, _FRESH_TYPES) \
            or state.schema != FRESH_STATE_SCHEMA:
        found["errors"] = [EXEC_FRESH_STATE_MALFORMED]
        return found
    if state.repository != request.repository or type(state.pr_number) is not int \
            or state.pr_number != request.pr_number:
        found["errors"] = [EXEC_FRESH_BINDING_MISMATCH]
        return found
    errors = []
    gate = rpg.evaluate_pr_gate(request.intent, request.validation, state.pr_snapshot, pr_number=request.pr_number)
    if rpg.PR_GATE_PR_MERGED in gate.reason_codes:
        found["already_merged"] = True
        errors.append(EXEC_PR_ALREADY_MERGED_OBSERVED)
    if gate.classification != rpg.REVIEWABLE_UNVERIFIED_SNAPSHOT:
        errors += [EXEC_FRESH_GATE_NOT_REVIEWABLE, *_gate_codes(gate, rpg._ALWAYS + rpg._MODE_CODES[gate.mode])]
    elif gate.context.fingerprint != request.gate_context_fingerprint:
        errors.append(EXEC_FRESH_BINDING_MISMATCH)
    else:
        ev = rha.evaluate_human_decision_evidence(gate, request.intent, request.validation, state.review_sequence,
                                                  pr_number=request.pr_number, now=now)
        if ev.classification != rha.REVIEW_CONSISTENT_UNVERIFIED:
            errors += [EXEC_FRESH_REVIEWS_NOT_FAVORABLE, *_gate_codes(ev, rha._ALWAYS + rha._MODE_CODES[ev.mode])]
        elif ev.identity.gate_context_fingerprint != request.gate_context_fingerprint:
            errors.append(EXEC_FRESH_BINDING_MISMATCH)
        if "required_linear_history" in state.pr_snapshot.checks.policy.rule_types:
            errors.append(EXEC_MERGE_METHOD_FORBIDDEN_BY_POLICY)
    if state.develop_tip_sha != request.base_sha:
        errors.append(EXEC_BASE_DRIFT)
    errors += _protection_errors(state.protection, request, gate if gate.candidate_reviewable else None)
    found["errors"] = list(dict.fromkeys(errors))
    seq = state.review_sequence
    found["digest"] = rr._digest(rr._canonical((
        state.pr_snapshot, seq.events if type(seq) is rha.ReviewEventSequence else seq,
        state.protection, state.develop_tip_sha)))
    return found


def _response_status(response, request) -> Optional[str]:
    """The response status if the answer is internally consistent, else None."""
    if not _host_value_ok(response, MergeResponse, MERGE_RESPONSE_SCHEMA) or response.status not in MERGE_STATUSES:
        return None
    if response.http_status != MERGE_STATUSES[response.status] \
            or (response.http_status is not None and type(response.http_status) is not int):
        return None
    if response.status == MERGE_MERGED:
        fmt = rpg._sha_format(request.head_sha)
        return response.status if ri._is_sha(response.merge_commit_sha, fmt) else None
    return response.status if response.merge_commit_sha is None else None


def _post_value(observed, request) -> Optional[PostMergeObservation]:
    if not _host_value_ok(observed, PostMergeObservation, POST_SCHEMA) or observed.repository != request.repository \
            or type(observed.pr_number) is not int or observed.pr_number != request.pr_number \
            or type(observed.merged) is not bool or observed.state not in rpg.PR_STATES:
        return None
    return observed


def _post_verified(observed, request, merge_sha) -> bool:
    return observed.merged is True and observed.state == "closed" and observed.head_sha == request.head_sha \
        and observed.merge_commit_sha == merge_sha and observed.develop_tip_sha == merge_sha \
        and observed.merge_commit_parents == (request.base_sha, request.head_sha)


def _post_untouched(observed, request) -> bool:
    return observed.merged is False and observed.state == "open" and observed.head_sha == request.head_sha \
        and observed.develop_tip_sha == request.base_sha


# ---------------------------------------------------------------------------
# The attempt (one request, at most one merge call)
# ---------------------------------------------------------------------------

class _Attempt:
    def __init__(self, request, host, clock):
        self.request, self.host, self.clock = request, host, clock
        self.states, self.steps, self.codes = [], [], []
        self.lease_id = self.command_id = self.reservation_id = self.permit_id = None
        self.lease = self.permit = None
        self.merge_calls = 0
        self.merge_status = self.merge_commit_sha = self.observed_tip = None
        self.already_merged = self.merged_by_attempt = False
        self.planes = dict(structural=False, command=False, permit=False, remote=False)

    def _enter(self, state):
        self.states.append(state)

    def _step(self, step, result=STEP_OK):
        self.steps.append(ExecutionStep(step, result))

    def _port(self, step, call):
        """Calls one host port; any exception becomes _FAILED, without detail."""
        try:
            return call()
        except Exception:  # noqa: BLE001 - no host detail is ever kept
            self._step(step, EXEC_HOST_PORT_FAILED)
            self.codes.append(EXEC_HOST_PORT_FAILED)
            return _FAILED

    def _now(self):
        try:
            now = self.clock()
        except Exception:  # noqa: BLE001
            return None
        return now if rha._clock_ok(now) else None

    def _stop(self, state, step, codes):
        """Records the failing step (unless the port already did) and returns
        the terminal state."""
        if not self.steps or self.steps[-1].step != step:
            self._step(step, codes[0])
        self.codes += codes
        return state

    def run(self):
        self._enter(PREPARED)
        self._step(STEP_VALIDATE_REQUEST)
        self.planes["structural"] = True   # re-derived; fresh reads follow
        try:
            terminal = self._drive()
        except Exception:  # noqa: BLE001 - never escape; uncertainty after a merge call
            self.codes.append(EXEC_INTERNAL_FAILURE)
            terminal = UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION if self.merge_calls else FAILED_SAFE
            if not self.merge_calls and RESERVED not in self.states:
                terminal = PRECONDITION_REFUSED
        terminal = self._finalize(terminal)
        self._release()
        if terminal == UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION:
            self.codes.append(EXEC_NO_RETRY_AFTER_UNCERTAINTY)
        if terminal == MERGED_VERIFIED:
            self.codes.append(EXEC_MERGED_VERIFIED_SIMULATED)
        if terminal != MERGED_VERIFIED:
            self.merged_by_attempt = self.planes["remote"] = False
        self._enter(terminal)
        return terminal

    def _drive(self):
        r, op = self.request, self.request.idempotency_key
        host = self.host

        # Lease / ownership.
        now = self._now()
        if now is None:
            return self._stop(PRECONDITION_REFUSED, STEP_ACQUIRE_LEASE, [EXEC_CLOCK_INVALID])
        grant = self._port(STEP_ACQUIRE_LEASE, lambda: host.acquire_lease(op, _lease_resource(r)))
        if grant is _FAILED or grant is None:
            return self._stop(PRECONDITION_REFUSED, STEP_ACQUIRE_LEASE, [EXEC_LEASE_UNAVAILABLE])
        if type(grant) is LeaseGrant and _id_ok(grant.lease_id):
            self.lease_id = grant.lease_id   # released on every path from here on
        errors = _lease_errors(grant, r, now)
        if errors:
            return self._stop(PRECONDITION_REFUSED, STEP_ACQUIRE_LEASE, errors)
        self.lease = grant
        self._step(STEP_ACQUIRE_LEASE)

        # Plane (b): the human command, verified by the host.
        verdict = self._port(STEP_VERIFY_COMMAND, lambda: host.verify_human_command(
            op, r.repository, r.pr_number, r.base_sha, r.head_sha, r.action))
        now = self._now()
        if verdict is _FAILED or now is None:
            return self._stop(AUTHORIZATION_REFUSED, STEP_VERIFY_COMMAND,
                              [EXEC_COMMAND_ABSENT if now else EXEC_CLOCK_INVALID])
        errors = _command_errors(verdict, r, now)
        if errors:
            return self._stop(AUTHORIZATION_REFUSED, STEP_VERIFY_COMMAND, errors)
        self.command_id = verdict.command_id
        self.planes["command"] = True
        self._step(STEP_VERIFY_COMMAND)

        # Plane (a), fresh: preflight read.
        state = self._port(STEP_PREFLIGHT_READ, lambda: host.read_fresh_state(r.repository, r.pr_number))
        now = self._now()
        if state is _FAILED or now is None:
            return self._stop(PRECONDITION_REFUSED, STEP_PREFLIGHT_READ,
                              [EXEC_FRESH_STATE_MALFORMED if now else EXEC_CLOCK_INVALID])
        preflight = _fresh_findings(r, state, now)
        if preflight["errors"]:
            self.already_merged = preflight["already_merged"]
            return self._stop(PRECONDITION_REFUSED, STEP_PREFLIGHT_READ, preflight["errors"])
        self._step(STEP_PREFLIGHT_READ)

        # Single-use reservation.
        receipt = self._port(STEP_RESERVE, lambda: host.reserve_single_use(op, self.command_id))
        if receipt is _FAILED:
            return self._stop(AUTHORIZATION_REFUSED, STEP_RESERVE, [EXEC_RESERVATION_MALFORMED])
        errors = _reservation_errors(receipt, r, self.command_id)
        if errors:
            return self._stop(AUTHORIZATION_REFUSED, STEP_RESERVE, errors)
        self.reservation_id = receipt.reservation_id
        self._step(STEP_RESERVE)
        self._enter(RESERVED)

        # Plane (c): transient operation permit.
        permit = self._port(STEP_ISSUE_PERMIT, lambda: host.issue_operation_permit(
            op, self.reservation_id, self.command_id))
        now = self._now()
        if permit is _FAILED or now is None:
            return self._stop(AUTHORIZATION_REFUSED, STEP_ISSUE_PERMIT,
                              [EXEC_PERMIT_MALFORMED if now else EXEC_CLOCK_INVALID])
        errors = _permit_errors(permit, r, self.reservation_id, self.command_id, now)
        if errors:
            return self._stop(AUTHORIZATION_REFUSED, STEP_ISSUE_PERMIT, errors)
        self.permit, self.permit_id = permit, permit.permit_id
        self.planes["permit"] = True
        self._step(STEP_ISSUE_PERMIT)

        # Final revalidation immediately before the operation.
        again = self._port(STEP_FINAL_COMMAND_CHECK, lambda: host.verify_human_command(
            op, r.repository, r.pr_number, r.base_sha, r.head_sha, r.action))
        now = self._now()
        if again is _FAILED or now is None:
            self.planes["command"] = False
            return self._stop(AUTHORIZATION_REFUSED, STEP_FINAL_COMMAND_CHECK,
                              [EXEC_COMMAND_ABSENT if now else EXEC_CLOCK_INVALID])
        errors = _command_errors(again, r, now)
        if not errors and again.command_id != self.command_id:
            errors = [EXEC_COMMAND_CHANGED]
        if errors:
            self.planes["command"] = False
            return self._stop(AUTHORIZATION_REFUSED, STEP_FINAL_COMMAND_CHECK, errors)
        self._step(STEP_FINAL_COMMAND_CHECK)

        state = self._port(STEP_FINAL_READ, lambda: host.read_fresh_state(r.repository, r.pr_number))
        now = self._now()
        if state is _FAILED or now is None:
            return self._stop(PRECONDITION_REFUSED, STEP_FINAL_READ,
                              [EXEC_FRESH_STATE_MALFORMED if now else EXEC_CLOCK_INVALID])
        final = _fresh_findings(r, state, now)
        errors = list(final["errors"])
        if not errors and final["digest"] != preflight["digest"]:
            errors = [EXEC_STATE_CHANGED_DURING_PREFLIGHT]
        if errors:
            self.already_merged = final["already_merged"]
            return self._stop(PRECONDITION_REFUSED, STEP_FINAL_READ, errors)
        if _window(self.permit.issued_at, self.permit.expires_at, now, MAX_PERMIT_TTL_SECONDS):
            self.planes["permit"] = False
            return self._stop(AUTHORIZATION_REFUSED, STEP_FINAL_READ, [EXEC_PERMIT_EXPIRED])
        if _window(self.lease.acquired_at, self.lease.expires_at, now, MAX_LEASE_SECONDS):
            return self._stop(PRECONDITION_REFUSED, STEP_FINAL_READ, [EXEC_LEASE_EXPIRED])
        self._step(STEP_FINAL_READ)

        # Consumption BEFORE the operation: a crash can never allow a replay.
        consumed = self._port(STEP_CONSUME, lambda: host.consume_single_use(self.reservation_id))
        if consumed is _FAILED or _consumption_errors(consumed, r, self.reservation_id):
            return self._stop(FAILED_SAFE, STEP_CONSUME, [EXEC_CONSUMPTION_FAILED])
        self._step(STEP_CONSUME)

        # The ONE operation: Merge PR API with the expected head SHA.
        self._enter(MERGE_ATTEMPTED)
        self.merge_calls += 1
        response = self._port(STEP_MERGE, lambda: host.merge_pull_request(
            r.repository, r.pr_number, r.head_sha, MERGE_METHOD, self.permit_id))
        status = None if response is _FAILED else _response_status(response, r)
        if response is not _FAILED:
            self._step(STEP_MERGE, STEP_OK if status else EXEC_MERGE_OUTCOME_UNKNOWN)
        self.merge_status = status
        observed = self._port(STEP_POSTCONDITION_READ, lambda: host.read_postcondition(r.repository, r.pr_number))
        observed = None if observed is _FAILED else _post_value(observed, r)
        if observed is not None:
            self.observed_tip = observed.develop_tip_sha
            self._step(STEP_POSTCONDITION_READ)
        elif not self.steps or self.steps[-1].step != STEP_POSTCONDITION_READ:
            self._step(STEP_POSTCONDITION_READ, EXEC_POSTCONDITION_UNREAD)
        return self._classify(status, response, observed)

    def _classify(self, status, response, observed):
        r = self.request
        if status is None or status == MERGE_TIMEOUT_AFTER_SEND:
            self.codes.append(EXEC_MERGE_OUTCOME_UNKNOWN)
            if observed is not None and observed.merged:
                self.codes.append(EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED)
            return UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION
        if status == MERGE_MERGED:
            if observed is None:
                self.codes.append(EXEC_POSTCONDITION_UNREAD)
                return UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION
            if not _post_verified(observed, r, response.merge_commit_sha):
                self.codes.append(EXEC_POSTCONDITION_CONTRADICTS)
                if observed.merge_commit_parents[:1] != (r.base_sha,):
                    self.codes.append(EXEC_POST_BASE_DRIFT)
                return UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION
            self.merge_commit_sha = response.merge_commit_sha
            self.merged_by_attempt = self.planes["remote"] = True
            return MERGED_VERIFIED
        self.codes.append(_REJECTION_CODES[status])   # explicit rejection or not sent: never a fallback write
        if observed is None:
            self.codes.append(EXEC_POSTCONDITION_UNREAD)
            return FAILED_SAFE
        if not _post_untouched(observed, r):
            self.codes.append(EXEC_POSTCONDITION_CONTRADICTS)
            if observed.merged:
                self.codes.append(EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED)
            return UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION
        return FAILED_SAFE

    def _finalize(self, terminal):
        if self.reservation_id is None:
            return terminal
        done = self._port(STEP_FINALIZE_RESERVATION,
                          lambda: self.host.finalize_reservation(self.reservation_id, terminal))
        if done is _FAILED:
            self.codes.append(EXEC_LEDGER_FINALIZE_FAILED)
            return UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION if self.merge_calls else terminal
        self._step(STEP_FINALIZE_RESERVATION)
        return terminal

    def _release(self):
        if self.lease_id is None:
            return
        done = self._port(STEP_RELEASE_LEASE, lambda: self.host.release_lease(self.lease_id))
        if done is _FAILED:
            self.codes.append(EXEC_LEASE_RELEASE_FAILED)
        else:
            self._step(STEP_RELEASE_LEASE)


# ---------------------------------------------------------------------------
# Outcomes and entry points
# ---------------------------------------------------------------------------

def _outcome(state, mode, request=None, codes=(), attempt=None, states=None, steps=None) -> PromotionExecutionOutcome:
    bound = request if type(request) is PromotionExecutionRequest and not _request_errors(request) else None
    a = attempt
    reasons = list(codes) + (a.codes if a else []) + list(_MODE_CODES[mode]) + list(_ALWAYS)
    draft = PromotionExecutionOutcome(
        state=state, reason_codes=tuple(dict.fromkeys(reasons)), fingerprint="", execution_mode=mode,
        operation_id=bound.idempotency_key if bound else None,
        request_fingerprint=bound.fingerprint if bound else None,
        repository=bound.repository if bound else None, pr_number=bound.pr_number if bound else None,
        base_sha=bound.base_sha if bound else None, head_sha=bound.head_sha if bound else None,
        action=bound.action if bound else None,
        lease_id=a.lease_id if a else None, command_id=a.command_id if a else None,
        reservation_id=a.reservation_id if a else None, permit_id=a.permit_id if a else None,
        merge_call_count=a.merge_calls if a else 0, merge_response_status=a.merge_status if a else None,
        merge_commit_sha=a.merge_commit_sha if a else None, observed_develop_tip_sha=a.observed_tip if a else None,
        observed_already_merged=a.already_merged if a else False,
        merge_performed_by_this_attempt=a.merged_by_attempt if a else False,
        structural_eligibility_passed=a.planes["structural"] if a else False,
        host_command_check_passed=a.planes["command"] if a else False,
        operation_permit_check_passed=a.planes["permit"] if a else False,
        remote_postcondition_confirmed=a.planes["remote"] if a else False,
        human_reconciliation_required=state == UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
        state_trace=tuple(a.states if a else states or (state,)),
        step_trace=tuple(a.steps if a else steps or ()),
    )
    return dataclasses.replace(draft, fingerprint=outcome_fingerprint(draft))


def _refused(state, mode, request, codes) -> PromotionExecutionOutcome:
    return _outcome(state, mode, request, codes, steps=(ExecutionStep(STEP_VALIDATE_REQUEST, codes[0]),))


def _system_clock() -> datetime:
    return datetime.now(timezone.utc)


def simulate_promotion(request, host, *, clock=None) -> PromotionExecutionOutcome:
    """Drives ONE attempt against in-memory simulation ports. The request is
    re-derived first; a missing or non-simulation host is refused before any
    port is touched. Never raises; at most one merge call; the outcome is
    always SIMULATED and never a real or authorized promotion. `clock`
    defaults to the system UTC clock and is read at every check."""
    try:
        errors = _request_errors(request)
    except Exception:  # noqa: BLE001
        errors = [EXEC_REQUEST_MALFORMED]
    if errors:
        return _refused(PRECONDITION_REFUSED, MODE_SIMULATED, request, errors)
    if host is None or getattr(type(host), "host_kind", None) != HOST_KIND_IN_MEMORY_SIMULATION \
            or type(getattr(type(host), "host_kind", None)) is not str:
        return _refused(AUTHORIZATION_REFUSED, MODE_SIMULATED, request, [EXEC_TRUSTED_HOST_ABSENT])
    attempt = _Attempt(request, host, _system_clock if clock is None else clock)
    state = attempt.run()
    return _outcome(state, MODE_SIMULATED, request, attempt=attempt)


def execute_promotion(request) -> PromotionExecutionOutcome:
    """Production entry. No audited privileged host and no authenticated human
    command source exist in this delivery, so it ALWAYS refuses, accepts no
    port, calls nothing and merges nothing. Never raises."""
    try:
        errors = _request_errors(request)
    except Exception:  # noqa: BLE001
        errors = [EXEC_REQUEST_MALFORMED]
    return _refused(AUTHORIZATION_REFUSED, MODE_PRODUCTION_BLOCKED, request,
                    [EXEC_TRUSTED_HOST_NOT_AVAILABLE, EXEC_PRODUCTION_ADAPTER_NOT_IMPLEMENTED, *errors])


# ---------------------------------------------------------------------------
# Outcome invariants
# ---------------------------------------------------------------------------

def _trace_ok(trace, final) -> bool:
    if type(trace) is not tuple or not trace or trace[-1] != final:
        return False
    previous = _START
    for state in trace:
        if state not in TRANSITIONS.get(previous, ()):
            return False
        previous = state
    return True


def outcome_invariant_errors(outcome) -> tuple:
    """Stable codes of every violated outcome invariant (empty when sound)."""
    if type(outcome) is not PromotionExecutionOutcome or not _plain(outcome, (PromotionExecutionOutcome,
                                                                              ExecutionStep)):
        return ("INV_MALFORMED",)
    o, errors = outcome, []
    try:
        if o.fingerprint != outcome_fingerprint(o):
            errors.append("INV_FINGERPRINT")
    except Exception:  # noqa: BLE001
        errors.append("INV_FINGERPRINT")
    if o.schema != OUTCOME_SCHEMA or o.state not in TERMINAL_STATES or not _trace_ok(o.state_trace, o.state):
        errors.append("INV_STATE")
    if o.execution_mode not in (MODE_SIMULATED, MODE_PRODUCTION_BLOCKED) or o.live_authorized is not False \
            or o.production_capable is not False or o.human_command_authenticated is not False \
            or o.retry_allowed is not False or o.executor_requirements_unmet != PRODUCTION_ACTIVATION_REQUIREMENTS:
        errors.append("INV_NOT_LIVE")
    codes = o.reason_codes
    if type(codes) is not tuple or len(set(codes)) != len(codes) \
            or not all(type(c) is str and c.startswith(_CODE_PREFIXES) for c in codes) \
            or o.execution_mode not in _MODE_CODES \
            or not set(_ALWAYS + _MODE_CODES[o.execution_mode]) <= set(codes):
        errors.append("INV_REASON_CODES")
    attempted = MERGE_ATTEMPTED in (o.state_trace if type(o.state_trace) is tuple else ())
    if o.merge_call_count not in (0, 1) or (o.merge_call_count == 1) != attempted:
        errors.append("INV_MERGE_CALLS")
    if o.state in (AUTHORIZATION_REFUSED, PRECONDITION_REFUSED) and o.merge_call_count:
        errors.append("INV_REFUSAL_MERGED")
    if (o.state == UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION) != (o.human_reconciliation_required is True) \
            or (o.state == UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION and o.merge_call_count != 1):
        errors.append("INV_UNCERTAIN")
    verified = o.state == MERGED_VERIFIED
    if o.merge_performed_by_this_attempt is not verified or o.remote_postcondition_confirmed is not verified:
        errors.append("INV_MERGE_CLAIM")
    if verified and not (o.structural_eligibility_passed and o.host_command_check_passed
                         and o.operation_permit_check_passed and o.merge_response_status == MERGE_MERGED
                         and o.merge_commit_sha is not None and o.observed_develop_tip_sha == o.merge_commit_sha
                         and o.execution_mode == MODE_SIMULATED and not o.observed_already_merged):
        errors.append("INV_VERIFIED_EVIDENCE")
    if o.execution_mode == MODE_PRODUCTION_BLOCKED and (
            o.state != AUTHORIZATION_REFUSED or o.merge_call_count or o.lease_id or o.command_id
            or any(s.step != STEP_VALIDATE_REQUEST for s in o.step_trace)):
        errors.append("INV_PRODUCTION_TOUCHED_HOST")
    return tuple(errors)


def verify_outcome(outcome) -> bool:
    """True only if every outcome invariant holds."""
    return outcome_invariant_errors(outcome) == ()

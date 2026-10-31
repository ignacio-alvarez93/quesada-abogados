"""FCP-10C-02: Governed quota recovery and evidence-failure advisor - pure,
deterministic, fail-closed, provider-neutral, READ-ONLY, NON-AUTHORITATIVE.

Answers ONE question: given the quota evidence the caller ALREADY holds
(an FCP-10A-02 `ObservationRequest`), the Runner results it ALREADY read
(`workers/<id>/result.json` and its `pipeline_result.json` entry), optional
explicit provider / auditor verdict texts, an optional declared deadline and,
optionally, the evidence of a proposed COMPOSITE recovery, what does that
evidence say about recovery from QUOTA_WAIT, about the Runner's own native
continuations, about each worker's outcome, and who alone may act next? It
never answers "may I dispatch / retry / resume / commit now?".

Why this is an advisor, not a recovery mechanism
------------------------------------------------
* Director and Runner stay the ONLY execution and Git authorities. The
  Runner alone ends a quota hold (`PipelineRunner._refresh` ->
  `PROVIDER_QUOTA_ELIGIBLE`, then its own next attempt), reconciles prior
  work (`_try_prior_work_reconciliation`: RECONCILED_FROM_PRIOR_ATTEMPT or
  PENDING_PROVIDER_CONTINUATION with its own `pending_resume_from`) and
  checkpoints (`ON_SUCCESS`). Nothing here transitions a state, retries,
  waits, sleeps, re-queues, derives a `resume_from`, switches a provider,
  buys, calls a remote API, runs a process, commits, rewrites a DAG or its
  history or touches Git, the filesystem, the clock, the environment or the
  network. The instant is the A02 request's explicit `as_of_utc`.
* Composition, not duplication: quota evidence goes through FCP-10A-02
  `adapt_observations` as is and every verdict text through the Runner's
  own `runner_providers.extract_verdict`. FCP-6 failure intelligence is
  CONSUMED, never imported: the frozen FCP-6C-04 guard admits only its two
  approved adapters as importers of 6A/6B, so the caller hands over the
  `WorkerDiagnostic` its own `runner_failure_intelligence.assess_worker`
  produced for that very result. It is checked against the FCP-6 vocabulary
  mirrored here (pinned to FCP-6 by the test suite) and against the
  result's own identity and state; a forged, foreign or inconsistent
  diagnostic is RUNNER_EVIDENCE_INTEGRITY, never trusted.
* Recovery is never inferred from the clock. A QUOTA_WAIT whose Runner-
  computed `next_eligible_utc` (RESET_HINT / BACKOFF_PROBE: the verified
  cooldown) is still ahead is COOLDOWN_PENDING; one whose instant has passed
  is RECOVERY_UNCONFIRMED (only the Runner's own next probe can end it). A
  provider is AVAILABLE_OBSERVED only when A02 itself observed NONE without
  doubt AND no FCP-6 diagnostic of a worker on it still reports a quota or
  auth hold (otherwise the evidence contradicts itself: UNKNOWN). A declared
  deadline that is reached, or that the eligibility instant does not
  precede, is DEADLINE_BLOCKED for a human: a new window is a decision.
* Runner technical SUCCESS (FCP-6 `SUCCESS_CONSISTENT`) is kept apart from
  the provider's own work status / textual verdict and from the auditor's
  textual verdict. The verdict classifier is conservative: only an exact,
  single, explicit `VERDICT=` token (PASS / PASSED / SUCCESS) reads PASS;
  anything the Runner itself reads as negative stays negative; anything
  else is UNVERIFIED; disagreeing lines are AMBIGUOUS. A worker's
  `work_verdict` is the most severe of its three axes
  (BLOCKED > FAIL > UNVERIFIED > PASS), so an auditor BLOCKED is never PASS
  and an absent audit is never PASS. Raw text is never echoed.
* Composite recovery (one checkpoint consolidating several components) is
  only ever ASSESSED against a formal criterion, never performed:
  well-formed component products (path -> sha256) and commits, no path
  touched by two components, a composite diff that is exactly the union of
  the components (union-only), every composite and observed tree hash equal
  to its component's, complete GLOBAL and HISTORICAL test runs on the
  composite commit with zero failures, errors, skips, expected failures and
  unexpected successes, a Host attestation bound to the composite commit and
  to `composite_evidence_fingerprint`, every component bound to a worker of
  this request with safe Runner evidence and PASS on BOTH its Runner and
  provider axes (BLOCKED, cancelled, preflight-refused, incomplete,
  UNVERIFIED or absent never qualify for lack of a FAIL), no explicit
  non-PASS auditor verdict, every component provider AVAILABLE_OBSERVED,
  and a VERIFIED Direction authorization. Any miss is BLOCKED. A
  well-formed `direction_authorization_id` is only a citation: it is
  VERIFIED only by the cited Direction act (`DirectionAuthorization`)
  bound to the composite commit, to `composite_evidence_fingerprint` and
  to the valid Host attestation it follows (a distinct act, never before
  it, never after the instant). A bare id, an unbound, mismatched or
  premature act is DIRECTION_AUTHORIZATION_UNVERIFIED and the composite
  stays BLOCKED. Verifying that binding grants nothing: Direction remains
  the authority, and even CRITERIA_MET authorizes nothing - the FCP-9
  C01/E02 exception is not a precedent.

Outcome (`RecoveryAdvice`, schema `fcp10c02-resource-quota-recovery-advice-
v1`): REFUSED (invalid request, nothing echoed) > BLOCKED (a human or
Direction must act) > UNKNOWN (evidence doubt) > WAITING (the Runner or the
read-only audit owns the next step) > CLEAR (nothing to recover; needs cited
evidence). None is a permit. The advice holds only validated ids, enumerated
codes, normalized UTC instants, integers, repository-relative paths and
fingerprints, and fixes every FCP-10A-01 zero-authority flag plus
`state_mutated`, `retry_scheduled`, `resume_from_derived`, `commit_created`,
`history_rewritten`, `checkpoint_consolidated` and `verdict_upgraded` to
False as read-only properties.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_observation as qo
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_providers as providers
except ImportError:  # pragma: no cover - direct script execution
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_observation as qo  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_providers as providers  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp10c02-resource-quota-recovery-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10c02-resource-quota-recovery-advice-v1"
SCHEMA_VERSION = 1
COMPOSITE_EVIDENCE_SCHEMA = "fcp10c02-composite-recovery-evidence-v1"
RECOVERY_MARKER = "FCP10C02_RECOVERY_ADVISORY_ONLY_READ_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_WORKERS = sc.MAX_ITEMS
MAX_COMPONENTS = 16
MAX_PATHS = 256
MAX_PATH_CHARS = 240
MAX_VERDICT_TEXT_CHARS = 65536
MAX_TEST_RUNS = 8
MAX_TEST_COUNT = 1_000_000
MAX_CANONICAL_JSON_BYTES = 262144

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

REFUSED = "REFUSED"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
WAITING = "WAITING"
CLEAR = "CLEAR"
OUTCOMES = (REFUSED, BLOCKED, UNKNOWN, WAITING, CLEAR)
STATUSES = (BLOCKED, UNKNOWN, WAITING, CLEAR)

ACTOR_HUMAN = "HUMAN_OPERATOR"
ACTOR_DIRECTION = "DIRECTION"
ACTOR_RUNNER = "RUNNER"
ACTOR_NONE = "NONE"
ACTORS = (ACTOR_HUMAN, ACTOR_DIRECTION, ACTOR_RUNNER, ACTOR_NONE)

# Explicit verdict classes (classifier output) and composed work verdicts.
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_BLOCKED = "BLOCKED"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_UNVERIFIED = "UNVERIFIED"
VERDICT_AMBIGUOUS = "AMBIGUOUS"
VERDICT_ABSENT = "ABSENT"
VERDICT_CLASSES = (VERDICT_PASS, VERDICT_FAIL, VERDICT_BLOCKED, VERDICT_PARTIAL, VERDICT_UNVERIFIED,
                   VERDICT_AMBIGUOUS, VERDICT_ABSENT)
WORK_VERDICTS = (VERDICT_BLOCKED, VERDICT_FAIL, VERDICT_UNVERIFIED, VERDICT_PASS)  # most severe first
_WORK_VERDICT_OF = {
    VERDICT_PASS: VERDICT_PASS, VERDICT_FAIL: VERDICT_FAIL, VERDICT_BLOCKED: VERDICT_BLOCKED,
    VERDICT_PARTIAL: VERDICT_BLOCKED, VERDICT_AMBIGUOUS: VERDICT_BLOCKED, VERDICT_UNVERIFIED: VERDICT_UNVERIFIED,
    VERDICT_ABSENT: VERDICT_UNVERIFIED,
}
_NEGATIVE_CLASSES = frozenset({VERDICT_FAIL, VERDICT_BLOCKED, VERDICT_PARTIAL, VERDICT_AMBIGUOUS})
# The only explicit tokens that read PASS (exact, after the Runner's own
# line extraction); everything else is never more positive than UNVERIFIED.
EXPLICIT_PASS_TOKENS = frozenset({"PASS", "PASSED", "SUCCESS"})
EXPLICIT_UNVERIFIED_TOKENS = frozenset({"UNVERIFIED", "INVALID_VERDICT"})
_CLASS_OF_STATUS = {
    providers.WorkStatus.SUCCESS: VERDICT_PASS, providers.WorkStatus.FAILED: VERDICT_FAIL,
    providers.WorkStatus.BLOCKED: VERDICT_BLOCKED, providers.WorkStatus.PARTIAL: VERDICT_PARTIAL,
}
# The Runner's raw `provider_work_status` values (providers.WorkStatus).
_CLASS_OF_PROVIDER_WORK_STATUS = {
    "SUCCESS": VERDICT_PASS, "FAILED": VERDICT_FAIL, "BLOCKED": VERDICT_BLOCKED, "PARTIAL": VERDICT_PARTIAL,
    "UNVERIFIED": VERDICT_UNVERIFIED, "INVALID_VERDICT": VERDICT_UNVERIFIED,
}

VERDICT_TEXT_MALFORMED = "VERDICT_TEXT_MALFORMED"
VERDICT_NOT_FOUND = "VERDICT_NOT_FOUND"
VERDICT_UNRECOGNIZED = "VERDICT_UNRECOGNIZED"
VERDICT_NOT_EXPLICIT = "VERDICT_NOT_EXPLICIT"
VERDICT_CONFLICTING = "VERDICT_CONFLICTING"
READING_REASONS = (VERDICT_TEXT_MALFORMED, VERDICT_NOT_FOUND, VERDICT_UNRECOGNIZED, VERDICT_NOT_EXPLICIT,
                   VERDICT_CONFLICTING)

# Native continuation (the Runner's own `attempt["reconciliation"]["decision"]`).
CONTINUATION_NONE = "NONE"
CONTINUATION_NATIVE_PENDING = "PENDING_PROVIDER_CONTINUATION"
CONTINUATION_RECONCILED = "RECONCILED_FROM_PRIOR_ATTEMPT"
CONTINUATION_UNREADABLE = "SKIPPED_WORK_PRODUCT_UNREADABLE"
CONTINUATION_UNRECOGNIZED = "UNRECOGNIZED"
CONTINUATIONS = (CONTINUATION_NONE, CONTINUATION_NATIVE_PENDING, CONTINUATION_RECONCILED, CONTINUATION_UNREADABLE,
                 CONTINUATION_UNRECOGNIZED)
_NATIVE_CONTINUATIONS = frozenset(CONTINUATIONS[1:4])

# Provider recoveries, their status, actor and action.
AVAILABLE_OBSERVED = "AVAILABLE_OBSERVED"
COOLDOWN_PENDING = "COOLDOWN_PENDING"
RECOVERY_UNCONFIRMED = "RECOVERY_UNCONFIRMED"
DEADLINE_BLOCKED = "DEADLINE_BLOCKED"
AUTH_BLOCKED = "AUTH_BLOCKED"
PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
PROVIDER_RECOVERIES = (AUTH_BLOCKED, DEADLINE_BLOCKED, PROVIDER_UNKNOWN, RECOVERY_UNCONFIRMED, COOLDOWN_PENDING,
                       AVAILABLE_OBSERVED)

RESTORE_PROVIDER_AUTH = "RESTORE_PROVIDER_AUTH"
DECIDE_NEW_EXECUTION_WINDOW = "DECIDE_NEW_EXECUTION_WINDOW"
REVIEW_QUOTA_EVIDENCE = "REVIEW_QUOTA_EVIDENCE"
OBSERVE_RUNNER_QUOTA_PROBE = "OBSERVE_RUNNER_QUOTA_PROBE"
AWAIT_RUNNER_ELIGIBILITY = "AWAIT_RUNNER_ELIGIBILITY"
REVIEW_RUNNER_EVIDENCE = "REVIEW_RUNNER_EVIDENCE"
CONFIRM_PROVIDER_PROCESS_STOPPED = "CONFIRM_PROVIDER_PROCESS_STOPPED"
REVIEW_SAFETY_REFUSAL = "REVIEW_SAFETY_REFUSAL"
REVIEW_INTERRUPTED_WORK = "REVIEW_INTERRUPTED_WORK"
AWAIT_RUNNER_NATIVE_CONTINUATION = "AWAIT_RUNNER_NATIVE_CONTINUATION"
AWAIT_RUNNER_QUOTA_REEVALUATION = "AWAIT_RUNNER_QUOTA_REEVALUATION"
OBSERVE_RUNNER = "OBSERVE_RUNNER"
REQUEST_DIRECTION = "REQUEST_DIRECTION"
AWAIT_READ_ONLY_AUDIT = "AWAIT_READ_ONLY_AUDIT"
REVIEW_WORK_OUTCOME = "REVIEW_WORK_OUTCOME"
NO_ACTION = "NO_ACTION"
ACTIONS = (RESTORE_PROVIDER_AUTH, DECIDE_NEW_EXECUTION_WINDOW, REVIEW_QUOTA_EVIDENCE, OBSERVE_RUNNER_QUOTA_PROBE,
           AWAIT_RUNNER_ELIGIBILITY, REVIEW_RUNNER_EVIDENCE, CONFIRM_PROVIDER_PROCESS_STOPPED, REVIEW_SAFETY_REFUSAL,
           REVIEW_INTERRUPTED_WORK, AWAIT_RUNNER_NATIVE_CONTINUATION, AWAIT_RUNNER_QUOTA_REEVALUATION,
           OBSERVE_RUNNER, REQUEST_DIRECTION, AWAIT_READ_ONLY_AUDIT, REVIEW_WORK_OUTCOME, NO_ACTION)

PROVIDER_RULES = {
    AUTH_BLOCKED: (BLOCKED, ACTOR_HUMAN, RESTORE_PROVIDER_AUTH),
    DEADLINE_BLOCKED: (BLOCKED, ACTOR_HUMAN, DECIDE_NEW_EXECUTION_WINDOW),
    PROVIDER_UNKNOWN: (UNKNOWN, ACTOR_HUMAN, REVIEW_QUOTA_EVIDENCE),
    RECOVERY_UNCONFIRMED: (WAITING, ACTOR_RUNNER, OBSERVE_RUNNER_QUOTA_PROBE),
    COOLDOWN_PENDING: (WAITING, ACTOR_RUNNER, AWAIT_RUNNER_ELIGIBILITY),
    AVAILABLE_OBSERVED: (CLEAR, ACTOR_NONE, NO_ACTION),
}

# Provider reason codes, in their fixed canonical order.
OBSERVED_AUTH_BLOCKED = "OBSERVED_AUTH_BLOCKED"
DIAGNOSTIC_AUTH_BLOCKED = "DIAGNOSTIC_AUTH_BLOCKED"
DEADLINE_REACHED = "DEADLINE_REACHED"
DEADLINE_PRECEDES_ELIGIBILITY = "DEADLINE_PRECEDES_ELIGIBILITY"
QUOTA_EVIDENCE_DOUBT = "QUOTA_EVIDENCE_DOUBT"
QUOTA_EVIDENCE_MISSING = "QUOTA_EVIDENCE_MISSING"
CONDITION_UNRESOLVED = "CONDITION_UNRESOLVED"
ELIGIBILITY_UNOBSERVED = "ELIGIBILITY_UNOBSERVED"
DIAGNOSTIC_CONTRADICTS_OBSERVATION = "DIAGNOSTIC_CONTRADICTS_OBSERVATION"
ELIGIBILITY_PASSED_UNCONFIRMED = "ELIGIBILITY_PASSED_UNCONFIRMED"
COOLDOWN_VERIFIED_PENDING = "COOLDOWN_VERIFIED_PENDING"
PROVIDER_REASONS = (OBSERVED_AUTH_BLOCKED, DIAGNOSTIC_AUTH_BLOCKED, DEADLINE_REACHED, DEADLINE_PRECEDES_ELIGIBILITY,
                    QUOTA_EVIDENCE_DOUBT, QUOTA_EVIDENCE_MISSING, CONDITION_UNRESOLVED, ELIGIBILITY_UNOBSERVED,
                    DIAGNOSTIC_CONTRADICTS_OBSERVATION, ELIGIBILITY_PASSED_UNCONFIRMED, COOLDOWN_VERIFIED_PENDING)

# Worker reason codes, in their fixed canonical order.
RUNNER_EVIDENCE_INTEGRITY = "RUNNER_EVIDENCE_INTEGRITY"
WORKER_PROVIDER_MISMATCH = "WORKER_PROVIDER_MISMATCH"
PROCESS_TERMINATION_UNRESOLVED = "PROCESS_TERMINATION_UNRESOLVED"
SAFETY_REFUSAL = "SAFETY_REFUSAL"
INTERRUPTED_OPERATOR_REVIEW = "INTERRUPTED_OPERATOR_REVIEW"
PROVIDER_AUTH_BLOCKED = "PROVIDER_AUTH_BLOCKED"
PROVIDER_QUOTA_WAIT = "PROVIDER_QUOTA_WAIT"
NATIVE_CONTINUATION_PENDING = "NATIVE_CONTINUATION_PENDING"
CONTINUATION_EVIDENCE_UNRECOGNIZED = "CONTINUATION_EVIDENCE_UNRECOGNIZED"
TRANSIENT_RETRY_WAIT = "TRANSIENT_RETRY_WAIT"
NOT_TERMINAL = "NOT_TERMINAL"
RUNNER_WORK_FAILED = "RUNNER_WORK_FAILED"
RUNNER_WORK_BLOCKED = "RUNNER_WORK_BLOCKED"
PROVIDER_VERDICT_DIVERGENT = "PROVIDER_VERDICT_DIVERGENT"
PROVIDER_VERDICT_NOT_PASS = "PROVIDER_VERDICT_NOT_PASS"
AUDITOR_VERDICT_NOT_PASS = "AUDITOR_VERDICT_NOT_PASS"
AUDITOR_VERDICT_ABSENT = "AUDITOR_VERDICT_ABSENT"
WORK_UNVERIFIED = "WORK_UNVERIFIED"
# Worker reasons in their fixed canonical order: the first one a worker
# carries fixes its status, actor and action; no reason at all is CLEAR.
WORKER_RULES = (
    (RUNNER_EVIDENCE_INTEGRITY, UNKNOWN, ACTOR_HUMAN, REVIEW_RUNNER_EVIDENCE),
    (WORKER_PROVIDER_MISMATCH, UNKNOWN, ACTOR_HUMAN, REVIEW_RUNNER_EVIDENCE),
    (PROCESS_TERMINATION_UNRESOLVED, BLOCKED, ACTOR_HUMAN, CONFIRM_PROVIDER_PROCESS_STOPPED),
    (SAFETY_REFUSAL, BLOCKED, ACTOR_HUMAN, REVIEW_SAFETY_REFUSAL),
    (INTERRUPTED_OPERATOR_REVIEW, BLOCKED, ACTOR_HUMAN, REVIEW_INTERRUPTED_WORK),
    (PROVIDER_AUTH_BLOCKED, BLOCKED, ACTOR_HUMAN, RESTORE_PROVIDER_AUTH),
    (CONTINUATION_EVIDENCE_UNRECOGNIZED, UNKNOWN, ACTOR_HUMAN, REVIEW_RUNNER_EVIDENCE),
    (NATIVE_CONTINUATION_PENDING, WAITING, ACTOR_RUNNER, AWAIT_RUNNER_NATIVE_CONTINUATION),
    (PROVIDER_QUOTA_WAIT, WAITING, ACTOR_RUNNER, AWAIT_RUNNER_QUOTA_REEVALUATION),
    (TRANSIENT_RETRY_WAIT, WAITING, ACTOR_RUNNER, OBSERVE_RUNNER),
    (NOT_TERMINAL, WAITING, ACTOR_RUNNER, OBSERVE_RUNNER),
    (RUNNER_WORK_FAILED, BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    (RUNNER_WORK_BLOCKED, BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    (PROVIDER_VERDICT_DIVERGENT, BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    (AUDITOR_VERDICT_NOT_PASS, BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    (PROVIDER_VERDICT_NOT_PASS, BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    (WORK_UNVERIFIED, UNKNOWN, ACTOR_HUMAN, REVIEW_WORK_OUTCOME),
    (AUDITOR_VERDICT_ABSENT, WAITING, ACTOR_DIRECTION, AWAIT_READ_ONLY_AUDIT),
)
WORKER_REASONS = tuple(rule[0] for rule in WORKER_RULES)
_WORKER_RULE = {rule[0]: rule[1:] for rule in WORKER_RULES}
# Worker reasons a composite judges through its verdict axes (Runner,
# provider, auditor); any other worker reason is unsafe component evidence.
_COMPOSITE_VERDICT_REASONS = frozenset({
    RUNNER_WORK_FAILED, RUNNER_WORK_BLOCKED, PROVIDER_VERDICT_DIVERGENT, PROVIDER_VERDICT_NOT_PASS,
    AUDITOR_VERDICT_NOT_PASS, AUDITOR_VERDICT_ABSENT, WORK_UNVERIFIED})

# Mirror of the FCP-6A-01 vocabulary (`runner_failure_intelligence`; pinned
# by tests, never imported, see the module docstring).
FI_DIAGNOSTIC_MARKER = "FCP6A01_INFORMATIONAL_NOT_CERTIFIED_NOT_AUTHORIZED"
FI_SCHEMA_WORKER = "fcp6a01-runner-worker-diagnostic-v1"
FI_DIAGNOSTIC_TYPE = "WorkerDiagnostic"
FI_MODULE_NAME = "runner_failure_intelligence"
FI_UNRECOGNIZED = "UNRECOGNIZED"
FI_WORKER_STATES = frozenset({
    "QUEUED", "WAITING_DEPENDENCY", "READY", "RUNNING", "RETRY_WAIT", "WAITING_PROVIDER_QUOTA",
    "BLOCKED_PROVIDER_AUTH", "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED", "INTERRUPTED",
})
FI_WORK_STATUS_SOURCES = frozenset({"PROVIDER", "RUNNER_ACCEPTANCE"})
FI_REASON_PRECEDENCE = (
    "MALFORMED_EVIDENCE", "IDENTITY_MISMATCH", "DUPLICATE_WORKER_ID", "UNKNOWN_STATE", "AGGREGATE_CONTRADICTION",
    "CONFLICTING_EVIDENCE", "RETRY_DECISION_UNRECOGNIZED", "PROCESS_TERMINATION_UNRESOLVED", "SAFETY_REFUSAL",
    "INTERRUPTED_OPERATOR_REVIEW", "PROVIDER_AUTH_BLOCKED", "CHECKPOINT_FAILED", "ACCEPTANCE_FAILED",
    "PREFLIGHT_REFUSED", "DEPENDENCY_CANCELLED", "NATIVE_CANCELLED", "NATIVE_FAILED", "NATIVE_BLOCKED",
    "PARTIAL_COMPLETION", "EVIDENCE_INCOMPLETE", "PROVIDER_QUOTA_WAIT", "TRANSIENT_RETRY_WAIT", "NOT_TERMINAL",
    "MISSING_WORKER_RESULT", "EXTRA_WORKER_RESULT", "EVIDENCE_MISSING", "EVIDENCE_UNPROVEN", "EMPTY_PIPELINE",
    "SUCCESS_CONSISTENT",
)
FI_ZERO_AUTHORITY_FLAGS = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed")
_FI_TOKEN_HEAD = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_FI_TOKEN_TAIL = _FI_TOKEN_HEAD | frozenset("0123456789_")

# FCP-6 reason codes read here (never reinterpreted, only grouped).
_FI_INTEGRITY = frozenset({"MALFORMED_EVIDENCE", "IDENTITY_MISMATCH", "DUPLICATE_WORKER_ID", "UNKNOWN_STATE",
                           "AGGREGATE_CONTRADICTION", "CONFLICTING_EVIDENCE", "RETRY_DECISION_UNRECOGNIZED",
                           "EVIDENCE_MISSING"})
_FI_FAILED = frozenset({"NATIVE_FAILED", "ACCEPTANCE_FAILED"})
_FI_BLOCKED = frozenset({"PROCESS_TERMINATION_UNRESOLVED", "SAFETY_REFUSAL", "INTERRUPTED_OPERATOR_REVIEW",
                         "PROVIDER_AUTH_BLOCKED", "CHECKPOINT_FAILED", "PREFLIGHT_REFUSED", "DEPENDENCY_CANCELLED",
                         "NATIVE_CANCELLED", "NATIVE_BLOCKED", "PARTIAL_COMPLETION", "EVIDENCE_INCOMPLETE"})
_FI_DIRECT = {"PROCESS_TERMINATION_UNRESOLVED": PROCESS_TERMINATION_UNRESOLVED, "SAFETY_REFUSAL": SAFETY_REFUSAL,
              "INTERRUPTED_OPERATOR_REVIEW": INTERRUPTED_OPERATOR_REVIEW,
              "PROVIDER_AUTH_BLOCKED": PROVIDER_AUTH_BLOCKED, "PROVIDER_QUOTA_WAIT": PROVIDER_QUOTA_WAIT,
              "TRANSIENT_RETRY_WAIT": TRANSIENT_RETRY_WAIT, "NOT_TERMINAL": NOT_TERMINAL}
_FI_UNSAFE_FOR_COMPOSITE = _FI_INTEGRITY | {"PROCESS_TERMINATION_UNRESOLVED", "SAFETY_REFUSAL",
                                            "INTERRUPTED_OPERATOR_REVIEW", "PROVIDER_AUTH_BLOCKED"}
SUCCESS_CONSISTENT = "SUCCESS_CONSISTENT"

# Composite recovery.
COMPOSITE_CRITERIA_MET = "CRITERIA_MET"
COMPOSITE_BLOCKED = "BLOCKED"
COMPOSITE_OUTCOMES = (COMPOSITE_CRITERIA_MET, COMPOSITE_BLOCKED)
SUITE_GLOBAL = "GLOBAL"
SUITE_HISTORICAL = "HISTORICAL"
SUITES = (SUITE_GLOBAL, SUITE_HISTORICAL)
COMPONENTS_MALFORMED = "COMPONENTS_MALFORMED"
COMPONENT_ID_INVALID = "COMPONENT_ID_INVALID"
COMPONENT_DUPLICATE = "COMPONENT_DUPLICATE"
COMPONENT_UNBOUND = "COMPONENT_UNBOUND"
COMMIT_SHA_INVALID = "COMMIT_SHA_INVALID"
COMMIT_DUPLICATE = "COMMIT_DUPLICATE"
PATH_INVALID = "PATH_INVALID"
PRODUCT_HASH_INVALID = "PRODUCT_HASH_INVALID"
PATH_DUPLICATE = "PATH_DUPLICATE"
PATH_COLLISION = "PATH_COLLISION"
DIFF_NOT_UNION_ONLY = "DIFF_NOT_UNION_ONLY"
PRODUCT_HASH_MISMATCH = "PRODUCT_HASH_MISMATCH"
TREE_HASH_MISMATCH = "TREE_HASH_MISMATCH"
TESTS_MALFORMED = "TESTS_MALFORMED"
TESTS_GLOBAL_MISSING = "TESTS_GLOBAL_MISSING"
TESTS_HISTORICAL_MISSING = "TESTS_HISTORICAL_MISSING"
TESTS_NOT_ON_COMPOSITE = "TESTS_NOT_ON_COMPOSITE"
TESTS_INCOMPLETE = "TESTS_INCOMPLETE"
TESTS_NOT_GREEN = "TESTS_NOT_GREEN"
TESTS_SKIPPED_OR_EXPECTED = "TESTS_SKIPPED_OR_EXPECTED"
HOST_ATTESTATION_MISSING = "HOST_ATTESTATION_MISSING"
HOST_ATTESTATION_INVALID = "HOST_ATTESTATION_INVALID"
HOST_ATTESTATION_MISMATCH = "HOST_ATTESTATION_MISMATCH"
COMPONENT_EVIDENCE_UNSAFE = "COMPONENT_EVIDENCE_UNSAFE"
COMPONENT_VERDICT_NOT_PASS = "COMPONENT_VERDICT_NOT_PASS"
COMPONENT_AUDITOR_NOT_PASS = "COMPONENT_AUDITOR_NOT_PASS"
QUOTA_NOT_RECOVERED = "QUOTA_NOT_RECOVERED"
DIRECTION_AUTHORIZATION_MISSING = "DIRECTION_AUTHORIZATION_MISSING"
DIRECTION_AUTHORIZATION_UNVERIFIED = "DIRECTION_AUTHORIZATION_UNVERIFIED"
COMPOSITE_REASONS = (
    COMPONENTS_MALFORMED, COMPONENT_ID_INVALID, COMPONENT_DUPLICATE, COMPONENT_UNBOUND, COMMIT_SHA_INVALID,
    COMMIT_DUPLICATE, PATH_INVALID, PRODUCT_HASH_INVALID, PATH_DUPLICATE, PATH_COLLISION, DIFF_NOT_UNION_ONLY,
    PRODUCT_HASH_MISMATCH, TREE_HASH_MISMATCH, TESTS_MALFORMED, TESTS_GLOBAL_MISSING, TESTS_HISTORICAL_MISSING,
    TESTS_NOT_ON_COMPOSITE, TESTS_INCOMPLETE, TESTS_NOT_GREEN, TESTS_SKIPPED_OR_EXPECTED, HOST_ATTESTATION_MISSING,
    HOST_ATTESTATION_INVALID, HOST_ATTESTATION_MISMATCH, COMPONENT_EVIDENCE_UNSAFE, COMPONENT_VERDICT_NOT_PASS,
    COMPONENT_AUDITOR_NOT_PASS,
    QUOTA_NOT_RECOVERED, DIRECTION_AUTHORIZATION_MISSING, DIRECTION_AUTHORIZATION_UNVERIFIED,
)

# Advice-level codes.
COMPOSITE_CRITERIA_NOT_MET = "COMPOSITE_CRITERIA_NOT_MET"
NO_EVIDENCE = qc.NO_EVIDENCE
ADVICE_REASONS = (COMPOSITE_CRITERIA_NOT_MET, NO_EVIDENCE)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = qc.REQUEST_NOT_TYPED
SCHEMA_VERSION_UNSUPPORTED = qc.SCHEMA_VERSION_UNSUPPORTED
REQUEST_ID_INVALID = qc.REQUEST_ID_INVALID
ID_SECRET_SHAPED = qc.ID_SECRET_SHAPED
QUOTA_REQUEST_REFUSED = "QUOTA_REQUEST_REFUSED"
DEADLINE_INVALID = "DEADLINE_INVALID"
WORKERS_MALFORMED = "WORKERS_MALFORMED"
WORKER_ID_INVALID = "WORKER_ID_INVALID"
WORKER_ID_DUPLICATE = "WORKER_ID_DUPLICATE"
WORKER_PROVIDER_INVALID = "WORKER_PROVIDER_INVALID"
PROVIDERS_TOO_MANY = "PROVIDERS_TOO_MANY"
COMPOSITE_NOT_TYPED = "COMPOSITE_NOT_TYPED"
REQUEST_TOO_LARGE = qc.REQUEST_TOO_LARGE
REQUEST_REASONS = (REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED,
                   QUOTA_REQUEST_REFUSED, DEADLINE_INVALID, WORKERS_MALFORMED, WORKER_ID_INVALID,
                   WORKER_ID_DUPLICATE, WORKER_PROVIDER_INVALID, PROVIDERS_TOO_MANY, COMPOSITE_NOT_TYPED,
                   REQUEST_TOO_LARGE)

_A02_DOUBT = frozenset(qo.DOUBT_REASONS) | {qo.AVAILABILITY_UNKNOWN}


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(qc._in(c, vocabulary) for c in codes)
            and codes == _ordered(codes, vocabulary))


def _sorted_ids(values) -> bool:
    return (type(values) is tuple and all(qc._valid_id(v) for v in values)
            and list(values) == sorted(set(values)))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _fingerprint_ok(value) -> bool:
    return type(value) is str and sc._FINGERPRINT_RE.fullmatch(value) is not None


def _commit_ok(value) -> bool:
    return (type(value) is str and len(value) == 40 and value.isascii()
            and all(c in "0123456789abcdef" for c in value))


def _path_ok(value) -> bool:
    """A repository-relative POSIX path: no root, drive, backslash, empty,
    `.` or `..` segment, ASCII printable only."""
    if type(value) is not str or not 0 < len(value) <= MAX_PATH_CHARS or not value.isascii():
        return False
    if any(not c.isprintable() for c in value) or "\\" in value or ":" in value or value.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _worst(verdicts) -> str:
    return min(verdicts, key=WORK_VERDICTS.index)


def _status_rank(status: str) -> int:
    return STATUSES.index(status)


# ---------------------------------------------------------------------------
# Conservative classifier of explicit verdicts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerdictReading:
    """Classification of one explicit-verdict text. Never carries the text."""
    verdict: str
    reasons: tuple
    candidates: int

    def __post_init__(self):
        if not qc._in(self.verdict, VERDICT_CLASSES):
            raise ValueError("unknown verdict class")
        if not _codes_ok(self.reasons, READING_REASONS):
            raise ValueError("reasons must be ordered reading codes")
        if not qc._bounded_int(self.candidates, 0, MAX_VERDICT_TEXT_CHARS):
            raise ValueError("candidates out of bounds")
        if self.verdict in (VERDICT_PASS, VERDICT_ABSENT) and self.reasons:
            raise ValueError("PASS / ABSENT carry no doubt")
        if self.verdict == VERDICT_PASS and self.candidates < 1:
            raise ValueError("PASS needs an explicit verdict line")
        if self.verdict == VERDICT_AMBIGUOUS and VERDICT_CONFLICTING not in self.reasons:
            raise ValueError("AMBIGUOUS is exactly conflicting lines")

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": list(self.reasons), "candidates": self.candidates}


def _explicit_token(value: str) -> str:
    return value.strip().strip("*_`").strip().upper()


def classify_explicit_verdict(text) -> VerdictReading:
    """Conservative reading of the line-anchored `VERDICT=` lines of `text`
    via the Runner's own `extract_verdict`. Only an exact PASS / PASSED /
    SUCCESS token reads PASS; whatever the Runner reads as negative stays
    negative; any other token is UNVERIFIED; lines that disagree are
    AMBIGUOUS. None is ABSENT. Never raises and never echoes the text."""
    if text is None:
        return VerdictReading(VERDICT_ABSENT, (), 0)
    if type(text) is not str or len(text) > MAX_VERDICT_TEXT_CHARS:
        return VerdictReading(VERDICT_UNVERIFIED, (VERDICT_TEXT_MALFORMED,), 0)
    _status, _raw, candidates, _note = providers.extract_verdict(text)
    if not candidates:
        return VerdictReading(VERDICT_UNVERIFIED, (VERDICT_NOT_FOUND,), 0)
    classes, reasons = set(), set()
    for candidate in candidates:
        token = _explicit_token(candidate["value"])
        status = candidate["status"]
        if status is not None and _CLASS_OF_STATUS[providers.WorkStatus(status)] != VERDICT_PASS:
            classes.add(_CLASS_OF_STATUS[providers.WorkStatus(status)])
        elif token in EXPLICIT_PASS_TOKENS:
            classes.add(VERDICT_PASS)
        elif token in EXPLICIT_UNVERIFIED_TOKENS:
            classes.add(VERDICT_UNVERIFIED)
        else:
            classes.add(VERDICT_UNVERIFIED)
            reasons.add(VERDICT_NOT_EXPLICIT if status is not None else VERDICT_UNRECOGNIZED)
    count = min(len(candidates), MAX_VERDICT_TEXT_CHARS)
    if len(classes) > 1:
        return VerdictReading(VERDICT_AMBIGUOUS, _ordered(reasons | {VERDICT_CONFLICTING}, READING_REASONS), count)
    verdict = classes.pop()
    return VerdictReading(verdict, () if verdict == VERDICT_PASS else _ordered(reasons, READING_REASONS), count)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkerEvidence:
    """One worker as the caller already read it: its Runner
    `workers/<id>/result.json` (`result`, None when absent) and its
    `pipeline_result.json["workers"]` entry (`summary`), the FCP-6
    `WorkerDiagnostic` the caller's own `assess_worker` produced for exactly
    these (`diagnostic`), the provider it is declared on, and optional
    explicit provider / auditor verdict texts."""
    worker_id: str
    provider_id: str
    result: object = None
    summary: object = None
    pipeline_id: Optional[str] = None
    diagnostic: object = None
    provider_verdict_text: Optional[str] = None
    auditor_verdict_text: Optional[str] = None


@dataclass(frozen=True)
class ComponentProduct:
    """One component of a composite recovery: the worker that produced it,
    its own commit and its product as unique `(path, sha256)` pairs."""
    component_id: str
    commit_sha: str
    products: tuple


@dataclass(frozen=True)
class SuiteRunEvidence:
    """One finished unittest run as the host observed it (counts only)."""
    suite: str
    suite_id: str
    commit_sha: str
    ran: int
    failures: int
    errors: int
    skipped: int
    expected_failures: int
    unexpected_successes: int
    complete: bool


@dataclass(frozen=True)
class HostAttestation:
    """The host's act binding one composite commit to one evidence
    fingerprint (`composite_evidence_fingerprint`)."""
    attestation_id: str
    composite_commit_sha: str
    evidence_fingerprint: str
    attested_at_utc: str


@dataclass(frozen=True)
class DirectionAuthorization:
    """The Direction act a cited `direction_authorization_id` names, bound
    to one composite commit, one evidence fingerprint and the Host
    attestation it follows. Verified only as that binding; it grants this
    contract nothing."""
    authorization_id: str
    composite_commit_sha: str
    evidence_fingerprint: str
    attestation_id: str
    authorized_at_utc: str


@dataclass(frozen=True)
class CompositeRecoveryEvidence:
    """Facts of a PROPOSED composite recovery. `composite_products` is the
    composite commit's diff as `(path, sha256)`; `observed_tree` the host's
    observation of those paths at the composite commit. Assessed only."""
    components: tuple
    composite_commit_sha: str
    composite_products: tuple
    observed_tree: tuple
    test_runs: tuple
    attestation: Optional[object] = None
    direction_authorization_id: Optional[str] = None
    direction_authorization: Optional[object] = None


@dataclass(frozen=True)
class RecoveryRequest:
    """Explicit, immutable recovery question. Validated by `advise_recovery`
    (fail closed), not here. The instant is `quota_request.as_of_utc`."""
    request_id: str
    quota_request: object
    workers: tuple = ()
    deadline_utc: Optional[str] = None
    composite: Optional[object] = None
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderRecovery:
    """Quota recovery view of one provider. Construction re-derives the
    status, actor and action from `recovery`."""
    provider_id: str
    recovery: str
    status: str
    actor: str
    action: str
    reasons: tuple
    evidence_ids: tuple
    availability: Optional[str] = None
    next_eligible_utc: Optional[str] = None
    eligibility_source: Optional[str] = None

    def __post_init__(self):
        if not sc._valid_provider_id(self.provider_id):
            raise ValueError("provider_id must be a valid provider id")
        if not qc._in(self.recovery, PROVIDER_RECOVERIES):
            raise ValueError("unknown recovery")
        if (self.status, self.actor, self.action) != PROVIDER_RULES[self.recovery]:
            raise ValueError("status / actor / action must be the recovery's own")
        if not _codes_ok(self.reasons, PROVIDER_REASONS):
            raise ValueError("reasons must be ordered provider reason codes")
        if (self.recovery == AVAILABLE_OBSERVED) != (not self.reasons):
            raise ValueError("only AVAILABLE_OBSERVED is free of reasons")
        if not _sorted_ids(self.evidence_ids):
            raise ValueError("evidence_ids must be sorted unique ids")
        if self.recovery == AVAILABLE_OBSERVED and (self.availability != "NONE" or not self.evidence_ids):
            raise ValueError("AVAILABLE_OBSERVED needs cited NONE evidence; recovery is never inferred")
        if self.availability is not None and not qc._in(self.availability, qc.AVAILABILITY_STATES):
            raise ValueError("availability must use the Router vocabulary")
        if self.recovery in (COOLDOWN_PENDING, RECOVERY_UNCONFIRMED) and (
                self.availability != "QUOTA_WAIT" or self.next_eligible_utc is None):
            raise ValueError("a cooldown is only a Runner quota wait with its eligibility instant")
        if self.next_eligible_utc is None:
            if self.eligibility_source is not None:
                raise ValueError("eligibility_source only with next_eligible_utc")
        elif (self.availability != "QUOTA_WAIT" or not qo._normalized_utc(self.next_eligible_utc)
              or not qc._in(self.eligibility_source, qc.ELIGIBILITY_SOURCES)):
            raise ValueError("only a Runner quota wait echoes a normalized eligibility instant")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "recovery": self.recovery, "status": self.status, "actor": self.actor,
            "action": self.action, "reasons": list(self.reasons), "evidence_ids": list(self.evidence_ids),
            "availability": self.availability, "next_eligible_utc": self.next_eligible_utc,
            "eligibility_source": self.eligibility_source,
        }


def work_verdict_for(runner_verdict: str, provider_verdict: str, auditor_verdict: str) -> str:
    """Most severe of the three axes; PASS only when all three are PASS."""
    return _worst((runner_verdict, provider_verdict, _WORK_VERDICT_OF[auditor_verdict]))


def worker_rule(reasons: tuple) -> tuple:
    """(status, actor, action) of the first matching reason; CLEAR without."""
    for code in reasons:
        return _WORKER_RULE[code]
    return CLEAR, ACTOR_NONE, NO_ACTION


@dataclass(frozen=True)
class WorkerRecovery:
    """Per-worker advice. The Runner axis (FCP-6), the provider axis (its
    raw work status plus its explicit textual verdict) and the auditor axis
    stay separate; construction re-derives `work_verdict` and the rule."""
    worker_id: str
    provider_id: str
    native_state: Optional[str]
    diagnostic_reasons: tuple
    continuation: str
    runner_verdict: str
    provider_work_status: Optional[str]
    work_status_source: Optional[str]
    provider_reading: VerdictReading
    provider_verdict: str
    auditor_reading: VerdictReading
    work_verdict: str
    reasons: tuple
    status: str
    actor: str
    action: str

    def __post_init__(self):
        if not sc._safe_id(self.worker_id) or not sc._valid_provider_id(self.provider_id):
            raise ValueError("worker_id / provider_id must be valid")
        if self.native_state is not None and not qc._in(self.native_state, FI_WORKER_STATES | {FI_UNRECOGNIZED}):
            raise ValueError("native_state must be a Runner state")
        if not _codes_ok(self.diagnostic_reasons, FI_REASON_PRECEDENCE):
            raise ValueError("diagnostic_reasons must be FCP-6's own ordered codes")
        if not qc._in(self.continuation, CONTINUATIONS):
            raise ValueError("unknown continuation")
        if not all(qc._in(v, WORK_VERDICTS) for v in (self.runner_verdict, self.provider_verdict, self.work_verdict)):
            raise ValueError("axis verdicts must be work verdicts")
        if self.runner_verdict == VERDICT_PASS and self.diagnostic_reasons != (SUCCESS_CONSISTENT,):
            raise ValueError("Runner PASS is exactly FCP-6 SUCCESS_CONSISTENT")
        if self.provider_work_status is not None and not qc._in(
                self.provider_work_status, tuple(_CLASS_OF_PROVIDER_WORK_STATUS) + (FI_UNRECOGNIZED,)):
            raise ValueError("provider_work_status must be a Runner work status")
        if self.work_status_source is not None and not qc._in(
                self.work_status_source, FI_WORK_STATUS_SOURCES | {FI_UNRECOGNIZED}):
            raise ValueError("work_status_source must be a Runner source")
        if type(self.provider_reading) is not VerdictReading or type(self.auditor_reading) is not VerdictReading:
            raise ValueError("readings must be VerdictReadings")
        if self.provider_verdict == VERDICT_PASS and self.provider_reading.verdict in _NEGATIVE_CLASSES:
            raise ValueError("a negative provider verdict is never PASS")
        if self.work_verdict != work_verdict_for(self.runner_verdict, self.provider_verdict,
                                                 self.auditor_reading.verdict):
            raise ValueError("work_verdict must be the most severe axis")
        if not _codes_ok(self.reasons, WORKER_REASONS):
            raise ValueError("reasons must be ordered worker reason codes")
        if self.work_verdict != VERDICT_PASS and not self.reasons:
            raise ValueError("a work verdict below PASS is always explained")
        if not self.diagnostic_reasons and RUNNER_EVIDENCE_INTEGRITY not in self.reasons:
            raise ValueError("a worker without trusted FCP-6 codes is an integrity doubt")
        if (self.status, self.actor, self.action) != worker_rule(self.reasons):
            raise ValueError("status / actor / action must be the first reason's rule")

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id, "provider_id": self.provider_id, "native_state": self.native_state,
            "diagnostic_reasons": list(self.diagnostic_reasons), "continuation": self.continuation,
            "runner_verdict": self.runner_verdict, "provider_work_status": self.provider_work_status,
            "work_status_source": self.work_status_source, "provider_reading": self.provider_reading.to_dict(),
            "provider_verdict": self.provider_verdict, "auditor_reading": self.auditor_reading.to_dict(),
            "work_verdict": self.work_verdict, "reasons": list(self.reasons), "status": self.status,
            "actor": self.actor, "action": self.action,
        }


@dataclass(frozen=True)
class CompositeAssessment:
    """Assessment of a proposed composite recovery against the formal
    criterion. CRITERIA_MET exactly when no reason holds, which needs a
    cited AND verified Direction authorization; it never consolidates
    anything and still authorizes nothing."""
    outcome: str
    reasons: tuple
    evidence_fingerprint: Optional[str]
    component_ids: tuple
    collisions: tuple
    direction_authorization_id: Optional[str]
    direction_authorization_verified: bool = False

    def __post_init__(self):
        if not _codes_ok(self.reasons, COMPOSITE_REASONS):
            raise ValueError("reasons must be ordered composite reason codes")
        if self.outcome != (COMPOSITE_BLOCKED if self.reasons else COMPOSITE_CRITERIA_MET):
            raise ValueError("CRITERIA_MET exactly when no reason holds")
        if self.evidence_fingerprint is not None and not _fingerprint_ok(self.evidence_fingerprint):
            raise ValueError("evidence_fingerprint must be a sha256 hex digest")
        if self.outcome == COMPOSITE_CRITERIA_MET and (
                self.evidence_fingerprint is None or not self.component_ids
                or not qc._valid_id(self.direction_authorization_id)):
            raise ValueError("CRITERIA_MET needs fingerprinted components and a cited Direction authorization")
        if not (type(self.component_ids) is tuple and all(sc._safe_id(c) for c in self.component_ids)
                and list(self.component_ids) == sorted(set(self.component_ids))):
            raise ValueError("component_ids must be sorted unique ids")
        if not (type(self.collisions) is tuple and all(_path_ok(p) for p in self.collisions)
                and list(self.collisions) == sorted(set(self.collisions))):
            raise ValueError("collisions must be sorted unique paths")
        if bool(self.collisions) != (PATH_COLLISION in self.reasons):
            raise ValueError("PATH_COLLISION exactly when collisions are listed")
        if self.direction_authorization_id is not None and not qc._valid_id(self.direction_authorization_id):
            raise ValueError("direction_authorization_id must be a valid id")
        cited = self.direction_authorization_id is not None
        verified = self.direction_authorization_verified
        if type(verified) is not bool or (verified and not cited):
            raise ValueError("only a cited Direction authorization can be verified")
        if ((DIRECTION_AUTHORIZATION_UNVERIFIED in self.reasons) != (cited and not verified)
                or (DIRECTION_AUTHORIZATION_MISSING in self.reasons) == cited):
            raise ValueError("a cited unverified Direction authorization is UNVERIFIED, an uncited one MISSING")

    @property
    def requires_direction_authorization(self) -> bool:
        return True

    @property
    def consolidation_performed(self) -> bool:
        return False

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome, "reasons": list(self.reasons), "evidence_fingerprint": self.evidence_fingerprint,
            "component_ids": list(self.component_ids), "collisions": list(self.collisions),
            "direction_authorization_id": self.direction_authorization_id,
            "direction_authorization_verified": self.direction_authorization_verified,
            "requires_direction_authorization": True, "consolidation_performed": False,
        }


class _RecoveryGuarantees(qc._QuotaGuarantees):
    """FCP-10A-01 zero-authority flags plus: no state mutation, retry,
    derived resume, commit, history rewrite, consolidation or upgrade."""

    @property
    def state_mutated(self) -> bool:
        return False

    @property
    def retry_scheduled(self) -> bool:
        return False

    @property
    def resume_from_derived(self) -> bool:
        return False

    @property
    def commit_created(self) -> bool:
        return False

    @property
    def history_rewritten(self) -> bool:
        return False

    @property
    def checkpoint_consolidated(self) -> bool:
        return False

    @property
    def verdict_upgraded(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = qc._QuotaGuarantees._guarantees()
        guarantees.update(marker=RECOVERY_MARKER, state_mutated=False, retry_scheduled=False,
                          resume_from_derived=False, commit_created=False, history_rewritten=False,
                          checkpoint_consolidated=False, verdict_upgraded=False)
        return guarantees


def outcome_for(request_reasons: tuple, advice_reasons: tuple, providers_: tuple, workers: tuple) -> str:
    """REFUSED > BLOCKED > UNKNOWN > WAITING > CLEAR."""
    if request_reasons:
        return REFUSED
    statuses = {p.status for p in providers_} | {w.status for w in workers}
    if COMPOSITE_CRITERIA_NOT_MET in advice_reasons:
        statuses.add(BLOCKED)
    if NO_EVIDENCE in advice_reasons:
        statuses.add(UNKNOWN)
    return min(statuses, key=_status_rank) if statuses else UNKNOWN


@dataclass(frozen=True)
class RecoveryAdvice(_RecoveryGuarantees):
    """Read-only recovery advice. Echo fields hold only validated values
    (None and () when refused). Construction re-derives the outcome."""
    outcome: str
    request_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    as_of_utc: Optional[str]
    deadline_utc: Optional[str]
    quota_snapshot_fingerprint: Optional[str]
    reasons: tuple
    evidence_ids: tuple
    providers: tuple
    workers: tuple
    composite: Optional[CompositeAssessment] = None

    def __post_init__(self):
        if not qc._in(self.outcome, OUTCOMES):
            raise ValueError("unknown outcome")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            echo = (self.request_id, self.request_fingerprint, self.as_of_utc, self.deadline_utc,
                    self.quota_snapshot_fingerprint, self.composite)
            if (self.outcome != REFUSED or self.reasons or self.evidence_ids or self.providers or self.workers
                    or echo != (None,) * len(echo)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not qc._valid_id(self.request_id) or not qo._normalized_utc(self.as_of_utc):
            raise ValueError("request_id / as_of_utc must be validated")
        if self.deadline_utc is not None and not qo._normalized_utc(self.deadline_utc):
            raise ValueError("deadline_utc must be normalized UTC")
        if not (_fingerprint_ok(self.request_fingerprint) and _fingerprint_ok(self.quota_snapshot_fingerprint)):
            raise ValueError("fingerprints must be sha256 hex digests")
        if not _codes_ok(self.reasons, ADVICE_REASONS):
            raise ValueError("reasons must be ordered advice codes")
        if not _sorted_ids(self.evidence_ids):
            raise ValueError("evidence_ids must be sorted unique ids")
        if (NO_EVIDENCE in self.reasons) != (not self.evidence_ids):
            raise ValueError("NO_EVIDENCE exactly when nothing is cited")
        if not (type(self.providers) is tuple and len(self.providers) <= qc.MAX_PROVIDERS
                and all(type(p) is ProviderRecovery for p in self.providers)):
            raise ValueError("providers must be ProviderRecoveries")
        ids = [p.provider_id for p in self.providers]
        if ids != sorted(set(ids)):
            raise ValueError("providers must be sorted and unique")
        if not (type(self.workers) is tuple and len(self.workers) <= MAX_WORKERS
                and all(type(w) is WorkerRecovery for w in self.workers)):
            raise ValueError("workers must be WorkerRecoveries")
        worker_ids = [w.worker_id for w in self.workers]
        if len(worker_ids) != len(set(worker_ids)) or any(w.provider_id not in ids for w in self.workers):
            raise ValueError("workers must be unique and each needs its provider view")
        if not {e for p in self.providers for e in p.evidence_ids} <= set(self.evidence_ids):
            raise ValueError("every provider citation must be cited by the advice")
        if self.composite is not None and type(self.composite) is not CompositeAssessment:
            raise ValueError("composite must be a CompositeAssessment")
        not_met = self.composite is not None and self.composite.outcome != COMPOSITE_CRITERIA_MET
        if not_met != (COMPOSITE_CRITERIA_NOT_MET in self.reasons):
            raise ValueError("COMPOSITE_CRITERIA_NOT_MET exactly when the composite is BLOCKED")
        if self.outcome != outcome_for((), self.reasons, self.providers, self.workers):
            raise ValueError("outcome must be exactly the one derived from the evidence")
        if self.outcome == CLEAR and not self.evidence_ids:
            raise ValueError("CLEAR must cite evidence; recovery is never inferred")

    def provider(self, provider_id: str) -> Optional[ProviderRecovery]:
        for view in self.providers:
            if view.provider_id == provider_id:
                return view
        return None

    def worker(self, worker_id: str) -> Optional[WorkerRecovery]:
        for view in self.workers:
            if view.worker_id == worker_id:
                return view
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome,
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "request_reasons": list(self.request_reasons), "as_of_utc": self.as_of_utc,
            "deadline_utc": self.deadline_utc, "quota_snapshot_fingerprint": self.quota_snapshot_fingerprint,
            "reasons": list(self.reasons), "evidence_ids": list(self.evidence_ids),
            "providers": [p.to_dict() for p in self.providers], "workers": [w.to_dict() for w in self.workers],
            "composite": None if self.composite is None else self.composite.to_dict(),
            **_RecoveryGuarantees._guarantees(),
        }


def canonical_json(advice: RecoveryAdvice) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    advice type (a subclass cannot substitute `to_dict`)."""
    if type(advice) is not RecoveryAdvice:
        raise TypeError("canonical_json accepts only a RecoveryAdvice")
    text = sc._canonical(RecoveryAdvice.to_dict(advice))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical advice exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _refused(reasons) -> RecoveryAdvice:
    return RecoveryAdvice(
        outcome=REFUSED, request_id=None, request_fingerprint=None,
        request_reasons=_ordered(reasons, REQUEST_REASONS), as_of_utc=None, deadline_utc=None,
        quota_snapshot_fingerprint=None, reasons=(), evidence_ids=(), providers=(), workers=(), composite=None,
    )


# ---------------------------------------------------------------------------
# Workers (FCP-6 as is, plus the Runner's own continuation and work status)
# ---------------------------------------------------------------------------

def _last_attempt(result) -> Optional[Mapping]:
    if not isinstance(result, Mapping):
        return None
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], Mapping):
        return None
    return attempts[-1]


def _continuation(last: Optional[Mapping]) -> str:
    """The Runner's own reconciliation decision; the path is never read."""
    if last is None or "reconciliation" not in last:
        return CONTINUATION_NONE
    reconciliation = last.get("reconciliation")
    decision = reconciliation.get("decision") if isinstance(reconciliation, Mapping) else None
    return decision if qc._in(decision, _NATIVE_CONTINUATIONS) else CONTINUATION_UNRECOGNIZED


def _provider_work_status(last: Optional[Mapping]) -> Optional[str]:
    raw = None if last is None else last.get("provider_work_status")
    if raw is None:
        return None
    return raw if qc._in(raw, _CLASS_OF_PROVIDER_WORK_STATUS) else FI_UNRECOGNIZED


def _runner_verdict(codes: tuple) -> str:
    if codes == (SUCCESS_CONSISTENT,):
        return VERDICT_PASS
    if any(c in _FI_BLOCKED for c in codes):
        return VERDICT_BLOCKED
    if any(c in _FI_FAILED for c in codes):
        return VERDICT_FAIL
    return VERDICT_UNVERIFIED


def _declared_provider_mismatch(evidence: WorkerEvidence) -> bool:
    for source in (evidence.result, evidence.summary):
        if isinstance(source, Mapping) and "provider" in source and source.get("provider") != evidence.provider_id:
            return True
    return False


def _diagnostic_ok(diagnostic, evidence: WorkerEvidence) -> bool:
    """The caller's FCP-6 `WorkerDiagnostic` for exactly this worker: its
    own frozen type and serialization, mirrored vocabulary, zero authority,
    and the result's own identity and state. Never raises."""
    kind = type(diagnostic)
    params = getattr(kind, "__dataclass_params__", None)
    if not (kind.__name__ == FI_DIAGNOSTIC_TYPE and kind.__module__.rsplit(".", 1)[-1] == FI_MODULE_NAME
            and getattr(params, "frozen", False) is True):
        return False
    try:
        payload = diagnostic.to_dict()
    except Exception:  # noqa: BLE001 - a broken diagnostic is never trusted
        return False
    if not isinstance(payload, dict) or (payload.get("schema"), payload.get("marker")) != (
            FI_SCHEMA_WORKER, FI_DIAGNOSTIC_MARKER):
        return False
    if any(payload.get(flag) is not False or getattr(diagnostic, flag, None) is not False
           for flag in FI_ZERO_AUTHORITY_FLAGS):
        return False
    codes, state, source = diagnostic.reason_codes, diagnostic.native_state, diagnostic.native_work_status_source
    if not (type(codes) is tuple and codes and _codes_ok(codes, FI_REASON_PRECEDENCE)
            and diagnostic.primary_reason == codes[0] and payload.get("reason_codes") == list(codes)):
        return False
    if diagnostic.worker_id != evidence.worker_id:
        return False
    if not (state is None or qc._in(state, FI_WORKER_STATES | {FI_UNRECOGNIZED})):
        return False
    if not (source is None or qc._in(source, FI_WORK_STATUS_SOURCES | {FI_UNRECOGNIZED})):
        return False
    # Bound to the records it diagnoses: every native field FCP-6 reads from
    # them is re-read here and must be the diagnostic's own, so a diagnostic
    # of another run, attempt or pipeline (or of no record at all) never
    # vouches for these records just because the worker id and state agree.
    return _diagnostic_bound(diagnostic, evidence) and (
        codes != (SUCCESS_CONSISTENT,) or _success_bound(diagnostic, evidence))


def _fi_token(value) -> Optional[str]:
    """FCP-6 `_token` (pinned by tests): None, the upper-case head of a
    native string, or UNRECOGNIZED."""
    if value is None:
        return None
    if not isinstance(value, str):
        return FI_UNRECOGNIZED
    head = value.split(":", 1)[0]
    ok = 0 < len(head) <= 64 and head[0] in _FI_TOKEN_HEAD and all(c in _FI_TOKEN_TAIL for c in head)
    return head if ok else FI_UNRECOGNIZED


def _fi_state(value) -> Optional[str]:
    """FCP-6 `_state_value` without its codes."""
    if value is None or qc._in(value, FI_WORKER_STATES):
        return value
    return _fi_token(value) if isinstance(value, str) else FI_UNRECOGNIZED


def _diagnostic_bound(diagnostic, evidence: WorkerEvidence) -> bool:
    """The diagnostic's native fields are exactly those of `evidence.result`
    / `evidence.summary` (identity, state, outcome, code, attempts, last
    attempt's runner state and source); absent or non-Mapping records are
    unbindable. Fails closed on any doubt."""
    result, summary = evidence.result, evidence.summary
    if not all(r is None or isinstance(r, Mapping) for r in (result, summary)):
        return False
    if result is None and summary is None:
        return False
    refs = diagnostic.evidence_refs
    if type(refs) is not tuple or ("worker_result" in refs) != (result is not None) or any(
            isinstance(r, str) and r.startswith("pipeline_result.workers") for r in refs) != (summary is not None):
        return False
    if summary is not None and summary.get("id") != evidence.worker_id:
        return False
    summary_state = _fi_state(summary.get("state")) if summary is not None else None
    outcome = code = runner_state = source = attempts_recorded = None
    result_state = None
    if result is not None:
        if result.get("worker_id") != evidence.worker_id:
            return False
        if evidence.pipeline_id is not None and result.get("pipeline_id") != evidence.pipeline_id:
            return False
        result_state = _fi_state(result.get("state"))
        outcome, code = _fi_token(result.get("outcome")), _fi_token(result.get("code"))
        attempts = result.get("attempts")
        if attempts is not None:
            if not isinstance(attempts, list) or not all(isinstance(a, Mapping) for a in attempts):
                return False
            attempts_recorded = len(attempts)
            if attempts:
                runner_state = _fi_token(attempts[-1].get("runner_state"))
                raw = attempts[-1].get("work_status_source")
                source = raw if qc._in(raw, FI_WORK_STATUS_SOURCES) else (None if raw is None else FI_UNRECOGNIZED)
    state = summary_state if summary_state is not None else result_state
    reason = _fi_token((summary if summary is not None else result).get("state_reason"))
    observed = (diagnostic.native_state, diagnostic.native_state_reason, diagnostic.native_outcome,
                diagnostic.native_code, diagnostic.native_runner_state, diagnostic.native_work_status_source,
                diagnostic.attempts_recorded)
    expected = (state, reason, outcome, code, runner_state, source, attempts_recorded)
    return all(type(a) is type(b) and a == b for a, b in zip(observed, expected))


def _success_bound(diagnostic, evidence: WorkerEvidence) -> bool:
    """A Runner PASS needs this very result, of this very pipeline, to prove
    its own success natively (FCP-6's success proof, re-read here): a
    present, typed result with a complete, stopped, COMPLETED last attempt
    whose work status is SUCCESS, and a summary (when given) that agrees."""
    result, summary, last = evidence.result, evidence.summary, _last_attempt(evidence.result)
    if last is None or not sc._safe_id(evidence.pipeline_id) or result.get("pipeline_id") != evidence.pipeline_id:
        return False
    if summary is not None and (summary.get("state") != "SUCCESS" or summary.get("result_path") is None):
        return False
    decision = last.get("retry_decision")
    return (
        _success_signals_clean(result, last, summary)
        and result.get("state") == "SUCCESS" and result.get("outcome") == "SUCCESS"
        and (diagnostic.native_state, diagnostic.native_outcome) == ("SUCCESS", "SUCCESS")
        and (diagnostic.retry_decision_kind, diagnostic.retry_decision_code) == ("NONE", "SUCCESS")
        and isinstance(decision, str) and decision.split(":")[:2] == ["NONE", "SUCCESS"]
        and diagnostic.attempts_recorded == len(result["attempts"]) >= 1
        and last.get("status") == "COMPLETED" and last.get("evidence_complete") is True
        and last.get("process_confirmed_stopped") is True and last.get("work_status") == "SUCCESS"
        and qc._in(last.get("work_status_source"), FI_WORK_STATUS_SOURCES)
        and result.get("work_status") == last.get("work_status")
        and result.get("work_status_source") == last.get("work_status_source")
    )


def _success_signals_clean(result: Mapping, last: Mapping, summary) -> bool:
    """None of the native signals FCP-6 turns into a non-success code is
    present: the Runner's own success writes no `code`, at most the
    reconciliation `state_reason`, and no unresolved process, unauthorized
    path, safety refusal or unresolved acceptance (conservative: a signal
    merely present in a doubtful shape is not clean)."""
    if result.get("code") is not None or last.get("runner_state") not in (None, "SUCCESS"):
        return False
    for record in (result, summary):
        if record is not None and record.get("state_reason") not in (None, "RECONCILED_FROM_PRIOR_ATTEMPT"):
            return False
    if any(last.get(flag) not in (None, False)
           for flag in ("process_termination_unresolved", "acceptance_termination_unresolved")):
        return False
    recovery = last.get("process_recovery")
    if recovery is not None and not (isinstance(recovery, Mapping) and recovery.get("resolution") != "UNRESOLVED"):
        return False
    for source in (result, last):
        if source.get("unauthorized_changed_paths") not in (None, []):
            return False
        verdict = source.get("safety_verdict")
        if isinstance(verdict, Mapping) and verdict.get("verdict") == "FAILED_SAFETY":
            return False
        acceptance = source.get("acceptance")
        if isinstance(acceptance, Mapping) and (acceptance.get("termination_unresolved") is True
                                                or acceptance.get("decision") == "PROCESS_UNRESOLVED"):
            return False
    return True


def _assess_worker(evidence: WorkerEvidence) -> WorkerRecovery:
    diagnostic = evidence.diagnostic
    trusted = _diagnostic_ok(diagnostic, evidence)
    codes = diagnostic.reason_codes if trusted else ()
    native_state = diagnostic.native_state if trusted else None
    source = diagnostic.native_work_status_source if trusted else None
    last = _last_attempt(evidence.result)
    continuation = _continuation(last)
    work_status = _provider_work_status(last)
    runner_verdict = _runner_verdict(codes)
    provider_reading = classify_explicit_verdict(evidence.provider_verdict_text)
    auditor_reading = classify_explicit_verdict(evidence.auditor_verdict_text)

    raw_class = VERDICT_ABSENT if work_status is None else _CLASS_OF_PROVIDER_WORK_STATUS.get(
        work_status, VERDICT_UNVERIFIED)
    # Without a text the provider axis is the Runner's own reading of the
    # provider's verdict; with one, the more severe of both.
    axis = (raw_class,) if provider_reading.verdict == VERDICT_ABSENT else (raw_class, provider_reading.verdict)
    provider_class = _worst(tuple(_WORK_VERDICT_OF[v] for v in axis))
    accepted = (runner_verdict == VERDICT_PASS and source == "RUNNER_ACCEPTANCE"
                and raw_class not in _NEGATIVE_CLASSES
                and provider_reading.verdict not in _NEGATIVE_CLASSES)
    # The Runner's own acceptance legitimately supersedes an absent or
    # unverified provider verdict (FABRIC H2-B); never a negative one.
    provider_verdict = VERDICT_PASS if accepted else provider_class

    reasons = set()
    if not trusted or any(c in _FI_INTEGRITY for c in codes):
        reasons.add(RUNNER_EVIDENCE_INTEGRITY)
    if _declared_provider_mismatch(evidence):
        reasons.add(WORKER_PROVIDER_MISMATCH)
    reasons |= {_FI_DIRECT[c] for c in codes if c in _FI_DIRECT}
    if continuation == CONTINUATION_UNRECOGNIZED:
        reasons.add(CONTINUATION_EVIDENCE_UNRECOGNIZED)
    elif continuation == CONTINUATION_NATIVE_PENDING and native_state in (
            "WAITING_PROVIDER_QUOTA", "RETRY_WAIT"):
        reasons.add(NATIVE_CONTINUATION_PENDING)
    if runner_verdict == VERDICT_FAIL:
        reasons.add(RUNNER_WORK_FAILED)
    elif runner_verdict == VERDICT_BLOCKED:
        reasons.add(RUNNER_WORK_BLOCKED)
    negative_provider = raw_class in _NEGATIVE_CLASSES or provider_reading.verdict in _NEGATIVE_CLASSES
    if negative_provider:
        reasons.add(PROVIDER_VERDICT_DIVERGENT if runner_verdict == VERDICT_PASS else PROVIDER_VERDICT_NOT_PASS)
    if auditor_reading.verdict in _NEGATIVE_CLASSES:
        reasons.add(AUDITOR_VERDICT_NOT_PASS)
    work_verdict = work_verdict_for(runner_verdict, provider_verdict, auditor_reading.verdict)
    if auditor_reading.verdict == VERDICT_ABSENT:
        reasons.add(AUDITOR_VERDICT_ABSENT)
    if auditor_reading.verdict == VERDICT_UNVERIFIED or (
            (runner_verdict, provider_verdict) != (VERDICT_PASS, VERDICT_PASS)
            and not reasons - {AUDITOR_VERDICT_ABSENT}):
        reasons.add(WORK_UNVERIFIED)
    ordered = _ordered(reasons, WORKER_REASONS)
    status, actor, action = worker_rule(ordered)
    return WorkerRecovery(
        worker_id=evidence.worker_id, provider_id=evidence.provider_id, native_state=native_state,
        diagnostic_reasons=codes, continuation=continuation, runner_verdict=runner_verdict,
        provider_work_status=work_status, work_status_source=source,
        provider_reading=provider_reading, provider_verdict=provider_verdict, auditor_reading=auditor_reading,
        work_verdict=work_verdict, reasons=ordered, status=status, actor=actor, action=action,
    )


# ---------------------------------------------------------------------------
# Providers (A02 as is, cross-checked with FCP-6, never upgraded)
# ---------------------------------------------------------------------------

def _recovery_of(reasons: set) -> str:
    if reasons & {OBSERVED_AUTH_BLOCKED, DIAGNOSTIC_AUTH_BLOCKED}:
        return AUTH_BLOCKED
    if reasons & {DEADLINE_REACHED, DEADLINE_PRECEDES_ELIGIBILITY}:
        return DEADLINE_BLOCKED
    if reasons & {QUOTA_EVIDENCE_DOUBT, QUOTA_EVIDENCE_MISSING, CONDITION_UNRESOLVED, ELIGIBILITY_UNOBSERVED,
                  DIAGNOSTIC_CONTRADICTS_OBSERVATION}:
        return PROVIDER_UNKNOWN
    if ELIGIBILITY_PASSED_UNCONFIRMED in reasons:
        return RECOVERY_UNCONFIRMED
    if COOLDOWN_VERIFIED_PENDING in reasons:
        return COOLDOWN_PENDING
    return AVAILABLE_OBSERVED


def _assess_provider(provider: str, view, workers: list, as_of, deadline) -> ProviderRecovery:
    reasons = set()
    held_by_diagnostic = any(PROVIDER_QUOTA_WAIT in w.reasons for w in workers)
    if any(PROVIDER_AUTH_BLOCKED in w.reasons for w in workers):
        reasons.add(DIAGNOSTIC_AUTH_BLOCKED)
    if view is None or qo.NO_EVIDENCE in view.reasons:
        reasons.add(QUOTA_EVIDENCE_MISSING)
        recovery = _recovery_of(reasons)
        status, actor, action = PROVIDER_RULES[recovery]
        return ProviderRecovery(provider_id=provider, recovery=recovery, status=status, actor=actor, action=action,
                                reasons=_ordered(reasons, PROVIDER_REASONS), evidence_ids=())
    availability = view.availability
    if availability == "AUTH_BLOCKED":
        reasons.add(OBSERVED_AUTH_BLOCKED)
    if any(r in _A02_DOUBT for r in view.reasons) and availability != "AUTH_BLOCKED":
        reasons.add(QUOTA_EVIDENCE_DOUBT)
    if qo.CONDITION_UNRESOLVED in view.reasons:
        reasons.add(CONDITION_UNRESOLVED)
    next_eligible = qc.parse_utc(view.next_eligible_utc) if view.next_eligible_utc else None
    if availability == "QUOTA_WAIT":
        if next_eligible is None:
            reasons.add(ELIGIBILITY_UNOBSERVED)
        elif next_eligible <= as_of:
            reasons.add(ELIGIBILITY_PASSED_UNCONFIRMED)
        else:
            reasons.add(COOLDOWN_VERIFIED_PENDING)
    elif availability == "NONE" and held_by_diagnostic:
        reasons.add(DIAGNOSTIC_CONTRADICTS_OBSERVATION)
    if availability != "AUTH_BLOCKED" and any(PROVIDER_AUTH_BLOCKED in w.reasons for w in workers):
        reasons.add(DIAGNOSTIC_CONTRADICTS_OBSERVATION)
    if deadline is not None and (availability != "NONE" or reasons):
        if as_of >= deadline:
            reasons.add(DEADLINE_REACHED)
        elif next_eligible is not None and availability == "QUOTA_WAIT" and next_eligible >= deadline:
            reasons.add(DEADLINE_PRECEDES_ELIGIBILITY)
    recovery = _recovery_of(reasons)
    status, actor, action = PROVIDER_RULES[recovery]
    wait = availability == "QUOTA_WAIT" and view.next_eligible_utc is not None
    return ProviderRecovery(
        provider_id=provider, recovery=recovery, status=status, actor=actor, action=action,
        reasons=_ordered(reasons, PROVIDER_REASONS), evidence_ids=view.evidence_ids, availability=availability,
        next_eligible_utc=view.next_eligible_utc if wait else None,
        eligibility_source=view.eligibility_source if wait else None,
    )


# ---------------------------------------------------------------------------
# Composite recovery criterion
# ---------------------------------------------------------------------------

def _pairs_ok(pairs, limit: int) -> bool:
    return (type(pairs) is tuple and 1 <= len(pairs) <= limit
            and all(type(p) is tuple and len(p) == 2 and type(p[0]) is str and type(p[1]) is str for p in pairs))


def _pairs_reasons(pairs) -> set:
    reasons = set()
    if not all(_path_ok(path) for path, _ in pairs):
        reasons.add(PATH_INVALID)
    if not all(_fingerprint_ok(digest) for _, digest in pairs):
        reasons.add(PRODUCT_HASH_INVALID)
    if len({path for path, _ in pairs}) != len(pairs):
        reasons.add(PATH_DUPLICATE)
    return reasons


def _structure_reasons(evidence: CompositeRecoveryEvidence) -> set:
    """Shape problems that make the evidence impossible to fingerprint."""
    components = evidence.components
    if not (type(components) is tuple and 1 <= len(components) <= MAX_COMPONENTS
            and all(type(c) is ComponentProduct and _pairs_ok(c.products, MAX_PATHS) for c in components)):
        return {COMPONENTS_MALFORMED}
    reasons = set()
    if not (_pairs_ok(evidence.composite_products, MAX_PATHS) and _pairs_ok(evidence.observed_tree, MAX_PATHS)):
        reasons.add(COMPONENTS_MALFORMED)
    if not all(sc._safe_id(c.component_id) and not qc._secret_shaped(c.component_id) for c in components):
        reasons.add(COMPONENT_ID_INVALID)
    if not (all(_commit_ok(c.commit_sha) for c in components) and _commit_ok(evidence.composite_commit_sha)):
        reasons.add(COMMIT_SHA_INVALID)
    runs = evidence.test_runs
    if not (type(runs) is tuple and len(runs) <= MAX_TEST_RUNS and all(type(r) is SuiteRunEvidence for r in runs)
            and all(_test_run_ok(r) for r in runs)):
        reasons.add(TESTS_MALFORMED)
    return reasons


def _test_run_ok(run: SuiteRunEvidence) -> bool:
    counts = (run.ran, run.failures, run.errors, run.skipped, run.expected_failures, run.unexpected_successes)
    return (qc._in(run.suite, SUITES) and qc._valid_id(run.suite_id) and _commit_ok(run.commit_sha)
            and all(qc._bounded_int(n, 0, MAX_TEST_COUNT) for n in counts) and type(run.complete) is bool)


def _evidence_body(evidence: CompositeRecoveryEvidence) -> dict:
    return {
        "schema": COMPOSITE_EVIDENCE_SCHEMA,
        "components": sorted(({"component_id": c.component_id, "commit_sha": c.commit_sha,
                               "products": sorted([p, h] for p, h in c.products)} for c in evidence.components),
                             key=lambda d: d["component_id"]),
        "composite_commit_sha": evidence.composite_commit_sha,
        "composite_products": sorted([p, h] for p, h in evidence.composite_products),
        "observed_tree": sorted([p, h] for p, h in evidence.observed_tree),
        "test_runs": sorted(([r.suite, r.suite_id, r.commit_sha, r.ran, r.failures, r.errors, r.skipped,
                              r.expected_failures, r.unexpected_successes, r.complete] for r in evidence.test_runs)),
    }


def composite_evidence_fingerprint(evidence) -> Optional[str]:
    """sha256 of the canonical composite evidence (attestation and Direction
    authorization excluded: they bind it). None when it is malformed."""
    if type(evidence) is not CompositeRecoveryEvidence or _structure_reasons(evidence):
        return None
    return _sha(sc._canonical(_evidence_body(evidence)))


def _assess_composite(evidence: CompositeRecoveryEvidence, workers: dict, providers_: dict,
                      as_of) -> CompositeAssessment:
    reasons = _structure_reasons(evidence)
    authorization = evidence.direction_authorization_id
    authorization_ok = qc._valid_id(authorization) and not qc._secret_shaped(authorization)
    if not authorization_ok:
        reasons.add(DIRECTION_AUTHORIZATION_MISSING)
    if COMPONENTS_MALFORMED in reasons:
        # Nothing to bind a Direction act to: a citation stays unverified.
        if authorization_ok:
            reasons.add(DIRECTION_AUTHORIZATION_UNVERIFIED)
        return CompositeAssessment(COMPOSITE_BLOCKED, _ordered(reasons, COMPOSITE_REASONS), None, (), (),
                                   authorization if authorization_ok else None)
    components = evidence.components
    ids = [c.component_id for c in components]
    if len(set(ids)) != len(ids):
        reasons.add(COMPONENT_DUPLICATE)
    commits = [c.commit_sha for c in components] + [evidence.composite_commit_sha]
    if len(set(commits)) != len(commits):
        reasons.add(COMMIT_DUPLICATE)
    for pairs in [c.products for c in components] + [evidence.composite_products, evidence.observed_tree]:
        reasons |= _pairs_reasons(pairs)

    owners = {}
    for component in components:
        for path, digest in component.products:
            owners.setdefault(path, []).append(digest)
    # An invalid path is already PATH_INVALID; only valid ones are echoed.
    collisions = tuple(sorted(p for p, digests in owners.items() if len(digests) > 1 and _path_ok(p)))
    if collisions:
        reasons.add(PATH_COLLISION)
    expected = {path: digests[0] for path, digests in owners.items()}
    composite = dict(evidence.composite_products)
    tree = dict(evidence.observed_tree)
    if set(composite) != set(expected):
        reasons.add(DIFF_NOT_UNION_ONLY)
    if any(composite[p] != expected[p] for p in set(composite) & set(expected)):
        reasons.add(PRODUCT_HASH_MISMATCH)
    if set(tree) != set(expected) or any(tree[p] != expected[p] for p in set(tree) & set(expected)):
        reasons.add(TREE_HASH_MISMATCH)

    if TESTS_MALFORMED not in reasons:
        runs = evidence.test_runs
        suites = {r.suite for r in runs}
        if SUITE_GLOBAL not in suites:
            reasons.add(TESTS_GLOBAL_MISSING)
        if SUITE_HISTORICAL not in suites:
            reasons.add(TESTS_HISTORICAL_MISSING)
        if any(r.commit_sha != evidence.composite_commit_sha for r in runs):
            reasons.add(TESTS_NOT_ON_COMPOSITE)
        if any(not r.complete or r.ran < 1 for r in runs):
            reasons.add(TESTS_INCOMPLETE)
        if any(r.failures or r.errors for r in runs):
            reasons.add(TESTS_NOT_GREEN)
        if any(r.skipped or r.expected_failures or r.unexpected_successes for r in runs):
            reasons.add(TESTS_SKIPPED_OR_EXPECTED)

    fingerprint = composite_evidence_fingerprint(evidence)
    attestation = evidence.attestation
    if attestation is None:
        reasons.add(HOST_ATTESTATION_MISSING)
    elif type(attestation) is not HostAttestation or not (
            qc._valid_id(attestation.attestation_id) and not qc._secret_shaped(attestation.attestation_id)
            and _commit_ok(attestation.composite_commit_sha) and _fingerprint_ok(attestation.evidence_fingerprint)
            and qc.parse_utc(attestation.attested_at_utc) is not None
            and qc.parse_utc(attestation.attested_at_utc) <= as_of):
        reasons.add(HOST_ATTESTATION_INVALID)
    elif (attestation.composite_commit_sha != evidence.composite_commit_sha
          or fingerprint is None or attestation.evidence_fingerprint != fingerprint):
        reasons.add(HOST_ATTESTATION_MISMATCH)
    # A well-formed id is only a citation: it is verified by the cited
    # Direction act bound to this commit, this fingerprint and the valid
    # Host attestation it follows - never by the id, nor by the Host alone.
    verified = authorization_ok and _direction_act_bound(
        evidence, fingerprint, reasons.isdisjoint(_HOST_ATTESTATION_REASONS), as_of)
    if authorization_ok and not verified:
        reasons.add(DIRECTION_AUTHORIZATION_UNVERIFIED)

    for component_id in ids:
        worker = workers.get(component_id)
        if worker is None:
            reasons.add(COMPONENT_UNBOUND)
            continue
        # Positive criterion, never "no FAIL": any worker doubt the verdict
        # axes below do not already express (continuation, wait, pending
        # state, integrity) is unsafe evidence.
        if any(c in _FI_UNSAFE_FOR_COMPOSITE for c in worker.diagnostic_reasons) or (
                set(worker.reasons) - _COMPOSITE_VERDICT_REASONS):
            reasons.add(COMPONENT_EVIDENCE_UNSAFE)
        # Runner and provider axes must both be PASS: BLOCKED (checkpoint
        # failed, preflight refused, cancelled, incomplete evidence),
        # UNVERIFIED or an absent state never qualifies.
        if (worker.runner_verdict, worker.provider_verdict) != (VERDICT_PASS, VERDICT_PASS):
            reasons.add(COMPONENT_VERDICT_NOT_PASS)
        # Audits follow the last checkpoint: only an explicit non-PASS blocks.
        if worker.auditor_reading.verdict not in (VERDICT_PASS, VERDICT_ABSENT):
            reasons.add(COMPONENT_AUDITOR_NOT_PASS)
        provider = providers_.get(worker.provider_id)
        if provider is None or provider.recovery != AVAILABLE_OBSERVED:
            reasons.add(QUOTA_NOT_RECOVERED)
    valid_ids = tuple(sorted({i for i in ids if sc._safe_id(i)}))
    return CompositeAssessment(
        outcome=COMPOSITE_BLOCKED if reasons else COMPOSITE_CRITERIA_MET,
        reasons=_ordered(reasons, COMPOSITE_REASONS), evidence_fingerprint=fingerprint,
        component_ids=valid_ids, collisions=collisions, direction_authorization_id=authorization if authorization_ok
        else None, direction_authorization_verified=verified,
    )


_HOST_ATTESTATION_REASONS = frozenset({HOST_ATTESTATION_MISSING, HOST_ATTESTATION_INVALID, HOST_ATTESTATION_MISMATCH})


def _direction_act_bound(evidence: CompositeRecoveryEvidence, fingerprint, attestation_ok: bool, as_of) -> bool:
    """The cited Direction act names this very commit, fingerprint and valid
    Host attestation, is a distinct act and lies between that attestation
    and the instant."""
    act, attestation = evidence.direction_authorization, evidence.attestation
    if not (attestation_ok and fingerprint is not None and type(act) is DirectionAuthorization):
        return False
    authorized_at = qc.parse_utc(act.authorized_at_utc) if type(act.authorized_at_utc) is str else None
    return (act.authorization_id == evidence.direction_authorization_id
            and act.authorization_id != attestation.attestation_id
            and act.composite_commit_sha == evidence.composite_commit_sha
            and act.evidence_fingerprint == fingerprint
            and act.attestation_id == attestation.attestation_id
            and authorized_at is not None
            and qc.parse_utc(attestation.attested_at_utc) <= authorized_at <= as_of)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _request_reasons(request) -> tuple:
    if type(request) is not RecoveryRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    elif qc._secret_shaped(request.request_id):
        reasons.add(ID_SECRET_SHAPED)
    if request.deadline_utc is not None and qc.parse_utc(request.deadline_utc) is None:
        reasons.add(DEADLINE_INVALID)
    workers = request.workers
    if not (type(workers) is tuple and len(workers) <= MAX_WORKERS
            and all(type(w) is WorkerEvidence for w in workers)):
        reasons.add(WORKERS_MALFORMED)
    else:
        ids = [w.worker_id for w in workers]
        if not all(sc._safe_id(i) for i in ids):
            reasons.add(WORKER_ID_INVALID)
        elif any(qc._secret_shaped(i) for i in ids):
            reasons.add(ID_SECRET_SHAPED)
        elif len(set(ids)) != len(ids):
            reasons.add(WORKER_ID_DUPLICATE)
        if not all(sc._valid_provider_id(w.provider_id) and not qc._secret_shaped(w.provider_id) for w in workers):
            reasons.add(WORKER_PROVIDER_INVALID)
        if not all(w.pipeline_id is None or sc._safe_id(w.pipeline_id) for w in workers):
            reasons.add(WORKER_ID_INVALID)
    if request.composite is not None and type(request.composite) is not CompositeRecoveryEvidence:
        reasons.add(COMPOSITE_NOT_TYPED)
    return _ordered(reasons, REQUEST_REASONS)


def advise_recovery(request: RecoveryRequest) -> RecoveryAdvice:
    """Pure, deterministic, read-only recovery advice. Never raises on bad
    input and never mutates it: an invalid request is an explained refusal.
    The result never transitions a state, retries, resumes, derives a
    `resume_from`, switches a provider, commits, consolidates a checkpoint,
    rewrites history or upgrades a verdict."""
    reasons = _request_reasons(request)
    snapshot = None
    if not reasons:
        snapshot = qo.adapt_observations(request.quota_request)
        if snapshot.request_reasons:
            reasons = _ordered(set(reasons) | {QUOTA_REQUEST_REFUSED}, REQUEST_REASONS)
    if reasons:
        return _refused(reasons)
    as_of = qc.parse_utc(snapshot.as_of_utc)
    deadline = None if request.deadline_utc is None else qc.parse_utc(request.deadline_utc)

    workers = tuple(_assess_worker(w) for w in request.workers)
    provider_ids = sorted({p.provider_id for p in snapshot.providers} | {w.provider_id for w in workers})
    if len(provider_ids) > qc.MAX_PROVIDERS:
        return _refused((PROVIDERS_TOO_MANY,))
    provider_views = tuple(
        _assess_provider(p, snapshot.provider_view(p), [w for w in workers if w.provider_id == p], as_of, deadline)
        for p in provider_ids)
    composite = None
    if request.composite is not None:
        composite = _assess_composite(request.composite, {w.worker_id: w for w in workers},
                                      {p.provider_id: p for p in provider_views}, as_of)

    cited = tuple(sorted({e for p in provider_views for e in p.evidence_ids}))
    advice_reasons = set()
    if composite is not None and composite.outcome != COMPOSITE_CRITERIA_MET:
        advice_reasons.add(COMPOSITE_CRITERIA_NOT_MET)
    if not cited:
        advice_reasons.add(NO_EVIDENCE)
    advice_reasons = _ordered(advice_reasons, ADVICE_REASONS)
    deadline_text = None if deadline is None else sc._utc_text(deadline)
    body = {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "request_id": request.request_id,
        "quota_snapshot_fingerprint": snapshot.snapshot_fingerprint, "deadline_utc": deadline_text,
        "workers": [w.to_dict() for w in workers],
        "composite_evidence_fingerprint": None if composite is None else composite.evidence_fingerprint,
        "composite": None if composite is None else composite.to_dict(),
    }
    body_text = sc._canonical(body)
    if len(body_text) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))
    advice = RecoveryAdvice(
        outcome=outcome_for((), advice_reasons, provider_views, workers), request_id=request.request_id,
        request_fingerprint=_sha(body_text), request_reasons=(), as_of_utc=snapshot.as_of_utc,
        deadline_utc=deadline_text, quota_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        reasons=advice_reasons, evidence_ids=cited, providers=provider_views, workers=workers, composite=composite,
    )
    if len(sc._canonical(RecoveryAdvice.to_dict(advice))) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))
    return advice

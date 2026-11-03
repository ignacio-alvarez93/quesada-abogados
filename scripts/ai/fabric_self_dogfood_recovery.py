"""FCP-12A-04: Self-Dogfood failure recovery contract V1 - pure,
deterministic, fail-closed, NON-BINDING classification of one governed
self-dogfood worker attempt that did not close, and an ADVISORY-ONLY check
of a proposed recovery handoff.

What it answers
---------------
"What kind of failure does the Runner's own evidence show for this attempt,
and - if a recovery is proposed - is the proposal a structured handoff that
already passes every Runner precondition, so a human may take it to the
existing Director recovery gateway?" - and nothing more. The best outcome
for a proposal is `HANDOFF_ADMISSIBLE`: it never retries, resumes, submits a
pipeline, commits, rolls back, resets, cleans, checks out, stashes, pushes,
merges, promotes or records anything. An `AUTO_RECOVER` action is always
DENIED.

No second retry engine
----------------------
The Runner (`runner_pipeline.PipelineRunner`) alone retries, backs off,
waits on quota, reconciles prior work and checkpoints; the Director
(`fabric_director.FabricDirectorService.recover`, `action=
"RESUME_WORK_PRODUCT"`) alone prepares a recovery pipeline, and
`claude_runner.evaluate_resume` alone admits a resume. Nothing here computes
a delay, a deadline, an attempt budget, a `resume_from`, a provider switch
or a next attempt; a Runner-owned wait (quota, transient retry, run in
progress) is reported as RUNNER_OWNS_RECOVERY and never proposed for a
handoff.

Reuse, never redefine
---------------------
* Failure reading: the caller's own FCP-6A-01
  `runner_failure_intelligence.assess_worker` diagnostic and FCP-6B-01
  `runner_recovery_advisory.advise_worker` advisory of that diagnostic.
  They are CONSUMED, never imported (the frozen FCP-6C-04 guard admits only
  two adapters as importers of 6A/6B). The diagnostic is bound to the
  Runner records it reads through FCP-10C-02's own binder
  (`fabric_resource_quota_recovery._diagnostic_ok`); the advisory is
  checked against the FCP-6B vocabulary mirrored here (pinned by tests) and
  must be exactly the advisory of that diagnostic.
* Isolation / HEAD: FCP-12A-02 `assess_guardrails` re-run here on a
  CONFIRM_ISOLATION request (a caller-made assessment is never trusted).
* Recovery gate: the Director's `DirectorRunDecision` and
  `_RECOVERY_ELIGIBLE_DECISION_CODES`; the timeout state is
  `claude_runner.RunState.TIMEOUT`; ids, commits, attempt leaves and
  evidence references are FCP-11A-01's; zero-authority flags extend
  FCP-12A-01.

Failure classes (non-binding; every applicable class, precedence order)
-----------------------------------------------------------------------
INVALID_EVIDENCE, DIVERGENT_CHECKPOINTS, WRONG_HEAD, UNSAFE_STATE, QUOTA,
TIMEOUT, PARTIAL, NATIVE_FAILURE, RUNNER_WAIT, NO_FAILURE. A diagnostic or
advisory that cannot be bound contributes nothing but INVALID_EVIDENCE: its
codes are never read.

Handoff rules (all must hold for HANDOFF_ADMISSIBLE)
----------------------------------------------------
* No blocking class (invalid evidence, divergent checkpoints, wrong HEAD,
  unsafe state, Runner-owned wait, nothing to recover); the bound FCP-6B
  responsibility is HUMAN_REVIEW or CORRECT_WORK.
* Structured `RecoveryHandoff`: the Director action, this pipeline / worker
  / provider / latest attempt / run leaf, the attempt base HEAD, the
  ATTEMPT_WORK_PRODUCT reference (PRESENT, bound to this lineage and listed
  in the Runner's `artifacts`) and the Director's own recovery-eligible
  decision for this worker; no requested automation; no external
  authorization.
* Runner preconditions, checked on facts already captured (never by
  running them): write mode, process confirmed stopped, evidence complete,
  isolation holds, the target HEAD is still the attempt base HEAD
  (`evaluate_resume` refuses any other) and no checkpoint was written.

Stdlib + sibling contracts only; no I/O, process, Git, network, clock or
environment access. Never raises on bad input; outputs hold only enumerated
codes and a digest, never raw input text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import claude_runner as cr
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_resource_quota_recovery as qr
    from scripts.ai import fabric_self_dogfood_contract as dc
    from scripts.ai import fabric_self_dogfood_guardrails as g
except ImportError:  # pragma: no cover - direct script execution
    import claude_runner as cr  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_resource_quota_recovery as qr  # type: ignore[no-redef]
    import fabric_self_dogfood_contract as dc  # type: ignore[no-redef]
    import fabric_self_dogfood_guardrails as g  # type: ignore[no-redef]

SCHEMA = "fcp12a04-self-dogfood-recovery-v1"
SCHEMA_VERSION = 1
RECOVERY_MARKER = "FCP12A04_SELF_DOGFOOD_RECOVERY_NON_BINDING_NOT_AUTHORIZED"

# The sibling contract versions this module was reviewed against.
SUPPORTED_CONTRACT_SCHEMA = "fcp12a01-self-dogfood-closure-v1"
SUPPORTED_GUARDRAILS_SCHEMA = "fcp12a02-self-dogfood-guardrails-v1"
SUPPORTED_SIBLING_SCHEMA_VERSION = 1

# The Director's only recovery confirmation (`FabricDirectorService.recover`).
DIRECTOR_RECOVERY_ACTION = "RESUME_WORK_PRODUCT"
NEXT_STEP_HUMAN_THEN_DIRECTOR = "HUMAN_DECISION_THEN_DIRECTOR_RECOVER"
_WRITE_MODE = "write"
_WORK_PRODUCT_FILENAME = "work_product.json"
_TIMEOUT = cr.RunState.TIMEOUT.value
_SUCCESS = "SUCCESS"

# Mirror of the FCP-6B-01 vocabulary (`runner_recovery_advisory`; pinned by
# tests, never imported, see the module docstring).
RA_ADVISORY_TYPE = "WorkerRecoveryAdvisory"
RA_MODULE_NAME = "runner_recovery_advisory"
RA_SCHEMA_WORKER = "fcp6b01-runner-worker-recovery-advisory-v1"
RA_ADVISORY_MARKER = "FCP6B01_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"
RA_ZERO_AUTHORITY_FLAGS = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed",
                           "resume_allowed", "merging_allowed")
RA_RESPONSIBILITIES = ("RUNNER_NATIVE", "HUMAN_REVIEW", "CORRECT_WORK", "EVIDENCE_REVIEW", "NONE", "UNKNOWN")
RA_CATEGORY_RULES = {
    "DIAGNOSTIC_UNUSABLE": ("UNKNOWN", "REVIEW_DIAGNOSTIC_INTEGRITY"),
    "EVIDENCE_INVALID": ("UNKNOWN", "REVIEW_EVIDENCE_INTEGRITY"),
    "EVIDENCE_CONFLICT": ("UNKNOWN", "REVIEW_EVIDENCE_CONFLICT"),
    "PROCESS_UNRESOLVED": ("HUMAN_REVIEW", "REVIEW_PROCESS_OWNERSHIP"),
    "SAFETY_REFUSED": ("HUMAN_REVIEW", "REVIEW_SAFETY_REFUSAL"),
    "PROVIDER_AUTH_BLOCKED": ("HUMAN_REVIEW", "REVIEW_PROVIDER_CREDENTIALS"),
    "INTERRUPTED": ("HUMAN_REVIEW", "REVIEW_PROCESS_OWNERSHIP"),
    "CHECKPOINT_FAILED": ("HUMAN_REVIEW", "REVIEW_CHECKPOINT_FAILURE"),
    "ACCEPTANCE_FAILED": ("CORRECT_WORK", "REVIEW_WORK_AND_TESTS"),
    "PREFLIGHT_REFUSED": ("HUMAN_REVIEW", "REVIEW_PREFLIGHT_REFUSAL"),
    "EVIDENCE_GAP": ("EVIDENCE_REVIEW", "INVESTIGATE_EVIDENCE"),
    "NATIVE_FAILED": ("HUMAN_REVIEW", "REVIEW_NATIVE_FAILURE"),
    "NATIVE_BLOCKED": ("HUMAN_REVIEW", "REVIEW_NATIVE_BLOCK"),
    "PARTIAL_COMPLETION": ("CORRECT_WORK", "REVIEW_PARTIAL_WORK"),
    "DEPENDENCY_CANCELLED": ("HUMAN_REVIEW", "REVIEW_UPSTREAM_DEPENDENCY"),
    "NATIVE_CANCELLED": ("HUMAN_REVIEW", "REVIEW_NATIVE_CANCELLATION"),
    "EXISTING_PROVIDER_QUOTA_WAIT": ("RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"),
    "EXISTING_RETRY_WAIT": ("RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"),
    "EXISTING_RUN_IN_PROGRESS": ("RUNNER_NATIVE", "OBSERVE_EXISTING_RUN"),
    "HISTORICAL_SUCCESS": ("NONE", "NO_FOLLOWUP_INDICATED"),
}
RA_REASON_CATEGORY = (
    ("DIAGNOSTIC_NOT_TYPED", "DIAGNOSTIC_UNUSABLE"), ("DIAGNOSTIC_INCONSISTENT", "DIAGNOSTIC_UNUSABLE"),
    ("MALFORMED_EVIDENCE", "EVIDENCE_INVALID"), ("IDENTITY_MISMATCH", "EVIDENCE_INVALID"),
    ("DUPLICATE_WORKER_ID", "EVIDENCE_INVALID"), ("UNKNOWN_STATE", "EVIDENCE_INVALID"),
    ("RETRY_DECISION_UNRECOGNIZED", "EVIDENCE_INVALID"), ("EMPTY_PIPELINE", "EVIDENCE_INVALID"),
    ("AGGREGATE_CONTRADICTION", "EVIDENCE_CONFLICT"), ("CONFLICTING_EVIDENCE", "EVIDENCE_CONFLICT"),
    ("PROCESS_TERMINATION_UNRESOLVED", "PROCESS_UNRESOLVED"), ("SAFETY_REFUSAL", "SAFETY_REFUSED"),
    ("PROVIDER_AUTH_BLOCKED", "PROVIDER_AUTH_BLOCKED"), ("INTERRUPTED_OPERATOR_REVIEW", "INTERRUPTED"),
    ("CHECKPOINT_FAILED", "CHECKPOINT_FAILED"), ("ACCEPTANCE_FAILED", "ACCEPTANCE_FAILED"),
    ("PREFLIGHT_REFUSED", "PREFLIGHT_REFUSED"), ("EVIDENCE_INCOMPLETE", "EVIDENCE_GAP"),
    ("EVIDENCE_MISSING", "EVIDENCE_GAP"), ("MISSING_WORKER_RESULT", "EVIDENCE_GAP"),
    ("EXTRA_WORKER_RESULT", "EVIDENCE_GAP"), ("EVIDENCE_UNPROVEN", "EVIDENCE_GAP"),
    ("NATIVE_FAILED", "NATIVE_FAILED"), ("NATIVE_BLOCKED", "NATIVE_BLOCKED"),
    ("PARTIAL_COMPLETION", "PARTIAL_COMPLETION"), ("DEPENDENCY_CANCELLED", "DEPENDENCY_CANCELLED"),
    ("NATIVE_CANCELLED", "NATIVE_CANCELLED"), ("PROVIDER_QUOTA_WAIT", "EXISTING_PROVIDER_QUOTA_WAIT"),
    ("TRANSIENT_RETRY_WAIT", "EXISTING_RETRY_WAIT"), ("NOT_TERMINAL", "EXISTING_RUN_IN_PROGRESS"),
    ("SUCCESS_CONSISTENT", "HISTORICAL_SUCCESS"),
)
_RA_CATEGORY_OF = dict(RA_REASON_CATEGORY)
_RA_PRECEDENCE = tuple(code for code, _ in RA_REASON_CATEGORY)
_RA_RETRY_KINDS = qr.FI_RETRY_DECISION_KINDS | {qr.FI_RETRY_KIND_ABSENT, qr.FI_UNRECOGNIZED}
_EVIDENCE_CATEGORIES = frozenset({"DIAGNOSTIC_UNUSABLE", "EVIDENCE_INVALID", "EVIDENCE_CONFLICT", "EVIDENCE_GAP"})
HANDOFF_RESPONSIBILITIES = ("HUMAN_REVIEW", "CORRECT_WORK")

# Failure classes, highest precedence first.
CLASS_INVALID_EVIDENCE = "INVALID_EVIDENCE"
CLASS_DIVERGENT_CHECKPOINTS = "DIVERGENT_CHECKPOINTS"
CLASS_WRONG_HEAD = "WRONG_HEAD"
CLASS_UNSAFE_STATE = "UNSAFE_STATE"
CLASS_QUOTA = "QUOTA"
CLASS_TIMEOUT = "TIMEOUT"
CLASS_PARTIAL = "PARTIAL"
CLASS_NATIVE_FAILURE = "NATIVE_FAILURE"
CLASS_RUNNER_WAIT = "RUNNER_WAIT"
CLASS_NO_FAILURE = "NO_FAILURE"
FAILURE_CLASSES = (
    CLASS_INVALID_EVIDENCE, CLASS_DIVERGENT_CHECKPOINTS, CLASS_WRONG_HEAD, CLASS_UNSAFE_STATE, CLASS_QUOTA,
    CLASS_TIMEOUT, CLASS_PARTIAL, CLASS_NATIVE_FAILURE, CLASS_RUNNER_WAIT, CLASS_NO_FAILURE,
)
# Classes no handoff may be proposed for (integrity, safety, Runner-owned, nothing to do).
BLOCKING_CLASSES = frozenset({CLASS_INVALID_EVIDENCE, CLASS_DIVERGENT_CHECKPOINTS, CLASS_WRONG_HEAD,
                              CLASS_UNSAFE_STATE, CLASS_QUOTA, CLASS_RUNNER_WAIT, CLASS_NO_FAILURE})

# FCP-6A-01 codes -> failure class (read only from a BOUND diagnostic).
_FI_CLASS = {
    **{c: CLASS_INVALID_EVIDENCE for c in (
        "MALFORMED_EVIDENCE", "IDENTITY_MISMATCH", "DUPLICATE_WORKER_ID", "UNKNOWN_STATE", "AGGREGATE_CONTRADICTION",
        "CONFLICTING_EVIDENCE", "RETRY_DECISION_UNRECOGNIZED", "EVIDENCE_INCOMPLETE", "MISSING_WORKER_RESULT",
        "EXTRA_WORKER_RESULT", "EVIDENCE_MISSING", "EVIDENCE_UNPROVEN", "EMPTY_PIPELINE")},
    **{c: CLASS_UNSAFE_STATE for c in (
        "PROCESS_TERMINATION_UNRESOLVED", "SAFETY_REFUSAL", "INTERRUPTED_OPERATOR_REVIEW", "PROVIDER_AUTH_BLOCKED")},
    **{c: CLASS_NATIVE_FAILURE for c in (
        "CHECKPOINT_FAILED", "ACCEPTANCE_FAILED", "PREFLIGHT_REFUSED", "DEPENDENCY_CANCELLED", "NATIVE_CANCELLED",
        "NATIVE_FAILED", "NATIVE_BLOCKED")},
    "PARTIAL_COMPLETION": CLASS_PARTIAL,
    "PROVIDER_QUOTA_WAIT": CLASS_QUOTA,
    "TRANSIENT_RETRY_WAIT": CLASS_RUNNER_WAIT,
    "NOT_TERMINAL": CLASS_RUNNER_WAIT,
    "SUCCESS_CONSISTENT": CLASS_NO_FAILURE,
}

# Automation a handoff may name only to be refused (never performed here).
FORBIDDEN_OPERATIONS = (
    "AUTO_RETRY", "AUTO_RESUME", "AUTO_SUBMIT_PIPELINE", "AUTO_COMMIT", "AUTO_CHECKPOINT", "ROLLBACK", "RESET",
    "CLEAN", "CHECKOUT", "STASH", "REBASE", "PUSH", "MERGE", "DELETE_WORKTREE", "PROMOTE", "SELF_APPROVE",
)
MAX_OPERATIONS = 32

# Requested actions.
ACTION_CLASSIFY = "CLASSIFY"
ACTION_REQUEST_HANDOFF = "REQUEST_HANDOFF"
ACTION_AUTO_RECOVER = "AUTO_RECOVER"
ACTIONS = (ACTION_CLASSIFY, ACTION_REQUEST_HANDOFF, ACTION_AUTO_RECOVER)

# Decisions.
CLASSIFIED = "CLASSIFIED"
HANDOFF_ADMISSIBLE = "HANDOFF_ADMISSIBLE"
DENIED = "DENIED"
INVALID_REQUEST = "INVALID_REQUEST"
DECISIONS = (CLASSIFIED, HANDOFF_ADMISSIBLE, DENIED, INVALID_REQUEST)

# Reason codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
ACTION_UNKNOWN = "ACTION_UNKNOWN"
HANDOFF_NOT_EXPECTED = "HANDOFF_NOT_EXPECTED"
INVALID_REASONS = (REQUEST_NOT_TYPED, SCHEMA_UNSUPPORTED, ACTION_UNKNOWN, HANDOFF_NOT_EXPECTED)
CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
EVIDENCE_MALFORMED = "EVIDENCE_MALFORMED"
EVIDENCE_PROVENANCE_MISMATCH = "EVIDENCE_PROVENANCE_MISMATCH"
DIAGNOSTIC_UNBOUND = "DIAGNOSTIC_UNBOUND"
ADVISORY_UNBOUND = "ADVISORY_UNBOUND"
ADVISORY_EVIDENCE_UNUSABLE = "ADVISORY_EVIDENCE_UNUSABLE"
CHECKPOINT_SOURCES_DIVERGE = "CHECKPOINT_SOURCES_DIVERGE"
CHECKPOINT_WITHOUT_SUCCESS = "CHECKPOINT_WITHOUT_SUCCESS"
CONTROLLER_HEAD_MOVED = "CONTROLLER_HEAD_MOVED"
TARGET_HEAD_UNEXPECTED = "TARGET_HEAD_UNEXPECTED"
ISOLATION_NOT_PROVEN = "ISOLATION_NOT_PROVEN"
RUNNER_SAFETY_SIGNAL = "RUNNER_SAFETY_SIGNAL"
RUNNER_OWNS_RECOVERY = "RUNNER_OWNS_RECOVERY"
NOTHING_TO_RECOVER = "NOTHING_TO_RECOVER"
RESPONSIBILITY_NOT_HUMAN = "RESPONSIBILITY_NOT_HUMAN"
HANDOFF_MISSING = "HANDOFF_MISSING"
HANDOFF_MALFORMED = "HANDOFF_MALFORMED"
HANDOFF_ACTION_NOT_CONFIRMED = "HANDOFF_ACTION_NOT_CONFIRMED"
HANDOFF_LINEAGE_MISMATCH = "HANDOFF_LINEAGE_MISMATCH"
HANDOFF_BASE_HEAD_MISMATCH = "HANDOFF_BASE_HEAD_MISMATCH"
WORK_PRODUCT_NOT_REFERENCED = "WORK_PRODUCT_NOT_REFERENCED"
DIRECTOR_DECISION_NOT_TYPED = "DIRECTOR_DECISION_NOT_TYPED"
DIRECTOR_DECISION_MISMATCH = "DIRECTOR_DECISION_MISMATCH"
DIRECTOR_NOT_ELIGIBLE = "DIRECTOR_NOT_ELIGIBLE"
NOT_WRITE_MODE = "NOT_WRITE_MODE"
PROCESS_NOT_CONFIRMED_STOPPED = "PROCESS_NOT_CONFIRMED_STOPPED"
EVIDENCE_NOT_COMPLETE = "EVIDENCE_NOT_COMPLETE"
AUTOMATION_FORBIDDEN = "AUTOMATION_FORBIDDEN"
EXTERNAL_AUTHORIZATION_NOT_ACCEPTED = "EXTERNAL_AUTHORIZATION_NOT_ACCEPTED"
AUTOMATED_RECOVERY_FORBIDDEN = "AUTOMATED_RECOVERY_FORBIDDEN"
ASSESSOR_FAULT = "ASSESSOR_FAULT"
REASONS = INVALID_REASONS + (
    CONTRACT_VERSION_UNSUPPORTED, EVIDENCE_MALFORMED, EVIDENCE_PROVENANCE_MISMATCH, DIAGNOSTIC_UNBOUND,
    ADVISORY_UNBOUND, ADVISORY_EVIDENCE_UNUSABLE, CHECKPOINT_SOURCES_DIVERGE, CHECKPOINT_WITHOUT_SUCCESS,
    CONTROLLER_HEAD_MOVED, TARGET_HEAD_UNEXPECTED, ISOLATION_NOT_PROVEN, RUNNER_SAFETY_SIGNAL, RUNNER_OWNS_RECOVERY,
    NOTHING_TO_RECOVER, RESPONSIBILITY_NOT_HUMAN, HANDOFF_MISSING, HANDOFF_MALFORMED, HANDOFF_ACTION_NOT_CONFIRMED,
    HANDOFF_LINEAGE_MISMATCH, HANDOFF_BASE_HEAD_MISMATCH, WORK_PRODUCT_NOT_REFERENCED, DIRECTOR_DECISION_NOT_TYPED,
    DIRECTOR_DECISION_MISMATCH, DIRECTOR_NOT_ELIGIBLE, NOT_WRITE_MODE, PROCESS_NOT_CONFIRMED_STOPPED,
    EVIDENCE_NOT_COMPLETE, AUTOMATION_FORBIDDEN, EXTERNAL_AUTHORIZATION_NOT_ACCEPTED, AUTOMATED_RECOVERY_FORBIDDEN,
    ASSESSOR_FAULT,
)
# Reason -> the failure class it evidences (reasons not listed are handoff-only).
_REASON_CLASS = {
    CONTRACT_VERSION_UNSUPPORTED: CLASS_INVALID_EVIDENCE, EVIDENCE_MALFORMED: CLASS_INVALID_EVIDENCE,
    EVIDENCE_PROVENANCE_MISMATCH: CLASS_INVALID_EVIDENCE, DIAGNOSTIC_UNBOUND: CLASS_INVALID_EVIDENCE,
    ADVISORY_UNBOUND: CLASS_INVALID_EVIDENCE, ADVISORY_EVIDENCE_UNUSABLE: CLASS_INVALID_EVIDENCE,
    ASSESSOR_FAULT: CLASS_INVALID_EVIDENCE,
    CHECKPOINT_SOURCES_DIVERGE: CLASS_DIVERGENT_CHECKPOINTS, CHECKPOINT_WITHOUT_SUCCESS: CLASS_DIVERGENT_CHECKPOINTS,
    CONTROLLER_HEAD_MOVED: CLASS_WRONG_HEAD, TARGET_HEAD_UNEXPECTED: CLASS_WRONG_HEAD,
    ISOLATION_NOT_PROVEN: CLASS_UNSAFE_STATE, RUNNER_SAFETY_SIGNAL: CLASS_UNSAFE_STATE,
}
# FCP-12A-02 HEAD reasons -> this module's HEAD reasons; any other denial is unproven isolation.
_GUARDRAIL_HEAD = {
    g.CONTROLLER_HEAD_UNEXPECTED: CONTROLLER_HEAD_MOVED, g.TARGET_HEAD_UNEXPECTED: TARGET_HEAD_UNEXPECTED,
    g.TARGET_HEAD_DRIFT: TARGET_HEAD_UNEXPECTED,
}


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _ordered_classes(classes) -> tuple:
    return tuple(sorted(set(classes), key=FAILURE_CLASSES.index))


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


def _is(value, expected) -> bool:
    """Exact-type equality: `True` never equals 1, foreign `__eq__` never runs."""
    return type(value) is type(expected) and value == expected


def _obj(value) -> dict:
    return value if type(value) is dict else {}


# ---------------------------------------------------------------------------
# Inputs (tainted; validated only by `assess_recovery`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FailureEvidence:
    """One worker as the caller already read it: its Runner
    `workers/<id>/result.json` (`result`), its `pipeline_result.json`
    `workers[]` entry (`summary`), the FCP-6A-01 diagnostic its own
    `assess_worker` produced for exactly these and the FCP-6B-01 advisory
    `advise_worker` produced for that diagnostic."""
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    provider_id: Optional[str] = None
    result: object = None
    summary: object = None
    diagnostic: object = None
    advisory: object = None


@dataclass(frozen=True)
class RecoveryHandoff:
    """A structured recovery proposal for a human and the Director."""
    schema_version: object = None
    action: Optional[str] = None
    prior_run_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    provider_id: Optional[str] = None
    attempt: Optional[int] = None
    attempt_leaf: Optional[str] = None
    base_head: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    work_product: object = None
    director_decision: object = None
    requested_operations: tuple = ()


@dataclass(frozen=True)
class RecoveryRequest:
    schema_version: object = None
    action: Optional[str] = None
    evidence: object = None
    guardrails: object = None
    handoff: object = None
    external_authorization: object = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _RecoveryGuarantees(dc._DogfoodGuarantees):
    """FCP-12A-01 zero-authority flags plus the recovery-specific ones."""

    @property
    def binding_decision(self) -> bool:
        return False

    @property
    def recovery_executed(self) -> bool:
        return False

    @property
    def pipeline_submission_allowed(self) -> bool:
        return False

    @property
    def commit_allowed(self) -> bool:
        return False

    @property
    def rollback_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = dc._DogfoodGuarantees._guarantees()
        guarantees.update(recovery_marker=RECOVERY_MARKER, binding_decision=False, recovery_executed=False,
                          pipeline_submission_allowed=False, commit_allowed=False, rollback_allowed=False)
        return guarantees


@dataclass(frozen=True)
class RecoveryAssessment(_RecoveryGuarantees):
    """Explainable, non-binding result. Construction re-checks every
    invariant, so a hand-made assessment cannot claim more than its reasons
    and classes allow. `binding` digests the facts an admissible handoff is
    bound to."""
    decision: str
    reasons: tuple
    action: Optional[str] = None
    failure_classes: tuple = ()
    advisory_category: Optional[str] = None
    responsibility: Optional[str] = None
    binding: Optional[str] = None

    def __post_init__(self):
        if not (type(self.decision) is str and self.decision in DECISIONS):
            raise ValueError("unknown recovery decision")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered recovery reason codes")
        if not (type(self.failure_classes) is tuple
                and all(type(c) is str and c in FAILURE_CLASSES for c in self.failure_classes)
                and self.failure_classes == _ordered_classes(self.failure_classes)):
            raise ValueError("failure_classes must be ordered failure classes")
        if not (self.action is None or (type(self.action) is str and self.action in ACTIONS)):
            raise ValueError("unknown recovery action")
        if not (self.advisory_category is None or (type(self.advisory_category) is str
                                                   and self.advisory_category in RA_CATEGORY_RULES)):
            raise ValueError("unknown advisory category")
        if not (self.responsibility is None or (type(self.responsibility) is str
                                                and self.responsibility in RA_RESPONSIBILITIES)):
            raise ValueError("unknown responsibility")
        if not (self.binding is None or (type(self.binding) is str and re.fullmatch(r"[0-9a-f]{64}", self.binding))):
            raise ValueError("binding must be a sha256 hex digest")
        invalid = any(r in INVALID_REASONS for r in self.reasons)
        if self.decision == INVALID_REQUEST:
            if not invalid or self.failure_classes or self.binding is not None or self.responsibility is not None:
                raise ValueError("INVALID_REQUEST needs an invalid-request reason and classifies nothing")
            return
        if invalid or not self.failure_classes or self.action is None:
            raise ValueError("a classified result needs an action, classes and no invalid-request reason")
        if self.decision == CLASSIFIED:
            if self.action != ACTION_CLASSIFY or self.binding is not None:
                raise ValueError("CLASSIFIED belongs to CLASSIFY and binds nothing")
        elif self.decision == DENIED:
            if self.action == ACTION_CLASSIFY or not self.reasons or self.binding is not None:
                raise ValueError("DENIED needs a recovery action, reasons and no binding")
        elif (self.action != ACTION_REQUEST_HANDOFF or self.reasons or self.binding is None
              or set(self.failure_classes) & BLOCKING_CLASSES or self.responsibility not in HANDOFF_RESPONSIBILITIES):
            raise ValueError("HANDOFF_ADMISSIBLE needs a clean, bound, human-owned, non-blocking handoff")

    @property
    def primary_class(self) -> Optional[str]:
        return self.failure_classes[0] if self.failure_classes else None

    @property
    def handoff_admissible(self) -> bool:
        return self.decision == HANDOFF_ADMISSIBLE

    @property
    def next_step(self) -> Optional[str]:
        """Only ever a human decision, then the existing Director gateway."""
        return NEXT_STEP_HUMAN_THEN_DIRECTOR if self.decision == HANDOFF_ADMISSIBLE else None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "decision": self.decision, "action": self.action,
            "handoff_admissible": self.decision == HANDOFF_ADMISSIBLE, "failure_classes": list(self.failure_classes),
            "primary_class": self.primary_class, "advisory_category": self.advisory_category,
            "responsibility": self.responsibility, "next_step": self.next_step, "binding": self.binding,
            "reasons": list(self.reasons), **_RecoveryGuarantees._guarantees(),
        }


def canonical_json(assessment: RecoveryAssessment) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(assessment) is not RecoveryAssessment:
        raise TypeError("canonical_json accepts only a RecoveryAssessment")
    return json.dumps(RecoveryAssessment.to_dict(assessment), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Evidence rules
# ---------------------------------------------------------------------------

class _Facts:
    """Mutable working state of one assessment; never leaves this module."""

    def __init__(self):
        self.reasons: list = []
        self.classes: set = set()
        self.diagnostic = None
        self.advisory = None
        self.last: dict = {}
        self.checkpoint: Optional[str] = None
        self.guardrail_binding: Optional[str] = None

    def deny(self, *codes) -> None:
        self.reasons.extend(codes)


def _advisory_bound(advisory, diagnostic) -> bool:
    """`advisory` is exactly FCP-6B `advise_worker(diagnostic)` for a
    consistent diagnostic: own frozen type and serialization, mirrored rule,
    zero authority and every echoed field equal to the diagnostic's."""
    kind = type(advisory)
    params = getattr(kind, "__dataclass_params__", None)
    if not (kind.__name__ == RA_ADVISORY_TYPE and kind.__module__.rsplit(".", 1)[-1] == RA_MODULE_NAME
            and getattr(params, "frozen", False) is True):
        return False
    payload = advisory.to_dict()
    if not (type(payload) is dict and _is(payload.get("schema"), RA_SCHEMA_WORKER)
            and _is(payload.get("marker"), RA_ADVISORY_MARKER)):
        return False
    if any(payload.get(flag) is not False or getattr(advisory, flag, None) is not False
           for flag in RA_ZERO_AUTHORITY_FLAGS):
        return False
    codes = set(diagnostic.reason_codes)
    if codes != {"SUCCESS_CONSISTENT"}:
        codes.discard("SUCCESS_CONSISTENT")
    expected = tuple(sorted(codes, key=_RA_PRECEDENCE.index))
    state, kind_ = diagnostic.native_state, diagnostic.retry_decision_kind
    echoed = (
        (advisory.worker_id, diagnostic.worker_id), (advisory.source_schema, qr.FI_SCHEMA_WORKER),
        (advisory.source_primary_reason, diagnostic.primary_reason),
        (advisory.native_state, None if state is None else state if state in qr.FI_WORKER_STATES
         else qr.FI_UNRECOGNIZED),
        (advisory.retry_decision_kind, kind_ if kind_ in _RA_RETRY_KINDS else qr.FI_UNRECOGNIZED),
    )
    if not all(type(a) is type(b) and a == b for a, b in echoed):
        return False
    reasons = advisory.reasons
    if not (type(reasons) is tuple and len(reasons) == len(expected)
            and all(_is(a, b) for a, b in zip(reasons, expected))):
        return False
    category = advisory.category
    return (type(category) is str and category == _RA_CATEGORY_OF[expected[0]]
            and (advisory.responsibility, advisory.observation) == RA_CATEGORY_RULES[category]
            and payload.get("category") == category and payload.get("reasons") == list(expected))


def _evidence_reasons(evidence, facts: _Facts) -> None:
    if (dc.SCHEMA, dc.SCHEMA_VERSION, g.SCHEMA, g.SCHEMA_VERSION) != (
            SUPPORTED_CONTRACT_SCHEMA, SUPPORTED_SIBLING_SCHEMA_VERSION, SUPPORTED_GUARDRAILS_SCHEMA,
            SUPPORTED_SIBLING_SCHEMA_VERSION):
        facts.deny(CONTRACT_VERSION_UNSUPPORTED)
    e = evidence
    if not (type(e) is FailureEvidence and cp.valid_id(e.pipeline_id) and cp.valid_id(e.worker_id)
            and cp.valid_id(e.provider_id) and (e.result is None or type(e.result) is dict)
            and type(e.summary) is dict):
        facts.deny(EVIDENCE_MALFORMED, DIAGNOSTIC_UNBOUND)
        return
    # A Runner-owned wait (RETRY_WAIT) writes no result.json: the summary alone is read then.
    result, summary = e.result, e.summary
    if result is not None:
        attempts = result.get("attempts")
        if not (type(attempts) is list and attempts and all(type(a) is dict for a in attempts)):
            facts.deny(EVIDENCE_MALFORMED)
        else:
            facts.last = attempts[-1]
        leaf = facts.last.get("run_id")
        if not (leaf is None or (type(leaf) is str and cp._ATTEMPT_LEAF_RE.fullmatch(leaf) is not None)):
            facts.deny(EVIDENCE_MALFORMED)
        if not (_is(result.get("pipeline_id"), e.pipeline_id) and _is(result.get("worker_id"), e.worker_id)
                and _is(result.get("provider"), e.provider_id) and _is(facts.last.get("provider"), e.provider_id)):
            facts.deny(EVIDENCE_PROVENANCE_MISMATCH)
    if not (_is(summary.get("id"), e.worker_id) and _is(summary.get("provider"), e.provider_id)):
        facts.deny(EVIDENCE_PROVENANCE_MISMATCH)
    try:
        bound = qr._diagnostic_ok(e.diagnostic, qr.WorkerEvidence(
            worker_id=e.worker_id, provider_id=e.provider_id, result=result, summary=summary,
            pipeline_id=e.pipeline_id, diagnostic=e.diagnostic))
    except Exception:  # noqa: BLE001 - a hostile diagnostic is never trusted
        bound = False
    if not bound:
        facts.deny(DIAGNOSTIC_UNBOUND)
        return
    facts.diagnostic = e.diagnostic
    try:
        advisory_ok = _advisory_bound(e.advisory, e.diagnostic)
    except Exception:  # noqa: BLE001 - a hostile advisory is never trusted
        advisory_ok = False
    if not advisory_ok:
        facts.deny(ADVISORY_UNBOUND)
    else:
        facts.advisory = e.advisory
        if e.advisory.category in _EVIDENCE_CATEGORIES:
            facts.deny(ADVISORY_EVIDENCE_UNUSABLE)
    diagnostic = e.diagnostic
    facts.classes.update(_FI_CLASS[c] for c in diagnostic.reason_codes)
    if any(c in _FI_CLASS and _FI_CLASS[c] == CLASS_UNSAFE_STATE for c in diagnostic.reason_codes):
        facts.deny(RUNNER_SAFETY_SIGNAL)
    if _TIMEOUT in (diagnostic.native_runner_state, diagnostic.native_code, diagnostic.native_state_reason):
        facts.classes.add(CLASS_TIMEOUT)


def _checkpoint_reasons(evidence, guardrails, handoff, facts: _Facts) -> None:
    """Every Runner and caller source of the checkpoint commit agrees, and
    a checkpoint exists only beside a Runner SUCCESS."""
    if type(evidence) is not FailureEvidence or type(evidence.summary) is not dict \
            or not (evidence.result is None or type(evidence.result) is dict):
        return
    result = _obj(evidence.result)
    records = [facts.last.get("checkpoint")] + ([result.get("checkpoint")] if "checkpoint" in result else [])
    if not all(c is None or type(c) is dict for c in records):
        facts.deny(EVIDENCE_MALFORMED)
        return
    sources = [evidence.summary.get("checkpoint_commit")]
    sources += [c.get("commit_hash") for c in records if c is not None]
    if type(guardrails) is g.GuardrailRequest:
        sources.append(guardrails.target_checkpoint_commit)
    if type(handoff) is RecoveryHandoff:
        sources.append(handoff.checkpoint_commit)
    if not all(s is None or _commit(s) for s in sources):
        facts.deny(EVIDENCE_MALFORMED)
        return
    if len(set(sources)) > 1:
        facts.deny(CHECKPOINT_SOURCES_DIVERGE)
        return
    facts.checkpoint = sources[0]
    if facts.checkpoint is not None and not _is(evidence.summary.get("state"), _SUCCESS):
        facts.deny(CHECKPOINT_WITHOUT_SUCCESS)


def _guardrail_reasons(evidence, guardrails, facts: _Facts) -> None:
    """FCP-12A-02 re-run on the post-attempt snapshots; HEAD denials are
    WRONG_HEAD, every other denial is unproven isolation."""
    if type(guardrails) is not g.GuardrailRequest or guardrails.action != g.ACTION_CONFIRM_ISOLATION:
        facts.deny(ISOLATION_NOT_PROVEN)
        return
    assessment = g.assess_guardrails(guardrails)
    for reason in assessment.reasons:
        facts.deny(_GUARDRAIL_HEAD.get(reason, ISOLATION_NOT_PROVEN))
    if assessment.isolation_holds:
        facts.guardrail_binding = assessment.binding
    plan, after = guardrails.plan, guardrails.target_after
    if type(plan) is not g.IsolationPlan or type(after) is not g.WorktreeSnapshot:
        return
    expected = facts.checkpoint if facts.checkpoint is not None else plan.attempt_base_head
    if not (_commit(after.head) and after.head == expected):
        facts.deny(TARGET_HEAD_UNEXPECTED)
    if type(evidence) is FailureEvidence and type(evidence.result) is dict:
        worktree = evidence.result.get("worktree")
        key = g.canonical_path_key(worktree) if type(worktree) is str else None
        if key is None or key != g.canonical_path_key(plan.target_path):
            facts.deny(EVIDENCE_PROVENANCE_MISMATCH)


# ---------------------------------------------------------------------------
# Handoff rules
# ---------------------------------------------------------------------------

def _work_product_listed(result: dict, evidence_dir) -> bool:
    """The Runner's own `artifacts` list the attempt's `work_product.json`
    directly inside its canonical `evidence_dir` (string comparison only)."""
    artifacts = result.get("artifacts")
    directory = g.canonical_path_key(evidence_dir) if type(evidence_dir) is str else None
    if directory is None or not (type(artifacts) is list and all(type(a) is str for a in artifacts)):
        return False
    return any(g.canonical_path_key(a) == directory + "/" + _WORK_PRODUCT_FILENAME for a in artifacts)


def _director_reasons(decision, handoff: RecoveryHandoff, evidence: FailureEvidence, facts: _Facts) -> list:
    if type(decision) is not fd.DirectorRunDecision:
        return [DIRECTOR_DECISION_NOT_TYPED]
    reasons = []
    state = facts.diagnostic.native_state if facts.diagnostic is not None else None
    if not (_is(decision.run_id, handoff.prior_run_id) and _is(decision.pipeline_id, evidence.pipeline_id)
            and _is(decision.worker_id, evidence.worker_id) and type(decision.worker_state) is str
            and decision.worker_state == state):
        reasons.append(DIRECTOR_DECISION_MISMATCH)
    if not (type(decision.decision_code) is str and decision.decision_code in fd._RECOVERY_ELIGIBLE_DECISION_CODES
            and decision.human_action_required is True):
        reasons.append(DIRECTOR_NOT_ELIGIBLE)
    return reasons


def _handoff_reasons(request: RecoveryRequest, facts: _Facts) -> list:
    handoff, evidence = request.handoff, request.evidence
    if handoff is None:
        return [HANDOFF_MISSING]
    h = handoff
    if not (type(h) is RecoveryHandoff and _is(h.schema_version, SCHEMA_VERSION) and cp.valid_id(h.prior_run_id)
            and cp.valid_id(h.pipeline_id) and cp.valid_id(h.worker_id) and cp.valid_id(h.provider_id)
            and type(h.attempt) is int and 1 <= h.attempt <= cp.MAX_ATTEMPTS and type(h.attempt_leaf) is str
            and cp._ATTEMPT_LEAF_RE.fullmatch(h.attempt_leaf) is not None and _commit(h.base_head)
            and type(h.requested_operations) is tuple and len(h.requested_operations) <= MAX_OPERATIONS
            and all(type(op) is str for op in h.requested_operations)):
        return [HANDOFF_MALFORMED]
    reasons = []
    if not _is(h.action, DIRECTOR_RECOVERY_ACTION):
        reasons.append(HANDOFF_ACTION_NOT_CONFIRMED)
    if h.requested_operations:
        known = all(op in FORBIDDEN_OPERATIONS for op in h.requested_operations)
        reasons.append(AUTOMATION_FORBIDDEN if known else HANDOFF_MALFORMED)
    if type(evidence) is not FailureEvidence or type(evidence.result) is not dict:
        return reasons + [HANDOFF_LINEAGE_MISMATCH]
    result, last = evidence.result, facts.last
    attempts = result.get("attempts")
    if not ((h.pipeline_id, h.worker_id, h.provider_id) == (evidence.pipeline_id, evidence.worker_id,
                                                            evidence.provider_id)
            and type(attempts) is list and h.attempt == len(attempts) and _is(last.get("attempt"), h.attempt)
            and _is(last.get("run_id"), h.attempt_leaf)):
        reasons.append(HANDOFF_LINEAGE_MISMATCH)
    plan = request.guardrails.plan if type(request.guardrails) is g.GuardrailRequest else None
    if not (type(plan) is g.IsolationPlan and _is(plan.attempt_base_head, h.base_head)):
        reasons.append(HANDOFF_BASE_HEAD_MISMATCH)
    ref = h.work_product
    if not (type(ref) is cp.EvidenceRef and dc._rebuilt(ref) and ref.kind == "ATTEMPT_WORK_PRODUCT"
            and ref.condition == cp.PRESENT and (ref.pipeline_id, ref.worker_id, ref.attempt_leaf) == (
                h.pipeline_id, h.worker_id, h.attempt_leaf)
            and _work_product_listed(result, last.get("evidence_dir"))
            and _is(result.get("evidence_dir"), last.get("evidence_dir"))):
        reasons.append(WORK_PRODUCT_NOT_REFERENCED)
    reasons += _director_reasons(h.director_decision, h, evidence, facts)
    # Runner preconditions (`evaluate_resume` / `PipelineRunner`), on captured facts only.
    if not _is(result.get("mode"), _WRITE_MODE):
        reasons.append(NOT_WRITE_MODE)
    if last.get("process_confirmed_stopped") is not True:
        reasons.append(PROCESS_NOT_CONFIRMED_STOPPED)
    if last.get("evidence_complete") is not True:
        reasons.append(EVIDENCE_NOT_COMPLETE)
    if facts.checkpoint is not None:
        reasons.append(CHECKPOINT_WITHOUT_SUCCESS if not _is(result.get("state"), _SUCCESS) else NOTHING_TO_RECOVER)
    return reasons


def _recovery_reasons(facts: _Facts, classes: tuple) -> list:
    reasons = []
    if CLASS_NO_FAILURE in classes:
        reasons.append(NOTHING_TO_RECOVER)
    if set(classes) & {CLASS_QUOTA, CLASS_RUNNER_WAIT}:
        reasons.append(RUNNER_OWNS_RECOVERY)
    responsibility = facts.advisory.responsibility if facts.advisory is not None else None
    if responsibility not in HANDOFF_RESPONSIBILITIES:
        reasons.append(RUNNER_OWNS_RECOVERY if responsibility == "RUNNER_NATIVE" else RESPONSIBILITY_NOT_HUMAN)
    return reasons


def _binding(request: RecoveryRequest, facts: _Facts, classes: tuple) -> str:
    h, d = request.handoff, facts.diagnostic
    facts_ = {
        "schema": SCHEMA, "prior_run_id": h.prior_run_id, "pipeline_id": h.pipeline_id, "worker_id": h.worker_id,
        "provider_id": h.provider_id, "attempt": h.attempt, "attempt_leaf": h.attempt_leaf,
        "base_head": h.base_head, "work_product_sha256": h.work_product.content_sha256,
        "director_decision_code": h.director_decision.decision_code, "guardrail_binding": facts.guardrail_binding,
        "diagnostic_reasons": list(d.reason_codes), "failure_classes": list(classes),
    }
    payload = json.dumps(facts_, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _invalid(*reasons) -> RecoveryAssessment:
    return RecoveryAssessment(decision=INVALID_REQUEST, reasons=_ordered(reasons))


def _assess(request: RecoveryRequest) -> RecoveryAssessment:
    if type(request) is not RecoveryRequest:
        return _invalid(REQUEST_NOT_TYPED)
    invalid = []
    if not _is(request.schema_version, SCHEMA_VERSION):
        invalid.append(SCHEMA_UNSUPPORTED)
    if not (type(request.action) is str and request.action in ACTIONS):
        invalid.append(ACTION_UNKNOWN)
    elif request.action == ACTION_CLASSIFY and request.handoff is not None:
        invalid.append(HANDOFF_NOT_EXPECTED)
    if invalid:
        return _invalid(*invalid)
    facts = _Facts()
    _evidence_reasons(request.evidence, facts)
    _checkpoint_reasons(request.evidence, request.guardrails, request.handoff, facts)
    _guardrail_reasons(request.evidence, request.guardrails, facts)
    facts.classes.update(_REASON_CLASS[r] for r in facts.reasons if r in _REASON_CLASS)
    if not facts.classes:  # nothing could be read at all: never a pass
        facts.classes.add(CLASS_INVALID_EVIDENCE)
    classes = _ordered_classes(facts.classes)
    advisory = facts.advisory
    shown = dict(advisory_category=advisory.category if advisory is not None else None,
                 responsibility=advisory.responsibility if advisory is not None else None)
    if request.action == ACTION_CLASSIFY:
        return RecoveryAssessment(decision=CLASSIFIED, reasons=_ordered(facts.reasons), action=ACTION_CLASSIFY,
                                  failure_classes=classes, **shown)
    reasons = list(facts.reasons) + _recovery_reasons(facts, classes)
    if request.action == ACTION_AUTO_RECOVER:
        reasons.append(AUTOMATED_RECOVERY_FORBIDDEN)
    else:
        reasons += _handoff_reasons(request, facts)
    if request.external_authorization is not None:
        reasons.append(EXTERNAL_AUTHORIZATION_NOT_ACCEPTED)
    if facts.guardrail_binding is None:
        reasons.append(ISOLATION_NOT_PROVEN)
    reasons = _ordered(reasons)
    if reasons:
        return RecoveryAssessment(decision=DENIED, reasons=reasons, action=request.action, failure_classes=classes,
                                  **shown)
    return RecoveryAssessment(decision=HANDOFF_ADMISSIBLE, reasons=(), action=ACTION_REQUEST_HANDOFF,
                              failure_classes=classes, binding=_binding(request, facts, classes), **shown)


def assess_recovery(request: RecoveryRequest) -> RecoveryAssessment:
    """Pure, deterministic, deny-by-default, non-binding failure
    classification and handoff check. Never raises on bad input; never
    retries, resumes, submits, commits, rolls back, touches Git or records
    anything."""
    try:
        return _assess(request)
    except Exception:  # noqa: BLE001 - hostile input must fail closed, never crash the caller
        action = request.action if type(request) is RecoveryRequest else None
        if not (type(action) is str and action in ACTIONS):
            return _invalid(ACTION_UNKNOWN if type(request) is RecoveryRequest else REQUEST_NOT_TYPED)
        if action == ACTION_CLASSIFY:
            return RecoveryAssessment(decision=CLASSIFIED, reasons=(ASSESSOR_FAULT,), action=action,
                                      failure_classes=(CLASS_INVALID_EVIDENCE,))
        return RecoveryAssessment(decision=DENIED, reasons=(ASSESSOR_FAULT,), action=action,
                                  failure_classes=(CLASS_INVALID_EVIDENCE,))

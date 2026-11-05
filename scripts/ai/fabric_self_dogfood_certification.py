"""FCP-12A-05: Self-Dogfood end-to-end certification evaluator V1 -
deterministic, fail-closed, NON-BINDING readiness check of one governed
self-dogfood worker attempt for the HOST audit.

What it answers
---------------
"Do the Runner's own evidence, the isolation guardrails and the closure
contract - re-run here, never taken from the caller - agree end to end, so
this attempt may be put in front of the host CI / PR and the existing FCP-3
human authorization?" - and nothing more. The ONLY outputs are
`READY_FOR_HOST_AUDIT` and `BLOCKED`. Nothing here is a merge, a closure, a
certification or an authorization: `READY_FOR_HOST_AUDIT` always lists the
host requirements still pending (host CI on a PR, FCP-3 human authorization,
the final host audit), the host CI state is always UNKNOWN and the human
authorization is always NONE. `DECLARE_CLOSED` and `REQUEST_MERGE` are always
BLOCKED.

Re-run, never trusted
---------------------
* Evidence: FCP-12A-03 `read_evidence` on the caller's `EvidenceRequest`
  (bounded, read-only, link-safe reads of the Runner state root and factory
  ledger). A pre-made `SelfDogfoodEvidence`, a provider transcript or any
  other object in its place is refused: Runner evidence is only what that
  reader corroborates.
* Isolation: FCP-12A-02 `assess_guardrails` on a CONFIRM_ISOLATION request,
  and `closure_identity` for the closure identity.
* Closure: FCP-12A-01 `assess_closure` (REQUEST_HUMAN_REVIEW) built from the
  re-read evidence, the re-run identity and the caller's FCP-8A-01
  `ValidationAssessment`.

Separate axes (never merged into one another)
---------------------------------------------
* `evidence_status`: RUNNER_CORROBORATED only from the re-run reader.
* `capability_status`: SYNTHETIC regression suites the caller declares. They
  are capability, never evidence: a claim labelled anything but
  SYNTHETIC_REGRESSION is refused, a partial suite (failure / error / skip /
  zero tests) blocks, and no number of passing suites can stand in for Runner
  evidence.
* `audit_status`: caller-supplied audit records are CLAIMS. This module
  invents no auditor and verifies none: the best status is
  CLAIMED_UNVERIFIED (an independent PASS bound to this checkpoint, no
  contradicting record). Absent, unbound, failed, inconclusive,
  contradicting or self (provider / Runner / CI) audits block.
* `host_ci_status`: always UNKNOWN. Host CI is read by the FCP-3 PR gate on
  the host; any CI claim supplied here is refused, never assumed PASS.
* `human_authorization`: always NONE. Any supplied authorization is refused;
  real promotion stays behind the existing FCP-3 human authorization.
* `security_status`: PROVEN_LOCAL only when isolation holds, the evidence
  (SAFE verdict, scope, protected CI paths) is corroborated and no foreign
  authority was supplied.
* `rollback_status`: ANCHORED when the attempt base HEAD is the same commit
  in the evidence, the isolation plan and the pre-attempt target snapshot,
  and the controller is still at the pinned base. The anchor is reported;
  rollback itself is never performed or allowed here.

Cross-source rules (any disagreement is a reason; contradiction never
averages out): evidence subject = certification subject; plan base commit =
certified FCP-11 base; ref = plan branch = observed target branches, never a
protected branch; evidence base HEAD = plan attempt base HEAD; guardrail
checkpoint = evidence checkpoint; evidence-observed target HEAD = guardrail
post-attempt target HEAD; every committed path inside the plan's scopes.

Traceability without leaks: `reasons` are this module's codes; `trace` holds
the sibling modules' own enumerated codes as `SOURCE:CODE`. Outputs hold only
codes, validated commits, counts and a digest - never a path, an id echoed
from an untrusted record, provider prose or any free text.

Stdlib + sibling contracts only. The only I/O is FCP-12A-03's own read-only
evidence read; no write, Git, process, network, clock or environment access.
Never raises on bad input.
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
    from scripts.ai import fabric_self_dogfood_contract as dc
    from scripts.ai import fabric_self_dogfood_evidence as ev
    from scripts.ai import fabric_self_dogfood_guardrails as g
    from scripts.ai import fabric_validation_contract as vc
except ImportError:  # pragma: no cover - direct script execution
    import claude_runner as cr  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_self_dogfood_contract as dc  # type: ignore[no-redef]
    import fabric_self_dogfood_evidence as ev  # type: ignore[no-redef]
    import fabric_self_dogfood_guardrails as g  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]

SCHEMA = "fcp12a05-self-dogfood-certification-v1"
SCHEMA_VERSION = 1
CERTIFICATION_MARKER = "FCP12A05_SELF_DOGFOOD_CERTIFICATION_NON_BINDING_NO_MERGE_NOT_AUTHORIZED"

# The sibling contract versions this module was reviewed against.
SUPPORTED_SIBLINGS = (
    ("fcp12a01-self-dogfood-closure-v1", 1), ("fcp12a02-self-dogfood-guardrails-v1", 1),
    ("fcp12a03-self-dogfood-evidence-v1", 1), ("fcp8a01-validation-assessment-v1", 1),
)

MAX_AUDITS = 64
MAX_CAPABILITIES = 64
MAX_TESTS = 10 ** 6

# Requested actions.
ACTION_REQUEST_HOST_AUDIT = "REQUEST_HOST_AUDIT"
ACTION_DECLARE_CLOSED = "DECLARE_CLOSED"
ACTION_REQUEST_MERGE = "REQUEST_MERGE"
ACTIONS = (ACTION_REQUEST_HOST_AUDIT, ACTION_DECLARE_CLOSED, ACTION_REQUEST_MERGE)

# Decisions: exactly these two, never anything that reads as merged / closed.
READY_FOR_HOST_AUDIT = "READY_FOR_HOST_AUDIT"
BLOCKED = "BLOCKED"
DECISIONS = (READY_FOR_HOST_AUDIT, BLOCKED)

# Axis vocabularies.
NOT_EVALUATED = "NOT_EVALUATED"
EVIDENCE_RUNNER_CORROBORATED = "RUNNER_CORROBORATED"
EVIDENCE_NOT_CORROBORATED = "NOT_CORROBORATED"
EVIDENCE_STATUSES = (NOT_EVALUATED, EVIDENCE_RUNNER_CORROBORATED, EVIDENCE_NOT_CORROBORATED)
CAPABILITY_NOT_DECLARED = "NOT_DECLARED"
CAPABILITY_SYNTHETIC_DECLARED = "SYNTHETIC_DECLARED"
CAPABILITY_REFUSED = "REFUSED"
CAPABILITY_STATUSES = (NOT_EVALUATED, CAPABILITY_NOT_DECLARED, CAPABILITY_SYNTHETIC_DECLARED, CAPABILITY_REFUSED)
AUDIT_MISSING_STATUS = "MISSING"
AUDIT_REFUSED_STATUS = "REFUSED"
AUDIT_CONTRADICTED_STATUS = "CONTRADICTED"
AUDIT_CLAIMED_UNVERIFIED = "CLAIMED_UNVERIFIED"
AUDIT_STATUSES = (NOT_EVALUATED, AUDIT_MISSING_STATUS, AUDIT_REFUSED_STATUS, AUDIT_CONTRADICTED_STATUS,
                  AUDIT_CLAIMED_UNVERIFIED)
SECURITY_PROVEN_LOCAL = "PROVEN_LOCAL"
SECURITY_NOT_PROVEN = "NOT_PROVEN"
SECURITY_STATUSES = (NOT_EVALUATED, SECURITY_PROVEN_LOCAL, SECURITY_NOT_PROVEN)
ROLLBACK_ANCHORED = "ANCHORED"
ROLLBACK_UNPROVEN = "UNPROVEN"
ROLLBACK_STATUSES = (NOT_EVALUATED, ROLLBACK_ANCHORED, ROLLBACK_UNPROVEN)
HOST_CI_UNKNOWN = cp.OUTCOME_UNKNOWN
HUMAN_AUTHORIZATION_NONE = "NONE"

# What the host still owes after READY_FOR_HOST_AUDIT (always all of them).
PENDING_HOST_REQUIREMENTS = ("HOST_CI_ON_PULL_REQUEST", "FCP3_HUMAN_AUTHORIZATION", "FINAL_HOST_AUDIT")
NEXT_STEP_HOST_AUDIT = "HOST_CI_PR_THEN_FCP3_HUMAN_AUTHORIZATION_THEN_FINAL_AUDIT"

# Capability provenance: synthetic regression is the only admissible label.
PROVENANCE_SYNTHETIC_REGRESSION = "SYNTHETIC_REGRESSION"

# Audit vocabulary. Only HUMAN / INDEPENDENT_AGENT audits can be independent.
AUDITOR_HUMAN = "HUMAN"
AUDITOR_INDEPENDENT_AGENT = "INDEPENDENT_AGENT"
AUDITOR_KINDS = (AUDITOR_HUMAN, AUDITOR_INDEPENDENT_AGENT, "PROVIDER", "RUNNER", "HOST_CI")
INDEPENDENT_AUDITOR_KINDS = (AUDITOR_HUMAN, AUDITOR_INDEPENDENT_AGENT)
AUDIT_PASS = "PASS"
AUDIT_FAIL = "FAIL"
AUDIT_INCONCLUSIVE = "INCONCLUSIVE"
AUDIT_VERDICTS = (AUDIT_PASS, AUDIT_FAIL, AUDIT_INCONCLUSIVE)

# Reason codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
ACTION_UNKNOWN = "ACTION_UNKNOWN"
TARGET_MALFORMED = "TARGET_MALFORMED"
INVALID_REASONS = (REQUEST_NOT_TYPED, SCHEMA_UNSUPPORTED, ACTION_UNKNOWN, TARGET_MALFORMED)
SIBLING_VERSION_UNSUPPORTED = "SIBLING_VERSION_UNSUPPORTED"
REF_PROTECTED = "REF_PROTECTED"
REF_MISMATCH = "REF_MISMATCH"
BASE_COMMIT_MISMATCH = "BASE_COMMIT_MISMATCH"
SUBJECT_MISMATCH = "SUBJECT_MISMATCH"
EVIDENCE_REQUEST_MISSING = "EVIDENCE_REQUEST_MISSING"
EVIDENCE_NOT_RUNNER_READ = "EVIDENCE_NOT_RUNNER_READ"
EVIDENCE_NOT_CORROBORATED_REASON = "EVIDENCE_NOT_CORROBORATED"
GUARDRAILS_MISSING = "GUARDRAILS_MISSING"
GUARDRAILS_NOT_CONFIRMATION = "GUARDRAILS_NOT_CONFIRMATION"
ISOLATION_NOT_PROVEN = "ISOLATION_NOT_PROVEN"
CLOSURE_CONTRACT_DENIED = "CLOSURE_CONTRACT_DENIED"
EVIDENCE_CONTRADICTED = "EVIDENCE_CONTRADICTED"
SCOPE_NOT_PLANNED = "SCOPE_NOT_PLANNED"
SECURITY_NOT_PROVEN_REASON = "SECURITY_NOT_PROVEN"
ROLLBACK_ANCHOR_UNPROVEN = "ROLLBACK_ANCHOR_UNPROVEN"
CAPABILITY_MALFORMED = "CAPABILITY_MALFORMED"
CAPABILITY_PROVENANCE_REFUSED = "CAPABILITY_PROVENANCE_REFUSED"
CAPABILITY_PARTIAL = "CAPABILITY_PARTIAL"
AUDIT_MISSING = "AUDIT_MISSING"
AUDIT_MALFORMED = "AUDIT_MALFORMED"
AUDIT_UNBOUND = "AUDIT_UNBOUND"
AUDIT_NOT_INDEPENDENT = "AUDIT_NOT_INDEPENDENT"
AUDIT_FAILED = "AUDIT_FAILED"
AUDIT_INCONCLUSIVE_REASON = "AUDIT_INCONCLUSIVE"
AUDIT_CONTRADICTED = "AUDIT_CONTRADICTED"
HOST_CI_CLAIM_NOT_ACCEPTED = "HOST_CI_CLAIM_NOT_ACCEPTED"
HUMAN_AUTHORIZATION_NOT_ACCEPTED = "HUMAN_AUTHORIZATION_NOT_ACCEPTED"
CLOSURE_REQUIRES_HOST_CI_AND_FCP3_HUMAN_AUTHORIZATION = "CLOSURE_REQUIRES_HOST_CI_AND_FCP3_HUMAN_AUTHORIZATION"
CERTIFIER_FAULT = "CERTIFIER_FAULT"
REASONS = INVALID_REASONS + (
    SIBLING_VERSION_UNSUPPORTED, REF_PROTECTED, REF_MISMATCH, BASE_COMMIT_MISMATCH, SUBJECT_MISMATCH,
    EVIDENCE_REQUEST_MISSING, EVIDENCE_NOT_RUNNER_READ, EVIDENCE_NOT_CORROBORATED_REASON, GUARDRAILS_MISSING,
    GUARDRAILS_NOT_CONFIRMATION, ISOLATION_NOT_PROVEN, CLOSURE_CONTRACT_DENIED, EVIDENCE_CONTRADICTED,
    SCOPE_NOT_PLANNED, SECURITY_NOT_PROVEN_REASON, ROLLBACK_ANCHOR_UNPROVEN, CAPABILITY_MALFORMED,
    CAPABILITY_PROVENANCE_REFUSED, CAPABILITY_PARTIAL, AUDIT_MISSING, AUDIT_MALFORMED, AUDIT_UNBOUND,
    AUDIT_NOT_INDEPENDENT, AUDIT_FAILED, AUDIT_INCONCLUSIVE_REASON, AUDIT_CONTRADICTED, HOST_CI_CLAIM_NOT_ACCEPTED,
    HUMAN_AUTHORIZATION_NOT_ACCEPTED, CLOSURE_REQUIRES_HOST_CI_AND_FCP3_HUMAN_AUTHORIZATION, CERTIFIER_FAULT,
)

# Trace sources and the enumerated vocabulary each may contribute.
TRACE_EVIDENCE = "EVIDENCE"
TRACE_GUARDRAILS = "GUARDRAILS"
TRACE_CLOSURE = "CLOSURE"
TRACE_SOURCES = (TRACE_EVIDENCE, TRACE_GUARDRAILS, TRACE_CLOSURE)
_TRACE_VOCABULARY = {TRACE_EVIDENCE: ev.REASONS, TRACE_GUARDRAILS: g.REASONS, TRACE_CLOSURE: dc.REASONS}

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _ordered_trace(pairs) -> tuple:
    return tuple(sorted(set(pairs), key=lambda p: (TRACE_SOURCES.index(p[0]), _TRACE_VOCABULARY[p[0]].index(p[1]))))


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


def _is(value, expected) -> bool:
    """Exact-type equality: `True` never equals 1, foreign `__eq__` never runs."""
    return type(value) is type(expected) and value == expected


def _in(value, vocabulary) -> bool:
    return type(value) is str and value in vocabulary


def _count(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_TESTS


# ---------------------------------------------------------------------------
# Inputs (frozen, TAINTED; validated only by `evaluate_certification`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CertificationTarget:
    """What is being certified: one worker of one pipeline, on one feature
    ref, developed from one pinned FCP-11 base commit."""
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    ref: Optional[str] = None
    base_commit: Optional[str] = None


@dataclass(frozen=True)
class CapabilityClaim:
    """A synthetic regression suite the caller ran (mocks / fixtures). It
    shows capability, never that a real dogfood run happened."""
    suite_id: Optional[str] = None
    provenance: Optional[str] = None
    tests_run: object = None
    failures: object = None
    errors: object = None
    skipped: object = None


@dataclass(frozen=True)
class AuditRecord:
    """An audit CLAIM about one checkpoint. Never verified here."""
    audit_id: Optional[str] = None
    auditor_kind: Optional[str] = None
    auditor_id: Optional[str] = None
    subject_pipeline_id: Optional[str] = None
    subject_worker_id: Optional[str] = None
    subject_commit: Optional[str] = None
    verdict: Optional[str] = None


@dataclass(frozen=True)
class CertificationRequest:
    schema_version: object = None
    action: Optional[str] = None
    target: object = None
    evidence_request: object = None
    guardrails: object = None
    validation: object = None
    capabilities: object = ()
    audits: object = ()
    host_ci: object = None
    human_authorization: object = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _CertificationGuarantees(dc._DogfoodGuarantees):
    """FCP-12A-01 zero-authority flags plus the certification-specific ones."""

    @property
    def binding_decision(self) -> bool:
        return False

    @property
    def merge_performed(self) -> bool:
        return False

    @property
    def host_audit_performed(self) -> bool:
        return False

    @property
    def host_ci_assumed(self) -> bool:
        return False

    @property
    def audit_verified(self) -> bool:
        return False

    @property
    def rollback_allowed(self) -> bool:
        return False

    @property
    def external_claims_accepted(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = dc._DogfoodGuarantees._guarantees()
        guarantees.update(certification_marker=CERTIFICATION_MARKER, binding_decision=False, merge_performed=False,
                          host_audit_performed=False, host_ci_assumed=False, audit_verified=False,
                          rollback_allowed=False, external_claims_accepted=False)
        return guarantees


@dataclass(frozen=True)
class CertificationAssessment(_CertificationGuarantees):
    """Explainable, non-binding certification readiness. Construction
    re-checks every invariant, so a hand-made assessment cannot claim more
    than its reasons and axes allow."""
    decision: str
    reasons: tuple
    action: Optional[str] = None
    trace: tuple = ()
    evidence_status: str = NOT_EVALUATED
    capability_status: str = NOT_EVALUATED
    audit_status: str = NOT_EVALUATED
    security_status: str = NOT_EVALUATED
    rollback_status: str = NOT_EVALUATED
    rollback_anchor: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    binding: Optional[str] = None

    def __post_init__(self):
        if not _in(self.decision, DECISIONS):
            raise ValueError("unknown certification decision")
        if not (type(self.reasons) is tuple and all(_in(r, REASONS) for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered certification reason codes")
        if not (type(self.trace) is tuple and all(
                type(p) is tuple and len(p) == 2 and _in(p[0], TRACE_SOURCES) and _in(p[1], _TRACE_VOCABULARY[p[0]])
                for p in self.trace) and self.trace == _ordered_trace(self.trace)):
            raise ValueError("trace must be ordered (source, sibling code) pairs")
        if not (self.action is None or _in(self.action, ACTIONS)):
            raise ValueError("unknown certification action")
        for value, vocabulary in ((self.evidence_status, EVIDENCE_STATUSES),
                                  (self.capability_status, CAPABILITY_STATUSES),
                                  (self.audit_status, AUDIT_STATUSES), (self.security_status, SECURITY_STATUSES),
                                  (self.rollback_status, ROLLBACK_STATUSES)):
            if not _in(value, vocabulary):
                raise ValueError("axis status outside its vocabulary")
        if not (self.rollback_anchor is None or _commit(self.rollback_anchor)) \
                or (self.rollback_anchor is not None) != (self.rollback_status == ROLLBACK_ANCHORED):
            raise ValueError("a rollback anchor exists exactly when the rollback is ANCHORED")
        if not (self.checkpoint_commit is None or _commit(self.checkpoint_commit)):
            raise ValueError("checkpoint_commit must be 40/64 hex")
        if not (self.binding is None or (type(self.binding) is str and _DIGEST_RE.fullmatch(self.binding))):
            raise ValueError("binding must be a sha256 hex digest")
        if self.decision == READY_FOR_HOST_AUDIT:
            ready = (
                not self.reasons and not self.trace and self.action == ACTION_REQUEST_HOST_AUDIT
                and self.evidence_status == EVIDENCE_RUNNER_CORROBORATED
                and self.capability_status in (CAPABILITY_NOT_DECLARED, CAPABILITY_SYNTHETIC_DECLARED)
                and self.audit_status == AUDIT_CLAIMED_UNVERIFIED and self.security_status == SECURITY_PROVEN_LOCAL
                and self.rollback_status == ROLLBACK_ANCHORED and self.checkpoint_commit is not None
                and self.checkpoint_commit != self.rollback_anchor and self.binding is not None
            )
            if not ready:
                raise ValueError("READY_FOR_HOST_AUDIT needs every axis proven, no reasons and a binding")
        elif not self.reasons or self.binding is not None:
            raise ValueError("BLOCKED needs at least one reason and binds nothing")

    @property
    def ready_for_host_audit(self) -> bool:
        return self.decision == READY_FOR_HOST_AUDIT

    @property
    def host_ci_status(self) -> str:
        """Always UNKNOWN: host CI is never read or assumed here."""
        return HOST_CI_UNKNOWN

    @property
    def human_authorization(self) -> str:
        """Always NONE: only the existing FCP-3 human authorization counts."""
        return HUMAN_AUTHORIZATION_NONE

    @property
    def pending_host_requirements(self) -> tuple:
        return PENDING_HOST_REQUIREMENTS

    @property
    def next_step(self) -> Optional[str]:
        return NEXT_STEP_HOST_AUDIT if self.decision == READY_FOR_HOST_AUDIT else None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "decision": self.decision, "action": self.action,
            "ready_for_host_audit": self.decision == READY_FOR_HOST_AUDIT, "reasons": list(self.reasons),
            "trace": [f"{s}:{c}" for s, c in self.trace], "evidence_status": self.evidence_status,
            "capability_status": self.capability_status, "audit_status": self.audit_status,
            "host_ci_status": HOST_CI_UNKNOWN, "human_authorization": HUMAN_AUTHORIZATION_NONE,
            "security_status": self.security_status, "rollback_status": self.rollback_status,
            "rollback_anchor": self.rollback_anchor, "checkpoint_commit": self.checkpoint_commit,
            "binding": self.binding, "pending_host_requirements": list(PENDING_HOST_REQUIREMENTS),
            "next_step": self.next_step, **_CertificationGuarantees._guarantees(),
        }


def canonical_json(assessment: CertificationAssessment) -> str:
    """Stable, sorted, compact serialization of the exact output type."""
    if type(assessment) is not CertificationAssessment:
        raise TypeError("canonical_json accepts only a CertificationAssessment")
    return json.dumps(CertificationAssessment.to_dict(assessment), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

class _Facts:
    """Mutable working state of one evaluation; never leaves this module."""

    def __init__(self):
        self.reasons: list = []
        self.trace: set = set()
        self.evidence = None
        self.guardrail = None
        self.audit_ids: tuple = ()
        self.suite_ids: tuple = ()

    def deny(self, *codes) -> None:
        self.reasons.extend(codes)

    def traced(self, source: str, codes) -> None:
        self.trace.update((source, c) for c in codes)


def _target_ok(target) -> bool:
    return (type(target) is CertificationTarget and cp.valid_id(target.pipeline_id) and cp.valid_id(target.worker_id)
            and g._branch_ok(target.ref) and _commit(target.base_commit))


def _sibling_versions_ok() -> bool:
    return ((dc.SCHEMA, dc.SCHEMA_VERSION), (g.SCHEMA, g.SCHEMA_VERSION), (ev.SCHEMA, ev.SCHEMA_VERSION),
            (vc.SCHEMA, vc.SCHEMA_VERSION)) == SUPPORTED_SIBLINGS


def _evidence_rules(request: CertificationRequest, facts: _Facts) -> str:
    er, target = request.evidence_request, request.target
    if er is None:
        facts.deny(EVIDENCE_REQUEST_MISSING)
        return EVIDENCE_NOT_CORROBORATED
    if type(er) is not ev.EvidenceRequest:
        facts.deny(EVIDENCE_NOT_RUNNER_READ)
        return EVIDENCE_NOT_CORROBORATED
    if not (_is(er.pipeline_id, target.pipeline_id) and _is(er.worker_id, target.worker_id)):
        facts.deny(SUBJECT_MISMATCH)
    result = ev.read_evidence(er)
    if not result.corroborated:
        facts.deny(EVIDENCE_NOT_CORROBORATED_REASON)
        facts.traced(TRACE_EVIDENCE, result.reasons)
        return EVIDENCE_NOT_CORROBORATED
    facts.evidence = result
    return EVIDENCE_RUNNER_CORROBORATED


def _guardrail_rules(request: CertificationRequest, facts: _Facts) -> None:
    gr = request.guardrails
    if gr is None:
        facts.deny(GUARDRAILS_MISSING)
        return
    if type(gr) is not g.GuardrailRequest or gr.action != g.ACTION_CONFIRM_ISOLATION:
        facts.deny(GUARDRAILS_NOT_CONFIRMATION)
        return
    assessment = g.assess_guardrails(gr)
    if not assessment.isolation_holds:
        facts.deny(ISOLATION_NOT_PROVEN)
        facts.traced(TRACE_GUARDRAILS, assessment.reasons)
        return
    facts.guardrail = assessment


def _closure_rules(request: CertificationRequest, facts: _Facts) -> None:
    """FCP-12A-01 on the re-read evidence and the re-run identity."""
    e = facts.evidence
    gr = request.guardrails if type(request.guardrails) is g.GuardrailRequest else None
    identity = g.closure_identity(gr) if gr is not None else None
    closure = dc.assess_closure(dc.CloseRequest(
        schema_version=dc.SCHEMA_VERSION, action=dc.ACTION_REQUEST_HUMAN_REVIEW, identity=identity,
        lineage=e.lineage() if e is not None else None, completion=e.completion() if e is not None else None,
        validation=request.validation, evidence=e.closure_evidence() if e is not None else ()))
    if not closure.review_requestable:
        facts.deny(CLOSURE_CONTRACT_DENIED)
        facts.traced(TRACE_CLOSURE, closure.reasons)


def _ref_rules(request: CertificationRequest, facts: _Facts) -> None:
    target, gr = request.target, request.guardrails
    if target.ref in cr.PROTECTED_BRANCHES:
        facts.deny(REF_PROTECTED)
    if type(gr) is not g.GuardrailRequest or type(gr.plan) is not g.IsolationPlan:
        return
    plan = gr.plan
    branches = [plan.target_branch] + [s.branch for s in (gr.target_before, gr.target_after)
                                       if type(s) is g.WorktreeSnapshot]
    if not all(_is(b, target.ref) for b in branches):
        facts.deny(REF_MISMATCH)
    if not _is(plan.base_commit, target.base_commit):
        facts.deny(BASE_COMMIT_MISMATCH)


def _cross_rules(request: CertificationRequest, facts: _Facts) -> None:
    """Evidence vs guardrails: one fact, one value, from every source."""
    e, gr = facts.evidence, request.guardrails
    if e is None or type(gr) is not g.GuardrailRequest or type(gr.plan) is not g.IsolationPlan:
        return
    plan, after = gr.plan, gr.target_after
    observed = request.evidence_request.observed_target_head
    after_head = after.head if type(after) is g.WorktreeSnapshot else None
    if not (_is(plan.attempt_base_head, e.attempt_base_head) and _is(gr.target_checkpoint_commit, e.checkpoint_commit)
            and _is(after_head, observed) and _is(observed, e.checkpoint_commit)):
        facts.deny(EVIDENCE_CONTRADICTED)
    scopes = plan.authorized_scopes
    if not (type(scopes) is tuple and all(type(s) is str for s in scopes)
            and all(cr.path_is_authorized(p, list(scopes)) for p in e.changed_paths)):
        facts.deny(SCOPE_NOT_PLANNED)


def _rollback_rules(request: CertificationRequest, facts: _Facts) -> tuple:
    """(status, anchor): the attempt base HEAD, agreed by every source, with
    the controller still at the certified base."""
    e, gr, target = facts.evidence, request.guardrails, request.target
    anchored = (
        e is not None and facts.guardrail is not None and type(gr.plan) is g.IsolationPlan
        and type(gr.target_before) is g.WorktreeSnapshot and type(gr.controller_after) is g.WorktreeSnapshot
        and _commit(e.attempt_base_head) and _is(gr.plan.attempt_base_head, e.attempt_base_head)
        and _is(gr.target_before.head, e.attempt_base_head)
        and _is(gr.controller_after.head, target.base_commit) and _is(gr.plan.controller_commit, target.base_commit)
    )
    if not anchored:
        facts.deny(ROLLBACK_ANCHOR_UNPROVEN)
        return ROLLBACK_UNPROVEN, None
    return ROLLBACK_ANCHORED, e.attempt_base_head


def _capability_rules(capabilities, facts: _Facts) -> str:
    if not (type(capabilities) is tuple and len(capabilities) <= MAX_CAPABILITIES
            and all(type(c) is CapabilityClaim for c in capabilities)):
        facts.deny(CAPABILITY_MALFORMED)
        return CAPABILITY_REFUSED
    if not capabilities:
        return CAPABILITY_NOT_DECLARED
    reasons = []
    ids = []
    for c in capabilities:
        if not (cp.valid_id(c.suite_id) and all(_count(v) for v in (c.tests_run, c.failures, c.errors, c.skipped))):
            reasons.append(CAPABILITY_MALFORMED)
            continue
        ids.append(c.suite_id)
        if not _is(c.provenance, PROVENANCE_SYNTHETIC_REGRESSION):
            reasons.append(CAPABILITY_PROVENANCE_REFUSED)
        if c.tests_run == 0 or c.failures or c.errors or c.skipped:
            reasons.append(CAPABILITY_PARTIAL)
    if len(set(ids)) != len(ids):
        reasons.append(CAPABILITY_MALFORMED)
    if reasons:
        facts.deny(*reasons)
        return CAPABILITY_REFUSED
    facts.suite_ids = tuple(sorted(ids))
    return CAPABILITY_SYNTHETIC_DECLARED


def _audit_rules(audits, target: CertificationTarget, facts: _Facts) -> str:
    if not (type(audits) is tuple and len(audits) <= MAX_AUDITS and all(type(a) is AuditRecord for a in audits)):
        facts.deny(AUDIT_MALFORMED)
        return AUDIT_REFUSED_STATUS
    if not audits:
        facts.deny(AUDIT_MISSING)
        return AUDIT_MISSING_STATUS
    e = facts.evidence
    commit = e.checkpoint_commit if e is not None else None
    provider = e.provider_id if e is not None else None
    reasons, ids, verdicts = [], [], set()
    for a in audits:
        if not (cp.valid_id(a.audit_id) and _in(a.auditor_kind, AUDITOR_KINDS) and cp.valid_id(a.auditor_id)
                and cp.valid_id(a.subject_pipeline_id) and cp.valid_id(a.subject_worker_id)
                and _commit(a.subject_commit) and _in(a.verdict, AUDIT_VERDICTS)):
            reasons.append(AUDIT_MALFORMED)
            continue
        ids.append(a.audit_id)
        if not ((a.subject_pipeline_id, a.subject_worker_id) == (target.pipeline_id, target.worker_id)
                and commit is not None and a.subject_commit == commit):
            reasons.append(AUDIT_UNBOUND)
            continue
        verdicts.add(a.verdict)
        if a.auditor_kind not in INDEPENDENT_AUDITOR_KINDS or a.auditor_id == provider:
            reasons.append(AUDIT_NOT_INDEPENDENT)
        if a.verdict == AUDIT_FAIL:
            reasons.append(AUDIT_FAILED)
        elif a.verdict == AUDIT_INCONCLUSIVE:
            reasons.append(AUDIT_INCONCLUSIVE_REASON)
    if len(set(ids)) != len(ids):
        reasons.append(AUDIT_MALFORMED)
    contradicted = AUDIT_PASS in verdicts and len(verdicts) > 1
    if contradicted:
        reasons.append(AUDIT_CONTRADICTED)
    if AUDIT_PASS not in verdicts and not reasons:
        reasons.append(AUDIT_MISSING)
    if reasons:
        facts.deny(*reasons)
        return AUDIT_CONTRADICTED_STATUS if contradicted else AUDIT_REFUSED_STATUS
    facts.audit_ids = tuple(sorted(ids))
    return AUDIT_CLAIMED_UNVERIFIED


def _binding(request: CertificationRequest, facts: _Facts, anchor: str) -> str:
    e, t = facts.evidence, request.target
    payload = {
        "schema": SCHEMA, "pipeline_id": t.pipeline_id, "worker_id": t.worker_id, "ref": t.ref,
        "base_commit": t.base_commit, "attempt": e.attempt, "attempt_leaf": e.attempt_leaf,
        "provider_id": e.provider_id, "rollback_anchor": anchor, "checkpoint_commit": e.checkpoint_commit,
        "guardrail_binding": facts.guardrail.binding,
        "evidence": {r.kind: r.content_sha256 for r in e.evidence},
        "validation_sha256": hashlib.sha256(vc.canonical_json(request.validation).encode("ascii")).hexdigest(),
        "audit_ids": list(facts.audit_ids), "suite_ids": list(facts.suite_ids),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _blocked_invalid(*reasons, action=None) -> CertificationAssessment:
    return CertificationAssessment(decision=BLOCKED, reasons=_ordered(reasons), action=action)


def _evaluate(request: CertificationRequest) -> CertificationAssessment:
    if type(request) is not CertificationRequest:
        return _blocked_invalid(REQUEST_NOT_TYPED)
    invalid = []
    if not _is(request.schema_version, SCHEMA_VERSION):
        invalid.append(SCHEMA_UNSUPPORTED)
    action = request.action if _in(request.action, ACTIONS) else None
    if action is None:
        invalid.append(ACTION_UNKNOWN)
    if not _target_ok(request.target):
        invalid.append(TARGET_MALFORMED)
    if invalid:
        return _blocked_invalid(*invalid, action=action)
    facts = _Facts()
    if not _sibling_versions_ok():
        facts.deny(SIBLING_VERSION_UNSUPPORTED)
    evidence_status = _evidence_rules(request, facts)
    _guardrail_rules(request, facts)
    _closure_rules(request, facts)
    _ref_rules(request, facts)
    _cross_rules(request, facts)
    rollback_status, anchor = _rollback_rules(request, facts)
    capability_status = _capability_rules(request.capabilities, facts)
    audit_status = _audit_rules(request.audits, request.target, facts)
    if request.host_ci is not None:
        facts.deny(HOST_CI_CLAIM_NOT_ACCEPTED)
    if request.human_authorization is not None:
        facts.deny(HUMAN_AUTHORIZATION_NOT_ACCEPTED)
    secure = (facts.evidence is not None and facts.guardrail is not None and request.host_ci is None
              and request.human_authorization is None)
    if not secure:
        facts.deny(SECURITY_NOT_PROVEN_REASON)
    if action != ACTION_REQUEST_HOST_AUDIT:
        facts.deny(CLOSURE_REQUIRES_HOST_CI_AND_FCP3_HUMAN_AUTHORIZATION)
    reasons = _ordered(facts.reasons)
    checkpoint = facts.evidence.checkpoint_commit if facts.evidence is not None else None
    axes = dict(action=action, evidence_status=evidence_status, capability_status=capability_status,
                audit_status=audit_status, security_status=SECURITY_PROVEN_LOCAL if secure else SECURITY_NOT_PROVEN,
                rollback_status=rollback_status, rollback_anchor=anchor, checkpoint_commit=checkpoint)
    if reasons:
        return CertificationAssessment(decision=BLOCKED, reasons=reasons, trace=_ordered_trace(facts.trace), **axes)
    return CertificationAssessment(decision=READY_FOR_HOST_AUDIT, reasons=(), binding=_binding(request, facts, anchor),
                                   **axes)


def evaluate_certification(request: CertificationRequest) -> CertificationAssessment:
    """Deterministic, deny-by-default, non-binding end-to-end readiness for
    the host audit. Never raises on bad input; never merges, closes,
    certifies, authorizes, runs Git, writes, rolls back or records anything."""
    try:
        return _evaluate(request)
    except Exception:  # noqa: BLE001 - hostile input must fail closed, never crash the caller
        action = request.action if type(request) is CertificationRequest and _in(request.action, ACTIONS) else None
        return CertificationAssessment(decision=BLOCKED, reasons=(CERTIFIER_FAULT,), action=action)

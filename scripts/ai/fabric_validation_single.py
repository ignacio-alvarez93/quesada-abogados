"""FCP-8A-02: SINGLE-WORKER validation evidence adapter - a pure, read-only,
fail-closed projection of ONE Director Work Order run onto the FCP-8A-01
`ValidationFacts` contract.

Sources (the only authority of the observation)
-----------------------------------------------
`observe_single_run(service, run_id)` calls exactly
`service.result(run_id)`, `service.evidence(run_id)` and
`service.decision(run_id)` - once each, in that order - and nothing else. It
never opens `result.json`/`metadata.json` itself, never re-runs Runner rules
(safety, resume, acceptance, checkpoint, availability) and never calls
`submit`, `run`, `recover`, `execute_work_order`, `PipelineRunner`, Git, a
shell, a socket or a file. A read that raises, or returns anything other than
the exact Director contract type, makes the whole observation UNKNOWN.

Join and contradictions
-----------------------
The three projections must describe the same `run_id`, `pipeline_id` and
`worker_id`. A disagreement makes `provenance_bound=False` and every other
fact UNKNOWN; a missing identity makes everything UNKNOWN. Any other field
the projections share (worker state, work status, evidence completeness,
safety verdict, unauthorized paths, checkpoint, provider condition, work
product presence) must agree verbatim; a disagreement or a mistyped value
turns only the facts that read that field UNKNOWN. A Director decision that
contradicts a positive fact turns that fact UNKNOWN. UNKNOWN is never True.

Fact mapping (each fact reads only its own fields)
--------------------------------------------------
* `work_success`: True only for worker_state SUCCESS with work_status SUCCESS
  certified by Runner (`work_status_source=RUNNER_ACCEPTANCE`), no provider
  condition and no missing ON_SUCCESS checkpoint. A provider-sourced SUCCESS
  (`provider_work_status`/`PROVIDER`) is reported, never certified: UNKNOWN.
  Terminal non-success states (incl. provider auth) are False; quota waits,
  in-progress and unrecognized states are UNKNOWN.
* `safety_clean`: Runner's own `safety_verdict` (SAFE -> True).
* `scope_clean`: no unauthorized changed path; an empty list only counts
  when the change metadata and the attempt verdict were actually observed.
* `evidence_complete`: the Director's `evidence_complete`, verbatim -
  independent of worker state, safety, scope, preflight, auth/quota and
  checkpoint.
* `provenance_bound`: the run/pipeline/worker join above.
* `acceptance_proven`: the last attempt's Runner-owned acceptance decision
  PASSED, bound to `work_status_source=RUNNER_ACCEPTANCE`.

A recovery decision (FAILED/PARTIAL/BLOCKED/RECOVERY review) is recorded as
an observation code and never raises any fact. Output (`SingleRunObservation`,
schema `fcp8a02-single-worker-validation-observation-v1`) contains only
enumerated codes and booleans - no ids, paths, provider text or Work Order
text - and fixes every authority flag to False.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_validation_contract as vc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]

SCHEMA = "fcp8a02-single-worker-validation-observation-v1"
SCHEMA_VERSION = 1
OBSERVATION_MARKER = "FCP8A02_SINGLE_WORKER_OBSERVATION_NOT_CERTIFIED_NOT_AUTHORIZED"
UNRECOGNIZED = "UNRECOGNIZED"

_WS = fd.pipeline.WorkerState
WORKER_STATES = frozenset(s.value for s in _WS)
WORK_STATUSES = frozenset(s.value for s in fd.providers.WorkStatus)
WORK_STATUS_SOURCES = fd.claude_runner.WORK_STATUS_SOURCES
COMPLETION_MODES = frozenset({fd.claude_runner.COMPLETION_MODE_CHECKPOINT,
                              fd.claude_runner.COMPLETION_MODE_SUCCESS_NOOP})
PROVIDER_AUTH_BLOCKED_CONDITION = "PROVIDER_AUTH_BLOCKED"
PROVIDER_QUOTA_EXHAUSTED_CONDITION = "PROVIDER_QUOTA_EXHAUSTED"
PROVIDER_CONDITIONS = frozenset({PROVIDER_AUTH_BLOCKED_CONDITION, PROVIDER_QUOTA_EXHAUSTED_CONDITION})
CHECKPOINT_POLICY_ON_SUCCESS = "ON_SUCCESS"
ACCEPTANCE_PASSED = "PASSED"

# Every `fabric_director._classify_decision` code.
DECISION_CODES = frozenset({
    "SAFETY_REVIEW_REQUIRED", "EVIDENCE_REVIEW_REQUIRED", "PROVIDER_AUTH_REQUIRED", "WAITING_PROVIDER",
    "IN_PROGRESS", "RECOVERY_REVIEW_REQUIRED", "CHECKPOINT_REVIEW_REQUIRED", "READY_FOR_HOST_AUDIT",
    "PARTIAL_REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED", "FAILED_REVIEW_REQUIRED", "CANCELLED", "REVIEW_REQUIRED",
})
RECOVERY_DECISION_CODES = frozenset({
    "FAILED_REVIEW_REQUIRED", "PARTIAL_REVIEW_REQUIRED", "RECOVERY_REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED",
})
# The only decisions compatible with a Runner-certified work success: the
# work may be fine while safety or evidence still needs review.
_DECISIONS_ALLOWING_WORK_SUCCESS = frozenset({
    "READY_FOR_HOST_AUDIT", "SAFETY_REVIEW_REQUIRED", "EVIDENCE_REVIEW_REQUIRED",
})
_NOT_SUCCESS_TERMINAL_STATES = frozenset({
    _WS.FAILED.value, _WS.PARTIAL.value, _WS.BLOCKED.value, _WS.CANCELLED.value, _WS.INTERRUPTED.value,
    _WS.BLOCKED_PROVIDER_AUTH.value,
})
_IN_PROGRESS_STATES = frozenset({
    _WS.QUEUED.value, _WS.WAITING_DEPENDENCY.value, _WS.READY.value, _WS.RUNNING.value, _WS.RETRY_WAIT.value,
})

# Checkpoint / preflight observation values.
CHECKPOINT_RECORDED = "RECORDED"
CHECKPOINT_ABSENT = "ABSENT"
CHECKPOINT_UNKNOWN = "UNKNOWN"
CHECKPOINT_STATES = (CHECKPOINT_RECORDED, CHECKPOINT_ABSENT, CHECKPOINT_UNKNOWN)
PREFLIGHT_OBSERVED = "OBSERVED"
PREFLIGHT_ABSENT = "ABSENT"
PREFLIGHT_MALFORMED = "MALFORMED"
PREFLIGHT_UNKNOWN = "UNKNOWN"
PREFLIGHT_STATES = (PREFLIGHT_OBSERVED, PREFLIGHT_ABSENT, PREFLIGHT_MALFORMED, PREFLIGHT_UNKNOWN)

# Observation codes, in their fixed canonical order.
OBSERVATION_CODES = (
    "RUN_ID_INVALID",
    "MULTIWORKER_REFUSED",
    "RESULT_READ_FAILED", "EVIDENCE_READ_FAILED", "DECISION_READ_FAILED",
    "RESULT_NOT_TYPED", "EVIDENCE_NOT_TYPED", "DECISION_NOT_TYPED",
    "DECISION_CODE_UNRECOGNIZED",
    "IDENTITY_MALFORMED", "RUN_ID_MISMATCH", "PIPELINE_ID_MISMATCH", "WORKER_ID_MISMATCH",
    "PIPELINE_ID_MISSING", "WORKER_ID_MISSING",
    "FIELD_MALFORMED",
    "WORKER_STATE_MISMATCH", "WORK_STATUS_MISMATCH", "PROVIDER_WORK_STATUS_MISMATCH",
    "WORK_STATUS_SOURCE_MISMATCH", "EVIDENCE_COMPLETE_MISMATCH", "SAFETY_VERDICT_MISMATCH",
    "UNAUTHORIZED_PATHS_MISMATCH", "CHECKPOINT_MISMATCH", "PROVIDER_CONDITION_MISMATCH",
    "WORK_PRODUCT_MISMATCH",
    "DECISION_CONTRADICTS_SOURCES", "ACCEPTANCE_SOURCE_CONTRADICTION",
    "WORKER_STATE_UNKNOWN", "WORKER_NOT_TERMINAL", "WORKER_NOT_SUCCESSFUL",
    "PROVIDER_AUTH_BLOCKED", "PROVIDER_QUOTA_WAIT", "PROVIDER_CONDITION_CONFLICTS_SUCCESS",
    "WORK_STATUS_NOT_CERTIFIED_SUCCESS", "WORK_STATUS_SOURCE_MISSING", "WORK_STATUS_PROVIDER_ONLY",
    "WORK_STATUS_SOURCE_UNRECOGNIZED", "PROVIDER_WORK_STATUS_DIVERGES",
    "CHECKPOINT_MISSING",
    "SAFETY_VERDICT_ABSENT", "SAFETY_VERDICT_NOT_SAFE",
    "UNAUTHORIZED_PATHS_PRESENT", "SCOPE_UNOBSERVED",
    "EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_UNKNOWN",
    "ACCEPTANCE_ABSENT", "ACCEPTANCE_NOT_PASSED",
    "PREFLIGHT_MALFORMED",
    "RECOVERY_DECISION_NOT_ELEVATED",
)

_SOURCES = (
    ("result", fd.DirectorRunSummary, "RESULT_READ_FAILED", "RESULT_NOT_TYPED"),
    ("evidence", fd.DirectorRunEvidence, "EVIDENCE_READ_FAILED", "EVIDENCE_NOT_TYPED"),
    ("decision", fd.DirectorRunDecision, "DECISION_READ_FAILED", "DECISION_NOT_TYPED"),
)
_MULTIWORKER_REFUSAL = "MULTIWORKER_RUN_USE_RESULT_BLUEPRINT"


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=OBSERVATION_CODES.index))


def _enum(value, vocabulary) -> Optional[str]:
    if value is None:
        return None
    return value if type(value) is str and value in vocabulary else UNRECOGNIZED


def _is_opt_str(value) -> bool:
    return value is None or type(value) is str


def _is_opt_bool(value) -> bool:
    return value is None or type(value) is bool


def _is_opt_dict(value) -> bool:
    return value is None or type(value) is dict


def _is_paths(value) -> bool:
    return type(value) is tuple and all(type(p) is str for p in value)


def _is_id(value) -> bool:
    return type(value) is str and bool(value)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SingleRunObservation(vc._NotAuthorized):
    """Advisory observation of one single-worker run. `assessment` is always
    exactly `assess_validation(facts)`. Status fields hold an enumerated
    value, None (not projected) or UNRECOGNIZED - never free text."""
    facts: vc.ValidationFacts
    assessment: vc.ValidationAssessment
    observation_codes: tuple
    worker_state: Optional[str] = None
    work_status: Optional[str] = None
    provider_work_status: Optional[str] = None
    work_status_source: Optional[str] = None
    provider_condition: Optional[str] = None
    decision_code: Optional[str] = None
    completion_mode: Optional[str] = None
    checkpoint: str = CHECKPOINT_UNKNOWN
    preflight: str = PREFLIGHT_UNKNOWN

    def __post_init__(self):
        if type(self.facts) is not vc.ValidationFacts:
            raise ValueError("facts must be ValidationFacts")
        if type(self.assessment) is not vc.ValidationAssessment or self.assessment != vc.assess_validation(self.facts):
            raise ValueError("assessment must be exactly assess_validation(facts)")
        if not (type(self.observation_codes) is tuple
                and all(type(c) is str and c in OBSERVATION_CODES for c in self.observation_codes)
                and self.observation_codes == _ordered(self.observation_codes)):
            raise ValueError("observation_codes must be ordered observation codes")
        if self.checkpoint not in CHECKPOINT_STATES or self.preflight not in PREFLIGHT_STATES:
            raise ValueError("unknown checkpoint/preflight observation")

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
            "assessment": vc.ValidationAssessment.to_dict(self.assessment),
            "observation_codes": list(self.observation_codes),
            "statuses": {
                "worker_state": self.worker_state, "work_status": self.work_status,
                "provider_work_status": self.provider_work_status, "work_status_source": self.work_status_source,
                "provider_condition": self.provider_condition, "decision_code": self.decision_code,
                "completion_mode": self.completion_mode, "checkpoint": self.checkpoint, "preflight": self.preflight,
            },
            "marker": OBSERVATION_MARKER, "certified": False, "authorizes_action": False,
            "execution_allowed": False, "merging_allowed": False, "promotion_allowed": False,
            "auto_retry_allowed": False, "resume_allowed": False,
        }


def canonical_json(observation: SingleRunObservation) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(observation) is not SingleRunObservation:
        raise TypeError("canonical_json accepts only a SingleRunObservation")
    return json.dumps(SingleRunObservation.to_dict(observation), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _build(facts: vc.ValidationFacts, codes, **statuses) -> SingleRunObservation:
    return SingleRunObservation(facts=facts, assessment=vc.assess_validation(facts),
                                observation_codes=_ordered(codes), **statuses)


def _unknown(codes, provenance_bound: Optional[bool] = None) -> SingleRunObservation:
    return _build(vc.ValidationFacts(provenance_bound=provenance_bound), codes)


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def observe_single_run(service, run_id) -> SingleRunObservation:
    """Read `result`, `evidence` and `decision` for `run_id` once each and
    project them onto `ValidationFacts`. Never raises on bad input or a
    failing read; never writes, dispatches, certifies or authorizes."""
    if not _is_id(run_id):
        return _unknown(("RUN_ID_INVALID",))
    codes = []
    sources = []
    for method, expected_type, read_failed, not_typed in _SOURCES:
        try:
            value = getattr(service, method)(run_id)
        except fd.DirectorError as exc:
            codes.append("MULTIWORKER_REFUSED" if exc.code == _MULTIWORKER_REFUSAL else read_failed)
            value = None
        except Exception:  # noqa: BLE001 - any read failure is UNKNOWN, never success
            codes.append(read_failed)
            value = None
        else:
            if type(value) is not expected_type:
                codes.append(not_typed)
                value = None
        sources.append(value)
    if codes:
        return _unknown(codes)
    return _observe(run_id, *sources)


class _Join:
    """Collects observation codes while checking that the projections agree
    on one shared field."""

    def __init__(self):
        self.codes = []

    def agree(self, mismatch: str, check, *values) -> tuple:
        if not all(check(v) for v in values):
            self.codes.append("FIELD_MALFORMED")
            return False, None
        if any(v != values[0] for v in values[1:]):
            self.codes.append(mismatch)
            return False, None
        return True, values[0]


def _observe(run_id: str, summary, evidence, decision) -> SingleRunObservation:
    decision_code = decision.decision_code
    if type(decision_code) is not str or decision_code not in DECISION_CODES:
        return _unknown(("DECISION_CODE_UNRECOGNIZED",))

    # Identity join: run_id / pipeline_id / worker_id.
    identities = [(s.run_id, s.pipeline_id, s.worker_id) for s in (summary, evidence, decision)]
    if not all(_is_opt_str(v) for ident in identities for v in ident):
        return _unknown(("IDENTITY_MALFORMED",))
    contradictions = []
    missing = []
    for index, (mismatch, absent) in enumerate((
            ("RUN_ID_MISMATCH", "RUN_ID_INVALID"), ("PIPELINE_ID_MISMATCH", "PIPELINE_ID_MISSING"),
            ("WORKER_ID_MISMATCH", "WORKER_ID_MISSING"))):
        values = [ident[index] for ident in identities]
        if index == 0:
            values.append(run_id)
        present = [v for v in values if _is_id(v)]
        if len(set(present)) > 1:
            contradictions.append(mismatch)
        elif len(present) < len(values):
            missing.append(absent)
    if contradictions:
        return _unknown(contradictions + missing, provenance_bound=False)
    if missing:
        return _unknown(missing)

    join = _Join()
    codes = join.codes
    ws_ok, worker_state = join.agree("WORKER_STATE_MISMATCH", _is_opt_str,
                                     summary.worker_state, evidence.worker_state, decision.worker_state)
    st_ok, work_status = join.agree("WORK_STATUS_MISMATCH", _is_opt_str, summary.work_status, evidence.work_status)
    pws_ok, provider_work_status = join.agree("PROVIDER_WORK_STATUS_MISMATCH", _is_opt_str,
                                              summary.provider_work_status, evidence.provider_work_status)
    src_ok, source = join.agree("WORK_STATUS_SOURCE_MISMATCH", _is_opt_str,
                                summary.work_status_source, evidence.work_status_source)
    ec_ok, evidence_complete = join.agree("EVIDENCE_COMPLETE_MISMATCH", _is_opt_bool, summary.evidence_complete,
                                          evidence.evidence_complete, decision.evidence_complete)
    sv_ok, safety_verdict = join.agree("SAFETY_VERDICT_MISMATCH", _is_opt_str,
                                       evidence.safety_verdict, decision.safety_verdict)
    up_ok, unauthorized = join.agree("UNAUTHORIZED_PATHS_MISMATCH", _is_paths,
                                     summary.unauthorized_changed_paths, evidence.unauthorized_changed_paths)
    cc_ok, checkpoint_commit = join.agree("CHECKPOINT_MISMATCH", _is_opt_str, summary.checkpoint_commit,
                                          evidence.checkpoint_commit, decision.checkpoint_commit)
    cp_ok, checkpoint_policy = join.agree("CHECKPOINT_MISMATCH", _is_opt_str,
                                          evidence.checkpoint_policy, decision.checkpoint_policy)
    pc_ok, provider_condition = join.agree("PROVIDER_CONDITION_MISMATCH", _is_opt_str, summary.provider_condition,
                                           evidence.provider_condition, decision.provider_condition)
    wp_ok, work_product_present = join.agree("WORK_PRODUCT_MISMATCH", _is_opt_bool,
                                             summary.work_product_present, decision.work_product_present)
    acc_ok = _is_opt_dict(evidence.acceptance)
    acceptance = evidence.acceptance if acc_ok else None
    if not acc_ok:
        codes.append("FIELD_MALFORMED")

    # work_success
    work_success = None
    if worker_state == _WS.BLOCKED_PROVIDER_AUTH.value or provider_condition == PROVIDER_AUTH_BLOCKED_CONDITION:
        codes.append("PROVIDER_AUTH_BLOCKED")
    if worker_state == _WS.WAITING_PROVIDER_QUOTA.value or provider_condition == PROVIDER_QUOTA_EXHAUSTED_CONDITION:
        codes.append("PROVIDER_QUOTA_WAIT")
    if ws_ok and st_ok and pws_ok and src_ok and pc_ok and cc_ok and cp_ok:
        if worker_state in _NOT_SUCCESS_TERMINAL_STATES:
            work_success = False
            codes.append("WORKER_NOT_SUCCESSFUL")
        elif worker_state == _WS.WAITING_PROVIDER_QUOTA.value or worker_state in _IN_PROGRESS_STATES:
            codes.append("WORKER_NOT_TERMINAL")
        elif worker_state != _WS.SUCCESS.value:
            codes.append("WORKER_STATE_UNKNOWN")
        elif work_status != "SUCCESS":
            codes.append("WORK_STATUS_NOT_CERTIFIED_SUCCESS")
        elif source is None:
            codes.append("WORK_STATUS_SOURCE_MISSING")
        elif source == fd.claude_runner.WORK_STATUS_SOURCE_PROVIDER:
            codes.append("WORK_STATUS_PROVIDER_ONLY")
        elif source != fd.claude_runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE:
            codes.append("WORK_STATUS_SOURCE_UNRECOGNIZED")
        elif provider_condition is not None:
            codes.append("PROVIDER_CONDITION_CONFLICTS_SUCCESS")
        elif checkpoint_policy == CHECKPOINT_POLICY_ON_SUCCESS and not checkpoint_commit:
            codes.append("CHECKPOINT_MISSING")
        else:
            work_success = True
        if type(provider_work_status) is str and type(work_status) is str and provider_work_status != work_status:
            codes.append("PROVIDER_WORK_STATUS_DIVERGES")

    # safety_clean
    safety_clean = None
    if sv_ok:
        if safety_verdict is None:
            codes.append("SAFETY_VERDICT_ABSENT")
        elif safety_verdict == "SAFE":
            safety_clean = True
        else:
            safety_clean = False
            codes.append("SAFETY_VERDICT_NOT_SAFE")

    # scope_clean
    scope_clean = None
    if up_ok and wp_ok and sv_ok:
        if unauthorized:
            scope_clean = False
            codes.append("UNAUTHORIZED_PATHS_PRESENT")
        elif work_product_present is None or safety_verdict is None:
            codes.append("SCOPE_UNOBSERVED")
        else:
            scope_clean = True

    # evidence_complete - verbatim, reads nothing else.
    if not ec_ok:
        evidence_complete = None
    elif evidence_complete is None:
        codes.append("EVIDENCE_COMPLETE_UNKNOWN")
    elif evidence_complete is False:
        codes.append("EVIDENCE_INCOMPLETE")

    # acceptance_proven
    acceptance_proven = None
    runner_sourced = source == fd.claude_runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE
    if acc_ok and src_ok:
        accepted = (acceptance or {}).get("decision")
        if acceptance is None:
            codes.append("ACCEPTANCE_ABSENT")
            if runner_sourced:
                codes.append("ACCEPTANCE_SOURCE_CONTRADICTION")
                work_success = None
        elif type(accepted) is not str:
            codes.append("FIELD_MALFORMED")
            if runner_sourced:
                work_success = None
        elif accepted == ACCEPTANCE_PASSED:
            if runner_sourced:
                acceptance_proven = True
            else:
                codes.append("ACCEPTANCE_SOURCE_CONTRADICTION")
        else:
            codes.append("ACCEPTANCE_NOT_PASSED")
            if runner_sourced:
                codes.append("ACCEPTANCE_SOURCE_CONTRADICTION")
                work_success = None
            else:
                acceptance_proven = False
    elif runner_sourced:
        work_success = None

    # Decision cross-checks: a decision never raises a fact, and one that
    # contradicts a positive fact turns it UNKNOWN.
    if decision_code in RECOVERY_DECISION_CODES:
        codes.append("RECOVERY_DECISION_NOT_ELEVATED")
    if decision_code == "CHECKPOINT_REVIEW_REQUIRED" and work_success is True:
        codes.append("CHECKPOINT_MISSING")
        work_success = None
    if work_success is True and decision_code not in _DECISIONS_ALLOWING_WORK_SUCCESS:
        codes.append("DECISION_CONTRADICTS_SOURCES")
        work_success = None
    if decision_code == "READY_FOR_HOST_AUDIT" and (
            worker_state != _WS.SUCCESS.value or evidence_complete is not True
            or safety_clean is False or scope_clean is False):
        codes.append("DECISION_CONTRADICTS_SOURCES")
        work_success = None
    if decision_code == "SAFETY_REVIEW_REQUIRED" and safety_clean is True and scope_clean is True:
        codes.append("DECISION_CONTRADICTS_SOURCES")
        safety_clean = scope_clean = None
    if decision_code == "EVIDENCE_REVIEW_REQUIRED" and evidence_complete is True:
        codes.append("DECISION_CONTRADICTS_SOURCES")
        evidence_complete = None

    preflight = evidence.preflight
    if preflight is None:
        preflight_state = PREFLIGHT_ABSENT
    elif type(preflight) is dict:
        preflight_state = PREFLIGHT_OBSERVED
    else:
        preflight_state = PREFLIGHT_MALFORMED
        codes.append("PREFLIGHT_MALFORMED")

    if not (cc_ok and cp_ok):
        checkpoint = CHECKPOINT_UNKNOWN
    else:
        checkpoint = CHECKPOINT_RECORDED if checkpoint_commit else CHECKPOINT_ABSENT

    facts = vc.ValidationFacts(
        work_success=work_success, safety_clean=safety_clean, scope_clean=scope_clean,
        evidence_complete=evidence_complete, provenance_bound=True, acceptance_proven=acceptance_proven,
    )
    return _build(
        facts, codes,
        worker_state=_enum(worker_state, WORKER_STATES), work_status=_enum(work_status, WORK_STATUSES),
        provider_work_status=_enum(provider_work_status, WORK_STATUSES),
        work_status_source=_enum(source, WORK_STATUS_SOURCES),
        provider_condition=_enum(provider_condition, PROVIDER_CONDITIONS), decision_code=decision_code,
        completion_mode=_enum(summary.completion_mode, COMPLETION_MODES), checkpoint=checkpoint,
        preflight=preflight_state,
    )

"""FCP-8B-02: evidence sufficiency rules - a pure, deterministic, fail-closed,
NON-AUTHORITATIVE classification of the FCP-8 validation observations.

Inputs (exclusively; anything else is INVALID_INPUT)
----------------------------------------------------
* `ValidationAssessment` (FCP-8A-01) - one unit.
* `SingleRunObservation` (FCP-8A-02) - one unit: its `assessment`.
* `DagRunObservation` (FCP-8B-01) - one unit per worker: each worker's
  `assessment`, plus the DAG-level classification and observation codes.

The rules never re-read Director/Runner projections and never re-derive a
fact: per-unit dimension states and reasons are the contract's own
consultative result (`assess_validation`), reused verbatim. An input whose
`assessment` is not exactly `assess_validation(facts)` (or an assessment
that no longer satisfies its own construction guard) is INPUT_INCONSISTENT
and contributes no unit. Safety, auth/quota availability, acceptance and
permissions remain Runner's sole authority.

Rules
-----
1. Every non-TRUE unit state already carries a contract reason. Reasons for
   a FALSE state and the contract's inconsistency reasons are NEGATIVE;
   reasons for an UNKNOWN or MALFORMED state are UNKNOWN (`NEGATIVE_CODES`
   / `UNKNOWN_CODES` partition `CODES`).
2. A negative is preserved: it is never dropped because other evidence is
   missing, and it always yields HUMAN_REVIEW_REQUIRED.
3. Any UNKNOWN (in provenance, scope, acceptance or evidence - and equally in
   work or safety) yields UNPROVEN and blocks VALIDATION_COMPLETE.
   UNKNOWN is never TRUE.
4. `work_success=True` never implies `evidence_complete=True` (and vice
   versa): WORK_SUCCESS reads only the `work_success` state of every unit
   (plus DAG-level work blockers), EVIDENCE_COMPLETE reads only the
   `evidence_complete` state of every unit.
5. VALIDATION_COMPLETE holds exactly when there is at least one unit and no
   NEGATIVE and no UNKNOWN code, i.e. every dimension of every unit is TRUE.
   Because the DAG projection carries neither safety nor acceptance, a DAG
   observation is never VALIDATION_COMPLETE.
6. Observation-level signals only ever add codes, never remove one: A-02
   identity/field contradictions are NEGATIVE (OBSERVATION_CONTRADICTION);
   A-02 unreadable/refused/malformed observations are UNKNOWN; B-01
   NOT_SUCCESSFUL, stale/mismatched provenance and aggregate/worker
   inconsistencies are NEGATIVE; UNOBSERVABLE, INVALID_PROJECTION,
   UNKNOWN_STATUS, NOT_TERMINAL and any classification short of
   ALL_WORKERS_PROVEN are UNKNOWN. Provider-reported work status is never
   read.

Outcomes (`OUTCOMES`) are separate booleans: WORK_SUCCESS, EVIDENCE_COMPLETE,
VALIDATION_COMPLETE, HUMAN_REVIEW_REQUIRED and UNPROVEN; HUMAN_REVIEW_REQUIRED
and UNPROVEN may both hold. `verdict` is the worst of them
(HUMAN_REVIEW_REQUIRED > UNPROVEN > VALIDATION_COMPLETE). None of them is a
permit: no classification authorizes merge, push, promotion, resume, retry,
fallback, provider switch or execution, and no next action is ever produced.
`DirectorRunDecision`, Runner and the FCP-3 gate are not replaced.

Output (`EvidenceClassification`, schema `fcp8b02-evidence-sufficiency-v1`)
holds only enumerated codes, states, booleans and counts. Stdlib plus the
FCP-8 contract/adapters only; no I/O, process, Git, network or environment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields

try:
    from scripts.ai import fabric_validation_contract as vc
    from scripts.ai import fabric_validation_dag as vd
    from scripts.ai import fabric_validation_single as vs
except ImportError:  # pragma: no cover - direct script execution
    import fabric_validation_contract as vc  # type: ignore[no-redef]
    import fabric_validation_dag as vd  # type: ignore[no-redef]
    import fabric_validation_single as vs  # type: ignore[no-redef]

SCHEMA = "fcp8b02-evidence-sufficiency-v1"
SCHEMA_VERSION = 1
RULES_MARKER = "FCP8B02_EVIDENCE_SUFFICIENCY_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Input sources.
SOURCE_ASSESSMENT = "ASSESSMENT"
SOURCE_SINGLE_RUN = "SINGLE_RUN"
SOURCE_DAG_RUN = "DAG_RUN"
SOURCE_INVALID = "INVALID_INPUT"
SOURCES = (SOURCE_ASSESSMENT, SOURCE_SINGLE_RUN, SOURCE_DAG_RUN, SOURCE_INVALID)

# Outcomes, in their fixed canonical order.
WORK_SUCCESS = "WORK_SUCCESS"
EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
VALIDATION_COMPLETE = "VALIDATION_COMPLETE"
HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
UNPROVEN = "UNPROVEN"
OUTCOMES = (WORK_SUCCESS, EVIDENCE_COMPLETE, VALIDATION_COMPLETE, HUMAN_REVIEW_REQUIRED, UNPROVEN)
VERDICTS = (VALIDATION_COMPLETE, HUMAN_REVIEW_REQUIRED, UNPROVEN)

# Rule codes beyond the contract's own reasons.
INPUT_NOT_TYPED = "INPUT_NOT_TYPED"
INPUT_INCONSISTENT = "INPUT_INCONSISTENT"
NO_UNITS = "NO_UNITS"
OBSERVATION_UNOBSERVABLE = "OBSERVATION_UNOBSERVABLE"
OBSERVATION_MALFORMED = "OBSERVATION_MALFORMED"
OBSERVATION_CONTRADICTION = "OBSERVATION_CONTRADICTION"
DAG_UNOBSERVABLE = "DAG_UNOBSERVABLE"
DAG_INVALID_PROJECTION = "DAG_INVALID_PROJECTION"
DAG_PROVENANCE_MISMATCH = "DAG_PROVENANCE_MISMATCH"
DAG_STATUS_UNKNOWN = "DAG_STATUS_UNKNOWN"
DAG_NOT_TERMINAL = "DAG_NOT_TERMINAL"
DAG_NOT_SUCCESSFUL = "DAG_NOT_SUCCESSFUL"
DAG_EVIDENCE_INSUFFICIENT = "DAG_EVIDENCE_INSUFFICIENT"
DAG_AGGREGATE_INCONSISTENT = "DAG_AGGREGATE_INCONSISTENT"
DAG_WORKER_INCONSISTENT = "DAG_WORKER_INCONSISTENT"

# Contract reasons split by the state they explain (rule 1).
NEGATIVE_REASONS = (
    vc.WORK_NOT_SUCCESSFUL, vc.SAFETY_NOT_CLEAN, vc.SCOPE_NOT_CLEAN, vc.EVIDENCE_INCOMPLETE,
    vc.PROVENANCE_NOT_BOUND, vc.ACCEPTANCE_NOT_PROVEN,
) + vc.INCONSISTENCY_REASONS
UNKNOWN_REASONS = tuple(r for r in vc.REASONS if r not in NEGATIVE_REASONS)

RULE_CODES = (
    INPUT_NOT_TYPED, INPUT_INCONSISTENT, NO_UNITS,
    OBSERVATION_UNOBSERVABLE, OBSERVATION_MALFORMED, OBSERVATION_CONTRADICTION,
    DAG_UNOBSERVABLE, DAG_INVALID_PROJECTION, DAG_PROVENANCE_MISMATCH, DAG_STATUS_UNKNOWN, DAG_NOT_TERMINAL,
    DAG_NOT_SUCCESSFUL, DAG_EVIDENCE_INSUFFICIENT, DAG_AGGREGATE_INCONSISTENT, DAG_WORKER_INCONSISTENT,
)
CODES = vc.REASONS + RULE_CODES
NEGATIVE_CODES = NEGATIVE_REASONS + (
    OBSERVATION_CONTRADICTION, DAG_PROVENANCE_MISMATCH, DAG_NOT_SUCCESSFUL, DAG_AGGREGATE_INCONSISTENT,
    DAG_WORKER_INCONSISTENT,
)
UNKNOWN_CODES = tuple(c for c in CODES if c not in NEGATIVE_CODES)
# Observation-level codes that also deny WORK_SUCCESS (rule 4).
WORK_BLOCKING_CODES = (DAG_NOT_SUCCESSFUL, DAG_STATUS_UNKNOWN, DAG_NOT_TERMINAL)

# FCP-8A-02 observation code -> rule code (rule 6). Provider-reported status
# divergence is deliberately absent: provider output is never a negative.
_SINGLE_CODE_RULES = {
    **{code: OBSERVATION_UNOBSERVABLE for code in (
        "RUN_ID_INVALID", "MULTIWORKER_REFUSED", "RESULT_READ_FAILED", "EVIDENCE_READ_FAILED",
        "DECISION_READ_FAILED", "RESULT_NOT_TYPED", "EVIDENCE_NOT_TYPED", "DECISION_NOT_TYPED",
        "DECISION_CODE_UNRECOGNIZED", "IDENTITY_MALFORMED", "PIPELINE_ID_MISSING", "WORKER_ID_MISSING")},
    **{code: OBSERVATION_MALFORMED for code in ("FIELD_MALFORMED", "PREFLIGHT_MALFORMED")},
    **{code: OBSERVATION_CONTRADICTION for code in (
        "RUN_ID_MISMATCH", "PIPELINE_ID_MISMATCH", "WORKER_ID_MISMATCH", "WORKER_STATE_MISMATCH",
        "WORK_STATUS_MISMATCH", "PROVIDER_WORK_STATUS_MISMATCH", "WORK_STATUS_SOURCE_MISMATCH",
        "EVIDENCE_COMPLETE_MISMATCH", "SAFETY_VERDICT_MISMATCH", "UNAUTHORIZED_PATHS_MISMATCH",
        "CHECKPOINT_MISMATCH", "PROVIDER_CONDITION_MISMATCH", "WORK_PRODUCT_MISMATCH",
        "DECISION_CONTRADICTS_SOURCES", "ACCEPTANCE_SOURCE_CONTRADICTION")},
}
# FCP-8B-01 DAG classification -> rule code (rule 6).
_DAG_CLASSIFICATION_RULES = {
    vd.UNOBSERVABLE: DAG_UNOBSERVABLE,
    vd.INVALID_PROJECTION: DAG_INVALID_PROJECTION,
    vd.UNKNOWN_STATUS: DAG_STATUS_UNKNOWN,
    vd.NOT_SUCCESSFUL: DAG_NOT_SUCCESSFUL,
    vd.NOT_TERMINAL: DAG_NOT_TERMINAL,
    vd.SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT: DAG_EVIDENCE_INSUFFICIENT,
    vd.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT: DAG_EVIDENCE_INSUFFICIENT,
}
# FCP-8B-01 DAG observation code -> rule code (rule 6).
_DAG_CODE_RULES = {
    "RUN_ID_MISMATCH": DAG_PROVENANCE_MISMATCH,
    "PIPELINE_ID_MISMATCH": DAG_PROVENANCE_MISMATCH,
    "STALE_PROVENANCE": DAG_PROVENANCE_MISMATCH,
    "PROVENANCE_REFUSED": DAG_PROVENANCE_MISMATCH,
    "AGGREGATE_SUCCESS_WITH_UNPROVEN_WORKER": DAG_AGGREGATE_INCONSISTENT,
    "AGGREGATE_UNVERIFIED_WITH_ALL_PROVEN": DAG_AGGREGATE_INCONSISTENT,
    "AGGREGATE_REASONS_MISMATCH": DAG_AGGREGATE_INCONSISTENT,
    "WORKER_INCONSISTENT": DAG_WORKER_INCONSISTENT,
}


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


def _is_unit(states) -> bool:
    return (type(states) is tuple and len(states) == len(vc.DIMENSIONS)
            and all(type(s) is str and s in vc.STATES for s in states))


def _state(states: tuple, dimension: str) -> str:
    return states[vc.DIMENSIONS.index(dimension)]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _NotAuthorized(vc._NotAuthorized):
    """The contract's zero-authority guarantees plus push, fallback and
    provider switch - all fixed, read-only and never fields."""

    @property
    def push_allowed(self) -> bool:
        return False

    @property
    def fallback_allowed(self) -> bool:
        return False

    @property
    def provider_switch_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        return {
            **vc._NotAuthorized._guarantees(), "marker": RULES_MARKER, "push_allowed": False,
            "fallback_allowed": False, "provider_switch_allowed": False,
        }


def _derive(unit_states: tuple, codes: tuple) -> dict:
    """Every outcome from units and codes. The single derivation both
    `classify_evidence` and the construction guard use."""
    negative = any(c in NEGATIVE_CODES for c in codes)
    unknown = any(c in UNKNOWN_CODES for c in codes)
    complete = bool(unit_states) and not negative and not unknown
    if negative:
        verdict = HUMAN_REVIEW_REQUIRED
    elif unknown:
        verdict = UNPROVEN
    else:
        verdict = VALIDATION_COMPLETE
    return {
        "verdict": verdict,
        "work_success": bool(unit_states) and all(_state(u, vc.WORK_SUCCESS) == vc.STATE_TRUE for u in unit_states)
        and not any(c in WORK_BLOCKING_CODES for c in codes),
        "evidence_complete": bool(unit_states)
        and all(_state(u, vc.EVIDENCE_COMPLETE) == vc.STATE_TRUE for u in unit_states),
        "validation_complete": complete, "human_review_required": negative, "unproven": unknown,
    }


@dataclass(frozen=True)
class EvidenceClassification(_NotAuthorized):
    """Advisory evidence sufficiency result. `unit_states` holds one contract
    STATES tuple per unit (DIMENSIONS order; DAG workers in plan order).
    Construction re-derives every outcome, so a hand-made classification
    cannot claim more than its units and codes prove."""
    source: str
    verdict: str
    work_success: bool
    evidence_complete: bool
    validation_complete: bool
    human_review_required: bool
    unproven: bool
    unit_states: tuple
    codes: tuple

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError("unknown evidence source")
        if not (type(self.unit_states) is tuple and len(self.unit_states) <= vd.MAX_WORKERS
                and all(_is_unit(u) for u in self.unit_states)):
            raise ValueError("unit_states must be contract state tuples")
        if not (type(self.codes) is tuple and all(type(c) is str and c in CODES for c in self.codes)
                and self.codes == _ordered(self.codes, CODES)):
            raise ValueError("codes must be ordered rule codes")
        if not self.unit_states and NO_UNITS not in self.codes:
            raise ValueError("a classification without units must carry NO_UNITS")
        states = {s for u in self.unit_states for s in u}
        if vc.STATE_FALSE in states and not any(c in NEGATIVE_CODES for c in self.codes):
            raise ValueError("a FALSE unit state must be preserved as a negative")
        if states & {vc.STATE_UNKNOWN, vc.STATE_MALFORMED} and not any(c in UNKNOWN_CODES for c in self.codes):
            raise ValueError("an UNKNOWN unit state must be preserved as unknown")
        for name in ("work_success", "evidence_complete", "validation_complete", "human_review_required",
                     "unproven"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a bool")
        actual = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("source", "unit_states",
                                                                                       "codes")}
        if actual != _derive(self.unit_states, self.codes):
            raise ValueError("outcomes must be exactly those derived from units and codes")

    @property
    def outcomes(self) -> tuple:
        flags = (self.work_success, self.evidence_complete, self.validation_complete, self.human_review_required,
                 self.unproven)
        return tuple(o for o, flag in zip(OUTCOMES, flags) if flag)

    @property
    def unit_count(self) -> int:
        return len(self.unit_states)

    @property
    def negative_codes(self) -> tuple:
        return tuple(c for c in self.codes if c in NEGATIVE_CODES)

    @property
    def unknown_codes(self) -> tuple:
        return tuple(c for c in self.codes if c in UNKNOWN_CODES)

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "source": self.source, "verdict": self.verdict,
            "outcomes": {
                WORK_SUCCESS: self.work_success, EVIDENCE_COMPLETE: self.evidence_complete,
                VALIDATION_COMPLETE: self.validation_complete, HUMAN_REVIEW_REQUIRED: self.human_review_required,
                UNPROVEN: self.unproven,
            },
            "unit_count": self.unit_count,
            "units": [{d: s for d, s in zip(vc.DIMENSIONS, u)} for u in self.unit_states],
            "codes": list(self.codes), "negative_codes": list(self.negative_codes),
            "unknown_codes": list(self.unknown_codes), **_NotAuthorized._guarantees(),
        }


def canonical_json(classification: EvidenceClassification) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(classification) is not EvidenceClassification:
        raise TypeError("canonical_json accepts only an EvidenceClassification")
    return json.dumps(EvidenceClassification.to_dict(classification), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _trusted_assessment(assessment) -> bool:
    """The assessment still satisfies the contract's own construction guard
    (catches post-construction tampering)."""
    if type(assessment) is not vc.ValidationAssessment:
        return False
    try:
        rebuilt = vc.ValidationAssessment(**{f.name: getattr(assessment, f.name)
                                            for f in fields(vc.ValidationAssessment)})
    except (TypeError, ValueError):
        return False
    return rebuilt == assessment


def _bound_assessment(facts, assessment) -> bool:
    """`assessment` is exactly the contract's `assess_validation(facts)`."""
    return (type(facts) is vc.ValidationFacts and _trusted_assessment(assessment)
            and assessment == vc.assess_validation(facts))


def _units_and_codes(observation) -> tuple:
    if type(observation) is vc.ValidationAssessment:
        if not _trusted_assessment(observation):
            return SOURCE_ASSESSMENT, (), [INPUT_INCONSISTENT]
        return SOURCE_ASSESSMENT, (observation,), []

    if type(observation) is vs.SingleRunObservation:
        codes = observation.observation_codes
        if not (_bound_assessment(observation.facts, observation.assessment) and type(codes) is tuple
                and all(type(c) is str for c in codes)):
            return SOURCE_SINGLE_RUN, (), [INPUT_INCONSISTENT]
        rules = [_SINGLE_CODE_RULES[c] for c in codes if c in _SINGLE_CODE_RULES]
        if any(c not in vs.OBSERVATION_CODES for c in codes):
            rules.append(INPUT_INCONSISTENT)
        return SOURCE_SINGLE_RUN, (observation.assessment,), rules

    if type(observation) is vd.DagRunObservation:
        workers, codes = observation.workers, observation.observation_codes
        if not (type(workers) is tuple and len(workers) <= vd.MAX_WORKERS
                and all(type(w) is vd.DagWorkerObservation and _bound_assessment(w.facts, w.assessment)
                        for w in workers)
                and type(codes) is tuple and all(type(c) is str for c in codes)
                and observation.classification in vd.DAG_CLASSIFICATIONS):
            return SOURCE_DAG_RUN, (), [INPUT_INCONSISTENT]
        rules = [_DAG_CODE_RULES[c] for c in codes if c in _DAG_CODE_RULES]
        if any(c not in vd.DAG_CODES for c in codes):
            rules.append(INPUT_INCONSISTENT)
        if observation.classification in _DAG_CLASSIFICATION_RULES:
            rules.append(_DAG_CLASSIFICATION_RULES[observation.classification])
        if (observation.classification == vd.ALL_WORKERS_PROVEN) != (observation.evidence_sufficient is True):
            rules.append(INPUT_INCONSISTENT)
        return SOURCE_DAG_RUN, tuple(w.assessment for w in workers), rules

    return SOURCE_INVALID, (), [INPUT_NOT_TYPED]


def classify_evidence(observation) -> EvidenceClassification:
    """Pure, deterministic evidence sufficiency classification of one FCP-8
    observation. Never raises on bad input, never reads anything beyond the
    given value, and never certifies, authorizes or triggers any action."""
    source, assessments, codes = _units_and_codes(observation)
    for assessment in assessments:
        codes.extend(assessment.reasons)
    if not assessments:
        codes.append(NO_UNITS)
    unit_states = tuple(a.states for a in assessments)
    codes = _ordered(codes, CODES)
    return EvidenceClassification(source=source, unit_states=unit_states, codes=codes,
                                  **_derive(unit_states, codes))

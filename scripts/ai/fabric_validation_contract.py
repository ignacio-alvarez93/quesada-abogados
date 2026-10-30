"""FCP-8A-01: Validation & Evidence contract V1 - pure, deterministic,
fail-closed, NON-AUTHORITATIVE assessment that keeps "the work succeeded"
and "the evidence is complete" as two independent questions.

Why two questions
-----------------
The Director projections (`DirectorRunSummary`, `DirectorRunEvidence`,
`DirectorRunDecision`, `DirectorDagWorkerSummary`) already carry a
`work_status`/`worker_state` and, separately, an `evidence_complete:
Optional[bool]`. A SUCCESS work status says nothing about whether the
attempt's evidence was fully written, and complete evidence says nothing
about whether the work succeeded. This module never infers one from the
other: each is its own caller-supplied fact, and each advisory outcome reads
only the facts it is documented to read.

Input (`ValidationFacts`, frozen; validated by `assess_validation`, never
by the constructor, so every malformed input yields an explained result)
--------------------------------------------------------------------------
Six tri-state dimensions, each exactly `True`, `False` or `None` (UNKNOWN):

* `work_success`: the worker's effective work status is Runner-certified
  SUCCESS.
* `safety_clean`: Runner's own write-mode safety verdict is SAFE.
* `scope_clean`: no changed path fell outside the authorized write scope.
* `evidence_complete`: the attempt's own evidence artifacts were fully
  written (the Director's `evidence_complete`, verbatim).
* `provenance_bound`: the evidence is bound to the run/worker/attempt it
  claims to describe (e.g. the worker record is PRESENT, not MISMATCH).
* `acceptance_proven`: Runner-owned acceptance commands PASSED.

Anything that is not a real `bool` or `None` (`1`, `"True"`, ...) is
MALFORMED and treated as UNKNOWN. UNKNOWN is never True.

Advisory outcomes (consultative classification, never a permit)
---------------------------------------------------------------
* `technical_success` = work_success, safety_clean and scope_clean are all
  True. Never reads an evidence dimension.
* `evidence_sufficient` = evidence_complete, provenance_bound and
  acceptance_proven are all True. Never reads a work dimension.
* `ready_for_human_review` = both of the above, with no inconsistency.

Inconsistencies (fail closed: all three outcomes forced False)
--------------------------------------------------------------
* `scope_clean=False` with `safety_clean=True`: Runner's write-mode safety
  verdict always fails on unauthorized paths (`evaluate_write_mode_safety`).
* `acceptance_proven=True` with `work_success=False`: a PASSED Runner-owned
  acceptance certifies the effective work status as SUCCESS.

Output (`ValidationAssessment`, schema `fcp8a01-validation-assessment-v1`,
version 1). `to_dict()` / `canonical_json()` are deterministic and contain
only enumerated codes and booleans - no paths, ids, emails, secrets,
provider text or Work Order text can reach them, because no such value is
ever an input. Every assessment fixes `certified`, `authorizes_action`,
`execution_allowed`, `merging_allowed`, `promotion_allowed`,
`auto_retry_allowed` and `resume_allowed` to False as read-only properties
(not dataclass fields: no constructor, `dataclasses.replace` or serialized
input can set them), and serialization always emits the module constants.

Stdlib only; no I/O, process, Git, network, environment or provider/Runner
import. Safety, auth/quota, execution, acceptance and permissions remain
Runner's sole authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from typing import Optional

SCHEMA = "fcp8a01-validation-assessment-v1"
SCHEMA_VERSION = 1
VALIDATION_MARKER = "FCP8A01_VALIDATION_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Dimension names, in their fixed canonical order.
WORK_SUCCESS = "work_success"
SAFETY_CLEAN = "safety_clean"
SCOPE_CLEAN = "scope_clean"
EVIDENCE_COMPLETE = "evidence_complete"
PROVENANCE_BOUND = "provenance_bound"
ACCEPTANCE_PROVEN = "acceptance_proven"
WORK_DIMENSIONS = (WORK_SUCCESS, SAFETY_CLEAN, SCOPE_CLEAN)
EVIDENCE_DIMENSIONS = (EVIDENCE_COMPLETE, PROVENANCE_BOUND, ACCEPTANCE_PROVEN)
DIMENSIONS = WORK_DIMENSIONS + EVIDENCE_DIMENSIONS

# Tri-state values as serialized.
STATE_TRUE = "TRUE"
STATE_FALSE = "FALSE"
STATE_UNKNOWN = "UNKNOWN"
STATE_MALFORMED = "MALFORMED"
STATES = (STATE_TRUE, STATE_FALSE, STATE_UNKNOWN, STATE_MALFORMED)

# Reason codes, in their fixed canonical order.
FACTS_NOT_TYPED = "FACTS_NOT_TYPED"
WORK_NOT_SUCCESSFUL = "WORK_NOT_SUCCESSFUL"
WORK_SUCCESS_UNKNOWN = "WORK_SUCCESS_UNKNOWN"
WORK_SUCCESS_MALFORMED = "WORK_SUCCESS_MALFORMED"
SAFETY_NOT_CLEAN = "SAFETY_NOT_CLEAN"
SAFETY_UNKNOWN = "SAFETY_UNKNOWN"
SAFETY_MALFORMED = "SAFETY_MALFORMED"
SCOPE_NOT_CLEAN = "SCOPE_NOT_CLEAN"
SCOPE_UNKNOWN = "SCOPE_UNKNOWN"
SCOPE_MALFORMED = "SCOPE_MALFORMED"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
EVIDENCE_UNKNOWN = "EVIDENCE_UNKNOWN"
EVIDENCE_MALFORMED = "EVIDENCE_MALFORMED"
PROVENANCE_NOT_BOUND = "PROVENANCE_NOT_BOUND"
PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"
PROVENANCE_MALFORMED = "PROVENANCE_MALFORMED"
ACCEPTANCE_NOT_PROVEN = "ACCEPTANCE_NOT_PROVEN"
ACCEPTANCE_UNKNOWN = "ACCEPTANCE_UNKNOWN"
ACCEPTANCE_MALFORMED = "ACCEPTANCE_MALFORMED"
INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY = "INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY"
INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS = "INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS"
INCONSISTENCY_REASONS = (INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY, INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS)
REASONS = (
    FACTS_NOT_TYPED,
    WORK_NOT_SUCCESSFUL, WORK_SUCCESS_UNKNOWN, WORK_SUCCESS_MALFORMED,
    SAFETY_NOT_CLEAN, SAFETY_UNKNOWN, SAFETY_MALFORMED,
    SCOPE_NOT_CLEAN, SCOPE_UNKNOWN, SCOPE_MALFORMED,
    EVIDENCE_INCOMPLETE, EVIDENCE_UNKNOWN, EVIDENCE_MALFORMED,
    PROVENANCE_NOT_BOUND, PROVENANCE_UNKNOWN, PROVENANCE_MALFORMED,
    ACCEPTANCE_NOT_PROVEN, ACCEPTANCE_UNKNOWN, ACCEPTANCE_MALFORMED,
) + INCONSISTENCY_REASONS

# dimension -> {state: reason}; TRUE contributes no reason.
_DIMENSION_REASON = {
    WORK_SUCCESS: {STATE_FALSE: WORK_NOT_SUCCESSFUL, STATE_UNKNOWN: WORK_SUCCESS_UNKNOWN,
                   STATE_MALFORMED: WORK_SUCCESS_MALFORMED},
    SAFETY_CLEAN: {STATE_FALSE: SAFETY_NOT_CLEAN, STATE_UNKNOWN: SAFETY_UNKNOWN, STATE_MALFORMED: SAFETY_MALFORMED},
    SCOPE_CLEAN: {STATE_FALSE: SCOPE_NOT_CLEAN, STATE_UNKNOWN: SCOPE_UNKNOWN, STATE_MALFORMED: SCOPE_MALFORMED},
    EVIDENCE_COMPLETE: {STATE_FALSE: EVIDENCE_INCOMPLETE, STATE_UNKNOWN: EVIDENCE_UNKNOWN,
                        STATE_MALFORMED: EVIDENCE_MALFORMED},
    PROVENANCE_BOUND: {STATE_FALSE: PROVENANCE_NOT_BOUND, STATE_UNKNOWN: PROVENANCE_UNKNOWN,
                       STATE_MALFORMED: PROVENANCE_MALFORMED},
    ACCEPTANCE_PROVEN: {STATE_FALSE: ACCEPTANCE_NOT_PROVEN, STATE_UNKNOWN: ACCEPTANCE_UNKNOWN,
                        STATE_MALFORMED: ACCEPTANCE_MALFORMED},
}

# Classification enum.
READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT = "TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT"
EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS = "EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS"
NOT_READY = "NOT_READY"
INCONSISTENT_FACTS = "INCONSISTENT_FACTS"
INVALID_FACTS = "INVALID_FACTS"
CLASSIFICATIONS = (
    READY_FOR_HUMAN_REVIEW, TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT, EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS,
    NOT_READY, INCONSISTENT_FACTS, INVALID_FACTS,
)


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


def _state(value) -> str:
    # `type(...) is bool` on purpose: 1, 0, "True" and bool subclasses are
    # MALFORMED, never coerced.
    if value is None:
        return STATE_UNKNOWN
    if type(value) is bool:
        return STATE_TRUE if value else STATE_FALSE
    return STATE_MALFORMED


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationFacts:
    """Caller-supplied tri-state facts for one worker attempt. Validated by
    `assess_validation` (fail closed), not here. None means UNKNOWN."""
    work_success: Optional[bool] = None
    safety_clean: Optional[bool] = None
    scope_clean: Optional[bool] = None
    evidence_complete: Optional[bool] = None
    provenance_bound: Optional[bool] = None
    acceptance_proven: Optional[bool] = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _NotAuthorized:
    """Fixed, read-only zero-authority guarantees (not dataclass fields, so no
    constructor, `dataclasses.replace` or serialization input can set them)."""

    @property
    def certified(self) -> bool:
        return False

    @property
    def authorizes_action(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def merging_allowed(self) -> bool:
        return False

    @property
    def promotion_allowed(self) -> bool:
        return False

    @property
    def auto_retry_allowed(self) -> bool:
        return False

    @property
    def resume_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        return {
            "marker": VALIDATION_MARKER, "certified": False, "authorizes_action": False, "execution_allowed": False,
            "merging_allowed": False, "promotion_allowed": False, "auto_retry_allowed": False,
            "resume_allowed": False,
        }


def _derive(states: tuple, inconsistencies: tuple) -> tuple:
    """(technical_success, evidence_sufficient, ready, classification) from
    validated per-dimension states. The single derivation both
    `assess_validation` and the construction guard use."""
    by_name = dict(zip(DIMENSIONS, states))
    technical = all(by_name[d] == STATE_TRUE for d in WORK_DIMENSIONS)
    evidence = all(by_name[d] == STATE_TRUE for d in EVIDENCE_DIMENSIONS)
    if inconsistencies:
        return False, False, False, INCONSISTENT_FACTS
    if technical and evidence:
        return True, True, True, READY_FOR_HUMAN_REVIEW
    if technical:
        return True, False, False, TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT
    if evidence:
        return False, True, False, EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS
    return False, False, False, NOT_READY


def _inconsistencies(states: tuple) -> tuple:
    by_name = dict(zip(DIMENSIONS, states))
    found = []
    if by_name[SCOPE_CLEAN] == STATE_FALSE and by_name[SAFETY_CLEAN] == STATE_TRUE:
        found.append(INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY)
    if by_name[ACCEPTANCE_PROVEN] == STATE_TRUE and by_name[WORK_SUCCESS] == STATE_FALSE:
        found.append(INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS)
    return tuple(found)


def _reasons_for(states: tuple) -> tuple:
    reasons = [_DIMENSION_REASON[d][s] for d, s in zip(DIMENSIONS, states) if s != STATE_TRUE]
    return _ordered(reasons + list(_inconsistencies(states)), REASONS)


@dataclass(frozen=True)
class ValidationAssessment(_NotAuthorized):
    """Explainable, advisory validation result. `states` holds one STATES
    value per DIMENSIONS entry, in that order. Construction re-derives every
    outcome from `states`, so a hand-made assessment cannot claim more than
    its own states prove."""
    classification: str
    technical_success: bool
    evidence_sufficient: bool
    ready_for_human_review: bool
    states: tuple
    reasons: tuple

    def __post_init__(self):
        if self.classification not in CLASSIFICATIONS:
            raise ValueError("unknown validation classification")
        for name in ("technical_success", "evidence_sufficient", "ready_for_human_review"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a bool")
        if not (type(self.states) is tuple and len(self.states) == len(DIMENSIONS)
                and all(type(s) is str and s in STATES for s in self.states)):
            raise ValueError("states must be one STATES value per dimension")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, REASONS)):
            raise ValueError("reasons must be ordered validation reason codes")
        if self.classification == INVALID_FACTS:
            expected = (False, False, False, INVALID_FACTS)
            if self.states != (STATE_UNKNOWN,) * len(DIMENSIONS) or self.reasons != (FACTS_NOT_TYPED,):
                raise ValueError("INVALID_FACTS carries only UNKNOWN states and FACTS_NOT_TYPED")
        else:
            expected = _derive(self.states, _inconsistencies(self.states))
            if self.reasons != _reasons_for(self.states):
                raise ValueError("reasons must be exactly those derived from states")
        actual = (self.technical_success, self.evidence_sufficient, self.ready_for_human_review, self.classification)
        if actual != expected:
            raise ValueError("advisory outcomes must be exactly those derived from states")

    def state_of(self, dimension: str) -> str:
        return self.states[DIMENSIONS.index(dimension)]

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "classification": self.classification,
            "technical_success": self.technical_success, "evidence_sufficient": self.evidence_sufficient,
            "ready_for_human_review": self.ready_for_human_review,
            "dimensions": {d: s for d, s in zip(DIMENSIONS, self.states)},
            "reasons": list(self.reasons), **_NotAuthorized._guarantees(),
        }


def canonical_json(assessment: ValidationAssessment) -> str:
    """Stable, sorted, compact serialization. Only the exact contract type is
    accepted, so a subclass cannot substitute its own `to_dict`."""
    if type(assessment) is not ValidationAssessment:
        raise TypeError("canonical_json accepts only a ValidationAssessment")
    return json.dumps(ValidationAssessment.to_dict(assessment), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def assess_validation(facts: ValidationFacts) -> ValidationAssessment:
    """Pure, deterministic validation assessment. Never raises on bad input:
    a non-`ValidationFacts` input is INVALID_FACTS and a malformed dimension
    is MALFORMED (never True). The result never certifies, authorizes,
    executes, merges, promotes, retries or resumes anything."""
    if type(facts) is not ValidationFacts:
        return ValidationAssessment(
            classification=INVALID_FACTS, technical_success=False, evidence_sufficient=False,
            ready_for_human_review=False, states=(STATE_UNKNOWN,) * len(DIMENSIONS), reasons=(FACTS_NOT_TYPED,),
        )
    states = tuple(_state(getattr(facts, f.name)) for f in fields(ValidationFacts))
    technical, evidence, ready, classification = _derive(states, _inconsistencies(states))
    return ValidationAssessment(
        classification=classification, technical_success=technical, evidence_sufficient=evidence,
        ready_for_human_review=ready, states=states, reasons=_reasons_for(states),
    )

"""Governed, provider-neutral selector self-healing (V1).

QCC_SELECTOR_SELF_HEALING_V1

When a primary/canonical selector fails to resolve at runtime, this
module evaluates a pool of currently observed candidate elements against
the last-known descriptor of the failed element and proposes AT MOST one
``HealedCandidate`` with explicit confidence and provenance.

Hard invariants:

- this module NEVER executes anything and NEVER mutates the canonical
  selector. It only proposes; canonical promotion is a separate governed
  lifecycle (out of scope here);
- more than one candidate tied for the top score is AMBIGUOUS, which
  fails closed regardless of individual confidence;
- HUMAN_ONLY interaction policy can never become execution-eligible
  through this module, no matter the confidence;
- AUTOMATION_ALLOWED healed candidates are execution-eligible only when
  ALL of: current state matches, the candidate is unambiguous, its
  confidence is strictly HIGH, the interaction policy allows automation,
  and the caller confirms evidence requirements are satisfied;
- no provider-specific (e.g. Mercurio) conditionals live in this module.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Mapping,
)


SELECTOR_HEALING_SCHEMA_VERSION = 1

SELECTOR_HEALING_CONFIDENCE_HIGH = "HIGH"
SELECTOR_HEALING_CONFIDENCE_MEDIUM = "MEDIUM"
SELECTOR_HEALING_CONFIDENCE_LOW = "LOW"

_CONFIDENCE_ORDER = {
    SELECTOR_HEALING_CONFIDENCE_LOW: 0,
    SELECTOR_HEALING_CONFIDENCE_MEDIUM: 1,
    SELECTOR_HEALING_CONFIDENCE_HIGH: 2,
}

SELECTOR_HEALING_STATUS_HEALED = "HEALED"
SELECTOR_HEALING_STATUS_AMBIGUOUS = "AMBIGUOUS"
SELECTOR_HEALING_STATUS_NOT_FOUND = "NOT_FOUND"

INTERACTION_POLICY_HUMAN_ONLY = "HUMAN_ONLY"
INTERACTION_POLICY_AUTOMATION_ALLOWED = "AUTOMATION_ALLOWED"
INTERACTION_POLICY_DENY = "DENY"

# Score contribution weights. Chosen so that a single strong, stable
# signal (canonical id, exact previously-observed-selector match) alone
# can reach MEDIUM but never HIGH by itself: HIGH requires corroboration
# from more than one independent signal, which is what makes coincidental
# same-label/same-type duplicates resolve to AMBIGUOUS instead of a false
# HIGH.
_WEIGHT_PREVIOUSLY_OBSERVED_SELECTOR = 0.45
_WEIGHT_ID = 0.30
_WEIGHT_NAME = 0.25
_WEIGHT_FORM_RELATIONSHIP = 0.15
_WEIGHT_ROLE = 0.12
_WEIGHT_ARIA = 0.12
_WEIGHT_STABLE_DATA_ATTRIBUTES = 0.15
_WEIGHT_STRUCTURAL_NEIGHBORHOOD = 0.10
_WEIGHT_ELEMENT_TYPE = 0.06
_WEIGHT_LABEL_TEXT = 0.05

_MAX_POSSIBLE_SCORE = (
    _WEIGHT_PREVIOUSLY_OBSERVED_SELECTOR
    + _WEIGHT_ID
    + _WEIGHT_NAME
    + _WEIGHT_FORM_RELATIONSHIP
    + _WEIGHT_ROLE
    + _WEIGHT_ARIA
    + _WEIGHT_STABLE_DATA_ATTRIBUTES
    + _WEIGHT_STRUCTURAL_NEIGHBORHOOD
    + _WEIGHT_ELEMENT_TYPE
    + _WEIGHT_LABEL_TEXT
)

_HIGH_THRESHOLD = 0.60
_MEDIUM_THRESHOLD = 0.25

_TIE_EPSILON = 1e-9


def _text(value):
    return str(value or "").strip()


def _lower(value):
    return _text(value).lower()


@dataclass(
    frozen=True,
    slots=True,
)
class ElementDescriptor:
    """Candidate evidence for one currently observed element.

    ``identifier_stable`` must be set to ``False`` by the caller when
    ``element_id``/``name`` are known to be framework-generated/volatile
    (e.g. hashed or positionally regenerated on every render). Unstable
    identifiers never contribute to the score, even on an exact match.
    """

    selector: str
    frame_path: str = "main"

    tag: str | None = None
    element_id: str | None = None
    name: str | None = None
    role: str | None = None

    aria_attributes: Mapping[str, str] = field(
        default_factory=dict,
    )
    stable_data_attributes: Mapping[str, str] = field(
        default_factory=dict,
    )

    label_text: str | None = None
    element_type: str | None = None

    # Ordered ancestor tag chain (outermost -> innermost), e.g.
    # ("form", "fieldset", "div"). Used only for coarse structural
    # similarity, never as a standalone identity signal.
    structural_path: tuple[str, ...] = ()

    # Owning form identity (id/name), if any.
    form_id: str | None = None

    identifier_stable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "selector",
            _text(self.selector) or None,
        )

        object.__setattr__(
            self,
            "frame_path",
            _text(self.frame_path) or "main",
        )

        object.__setattr__(
            self,
            "structural_path",
            tuple(
                _lower(item)
                for item in (self.structural_path or ())
                if _text(item)
            ),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class TargetDescriptor:
    """Last-known descriptor of the element whose primary selector
    failed to resolve. Same shape as ``ElementDescriptor`` plus the
    set of previously observed equivalent selectors (historical
    evidence, e.g. from earlier successful healing or Twin navigation
    learning)."""

    tag: str | None = None
    element_id: str | None = None
    name: str | None = None
    role: str | None = None

    aria_attributes: Mapping[str, str] = field(
        default_factory=dict,
    )
    stable_data_attributes: Mapping[str, str] = field(
        default_factory=dict,
    )

    label_text: str | None = None
    element_type: str | None = None
    structural_path: tuple[str, ...] = ()
    form_id: str | None = None

    identifier_stable: bool = True

    previously_observed_selectors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "structural_path",
            tuple(
                _lower(item)
                for item in (self.structural_path or ())
                if _text(item)
            ),
        )

        object.__setattr__(
            self,
            "previously_observed_selectors",
            tuple(
                _text(item)
                for item in (
                    self.previously_observed_selectors or ()
                )
                if _text(item)
            ),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class HealedCandidate:
    """A single proposed replacement selector. Never authoritative."""

    candidate_selector: str
    frame_path: str
    confidence: str
    score: float
    matched_signals: tuple[str, ...]
    provenance: Mapping[str, object]


@dataclass(
    frozen=True,
    slots=True,
)
class SelectorHealingResult:
    schema_version: int
    status: str
    healed_candidate: HealedCandidate | None
    candidates_considered: int
    reason: str | None


def _confidence_for_score(score: float) -> str | None:
    if score <= 0:
        return None

    if score >= _HIGH_THRESHOLD:
        return SELECTOR_HEALING_CONFIDENCE_HIGH

    if score >= _MEDIUM_THRESHOLD:
        return SELECTOR_HEALING_CONFIDENCE_MEDIUM

    return SELECTOR_HEALING_CONFIDENCE_LOW


def _score_candidate(
    target: TargetDescriptor,
    candidate: ElementDescriptor,
) -> tuple[float, tuple[str, ...], dict]:
    score = 0.0
    matched: list[str] = []
    provenance: dict = {}

    if (
        candidate.selector
        and candidate.selector in target.previously_observed_selectors
    ):
        score += _WEIGHT_PREVIOUSLY_OBSERVED_SELECTOR
        matched.append("previously_observed_selector")

    id_match = (
        candidate.identifier_stable
        and target.identifier_stable
        and _text(target.element_id)
        and _lower(target.element_id) == _lower(candidate.element_id)
    )

    if id_match:
        score += _WEIGHT_ID
        matched.append("id")

    name_match = (
        candidate.identifier_stable
        and target.identifier_stable
        and _text(target.name)
        and _lower(target.name) == _lower(candidate.name)
    )

    if name_match:
        score += _WEIGHT_NAME
        matched.append("name")

    if (
        _text(target.form_id)
        and _lower(target.form_id) == _lower(candidate.form_id)
    ):
        score += _WEIGHT_FORM_RELATIONSHIP
        matched.append("form_relationship")

    if (
        _text(target.role)
        and _lower(target.role) == _lower(candidate.role)
    ):
        score += _WEIGHT_ROLE
        matched.append("role")

    target_aria = {
        _lower(k): _lower(v)
        for k, v in (target.aria_attributes or {}).items()
    }
    candidate_aria = {
        _lower(k): _lower(v)
        for k, v in (candidate.aria_attributes or {}).items()
    }

    if target_aria and candidate_aria:
        shared = set(target_aria) & set(candidate_aria)
        aria_matches = [
            key
            for key in shared
            if target_aria[key] == candidate_aria[key]
        ]

        if aria_matches:
            score += _WEIGHT_ARIA
            matched.append("aria_attributes")
            provenance["aria_matches"] = sorted(aria_matches)

    target_data = {
        _lower(k): _lower(v)
        for k, v in (target.stable_data_attributes or {}).items()
    }
    candidate_data = {
        _lower(k): _lower(v)
        for k, v in (candidate.stable_data_attributes or {}).items()
    }

    if target_data and candidate_data:
        shared_data = set(target_data) & set(candidate_data)
        data_matches = [
            key
            for key in shared_data
            if target_data[key] == candidate_data[key]
        ]

        if data_matches:
            score += _WEIGHT_STABLE_DATA_ATTRIBUTES
            matched.append("stable_data_attributes")
            provenance["stable_data_attribute_matches"] = sorted(
                data_matches
            )

    if (
        target.structural_path
        and target.structural_path == candidate.structural_path
    ):
        score += _WEIGHT_STRUCTURAL_NEIGHBORHOOD
        matched.append("structural_neighborhood")

    if (
        _text(target.element_type)
        and _lower(target.element_type) == _lower(candidate.element_type)
    ):
        score += _WEIGHT_ELEMENT_TYPE
        matched.append("element_type")

    if (
        _text(target.label_text)
        and _lower(target.label_text) == _lower(candidate.label_text)
    ):
        score += _WEIGHT_LABEL_TEXT
        matched.append("label_text")

    return score, tuple(matched), provenance


def evaluate_selector_healing(
    *,
    target: TargetDescriptor,
    candidates,
) -> SelectorHealingResult:
    """Evaluate healing candidates for one failed selector.

    ``candidates``: iterable of ``ElementDescriptor``, the currently
    observed elements considered as replacement candidates. This
    function is a pure read-model: it never touches storage, never
    executes, and never mutates anything.
    """

    if not isinstance(target, TargetDescriptor):
        raise TypeError(
            "QCC_SELECTOR_HEALING_TARGET_INVALID"
        )

    candidates = tuple(candidates or ())

    for candidate in candidates:
        if not isinstance(candidate, ElementDescriptor):
            raise TypeError(
                "QCC_SELECTOR_HEALING_CANDIDATE_INVALID"
            )

    scored = []

    for candidate in candidates:
        if not candidate.selector:
            continue

        score, matched, provenance = _score_candidate(
            target,
            candidate,
        )

        if score <= 0:
            continue

        scored.append(
            (score, matched, provenance, candidate)
        )

    if not scored:
        return SelectorHealingResult(
            schema_version=SELECTOR_HEALING_SCHEMA_VERSION,
            status=SELECTOR_HEALING_STATUS_NOT_FOUND,
            healed_candidate=None,
            candidates_considered=len(candidates),
            reason="NO_PLAUSIBLE_CANDIDATE",
        )

    top_score = max(item[0] for item in scored)

    top = [
        item
        for item in scored
        if abs(item[0] - top_score) <= _TIE_EPSILON
    ]

    if len(top) > 1:
        return SelectorHealingResult(
            schema_version=SELECTOR_HEALING_SCHEMA_VERSION,
            status=SELECTOR_HEALING_STATUS_AMBIGUOUS,
            healed_candidate=None,
            candidates_considered=len(candidates),
            reason="MULTIPLE_CANDIDATES_TIED",
        )

    score, matched, provenance, candidate = top[0]

    confidence = _confidence_for_score(score)

    healed = HealedCandidate(
        candidate_selector=candidate.selector,
        frame_path=candidate.frame_path,
        confidence=confidence,
        score=round(score, 6),
        matched_signals=matched,
        provenance=provenance,
    )

    return SelectorHealingResult(
        schema_version=SELECTOR_HEALING_SCHEMA_VERSION,
        status=SELECTOR_HEALING_STATUS_HEALED,
        healed_candidate=healed,
        candidates_considered=len(candidates),
        reason=None,
    )


def resolve_selector_healing_execution_eligibility(
    *,
    healing_result: SelectorHealingResult,
    interaction_policy: str,
    current_functional_state: str | None,
    required_functional_state: str | None,
    evidence_requirements_satisfied: bool,
) -> dict:
    """Decide whether a healed candidate may be considered for execution.

    This NEVER promotes the canonical selector. It only answers whether
    the caller's gate is allowed to consider the healed candidate at
    all. A ``True`` result still requires the caller's own execution
    gate (see the evidence-based execution gate, R4) to make the final
    call.
    """

    policy = _text(interaction_policy).upper()

    if policy == INTERACTION_POLICY_HUMAN_ONLY:
        return {
            "eligible": False,
            "reason": "HUMAN_ONLY_NEVER_EXECUTION_ELIGIBLE",
        }

    if policy != INTERACTION_POLICY_AUTOMATION_ALLOWED:
        return {
            "eligible": False,
            "reason": "INTERACTION_POLICY_NOT_AUTOMATION_ALLOWED",
        }

    if not isinstance(healing_result, SelectorHealingResult):
        raise TypeError(
            "QCC_SELECTOR_HEALING_RESULT_INVALID"
        )

    if healing_result.status != SELECTOR_HEALING_STATUS_HEALED:
        return {
            "eligible": False,
            "reason": (
                "AMBIGUOUS_CANDIDATE"
                if healing_result.status
                == SELECTOR_HEALING_STATUS_AMBIGUOUS
                else "NO_HEALED_CANDIDATE"
            ),
        }

    healed = healing_result.healed_candidate

    if healed.confidence != SELECTOR_HEALING_CONFIDENCE_HIGH:
        return {
            "eligible": False,
            "reason": "CONFIDENCE_BELOW_HIGH_THRESHOLD",
        }

    normalized_current = _text(current_functional_state).upper() or None
    normalized_required = _text(required_functional_state).upper() or None

    if (
        normalized_required is not None
        and normalized_current != normalized_required
    ):
        return {
            "eligible": False,
            "reason": "STATE_MISMATCH",
        }

    if not evidence_requirements_satisfied:
        return {
            "eligible": False,
            "reason": "EVIDENCE_REQUIREMENTS_NOT_SATISFIED",
        }

    return {
        "eligible": True,
        "reason": "HIGH_CONFIDENCE_UNAMBIGUOUS_STATE_MATCHED",
    }

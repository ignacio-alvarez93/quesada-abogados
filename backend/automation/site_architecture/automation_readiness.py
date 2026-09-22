"""Read-only automation readiness assessment (V0).

QCC_AUTOMATION_READINESS_V0

Aggregates already-computed, provider-neutral evidence into a single
explainable readiness report: a score, a per-dimension breakdown,
blockers and unknowns.

Hard invariants:

- this module NEVER grants execution authority. The score is
  informational only; nothing here feeds back into the execution gate;
- a HUMAN_ONLY action that is known and intentional must NOT reduce
  readiness merely because it is not automatable. Only a genuinely
  UNKNOWN/unset interaction policy reduces the policy-coverage
  dimension;
- a dimension with no data (``total_count == 0`` or the whole dimension
  input is ``None``) is reported as unknown, never silently scored as
  perfect or zero.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)


AUTOMATION_READINESS_SCHEMA_VERSION = 1

_KNOWN_INTERACTION_POLICIES = frozenset({
    "AUTOMATION_ALLOWED",
    "HUMAN_ONLY",
    "DENY",
})


def is_interaction_policy_known(policy) -> bool:
    """HUMAN_ONLY and DENY are just as "known" as AUTOMATION_ALLOWED.

    Only an empty/unrecognized policy value counts as unknown and
    therefore reduces readiness.
    """

    normalized = str(policy or "").strip().upper()

    return normalized in _KNOWN_INTERACTION_POLICIES


@dataclass(
    frozen=True,
    slots=True,
)
class DimensionCounts:
    covered: int
    total: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.covered, int)
            or not isinstance(self.total, int)
        ):
            raise TypeError(
                "QCC_AUTOMATION_READINESS_COUNTS_INVALID"
            )

        if self.total < 0 or self.covered < 0:
            raise ValueError(
                "QCC_AUTOMATION_READINESS_COUNTS_NEGATIVE"
            )

        if self.covered > self.total:
            raise ValueError(
                "QCC_AUTOMATION_READINESS_COUNTS_COVERED_EXCEEDS_TOTAL"
            )

    @property
    def ratio(self) -> float | None:
        if self.total == 0:
            return None

        return self.covered / self.total


_DIMENSIONS = (
    "state_coverage",
    "transition_coverage",
    "selector_confidence",
    "policy_coverage",
    "evidence_coverage",
    "contract_watcher_stability",
    "twin_fidelity",
    "recovery_coverage",
)

_BLOCKER_FOR_DIMENSION = {
    "state_coverage": "STATE_COVERAGE_INCOMPLETE",
    "transition_coverage": "TRANSITION_COVERAGE_INCOMPLETE",
    "selector_confidence": "SELECTOR_CONFIDENCE_INCOMPLETE",
    "policy_coverage": "UNKNOWN_INTERACTION_POLICY_PRESENT",
    "evidence_coverage": "EVIDENCE_COVERAGE_INCOMPLETE",
    "contract_watcher_stability": "CONTRACT_WATCHER_UNSTABLE",
    "twin_fidelity": "TWIN_FIDELITY_INCOMPLETE",
    "recovery_coverage": "RECOVERY_COVERAGE_INCOMPLETE",
}


@dataclass(
    frozen=True,
    slots=True,
)
class AutomationReadinessInputs:
    """One ``DimensionCounts`` (or ``None`` when unavailable) per
    dimension. ``runtime_health_available`` is a plain boolean signal,
    not a ratio: it only ever contributes an unknown/blocker entry when
    ``False``, never a score."""

    state_coverage: DimensionCounts | None = None
    transition_coverage: DimensionCounts | None = None
    selector_confidence: DimensionCounts | None = None
    policy_coverage: DimensionCounts | None = None
    evidence_coverage: DimensionCounts | None = None
    contract_watcher_stability: DimensionCounts | None = None
    twin_fidelity: DimensionCounts | None = None
    recovery_coverage: DimensionCounts | None = None
    runtime_health_available: bool = False

    def __post_init__(self) -> None:
        for name in _DIMENSIONS:
            value = getattr(self, name)

            if value is not None and not isinstance(
                value, DimensionCounts
            ):
                raise TypeError(
                    "QCC_AUTOMATION_READINESS_DIMENSION_INVALID:"
                    + name
                )

        if not isinstance(self.runtime_health_available, bool):
            raise TypeError(
                "QCC_AUTOMATION_READINESS_RUNTIME_HEALTH_INVALID"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class AutomationReadinessReport:
    schema_version: int
    score: float | None
    dimension_scores: dict
    blockers: tuple[str, ...]
    unknowns: tuple[str, ...]


def assess_automation_readiness(
    inputs: AutomationReadinessInputs,
) -> AutomationReadinessReport:
    if not isinstance(inputs, AutomationReadinessInputs):
        raise TypeError(
            "QCC_AUTOMATION_READINESS_INPUTS_INVALID"
        )

    dimension_scores = {}
    blockers = []
    unknowns = []

    available_ratios = []

    for name in _DIMENSIONS:
        counts = getattr(inputs, name)

        if counts is None:
            dimension_scores[name] = None
            unknowns.append(name.upper() + "_UNAVAILABLE")
            continue

        ratio = counts.ratio

        if ratio is None:
            dimension_scores[name] = None
            unknowns.append(name.upper() + "_NO_DATA")
            continue

        dimension_scores[name] = ratio
        available_ratios.append(ratio)

        if ratio < 1.0:
            blockers.append(_BLOCKER_FOR_DIMENSION[name])

    if not inputs.runtime_health_available:
        unknowns.append("RUNTIME_HEALTH_UNAVAILABLE")

    score = (
        sum(available_ratios) / len(available_ratios)
        if available_ratios
        else None
    )

    return AutomationReadinessReport(
        schema_version=AUTOMATION_READINESS_SCHEMA_VERSION,
        score=score,
        dimension_scores=dimension_scores,
        blockers=tuple(blockers),
        unknowns=tuple(unknowns),
    )

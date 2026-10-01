"""UWT-2 state comparison contract.

Exposes ``compare_functional_state(previous, current)``, conceptually
equivalent to the work order's ``compare(previous_observation,
current_observation)``, returning a FunctionalDelta that classifies the
transition as exactly one of:

    SAME_FUNCTIONAL_STATE
    FUNCTIONAL_STATE_CHANGED
    UNKNOWN

Decision policy (work order section 9):

    URL is a signal, not state authority.

``page_identity`` is therefore reported as a non-decisive signal.
Only the operative evidence (actions / active_ui_regions / catalogs /
catalog_relations) is decisive. Ambiguous or insufficient evidence
(missing observation, EXTERNAL_UI_BOUNDARY, unavailable evidence) fails
closed to UNKNOWN rather than guessing SAME or CHANGED.
"""

from __future__ import annotations

from dataclasses import dataclass

from .functional_state import FunctionalState
from .stable_state_fingerprint import OPERATIVE_SECTIONS
from .state_signals import (
    SignalCategory,
    StateSignal,
    build_state_signal,
)


FUNCTIONAL_DELTA_SCHEMA_VERSION = 1
FUNCTIONAL_DELTA_TYPE = "QCC_UWT_FUNCTIONAL_DELTA"

SAME_FUNCTIONAL_STATE = "SAME_FUNCTIONAL_STATE"
FUNCTIONAL_STATE_CHANGED = "FUNCTIONAL_STATE_CHANGED"
UNKNOWN = "UNKNOWN"

UNKNOWN_REASON_MISSING_OBSERVATION = "MISSING_OBSERVATION"
UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY = "EXTERNAL_UI_BOUNDARY_PRESENT"
UNKNOWN_REASON_EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
UNKNOWN_REASON_CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"


@dataclass(frozen=True, slots=True)
class FunctionalDelta:
    """Structured, explainable result of a functional state comparison."""

    schema_version: int
    delta_type: str
    classification: str
    reason: str | None
    signals: tuple[StateSignal, ...]


def _unknown(reason, signals=()) -> FunctionalDelta:
    return FunctionalDelta(
        schema_version=FUNCTIONAL_DELTA_SCHEMA_VERSION,
        delta_type=FUNCTIONAL_DELTA_TYPE,
        classification=UNKNOWN,
        reason=reason,
        signals=tuple(signals),
    )


def compare_functional_state(
    previous,
    current,
) -> FunctionalDelta:
    """Compares two FunctionalState observations. Fails closed to UNKNOWN."""

    if previous is None or current is None:
        return _unknown(
            UNKNOWN_REASON_MISSING_OBSERVATION
        )

    if not isinstance(
        previous,
        FunctionalState,
    ) or not isinstance(
        current,
        FunctionalState,
    ):
        raise TypeError(
            "QCC_UWT_FUNCTIONAL_DELTA_INPUT_INVALID"
        )

    if (
        previous.external_ui_boundary is not None
        or current.external_ui_boundary is not None
    ):
        return _unknown(
            UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY
        )

    if (
        not previous.evidence_available
        or not current.evidence_available
    ):
        return _unknown(
            UNKNOWN_REASON_EVIDENCE_UNAVAILABLE
        )

    signals = []

    page_changed = (
        dict(previous.page_identity)
        != dict(current.page_identity)
    )

    signals.append(
        build_state_signal(
            name="page_identity",
            category=SignalCategory.FUNCTIONAL,
            changed=page_changed,
            decisive=False,
        )
    )

    operative_changed = False

    for section in OPERATIVE_SECTIONS:
        section_changed = (
            previous.operative_payload.get(section)
            != current.operative_payload.get(section)
        )

        if section_changed:
            operative_changed = True

        signals.append(
            build_state_signal(
                name=section,
                category=SignalCategory.FUNCTIONAL,
                changed=section_changed,
                decisive=True,
            )
        )

    fingerprint_changed = (
        previous.fingerprint.operative_value
        != current.fingerprint.operative_value
    )

    if fingerprint_changed != operative_changed:
        # The decisive fingerprint and the per-section signals it is
        # derived from disagree. This should be structurally impossible
        # given stable_state_fingerprint.operative_payload_subset uses
        # the same sections; fail closed rather than silently trusting
        # either source.
        return _unknown(
            UNKNOWN_REASON_CONTRADICTORY_EVIDENCE,
            signals,
        )

    classification = (
        FUNCTIONAL_STATE_CHANGED
        if operative_changed
        else SAME_FUNCTIONAL_STATE
    )

    return FunctionalDelta(
        schema_version=FUNCTIONAL_DELTA_SCHEMA_VERSION,
        delta_type=FUNCTIONAL_DELTA_TYPE,
        classification=classification,
        reason=None,
        signals=tuple(signals),
    )

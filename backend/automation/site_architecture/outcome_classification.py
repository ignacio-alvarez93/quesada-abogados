"""Post-action outcome classification (V1).

QCC_POST_ACTION_OBSERVATION_V1

Pure, provider-neutral comparison of a functional-state fingerprint
observed BEFORE a governed action against the fingerprint observed
AFTER it. This module never executes anything, never re-observes the
browser itself and never decides whether to retry: it only classifies
what was actually observed so a caller (the state-aware execution
orchestrator) can decide on safe recovery.

Hard invariants:

- SeleniumBase not raising an exception is never treated as success:
  the classification is always derived from the observed fingerprint
  diff, never from the absence of an executor error;
- a fingerprint that did not change is never silently promoted to
  ``EXPECTED``;
- ``retry_eligible`` is only ever ``True`` when the caller has
  explicitly declared the action idempotent. This module never infers
  idempotency from the action kind or from the observed outcome.
"""

from __future__ import annotations

from dataclasses import dataclass


OUTCOME_CLASSIFICATION_SCHEMA_VERSION = 1

OUTCOME_EXPECTED = "EXPECTED"
OUTCOME_OBSERVED_DIFFERENT_KNOWN = "OBSERVED_DIFFERENT_KNOWN"
OUTCOME_OBSERVED_UNKNOWN = "OBSERVED_UNKNOWN"
OUTCOME_TRANSITION_NOT_OBSERVED = "TRANSITION_NOT_OBSERVED"
OUTCOME_EXECUTION_ERROR = "EXECUTION_ERROR"
OUTCOME_HUMAN_HANDOFF = "HUMAN_HANDOFF"

_VALID_OUTCOMES = frozenset({
    OUTCOME_EXPECTED,
    OUTCOME_OBSERVED_DIFFERENT_KNOWN,
    OUTCOME_OBSERVED_UNKNOWN,
    OUTCOME_TRANSITION_NOT_OBSERVED,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_HUMAN_HANDOFF,
})

ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED = (
    "ACTION_CONFIRMED_NOT_EXECUTED"
)
ACTION_DISPOSITION_EXECUTION_ATTEMPTED = (
    "ACTION_EXECUTION_ATTEMPTED"
)
ACTION_DISPOSITION_EFFECT_UNKNOWN = (
    "ACTION_EXECUTION_EFFECT_UNKNOWN"
)
ACTION_DISPOSITION_CONFIRMED = (
    "ACTION_EXECUTION_CONFIRMED"
)

_VALID_DISPOSITIONS = frozenset({
    ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
    ACTION_DISPOSITION_EXECUTION_ATTEMPTED,
    ACTION_DISPOSITION_EFFECT_UNKNOWN,
    ACTION_DISPOSITION_CONFIRMED,
})


@dataclass(
    frozen=True,
    slots=True,
)
class PostActionClassification:
    schema_version: int
    classification: str
    disposition: str
    retry_eligible: bool

    def __post_init__(self) -> None:
        if self.classification not in _VALID_OUTCOMES:
            raise ValueError(
                "QCC_OUTCOME_CLASSIFICATION_INVALID"
            )

        if self.disposition not in _VALID_DISPOSITIONS:
            raise ValueError(
                "QCC_ACTION_DISPOSITION_INVALID"
            )

        if not isinstance(self.retry_eligible, bool):
            raise TypeError(
                "QCC_OUTCOME_RETRY_ELIGIBLE_INVALID"
            )


def classify_post_action_outcome(
    *,
    execution_error,
    fingerprint_before: str | None,
    fingerprint_after: str | None,
    expected_successor_fingerprint: str | None = None,
    known_fingerprints=frozenset(),
    idempotent: bool = False,
) -> PostActionClassification:
    """Classify what was actually observed after a governed action.

    ``execution_error``: the exception raised by the executor, or
    ``None`` if the executor call did not raise. Never treated as
    proof of success or failure by itself.

    ``known_fingerprints``: fingerprints already known to the caller
    (e.g. expected-graph states, previously observed navigation-graph
    nodes). Used only to distinguish a known divergence from a
    genuinely unknown successor.
    """

    if fingerprint_after is None:
        # Could not re-observe the browser at all.
        return PostActionClassification(
            schema_version=OUTCOME_CLASSIFICATION_SCHEMA_VERSION,
            classification=(
                OUTCOME_EXECUTION_ERROR
                if execution_error is not None
                else OUTCOME_TRANSITION_NOT_OBSERVED
            ),
            disposition=ACTION_DISPOSITION_EFFECT_UNKNOWN,
            retry_eligible=False,
        )

    if fingerprint_after == fingerprint_before:
        return PostActionClassification(
            schema_version=OUTCOME_CLASSIFICATION_SCHEMA_VERSION,
            classification=OUTCOME_TRANSITION_NOT_OBSERVED,
            disposition=(
                ACTION_DISPOSITION_EFFECT_UNKNOWN
                if execution_error is not None
                else ACTION_DISPOSITION_EXECUTION_ATTEMPTED
            ),
            retry_eligible=bool(
                idempotent
                and execution_error is None
            ),
        )

    # The fingerprint changed: some effect was observed.
    if expected_successor_fingerprint is not None:
        if fingerprint_after == expected_successor_fingerprint:
            return PostActionClassification(
                schema_version=(
                    OUTCOME_CLASSIFICATION_SCHEMA_VERSION
                ),
                classification=OUTCOME_EXPECTED,
                disposition=ACTION_DISPOSITION_CONFIRMED,
                retry_eligible=False,
            )

        if fingerprint_after in known_fingerprints:
            return PostActionClassification(
                schema_version=(
                    OUTCOME_CLASSIFICATION_SCHEMA_VERSION
                ),
                classification=(
                    OUTCOME_OBSERVED_DIFFERENT_KNOWN
                ),
                disposition=ACTION_DISPOSITION_CONFIRMED,
                retry_eligible=False,
            )

        return PostActionClassification(
            schema_version=OUTCOME_CLASSIFICATION_SCHEMA_VERSION,
            classification=OUTCOME_OBSERVED_UNKNOWN,
            disposition=ACTION_DISPOSITION_CONFIRMED,
            retry_eligible=False,
        )

    if execution_error is not None:
        return PostActionClassification(
            schema_version=OUTCOME_CLASSIFICATION_SCHEMA_VERSION,
            classification=OUTCOME_EXECUTION_ERROR,
            disposition=ACTION_DISPOSITION_EFFECT_UNKNOWN,
            retry_eligible=False,
        )

    # Changed, no explicit expectation declared, executor did not
    # raise: treat as a confirmed, uneventful success.
    return PostActionClassification(
        schema_version=OUTCOME_CLASSIFICATION_SCHEMA_VERSION,
        classification=OUTCOME_EXPECTED,
        disposition=ACTION_DISPOSITION_CONFIRMED,
        retry_eligible=False,
    )

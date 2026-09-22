from backend.automation.site_architecture.outcome_classification import (
    ACTION_DISPOSITION_CONFIRMED,
    ACTION_DISPOSITION_EFFECT_UNKNOWN,
    ACTION_DISPOSITION_EXECUTION_ATTEMPTED,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_EXPECTED,
    OUTCOME_OBSERVED_DIFFERENT_KNOWN,
    OUTCOME_OBSERVED_UNKNOWN,
    OUTCOME_TRANSITION_NOT_OBSERVED,
    classify_post_action_outcome,
)


def test_no_observation_is_never_treated_as_success():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after=None,
    )

    assert result.classification == OUTCOME_TRANSITION_NOT_OBSERVED
    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN
    assert result.retry_eligible is False


def test_unchanged_fingerprint_is_not_observed_and_not_retried_by_default():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-1",
        idempotent=False,
    )

    assert result.classification == OUTCOME_TRANSITION_NOT_OBSERVED
    assert result.disposition == ACTION_DISPOSITION_EXECUTION_ATTEMPTED
    assert result.retry_eligible is False


def test_unchanged_fingerprint_is_retry_eligible_only_when_idempotent():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-1",
        idempotent=True,
    )

    assert result.retry_eligible is True


def test_execution_error_with_unchanged_fingerprint_never_retries():
    result = classify_post_action_outcome(
        execution_error=RuntimeError("boom"),
        fingerprint_before="fp-1",
        fingerprint_after="fp-1",
        idempotent=True,
    )

    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN
    assert result.retry_eligible is False


def test_expected_successor_observed_is_expected():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-2",
        expected_successor_fingerprint="fp-2",
    )

    assert result.classification == OUTCOME_EXPECTED
    assert result.disposition == ACTION_DISPOSITION_CONFIRMED
    assert result.retry_eligible is False


def test_known_different_successor_is_divergence():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-3",
        expected_successor_fingerprint="fp-2",
        known_fingerprints=frozenset({"fp-3"}),
    )

    assert result.classification == OUTCOME_OBSERVED_DIFFERENT_KNOWN
    assert result.disposition == ACTION_DISPOSITION_CONFIRMED


def test_unknown_successor_is_observed_unknown():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-4",
        expected_successor_fingerprint="fp-2",
        known_fingerprints=frozenset({"fp-3"}),
    )

    assert result.classification == OUTCOME_OBSERVED_UNKNOWN
    assert result.disposition == ACTION_DISPOSITION_CONFIRMED


def test_changed_with_error_and_no_expectation_is_execution_error():
    result = classify_post_action_outcome(
        execution_error=RuntimeError("boom"),
        fingerprint_before="fp-1",
        fingerprint_after="fp-2",
    )

    assert result.classification == OUTCOME_EXECUTION_ERROR
    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN


def test_changed_without_expectation_or_error_is_expected():
    result = classify_post_action_outcome(
        execution_error=None,
        fingerprint_before="fp-1",
        fingerprint_after="fp-2",
    )

    assert result.classification == OUTCOME_EXPECTED
    assert result.disposition == ACTION_DISPOSITION_CONFIRMED

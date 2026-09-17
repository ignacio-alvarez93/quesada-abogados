import pytest

from backend.qcc.auto_twin.contract_watcher import (
    ContractWatchState,
    build_contract_watcher_evidence,
)
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
    ContractWatcherConfirmationState,
    apply_confirmation_step,
    compute_semantic_change_signature,
    confirmation_policy_from_dict,
)


def _snapshot(elements=(), pathname="/step/1"):
    return {
        "schema_version": 1,
        "page": {"pathname": pathname},
        "elements": tuple(elements),
        "catalogs": (),
    }


def _element(selector, *, disabled=False):
    return {
        "frame_path": "main",
        "semantics": ("BUTTON",),
        "selectors": {
            "frame_path": "main",
            "primary": {
                "strategy": "ID",
                "selector": selector,
                "confidence": "HIGH",
                "unique": True,
            },
            "fallbacks": (),
            "candidates": ({
                "strategy": "ID",
                "selector": selector,
                "confidence": "HIGH",
                "unique": True,
            },),
            "confidence": "HIGH",
        },
        "interaction": {
            "state": "INTERACTABLE",
            "visible": True,
            "in_viewport": True,
            "disabled": disabled,
            "readonly": False,
            "pointer_events": "auto",
        },
        "geometry": {
            "coordinate_space": "TOP_LEVEL_VIEWPORT",
            "frame_path": "main",
            "viewport_rect": None,
        },
    }


def _evidence(before, after, *, contract_key="ctr", created_at=None, before_reference=None, after_reference=None):
    return build_contract_watcher_evidence(
        contract_key=contract_key,
        before=before,
        after=after,
        before_reference=before_reference,
        after_reference=after_reference,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# ContractWatcherConfirmationPolicy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("invalid", [0, -1, -5, "3", 1.5, True, None])
def test_policy_rejects_non_positive_or_invalid_threshold(invalid):
    with pytest.raises(ValueError):
        ContractWatcherConfirmationPolicy(required_consecutive_observations=invalid)


def test_policy_accepts_positive_integer_threshold():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    assert policy.required_consecutive_observations == 3
    assert policy.to_dict()["required_consecutive_observations"] == 3


def test_policy_round_trips_through_dict():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    rebuilt = confirmation_policy_from_dict(policy.to_dict())

    assert rebuilt == policy


def test_policy_is_immutable():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    with pytest.raises(Exception):
        policy.required_consecutive_observations = 5


# ---------------------------------------------------------------------------
# compute_semantic_change_signature
# ---------------------------------------------------------------------------


def test_semantic_signature_stable_across_incidental_differences():
    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    evidence_one = _evidence(
        before,
        after,
        created_at="2026-01-01T00:00:00.000000Z",
        before_reference="capture-1",
        after_reference="capture-2",
    )

    evidence_two = _evidence(
        before,
        after,
        created_at="2026-06-15T12:30:00.123456Z",
        before_reference="capture-99",
        after_reference="capture-100",
    )

    assert (
        compute_semantic_change_signature(evidence_one)
        == compute_semantic_change_signature(evidence_two)
    )


def test_semantic_signature_changes_with_structural_comparison():
    before = _snapshot(elements=[_element("#a")])
    after_add = _snapshot(elements=[_element("#a"), _element("#b")])
    after_remove = _snapshot(elements=[])

    evidence_add = _evidence(before, after_add)
    evidence_remove = _evidence(before, after_remove)

    assert (
        compute_semantic_change_signature(evidence_add)
        != compute_semantic_change_signature(evidence_remove)
    )


def test_semantic_signature_fails_closed_on_tampering():
    evidence = _evidence(_snapshot(), _snapshot())

    tampered = dict(evidence)
    tampered["severity"] = "BREAKING"

    with pytest.raises(ValueError):
        compute_semantic_change_signature(tampered)


# ---------------------------------------------------------------------------
# apply_confirmation_step (pure algorithm)
# ---------------------------------------------------------------------------


def test_first_suspected_observation_starts_streak_at_one():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    state, lifecycle_state = apply_confirmation_step(
        state=ContractWatcherConfirmationState(),
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-aaa",
        policy=policy,
    )

    assert state.streak_count == 1
    assert state.streak_signature == "cwsig-aaa"
    assert lifecycle_state == ContractWatchState.CHANGE_SUSPECTED.value


def test_same_signature_below_threshold_remains_suspected():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    state = ContractWatcherConfirmationState()

    for _ in range(2):
        state, lifecycle_state = apply_confirmation_step(
            state=state,
            watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
            semantic_signature="cwsig-aaa",
            policy=policy,
        )

    assert state.streak_count == 2
    assert lifecycle_state == ContractWatchState.CHANGE_SUSPECTED.value


def test_exact_threshold_confirms_change():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    state = ContractWatcherConfirmationState()
    lifecycle_state = None

    for _ in range(3):
        state, lifecycle_state = apply_confirmation_step(
            state=state,
            watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
            semantic_signature="cwsig-aaa",
            policy=policy,
        )

    assert state.streak_count == 3
    assert lifecycle_state == ContractWatchState.CHANGE_CONFIRMED.value


def test_threshold_of_one_confirms_on_first_observation():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=1)

    state, lifecycle_state = apply_confirmation_step(
        state=ContractWatcherConfirmationState(),
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-aaa",
        policy=policy,
    )

    assert lifecycle_state == ContractWatchState.CHANGE_CONFIRMED.value


def test_different_signature_resets_streak_instead_of_inheriting_it():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    state = ContractWatcherConfirmationState()

    for _ in range(2):
        state, _ = apply_confirmation_step(
            state=state,
            watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
            semantic_signature="cwsig-aaa",
            policy=policy,
        )

    state, lifecycle_state = apply_confirmation_step(
        state=state,
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-bbb",
        policy=policy,
    )

    assert state.streak_signature == "cwsig-bbb"
    assert state.streak_count == 1
    assert lifecycle_state == ContractWatchState.CHANGE_SUSPECTED.value


def test_no_change_breaks_pending_streak_and_reports_no_change():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    state, _ = apply_confirmation_step(
        state=ContractWatcherConfirmationState(),
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-aaa",
        policy=policy,
    )

    state, lifecycle_state = apply_confirmation_step(
        state=state,
        watch_state=ContractWatchState.NO_CHANGE.value,
        semantic_signature=None,
        policy=policy,
    )

    assert state.streak_count == 0
    assert state.streak_signature is None
    assert lifecycle_state == ContractWatchState.NO_CHANGE.value


def test_validation_required_never_increments_or_confirms():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    state, _ = apply_confirmation_step(
        state=ContractWatcherConfirmationState(),
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-aaa",
        policy=policy,
    )

    preserved_state, lifecycle_state = apply_confirmation_step(
        state=state,
        watch_state=ContractWatchState.VALIDATION_REQUIRED.value,
        semantic_signature="cwsig-unused",
        policy=policy,
    )

    assert preserved_state == state
    assert lifecycle_state == ContractWatchState.VALIDATION_REQUIRED.value

    # A subsequent valid observation of the same change can still
    # continue the preserved streak towards confirmation.
    final_state, final_lifecycle_state = apply_confirmation_step(
        state=preserved_state,
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature="cwsig-aaa",
        policy=policy,
    )

    assert final_state.streak_count == 2
    assert final_lifecycle_state == ContractWatchState.CHANGE_CONFIRMED.value


def test_breaking_severity_does_not_shorten_threshold():
    # The algorithm never consults severity at all; a BREAKING change
    # still needs the full configured number of consecutive matching
    # observations, exactly like any other severity.
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    before = _snapshot(elements=[_element("#a"), _element("#b")])
    after = _snapshot(elements=[_element("#a")])

    breaking_evidence = _evidence(before, after)
    assert breaking_evidence["severity"] == "BREAKING"

    signature = compute_semantic_change_signature(breaking_evidence)

    state = ContractWatcherConfirmationState()
    lifecycle_state = None

    for _ in range(2):
        state, lifecycle_state = apply_confirmation_step(
            state=state,
            watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
            semantic_signature=signature,
            policy=policy,
        )

    assert lifecycle_state == ContractWatchState.CHANGE_SUSPECTED.value

    state, lifecycle_state = apply_confirmation_step(
        state=state,
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        semantic_signature=signature,
        policy=policy,
    )

    assert lifecycle_state == ContractWatchState.CHANGE_CONFIRMED.value


def test_confirmed_or_rebuild_required_watch_state_is_rejected_as_input():
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    with pytest.raises(ValueError):
        apply_confirmation_step(
            state=ContractWatcherConfirmationState(),
            watch_state=ContractWatchState.CHANGE_CONFIRMED.value,
            semantic_signature="cwsig-aaa",
            policy=policy,
        )

    with pytest.raises(ValueError):
        apply_confirmation_step(
            state=ContractWatcherConfirmationState(),
            watch_state=ContractWatchState.REBUILD_REQUIRED.value,
            semantic_signature="cwsig-aaa",
            policy=policy,
        )

import pytest

from backend.qcc.auto_twin import (
    ContractWatchState,
    ContractWatcherConfirmationPolicy,
    ContractWatcherEvidenceStore,
    ContractWatcherHistoryStore,
    build_contract_watcher_evidence,
    compute_semantic_change_signature,
    confirmation_policy_from_dict,
    evaluate_and_register_contract_watcher_observation,
    get_contract_watcher_lifecycle_status,
    reconstruct_contract_watcher_lifecycle,
)


def _element(selector):
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
            "disabled": False,
            "readonly": False,
            "pointer_events": "auto",
        },
        "geometry": {
            "coordinate_space": "TOP_LEVEL_VIEWPORT",
            "frame_path": "main",
            "viewport_rect": None,
        },
    }


def _snapshot(elements=()):
    return {
        "schema_version": 1,
        "page": {"pathname": "/step/1"},
        "elements": tuple(elements),
        "catalogs": (),
    }


def test_public_confirmation_policy_rejects_below_minimum_threshold():
    with pytest.raises(ValueError):
        ContractWatcherConfirmationPolicy(required_consecutive_observations=1)


def test_public_api_end_to_end_confirmation(tmp_path):
    evidence_store = ContractWatcherEvidenceStore(root=tmp_path / "evidence")
    history_store = ContractWatcherHistoryStore(root=tmp_path / "evidence")
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    first_evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=before,
        after=after,
        created_at="2026-01-01T00:00:00.000000Z",
    )

    second_evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=before,
        after=after,
        created_at="2026-01-02T00:00:00.000000Z",
    )

    assert compute_semantic_change_signature(
        first_evidence
    ) == compute_semantic_change_signature(second_evidence)

    assert confirmation_policy_from_dict(policy.to_dict()) == policy

    first_result = evaluate_and_register_contract_watcher_observation(
        first_evidence,
        policy=policy,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert (
        first_result["entry"]["lifecycle_state"]
        == ContractWatchState.CHANGE_SUSPECTED.value
    )

    second_result = evaluate_and_register_contract_watcher_observation(
        second_evidence,
        policy=policy,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert (
        second_result["entry"]["lifecycle_state"]
        == ContractWatchState.CHANGE_CONFIRMED.value
    )

    status = get_contract_watcher_lifecycle_status(
        "ctr", history_store=history_store
    )

    assert status["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value

    reconstructed = reconstruct_contract_watcher_lifecycle(
        "ctr", history_store=history_store
    )

    assert (
        reconstructed["lifecycle_state"]
        == ContractWatchState.CHANGE_CONFIRMED.value
    )

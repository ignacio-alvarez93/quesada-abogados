import pytest

from backend.qcc.auto_twin.contract_watcher import (
    ContractWatchState,
    build_contract_watcher_evidence,
)
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_lifecycle import (
    evaluate_and_register_contract_watcher_observation,
    get_contract_watcher_lifecycle_status,
    reconstruct_contract_watcher_lifecycle,
)
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore


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


def _snapshot(elements=(), pathname="/step/1"):
    return {
        "schema_version": 1,
        "page": {"pathname": pathname},
        "elements": tuple(elements),
        "catalogs": (),
    }


def _stores(tmp_path):
    return (
        ContractWatcherEvidenceStore(root=tmp_path / "evidence"),
        ContractWatcherHistoryStore(root=tmp_path / "evidence"),
    )


def test_lifecycle_requires_explicit_policy(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=_snapshot(),
        after=_snapshot(),
        created_at="2026-01-01T00:00:00.000000Z",
    )

    with pytest.raises(TypeError):
        evaluate_and_register_contract_watcher_observation(
            evidence,
            policy=None,
            evidence_store=evidence_store,
            history_store=history_store,
        )


def test_end_to_end_confirmation_after_repeated_matching_change(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)

    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    first_evidence = build_contract_watcher_evidence(
        contract_key="mercurio-ex01",
        before=before,
        after=after,
        before_reference="capture-1",
        after_reference="capture-2",
        created_at="2026-01-01T00:00:00.000000Z",
    )

    second_evidence = build_contract_watcher_evidence(
        contract_key="mercurio-ex01",
        before=before,
        after=after,
        before_reference="capture-2",
        after_reference="capture-3",
        created_at="2026-01-02T00:00:00.000000Z",
    )

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
        "mercurio-ex01", history_store=history_store
    )

    assert status["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value
    assert status["streak_count"] == 2

    reconstructed = reconstruct_contract_watcher_lifecycle(
        "mercurio-ex01", history_store=history_store
    )

    assert (
        reconstructed["lifecycle_state"]
        == ContractWatchState.CHANGE_CONFIRMED.value
    )

    # Both underlying evidence records remain independently retrievable
    # from the existing 1A evidence store, never duplicated.
    assert evidence_store.get(
        contract_key="mercurio-ex01",
        evidence_id=first_evidence["evidence_id"],
    ) is not None
    assert evidence_store.get(
        contract_key="mercurio-ex01",
        evidence_id=second_evidence["evidence_id"],
    ) is not None


def test_replaying_same_evidence_twice_is_idempotent(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=3)

    evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=_snapshot(elements=[_element("#a")]),
        after=_snapshot(elements=[_element("#a"), _element("#b")]),
        created_at="2026-01-01T00:00:00.000000Z",
    )

    first = evaluate_and_register_contract_watcher_observation(
        evidence,
        policy=policy,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    second = evaluate_and_register_contract_watcher_observation(
        evidence,
        policy=policy,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert first["entry"] == second["entry"]

    status = get_contract_watcher_lifecycle_status(
        "ctr", history_store=history_store
    )

    assert status["history_length"] == 1
    assert status["streak_count"] == 1


def test_confirmed_watch_state_evidence_is_rejected_as_raw_input(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    policy = ContractWatcherConfirmationPolicy(required_consecutive_observations=1)

    evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=_snapshot(elements=[_element("#a")]),
        after=_snapshot(elements=[_element("#a"), _element("#b")]),
    )

    forged = dict(evidence)
    forged["watch_state"] = ContractWatchState.CHANGE_CONFIRMED.value

    with pytest.raises(ValueError):
        evaluate_and_register_contract_watcher_observation(
            forged,
            policy=policy,
            evidence_store=evidence_store,
            history_store=history_store,
        )


def test_missing_contract_has_no_lifecycle_status(tmp_path):
    _, history_store = _stores(tmp_path)

    status = get_contract_watcher_lifecycle_status(
        "unknown-contract", history_store=history_store
    )

    assert status["lifecycle_state"] is None
    assert status["history_length"] == 0

import pytest

from backend.qcc.auto_twin.contract_watcher import ContractWatchState
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)


POLICY = ContractWatcherConfirmationPolicy(required_consecutive_observations=2)


def _register(store, *, evidence_id, watch_state, created_at, semantic_signature, severity="NON_BREAKING", contract_key="ctr", policy=POLICY):
    return store.register_observation(
        contract_key=contract_key,
        evidence_id=evidence_id,
        watch_state=watch_state,
        severity=severity,
        created_at=created_at,
        semantic_signature=semantic_signature,
        policy=policy,
    )


def test_first_changed_observation_is_suspected(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    result = _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    assert result["created"] is True
    assert result["entry"]["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert result["entry"]["streak_count"] == 1


def test_reaching_threshold_confirms(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    result = _register(
        store,
        evidence_id="cwev-2",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-02T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    assert result["entry"]["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value
    assert result["entry"]["streak_count"] == 2


def test_duplicate_replay_is_idempotent_and_not_double_counted(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    first_replay = _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    second_replay = _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    assert first_replay["created"] is False
    assert second_replay["created"] is False
    assert store.current_status(contract_key="ctr")["history_length"] == 1
    assert store.current_status(contract_key="ctr")["streak_count"] == 1


def test_out_of_order_observation_is_rejected(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-05T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    with pytest.raises(ValueError):
        _register(
            store,
            evidence_id="cwev-2",
            watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
            created_at="2026-01-01T00:00:00.000000Z",
            semantic_signature="cwsig-a",
        )


def test_no_change_resets_streak_in_store(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    result = _register(
        store,
        evidence_id="cwev-2",
        watch_state=ContractWatchState.NO_CHANGE.value,
        created_at="2026-01-02T00:00:00.000000Z",
        semantic_signature=None,
        severity="COSMETIC",
    )

    assert result["entry"]["lifecycle_state"] == ContractWatchState.NO_CHANGE.value
    assert result["entry"]["streak_count"] == 0


def test_validation_required_does_not_increment_store_streak(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    result = _register(
        store,
        evidence_id="cwev-2",
        watch_state=ContractWatchState.VALIDATION_REQUIRED.value,
        created_at="2026-01-02T00:00:00.000000Z",
        semantic_signature="cwsig-unused",
        severity="UNKNOWN",
    )

    assert result["entry"]["lifecycle_state"] == ContractWatchState.VALIDATION_REQUIRED.value
    assert result["entry"]["streak_count"] == 1
    assert result["entry"]["streak_signature"] == "cwsig-a"


def test_restart_reconstructs_identical_state(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    _register(
        store,
        evidence_id="cwev-2",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-02T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    reloaded_store = ContractWatcherHistoryStore(root=tmp_path)

    reconstructed = reloaded_store.reconstruct(contract_key="ctr")

    assert reconstructed["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value
    assert reconstructed["streak_count"] == 2
    assert len(reconstructed["timeline"]) == 2


def test_reconstruction_detects_tampering(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
    )

    path = store.history_path(contract_key="ctr")

    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0]["streak_count"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        store.reconstruct(contract_key="ctr")


def test_different_contracts_do_not_share_streaks(tmp_path):
    store = ContractWatcherHistoryStore(root=tmp_path)

    _register(
        store,
        evidence_id="cwev-1",
        watch_state=ContractWatchState.CHANGE_SUSPECTED.value,
        created_at="2026-01-01T00:00:00.000000Z",
        semantic_signature="cwsig-a",
        contract_key="ctr-a",
    )

    status_b = store.current_status(contract_key="ctr-b")

    assert status_b["history_length"] == 0
    assert status_b["lifecycle_state"] is None

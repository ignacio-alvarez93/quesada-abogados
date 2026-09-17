import pytest

from backend.qcc.auto_twin.contract_watcher import ContractWatchState
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_lifecycle import (
    get_contract_watcher_lifecycle_status,
)
from backend.qcc.auto_twin.contract_watcher_pipeline import (
    ContractWatcherBaselineIdentityError,
    ContractWatcherCycleOutcome,
    ContractWatcherCycleRequest,
    ContractWatcherObservationInput,
    ContractWatcherWatchTarget,
    run_contract_watcher_cycle,
    run_contract_watcher_cycle_batch,
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


def _unmatched_element():
    return {
        "frame_path": "main",
        "selectors": {"frame_path": "main", "candidates": ()},
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


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(
        required_consecutive_observations=threshold
    )


BASELINE = _snapshot(elements=[_element("#a")])
DIVERGED = _snapshot(elements=[_element("#a"), _element("#b")])


def _target(*, contract_key="ctr", baseline_reference="cap-A", policy=None):
    return ContractWatcherWatchTarget(
        contract_key=contract_key,
        baseline_reference=baseline_reference,
        baseline_contract=BASELINE,
        confirmation_policy=policy or _policy(),
    )


def _observation(*, reference, contract=DIVERGED, observed_at=None):
    return ContractWatcherObservationInput(
        observation_reference=reference,
        observation_contract=contract,
        observed_at=observed_at,
    )


def test_first_observation_of_a_semantic_divergence_is_suspected(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()
    observation = _observation(
        reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
    )

    receipt = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert receipt["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert receipt["streak_count"] == 1
    assert receipt["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    assert receipt["baseline_reference"] == "cap-A"
    assert receipt["observation_reference"] == "cap-B1"


def test_distinct_observation_of_same_divergence_confirms_at_threshold(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    first = run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    second = run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B2", observed_at="2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert first["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert second["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value
    assert second["streak_count"] == 2

    # Distinct physical observations of the same semantic divergence:
    # distinct evidence identity, same semantic signature.
    assert first["evidence_id"] != second["evidence_id"]
    assert first["semantic_signature"] == second["semantic_signature"]


def test_exact_replay_does_not_advance_streak(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()
    observation = _observation(
        reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
    )

    first = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    replay = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert first["evidence_id"] == replay["evidence_id"]
    assert replay["streak_count"] == 1
    assert replay["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    assert replay["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value


def test_baseline_identity_change_is_rejected_and_cannot_inherit_streak(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target(baseline_reference="cap-A")

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    drifted_target = _target(baseline_reference="cap-A-DIFFERENT")

    with pytest.raises(ContractWatcherBaselineIdentityError):
        run_contract_watcher_cycle(
            drifted_target,
            _observation(
                reference="cap-B2", observed_at="2026-01-02T00:00:00.000000Z"
            ),
            evidence_store=evidence_store,
            history_store=history_store,
        )

    # The rejected cycle must never have touched durable history.
    status = get_contract_watcher_lifecycle_status(
        "ctr", history_store=history_store
    )

    assert status["history_length"] == 1
    assert status["streak_count"] == 1
    assert status["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value


def test_baseline_reference_reused_for_different_content_is_rejected(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target(baseline_reference="cap-A")

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    drifted_content_baseline = _snapshot(elements=[_element("#a"), _element("#zzz")])

    drifted_target = ContractWatcherWatchTarget(
        contract_key="ctr",
        baseline_reference="cap-A",
        baseline_contract=drifted_content_baseline,
        confirmation_policy=_policy(),
    )

    with pytest.raises(ContractWatcherBaselineIdentityError):
        run_contract_watcher_cycle(
            drifted_target,
            _observation(
                reference="cap-B2", observed_at="2026-01-02T00:00:00.000000Z"
            ),
            evidence_store=evidence_store,
            history_store=history_store,
        )


def test_observation_identical_to_baseline_is_no_change(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    receipt = run_contract_watcher_cycle(
        target,
        _observation(
            reference="cap-B1",
            contract=BASELINE,
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert receipt["watch_state"] == ContractWatchState.NO_CHANGE.value
    assert receipt["lifecycle_state"] == ContractWatchState.NO_CHANGE.value
    assert receipt["streak_count"] == 0


def test_incomparable_observation_requires_validation(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    receipt = run_contract_watcher_cycle(
        target,
        _observation(
            reference="cap-B1",
            contract=_snapshot(elements=[_unmatched_element()]),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert receipt["watch_state"] == ContractWatchState.VALIDATION_REQUIRED.value
    assert receipt["lifecycle_state"] == ContractWatchState.VALIDATION_REQUIRED.value
    assert receipt["streak_count"] == 0


def test_separate_contract_keys_never_share_lifecycle(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    receipt_one = run_contract_watcher_cycle(
        _target(contract_key="ctr-1"),
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    receipt_two = run_contract_watcher_cycle(
        _target(contract_key="ctr-2"),
        _observation(
            reference="cap-B1",
            contract=BASELINE,
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert receipt_one["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert receipt_two["lifecycle_state"] == ContractWatchState.NO_CHANGE.value

    status_one = get_contract_watcher_lifecycle_status(
        "ctr-1", history_store=history_store
    )
    status_two = get_contract_watcher_lifecycle_status(
        "ctr-2", history_store=history_store
    )

    assert status_one["history_length"] == 1
    assert status_two["history_length"] == 1
    assert status_one["lifecycle_state"] != status_two["lifecycle_state"]


def test_restart_reconstruction_reproduces_identical_receipt(tmp_path):
    root = tmp_path / "evidence"
    target = _target()
    observation = _observation(
        reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
    )

    evidence_store_before = ContractWatcherEvidenceStore(root=root)
    history_store_before = ContractWatcherHistoryStore(root=root)

    before_restart = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store_before,
        history_store=history_store_before,
    )

    # Simulate a process restart: brand-new store instances over the same
    # durable root, no in-memory state carried over.
    evidence_store_after = ContractWatcherEvidenceStore(root=root)
    history_store_after = ContractWatcherHistoryStore(root=root)

    after_restart = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store_after,
        history_store=history_store_after,
    )

    assert before_restart == after_restart
    assert after_restart["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    assert after_restart["streak_count"] == 1


def test_malformed_target_and_observation_fail_closed():
    with pytest.raises(ValueError):
        ContractWatcherWatchTarget(
            contract_key="",
            baseline_reference="cap-A",
            baseline_contract=BASELINE,
            confirmation_policy=_policy(),
        )

    with pytest.raises(ValueError):
        ContractWatcherWatchTarget(
            contract_key="ctr",
            baseline_reference="",
            baseline_contract=BASELINE,
            confirmation_policy=_policy(),
        )

    with pytest.raises(ValueError):
        ContractWatcherWatchTarget(
            contract_key="ctr",
            baseline_reference="cap-A",
            baseline_contract=None,
            confirmation_policy=_policy(),
        )

    with pytest.raises(TypeError):
        ContractWatcherWatchTarget(
            contract_key="ctr",
            baseline_reference="cap-A",
            baseline_contract=BASELINE,
            confirmation_policy=None,
        )

    with pytest.raises(ValueError):
        ContractWatcherObservationInput(
            observation_reference="",
            observation_contract=DIVERGED,
        )

    with pytest.raises(ValueError):
        ContractWatcherObservationInput(
            observation_reference="cap-B1",
            observation_contract=None,
        )


def test_run_cycle_rejects_wrong_argument_types(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    with pytest.raises(TypeError):
        run_contract_watcher_cycle(
            "not-a-target",
            _observation(reference="cap-B1"),
            evidence_store=evidence_store,
            history_store=history_store,
        )

    with pytest.raises(TypeError):
        run_contract_watcher_cycle(
            _target(),
            "not-an-observation",
            evidence_store=evidence_store,
            history_store=history_store,
        )


def test_batch_processes_independent_requests_deterministically(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    requests = [
        ContractWatcherCycleRequest(
            target=_target(contract_key="ctr-1"),
            observation=_observation(
                reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
            ),
        ),
        ContractWatcherCycleRequest(
            target=_target(contract_key="ctr-2"),
            observation=_observation(
                reference="cap-B1",
                contract=BASELINE,
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
        ),
        ContractWatcherCycleRequest(
            target=_target(contract_key="ctr-3"),
            observation=_observation(
                reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
            ),
        ),
    ]

    run_1 = run_contract_watcher_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert run_1["requested"] == 3
    assert run_1["processed"] == 3
    assert run_1["failed"] == 0
    assert [r["contract_key"] for r in run_1["results"]] == [
        "ctr-1",
        "ctr-2",
        "ctr-3",
    ]
    assert run_1["lifecycle_counts"] == {
        ContractWatchState.CHANGE_SUSPECTED.value: 2,
        ContractWatchState.NO_CHANGE.value: 1,
    }

    # A fresh evaluation over a second, independent set of stores in the
    # same input order reproduces the same aggregate counts.
    evidence_store_2, history_store_2 = _stores(tmp_path / "second-run")

    run_2 = run_contract_watcher_cycle_batch(
        requests, evidence_store=evidence_store_2, history_store=history_store_2
    )

    assert run_2["lifecycle_counts"] == run_1["lifecycle_counts"]


def test_batch_records_per_target_failure_without_aborting_others(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target(contract_key="ctr-1")

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    drifted_target = _target(
        contract_key="ctr-1", baseline_reference="cap-A-DIFFERENT"
    )

    requests = [
        ContractWatcherCycleRequest(
            target=drifted_target,
            observation=_observation(
                reference="cap-B2", observed_at="2026-01-02T00:00:00.000000Z"
            ),
        ),
        ContractWatcherCycleRequest(
            target=_target(contract_key="ctr-2"),
            observation=_observation(
                reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
            ),
        ),
    ]

    run_result = run_contract_watcher_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert run_result["requested"] == 2
    assert run_result["processed"] == 1
    assert run_result["failed"] == 1
    assert run_result["results"][0]["contract_key"] == "ctr-2"
    assert run_result["failures"][0]["contract_key"] == "ctr-1"
    assert run_result["failures"][0]["index"] == 0


def test_batch_rejects_malformed_collection_and_items(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    with pytest.raises(TypeError):
        run_contract_watcher_cycle_batch(
            "not-a-list",
            evidence_store=evidence_store,
            history_store=history_store,
        )

    with pytest.raises(TypeError):
        run_contract_watcher_cycle_batch(
            ["not-a-request"],
            evidence_store=evidence_store,
            history_store=history_store,
        )

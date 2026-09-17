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
    ContractWatcherObservationOrderingError,
    ContractWatcherWatchTarget,
    build_baseline_content_signature,
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
TRIPLE_DIVERGED = _snapshot(elements=[_element("#a"), _element("#b"), _element("#c")])


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

    # The outcome legitimately differs: the first cycle newly registers
    # the observation, the restart replay reproduces an already-persisted
    # one. That difference is correct operational semantics and must
    # never be erased.
    assert before_restart["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    assert after_restart["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value

    # Everything else must be durably, deterministically reconstructed
    # from disk alone: identical physical evidence identity, identical
    # semantic signature, identical watch/severity/lifecycle state,
    # identical streak and policy, identical history length and
    # baseline/observation references, and no confirmation advancement
    # across the restart.
    non_outcome_fields = set(before_restart) - {"outcome"}
    assert non_outcome_fields == set(after_restart) - {"outcome"}

    for field in non_outcome_fields:
        assert after_restart[field] == before_restart[field], field

    assert after_restart["evidence_id"] == before_restart["evidence_id"]
    assert after_restart["semantic_signature"] == before_restart["semantic_signature"]
    assert after_restart["watch_state"] == before_restart["watch_state"]
    assert after_restart["severity"] == before_restart["severity"]
    assert after_restart["lifecycle_state"] == before_restart["lifecycle_state"]
    assert after_restart["streak_signature"] == before_restart["streak_signature"]
    assert after_restart["policy"] == before_restart["policy"]
    assert after_restart["baseline_reference"] == before_restart["baseline_reference"]
    assert after_restart["observation_reference"] == before_restart["observation_reference"]
    assert after_restart["history_length"] == before_restart["history_length"] == 1
    assert after_restart["streak_count"] == before_restart["streak_count"] == 1


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


def test_baseline_content_signature_changes_for_purely_additive_element():
    # This is the exact fixture pair the baseline-content-drift invariant
    # must catch: adding "#zzz" does not touch any functional/active-UI
    # signal (no active class tokens, no aria state), so the narrower 1A
    # functional-state fingerprint legitimately stays identical between
    # them; the canonical baseline content signature must not.
    baseline_signature = build_baseline_content_signature(BASELINE)
    drifted_signature = build_baseline_content_signature(
        _snapshot(elements=[_element("#a"), _element("#zzz")])
    )

    assert baseline_signature != drifted_signature


def test_baseline_content_signature_stable_for_equivalent_canonical_input():
    first = build_baseline_content_signature(_snapshot(elements=[_element("#a")]))
    second = build_baseline_content_signature(_snapshot(elements=[_element("#a")]))

    # Independently constructed but canonically identical payloads (no
    # shared Python object identity) must produce the same signature.
    assert first == second
    assert first == build_baseline_content_signature(BASELINE)


def test_baseline_content_signature_ignores_incidental_captured_at():
    without_captured_at = _snapshot(elements=[_element("#a")])
    with_captured_at = dict(without_captured_at)
    with_captured_at["captured_at"] = "2026-01-01T00:00:00.000000Z"

    # captured_at is the DOM capture instant, not baseline content: the
    # canonical identity deliberately ignores it, exactly as the existing
    # contract_watcher evidence identity ignores created_at.
    assert (
        build_baseline_content_signature(without_captured_at)
        == build_baseline_content_signature(with_captured_at)
    )


def test_baseline_reused_reference_with_canonically_identical_content_survives_restart(
    tmp_path,
):
    root = tmp_path / "evidence"
    target = _target()
    observation = _observation(
        reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
    )

    evidence_store_before = ContractWatcherEvidenceStore(root=root)
    history_store_before = ContractWatcherHistoryStore(root=root)

    run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store_before,
        history_store=history_store_before,
    )

    # Simulate a process restart against the same durable root: the
    # pinned baseline content identity must be read back from disk, not
    # from any in-memory cache, and must still accept the unchanged
    # canonical baseline.
    evidence_store_after = ContractWatcherEvidenceStore(root=root)
    history_store_after = ContractWatcherHistoryStore(root=root)

    replay = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store_after,
        history_store=history_store_after,
    )

    assert replay["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value


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


# ---------------------------------------------------------------------------
# QCC-CONTRACT-WATCHER-1F: restart-safe idempotent persisted-capture
# processing regression coverage.
# ---------------------------------------------------------------------------


def test_replay_vs_genuine_content_change_are_distinguishable(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    first = run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    replay = run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    genuinely_changed = run_contract_watcher_cycle(
        target,
        _observation(
            reference="cap-B2",
            contract=TRIPLE_DIVERGED,
            observed_at="2026-01-02T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert replay["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    assert replay["evidence_id"] == first["evidence_id"]
    assert replay["streak_count"] == 1

    assert (
        genuinely_changed["outcome"]
        == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )
    assert genuinely_changed["evidence_id"] != first["evidence_id"]
    assert genuinely_changed["semantic_signature"] != first["semantic_signature"]
    # A different structural change breaks the pending streak instead of
    # inheriting it: the second, distinct divergence starts back at 1.
    assert genuinely_changed["streak_count"] == 1
    assert (
        genuinely_changed["lifecycle_state"]
        == ContractWatchState.CHANGE_SUSPECTED.value
    )

    status = get_contract_watcher_lifecycle_status("ctr", history_store=history_store)
    assert status["history_length"] == 2


def test_reordered_processing_of_independent_targets_converges(tmp_path):
    def _requests():
        return [
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
        ]

    forward_evidence, forward_history = _stores(tmp_path / "forward")
    run_contract_watcher_cycle_batch(
        _requests(), evidence_store=forward_evidence, history_store=forward_history
    )

    reversed_requests = list(reversed(_requests()))
    reversed_evidence, reversed_history = _stores(tmp_path / "reversed")
    run_contract_watcher_cycle_batch(
        reversed_requests,
        evidence_store=reversed_evidence,
        history_store=reversed_history,
    )

    for contract_key in ("ctr-1", "ctr-2"):
        forward_status = get_contract_watcher_lifecycle_status(
            contract_key, history_store=forward_history
        )
        reversed_status = get_contract_watcher_lifecycle_status(
            contract_key, history_store=reversed_history
        )

        assert forward_status["lifecycle_state"] == reversed_status["lifecycle_state"]
        assert forward_status["streak_count"] == reversed_status["streak_count"]
        assert forward_status["history_length"] == reversed_status["history_length"]
        assert forward_status["entries"] == reversed_status["entries"]


def test_restart_of_partially_processed_batch_converges_without_duplicates(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    request_one = ContractWatcherCycleRequest(
        target=_target(contract_key="ctr-1"),
        observation=_observation(
            reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
        ),
    )
    request_two = ContractWatcherCycleRequest(
        target=_target(contract_key="ctr-2"),
        observation=_observation(
            reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
        ),
    )

    # Simulates a process that crashed after completing only the first
    # unit of work in what was meant to be a two-request batch.
    run_contract_watcher_cycle(
        request_one.target,
        request_one.observation,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    # Restart: rerun the FULL originally intended batch against the same
    # durable stores, exactly as a restarted worker would.
    restarted = run_contract_watcher_cycle_batch(
        [request_one, request_two],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert restarted["failed"] == 0
    assert restarted["processed"] == 2
    assert (
        restarted["results"][0]["outcome"]
        == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    )
    assert (
        restarted["results"][1]["outcome"]
        == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )

    status_one = get_contract_watcher_lifecycle_status(
        "ctr-1", history_store=history_store
    )
    assert status_one["history_length"] == 1


def test_out_of_order_observation_is_isolated_as_a_governed_batch_failure(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target(contract_key="ctr-1")

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    requests = [
        ContractWatcherCycleRequest(
            # A genuinely new capture for the same contract, but with a
            # timestamp that regresses relative to the last persisted
            # entry (e.g. clock skew or a stale-ordered retry).
            target=target,
            observation=_observation(
                reference="cap-B2",
                contract=TRIPLE_DIVERGED,
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
        ),
        ContractWatcherCycleRequest(
            target=_target(contract_key="ctr-2"),
            observation=_observation(
                reference="cap-B1", observed_at="2026-01-01T00:00:00.000000Z"
            ),
        ),
    ]

    result = run_contract_watcher_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert result["requested"] == 2
    assert result["processed"] == 1
    assert result["failed"] == 1
    assert result["failures"][0]["contract_key"] == "ctr-1"
    assert result["results"][0]["contract_key"] == "ctr-2"

    # The rejected retry must never have touched ctr-1's durable history.
    status_one = get_contract_watcher_lifecycle_status(
        "ctr-1", history_store=history_store
    )
    assert status_one["history_length"] == 1


def test_out_of_order_observation_raises_specific_cycle_error_type(tmp_path):
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    with pytest.raises(ContractWatcherObservationOrderingError):
        run_contract_watcher_cycle(
            target,
            _observation(
                reference="cap-B2",
                contract=TRIPLE_DIVERGED,
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
            evidence_store=evidence_store,
            history_store=history_store,
        )


def test_next_genuine_capture_after_ordering_rejection_converges(tmp_path):
    # Evidence identity (evidence_id) deliberately excludes created_at, so
    # an out-of-order attempt for a given reference cannot be "retried"
    # by merely re-timestamping the exact same reference: the first
    # write of that evidence identity permanently pins its created_at.
    # Restart-safe recovery instead comes from the normal, realistic
    # path already used by 1D/1E: the NEXT genuinely new capture
    # reference carries its own correctly-ordered timestamp and is
    # entirely unaffected by an earlier rejected sibling.
    evidence_store, history_store = _stores(tmp_path)
    target = _target()

    run_contract_watcher_cycle(
        target,
        _observation(reference="cap-B1", observed_at="2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    with pytest.raises(ContractWatcherObservationOrderingError):
        run_contract_watcher_cycle(
            target,
            _observation(
                reference="cap-B2",
                contract=TRIPLE_DIVERGED,
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
            evidence_store=evidence_store,
            history_store=history_store,
        )

    assert (
        get_contract_watcher_lifecycle_status("ctr", history_store=history_store)[
            "history_length"
        ]
        == 1
    )

    next_genuine = run_contract_watcher_cycle(
        target,
        _observation(
            reference="cap-B3",
            contract=TRIPLE_DIVERGED,
            observed_at="2026-01-03T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert (
        next_genuine["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )

    status = get_contract_watcher_lifecycle_status("ctr", history_store=history_store)
    assert status["history_length"] == 2

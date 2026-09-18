import json

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
)
from backend.qcc.auto_twin.contract_watcher_persisted_adapter import (
    ContractWatcherPersistedCaptureError,
    ContractWatcherPersistedCaptureRef,
    ContractWatcherPersistedCrossContractMismatchError,
    ContractWatcherPersistedWatchRequest,
    resolve_contract_watcher_persisted_cycle_inputs,
    resolve_persisted_site_contract,
    run_contract_watcher_persisted_cycle,
    run_contract_watcher_persisted_cycle_batch,
)
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore


PNG = b"\x89PNG\r\n\x1a\n" + b"fixture"


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


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


def _write_capture(
    root,
    *,
    capture_id,
    elements=(),
    pathname="/case/step",
    functional_state="STATE_A",
    site_code="GENERIC",
    profile_key="twin_discovery",
    schema_version=1,
):
    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    artifacts = {
        "raw_capture": "qcc_capture.json",
        "site_architecture": "site_architecture.json",
        "state_observation": "state_observation.json",
        "metadata": "metadata.json",
    }

    metadata = {
        "capture_id": capture_id,
        "site_code": site_code,
        "artifacts": artifacts,
        "retention": {"browser_profile_key": profile_key},
        "state_observation": {
            "state": functional_state,
            "fingerprint": "fingerprint-" + capture_id,
        },
    }

    _write_json(capture_dir / "metadata.json", metadata)

    _write_json(
        capture_dir / "qcc_capture.json",
        {
            "schema_version": 1,
            "browser_profile_key": profile_key,
            "main_url": "http://127.0.0.1:8767" + pathname,
        },
    )

    _write_json(
        capture_dir / "site_architecture.json",
        {
            "schema_version": schema_version,
            "page": {
                "pathname": pathname,
                "url": "http://127.0.0.1:8767" + pathname,
            },
            "viewport": {
                "inner_width": 1534,
                "inner_height": 911,
                "device_pixel_ratio": 1,
                "scroll_x": 0,
                "scroll_y": 0,
            },
            "elements": list(elements),
            "catalogs": [],
        },
    )

    _write_json(
        capture_dir / "state_observation.json",
        {
            "schema_version": 1,
            "state": functional_state,
            "fingerprint": "fingerprint-" + capture_id,
        },
    )

    return capture_dir


def _ref(root, capture_id):
    return ContractWatcherPersistedCaptureRef(capture_id=capture_id, root=root)


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _stores(tmp_path):
    return (
        ContractWatcherEvidenceStore(root=tmp_path / "evidence"),
        ContractWatcherHistoryStore(root=tmp_path / "evidence"),
    )


def test_resolve_persisted_site_contract_reads_capture(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])

    artifact = resolve_persisted_site_contract(_ref(root, "cap-A"))

    assert artifact["capture_id"] == "cap-A"
    assert artifact["pathname"] == "/case/step"
    assert artifact["functional_state"] == "STATE_A"
    assert artifact["site_contract"]["schema_version"] == 1
    assert len(artifact["site_contract"]["elements"]) == 1


def test_missing_capture_fails_closed(tmp_path):
    root = tmp_path / "site_architecture"
    root.mkdir()

    with pytest.raises(ContractWatcherPersistedCaptureError):
        resolve_persisted_site_contract(_ref(root, "missing"))


def test_unsupported_schema_version_fails_closed(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", schema_version=2)

    evidence_store, history_store = _stores(tmp_path)

    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-A"),
        confirmation_policy=_policy(),
    )

    with pytest.raises(ValueError):
        run_contract_watcher_persisted_cycle(
            request, evidence_store=evidence_store, history_store=history_store
        )


def test_first_persisted_divergent_observation_is_suspected(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root,
        capture_id="cap-B1",
        elements=[_element("#a"), _element("#b")],
    )

    evidence_store, history_store = _stores(tmp_path)

    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-01T00:00:00.000000Z",
    )

    receipt = run_contract_watcher_persisted_cycle(
        request, evidence_store=evidence_store, history_store=history_store
    )

    assert receipt["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert receipt["streak_count"] == 1
    assert receipt["baseline_capture_id"] == "cap-A"
    assert receipt["observation_capture_id"] == "cap-B1"
    assert receipt["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value


def test_second_distinct_persisted_observation_confirms_at_threshold(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )
    _write_capture(
        root, capture_id="cap-B2", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    def _request(observation_capture_id, observed_at):
        return ContractWatcherPersistedWatchRequest(
            contract_key="ctr",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, observation_capture_id),
            confirmation_policy=_policy(),
            observed_at=observed_at,
        )

    first = run_contract_watcher_persisted_cycle(
        _request("cap-B1", "2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    second = run_contract_watcher_persisted_cycle(
        _request("cap-B2", "2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert first["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert second["lifecycle_state"] == ContractWatchState.CHANGE_CONFIRMED.value
    assert second["streak_count"] == 2
    assert first["evidence_id"] != second["evidence_id"]
    assert first["semantic_signature"] == second["semantic_signature"]


def test_exact_artifact_replay_does_not_advance_streak(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-01T00:00:00.000000Z",
    )

    first = run_contract_watcher_persisted_cycle(
        request, evidence_store=evidence_store, history_store=history_store
    )

    replay = run_contract_watcher_persisted_cycle(
        request, evidence_store=evidence_store, history_store=history_store
    )

    assert first["evidence_id"] == replay["evidence_id"]
    assert replay["streak_count"] == 1
    assert replay["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value


def test_ambiguous_or_malformed_persisted_payload_fails_closed(tmp_path):
    root = tmp_path / "site_architecture"
    capture_dir = _write_capture(root, capture_id="cap-A", elements=[_element("#a")])

    (capture_dir / "site_architecture.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ContractWatcherPersistedCaptureError):
        resolve_persisted_site_contract(_ref(root, "cap-A"))


def test_cross_contract_pathname_mismatch_is_rejected(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(
        root, capture_id="cap-A", elements=[_element("#a")], pathname="/page/one"
    )
    _write_capture(
        root,
        capture_id="cap-B1",
        elements=[_element("#a"), _element("#b")],
        pathname="/page/two",
    )

    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
    )

    with pytest.raises(ContractWatcherPersistedCrossContractMismatchError):
        run_contract_watcher_persisted_cycle(request)


def test_reused_baseline_reference_with_changed_content_is_rejected(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-01T00:00:00.000000Z",
    )

    run_contract_watcher_persisted_cycle(
        request, evidence_store=evidence_store, history_store=history_store
    )

    # A second, DIFFERENT persisted capture directory that reuses the
    # SAME capture_id-as-reference for canonically different baseline
    # content -- a corrupted/hand-edited persisted fixture. Simulated by
    # re-pointing the ref at a distinct root with the same capture_id but
    # different content, which is exactly the identity 1C's baseline
    # content pin protects against.
    other_root = tmp_path / "site_architecture_drifted"
    _write_capture(
        other_root, capture_id="cap-A", elements=[_element("#a"), _element("#zzz")]
    )

    drifted_request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(other_root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-02T00:00:00.000000Z",
    )

    with pytest.raises(ContractWatcherBaselineIdentityError):
        run_contract_watcher_persisted_cycle(
            drifted_request, evidence_store=evidence_store, history_store=history_store
        )


def test_restart_with_fresh_stores_reproduces_lifecycle_state(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_root = tmp_path / "evidence"
    request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-01T00:00:00.000000Z",
    )

    before_restart = run_contract_watcher_persisted_cycle(
        request,
        evidence_store=ContractWatcherEvidenceStore(root=evidence_root),
        history_store=ContractWatcherHistoryStore(root=evidence_root),
    )

    after_restart = run_contract_watcher_persisted_cycle(
        request,
        evidence_store=ContractWatcherEvidenceStore(root=evidence_root),
        history_store=ContractWatcherHistoryStore(root=evidence_root),
    )

    assert before_restart["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    assert after_restart["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    assert after_restart["lifecycle_state"] == before_restart["lifecycle_state"]
    assert after_restart["streak_count"] == before_restart["streak_count"]
    assert after_restart["evidence_id"] == before_restart["evidence_id"]


def test_separate_contract_keys_remain_isolated(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    receipt_one = run_contract_watcher_persisted_cycle(
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-1",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-B1"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    receipt_two = run_contract_watcher_persisted_cycle(
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-2",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-A"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert receipt_one["lifecycle_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert receipt_two["lifecycle_state"] == ContractWatchState.NO_CHANGE.value

    status_one = get_contract_watcher_lifecycle_status("ctr-1", history_store=history_store)
    status_two = get_contract_watcher_lifecycle_status("ctr-2", history_store=history_store)

    assert status_one["history_length"] == 1
    assert status_two["history_length"] == 1


def test_batch_processes_independent_persisted_requests_deterministically(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    requests = [
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-1",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-B1"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-2",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-A"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
    ]

    result = run_contract_watcher_persisted_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert result["requested"] == 2
    assert result["processed"] == 2
    assert result["failed"] == 0
    assert [r["contract_key"] for r in result["results"]] == ["ctr-1", "ctr-2"]
    assert result["lifecycle_counts"] == {
        ContractWatchState.CHANGE_SUSPECTED.value: 1,
        ContractWatchState.NO_CHANGE.value: 1,
    }


def test_batch_records_persisted_resolution_failure_without_aborting_others(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    requests = [
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-1",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "missing-capture"),
            confirmation_policy=_policy(),
        ),
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-2",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-B1"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
    ]

    result = run_contract_watcher_persisted_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert result["requested"] == 2
    assert result["processed"] == 1
    assert result["failed"] == 1
    assert result["failures"][0]["contract_key"] == "ctr-1"
    assert result["results"][0]["contract_key"] == "ctr-2"


def test_batch_rejects_malformed_collection_and_items(tmp_path):
    evidence_store, history_store = _stores(tmp_path)

    with pytest.raises(TypeError):
        run_contract_watcher_persisted_cycle_batch(
            "not-a-list", evidence_store=evidence_store, history_store=history_store
        )

    with pytest.raises(TypeError):
        run_contract_watcher_persisted_cycle_batch(
            ["not-a-request"], evidence_store=evidence_store, history_store=history_store
        )


def test_malformed_request_fails_closed(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])

    with pytest.raises(ValueError):
        ContractWatcherPersistedWatchRequest(
            contract_key="",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-A"),
            confirmation_policy=_policy(),
        )

    with pytest.raises(TypeError):
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr",
            baseline_capture="not-a-ref",
            observation_capture=_ref(root, "cap-A"),
            confirmation_policy=_policy(),
        )

    with pytest.raises(TypeError):
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-A"),
            confirmation_policy=None,
        )


def test_resolve_cycle_inputs_type_checks_request():
    with pytest.raises(TypeError):
        resolve_contract_watcher_persisted_cycle_inputs("not-a-request")


# ---------------------------------------------------------------------------
# QCC-CONTRACT-WATCHER-1F: restart-safe idempotent persisted-capture
# processing regression coverage.
# ---------------------------------------------------------------------------


def test_duplicate_persisted_batch_replay_is_idempotent(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    requests = [
        ContractWatcherPersistedWatchRequest(
            contract_key="ctr-1",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, "cap-B1"),
            confirmation_policy=_policy(),
            observed_at="2026-01-01T00:00:00.000000Z",
        ),
    ]

    first_run = run_contract_watcher_persisted_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    # Repeated processing of the exact same persisted capture pair, as a
    # restarted worker (or a scheduler tick that overlaps a previous one)
    # would do, must never duplicate the observation.
    second_run = run_contract_watcher_persisted_cycle_batch(
        requests, evidence_store=evidence_store, history_store=history_store
    )

    assert first_run["results"][0]["outcome"] == (
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )
    assert second_run["results"][0]["outcome"] == (
        ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    )
    assert second_run["failed"] == 0

    status = get_contract_watcher_lifecycle_status("ctr-1", history_store=history_store)
    assert status["history_length"] == 1


def test_reordered_persisted_batch_converges_to_same_state(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    def _requests():
        return [
            ContractWatcherPersistedWatchRequest(
                contract_key="ctr-1",
                baseline_capture=_ref(root, "cap-A"),
                observation_capture=_ref(root, "cap-B1"),
                confirmation_policy=_policy(),
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
            ContractWatcherPersistedWatchRequest(
                contract_key="ctr-2",
                baseline_capture=_ref(root, "cap-A"),
                observation_capture=_ref(root, "cap-A"),
                confirmation_policy=_policy(),
                observed_at="2026-01-01T00:00:00.000000Z",
            ),
        ]

    forward_evidence, forward_history = _stores(tmp_path / "forward")
    run_contract_watcher_persisted_cycle_batch(
        _requests(), evidence_store=forward_evidence, history_store=forward_history
    )

    reversed_evidence, reversed_history = _stores(tmp_path / "reversed")
    run_contract_watcher_persisted_cycle_batch(
        list(reversed(_requests())),
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

        assert forward_status["entries"] == reversed_status["entries"]


def test_restart_after_partial_persisted_batch_failure_converges(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )

    evidence_store, history_store = _stores(tmp_path)

    unresolvable_request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr-1",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "missing-capture"),
        confirmation_policy=_policy(),
    )
    valid_request = ContractWatcherPersistedWatchRequest(
        contract_key="ctr-2",
        baseline_capture=_ref(root, "cap-A"),
        observation_capture=_ref(root, "cap-B1"),
        confirmation_policy=_policy(),
        observed_at="2026-01-01T00:00:00.000000Z",
    )

    interrupted = run_contract_watcher_persisted_cycle_batch(
        [unresolvable_request, valid_request],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert interrupted["processed"] == 1
    assert interrupted["failed"] == 1

    # Restart: the missing capture is now available (e.g. ingestion
    # finished after the first pass), and the same logical batch is
    # replayed in full.
    _write_capture(
        root, capture_id="missing-capture", elements=[_element("#a"), _element("#c")]
    )

    restarted = run_contract_watcher_persisted_cycle_batch(
        [unresolvable_request, valid_request],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert restarted["processed"] == 2
    assert restarted["failed"] == 0
    assert restarted["results"][0]["contract_key"] == "ctr-1"
    assert restarted["results"][0]["outcome"] == (
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )
    assert restarted["results"][1]["outcome"] == (
        ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    )

    status_two = get_contract_watcher_lifecycle_status("ctr-2", history_store=history_store)
    assert status_two["history_length"] == 1


def test_genuine_changed_capture_vs_replay_are_distinguishable(tmp_path):
    root = tmp_path / "site_architecture"
    _write_capture(root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        root, capture_id="cap-B1", elements=[_element("#a"), _element("#b")]
    )
    _write_capture(
        root,
        capture_id="cap-B2",
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    evidence_store, history_store = _stores(tmp_path)

    def _request(observation_capture_id, observed_at):
        return ContractWatcherPersistedWatchRequest(
            contract_key="ctr",
            baseline_capture=_ref(root, "cap-A"),
            observation_capture=_ref(root, observation_capture_id),
            confirmation_policy=_policy(),
            observed_at=observed_at,
        )

    first = run_contract_watcher_persisted_cycle(
        _request("cap-B1", "2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    replay = run_contract_watcher_persisted_cycle(
        _request("cap-B1", "2026-01-01T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    genuinely_changed = run_contract_watcher_persisted_cycle(
        _request("cap-B2", "2026-01-02T00:00:00.000000Z"),
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert replay["outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value
    assert replay["evidence_id"] == first["evidence_id"]

    assert genuinely_changed["outcome"] == (
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    )
    assert genuinely_changed["evidence_id"] != first["evidence_id"]
    assert genuinely_changed["semantic_signature"] != first["semantic_signature"]

    status = get_contract_watcher_lifecycle_status("ctr", history_store=history_store)
    assert status["history_length"] == 2

import json

import pytest

from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_lifecycle import (
    get_contract_watcher_lifecycle_status,
)
from backend.qcc.auto_twin.contract_watcher_persisted_backlog import (
    CONTRACT_WATCHER_BACKLOG_SKIP_BASELINE_CAPTURE_UNREADABLE,
    CONTRACT_WATCHER_BACKLOG_SKIP_NOTHING_PENDING,
    CONTRACT_WATCHER_BACKLOG_SKIP_STATE_NOT_BASELINED,
    select_contract_watcher_persisted_backlog,
)
from backend.qcc.auto_twin.contract_watcher_pipeline import ContractWatcherCycleOutcome
from backend.qcc.auto_twin.contract_watcher_persisted_adapter import (
    ContractWatcherPersistedWatchRequest,
    run_contract_watcher_persisted_cycle,
    run_contract_watcher_persisted_cycle_batch,
)
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import (
    AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION,
    AUTO_TWIN_OBSERVATION_STORE_TYPE,
    AutoTwinObservationStore,
)


ORIGIN = "http://127.0.0.1:8767"

T1 = "2026-01-01T00:00:00.000000+00:00"
T2 = "2026-01-02T00:00:00.000000+00:00"
T3 = "2026-01-03T00:00:00.000000+00:00"


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _site(twin_key, site_code):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(ORIGIN,),
    )


def _observe(store, site, *, capture_id, fingerprint, pathname="/case/step",
             state="STATE_A", observed_at="2026-01-01T00:00:00.000000Z"):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=observed_at,
        browser_profile_key="twin_discovery",
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"state": state, "fingerprint": fingerprint},
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


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_capture(root, *, capture_id, received_at, elements=(), pathname="/case/step",
                    functional_state="STATE_A", site_code="GENERIC"):
    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    state_observation = {
        "state": functional_state,
        "fingerprint": "fingerprint-" + capture_id,
    }

    metadata = {
        "capture_id": capture_id,
        "site_code": site_code,
        "received_at": received_at,
        "page": {"url": ORIGIN + pathname, "title": "t"},
        "artifacts": {
            "raw_capture": "qcc_capture.json",
            "site_architecture": "site_architecture.json",
            "state_observation": "state_observation.json",
            "metadata": "metadata.json",
        },
        "retention": {"browser_profile_key": "twin_discovery"},
        "state_observation": state_observation,
    }

    _write_json(capture_dir / "metadata.json", metadata)

    _write_json(
        capture_dir / "qcc_capture.json",
        {
            "schema_version": 1,
            "browser_profile_key": "twin_discovery",
            "main_url": ORIGIN + pathname,
        },
    )

    _write_json(
        capture_dir / "site_architecture.json",
        {
            "schema_version": 1,
            "page": {"pathname": pathname, "url": ORIGIN + pathname},
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
        {"schema_version": 1, **state_observation},
    )

    return capture_dir


def _write_malformed_capture(root, *, capture_id, received_at, pathname="/case/step",
                              functional_state="STATE_A", site_code="GENERIC"):
    """A capture that is enumerable (valid metadata.json) but never resolvable.

    ``site_architecture.json`` deliberately omits the required ``page``
    key, so ``load_auto_twin_persisted_capture_bundle`` fails closed with
    ``QCC_AUTO_TWIN_PERSISTED_CAPTURE_PAGE_INVALID``.
    """

    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    metadata = {
        "capture_id": capture_id,
        "site_code": site_code,
        "received_at": received_at,
        "page": {"url": ORIGIN + pathname, "title": "t"},
        "artifacts": {
            "raw_capture": "qcc_capture.json",
            "site_architecture": "site_architecture.json",
            "state_observation": "state_observation.json",
            "metadata": "metadata.json",
        },
        "retention": {"browser_profile_key": "twin_discovery"},
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
            "browser_profile_key": "twin_discovery",
            "main_url": ORIGIN + pathname,
        },
    )

    _write_json(
        capture_dir / "site_architecture.json",
        {
            "schema_version": 1,
            "viewport": {
                "inner_width": 1534,
                "inner_height": 911,
                "device_pixel_ratio": 1,
                "scroll_x": 0,
                "scroll_y": 0,
            },
            "elements": [],
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


def _stores(tmp_path):
    return (
        ContractWatcherEvidenceStore(root=tmp_path / "evidence"),
        ContractWatcherHistoryStore(root=tmp_path / "evidence"),
    )


# ---------------------------------------------------------------------------
# Core no-skip backlog behaviour.
# ---------------------------------------------------------------------------


def test_all_pending_captures_after_baseline_are_selected_in_order(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    # Both B and C land before any select+batch pass ever runs -- the
    # boundary QCC-CONTRACT-WATCHER-1F documented and left open.
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert selection["skipped"] == []
    assert [
        request.observation_capture.capture_id for request in selection["selected"]
    ] == ["cap-B", "cap-C"]
    assert all(
        request.baseline_capture.capture_id == "cap-A"
        for request in selection["selected"]
    )
    assert all(
        isinstance(request, ContractWatcherPersistedWatchRequest)
        for request in selection["selected"]
    )

    batch_result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert batch_result["requested"] == 2
    assert batch_result["processed"] == 2
    assert batch_result["failed"] == 0

    contract_key = selection["selected"][0].contract_key

    status = get_contract_watcher_lifecycle_status(
        contract_key, history_store=history_store
    )
    assert status["history_length"] == 2

    evidenced_captures = {
        record["after_reference"] for record in evidence_store.list(contract_key=contract_key)
    }
    assert evidenced_captures == {"cap-B", "cap-C"}


def test_restart_after_first_pending_capture_succeeds_selects_only_remaining(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    first_selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [
        request.observation_capture.capture_id
        for request in first_selection["selected"]
    ] == ["cap-B", "cap-C"]

    # Simulates a worker that completed exactly the first pending capture
    # (cap-B) before restarting -- cap-C's cycle never ran.
    run_contract_watcher_persisted_cycle(
        first_selection["selected"][0],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    second_selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [
        request.observation_capture.capture_id
        for request in second_selection["selected"]
    ] == ["cap-C"]


def test_repeated_select_and_batch_over_drained_backlog_is_convergent(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    def _cycle():
        selection = select_contract_watcher_persisted_backlog(
            store,
            confirmation_policy=_policy(),
            capture_root=capture_root,
            evidence_store=evidence_store,
            history_store=history_store,
        )
        result = run_contract_watcher_persisted_cycle_batch(
            selection["selected"],
            evidence_store=evidence_store,
            history_store=history_store,
        )
        return selection, result

    first_selection, first_result = _cycle()
    assert first_result["processed"] == 2

    contract_key = first_selection["selected"][0].contract_key

    # Overlapping scheduler tick / restarted worker re-deriving the
    # backlog over an already fully drained inventory.
    second_selection, second_result = _cycle()

    assert second_selection["selected"] == []
    assert second_result["requested"] == 0

    status = get_contract_watcher_lifecycle_status(
        contract_key, history_store=history_store
    )
    assert status["history_length"] == 2


def test_replay_of_same_backlog_requests_creates_no_duplicate_evidence(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    first_result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [record["outcome"] for record in first_result["results"]] == [
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value,
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value,
    ]

    # The exact same, already-selected requests are replayed (e.g. a
    # stale in-memory batch retried after a transient network blip).
    replay_result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [record["outcome"] for record in replay_result["results"]] == [
        ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value,
        ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value,
    ]

    contract_key = selection["selected"][0].contract_key
    status = get_contract_watcher_lifecycle_status(
        contract_key, history_store=history_store
    )
    assert status["history_length"] == 2


def test_malformed_intermediate_capture_does_not_suppress_valid_later_capture(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_malformed_capture(capture_root, capture_id="cap-B", received_at=T2)
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [
        request.observation_capture.capture_id for request in selection["selected"]
    ] == ["cap-B", "cap-C"]

    result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["requested"] == 2
    assert result["processed"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["observation_capture_id"] == "cap-C"
    assert result["failures"][0]["request_id"].endswith(":cap-B")

    # cap-B was never durably evidenced: it remains deterministically
    # discoverable/retryable on the next pass. cap-C is now excluded
    # (already independently evidenced).
    second_selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert [
        request.observation_capture.capture_id
        for request in second_selection["selected"]
    ] == ["cap-B"]


def test_genuinely_changed_later_capture_remains_distinguishable(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    evidence_ids = [record["evidence_id"] for record in result["results"]]
    semantic_signatures = [record["semantic_signature"] for record in result["results"]]

    assert len(set(evidence_ids)) == 2
    assert len(set(semantic_signatures)) == 2


def test_separate_contract_keys_remain_isolated(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(
        capture_root, capture_id="cap-A1", received_at=T1, pathname="/a",
        elements=[_element("#a")],
    )
    _write_capture(
        capture_root, capture_id="cap-B1", received_at=T2, pathname="/a",
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-A2", received_at=T1, pathname="/b",
        elements=[_element("#x")],
    )
    _write_capture(
        capture_root, capture_id="cap-B2", received_at=T2, pathname="/b",
        elements=[_element("#x"), _element("#y")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site_a = _site("twin-a", "SITE_A")
    site_b = _site("twin-b", "SITE_B")

    _observe(store, site_a, capture_id="cap-A1", fingerprint="fp-a1", pathname="/a", observed_at=T1)
    _observe(store, site_a, capture_id="cap-B1", fingerprint="fp-b1", pathname="/a", observed_at=T2)
    _observe(store, site_b, capture_id="cap-A2", fingerprint="fp-a2", pathname="/b", observed_at=T1)
    _observe(store, site_b, capture_id="cap-B2", fingerprint="fp-b2", pathname="/b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert len(selection["selected"]) == 2

    contract_keys = {request.contract_key for request in selection["selected"]}
    assert len(contract_keys) == 2

    observed_captures = {
        request.contract_key: request.observation_capture.capture_id
        for request in selection["selected"]
    }
    assert set(observed_captures.values()) == {"cap-B1", "cap-B2"}

    result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["processed"] == 2

    for contract_key in contract_keys:
        status = get_contract_watcher_lifecycle_status(
            contract_key, history_store=history_store
        )
        assert status["history_length"] == 1


# ---------------------------------------------------------------------------
# Skip / fail-closed reporting.
# ---------------------------------------------------------------------------


def test_state_without_baseline_is_skipped_not_raised(tmp_path):
    path = tmp_path / "observation_state.json"

    payload = {
        "schema_version": AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION,
        "store_type": AUTO_TWIN_OBSERVATION_STORE_TYPE,
        "revision": 1,
        "twins": {
            "twin-a": {
                "twin_key": "twin-a",
                "site_code": "SITE_A",
                "states": {
                    "state-1": {
                        "state_key": "state-1",
                        "pathname": "/case/step",
                        "functional_state": "STATE_A",
                        "baseline_fingerprint": None,
                        "baseline_capture_id": None,
                        "last_fingerprint": None,
                        "last_capture_id": None,
                        "observation_count": 0,
                        "last_classification": "UNKNOWN",
                    },
                },
                "last_observation": None,
            },
        },
    }

    path.write_text(json.dumps(payload), encoding="utf-8")

    store = AutoTwinObservationStore(path=path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert selection["selected"] == []
    assert len(selection["skipped"]) == 1
    assert selection["skipped"][0]["reason"] == (
        CONTRACT_WATCHER_BACKLOG_SKIP_STATE_NOT_BASELINED
    )


def test_no_pending_captures_beyond_baseline_is_skipped(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert selection["selected"] == []
    assert len(selection["skipped"]) == 1
    assert selection["skipped"][0]["reason"] == (
        CONTRACT_WATCHER_BACKLOG_SKIP_NOTHING_PENDING
    )


def test_missing_baseline_capture_on_disk_is_skipped_not_raised(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    # cap-A is registered as baseline in AUTO TWIN bookkeeping but was
    # never (or is no longer) materialized on the persisted capture root.
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert selection["selected"] == []
    assert len(selection["skipped"]) == 1
    assert selection["skipped"][0]["reason"] == (
        CONTRACT_WATCHER_BACKLOG_SKIP_BASELINE_CAPTURE_UNREADABLE
    )


# ---------------------------------------------------------------------------
# Determinism / non-mutation / input validation.
# ---------------------------------------------------------------------------


def test_selection_ordering_is_stable_across_repeated_calls(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )
    _write_capture(
        capture_root, capture_id="cap-C", received_at=T3,
        elements=[_element("#a"), _element("#b"), _element("#c")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    first = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    second = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    first_order = [request.observation_capture.capture_id for request in first["selected"]]
    second_order = [request.observation_capture.capture_id for request in second["selected"]]

    assert first_order == second_order == ["cap-B", "cap-C"]


def test_selector_never_mutates_observation_store_or_evidence(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(
        capture_root, capture_id="cap-B", received_at=T2,
        elements=[_element("#a"), _element("#b")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    before = store.snapshot()

    selection = select_contract_watcher_persisted_backlog(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    after = store.snapshot()

    assert before == after
    assert evidence_store.list() == []

    contract_key = selection["selected"][0].contract_key
    assert history_store.list_entries(contract_key=contract_key) == []


def test_backlog_rejects_invalid_observation_store_type():
    with pytest.raises(TypeError):
        select_contract_watcher_persisted_backlog(
            "not-a-store",
            confirmation_policy=_policy(),
        )


def test_backlog_requires_confirmation_policy(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")

    with pytest.raises(TypeError):
        select_contract_watcher_persisted_backlog(
            store,
            confirmation_policy=None,
        )


def test_malformed_snapshot_fails_closed(tmp_path):
    class _BrokenSnapshotStore(AutoTwinObservationStore):
        def __init__(self, *, path, broken_payload):
            super().__init__(path=path)
            self._broken_payload = broken_payload

        def snapshot(self, twin_key=None, *, current_only=False):
            return self._broken_payload

    store = _BrokenSnapshotStore(
        path=tmp_path / "observation_state.json",
        broken_payload={"twins": "not-a-dict"},
    )

    evidence_store, history_store = _stores(tmp_path)

    with pytest.raises(ValueError):
        select_contract_watcher_persisted_backlog(
            store,
            confirmation_policy=_policy(),
            capture_root=tmp_path / "site_architecture",
            evidence_store=evidence_store,
            history_store=history_store,
        )

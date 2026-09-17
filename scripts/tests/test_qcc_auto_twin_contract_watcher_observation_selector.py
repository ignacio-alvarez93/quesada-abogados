import json

import pytest

from backend.qcc.auto_twin.contract_watcher import ContractWatchState
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_observation_selector import (
    CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE,
    CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED,
    contract_watcher_observation_contract_key,
    select_contract_watcher_persisted_watch_requests,
)
from backend.qcc.auto_twin.contract_watcher_persisted_adapter import (
    ContractWatcherPersistedWatchRequest,
    run_contract_watcher_persisted_cycle_batch,
)
from backend.qcc.auto_twin.contract_watcher_store import (
    _SAFE_SEGMENT_RE,
    ContractWatcherEvidenceStore,
)
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import (
    AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION,
    AUTO_TWIN_OBSERVATION_STORE_TYPE,
    AutoTwinObservationStore,
)


ORIGIN = "http://127.0.0.1:8767"


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _site(twin_key, site_code, *, discover_unknown_states=True):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(ORIGIN,),
        discover_unknown_states=discover_unknown_states,
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


def _write_capture(root, *, capture_id, elements=(), pathname="/case/step",
                    functional_state="STATE_A", site_code="GENERIC"):
    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    metadata = {
        "capture_id": capture_id,
        "site_code": site_code,
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
        {
            "schema_version": 1,
            "state": functional_state,
            "fingerprint": "fingerprint-" + capture_id,
        },
    )

    return capture_dir


class _BrokenSnapshotStore(AutoTwinObservationStore):
    """Test-only store subclass returning a structurally invalid snapshot."""

    def __init__(self, *, path, broken_payload):
        super().__init__(path=path)
        self._broken_payload = broken_payload

    def snapshot(self, twin_key=None, *, current_only=False):
        return self._broken_payload


def test_contract_key_convention_is_deterministic():
    first = contract_watcher_observation_contract_key("twin-a", "state-1")
    second = contract_watcher_observation_contract_key("twin-a", "state-1")

    assert first == second

    with pytest.raises(ValueError):
        contract_watcher_observation_contract_key("", "state-1")


def test_contract_key_same_pair_yields_same_key():
    assert contract_watcher_observation_contract_key(
        "twin-a", "state-1"
    ) == contract_watcher_observation_contract_key("twin-a", "state-1")


def test_contract_key_distinct_pairs_yield_distinct_keys():
    keys = {
        contract_watcher_observation_contract_key("twin-a", "state-1"),
        contract_watcher_observation_contract_key("twin-a", "state-2"),
        contract_watcher_observation_contract_key("twin-b", "state-1"),
        contract_watcher_observation_contract_key("twin-b", "state-2"),
    }

    assert len(keys) == 4


def test_contract_key_ambiguous_concatenation_pairs_cannot_collide():
    adversarial_pairs = [
        (("a::b", "c"), ("a", "b::c")),
        (("a:b", "c"), ("a", "b:c")),
        (("ab", "c"), ("a", "bc")),
        (('a"b', "c"), ("a", 'b"c')),
        (("a\\", "b"), ("a", "\\b")),
    ]

    for (left_twin, left_state), (right_twin, right_state) in adversarial_pairs:
        left_key = contract_watcher_observation_contract_key(left_twin, left_state)
        right_key = contract_watcher_observation_contract_key(right_twin, right_state)

        assert left_key != right_key


def test_contract_key_satisfies_history_store_safe_segment_validator(tmp_path):
    keys = [
        contract_watcher_observation_contract_key("twin-a", "state-1"),
        contract_watcher_observation_contract_key("twin-a::b", "state-1"),
        contract_watcher_observation_contract_key("a", "b::c"),
        contract_watcher_observation_contract_key("weird key/with spaces", "..\\..\\etc"),
    ]

    history_store = ContractWatcherHistoryStore(root=tmp_path / "evidence")

    for key in keys:
        assert _SAFE_SEGMENT_RE.fullmatch(key)

        # Must not raise QCC_CONTRACT_WATCHER_HISTORY_CONTRACT_KEY_INVALID.
        history_store.history_path(contract_key=key)


def test_derives_request_for_known_state_with_distinct_captures(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a")
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b")

    result = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert result["skipped"] == []
    assert len(result["selected"]) == 1

    request = result["selected"][0]

    assert isinstance(request, ContractWatcherPersistedWatchRequest)
    assert request.baseline_capture.capture_id == "cap-A"
    assert request.observation_capture.capture_id == "cap-B"

    observed_state_key = next(iter(store.snapshot()["twins"]["twin-a"]["states"]))

    assert request.contract_key == contract_watcher_observation_contract_key(
        "twin-a", observed_state_key
    )


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

    result = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert result["selected"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == (
        CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED
    )
    assert result["skipped"][0]["twin_key"] == "twin-a"
    assert result["skipped"][0]["state_key"] == "state-1"


def test_baseline_equal_to_last_capture_is_skipped(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a")

    result = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert result["selected"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == (
        CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE
    )


def test_multiple_entries_have_stable_deterministic_ordering(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")

    site_b = _site("twin-b", "SITE_B")
    site_a = _site("twin-a", "SITE_A")

    _observe(store, site_b, capture_id="cap-B1", fingerprint="fp-1", pathname="/b")
    _observe(store, site_b, capture_id="cap-B2", fingerprint="fp-2", pathname="/b")

    _observe(store, site_a, capture_id="cap-A1", fingerprint="fp-1", pathname="/a")
    _observe(store, site_a, capture_id="cap-A2", fingerprint="fp-2", pathname="/a")

    first = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    second = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    first_keys = [request.contract_key for request in first["selected"]]
    second_keys = [request.contract_key for request in second["selected"]]

    assert first_keys == second_keys

    snapshot = store.snapshot()
    state_key_a = next(iter(snapshot["twins"]["twin-a"]["states"]))
    state_key_b = next(iter(snapshot["twins"]["twin-b"]["states"]))

    assert first_keys[0] == contract_watcher_observation_contract_key(
        "twin-a", state_key_a
    )
    assert first_keys[1] == contract_watcher_observation_contract_key(
        "twin-b", state_key_b
    )


def test_selector_never_mutates_observation_store(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a")
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b")

    before = store.snapshot()

    select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    after = store.snapshot()

    assert before == after


def test_selector_rejects_invalid_observation_store_type():
    with pytest.raises(TypeError):
        select_contract_watcher_persisted_watch_requests(
            "not-a-store",
            confirmation_policy=_policy(),
        )


def test_selector_requires_confirmation_policy(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")

    with pytest.raises(TypeError):
        select_contract_watcher_persisted_watch_requests(
            store,
            confirmation_policy=None,
        )


def test_malformed_snapshot_fails_closed(tmp_path):
    store = _BrokenSnapshotStore(
        path=tmp_path / "observation_state.json",
        broken_payload={"twins": "not-a-dict"},
    )

    with pytest.raises(ValueError):
        select_contract_watcher_persisted_watch_requests(
            store,
            confirmation_policy=_policy(),
        )

    store_bad_states = _BrokenSnapshotStore(
        path=tmp_path / "observation_state_2.json",
        broken_payload={"twins": {"twin-a": {"states": "not-a-dict"}}},
    )

    with pytest.raises(ValueError):
        select_contract_watcher_persisted_watch_requests(
            store_bad_states,
            confirmation_policy=_policy(),
        )


def test_selected_requests_round_trip_through_persisted_cycle_batch(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", elements=[_element("#a")])
    _write_capture(
        capture_root,
        capture_id="cap-B",
        elements=[_element("#a"), _element("#b")],
    )

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a")
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b")

    result = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=capture_root,
    )

    assert len(result["selected"]) == 1

    evidence_store = ContractWatcherEvidenceStore(root=tmp_path / "evidence")
    history_store = ContractWatcherHistoryStore(root=tmp_path / "evidence")

    batch_result = run_contract_watcher_persisted_cycle_batch(
        result["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert batch_result["requested"] == 1
    assert batch_result["processed"] == 1
    assert batch_result["failed"] == 0
    assert batch_result["lifecycle_counts"] == {
        ContractWatchState.CHANGE_SUSPECTED.value: 1,
    }
    assert batch_result["results"][0]["baseline_capture_id"] == "cap-A"
    assert batch_result["results"][0]["observation_capture_id"] == "cap-B"


def test_selected_request_with_deleted_persisted_capture_fails_closed_via_batch(tmp_path):
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a")
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b")

    result = select_contract_watcher_persisted_watch_requests(
        store,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert len(result["selected"]) == 1

    evidence_store = ContractWatcherEvidenceStore(root=tmp_path / "evidence")
    history_store = ContractWatcherHistoryStore(root=tmp_path / "evidence")

    batch_result = run_contract_watcher_persisted_cycle_batch(
        result["selected"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert batch_result["requested"] == 1
    assert batch_result["processed"] == 0
    assert batch_result["failed"] == 1
    assert batch_result["failures"][0]["contract_key"] == result["selected"][0].contract_key

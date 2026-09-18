"""QCC Contract Watcher — retention interlock regressions (Work Order 1H).

Covers the AUTO TWIN side of the retention-protection contract:

- ``contract_watcher_governed_protected_capture_ids`` (the durable
  protected-set computation, reusing 1G's own enumeration/ordering/
  "already evidenced" helpers);
- ``contract_watcher_retention_protected_capture_id_provider`` (the
  smallest adapter wrapping it into the zero-arg callable
  ``QccSiteArchitectureIngestor(protected_capture_ids=...)`` expects);
- the full end-to-end interlock, wiring a real
  ``QccSiteArchitectureIngestor`` retention ring together with the
  adapter over a shared persisted capture root, with deliberately small
  retention limits.
"""

import json

import pytest

from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_persisted_adapter import (
    run_contract_watcher_persisted_cycle_batch,
)
from backend.qcc.auto_twin.contract_watcher_persisted_backlog import (
    contract_watcher_governed_protected_capture_ids,
    select_contract_watcher_persisted_backlog,
)
from backend.qcc.auto_twin.contract_watcher_retention_adapter import (
    contract_watcher_retention_protected_capture_id_provider,
)
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore
from backend.qcc.site_architecture.ingestor import QccSiteArchitectureIngestor


ORIGIN = "http://127.0.0.1:8767"
RETENTION_PROFILE = "twin_discovery"

T1 = "2026-01-01T00:00:00.000000+00:00"
T2 = "2026-01-02T00:00:00.000000+00:00"
T3 = "2026-01-03T00:00:00.000000+00:00"
T4 = "2026-01-04T00:00:00.000000+00:00"


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _site(twin_key, site_code):
    return AutoTwinManagedSite(twin_key=twin_key, site_code=site_code, origins=(ORIGIN,))


def _observe(store, site, *, capture_id, fingerprint, pathname="/case/step",
             state="STATE_A", observed_at=T1):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=observed_at,
        browser_profile_key=RETENTION_PROFILE,
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
                    functional_state="STATE_A", site_code="GENERIC", scope="GENERAL"):
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
        "retention": {
            "mode": "PROFILE_ORIGIN_ARCHITECTURE_SCOPE_RING",
            "browser_profile_key": RETENTION_PROFILE,
            "origin": ORIGIN,
            "architecture_scope": scope,
            "functional_state": functional_state,
        },
        "state_observation": state_observation,
    }

    _write_json(capture_dir / "metadata.json", metadata)

    _write_json(
        capture_dir / "qcc_capture.json",
        {
            "schema_version": 1,
            "browser_profile_key": RETENTION_PROFILE,
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
                              functional_state="STATE_A", site_code="GENERIC", scope="GENERAL"):
    """Enumerable (valid metadata.json) but never resolvable by 1C/1D."""

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
        "retention": {
            "mode": "PROFILE_ORIGIN_ARCHITECTURE_SCOPE_RING",
            "browser_profile_key": RETENTION_PROFILE,
            "origin": ORIGIN,
            "architecture_scope": scope,
            "functional_state": functional_state,
        },
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
            "browser_profile_key": RETENTION_PROFILE,
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


def _stores(tmp_path, *, name="evidence"):
    return (
        ContractWatcherEvidenceStore(root=tmp_path / name),
        ContractWatcherHistoryStore(root=tmp_path / name),
    )


def _scope(*, scope="GENERAL"):
    return {
        "browser_profile_key": RETENTION_PROFILE,
        "origin": ORIGIN,
        "architecture_scope": scope,
    }


# ---------------------------------------------------------------------------
# contract_watcher_governed_protected_capture_ids
# ---------------------------------------------------------------------------


def test_baseline_and_all_unevidenced_captures_are_protected(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    protected = contract_watcher_governed_protected_capture_ids(
        store,
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert protected == {"cap-A", "cap-B", "cap-C"}


def test_durably_evidenced_capture_is_no_longer_protected(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)
    _observe(store, site, capture_id="cap-C", fingerprint="fp-c", observed_at=T3)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    contract_key = selection["selected"][0].contract_key

    # Only cap-B is durably evidenced; cap-C is left pending.
    run_contract_watcher_persisted_cycle_batch(
        [request for request in selection["selected"] if request.observation_capture.capture_id == "cap-B"],
        evidence_store=evidence_store,
        history_store=history_store,
    )

    protected = contract_watcher_governed_protected_capture_ids(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    assert protected == {"cap-A", "cap-C"}
    assert contract_key  # sanity: a governed contract actually exists


def test_unobserved_captures_are_never_protected(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    evidence_store, history_store = _stores(tmp_path)

    protected = contract_watcher_governed_protected_capture_ids(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    assert protected == frozenset()


def test_governed_protection_raises_on_evidence_history_inconsistency(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")

    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    run_contract_watcher_persisted_cycle_batch(
        selection["selected"], evidence_store=evidence_store, history_store=history_store,
    )

    contract_key = selection["selected"][0].contract_key

    # Corrupt durable state: delete the evidence a history entry references.
    entry = history_store.list_entries(contract_key=contract_key)[0]
    evidence_path = evidence_store.evidence_path(
        contract_key=contract_key, evidence_id=entry["evidence_id"],
    )
    evidence_path.unlink()

    with pytest.raises(ValueError):
        contract_watcher_governed_protected_capture_ids(
            store, capture_root=capture_root,
            evidence_store=evidence_store, history_store=history_store,
        )


def test_governed_protection_rejects_invalid_observation_store_type():
    with pytest.raises(TypeError):
        contract_watcher_governed_protected_capture_ids("not-a-store")


# ---------------------------------------------------------------------------
# contract_watcher_retention_protected_capture_id_provider
# ---------------------------------------------------------------------------


def test_adapter_rejects_invalid_observation_store_type():
    with pytest.raises(TypeError):
        contract_watcher_retention_protected_capture_id_provider("not-a-store")


def test_adapter_provider_recomputes_durably_every_call(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    assert provider() == {"cap-A", "cap-B"}

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    run_contract_watcher_persisted_cycle_batch(
        selection["selected"], evidence_store=evidence_store, history_store=history_store,
    )

    assert provider() == {"cap-A"}


def test_adapter_provider_propagates_resolution_failure(tmp_path):
    capture_root = tmp_path / "site_architecture"
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")

    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
    )

    class _BrokenSnapshotStore(AutoTwinObservationStore):
        def snapshot(self, twin_key=None, *, current_only=False):
            raise RuntimeError("QCC_TEST_SNAPSHOT_UNAVAILABLE")

    broken_provider = contract_watcher_retention_protected_capture_id_provider(
        _BrokenSnapshotStore(path=tmp_path / "observation_state.json"),
        capture_root=capture_root,
    )

    with pytest.raises(RuntimeError):
        broken_provider()

    # Sanity: the well-formed provider still works.
    assert provider() == frozenset()


# ---------------------------------------------------------------------------
# Full interlock: real retention ring + adapter, deliberately small limits.
# ---------------------------------------------------------------------------


def test_baseline_survives_small_retention_limit(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)
    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=1,
        protected_capture_ids=provider,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-C", scope=_scope())

    # cap-B/cap-C also match the same governed, already-baselined
    # contract identity and have never been independently evidenced
    # either, so the ring protects all three rather than guess.
    assert removed == []
    assert (capture_root / "cap-A").exists()


def test_pending_capture_survives_while_unevidenced_after_newer_arrive(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])
    _write_capture(capture_root, capture_id="cap-D", received_at=T4, elements=[_element("#a"), _element("#b"), _element("#c"), _element("#d")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)
    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=2,
        protected_capture_ids=provider,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-D", scope=_scope())

    # cap-B/cap-C/cap-D have never been independently evidenced -- the
    # governed contract's ring is allowed to temporarily exceed its
    # configured limit rather than lose unevidenced pending evidence.
    assert removed == []
    for capture_id in ("cap-A", "cap-B", "cap-C", "cap-D"):
        assert (capture_root / capture_id).exists()


def test_pending_capture_becomes_retention_eligible_once_durably_evidenced(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])
    _write_capture(capture_root, capture_id="cap-D", received_at=T4, elements=[_element("#a"), _element("#b"), _element("#c"), _element("#d")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)
    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=2,
        protected_capture_ids=provider,
    )

    # Nothing evidenced yet: the ring exceeds its limit rather than lose
    # unevidenced evidence.
    assert ingestor._prune_retention_scope(current_capture_id="cap-D", scope=_scope()) == []

    # Now durably evidence exactly cap-B (never cap-C/cap-D).
    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    run_contract_watcher_persisted_cycle_batch(
        [r for r in selection["selected"] if r.observation_capture.capture_id == "cap-B"],
        evidence_store=evidence_store, history_store=history_store,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-D", scope=_scope())

    assert removed == ["cap-B"]
    for capture_id in ("cap-A", "cap-C", "cap-D"):
        assert (capture_root / capture_id).exists()


def test_malformed_pending_capture_survives_even_when_later_capture_succeeds(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_malformed_capture(capture_root, capture_id="cap-B", received_at=T2)
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-D", received_at=T4, elements=[_element("#a"), _element("#b"), _element("#c")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    batch_result = run_contract_watcher_persisted_cycle_batch(
        selection["selected"], evidence_store=evidence_store, history_store=history_store,
    )

    # cap-B fails to resolve (malformed); cap-C and cap-D succeed.
    assert batch_result["processed"] == 2
    assert batch_result["failed"] == 1

    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=2,
        protected_capture_ids=provider,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-D", scope=_scope())

    # cap-B (malformed, never durably evidenced) survives; cap-C (older,
    # but durably evidenced and not the latest-of-state) is the one
    # retention removes instead. cap-A (pinned baseline) and cap-D
    # (latest of its functional_state) also survive.
    assert removed == ["cap-C"]
    for capture_id in ("cap-A", "cap-B", "cap-D"):
        assert (capture_root / capture_id).exists()
    assert not (capture_root / "cap-C").exists()


def test_restart_reconstructs_the_same_protected_set(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])

    observation_path = tmp_path / "observation_state.json"

    store = AutoTwinObservationStore(path=observation_path)
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    run_contract_watcher_persisted_cycle_batch(
        [r for r in selection["selected"] if r.observation_capture.capture_id == "cap-B"],
        evidence_store=evidence_store, history_store=history_store,
    )

    before_restart = contract_watcher_governed_protected_capture_ids(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    # Simulate a full process restart: brand-new store/evidence/history
    # instances, re-pointed at the exact same durable paths, with no
    # shared in-memory state whatsoever.
    restarted_store = AutoTwinObservationStore(path=observation_path)
    restarted_evidence_store, restarted_history_store = _stores(tmp_path)

    after_restart = contract_watcher_governed_protected_capture_ids(
        restarted_store, capture_root=capture_root,
        evidence_store=restarted_evidence_store, history_store=restarted_history_store,
    )

    assert before_restart == after_restart == {"cap-A", "cap-C"}


def test_independent_contracts_remain_isolated(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A1", received_at=T1, pathname="/a", elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B1", received_at=T2, pathname="/a", elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-A2", received_at=T1, pathname="/b", elements=[_element("#x")])
    _write_capture(capture_root, capture_id="cap-B2", received_at=T2, pathname="/b", elements=[_element("#x"), _element("#y")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site_a = _site("twin-a", "SITE_A")
    site_b = _site("twin-b", "SITE_B")

    _observe(store, site_a, capture_id="cap-A1", fingerprint="fp-a1", pathname="/a", observed_at=T1)
    _observe(store, site_a, capture_id="cap-B1", fingerprint="fp-b1", pathname="/a", observed_at=T2)
    # twin-b only ever explicitly observes its baseline; cap-B2 is
    # discovered purely by matching persisted-capture identity, exactly
    # like 1G's own no-skip backlog.
    _observe(store, site_b, capture_id="cap-A2", fingerprint="fp-a2", pathname="/b", observed_at=T1)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    # Only evidence twin-a's pending capture; twin-b's cap-B2 is left
    # pending/unevidenced.
    run_contract_watcher_persisted_cycle_batch(
        [r for r in selection["selected"] if r.observation_capture.capture_id == "cap-B1"],
        evidence_store=evidence_store, history_store=history_store,
    )

    protected = contract_watcher_governed_protected_capture_ids(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    # twin-a: baseline protected, evidenced pending capture no longer
    # protected. twin-b: baseline protected, and cap-B2 remains
    # protected because it is still pending for twin-b's own contract --
    # never because of anything twin-a did.
    assert protected == {"cap-A1", "cap-A2", "cap-B2"}


def test_ordinary_non_watcher_ingestion_preserves_previous_retention_behavior(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])
    _write_capture(capture_root, capture_id="cap-C", received_at=T3, elements=[_element("#a"), _element("#b"), _element("#c")])

    # No AUTO TWIN observation ever happened for these captures.
    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    evidence_store, history_store = _stores(tmp_path)

    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    assert provider() == frozenset()

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=2,
        protected_capture_ids=provider,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-C", scope=_scope())

    # Identical to the pre-1H, unprotected ring: only the oldest capture
    # (not the latest-of-state, not the current one) is evicted.
    assert removed == ["cap-A"]


def test_protection_resolution_failure_never_deletes_governed_pending_evidence(tmp_path):
    capture_root = tmp_path / "site_architecture"
    _write_capture(capture_root, capture_id="cap-A", received_at=T1, elements=[_element("#a")])
    _write_capture(capture_root, capture_id="cap-B", received_at=T2, elements=[_element("#a"), _element("#b")])

    store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site("twin-a", "SITE_A")
    _observe(store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
    _observe(store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

    evidence_store, history_store = _stores(tmp_path)

    selection = select_contract_watcher_persisted_backlog(
        store, confirmation_policy=_policy(), capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )
    run_contract_watcher_persisted_cycle_batch(
        selection["selected"], evidence_store=evidence_store, history_store=history_store,
    )

    contract_key = selection["selected"][0].contract_key

    # Corrupt durable state after the fact: a history entry now
    # references evidence that no longer exists.
    entry = history_store.list_entries(contract_key=contract_key)[0]
    evidence_store.evidence_path(
        contract_key=contract_key, evidence_id=entry["evidence_id"],
    ).unlink()

    provider = contract_watcher_retention_protected_capture_id_provider(
        store, capture_root=capture_root,
        evidence_store=evidence_store, history_store=history_store,
    )

    ingestor = QccSiteArchitectureIngestor(
        output_root=capture_root,
        recognizer_registry=object(),
        retention_limit=1,
        protected_capture_ids=provider,
    )

    removed = ingestor._prune_retention_scope(current_capture_id="cap-B", scope=_scope())

    assert removed == []
    assert (capture_root / "cap-A").exists()
    assert (capture_root / "cap-B").exists()

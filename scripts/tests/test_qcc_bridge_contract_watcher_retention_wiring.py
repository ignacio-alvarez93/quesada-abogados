"""QCC Contract Watcher — live QCC Bridge retention wiring (Work Order 1I).

Closes the exact invocation boundary 1H's own module docstring
(``backend.qcc.auto_twin.contract_watcher_retention_adapter``) documented
as explicitly out of scope: wiring
``contract_watcher_retention_protected_capture_id_provider(...)`` into the
real ``QccSiteArchitectureIngestor`` that ``backend/qcc/bridge/server.py``
constructs for live capture ingestion.

These tests exercise ``QccBridgeServer`` itself -- never a hand-rolled
ingestor/provider pair -- so a regression in the actual construction-time
wiring (not merely in the provider/adapter logic 1H already covers) would
fail here.
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
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore
from backend.qcc.bridge.server import QccBridgeServer
from backend.qcc.site_architecture.ingestor import QccSiteArchitectureIngestor


ORIGIN = "https://example.test"
PROFILE = "profile-a"

T1 = "2026-01-01T00:00:00.000000+00:00"
T2 = "2026-01-02T00:00:00.000000+00:00"


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _site(twin_key="twin-a", site_code="SITE_A"):
    return AutoTwinManagedSite(twin_key=twin_key, site_code=site_code, origins=(ORIGIN,))


def _observe(store, site, *, capture_id, fingerprint, observed_at=T1, pathname="/"):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=observed_at,
        browser_profile_key=PROFILE,
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"state": None, "fingerprint": fingerprint},
    )


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_capture(root, *, capture_id, received_at, pathname="/"):
    """Enumerable persisted capture, minimally shaped like a real one."""

    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    metadata = {
        "capture_id": capture_id,
        "site_code": "GENERIC",
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
            "browser_profile_key": PROFILE,
            "origin": ORIGIN,
            "architecture_scope": "GENERAL",
            "functional_state": None,
        },
        "state_observation": {"state": None, "fingerprint": "fp-" + capture_id},
    }

    _write_json(capture_dir / "metadata.json", metadata)
    _write_json(
        capture_dir / "qcc_capture.json",
        {"schema_version": 1, "browser_profile_key": PROFILE, "main_url": ORIGIN + pathname},
    )
    _write_json(
        capture_dir / "site_architecture.json",
        {
            "schema_version": 1,
            "page": {"pathname": pathname, "url": ORIGIN + pathname},
            "viewport": {
                "inner_width": 1024,
                "inner_height": 768,
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
        {"schema_version": 1, "state": None, "fingerprint": "fp-" + capture_id},
    )

    return capture_dir


def _dom_capture(html="<html></html>"):
    return {
        "ok": True,
        "capture_type": "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at": "2026-08-22T21:00:00Z",
        "browser_profile_key": PROFILE,
        "frames": [{
            "frame_id": 0,
            "document_id": "main",
            "result": {
                "schema_version": 1,
                "captured_at": "2026-08-22T21:00:00Z",
                "url": ORIGIN + "/",
                "origin": ORIGIN,
                "pathname": "/",
                "title": "QCC Test",
                "ready_state": "complete",
                "content_type": "text/html",
                "character_set": "UTF-8",
                "html": html,
                "counts": {"elements": 0},
                "elements": [],
                "shadow_roots": [],
            },
        }],
    }


def _bridge(tmp_path, *, retention_limit=None, observation_store=None):
    return QccBridgeServer(
        port=0,
        site_architecture_output_root=tmp_path / "site_architecture",
        site_architecture_retention_limit=retention_limit,
        auto_twin_observation_store=(
            observation_store
            if observation_store is not None
            else AutoTwinObservationStore(path=tmp_path / "observation_state.json")
        ),
        contract_watcher_evidence_store=ContractWatcherEvidenceStore(
            root=tmp_path / "contract_watcher"
        ),
        contract_watcher_history_store=ContractWatcherHistoryStore(
            root=tmp_path / "contract_watcher"
        ),
    )


# ---------------------------------------------------------------------------
# Construction-time wiring
# ---------------------------------------------------------------------------


def test_default_bridge_construction_wires_live_retention_protection_provider(tmp_path):
    bridge = _bridge(tmp_path)

    try:
        ingestor = bridge.site_architecture_ingestor

        assert ingestor.output_root == tmp_path / "site_architecture"

        provider = ingestor._protected_capture_ids
        assert provider is not None
        assert callable(provider)

        # Recomputes durably from the exact stores the bridge itself
        # owns -- never raises, never a stale in-memory cursor.
        assert provider() == frozenset()

    finally:
        bridge.close()


def test_custom_ingestor_is_never_silently_replaced_or_rewired(tmp_path):
    custom_ingestor = QccSiteArchitectureIngestor(output_root=tmp_path / "custom")

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=custom_ingestor,
    )

    try:
        assert bridge.site_architecture_ingestor is custom_ingestor
        # 1I must never mutate a caller-supplied ingestor's protection.
        assert custom_ingestor._protected_capture_ids is None

    finally:
        bridge.close()


def test_custom_ingestor_supersedes_output_root_and_retention_overrides(tmp_path):
    custom_ingestor = QccSiteArchitectureIngestor(output_root=tmp_path / "custom")

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=custom_ingestor,
        site_architecture_output_root=tmp_path / "ignored",
        site_architecture_retention_limit=1,
    )

    try:
        assert bridge.site_architecture_ingestor is custom_ingestor
        assert custom_ingestor.output_root == tmp_path / "custom"

    finally:
        bridge.close()


# ---------------------------------------------------------------------------
# Protection sees the exact same stores/root as the Bridge ingestion path
# ---------------------------------------------------------------------------


def test_protection_sees_baseline_and_pending_captures_from_bridge_stores(tmp_path):
    bridge = _bridge(tmp_path)

    try:
        capture_root = bridge.site_architecture_ingestor.output_root
        _write_capture(capture_root, capture_id="cap-A", received_at=T1)
        _write_capture(capture_root, capture_id="cap-B", received_at=T2)

        site = _site()
        _observe(bridge.auto_twin_observation_store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
        _observe(bridge.auto_twin_observation_store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

        provider = bridge.site_architecture_ingestor._protected_capture_ids

        assert provider() == {"cap-A", "cap-B"}

    finally:
        bridge.close()


def test_restart_reconstruction_preserves_protection(tmp_path):
    observation_path = tmp_path / "observation_state.json"

    bridge = _bridge(
        tmp_path,
        observation_store=AutoTwinObservationStore(path=observation_path),
    )

    try:
        capture_root = bridge.site_architecture_ingestor.output_root
        _write_capture(capture_root, capture_id="cap-A", received_at=T1)
        _write_capture(capture_root, capture_id="cap-B", received_at=T2)

        site = _site()
        _observe(bridge.auto_twin_observation_store, site, capture_id="cap-A", fingerprint="fp-a", observed_at=T1)
        _observe(bridge.auto_twin_observation_store, site, capture_id="cap-B", fingerprint="fp-b", observed_at=T2)

        before_restart = bridge.site_architecture_ingestor._protected_capture_ids()

    finally:
        bridge.close()

    # A brand-new QccBridgeServer, re-pointed at the exact same durable
    # roots, with no shared in-memory state whatsoever.
    restarted_bridge = _bridge(
        tmp_path,
        observation_store=AutoTwinObservationStore(path=observation_path),
    )

    try:
        after_restart = restarted_bridge.site_architecture_ingestor._protected_capture_ids()

        assert before_restart == after_restart == {"cap-A", "cap-B"}

    finally:
        restarted_bridge.close()


# ---------------------------------------------------------------------------
# Real ingestion through the Bridge/default production path
# ---------------------------------------------------------------------------


def test_bridge_ingestion_with_low_retention_cannot_prune_unevidenced_pending_capture(tmp_path):
    bridge = _bridge(tmp_path, retention_limit=1)

    try:
        ingestor = bridge.site_architecture_ingestor
        site = _site()

        result_a = ingestor.ingest(_dom_capture())
        cap_a = result_a["capture_id"]

        _observe(bridge.auto_twin_observation_store, site, capture_id=cap_a, fingerprint="fp-a", observed_at=T1)

        result_b = ingestor.ingest(_dom_capture())
        cap_b = result_b["capture_id"]

        # cap_b has never been independently evidenced -- retention must
        # not remove it (nor the pinned baseline cap_a) despite the ring
        # limit of 1.
        assert result_b["retention_removed_capture_ids"] == []
        assert (ingestor.output_root / cap_a).exists()
        assert (ingestor.output_root / cap_b).exists()

        result_c = ingestor.ingest(_dom_capture())
        cap_c = result_c["capture_id"]

        assert result_c["retention_removed_capture_ids"] == []
        for capture_id in (cap_a, cap_b, cap_c):
            assert (ingestor.output_root / capture_id).exists()

        # Diagnostic (Work Order 1I-FIX1): record the durable governed
        # protected set immediately before evidencing cap_b, using the
        # exact same stores/root the live bridge wiring itself reads --
        # never a hand-rolled provider -- so a regression is localized to
        # either (a) evidence/history cross-validation never releasing
        # cap_b, or (b) the retention ring's own pruning arithmetic, and
        # never left ambiguous between the two.
        protected_before_evidencing = contract_watcher_governed_protected_capture_ids(
            bridge.auto_twin_observation_store,
            capture_root=ingestor.output_root,
            evidence_store=bridge.contract_watcher_evidence_store,
            history_store=bridge.contract_watcher_history_store,
        )

        assert cap_b in protected_before_evidencing
        assert cap_a in protected_before_evidencing
        assert cap_c in protected_before_evidencing

        # Now durably evidence exactly cap_b (never cap_c).
        selection = select_contract_watcher_persisted_backlog(
            bridge.auto_twin_observation_store,
            confirmation_policy=_policy(),
            capture_root=ingestor.output_root,
            evidence_store=bridge.contract_watcher_evidence_store,
            history_store=bridge.contract_watcher_history_store,
        )

        batch_result = run_contract_watcher_persisted_cycle_batch(
            [r for r in selection["selected"] if r.observation_capture.capture_id == cap_b],
            evidence_store=bridge.contract_watcher_evidence_store,
            history_store=bridge.contract_watcher_history_store,
        )

        # Localizes a silent governed-rejection during evidencing (which
        # would otherwise look identical to a retention-side bug: cap_b
        # would simply never durably leave the protected set).
        assert batch_result["failed"] == 0, batch_result["failures"]
        assert batch_result["processed"] == 1

        protected_after_evidencing = contract_watcher_governed_protected_capture_ids(
            bridge.auto_twin_observation_store,
            capture_root=ingestor.output_root,
            evidence_store=bridge.contract_watcher_evidence_store,
            history_store=bridge.contract_watcher_history_store,
        )

        assert cap_b not in protected_after_evidencing
        assert cap_a in protected_after_evidencing
        assert cap_c in protected_after_evidencing

        # A new ingestion re-triggers the prune pass: cap_b is now
        # retention-eligible; cap_a (baseline) and cap_c (still pending)
        # survive.
        result_d = ingestor.ingest(_dom_capture())
        cap_d = result_d["capture_id"]

        assert result_d["retention_removed_capture_ids"] == [cap_b]
        assert not (ingestor.output_root / cap_b).exists()
        for capture_id in (cap_a, cap_c, cap_d):
            assert (ingestor.output_root / capture_id).exists()

    finally:
        bridge.close()


def test_bridge_ordinary_non_watcher_ingestion_remains_backward_compatible(tmp_path):
    """No AUTO TWIN observation ever happens -- the plain ring still evicts."""

    bridge = _bridge(tmp_path, retention_limit=1)

    try:
        ingestor = bridge.site_architecture_ingestor

        ingestor.ingest(_dom_capture())
        result_b = ingestor.ingest(_dom_capture())

        # Nothing was ever observed by AUTO TWIN for either capture, so
        # the provider protects nothing and the pre-1I ring behavior
        # (evict down to the limit) is preserved.
        assert len(result_b["retention_removed_capture_ids"]) == 1

    finally:
        bridge.close()


def test_bridge_server_import_has_no_circular_import_or_side_effect():
    import importlib

    import backend.qcc.bridge.server as module

    reloaded = importlib.reload(module)

    assert reloaded.QccBridgeServer is not None

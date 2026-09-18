"""Provider-neutral retention protection contract (Work Order 1H).

These tests exercise ``QccSiteArchitectureIngestor``'s
``protected_capture_ids`` constructor argument in isolation, without any
knowledge of Contract Watcher or AUTO TWIN -- exactly mirroring how the
site_architecture layer itself must remain oblivious to who supplies
the protected set.
"""

import json

import pytest

from backend.qcc.site_architecture.ingestor import (
    QccSiteArchitectureIngestor,
)


def _ingestor(
    tmp_path,
    *,
    limit=2,
    protected_capture_ids=None,
):
    return QccSiteArchitectureIngestor(
        output_root=tmp_path,
        recognizer_registry=object(),
        retention_limit=limit,
        protected_capture_ids=protected_capture_ids,
    )


def _capture_dir(
    root,
    capture_id,
    *,
    profile="profile-a",
    origin="https://example.com",
):
    folder = root / capture_id
    folder.mkdir()

    metadata = {
        "capture_id": capture_id,
        "retention": {
            "mode": "PROFILE_ORIGIN_ARCHITECTURE_SCOPE_RING",
            "browser_profile_key": profile,
            "origin": origin,
        },
    }

    (folder / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    return folder


def _scope():
    return {
        "browser_profile_key": "profile-a",
        "origin": "https://example.com",
    }


def test_no_protected_ids_preserves_previous_ring_behavior(tmp_path):
    ingestor = _ingestor(tmp_path, limit=2, protected_capture_ids=None)

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )

    assert removed == ["001"]


def test_explicit_static_collection_protects_a_capture_beyond_the_ring(tmp_path):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
        protected_capture_ids=frozenset({"001"}),
    )

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )

    # Only 1 capture is in excess of the limit; "001" is explicitly
    # protected, so "002" is pruned instead.
    assert removed == ["002"]
    assert (tmp_path / "001").exists()
    assert (tmp_path / "003").exists()


def test_explicit_static_collection_still_prunes_unprotected_excess(tmp_path):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
        protected_capture_ids=frozenset({"999-not-present"}),
    )

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )

    assert removed == ["001"]


def test_callable_provider_is_invoked_fresh_on_every_prune(tmp_path):
    calls = []

    def provider():
        calls.append(1)
        # Protects everything so neither call actually deletes anything,
        # keeping the capture count (and therefore the excess-over-limit
        # trigger) identical across both calls.
        return {"001", "002"}

    ingestor = _ingestor(tmp_path, limit=2, protected_capture_ids=provider)

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    first = ingestor._prune_retention_scope(current_capture_id="003", scope=_scope())
    second = ingestor._prune_retention_scope(current_capture_id="003", scope=_scope())

    assert first == []
    assert second == []
    assert len(calls) == 2


def test_callable_provider_reacting_to_new_state_unprotects_captures(tmp_path):
    protected = {"001"}

    def provider():
        return frozenset(protected)

    ingestor = _ingestor(tmp_path, limit=2, protected_capture_ids=provider)

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed_first = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )
    assert removed_first == ["002"]
    assert (tmp_path / "001").exists()

    protected.clear()

    _capture_dir(tmp_path, "004")

    removed_second = ingestor._prune_retention_scope(
        current_capture_id="004",
        scope=_scope(),
    )

    assert removed_second == ["001"]


def test_callable_provider_failure_fails_closed_no_deletion(tmp_path):
    def provider():
        raise RuntimeError("QCC_TEST_RETENTION_PROTECTION_UNAVAILABLE")

    ingestor = _ingestor(tmp_path, limit=2, protected_capture_ids=provider)

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )

    assert removed == []
    assert (tmp_path / "001").exists()
    assert (tmp_path / "002").exists()
    assert (tmp_path / "003").exists()


def test_non_iterable_resolved_value_fails_closed_no_deletion(tmp_path):
    ingestor = _ingestor(tmp_path, limit=2, protected_capture_ids=object())

    for capture_id in ("001", "002", "003"):
        _capture_dir(tmp_path, capture_id)

    removed = ingestor._prune_retention_scope(
        current_capture_id="003",
        scope=_scope(),
    )

    assert removed == []


def test_resolve_protected_capture_ids_helper_reports_failure_flag(tmp_path):
    ingestor = _ingestor(tmp_path, protected_capture_ids=lambda: 1 / 0)

    ids, failed = ingestor._resolve_protected_capture_ids()

    assert ids == frozenset()
    assert failed is True


def test_resolve_protected_capture_ids_helper_normalizes_blank_entries(tmp_path):
    ingestor = _ingestor(
        tmp_path,
        protected_capture_ids=["001", "", None, "  002  ".strip()],
    )

    ids, failed = ingestor._resolve_protected_capture_ids()

    assert failed is False
    assert ids == frozenset({"001", "002"})

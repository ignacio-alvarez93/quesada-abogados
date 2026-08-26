import json

import pytest

from backend.automation.site_architecture import (
    SITE_ARCHITECTURE_SCHEMA_VERSION,
    SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE,
    SiteArchitecturePage,
    SiteArchitectureSnapshot,
    SiteArchitectureSource,
    SiteArchitectureViewport,
)


def test_site_architecture_schema_version_is_explicit():
    assert (
        SITE_ARCHITECTURE_SCHEMA_VERSION
        == 1
    )


def test_snapshot_has_canonical_json_safe_shape():
    snapshot = SiteArchitectureSnapshot(
        source=SiteArchitectureSource(
            kind=SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE,
            schema_version=1,
        ),
        captured_at="2026-08-22T12:00:00.000Z",
        page=SiteArchitecturePage(
            url="https://example.test/page",
            origin="https://example.test",
            pathname="/page",
            title="Página prueba",
            ready_state="complete",
        ),
    )

    payload = snapshot.to_dict()

    assert payload["schema_version"] == 1
    assert payload["source"]["kind"] == "DOM_CAPTURE"
    assert payload["page"]["pathname"] == "/page"

    assert payload["documents"] == ()
    assert payload["elements"] == ()
    assert payload["actions"] == ()
    assert payload["frames"] == ()
    assert payload["shadow_roots"] == ()

    json.dumps(
        payload,
        ensure_ascii=False,
    )


def test_viewport_can_remain_unknown_until_geometry_capture():
    viewport = SiteArchitectureViewport()

    assert viewport.inner_width is None
    assert viewport.inner_height is None
    assert viewport.scroll_x is None
    assert viewport.scroll_y is None
    assert viewport.device_pixel_ratio is None


def test_snapshot_rejects_unknown_schema_version():
    with pytest.raises(
        ValueError,
        match=(
            "SITE_ARCHITECTURE_SCHEMA_VERSION_UNSUPPORTED"
        ),
    ):
        SiteArchitectureSnapshot(
            source=SiteArchitectureSource(
                kind="DOM_CAPTURE",
                schema_version=1,
            ),
            schema_version=999,
        )


def test_snapshot_catalog_contract_defaults_empty():
    snapshot = SiteArchitectureSnapshot(
        source=SiteArchitectureSource(
            kind=SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE,
            schema_version=1,
        ),
    )

    payload = snapshot.to_dict()

    assert payload["catalogs"] == ()
    assert payload["catalog_relations"] == ()
    assert payload["actions"] == ()

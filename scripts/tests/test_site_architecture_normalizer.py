import pytest

from backend.automation.site_architecture import (
    normalize_dom_capture,
)


def _payload():
    return {
        "schema_version": 1,
        "captured_at":
            "2026-08-22T19:30:00.000Z",
        "metadata": {
            "url":
                (
                    "https://example.test/page"
                    "?province=33&step=2"
                ),
            "origin":
                "https://example.test",
            "pathname":
                "/page",
            "title":
                "Página prueba",
            "ready_state":
                "complete",
        },
        "documents": [
            {
                "frame_path": "main",
                "element_count": 4,
            },
        ],
        "elements": [
            {
                "index": 0,
                "tag": "html",
            },
        ],
        "frames": [
            {
                "index": 1,
                "frame_path": "1",
            },
        ],
        "shadows": [
            {
                "index": 1,
                "host_tag": "x-widget",
            },
        ],
        "counts": {
            "documents": 1,
            "elements": 1,
            "iframes": 1,
            "open_shadow_roots": 1,
        },
    }


def test_normalize_dom_capture_maps_page_identity():
    snapshot = normalize_dom_capture(
        _payload()
    )

    assert snapshot.schema_version == 1
    assert snapshot.source.kind == "DOM_CAPTURE"
    assert snapshot.source.schema_version == 1

    assert (
        snapshot.captured_at
        == "2026-08-22T19:30:00.000Z"
    )

    assert (
        snapshot.page.url
        == (
            "https://example.test/page"
            "?province=33&step=2"
        )
    )
    assert (
        snapshot.page.origin
        == "https://example.test"
    )
    assert snapshot.page.pathname == "/page"
    assert (
        snapshot.page.query
        == "province=33&step=2"
    )
    assert snapshot.page.title == "Página prueba"
    assert snapshot.page.ready_state == "complete"


def test_normalize_dom_capture_preserves_structural_inventory():
    snapshot = normalize_dom_capture(
        _payload()
    )

    assert len(snapshot.documents) == 1
    assert len(snapshot.elements) == 1
    assert len(snapshot.frames) == 1
    assert len(snapshot.shadow_roots) == 1

    assert (
        snapshot.documents[0]["frame_path"]
        == "main"
    )
    assert snapshot.elements[0]["tag"] == "html"
    assert snapshot.frames[0]["frame_path"] == "1"

    assert (
        snapshot.shadow_roots[0]["host_tag"]
        == "x-widget"
    )

    assert snapshot.counts["elements"] == 1


def test_normalize_dom_capture_rejects_invalid_payload():
    with pytest.raises(
        ValueError,
        match=(
            "SITE_ARCHITECTURE_DOM_CAPTURE_INVALID"
        ),
    ):
        normalize_dom_capture(
            ["not", "a", "payload"]
        )


def test_normalize_dom_capture_rejects_unknown_raw_schema():
    payload = _payload()
    payload["schema_version"] = 999

    with pytest.raises(
        ValueError,
        match=(
            "SITE_ARCHITECTURE_DOM_CAPTURE_SCHEMA_UNSUPPORTED"
        ),
    ):
        normalize_dom_capture(
            payload
        )


def test_normalize_dom_capture_adds_element_semantics():
    payload = _payload()

    payload["elements"] = [
        {
            "index": 0,
            "tag": "input",
            "type": "file",
            "role": "",
        },
        {
            "index": 1,
            "tag": "input",
            "type": "submit",
            "role": "",
        },
        {
            "index": 2,
            "tag": "div",
            "type": "",
            "role": "button",
        },
    ]

    snapshot = normalize_dom_capture(
        payload
    )

    assert (
        snapshot.elements[0]["semantics"]
        == ("FILE_INPUT",)
    )

    assert (
        snapshot.elements[1]["semantics"]
        == ("BUTTON", "SUBMIT")
    )

    assert (
        snapshot.elements[2]["semantics"]
        == ("BUTTON",)
    )


def test_normalize_dom_capture_adds_selector_profile():
    payload = _payload()

    payload["elements"] = [
        {
            "index": 0,
            "frame_path": "main",
            "tag": "input",
            "id": "documento",
            "name": "documento",
            "type": "file",
            "role": "",
            "attributes": {},
        },
    ]

    snapshot = normalize_dom_capture(
        payload
    )

    selectors = (
        snapshot.elements[0]["selectors"]
    )

    assert selectors["frame_path"] == "main"

    assert (
        selectors["primary"]["selector"]
        == "#documento"
    )

    assert (
        selectors["primary"]["unique"]
        is True
    )

    assert selectors["confidence"] == "HIGH"

    assert (
        selectors["fallbacks"][0]["selector"]
        == '[name="documento"]'
    )


def test_normalizer_does_not_promote_ambiguous_selector():
    payload = _payload()

    payload["elements"] = [
        {
            "index": 0,
            "frame_path": "main",
            "tag": "button",
            "role": "button",
            "attributes": {},
        },
        {
            "index": 1,
            "frame_path": "main",
            "tag": "button",
            "role": "button",
            "attributes": {},
        },
    ]

    snapshot = normalize_dom_capture(
        payload
    )

    selectors = (
        snapshot.elements[0]["selectors"]
    )

    assert selectors["primary"] is None
    assert selectors["fallbacks"] == ()
    assert selectors["confidence"] is None

    assert (
        selectors["candidates"][0]["unique"]
        is False
    )


def test_normalizer_maps_viewport_and_element_geometry():
    payload = _payload()

    payload["viewport"] = {
        "inner_width": 1280,
        "inner_height": 720,
        "scroll_x": 120,
        "scroll_y": 340,
        "device_pixel_ratio": 1.25,
    }

    payload["elements"] = [{
        "index": 0,
        "frame_path": "main",
        "tag": "button",
        "id": "continuar",
        "attributes": {},
        "rect": {
            "x": 300,
            "y": 400,
            "width": 120,
            "height": 40,
        },
    }]

    snapshot = normalize_dom_capture(
        payload
    )

    assert snapshot.viewport.inner_width == 1280
    assert snapshot.viewport.scroll_y == 340

    geometry = (
        snapshot.elements[0]["geometry"]
    )

    assert (
        geometry["coordinate_space"]
        == "TOP_LEVEL_VIEWPORT"
    )
    assert geometry["center"]["x"] == 360.0
    assert geometry["center"]["y"] == 420.0


def test_normalizer_adds_interaction_state():
    payload = _payload()

    payload["elements"] = [{
        "index": 0,
        "frame_path": "main",
        "tag": "button",
        "id": "continuar",
        "visible": True,
        "disabled": False,
        "attributes": {},
        "interaction_signals": {
            "hidden": False,
            "aria_hidden": False,
            "aria_disabled": False,
            "readonly": False,
            "in_viewport": True,
            "opacity": "1",
            "pointer_events": "auto",
        },
    }]

    snapshot = normalize_dom_capture(
        payload
    )

    interaction = (
        snapshot.elements[0]["interaction"]
    )

    assert interaction["visible"] is True
    assert interaction["interactable"] is True
    assert interaction["state"] == "INTERACTABLE"


def test_normalizer_strips_raw_html_from_nested_records():
    payload = _payload()

    payload["frames"] = [{
        "index": 1,
        "frame_path": "1",
        "html": "<html>raw frame</html>",
    }]

    payload["shadows"] = [{
        "index": 1,
        "frame_path": "main",
        "html": "<div>raw shadow</div>",
    }]

    snapshot = normalize_dom_capture(
        payload
    )

    assert "html" not in snapshot.frames[0]
    assert "html" not in snapshot.shadow_roots[0]


def test_normalizer_builds_catalog_reference_graph():
    payload = _payload()

    payload["catalogs"] = [
        {
            "catalog_type":
                "native_select",
            "selector":
                "#province",
            "frame_path":
                "main",
            "element": {
                "tag": "select",
                "id": "province",
                "name": "province",
            },
            "dependency_hints": {
                "data-target":
                    "municipality",
            },
        },
        {
            "catalog_type":
                "native_select",
            "selector":
                "#municipality",
            "frame_path":
                "main",
            "element": {
                "tag": "select",
                "id": "municipality",
                "name": "municipality",
            },
            "dependency_hints":
                {},
        },
    ]

    snapshot = normalize_dom_capture(
        payload
    )

    assert len(snapshot.catalogs) == 2
    assert len(
        snapshot.catalog_relations
    ) == 1

    relation = (
        snapshot.catalog_relations[0]
    )

    assert (
        relation["relation"]
        == "DOM_REFERENCE"
    )

    assert (
        relation["source"]
        == "main::#province"
    )

    assert (
        relation["target"]
        == "main::#municipality"
    )

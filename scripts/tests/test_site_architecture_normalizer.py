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


def test_normalizer_builds_canonical_action_inventory():
    payload = {
        "schema_version": 1,
        "captured_at":
            "2026-08-24T09:45:00.000Z",

        "metadata": {
            "url":
                "https://example.test/page",

            "origin":
                "https://example.test",

            "pathname":
                "/page",

            "title":
                "Test",

            "ready_state":
                "complete",
        },

        "elements": [
            {
                "index": 0,
                "tag": "button",
                "id": "continue-action",
                "name": "",
                "type": "button",
                "role": "button",

                "attributes": {
                    "id": "continue-action",
                    "type": "button",
                    "role": "button",
                },

                "visible": True,

                "rect": {
                    "x": 10,
                    "y": 10,
                    "width": 100,
                    "height": 30,
                },

                "interaction_signals": {
                    "hidden": False,
                    "aria_hidden": False,
                    "aria_disabled": False,
                    "readonly": False,
                    "in_viewport": True,
                    "opacity": 1,
                    "pointer_events": "auto",
                },
            }
        ],

        "documents": [],
        "frames": [],
        "shadows": [],
        "catalogs": [],
        "counts": {},
    }

    snapshot = normalize_dom_capture(
        payload
    )

    assert len(snapshot.actions) == 1

    action = snapshot.actions[0]

    assert action["kind"] == "BUTTON"

    assert (
        action["policy"]
        == "REQUIRES_POLICY"
    )

    assert (
        action["selector"]
        == "#continue-action"
    )

    assert (
        action["element"]["id"]
        == "continue-action"
    )

    serialized = snapshot.to_dict()

    assert "actions" in serialized
    assert len(serialized["actions"]) == 1


# ---------------------------------------------------------------------------
# Structural provenance (AUTO TWIN STRUCTURAL PROVENANCE PREREQUISITE V1)
# ---------------------------------------------------------------------------


def _structural_payload():
    payload = _payload()

    payload["elements"] = [
        {
            "index": 0,
            "frame_path": "main",
            "tag": "div",
            "id": "container",
            "attributes": {"id": "container"},
            "parent_index": None,
            "previous_element_sibling_index": None,
            "next_element_sibling_index": None,
            "dom_depth": 0,
            "child_element_count": 2,
        },
        {
            "index": 1,
            "frame_path": "main",
            "tag": "span",
            "id": "first",
            "attributes": {"id": "first"},
            "parent_index": 0,
            "previous_element_sibling_index": None,
            "next_element_sibling_index": 2,
            "dom_depth": 1,
            "child_element_count": 0,
        },
        {
            "index": 2,
            "frame_path": "main",
            "tag": "span",
            "id": "second",
            "attributes": {"id": "second"},
            "parent_index": 0,
            "previous_element_sibling_index": 1,
            "next_element_sibling_index": None,
            "dom_depth": 1,
            "child_element_count": 0,
        },
    ]

    return payload


def test_normalizer_projects_parent_relation_with_selector_identity():
    snapshot = normalize_dom_capture(
        _structural_payload()
    )

    first = snapshot.elements[1]

    parent = first["structure"]["parent"]

    assert parent["capture_index"] == 0
    assert parent["frame_path"] == "main"
    assert parent["selector"] == "#container"


def test_normalizer_projects_previous_sibling_relation_with_selector_identity():
    snapshot = normalize_dom_capture(
        _structural_payload()
    )

    second = snapshot.elements[2]

    previous_sibling = (
        second["structure"]["previous_sibling"]
    )

    assert previous_sibling["capture_index"] == 1
    assert previous_sibling["frame_path"] == "main"
    assert previous_sibling["selector"] == "#first"


def test_normalizer_projects_next_sibling_relation_with_selector_identity():
    snapshot = normalize_dom_capture(
        _structural_payload()
    )

    first = snapshot.elements[1]

    next_sibling = (
        first["structure"]["next_sibling"]
    )

    assert next_sibling["capture_index"] == 2
    assert next_sibling["frame_path"] == "main"
    assert next_sibling["selector"] == "#second"


def test_normalizer_preserves_frame_document_ownership_in_structure():
    payload = _structural_payload()

    payload["elements"].append({
        "index": 0,
        "frame_path": "1",
        "tag": "div",
        "id": "frame-root",
        "attributes": {"id": "frame-root"},
        "parent_index": None,
        "previous_element_sibling_index": None,
        "next_element_sibling_index": None,
        "dom_depth": 0,
        "child_element_count": 0,
    })

    snapshot = normalize_dom_capture(payload)

    frame_root = snapshot.elements[-1]

    assert frame_root["frame_path"] == "1"
    assert frame_root["structure"]["parent"] is None


def test_normalizer_capture_index_is_diagnostic_only_not_cross_snapshot_identity():
    before = normalize_dom_capture(
        _structural_payload()
    )

    after_payload = _structural_payload()

    # Same capture_index (1), different element identity: capture_index
    # alone must never be treated as a stable cross-snapshot identity.
    after_payload["elements"][1]["id"] = "renamed-first"
    after_payload["elements"][1]["attributes"] = {
        "id": "renamed-first"
    }

    after = normalize_dom_capture(after_payload)

    before_parent = before.elements[1]["structure"]["parent"]
    after_parent = after.elements[1]["structure"]["parent"]

    assert (
        before_parent["capture_index"]
        == after_parent["capture_index"]
    )
    assert (
        before.elements[1]["selectors"]["primary"]["selector"]
        != after.elements[1]["selectors"]["primary"]["selector"]
    )


def test_normalizer_missing_related_element_fails_closed():
    payload = _structural_payload()

    # parent_index references an index absent from the capture set.
    payload["elements"][1]["parent_index"] = 99

    snapshot = normalize_dom_capture(payload)

    assert (
        snapshot.elements[1]["structure"]["parent"]
        is None
    )


def test_normalizer_relation_with_unresolved_selector_remains_unresolved():
    payload = _structural_payload()

    payload["elements"][0]["id"] = ""
    payload["elements"][0]["attributes"] = {}

    snapshot = normalize_dom_capture(payload)

    parent = snapshot.elements[1]["structure"]["parent"]

    assert parent["capture_index"] == 0
    assert parent["selector"] is None


def test_normalizer_does_not_persist_raw_html_in_structure():
    snapshot = normalize_dom_capture(
        _structural_payload()
    )

    serialized = str(snapshot.to_dict())

    assert "outerHTML" not in serialized


def test_normalizer_structural_serialization_is_deterministic():
    payload = _structural_payload()

    first = normalize_dom_capture(payload).to_dict()
    second = normalize_dom_capture(payload).to_dict()

    assert first == second


def test_normalizer_structure_coexists_with_existing_normalization():
    snapshot = normalize_dom_capture(
        _structural_payload()
    )

    first = snapshot.elements[1]

    assert first["tag"] == "span"
    assert "semantics" in first
    assert "selectors" in first
    assert "geometry" in first
    assert "interaction" in first
    assert "structure" in first

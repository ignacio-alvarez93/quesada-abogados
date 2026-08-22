import json
from datetime import datetime
from pathlib import Path

from backend.automation import (
    dom_inspector,
)


class FakeBrowser:
    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.scripts = []

    def execute_script(
        self,
        code,
    ):
        self.scripts.append(
            code
        )

        return self.payload


def _payload():
    return {
        "schema_version":
            1,

        "captured_at":
            "2026-08-22T12:00:00.000Z",

        "metadata": {
            "url":
                "https://example.test/page",

            "origin":
                "https://example.test",

            "pathname":
                "/page",

            "title":
                "Página prueba",

            "ready_state":
                "complete",

            "content_type":
                "text/html",

            "character_set":
                "UTF-8",
        },

        "viewport": {
            "inner_width": 1280,
            "inner_height": 720,
            "client_width": 1265,
            "client_height": 705,
            "scroll_x": 120,
            "scroll_y": 340,
            "device_pixel_ratio": 1.25,
            "screen_x": 40,
            "screen_y": 20,
            "outer_width": 1296,
            "outer_height": 839,
        },

        "html":
            (
                "<html><body>"
                "<form id='f1'>"
                "<input id='name'>"
                "</form>"
                "</body></html>"
            ),

        "counts": {
            "documents":
                2,

            "elements":
                7,

            "forms":
                1,

            "inputs":
                1,

            "textareas":
                0,

            "selects":
                0,

            "buttons":
                1,

            "links":
                0,

            "tables":
                0,

            "iframes":
                2,

            "accessible_iframes":
                1,

            "inaccessible_iframes":
                1,

            "open_shadow_roots":
                1,
        },

        "documents": [
            {
                "frame_path":
                    "main",

                "url":
                    "https://example.test/page",

                "title":
                    "Página prueba",

                "element_count":
                    5,

                "forms":
                    1,

                "inputs":
                    1,

                "textareas":
                    0,

                "selects":
                    0,

                "buttons":
                    0,

                "links":
                    0,

                "tables":
                    0,
            },

            {
                "frame_path":
                    "1",

                "url":
                    "https://example.test/frame",

                "title":
                    "Frame",

                "element_count":
                    2,

                "forms":
                    0,

                "inputs":
                    0,

                "textareas":
                    0,

                "selects":
                    0,

                "buttons":
                    1,

                "links":
                    0,

                "tables":
                    0,
            },
        ],

        "elements": [
            {
                "index":
                    2,

                "frame_path":
                    "main",

                "tag":
                    "input",

                "id":
                    "name",

                "name":
                    "",

                "type":
                    "text",

                "role":
                    "",

                "classes":
                    [],

                "attributes": {
                    "id":
                        "name",
                },

                "text":
                    "",

                "visible":
                    True,

                "disabled":
                    False,

                "shadow_root":
                    False,

                "rect":
                    None,
            }
        ],

        "frames": [
            {
                "index":
                    1,

                "frame_path":
                    "1",

                "parent_frame_path":
                    "main",

                "tag":
                    "iframe",

                "id":
                    "same",

                "name":
                    "",

                "src":
                    "/frame",

                "accessible":
                    True,

                "url":
                    "https://example.test/frame",

                "title":
                    "Frame",

                "html":
                    (
                        "<html><body>"
                        "<button>OK</button>"
                        "</body></html>"
                    ),

                "error":
                    None,
            },

            {
                "index":
                    2,

                "frame_path":
                    "2",

                "parent_frame_path":
                    "main",

                "tag":
                    "iframe",

                "id":
                    "cross",

                "name":
                    "",

                "src":
                    "https://other.test/",

                "accessible":
                    False,

                "url":
                    "",

                "title":
                    "",

                "html":
                    "",

                "error":
                    "SecurityError",
            },
        ],

        "shadows": [
            {
                "index":
                    1,

                "frame_path":
                    "main",

                "host_element_index":
                    3,

                "host_tag":
                    "x-widget",

                "host_id":
                    "widget",

                "host_classes":
                    [],

                "html":
                    (
                        "<button "
                        "id='inside'>"
                        "OK"
                        "</button>"
                    ),
            }
        ],
    }


def test_capture_writes_all_artifacts(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector
        .capture_dom_snapshot(
            browser,
            tmp_path,
            timestamp=datetime(
                2026,
                8,
                22,
                14,
                30,
                0,
            ),
        )
    )

    capture_dir = (
        result[
            "capture_dir"
        ]
    )

    assert capture_dir.is_dir()

    assert (
        capture_dir
        / "page.html"
    ).is_file()

    assert (
        capture_dir
        / "dom_inventory.json"
    ).is_file()

    assert (
        capture_dir
        / "metadata.json"
    ).is_file()

    assert (
        capture_dir
        / "frames"
        / "frame_001.html"
    ).is_file()

    assert not (
        capture_dir
        / "frames"
        / "frame_002.html"
    ).exists()

    assert (
        capture_dir
        / "shadow_roots"
        / "shadow_001.html"
    ).is_file()


def test_page_html_is_current_dom_payload(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector
        .capture_dom_snapshot(
            browser,
            tmp_path,
            timestamp=datetime(
                2026,
                8,
                22,
                14,
                31,
                0,
            ),
        )
    )

    html = (
        result[
            "page_path"
        ].read_text(
            encoding="utf-8"
        )
    )

    assert (
        "<form id='f1'>"
        in html
    )

    assert (
        "<input id='name'>"
        in html
    )


def test_inventory_keeps_structure_without_inline_frame_html(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector
        .capture_dom_snapshot(
            browser,
            tmp_path,
            timestamp=datetime(
                2026,
                8,
                22,
                14,
                32,
                0,
            ),
        )
    )

    inventory = json.loads(
        result[
            "inventory_path"
        ].read_text(
            encoding="utf-8"
        )
    )

    assert (
        inventory[
            "counts"
        ][
            "accessible_iframes"
        ]
        == 1
    )

    assert (
        inventory[
            "counts"
        ][
            "inaccessible_iframes"
        ]
        == 1
    )

    assert (
        inventory[
            "frames"
        ][0][
            "artifact"
        ]
        == "frames/frame_001.html"
    )

    assert (
        inventory[
            "frames"
        ][1][
            "artifact"
        ]
        is None
    )

    assert (
        "html"
        not in inventory[
            "frames"
        ][0]
    )

    assert (
        inventory[
            "shadow_roots"
        ][0][
            "artifact"
        ]
        == (
            "shadow_roots/"
            "shadow_001.html"
        )
    )


def test_metadata_summarizes_capture(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector
        .capture_dom_snapshot(
            browser,
            tmp_path,
            timestamp=datetime(
                2026,
                8,
                22,
                14,
                33,
                0,
            ),
        )
    )

    metadata = json.loads(
        result[
            "metadata_path"
        ].read_text(
            encoding="utf-8"
        )
    )

    assert (
        metadata[
            "url"
        ]
        == "https://example.test/page"
    )

    assert (
        metadata[
            "title"
        ]
        == "Página prueba"
    )

    assert (
        metadata[
            "artifacts"
        ][
            "frames"
        ]
        == 1
    )

    assert (
        metadata[
            "artifacts"
        ][
            "shadow_roots"
        ]
        == 1
    )


def test_inspector_javascript_covers_live_dom_frames_and_shadow_roots():
    browser = FakeBrowser(
        _payload()
    )

    payload = (
        dom_inspector
        ._capture_browser_payload(
            browser
        )
    )

    assert (
        payload[
            "schema_version"
        ]
        == 1
    )

    assert len(
        browser.scripts
    ) == 1

    script = (
        browser.scripts[
            0
        ]
    )

    required = (
        "documentElement",
        "outerHTML",
        "contentDocument",
        "shadowRoot",
        "querySelectorAll",
        "inspectDocument",
    )

    for token in required:
        assert token in script


def test_inspector_does_not_request_browser_storage():
    source = Path(
        "backend/automation/dom_inspector.py"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "document.cookie",
        "localStorage",
        "sessionStorage",
        "getAllCookies",
    )

    for token in forbidden:
        assert token not in source


class FakeCdpBrowser:
    """Replica la superficie relevante de sb_cdp.Chrome."""

    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.evaluated = []
        self.execute_calls = []

    def evaluate(
        self,
        expression,
    ):
        self.evaluated.append(
            expression
        )

        return self.payload

    def execute_script(
        self,
        code,
    ):
        self.execute_calls.append(
            code
        )

        raise AssertionError(
            "CDP debe usar evaluate(), no execute_script()"
        )


def test_inspector_prefers_cdp_evaluate_without_top_level_return():
    browser = FakeCdpBrowser(
        _payload()
    )

    result = (
        dom_inspector
        ._capture_browser_payload(
            browser
        )
    )

    assert (
        result[
            "schema_version"
        ]
        == 1
    )

    assert len(
        browser.evaluated
    ) == 1

    assert (
        browser.execute_calls
        == []
    )

    expression = (
        browser.evaluated[
            0
        ].lstrip()
    )

    assert expression.startswith(
        "(function () {"
    )

    assert not expression.startswith(
        "return "
    )


def test_inspector_webdriver_path_adds_return():
    browser = FakeBrowser(
        _payload()
    )

    (
        dom_inspector
        ._capture_browser_payload(
            browser
        )
    )

    script = (
        browser.scripts[
            0
        ].lstrip()
    )

    assert script.startswith(
        "return (function () {"
    )


def test_inventory_persists_viewport_geometry(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector
        .capture_dom_snapshot(
            browser,
            tmp_path,
        )
    )

    inventory = json.loads(
        result[
            "inventory_path"
        ].read_text(
            encoding="utf-8"
        )
    )

    viewport = inventory["viewport"]

    assert viewport["inner_width"] == 1280
    assert viewport["inner_height"] == 720
    assert viewport["scroll_x"] == 120
    assert viewport["scroll_y"] == 340
    assert viewport["device_pixel_ratio"] == 1.25
    assert viewport["screen_x"] == 40
    assert viewport["screen_y"] == 20


def test_inspector_javascript_captures_browser_geometry():
    browser = FakeBrowser(
        _payload()
    )

    (
        dom_inspector
        ._capture_browser_payload(
            browser
        )
    )

    script = browser.scripts[0]

    required = (
        "window.innerWidth",
        "window.innerHeight",
        "clientWidth",
        "clientHeight",
        "window.scrollX",
        "window.scrollY",
        "window.devicePixelRatio",
        "window.screenX",
        "window.screenY",
        "window.outerWidth",
        "window.outerHeight",
    )

    for token in required:
        assert token in script


def test_inspector_javascript_captures_interaction_signals():
    browser = FakeBrowser(
        _payload()
    )

    dom_inspector._capture_browser_payload(
        browser
    )

    script = browser.scripts[0]

    required = (
        "interaction_signals",
        "aria-hidden",
        "aria-disabled",
        "element.readOnly",
        "pointerEvents",
        "style.opacity",
        "rect.right",
        "rect.bottom",
    )

    for token in required:
        assert token in script


def test_capture_can_optionally_return_raw_payload(
    tmp_path,
):
    browser = FakeBrowser(
        _payload()
    )

    result = (
        dom_inspector.capture_dom_snapshot(
            browser,
            tmp_path,
            label="raw_payload",
            include_payload=True,
        )
    )

    assert isinstance(
        result["raw_payload"],
        dict,
    )

    assert (
        result["raw_payload"][
            "schema_version"
        ]
        == dom_inspector.DOM_CAPTURE_SCHEMA_VERSION
    )

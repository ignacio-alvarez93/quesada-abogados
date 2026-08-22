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

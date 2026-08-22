import json

import pytest

from backend.automation.site_architecture import (
    adapt_qcc_extension_capture,
    persist_site_architecture_from_qcc_capture,
)


def _frame_result(
    *,
    url,
    title,
    element_id,
):
    return {
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00Z",
        "url": url,
        "origin":
            "https://example.test",
        "pathname":
            "/form",
        "title": title,
        "ready_state":
            "complete",
        "content_type":
            "text/html",
        "character_set":
            "UTF-8",
        "html":
            "<html></html>",
        "counts": {
            "elements": 1,
            "buttons": 1,
        },
        "elements": [{
            "index": 0,
            "tag": "button",
            "id": element_id,
            "name": "",
            "type": "button",
            "role": "",
            "attributes": {},
            "text": "Continuar",
            "visible": True,
            "disabled": False,
        }],
        "shadow_roots": [],
    }


def _capture():
    return {
        "ok": True,
        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00Z",
        "tab_id": 10,
        "captured_frames": 2,
        "frames": [
            {
                "frame_id": 0,
                "document_id": "doc-main",
                "result": _frame_result(
                    url="https://example.test/form",
                    title="Main",
                    element_id="continue",
                ),
            },
            {
                "frame_id": 7,
                "document_id": "doc-child",
                "result": _frame_result(
                    url="https://example.test/frame",
                    title="Child",
                    element_id="child-button",
                ),
            },
        ],
    }


def test_qcc_capture_is_adapted_without_inventing_geometry():
    raw = adapt_qcc_extension_capture(
        _capture()
    )

    assert raw["schema_version"] == 1
    assert (
        raw["metadata"]["title"]
        == "Main"
    )

    assert len(raw["documents"]) == 2
    assert len(raw["elements"]) == 2
    assert len(raw["frames"]) == 1

    assert (
        raw["elements"][0]["frame_path"]
        == "main"
    )

    assert (
        raw["elements"][1]["frame_path"]
        == "qcc-frame:7"
    )

    assert raw["viewport"] == {}

    assert (
        raw["elements"][0][
            "interaction_signals"
        ]["in_viewport"]
        is None
    )


def test_qcc_capture_rejects_unknown_type():
    payload = _capture()
    payload["capture_type"] = "OTHER"

    with pytest.raises(
        ValueError,
        match="QCC_EXTENSION_CAPTURE_TYPE_INVALID",
    ):
        adapt_qcc_extension_capture(
            payload
        )


def test_qcc_capture_persists_as_canonical_snapshot(
    tmp_path,
):
    result = (
        persist_site_architecture_from_qcc_capture(
            _capture(),
            tmp_path,
        )
    )

    payload = json.loads(
        result["snapshot_path"]
        .read_text(
            encoding="utf-8"
        )
    )

    assert (
        payload["page"]["title"]
        == "Main"
    )

    assert len(
        payload["elements"]
    ) == 2

    main = payload["elements"][0]

    assert (
        main["selectors"]["primary"][
            "selector"
        ]
        == "#continue"
    )

    assert (
        main["geometry"]["viewport_rect"]
        is None
    )

    assert (
        main["interaction"]["interactable"]
        is False
    )


def test_qcc_capture_requires_real_main_frame():
    payload = _capture()

    payload["frames"] = [
        payload["frames"][1]
    ]

    with pytest.raises(
        ValueError,
        match="QCC_EXTENSION_CAPTURE_MAIN_FRAME_MISSING",
    ):
        adapt_qcc_extension_capture(
            payload
        )


def test_qcc_capture_rejects_unknown_frame_schema():
    payload = _capture()

    payload["frames"][1]["result"][
        "schema_version"
    ] = 99

    with pytest.raises(
        ValueError,
        match="QCC_EXTENSION_FRAME_SCHEMA_UNSUPPORTED",
    ):
        adapt_qcc_extension_capture(
            payload
        )

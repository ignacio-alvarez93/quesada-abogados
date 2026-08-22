import json

from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


def _capture():
    frame = {
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00Z",
        "url":
            "https://example.test/form",
        "origin":
            "https://example.test",
        "pathname":
            "/form",
        "hostname":
            "example.test",
        "title":
            "Página prueba",
        "ready_state":
            "complete",
        "content_type":
            "text/html",
        "character_set":
            "UTF-8",
        "html":
            "<html><body></body></html>",
        "counts": {
            "elements": 0,
        },
        "elements": [],
        "shadow_roots": [],
    }

    return {
        "ok": True,
        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00Z",
        "tab_id": 1,
        "captured_frames": 1,
        "frames": [{
            "frame_id": 0,
            "document_id": "main-doc",
            "result": frame,
        }],
    }


def test_ingestor_supports_manual_chrome(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    result = ingestor.ingest(
        _capture()
    )

    assert (
        result["context_mode"]
        == "MANUAL"
    )
    assert result["session_id"] is None

    capture_dir = (
        tmp_path
        / result["capture_id"]
    )

    assert (
        capture_dir
        / "qcc_capture.json"
    ).exists()

    assert (
        capture_dir
        / "site_architecture.json"
    ).exists()

    metadata = json.loads(
        (
            capture_dir
            / "metadata.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        metadata["page"]["title"]
        == "Página prueba"
    )


def test_ingestor_enriches_assisted_presentation(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    result = ingestor.ingest(
        _capture(),
        context={
            "active": True,
            "active_session": {
                "session_id":
                    "merc-test-001",
                "provider":
                    "MERCURIO",
                "runtime":
                    "SELENIUMBASE_ASSISTED",
            },
        },
    )

    assert (
        result["context_mode"]
        == "ASSISTED_PRESENTATION"
    )

    assert (
        result["session_id"]
        == "merc-test-001"
    )

    assert (
        result["active_session"][
            "provider"
        ]
        == "MERCURIO"
    )


def test_invalid_capture_leaves_no_partial_artifacts(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture = _capture()
    capture["capture_type"] = "INVALID"

    try:
        ingestor.ingest(
            capture
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "invalid capture should fail"
        )

    assert list(
        tmp_path.iterdir()
    ) == []

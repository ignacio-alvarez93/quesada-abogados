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

    assert (
        result["target_mode"]
        == "PASSIVE_INSPECTION"
    )

    assert (
        result["site_target"]["origin"]
        == "https://example.test"
    )

    assert (
        result["site_target"]["host"]
        == "example.test"
    )

    assert (
        result["site_target"]["pathname"]
        == "/form"
    )

    assert (
        result["site_target"]["site_code"]
        is None
    )

    assert (
        result["site_target"]["environment"]
        is None
    )

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
        == "MANUAL"
    )

    assert (
        result["session_id"]
        is None
    )

    assert (
        result["active_session"]
        is None
    )

    assert (
        result["session_bound"]
        is False
    )

    # La captura sigue siendo una operación
    # pasiva aunque exista runtime asistido.
    assert (
        result["target_mode"]
        == "PASSIVE_INSPECTION"
    )

    assert (
        result["site_target"]["site_code"]
        is None
    )

    assert (
        result["site_target"]["environment"]
        is None
    )


def test_site_target_metadata_hides_query_and_fragment(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture = _capture()

    capture["frames"][0]["result"]["url"] = (
        "https://example.test/form"
        "?session=SECRET123"
        "#private-section"
    )

    result = ingestor.ingest(
        capture
    )

    target = result[
        "site_target"
    ]

    serialized = repr(
        target
    )

    assert "SECRET123" not in serialized
    assert "private-section" not in serialized

    assert (
        target["pathname"]
        == "/form"
    )

    assert (
        target["has_query"]
        is True
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



def test_ingestor_attaches_viewport_visual_artifact(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture_result = ingestor.ingest(
        _capture()
    )

    capture_id = capture_result[
        "capture_id"
    ]

    png = (
        b"\x89PNG\r\n\x1a\n"
        b"QCC_TEST_VIEWPORT"
    )

    result = (
        ingestor.attach_visual_artifact(
            capture_id,
            kind="viewport",
            content=png,
        )
    )

    capture_dir = (
        tmp_path
        / capture_id
    )

    screenshot = (
        capture_dir
        / "screenshot_viewport.png"
    )

    assert screenshot.exists()
    assert screenshot.read_bytes() == png

    assert (
        result["kind"]
        == "viewport"
    )

    assert (
        result["artifact"]
        == "screenshot_viewport.png"
    )

    metadata = json.loads(
        (
            capture_dir
            / "metadata.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        metadata[
            "artifacts"
        ][
            "screenshot_viewport"
        ]
        == "screenshot_viewport.png"
    )

    assert (
        metadata[
            "visual_evidence"
        ][
            "schema_version"
        ]
        == 1
    )

    assert (
        metadata[
            "visual_evidence"
        ][
            "viewport"
        ][
            "content_type"
        ]
        == "image/png"
    )

    assert (
        metadata[
            "visual_evidence"
        ][
            "viewport"
        ][
            "bytes"
        ]
        == len(png)
    )


def test_ingestor_visual_artifact_rejects_unknown_kind(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture_id = (
        ingestor.ingest(
            _capture()
        )[
            "capture_id"
        ]
    )

    try:
        ingestor.attach_visual_artifact(
            capture_id,
            kind="desktop",
            content=(
                b"\x89PNG\r\n\x1a\nBAD"
            ),
        )

    except ValueError as exc:
        assert (
            str(exc)
            == "QCC_VISUAL_ARTIFACT_KIND_INVALID"
        )

    else:
        raise AssertionError(
            "Unknown visual artifact kind accepted"
        )


def test_ingestor_visual_artifact_rejects_path_traversal(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    try:
        ingestor.attach_visual_artifact(
            "../outside",
            kind="viewport",
            content=(
                b"\x89PNG\r\n\x1a\nBAD"
            ),
        )

    except ValueError as exc:
        assert (
            str(exc)
            == "QCC_VISUAL_ARTIFACT_CAPTURE_ID_INVALID"
        )

    else:
        raise AssertionError(
            "Path traversal capture_id accepted"
        )


def test_ingestor_visual_artifact_rejects_non_png(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture_id = (
        ingestor.ingest(
            _capture()
        )[
            "capture_id"
        ]
    )

    try:
        ingestor.attach_visual_artifact(
            capture_id,
            kind="viewport",
            content=b"NOT_A_PNG",
        )

    except ValueError as exc:
        assert (
            str(exc)
            == "QCC_VISUAL_ARTIFACT_PNG_INVALID"
        )

    else:
        raise AssertionError(
            "Non-PNG visual artifact accepted"
        )

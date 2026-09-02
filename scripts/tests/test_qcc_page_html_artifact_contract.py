from pathlib import Path

from backend.qcc.site_architecture.ingestor import (
    QCC_HTML_ARTIFACT_FILENAME,
    QCC_HTML_EVIDENCE_SCHEMA_VERSION,
    _extract_main_frame_html,
)


INGESTOR = Path(
    "backend/qcc/site_architecture/ingestor.py"
)


def test_extract_main_frame_html_uses_frame_zero():
    capture = {
        "frames": [
            {
                "frame_id": 3,
                "result": {
                    "html":
                        "<html><body>iframe</body></html>",
                },
            },
            {
                "frame_id": 0,
                "result": {
                    "html":
                        "<html><body>main</body></html>",
                },
            },
        ],
    }

    assert (
        _extract_main_frame_html(
            capture
        )
        == "<html><body>main</body></html>"
    )


def test_extract_main_frame_html_does_not_mutate_html():
    html = (
        '<html lang="es">'
        "<body>QCC</body>"
        "</html>"
    )

    capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "html": html,
                },
            },
        ],
    }

    assert (
        _extract_main_frame_html(
            capture
        )
        == html
    )

    assert (
        not _extract_main_frame_html(
            capture
        ).startswith(
            "<!DOCTYPE"
        )
    )


def test_extract_main_frame_html_is_fail_open():
    assert (
        _extract_main_frame_html(
            {}
        )
        is None
    )

    assert (
        _extract_main_frame_html(
            {
                "frames": [
                    {
                        "frame_id": 0,
                        "result": {},
                    },
                ],
            }
        )
        is None
    )


def test_page_html_artifact_contract():
    assert (
        QCC_HTML_EVIDENCE_SCHEMA_VERSION
        == 1
    )

    assert (
        QCC_HTML_ARTIFACT_FILENAME
        == "page.html"
    )


def test_ingestor_materializes_html_evidence():
    source = INGESTOR.read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_PAGE_HTML_MATERIALIZED_V1",
        "QCC_HTML_EVIDENCE_METADATA_V1",
        "_extract_main_frame_html(",
        '"page_html"',
        '"html_evidence"',
        '"text/html; charset=utf-8"',
        '"document.documentElement.outerHTML"',
    )

    for token in required:
        assert token in source

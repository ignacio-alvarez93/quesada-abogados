import json
from pathlib import Path
from urllib.request import (
    Request,
    urlopen,
)

import pytest

from backend.qcc.bridge.server import (
    QccBridgeServer,
)

from backend.qcc.site_architecture.ingestor import (
    QCC_PAGE_ARCHIVE_ARTIFACT_FILENAMES,
    QCC_PAGE_ARCHIVE_EVIDENCE_SCHEMA_VERSION,
    QccSiteArchitectureIngestor,
)


def _mhtml():
    return (
        b"From: <Saved by Blink>\r\n"
        b"Snapshot-Content-Location: https://example.com/\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/related; "
        b'boundary="qcc-boundary"\r\n'
        b"\r\n"
        b"--qcc-boundary\r\n"
        b"Content-Type: text/html\r\n"
        b"Content-Location: https://example.com/\r\n"
        b"\r\n"
        b"<html><body>QCC</body></html>\r\n"
        b"--qcc-boundary--\r\n"
    )


def _seed_capture(root, capture_id):
    capture_dir = (
        root
        / capture_id
    )

    capture_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    (
        capture_dir
        / "metadata.json"
    ).write_text(
        json.dumps(
            {
                "capture_id":
                    capture_id,

                "artifacts": {
                    "metadata":
                        "metadata.json",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return capture_dir


def test_page_mhtml_artifact_contract():
    assert (
        QCC_PAGE_ARCHIVE_EVIDENCE_SCHEMA_VERSION
        == 1
    )

    assert (
        QCC_PAGE_ARCHIVE_ARTIFACT_FILENAMES[
            "mhtml"
        ]
        == "page.mhtml"
    )


def test_ingestor_attaches_page_mhtml(tmp_path):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    capture_id = (
        "capture_mhtml_test"
    )

    capture_dir = _seed_capture(
        tmp_path,
        capture_id,
    )

    content = _mhtml()

    result = (
        ingestor
        .attach_page_archive_artifact(
            capture_id,
            kind="mhtml",
            content=content,
        )
    )

    artifact = (
        capture_dir
        / "page.mhtml"
    )

    assert artifact.exists()

    assert (
        artifact.read_bytes()
        == content
    )

    assert (
        result["bytes"]
        == len(content)
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
            "page_mhtml"
        ]
        == "page.mhtml"
    )

    evidence = (
        metadata[
            "page_archive_evidence"
        ][
            "mhtml"
        ]
    )

    assert (
        evidence["source"]
        == "chrome.pageCapture.saveAsMHTML"
    )

    assert (
        evidence["bytes"]
        == len(content)
    )


def test_ingestor_rejects_invalid_mhtml(tmp_path):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    capture_id = (
        "capture_invalid_mhtml"
    )

    _seed_capture(
        tmp_path,
        capture_id,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_PAGE_ARCHIVE_MHTML_INVALID"
        ),
    ):
        (
            ingestor
            .attach_page_archive_artifact(
                capture_id,
                kind="mhtml",
                content=b"not-mhtml",
            )
        )


def test_bridge_accepts_page_mhtml(tmp_path):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    capture_id = (
        "capture_bridge_mhtml"
    )

    capture_dir = _seed_capture(
        tmp_path,
        capture_id,
    )

    server = QccBridgeServer(
        port=0,
        site_architecture_ingestor=ingestor,
    )

    server.start()

    try:
        request = Request(
            (
                "http://"
                + server.host
                + ":"
                + str(server.port)
                + "/qcc/site-architecture/page-artifact"
            ),
            data=_mhtml(),
            method="POST",
            headers={
                "Content-Type":
                    "multipart/related",

                "X-QCC-Protocol-Version":
                    "1",

                "X-QCC-Capture-Id":
                    capture_id,

                "X-QCC-Page-Kind":
                    "mhtml",
            },
        )

        with urlopen(
            request,
            timeout=5,
        ) as response:
            payload = json.loads(
                response
                .read()
                .decode(
                    "utf-8"
                )
            )

        assert (
            payload["ok"]
            is True
        )

        assert (
            payload["artifact"]
            == "page.mhtml"
        )

        assert (
            (
                capture_dir
                / "page.mhtml"
            ).exists()
        )

    finally:
        server.close()

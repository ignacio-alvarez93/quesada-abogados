import json
from datetime import (
    datetime,
    timezone,
)
from urllib.error import HTTPError
from urllib.request import (
    Request,
    urlopen,
)

import backend.qcc.bridge.server as qcc_bridge_server

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


def _capture(
    *,
    html="<html></html>",
):
    return {
        "ok": True,
        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00Z",
        "frames": [{
            "frame_id": 0,
            "document_id": "main",
            "result": {
                "schema_version": 1,
                "captured_at":
                    "2026-08-22T21:00:00Z",
                "url":
                    "https://example.test/",
                "origin":
                    "https://example.test",
                "pathname": "/",
                "title": "QCC Test",
                "ready_state":
                    "complete",
                "content_type":
                    "text/html",
                "character_set":
                    "UTF-8",
                "html": html,
                "counts": {
                    "elements": 0,
                },
                "elements": [],
                "shadow_roots": [],
            },
        }],
    }


def _post(
    base,
    capture,
):
    body = json.dumps({
        "protocol_version":
            QCC_PROTOCOL_VERSION,
        "capture":
            capture,
    }).encode("utf-8")

    request = Request(
        (
            base
            + "/qcc/site-architecture/capture"
        ),
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:
        response = urlopen(
            request,
            timeout=2,
        )
    except HTTPError as exc:
        return (
            exc.code,
            json.loads(
                exc.read().decode("utf-8")
            ),
        )

    with response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_bridge_accepts_capture_without_active_session(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = _post(
            base,
            _capture(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert (
            payload["context_mode"]
            == "MANUAL"
        )
        assert payload["session_id"] is None

    finally:
        bridge.close()


def test_bridge_enriches_capture_with_active_session(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            QccPresentationSession(
                session_id="merc-001",
                expedient_id=1,
                client_id=1,
                procedure="TEST",
                provider="MERCURIO",
                runtime="SELENIUMBASE_ASSISTED",
                started_at=datetime.now(
                    timezone.utc
                ),
                status=(
                    QccPresentationStatus
                    .AUTOMATING
                ),
                current_step="TEST",
                progress=10,
                requires_user_action=False,
            )
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = _post(
            base,
            _capture(),
        )

        assert status == 200
        assert (
            payload["context_mode"]
            == "ASSISTED_PRESENTATION"
        )
        assert (
            payload["session_id"]
            == "merc-001"
        )

    finally:
        bridge.close()


def test_site_architecture_channel_accepts_more_than_64k(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = _post(
            base,
            _capture(
                html=(
                    "<html>"
                    + ("x" * 100_000)
                    + "</html>"
                )
            ),
        )

        assert status == 200
        assert payload["ok"] is True

    finally:
        bridge.close()


def test_site_architecture_channel_has_64m_limit():
    assert (
        qcc_bridge_server
        .QCC_SITE_ARCHITECTURE_MAX_BYTES
        == 64 * 1024 * 1024
    )


def test_site_architecture_channel_rejects_oversize(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        qcc_bridge_server,
        "QCC_SITE_ARCHITECTURE_MAX_BYTES",
        1024,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = _post(
            base,
            _capture(
                html=(
                    "<html>"
                    + ("x" * 2048)
                    + "</html>"
                )
            ),
        )

        assert status == 400

        assert (
            payload["error"]
            == "QCC_SITE_ARCHITECTURE_REQUEST_TOO_LARGE"
        )

        assert list(
            tmp_path.iterdir()
        ) == []

    finally:
        bridge.close()


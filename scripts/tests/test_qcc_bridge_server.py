import json
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from backend.qcc.bridge.server import (
    QCC_BRIDGE_HOST,
    QCC_PROTOCOL_VERSION,
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


@pytest.fixture
def bridge():
    server = QccBridgeServer(
        port=0,
    )

    server.start()

    try:
        yield server
    finally:
        server.close()


def _get_json(
    url: str,
) -> tuple[int, dict]:
    try:
        response = urlopen(
            url,
            timeout=2,
        )
    except HTTPError as exc:
        body = exc.read().decode(
            "utf-8"
        )

        return (
            exc.code,
            json.loads(body),
        )

    with response:
        body = response.read().decode(
            "utf-8"
        )

        return (
            response.status,
            json.loads(body),
        )


def test_bridge_binds_only_to_loopback():
    with pytest.raises(
        ValueError,
        match="QCC_BRIDGE_LOOPBACK_ONLY",
    ):
        QccBridgeServer(
            host="0.0.0.0",
            port=0,
        )


def test_bridge_uses_ephemeral_port_in_tests(
    bridge,
):
    assert bridge.host == QCC_BRIDGE_HOST
    assert bridge.port > 0
    assert bridge.is_running is True


def test_health_endpoint_contract(
    bridge,
):
    status, payload = _get_json(
        f"http://{bridge.host}:"
        f"{bridge.port}/qcc/health"
    )

    assert status == 200

    assert payload == {
        "service": "qcc_bridge",
        "status": "ok",
        "protocol_version":
            QCC_PROTOCOL_VERSION,
    }


def test_unknown_route_is_404(
    bridge,
):
    status, payload = _get_json(
        f"http://{bridge.host}:"
        f"{bridge.port}/unknown"
    )

    assert status == 404

    assert payload == {
        "error": "QCC_ROUTE_NOT_FOUND",
    }


def test_bridge_close_stops_runtime(
    bridge,
):
    assert bridge.is_running is True

    bridge.close()

    assert bridge.is_running is False



def test_context_endpoint_starts_empty(
    bridge,
):
    status, payload = _get_json(
        f"http://{bridge.host}:"
        f"{bridge.port}/qcc/context"
    )

    assert status == 200

    assert payload == {
        "protocol_version":
            QCC_PROTOCOL_VERSION,
        "revision":
            0,
        "active":
            False,
        "active_session":
            None,
    }


def test_context_endpoint_reflects_live_session(
    bridge,
):
    from datetime import (
        datetime,
        timezone,
    )

    session = QccPresentationSession(
        session_id="qcc-live-001",
        expedient_id=1842,
        client_id=321,
        procedure=(
            "REAGRUPACION_FAMILIAR_INICIAL"
        ),
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime(
            2026,
            8,
            22,
            8,
            30,
            tzinfo=timezone.utc,
        ),
        status=(
            QccPresentationStatus.AUTOMATING
        ),
        current_step="UPLOAD_DOCUMENTS",
        progress=68,
        requires_user_action=False,
    )

    bridge.context_store.set_active_session(
        session
    )

    status, payload = _get_json(
        f"http://{bridge.host}:"
        f"{bridge.port}/qcc/context"
    )

    assert status == 200
    assert payload["active"] is True
    assert payload["revision"] == 1

    active = payload["active_session"]

    assert active["session_id"] == (
        "qcc-live-001"
    )

    assert active["provider"] == "MERCURIO"

    assert (
        active["runtime"]
        == "SELENIUMBASE_ASSISTED"
    )

    assert active["progress"] == 68

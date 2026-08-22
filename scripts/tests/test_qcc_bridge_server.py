import json
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from backend.qcc.bridge.server import (
    QCC_BRIDGE_HOST,
    QCC_PROTOCOL_VERSION,
    QccBridgeServer,
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

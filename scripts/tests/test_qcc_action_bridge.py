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

import pytest

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
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


def _session(
    session_id="qcc-actions-001",
):
    return QccPresentationSession(
        session_id=session_id,
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
            .WAITING_USER
        ),
        current_step="DOCUMENTS_READY",
        progress=88,
        requires_user_action=True,
    )


def _post(
    url,
    payload,
):
    request = Request(
        url,
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
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
                exc.read().decode(
                    "utf-8"
                )
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


def test_action_requires_active_session(
    bridge,
):
    status, payload = _post(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/session/qcc-actions-001/action"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
            "action":
                "DOCUMENTS_START",
            "payload":
                {},
        },
    )

    assert status == 409

    assert payload["error"] == (
        "QCC_ACTION_SESSION_NOT_ACTIVE"
    )


def test_action_round_trip_through_bridge(
    bridge,
):
    bridge.context_store.set_active_session(
        _session()
    )

    base = (
        f"http://{bridge.host}:"
        f"{bridge.port}"
    )

    status, submitted = _post(
        (
            base
            + "/qcc/session/"
            + "qcc-actions-001"
            + "/action"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
            "action":
                "DOCUMENT_PREPARE",
            "payload": {
                "document_index": 1,
            },
        },
    )

    assert status == 200
    assert submitted["ok"] is True
    assert submitted["pending"] == 1

    status, consumed = _post(
        (
            base
            + "/qcc/session/"
            + "qcc-actions-001"
            + "/action/consume"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
        },
    )

    assert status == 200
    assert consumed["available"] is True

    action = consumed["action"]

    assert (
        action["session_id"]
        == "qcc-actions-001"
    )

    assert (
        action["action"]
        == "DOCUMENT_PREPARE"
    )

    assert action["payload"] == {
        "document_index": 1,
    }

    status, empty = _post(
        (
            base
            + "/qcc/session/"
            + "qcc-actions-001"
            + "/action/consume"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
        },
    )

    assert status == 200
    assert empty["available"] is False
    assert empty["action"] is None


def test_action_rejects_wrong_session(
    bridge,
):
    bridge.context_store.set_active_session(
        _session()
    )

    status, payload = _post(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/session/other/action"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
            "action":
                "DOCUMENTS_START",
            "payload":
                {},
        },
    )

    assert status == 409

    assert payload["error"] == (
        "QCC_ACTION_SESSION_NOT_ACTIVE"
    )


def test_action_rejects_invalid_document_payload(
    bridge,
):
    bridge.context_store.set_active_session(
        _session()
    )

    status, payload = _post(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/session/qcc-actions-001/action"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,
            "action":
                "DOCUMENT_PREPARE",
            "payload":
                {},
        },
    )

    assert status == 400

    assert payload["error"] == (
        "QCC_ACTION_DOCUMENT_INDEX_INVALID"
    )

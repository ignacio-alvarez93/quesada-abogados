import json
from datetime import (
    datetime,
    timezone,
)
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.action_client import (
    QccActionClient,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


def _active_session():
    return QccPresentationSession(
        session_id="qcc-client-001",
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


def test_action_client_consumes_bridge_action():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _active_session()
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        body = json.dumps(
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,
                "action":
                    "DOCUMENT_PREPARE",
                "payload": {
                    "document_index": 3,
                },
            }
        ).encode(
            "utf-8"
        )

        request = Request(
            (
                base
                + "/qcc/session/"
                + "qcc-client-001"
                + "/action"
            ),
            data=body,
            headers={
                "Content-Type":
                    "application/json",
            },
            method="POST",
        )

        with urlopen(
            request,
            timeout=2,
        ) as response:
            assert response.status == 200

        client = QccActionClient(
            session_id="qcc-client-001",
            bridge_base_url=base,
            timeout=1,
        )

        action = (
            client.consume_next()
        )

        assert action is not None

        assert (
            action["action"]
            == "DOCUMENT_PREPARE"
        )

        assert action["payload"] == {
            "document_index": 3,
        }

        assert (
            client.consume_next()
            is None
        )

    finally:
        bridge.close()


def test_action_client_is_fail_open():
    client = QccActionClient(
        session_id="qcc-missing",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.05,
    )

    assert (
        client.consume_next()
        is None
    )

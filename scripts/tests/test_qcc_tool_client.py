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
from backend.qcc.client.tool_client import (
    QccToolClient,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


def test_tool_client_consumes_dom_inspect():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            QccPresentationSession(
                session_id="tool-client-1",
                expedient_id=1,
                client_id=1,
                procedure="TEST",
                provider="MERCURIO",
                runtime=(
                    "SELENIUMBASE_ASSISTED"
                ),
                started_at=datetime.now(
                    timezone.utc
                ),
                status=(
                    QccPresentationStatus
                    .AUTOMATING
                ),
                current_step="TEST",
                progress=1,
                requires_user_action=False,
            )
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        body = json.dumps(
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,
                "tool":
                    "DOM_INSPECT",
                "payload":
                    {},
            }
        ).encode(
            "utf-8"
        )

        request = Request(
            (
                base
                + "/qcc/session/"
                + "tool-client-1"
                + "/tool"
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
        ):
            pass

        client = QccToolClient(
            session_id="tool-client-1",
            bridge_base_url=base,
            timeout=1,
        )

        tool = client.consume_next()

        assert tool is not None

        assert (
            tool["tool"]
            == "DOM_INSPECT"
        )

        assert (
            client.consume_next()
            is None
        )

    finally:
        bridge.close()


def test_tool_client_is_fail_open():
    client = QccToolClient(
        session_id="missing",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.05,
    )

    assert (
        client.consume_next()
        is None
    )

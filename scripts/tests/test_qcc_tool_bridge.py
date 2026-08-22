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
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
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

    with urlopen(
        request,
        timeout=2,
    ) as response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_dom_tool_round_trip_is_independent():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        session = QccPresentationSession(
            session_id="tool-session-1",
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
            progress=1,
            requires_user_action=False,
        )

        bridge.context_store.set_active_session(
            session
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, submitted = _post(
            (
                base
                + "/qcc/session/"
                + "tool-session-1"
                + "/tool"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,
                "client_tool_id":
                    "chrome-tool-1",
                "tool":
                    "DOM_INSPECT",
                "payload":
                    {},
            },
        )

        assert status == 200
        assert submitted["ok"] is True
        assert submitted["pending"] == 1

        # La herramienta NO entra en ActionStore.
        assert (
            bridge.action_store.pending_count(
                "tool-session-1"
            )
            == 0
        )

        status, consumed = _post(
            (
                base
                + "/qcc/session/"
                + "tool-session-1"
                + "/tool/consume"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,
            },
        )

        assert status == 200
        assert consumed["available"] is True

        tool = consumed["tool"]

        assert (
            tool["tool"]
            == "DOM_INSPECT"
        )

        assert tool["payload"] == {}

    finally:
        bridge.close()

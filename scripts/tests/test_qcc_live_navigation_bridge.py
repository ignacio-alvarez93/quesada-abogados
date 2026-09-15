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

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id="navigation-session-1",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="TEST_PROVIDER",
        runtime="TEST_RUNTIME",
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


def _navigation(
    session_id="navigation-session-1",
    *,
    state="STATE_A",
):
    return QccLiveNavigationContext(
        session_id=session_id,
        updated_at=datetime.now(
            timezone.utc
        ),
        current_state=state,
        current_fingerprint="fp-current",
        target_state="STATE_B",
        target_fingerprint="fp-target",
        route_reachable=True,
        remaining_steps=1,
        next_step_kind="BUTTON",
        next_step_policy="NAVIGATION",
        next_step_selector="#continue",
        next_step_frame_path=("main",),
        next_step_confidence=0.98,
        governance_decision="HUMAN_ONLY",
        governance_reason="SITE_POLICY",
        automation_allowed=False,
        display_title="Acción manual",
        display_instruction=(
            "Continúa manualmente."
        ),
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


def test_bridge_projects_live_navigation():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session()
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, response = _post(
            (
                base
                + "/qcc/session/"
                + "navigation-session-1"
                + "/navigation"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    _navigation().to_payload(),
            },
        )

        assert status == 200
        assert response["ok"] is True
        assert response["revision"] == 2

        snapshot = (
            bridge.context_store
            .snapshot()
        )

        live = snapshot[
            "live_navigation"
        ]

        assert (
            live["current"]["state"]
            == "STATE_A"
        )

        assert (
            live["target"]["state"]
            == "STATE_B"
        )

        assert (
            live["governance"]["decision"]
            == "HUMAN_ONLY"
        )

        assert (
            live["governance"][
                "automation_allowed"
            ]
            is False
        )

    finally:
        bridge.close()


def test_navigation_requires_active_session():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, response = _post(
            (
                base
                + "/qcc/session/"
                + "navigation-session-1"
                + "/navigation"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    _navigation().to_payload(),
            },
        )

        assert status == 409

        assert response["error"] == (
            "QCC_LIVE_NAVIGATION_SESSION_NOT_ACTIVE"
        )

    finally:
        bridge.close()


def test_navigation_rejects_payload_session_mismatch():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session(
                "session-a"
            )
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, response = _post(
            (
                base
                + "/qcc/session/"
                + "session-a"
                + "/navigation"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    _navigation(
                        "session-b"
                    ).to_payload(),
            },
        )

        assert status == 409

        assert response["error"] == (
            "QCC_LIVE_NAVIGATION_SESSION_MISMATCH"
        )

        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

    finally:
        bridge.close()


def test_navigation_rejects_invalid_protocol():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session()
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, response = _post(
            (
                base
                + "/qcc/session/"
                + "navigation-session-1"
                + "/navigation"
            ),
            {
                "protocol_version":
                    999,

                "navigation":
                    _navigation().to_payload(),
            },
        )

        assert status == 400

        assert response["error"] == (
            "QCC_PROTOCOL_VERSION_INVALID"
        )

    finally:
        bridge.close()


def test_navigation_rejects_unapproved_nested_field():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session()
        )

        navigation = (
            _navigation().to_payload()
        )

        navigation[
            "next_step"
        ]["text"] = (
            "DOM text must not pass"
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, response = _post(
            (
                base
                + "/qcc/session/"
                + "navigation-session-1"
                + "/navigation"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    navigation,
            },
        )

        assert status == 400

        assert (
            "QCC_LIVE_NAVIGATION_FIELD_NOT_ALLOWED"
            in response["error"]
        )

        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

    finally:
        bridge.close()


def test_navigation_snapshot_is_replaceable():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session()
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        url = (
            base
            + "/qcc/session/"
            + "navigation-session-1"
            + "/navigation"
        )

        status, first = _post(
            url,
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    _navigation(
                        state="STATE_A"
                    ).to_payload(),
            },
        )

        assert status == 200
        assert first["revision"] == 2

        status, second = _post(
            url,
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "navigation":
                    _navigation(
                        state="STATE_B"
                    ).to_payload(),
            },
        )

        assert status == 200
        assert second["revision"] == 3

        assert (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ][
                "current"
            ][
                "state"
            ]
            == "STATE_B"
        )

    finally:
        bridge.close()

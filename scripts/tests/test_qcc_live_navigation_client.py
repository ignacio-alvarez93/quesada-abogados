from datetime import (
    datetime,
    timezone,
)

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.navigation_client import (
    QccLiveNavigationClient,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id="client-navigation-1",
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
    session_id="client-navigation-1",
):
    return QccLiveNavigationContext(
        session_id=session_id,
        updated_at=datetime.now(
            timezone.utc
        ),
        current_state="STATE_A",
        current_fingerprint="fp-a",
        target_state="STATE_B",
        target_fingerprint="fp-b",
        route_reachable=True,
        remaining_steps=1,
        governance_decision="HUMAN_ONLY",
        governance_reason="SITE_POLICY",
        automation_allowed=False,
    )


def test_client_publishes_navigation_end_to_end():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            _session()
        )

        client = QccLiveNavigationClient(
            session_id=(
                "client-navigation-1"
            ),
            bridge_base_url=(
                f"http://{bridge.host}:"
                f"{bridge.port}"
            ),
            timeout=1,
        )

        assert (
            client.publish(
                _navigation()
            )
            is True
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["state"]
            == "STATE_A"
        )

        assert (
            live["governance"]["decision"]
            == "HUMAN_ONLY"
        )

    finally:
        bridge.close()


def test_client_rejects_different_session_fail_open():
    client = QccLiveNavigationClient(
        session_id="session-a",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.05,
    )

    assert (
        client.publish(
            _navigation(
                "session-b"
            )
        )
        is False
    )


def test_client_is_fail_open_without_bridge():
    client = QccLiveNavigationClient(
        session_id="client-navigation-1",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.05,
    )

    assert (
        client.publish(
            _navigation()
        )
        is False
    )


def test_client_rejects_non_navigation_object():
    client = QccLiveNavigationClient(
        session_id="client-navigation-1",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.05,
    )

    assert (
        client.publish(
            object()
        )
        is False
    )


def test_navigation_client_has_no_browser_control():
    from pathlib import Path

    source = Path(
        "backend/qcc/client/"
        "navigation_client.py"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "seleniumbase",
        "webdriver",
        "pyautogui",
        "click_js",
        "browser_actions",
    )

    lowered = source.lower()

    for token in forbidden:
        assert token not in lowered

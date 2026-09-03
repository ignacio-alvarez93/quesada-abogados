import json
from datetime import (
    datetime,
    timezone,
)
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id,
    *,
    provider="MERCURIO",
    status=QccPresentationStatus.AUTOMATING,
    progress=25,
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider=provider,
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(
            timezone.utc
        ),
        status=status,
        current_step="RUNNING",
        progress=progress,
        requires_user_action=False,
    )


def _get_json(
    url,
):
    try:
        response = urlopen(
            url,
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


def test_profile_context_returns_exact_browser_not_legacy():
    bridge = QccBridgeServer(
        port=0,
    )

    session_a = _session(
        "session-a",
        progress=21,
    )

    session_b = _session(
        "session-b",
        progress=84,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-a",
        session=session_a,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-b",
        session=session_b,
    )

    # Legacy apunta deliberadamente al navegador B.
    bridge.context_store.set_active_session(
        session_b
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/context"
                "?browser_profile_key=profile-a"
            )
        )

        assert status == 200

        assert (
            payload[
                "browser_profile_key"
            ]
            == "profile-a"
        )

        assert (
            payload[
                "active_session"
            ]["session_id"]
            == "session-a"
        )

        assert (
            payload[
                "active_session"
            ]["progress"]
            == 21
        )

    finally:
        bridge.close()


def test_legacy_context_endpoint_remains_last_global_projection():
    bridge = QccBridgeServer(
        port=0,
    )

    legacy = _session(
        "legacy-session"
    )

    bridge.context_store.set_active_session(
        legacy
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "session-a"
        ),
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/context"
            )
        )

        assert status == 200

        assert (
            payload[
                "active_session"
            ]["session_id"]
            == "legacy-session"
        )

        # Contrato legacy: no añadimos profile_key
        # al payload global.
        assert (
            "browser_profile_key"
            not in payload
        )

    finally:
        bridge.close()


def test_unknown_profile_is_inactive_without_phantom_registration():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "session-a"
        ),
    )

    before = (
        bridge.browser_registry
        .profile_keys()
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/context"
                "?browser_profile_key="
                + quote(
                    "unknown-profile"
                )
            )
        )

        assert status == 200

        assert (
            payload[
                "browser_profile_key"
            ]
            == "unknown-profile"
        )

        assert payload["active"] is False

        assert (
            payload["active_session"]
            is None
        )

        assert (
            bridge.browser_registry
            .profile_keys()
            == before
        )

    finally:
        bridge.close()


def test_empty_profile_query_is_rejected():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/context"
                "?browser_profile_key="
            )
        )

        assert status == 400

        assert (
            payload["error"]
            == "QCC_BROWSER_PROFILE_KEY_REQUIRED"
        )

    finally:
        bridge.close()


def test_duplicate_profile_query_is_rejected():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/context"
                "?browser_profile_key=profile-a"
                "&browser_profile_key=profile-b"
            )
        )

        assert status == 400

        assert (
            payload["error"]
            == "QCC_BROWSER_PROFILE_KEY_AMBIGUOUS"
        )

    finally:
        bridge.close()


def test_browsers_endpoint_lists_profiles_deterministically():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.browser_registry.set_active_session(
        profile_key="z-profile",
        session=_session(
            "z-session",
            provider="TEST_Z",
            progress=90,
        ),
    )

    bridge.browser_registry.set_active_session(
        profile_key="a-profile",
        session=_session(
            "a-session",
            provider="TEST_A",
            progress=10,
        ),
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/browsers"
            )
        )

        assert status == 200

        assert (
            payload[
                "protocol_version"
            ]
            == QCC_PROTOCOL_VERSION
        )

        assert payload["count"] == 2

        assert [
            item[
                "browser_profile_key"
            ]
            for item in payload[
                "browsers"
            ]
        ] == [
            "a-profile",
            "z-profile",
        ]

        first = payload[
            "browsers"
        ][0]

        assert (
            first["session_id"]
            == "a-session"
        )

        assert (
            first["provider"]
            == "TEST_A"
        )

        assert (
            first["progress"]
            == 10
        )

    finally:
        bridge.close()


def test_browsers_endpoint_is_summary_not_full_context_dump():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "session-a"
        ),
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/browsers"
            )
        )

        assert status == 200

        item = payload[
            "browsers"
        ][0]

        assert (
            "active_session"
            not in item
        )

        assert (
            "live_navigation"
            not in item
        )

        assert (
            "navigation_intent"
            not in item
        )

        assert (
            "last_event"
            not in item
        )

    finally:
        bridge.close()


def test_browsers_endpoint_empty_registry_is_valid():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        status, payload = _get_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/browsers"
            )
        )

        assert status == 200
        assert payload["count"] == 0
        assert payload["browsers"] == []

    finally:
        bridge.close()

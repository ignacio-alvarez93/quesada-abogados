import json
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    Request,
    urlopen,
)
from uuid import uuid4

from backend.qcc.bridge.server import (
    QccBridgeServer,
    _qcc_resolve_context_store_for_session,
    _qcc_session_id_from_path,
)
from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


SERVER_SOURCE = Path(
    "backend/qcc/bridge/server.py"
)


def _session(
    session_id,
    *,
    waiting=False,
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
            if waiting
            else
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step=(
            "DOCUMENTS_READY"
            if waiting
            else "RUNNING"
        ),
        progress=50,
        requires_user_action=waiting,
    )


def _post_json(
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


def test_session_path_parser_is_exact():
    assert (
        _qcc_session_id_from_path(
            "/qcc/session/session-a/navigation"
        )
        == "session-a"
    )

    assert (
        _qcc_session_id_from_path(
            "/qcc/session/session%20a/action"
        )
        == "session a"
    )

    assert (
        _qcc_session_id_from_path(
            "/qcc/session"
        )
        is None
    )

    assert (
        _qcc_session_id_from_path(
            "/qcc/context"
        )
        is None
    )


def test_registered_session_resolves_exact_profile_store():
    legacy = QccContextStore()
    registry = QccBrowserRegistry()

    session_a = _session(
        "session-a"
    )

    session_b = _session(
        "session-b"
    )

    legacy.set_active_session(
        session_b
    )

    registry.set_active_session(
        profile_key="profile-a",
        session=session_a,
    )

    registry.set_active_session(
        profile_key="profile-b",
        session=session_b,
    )

    resolved = (
        _qcc_resolve_context_store_for_session(
            legacy_store=legacy,
            browser_registry=registry,
            session_id="session-a",
        )
    )

    assert resolved is (
        registry.get_store(
            "profile-a"
        )
    )

    assert (
        resolved
        .get_active_session()
        .session_id
        == "session-a"
    )


def test_legacy_unregistered_session_keeps_legacy_store():
    legacy = QccContextStore()
    registry = QccBrowserRegistry()

    resolved = (
        _qcc_resolve_context_store_for_session(
            legacy_store=legacy,
            browser_registry=registry,
            session_id="legacy-session",
        )
    )


    assert resolved is legacy

def test_action_for_profile_a_survives_legacy_profile_b():
    # Prueba HTTP real del fallo multi-browser crítico.
    #
    # Legacy apunta a B, pero /session/A/action
    # debe validarse contra el store propietario de A.

    bridge = QccBridgeServer(
        port=0,
    )

    session_a = _session(
        "session-a",
        waiting=True,
    )

    session_b = _session(
        "session-b",
        waiting=True,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-a",
        session=session_a,
    )

    bridge.browser_registry.set_active_session(
        profile_key="profile-b",
        session=session_b,
    )

    # Simula que B fue la última publicación global.
    bridge.context_store.set_active_session(
        session_b
    )

    bridge.start()

    try:
        status, payload = _post_json(
            (
                f"http://{bridge.host}:"
                f"{bridge.port}"
                "/qcc/session/session-a/action"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "client_action_id":
                    str(
                        uuid4()
                    ),

                "action":
                    "DOCUMENTS_START",

                "payload": {},
            },
        )

        assert status == 200
        assert payload["ok"] is True

        # La proyección legacy sigue siendo B.
        assert (
            bridge.context_store
            .get_active_session()
            .session_id
            == "session-b"
        )

        # Y A continúa siendo A en su store.
        assert (
            bridge.browser_registry
            .get_store_for_session(
                "session-a"
            )
            .get_active_session()
            .session_id
            == "session-a"
        )

    finally:
        bridge.close()


def test_do_post_routes_before_session_specific_handlers():
    text = SERVER_SOURCE.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "    def do_POST(self) -> None:"
    )

    end = text.index(
        "class QccBridgeServer:",
        start,
    )

    block = text[
        start:end
    ]

    routing = block.index(
        "QCC_MULTI_BROWSER_SESSION_ROUTING_V1"
    )

    first_session_handler = block.index(
        "# POST /qcc/session/<id>/navigation"
    )

    assert routing < first_session_handler

    assert (
        "_qcc_resolve_context_store_for_session("
        in block
    )

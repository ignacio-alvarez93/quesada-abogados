import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from backend.qcc.bridge.server import QccBridgeServer
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


@pytest.fixture
def bridge():
    server = QccBridgeServer(port=0)
    server.start()

    try:
        yield server
    finally:
        server.close()


def _post(url, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        response = urlopen(request, timeout=2)
    except HTTPError as exc:
        return (exc.code, json.loads(exc.read().decode("utf-8")))

    with response:
        return (response.status, json.loads(response.read().decode("utf-8")))


def _session(
    *,
    session_id="qcc-fill-abort-001",
    status=QccPresentationStatus.WAITING_USER,
    current_step="READY_TO_FILL",
    requires_user_action=True,
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="EX01",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(timezone.utc),
        status=status,
        current_step=current_step,
        progress=35,
        requires_user_action=requires_user_action,
    )


def _action_url(session_id, server):
    return f"http://{server.host}:{server.port}/qcc/session/{session_id}/action"


def test_fill_start_accepted_when_ready_to_fill(bridge):
    bridge.context_store.set_active_session(_session())

    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_FILL_START",
            "payload": {},
        },
    )

    assert status == 200
    assert payload["ok"] is True


def test_fill_start_rejected_when_not_ready_to_fill(bridge):
    bridge.context_store.set_active_session(
        _session(
            status=QccPresentationStatus.AUTOMATING,
            current_step="PROCEDURE_SELECTION",
            requires_user_action=False,
        )
    )

    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_FILL_START",
            "payload": {},
        },
    )

    assert status == 409
    assert payload["error"] == "QCC_ACTION_FILL_NOT_READY"


def test_fill_start_rejected_once_already_filling(bridge):
    """Double click / repeated command while FILLING must not queue a
    second concurrent fill: the server-side status gate is the
    defense-in-depth half of that guarantee."""

    bridge.context_store.set_active_session(
        _session(
            status=QccPresentationStatus.FILLING,
            current_step="FILLING",
            requires_user_action=False,
        )
    )

    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_FILL_START",
            "payload": {},
        },
    )

    assert status == 409
    assert payload["error"] == "QCC_ACTION_FILL_NOT_READY"


def test_abort_accepted_and_queued_for_active_session(bridge):
    bridge.context_store.set_active_session(
        _session(
            status=QccPresentationStatus.AUTOMATING,
            current_step="PROCEDURE_SELECTION",
            requires_user_action=False,
        )
    )

    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_ABORT",
            "payload": {},
        },
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["pending"] == 1

    status, consumed = _post(
        _action_url("qcc-fill-abort-001", bridge) + "/consume",
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 200
    assert consumed["action"]["action"] == "PRESENTATION_ABORT"


def test_abort_is_idempotent_once_already_aborted(bridge):
    bridge.context_store.set_active_session(
        _session(
            status=QccPresentationStatus.ABORTED_BY_USER,
            current_step="ABORTED",
            requires_user_action=False,
        )
    )

    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_ABORT",
            "payload": {},
        },
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["already_aborted"] is True
    assert payload["pending"] == 0

    # Repeating it again is still a stable no-op, never a 4xx.
    status, payload = _post(
        _action_url("qcc-fill-abort-001", bridge),
        {
            "protocol_version": QCC_PROTOCOL_VERSION,
            "action": "PRESENTATION_ABORT",
            "payload": {},
        },
    )

    assert status == 200
    assert payload["already_aborted"] is True

"""QCC_ASSISTED_FILL_REAL_FIX_V2: end-to-end regression over the REAL
SidePanel -> Bridge -> action queue -> runtime channel.

Unlike ``test_qcc_presentation_fill_abort_action_bridge.py`` (which pokes
``context_store`` directly), these tests exercise the actual production
wiring with no shortcuts:

  * ``QccPresentationReporter`` publishes exactly as
    ``app.run_presentacion_asistida`` does (including
    ``browser_profile_key``), over real HTTP, into a real
    ``QccBridgeServer``;
  * the SidePanel-equivalent read (``GET /qcc/context?browser_profile_key=``)
    and the action-submit gate (``POST /qcc/session/<id>/action``) are
    proven to agree on the exact same READY_TO_FILL state;
  * ``QccActionClient.consume_next()`` (the real runtime consumer) is used
    to drain the queue, proving single-queue/single-consume semantics;
  * no fill-shaped action is ever accepted before the operator-equivalent
    command, and an unrelated/invalid session fails closed.

No real browser/SeleniumBase/Mercurio is involved anywhere here.
"""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from backend.qcc.bridge.server import QccBridgeServer
from backend.qcc.client.action_client import QccActionClient
from backend.qcc.client.presentation_reporter import QccPresentationReporter
from backend.qcc.contracts.protocol import QCC_PROTOCOL_VERSION


@pytest.fixture
def bridge():
    server = QccBridgeServer(port=0)
    server.start()
    try:
        yield server
    finally:
        server.close()


def _base(bridge):
    return f"http://{bridge.host}:{bridge.port}"


def _get_json(url):
    with urlopen(url, timeout=2) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_action(bridge, session_id, action, payload=None, client_action_id=None):
    body = {
        "protocol_version": QCC_PROTOCOL_VERSION,
        "action": action,
        "payload": payload or {},
    }
    if client_action_id is not None:
        body["client_action_id"] = client_action_id

    request = Request(
        f"{_base(bridge)}/qcc/session/{session_id}/action",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _reporter(bridge, session_id="qcc-real-chain-001", browser_profile_key="own-browser-key"):
    return QccPresentationReporter(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="EX01",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        browser_profile_key=browser_profile_key,
        browser_session_mode="ASSISTED" if browser_profile_key else None,
        bridge_base_url=_base(bridge),
    )


def test_sidepanel_ready_to_fill_matches_bridge_fill_gate(bridge):
    """Test #1: the exact state the SidePanel would render as
    READY_TO_FILL (via ``GET /qcc/context?browser_profile_key=``) is the
    same state the Bridge's fill-start gate accepts."""

    session_id = "qcc-real-chain-001"
    reporter = _reporter(bridge, session_id=session_id)

    assert reporter.waiting_user(
        step="READY_TO_FILL",
        progress=35,
        message="Formulario listo para volcar datos",
    )

    status, ctx = _get_json(
        f"{_base(bridge)}/qcc/context?browser_profile_key=own-browser-key"
    )
    assert status == 200
    assert ctx["active"] is True

    active_session = ctx["active_session"]
    assert active_session["session_id"] == session_id
    assert active_session["status"] == "WAITING_USER"
    assert active_session["current_step"] == "READY_TO_FILL"
    assert active_session["requires_user_action"] is True

    status, payload = _post_action(bridge, session_id, "PRESENTATION_FILL_START")
    assert status == 200
    assert payload["ok"] is True


def test_fill_start_queued_exactly_once_and_consumed_exactly_once(bridge):
    """Tests #2 and #3: PRESENTATION_FILL_START is queued once and the
    real runtime consumer (``QccActionClient``) drains it exactly once."""

    session_id = "qcc-real-chain-002"
    reporter = _reporter(bridge, session_id=session_id)

    assert reporter.waiting_user(
        step="READY_TO_FILL", progress=35, message="x"
    )

    status, payload = _post_action(
        bridge,
        session_id,
        "PRESENTATION_FILL_START",
        client_action_id="click-1",
    )
    assert status == 200
    assert payload["pending"] == 1

    # A repeated submission with the SAME client_action_id (double
    # click) must not queue a second action.
    status, payload = _post_action(
        bridge,
        session_id,
        "PRESENTATION_FILL_START",
        client_action_id="click-1",
    )
    assert status == 200
    assert payload["pending"] == 1

    action_client = QccActionClient(
        session_id=session_id,
        bridge_base_url=_base(bridge),
    )

    first = action_client.consume_next()
    assert first is not None
    assert first["action"] == "PRESENTATION_FILL_START"

    second = action_client.consume_next()
    assert second is None


def test_fill_cannot_be_queued_before_ready_to_fill(bridge):
    """Test #6: no explicit VOLCAR DATOS-equivalent command can be
    accepted before the runtime has actually reported READY_TO_FILL."""

    session_id = "qcc-real-chain-003"
    reporter = _reporter(bridge, session_id=session_id)

    assert reporter.automating(
        step="PROCEDURE_SELECTION", progress=10, message="x"
    )

    status, payload = _post_action(bridge, session_id, "PRESENTATION_FILL_START")
    assert status == 409
    assert payload["error"] == "QCC_ACTION_FILL_NOT_READY"


def test_fill_fails_closed_for_unrelated_session(bridge):
    """Test #7: a session that never published through the Bridge --
    standing in for an incompatible/unknown page/session -- always
    fails closed, never silently accepted."""

    reporter = _reporter(bridge, session_id="qcc-real-chain-004")
    assert reporter.waiting_user(
        step="READY_TO_FILL", progress=35, message="x"
    )

    status, payload = _post_action(
        bridge, "qcc-completely-unrelated-session", "PRESENTATION_FILL_START"
    )
    assert status == 409
    assert payload["error"] == "QCC_ACTION_SESSION_NOT_ACTIVE"


def test_abort_still_works_through_the_real_publish_chain(bridge):
    """Abort regression over the same real chain: ABORTAR PRESENTACIÓN
    must keep working after the fill-path fix, at any non-terminal
    step, including while READY_TO_FILL is displayed."""

    session_id = "qcc-real-chain-005"
    reporter = _reporter(bridge, session_id=session_id)

    assert reporter.waiting_user(
        step="READY_TO_FILL", progress=35, message="x"
    )

    status, payload = _post_action(bridge, session_id, "PRESENTATION_ABORT")
    assert status == 200
    assert payload["ok"] is True

    action_client = QccActionClient(
        session_id=session_id,
        bridge_base_url=_base(bridge),
    )

    action = action_client.consume_next()
    assert action is not None
    assert action["action"] == "PRESENTATION_ABORT"

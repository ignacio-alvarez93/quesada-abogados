import json
from datetime import datetime, timezone

from backend.qcc.bridge.server import QccBridgeServer

from scripts.tests.test_qcc_human_dom_action_bridge import (
    FP_A,
    _canonical_action,
    _evidence,
    _navigation,
    _post,
    _session,
    _signal_payload,
)

from backend.qcc.contracts.protocol import QCC_PROTOCOL_VERSION


def _ready_bridge_with_teaching(tmp_path):
    bridge = QccBridgeServer(
        port=0,
        human_navigation_candidate_store=None,
    )

    bridge.context_store.set_active_session(_session())
    bridge.context_store.set_live_navigation(_navigation())
    bridge.context_store.set_navigation_environment(
        "REAL",
        session_id="human-session-1",
    )

    evidence = _evidence()
    bridge.context_store.set_live_action_evidence(evidence)

    bridge.start()

    return bridge, evidence


ROUTE = "/qcc/session/human-session-1/human-policy-teaching"


def _teaching_payload(evidence, *, taught_by="SIDE_PANEL", **kwargs):
    base = _signal_payload(evidence, **kwargs)
    base["taught_by"] = taught_by
    return base


def test_teaching_route_creates_human_only_restriction(tmp_path):
    bridge, evidence = _ready_bridge_with_teaching(tmp_path)

    try:
        status, payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["status"] == "CREATED"
        assert payload["resulting_restriction"] == "HUMAN_ONLY"

        restriction = (
            bridge.human_policy_teaching_store.resolve_restriction(
                site_code="MERCURIO",
                environment="REAL",
                kind="BUTTON",
                selector="#continuar",
                frame_path="main",
            )
        )

        assert restriction == "HUMAN_ONLY"

    finally:
        bridge.close()


def test_teaching_route_response_never_echoes_dom_authority(tmp_path):
    bridge, evidence = _ready_bridge_with_teaching(tmp_path)

    try:
        status, payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence),
        )

        assert status == 200

        serialized = json.dumps(payload)

        for forbidden in (
            "#continuar",
            "BUTTON",
            "MERCURIO",
            "REAL",
            FP_A,
            "selector",
            "kind",
            "site_code",
        ):
            assert forbidden not in serialized

    finally:
        bridge.close()


def test_teaching_route_rejects_unknown_actor(tmp_path):
    bridge, evidence = _ready_bridge_with_teaching(tmp_path)

    try:
        status, payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence, taught_by="SOMETHING_ELSE"),
        )

        assert status == 400
        assert payload["error"] == "QCC_HUMAN_POLICY_TEACHING_ACTOR_INVALID"

    finally:
        bridge.close()


def test_teaching_route_rejects_ambiguous_action(tmp_path):
    bridge = QccBridgeServer(port=0)

    bridge.context_store.set_active_session(_session())
    bridge.context_store.set_live_navigation(_navigation())
    bridge.context_store.set_navigation_environment(
        "REAL",
        session_id="human-session-1",
    )

    from backend.qcc.context.live_action_evidence import (
        QccLiveActionEvidence,
    )

    duplicate = _canonical_action()

    evidence = QccLiveActionEvidence(
        session_id="human-session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        actions=(
            {**duplicate, "kind": "LINK"},
            {**duplicate, "kind": "BUTTON"},
        ),
        captured_at=datetime.now(timezone.utc),
    )

    bridge.context_store.set_live_action_evidence(evidence)
    bridge.start()

    try:
        status, payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence),
        )

        assert status == 409
        assert payload["error"] == "QCC_HUMAN_DOM_SIGNAL_ACTION_AMBIGUOUS"

    finally:
        bridge.close()


def test_teaching_route_repeated_call_is_idempotent(tmp_path):
    bridge, evidence = _ready_bridge_with_teaching(tmp_path)

    try:
        first_status, first_payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence, event_id="evt-a"),
        )

        second_status, second_payload = _post(
            bridge,
            ROUTE,
            _teaching_payload(evidence, event_id="evt-b"),
        )

        assert first_status == 200
        assert second_status == 200
        assert first_payload["status"] == "CREATED"
        assert second_payload["status"] == "ALREADY_TAUGHT"
        assert (
            second_payload["resulting_restriction"]
            == "HUMAN_ONLY"
        )

    finally:
        bridge.close()


def test_teaching_route_rejects_protocol_mismatch(tmp_path):
    bridge, evidence = _ready_bridge_with_teaching(tmp_path)

    try:
        payload = _teaching_payload(evidence)
        payload["protocol_version"] = "WRONG"

        status, response = _post(bridge, ROUTE, payload)

        assert status == 400
        assert response["error"] == "QCC_PROTOCOL_VERSION_INVALID"

    finally:
        bridge.close()

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

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.navigation_intent_client import (
    QccNavigationIntentClient,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _session():
    return QccPresentationSession(
        session_id="session-1",
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="TEST_SITE",
        runtime="TEST_RUNTIME",
        started_at=datetime.now(
            timezone.utc
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="DOMAIN_STEP",
        progress=10,
        requires_user_action=False,
    )


def _current():
    return QccLiveNavigationContext(
        session_id="session-1",
        updated_at=datetime.now(
            timezone.utc
        ),
        current_state="STATE_A",
        current_fingerprint=FP_A,
    )


def _transition():
    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "changed":
            True,

        "status":
            STATE_TRANSITION_CHANGED,

        "before_fingerprint":
            FP_A,

        "after_fingerprint":
            FP_B,

        "action": {
            "kind":
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                "#continue",

            "frame_path":
                "main",
        },

        "confidence":
            STATE_TRANSITION_CONFIDENCE_HIGH,

        "contract_changed":
            False,

        "inconclusive":
            False,
    }


def _post(
    bridge,
    session_id,
    intent,
):
    body = json.dumps({
        "protocol_version":
            QCC_PROTOCOL_VERSION,

        "intent":
            intent,
    }).encode(
        "utf-8"
    )

    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/session/"
            + session_id
            + "/navigation-intent"
        ),
        data=body,
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


def test_navigation_intent_roundtrip_contract():
    intent = QccNavigationIntent(
        session_id="session-1",
        site_code="TEST_SITE",
        target_state="STATE_B",
    )

    restored = (
        QccNavigationIntent
        .from_payload(
            intent.to_payload()
        )
    )

    assert restored == intent


def test_bridge_set_intent_immediately_replans(
    tmp_path,
):
    knowledge = NavigationKnowledgeStore(
        root=tmp_path
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    bridge = QccBridgeServer(
        port=0,
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.context_store.set_live_navigation(
        _current()
    )

    bridge.start()

    try:
        intent = QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )

        status, payload = _post(
            bridge,
            "session-1",
            intent.to_payload(),
        )

        assert status == 200
        assert payload["ok"] is True

        assert (
            payload[
                "live_planning"
            ][
                "refreshed"
            ]
            is True
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["fingerprint"]
            == FP_A
        )

        assert (
            live["target"]["fingerprint"]
            == FP_B
        )

        assert (
            live["route"]["remaining_steps"]
            == 1
        )

        assert (
            live["next_step"]["selector"]
            == "#continue"
        )

        assert (
            live["governance"]
            is None
        )

    finally:
        bridge.close()


def test_clear_intent_preserves_current_and_removes_plan(
    tmp_path,
):
    knowledge = NavigationKnowledgeStore(
        root=tmp_path
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    bridge = QccBridgeServer(
        port=0,
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.context_store.set_live_navigation(
        _current()
    )

    bridge.start()

    try:
        intent = QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )

        status, _ = _post(
            bridge,
            "session-1",
            intent.to_payload(),
        )

        assert status == 200

        status, payload = _post(
            bridge,
            "session-1",
            None,
        )

        assert status == 200

        assert (
            bridge.context_store
            .get_navigation_intent()
            is None
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["fingerprint"]
            == FP_A
        )

        assert (
            live["target"]["fingerprint"]
            is None
        )

        assert (
            live["route"]["reachable"]
            is None
        )

        assert live["next_step"] is None
        assert live["governance"] is None

        assert (
            payload[
                "live_planning"
            ][
                "refreshed"
            ]
            is True
        )

    finally:
        bridge.close()


def test_wrong_session_is_rejected(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=tmp_path
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        intent = QccNavigationIntent(
            session_id="other",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )

        status, payload = _post(
            bridge,
            "other",
            intent.to_payload(),
        )

        assert status == 409

        assert (
            payload["error"]
            == "QCC_NAVIGATION_INTENT_SESSION_NOT_ACTIVE"
        )

    finally:
        bridge.close()


def test_wrong_site_is_rejected(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=tmp_path
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        intent = QccNavigationIntent(
            session_id="session-1",
            site_code="OTHER_SITE",
            target_state="STATE_B",
        )

        status, payload = _post(
            bridge,
            "session-1",
            intent.to_payload(),
        )

        assert status == 409

        assert (
            payload["error"]
            == "QCC_NAVIGATION_INTENT_SITE_MISMATCH"
        )

    finally:
        bridge.close()


def test_fail_open_client_can_set_and_clear(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=tmp_path
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        client = QccNavigationIntentClient(
            session_id="session-1",
            bridge_base_url=(
                f"http://{bridge.host}:"
                f"{bridge.port}"
            ),
        )

        intent = QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )

        assert (
            client.publish(
                intent
            )
            is True
        )

        assert (
            bridge.context_store
            .get_navigation_intent()
            is not None
        )

        assert client.clear() is True

        assert (
            bridge.context_store
            .get_navigation_intent()
            is None
        )

    finally:
        bridge.close()

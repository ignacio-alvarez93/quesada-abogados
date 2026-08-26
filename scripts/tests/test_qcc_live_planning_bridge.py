import json
from datetime import (
    datetime,
    timezone,
)
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
from backend.qcc.context.live_planning_coordinator import (
    LIVE_PLANNING_NO_INTENT,
    LIVE_PLANNING_REFRESHED,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
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


class _FakeIngestor:
    def __init__(
        self,
        *,
        session_bound=True,
    ):
        self._session_bound = (
            session_bound
        )

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        if self._session_bound:
            session_id = "session-1"
            site_code = "TEST_SITE"
            context_mode = (
                "ASSISTED_PRESENTATION"
            )
        else:
            session_id = None
            site_code = None
            context_mode = "MANUAL"

        return {
            "capture_id":
                "capture-1",

            "context_mode":
                context_mode,

            "session_id":
                session_id,

            "page": {
                "url":
                    "https://example.test/"
            },

            "site_code":
                site_code,

            "state_observation": {
                "state":
                    "STATE_A",

                "fingerprint":
                    FP_A,
            },

            "counts": {
                "elements": 0,
            },
        }


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


def _post_capture(
    bridge,
):
    body = json.dumps({
        "protocol_version":
            QCC_PROTOCOL_VERSION,

        "capture": {
            "fake":
                True,
        },
    }).encode(
        "utf-8"
    )

    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/site-architecture/capture"
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
    ) as response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_bridge_owns_injected_navigation_knowledge_store(
    tmp_path,
):
    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor()
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    try:
        assert (
            bridge.navigation_knowledge_store
            is knowledge
        )

    finally:
        bridge.close()


def test_capture_projects_and_plans_from_injected_knowledge(
    tmp_path,
):
    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor()
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.context_store.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )
    )

    bridge.start()

    try:
        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is True
        )

        planning = payload[
            "live_planning"
        ]

        assert (
            planning["refreshed"]
            is True
        )

        assert (
            planning["reason"]
            == LIVE_PLANNING_REFRESHED
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"][
                "fingerprint"
            ]
            == FP_A
        )

        assert (
            live["target"][
                "fingerprint"
            ]
            == FP_B
        )

        assert (
            live["route"][
                "reachable"
            ]
            is True
        )

        assert (
            live["route"][
                "remaining_steps"
            ]
            == 1
        )

        assert (
            live["next_step"][
                "selector"
            ]
            == "#continue"
        )

        # El Bridge todavía NO gobierna.
        assert (
            live["governance"]
            is None
        )

    finally:
        bridge.close()


def test_capture_without_intent_keeps_current_only(
    tmp_path,
):
    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor()
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is True
        )

        assert (
            payload[
                "live_planning"
            ][
                "refreshed"
            ]
            is False
        )

        assert (
            payload[
                "live_planning"
            ][
                "reason"
            ]
            == LIVE_PLANNING_NO_INTENT
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"][
                "fingerprint"
            ]
            == FP_A
        )

        assert (
            live["target"][
                "fingerprint"
            ]
            is None
        )

    finally:
        bridge.close()


def test_unprojected_capture_never_replans_stale_current(
    tmp_path,
):
    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor(
                session_bound=False
            )
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.context_store.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_B",
        )
    )

    bridge.start()

    try:
        before_revision = (
            bridge.context_store.revision
        )

        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is False
        )

        # Regla crítica:
        # una captura no vinculada a la sesión
        # no reutiliza un CURRENT anterior.
        assert (
            payload[
                "live_planning"
            ]
            is None
        )

        assert (
            bridge.context_store.revision
            == before_revision
        )

        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

    finally:
        bridge.close()


def test_bridge_default_knowledge_store_is_available():
    bridge = QccBridgeServer(
        port=0
    )

    try:
        assert isinstance(
            bridge.navigation_knowledge_store,
            NavigationKnowledgeStore,
        )

    finally:
        bridge.close()

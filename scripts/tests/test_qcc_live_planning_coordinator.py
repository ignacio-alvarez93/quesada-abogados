from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)
from backend.qcc.context.live_planning_coordinator import (
    LIVE_PLANNING_NO_CURRENT,
    LIVE_PLANNING_NO_INTENT,
    LIVE_PLANNING_REFRESHED,
    LIVE_PLANNING_TARGET_UNRESOLVED,
    refresh_live_navigation_plan,
)
from backend.qcc.context.live_state_projection import (
    project_ingested_state_observation,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


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


def _transition(
    before,
    after,
    *,
    selector,
):
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
            before,

        "after_fingerprint":
            after,

        "action": {
            "kind":
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                selector,

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


def _observe(
    store,
    *,
    fingerprint,
    state,
):
    return (
        project_ingested_state_observation(
            store,
            {
                "session_id":
                    "session-1",

                "site_code":
                    "TEST_SITE",

                "received_at":
                    "2026-08-26T13:00:00+00:00",

                "state_observation": {
                    "state":
                        state,

                    "fingerprint":
                        fingerprint,
                },
            },
        )
    )


def test_without_current_does_not_plan(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    result = (
        refresh_live_navigation_plan(
            context,
            knowledge,
        )
    )

    assert (
        result["refreshed"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_PLANNING_NO_CURRENT
    )


def test_without_intent_preserves_current_only(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    _observe(
        context,
        fingerprint=FP_A,
        state="STATE_A",
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    result = (
        refresh_live_navigation_plan(
            context,
            knowledge,
        )
    )

    assert (
        result["refreshed"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_PLANNING_NO_INTENT
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["current"]["fingerprint"]
        == FP_A
    )

    assert (
        live["target"]["fingerprint"]
        is None
    )


def test_current_intent_and_knowledge_produce_route(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_C",
        )
    )

    _observe(
        context,
        fingerprint=FP_A,
        state="STATE_A",
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            selector="#first",
        ),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(
            FP_B,
            FP_C,
            selector="#second",
        ),
        before_state="STATE_B",
        after_state="STATE_C",
    )

    result = (
        refresh_live_navigation_plan(
            context,
            knowledge,
        )
    )

    assert (
        result["refreshed"]
        is True
    )

    assert (
        result["reason"]
        == LIVE_PLANNING_REFRESHED
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["current"]["state"]
        == "STATE_A"
    )

    assert (
        live["target"]["state"]
        == "STATE_C"
    )

    assert (
        live["target"]["fingerprint"]
        == FP_C
    )

    assert (
        live["route"]["reachable"]
        is True
    )

    assert (
        live["route"]["remaining_steps"]
        == 2
    )

    assert (
        live["next_step"]["selector"]
        == "#first"
    )

    assert (
        live["governance"]
        is None
    )


def test_new_current_recalculates_same_intent(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_C",
        )
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            selector="#first",
        ),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    knowledge.record_transition(
        "TEST_SITE",
        _transition(
            FP_B,
            FP_C,
            selector="#second",
        ),
        before_state="STATE_B",
        after_state="STATE_C",
    )

    _observe(
        context,
        fingerprint=FP_A,
        state="STATE_A",
    )

    refresh_live_navigation_plan(
        context,
        knowledge,
    )

    first = context.snapshot()[
        "live_navigation"
    ]

    assert (
        first["route"]["remaining_steps"]
        == 2
    )

    # Chrome avanza al siguiente estado.
    # La observación invalida el plan viejo.
    _observe(
        context,
        fingerprint=FP_B,
        state="STATE_B",
    )

    between = context.snapshot()[
        "live_navigation"
    ]

    assert (
        between["target"]["state"]
        is None
    )

    assert (
        between["next_step"]
        is None
    )

    # El intent sigue existiendo y la ruta
    # se recalcula desde el CURRENT nuevo.
    refresh_live_navigation_plan(
        context,
        knowledge,
    )

    second = context.snapshot()[
        "live_navigation"
    ]

    assert (
        second["target"]["state"]
        == "STATE_C"
    )

    assert (
        second["route"]["remaining_steps"]
        == 1
    )

    assert (
        second["next_step"]["selector"]
        == "#second"
    )


def test_unknown_target_is_visible_but_not_invented(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="UNKNOWN_TARGET",
        )
    )

    _observe(
        context,
        fingerprint=FP_A,
        state="STATE_A",
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    result = (
        refresh_live_navigation_plan(
            context,
            knowledge,
        )
    )

    assert (
        result["refreshed"]
        is True
    )

    assert (
        result["reason"]
        == LIVE_PLANNING_TARGET_UNRESOLVED
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["target"]["state"]
        == "UNKNOWN_TARGET"
    )

    assert (
        live["target"]["fingerprint"]
        is None
    )

    assert (
        live["route"]["reachable"]
        is None
    )

    assert (
        live["next_step"]
        is None
    )

    assert (
        live["governance"]
        is None
    )


def test_known_but_unreachable_target_is_fail_closed(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_navigation_intent(
        QccNavigationIntent(
            session_id="session-1",
            site_code="TEST_SITE",
            target_state="STATE_C",
        )
    )

    _observe(
        context,
        fingerprint=FP_A,
        state="STATE_A",
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=tmp_path
        )
    )

    # STATE_C existe, pero en una región
    # desconectada del CURRENT A.
    knowledge.record_transition(
        "TEST_SITE",
        _transition(
            FP_B,
            FP_C,
            selector="#isolated",
        ),
        before_state="STATE_B",
        after_state="STATE_C",
    )

    result = (
        refresh_live_navigation_plan(
            context,
            knowledge,
        )
    )

    assert (
        result["reason"]
        == LIVE_PLANNING_TARGET_UNRESOLVED
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["route"]["reachable"]
        is False
    )

    assert (
        live["next_step"]
        is None
    )

    assert (
        live["governance"]
        is None
    )

from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
)
from backend.qcc.context.live_navigation_planner import (
    LIVE_PLAN_GRAPH_INVALID,
    LIVE_PLAN_NO_CURRENT,
    LIVE_PLAN_PROJECTED,
    LIVE_PLAN_TARGET_REQUIRED,
    project_live_navigation_plan,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
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
        current_step="DOMAIN_STEP_NOT_SITE_STATE",
        progress=10,
        requires_user_action=False,
    )


def _current(
    fingerprint=FP_A,
):
    return QccLiveNavigationContext(
        session_id="session-1",
        updated_at=datetime.now(
            timezone.utc
        ),
        current_state="STATE_A",
        current_fingerprint=fingerprint,
    )


def _graph():
    return {
        "schema_version":
            NAVIGATION_GRAPH_SCHEMA_VERSION,

        "graph_type":
            NAVIGATION_GRAPH_TYPE,

        "observation_count":
            2,

        "changed_observation_count":
            2,

        "node_count":
            3,

        "edge_count":
            2,

        "nodes": (
            {
                "fingerprint":
                    FP_A,
                "appearance_count":
                    1,
                "incoming_edge_count":
                    0,
                "outgoing_edge_count":
                    1,
            },
            {
                "fingerprint":
                    FP_B,
                "appearance_count":
                    2,
                "incoming_edge_count":
                    1,
                "outgoing_edge_count":
                    1,
            },
            {
                "fingerprint":
                    FP_C,
                "appearance_count":
                    1,
                "incoming_edge_count":
                    1,
                "outgoing_edge_count":
                    0,
            },
        ),

        "edges": (
            {
                "source_fingerprint":
                    FP_A,

                "target_fingerprint":
                    FP_B,

                "action": {
                    "kind":
                        "SELECT",

                    "policy":
                        "STATE_CHANGE_CANDIDATE",

                    "selector":
                        "#province",

                    "frame_path":
                        "main",
                },

                "observation_count":
                    1,

                "confidence":
                    "HIGH",

                "confidence_counts": {
                    "HIGH": 1,
                    "MEDIUM": 0,
                    "LOW": 0,
                },

                "contract_changed_count":
                    0,

                "inconclusive_count":
                    0,
            },
            {
                "source_fingerprint":
                    FP_B,

                "target_fingerprint":
                    FP_C,

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

                "observation_count":
                    1,

                "confidence":
                    "MEDIUM",

                "confidence_counts": {
                    "HIGH": 0,
                    "MEDIUM": 1,
                    "LOW": 0,
                },

                "contract_changed_count":
                    0,

                "inconclusive_count":
                    0,
            },
        ),
    }


def _store():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _current()
    )

    return store


def test_live_planner_projects_route():
    store = _store()

    result = (
        project_live_navigation_plan(
            store,
            _graph(),
            target_state="STATE_C",
            target_fingerprint=FP_C,
        )
    )

    assert (
        result["projected"]
        is True
    )

    assert (
        result["reason"]
        == LIVE_PLAN_PROJECTED
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

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


def test_live_planner_projects_only_first_step():
    store = _store()

    project_live_navigation_plan(
        store,
        _graph(),
        target_state="STATE_C",
        target_fingerprint=FP_C,
    )

    next_step = (
        store.snapshot()[
            "live_navigation"
        ][
            "next_step"
        ]
    )

    assert (
        next_step["kind"]
        == "SELECT"
    )

    assert (
        next_step["selector"]
        == "#province"
    )

    assert (
        next_step["frame_path"]
        == ["main"]
    )

    assert (
        next_step["confidence"]
        == 1.0
    )


def test_planner_never_governs_or_authorizes():
    store = _store()

    project_live_navigation_plan(
        store,
        _graph(),
        target_state="STATE_C",
        target_fingerprint=FP_C,
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["governance"]
        is None
    )


def test_already_at_target_requires_no_next_step():
    store = _store()

    result = (
        project_live_navigation_plan(
            store,
            _graph(),
            target_state="STATE_A",
            target_fingerprint=FP_A,
        )
    )

    assert (
        result["projected"]
        is True
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["route"]["reachable"]
        is True
    )

    assert (
        live["route"]["remaining_steps"]
        == 0
    )

    assert (
        live["next_step"]
        is None
    )


def test_target_is_explicit_not_inferred_from_current_step():
    store = _store()

    result = (
        project_live_navigation_plan(
            store,
            _graph(),
            target_fingerprint=None,
        )
    )

    assert (
        result["projected"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_PLAN_TARGET_REQUIRED
    )


def test_no_current_state_cannot_plan():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    result = (
        project_live_navigation_plan(
            store,
            _graph(),
            target_fingerprint=FP_C,
        )
    )

    assert (
        result["projected"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_PLAN_NO_CURRENT
    )


def test_invalid_graph_fails_closed():
    store = _store()

    result = (
        project_live_navigation_plan(
            store,
            {
                "invalid": True,
            },
            target_fingerprint=FP_C,
        )
    )

    assert (
        result["projected"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_PLAN_GRAPH_INVALID
    )


def test_new_plan_invalidates_old_governance():
    store = _store()

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="session-1",
            updated_at=datetime.now(
                timezone.utc
            ),
            current_state="STATE_A",
            current_fingerprint=FP_A,
            target_state="OLD_TARGET",
            target_fingerprint=FP_B,
            route_reachable=True,
            remaining_steps=1,
            next_step_kind="BUTTON",
            next_step_policy="REQUIRES_POLICY",
            next_step_selector="#old",
            governance_decision=(
                "AUTOMATION_ALLOWED"
            ),
            governance_reason="OLD_DOM",
            automation_allowed=True,
        )
    )

    project_live_navigation_plan(
        store,
        _graph(),
        target_state="STATE_C",
        target_fingerprint=FP_C,
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["governance"]
        is None
    )

    assert (
        live["target"]["state"]
        == "STATE_C"
    )

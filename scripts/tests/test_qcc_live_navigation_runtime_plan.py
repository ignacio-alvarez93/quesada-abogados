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
from backend.qcc.context.live_navigation_planner import (
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


def _context():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="session-1",
            updated_at=datetime.now(
                timezone.utc
            ),
            current_state="STATE_A",
            current_fingerprint=FP_A,
        )
    )

    return store


def _graph(
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

    return knowledge.build_graph(
        "TEST_SITE"
    )


def test_runtime_plan_is_absent_by_default(
    tmp_path,
):
    result = (
        project_live_navigation_plan(
            _context(),
            _graph(
                tmp_path
            ),
            target_state="STATE_B",
            target_fingerprint=FP_B,
        )
    )

    assert (
        result["projected"]
        is True
    )

    assert (
        "runtime_plan"
        not in result
    )


def test_runtime_plan_can_be_requested_explicitly(
    tmp_path,
):
    context = _context()

    result = (
        project_live_navigation_plan(
            context,
            _graph(
                tmp_path
            ),
            target_state="STATE_B",
            target_fingerprint=FP_B,
            include_runtime_plan=True,
        )
    )

    plan = result[
        "runtime_plan"
    ]

    assert (
        plan["plan_type"]
        == "QCC_NAVIGATION_PLAN"
    )

    assert (
        plan["source_fingerprint"]
        == FP_A
    )

    assert (
        plan["target_fingerprint"]
        == FP_B
    )

    assert (
        plan["next_step"][
            "action"
        ][
            "selector"
        ]
        == "#continue"
    )

    # El plan íntegro NO entra en el contexto.
    snapshot = context.snapshot()

    assert (
        "runtime_plan"
        not in snapshot
    )

    assert (
        snapshot[
            "live_navigation"
        ][
            "next_step"
        ][
            "selector"
        ]
        == "#continue"
    )


def test_runtime_plan_does_not_grant_governance(
    tmp_path,
):
    context = _context()

    result = (
        project_live_navigation_plan(
            context,
            _graph(
                tmp_path
            ),
            target_state="STATE_B",
            target_fingerprint=FP_B,
            include_runtime_plan=True,
        )
    )

    assert (
        result[
            "runtime_plan"
        ][
            "reachable"
        ]
        is True
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert live["governance"] is None

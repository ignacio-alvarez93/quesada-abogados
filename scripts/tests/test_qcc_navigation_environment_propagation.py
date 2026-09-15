from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.navigation_graph import (
    build_navigation_graph,
)
from backend.qcc.context.live_planning_coordinator import (
    refresh_live_navigation_plan,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.context.navigation_target_resolver import (
    resolve_navigation_target,
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


FP_CURRENT = "a" * 64


class RecordingKnowledgeStore(
    NavigationKnowledgeStore
):
    def __init__(
        self,
        *,
        root,
    ):
        super().__init__(
            root=root
        )

        self.calls = []

    def build_graph(
        self,
        site_code,
        *,
        environment="GENERIC",
    ):
        self.calls.append(
            (
                "build_graph",
                site_code,
                str(
                    getattr(
                        environment,
                        "value",
                        environment,
                    )
                ).upper(),
            )
        )

        return build_navigation_graph(
            ()
        )

    def resolve_state_fingerprints(
        self,
        site_code,
        state_code,
        *,
        environment="GENERIC",
    ):
        self.calls.append(
            (
                "resolve_state_fingerprints",
                site_code,
                state_code,
                str(
                    getattr(
                        environment,
                        "value",
                        environment,
                    )
                ).upper(),
            )
        )

        return ()


def _intent():
    return QccNavigationIntent(
        session_id="session-env",
        site_code="TEST_SITE",
        target_state="TARGET",
    )


def _session():
    return QccPresentationSession(
        session_id="session-env",
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
        current_step="TEST",
        progress=10,
        requires_user_action=False,
    )


def _current():
    return QccLiveNavigationContext(
        session_id="session-env",
        updated_at=datetime.now(
            timezone.utc
        ),
        current_state="CURRENT",
        current_fingerprint=(
            FP_CURRENT
        ),
    )


def test_target_resolver_propagates_environment(
    tmp_path,
):
    knowledge = RecordingKnowledgeStore(
        root=(
            tmp_path
            / "knowledge"
        )
    )

    result = resolve_navigation_target(
        knowledge,
        _intent(),
        current_fingerprint=(
            FP_CURRENT
        ),
        environment="REAL",
    )

    assert result["resolved"] is False

    assert knowledge.calls == [
        (
            "build_graph",
            "TEST_SITE",
            "REAL",
        ),
        (
            "resolve_state_fingerprints",
            "TEST_SITE",
            "TARGET",
            "REAL",
        ),
    ]


def test_target_resolver_keeps_generic_default(
    tmp_path,
):
    knowledge = RecordingKnowledgeStore(
        root=(
            tmp_path
            / "knowledge"
        )
    )

    resolve_navigation_target(
        knowledge,
        _intent(),
        current_fingerprint=(
            FP_CURRENT
        ),
    )

    assert knowledge.calls == [
        (
            "build_graph",
            "TEST_SITE",
            "GENERIC",
        ),
        (
            "resolve_state_fingerprints",
            "TEST_SITE",
            "TARGET",
            "GENERIC",
        ),
    ]


def test_live_planning_coordinator_propagates_environment(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_live_navigation(
        _current()
    )

    context.set_navigation_intent(
        _intent()
    )

    knowledge = RecordingKnowledgeStore(
        root=(
            tmp_path
            / "knowledge"
        )
    )

    result = refresh_live_navigation_plan(
        context,
        knowledge,
        environment="LAB",
    )

    assert result["refreshed"] is True

    assert (
        result["reason"]
        == "TARGET_UNRESOLVED"
    )

    assert knowledge.calls == [
        (
            "build_graph",
            "TEST_SITE",
            "LAB",
        ),
        (
            "resolve_state_fingerprints",
            "TEST_SITE",
            "TARGET",
            "LAB",
        ),
    ]


def test_environment_is_not_added_to_public_live_navigation(
    tmp_path,
):
    context = QccContextStore()

    context.set_active_session(
        _session()
    )

    context.set_live_navigation(
        _current()
    )

    context.set_navigation_intent(
        _intent()
    )

    knowledge = RecordingKnowledgeStore(
        root=(
            tmp_path
            / "knowledge"
        )
    )

    refresh_live_navigation_plan(
        context,
        knowledge,
        environment="REAL",
    )

    payload = context.snapshot()

    assert (
        "environment"
        not in payload
    )

    assert (
        "environment"
        not in (
            payload.get(
                "live_navigation"
            )
            or {}
        )
    )

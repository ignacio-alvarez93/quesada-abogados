from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceOrigin,
    ManagedSiteGovernanceRegistration,
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_DENY,
    SITE_INTERACTION_HUMAN_ONLY,
    SiteInteractionPolicy,
)
from backend.qcc.context.live_governance_coordinator import (
    LIVE_GOVERNANCE_APPLIED,
    LIVE_GOVERNANCE_MANAGED_SITE_UNRESOLVED,
    LIVE_GOVERNANCE_RUNTIME_PLAN_UNAVAILABLE,
    LIVE_GOVERNANCE_SITE_MISMATCH,
    apply_live_navigation_governance,
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


def _profile(
    environment,
):
    return ManagedSiteProfile(
        site_code="TEST_SITE",
        environment=environment,
        allowed_origins=(
            "https://managed.example.test",
        ),
        allowed_path_prefixes=(
            "/app",
        ),
        interaction_policy=(
            "TEST_POLICY"
        ),
    )


def _policy():
    return SiteInteractionPolicy(
        policy_code="TEST_POLICY",
        site_code="TEST_SITE",
        action_kind_rules={
            "BUTTON":
                "HUMAN_ONLY",

            "SELECT":
                "AUTOMATION_ALLOWED",
        },
    )


def _registry():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        ManagedSiteGovernanceRegistration(
            site_code="TEST_SITE",
            origins=(
                ManagedSiteGovernanceOrigin(
                    environment="REAL",
                    origin=(
                        "https://managed.example.test"
                    ),
                ),
            ),
            profile_builder=_profile,
            policy_builder=_policy,
        )
    )

    return registry


def _session(
    *,
    provider="TEST_SITE",
):
    return QccPresentationSession(
        session_id="session-1",
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider=provider,
        runtime="TEST_RUNTIME",
        started_at=datetime.now(
            timezone.utc
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
    )


def _context(
    *,
    provider="TEST_SITE",
    kind="BUTTON",
    policy="REQUIRES_POLICY",
    selector="#continue",
):
    store = QccContextStore()

    store.set_active_session(
        _session(
            provider=provider
        )
    )

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="session-1",
            updated_at=datetime.now(
                timezone.utc
            ),

            current_state="STATE_A",
            current_fingerprint=FP_A,

            target_state="STATE_B",
            target_fingerprint=FP_B,

            route_reachable=True,
            remaining_steps=1,

            next_step_kind=kind,
            next_step_policy=policy,
            next_step_selector=selector,
            next_step_frame_path=(
                "main",
            ),
            next_step_confidence=1.0,

            governance_decision=None,
            governance_reason=None,
            automation_allowed=None,
        )
    )

    return store


def _action(
    *,
    kind="BUTTON",
    policy="REQUIRES_POLICY",
    selector="#continue",
    visible=True,
    disabled=False,
    interactable=True,
):
    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            "main",

        "interaction": {
            "visible":
                visible,

            "disabled":
                disabled,

            "interactable":
                interactable,
        },
    }


def _plan(
    *,
    kind="BUTTON",
    policy="REQUIRES_POLICY",
    selector="#continue",
):
    action = {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            "main",
    }

    step = {
        "index":
            1,

        "source_fingerprint":
            FP_A,

        "target_fingerprint":
            FP_B,

        "action":
            action,

        "confidence":
            "HIGH",

        "observation_count":
            1,

        "contract_changed_count":
            0,

        "inconclusive_count":
            0,
    }

    return {
        "schema_version":
            1,

        "plan_type":
            "QCC_NAVIGATION_PLAN",

        "source_fingerprint":
            FP_A,

        "target_fingerprint":
            FP_B,

        "reachable":
            True,

        "status":
            "ROUTE_FOUND",

        "reason":
            "ROUTE_FOUND",

        "route_fingerprints":
            (
                FP_A,
                FP_B,
            ),

        "step_count":
            1,

        "remaining_steps":
            1,

        "next_step":
            step,

        "steps":
            (
                step,
            ),

        "visited_node_count":
            1,
    }


def _planning(
    **kwargs,
):
    return {
        "refreshed":
            True,

        "reason":
            "REFRESHED",

        "target_resolution":
            {
                "resolved":
                    True,
            },

        "planning": {
            "projected":
                True,

            "reason":
                "PROJECTED",

            "runtime_plan":
                _plan(
                    **kwargs
                ),
        },
    }


def test_live_button_is_projected_human_only():
    context = _context()

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning()
            ),
            live_actions=(
                _action(),
            ),
            page_url=(
                "https://managed.example.test"
                "/app/form"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["applied"]
        is True
    )

    assert (
        result["reason"]
        == LIVE_GOVERNANCE_APPLIED
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )

    assert (
        result["automation_allowed"]
        is False
    )

    live = (
        context.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["governance"][
            "decision"
        ]
        == SITE_INTERACTION_HUMAN_ONLY
    )

    assert (
        live["governance"][
            "automation_allowed"
        ]
        is False
    )

    # 9F no altera la ruta calculada por 9E.
    assert (
        live["next_step"]["selector"]
        == "#continue"
    )

    assert (
        live["route"]["remaining_steps"]
        == 1
    )


def test_live_select_can_be_automation_allowed():
    context = _context(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#province",
    )

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning(
                    kind="SELECT",
                    policy=(
                        "STATE_CHANGE_CANDIDATE"
                    ),
                    selector="#province",
                )
            ),
            live_actions=(
                _action(
                    kind="SELECT",
                    policy=(
                        "STATE_CHANGE_CANDIDATE"
                    ),
                    selector="#province",
                ),
            ),
            page_url=(
                "https://managed.example.test"
                "/app/form"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    )

    assert (
        result["automation_allowed"]
        is True
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["governance"][
            "automation_allowed"
        ]
        is True
    )


def test_missing_live_action_fails_closed():
    context = _context()

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning()
            ),
            live_actions=(),
            page_url=(
                "https://managed.example.test"
                "/app/form"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["automation_allowed"]
        is False
    )

    live = context.snapshot()[
        "live_navigation"
    ]

    assert (
        live["governance"][
            "reason"
        ]
        == "LIVE_ACTION_NOT_OBSERVED"
    )


def test_hidden_live_action_fails_generic_safety():
    context = _context(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#province",
    )

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning(
                    kind="SELECT",
                    policy=(
                        "STATE_CHANGE_CANDIDATE"
                    ),
                    selector="#province",
                )
            ),
            live_actions=(
                _action(
                    kind="SELECT",
                    policy=(
                        "STATE_CHANGE_CANDIDATE"
                    ),
                    selector="#province",
                    visible=False,
                    interactable=False,
                ),
            ),
            page_url=(
                "https://managed.example.test"
                "/app/form"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        context.snapshot()[
            "live_navigation"
        ][
            "governance"
        ][
            "reason"
        ]
        == "GENERIC_SAFETY_DENY"
    )


def test_unknown_managed_origin_is_denied():
    context = _context()

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning()
            ),
            live_actions=(
                _action(),
            ),
            page_url=(
                "https://unknown.example.test"
                "/app"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == LIVE_GOVERNANCE_MANAGED_SITE_UNRESOLVED
    )

    assert (
        result["automation_allowed"]
        is False
    )


def test_session_site_mismatch_is_denied():
    context = _context(
        provider="OTHER_SITE"
    )

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                _planning()
            ),
            live_actions=(
                _action(),
            ),
            page_url=(
                "https://managed.example.test"
                "/app"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == LIVE_GOVERNANCE_SITE_MISMATCH
    )


def test_runtime_plan_is_required_not_synthesized():
    context = _context()

    planning_result = {
        "refreshed":
            True,

        "reason":
            "REFRESHED",

        "planning": {
            "projected":
                True,

            # Deliberadamente sin runtime_plan.
        },
    }

    before = context.revision

    result = (
        apply_live_navigation_governance(
            context,
            _registry(),
            planning_result=(
                planning_result
            ),
            live_actions=(
                _action()
            ),
            page_url=(
                "https://managed.example.test"
                "/app"
            ),
            site_code="TEST_SITE",
        )
    )

    assert (
        result["applied"]
        is False
    )

    assert (
        result["reason"]
        == LIVE_GOVERNANCE_RUNTIME_PLAN_UNAVAILABLE
    )

    # El coordinador no inventa un plan desde
    # QccLiveNavigationContext.
    assert context.revision == before

    assert (
        context.snapshot()[
            "live_navigation"
        ][
            "governance"
        ]
        is None
    )


def test_live_governance_does_not_change_current_or_target():
    context = _context()

    before = (
        context.snapshot()[
            "live_navigation"
        ]
    )

    apply_live_navigation_governance(
        context,
        _registry(),
        planning_result=(
            _planning()
        ),
        live_actions=(
            _action(),
        ),
        page_url=(
            "https://managed.example.test"
            "/app/form"
        ),
        site_code="TEST_SITE",
    )

    after = (
        context.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        after["current"]
        == before["current"]
    )

    assert (
        after["target"]
        == before["target"]
    )

    assert (
        after["route"]
        == before["route"]
    )

    assert (
        after["next_step"]
        == before["next_step"]
    )

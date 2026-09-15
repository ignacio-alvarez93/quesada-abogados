from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_DENY,
    SITE_INTERACTION_HUMAN_ONLY,
)
from backend.automation.site_policies.default_registry import (
    build_default_managed_site_governance_registry,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_REAL_ORIGIN,
)
from backend.qcc.context.live_governance_coordinator import (
    LIVE_GOVERNANCE_MANAGED_SITE_UNRESOLVED,
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


def _context(
    *,
    kind,
    policy,
    selector,
):
    store = QccContextStore()

    store.set_active_session(
        QccPresentationSession(
            session_id="merc-1",
            expedient_id=1,
            client_id=1,
            procedure="TEST",
            provider="MERCURIO",
            runtime="TEST_RUNTIME",
            started_at=datetime.now(
                timezone.utc
            ),
            status=(
                QccPresentationStatus
                .AUTOMATING
            ),
        )
    )

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="merc-1",
            updated_at=datetime.now(
                timezone.utc
            ),
            current_state="ENTRY",
            current_fingerprint=FP_A,
            target_state="NEXT",
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
        )
    )

    return store


def _planning(
    kind,
    policy,
    selector,
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
        "refreshed":
            True,

        "planning": {
            "projected":
                True,

            "runtime_plan": {
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
            },
        },
    }


def _live(
    kind,
    policy,
    selector,
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
                True,

            "disabled":
                False,

            "interactable":
                True,
        },
    }


def test_mercurio_real_button_is_human_only_jit():
    context = _context(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#continue",
    )

    result = (
        apply_live_navigation_governance(
            context,
            build_default_managed_site_governance_registry(),
            planning_result=(
                _planning(
                    "BUTTON",
                    "REQUIRES_POLICY",
                    "#continue",
                )
            ),
            live_actions=(
                _live(
                    "BUTTON",
                    "REQUIRES_POLICY",
                    "#continue",
                ),
            ),
            page_url=(
                MERCURIO_REAL_ORIGIN
                + "/mercurio/"
                "entradaMercurio.html"
            ),
            site_code="MERCURIO",
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )

    assert (
        result["automation_allowed"]
        is False
    )


def test_mercurio_real_select_can_be_allowed_jit():
    context = _context(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#provincia",
    )

    result = (
        apply_live_navigation_governance(
            context,
            build_default_managed_site_governance_registry(),
            planning_result=(
                _planning(
                    "SELECT",
                    "STATE_CHANGE_CANDIDATE",
                    "#provincia",
                )
            ),
            live_actions=(
                _live(
                    "SELECT",
                    "STATE_CHANGE_CANDIDATE",
                    "#provincia",
                ),
            ),
            page_url=(
                MERCURIO_REAL_ORIGIN
                + "/mercurio/"
                "entradaMercurio.html"
            ),
            site_code="MERCURIO",
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


def test_mercurio_selector_not_seen_now_is_denied():
    context = _context(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#continue",
    )

    result = (
        apply_live_navigation_governance(
            context,
            build_default_managed_site_governance_registry(),
            planning_result=(
                _planning(
                    "BUTTON",
                    "REQUIRES_POLICY",
                    "#continue",
                )
            ),
            live_actions=(),
            page_url=(
                MERCURIO_REAL_ORIGIN
                + "/mercurio/"
                "entradaMercurio.html"
            ),
            site_code="MERCURIO",
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
        == "LIVE_ACTION_NOT_OBSERVED"
    )


def test_recognizable_but_unmanaged_sede_is_denied():
    context = _context(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#continue",
    )

    result = (
        apply_live_navigation_governance(
            context,
            build_default_managed_site_governance_registry(),
            planning_result=(
                _planning(
                    "BUTTON",
                    "REQUIRES_POLICY",
                    "#continue",
                )
            ),
            live_actions=(
                _live(
                    "BUTTON",
                    "REQUIRES_POLICY",
                    "#continue",
                ),
            ),
            page_url=(
                "https://sede."
                "administracionespublicas.gob.es/"
            ),
            site_code="MERCURIO",
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

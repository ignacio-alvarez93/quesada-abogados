from backend.automation.site_architecture import (
    govern_navigation_plan,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_HUMAN_ONLY,
)
from backend.automation.site_architecture.site_target import (
    SiteTarget,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
    MERCURIO_SITE_CODE,
    build_mercurio_interaction_policy,
    build_mercurio_profile,
)


def _plan(
    action,
):
    step = {
        "index":
            1,

        "source_fingerprint":
            "ENTRY",

        "target_fingerprint":
            "NEXT",

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
            "ENTRY",

        "target_fingerprint":
            "NEXT",

        "reachable":
            True,

        "status":
            "ROUTE_FOUND",

        "reason":
            "ROUTE_FOUND",

        "route_fingerprints":
            (
                "ENTRY",
                "NEXT",
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


def _target(
    origin,
    environment,
):
    return SiteTarget(
        url=(
            origin
            + "/mercurio/"
            "entradaMercurio.html"
        ),
        mode="MANAGED_EXECUTION",
        site_code=MERCURIO_SITE_CODE,
        environment=environment,
    )


def test_mercurio_real_continue_is_human_only():
    action = {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            "#continue",

        "frame_path":
            "main",
    }

    result = govern_navigation_plan(
        _plan(
            action
        ),
        target=_target(
            MERCURIO_REAL_ORIGIN,
            "REAL",
        ),
        profile=(
            build_mercurio_profile(
                "REAL"
            )
        ),
        policy=(
            build_mercurio_interaction_policy()
        ),
        current_actions=(
            _live(
                "BUTTON",
                "REQUIRES_POLICY",
                "#continue",
            ),
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )

    assert (
        result["automation_allowed"]
        is False
    )


def test_mercurio_lab_continue_is_also_human_only():
    action = {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            "#continue",

        "frame_path":
            "main",
    }

    result = govern_navigation_plan(
        _plan(
            action
        ),
        target=_target(
            MERCURIO_LAB_ORIGIN,
            "LAB",
        ),
        profile=(
            build_mercurio_profile(
                "LAB"
            )
        ),
        policy=(
            build_mercurio_interaction_policy()
        ),
        current_actions=(
            _live(
                "BUTTON",
                "REQUIRES_POLICY",
                "#continue",
            ),
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )


def test_mercurio_select_preparation_can_be_automated():
    action = {
        "kind":
            "SELECT",

        "policy":
            "STATE_CHANGE_CANDIDATE",

        "selector":
            "#provincia",

        "frame_path":
            "main",
    }

    result = govern_navigation_plan(
        _plan(
            action
        ),
        target=_target(
            MERCURIO_REAL_ORIGIN,
            "REAL",
        ),
        profile=(
            build_mercurio_profile(
                "REAL"
            )
        ),
        policy=(
            build_mercurio_interaction_policy()
        ),
        current_actions=(
            _live(
                "SELECT",
                "STATE_CHANGE_CANDIDATE",
                "#provincia",
            ),
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    )

    assert (
        result["automation_allowed"]
        is True
    )

from copy import deepcopy
from pathlib import Path

from backend.automation.site_architecture.governed_navigation import (
    GOVERNED_NAVIGATION_NO_ACTION,
    GOVERNED_NAVIGATION_OBSERVE_ONLY,
    GOVERNED_NAVIGATION_TYPE,
    govern_navigation_plan,
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
from backend.automation.site_architecture.site_target import (
    SiteTarget,
)


def _target(
    *,
    url=(
        "https://portal.example.test"
        "/managed/form"
    ),
):
    return SiteTarget(
        url=url,
        mode="MANAGED_EXECUTION",
        site_code="SITE_ALPHA",
        environment="REAL",
    )


def _profile():
    return ManagedSiteProfile(
        site_code="SITE_ALPHA",
        environment="REAL",
        allowed_origins=(
            "https://portal.example.test",
        ),
        allowed_path_prefixes=(
            "/managed",
        ),
        interaction_policy=(
            "SITE_ALPHA_DEFAULT"
        ),
    )


def _policy():
    return SiteInteractionPolicy(
        policy_code=(
            "SITE_ALPHA_DEFAULT"
        ),
        site_code="SITE_ALPHA",
        action_kind_rules={
            "SELECT":
                "AUTOMATION_ALLOWED",

            "BUTTON":
                "HUMAN_ONLY",
        },
    )


def _action(
    *,
    kind,
    policy,
    selector,
    visible=True,
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

            "interactable":
                visible,

            "disabled":
                False,
        },
    }


def _step(
    index,
    source,
    target,
    action,
):
    return {
        "index":
            index,

        "source_fingerprint":
            source,

        "target_fingerprint":
            target,

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


def _plan(
    *steps,
    reachable=True,
    status="ROUTE_FOUND",
):
    steps = tuple(
        steps
    )

    return {
        "schema_version":
            1,

        "plan_type":
            "QCC_NAVIGATION_PLAN",

        "source_fingerprint":
            "A",

        "target_fingerprint":
            (
                steps[-1][
                    "target_fingerprint"
                ]
                if steps
                else "A"
            ),

        "reachable":
            reachable,

        "status":
            status,

        "reason":
            status,

        "route_fingerprints":
            (),

        "step_count":
            len(
                steps
            ),

        "remaining_steps":
            len(
                steps
            ),

        "next_step":
            (
                steps[0]
                if steps
                else None
            ),

        "steps":
            steps,

        "visited_node_count":
            1,
    }


def test_button_is_human_only_when_live_action_matches():
    planned = {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            "#continue",

        "frame_path":
            "main",
    }

    live = _action(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#continue",
    )

    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                planned,
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            live,
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


def test_select_can_be_automation_allowed():
    planned = {
        "kind":
            "SELECT",

        "policy":
            "STATE_CHANGE_CANDIDATE",

        "selector":
            "#province",

        "frame_path":
            "main",
    }

    live = _action(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#province",
    )

    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                planned,
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            live,
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


def test_planned_action_missing_from_live_dom_fails_closed():
    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                {
                    "kind":
                        "BUTTON",

                    "policy":
                        "REQUIRES_POLICY",

                    "selector":
                        "#continue",

                    "frame_path":
                        "main",
                },
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == "LIVE_ACTION_NOT_OBSERVED"
    )


def test_hidden_live_action_fails_generic_safety():
    planned = {
        "kind":
            "SELECT",

        "policy":
            "STATE_CHANGE_CANDIDATE",

        "selector":
            "#province",

        "frame_path":
            "main",
    }

    hidden = _action(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#province",
        visible=False,
    )

    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                planned,
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            hidden,
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == "GENERIC_SAFETY_DENY"
    )


def test_automatic_transition_is_observe_only():
    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                None,
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(),
    )

    assert (
        result["decision"]
        == GOVERNED_NAVIGATION_OBSERVE_ONLY
    )

    assert (
        result["automation_allowed"]
        is False
    )

    assert (
        result["reason"]
        == "AUTOMATIC_TRANSITION"
    )


def test_future_steps_are_not_pre_authorized():
    first = _step(
        1,
        "A",
        "B",
        {
            "kind":
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                "#one",

            "frame_path":
                "main",
        },
    )

    second = _step(
        2,
        "B",
        "C",
        {
            "kind":
                "SELECT",

            "policy":
                "STATE_CHANGE_CANDIDATE",

            "selector":
                "#future",

            "frame_path":
                "main",
        },
    )

    live = _action(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#one",
    )

    result = govern_navigation_plan(
        _plan(
            first,
            second,
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            live,
        ),
    )

    assert (
        result["governed_step_index"]
        == 1
    )

    assert (
        result["unevaluated_step_count"]
        == 1
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )


def test_unauthorized_target_blocks_before_action_policy():
    planned = {
        "kind":
            "SELECT",

        "policy":
            "STATE_CHANGE_CANDIDATE",

        "selector":
            "#province",

        "frame_path":
            "main",
    }

    live = _action(
        kind="SELECT",
        policy="STATE_CHANGE_CANDIDATE",
        selector="#province",
    )

    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                planned,
            )
        ),
        target=_target(
            url=(
                "https://portal.example.test"
                "/outside/form"
            )
        ),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            live,
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert result[
        "reason"
    ].startswith(
        "MANAGED_TARGET_DENIED:"
    )


def test_already_at_target_requires_no_action():
    result = govern_navigation_plan(
        _plan(
            reachable=True,
            status="ALREADY_AT_TARGET",
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(),
    )

    assert (
        result["decision"]
        == GOVERNED_NAVIGATION_NO_ACTION
    )


def test_live_action_payload_does_not_leak():
    planned = {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            "#continue",

        "frame_path":
            "main",
    }

    live = _action(
        kind="BUTTON",
        policy="REQUIRES_POLICY",
        selector="#continue",
    )

    live["text"] = "PERSONAL DATA"
    live["value"] = "SECRET"

    result = govern_navigation_plan(
        _plan(
            _step(
                1,
                "A",
                "B",
                planned,
            )
        ),
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            live,
        ),
    )

    serialized = repr(
        result
    )

    assert "PERSONAL DATA" not in serialized
    assert "SECRET" not in serialized


def test_input_plan_is_not_mutated():
    plan = _plan(
        _step(
            1,
            "A",
            "B",
            {
                "kind":
                    "BUTTON",

                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    "#continue",

                "frame_path":
                    "main",
            },
        )
    )

    before = deepcopy(
        plan
    )

    govern_navigation_plan(
        plan,
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        current_actions=(
            _action(
                kind="BUTTON",
                policy="REQUIRES_POLICY",
                selector="#continue",
            ),
        ),
    )

    assert plan == before


def test_generic_module_has_no_provider_coupling():
    source = Path(
        "backend/automation/"
        "site_architecture/"
        "governed_navigation.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    assert "MERCURIO" not in source
    assert "ICP_PLUS" not in source
    assert "DEHU" not in source


def test_governed_navigation_is_public_api():
    from backend.automation import (
        site_architecture,
    )

    assert (
        site_architecture
        .GOVERNED_NAVIGATION_TYPE
        == "QCC_GOVERNED_NAVIGATION"
    )

    assert (
        site_architecture
        .govern_navigation_plan
        is govern_navigation_plan
    )

    assert (
        GOVERNED_NAVIGATION_TYPE
        == "QCC_GOVERNED_NAVIGATION"
    )

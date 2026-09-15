import pytest

from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_DENY,
    evaluate_site_interaction,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
)
from backend.automation.site_policies.default_registry import (
    build_default_managed_site_governance_registry,
)
from backend.automation.site_policies.red_sara import (
    RED_SARA_CAPABILITIES,
    RED_SARA_INTERACTION_POLICY_CODE,
    RED_SARA_REAL_ORIGIN,
    RED_SARA_SITE_CODE,
    build_red_sara_interaction_policy,
    build_red_sara_profile,
)


REAL_URL = (
    RED_SARA_REAL_ORIGIN
    + "/es/"
)


def test_default_registry_resolves_red_sara_real():
    registry = (
        build_default_managed_site_governance_registry()
    )

    registration = (
        registry.get_by_site_code(
            RED_SARA_SITE_CODE
        )
    )

    assert registration is not None

    resolved = registry.resolve(
        url=REAL_URL,
        site_code=RED_SARA_SITE_CODE,
    )

    assert resolved is not None

    assert (
        resolved.environment
        == SiteEnvironment.REAL
    )

    assert (
        resolved.site_code
        == RED_SARA_SITE_CODE
    )

    assert (
        resolved.profile.site_code
        == RED_SARA_SITE_CODE
    )

    assert (
        resolved.profile.interaction_policy
        == RED_SARA_INTERACTION_POLICY_CODE
    )

    assert (
        resolved.policy.site_code
        == RED_SARA_SITE_CODE
    )


def test_red_sara_initial_profile_is_observation_only():
    profile = (
        build_red_sara_profile(
            SiteEnvironment.REAL
        )
    )

    assert (
        profile.allowed_origins
        == (
            RED_SARA_REAL_ORIGIN,
        )
    )

    assert (
        profile.allowed_path_prefixes
        == (
            "/",
        )
    )

    assert (
        profile.capabilities
        == RED_SARA_CAPABILITIES
    )

    assert (
        "STATE_OBSERVATION"
        in profile.capabilities
    )


def test_red_sara_policy_grants_no_automation_rules():
    policy = (
        build_red_sara_interaction_policy()
    )

    assert (
        policy.action_kind_rules
        == {}
    )


def test_red_sara_unknown_action_is_fail_closed():
    registry = (
        build_default_managed_site_governance_registry()
    )

    resolved = registry.resolve(
        url=REAL_URL,
        site_code=RED_SARA_SITE_CODE,
    )

    result = evaluate_site_interaction(
        target=resolved.target,
        profile=resolved.profile,
        policy=resolved.policy,
        action={
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                (
                    "dnt-horizontal-menu-item"
                    '[idoption="2"]'
                ),

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
        },
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["automation_allowed"]
        is False
    )


def test_red_sara_lab_is_not_invented():
    with pytest.raises(
        ValueError,
        match="RED_SARA_ENVIRONMENT_INVALID",
    ):
        build_red_sara_profile(
            SiteEnvironment.LAB
        )


def test_red_sara_wrong_origin_does_not_resolve():
    registry = (
        build_default_managed_site_governance_registry()
    )

    resolved = registry.resolve(
        url=(
            "https://example.invalid/es/"
        ),
        site_code=(
            RED_SARA_SITE_CODE
        ),
    )

    assert resolved is None

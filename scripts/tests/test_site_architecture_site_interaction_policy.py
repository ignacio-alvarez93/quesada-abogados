from pathlib import Path

from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_DENY,
    SITE_INTERACTION_HUMAN_ONLY,
    SiteInteractionPolicy,
    evaluate_site_interaction,
)
from backend.automation.site_architecture.site_target import (
    SiteTarget,
)


def _target():
    return SiteTarget(
        url=(
            "https://portal.example.test"
            "/managed/form"
        ),
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
        policy_code="SITE_ALPHA_DEFAULT",
        site_code="SITE_ALPHA",
        action_kind_rules={
            "INPUT_VALUE":
                "AUTOMATION_ALLOWED",
            "SELECT":
                "AUTOMATION_ALLOWED",
            "LINK":
                "AUTOMATION_ALLOWED",
            "BUTTON":
                "HUMAN_ONLY",
            "SUBMIT":
                "HUMAN_ONLY",
        },
    )


def _action(
    kind,
    policy,
):
    return {
        "kind":
            kind,
        "policy":
            policy,
        "selector":
            "#target",
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


def test_site_can_allow_input_automation():
    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        action=_action(
            "INPUT_VALUE",
            "VALUE_CHANGE_CANDIDATE",
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


def test_site_can_allow_navigation():
    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        action=_action(
            "LINK",
            "NAVIGATION_CANDIDATE",
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    )


def test_site_can_force_button_human_only():
    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        action=_action(
            "BUTTON",
            "REQUIRES_POLICY",
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


def test_site_can_force_submit_human_only():
    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        action=_action(
            "SUBMIT",
            "REQUIRES_POLICY",
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )


def test_generic_deny_cannot_be_overridden():
    policy = SiteInteractionPolicy(
        policy_code="SITE_ALPHA_DEFAULT",
        site_code="SITE_ALPHA",
        action_kind_rules={
            "SELECT":
                "AUTOMATION_ALLOWED",
        },
    )

    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=policy,
        action=_action(
            "SELECT",
            "NAVIGATION_CANDIDATE",
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


def test_missing_site_rule_fails_closed():
    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=_policy(),
        action=_action(
            "CHECKBOX",
            "STATE_CHANGE_CANDIDATE",
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == "SITE_INTERACTION_RULE_MISSING"
    )


def test_policy_identity_mismatch_fails_closed():
    policy = SiteInteractionPolicy(
        policy_code="OTHER_POLICY",
        site_code="SITE_ALPHA",
        action_kind_rules={
            "INPUT_VALUE":
                "AUTOMATION_ALLOWED",
        },
    )

    result = evaluate_site_interaction(
        target=_target(),
        profile=_profile(),
        policy=policy,
        action=_action(
            "INPUT_VALUE",
            "VALUE_CHANGE_CANDIDATE",
        ),
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_DENY
    )

    assert (
        result["reason"]
        == "SITE_INTERACTION_POLICY_MISMATCH"
    )


def test_generic_policy_has_no_provider_names():
    source = Path(
        "backend/automation/site_architecture/"
        "site_interaction_policy.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    assert "MERCURIO" not in source
    assert "DEHU" not in source
    assert "INSTAGRAM" not in source

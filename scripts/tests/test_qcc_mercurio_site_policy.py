import pytest

from backend.automation.site_architecture.managed_execution import (
    authorize_managed_target,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_HUMAN_ONLY,
    evaluate_site_interaction,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
    SiteTarget,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_ALLOWED_PATH_PREFIXES,
    MERCURIO_CAPABILITIES,
    MERCURIO_INTERACTION_POLICY_CODE,
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
    MERCURIO_SITE_CODE,
    build_mercurio_interaction_policy,
    build_mercurio_profile,
)


def _target(
    environment,
    origin,
):
    return SiteTarget(
        url=(
            origin
            + "/mercurio/"
            + "nuevaSolicitud-EX01.html"
        ),
        mode="MANAGED_EXECUTION",
        site_code=MERCURIO_SITE_CODE,
        environment=environment,
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


def test_lab_and_real_share_functional_policy():
    lab = build_mercurio_profile(
        "LAB"
    )

    real = build_mercurio_profile(
        "REAL"
    )

    assert (
        lab.site_code
        == real.site_code
        == MERCURIO_SITE_CODE
    )

    assert (
        lab.interaction_policy
        == real.interaction_policy
        == MERCURIO_INTERACTION_POLICY_CODE
    )

    assert (
        lab.allowed_path_prefixes
        == real.allowed_path_prefixes
        == MERCURIO_ALLOWED_PATH_PREFIXES
    )

    assert (
        lab.capabilities
        == real.capabilities
        == MERCURIO_CAPABILITIES
    )


def test_lab_and_real_only_change_environment_and_origin():
    lab = build_mercurio_profile(
        SiteEnvironment.LAB
    )

    real = build_mercurio_profile(
        SiteEnvironment.REAL
    )

    assert (
        lab.environment
        == SiteEnvironment.LAB
    )

    assert (
        real.environment
        == SiteEnvironment.REAL
    )

    assert (
        lab.allowed_origins
        == (
            MERCURIO_LAB_ORIGIN,
        )
    )

    assert (
        real.allowed_origins
        == (
            MERCURIO_REAL_ORIGIN,
        )
    )


@pytest.mark.parametrize(
    (
        "environment",
        "origin",
    ),
    (
        (
            "LAB",
            MERCURIO_LAB_ORIGIN,
        ),
        (
            "REAL",
            MERCURIO_REAL_ORIGIN,
        ),
    ),
)
def test_mercurio_target_is_authorized_in_matching_environment(
    environment,
    origin,
):
    profile = (
        build_mercurio_profile(
            environment
        )
    )

    target = _target(
        environment,
        origin,
    )

    result = (
        authorize_managed_target(
            target,
            profile,
        )
    )

    assert result[
        "authorized"
    ] is True


def test_lab_target_is_not_authorized_by_real_profile():
    target = _target(
        "LAB",
        MERCURIO_LAB_ORIGIN,
    )

    profile = (
        build_mercurio_profile(
            "REAL"
        )
    )

    result = (
        authorize_managed_target(
            target,
            profile,
        )
    )

    assert result[
        "authorized"
    ] is False


@pytest.mark.parametrize(
    (
        "kind",
        "generic_policy",
    ),
    (
        (
            "INPUT_VALUE",
            "VALUE_CHANGE_CANDIDATE",
        ),
        (
            "SELECT",
            "STATE_CHANGE_CANDIDATE",
        ),
        (
            "RADIO",
            "STATE_CHANGE_CANDIDATE",
        ),
        (
            "CHECKBOX",
            "STATE_CHANGE_CANDIDATE",
        ),
        (
            "FILE_UPLOAD",
            "REQUIRES_POLICY",
        ),
    ),
)
def test_mercurio_allows_preparation_actions(
    kind,
    generic_policy,
):
    target = _target(
        "REAL",
        MERCURIO_REAL_ORIGIN,
    )

    profile = (
        build_mercurio_profile(
            "REAL"
        )
    )

    policy = (
        build_mercurio_interaction_policy()
    )

    result = (
        evaluate_site_interaction(
            target=target,
            profile=profile,
            policy=policy,
            action=_action(
                kind,
                generic_policy,
            ),
        )
    )

    assert (
        result["decision"]
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    )


@pytest.mark.parametrize(
    (
        "kind",
        "generic_policy",
    ),
    (
        (
            "TAB",
            "NAVIGATION_CANDIDATE",
        ),
        (
            "LINK",
            "NAVIGATION_CANDIDATE",
        ),
        (
            "BUTTON",
            "REQUIRES_POLICY",
        ),
        (
            "SUBMIT",
            "REQUIRES_POLICY",
        ),
    ),
)
def test_mercurio_click_driven_actions_are_human_only(
    kind,
    generic_policy,
):
    target = _target(
        "REAL",
        MERCURIO_REAL_ORIGIN,
    )

    profile = (
        build_mercurio_profile(
            "REAL"
        )
    )

    policy = (
        build_mercurio_interaction_policy()
    )

    result = (
        evaluate_site_interaction(
            target=target,
            profile=profile,
            policy=policy,
            action=_action(
                kind,
                generic_policy,
            ),
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


def test_file_upload_is_not_same_as_attach_button():
    target = _target(
        "REAL",
        MERCURIO_REAL_ORIGIN,
    )

    profile = (
        build_mercurio_profile(
            "REAL"
        )
    )

    policy = (
        build_mercurio_interaction_policy()
    )

    file_result = evaluate_site_interaction(
        target=target,
        profile=profile,
        policy=policy,
        action=_action(
            "FILE_UPLOAD",
            "REQUIRES_POLICY",
        ),
    )

    button_result = evaluate_site_interaction(
        target=target,
        profile=profile,
        policy=policy,
        action=_action(
            "BUTTON",
            "REQUIRES_POLICY",
        ),
    )

    assert (
        file_result["decision"]
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    )

    assert (
        button_result["decision"]
        == SITE_INTERACTION_HUMAN_ONLY
    )


def test_invalid_environment_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "MERCURIO_ENVIRONMENT_INVALID"
        ),
    ):
        build_mercurio_profile(
            "STAGING"
        )

from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceOrigin,
    ManagedSiteGovernanceRegistration,
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SiteInteractionPolicy,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
    SiteTargetMode,
)


def _profile(
    environment,
):
    origin = (
        "https://lab.example.test"
        if environment
        == SiteEnvironment.LAB
        else "https://real.example.test"
    )

    return ManagedSiteProfile(
        site_code="SITE_ALPHA",
        environment=environment,
        allowed_origins=(
            origin,
        ),
        allowed_path_prefixes=(
            "/managed",
        ),
        interaction_policy=(
            "SITE_ALPHA_V1"
        ),
    )


def _policy():
    return SiteInteractionPolicy(
        policy_code="SITE_ALPHA_V1",
        site_code="SITE_ALPHA",
        action_kind_rules={
            "BUTTON":
                "HUMAN_ONLY",

            "SELECT":
                "AUTOMATION_ALLOWED",
        },
    )


def _registration():
    return ManagedSiteGovernanceRegistration(
        site_code="SITE_ALPHA",
        origins=(
            ManagedSiteGovernanceOrigin(
                environment="LAB",
                origin=(
                    "https://lab.example.test"
                ),
            ),
            ManagedSiteGovernanceOrigin(
                environment="REAL",
                origin=(
                    "https://real.example.test"
                ),
            ),
        ),
        profile_builder=_profile,
        policy_builder=_policy,
    )


def test_registry_resolves_environment_from_live_origin():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        _registration()
    )

    resolved = registry.resolve(
        url=(
            "https://lab.example.test"
            "/managed/form?session=secret"
        ),
        site_code="SITE_ALPHA",
    )

    assert resolved is not None

    assert (
        resolved.environment
        == SiteEnvironment.LAB
    )

    assert (
        resolved.target.mode
        == SiteTargetMode.MANAGED_EXECUTION
    )

    assert (
        resolved.target.site_code
        == "SITE_ALPHA"
    )

    assert (
        resolved.profile.environment
        == SiteEnvironment.LAB
    )

    assert (
        resolved.policy.site_code
        == "SITE_ALPHA"
    )


def test_unknown_origin_is_not_governable():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        _registration()
    )

    assert (
        registry.resolve(
            url=(
                "https://unknown.example.test"
                "/managed"
            ),
            site_code="SITE_ALPHA",
        )
        is None
    )


def test_site_mismatch_is_not_governable():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        _registration()
    )

    assert (
        registry.resolve(
            url=(
                "https://real.example.test"
                "/managed"
            ),
            site_code="OTHER_SITE",
        )
        is None
    )


def test_query_never_changes_origin_resolution():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        _registration()
    )

    resolved = registry.resolve(
        url=(
            "https://real.example.test"
            "/managed?token=ABC"
        ),
        site_code="SITE_ALPHA",
    )

    assert resolved is not None

    assert (
        resolved.environment
        == SiteEnvironment.REAL
    )

    assert (
        resolved.target.has_query
        is True
    )


def test_duplicate_origin_is_rejected():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        _registration()
    )

    other = ManagedSiteGovernanceRegistration(
        site_code="SITE_BETA",
        origins=(
            ManagedSiteGovernanceOrigin(
                environment="REAL",
                origin=(
                    "https://real.example.test"
                ),
            ),
        ),
        profile_builder=lambda environment: (
            ManagedSiteProfile(
                site_code="SITE_BETA",
                environment=environment,
                allowed_origins=(
                    "https://real.example.test",
                ),
                allowed_path_prefixes=(
                    "/",
                ),
                interaction_policy="BETA",
            )
        ),
        policy_builder=lambda: (
            SiteInteractionPolicy(
                policy_code="BETA",
                site_code="SITE_BETA",
                action_kind_rules={
                    "BUTTON":
                        "DENY",
                },
            )
        ),
    )

    try:
        registry.register(
            other
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "duplicate origin must fail closed"
        )

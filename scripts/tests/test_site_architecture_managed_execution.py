from pathlib import Path

import pytest

from backend.automation.site_architecture.managed_execution import (
    MANAGED_EXECUTION_AUTHORIZED,
    MANAGED_EXECUTION_DENY,
    ManagedSiteProfile,
    ManagedSiteProfileConfigurationError,
    authorize_managed_target,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
    SiteTarget,
)


def _profile(
    *,
    environment="REAL",
    origins=(
        "https://portal.example.test",
    ),
    paths=(
        "/managed",
    ),
):
    return ManagedSiteProfile(
        site_code="SITE_ALPHA",
        environment=environment,
        allowed_origins=origins,
        allowed_path_prefixes=paths,
        interaction_policy=(
            "SITE_ALPHA_DEFAULT"
        ),
        capabilities=(
            "FORM_FILL",
            "STATE_OBSERVATION",
        ),
    )


def _target(
    *,
    url=(
        "https://portal.example.test"
        "/managed/form"
    ),
    environment="REAL",
):
    return SiteTarget(
        url=url,
        mode="MANAGED_EXECUTION",
        site_code="SITE_ALPHA",
        environment=environment,
    )


def test_authorizes_matching_managed_target():
    result = authorize_managed_target(
        _target(),
        _profile(),
    )

    assert (
        result["decision"]
        == MANAGED_EXECUTION_AUTHORIZED
    )

    assert result["authorized"] is True

    assert (
        result["reason"]
        == "MANAGED_TARGET_AUTHORIZED"
    )


def test_passive_target_is_denied():
    target = SiteTarget(
        url=(
            "https://portal.example.test"
            "/managed/form"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(),
    )

    assert (
        result["decision"]
        == MANAGED_EXECUTION_DENY
    )

    assert (
        result["reason"]
        == "TARGET_NOT_MANAGED"
    )


def test_site_code_mismatch_is_denied():
    target = SiteTarget(
        url=(
            "https://portal.example.test"
            "/managed/form"
        ),
        mode="MANAGED_EXECUTION",
        site_code="OTHER_SITE",
        environment="REAL",
    )

    result = authorize_managed_target(
        target,
        _profile(),
    )

    assert result["authorized"] is False

    assert (
        result["reason"]
        == "SITE_CODE_MISMATCH"
    )


def test_environment_mismatch_is_denied():
    result = authorize_managed_target(
        _target(
            environment="LAB"
        ),
        _profile(
            environment="REAL"
        ),
    )

    assert result["authorized"] is False

    assert (
        result["reason"]
        == "ENVIRONMENT_MISMATCH"
    )


def test_origin_mismatch_is_denied():
    target = _target(
        url=(
            "https://other.example.test"
            "/managed/form"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(),
    )

    assert (
        result["reason"]
        == "ORIGIN_NOT_ALLOWED"
    )


def test_path_outside_profile_is_denied():
    target = _target(
        url=(
            "https://portal.example.test"
            "/private/form"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(),
    )

    assert (
        result["reason"]
        == "PATH_NOT_ALLOWED"
    )


def test_path_prefix_uses_segment_boundary():
    target = _target(
        url=(
            "https://portal.example.test"
            "/managed-other/form"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(
            paths=(
                "/managed",
            )
        ),
    )

    assert (
        result["reason"]
        == "PATH_NOT_ALLOWED"
    )


def test_root_path_profile_allows_entire_origin():
    target = _target(
        url=(
            "https://portal.example.test"
            "/anything/here"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(
            paths=(
                "/",
            )
        ),
    )

    assert result["authorized"] is True


def test_query_does_not_change_path_authorization():
    target = _target(
        url=(
            "https://portal.example.test"
            "/managed/form"
            "?session=SECRET"
        )
    )

    result = authorize_managed_target(
        target,
        _profile(),
    )

    assert result["authorized"] is True

    serialized = repr(
        result
    )

    assert "SECRET" not in serialized


def test_profile_normalizes_contract_values():
    profile = ManagedSiteProfile(
        site_code=" site_alpha ",
        environment="real",
        allowed_origins=(
            "https://PORTAL.EXAMPLE.TEST:443",
        ),
        allowed_path_prefixes=(
            "/managed/",
        ),
        interaction_policy=(
            " site_alpha_default "
        ),
        capabilities=(
            "form_fill",
            "FORM_FILL",
        ),
    )

    assert (
        profile.site_code
        == "SITE_ALPHA"
    )

    assert (
        profile.environment
        == SiteEnvironment.REAL
    )

    assert (
        profile.allowed_origins
        == (
            "https://portal.example.test",
        )
    )

    assert (
        profile.allowed_path_prefixes
        == (
            "/managed",
        )
    )

    assert (
        profile.capabilities
        == (
            "FORM_FILL",
        )
    )


def test_origin_must_not_contain_path():
    with pytest.raises(
        ManagedSiteProfileConfigurationError,
        match=(
            "MANAGED_ORIGIN_MUST_BE_ORIGIN_ONLY"
        ),
    ):
        _profile(
            origins=(
                "https://portal.example.test/path",
            )
        )


def test_profile_requires_origins():
    with pytest.raises(
        ManagedSiteProfileConfigurationError,
        match=(
            "MANAGED_ALLOWED_ORIGINS_REQUIRED"
        ),
    ):
        _profile(
            origins=()
        )


def test_profile_requires_paths():
    with pytest.raises(
        ManagedSiteProfileConfigurationError,
        match=(
            "MANAGED_ALLOWED_PATHS_REQUIRED"
        ),
    ):
        _profile(
            paths=()
        )


def test_profile_requires_interaction_policy():
    with pytest.raises(
        ManagedSiteProfileConfigurationError,
        match=(
            "MANAGED_INTERACTION_POLICY_REQUIRED"
        ),
    ):
        ManagedSiteProfile(
            site_code="SITE_ALPHA",
            environment="REAL",
            allowed_origins=(
                "https://portal.example.test",
            ),
            allowed_path_prefixes=(
                "/",
            ),
            interaction_policy="",
        )


def test_lab_and_real_are_separate_authorizations():
    lab_profile = _profile(
        environment="LAB",
        origins=(
            "http://127.0.0.1:9000",
        ),
    )

    real_profile = _profile(
        environment="REAL",
        origins=(
            "https://portal.example.test",
        ),
    )

    lab_target = _target(
        url=(
            "http://127.0.0.1:9000"
            "/managed/form"
        ),
        environment="LAB",
    )

    assert authorize_managed_target(
        lab_target,
        lab_profile,
    )["authorized"] is True

    assert authorize_managed_target(
        lab_target,
        real_profile,
    )["authorized"] is False


def test_generic_contract_contains_no_provider_names():
    source = Path(
        "backend/automation/site_architecture/"
        "managed_execution.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    assert "MERCURIO" not in source
    assert "DEHU" not in source
    assert "INSTAGRAM" not in source

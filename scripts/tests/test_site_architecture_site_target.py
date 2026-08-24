from pathlib import Path

import pytest

from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
    SiteTarget,
    SiteTargetConfigurationError,
    SiteTargetMode,
)


def test_passive_inspection_accepts_arbitrary_web():
    target = SiteTarget(
        url=(
            "https://example.test/"
            "competitor/posts"
        ),
    )

    assert (
        target.mode
        == SiteTargetMode.PASSIVE_INSPECTION
    )

    assert target.site_code is None
    assert target.environment is None

    assert (
        target.origin
        == "https://example.test"
    )

    assert (
        target.pathname
        == "/competitor/posts"
    )


def test_passive_inspection_needs_no_lab():
    target = SiteTarget(
        url="https://social.example/profile",
        mode="PASSIVE_INSPECTION",
    )

    assert target.environment is None
    assert target.site_code is None


def test_known_site_can_also_be_inspected_passively():
    target = SiteTarget(
        url="https://portal.example/",
        mode="PASSIVE_INSPECTION",
        site_code="portal_x",
        environment="REAL",
    )

    assert (
        target.site_code
        == "PORTAL_X"
    )

    assert (
        target.environment
        == SiteEnvironment.REAL
    )


def test_managed_execution_requires_site_code():
    with pytest.raises(
        SiteTargetConfigurationError,
        match=(
            "SITE_TARGET_SITE_CODE_REQUIRED"
        ),
    ):
        SiteTarget(
            url="https://example.test/",
            mode="MANAGED_EXECUTION",
            environment="REAL",
        )


def test_managed_execution_requires_environment():
    with pytest.raises(
        SiteTargetConfigurationError,
        match=(
            "SITE_TARGET_ENVIRONMENT_REQUIRED"
        ),
    ):
        SiteTarget(
            url="https://example.test/",
            mode="MANAGED_EXECUTION",
            site_code="SITE_ALPHA",
        )


def test_managed_lab_and_real_share_site_identity():
    lab = SiteTarget(
        url="http://127.0.0.1:9000/form",
        mode="MANAGED_EXECUTION",
        site_code="SITE_ALPHA",
        environment="LAB",
    )

    real = SiteTarget(
        url="https://site-alpha.example/form",
        mode="MANAGED_EXECUTION",
        site_code="SITE_ALPHA",
        environment="REAL",
    )

    assert (
        lab.site_code
        == real.site_code
        == "SITE_ALPHA"
    )

    assert (
        lab.mode
        == real.mode
        == SiteTargetMode.MANAGED_EXECUTION
    )

    assert (
        lab.environment
        == SiteEnvironment.LAB
    )

    assert (
        real.environment
        == SiteEnvironment.REAL
    )


def test_public_dict_does_not_leak_query():
    target = SiteTarget(
        url=(
            "https://example.test/form"
            "?session=SECRET123"
            "#private-section"
        ),
    )

    public = (
        target.to_public_dict()
    )

    serialized = repr(
        public
    )

    assert "SECRET123" not in serialized
    assert "private-section" not in serialized

    assert (
        public["pathname"]
        == "/form"
    )

    assert (
        public["has_query"]
        is True
    )


def test_runtime_url_remains_available():
    url = (
        "https://example.test/form"
        "?step=2"
    )

    target = SiteTarget(
        url=url
    )

    assert target.url == url


@pytest.mark.parametrize(
    "url",
    (
        "",
        "ftp://example.test/file",
        "file:///tmp/test",
        "example.test",
    ),
)
def test_invalid_urls_are_rejected(
    url,
):
    with pytest.raises(
        SiteTargetConfigurationError
    ):
        SiteTarget(
            url=url
        )


def test_credentials_in_url_are_rejected():
    with pytest.raises(
        SiteTargetConfigurationError,
        match=(
            "SITE_TARGET_CREDENTIALS_FORBIDDEN"
        ),
    ):
        SiteTarget(
            url=(
                "https://user:password"
                "@example.test/"
            )
        )


def test_default_https_port_is_normalized():
    target = SiteTarget(
        url="https://example.test:443/path"
    )

    assert (
        target.origin
        == "https://example.test"
    )


def test_non_default_port_is_preserved():
    target = SiteTarget(
        url="http://127.0.0.1:8767/path"
    )

    assert (
        target.origin
        == "http://127.0.0.1:8767"
    )


def test_invalid_mode_is_rejected():
    with pytest.raises(
        SiteTargetConfigurationError
    ):
        SiteTarget(
            url="https://example.test/",
            mode="DO_WHATEVER",
        )


def test_invalid_environment_is_rejected():
    with pytest.raises(
        SiteTargetConfigurationError
    ):
        SiteTarget(
            url="https://example.test/",
            mode="MANAGED_EXECUTION",
            site_code="SITE_ALPHA",
            environment="PRODUCTIONISH",
        )


def test_contract_module_contains_no_site_specific_provider():
    source = Path(
        "backend/automation/site_architecture/"
        "site_target.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    assert "MERCURIO" not in source
    assert "DEHU" not in source
    assert "ICPPLUS" not in source

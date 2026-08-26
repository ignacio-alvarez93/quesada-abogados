from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
)
from backend.automation.site_policies.default_registry import (
    build_default_managed_site_governance_registry,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
)


def test_mercurio_lab_resolves_to_lab():
    registry = (
        build_default_managed_site_governance_registry()
    )

    resolved = registry.resolve(
        url=(
            MERCURIO_LAB_ORIGIN
            + "/mercurio/"
            "entradaMercurio.html"
        ),
        site_code="MERCURIO",
    )

    assert resolved is not None

    assert (
        resolved.environment
        == SiteEnvironment.LAB
    )

    assert (
        resolved.profile.environment
        == SiteEnvironment.LAB
    )


def test_mercurio_real_resolves_to_real():
    registry = (
        build_default_managed_site_governance_registry()
    )

    resolved = registry.resolve(
        url=(
            MERCURIO_REAL_ORIGIN
            + "/mercurio/"
            "entradaMercurio.html"
        ),
        site_code="MERCURIO",
    )

    assert resolved is not None

    assert (
        resolved.environment
        == SiteEnvironment.REAL
    )

    assert (
        resolved.profile.environment
        == SiteEnvironment.REAL
    )


def test_mercurio_lab_and_real_share_policy_code():
    registry = (
        build_default_managed_site_governance_registry()
    )

    lab = registry.resolve(
        url=(
            MERCURIO_LAB_ORIGIN
            + "/mercurio/"
            "entradaMercurio.html"
        ),
        site_code="MERCURIO",
    )

    real = registry.resolve(
        url=(
            MERCURIO_REAL_ORIGIN
            + "/mercurio/"
            "entradaMercurio.html"
        ),
        site_code="MERCURIO",
    )

    assert (
        lab.policy.policy_code
        == real.policy.policy_code
    )

    assert (
        lab.policy.action_kind_rules
        == real.policy.action_kind_rules
    )


def test_sede_recognition_origin_is_not_mercurio_managed_origin():
    registry = (
        build_default_managed_site_governance_registry()
    )

    # Sede puede formar parte del reconocimiento
    # semántico Mercurio, pero NO del perfil de
    # ejecución gestionada Mercurio.
    resolved = registry.resolve(
        url=(
            "https://sede."
            "administracionespublicas.gob.es/"
        ),
        site_code="MERCURIO",
    )

    assert resolved is None


def test_localhost_twin_alias_is_not_silently_authorized():
    registry = (
        build_default_managed_site_governance_registry()
    )

    resolved = registry.resolve(
        url=(
            "http://localhost:8767/"
            "mercurio/"
            "entradaMercurio.html"
        ),
        site_code="MERCURIO",
    )

    assert resolved is None

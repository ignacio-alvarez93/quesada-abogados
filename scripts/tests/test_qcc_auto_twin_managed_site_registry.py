import pytest

from backend.qcc.auto_twin import (
    AutoTwinManagedSite,
    AutoTwinManagedSiteRegistry,
)


def _mercurio(
    **kwargs,
):
    values = {
        "twin_key":
            "mercurio",

        "site_code":
            "MERCURIO",

        "origins": (
            "https://mercurio.delegaciondelgobierno.gob.es",
        ),

        "path_prefixes": (
            "/mercurio",
        ),
    }

    values.update(
        kwargs
    )

    return AutoTwinManagedSite(
        **values
    )


def test_managed_site_normalizes_contract():
    site = AutoTwinManagedSite(
        twin_key=" mercurio ",
        site_code=" mercurio ",
        origins=(
            "HTTPS://MERCURIO.DELEGACIONDELGOBIERNO.GOB.ES/",
        ),
        path_prefixes=(
            "mercurio/",
        ),
    )

    assert site.twin_key == "mercurio"
    assert site.site_code == "MERCURIO"

    assert site.origins == (
        "https://mercurio.delegaciondelgobierno.gob.es",
    )

    assert site.path_prefixes == (
        "/mercurio",
    )


def test_managed_site_matches_own_scope():
    site = _mercurio()

    assert site.matches_url(
        "https://mercurio.delegaciondelgobierno.gob.es/mercurio/index.html"
    )

    assert site.matches_url(
        "https://mercurio.delegaciondelgobierno.gob.es/mercurio/ex02/datos.html?x=1"
    )


def test_managed_site_rejects_other_path():
    site = _mercurio()

    assert not site.matches_url(
        "https://mercurio.delegaciondelgobierno.gob.es/other/index.html"
    )


def test_managed_site_rejects_other_origin():
    site = _mercurio()

    assert not site.matches_url(
        "https://example.com/mercurio/index.html"
    )


def test_disabled_site_does_not_resolve():
    site = _mercurio(
        enabled=False
    )

    assert not site.matches_url(
        "https://mercurio.delegaciondelgobierno.gob.es/mercurio/index.html"
    )


def test_registry_registers_and_resolves():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    revision = registry.register(
        _mercurio()
    )

    assert revision == 1

    resolved = (
        registry.resolve_url(
            "https://mercurio.delegaciondelgobierno.gob.es/mercurio/ex01/foo.html"
        )
    )

    assert resolved is not None
    assert resolved.twin_key == "mercurio"
    assert resolved.site_code == "MERCURIO"


def test_registry_unknown_url_returns_none():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    assert (
        registry.resolve_url(
            "https://example.com/"
        )
        is None
    )


def test_registry_can_resolve_site_code():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    site = (
        registry.get_by_site_code(
            "mercurio"
        )
    )

    assert site is not None
    assert site.twin_key == "mercurio"


def test_registry_rejects_duplicate_twin_key():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_KEY_ALREADY_REGISTERED",
    ):
        registry.register(
            _mercurio(
                site_code="MERCURIO_2",
            )
        )


def test_registry_rejects_duplicate_site_code():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_SITE_CODE_ALREADY_REGISTERED",
    ):
        registry.register(
            AutoTwinManagedSite(
                twin_key="mercurio-second",
                site_code="MERCURIO",
                origins=(
                    "https://other.example",
                ),
            )
        )


def test_registry_rejects_exact_scope_collision():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_SCOPE_CONFLICT",
    ):
        registry.register(
            AutoTwinManagedSite(
                twin_key="other",
                site_code="OTHER",
                origins=(
                    "https://mercurio.delegaciondelgobierno.gob.es",
                ),
                path_prefixes=(
                    "/mercurio",
                ),
            )
        )


def test_more_specific_scope_wins():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        AutoTwinManagedSite(
            twin_key="portal",
            site_code="PORTAL",
            origins=(
                "https://example.com",
            ),
            path_prefixes=(
                "/",
            ),
        )
    )

    registry.register(
        AutoTwinManagedSite(
            twin_key="specific",
            site_code="SPECIFIC",
            origins=(
                "https://example.com",
            ),
            path_prefixes=(
                "/app",
            ),
        )
    )

    resolved = (
        registry.resolve_url(
            "https://example.com/app/page"
        )
    )

    assert resolved is not None
    assert resolved.twin_key == "specific"


def test_registry_snapshot_is_stable():
    registry = (
        AutoTwinManagedSiteRegistry()
    )

    registry.register(
        _mercurio()
    )

    assert registry.snapshots() == [
        {
            "schema_version": 1,
            "twin_key": "mercurio",
            "site_code": "MERCURIO",
            "origins": [
                "https://mercurio.delegaciondelgobierno.gob.es",
            ],
            "path_prefixes": [
                "/mercurio",
            ],
            "enabled": True,
            "auto_update": True,
            "discover_unknown_states": True,
            "registry_revision": 1,
        }
    ]

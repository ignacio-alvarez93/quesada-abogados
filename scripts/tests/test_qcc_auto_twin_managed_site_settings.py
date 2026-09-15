from backend.qcc.auto_twin import (
    AutoTwinManagedSite,
    AutoTwinManagedSiteStore,
)


def _store(
    tmp_path,
):
    store = AutoTwinManagedSiteStore(
        path=(
            tmp_path
            / "managed_sites.json"
        )
    )

    store.register(
        AutoTwinManagedSite(
            twin_key="mercurio",
            site_code="MERCURIO",
            origins=(
                "https://mercurio.delegaciondelgobierno.gob.es",
            ),
            path_prefixes=(
                "/mercurio",
            ),
        )
    )

    return store


def test_settings_update_preserves_identity(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    revision = store.update_settings(
        "mercurio",
        auto_update=False,
    )

    assert revision == 2

    site = store.get(
        "mercurio"
    )

    assert site.twin_key == "mercurio"
    assert site.site_code == "MERCURIO"

    assert site.origins == (
        "https://mercurio.delegaciondelgobierno.gob.es",
    )

    assert site.path_prefixes == (
        "/mercurio",
    )

    assert site.enabled is True
    assert site.auto_update is False


def test_disable_removes_url_from_active_resolution(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    url = (
        "https://mercurio.delegaciondelgobierno.gob.es"
        "/mercurio/index.html"
    )

    assert (
        store.resolve_url(
            url
        )
        is not None
    )

    store.update_settings(
        "mercurio",
        enabled=False,
    )

    assert (
        store.resolve_url(
            url
        )
        is None
    )


def test_settings_survive_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    store = AutoTwinManagedSiteStore(
        path=path
    )

    store.register(
        AutoTwinManagedSite(
            twin_key="mercurio",
            site_code="MERCURIO",
            origins=(
                "https://mercurio.delegaciondelgobierno.gob.es",
            ),
            path_prefixes=(
                "/mercurio",
            ),
        )
    )

    store.update_settings(
        "mercurio",
        auto_update=False,
        discover_unknown_states=False,
    )

    reloaded = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    site = reloaded.get(
        "mercurio"
    )

    assert site.auto_update is False

    assert (
        site.discover_unknown_states
        is False
    )

    assert reloaded.revision == 2


def test_noop_settings_do_not_create_revision(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    revision = store.update_settings(
        "mercurio",
        enabled=True,
    )

    assert revision == 1

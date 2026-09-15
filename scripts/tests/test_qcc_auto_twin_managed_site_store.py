import json

from backend.qcc.auto_twin import (
    AUTO_TWIN_MANAGED_SITE_STORE_TYPE,
    AutoTwinManagedSite,
    AutoTwinManagedSiteStore,
)


def _site():
    return AutoTwinManagedSite(
        twin_key="mercurio",
        site_code="MERCURIO",
        origins=(
            "https://mercurio.delegaciondelgobierno.gob.es",
        ),
        path_prefixes=(
            "/mercurio",
        ),
    )


def test_empty_store_does_not_create_file(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    store = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    assert store.revision == 0
    assert store.snapshot()["count"] == 0

    assert not path.exists()


def test_register_persists_atomically(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    store = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    revision = store.register(
        _site()
    )

    assert revision == 1
    assert path.is_file()

    temporary = (
        path.with_suffix(
            ".json.tmp"
        )
    )

    assert not temporary.exists()

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        payload["store_type"]
        == AUTO_TWIN_MANAGED_SITE_STORE_TYPE
    )

    assert payload["revision"] == 1
    assert payload["count"] == 1

    assert (
        payload[
            "managed_twins"
        ][0]["twin_key"]
        == "mercurio"
    )


def test_store_survives_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    first = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    first.register(
        _site()
    )

    second = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    assert second.revision == 1

    site = second.get(
        "mercurio"
    )

    assert site is not None
    assert site.site_code == "MERCURIO"


def test_store_resolves_live_url_after_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    store = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    store.register(
        _site()
    )

    reloaded = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    resolved = (
        reloaded.resolve_url(
            "https://mercurio.delegaciondelgobierno.gob.es/mercurio/ex02/foo.html"
        )
    )

    assert resolved is not None
    assert resolved.twin_key == "mercurio"


def test_failed_registration_does_not_mutate_disk(
    tmp_path,
):
    path = (
        tmp_path
        / "managed_sites.json"
    )

    store = (
        AutoTwinManagedSiteStore(
            path=path
        )
    )

    store.register(
        _site()
    )

    before = path.read_bytes()

    try:
        store.register(
            _site()
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "duplicate registration should fail"
        )

    assert path.read_bytes() == before
    assert store.revision == 1

from types import SimpleNamespace


from backend.qcc.auto_twin.catalog_probe_decision import (
    AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,
    build_auto_twin_catalog_probe_decision,
)


class FakeRegistry:
    def __init__(
        self,
        *profiles,
    ):
        self._profiles = tuple(
            profiles
        )

    def profile_keys(
        self,
    ):
        return self._profiles


class FakeManagedStore:
    def __init__(
        self,
        site=None,
    ):
        self.site = site

    def resolve_url(
        self,
        url,
    ):
        if (
            self.site is not None
            and str(url).startswith(
                "https://example.invalid/"
            )
        ):
            return self.site

        return None


def site(
    *,
    enabled=True,
):
    return SimpleNamespace(
        twin_key="example",
        site_code="EXAMPLE",
        enabled=enabled,
    )


def decision(
    *,
    profile="twin_discovery",
    registered=True,
    managed=True,
    enabled=True,
):
    registry = FakeRegistry(
        *(
            [profile]
            if registered
            else []
        )
    )

    store = FakeManagedStore(
        (
            site(
                enabled=enabled
            )
            if managed
            else None
        )
    )

    return (
        build_auto_twin_catalog_probe_decision(
            store,
            registry,

            browser_profile_key=profile,

            url=(
                "https://example.invalid/path"
            ),
        )
    )


def test_discovery_profile_on_managed_site_is_allowed():
    result = decision()

    assert (
        result[
            "decision_type"
        ]
        == AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE
    )

    assert result["allowed"] is True

    assert (
        result["reason"]
        == "ACTIVE_CATALOG_PROBE_ALLOWED"
    )

    assert (
        result[
            "profile_policy"
        ][
            "active_catalog_probe"
        ]
        is True
    )

    assert (
        result["twin_key"]
        == "example"
    )


def test_observer_profile_is_denied():
    result = decision(
        profile="ordinary_browser",
    )

    assert result["allowed"] is False

    assert (
        result["reason"]
        == "PROFILE_POLICY_DENIED"
    )


def test_unregistered_discovery_profile_is_denied():
    result = decision(
        registered=False,
    )

    assert result["allowed"] is False

    assert (
        result["reason"]
        == "PROFILE_NOT_REGISTERED"
    )


def test_unmanaged_url_is_denied():
    result = decision(
        managed=False,
    )

    assert result["allowed"] is False

    assert (
        result["reason"]
        == "UNMANAGED_URL"
    )


def test_disabled_managed_twin_is_denied():
    result = decision(
        enabled=False,
    )

    assert result["allowed"] is False

    assert (
        result["reason"]
        == "MANAGED_TWIN_DISABLED"
    )


def test_missing_authority_fails_closed():
    result = (
        build_auto_twin_catalog_probe_decision(
            None,
            None,

            browser_profile_key=(
                "twin_discovery"
            ),

            url=(
                "https://example.invalid/path"
            ),
        )
    )

    assert result["allowed"] is False

    assert (
        result["reason"]
        == "AUTHORITY_UNAVAILABLE"
    )


def test_extension_identity_is_not_authority_by_itself():
    result = decision(
        profile="twin_discovery",
        registered=False,
    )

    assert result["allowed"] is False

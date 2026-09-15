import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
    AUTO_TWIN_POLICY_DISCOVERY,
    AUTO_TWIN_POLICY_OBSERVER,
    AutoTwinProfilePolicy,
    build_auto_twin_profile_policy,
)


def test_discovery_profile_has_full_auto_twin_capabilities():
    policy = build_auto_twin_profile_policy(
        AUTO_TWIN_DISCOVERY_PROFILE_KEY
    )

    assert isinstance(
        policy,
        AutoTwinProfilePolicy,
    )

    assert (
        policy.policy_code
        == AUTO_TWIN_POLICY_DISCOVERY
    )

    assert policy.observe_managed_twins is True
    assert policy.detect_changes is True
    assert policy.capture_catalogs is True
    assert policy.active_discovery is True
    assert policy.active_catalog_probe is True
    assert policy.deep_capture is True
    assert policy.validate_twin is True


@pytest.mark.parametrize(
    "profile_key",
    (
        "mercurio_assisted",
        "qcc_assisted",
        "dehu",
        "whatsapp_dev",
    ),
)
def test_normal_profiles_are_passive_twin_observers(
    profile_key,
):
    policy = build_auto_twin_profile_policy(
        profile_key
    )

    assert (
        policy.policy_code
        == AUTO_TWIN_POLICY_OBSERVER
    )

    # Cualquier navegador puede alimentar cambios
    # cuando visite una sede con TWIN gestionado.
    assert policy.observe_managed_twins is True
    assert policy.detect_changes is True
    assert policy.capture_catalogs is True

    # No experimenta sobre REAL.
    assert policy.active_discovery is False
    assert policy.active_catalog_probe is False
    assert policy.deep_capture is False
    assert policy.validate_twin is False


def test_assisted_profile_does_not_gain_active_discovery():
    policy = build_auto_twin_profile_policy(
        "mercurio_assisted"
    )

    assert policy.observe_managed_twins is True
    assert policy.detect_changes is True

    assert policy.active_discovery is False
    assert policy.active_catalog_probe is False


def test_policy_serialization_is_explicit():
    payload = (
        build_auto_twin_profile_policy(
            "twin_discovery"
        )
        .to_dict()
    )

    assert payload == {
        "schema_version": 1,
        "profile_key": "twin_discovery",
        "policy_code": "DISCOVERY",
        "observe_managed_twins": True,
        "detect_changes": True,
        "capture_catalogs": True,
        "active_discovery": True,
        "active_catalog_probe": True,
        "deep_capture": True,
        "validate_twin": True,
    }


@pytest.mark.parametrize(
    "profile_key",
    (
        None,
        "",
        "   ",
    ),
)
def test_profile_key_is_required(
    profile_key,
):
    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_PROFILE_KEY_REQUIRED",
    ):
        build_auto_twin_profile_policy(
            profile_key
        )

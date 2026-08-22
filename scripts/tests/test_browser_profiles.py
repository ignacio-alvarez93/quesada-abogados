from unittest.mock import patch

from backend.automation import (
    browser_profiles,
)


def test_browser_profile_resolves_under_project_root(
    tmp_path,
):
    with patch.object(
        browser_profiles,
        "get_project_root",
        return_value=tmp_path,
    ):
        result = (
            browser_profiles
            .get_browser_profile_dir(
                "qcc_assisted"
            )
        )

    assert result == (
        tmp_path
        / "data"
        / "browser_profiles"
        / "qcc_assisted"
    )

    assert result.is_dir()


def test_browser_profile_key_is_sanitized(
    tmp_path,
):
    with patch.object(
        browser_profiles,
        "get_project_root",
        return_value=tmp_path,
    ):
        result = (
            browser_profiles
            .get_browser_profile_dir(
                "demo/profile"
            )
        )

    assert result.name == "demo_profile"


def test_browser_profile_rejects_empty_key():
    try:
        (
            browser_profiles
            .normalize_browser_profile_key(
                "   "
            )
        )
    except ValueError:
        return

    raise AssertionError(
        "profile_key vacío debería rechazarse"
    )

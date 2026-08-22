"""Resolución genérica de perfiles persistentes de navegador."""

from backend.automation.browser_session import (
    get_project_root,
)


def normalize_browser_profile_key(
    profile_key,
):
    clean_key = (
        str(
            profile_key
            or ""
        )
        .strip()
        .replace("\\", "_")
        .replace("/", "_")
    )

    if not clean_key:
        raise ValueError(
            "profile_key de navegador vacío"
        )

    return clean_key


def get_browser_profile_dir(
    profile_key,
):
    """
    Resuelve un profile_key lógico a su user-data-dir físico.

    No conoce consumidores, extensiones ni SeleniumBase.
    """
    clean_key = (
        normalize_browser_profile_key(
            profile_key
        )
    )

    profile_dir = (
        get_project_root()
        / "data"
        / "browser_profiles"
        / clean_key
    )

    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return profile_dir

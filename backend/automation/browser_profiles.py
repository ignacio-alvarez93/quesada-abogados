"""Resolución genérica de perfiles persistentes de navegador."""

from pathlib import Path

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

    if clean_key in {".", ".."} or ":" in clean_key:
        raise ValueError("profile_key de navegador no válido")

    return clean_key


def get_browser_profile_dir(
    profile_key,
    *,
    profiles_root=None,
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

    if profiles_root is None:
        root = get_project_root() / "data" / "browser_profiles"
    else:
        root = Path(profiles_root).expanduser()
        if not root.is_absolute():
            raise ValueError("Browser profiles root must be absolute")
        root = root.resolve()

    profile_dir = root / clean_key

    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return profile_dir

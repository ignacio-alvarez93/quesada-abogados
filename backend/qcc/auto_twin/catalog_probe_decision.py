"""Decisión autoritativa para mutación catalogal AUTO TWIN.

Este módulo NO ejecuta ninguna interacción web.

Autoriza únicamente cuando concurren:

    browser registrado
        +
    profile policy active_catalog_probe
        +
    URL perteneciente a TWIN gestionado y habilitado

La autorización de adquisición HARVEST_ALLOWED pertenece
a la extensión y debe cumplirse adicionalmente allí.
"""

from __future__ import annotations


from .profile_policy import (
    build_auto_twin_profile_policy,
)


AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_PROBE_DECISION"
)


def build_auto_twin_catalog_probe_decision(
    managed_site_store,
    browser_registry,
    *,
    browser_profile_key,
    url,
):
    profile_key = str(
        browser_profile_key
        or ""
    ).strip()

    page_url = str(
        url
        or ""
    ).strip()

    base = {
        "schema_version":
            AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION,

        "decision_type":
            AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,

        "allowed":
            False,

        "browser_profile_key":
            profile_key
            or None,

        "url":
            page_url
            or None,

        "twin_key":
            None,

        "site_code":
            None,
    }

    if not profile_key:
        return {
            **base,
            "reason":
                "PROFILE_UNBOUND",
        }

    if not page_url:
        return {
            **base,
            "reason":
                "URL_REQUIRED",
        }

    if (
        managed_site_store is None
        or browser_registry is None
    ):
        return {
            **base,
            "reason":
                "AUTHORITY_UNAVAILABLE",
        }

    registered_profiles = set(
        browser_registry.profile_keys()
        or ()
    )

    if profile_key not in registered_profiles:
        return {
            **base,
            "reason":
                "PROFILE_NOT_REGISTERED",
        }

    profile_policy = (
        build_auto_twin_profile_policy(
            profile_key
        )
    )

    if (
        getattr(
            profile_policy,
            "active_catalog_probe",
            False,
        )
        is not True
    ):
        return {
            **base,
            "reason":
                "PROFILE_POLICY_DENIED",

            "profile_policy":
                profile_policy.to_dict(),
        }

    managed_twin = (
        managed_site_store.resolve_url(
            page_url
        )
    )

    if managed_twin is None:
        return {
            **base,
            "reason":
                "UNMANAGED_URL",

            "profile_policy":
                profile_policy.to_dict(),
        }

    base[
        "twin_key"
    ] = getattr(
        managed_twin,
        "twin_key",
        None,
    )

    base[
        "site_code"
    ] = getattr(
        managed_twin,
        "site_code",
        None,
    )

    if (
        getattr(
            managed_twin,
            "enabled",
            False,
        )
        is not True
    ):
        return {
            **base,
            "reason":
                "MANAGED_TWIN_DISABLED",

            "profile_policy":
                profile_policy.to_dict(),
        }

    return {
        **base,

        "allowed":
            True,

        "reason":
            "ACTIVE_CATALOG_PROBE_ALLOWED",

        "profile_policy":
            profile_policy.to_dict(),
    }

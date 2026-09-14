"""Proyección de una captura Site Architecture sobre AUTO TWIN.

Esta capa:
- NO captura;
- NO interactúa con la web;
- NO modifica Site Architecture;
- NO materializa el TWIN;
- NO sustituye baselines.

Resuelve únicamente:

    browser profile policy
        +
    ingested Site Architecture result
        +
    managed TWIN registry
        ↓
    AutoTwinObservationStore
"""

from __future__ import annotations

from .managed_site_store import (
    AutoTwinManagedSiteStore,
)
from .observation_store import (
    AutoTwinObservationStore,
)
from .profile_policy import (
    build_auto_twin_profile_policy,
)


AUTO_TWIN_OBSERVATION_PROJECTION_SCHEMA_VERSION = 1

AUTO_TWIN_OBSERVATION_PROJECTION_TYPE = (
    "QCC_AUTO_TWIN_OBSERVATION_PROJECTION"
)

AUTO_TWIN_OBSERVATION_REASON_PROFILE_UNBOUND = (
    "PROFILE_UNBOUND"
)

AUTO_TWIN_OBSERVATION_REASON_POLICY_DISABLED = (
    "POLICY_DISABLED"
)

AUTO_TWIN_OBSERVATION_REASON_URL_UNAVAILABLE = (
    "URL_UNAVAILABLE"
)

AUTO_TWIN_OBSERVATION_REASON_UNMANAGED_URL = (
    "UNMANAGED_URL"
)


def _base_result(
    *,
    processed,
    reason=None,
    browser_profile_key=None,
    twin_key=None,
):
    return {
        "schema_version":
            AUTO_TWIN_OBSERVATION_PROJECTION_SCHEMA_VERSION,

        "projection_type":
            AUTO_TWIN_OBSERVATION_PROJECTION_TYPE,

        "processed":
            processed is True,

        "reason":
            reason,

        "browser_profile_key":
            browser_profile_key,

        "twin_key":
            twin_key,
    }


def project_ingested_auto_twin_observation(
    managed_site_store,
    observation_store,
    *,
    browser_profile_key,
    ingest_result,
):
    """Proyecta una captura backend-authoritative sobre AUTO TWIN."""

    if not isinstance(
        managed_site_store,
        AutoTwinManagedSiteStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MANAGED_STORE_INVALID"
        )

    if not isinstance(
        observation_store,
        AutoTwinObservationStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_OBSERVATION_STORE_INVALID"
        )

    if not isinstance(
        ingest_result,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_INGEST_RESULT_INVALID"
        )

    profile_key = str(
        browser_profile_key
        or ""
    ).strip()

    if not profile_key:
        return _base_result(
            processed=False,
            reason=(
                AUTO_TWIN_OBSERVATION_REASON_PROFILE_UNBOUND
            ),
        )

    policy = build_auto_twin_profile_policy(
        profile_key
    )

    if (
        not policy.observe_managed_twins
        or not policy.detect_changes
    ):
        return {
            **_base_result(
                processed=False,
                reason=(
                    AUTO_TWIN_OBSERVATION_REASON_POLICY_DISABLED
                ),
                browser_profile_key=(
                    profile_key
                ),
            ),

            "profile_policy":
                policy.to_dict(),
        }

    page = ingest_result.get(
        "page"
    )

    if not isinstance(
        page,
        dict,
    ):
        page = {}

    page_url = str(
        page.get(
            "url"
        )
        or ""
    ).strip()

    if not page_url:
        return {
            **_base_result(
                processed=False,
                reason=(
                    AUTO_TWIN_OBSERVATION_REASON_URL_UNAVAILABLE
                ),
                browser_profile_key=(
                    profile_key
                ),
            ),

            "profile_policy":
                policy.to_dict(),
        }

    managed_twin = (
        managed_site_store.resolve_url(
            page_url
        )
    )

    if managed_twin is None:
        return {
            **_base_result(
                processed=False,
                reason=(
                    AUTO_TWIN_OBSERVATION_REASON_UNMANAGED_URL
                ),
                browser_profile_key=(
                    profile_key
                ),
            ),

            "url":
                page_url,

            "profile_policy":
                policy.to_dict(),
        }

    observation = (
        observation_store.observe(
            managed_twin,

            capture_id=(
                ingest_result.get(
                    "capture_id"
                )
            ),

            observed_at=(
                ingest_result.get(
                    "received_at"
                )
            ),

            browser_profile_key=(
                profile_key
            ),

            url=(
                page_url
            ),

            site_code=(
                ingest_result.get(
                    "site_code"
                )
            ),

            state_observation=(
                ingest_result.get(
                    "state_observation"
                )
            ),
        )
    )

    return {
        **_base_result(
            processed=True,
            browser_profile_key=(
                profile_key
            ),
            twin_key=(
                managed_twin.twin_key
            ),
        ),

        "classification":
            observation.get(
                "classification"
            ),

        "capture_id":
            observation.get(
                "capture_id"
            ),

        "observed_at":
            observation.get(
                "observed_at"
            ),

        "pathname":
            observation.get(
                "pathname"
            ),

        "functional_state":
            observation.get(
                "functional_state"
            ),

        "auto_update":
            observation.get(
                "auto_update"
            ),

        "state_key":
            observation.get(
                "state_key"
            ),

        "fingerprint":
            observation.get(
                "fingerprint"
            ),

        "baseline_fingerprint":
            observation.get(
                "baseline_fingerprint"
            ),

        "baseline_capture_id":
            observation.get(
                "baseline_capture_id"
            ),

        "state_registered":
            observation.get(
                "state_registered"
            ),

        "observation_store_revision":
            observation.get(
                "store_revision"
            ),

        "profile_policy":
            policy.to_dict(),
    }

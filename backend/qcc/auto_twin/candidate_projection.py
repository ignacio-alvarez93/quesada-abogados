"""Proyección gobernada CHANGED -> Candidate Revision.

No altera ACTIVE.
No materializa Twin.
No ejecuta navegación.

Solo convierte una observación AUTO TWIN ya clasificada
como CHANGED en una revisión PENDING_VALIDATION.
"""

from __future__ import annotations

from .candidate_revision_store import (
    AutoTwinCandidateRevisionStore,
)
from .managed_site_store import (
    AutoTwinManagedSiteStore,
)
from .observation_store import (
    AUTO_TWIN_OBSERVATION_CHANGED,
)


AUTO_TWIN_CANDIDATE_PROJECTION_SCHEMA_VERSION = 1

AUTO_TWIN_CANDIDATE_PROJECTION_TYPE = (
    "QCC_AUTO_TWIN_CANDIDATE_PROJECTION"
)

AUTO_TWIN_CANDIDATE_REASON_OBSERVATION_NOT_PROCESSED = (
    "OBSERVATION_NOT_PROCESSED"
)

AUTO_TWIN_CANDIDATE_REASON_OBSERVATION_NOT_CHANGED = (
    "OBSERVATION_NOT_CHANGED"
)

AUTO_TWIN_CANDIDATE_REASON_AUTO_UPDATE_DISABLED = (
    "AUTO_UPDATE_DISABLED"
)

AUTO_TWIN_CANDIDATE_REASON_TWIN_NOT_FOUND = (
    "TWIN_NOT_FOUND"
)


def _result(
    *,
    processed,
    reason=None,
    twin_key=None,
):
    return {
        "schema_version":
            AUTO_TWIN_CANDIDATE_PROJECTION_SCHEMA_VERSION,

        "projection_type":
            AUTO_TWIN_CANDIDATE_PROJECTION_TYPE,

        "processed":
            processed is True,

        "reason":
            reason,

        "twin_key":
            twin_key,
    }


def project_auto_twin_candidate_revision(
    managed_site_store,
    candidate_store,
    observation,
):
    if not isinstance(
        managed_site_store,
        AutoTwinManagedSiteStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MANAGED_STORE_INVALID"
        )

    if not isinstance(
        candidate_store,
        AutoTwinCandidateRevisionStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CANDIDATE_STORE_INVALID"
        )

    if not isinstance(
        observation,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_OBSERVATION_INVALID"
        )

    twin_key = str(
        observation.get(
            "twin_key"
        )
        or ""
    ).strip()

    if observation.get(
        "processed"
    ) is not True:
        return _result(
            processed=False,
            reason=(
                AUTO_TWIN_CANDIDATE_REASON_OBSERVATION_NOT_PROCESSED
            ),
            twin_key=(
                twin_key
                or None
            ),
        )

    classification = str(
        observation.get(
            "classification"
        )
        or ""
    ).strip().upper()

    if (
        classification
        != AUTO_TWIN_OBSERVATION_CHANGED
    ):
        return _result(
            processed=False,
            reason=(
                AUTO_TWIN_CANDIDATE_REASON_OBSERVATION_NOT_CHANGED
            ),
            twin_key=(
                twin_key
                or None
            ),
        )

    if (
        observation.get(
            "auto_update"
        )
        is not True
    ):
        return _result(
            processed=False,
            reason=(
                AUTO_TWIN_CANDIDATE_REASON_AUTO_UPDATE_DISABLED
            ),
            twin_key=(
                twin_key
                or None
            ),
        )

    managed_twin = (
        managed_site_store.get(
            twin_key
        )
    )

    if managed_twin is None:
        return _result(
            processed=False,
            reason=(
                AUTO_TWIN_CANDIDATE_REASON_TWIN_NOT_FOUND
            ),
            twin_key=(
                twin_key
                or None
            ),
        )

    candidate_result = (
        candidate_store
        .record_changed_observation(
            managed_twin,
            observation,
        )
    )

    candidate = (
        candidate_result.get(
            "candidate"
        )
        or {}
    )

    return {
        **_result(
            processed=True,
            twin_key=twin_key,
        ),

        "created":
            candidate_result.get(
                "created"
            )
            is True,

        "updated":
            candidate_result.get(
                "updated"
            )
            is True,

        "candidate_store_revision":
            candidate_result.get(
                "store_revision"
            ),

        "candidate_id":
            candidate.get(
                "candidate_id"
            ),

        "candidate_revision":
            candidate.get(
                "candidate_revision"
            ),

        "status":
            candidate.get(
                "status"
            ),

        "capture_id":
            observation.get(
                "capture_id"
            ),

        "baseline_capture_id":
            observation.get(
                "baseline_capture_id"
            ),
    }

"""UWT-2 stable functional fingerprint.

Deliberately reuses the existing QCC Site Architecture functional state
authority (backend.automation.site_architecture.state_fingerprint) rather
than recomputing canonicalization/hashing rules. See
QCC_UWT_2_FUNCTIONAL_STATE_DETECTOR_V1 work order, section 14/16: avoid a
second competing fingerprint authority.

Two values are exposed:

- ``value``: the full Site Architecture functional fingerprint, including
  page identity (origin/pathname). Kept for compatibility with existing
  QCC fingerprint semantics (see test_pathname_change_changes_fingerprint).

- ``operative_value``: a narrower, page-excluded digest over
  actions/active_ui_regions/catalogs/catalog_relations only. This is the
  decisive signal UWT-2 uses to compare functional equivalence, because
  the work order requires URL to be a signal, not state authority
  (section 9): a different URL with equivalent operative evidence may
  still be the SAME_FUNCTIONAL_STATE.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_fingerprint,
    build_functional_state_payload,
)


STABLE_STATE_FINGERPRINT_SCHEMA_VERSION = 1
STABLE_STATE_FINGERPRINT_ALGORITHM = "sha256"

_OPERATIVE_NAMESPACE = "QCC_UWT_OPERATIVE_STATE_V1\0"

# Single source of truth for which Site Architecture functional payload
# sections are decisive (page-independent) operative evidence. Reused by
# functional_state.py and functional_delta.py to avoid drift.
OPERATIVE_SECTIONS = (
    "actions",
    "active_ui_regions",
    "catalogs",
    "catalog_relations",
)


@dataclass(frozen=True, slots=True)
class StableStateFingerprint:
    """Deterministic, versioned functional fingerprint pair."""

    schema_version: int
    algorithm: str
    value: str
    operative_value: str


def operative_payload_subset(payload):
    """Extracts the page-independent operative evidence subset."""

    if not isinstance(payload, dict):
        raise ValueError(
            "QCC_UWT_STABLE_FINGERPRINT_PAYLOAD_INVALID"
        )

    return {
        key: payload.get(key)
        for key in OPERATIVE_SECTIONS
    }


def _operative_digest(payload):
    subset = operative_payload_subset(
        payload
    )

    canonical = json.dumps(
        subset,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        (
            _OPERATIVE_NAMESPACE
            + canonical
        ).encode("utf-8")
    ).hexdigest()


def build_stable_state_fingerprint(
    snapshot,
) -> StableStateFingerprint:
    """Builds the UWT-2 fingerprint pair from a Site Architecture snapshot."""

    payload = build_functional_state_payload(
        snapshot
    )

    return StableStateFingerprint(
        schema_version=(
            STABLE_STATE_FINGERPRINT_SCHEMA_VERSION
        ),
        algorithm=(
            STABLE_STATE_FINGERPRINT_ALGORITHM
        ),
        value=build_functional_state_fingerprint(
            snapshot
        ),
        operative_value=_operative_digest(
            payload
        ),
    )

"""UWT-2 FunctionalState contract and observation adapter boundary.

FunctionalState is the provider-neutral, site-neutral representation of
a stable functional web state. It carries no knowledge of client,
expedient, legal procedure semantics or CRM business entities.

Boundary:

    Site Architecture observation
            |
            v
    UWT observation adapter  (build_functional_state)
            |
            v
    FunctionalState

This module does not duplicate QCC Site Architecture capture schemas.
It consumes an already normalized SiteArchitectureSnapshot (or an
equivalent normalized dict) through the existing
``build_functional_state_payload`` authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_payload,
)

from .stable_state_fingerprint import (
    StableStateFingerprint,
    build_stable_state_fingerprint,
    operative_payload_subset,
)


FUNCTIONAL_STATE_SCHEMA_VERSION = 1
FUNCTIONAL_STATE_TYPE = "QCC_UWT_FUNCTIONAL_STATE"

# EXTERNAL_UI_BOUNDARY_V1
#
# Evidence that the workflow reached something outside normal observable
# web DOM (browser-native chooser/dialog). UWT-2 does not model these as
# ordinary DOM state: no page_identity, no operative_payload, no
# fingerprint can exist for them. See functional_delta.py for how
# comparisons fail closed to UNKNOWN whenever a boundary is present.
EXTERNAL_UI_BOUNDARY_CERTIFICATE_CHOOSER = "CERTIFICATE_CHOOSER"
EXTERNAL_UI_BOUNDARY_FILE_DIALOG = "FILE_DIALOG"
EXTERNAL_UI_BOUNDARY_NATIVE_DIALOG = "NATIVE_DIALOG"
EXTERNAL_UI_BOUNDARY_OTHER = "OTHER"

EXTERNAL_UI_BOUNDARY_KINDS = frozenset(
    {
        EXTERNAL_UI_BOUNDARY_CERTIFICATE_CHOOSER,
        EXTERNAL_UI_BOUNDARY_FILE_DIALOG,
        EXTERNAL_UI_BOUNDARY_NATIVE_DIALOG,
        EXTERNAL_UI_BOUNDARY_OTHER,
    }
)


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


@dataclass(frozen=True, slots=True)
class ExternalUIBoundary:
    """Marks that evidence is outside normal observable web DOM."""

    kind: str
    detail: str | None = None


def build_external_ui_boundary(
    *,
    kind,
    detail=None,
) -> ExternalUIBoundary:
    normalized_kind = str(
        kind
        or ""
    ).strip().upper()

    if normalized_kind not in EXTERNAL_UI_BOUNDARY_KINDS:
        normalized_kind = EXTERNAL_UI_BOUNDARY_OTHER

    return ExternalUIBoundary(
        kind=normalized_kind,
        detail=_text(detail),
    )


@dataclass(frozen=True, slots=True)
class FunctionalState:
    """Provider-neutral stable functional web state representation."""

    schema_version: int
    state_type: str

    site_identity: str | None

    # {"origin": str | None, "pathname": str | None}
    # Evidentiary only: see functional_delta.py policy notes.
    page_identity: MappingProxyType

    # Normalized structural + interaction evidence, keyed by section:
    # actions, active_ui_regions, catalogs, catalog_relations.
    operative_payload: MappingProxyType

    fingerprint: StableStateFingerprint | None

    external_ui_boundary: ExternalUIBoundary | None = None

    evidence_available: bool = True


def _empty_functional_state(
    *,
    site_identity,
    external_ui_boundary=None,
):
    return FunctionalState(
        schema_version=FUNCTIONAL_STATE_SCHEMA_VERSION,
        state_type=FUNCTIONAL_STATE_TYPE,
        site_identity=_text(site_identity),
        page_identity=MappingProxyType(
            {
                "origin": None,
                "pathname": None,
            }
        ),
        operative_payload=MappingProxyType({}),
        fingerprint=None,
        external_ui_boundary=external_ui_boundary,
        evidence_available=False,
    )


def build_functional_state(
    *,
    snapshot=None,
    site_identity=None,
    external_ui_boundary=None,
) -> FunctionalState:
    """UWT observation adapter: Site Architecture snapshot -> FunctionalState.

    Exactly one of ``snapshot`` / ``external_ui_boundary`` governs the
    result. Missing/invalid evidence fails closed to an
    ``evidence_available=False`` FunctionalState rather than raising,
    so callers can route it directly into UNKNOWN comparisons.
    """

    if external_ui_boundary is not None:
        if not isinstance(
            external_ui_boundary,
            ExternalUIBoundary,
        ):
            raise TypeError(
                "QCC_UWT_FUNCTIONAL_STATE_BOUNDARY_INVALID"
            )

        return _empty_functional_state(
            site_identity=site_identity,
            external_ui_boundary=external_ui_boundary,
        )

    if snapshot is None:
        return _empty_functional_state(
            site_identity=site_identity,
        )

    try:
        payload = build_functional_state_payload(
            snapshot
        )

        fingerprint = build_stable_state_fingerprint(
            snapshot
        )
    except (ValueError, TypeError):
        # Fail closed: malformed/unsupported evidence is UNKNOWN,
        # never silently treated as SAME or CHANGED.
        return _empty_functional_state(
            site_identity=site_identity,
        )

    page = payload.get("page")

    if not isinstance(page, dict):
        page = {}

    operative_payload = operative_payload_subset(
        payload
    )

    return FunctionalState(
        schema_version=FUNCTIONAL_STATE_SCHEMA_VERSION,
        state_type=FUNCTIONAL_STATE_TYPE,
        site_identity=_text(site_identity),
        page_identity=MappingProxyType(
            {
                "origin": page.get("origin"),
                "pathname": page.get("pathname"),
            }
        ),
        operative_payload=MappingProxyType(
            operative_payload
        ),
        fingerprint=fingerprint,
        external_ui_boundary=None,
        evidence_available=True,
    )

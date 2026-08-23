"""Normalización RAW DOM Capture → QCC Site Architecture."""

from __future__ import annotations

from urllib.parse import urlsplit

from backend.automation.dom_inspector import (
    DOM_CAPTURE_SCHEMA_VERSION,
)

from .catalogs import (
    build_catalog_reference_graph,
    normalize_catalogs,
)
from .geometry import (
    normalize_element_geometry,
    normalize_viewport,
)

from .models import (
    SiteArchitecturePage,
    SiteArchitectureSnapshot,
    SiteArchitectureSource,
)
from .schema import (
    SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE,
)

from .semantics import (
    classify_element_semantics,
)

from .selectors import (
    build_selector_occurrence_index,
    resolve_selector_profile,
)

from .visibility import (
    normalize_interaction_state,
)


def _require_dom_capture_payload(
    payload,
):
    if not isinstance(payload, dict):
        raise ValueError(
            "SITE_ARCHITECTURE_DOM_CAPTURE_INVALID"
        )

    try:
        schema_version = int(
            payload.get("schema_version")
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "SITE_ARCHITECTURE_DOM_CAPTURE_SCHEMA_INVALID"
        ) from exc

    if (
        schema_version
        != DOM_CAPTURE_SCHEMA_VERSION
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_DOM_CAPTURE_SCHEMA_UNSUPPORTED"
        )

    return schema_version


def _query_from_metadata(
    metadata,
):
    explicit = str(
        metadata.get("query")
        or ""
    )

    if explicit:
        return explicit

    url = str(
        metadata.get("url")
        or ""
    )

    if not url:
        return ""

    return urlsplit(url).query


def _copy_record(
    item,
    *,
    excluded=(),
):
    record = dict(item)

    for key in excluded:
        record.pop(
            key,
            None,
        )

    return record



def _normalize_element(
    item,
    *,
    elements,
    selector_occurrence_index,
):
    record = dict(item)

    record["semantics"] = (
        classify_element_semantics(
            record
        )
    )

    record["selectors"] = (
        resolve_selector_profile(
            record,
            elements,
            occurrence_index=(
                selector_occurrence_index
            ),
        ).to_dict()
    )

    record["geometry"] = (
        normalize_element_geometry(
            record
        )
    )

    record["interaction"] = (
        normalize_interaction_state(
            record
        )
    )

    return record



def normalize_dom_capture(
    payload,
):
    """Convierte un DOM Capture RAW en SiteArchitectureSnapshot."""

    source_schema_version = (
        _require_dom_capture_payload(
            payload
        )
    )

    metadata = dict(
        payload.get("metadata")
        or {}
    )

    elements = (
        payload.get("elements")
        or []
    )

    selector_occurrence_index = (
        build_selector_occurrence_index(
            elements
        )
    )

    catalogs = normalize_catalogs(
        payload.get("catalogs")
        or ()
    )

    catalog_relations = (
        build_catalog_reference_graph(
            catalogs
        )
    )

    page = SiteArchitecturePage(
        url=str(
            metadata.get("url")
            or ""
        ),
        origin=str(
            metadata.get("origin")
            or ""
        ),
        pathname=str(
            metadata.get("pathname")
            or ""
        ),
        query=_query_from_metadata(
            metadata
        ),
        title=str(
            metadata.get("title")
            or ""
        ),
        ready_state=str(
            metadata.get("ready_state")
            or ""
        ),
    )

    return SiteArchitectureSnapshot(
        source=SiteArchitectureSource(
            kind=(
                SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE
            ),
            schema_version=(
                source_schema_version
            ),
        ),
        captured_at=(
            payload.get("captured_at")
        ),
        page=page,
        viewport=normalize_viewport(
            payload.get("viewport")
        ),
        documents=tuple(
            dict(item)
            for item in (
                payload.get("documents")
                or []
            )
        ),
        elements=tuple(
            _normalize_element(
                item,
                elements=elements,
                selector_occurrence_index=(
                    selector_occurrence_index
                ),
            )
            for item in elements
        ),
        frames=tuple(
            _copy_record(
                item,
                excluded=("html",),
            )
            for item in (
                payload.get("frames")
                or []
            )
        ),
        shadow_roots=tuple(
            _copy_record(
                item,
                excluded=("html",),
            )
            for item in (
                payload.get("shadows")
                or []
            )
        ),
        catalogs=catalogs,
        catalog_relations=(
            catalog_relations
        ),
        counts=dict(
            payload.get("counts")
            or {}
        ),
    )

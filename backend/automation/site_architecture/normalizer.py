"""Normalización RAW DOM Capture → QCC Site Architecture."""

from __future__ import annotations

from urllib.parse import urlsplit

from backend.automation.dom_inspector import (
    DOM_CAPTURE_SCHEMA_VERSION,
)

from .action_inventory import (
    build_action_inventory,
)

from .catalogs import (
    build_catalog_reference_graph,
    merge_catalogs_with_select_actions,
    normalize_catalogs,
)
from .form_state import (
    normalize_form_constraints,
    normalize_form_state,
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

    form_state = normalize_form_state(
        record
    )

    if form_state is not None:
        record["form_state"] = form_state

    form_constraints = (
        normalize_form_constraints(
            record
        )
    )

    if form_constraints is not None:
        record["form_constraints"] = (
            form_constraints
        )

    return record


def _element_capture_index(record):
    value = record.get("index")

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _element_frame_path(record):
    return str(
        record.get("frame_path")
        or "main"
    )


def _structural_relation(
    elements_by_capture_key,
    frame_path,
    raw_index,
):
    """Projects ONE raw same-capture relation index into generic
    normalized structure.

    `raw_index` is only ever meaningful inside its own capture/frame
    context. A relation whose referenced index is absent from the
    current capture set fails closed (``None``) rather than guessing.
    """

    if raw_index is None:
        return None

    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return None

    related = elements_by_capture_key.get(
        (frame_path, index)
    )

    if related is None:
        return None

    selectors = related.get("selectors")

    primary = (
        selectors.get("primary")
        if isinstance(selectors, dict)
        else None
    )

    selector = (
        primary.get("selector")
        if isinstance(primary, dict)
        else None
    )

    return {
        "capture_index": index,
        "frame_path": frame_path,
        "selector": selector,
    }


def _attach_structural_relations(normalized_elements):
    """PASS 2: resolves raw relation indexes against the same-capture
    normalized element map, built from the already-selector-resolved
    PASS 1 output. Never contaminates selector generation with
    recursive structural lookups.
    """

    elements_by_capture_key = {}

    for record in normalized_elements:
        index = _element_capture_index(record)

        if index is None:
            continue

        elements_by_capture_key[
            (
                _element_frame_path(record),
                index,
            )
        ] = record

    result = []

    for record in normalized_elements:
        frame_path = _element_frame_path(record)

        structure = {
            "dom_depth":
                record.get("dom_depth"),

            "child_element_count":
                record.get("child_element_count"),

            "parent":
                _structural_relation(
                    elements_by_capture_key,
                    frame_path,
                    record.get("parent_index"),
                ),

            "previous_sibling":
                _structural_relation(
                    elements_by_capture_key,
                    frame_path,
                    record.get(
                        "previous_element_sibling_index"
                    ),
                ),

            "next_sibling":
                _structural_relation(
                    elements_by_capture_key,
                    frame_path,
                    record.get(
                        "next_element_sibling_index"
                    ),
                ),
        }

        updated = dict(record)
        updated["structure"] = structure

        result.append(updated)

    return tuple(result)


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

    normalized_elements = tuple(
        _normalize_element(
            item,
            elements=elements,
            selector_occurrence_index=(
                selector_occurrence_index
            ),
        )
        for item in elements
    )

    normalized_elements = (
        _attach_structural_relations(
            normalized_elements
        )
    )

    actions = build_action_inventory(
        normalized_elements
    )

    catalogs = normalize_catalogs(
        merge_catalogs_with_select_actions(
            payload.get("catalogs")
            or (),
            actions,
        )
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
        elements=normalized_elements,
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
        actions=actions,
        counts=dict(
            payload.get("counts")
            or {}
        ),
    )

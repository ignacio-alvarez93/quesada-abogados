"""Diff estructural de contratos QCC Site Architecture."""

from __future__ import annotations

from enum import Enum

from .models import (
    SiteArchitectureSnapshot,
)
from .schema import (
    require_supported_schema_version,
)
from .snapshot import (
    build_normalized_snapshot_payload,
)


class ContractChange(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"


SEMANTICS_CHANGED = "SEMANTICS_CHANGED"
SELECTOR_CHANGED = "SELECTOR_CHANGED"
INTERACTION_CHANGED = "INTERACTION_CHANGED"
GEOMETRY_CHANGED = "GEOMETRY_CHANGED"
PAGE_CHANGED = "PAGE_CHANGED"

DEFAULT_GEOMETRY_TOLERANCE_PX = 8.0


def _snapshot_payload(value):
    if isinstance(
        value,
        SiteArchitectureSnapshot,
    ):
        return build_normalized_snapshot_payload(
            value
        )

    if not isinstance(value, dict):
        raise ValueError(
            "SITE_ARCHITECTURE_DIFF_INPUT_INVALID"
        )

    require_supported_schema_version(
        value.get("schema_version")
    )

    return value


def _frame_path(element):
    selectors = element.get(
        "selectors"
    )

    if isinstance(selectors, dict):
        value = selectors.get(
            "frame_path"
        )

        if value:
            return str(value)

    return str(
        element.get("frame_path")
        or "main"
    )


def _candidate_keys(element):
    selectors = element.get(
        "selectors"
    )

    if not isinstance(selectors, dict):
        return ()

    frame_path = _frame_path(
        element
    )

    keys = []

    for candidate in (
        selectors.get("candidates")
        or ()
    ):
        if not isinstance(candidate, dict):
            continue

        if candidate.get("unique") is not True:
            continue

        selector = str(
            candidate.get("selector")
            or ""
        )

        if selector:
            keys.append(
                (frame_path, selector)
            )

    return tuple(keys)


def _candidate_index(elements):
    index = {}

    for position, element in enumerate(
        elements
    ):
        if not isinstance(element, dict):
            continue

        for key in _candidate_keys(
            element
        ):
            index.setdefault(
                key,
                set(),
            ).add(position)

    return index


def _selector_signature(element):
    selectors = element.get(
        "selectors"
    )

    if not isinstance(selectors, dict):
        return None

    primary = selectors.get(
        "primary"
    )

    if not isinstance(primary, dict):
        primary = {}

    fallbacks = tuple(
        item.get("selector")
        for item in (
            selectors.get("fallbacks")
            or ()
        )
        if isinstance(item, dict)
    )

    return (
        primary.get("strategy"),
        primary.get("selector"),
        primary.get("confidence"),
        primary.get("unique"),
        fallbacks,
    )


def _interaction_signature(element):
    interaction = element.get(
        "interaction"
    )

    if not isinstance(interaction, dict):
        return None

    return (
        interaction.get("visible"),
        interaction.get("disabled"),
        interaction.get("aria_disabled"),
        interaction.get("readonly"),
        interaction.get("hidden"),
        interaction.get("aria_hidden"),
        interaction.get("pointer_events"),
    )


def _changes(
    before,
    after,
    *,
    geometry_tolerance,
):
    changes = []

    if tuple(
        before.get("semantics")
        or ()
    ) != tuple(
        after.get("semantics")
        or ()
    ):
        changes.append(
            SEMANTICS_CHANGED
        )

    if (
        _selector_signature(before)
        != _selector_signature(after)
    ):
        changes.append(
            SELECTOR_CHANGED
        )

    if (
        _interaction_signature(before)
        != _interaction_signature(after)
    ):
        changes.append(
            INTERACTION_CHANGED
        )

    if _geometry_changed(
        before,
        after,
        tolerance=geometry_tolerance,
    ):
        changes.append(
            GEOMETRY_CHANGED
        )

    return tuple(changes)


def _match_elements(
    before_elements,
    after_elements,
):
    after_index = _candidate_index(
        after_elements
    )

    matches = {}
    used_after = set()

    for before_index, element in enumerate(
        before_elements
    ):
        targets = set()

        for key in _candidate_keys(
            element
        ):
            targets.update(
                after_index.get(
                    key,
                    ()
                )
            )

        targets -= used_after

        if len(targets) != 1:
            continue

        after_position = next(
            iter(targets)
        )

        matches[before_index] = (
            after_position
        )

        used_after.add(
            after_position
        )

    return matches


def diff_site_architecture(
    before,
    after,
    *,
    geometry_tolerance_px=(
        DEFAULT_GEOMETRY_TOLERANCE_PX
    ),
):
    try:
        geometry_tolerance_px = float(
            geometry_tolerance_px
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "SITE_ARCHITECTURE_GEOMETRY_TOLERANCE_INVALID"
        ) from exc

    if geometry_tolerance_px < 0:
        raise ValueError(
            "SITE_ARCHITECTURE_GEOMETRY_TOLERANCE_INVALID"
        )
    before_payload = (
        _snapshot_payload(before)
    )
    after_payload = (
        _snapshot_payload(after)
    )

    before_elements = tuple(
        before_payload.get("elements")
        or ()
    )

    after_elements = tuple(
        after_payload.get("elements")
        or ()
    )

    matches = _match_elements(
        before_elements,
        after_elements,
    )

    matched_after = set(
        matches.values()
    )

    changes = []
    unmatched_before = []
    unmatched_after = []

    for index, element in enumerate(
        before_elements
    ):
        keys = _candidate_keys(
            element
        )

        if index not in matches:
            if keys:
                changes.append({
                    "change": ContractChange.REMOVED.value,
                    "identity": keys[0],
                    "before_index": index,
                    "after_index": None,
                    "changes": (),
                })
            else:
                unmatched_before.append(
                    index
                )

            continue

        after_index = matches[index]

        element_changes = _changes(
            element,
            after_elements[after_index],
            geometry_tolerance=(
                geometry_tolerance_px
            ),
        )

        changes.append({
            "change": (
                ContractChange.CHANGED.value
                if element_changes
                else ContractChange.UNCHANGED.value
            ),
            "identity": keys[0],
            "before_index": index,
            "after_index": after_index,
            "changes": element_changes,
        })

    for index, element in enumerate(
        after_elements
    ):
        if index in matched_after:
            continue

        keys = _candidate_keys(
            element
        )

        if keys:
            changes.append({
                "change": ContractChange.ADDED.value,
                "identity": keys[0],
                "before_index": None,
                "after_index": index,
                "changes": (),
            })
        else:
            unmatched_after.append(
                index
            )

    counts = {
        value.value: sum(
            item["change"] == value.value
            for item in changes
        )
        for value in ContractChange
    }

    page_changed = (
        _page_signature(before_payload)
        != _page_signature(after_payload)
    )

    contract_changed = (
        page_changed
        or counts["ADDED"] > 0
        or counts["REMOVED"] > 0
        or counts["CHANGED"] > 0
    )

    inconclusive = bool(
        unmatched_before
        or unmatched_after
    )

    return {
        "contract_changed":
            contract_changed,
        "inconclusive":
            inconclusive,
        "page": {
            "changed":
                page_changed,
            "changes": (
                (PAGE_CHANGED,)
                if page_changed
                else ()
            ),
        },
        "geometry_tolerance_px":
            geometry_tolerance_px,
        "counts":
            counts,
        "elements":
            tuple(changes),
        "unmatched_before":
            tuple(unmatched_before),
        "unmatched_after":
            tuple(unmatched_after),
    }


def _page_signature(payload):
    page = payload.get("page")

    if not isinstance(page, dict):
        return None

    return (
        page.get("url"),
        page.get("origin"),
        page.get("pathname"),
        page.get("query"),
        page.get("title"),
        page.get("signature"),
    )


def _geometry_rect(element):
    geometry = element.get("geometry")

    if not isinstance(geometry, dict):
        return None

    rect = geometry.get("viewport_rect")

    if not isinstance(rect, dict):
        return None

    try:
        return tuple(
            float(rect[key])
            for key in (
                "x",
                "y",
                "width",
                "height",
            )
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def _geometry_changed(
    before,
    after,
    *,
    tolerance,
):
    before_rect = _geometry_rect(before)
    after_rect = _geometry_rect(after)

    if (
        before_rect is None
        and after_rect is None
    ):
        return False

    if (
        before_rect is None
        or after_rect is None
    ):
        return True

    return any(
        abs(left - right) > tolerance
        for left, right in zip(
            before_rect,
            after_rect,
        )
    )

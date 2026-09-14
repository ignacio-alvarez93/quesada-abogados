"""Canonical pre-action navigation context.

Captures only discrete selection state used to resolve conditional
navigation branches. It does not grant execution authority.
"""

from __future__ import annotations

import hashlib
import itertools
import json


def _text(value):
    result = str(value or "").strip()
    return result or None


def _values(value):
    if value is None:
        return ()

    if isinstance(value, (str, int, float, bool)):
        value = [value]

    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()

    normalized = sorted({
        str(item).strip()
        for item in value
        if str(item).strip()
    })

    return tuple(normalized)


def normalize_navigation_context(value):
    """Return deterministic immutable discrete-selection context."""

    if value is None:
        return ()

    if isinstance(value, dict):
        if isinstance(value.get("controls"), (list, tuple)):
            value = value["controls"]
        else:
            value = [
                {
                    "key": key,
                    "selected_values": selected,
                }
                for key, selected in value.items()
            ]

    if not isinstance(value, (list, tuple)):
        raise ValueError(
            "QCC_NAVIGATION_CONTEXT_INVALID"
        )

    normalized = {}

    for item in value:
        if not isinstance(item, dict):
            continue

        selector = _text(
            item.get("selector")
        )

        key = (
            _text(item.get("key"))
            or _text(item.get("control_key"))
            or selector
        )

        if not key:
            continue

        frame_path = (
            _text(item.get("frame_path"))
            or "main"
        )

        kind = (
            _text(item.get("kind"))
            or "DISCRETE"
        ).upper()

        selected_values = _values(
            item.get("selected_values")
        )

        if not selected_values:
            selected_value = item.get(
                "selected_value"
            )

            if selected_value is not None:
                selected_values = _values(
                    [selected_value]
                )

        if not selected_values:
            if item.get("checked") is True:
                selected_values = (
                    _text(item.get("value"))
                    or "CHECKED",
                )

            elif item.get("selected") is True:
                selected_values = (
                    _text(item.get("value"))
                    or _text(item.get("label"))
                    or "SELECTED",
                )

        if not selected_values:
            continue

        identity = (
            frame_path,
            key,
            kind,
            selector or "",
        )

        previous = normalized.get(
            identity,
            set(),
        )

        previous.update(
            selected_values
        )

        normalized[
            identity
        ] = previous

    result = []

    for (
        frame_path,
        key,
        kind,
        selector,
    ), values in sorted(
        normalized.items()
    ):
        result.append({
            "key":
                key,

            "selector":
                selector or None,

            "frame_path":
                frame_path,

            "kind":
                kind,

            "selected_values":
                sorted(values),
        })

    return tuple(
        json.loads(
            json.dumps(item)
        )
        for item in result
    )


def navigation_context_to_json(value):
    return [
        json.loads(
            json.dumps(item)
        )
        for item in normalize_navigation_context(
            value
        )
    ]


def navigation_context_signature(value):
    normalized = navigation_context_to_json(
        value
    )

    if not normalized:
        return None

    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def navigation_context_map(value):
    result = {}

    for item in normalize_navigation_context(
        value
    ):
        result[
            item["key"]
        ] = tuple(
            item["selected_values"]
        )

    return result


def project_navigation_context(
    value,
    keys,
):
    wanted = {
        str(key)
        for key in keys
    }

    return tuple(
        item
        for item in normalize_navigation_context(
            value
        )
        if item["key"] in wanted
    )


def derive_navigation_discriminator_keys(
    transitions,
):
    """Find smallest key set that uniquely explains each target."""

    records = [
        item
        for item in transitions
        if isinstance(item, dict)
    ]

    if len(records) < 2:
        return ()

    outcomes = {
        str(
            item.get(
                "after_fingerprint"
            )
            or ""
        )
        for item in records
    }

    outcomes.discard("")

    if len(outcomes) <= 1:
        return ()

    contexts = [
        navigation_context_map(
            item.get(
                "navigation_context"
            )
        )
        for item in records
    ]

    keys = sorted({
        key
        for context in contexts
        for key in context
    })

    varying = [
        key
        for key in keys
        if len({
            context.get(key)
            for context in contexts
        }) > 1
    ]

    for size in range(
        1,
        len(varying) + 1,
    ):
        for subset in itertools.combinations(
            varying,
            size,
        ):
            route_map = {}
            valid = True

            for transition, context in zip(
                records,
                contexts,
            ):
                signature = tuple(
                    (
                        key,
                        context.get(key),
                    )
                    for key in subset
                )

                if any(
                    values is None
                    for _, values
                    in signature
                ):
                    valid = False
                    break

                target = str(
                    transition.get(
                        "after_fingerprint"
                    )
                    or ""
                )

                previous = route_map.get(
                    signature
                )

                if (
                    previous is not None
                    and previous != target
                ):
                    valid = False
                    break

                route_map[
                    signature
                ] = target

            if (
                valid
                and len(
                    set(
                        route_map.values()
                    )
                )
                == len(outcomes)
            ):
                return tuple(
                    subset
                )

    return ()

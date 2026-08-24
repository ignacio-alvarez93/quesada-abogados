"""Adaptador QCC Extension DOM Capture -> DOM_CAPTURE."""

from __future__ import annotations

from backend.automation.dom_inspector import (
    DOM_CAPTURE_SCHEMA_VERSION,
)


QCC_EXTENSION_DOM_CAPTURE_SCHEMA_VERSION = 1
QCC_EXTENSION_DOM_CAPTURE_TYPE = (
    "QCC_EXTENSION_DOM_CAPTURE"
)


def _require_capture(payload):
    if not isinstance(payload, dict):
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_INVALID"
        )

    if (
        payload.get("capture_type")
        != QCC_EXTENSION_DOM_CAPTURE_TYPE
    ):
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_TYPE_INVALID"
        )

    if (
        payload.get("schema_version")
        != QCC_EXTENSION_DOM_CAPTURE_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_SCHEMA_UNSUPPORTED"
        )

    frames = payload.get("frames")

    if not isinstance(frames, (list, tuple)):
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_FRAMES_INVALID"
        )

    return tuple(frames)


def _frame_id(frame):
    if not isinstance(frame, dict):
        return None

    value = frame.get("frame_id")

    if isinstance(value, bool):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _frame_path(
    frame,
    *,
    position,
    is_main,
):
    if is_main:
        return "main"

    frame_id = _frame_id(frame)

    if frame_id is not None:
        return f"qcc-frame:{frame_id}"

    return f"qcc-frame-index:{position}"


def _aggregate_counts(
    frame_results,
):
    totals = {}

    for result in frame_results:
        counts = result.get("counts")

        if not isinstance(counts, dict):
            continue

        for key, value in counts.items():
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
            ):
                totals[key] = (
                    totals.get(key, 0)
                    + value
                )

    return totals


def adapt_qcc_extension_capture(
    payload,
):
    """Convierte captura QCC a RAW compatible con Site Architecture."""

    frames = _require_capture(
        payload
    )

    valid_frames = []

    for position, frame in enumerate(
        frames
    ):
        if not isinstance(frame, dict):
            continue

        result = frame.get("result")

        if not isinstance(result, dict):
            continue

        if (
            result.get("schema_version")
            != QCC_EXTENSION_DOM_CAPTURE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_EXTENSION_FRAME_SCHEMA_UNSUPPORTED"
            )

        valid_frames.append(
            (position, frame, result)
        )

    if not valid_frames:
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_MAIN_FRAME_MISSING"
        )

    main_entry = next(
        (
            item
            for item in valid_frames
            if _frame_id(item[1]) == 0
        ),
        None,
    )

    if main_entry is None:
        raise ValueError(
            "QCC_EXTENSION_CAPTURE_MAIN_FRAME_MISSING"
        )

    main_position = main_entry[0]
    main_result = main_entry[2]

    documents = []
    elements = []
    frame_records = []
    shadows = []
    catalogs = []
    frame_results = []

    for position, frame, result in valid_frames:
        is_main = (
            position == main_position
        )

        frame_path = _frame_path(
            frame,
            position=position,
            is_main=is_main,
        )

        frame_id = _frame_id(frame)

        document_id = frame.get(
            "document_id"
        )

        frame_results.append(
            result
        )

        documents.append({
            "frame_path":
                frame_path,
            "frame_id":
                frame_id,
            "document_id":
                document_id,
            "url":
                result.get("url"),
            "title":
                result.get("title"),
            "ready_state":
                result.get("ready_state"),
            "content_type":
                result.get("content_type"),
            "character_set":
                result.get("character_set"),
        })

        for item in (
            result.get("elements")
            or ()
        ):
            if not isinstance(item, dict):
                continue

            record = dict(item)
            attributes = record.get(
                "attributes"
            )

            if not isinstance(
                attributes,
                dict,
            ):
                attributes = {}

            record["frame_path"] = (
                frame_path
            )

            record["qcc_frame_id"] = (
                frame_id
            )

            record["qcc_document_id"] = (
                document_id
            )

            record["interaction_signals"] = {
                "hidden":
                    "hidden" in attributes,

                "aria_hidden":
                    str(
                        attributes.get(
                            "aria-hidden"
                        )
                        or ""
                    ).lower() == "true",

                "aria_disabled":
                    str(
                        attributes.get(
                            "aria-disabled"
                        )
                        or ""
                    ).lower() == "true",

                "readonly":
                    "readonly" in attributes,

                "in_viewport":
                    None,

                "opacity":
                    None,

                "pointer_events":
                    None,
            }

            elements.append(
                record
            )

        catalog_probe = (
            result.get("catalog_probe")
            or {}
        )

        if isinstance(
            catalog_probe,
            dict,
        ):
            for catalog in (
                catalog_probe.get("elements")
                or ()
            ):
                if not isinstance(
                    catalog,
                    dict,
                ):
                    continue

                record = dict(catalog)

                record["frame_path"] = (
                    frame_path
                )

                record["qcc_frame_id"] = (
                    frame_id
                )

                record["qcc_document_id"] = (
                    document_id
                )

                catalogs.append(
                    record
                )

        for shadow in (
            result.get("shadow_roots")
            or ()
        ):
            if not isinstance(
                shadow,
                dict,
            ):
                continue

            record = dict(shadow)
            record["frame_path"] = (
                frame_path
            )
            record["qcc_frame_id"] = (
                frame_id
            )

            shadows.append(
                record
            )

        if not is_main:
            frame_records.append({
                "index":
                    position,
                "frame_path":
                    frame_path,
                "frame_id":
                    frame_id,
                "document_id":
                    document_id,
                "accessible":
                    True,
                "url":
                    result.get("url"),
                "title":
                    result.get("title"),
                "html":
                    result.get(
                        "html",
                        "",
                    ),
                "path_basis":
                    "chrome_frame_id",
            })

    return {
        "schema_version":
            DOM_CAPTURE_SCHEMA_VERSION,

        "captured_at":
            payload.get("captured_at"),

        "metadata": {
            "url":
                main_result.get("url"),
            "origin":
                main_result.get("origin"),
            "pathname":
                main_result.get("pathname"),
            "title":
                main_result.get("title"),
            "ready_state":
                main_result.get("ready_state"),
            "content_type":
                main_result.get("content_type"),
            "character_set":
                main_result.get("character_set"),
        },

        "viewport":
            {},

        "counts":
            _aggregate_counts(
                frame_results
            ),

        "documents":
            documents,

        "elements":
            elements,

        "frames":
            frame_records,

        "shadows":
            shadows,

        "catalogs":
            catalogs,

        "catalog_relations":
            [],

        "html":
            main_result.get(
                "html",
                "",
            ),
    }

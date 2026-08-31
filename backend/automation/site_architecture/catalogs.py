"""Normalización y grafo estático de catálogos Site Architecture."""

from __future__ import annotations


CATALOG_RELATION_DOM_REFERENCE = (
    "DOM_REFERENCE"
)

CATALOG_EVIDENCE_DOM_ATTRIBUTE_REFERENCE = (
    "DOM_ATTRIBUTE_REFERENCE"
)


_IDREF_LIST_ATTRIBUTES = frozenset({
    "aria-controls",
    "aria-owns",
})


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _element(record):
    value = record.get(
        "element"
    )

    if not isinstance(
        value,
        dict,
    ):
        return {}

    return dict(value)


def _catalog_key(
    record,
    *,
    position,
):
    frame_path = _text(
        record.get("frame_path")
    ) or "main"

    selector = _text(
        record.get("selector")
    )

    if selector:
        identity = selector

    else:
        element = _element(
            record
        )

        element_id = _text(
            element.get("id")
        )

        element_name = _text(
            element.get("name")
        )

        if element_id:
            identity = (
                "#"
                + element_id
            )

        elif element_name:
            identity = (
                '[name="'
                + element_name
                + '"]'
            )

        else:
            identity = (
                "catalog:"
                + str(position)
            )

    return (
        frame_path
        + "::"
        + identity
    )


def _normalize_dependency_hints(
    value,
):
    if not isinstance(
        value,
        dict,
    ):
        return {}

    result = {}

    for name, raw_value in value.items():
        attribute = _text(
            name
        )

        reference = _text(
            raw_value
        )

        if not attribute:
            continue

        if not reference:
            continue

        # id/name aparecieron como ruido en capturas
        # anteriores del Passive Catalog Probe.
        if attribute.lower() in {
            "id",
            "name",
        }:
            continue

        result[attribute] = (
            reference
        )

    return result


def normalize_catalogs(
    catalogs,
):
    """Normaliza inventario RAW sin inferir causalidad."""

    normalized = []

    for position, item in enumerate(
        catalogs
        or ()
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        record = dict(item)

        frame_path = _text(
            record.get("frame_path")
        ) or "main"

        element = _element(
            record
        )

        record["frame_path"] = (
            frame_path
        )

        record["element"] = (
            element
        )

        record["selector"] = _text(
            record.get("selector")
        )

        record["dependency_hints"] = (
            _normalize_dependency_hints(
                record.get(
                    "dependency_hints"
                )
            )
        )

        record["catalog_key"] = (
            _catalog_key(
                record,
                position=position,
            )
        )

        normalized.append(
            record
        )

    return tuple(normalized)


def merge_catalogs_with_select_actions(
    catalogs,
    actions,
):
    """
    Completa el inventario RAW de catálogos con SELECT
    ya demostrados por el inventario canónico de acciones.

    Un catálogo explícito (por ejemplo QCC catalog_probe)
    prevalece siempre sobre la derivación mínima.
    """

    merged = []

    seen = set()

    for item in (
        catalogs
        or ()
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        record = dict(item)

        frame_path = (
            _text(
                record.get(
                    "frame_path"
                )
            )
            or "main"
        )

        selector = _text(
            record.get(
                "selector"
            )
        )

        merged.append(
            record
        )

        if selector:
            seen.add(
                (
                    frame_path,
                    selector,
                )
            )

    for action in (
        actions
        or ()
    ):
        if not isinstance(
            action,
            dict,
        ):
            continue

        if (
            _text(
                action.get("kind")
            ).upper()
            != "SELECT"
        ):
            continue

        selector = _text(
            action.get(
                "selector"
            )
        )

        if not selector:
            continue

        frame_path = (
            _text(
                action.get(
                    "frame_path"
                )
            )
            or "main"
        )

        identity = (
            frame_path,
            selector,
        )

        if identity in seen:
            continue

        raw_element = (
            action.get(
                "element"
            )
            or {}
        )

        if not isinstance(
            raw_element,
            dict,
        ):
            raw_element = {}

        merged.append({
            "catalog_type":
                "native_select",

            "selector":
                selector,

            "frame_path":
                frame_path,

            "element": {
                "tag":
                    _text(
                        raw_element.get(
                            "tag"
                        )
                    )
                    or "select",

                "id":
                    _text(
                        raw_element.get(
                            "id"
                        )
                    ),

                "name":
                    _text(
                        raw_element.get(
                            "name"
                        )
                    ),

                "type":
                    _text(
                        raw_element.get(
                            "type"
                        )
                    ),

                "role":
                    _text(
                        raw_element.get(
                            "role"
                        )
                    ),
            },

            "dependency_hints":
                {},
        })

        seen.add(
            identity
        )

    return tuple(
        merged
    )


def _reference_candidates(
    attribute,
    value,
):
    attribute = _text(
        attribute
    ).lower()

    value = _text(
        value
    )

    if not value:
        return ()

    if (
        attribute
        in _IDREF_LIST_ATTRIBUTES
    ):
        values = (
            value.split()
        )

    else:
        values = (
            value,
        )

    result = []

    for candidate in values:
        candidate = _text(
            candidate
        )

        if candidate.startswith(
            "#"
        ):
            candidate = (
                candidate[1:]
            )

        if candidate:
            result.append(
                candidate
            )

    return tuple(result)


def build_catalog_reference_graph(
    catalogs,
):
    """Construye referencias DOM demostradas entre catálogos."""

    catalogs = tuple(
        catalogs
        or ()
    )

    id_index = {}

    for catalog in catalogs:
        if not isinstance(
            catalog,
            dict,
        ):
            continue

        element = _element(
            catalog
        )

        element_id = _text(
            element.get("id")
        )

        if not element_id:
            continue

        frame_path = _text(
            catalog.get("frame_path")
        ) or "main"

        id_index[
            (
                frame_path,
                element_id,
            )
        ] = catalog

    relations = []
    seen = set()

    for source in catalogs:
        if not isinstance(
            source,
            dict,
        ):
            continue

        source_key = _text(
            source.get("catalog_key")
        )

        frame_path = _text(
            source.get("frame_path")
        ) or "main"

        hints = source.get(
            "dependency_hints"
        )

        if not isinstance(
            hints,
            dict,
        ):
            continue

        for attribute, value in hints.items():
            for target_id in (
                _reference_candidates(
                    attribute,
                    value,
                )
            ):
                target = id_index.get(
                    (
                        frame_path,
                        target_id,
                    )
                )

                if target is None:
                    continue

                target_key = _text(
                    target.get(
                        "catalog_key"
                    )
                )

                if (
                    not source_key
                    or not target_key
                    or source_key
                    == target_key
                ):
                    continue

                signature = (
                    source_key,
                    target_key,
                    _text(attribute),
                    target_id,
                )

                if signature in seen:
                    continue

                seen.add(
                    signature
                )

                relations.append({
                    "relation":
                        CATALOG_RELATION_DOM_REFERENCE,

                    "source":
                        source_key,

                    "target":
                        target_key,

                    "source_selector":
                        _text(
                            source.get(
                                "selector"
                            )
                        ),

                    "target_selector":
                        _text(
                            target.get(
                                "selector"
                            )
                        ),

                    "frame_path":
                        frame_path,

                    "evidence": {
                        "kind":
                            CATALOG_EVIDENCE_DOM_ATTRIBUTE_REFERENCE,

                        "attribute":
                            _text(
                                attribute
                            ),

                        "value":
                            _text(
                                value
                            ),

                        "resolved_id":
                            target_id,
                    },

                    "confidence":
                        1.0,
                })

    relations.sort(
        key=lambda item: (
            item["source"],
            item["target"],
            item["evidence"][
                "attribute"
            ],
            item["evidence"][
                "resolved_id"
            ],
        )
    )

    return tuple(relations)

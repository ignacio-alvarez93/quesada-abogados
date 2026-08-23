"""Evidencia dinámica de dependencias entre catálogos."""

from __future__ import annotations


CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED = (
    "SOURCE_SELECTION_CHANGED"
)

CATALOG_DYNAMIC_OPTIONS_CHANGED = (
    "CATALOG_OPTIONS_CHANGED"
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _catalog_index(catalogs):
    result = {}

    for catalog in (
        catalogs
        or ()
    ):
        if not isinstance(
            catalog,
            dict,
        ):
            continue

        key = _text(
            catalog.get(
                "catalog_key"
            )
        )

        if not key:
            continue

        result[key] = catalog

    return result


def _state(record):
    value = record.get(
        "state"
    )

    if not isinstance(
        value,
        dict,
    ):
        return {}

    return value


def _selection_signature(record):
    state = _state(
        record
    )

    selected_values = (
        state.get(
            "selected_values"
        )
        or ()
    )

    if not isinstance(
        selected_values,
        (list, tuple),
    ):
        selected_values = ()

    return (
        _text(
            state.get(
                "selected_value"
            )
        ),
        _text(
            state.get(
                "selected_label"
            )
        ),
        tuple(
            _text(value)
            for value
            in selected_values
        ),
        state.get(
            "selected_index"
        ),
    )


def _option_signature(record):
    result = []

    for option in (
        record.get("options")
        or ()
    ):
        if not isinstance(
            option,
            dict,
        ):
            continue

        result.append((
            _text(
                option.get(
                    "value"
                )
            ),
            _text(
                option.get(
                    "label"
                )
            ),
            bool(
                option.get(
                    "disabled"
                )
            ),
        ))

    return tuple(result)


def build_catalog_dynamic_evidence(
    before_catalogs,
    after_catalogs,
    *,
    source_catalog_key,
):
    """
    Compara dos estados de catálogo producidos alrededor
    de UN cambio deliberado.

    No ejecuta acciones y no inventa causalidad cuando
    el catálogo fuente no ha cambiado realmente.
    """

    source_catalog_key = _text(
        source_catalog_key
    )

    if not source_catalog_key:
        raise ValueError(
            "CATALOG_DYNAMIC_SOURCE_REQUIRED"
        )

    before = _catalog_index(
        before_catalogs
    )

    after = _catalog_index(
        after_catalogs
    )

    before_source = before.get(
        source_catalog_key
    )

    after_source = after.get(
        source_catalog_key
    )

    if (
        before_source is None
        or after_source is None
    ):
        raise ValueError(
            "CATALOG_DYNAMIC_SOURCE_NOT_FOUND"
        )

    before_selection = (
        _selection_signature(
            before_source
        )
    )

    after_selection = (
        _selection_signature(
            after_source
        )
    )

    if (
        before_selection
        == after_selection
    ):
        raise ValueError(
            "CATALOG_DYNAMIC_SOURCE_UNCHANGED"
        )

    evidence = [{
        "kind":
            CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,

        "source":
            source_catalog_key,

        "target":
            source_catalog_key,

        "before": {
            "selected_value":
                before_selection[0],

            "selected_label":
                before_selection[1],
        },

        "after": {
            "selected_value":
                after_selection[0],

            "selected_label":
                after_selection[1],
        },
    }]

    shared_keys = (
        set(before)
        & set(after)
    )

    for target_key in sorted(
        shared_keys
    ):
        if (
            target_key
            == source_catalog_key
        ):
            continue

        before_target = (
            before[target_key]
        )

        after_target = (
            after[target_key]
        )

        before_options = (
            _option_signature(
                before_target
            )
        )

        after_options = (
            _option_signature(
                after_target
            )
        )

        if (
            before_options
            == after_options
        ):
            continue

        evidence.append({
            "kind":
                CATALOG_DYNAMIC_OPTIONS_CHANGED,

            "source":
                source_catalog_key,

            "target":
                target_key,

            "before_options_count":
                len(before_options),

            "after_options_count":
                len(after_options),

            "before_selected_value":
                _selection_signature(
                    before_target
                )[0],

            "after_selected_value":
                _selection_signature(
                    after_target
                )[0],
        })

    return tuple(
        evidence
    )


CATALOG_RELATION_INFLUENCES = (
    "INFLUENCES"
)

CATALOG_RELATION_DEPENDS_ON = (
    "DEPENDS_ON"
)

CATALOG_CAUSAL_EVIDENCE_OBSERVED_MUTATION = (
    "OBSERVED_CATALOG_MUTATION"
)


def build_catalog_causal_relations(
    dynamic_evidence,
):
    """
    Promueve cambios dinámicos observados a relaciones
    causales canónicas.

    Solo CATALOG_OPTIONS_CHANGED demuestra aquí una
    influencia entre dos catálogos distintos.
    """

    relations = []
    seen = set()

    for evidence in (
        dynamic_evidence
        or ()
    ):
        if not isinstance(
            evidence,
            dict,
        ):
            continue

        if (
            evidence.get("kind")
            != CATALOG_DYNAMIC_OPTIONS_CHANGED
        ):
            continue

        source = _text(
            evidence.get("source")
        )

        target = _text(
            evidence.get("target")
        )

        if (
            not source
            or not target
            or source == target
        ):
            continue

        causal_evidence = {
            "kind":
                CATALOG_CAUSAL_EVIDENCE_OBSERVED_MUTATION,

            "observation":
                CATALOG_DYNAMIC_OPTIONS_CHANGED,

            "before_options_count":
                int(
                    evidence.get(
                        "before_options_count"
                    )
                    or 0
                ),

            "after_options_count":
                int(
                    evidence.get(
                        "after_options_count"
                    )
                    or 0
                ),
        }

        candidates = (
            {
                "relation":
                    CATALOG_RELATION_INFLUENCES,

                "source":
                    source,

                "target":
                    target,

                "evidence":
                    dict(
                        causal_evidence
                    ),

                "confidence":
                    1.0,
            },
            {
                "relation":
                    CATALOG_RELATION_DEPENDS_ON,

                "source":
                    target,

                "target":
                    source,

                "evidence":
                    dict(
                        causal_evidence
                    ),

                "confidence":
                    1.0,
            },
        )

        for relation in candidates:
            signature = (
                relation["relation"],
                relation["source"],
                relation["target"],
            )

            if signature in seen:
                continue

            seen.add(
                signature
            )

            relations.append(
                relation
            )

    relations.sort(
        key=lambda relation: (
            relation["relation"],
            relation["source"],
            relation["target"],
        )
    )

    return tuple(
        relations
    )

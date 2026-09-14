"""Comparador estático de catálogos REAL ↔ TWIN.

Compara únicamente el estado de catálogo demostrado por
Site Architecture:

- identidad estable;
- tipo / selector / frame;
- identidad del elemento;
- selección actual;
- opciones y orden;
- dependency hints;
- grafo estático de referencias DOM.

La causalidad dinámica pertenece a BEHAVIOR y queda fuera
de este comparador.

No modifica candidates ni lifecycle.
"""

from __future__ import annotations

from copy import deepcopy

from backend.automation.site_architecture.catalogs import (
    build_catalog_reference_graph,
    normalize_catalogs,
)

from .capture_pair import (
    AUTO_TWIN_CAPTURE_PAIR_READY,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)


AUTO_TWIN_CATALOG_COMPARATOR_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_COMPARATOR_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_FIDELITY_COMPARISON"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _element_signature(
    catalog,
):
    element = catalog.get(
        "element"
    )

    if not isinstance(
        element,
        dict,
    ):
        element = {}

    return (
        _text(
            element.get(
                "tag"
            )
        ).lower(),

        _text(
            element.get(
                "id"
            )
        ),

        _text(
            element.get(
                "name"
            )
        ),

        _text(
            element.get(
                "type"
            )
        ).lower(),

        _text(
            element.get(
                "role"
            )
        ).lower(),
    )


def _state_signature(
    catalog,
):
    state = catalog.get(
        "state"
    )

    if not isinstance(
        state,
        dict,
    ):
        state = {}

    selected_values = (
        state.get(
            "selected_values"
        )
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
            _text(
                item
            )
            for item
            in selected_values
        ),

        state.get(
            "selected_index"
        ),
    )


def _option_signature(
    catalog,
):
    result = []

    for option in (
        catalog.get(
            "options"
        )
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

            option.get(
                "disabled"
            )
            is True,

            option.get(
                "selected"
            )
            is True,
        ))

    return tuple(
        result
    )


def _dependency_signature(
    catalog,
):
    hints = catalog.get(
        "dependency_hints"
    )

    if not isinstance(
        hints,
        dict,
    ):
        return ()

    return tuple(
        sorted(
            (
                _text(
                    key
                ),
                _text(
                    value
                ),
            )
            for key, value
            in hints.items()
        )
    )


def _catalog_signature(
    catalog,
):
    options = (
        _option_signature(
            catalog
        )
    )

    declared_options_count = (
        catalog.get(
            "options_count"
        )
    )

    try:
        declared_options_count = int(
            declared_options_count
        )

    except (
        TypeError,
        ValueError,
    ):
        declared_options_count = (
            len(
                options
            )
        )

    return (
        _text(
            catalog.get(
                "catalog_type"
            )
        ).lower(),

        _text(
            catalog.get(
                "selector"
            )
        ),

        _text(
            catalog.get(
                "frame_path"
            )
        )
        or "main",

        _element_signature(
            catalog
        ),

        _state_signature(
            catalog
        ),

        options,

        declared_options_count,

        _dependency_signature(
            catalog
        ),
    )


def _relation_signature(
    relation,
):
    evidence = relation.get(
        "evidence"
    )

    if not isinstance(
        evidence,
        dict,
    ):
        evidence = {}

    return (
        _text(
            relation.get(
                "relation"
            )
        ),

        _text(
            relation.get(
                "source"
            )
        ),

        _text(
            relation.get(
                "target"
            )
        ),

        _text(
            relation.get(
                "frame_path"
            )
        )
        or "main",

        _text(
            evidence.get(
                "kind"
            )
        ),

        _text(
            evidence.get(
                "attribute"
            )
        ),

        _text(
            evidence.get(
                "value"
            )
        ),

        _text(
            evidence.get(
                "resolved_id"
            )
        ),
    )


def _catalog_index(
    catalogs,
):
    index = {}

    anonymous = []

    for catalog in catalogs:
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
            anonymous.append(
                catalog
            )
            continue

        # normalize_catalogs genera catalog:<position>
        # cuando no existe selector/id/name. Esa identidad
        # depende del orden y no es suficientemente fuerte
        # para declarar fidelidad automática.
        if "::catalog:" in key:
            anonymous.append(
                catalog
            )
            continue

        index[
            key
        ] = catalog

    return (
        index,
        tuple(
            anonymous
        ),
    )


def compare_auto_twin_catalogs(
    *,
    capture_pair,
    real_snapshot,
    twin_snapshot,
) -> dict:
    if not isinstance(
        capture_pair,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_INVALID"
        )

    if (
        capture_pair.get(
            "status"
        )
        != AUTO_TWIN_CAPTURE_PAIR_READY
        or capture_pair.get(
            "ready_for_comparison"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_NOT_READY"
        )

    if not isinstance(
        real_snapshot,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_REAL_SNAPSHOT_INVALID"
        )

    if not isinstance(
        twin_snapshot,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_TWIN_SNAPSHOT_INVALID"
        )

    real_catalogs = normalize_catalogs(
        real_snapshot.get(
            "catalogs"
        )
        or ()
    )

    twin_catalogs = normalize_catalogs(
        twin_snapshot.get(
            "catalogs"
        )
        or ()
    )

    (
        real_index,
        real_anonymous,
    ) = _catalog_index(
        real_catalogs
    )

    (
        twin_index,
        twin_anonymous,
    ) = _catalog_index(
        twin_catalogs
    )

    real_keys = set(
        real_index
    )

    twin_keys = set(
        twin_index
    )

    added_keys = (
        twin_keys
        - real_keys
    )

    removed_keys = (
        real_keys
        - twin_keys
    )

    common_keys = (
        real_keys
        & twin_keys
    )

    changed_catalogs = 0
    option_changes = 0
    state_changes = 0
    dependency_changes = 0
    identity_changes = 0

    for key in common_keys:
        real_catalog = (
            real_index[
                key
            ]
        )

        twin_catalog = (
            twin_index[
                key
            ]
        )

        real_signature = (
            _catalog_signature(
                real_catalog
            )
        )

        twin_signature = (
            _catalog_signature(
                twin_catalog
            )
        )

        if (
            real_signature
            == twin_signature
        ):
            continue

        changed_catalogs += 1

        if (
            _option_signature(
                real_catalog
            )
            != _option_signature(
                twin_catalog
            )
            or (
                real_signature[
                    6
                ]
                != twin_signature[
                    6
                ]
            )
        ):
            option_changes += 1

        if (
            _state_signature(
                real_catalog
            )
            != _state_signature(
                twin_catalog
            )
        ):
            state_changes += 1

        if (
            _dependency_signature(
                real_catalog
            )
            != _dependency_signature(
                twin_catalog
            )
        ):
            dependency_changes += 1

        if (
            real_signature[
                0:4
            ]
            != twin_signature[
                0:4
            ]
        ):
            identity_changes += 1

    real_relations = {
        _relation_signature(
            relation
        )
        for relation
        in build_catalog_reference_graph(
            real_catalogs
        )
        if isinstance(
            relation,
            dict,
        )
    }

    twin_relations = {
        _relation_signature(
            relation
        )
        for relation
        in build_catalog_reference_graph(
            twin_catalogs
        )
        if isinstance(
            relation,
            dict,
        )
    }

    added_relations = (
        twin_relations
        - real_relations
    )

    removed_relations = (
        real_relations
        - twin_relations
    )

    failed = (
        bool(
            added_keys
        )
        or bool(
            removed_keys
        )
        or changed_catalogs > 0
        or bool(
            added_relations
        )
        or bool(
            removed_relations
        )
    )

    inconclusive = (
        bool(
            real_anonymous
        )
        or bool(
            twin_anonymous
        )
    )

    if failed:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

        summary = (
            "Catalog fidelity differences detected."
        )

    elif inconclusive:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
        )

        summary = (
            "Catalog comparison contains unaddressable catalogs."
        )

    else:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_PASS
        )

        summary = (
            "Catalog inventory and static references equivalent."
        )

    real_capture = (
        capture_pair.get(
            "real_capture"
        )
        or {}
    )

    twin_capture = (
        capture_pair.get(
            "twin_capture"
        )
        or {}
    )

    return {
        "schema_version":
            AUTO_TWIN_CATALOG_COMPARATOR_SCHEMA_VERSION,

        "comparison_type":
            AUTO_TWIN_CATALOG_COMPARATOR_TYPE,

        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "checks": {
            "CATALOGS": {
                "status":
                    status,

                "summary":
                    summary,

                "metrics": {
                    "real_catalog_count":
                        len(
                            real_catalogs
                        ),

                    "twin_catalog_count":
                        len(
                            twin_catalogs
                        ),

                    "added_catalogs":
                        len(
                            added_keys
                        ),

                    "removed_catalogs":
                        len(
                            removed_keys
                        ),

                    "changed_catalogs":
                        changed_catalogs,

                    "identity_changes":
                        identity_changes,

                    "state_changes":
                        state_changes,

                    "option_changes":
                        option_changes,

                    "dependency_changes":
                        dependency_changes,

                    "real_relation_count":
                        len(
                            real_relations
                        ),

                    "twin_relation_count":
                        len(
                            twin_relations
                        ),

                    "added_relations":
                        len(
                            added_relations
                        ),

                    "removed_relations":
                        len(
                            removed_relations
                        ),

                    "real_unaddressable_catalogs":
                        len(
                            real_anonymous
                        ),

                    "twin_unaddressable_catalogs":
                        len(
                            twin_anonymous
                        ),
                },

                "references": {
                    "capture_pair_id":
                        capture_pair.get(
                            "capture_pair_id"
                        ),

                    "real_capture_id":
                        real_capture.get(
                            "capture_id"
                        ),

                    "twin_capture_id":
                        twin_capture.get(
                            "capture_id"
                        ),
                },
            },
        },

        "inconclusive":
            inconclusive,

        "catalog_fidelity_pass":
            (
                status
                == AUTO_TWIN_VALIDATION_CHECK_PASS
            ),
    }

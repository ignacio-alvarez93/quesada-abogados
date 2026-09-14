"""Adapters de comportamiento dinámico de catálogos AUTO TWIN.

Unidad funcional comparada:

    source value A
        ↓
    source value B
        ↓
    target options mutation

REAL:
    QCC_SITE_CATALOG_HARVEST
    -> REAL_CONTROLLED_HARVEST

TWIN:
    analyze_qcc_catalog_experiment() result
    -> TWIN_CONTROLLED

Ambos lados se proyectan sobre la misma evidencia funcional
canónica.

No ejecuta acciones.
No modifica lifecycle.
No modifica Mercurio.
"""

from __future__ import annotations

from backend.automation.site_architecture.catalog_dynamics import (
    CATALOG_DYNAMIC_OPTIONS_CHANGED,
    CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,
    build_catalog_causal_relations,
    catalog_option_identity_signature,
)

from .behavior_trace import (
    AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION,
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    build_auto_twin_behavior_trace,
)


QCC_SITE_CATALOG_HARVEST_SCHEMA_VERSION = 1
QCC_SITE_CATALOG_HARVEST_TYPE = (
    "QCC_SITE_CATALOG_HARVEST"
)


def _text(
    value,
):
    result = str(
        value
        or ""
    ).strip()

    return result or None


def _count(
    value,
    *,
    error,
):
    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            error
        )

    try:
        result = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            error
        ) from exc

    if result < 0:
        raise ValueError(
            error
        )

    return result


def _catalog_key(
    selector,
):
    selector = _text(
        selector
    )

    if not selector:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_SELECTOR_REQUIRED"
        )

    return (
        "main::"
        + selector
    )


def _option_signature(
    options,
):
    if not isinstance(
        options,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_OPTIONS_INVALID"
        )

    signature = []

    for option in options:
        if not isinstance(
            option,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_OPTION_INVALID"
            )

        signature.append((
            str(
                option.get(
                    "value"
                )
                or ""
            ),

            str(
                option.get(
                    "label"
                )
                or ""
            ),

            bool(
                option.get(
                    "disabled"
                )
            ),
        ))

    return tuple(
        signature
    )


def _dynamic_evidence_for_pair(
    *,
    source_key,
    target_key,
    before_value,
    after_value,
    before_target_options,
    after_target_options,
):
    before_value = _text(
        before_value
    )

    after_value = _text(
        after_value
    )

    if (
        not before_value
        or not after_value
        or before_value
        == after_value
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_SOURCE_TRANSITION_INVALID"
        )

    evidence = [{
        "kind":
            CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,

        "source":
            source_key,

        "target":
            source_key,

        "before": {
            "selected_value":
                before_value,

            "selected_label":
                "",
        },

        "after": {
            "selected_value":
                after_value,

            "selected_label":
                "",
        },
    }]

    before_signature = (
        _option_signature(
            before_target_options
        )
    )

    after_signature = (
        _option_signature(
            after_target_options
        )
    )

    if (
        before_signature
        != after_signature
    ):
        evidence.append({
            "kind":
                CATALOG_DYNAMIC_OPTIONS_CHANGED,

            "source":
                source_key,

            "target":
                target_key,

            "before_options_count":
                len(
                    before_signature
                ),

            "after_options_count":
                len(
                    after_signature
                ),

            "before_options_signature":
                catalog_option_identity_signature(
                    before_target_options
                ),

            "after_options_signature":
                catalog_option_identity_signature(
                    after_target_options
                ),
        })

    return tuple(
        evidence
    )


def _behavior_effects(
    dynamic_evidence,
):
    result = []

    for evidence in (
        dynamic_evidence
        or ()
    ):
        kind = evidence.get(
            "kind"
        )

        if (
            kind
            == CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED
        ):
            before = (
                evidence.get(
                    "before"
                )
                or {}
            )

            after = (
                evidence.get(
                    "after"
                )
                or {}
            )

            result.append({
                "kind":
                    kind,

                "source":
                    evidence.get(
                        "source"
                    ),

                "target":
                    evidence.get(
                        "target"
                    ),

                "before_value":
                    before.get(
                        "selected_value"
                    ),

                "after_value":
                    after.get(
                        "selected_value"
                    ),
            })

            continue

        if (
            kind
            == CATALOG_DYNAMIC_OPTIONS_CHANGED
        ):
            result.append({
                "kind":
                    kind,

                "source":
                    evidence.get(
                        "source"
                    ),

                "target":
                    evidence.get(
                        "target"
                    ),

                "before_options_count":
                    evidence.get(
                        "before_options_count"
                    ),

                "after_options_count":
                    evidence.get(
                        "after_options_count"
                    ),

                "before_options_signature":
                    evidence.get(
                        "before_options_signature"
                    ),

                "after_options_signature":
                    evidence.get(
                        "after_options_signature"
                    ),
            })

    return tuple(
        result
    )


def _behavior_relations(
    dynamic_evidence,
):
    canonical = (
        build_catalog_causal_relations(
            dynamic_evidence
        )
    )

    result = []

    for relation in canonical:
        evidence = (
            relation.get(
                "evidence"
            )
            or {}
        )

        result.append({
            "relation":
                relation.get(
                    "relation"
                ),

            "source":
                relation.get(
                    "source"
                ),

            "target":
                relation.get(
                    "target"
                ),

            "evidence_kind":
                evidence.get(
                    "kind"
                ),

            "before_options_count":
                evidence.get(
                    "before_options_count"
                ),

            "after_options_count":
                evidence.get(
                    "after_options_count"
                ),
        })

    return tuple(
        result
    )


def _validate_real_harvest(
    artifact,
):
    if not isinstance(
        artifact,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_REAL_CATALOG_HARVEST_INVALID"
        )

    if (
        artifact.get(
            "schema_version"
        )
        != QCC_SITE_CATALOG_HARVEST_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_HARVEST_SCHEMA_INVALID"
        )

    if (
        artifact.get(
            "artifact_type"
        )
        != QCC_SITE_CATALOG_HARVEST_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_HARVEST_TYPE_INVALID"
        )

    source = artifact.get(
        "source"
    )

    target = artifact.get(
        "target"
    )

    if (
        not isinstance(
            source,
            dict,
        )
        or not isinstance(
            target,
            dict,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_ENDPOINTS_INVALID"
        )

    source_selector = _text(
        source.get(
            "selector"
        )
    )

    target_selector = _text(
        target.get(
            "selector"
        )
    )

    if (
        not source_selector
        or not target_selector
        or source_selector
        == target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_SELECTORS_INVALID"
        )

    source_options = source.get(
        "options"
    )

    if not isinstance(
        source_options,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_SOURCE_OPTIONS_INVALID"
        )

    source_values = []

    for option in source_options:
        if not isinstance(
            option,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_SOURCE_OPTION_INVALID"
            )

        value = _text(
            option.get(
                "value"
            )
        )

        if not value:
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_SOURCE_VALUE_INVALID"
            )

        if value in source_values:
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_SOURCE_DUPLICATE"
            )

        source_values.append(
            value
        )

    observations = artifact.get(
        "observations"
    )

    if not isinstance(
        observations,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_OBSERVATIONS_INVALID"
        )

    observed = {}

    for observation in observations:
        if not isinstance(
            observation,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_OBSERVATION_INVALID"
            )

        value = _text(
            observation.get(
                "source_value"
            )
        )

        if not value:
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_OBSERVATION_VALUE_INVALID"
            )

        if value in observed:
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CATALOG_OBSERVATION_DUPLICATE"
            )

        target_options = observation.get(
            "target_options"
        )

        # Valida forma completa ahora.
        _option_signature(
            target_options
        )

        observed[
            value
        ] = {
            "source_value":
                value,

            "target_options":
                target_options,
        }

    completion = artifact.get(
        "completion"
    )

    if not isinstance(
        completion,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_COMPLETION_INVALID"
        )

    source_option_count = _count(
        completion.get(
            "source_options"
        ),
        error=(
            "QCC_AUTO_TWIN_REAL_CATALOG_COMPLETION_COUNT_INVALID"
        ),
    )

    observation_count = _count(
        completion.get(
            "observations"
        ),
        error=(
            "QCC_AUTO_TWIN_REAL_CATALOG_COMPLETION_COUNT_INVALID"
        ),
    )

    if (
        completion.get(
            "complete"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_HARVEST_INCOMPLETE"
        )

    if (
        source_option_count
        != len(
            source_options
        )
        or observation_count
        != len(
            observations
        )
        or observation_count
        != source_option_count
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_COMPLETION_MISMATCH"
        )

    if (
        set(
            source_values
        )
        != set(
            observed
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_COVERAGE_MISMATCH"
        )

    restoration = artifact.get(
        "restoration"
    )

    if not isinstance(
        restoration,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_RESTORATION_INVALID"
        )

    if (
        restoration.get(
            "exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_RESTORATION_REQUIRED"
        )

    if (
        observation_count > 1
        and restoration.get(
            "attempted"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_RESTORATION_ATTEMPT_REQUIRED"
        )

    return {
        "source_selector":
            source_selector,

        "target_selector":
            target_selector,

        "source_key":
            _catalog_key(
                source_selector
            ),

        "target_key":
            _catalog_key(
                target_selector
            ),

        "observations":
            observed,

        "source_option_count":
            source_option_count,

        "observation_count":
            observation_count,

        "source_system":
            _text(
                artifact.get(
                    "source_system"
                )
            ),

        "origin":
            _text(
                artifact.get(
                    "origin"
                )
            ),

        "pathname":
            _text(
                artifact.get(
                    "pathname"
                )
            ),

        "harvested_at":
            _text(
                artifact.get(
                    "harvested_at"
                )
            ),

        "restoration_attempted":
            bool(
                restoration.get(
                    "attempted"
                )
            ),
    }


def behavior_trace_from_real_catalog_harvest(
    artifact,
    *,
    twin_key,
    candidate_id,
    before_source_value,
    after_source_value,
    policy="REAL_GOVERNED_HARVEST",
):
    """Proyecta UNA transición A->B de una cosecha REAL completa."""

    normalized = (
        _validate_real_harvest(
            artifact
        )
    )

    before_value = _text(
        before_source_value
    )

    after_value = _text(
        after_source_value
    )

    before = (
        normalized[
            "observations"
        ].get(
            before_value
        )
    )

    after = (
        normalized[
            "observations"
        ].get(
            after_value
        )
    )

    if (
        before is None
        or after is None
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_REAL_CATALOG_PAIR_NOT_OBSERVED"
        )

    dynamic_evidence = (
        _dynamic_evidence_for_pair(
            source_key=(
                normalized[
                    "source_key"
                ]
            ),
            target_key=(
                normalized[
                    "target_key"
                ]
            ),
            before_value=(
                before_value
            ),
            after_value=(
                after_value
            ),
            before_target_options=(
                before[
                    "target_options"
                ]
            ),
            after_target_options=(
                after[
                    "target_options"
                ]
            ),
        )
    )

    return build_auto_twin_behavior_trace(
        twin_key=twin_key,
        candidate_id=candidate_id,
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
        action={
            "kind":
                "SELECT",

            "selector":
                normalized[
                    "source_selector"
                ],

            "frame_path":
                "main",
        },

        # No afirmamos transición de página/estado.
        # La mutación funcional vive en effects.
        transition={
            "before_state":
                None,

            "after_state":
                None,

            "changed":
                False,
        },
        effects=(
            _behavior_effects(
                dynamic_evidence
            )
        ),
        causal_relations=(
            _behavior_relations(
                dynamic_evidence
            )
        ),
        policy=policy,
        restoration_status=(
            AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
        ),
        references={
            "artifact_type":
                QCC_SITE_CATALOG_HARVEST_TYPE,

            "source_system":
                normalized[
                    "source_system"
                ],

            "origin":
                normalized[
                    "origin"
                ],

            "pathname":
                normalized[
                    "pathname"
                ],

            "harvested_at":
                normalized[
                    "harvested_at"
                ],

            "source_selector":
                normalized[
                    "source_selector"
                ],

            "target_selector":
                normalized[
                    "target_selector"
                ],

            "before_source_value":
                before_value,

            "after_source_value":
                after_value,

            "source_option_count":
                normalized[
                    "source_option_count"
                ],

            "observation_count":
                normalized[
                    "observation_count"
                ],

            "restoration_attempted":
                normalized[
                    "restoration_attempted"
                ],

            "restoration_exact":
                True,
        },
    )


def _filtered_twin_dynamic_evidence(
    analysis,
    *,
    target_selector,
):
    if not isinstance(
        analysis,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_ANALYSIS_INVALID"
        )

    if (
        analysis.get(
            "restoration_exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_RESTORATION_REQUIRED"
        )

    source_selector = _text(
        analysis.get(
            "selector"
        )
    )

    source_key = _text(
        analysis.get(
            "source_catalog_key"
        )
    )

    target_selector = _text(
        target_selector
    )

    if (
        not source_selector
        or not source_key
        or not target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_IDENTITY_INVALID"
        )

    expected_source_key = (
        _catalog_key(
            source_selector
        )
    )

    if (
        source_key
        != expected_source_key
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_SOURCE_KEY_MISMATCH"
        )

    target_key = (
        _catalog_key(
            target_selector
        )
    )

    if (
        target_key
        == source_key
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_TARGET_INVALID"
        )

    evidence = analysis.get(
        "evidence"
    )

    if not isinstance(
        evidence,
        (list, tuple),
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_EVIDENCE_INVALID"
        )

    source_changes = [
        item
        for item
        in evidence
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "kind"
            )
            == CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED
            and item.get(
                "source"
            )
            == source_key
        )
    ]

    if (
        len(
            source_changes
        )
        != 1
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_SOURCE_CHANGE_REQUIRED"
        )

    source_change = source_changes[0]

    before = (
        source_change.get(
            "before"
        )
        or {}
    )

    after = (
        source_change.get(
            "after"
        )
        or {}
    )

    before_value = _text(
        before.get(
            "selected_value"
        )
    )

    after_value = _text(
        after.get(
            "selected_value"
        )
    )

    if (
        not before_value
        or not after_value
        or before_value
        == after_value
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_SOURCE_CHANGE_INVALID"
        )

    filtered = [{
        "kind":
            CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,

        "source":
            source_key,

        "target":
            source_key,

        "before": {
            "selected_value":
                before_value,

            "selected_label":
                "",
        },

        "after": {
            "selected_value":
                after_value,

            "selected_label":
                "",
        },
    }]

    target_changes = [
        item
        for item
        in evidence
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "kind"
            )
            == CATALOG_DYNAMIC_OPTIONS_CHANGED
            and item.get(
                "source"
            )
            == source_key
            and item.get(
                "target"
            )
            == target_key
        )
    ]

    if len(
        target_changes
    ) > 1:
        raise ValueError(
            "QCC_AUTO_TWIN_TWIN_CATALOG_TARGET_CHANGE_AMBIGUOUS"
        )

    if target_changes:
        target_change = (
            target_changes[0]
        )

        filtered.append({
            "kind":
                CATALOG_DYNAMIC_OPTIONS_CHANGED,

            "source":
                source_key,

            "target":
                target_key,

            # Common REAL↔TWIN functional projection.
            "before_options_count":
                _count(
                    target_change.get(
                        "before_options_count"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_TWIN_CATALOG_COUNT_INVALID"
                    ),
                ),

            "after_options_count":
                _count(
                    target_change.get(
                        "after_options_count"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_TWIN_CATALOG_COUNT_INVALID"
                    ),
                ),

            "before_options_signature":
                target_change.get(
                    "before_options_signature"
                ),

            "after_options_signature":
                target_change.get(
                    "after_options_signature"
                ),
        })

    return {
        "source_selector":
            source_selector,

        "source_key":
            source_key,

        "target_selector":
            target_selector,

        "target_key":
            target_key,

        "before_value":
            before_value,

        "after_value":
            after_value,

        "dynamic_evidence":
            tuple(
                filtered
            ),
    }


def behavior_trace_from_twin_catalog_analysis(
    analysis,
    *,
    twin_key,
    candidate_id,
    target_selector,
    policy="TWIN_ONLY",
):
    """Proyecta un análisis TWIN sobre el mismo contrato REAL."""

    normalized = (
        _filtered_twin_dynamic_evidence(
            analysis,
            target_selector=(
                target_selector
            ),
        )
    )

    compared_catalogs = _count(
        analysis.get(
            "compared_catalogs"
        )
        or 0,
        error=(
            "QCC_AUTO_TWIN_TWIN_CATALOG_COMPARED_COUNT_INVALID"
        ),
    )

    return build_auto_twin_behavior_trace(
        twin_key=twin_key,
        candidate_id=candidate_id,
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
        action={
            "kind":
                "SELECT",

            "selector":
                normalized[
                    "source_selector"
                ],

            "frame_path":
                "main",
        },
        transition={
            "before_state":
                None,

            "after_state":
                None,

            "changed":
                False,
        },
        effects=(
            _behavior_effects(
                normalized[
                    "dynamic_evidence"
                ]
            )
        ),
        causal_relations=(
            _behavior_relations(
                normalized[
                    "dynamic_evidence"
                ]
            )
        ),
        policy=policy,
        restoration_status=(
            AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
        ),
        references={
            "source_catalog_key":
                normalized[
                    "source_key"
                ],

            "target_catalog_key":
                normalized[
                    "target_key"
                ],

            "before_source_value":
                normalized[
                    "before_value"
                ],

            "after_source_value":
                normalized[
                    "after_value"
                ],

            "analysis_evidence_count":
                _count(
                    analysis.get(
                        "evidence_count"
                    )
                    or len(
                        analysis.get(
                            "evidence"
                        )
                        or ()
                    ),
                    error=(
                        "QCC_AUTO_TWIN_TWIN_CATALOG_EVIDENCE_COUNT_INVALID"
                    ),
                ),

            "analysis_causal_relation_count":
                _count(
                    analysis.get(
                        "causal_relation_count"
                    )
                    or len(
                        analysis.get(
                            "causal_relations"
                        )
                        or ()
                    ),
                    error=(
                        "QCC_AUTO_TWIN_TWIN_CATALOG_RELATION_COUNT_INVALID"
                    ),
                ),

            "compared_catalogs":
                compared_catalogs,

            "restoration_exact":
                True,
        },
    )

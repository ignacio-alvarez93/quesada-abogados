"""Contrato ligero de comportamiento AUTO TWIN.

Normaliza evidencia funcional independientemente de cómo
se obtuvo:

REAL:
- acción humana observada;
- policy puede ser HUMAN_ONLY.

TWIN:
- experimento controlado;
- policy puede ser AUTOMATION_ALLOWED;
- restauración exacta obligatoria.

La policy NO forma parte de la firma funcional.

No ejecuta acciones.
No modifica candidates.
No modifica lifecycle.
"""

from __future__ import annotations

import hashlib
import json


AUTO_TWIN_BEHAVIOR_TRACE_SCHEMA_VERSION = 1

AUTO_TWIN_BEHAVIOR_TRACE_TYPE = (
    "QCC_AUTO_TWIN_BEHAVIOR_TRACE"
)


AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED = (
    "REAL_OBSERVED"
)

AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST = (
    "REAL_CONTROLLED_HARVEST"
)

AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED = (
    "TWIN_CONTROLLED"
)

AUTO_TWIN_BEHAVIOR_REAL_SOURCES = frozenset({
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST,
})

AUTO_TWIN_BEHAVIOR_SOURCES = frozenset({
    *AUTO_TWIN_BEHAVIOR_REAL_SOURCES,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
})


AUTO_TWIN_BEHAVIOR_KIND_GENERIC = (
    "GENERIC"
)

AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION = (
    "NAVIGATION"
)

AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION = (
    "CATALOG_MUTATION"
)

AUTO_TWIN_BEHAVIOR_KINDS = frozenset({
    AUTO_TWIN_BEHAVIOR_KIND_GENERIC,
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION,
})


AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT = (
    "EXACT"
)

AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE = (
    "NOT_APPLICABLE"
)


_ALLOWED_ACTION_FIELDS = frozenset({
    "kind",
    "selector",
    "frame_path",
    "action_code",
})


_ALLOWED_TRANSITION_FIELDS = frozenset({
    "before_state",
    "after_state",
    "changed",
})


_ALLOWED_EFFECT_FIELDS = frozenset({
    "kind",
    "source",
    "target",
    "before_value",
    "after_value",
    "before_options_count",
    "after_options_count",
    "before_selected_value",
    "after_selected_value",
    "before_options_signature",
    "after_options_signature",
})


_ALLOWED_RELATION_FIELDS = frozenset({
    "relation",
    "source",
    "target",
    "evidence_kind",
    "before_options_count",
    "after_options_count",
})


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _optional_text(
    value,
):
    result = _text(
        value
    )

    return (
        result
        or None
    )


def _integer_or_none(
    value,
    *,
    error,
):
    if value is None:
        return None

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


def _normalize_source(
    value,
) -> str:
    source = _text(
        value
    ).upper()

    if source not in AUTO_TWIN_BEHAVIOR_SOURCES:
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_SOURCE_INVALID"
        )

    return source


def _normalize_behavior_kind(
    value,
) -> str:
    behavior_kind = _text(
        value
    ).upper()

    if behavior_kind not in AUTO_TWIN_BEHAVIOR_KINDS:
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_KIND_INVALID"
        )

    return behavior_kind


def _normalize_action(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_ACTION_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_ACTION_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_ACTION_FIELDS_INVALID"
        )

    kind = _text(
        value.get(
            "kind"
        )
    ).upper()

    selector = _optional_text(
        value.get(
            "selector"
        )
    )

    action_code = _optional_text(
        value.get(
            "action_code"
        )
    )

    if not kind:
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_ACTION_KIND_REQUIRED"
        )

    if (
        not selector
        and not action_code
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_ACTION_IDENTITY_REQUIRED"
        )

    return {
        "kind":
            kind,

        "selector":
            selector,

        "frame_path":
            _text(
                value.get(
                    "frame_path"
                )
            )
            or "main",

        "action_code":
            action_code,
    }


def _normalize_transition(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRANSITION_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_TRANSITION_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRANSITION_FIELDS_INVALID"
        )

    changed = value.get(
        "changed"
    )

    if not isinstance(
        changed,
        bool,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_CHANGED_INVALID"
        )

    return {
        "before_state":
            _optional_text(
                value.get(
                    "before_state"
                )
            ),

        "after_state":
            _optional_text(
                value.get(
                    "after_state"
                )
            ),

        "changed":
            changed,
    }


def _normalize_effect(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_EFFECT_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_EFFECT_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_EFFECT_FIELDS_INVALID"
        )

    kind = _text(
        value.get(
            "kind"
        )
    ).upper()

    if not kind:
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_EFFECT_KIND_REQUIRED"
        )

    return {
        "kind":
            kind,

        "source":
            _optional_text(
                value.get(
                    "source"
                )
            ),

        "target":
            _optional_text(
                value.get(
                    "target"
                )
            ),

        "before_value":
            _optional_text(
                value.get(
                    "before_value"
                )
            ),

        "after_value":
            _optional_text(
                value.get(
                    "after_value"
                )
            ),

        "before_options_count":
            _integer_or_none(
                value.get(
                    "before_options_count"
                ),
                error=(
                    "QCC_AUTO_TWIN_BEHAVIOR_EFFECT_COUNT_INVALID"
                ),
            ),

        "after_options_count":
            _integer_or_none(
                value.get(
                    "after_options_count"
                ),
                error=(
                    "QCC_AUTO_TWIN_BEHAVIOR_EFFECT_COUNT_INVALID"
                ),
            ),

        "before_selected_value":
            _optional_text(
                value.get(
                    "before_selected_value"
                )
            ),

        "after_selected_value":
            _optional_text(
                value.get(
                    "after_selected_value"
                )
            ),

        "before_options_signature":
            _optional_text(
                value.get(
                    "before_options_signature"
                )
            ),

        "after_options_signature":
            _optional_text(
                value.get(
                    "after_options_signature"
                )
            ),
    }


def _normalize_relation(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_RELATION_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_RELATION_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_RELATION_FIELDS_INVALID"
        )

    relation = _text(
        value.get(
            "relation"
        )
    ).upper()

    source = _text(
        value.get(
            "source"
        )
    )

    target = _text(
        value.get(
            "target"
        )
    )

    if (
        not relation
        or not source
        or not target
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_RELATION_IDENTITY_REQUIRED"
        )

    return {
        "relation":
            relation,

        "source":
            source,

        "target":
            target,

        "evidence_kind":
            _optional_text(
                value.get(
                    "evidence_kind"
                )
            ),

        "before_options_count":
            _integer_or_none(
                value.get(
                    "before_options_count"
                ),
                error=(
                    "QCC_AUTO_TWIN_BEHAVIOR_RELATION_COUNT_INVALID"
                ),
            ),

        "after_options_count":
            _integer_or_none(
                value.get(
                    "after_options_count"
                ),
                error=(
                    "QCC_AUTO_TWIN_BEHAVIOR_RELATION_COUNT_INVALID"
                ),
            ),
    }


def _dedupe_sorted(
    values,
) -> tuple[dict, ...]:
    indexed = {}

    for value in values:
        canonical = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

        indexed[
            canonical
        ] = value

    return tuple(
        indexed[
            key
        ]
        for key
        in sorted(
            indexed
        )
    )


def _normalize_scalar_references(
    value,
) -> dict:
    if value is None:
        return {}

    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_REFERENCES_INVALID"
        )

    result = {}

    for raw_key, raw_value in value.items():
        key = _text(
            raw_key
        )

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_BEHAVIOR_REFERENCES_INVALID"
            )

        if isinstance(
            raw_value,
            (
                dict,
                list,
                tuple,
                set,
            ),
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_BEHAVIOR_REFERENCES_INVALID"
            )

        result[
            key
        ] = raw_value

    return result


def _sha256(
    value,
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def build_auto_twin_behavior_trace(
    *,
    twin_key,
    candidate_id,
    source,
    action,
    transition,
    behavior_kind=AUTO_TWIN_BEHAVIOR_KIND_GENERIC,
    effects=(),
    causal_relations=(),
    policy=None,
    restoration_status=None,
    references=None,
) -> dict:
    normalized_twin_key = _text(
        twin_key
    )

    normalized_candidate_id = _text(
        candidate_id
    )

    if not normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_KEY_REQUIRED"
        )

    if not normalized_candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
        )

    normalized_source = (
        _normalize_source(
            source
        )
    )

    normalized_behavior_kind = (
        _normalize_behavior_kind(
            behavior_kind
        )
    )

    normalized_action = (
        _normalize_action(
            action
        )
    )

    normalized_transition = (
        _normalize_transition(
            transition
        )
    )

    if not isinstance(
        effects,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_EFFECTS_INVALID"
        )

    normalized_effects = (
        _dedupe_sorted(
            tuple(
                _normalize_effect(
                    effect
                )
                for effect
                in effects
            )
        )
    )

    if not isinstance(
        causal_relations,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_RELATIONS_INVALID"
        )

    normalized_relations = (
        _dedupe_sorted(
            tuple(
                _normalize_relation(
                    relation
                )
                for relation
                in causal_relations
            )
        )
    )

    normalized_policy = (
        _optional_text(
            policy
        )
    )

    controlled_source = (
        normalized_source
        in {
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST,
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
        }
    )

    restoration = (
        _text(
            restoration_status
        ).upper()
        if restoration_status is not None
        else (
            AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
            if controlled_source
            else AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE
        )
    )

    if (
        normalized_source
        == AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        and restoration
        != AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    ):
        # Contrato histórico público: se conserva.
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_RESTORATION_REQUIRED"
        )

    if (
        normalized_source
        == AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
        and restoration
        != AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_CONTROLLED_RESTORATION_REQUIRED"
        )

    if (
        normalized_source
        == AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        and restoration
        != AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE
    ):
        # Contrato histórico público: se conserva.
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_REAL_RESTORATION_INVALID"
        )

    normalized_references = (
        _normalize_scalar_references(
            references
        )
    )

    # Esta es la identidad funcional REAL ↔ TWIN.
    #
    # Deliberadamente excluye:
    # - source;
    # - policy;
    # - fingerprints físicos;
    # - ids de captura;
    # - mecanismo de ejecución;
    # - restoration_status.
    #
    # REAL puede ser HUMAN_ONLY y TWIN AUTOMATION_ALLOWED
    # sin dejar de representar el mismo comportamiento.
    functional_identity = {
        "behavior_kind":
            normalized_behavior_kind,

        "action":
            normalized_action,

        "transition":
            normalized_transition,

        "effects":
            normalized_effects,

        "causal_relations":
            normalized_relations,
    }

    functional_signature = (
        _sha256(
            functional_identity
        )
    )

    trace_identity = {
        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "source":
            normalized_source,

        "functional_signature":
            functional_signature,
    }

    return {
        "schema_version":
            AUTO_TWIN_BEHAVIOR_TRACE_SCHEMA_VERSION,

        "trace_type":
            AUTO_TWIN_BEHAVIOR_TRACE_TYPE,

        "behavior_trace_id":
            _sha256(
                trace_identity
            ),

        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "source":
            normalized_source,

        "behavior_kind":
            normalized_behavior_kind,

        "policy":
            normalized_policy,

        "restoration_status":
            restoration,

        "action":
            normalized_action,

        "transition":
            normalized_transition,

        "effects":
            normalized_effects,

        "causal_relations":
            normalized_relations,

        "references":
            normalized_references,

        "functional_signature":
            functional_signature,
    }

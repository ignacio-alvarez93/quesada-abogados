"""Evidencia de efectos dinámicos de formulario — Site Architecture.

Describe efectos observables causados por UNA acción deliberada y
conocida entre un snapshot normalizado ANTES y un snapshot normalizado
DESPUÉS.

Este módulo es PURO: no ejecuta ninguna interacción de navegador y no
reproduce comportamiento. Reutiliza sin duplicar las autoridades
existentes de visibilidad (``visibility.py``), estado de formulario
(``form_state.py``) y dinámica de catálogos (``catalog_dynamics.py``).
"""

from __future__ import annotations

from .catalog_dynamics import (
    build_catalog_causal_relations,
    build_catalog_dynamic_evidence,
)
from .models import (
    SiteArchitectureSnapshot,
)


DYNAMIC_FORM_EFFECT_SCHEMA_VERSION = 1


EFFECT_VISIBILITY_CHANGED = "VISIBILITY_CHANGED"
EFFECT_INTERACTABLE_CHANGED = "INTERACTABLE_CHANGED"
EFFECT_DISABLED_CHANGED = "DISABLED_CHANGED"
EFFECT_READONLY_CHANGED = "READONLY_CHANGED"
EFFECT_REQUIRED_CHANGED = "REQUIRED_CHANGED"
EFFECT_HAS_VALUE_CHANGED = "HAS_VALUE_CHANGED"
EFFECT_CHECKED_CHANGED = "CHECKED_CHANGED"
EFFECT_SELECTION_CHANGED = "SELECTION_CHANGED"
EFFECT_CONTROL_APPEARED = "CONTROL_APPEARED"
EFFECT_CONTROL_DISAPPEARED = "CONTROL_DISAPPEARED"


UNRESOLVED_REASON_SELECTOR_UNRESOLVED = (
    "SELECTOR_UNRESOLVED"
)
UNRESOLVED_REASON_AMBIGUOUS_IDENTITY = (
    "AMBIGUOUS_IDENTITY"
)


# Identidad de control: únicamente semánticas ya reconocidas por
# `semantics.py` que representan controles interactivos o de
# formulario. No se inventa taxonomía nueva.
_CONTROL_SEMANTICS = frozenset({
    "TEXT_INPUT",
    "TEXTAREA",
    "FILE_INPUT",
    "HIDDEN_INPUT",
    "CHECKBOX",
    "RADIO",
    "SELECT",
    "BUTTON",
    "SUBMIT",
    "LINK",
})

# Orden de prioridad fijo para derivar un único `semantic_kind`
# descriptivo cuando un elemento porta varias semánticas combinadas.
_SEMANTIC_KIND_PRIORITY = (
    "SELECT",
    "CHECKBOX",
    "RADIO",
    "FILE_INPUT",
    "TEXTAREA",
    "TEXT_INPUT",
    "HIDDEN_INPUT",
    "SUBMIT",
    "BUTTON",
    "LINK",
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _frame_path(element):
    return (
        _text(
            element.get("frame_path")
        )
        or "main"
    )


def _semantics(element):
    return {
        str(value).strip().upper()
        for value in (
            element.get("semantics")
            or ()
        )
        if str(value).strip()
    }


def _semantic_kind(element):
    semantics = _semantics(element)

    for candidate in _SEMANTIC_KIND_PRIORITY:
        if candidate in semantics:
            return candidate

    return None


def _primary_selector(element):
    selectors = (
        element.get("selectors")
        or {}
    )

    if not isinstance(selectors, dict):
        return None

    primary = (
        selectors.get("primary")
        or {}
    )

    if not isinstance(primary, dict):
        return None

    selector = _text(
        primary.get("selector")
    )

    return selector or None


def _interaction(element):
    value = element.get("interaction")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _form_state(element):
    value = element.get("form_state")

    return (
        value
        if isinstance(value, dict)
        else None
    )


def _form_constraints(element):
    value = element.get("form_constraints")

    return (
        value
        if isinstance(value, dict)
        else None
    )


def _control_key(frame_path, selector, kind):
    return (
        frame_path
        + "::"
        + kind
        + "::"
        + selector
    )


def _target(key, element):
    return {
        "control_key": key,
        "frame_path": _frame_path(element),
        "selector": _primary_selector(element),
        "semantic_kind": _semantic_kind(element),
    }


def _build_control_index(elements):
    """Indexa controles por identidad estructural estable.

    Nunca empareja por posición de array. Los controles sin selector
    primario seguro, o cuya identidad colisiona con otro control del
    mismo snapshot, quedan fuera del índice y se reportan como
    evidencia inconclusa.
    """

    index = {}
    ambiguous = set()
    unresolved = []

    for element in (
        elements
        or ()
    ):
        if not isinstance(element, dict):
            continue

        kind = _semantic_kind(element)

        if kind is None:
            continue

        frame_path = _frame_path(element)
        selector = _primary_selector(element)

        if not selector:
            unresolved.append({
                "frame_path": frame_path,
                "semantic_kind": kind,
                "control_key": None,
                "reason":
                    UNRESOLVED_REASON_SELECTOR_UNRESOLVED,
            })
            continue

        key = _control_key(
            frame_path,
            selector,
            kind,
        )

        if key in ambiguous:
            continue

        if key in index:
            ambiguous.add(key)
            index.pop(key, None)

            unresolved.append({
                "frame_path": frame_path,
                "semantic_kind": kind,
                "control_key": key,
                "reason":
                    UNRESOLVED_REASON_AMBIGUOUS_IDENTITY,
            })
            continue

        index[key] = element

    return index, unresolved


def _bool_effect(kind, key, element, before_value, after_value):
    if before_value is None and after_value is None:
        return None

    if before_value == after_value:
        return None

    return {
        "kind": kind,
        "target": _target(key, element),
        "before": before_value,
        "after": after_value,
    }


def _diff_control(key, before_element, after_element):
    effects = []

    before_interaction = _interaction(before_element)
    after_interaction = _interaction(after_element)

    for field_name, kind in (
        ("visible", EFFECT_VISIBILITY_CHANGED),
        ("interactable", EFFECT_INTERACTABLE_CHANGED),
        ("disabled", EFFECT_DISABLED_CHANGED),
        ("readonly", EFFECT_READONLY_CHANGED),
    ):
        effect = _bool_effect(
            kind,
            key,
            after_element,
            before_interaction.get(field_name),
            after_interaction.get(field_name),
        )

        if effect is not None:
            effects.append(effect)

    before_constraints = _form_constraints(before_element)
    after_constraints = _form_constraints(after_element)

    if (
        before_constraints is not None
        and after_constraints is not None
    ):
        effect = _bool_effect(
            EFFECT_REQUIRED_CHANGED,
            key,
            after_element,
            before_constraints.get("required"),
            after_constraints.get("required"),
        )

        if effect is not None:
            effects.append(effect)

    before_state = _form_state(before_element)
    after_state = _form_state(after_element)

    if (
        before_state is not None
        and after_state is not None
    ):
        effect = _bool_effect(
            EFFECT_HAS_VALUE_CHANGED,
            key,
            after_element,
            before_state.get("has_value"),
            after_state.get("has_value"),
        )

        if effect is not None:
            effects.append(effect)

        effect = _bool_effect(
            EFFECT_CHECKED_CHANGED,
            key,
            after_element,
            before_state.get("checked"),
            after_state.get("checked"),
        )

        if effect is not None:
            effects.append(effect)

        before_selection = (
            tuple(
                before_state.get("selected_values")
                or ()
            ),
            tuple(
                before_state.get("selected_indexes")
                or ()
            ),
        )

        after_selection = (
            tuple(
                after_state.get("selected_values")
                or ()
            ),
            tuple(
                after_state.get("selected_indexes")
                or ()
            ),
        )

        if before_selection != after_selection:
            effects.append({
                "kind": EFFECT_SELECTION_CHANGED,
                "target": _target(key, after_element),
                "before": {
                    "selected_values": before_selection[0],
                    "selected_indexes": before_selection[1],
                },
                "after": {
                    "selected_values": after_selection[0],
                    "selected_indexes": after_selection[1],
                },
            })

    return effects


def _appeared_effect(key, element):
    return {
        "kind": EFFECT_CONTROL_APPEARED,
        "target": _target(key, element),
        "before": None,
        "after": True,
    }


def _disappeared_effect(key, element):
    return {
        "kind": EFFECT_CONTROL_DISAPPEARED,
        "target": _target(key, element),
        "before": True,
        "after": None,
    }


def _project_source_action(action):
    """Proyecta únicamente identidad estructural de la acción fuente.

    Nunca persiste valor tecleado, contraseña, fichero ni texto libre.
    """

    if not isinstance(action, dict):
        raise ValueError(
            "DYNAMIC_FORM_EFFECT_ACTION_REQUIRED"
        )

    kind = _text(action.get("kind"))

    if not kind:
        raise ValueError(
            "DYNAMIC_FORM_EFFECT_ACTION_REQUIRED"
        )

    selector = _text(action.get("selector")) or None

    frame_path = (
        _text(action.get("frame_path"))
        or "main"
    )

    policy = _text(action.get("policy")) or None

    projected = {
        "kind": kind,
        "selector": selector,
        "frame_path": frame_path,
        "policy": policy,
        "resolved": selector is not None,
    }

    return projected


def _sorted_unresolved(entries):
    return tuple(
        sorted(
            (
                dict(entry)
                for entry in entries
            ),
            key=lambda entry: (
                entry.get("control_key") or "",
                entry.get("frame_path") or "",
                entry.get("semantic_kind") or "",
                entry.get("reason") or "",
            ),
        )
    )


def build_dynamic_form_effect_evidence(
    before,
    after,
    *,
    action,
    source_catalog_key=None,
):
    """Construye evidencia determinista de efectos de formulario.

    `before`/`after` deben ser instancias normalizadas de
    ``SiteArchitectureSnapshot``. `action` es obligatoria y representa
    la ÚNICA acción deliberada conocida que conecta ambos snapshots.

    No ejecuta interacción de navegador. No infiere causalidad por la
    mera diferencia entre snapshots no relacionados.
    """

    if not isinstance(before, SiteArchitectureSnapshot):
        raise ValueError(
            "DYNAMIC_FORM_EFFECT_BEFORE_SNAPSHOT_REQUIRED"
        )

    if not isinstance(after, SiteArchitectureSnapshot):
        raise ValueError(
            "DYNAMIC_FORM_EFFECT_AFTER_SNAPSHOT_REQUIRED"
        )

    projected_action = _project_source_action(action)

    before_index, before_unresolved = _build_control_index(
        before.elements
    )

    after_index, after_unresolved = _build_control_index(
        after.elements
    )

    before_keys = set(before_index)
    after_keys = set(after_index)

    effects = []

    for key in (before_keys & after_keys):
        effects.extend(
            _diff_control(
                key,
                before_index[key],
                after_index[key],
            )
        )

    for key in (after_keys - before_keys):
        effects.append(
            _appeared_effect(
                key,
                after_index[key],
            )
        )

    for key in (before_keys - after_keys):
        effects.append(
            _disappeared_effect(
                key,
                before_index[key],
            )
        )

    effects.sort(
        key=lambda effect: (
            effect["target"]["control_key"],
            effect["kind"],
        )
    )

    unresolved = _sorted_unresolved(
        before_unresolved
        + after_unresolved
    )

    result = {
        "schema_version":
            DYNAMIC_FORM_EFFECT_SCHEMA_VERSION,

        "action": projected_action,

        "form_effects": tuple(effects),

        "effect_count": len(effects),

        "unresolved": unresolved,

        "inconclusive":
            bool(unresolved)
            or not projected_action["resolved"],
    }

    if source_catalog_key is not None:
        dynamic_evidence = build_catalog_dynamic_evidence(
            before.catalogs,
            after.catalogs,
            source_catalog_key=source_catalog_key,
        )

        result["catalog_dynamic_evidence"] = dynamic_evidence

        result["catalog_causal_relations"] = (
            build_catalog_causal_relations(
                dynamic_evidence
            )
        )

    return result

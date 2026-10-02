"""Estado funcional de formulario observable — Site Architecture.

Captura evidencia de CONTROL (hay valor, está marcado, qué opción
está seleccionada, hay fichero elegido) sin promover el valor
literal del usuario a identidad funcional normalizada.

No decide branching. No es autoridad de fingerprint funcional.
"""

from __future__ import annotations


FORM_STATE_SCHEMA_VERSION = 1
FORM_CONSTRAINTS_SCHEMA_VERSION = 1


_STATE_SEMANTICS = frozenset({
    "TEXT_INPUT",
    "TEXTAREA",
    "FILE_INPUT",
    "HIDDEN_INPUT",
    "CHECKBOX",
    "RADIO",
    "SELECT",
})

_TEXT_LIKE_SEMANTICS = frozenset({
    "TEXT_INPUT",
    "TEXTAREA",
    "HIDDEN_INPUT",
})


def _as_bool(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return (
            value.strip().lower()
            == "true"
        )

    if value is None:
        return False

    return bool(value)


def _as_optional_bool(value):
    if value is None:
        return None

    return _as_bool(value)


def _semantics(element):
    return {
        str(value).strip().upper()
        for value in (
            element.get("semantics")
            or ()
        )
        if str(value).strip()
    }


def _attributes(element):
    value = (
        element.get("attributes")
        or {}
    )

    if not isinstance(value, dict):
        return {}

    return value


def _form_signals(element):
    value = (
        element.get("form_signals")
        or {}
    )

    if not isinstance(value, dict):
        return {}

    return value


def _options(element):
    value = element.get("options")

    if not isinstance(value, list):
        return ()

    return tuple(
        option
        for option in value
        if isinstance(option, dict)
    )


def _attribute_text(attributes, name):
    if name not in attributes:
        return None

    text = str(
        attributes.get(name)
        if attributes.get(name) is not None
        else ""
    ).strip()

    return text or None


def _bool_constraint(signals, attributes, key):
    if (
        key in signals
        and signals.get(key) is not None
    ):
        return _as_bool(
            signals.get(key)
        )

    return key in attributes


def is_relevant_form_control(element):
    """True si el elemento es un control de formulario observable."""

    if not isinstance(element, dict):
        return False

    return bool(
        _semantics(element)
        & _STATE_SEMANTICS
    )


def normalize_form_state(element):
    """Deriva evidencia observable de estado de formulario.

    Devuelve ``None`` cuando el elemento no es un control de
    formulario relevante.
    """

    if not isinstance(element, dict):
        return None

    semantics = _semantics(element)

    if not (semantics & _STATE_SEMANTICS):
        return None

    signals = _form_signals(element)

    has_value = None
    checked = None
    selected_values = []
    selected_indexes = []
    file_selected = None

    if "SELECT" in semantics:
        for (
            position,
            option,
        ) in enumerate(
            _options(element)
        ):
            if _as_bool(
                option.get("selected")
            ):
                selected_values.append(
                    str(
                        option.get("value")
                        or ""
                    )
                )

                selected_indexes.append(
                    position
                )

    elif (
        "CHECKBOX" in semantics
        or "RADIO" in semantics
    ):
        raw_checked = (
            element.get("checked")
        )

        if raw_checked is None:
            raw_checked = (
                signals.get("checked")
            )

        checked = _as_optional_bool(
            raw_checked
        )

    elif "FILE_INPUT" in semantics:
        file_selected = (
            _as_optional_bool(
                signals.get(
                    "file_selected"
                )
            )
        )

    elif semantics & _TEXT_LIKE_SEMANTICS:
        if "has_value" in signals:
            has_value = _as_optional_bool(
                signals.get("has_value")
            )

    return {
        "schema_version":
            FORM_STATE_SCHEMA_VERSION,

        "has_value":
            has_value,

        "checked":
            checked,

        "selected_values":
            tuple(selected_values),

        "selected_indexes":
            tuple(selected_indexes),

        "file_selected":
            file_selected,
    }


def normalize_form_constraints(element):
    """Deriva restricciones genéricas de formulario observables.

    Devuelve ``None`` cuando el elemento no es un control de
    formulario relevante.
    """

    if not isinstance(element, dict):
        return None

    semantics = _semantics(element)

    if not (semantics & _STATE_SEMANTICS):
        return None

    attributes = _attributes(element)
    signals = _form_signals(element)

    raw_disabled = element.get("disabled")

    if raw_disabled is None:
        raw_disabled = signals.get(
            "disabled"
        )

    return {
        "schema_version":
            FORM_CONSTRAINTS_SCHEMA_VERSION,

        "required":
            _bool_constraint(
                signals,
                attributes,
                "required",
            ),

        "readonly":
            _bool_constraint(
                signals,
                attributes,
                "readonly",
            ),

        "disabled":
            _as_bool(raw_disabled),

        "multiple":
            _bool_constraint(
                signals,
                attributes,
                "multiple",
            ),

        "pattern":
            _attribute_text(
                attributes,
                "pattern",
            ),

        "min":
            _attribute_text(
                attributes,
                "min",
            ),

        "max":
            _attribute_text(
                attributes,
                "max",
            ),

        "step":
            _attribute_text(
                attributes,
                "step",
            ),

        "minlength":
            _attribute_text(
                attributes,
                "minlength",
            ),

        "maxlength":
            _attribute_text(
                attributes,
                "maxlength",
            ),

        "placeholder":
            _attribute_text(
                attributes,
                "placeholder",
            ),

        "autocomplete":
            _attribute_text(
                attributes,
                "autocomplete",
            ),
    }

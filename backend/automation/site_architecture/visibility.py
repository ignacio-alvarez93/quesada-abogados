"""Visibilidad e interactuabilidad de Site Architecture."""

from __future__ import annotations

from enum import Enum


class InteractionState(str, Enum):
    INTERACTABLE = "INTERACTABLE"
    HIDDEN = "HIDDEN"
    OFF_VIEWPORT = "OFF_VIEWPORT"
    DISABLED = "DISABLED"
    READONLY = "READONLY"
    NOT_INTERACTABLE = "NOT_INTERACTABLE"


_ACTIONABLE_SEMANTICS = frozenset({
    "TEXT_INPUT",
    "FILE_INPUT",
    "CHECKBOX",
    "RADIO",
    "SELECT",
    "TEXTAREA",
    "BUTTON",
    "SUBMIT",
    "LINK",
})

_EDITABLE_SEMANTICS = frozenset({
    "TEXT_INPUT",
    "TEXTAREA",
})


def _as_bool(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return (
            value.strip().lower()
            == "true"
        )

    return bool(value)


def _as_float(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_interaction_state(
    element,
):
    """Deriva estado funcional sin realizar interacción runtime."""

    if not isinstance(element, dict):
        return {
            "exists": False,
            "visible": False,
            "in_viewport": None,
            "interactable": False,
            "state":
                InteractionState.NOT_INTERACTABLE.value,
        }

    signals = element.get(
        "interaction_signals"
    )

    if not isinstance(signals, dict):
        signals = {}

    raw_visible = _as_bool(
        element.get("visible")
    )

    hidden = _as_bool(
        signals.get("hidden")
    )

    aria_hidden = _as_bool(
        signals.get("aria_hidden")
    )

    native_disabled = _as_bool(
        element.get("disabled")
    )

    aria_disabled = _as_bool(
        signals.get("aria_disabled")
    )

    readonly = _as_bool(
        signals.get("readonly")
    )

    in_viewport = (
        signals.get("in_viewport")
    )

    if not isinstance(
        in_viewport,
        bool,
    ):
        in_viewport = None

    opacity = _as_float(
        signals.get("opacity")
    )

    pointer_events = str(
        signals.get("pointer_events")
        or ""
    ).strip().lower()

    semantics = set(
        element.get("semantics")
        or ()
    )

    disabled = (
        native_disabled
        or aria_disabled
    )

    visible = (
        raw_visible
        and not hidden
        and not aria_hidden
        and opacity != 0.0
    )

    readonly_blocks = (
        readonly
        and bool(
            semantics
            & _EDITABLE_SEMANTICS
        )
    )

    if not visible:
        state = InteractionState.HIDDEN
    elif disabled:
        state = InteractionState.DISABLED
    elif in_viewport is False:
        state = InteractionState.OFF_VIEWPORT
    elif pointer_events == "none":
        state = InteractionState.NOT_INTERACTABLE
    elif readonly_blocks:
        state = InteractionState.READONLY
    elif semantics & _ACTIONABLE_SEMANTICS:
        state = InteractionState.INTERACTABLE
    else:
        state = InteractionState.NOT_INTERACTABLE

    return {
        "exists": True,
        "raw_visible": raw_visible,
        "visible": visible,
        "in_viewport": in_viewport,
        "native_disabled": native_disabled,
        "aria_disabled": aria_disabled,
        "disabled": disabled,
        "aria_hidden": aria_hidden,
        "hidden": hidden,
        "readonly": readonly,
        "opacity": opacity,
        "pointer_events": (
            pointer_events
            or None
        ),
        "interactable": (
            state
            == InteractionState.INTERACTABLE
        ),
        "state": state.value,
    }

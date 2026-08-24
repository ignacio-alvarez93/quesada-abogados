"""Detección pasiva de transiciones funcionales QCC."""

from __future__ import annotations

from .contract_diff import (
    diff_site_architecture,
)
from .state_fingerprint import (
    build_functional_state_fingerprint,
)


STATE_TRANSITION_SCHEMA_VERSION = 1
STATE_TRANSITION_TYPE = "QCC_STATE_TRANSITION"

STATE_TRANSITION_CHANGED = (
    "FUNCTIONAL_STATE_CHANGED"
)

STATE_TRANSITION_UNCHANGED = (
    "FUNCTIONAL_STATE_UNCHANGED"
)

STATE_TRANSITION_CONFIDENCE_HIGH = "HIGH"
STATE_TRANSITION_CONFIDENCE_MEDIUM = "MEDIUM"
STATE_TRANSITION_CONFIDENCE_LOW = "LOW"


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


def _normalize_action(action):
    """
    Conserva únicamente identidad funcional de la acción.

    No transporta text, value, payload ni datos de formulario.
    """

    if action is None:
        return None

    if not isinstance(action, dict):
        raise ValueError(
            "SITE_ARCHITECTURE_TRANSITION_ACTION_INVALID"
        )

    return {
        "kind":
            _text(
                action.get("kind")
            ),

        "policy":
            _text(
                action.get("policy")
            ),

        "selector":
            _text(
                action.get("selector")
            ),

        "frame_path":
            str(
                action.get("frame_path")
                or "main"
            ),
    }


def _transition_confidence(
    *,
    changed,
    inconclusive,
):
    if not inconclusive:
        return (
            STATE_TRANSITION_CONFIDENCE_HIGH
        )

    if changed:
        # El fingerprint demuestra cambio funcional,
        # aunque el diff estructural no pueda emparejar
        # todos los elementos.
        return (
            STATE_TRANSITION_CONFIDENCE_MEDIUM
        )

    return (
        STATE_TRANSITION_CONFIDENCE_LOW
    )


def detect_state_transition(
    before,
    after,
    *,
    action=None,
):
    """
    Compara dos Site Architecture snapshots sin ejecutar acciones.

    El fingerprint gobierna la existencia de transición funcional.
    El contract diff aporta evidencia diagnóstica adicional.
    """

    before_fingerprint = (
        build_functional_state_fingerprint(
            before
        )
    )

    after_fingerprint = (
        build_functional_state_fingerprint(
            after
        )
    )

    changed = (
        before_fingerprint
        != after_fingerprint
    )

    contract_diff = (
        diff_site_architecture(
            before,
            after,
        )
    )

    inconclusive = bool(
        contract_diff.get(
            "inconclusive"
        )
    )

    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "status":
            (
                STATE_TRANSITION_CHANGED
                if changed
                else STATE_TRANSITION_UNCHANGED
            ),

        "changed":
            changed,

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

        "action":
            _normalize_action(
                action
            ),

        "contract_changed":
            bool(
                contract_diff.get(
                    "contract_changed"
                )
            ),

        "inconclusive":
            inconclusive,

        "confidence":
            _transition_confidence(
                changed=changed,
                inconclusive=inconclusive,
            ),

        "contract_diff":
            contract_diff,
    }

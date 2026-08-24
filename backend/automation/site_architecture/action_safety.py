"""Política fail-closed de seguridad para acciones QCC."""

from __future__ import annotations

from .action_inventory import (
    ACTION_POLICY_NAVIGATION,
    ACTION_POLICY_REQUIRES_POLICY,
    ACTION_POLICY_STATE_CHANGE,
    ACTION_POLICY_VALUE_CHANGE,
)


ACTION_SAFETY_SCHEMA_VERSION = 1

ACTION_SAFETY_REVERSIBLE_CANDIDATE = (
    "REVERSIBLE_CANDIDATE"
)

ACTION_SAFETY_NAVIGATION_CANDIDATE = (
    "NAVIGATION_CANDIDATE"
)

ACTION_SAFETY_REVIEW_REQUIRED = (
    "REVIEW_REQUIRED"
)

ACTION_SAFETY_HUMAN_ONLY = (
    "HUMAN_ONLY"
)

ACTION_SAFETY_DENY = "DENY"


_EXPECTED_POLICY = {
    "SELECT":
        ACTION_POLICY_STATE_CHANGE,

    "RADIO":
        ACTION_POLICY_STATE_CHANGE,

    "CHECKBOX":
        ACTION_POLICY_STATE_CHANGE,

    "INPUT_VALUE":
        ACTION_POLICY_VALUE_CHANGE,

    "TAB":
        ACTION_POLICY_NAVIGATION,

    "LINK":
        ACTION_POLICY_NAVIGATION,

    "BUTTON":
        ACTION_POLICY_REQUIRES_POLICY,

    "SUBMIT":
        ACTION_POLICY_REQUIRES_POLICY,

    "FILE_UPLOAD":
        ACTION_POLICY_REQUIRES_POLICY,
}


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _decision(
    action,
    *,
    decision,
    reason,
    requires_restore=False,
):
    return {
        "schema_version":
            ACTION_SAFETY_SCHEMA_VERSION,

        "decision":
            decision,

        "reason":
            reason,

        "requires_restore":
            bool(
                requires_restore
            ),

        "action": {
            "kind":
                _text(
                    action.get("kind")
                ),

            "policy":
                _text(
                    action.get("policy")
                ),

            "selector":
                (
                    _text(
                        action.get("selector")
                    )
                    or None
                ),

            "frame_path":
                _text(
                    action.get(
                        "frame_path"
                    )
                )
                or "main",
        },
    }


def evaluate_action_safety(
    action,
):
    """
    Clasifica una acción sin ejecutarla.

    UNKNOWN siempre es DENY.

    Esta función NO concede por sí sola permiso
    de ejecución activa. Solo genera candidatos
    que una capa posterior deberá gobernar.
    """

    if not isinstance(
        action,
        dict,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_ACTION_SAFETY_INPUT_INVALID"
        )

    kind = _text(
        action.get("kind")
    ).upper()

    policy = _text(
        action.get("policy")
    ).upper()

    expected_policy = (
        _EXPECTED_POLICY.get(
            kind
        )
    )

    if expected_policy is None:
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="UNKNOWN_ACTION_KIND",
        )

    if policy != expected_policy:
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="ACTION_POLICY_MISMATCH",
        )

    selector = _text(
        action.get("selector")
    )

    if not selector:
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="SELECTOR_MISSING",
        )

    interaction = (
        action.get("interaction")
        or {}
    )

    if not isinstance(
        interaction,
        dict,
    ):
        interaction = {}

    if (
        interaction.get("visible")
        is not True
    ):
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="ACTION_NOT_VISIBLE",
        )

    if (
        interaction.get("disabled")
        is True
    ):
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="ACTION_DISABLED",
        )

    if (
        interaction.get("interactable")
        is not True
    ):
        return _decision(
            action,
            decision=ACTION_SAFETY_DENY,
            reason="ACTION_NOT_INTERACTABLE",
        )

    if kind in {
        "TAB",
        "LINK",
    }:
        return _decision(
            action,
            decision=(
                ACTION_SAFETY_NAVIGATION_CANDIDATE
            ),
            reason=(
                "NAVIGATION_REQUIRES_SITE_POLICY"
            ),
        )

    if kind in {
        "BUTTON",
        "SUBMIT",
        "FILE_UPLOAD",
        "INPUT_VALUE",
    }:
        return _decision(
            action,
            decision=(
                ACTION_SAFETY_REVIEW_REQUIRED
            ),
            reason=(
                "ACTIVE_ACTION_REQUIRES_SITE_POLICY"
            ),
        )

    if kind in {
        "SELECT",
        "RADIO",
        "CHECKBOX",
    }:
        return _decision(
            action,
            decision=(
                ACTION_SAFETY_REVERSIBLE_CANDIDATE
            ),
            reason=(
                "REVERSIBLE_STATE_CHANGE_CANDIDATE"
            ),
            requires_restore=True,
        )

    return _decision(
        action,
        decision=ACTION_SAFETY_DENY,
        reason="FAIL_CLOSED",
    )

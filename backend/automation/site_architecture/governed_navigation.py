"""Gobierno JIT del siguiente paso de navegación QCC."""

from __future__ import annotations

from copy import deepcopy

from .managed_execution import (
    authorize_managed_target,
)
from .navigation_planner import (
    NAVIGATION_PLAN_ALREADY_AT_TARGET,
    NAVIGATION_PLAN_ROUTE_FOUND,
    NAVIGATION_PLAN_TYPE,
)
from .site_interaction_policy import (
    SITE_INTERACTION_DENY,
    evaluate_site_interaction,
)


GOVERNED_NAVIGATION_SCHEMA_VERSION = 1
GOVERNED_NAVIGATION_TYPE = (
    "QCC_GOVERNED_NAVIGATION"
)

GOVERNED_NAVIGATION_NO_ACTION = (
    "NO_ACTION_REQUIRED"
)

GOVERNED_NAVIGATION_OBSERVE_ONLY = (
    "OBSERVE_ONLY"
)

GOVERNED_NAVIGATION_AUTOMATIC_TRANSITION = (
    "AUTOMATIC_TRANSITION"
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _normalize_identity(
    action,
):
    if not isinstance(
        action,
        dict,
    ):
        return None

    kind = _text(
        action.get("kind")
    ).upper()

    policy = _text(
        action.get("policy")
    ).upper()

    selector = _text(
        action.get("selector")
    )

    frame_path = (
        _text(
            action.get(
                "frame_path"
            )
        )
        or "main"
    )

    if (
        not kind
        or not policy
        or not selector
    ):
        return None

    return (
        kind,
        policy,
        selector,
        frame_path,
    )


def _normalize_plan(
    plan,
):
    if not isinstance(
        plan,
        dict,
    ):
        raise ValueError(
            "GOVERNED_NAVIGATION_PLAN_INVALID"
        )

    if (
        plan.get(
            "plan_type"
        )
        != NAVIGATION_PLAN_TYPE
    ):
        raise ValueError(
            "GOVERNED_NAVIGATION_PLAN_TYPE_INVALID"
        )

    steps = plan.get(
        "steps"
    )

    if not isinstance(
        steps,
        (tuple, list),
    ):
        raise ValueError(
            "GOVERNED_NAVIGATION_STEPS_INVALID"
        )

    next_step = plan.get(
        "next_step"
    )

    if (
        next_step is not None
        and not isinstance(
            next_step,
            dict,
        )
    ):
        raise ValueError(
            "GOVERNED_NAVIGATION_NEXT_STEP_INVALID"
        )

    return (
        tuple(
            steps
        ),
        next_step,
    )


def _base_result(
    *,
    plan,
    target_authorization,
    decision,
    reason,
    automation_allowed=False,
    interaction=None,
    matched_action=None,
):
    steps = tuple(
        plan.get(
            "steps"
        )
        or ()
    )

    next_step = plan.get(
        "next_step"
    )

    return {
        "schema_version":
            GOVERNED_NAVIGATION_SCHEMA_VERSION,

        "governed_navigation_type":
            GOVERNED_NAVIGATION_TYPE,

        "plan_status":
            plan.get(
                "status"
            ),

        "reachable":
            bool(
                plan.get(
                    "reachable"
                )
            ),

        "source_fingerprint":
            plan.get(
                "source_fingerprint"
            ),

        "target_fingerprint":
            plan.get(
                "target_fingerprint"
            ),

        "step_count":
            len(
                steps
            ),

        "governed_step_index":
            (
                next_step.get(
                    "index"
                )
                if isinstance(
                    next_step,
                    dict,
                )
                else None
            ),

        "unevaluated_step_count":
            max(
                len(
                    steps
                )
                - (
                    1
                    if next_step
                    is not None
                    else 0
                ),
                0,
            ),

        "decision":
            decision,

        "reason":
            reason,

        "automation_allowed":
            bool(
                automation_allowed
            ),

        "target_authorization":
            deepcopy(
                target_authorization
            ),

        "interaction":
            deepcopy(
                interaction
            ),

        # Solo identidad segura del action vivo.
        "matched_action":
            deepcopy(
                matched_action
            ),
    }


def _safe_action_identity(
    action,
):
    identity = _normalize_identity(
        action
    )

    if identity is None:
        return None

    (
        kind,
        policy,
        selector,
        frame_path,
    ) = identity

    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            frame_path,
    }


def govern_navigation_plan(
    plan,
    *,
    target,
    profile,
    policy,
    current_actions=(),
):
    """
    Gobierna únicamente el siguiente paso.

    La ruta completa sigue siendo descriptiva.

    Un paso activo solo puede autorizarse usando
    una acción observada EN EL ESTADO VIVO ACTUAL.

    Los pasos futuros nunca se preautorizan.

    Una transición sin acción significa observar
    el cambio automático; no significa ejecutar.
    """

    steps, next_step = (
        _normalize_plan(
            plan
        )
    )

    target_authorization = (
        authorize_managed_target(
            target,
            profile,
        )
    )

    if not plan.get(
        "reachable"
    ):
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason="PLAN_UNREACHABLE",
        )

    if (
        plan.get("status")
        == NAVIGATION_PLAN_ALREADY_AT_TARGET
    ):
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                GOVERNED_NAVIGATION_NO_ACTION
            ),
            reason="ALREADY_AT_TARGET",
        )

    if (
        plan.get("status")
        != NAVIGATION_PLAN_ROUTE_FOUND
        or next_step is None
    ):
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason="NEXT_STEP_UNAVAILABLE",
        )

    if not target_authorization[
        "authorized"
    ]:
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason=(
                "MANAGED_TARGET_DENIED:"
                + str(
                    target_authorization[
                        "reason"
                    ]
                )
            ),
        )

    planned_action = (
        next_step.get(
            "action"
        )
    )

    if planned_action is None:
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                GOVERNED_NAVIGATION_OBSERVE_ONLY
            ),
            reason=(
                GOVERNED_NAVIGATION_AUTOMATIC_TRANSITION
            ),
        )

    planned_identity = (
        _normalize_identity(
            planned_action
        )
    )

    if planned_identity is None:
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason="PLANNED_ACTION_IDENTITY_INVALID",
        )

    if not isinstance(
        current_actions,
        (tuple, list),
    ):
        raise ValueError(
            "GOVERNED_NAVIGATION_CURRENT_ACTIONS_INVALID"
        )

    matches = []

    for action in current_actions:
        if (
            _normalize_identity(
                action
            )
            == planned_identity
        ):
            matches.append(
                action
            )

    if not matches:
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason="LIVE_ACTION_NOT_OBSERVED",
        )

    if len(matches) != 1:
        return _base_result(
            plan=plan,
            target_authorization=(
                target_authorization
            ),
            decision=(
                SITE_INTERACTION_DENY
            ),
            reason="LIVE_ACTION_IDENTITY_AMBIGUOUS",
        )

    live_action = matches[0]

    interaction = (
        evaluate_site_interaction(
            target=target,
            profile=profile,
            policy=policy,
            action=live_action,
        )
    )

    return _base_result(
        plan=plan,
        target_authorization=(
            target_authorization
        ),
        decision=(
            interaction[
                "decision"
            ]
        ),
        reason=(
            interaction[
                "reason"
            ]
        ),
        automation_allowed=(
            interaction[
                "automation_allowed"
            ]
        ),
        interaction=interaction,
        matched_action=(
            _safe_action_identity(
                live_action
            )
        ),
    )

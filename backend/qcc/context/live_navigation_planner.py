"""Planificación descriptiva de navegación viva QCC.

Esta capa conecta:

CURRENT observado
+ TARGET explícito
+ Navigation Graph conocido
-> ROUTE descriptiva

No ejecuta.
No gobierna.
No concede permisos.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.navigation_planner import (
    NAVIGATION_PLAN_ALREADY_AT_TARGET,
    NAVIGATION_PLAN_ROUTE_FOUND,
    plan_navigation_route,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)


LIVE_PLAN_PROJECTED = "PROJECTED"
LIVE_PLAN_NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
LIVE_PLAN_NO_CURRENT = "NO_CURRENT"
LIVE_PLAN_STALE_SESSION = "STALE_SESSION"
LIVE_PLAN_TARGET_REQUIRED = "TARGET_REQUIRED"
LIVE_PLAN_GRAPH_INVALID = "GRAPH_INVALID"


_CONFIDENCE_PROJECTION = {
    # Rango ordinal para el contrato visual V1.
    # No representa probabilidad estadística.
    "LOW": 0.33,
    "MEDIUM": 0.66,
    "HIGH": 1.0,
}


def _text(
    value,
):
    normalized = str(
        value
        or ""
    ).strip()

    return normalized or None


def _frame_path(
    value,
):
    if value is None:
        return None

    if isinstance(
        value,
        tuple,
    ):
        return tuple(
            str(part)
            for part in value
        )

    if isinstance(
        value,
        list,
    ):
        return tuple(
            str(part)
            for part in value
        )

    normalized = _text(
        value
    )

    if normalized is None:
        return None

    return (
        normalized,
    )


def _confidence(
    value,
):
    normalized = (
        _text(
            value
        )
        or ""
    ).upper()

    return (
        _CONFIDENCE_PROJECTION
        .get(
            normalized
        )
    )


def _result(
    *,
    projected,
    reason,
    revision=None,
    plan_status=None,
):
    return {
        "projected":
            bool(
                projected
            ),

        "reason":
            str(
                reason
            ),

        "revision":
            (
                int(
                    revision
                )
                if revision is not None
                else None
            ),

        "plan_status":
            (
                str(
                    plan_status
                )
                if plan_status is not None
                else None
            ),
    }


def project_live_navigation_plan(
    context_store,
    graph,
    *,
    target_fingerprint,
    target_state=None,
):
    """Calcula y proyecta una ruta sobre CURRENT vivo.

    El target es explícito.

    Esta función deliberadamente NO intenta deducir
    objetivos desde procedure/current_step.

    Tampoco llama a governed_navigation.
    """

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_NO_ACTIVE_SESSION
            ),
        )

    active_session = (
        context_store
        .get_active_session()
    )

    if active_session is None:
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_NO_ACTIVE_SESSION
            ),
        )

    current = (
        context_store
        .get_live_navigation()
    )

    if current is None:
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_NO_CURRENT
            ),
        )

    if (
        current.session_id
        != active_session.session_id
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_STALE_SESSION
            ),
        )

    source_fingerprint = (
        _text(
            current.current_fingerprint
        )
    )

    if source_fingerprint is None:
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_NO_CURRENT
            ),
        )

    normalized_target = (
        _text(
            target_fingerprint
        )
    )

    if normalized_target is None:
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_TARGET_REQUIRED
            ),
        )

    try:
        plan = plan_navigation_route(
            graph,
            source_fingerprint,
            normalized_target,
        )

    except (
        TypeError,
        ValueError,
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_GRAPH_INVALID
            ),
        )

    next_step = (
        plan.get(
            "next_step"
        )
    )

    action = (
        next_step.get(
            "action"
        )
        if isinstance(
            next_step,
            dict,
        )
        else None
    )

    if not isinstance(
        action,
        dict,
    ):
        action = {}

    navigation = (
        QccLiveNavigationContext(
            session_id=(
                active_session.session_id
            ),

            updated_at=datetime.now(
                timezone.utc
            ),

            current_state=(
                current.current_state
            ),

            current_fingerprint=(
                source_fingerprint
            ),

            target_state=(
                _text(
                    target_state
                )
            ),

            target_fingerprint=(
                normalized_target
            ),

            route_reachable=(
                bool(
                    plan.get(
                        "reachable"
                    )
                )
            ),

            remaining_steps=(
                int(
                    plan.get(
                        "remaining_steps",
                        0,
                    )
                    or 0
                )
            ),

            next_step_kind=(
                _text(
                    action.get(
                        "kind"
                    )
                )
                if next_step
                is not None
                else None
            ),

            next_step_policy=(
                _text(
                    action.get(
                        "policy"
                    )
                )
                if next_step
                is not None
                else None
            ),

            next_step_selector=(
                _text(
                    action.get(
                        "selector"
                    )
                )
                if next_step
                is not None
                else None
            ),

            next_step_frame_path=(
                _frame_path(
                    action.get(
                        "frame_path"
                    )
                )
                if next_step
                is not None
                else None
            ),

            next_step_confidence=(
                _confidence(
                    next_step.get(
                        "confidence"
                    )
                )
                if next_step
                is not None
                else None
            ),

            # El planner NUNCA concede permisos.
            governance_decision=None,
            governance_reason=None,
            automation_allowed=None,

            display_title=(
                "Objetivo alcanzado"
                if (
                    plan.get(
                        "status"
                    )
                    == NAVIGATION_PLAN_ALREADY_AT_TARGET
                )
                else (
                    "Ruta disponible"
                    if (
                        plan.get(
                            "status"
                        )
                        == NAVIGATION_PLAN_ROUTE_FOUND
                    )
                    else
                    "Ruta no disponible"
                )
            ),

            display_instruction=(
                None
            ),
        )
    )

    try:
        revision = (
            context_store
            .set_live_navigation(
                navigation
            )
        )

    except ValueError:
        # La sesión pudo cambiar mientras
        # se calculaba la ruta.
        return _result(
            projected=False,
            reason=(
                LIVE_PLAN_STALE_SESSION
            ),
            plan_status=(
                plan.get(
                    "status"
                )
            ),
        )

    return _result(
        projected=True,
        reason=(
            LIVE_PLAN_PROJECTED
        ),
        revision=revision,
        plan_status=(
            plan.get(
                "status"
            )
        ),
    )

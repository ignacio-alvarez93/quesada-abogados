"""Coordinación descriptiva de navegación viva QCC.

Encadena:

CURRENT
+ NavigationIntent
+ NavigationKnowledge
-> Target Resolver
-> Live Planner

No ejecuta acciones.
No gobierna interacciones.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

from backend.qcc.context.live_navigation_planner import (
    project_live_navigation_plan,
)
from backend.qcc.context.navigation_target_resolver import (
    resolve_navigation_target,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


LIVE_PLANNING_REFRESHED = (
    "REFRESHED"
)

LIVE_PLANNING_CLEARED = (
    "CLEARED"
)

LIVE_PLANNING_NO_ACTIVE_SESSION = (
    "NO_ACTIVE_SESSION"
)

LIVE_PLANNING_NO_CURRENT = (
    "NO_CURRENT"
)

LIVE_PLANNING_NO_INTENT = (
    "NO_INTENT"
)

LIVE_PLANNING_STALE_SESSION = (
    "STALE_SESSION"
)

LIVE_PLANNING_SITE_MISMATCH = (
    "SITE_MISMATCH"
)

LIVE_PLANNING_TARGET_UNRESOLVED = (
    "TARGET_UNRESOLVED"
)

LIVE_PLANNING_PLAN_NOT_PROJECTED = (
    "PLAN_NOT_PROJECTED"
)


def _code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    return normalized or None


def _result(
    *,
    refreshed,
    reason,
    target_resolution=None,
    planning=None,
    revision=None,
):
    return {
        "refreshed":
            bool(
                refreshed
            ),

        "reason":
            str(
                reason
            ),

        "target_resolution":
            target_resolution,

        "planning":
            planning,

        "revision":
            (
                int(
                    revision
                )
                if revision is not None
                else None
            ),
    }


def _project_unresolved_target(
    context_store,
    current,
    intent,
    resolution,
):
    """Publica CURRENT + INTENT aunque aún no exista ruta."""

    reachable = (
        resolution.get(
            "reachable"
        )
    )

    if reachable is not False:
        reachable = None

    navigation = (
        QccLiveNavigationContext(
            session_id=(
                current.session_id
            ),

            updated_at=datetime.now(
                timezone.utc
            ),

            current_state=(
                current.current_state
            ),

            current_fingerprint=(
                current.current_fingerprint
            ),

            target_state=(
                intent.target_state
            ),

            target_fingerprint=(
                intent.target_fingerprint
            ),

            route_reachable=(
                reachable
            ),

            remaining_steps=None,

            next_step_kind=None,
            next_step_policy=None,
            next_step_selector=None,
            next_step_frame_path=None,
            next_step_confidence=None,

            governance_decision=None,
            governance_reason=None,
            automation_allowed=None,

            display_title=(
                "Objetivo sin ruta conocida"
            ),

            display_instruction=None,
        )
    )

    return (
        context_store
        .set_live_navigation(
            navigation
        )
    )


def clear_live_navigation_plan(
    context_store,
):
    """Elimina target/route/next_step conservando CURRENT.

    También invalida cualquier governance anterior.
    """

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        raise TypeError(
            "QCC_LIVE_PLANNING_CONTEXT_STORE_INVALID"
        )

    session = (
        context_store
        .get_active_session()
    )

    if session is None:
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_NO_ACTIVE_SESSION
            ),
        )

    current = (
        context_store
        .get_live_navigation()
    )

    if current is None:
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_NO_CURRENT
            ),
        )

    if (
        current.session_id
        != session.session_id
    ):
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_STALE_SESSION
            ),
        )

    navigation = (
        QccLiveNavigationContext(
            session_id=(
                current.session_id
            ),

            updated_at=datetime.now(
                timezone.utc
            ),

            current_state=(
                current.current_state
            ),

            current_fingerprint=(
                current.current_fingerprint
            ),

            target_state=None,
            target_fingerprint=None,

            route_reachable=None,
            remaining_steps=None,

            next_step_kind=None,
            next_step_policy=None,
            next_step_selector=None,
            next_step_frame_path=None,
            next_step_confidence=None,

            governance_decision=None,
            governance_reason=None,
            automation_allowed=None,

            display_title=None,
            display_instruction=None,
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
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_STALE_SESSION
            ),
        )

    return _result(
        refreshed=True,
        reason=(
            LIVE_PLANNING_CLEARED
        ),
        revision=revision,
    )


def refresh_live_navigation_plan(
    context_store,
    knowledge_store,
    *,
    include_runtime_plan=False,
):
    """Recalcula la navegación desde el CURRENT vivo.

    El objetivo procede exclusivamente del
    NavigationIntent de la sesión.

    El conocimiento procede exclusivamente del
    NavigationKnowledgeStore del sitio.

    Nunca se infiere autorización de la ruta.
    """

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        raise TypeError(
            "QCC_LIVE_PLANNING_CONTEXT_STORE_INVALID"
        )

    if not isinstance(
        knowledge_store,
        NavigationKnowledgeStore,
    ):
        raise TypeError(
            "QCC_LIVE_PLANNING_KNOWLEDGE_STORE_INVALID"
        )

    session = (
        context_store
        .get_active_session()
    )

    if session is None:
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_NO_ACTIVE_SESSION
            ),
        )

    current = (
        context_store
        .get_live_navigation()
    )

    if (
        current is None
        or not current.current_fingerprint
    ):
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_NO_CURRENT
            ),
        )

    if (
        current.session_id
        != session.session_id
    ):
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_STALE_SESSION
            ),
        )

    intent = (
        context_store
        .get_navigation_intent()
    )

    if intent is None:
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_NO_INTENT
            ),
        )

    if (
        intent.session_id
        != session.session_id
    ):
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_STALE_SESSION
            ),
        )

    if (
        _code(
            session.provider
        )
        != _code(
            intent.site_code
        )
    ):
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_SITE_MISMATCH
            ),
        )

    resolution = (
        resolve_navigation_target(
            knowledge_store,
            intent,
            current_fingerprint=(
                current.current_fingerprint
            ),
        )
    )

    if not resolution[
        "resolved"
    ]:
        try:
            revision = (
                _project_unresolved_target(
                    context_store,
                    current,
                    intent,
                    resolution,
                )
            )

        except ValueError:
            return _result(
                refreshed=False,
                reason=(
                    LIVE_PLANNING_STALE_SESSION
                ),
                target_resolution=(
                    resolution
                ),
            )

        return _result(
            refreshed=True,
            reason=(
                LIVE_PLANNING_TARGET_UNRESOLVED
            ),
            target_resolution=(
                resolution
            ),
            revision=revision,
        )

    graph = (
        knowledge_store
        .build_graph(
            intent.site_code
        )
    )

    planning = (
        project_live_navigation_plan(
            context_store,
            graph,
            target_state=(
                resolution[
                    "target_state"
                ]
            ),
            target_fingerprint=(
                resolution[
                    "target_fingerprint"
                ]
            ),
            include_runtime_plan=(
                include_runtime_plan
            ),
        )
    )

    if not planning[
        "projected"
    ]:
        return _result(
            refreshed=False,
            reason=(
                LIVE_PLANNING_PLAN_NOT_PROJECTED
            ),
            target_resolution=(
                resolution
            ),
            planning=planning,
        )

    return _result(
        refreshed=True,
        reason=(
            LIVE_PLANNING_REFRESHED
        ),
        target_resolution=(
            resolution
        ),
        planning=planning,
        revision=(
            planning.get(
                "revision"
            )
        ),
    )

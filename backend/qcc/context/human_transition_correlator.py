"""Correlación runtime-only entre acción humana y CURRENT posterior.

Una acción humana abre un episodio causal.

Cada CURRENT posterior actualiza provisionalmente el destino B del
mismo episodio. El episodio no se consume con el primer snapshot.

La llegada de la siguiente acción humana cierra el episodio anterior
contra el último CURRENT observado.
"""

from __future__ import annotations

from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
    normalize_utc_datetime,
)


def _observation_identity(
    context_store,
):
    getter = getattr(
        context_store,
        "get_observation_identity",
        None,
    )

    if callable(getter):
        return getter()

    getter = getattr(
        context_store,
        "get_active_session",
        None,
    )

    return (
        getter()
        if callable(getter)
        else None
    )


def correlate_observed_human_transition(
    context_store,
    *,
    after_site_code,
    after_observed_at,
):
    """Actualiza el destino provisional del episodio causal abierto."""

    if context_store is None:
        return None

    after_time = normalize_utc_datetime(
        after_observed_at,
        "QCC_HUMAN_TRANSITION_AFTER_TIME_INVALID",
    )

    site_code = str(
        after_site_code
        or ""
    ).strip().upper()

    if not site_code:
        return None

    session = _observation_identity(
        context_store
    )

    current = (
        context_store
        .get_live_navigation()
    )

    environment = (
        context_store
        .get_navigation_environment()
    )

    if (
        session is None
        or current is None
        or environment is None
    ):
        return None

    action = (
        context_store
        .get_observed_human_action()
    )

    if action is None:
        return None

    if (
        action.session_id
        != session.session_id
        or current.session_id
        != action.session_id
    ):
        return None

    if (
        action.site_code
        != site_code
    ):
        return None

    if (
        action.environment
        != environment
    ):
        return None

    if (
        after_time
        <= action.observed_at
    ):
        return None

    transition = (
        QccObservedHumanTransition
        .from_action(
            action,
            after_state=(
                current.current_state
            ),
            after_fingerprint=(
                current.current_fingerprint
            ),
            after_observed_at=(
                after_time
            ),
        )
    )

    setter = getattr(
        context_store,
        "set_observed_human_transition",
        None,
    )

    if callable(setter):
        transition = setter(
            transition
        )

    return transition


def finalize_observed_human_transition_against_next_action(
    context_store,
    *,
    next_action,
):
    """Cierra X contra el estado exacto existente antes de Y.

    La siguiente acción humana válida Y constituye una frontera
    causal fuerte porque su LiveActionEvidence fue capturada
    mientras el usuario todavía estaba físicamente en B.

    Por tanto:

        X -> Y.before

    No dependemos del CURRENT existente cuando el HTTP de Y
    alcanza el Bridge. CURRENT puede haber avanzado ya a C.
    """

    if context_store is None:
        return None

    if not isinstance(
        next_action,
        QccObservedHumanAction,
    ):
        raise TypeError(
            "QCC_HUMAN_TRANSITION_NEXT_ACTION_TYPE_INVALID"
        )

    boundary_time = normalize_utc_datetime(
        next_action.observed_at,
        "QCC_HUMAN_TRANSITION_BOUNDARY_TIME_INVALID",
    )

    action = (
        context_store
        .get_observed_human_action(
            now=boundary_time,
        )
    )

    if action is None:
        return None

    # Retry/idempotency of the same physical event is not
    # a new causal boundary.
    if (
        action.event_id
        == next_action.event_id
    ):
        return None

    session = _observation_identity(
        context_store
    )

    environment = (
        context_store
        .get_navigation_environment()
    )

    if (
        session is None
        or environment is None
    ):
        return None

    if (
        session.session_id
        != action.session_id
        or next_action.session_id
        != action.session_id
    ):
        return None

    if (
        next_action.site_code
        != action.site_code
        or next_action.environment
        != action.environment
        or environment
        != action.environment
    ):
        return None

    if (
        boundary_time
        <= action.observed_at
    ):
        return None

    transition = (
        QccObservedHumanTransition
        .from_action(
            action,
            after_state=(
                next_action.before_state
            ),
            after_fingerprint=(
                next_action.before_fingerprint
            ),
            # Y.before was necessarily observed before the
            # physical action Y. Using the boundary time is
            # conservative and preserves strict ordering.
            after_observed_at=(
                boundary_time
            ),
        )
    )

    consumed = (
        context_store
        .consume_observed_human_action(
            session_id=(
                action.session_id
            ),
            now=boundary_time,
        )
    )

    if (
        consumed is None
        or consumed.event_id
        != action.event_id
    ):
        return None

    # Any provisional snapshot belonging to X is superseded
    # by the stronger exact Y.before boundary.
    clearer = getattr(
        context_store,
        "clear_observed_human_transition",
        None,
    )

    if callable(
        clearer
    ):
        clearer(
            session_id=(
                action.session_id
            )
        )

    return transition


def finalize_observed_human_transition(
    context_store,
    *,
    before_next_action_at,
):
    """Cierra A -> último B justo antes de comenzar una nueva acción.

    Si no existe destino provisional posterior a A, no se inventa
    causalidad y la acción permanece pendiente para que el caller
    pueda aplicar su política fail-closed habitual.
    """

    if context_store is None:
        return None

    boundary_time = normalize_utc_datetime(
        before_next_action_at,
        "QCC_HUMAN_TRANSITION_BOUNDARY_TIME_INVALID",
    )

    action = (
        context_store
        .get_observed_human_action()
    )

    if action is None:
        return None

    getter = getattr(
        context_store,
        "get_observed_human_transition",
        None,
    )

    transition = (
        getter()
        if callable(getter)
        else None
    )

    if transition is None:
        return None

    if (
        transition.event_id
        != action.event_id
        or transition.session_id
        != action.session_id
    ):
        return None

    after_time = normalize_utc_datetime(
        transition.after_observed_at,
        "QCC_HUMAN_TRANSITION_AFTER_TIME_INVALID",
    )

    if (
        after_time
        >= boundary_time
    ):
        return None

    consumed = (
        context_store
        .consume_observed_human_action(
            session_id=(
                action.session_id
            ),
            now=boundary_time,
        )
    )

    if (
        consumed is None
        or consumed.event_id
        != action.event_id
    ):
        return None

    clearer = getattr(
        context_store,
        "clear_observed_human_transition",
        None,
    )

    if callable(clearer):
        clearer(
            session_id=(
                action.session_id
            )
        )

    return transition

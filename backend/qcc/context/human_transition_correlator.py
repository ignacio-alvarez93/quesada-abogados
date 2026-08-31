"""Correlación runtime-only entre acción humana y CURRENT posterior."""

from __future__ import annotations

from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
    normalize_utc_datetime,
)


def correlate_observed_human_transition(
    context_store,
    *,
    after_site_code,
    after_observed_at,
):
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

    session = (
        context_store
        .get_active_session()
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

    # B debe ser realmente posterior al gesto humano.
    if (
        after_time
        <= action.observed_at
    ):
        return None

    consumed = (
        context_store
        .consume_observed_human_action(
            session_id=(
                action.session_id
            ),
            now=after_time,
        )
    )

    if (
        consumed is None
        or consumed.event_id
        != action.event_id
    ):
        return None

    transition = (
        QccObservedHumanTransition
        .from_action(
            consumed,
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
        setter(
            transition
        )

    return transition

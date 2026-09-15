"""Adapters de evidencia de navegación hacia BehaviorTrace.

REAL:
    QccObservedHumanTransition
        -> REAL_OBSERVED BehaviorTrace

TWIN:
    QCC_STATE_TRANSITION
        -> TWIN_CONTROLLED BehaviorTrace

El adapter no ejecuta acciones.

Para TWIN exige que el caller demuestre restauración exacta
del entorno después de obtener la transición.
"""

from __future__ import annotations

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
    STATE_TRANSITION_UNCHANGED,
)

from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)


from .behavior_trace import (
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    build_auto_twin_behavior_trace,
)


def _text(
    value,
):
    result = str(
        value
        or ""
    ).strip()

    return result or None


def _twin_transition(
    value,
):
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != STATE_TRANSITION_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_INVALID"
        )

    if (
        value.get(
            "transition_type"
        )
        != STATE_TRANSITION_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_TYPE_INVALID"
        )

    changed = value.get(
        "changed"
    )

    if not isinstance(
        changed,
        bool,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_CHANGED_INVALID"
        )

    expected_status = (
        STATE_TRANSITION_CHANGED
        if changed
        else STATE_TRANSITION_UNCHANGED
    )

    if (
        value.get(
            "status"
        )
        != expected_status
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_STATUS_INVALID"
        )

    action = value.get(
        "action"
    )

    if not isinstance(
        action,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TWIN_ACTION_REQUIRED"
        )

    kind = _text(
        action.get(
            "kind"
        )
    )

    selector = _text(
        action.get(
            "selector"
        )
    )

    if (
        not kind
        or not selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TWIN_ACTION_INVALID"
        )

    before_fingerprint = _text(
        value.get(
            "before_fingerprint"
        )
    )

    after_fingerprint = _text(
        value.get(
            "after_fingerprint"
        )
    )

    if (
        not before_fingerprint
        or not after_fingerprint
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_FINGERPRINT_REQUIRED"
        )

    return {
        "changed":
            changed,

        "action": {
            "kind":
                kind,

            "selector":
                selector,

            "frame_path":
                _text(
                    action.get(
                        "frame_path"
                    )
                )
                or "main",
        },

        "policy":
            _text(
                action.get(
                    "policy"
                )
            ),

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

        "confidence":
            _text(
                value.get(
                    "confidence"
                )
            ),

        "contract_changed":
            bool(
                value.get(
                    "contract_changed"
                )
            ),

        "inconclusive":
            bool(
                value.get(
                    "inconclusive"
                )
            ),
    }


def behavior_trace_from_observed_human_transition(
    transition,
    *,
    twin_key,
    candidate_id,
):
    """Adapta evidencia humana REAL sin reconstruir nada."""

    if not isinstance(
        transition,
        QccObservedHumanTransition,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_REAL_HUMAN_TRANSITION_INVALID"
        )

    return build_auto_twin_behavior_trace(
        twin_key=twin_key,
        candidate_id=candidate_id,
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
        ),
        action={
            "kind":
                transition.kind,

            "selector":
                transition.selector,

            "frame_path":
                transition.frame_path,
        },
        transition={
            "before_state":
                transition.before_state,

            "after_state":
                transition.after_state,

            "changed":
                transition.changed,
        },
        policy=(
            transition.policy
        ),
        references={
            "event_id":
                transition.event_id,

            "session_id":
                transition.session_id,

            "site_code":
                transition.site_code,

            "environment":
                transition.environment,

            "before_fingerprint":
                transition.before_fingerprint,

            "after_fingerprint":
                transition.after_fingerprint,

            "action_observed_at":
                transition.action_observed_at.isoformat(),

            "after_observed_at":
                transition.after_observed_at.isoformat(),
        },
    )


def behavior_trace_from_twin_state_transition(
    transition,
    *,
    twin_key,
    candidate_id,
    before_state,
    after_state,
    restoration_exact,
):
    """Adapta QCC_STATE_TRANSITION obtenido en TWIN.

    `restoration_exact=True` debe proceder del runtime que
    restauró el TWIN después de la prueba. El adapter no realiza
    ni simula esa restauración.
    """

    if restoration_exact is not True:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TWIN_RESTORATION_REQUIRED"
        )

    normalized = (
        _twin_transition(
            transition
        )
    )

    return build_auto_twin_behavior_trace(
        twin_key=twin_key,
        candidate_id=candidate_id,
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
        ),
        action=(
            normalized[
                "action"
            ]
        ),
        transition={
            "before_state":
                _text(
                    before_state
                ),

            "after_state":
                _text(
                    after_state
                ),

            "changed":
                normalized[
                    "changed"
                ],
        },
        policy=(
            normalized[
                "policy"
            ]
        ),
        restoration_status=(
            AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
        ),
        references={
            "before_fingerprint":
                normalized[
                    "before_fingerprint"
                ],

            "after_fingerprint":
                normalized[
                    "after_fingerprint"
                ],

            "confidence":
                normalized[
                    "confidence"
                ],

            "contract_changed":
                normalized[
                    "contract_changed"
                ],

            "inconclusive":
                normalized[
                    "inconclusive"
                ],
        },
    )

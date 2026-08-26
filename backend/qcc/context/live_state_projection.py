"""Proyección segura de observación viva hacia QCC Context.

Una captura nueva solo puede publicar CURRENT.

Nunca conserva target, route, next_step ni governance
anteriores: deben recalcularse contra el DOM vivo.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from typing import Any

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)


LIVE_STATE_PROJECTED = (
    "PROJECTED"
)

LIVE_STATE_NO_ACTIVE_SESSION = (
    "NO_ACTIVE_SESSION"
)

LIVE_STATE_CAPTURE_NOT_SESSION_BOUND = (
    "CAPTURE_NOT_SESSION_BOUND"
)

LIVE_STATE_STALE_SESSION = (
    "STALE_SESSION"
)

LIVE_STATE_SITE_UNRECOGNIZED = (
    "SITE_UNRECOGNIZED"
)

LIVE_STATE_SITE_MISMATCH = (
    "SITE_MISMATCH"
)

LIVE_STATE_OBSERVATION_INVALID = (
    "OBSERVATION_INVALID"
)


def _normalized_code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    return normalized or None


def _updated_at(
    value,
):
    if isinstance(
        value,
        datetime,
    ):
        parsed = value

    else:
        raw = str(
            value
            or ""
        ).strip()

        if not raw:
            return datetime.now(
                timezone.utc
            )

        if raw.endswith(
            "Z"
        ):
            raw = (
                raw[:-1]
                + "+00:00"
            )

        try:
            parsed = (
                datetime.fromisoformat(
                    raw
                )
            )
        except ValueError:
            return datetime.now(
                timezone.utc
            )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed


def _result(
    *,
    projected,
    reason,
    revision=None,
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
    }


def project_ingested_state_observation(
    context_store,
    ingest_result,
):
    """Proyecta CURRENT si captura y sesión siguen vinculadas.

    Condiciones:
    - la captura nació bajo una sesión activa;
    - esa misma session_id sigue activa;
    - site_code observado coincide con provider;
    - existe fingerprint funcional.

    La observación es pasiva y nunca concede permisos.
    """

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_NO_ACTIVE_SESSION
            ),
        )

    if not isinstance(
        ingest_result,
        dict,
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_OBSERVATION_INVALID
            ),
        )

    capture_session_id = str(
        ingest_result.get(
            "session_id"
        )
        or ""
    ).strip()

    if not capture_session_id:
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_CAPTURE_NOT_SESSION_BOUND
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
                LIVE_STATE_NO_ACTIVE_SESSION
            ),
        )

    if (
        active_session.session_id
        != capture_session_id
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_STALE_SESSION
            ),
        )

    observed_site_code = (
        _normalized_code(
            ingest_result.get(
                "site_code"
            )
        )
    )

    if observed_site_code is None:
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_SITE_UNRECOGNIZED
            ),
        )

    expected_site_code = (
        _normalized_code(
            active_session.provider
        )
    )

    if (
        observed_site_code
        != expected_site_code
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_SITE_MISMATCH
            ),
        )

    observation = (
        ingest_result.get(
            "state_observation"
        )
    )

    if not isinstance(
        observation,
        dict,
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_OBSERVATION_INVALID
            ),
        )

    fingerprint = str(
        observation.get(
            "fingerprint"
        )
        or ""
    ).strip()

    if (
        len(
            fingerprint
        )
        != 64
        or any(
            character
            not in "0123456789abcdefABCDEF"
            for character
            in fingerprint
        )
    ):
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_OBSERVATION_INVALID
            ),
        )

    state = (
        _normalized_code(
            observation.get(
                "state"
            )
        )
    )

    navigation = (
        QccLiveNavigationContext(
            session_id=(
                capture_session_id
            ),

            updated_at=(
                _updated_at(
                    ingest_result.get(
                        "received_at"
                    )
                )
            ),

            current_state=
                state,

            current_fingerprint=
                fingerprint,

            # IMPORTANTE:
            # cualquier planificación anterior
            # queda invalidada por un DOM nuevo.
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
        # La sesión pudo cambiar entre
        # get_active_session() y el write.
        return _result(
            projected=False,
            reason=(
                LIVE_STATE_STALE_SESSION
            ),
        )

    return _result(
        projected=True,
        reason=(
            LIVE_STATE_PROJECTED
        ),
        revision=revision,
    )

"""Store en memoria del contexto operativo de QCC.

No es persistencia canónica.

Su función es proyectar hacia Chrome el estado actual
de una presentación/automatización administrada por
el backend del ERP.
"""

from __future__ import annotations

import threading
from typing import Any

from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.context.observed_human_action import (
    QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS,
    QccObservedHumanAction,
)
from backend.qcc.context.live_action_evidence import (
    QCC_LIVE_ACTION_EVIDENCE_TTL_SECONDS,
    QccLiveActionEvidence,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)


class QccContextStore:
    """Snapshot thread-safe del contexto activo de QCC."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

        self._active_session: (
            QccPresentationSession
            | None
        ) = None

        self._live_navigation: (
            QccLiveNavigationContext
            | None
        ) = None

        self._navigation_intent: (
            QccNavigationIntent
            | None
        ) = None

        # Runtime-only.
        #
        # Namespace de NavigationKnowledge asociado
        # a la URL/origin viva observada para ESTA
        # sesión.
        #
        # No forma parte de snapshot() ni de ningún
        # contrato HTTP público.
        self._navigation_environment: (
            str
            | None
        ) = None

        # Runtime-only.
        #
        # Evidencia de UNA acción humana explícitamente
        # observada y todavía no correlacionada con una
        # observación posterior.
        #
        # Nunca forma parte de snapshot().
        self._observed_human_action: (
            QccObservedHumanAction
            | None
        ) = None

        # Runtime-only.
        #
        # Inventario canónico de acciones asociado al
        # CURRENT exacto observado en la última captura.
        #
        # No forma parte de snapshot().
        self._live_action_evidence: (
            QccLiveActionEvidence
            | None
        ) = None

        # Runtime-only.
        #
        # Última transición humana A + acción + B
        # correlacionada contra CURRENT.
        #
        # Nunca forma parte de snapshot().
        self._observed_human_transition: (
            QccObservedHumanTransition
            | None
        ) = None

        self._revision = 0

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def get_active_session(
        self,
    ) -> QccPresentationSession | None:
        with self._lock:
            return self._active_session

    def get_live_navigation(
        self,
    ) -> QccLiveNavigationContext | None:
        with self._lock:
            return self._live_navigation

    def get_navigation_intent(
        self,
    ) -> QccNavigationIntent | None:
        with self._lock:
            return self._navigation_intent

    def get_navigation_environment(
        self,
    ) -> str | None:
        """Devuelve el environment runtime de la sesión.

        Deliberadamente NO se publica mediante snapshot().
        """

        with self._lock:
            return self._navigation_environment

    def set_navigation_environment(
        self,
        environment,
        *,
        session_id: str,
    ) -> str:
        """Vincula un environment runtime a la sesión activa.

        El scope procede de evidencia runtime fiable
        —por ejemplo, origin viva resuelta por el registry—.

        Una misma sesión no puede cambiar silenciosamente
        de environment.
        """

        normalized_session_id = str(
            session_id
            or ""
        ).strip()

        if not normalized_session_id:
            raise ValueError(
                "QCC_NAVIGATION_ENVIRONMENT_SESSION_ID_REQUIRED"
            )

        normalized_environment = str(
            getattr(
                environment,
                "value",
                environment,
            )
            or ""
        ).strip().upper()

        if not normalized_environment:
            raise ValueError(
                "QCC_NAVIGATION_ENVIRONMENT_REQUIRED"
            )

        with self._lock:
            session = self._active_session

            if (
                session is None
                or session.session_id
                != normalized_session_id
            ):
                raise ValueError(
                    "QCC_NAVIGATION_ENVIRONMENT_SESSION_NOT_ACTIVE"
                )

            current = (
                self._navigation_environment
            )

            if (
                current is not None
                and current
                != normalized_environment
            ):
                raise ValueError(
                    "QCC_NAVIGATION_ENVIRONMENT_CONFLICT"
                )

            self._navigation_environment = (
                normalized_environment
            )

            # IMPORTANTE:
            #
            # No incrementamos revision.
            # Es contexto privado runtime-only y no cambia
            # el snapshot público observable.
            return normalized_environment

    def clear_navigation_environment(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Elimina únicamente el environment runtime."""

        with self._lock:
            current = (
                self._navigation_environment
            )

            if current is None:
                return False

            if session_id is not None:
                normalized_session_id = str(
                    session_id
                    or ""
                ).strip()

                session = self._active_session

                if (
                    session is None
                    or session.session_id
                    != normalized_session_id
                ):
                    return False

            self._navigation_environment = None
            self._observed_human_action = None
            self._live_action_evidence = None
            self._observed_human_transition = None

            # Igual que set: no modifica revision pública.
            return True

    def get_live_action_evidence(
        self,
        *,
        now=None,
        ttl_seconds=(
            QCC_LIVE_ACTION_EVIDENCE_TTL_SECONDS
        ),
    ) -> QccLiveActionEvidence | None:
        """Devuelve inventario canónico si sigue ligado al CURRENT."""

        with self._lock:
            evidence = (
                self._live_action_evidence
            )

            if evidence is None:
                return None

            session = (
                self._active_session
            )

            current = (
                self._live_navigation
            )

            if (
                session is None
                or session.session_id
                != evidence.session_id
            ):
                self._live_action_evidence = None
                return None

            provider = str(
                session.provider
                or ""
            ).strip().upper()

            if (
                provider
                != evidence.site_code
            ):
                self._live_action_evidence = None
                return None

            if (
                self._navigation_environment
                != evidence.environment
            ):
                self._live_action_evidence = None
                return None

            if (
                current is None
                or current.session_id
                != evidence.session_id
                or current.current_fingerprint
                != evidence.before_fingerprint
            ):
                self._live_action_evidence = None
                return None

            if (
                evidence.before_state
                is not None
                and current.current_state
                != evidence.before_state
            ):
                self._live_action_evidence = None
                return None

            if not evidence.is_fresh(
                now=now,
                ttl_seconds=ttl_seconds,
            ):
                self._live_action_evidence = None
                return None

            return evidence

    def set_live_action_evidence(
        self,
        evidence: QccLiveActionEvidence,
    ) -> QccLiveActionEvidence:
        """Liga acciones canónicas al CURRENT exacto."""

        if not isinstance(
            evidence,
            QccLiveActionEvidence,
        ):
            raise TypeError(
                "QCC_LIVE_ACTION_EVIDENCE_TYPE_INVALID"
            )

        with self._lock:
            session = (
                self._active_session
            )

            current = (
                self._live_navigation
            )

            if (
                session is None
                or session.session_id
                != evidence.session_id
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_SESSION_NOT_ACTIVE"
                )

            provider = str(
                session.provider
                or ""
            ).strip().upper()

            if (
                provider
                != evidence.site_code
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_SITE_MISMATCH"
                )

            if (
                self._navigation_environment
                is None
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_ENVIRONMENT_UNAVAILABLE"
                )

            if (
                self._navigation_environment
                != evidence.environment
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_ENVIRONMENT_MISMATCH"
                )

            if current is None:
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_CURRENT_REQUIRED"
                )

            if (
                current.session_id
                != evidence.session_id
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_CURRENT_SESSION_MISMATCH"
                )

            if (
                current.current_fingerprint
                != evidence.before_fingerprint
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_FINGERPRINT_MISMATCH"
                )

            if (
                evidence.before_state
                is not None
                and current.current_state
                != evidence.before_state
            ):
                raise ValueError(
                    "QCC_LIVE_ACTION_EVIDENCE_STATE_MISMATCH"
                )

            self._live_action_evidence = (
                evidence
            )

            # Runtime-only: no revision pública.
            return evidence

    def clear_live_action_evidence(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Invalida inventario canónico pendiente."""

        with self._lock:
            evidence = (
                self._live_action_evidence
            )

            if evidence is None:
                return False

            if (
                session_id is not None
                and evidence.session_id
                != str(
                    session_id
                ).strip()
            ):
                return False

            self._live_action_evidence = None

            # Runtime-only: no revision pública.
            return True

    def get_observed_human_action(
        self,
        *,
        now=None,
        ttl_seconds=(
            QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS
        ),
    ) -> QccObservedHumanAction | None:
        """Devuelve evidencia pendiente si sigue siendo fresca."""

        with self._lock:
            action = (
                self._observed_human_action
            )

            if action is None:
                return None

            if not action.is_fresh(
                now=now,
                ttl_seconds=ttl_seconds,
            ):
                self._observed_human_action = None
                return None

            session = (
                self._active_session
            )

            if (
                session is None
                or session.session_id
                != action.session_id
            ):
                self._observed_human_action = None
                return None

            if (
                self._navigation_environment
                != action.environment
            ):
                self._observed_human_action = None
                return None

            return action

    def set_observed_human_action(
        self,
        action: QccObservedHumanAction,
    ) -> QccObservedHumanAction:
        """Registra una única evidencia humana no ambigua.

        La evidencia debe quedar anclada al CURRENT exacto
        que existía antes de la acción.
        """

        if not isinstance(
            action,
            QccObservedHumanAction,
        ):
            raise TypeError(
                "QCC_OBSERVED_HUMAN_ACTION_TYPE_INVALID"
            )

        with self._lock:
            session = (
                self._active_session
            )

            if (
                session is None
                or session.session_id
                != action.session_id
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_SESSION_NOT_ACTIVE"
                )

            provider = str(
                session.provider
                or ""
            ).strip().upper()

            if (
                provider
                != action.site_code
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_SITE_MISMATCH"
                )

            if (
                self._navigation_environment
                is None
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_ENVIRONMENT_UNAVAILABLE"
                )

            if (
                self._navigation_environment
                != action.environment
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_ENVIRONMENT_MISMATCH"
                )

            current = (
                self._live_navigation
            )

            if current is None:
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_CURRENT_REQUIRED"
                )

            if (
                current.session_id
                != action.session_id
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_CURRENT_SESSION_MISMATCH"
                )

            if (
                current.current_fingerprint
                != action.before_fingerprint
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_FINGERPRINT_MISMATCH"
                )

            if (
                action.before_state
                is not None
                and current.current_state
                != action.before_state
            ):
                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_STATE_MISMATCH"
                )

            pending = (
                self._observed_human_action
            )

            if pending is not None:
                if (
                    pending.event_id
                    == action.event_id
                ):
                    # Reintento de transporte:
                    # idempotente.
                    return pending

                # Más de una acción antes de observar B:
                # la causalidad queda ambigua.
                self._observed_human_action = None

                raise ValueError(
                    "QCC_OBSERVED_HUMAN_ACTION_AMBIGUOUS"
                )

            self._observed_human_action = (
                action
            )

            # Runtime-only: no revision pública.
            return action

    def consume_observed_human_action(
        self,
        *,
        session_id: str,
        now=None,
        ttl_seconds=(
            QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS
        ),
    ) -> QccObservedHumanAction | None:
        """Consume como máximo una evidencia humana fresca."""

        normalized_session_id = str(
            session_id
            or ""
        ).strip()

        if not normalized_session_id:
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_SESSION_ID_REQUIRED"
            )

        with self._lock:
            session = (
                self._active_session
            )

            if (
                session is None
                or session.session_id
                != normalized_session_id
            ):
                return None

            action = (
                self._observed_human_action
            )

            if action is None:
                return None

            # Single-use incluso si después resulta inválida.
            self._observed_human_action = None

            if (
                action.session_id
                != normalized_session_id
            ):
                return None

            if (
                self._navigation_environment
                != action.environment
            ):
                return None

            if not action.is_fresh(
                now=now,
                ttl_seconds=ttl_seconds,
            ):
                return None

            return action

    def clear_observed_human_action(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Invalida evidencia humana pendiente."""

        with self._lock:
            action = (
                self._observed_human_action
            )

            if action is None:
                return False

            if (
                session_id is not None
                and action.session_id
                != str(
                    session_id
                ).strip()
            ):
                return False

            self._observed_human_action = None

            # Runtime-only: no revision pública.
            return True

    def set_active_session(
        self,
        session: QccPresentationSession,
    ) -> int:
        if not isinstance(
            session,
            QccPresentationSession,
        ):
            raise TypeError(
                "QCC_SESSION_TYPE_INVALID"
            )

        with self._lock:
            previous = self._active_session

            if (
                previous is not None
                and previous.session_id
                != session.session_id
            ):
                self._live_navigation = None
                self._navigation_intent = None
                self._navigation_environment = None
                self._observed_human_action = None
                self._live_action_evidence = None

            self._active_session = session
            self._revision += 1

            return self._revision

    def set_live_navigation(
        self,
        navigation: QccLiveNavigationContext,
    ) -> int:
        if not isinstance(
            navigation,
            QccLiveNavigationContext,
        ):
            raise TypeError(
                "QCC_LIVE_NAVIGATION_TYPE_INVALID"
            )

        with self._lock:
            session = self._active_session

            if (
                session is None
                or session.session_id
                != navigation.session_id
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_SESSION_NOT_ACTIVE"
                )

            self._live_action_evidence = None
            self._live_navigation = navigation
            self._revision += 1

            return self._revision

    def set_navigation_intent(
        self,
        intent: QccNavigationIntent,
    ) -> int:
        if not isinstance(
            intent,
            QccNavigationIntent,
        ):
            raise TypeError(
                "QCC_NAVIGATION_INTENT_TYPE_INVALID"
            )

        with self._lock:
            session = self._active_session

            if (
                session is None
                or session.session_id
                != intent.session_id
            ):
                raise ValueError(
                    "QCC_NAVIGATION_INTENT_SESSION_NOT_ACTIVE"
                )

            provider = str(
                session.provider
                or ""
            ).strip().upper()

            if (
                provider
                != intent.site_code
            ):
                raise ValueError(
                    "QCC_NAVIGATION_INTENT_SITE_MISMATCH"
                )

            self._navigation_intent = (
                intent
            )

            self._revision += 1

            return self._revision

    def clear_navigation_intent(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        with self._lock:
            current = (
                self._navigation_intent
            )

            if current is None:
                return False

            if (
                session_id is not None
                and current.session_id
                != session_id
            ):
                return False

            self._navigation_intent = None
            self._revision += 1

            return True

    def clear_live_navigation(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        with self._lock:
            current = self._live_navigation

            if current is None:
                return False

            if (
                session_id is not None
                and current.session_id
                != session_id
            ):
                return False

            self._live_navigation = None
            self._observed_human_action = None
            self._live_action_evidence = None
            self._revision += 1

            return True

    def clear_active_session(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Elimina la sesión activa y su navegación.

        Si se proporciona session_id, solo elimina la
        sesión si todavía coincide. Esto evita que un
        runtime antiguo borre accidentalmente una sesión
        posterior.
        """

        with self._lock:
            current = self._active_session

            if current is None:
                return False

            if (
                session_id is not None
                and current.session_id
                != session_id
            ):
                return False

            self._active_session = None
            self._live_navigation = None
            self._navigation_intent = None
            self._navigation_environment = None
            self._observed_human_action = None
            self._live_action_evidence = None
            self._revision += 1

            return True


    def get_observed_human_transition(
        self,
    ) -> QccObservedHumanTransition | None:
        """Devuelve la transición humana ligada al CURRENT actual."""

        with self._lock:
            transition = (
                self._observed_human_transition
            )

            if transition is None:
                return None

            session = self._active_session
            current = self._live_navigation

            if (
                session is None
                or current is None
                or session.session_id
                != transition.session_id
                or current.session_id
                != transition.session_id
                or str(
                    session.provider
                    or ""
                ).strip().upper()
                != transition.site_code
                or self._navigation_environment
                != transition.environment
                or current.current_fingerprint
                != transition.after_fingerprint
            ):
                self._observed_human_transition = None
                return None

            if (
                transition.after_state
                is not None
                and current.current_state
                != transition.after_state
            ):
                self._observed_human_transition = None
                return None

            return transition

    def set_observed_human_transition(
        self,
        transition: QccObservedHumanTransition,
    ) -> QccObservedHumanTransition:
        """Liga una transición humana terminada al CURRENT B."""

        if not isinstance(
            transition,
            QccObservedHumanTransition,
        ):
            raise TypeError(
                "QCC_HUMAN_TRANSITION_TYPE_INVALID"
            )

        with self._lock:
            session = self._active_session
            current = self._live_navigation

            if (
                session is None
                or session.session_id
                != transition.session_id
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_SESSION_NOT_ACTIVE"
                )

            if (
                str(
                    session.provider
                    or ""
                ).strip().upper()
                != transition.site_code
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_SITE_MISMATCH"
                )

            if (
                self._navigation_environment
                != transition.environment
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_ENVIRONMENT_MISMATCH"
                )

            if (
                current is None
                or current.session_id
                != transition.session_id
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_CURRENT_REQUIRED"
                )

            if (
                current.current_fingerprint
                != transition.after_fingerprint
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_AFTER_FINGERPRINT_MISMATCH"
                )

            if (
                transition.after_state
                is not None
                and current.current_state
                != transition.after_state
            ):
                raise ValueError(
                    "QCC_HUMAN_TRANSITION_AFTER_STATE_MISMATCH"
                )

            existing = (
                self._observed_human_transition
            )

            if (
                existing is not None
                and existing.event_id
                == transition.event_id
            ):
                return existing

            self._observed_human_transition = (
                transition
            )

            # Runtime-only: no revision pública.
            return transition

    def clear_observed_human_transition(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        with self._lock:
            transition = (
                self._observed_human_transition
            )

            if transition is None:
                return False

            if (
                session_id is not None
                and transition.session_id
                != str(
                    session_id
                    or ""
                ).strip()
            ):
                return False

            self._observed_human_transition = None
            return True

    def snapshot(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._active_session
            navigation = self._live_navigation

            return {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "revision":
                    self._revision,

                "active":
                    session is not None,

                "active_session":
                    (
                        session.to_payload()
                        if session is not None
                        else None
                    ),

                "live_navigation":
                    (
                        navigation.to_payload()
                        if navigation is not None
                        else None
                    ),
            }

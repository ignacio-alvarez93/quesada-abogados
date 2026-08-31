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

            # Igual que set: no modifica revision pública.
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
            self._revision += 1

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

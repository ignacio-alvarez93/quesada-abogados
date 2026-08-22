"""Store en memoria del contexto operativo de QCC.

No es persistencia canónica.

Su función es proyectar hacia Chrome el estado actual
de una presentación/automatización administrada por
el backend del ERP.
"""

from __future__ import annotations

import threading
from typing import Any

from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)


class QccContextStore:
    """Snapshot thread-safe del contexto activo de QCC."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

        self._active_session: (
            QccPresentationSession
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
            self._active_session = session
            self._revision += 1

            return self._revision

    def clear_active_session(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Elimina la sesión activa.

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
            self._revision += 1

            return True

    def snapshot(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._active_session

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
            }

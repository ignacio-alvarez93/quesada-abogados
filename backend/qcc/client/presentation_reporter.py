"""Reporter fail-open para runtimes de presentación.

Este cliente NO controla el navegador.

Su única responsabilidad es publicar snapshots operativos
hacia QCC Bridge. Un fallo de QCC nunca debe impedir que
el runtime consumidor continúe funcionando.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import (
    datetime,
    timezone,
)
import json
from typing import (
    Any,
    Mapping,
)
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


DEFAULT_QCC_BRIDGE_URL = (
    "http://127.0.0.1:8766"
)

DEFAULT_QCC_TIMEOUT = 0.4


class QccPresentationReporter:
    """Publicador desacoplado de estados de presentación."""

    def __init__(
        self,
        *,
        session_id: str,
        expedient_id: int,
        client_id: int,
        procedure: str,
        provider: str,
        runtime: str,
        started_at: datetime | None = None,
        bridge_base_url: str = (
            DEFAULT_QCC_BRIDGE_URL
        ),
        timeout: float = (
            DEFAULT_QCC_TIMEOUT
        ),
    ) -> None:
        self._bridge_base_url = (
            str(bridge_base_url)
            .rstrip("/")
        )

        self._timeout = float(
            timeout
        )

        self._session = (
            QccPresentationSession(
                session_id=session_id,
                expedient_id=expedient_id,
                client_id=client_id,
                procedure=procedure,
                provider=provider,
                runtime=runtime,
                started_at=(
                    started_at
                    or datetime.now(
                        timezone.utc
                    )
                ),
                status=(
                    QccPresentationStatus
                    .AUTOMATING
                ),
                current_step="STARTING",
                progress=0,
                requires_user_action=False,
                last_event={
                    "event":
                        "presentation.started",
                    "message":
                        "Presentación iniciada",
                },
            )
        )

    @property
    def session(
        self,
    ) -> QccPresentationSession:
        return self._session

    def _publish(
        self,
    ) -> bool:
        body = json.dumps(
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "session":
                    self._session.to_payload(),
            },
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        request = Request(
            (
                self._bridge_base_url
                + "/qcc/session"
            ),
            data=body,
            headers={
                "Content-Type":
                    "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self._timeout,
            ) as response:
                return (
                    int(
                        response.status
                    )
                    == 200
                )

        except Exception:
            # QCC es observabilidad:
            # nunca gobierna ni bloquea el runtime.
            return False

    def _transition(
        self,
        *,
        status: QccPresentationStatus,
        current_step: str,
        progress: int,
        requires_user_action: bool,
        event: str,
        message: str,
        event_details: (
            Mapping[str, Any]
            | None
        ) = None,
    ) -> bool:
        try:
            self._session = replace(
                self._session,
                status=status,
                current_step=current_step,
                progress=progress,
                requires_user_action=(
                    requires_user_action
                ),
                last_event={
                    "event":
                        event,
                    "message":
                        message,
                    **(
                        dict(
                            event_details
                        )
                        if event_details
                        is not None
                        else {}
                    ),
                },
            )

        except Exception:
            return False

        return self._publish()

    def started(
        self,
    ) -> bool:
        return self._publish()

    def automating(
        self,
        *,
        step: str,
        progress: int,
        message: str,
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .AUTOMATING
            ),
            current_step=step,
            progress=progress,
            requires_user_action=False,
            event=(
                "presentation.progress_changed"
            ),
            message=message,
        )

    def waiting_user(
        self,
        *,
        step: str,
        progress: int,
        message: str,
        event_details: (
            Mapping[str, Any]
            | None
        ) = None,
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .WAITING_USER
            ),
            current_step=step,
            progress=progress,
            requires_user_action=True,
            event=(
                "presentation.waiting_user"
            ),
            message=message,
            event_details=event_details,
        )

    def user_action_detected(
        self,
        *,
        step: str,
        progress: int,
        message: str = (
            "Acción manual detectada"
        ),
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .USER_ACTION_DETECTED
            ),
            current_step=step,
            progress=progress,
            requires_user_action=False,
            event=(
                "presentation."
                "user_action_detected"
            ),
            message=message,
        )

    def resuming(
        self,
        *,
        step: str,
        progress: int,
        message: str = (
            "Reanudando automatización"
        ),
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .RESUMING
            ),
            current_step=step,
            progress=progress,
            requires_user_action=False,
            event=(
                "presentation.resuming"
            ),
            message=message,
        )

    def completed(
        self,
        *,
        message: str = (
            "Presentación completada"
        ),
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .COMPLETED
            ),
            current_step="COMPLETED",
            progress=100,
            requires_user_action=False,
            event=(
                "presentation.completed"
            ),
            message=message,
        )

    def error(
        self,
        *,
        step: str,
        message: str,
    ) -> bool:
        return self._transition(
            status=(
                QccPresentationStatus
                .ERROR
            ),
            current_step=step,
            progress=(
                self._session.progress
            ),
            requires_user_action=False,
            event=(
                "presentation.error"
            ),
            message=message,
        )

"""Contratos versionados de Quesada Chrome Companion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


QCC_PROTOCOL_VERSION = 1


class QccPresentationStatus(
    str,
    Enum,
):
    """Estados operativos visibles para QCC."""

    AUTOMATING = "AUTOMATING"
    WAITING_USER = "WAITING_USER"
    USER_ACTION_DETECTED = (
        "USER_ACTION_DETECTED"
    )
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationSession:
    """Proyección de una presentación activa.

    QCC no es la fuente canónica de estos datos.
    Esta estructura es exclusivamente un contrato
    de transporte/proyección.
    """

    session_id: str
    expedient_id: int
    client_id: int
    procedure: str
    provider: str
    runtime: str
    started_at: datetime
    status: QccPresentationStatus

    current_step: str | None = None
    progress: int = 0
    requires_user_action: bool = False

    last_event: (
        Mapping[str, Any]
        | None
    ) = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "QCC_SESSION_ID_REQUIRED"
            )

        if self.expedient_id <= 0:
            raise ValueError(
                "QCC_EXPEDIENT_ID_INVALID"
            )

        if self.client_id <= 0:
            raise ValueError(
                "QCC_CLIENT_ID_INVALID"
            )

        for field_name in (
            "procedure",
            "provider",
            "runtime",
        ):
            value = getattr(
                self,
                field_name,
            )

            if not str(value).strip():
                raise ValueError(
                    "QCC_SESSION_FIELD_REQUIRED:"
                    f"{field_name}"
                )

        if not 0 <= self.progress <= 100:
            raise ValueError(
                "QCC_PROGRESS_OUT_OF_RANGE"
            )

        if (
            self.status
            == QccPresentationStatus.WAITING_USER
            and not self.requires_user_action
        ):
            raise ValueError(
                "QCC_WAITING_USER_REQUIRES_ACTION"
            )

    def to_payload(
        self,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id":
                self.session_id,

            "expedient_id":
                self.expedient_id,

            "client_id":
                self.client_id,

            "procedure":
                self.procedure,

            "provider":
                self.provider,

            "runtime":
                self.runtime,

            "started_at":
                self.started_at.isoformat(),

            "status":
                self.status.value,

            "current_step":
                self.current_step,

            "progress":
                self.progress,

            "requires_user_action":
                self.requires_user_action,

            "last_event":
                (
                    dict(self.last_event)
                    if self.last_event
                    is not None
                    else None
                ),
        }

        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "QccPresentationSession":
        """Reconstruye una sesión desde transporte QCC."""

        if not isinstance(
            payload,
            Mapping,
        ):
            raise ValueError(
                "QCC_SESSION_PAYLOAD_INVALID"
            )

        try:
            started_at = datetime.fromisoformat(
                str(
                    payload[
                        "started_at"
                    ]
                )
            )

            status = QccPresentationStatus(
                str(
                    payload[
                        "status"
                    ]
                )
            )

            expedient_id = int(
                payload[
                    "expedient_id"
                ]
            )

            client_id = int(
                payload[
                    "client_id"
                ]
            )

            progress = int(
                payload.get(
                    "progress",
                    0,
                )
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_SESSION_PAYLOAD_INVALID"
            ) from exc

        requires_user_action = (
            payload.get(
                "requires_user_action",
                False,
            )
        )

        if not isinstance(
            requires_user_action,
            bool,
        ):
            raise ValueError(
                "QCC_SESSION_PAYLOAD_INVALID"
            )

        last_event = payload.get(
            "last_event"
        )

        if (
            last_event is not None
            and not isinstance(
                last_event,
                Mapping,
            )
        ):
            raise ValueError(
                "QCC_SESSION_PAYLOAD_INVALID"
            )

        current_step = payload.get(
            "current_step"
        )

        return cls(
            session_id=str(
                payload.get(
                    "session_id",
                    "",
                )
            ),
            expedient_id=expedient_id,
            client_id=client_id,
            procedure=str(
                payload.get(
                    "procedure",
                    "",
                )
            ),
            provider=str(
                payload.get(
                    "provider",
                    "",
                )
            ),
            runtime=str(
                payload.get(
                    "runtime",
                    "",
                )
            ),
            started_at=started_at,
            status=status,
            current_step=(
                None
                if current_step is None
                else str(current_step)
            ),
            progress=progress,
            requires_user_action=(
                requires_user_action
            ),
            last_event=(
                dict(last_event)
                if last_event is not None
                else None
            ),
        )

"""Contrato V1 de acciones humanas enviadas desde QCC.

Las acciones son intención del usuario.

NO contienen:
- operaciones SeleniumBase;
- selectores DOM;
- SQL;
- secretos del navegador;
- rutas completas de documentos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QccActionType(
    str,
    Enum,
):
    DOCUMENTS_START = "DOCUMENTS_START"
    DOCUMENT_PREPARE = "DOCUMENT_PREPARE"
    DOCUMENT_SKIP = "DOCUMENT_SKIP"
    DOCUMENT_FORCE_TYPE = "DOCUMENT_FORCE_TYPE"


@dataclass(
    frozen=True,
    slots=True,
)
class QccActionRequest:
    session_id: str
    action: QccActionType
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        session_id = str(
            self.session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_ACTION_SESSION_ID_REQUIRED"
            )

        if not isinstance(
            self.action,
            QccActionType,
        ):
            raise ValueError(
                "QCC_ACTION_TYPE_INVALID"
            )

        if not isinstance(
            self.payload,
            dict,
        ):
            raise ValueError(
                "QCC_ACTION_PAYLOAD_INVALID"
            )

        payload = dict(
            self.payload
        )

        allowed_keys = {
            "document_index",
            "value",
        }

        if not set(
            payload
        ).issubset(
            allowed_keys
        ):
            raise ValueError(
                "QCC_ACTION_PAYLOAD_KEY_INVALID"
            )

        if (
            self.action
            == QccActionType.DOCUMENTS_START
            and payload
        ):
            raise ValueError(
                "QCC_ACTION_START_PAYLOAD_INVALID"
            )

        document_actions = {
            QccActionType.DOCUMENT_PREPARE,
            QccActionType.DOCUMENT_SKIP,
            QccActionType.DOCUMENT_FORCE_TYPE,
        }

        if self.action in document_actions:
            document_index = payload.get(
                "document_index"
            )

            if (
                isinstance(
                    document_index,
                    bool,
                )
                or not isinstance(
                    document_index,
                    int,
                )
                or document_index <= 0
            ):
                raise ValueError(
                    "QCC_ACTION_DOCUMENT_INDEX_INVALID"
                )

        if (
            self.action
            == QccActionType.DOCUMENT_FORCE_TYPE
        ):
            value = payload.get(
                "value"
            )

            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
                or len(
                    value.strip()
                ) > 32
            ):
                raise ValueError(
                    "QCC_ACTION_DOCUMENT_TYPE_INVALID"
                )

            payload[
                "value"
            ] = value.strip()

        object.__setattr__(
            self,
            "session_id",
            session_id,
        )

        object.__setattr__(
            self,
            "payload",
            payload,
        )

    def to_payload(
        self,
    ) -> dict[str, Any]:
        return {
            "session_id":
                self.session_id,

            "action":
                self.action.value,

            "payload":
                dict(
                    self.payload
                ),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        session_id: str,
    ) -> "QccActionRequest":
        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_ACTION_REQUEST_INVALID"
            )

        raw_action = payload.get(
            "action"
        )

        try:
            action = QccActionType(
                str(
                    raw_action
                ).strip()
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_ACTION_TYPE_INVALID"
            ) from exc

        raw_payload = payload.get(
            "payload",
            {},
        )

        return cls(
            session_id=session_id,
            action=action,
            payload=raw_payload,
        )

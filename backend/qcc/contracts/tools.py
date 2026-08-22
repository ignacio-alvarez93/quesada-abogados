"""Contrato V1 de herramientas solicitadas desde QCC.

Una herramienta QCC expresa una intención diagnóstica.

NO contiene:
- operaciones SeleniumBase;
- JavaScript arbitrario;
- selectores arbitrarios;
- rutas del sistema;
- secretos;
- HTML o DOM crudo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QccToolType(
    str,
    Enum,
):
    DOM_INSPECT = "DOM_INSPECT"


@dataclass(
    frozen=True,
    slots=True,
)
class QccToolRequest:
    session_id: str
    tool: QccToolType
    payload: dict[str, Any]
    client_tool_id: str | None = None

    def __post_init__(
        self,
    ) -> None:
        session_id = str(
            self.session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_TOOL_SESSION_ID_REQUIRED"
            )

        client_tool_id = (
            None
            if self.client_tool_id is None
            else str(
                self.client_tool_id
            ).strip()
        )

        if (
            self.client_tool_id is not None
            and (
                not client_tool_id
                or len(
                    client_tool_id
                ) > 128
            )
        ):
            raise ValueError(
                "QCC_CLIENT_TOOL_ID_INVALID"
            )

        if not isinstance(
            self.tool,
            QccToolType,
        ):
            raise ValueError(
                "QCC_TOOL_TYPE_INVALID"
            )

        if not isinstance(
            self.payload,
            dict,
        ):
            raise ValueError(
                "QCC_TOOL_PAYLOAD_INVALID"
            )

        payload = dict(
            self.payload
        )

        # DOM_INSPECT V1 no admite parámetros.
        #
        # El Side Panel no puede enviar:
        # - JavaScript;
        # - selectores;
        # - rutas;
        # - scopes arbitrarios.
        if (
            self.tool
            == QccToolType.DOM_INSPECT
            and payload
        ):
            raise ValueError(
                "QCC_TOOL_DOM_INSPECT_PAYLOAD_INVALID"
            )

        object.__setattr__(
            self,
            "session_id",
            session_id,
        )

        object.__setattr__(
            self,
            "client_tool_id",
            client_tool_id,
        )

        object.__setattr__(
            self,
            "payload",
            payload,
        )

    def to_payload(
        self,
    ) -> dict[str, Any]:
        result = {
            "session_id":
                self.session_id,

            "tool":
                self.tool.value,

            "payload":
                dict(
                    self.payload
                ),
        }

        if self.client_tool_id is not None:
            result[
                "client_tool_id"
            ] = self.client_tool_id

        return result

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        session_id: str,
    ) -> "QccToolRequest":
        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_TOOL_REQUEST_INVALID"
            )

        raw_tool = payload.get(
            "tool"
        )

        try:
            tool = QccToolType(
                str(
                    raw_tool
                ).strip()
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_TOOL_TYPE_INVALID"
            ) from exc

        return cls(
            session_id=session_id,
            tool=tool,
            payload=payload.get(
                "payload",
                {},
            ),
            client_tool_id=(
                payload.get(
                    "client_tool_id"
                )
            ),
        )

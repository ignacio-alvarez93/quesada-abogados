"""Cliente fail-open para consumir acciones QCC.

Este módulo NO controla el navegador.

El runtime puede consultar al Bridge si existe una
acción humana pendiente para su session_id.

Si QCC no está disponible devuelve None y permite
al consumidor conservar su mecanismo manual anterior.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)
from backend.qcc.client.presentation_reporter import (
    DEFAULT_QCC_BRIDGE_URL,
    DEFAULT_QCC_TIMEOUT,
)


class QccActionClient:
    def __init__(
        self,
        *,
        session_id: str,
        bridge_base_url: str = (
            DEFAULT_QCC_BRIDGE_URL
        ),
        timeout: float = (
            DEFAULT_QCC_TIMEOUT
        ),
    ) -> None:
        session_id = str(
            session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_ACTION_SESSION_ID_REQUIRED"
            )

        self._session_id = (
            session_id
        )

        self._bridge_base_url = (
            str(
                bridge_base_url
            ).rstrip("/")
        )

        self._timeout = float(
            timeout
        )

    @property
    def session_id(
        self,
    ) -> str:
        return self._session_id

    def consume_next(
        self,
    ) -> dict[str, Any] | None:
        body = json.dumps(
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,
            }
        ).encode(
            "utf-8"
        )

        request = Request(
            (
                self._bridge_base_url
                + "/qcc/session/"
                + self._session_id
                + "/action/consume"
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
                if (
                    int(
                        response.status
                    )
                    != 200
                ):
                    return None

                payload = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except Exception:
            return None

        if not isinstance(
            payload,
            dict,
        ):
            return None

        if not payload.get(
            "available"
        ):
            return None

        action = payload.get(
            "action"
        )

        if not isinstance(
            action,
            dict,
        ):
            return None

        return action

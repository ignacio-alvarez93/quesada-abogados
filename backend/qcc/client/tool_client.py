"""Cliente runtime fail-open para QCC Tool Channel.

No controla Chrome ni SeleniumBase.

Su única responsabilidad es consumir una intención
diagnóstica ya validada por el Bridge.
"""

from __future__ import annotations

import json
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


class QccToolClient:
    def __init__(
        self,
        *,
        session_id,
        bridge_base_url=(
            DEFAULT_QCC_BRIDGE_URL
        ),
        timeout=(
            DEFAULT_QCC_TIMEOUT
        ),
    ):
        session_id = str(
            session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_TOOL_SESSION_ID_REQUIRED"
            )

        self._session_id = session_id

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
    ):
        return self._session_id

    def consume_next(
        self,
    ):
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
                + "/tool/consume"
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

        tool = payload.get(
            "tool"
        )

        if not isinstance(
            tool,
            dict,
        ):
            return None

        return tool

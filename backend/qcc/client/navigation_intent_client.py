"""Cliente fail-open para declarar NavigationIntent QCC.

Solo comunica un objetivo de navegación.

No controla Chrome.
No calcula rutas.
No gobierna permisos.
"""

from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.client.presentation_reporter import (
    DEFAULT_QCC_BRIDGE_URL,
    DEFAULT_QCC_TIMEOUT,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)


class QccNavigationIntentClient:
    """Publicador fail-open de objetivos de navegación."""

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
                "QCC_NAVIGATION_INTENT_SESSION_ID_REQUIRED"
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
    ):
        return self._session_id

    def _publish(
        self,
        intent_payload,
    ):
        try:
            body = json.dumps(
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "intent":
                        intent_payload,
                },
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )

            session_id = quote(
                self._session_id,
                safe="",
            )

            request = Request(
                (
                    self._bridge_base_url
                    + "/qcc/session/"
                    + session_id
                    + "/navigation-intent"
                ),
                data=body,
                headers={
                    "Content-Type":
                        "application/json",
                },
                method="POST",
            )

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
            # QCC nunca bloquea al runtime.
            return False

    def publish(
        self,
        intent,
    ):
        if not isinstance(
            intent,
            QccNavigationIntent,
        ):
            return False

        if (
            intent.session_id
            != self._session_id
        ):
            return False

        return self._publish(
            intent.to_payload()
        )

    def clear(
        self,
    ):
        return self._publish(
            None
        )

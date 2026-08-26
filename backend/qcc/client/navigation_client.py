"""Cliente fail-open para publicar navegación viva QCC.

No controla el navegador ni políticas de ejecución.

Solo transporta un QccLiveNavigationContext ya construido
hacia el Bridge. Si QCC no está disponible, devuelve False
sin bloquear el runtime consumidor.
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
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)


class QccLiveNavigationClient:
    """Publicador fail-open de snapshots live navigation."""

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
                "QCC_LIVE_NAVIGATION_SESSION_ID_REQUIRED"
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
    ) -> str:
        return self._session_id

    def publish(
        self,
        navigation: QccLiveNavigationContext,
    ) -> bool:
        """Publica un snapshot ya gobernado.

        Fallos de red, Bridge, sesión o contrato
        nunca deben romper el runtime productor.
        """

        if not isinstance(
            navigation,
            QccLiveNavigationContext,
        ):
            return False

        if (
            navigation.session_id
            != self._session_id
        ):
            return False

        try:
            body = json.dumps(
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "navigation":
                        navigation.to_payload(),
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
                    + "/navigation"
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
            # Observabilidad fail-open:
            # QCC nunca impide continuar al runtime.
            return False

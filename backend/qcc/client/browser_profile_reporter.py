"""Registro fail-open de perfiles gobernados en QCC.

Este cliente no controla el navegador ni representa una
presentación concreta.

Publica exclusivamente metadata explícita del BrowserSession:

- browser_profile_key;
- BrowserSessionMode.

QCC nunca debe bloquear el arranque del consumidor.
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


DEFAULT_QCC_BRIDGE_URL = (
    "http://127.0.0.1:8766"
)

DEFAULT_QCC_BROWSER_PROFILE_TIMEOUT = 0.4


class QccBrowserProfileReporter:
    """Publica identidad funcional de un navegador gobernado."""

    def __init__(
        self,
        *,
        browser_profile_key,
        browser_session_mode,
        bridge_base_url=DEFAULT_QCC_BRIDGE_URL,
        timeout=DEFAULT_QCC_BROWSER_PROFILE_TIMEOUT,
    ):
        profile_key = str(
            browser_profile_key
            or ""
        ).strip()

        if not profile_key:
            raise ValueError(
                "QCC_BROWSER_PROFILE_KEY_REQUIRED"
            )

        mode = str(
            getattr(
                browser_session_mode,
                "value",
                browser_session_mode,
            )
            or ""
        ).strip().upper()

        if mode not in {
            "EPHEMERAL",
            "PERSISTENT",
            "ASSISTED",
        }:
            raise ValueError(
                "QCC_BROWSER_SESSION_MODE_INVALID"
            )

        self._browser_profile_key = (
            profile_key
        )

        self._browser_session_mode = (
            mode
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
    def browser_profile_key(
        self,
    ):
        return self._browser_profile_key


    @property
    def browser_session_mode(
        self,
    ):
        return self._browser_session_mode


    def register(
        self,
    ) -> bool:
        body = json.dumps(
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "browser_profile_key":
                    self._browser_profile_key,

                "browser_session_mode":
                    self._browser_session_mode,
            },
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        request = Request(
            (
                self._bridge_base_url
                + "/qcc/browser-profile"
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
            # Observabilidad fail-open:
            # nunca bloquea el BrowserSession.
            return False

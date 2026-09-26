"""Transporte HTTP oficial del BOE.

Solo esta capa conoce URLs, HTTP y formatos remotos.

Se implementa exclusivamente con biblioteca estándar para evitar
introducir dependencias externas durante la incubación de Knowledge.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from typing import Final
import urllib.error
import urllib.parse
import urllib.request

from .parser import (
    parse_boe_xml_document_payload,
)


BOE_SUMMARY_ENDPOINT: Final[str] = (
    "https://www.boe.es/datosabiertos/api/"
    "boe/sumario/{date}"
)

BOE_DOCUMENT_XML_ENDPOINT: Final[str] = (
    "https://www.boe.es/diario_boe/"
    "xml.php?id={external_id}"
)

DEFAULT_USER_AGENT: Final[str] = (
    "QuesadaAbogados-Knowledge/1.0"
)


class BoeTransportError(RuntimeError):
    """Error controlado de comunicación o formato remoto BOE."""


class BoeHttpTransport:
    """Transporte real para la API pública del BOE."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        timeout = float(timeout_seconds)

        if timeout <= 0:
            raise ValueError(
                "BOE timeout_seconds debe ser > 0"
            )

        normalized_agent = str(
            user_agent or ""
        ).strip()

        if not normalized_agent:
            raise ValueError(
                "BOE user_agent no puede estar vacío"
            )

        self._timeout_seconds = timeout
        self._user_agent = normalized_agent

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def user_agent(self) -> str:
        return self._user_agent

    def _request_bytes(
        self,
        url: str,
        *,
        accept: str,
    ) -> bytes:
        request = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "Accept": accept,
                "User-Agent": self._user_agent,
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = int(
                    getattr(
                        response,
                        "status",
                        200,
                    )
                    or 200
                )

                if status != 200:
                    raise BoeTransportError(
                        f"BOE HTTP inesperado: {status}"
                    )

                return response.read()

        except urllib.error.HTTPError as exc:
            raise BoeTransportError(
                "BOE HTTP error "
                f"{exc.code}: {exc.reason}"
            ) from exc

        except urllib.error.URLError as exc:
            raise BoeTransportError(
                f"BOE conexión fallida: {exc.reason}"
            ) from exc

        except TimeoutError as exc:
            raise BoeTransportError(
                "BOE agotó timeout de conexión"
            ) from exc

    @staticmethod
    def _normalize_summary_date(
        cursor: str | None,
    ) -> str:
        value = str(
            cursor or ""
        ).strip()

        if not value:
            raise ValueError(
                "BoeHttpTransport.discover requiere "
                "fecha explícita AAAAMMDD"
            )

        if len(value) != 8 or not value.isdigit():
            raise ValueError(
                "BOE discovery date debe usar AAAAMMDD"
            )

        try:
            datetime.strptime(
                value,
                "%Y%m%d",
            )
        except ValueError as exc:
            raise ValueError(
                "BOE discovery date no es válida"
            ) from exc

        return value

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> Mapping[str, object]:
        publication_date = (
            self._normalize_summary_date(
                cursor
            )
        )

        url = BOE_SUMMARY_ENDPOINT.format(
            date=publication_date,
        )

        raw = self._request_bytes(
            url,
            accept="application/json",
        )

        try:
            payload = json.loads(
                raw.decode("utf-8-sig")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise BoeTransportError(
                "BOE devolvió JSON de sumario no válido"
            ) from exc

        if not isinstance(
            payload,
            Mapping,
        ):
            raise BoeTransportError(
                "BOE sumario JSON debe ser objeto"
            )

        return payload

    def fetch(
        self,
        external_id: str,
    ) -> Mapping[str, object]:
        identifier = str(
            external_id or ""
        ).strip()

        if not identifier:
            raise ValueError(
                "BOE fetch requiere external_id"
            )

        if not identifier.startswith(
            "BOE-"
        ):
            raise ValueError(
                "BOE external_id tiene formato inesperado"
            )

        encoded_identifier = (
            urllib.parse.quote(
                identifier,
                safe="",
            )
        )

        url = BOE_DOCUMENT_XML_ENDPOINT.format(
            external_id=encoded_identifier,
        )

        raw_xml = self._request_bytes(
            url,
            accept=(
                "application/xml,"
                "text/xml;q=0.9,*/*;q=0.1"
            ),
        )

        try:
            return parse_boe_xml_document_payload(
                identifier,
                raw_xml,
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise BoeTransportError(
                "BOE devolvió documento XML "
                "incompatible"
            ) from exc

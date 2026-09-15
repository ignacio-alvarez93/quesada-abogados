"""Transporte HTTP para BOE Legislación Consolidada.

Solo esta capa conoce URLs, HTTP y negociación JSON/XML.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from typing import Final
import urllib.error
import urllib.parse
import urllib.request


BASE_ENDPOINT: Final[str] = (
    "https://www.boe.es/datosabiertos/api/"
    "legislacion-consolidada"
)

METADATA_ENDPOINT: Final[str] = (
    BASE_ENDPOINT
    + "/id/{external_id}/metadatos"
)

ANALYSIS_ENDPOINT: Final[str] = (
    BASE_ENDPOINT
    + "/id/{external_id}/analisis"
)

INDEX_ENDPOINT: Final[str] = (
    BASE_ENDPOINT
    + "/id/{external_id}/texto/indice"
)

TEXT_ENDPOINT: Final[str] = (
    BASE_ENDPOINT
    + "/id/{external_id}/texto"
)

DEFAULT_USER_AGENT: Final[str] = (
    "QuesadaAbogados-Knowledge/1.0"
)


class BoeConsolidatedTransportError(
    RuntimeError
):
    """Error controlado del proveedor remoto."""


class BoeConsolidatedHttpTransport:
    """Transporte real para legislación consolidada AEBOE."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        timeout = float(
            timeout_seconds
        )

        if timeout <= 0:
            raise ValueError(
                "BOE Consolidado timeout "
                "debe ser > 0"
            )

        normalized_agent = str(
            user_agent or ""
        ).strip()

        if not normalized_agent:
            raise ValueError(
                "BOE Consolidado user_agent "
                "no puede estar vacío"
            )

        self._timeout_seconds = timeout
        self._user_agent = (
            normalized_agent
        )

    @property
    def timeout_seconds(
        self,
    ) -> float:
        return self._timeout_seconds

    @property
    def user_agent(
        self,
    ) -> str:
        return self._user_agent

    def _request_bytes(
        self,
        url: str,
        *,
        accept: str,
    ) -> bytes:
        request = (
            urllib.request.Request(
                url=url,
                method="GET",
                headers={
                    "Accept": accept,
                    "User-Agent": (
                        self._user_agent
                    ),
                },
            )
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=(
                    self._timeout_seconds
                ),
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
                    raise (
                        BoeConsolidatedTransportError(
                            "BOE Consolidado "
                            "HTTP inesperado: "
                            f"{status}"
                        )
                    )

                return response.read()

        except urllib.error.HTTPError as exc:
            raise (
                BoeConsolidatedTransportError(
                    "BOE Consolidado "
                    f"HTTP error {exc.code}: "
                    f"{exc.reason}"
                )
            ) from exc

        except urllib.error.URLError as exc:
            raise (
                BoeConsolidatedTransportError(
                    "BOE Consolidado "
                    "conexión fallida: "
                    f"{exc.reason}"
                )
            ) from exc

        except TimeoutError as exc:
            raise (
                BoeConsolidatedTransportError(
                    "BOE Consolidado "
                    "agotó timeout"
                )
            ) from exc

    @staticmethod
    def _normalize_date(
        cursor: str | None,
    ) -> str:
        value = str(
            cursor or ""
        ).strip()

        if not value:
            raise ValueError(
                "BOE Consolidado discovery "
                "requiere fecha AAAAMMDD"
            )

        if (
            len(value) != 8
            or not value.isdigit()
        ):
            raise ValueError(
                "BOE Consolidado fecha "
                "debe usar AAAAMMDD"
            )

        try:
            datetime.strptime(
                value,
                "%Y%m%d",
            )
        except ValueError as exc:
            raise ValueError(
                "BOE Consolidado fecha "
                "no es válida"
            ) from exc

        return value

    @staticmethod
    def _decode_json(
        raw: bytes,
        *,
        context: str,
    ) -> Mapping[str, object]:
        try:
            payload = json.loads(
                raw.decode(
                    "utf-8-sig"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise (
                BoeConsolidatedTransportError(
                    "BOE Consolidado "
                    f"{context} JSON inválido"
                )
            ) from exc

        if not isinstance(
            payload,
            Mapping,
        ):
            raise (
                BoeConsolidatedTransportError(
                    "BOE Consolidado "
                    f"{context} debe ser objeto"
                )
            )

        return payload

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> Mapping[str, object]:
        update_date = (
            self._normalize_date(
                cursor
            )
        )

        query = urllib.parse.urlencode(
            {
                "from": update_date,
                "to": update_date,
                "limit": -1,
            }
        )

        url = (
            f"{BASE_ENDPOINT}?{query}"
        )

        raw = self._request_bytes(
            url,
            accept="application/json",
        )

        return self._decode_json(
            raw,
            context="discovery",
        )

    @staticmethod
    def _normalize_external_id(
        external_id: str,
    ) -> str:
        identifier = str(
            external_id or ""
        ).strip()

        if not identifier:
            raise ValueError(
                "BOE Consolidado fetch "
                "requiere external_id"
            )

        if not identifier.startswith(
            "BOE-"
        ):
            raise ValueError(
                "BOE Consolidado external_id "
                "tiene formato inesperado"
            )

        return identifier

    def fetch(
        self,
        external_id: str,
    ) -> Mapping[str, object]:
        identifier = (
            self._normalize_external_id(
                external_id
            )
        )

        encoded = urllib.parse.quote(
            identifier,
            safe="",
        )

        metadata_raw = (
            self._request_bytes(
                METADATA_ENDPOINT.format(
                    external_id=encoded,
                ),
                accept="application/json",
            )
        )

        analysis_raw = (
            self._request_bytes(
                ANALYSIS_ENDPOINT.format(
                    external_id=encoded,
                ),
                accept="application/json",
            )
        )

        index_raw = (
            self._request_bytes(
                INDEX_ENDPOINT.format(
                    external_id=encoded,
                ),
                accept="application/json",
            )
        )

        text_xml = (
            self._request_bytes(
                TEXT_ENDPOINT.format(
                    external_id=encoded,
                ),
                accept=(
                    "application/xml,"
                    "text/xml;q=0.9,"
                    "*/*;q=0.1"
                ),
            )
        )

        return {
            "id": identifier,
            "metadata": (
                self._decode_json(
                    metadata_raw,
                    context="metadatos",
                )
            ),
            "analysis": (
                self._decode_json(
                    analysis_raw,
                    context="análisis",
                )
            ),
            "index": (
                self._decode_json(
                    index_raw,
                    context="índice",
                )
            ),
            "text_xml": text_xml,
        }

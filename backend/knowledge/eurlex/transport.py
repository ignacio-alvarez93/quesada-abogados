"""Transporte HTTP oficial para EUR-Lex / Cellar.

Responsabilidades:

- recuperar tree notices oficiales desde Cellar;
- recuperar expresión española del acto original;
- detectar la última revisión consolidada mediante CELEX sector 0;
- intentar primero Cellar para el consolidado;
- usar EUR-Lex oficial como fallback cuando Cellar no expone
  directamente esa manifestación;
- retry/backoff controlado para errores transitorios.

No realiza canonicalización Knowledge, persistencia, UI ni IA.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Final
import urllib.error
import urllib.parse
import urllib.request

from .parser import (
    consolidated_revision_date,
    list_consolidated_celex_revisions,
    normalize_celex,
    parse_tree_notice_identifiers,
    select_latest_consolidated_celex,
)


CELLAR_CELEX_BASE: Final[str] = (
    "https://publications.europa.eu/resource/celex/"
)

EUR_LEX_CONTENT_BASE: Final[str] = (
    "https://eur-lex.europa.eu/legal-content/ES/TXT/HTML/"
)


ELI_BASE: Final[str] = (
    "https://data.europa.eu/eli"
)

DEFAULT_USER_AGENT: Final[str] = (
    "QuesadaAbogados-Knowledge/1.0"
)

DEFAULT_LANGUAGE: Final[str] = "spa"

_RETRYABLE_HTTP_STATUS = frozenset(
    {
        408,
        425,
        429,
        500,
        502,
        503,
        504,
    }
)


class EurLexTransportError(RuntimeError):
    """Error controlado del transporte EUR-Lex."""


class EurLexNotFoundError(EurLexTransportError):
    """La representación solicitada no está disponible por esa ruta."""



class EurLexRepresentationPendingError(
    EurLexTransportError
):
    """EUR-Lex aún no entrega una representación final."""


class EurLexConsolidatedRepresentationUnavailableError(
    EurLexTransportError
):
    """No existe representación consolidada utilizable en español."""


@dataclass(frozen=True, slots=True)
class EurLexHttpResponse:
    """Respuesta binaria normalizada del transporte."""

    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    transport: str


class EurLexHttpTransport:
    """Transporte oficial EUR-Lex con Cellar como ruta primaria."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        attempts: int = 3,
        backoff_seconds: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        urlopen_fn: Callable[..., object] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        timeout = float(
            timeout_seconds
        )

        if timeout <= 0:
            raise ValueError(
                "EUR-Lex timeout debe ser > 0"
            )

        if (
            not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or attempts <= 0
        ):
            raise ValueError(
                "EUR-Lex attempts debe ser entero positivo"
            )

        backoff = float(
            backoff_seconds
        )

        if backoff < 0:
            raise ValueError(
                "EUR-Lex backoff debe ser >= 0"
            )

        agent = str(
            user_agent or ""
        ).strip()

        if not agent:
            raise ValueError(
                "EUR-Lex user_agent no puede estar vacío"
            )

        self._timeout_seconds = timeout
        self._attempts = attempts
        self._backoff_seconds = backoff
        self._user_agent = agent

        self._urlopen = (
            urlopen_fn
            if urlopen_fn is not None
            else urllib.request.urlopen
        )

        self._sleep = (
            sleep_fn
            if sleep_fn is not None
            else time.sleep
        )

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def backoff_seconds(self) -> float:
        return self._backoff_seconds

    @property
    def user_agent(self) -> str:
        return self._user_agent

    @staticmethod
    def _cellar_url(
        celex: str,
    ) -> str:
        encoded = urllib.parse.quote(
            normalize_celex(
                celex
            ),
            safe="",
        )

        return (
            CELLAR_CELEX_BASE
            + encoded
        )

    @staticmethod
    def _eurlex_content_url(
        celex: str,
    ) -> str:
        identifier = normalize_celex(
            celex
        )

        query = urllib.parse.urlencode(
            {
                "uri": (
                    f"CELEX:{identifier}"
                )
            }
        )

        return (
            f"{EUR_LEX_CONTENT_BASE}"
            f"?{query}"
        )

    @staticmethod
    def _eli_consolidated_url(
        consolidated_celex: str,
    ) -> str | None:
        """Construye ELI fechado para actos consolidados.

        Ejemplo:

            02024L1233-20240430

        pasa a:

            https://data.europa.eu/eli/
            dir/2024/1233/
            2024-04-30/spa/html

        Para tratados y tipos no cubiertos en V1 se devuelve None
        y se mantiene el fallback oficial por CELEX.
        """

        identifier = normalize_celex(
            consolidated_celex
        )

        if not identifier.startswith(
            "0"
        ):
            raise ValueError(
                "ELI consolidado requiere "
                "CELEX sector 0"
            )

        revision_date = (
            consolidated_revision_date(
                identifier
            )
        )

        if revision_date is None:
            return None

        base = identifier.rsplit(
            "-",
            1,
        )[0]

        # Los tratados usan /TXT y no siguen
        # el patrón ELI de reglamentos/directivas/decisiones.
        if "/" in base:
            return None

        if len(base) < 7:
            return None

        year = base[1:5]
        celex_type = base[5]
        number_raw = base[6:]

        if (
            not year.isdigit()
            or not number_raw.isdigit()
        ):
            return None

        eli_types = {
            "L": "dir",
            "R": "reg",
            "D": "dec",
        }

        eli_type = eli_types.get(
            celex_type
        )

        if eli_type is None:
            return None

        number = str(
            int(
                number_raw
            )
        )

        return (
            f"{ELI_BASE}/"
            f"{eli_type}/"
            f"{year}/"
            f"{number}/"
            f"{revision_date.isoformat()}/"
            "spa/html"
        )

    def _request_bytes(
        self,
        url: str,
        *,
        accept: str,
        language: str | None,
        transport_name: str,
    ) -> EurLexHttpResponse:
        headers = {
            "Accept": accept,
            "User-Agent": self._user_agent,
            "Accept-Max-Cs-Size": str(
                100 * 1024 * 1024
            ),
        }

        if language:
            headers[
                "Accept-Language"
            ] = language

        request = urllib.request.Request(
            url=url,
            method="GET",
            headers=headers,
        )

        last_error: BaseException | None = None

        for attempt in range(
            1,
            self._attempts + 1,
        ):
            try:
                with self._urlopen(
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

                    final_url = str(
                        response.geturl()
                    )

                    content_type = str(
                        response.headers.get(
                            "Content-Type",
                            "",
                        )
                        or ""
                    )

                    body = response.read()

                    if status == 404:
                        raise EurLexNotFoundError(
                            "EUR-Lex recurso no disponible "
                            f"por {transport_name}: {url}"
                        )

                    # Algunas superficies EUR-Lex responden 202
                    # mientras preparan la representación.
                    # Nunca debe aceptarse como documento jurídico.
                    if status == 202:
                        last_error = EurLexRepresentationPendingError(
                            "EUR-Lex representación aún no disponible "
                            f"(HTTP 202) por {transport_name}"
                        )

                    elif status != 200:
                        raise EurLexTransportError(
                            "EUR-Lex HTTP inesperado "
                            f"{status} por {transport_name}"
                        )

                    elif not body:
                        raise EurLexTransportError(
                            "EUR-Lex devolvió respuesta vacía "
                            f"por {transport_name}"
                        )

                    else:
                        return EurLexHttpResponse(
                            requested_url=url,
                            final_url=final_url,
                            status=status,
                            content_type=content_type,
                            body=body,
                            transport=transport_name,
                        )

            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise EurLexNotFoundError(
                        "EUR-Lex recurso no disponible "
                        f"por {transport_name}: {url}"
                    ) from exc

                last_error = exc

                if (
                    exc.code
                    not in _RETRYABLE_HTTP_STATUS
                ):
                    raise EurLexTransportError(
                        "EUR-Lex HTTP error "
                        f"{exc.code} por {transport_name}: "
                        f"{exc.reason}"
                    ) from exc

            except EurLexNotFoundError:
                raise

            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
            ) as exc:
                last_error = exc

            if attempt < self._attempts:
                self._sleep(
                    self._backoff_seconds
                    * attempt
                )

        if isinstance(
            last_error,
            EurLexRepresentationPendingError,
        ):
            raise last_error

        raise EurLexTransportError(
            "EUR-Lex agotó reintentos "
            f"por {transport_name}: "
            f"{type(last_error).__name__}: "
            f"{last_error}"
        ) from last_error

    def fetch_tree_notice(
        self,
        celex: str,
    ) -> EurLexHttpResponse:
        """Recupera notice XML estructurado desde Cellar."""

        return self._request_bytes(
            self._cellar_url(
                celex
            ),
            accept=(
                "application/xml;"
                "notice=tree"
            ),
            language=DEFAULT_LANGUAGE,
            transport_name="CELLAR_TREE",
        )

    def fetch_original_content(
        self,
        celex: str,
    ) -> EurLexHttpResponse:
        """Recupera expresión española del acto original.

        Cellar es primario. EUR-Lex HTML es fallback oficial.
        """

        identifier = normalize_celex(
            celex
        )

        try:
            return self._request_bytes(
                self._cellar_url(
                    identifier
                ),
                accept=(
                    "application/xhtml+xml,"
                    "text/html;q=0.9"
                ),
                language=DEFAULT_LANGUAGE,
                transport_name="CELLAR_CONTENT",
            )

        except EurLexNotFoundError:
            return self._request_bytes(
                self._eurlex_content_url(
                    identifier
                ),
                accept=(
                    "text/html,"
                    "application/xhtml+xml;q=0.9"
                ),
                language=None,
                transport_name="EUR_LEX_CONTENT",
            )

    def fetch_consolidated_content(
        self,
        consolidated_celex: str,
    ) -> EurLexHttpResponse:
        """Recupera una revisión consolidada española concreta.

        Prioridad:

        1. Cellar español.
        2. ELI fechado español.

        Para actos con ELI determinista, un 404 o un 202 persistente
        del ELI español NO autoriza a recuperar otra lengua ni una
        página genérica. Se informa que esa revisión no dispone de
        representación española utilizable.

        Los tipos sin ELI derivable (por ejemplo tratados) conservan
        como último fallback la consulta CELEX oficial.
        """

        identifier = normalize_celex(
            consolidated_celex
        )

        if not identifier.startswith(
            "0"
        ):
            raise ValueError(
                "Consolidated fetch requiere CELEX sector 0"
            )

        try:
            return self._request_bytes(
                self._cellar_url(
                    identifier
                ),
                accept=(
                    "application/xhtml+xml,"
                    "text/html;q=0.9"
                ),
                language=DEFAULT_LANGUAGE,
                transport_name=(
                    "CELLAR_CONSOLIDATED"
                ),
            )

        except EurLexNotFoundError:
            pass

        eli_url = (
            self._eli_consolidated_url(
                identifier
            )
        )

        if eli_url is not None:
            try:
                return self._request_bytes(
                    eli_url,
                    accept=(
                        "text/html,"
                        "application/xhtml+xml;q=0.9"
                    ),
                    language=None,
                    transport_name=(
                        "ELI_CONSOLIDATED"
                    ),
                )

            except (
                EurLexNotFoundError,
                EurLexRepresentationPendingError,
            ) as exc:
                raise (
                    EurLexConsolidatedRepresentationUnavailableError(
                        "EUR-Lex no ofrece representación "
                        "consolidada española utilizable para "
                        f"{identifier}"
                    )
                ) from exc

        # Solo para tipos para los que no sabemos construir
        # un ELI consolidado inequívoco.
        return self._request_bytes(
            self._eurlex_content_url(
                identifier
            ),
            accept=(
                "text/html,"
                "application/xhtml+xml;q=0.9"
            ),
            language=None,
            transport_name=(
                "EUR_LEX_CONSOLIDATED"
            ),
        )


    def fetch_original(
        self,
        original_celex: str,
    ) -> Mapping[str, object]:
        """Payload nativo para el futuro provider EUR_LEX."""

        identifier = normalize_celex(
            original_celex
        )

        if identifier.startswith(
            "0"
        ):
            raise ValueError(
                "EUR_LEX original no acepta sector 0"
            )

        metadata = self.fetch_tree_notice(
            identifier
        )

        content = self.fetch_original_content(
            identifier
        )

        return {
            "id": identifier,
            "metadata_xml": metadata.body,
            "metadata_final_url": (
                metadata.final_url
            ),
            "content_xhtml": content.body,
            "content_final_url": (
                content.final_url
            ),
            "content_transport": (
                content.transport
            ),
        }

    def resolve_latest_consolidated(
        self,
        original_celex: str,
    ) -> tuple[
        str,
        EurLexHttpResponse,
    ]:
        """Resuelve revisión sector 0 usando metadata real del original."""

        identifier = normalize_celex(
            original_celex
        )

        if identifier.startswith(
            "0"
        ):
            raise ValueError(
                "Resolver consolidado requiere acto original"
            )

        metadata = self.fetch_tree_notice(
            identifier
        )

        identifiers = (
            parse_tree_notice_identifiers(
                metadata.body
            )
        )

        consolidated = (
            select_latest_consolidated_celex(
                identifier,
                identifiers,
            )
        )

        if consolidated is None:
            raise EurLexNotFoundError(
                "EUR-Lex no expone revisión consolidada "
                f"para {identifier}"
            )

        return (
            consolidated,
            metadata,
        )

    def fetch_consolidated(
        self,
        original_celex: str,
    ) -> Mapping[str, object]:
        """Payload para EUR_LEX_CONSOLIDATED.

        La revisión seleccionada es la más reciente que realmente
        dispone de representación española utilizable.

        Una revisión posterior que afecte solo a otra lengua no
        desplaza artificialmente la versión española anterior.
        """

        identifier = normalize_celex(
            original_celex
        )

        if identifier.startswith(
            "0"
        ):
            raise ValueError(
                "EUR_LEX_CONSOLIDATED requiere acto original"
            )

        metadata = self.fetch_tree_notice(
            identifier
        )

        identifiers = (
            parse_tree_notice_identifiers(
                metadata.body
            )
        )

        candidates = (
            list_consolidated_celex_revisions(
                identifier,
                identifiers,
            )
        )

        if not candidates:
            raise EurLexNotFoundError(
                "EUR-Lex no expone revisiones consolidadas "
                f"para {identifier}"
            )

        unavailable: list[str] = []

        for consolidated in candidates:
            try:
                content = (
                    self.fetch_consolidated_content(
                        consolidated
                    )
                )

            except (
                EurLexConsolidatedRepresentationUnavailableError
            ):
                unavailable.append(
                    consolidated
                )
                continue

            return {
                "id": identifier,
                "consolidated_celex": (
                    consolidated
                ),
                "metadata_xml": metadata.body,
                "metadata_final_url": (
                    metadata.final_url
                ),
                "content_xhtml": content.body,
                "content_final_url": (
                    content.final_url
                ),
                "content_transport": (
                    content.transport
                ),
                "skipped_unavailable_revisions": (
                    tuple(
                        unavailable
                    )
                ),
            }

        raise (
            EurLexConsolidatedRepresentationUnavailableError(
                "EUR-Lex no dispone de ninguna "
                "revisión consolidada española utilizable "
                f"para {identifier}; candidatos="
                f"{tuple(candidates)}"
            )
        )

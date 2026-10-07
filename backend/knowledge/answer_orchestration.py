"""Orquestación provider-neutral de respuestas sobre Knowledge.

Capa de aplicación sobre ``KnowledgeQueryService`` (retrieval/provenance
existente). Responde SIEMPRE con uno de tres modos explícitos:

    SOURCE_BACKED
        referencia fuentes Knowledge recuperables, con procedencia
        estructurada y contexto temporal preservado. Nunca fabrica
        citas: ``citations`` son objetos ``KnowledgeProvenance`` reales
        producidos por ``KnowledgeQueryService``.

    INSUFFICIENT_EVIDENCE
        no hay evidencia recuperable para la consulta. Expone un
        motivo explícito y la evidencia concreta que falta. Nunca
        inventa una respuesta.

    INFERENCE_ONLY
        respuesta producida por un motor de inferencia externo, nunca
        por el corpus Knowledge. Requiere opt-in explícito
        (``allow_inference=True``) y un ``KnowledgeInferenceProvider``
        inyectado; siempre lleva un ``inference_disclaimer`` explícito
        y jamás incluye ``citations``, para que no pueda confundirse
        con una respuesta con respaldo documental.

Principios:

- este módulo NO invoca OpenAI, Claude ni ningún proveedor de IA
  concreto. ``KnowledgeInferenceProvider`` es únicamente el límite del
  contrato (puerto); su implementación de infraestructura vive, si
  llega a existir, fuera del dominio/aplicación Knowledge;
- no escribe en ``KnowledgeCatalog`` ni en revisiones de promoción:
  ``KnowledgeHumanReviewGateService`` sigue siendo la única vía para
  mutar DISCOVERED -> FOLLOWED y permanece fuera del alcance de este
  módulo;
- los tres modos son mutuamente excluyentes e inmutables una vez
  construidos: ``KnowledgeAnswer`` valida en ``__post_init__`` que cada
  modo cumple sus invariantes (p. ej. INFERENCE_ONLY nunca puede llevar
  ``citations``, SOURCE_BACKED nunca puede llevar
  ``inference_disclaimer``);
- sin SQL, red, UI ni IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from .query import (
    DEFAULT_SEARCH_LIMIT,
    KnowledgeProvenance,
    KnowledgeQueryService,
    KnowledgeSearchResult,
)
from .source_registry import normalize_source_key


INFERENCE_DISCLAIMER = (
    "Respuesta generada por inferencia externa, sin respaldo "
    "documental verificable en el corpus Knowledge. No constituye "
    "una respuesta con fuente jurídica/legal verificada y no debe "
    "tratarse como tal."
)


class KnowledgeAnswerMode(str, Enum):
    SOURCE_BACKED = "SOURCE_BACKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INFERENCE_ONLY = "INFERENCE_ONLY"


def _require_date(value: object, *, field_name: str) -> date:
    # datetime hereda de date: se rechaza explícitamente para evitar
    # ambigüedad horaria, igual que en KnowledgeQueryService.
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} debe ser datetime.date")

    return value


# ============================================================
# REQUEST
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeAnswerRequest:
    """Entrada provider-neutral de una pregunta dirigida a Knowledge."""

    query: str
    source_key: str | None = None
    as_of: date | None = None
    limit: int = DEFAULT_SEARCH_LIMIT

    # Opt-in explícito: sin esta bandera, el servicio nunca produce
    # INFERENCE_ONLY aunque exista un KnowledgeInferenceProvider
    # inyectado.
    allow_inference: bool = False

    def __post_init__(self) -> None:
        query = str(self.query or "").strip()

        if not query:
            raise ValueError(
                "KnowledgeAnswerRequest.query no puede estar vacío"
            )

        object.__setattr__(self, "query", query)

        if self.source_key is not None:
            object.__setattr__(
                self,
                "source_key",
                normalize_source_key(self.source_key),
            )

        if self.as_of is not None:
            object.__setattr__(
                self,
                "as_of",
                _require_date(self.as_of, field_name="as_of"),
            )

        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit < 1
        ):
            raise ValueError(
                "KnowledgeAnswerRequest.limit debe ser entero >= 1"
            )

        if not isinstance(self.allow_inference, bool):
            raise TypeError(
                "KnowledgeAnswerRequest.allow_inference debe ser bool"
            )


# ============================================================
# INFERENCE BOUNDARY (puerto, sin implementación concreta)
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeInferenceOutcome:
    """Resultado opaco de un motor de inferencia externo.

    Knowledge no conoce ni depende del proveedor concreto que lo
    produjo: ``engine_label`` es un identificador operativo libre
    (p. ej. ``"EXTERNAL_INFERENCE_ENGINE"``), nunca el nombre de un
    producto/SDK concreto dentro de un contrato de dominio.
    """

    content_text: str
    engine_label: str

    def __post_init__(self) -> None:
        content_text = str(self.content_text or "").strip()

        if not content_text:
            raise ValueError(
                "KnowledgeInferenceOutcome.content_text no puede "
                "estar vacío"
            )

        object.__setattr__(self, "content_text", content_text)

        engine_label = str(self.engine_label or "").strip()

        if not engine_label:
            raise ValueError(
                "KnowledgeInferenceOutcome.engine_label no puede "
                "estar vacío"
            )

        object.__setattr__(self, "engine_label", engine_label)


@runtime_checkable
class KnowledgeInferenceProvider(Protocol):
    """Puerto provider-neutral para respuestas NO corpus-backed.

    Ninguna implementación concreta (OpenAI, Claude u otro proveedor)
    pertenece al dominio/aplicación Knowledge. Esta fase define
    exclusivamente el límite del contrato; invocar un proveedor real
    es responsabilidad de un adaptador de infraestructura externo,
    fuera de este módulo.
    """

    def infer(
        self,
        request: KnowledgeAnswerRequest,
    ) -> KnowledgeInferenceOutcome:
        ...


# ============================================================
# ANSWER
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeAnswer:
    """Respuesta provider-neutral con modo explícito e invariantes.

    Las validaciones de ``__post_init__`` son la garantía estructural
    de las reglas de negocio: ningún llamador puede construir un
    INFERENCE_ONLY que aparente ser SOURCE_BACKED, ni un
    INSUFFICIENT_EVIDENCE con contenido fabricado.
    """

    mode: KnowledgeAnswerMode

    query: str
    source_key: str | None
    as_of: date | None

    content_text: str = ""

    # Procedencia estructurada real; nunca sintetizada. Vacío salvo en
    # SOURCE_BACKED.
    citations: tuple[KnowledgeProvenance, ...] = ()

    # "AS_OF" o "LATEST_KNOWN"; preserva el contexto temporal de la
    # búsqueda subyacente. Vacío fuera de SOURCE_BACKED.
    temporal_basis: str = ""

    # Evidencia concreta identificada como ausente. Obligatorio y no
    # vacío en INSUFFICIENT_EVIDENCE.
    missing_evidence: tuple[str, ...] = ()

    reason: str = ""

    # Separación explícita obligatoria en INFERENCE_ONLY; vacío en los
    # demás modos.
    inference_disclaimer: str = ""
    engine_label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.mode, KnowledgeAnswerMode):
            raise TypeError(
                "KnowledgeAnswer.mode debe ser KnowledgeAnswerMode"
            )

        if self.mode is KnowledgeAnswerMode.SOURCE_BACKED:
            self._validate_source_backed()
        elif self.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE:
            self._validate_insufficient_evidence()
        else:
            self._validate_inference_only()

    def _validate_source_backed(self) -> None:
        if not self.citations:
            raise ValueError(
                "SOURCE_BACKED debe referenciar al menos una fuente "
                "Knowledge recuperable (citations vacío)"
            )

        for citation in self.citations:
            if not isinstance(citation, KnowledgeProvenance):
                raise TypeError(
                    "SOURCE_BACKED.citations debe contener solo "
                    "KnowledgeProvenance"
                )

        if not self.content_text.strip():
            raise ValueError(
                "SOURCE_BACKED no puede tener content_text vacío"
            )

        if self.inference_disclaimer or self.engine_label:
            raise ValueError(
                "SOURCE_BACKED no puede llevar marcas de inferencia"
            )

        if self.missing_evidence:
            raise ValueError(
                "SOURCE_BACKED no puede declarar missing_evidence"
            )

    def _validate_insufficient_evidence(self) -> None:
        if self.content_text.strip():
            raise ValueError(
                "INSUFFICIENT_EVIDENCE no puede fabricar content_text"
            )

        if self.citations:
            raise ValueError(
                "INSUFFICIENT_EVIDENCE no puede llevar citations"
            )

        if self.inference_disclaimer or self.engine_label:
            raise ValueError(
                "INSUFFICIENT_EVIDENCE no puede llevar marcas de "
                "inferencia"
            )

        if not self.reason.strip():
            raise ValueError(
                "INSUFFICIENT_EVIDENCE requiere reason explícito"
            )

        if not self.missing_evidence:
            raise ValueError(
                "INSUFFICIENT_EVIDENCE debe identificar la evidencia "
                "ausente"
            )

    def _validate_inference_only(self) -> None:
        if self.citations:
            raise ValueError(
                "INFERENCE_ONLY no puede llevar citations: no es una "
                "respuesta corpus-backed y nunca debe aparentarlo"
            )

        if not self.content_text.strip():
            raise ValueError(
                "INFERENCE_ONLY no puede tener content_text vacío"
            )

        if not self.inference_disclaimer.strip():
            raise ValueError(
                "INFERENCE_ONLY requiere inference_disclaimer "
                "explícito"
            )

        if not self.engine_label.strip():
            raise ValueError(
                "INFERENCE_ONLY requiere engine_label explícito"
            )

        if self.missing_evidence:
            raise ValueError(
                "INFERENCE_ONLY no declara missing_evidence: use "
                "INSUFFICIENT_EVIDENCE para esa afirmación"
            )

    @property
    def is_source_backed(self) -> bool:
        return self.mode is KnowledgeAnswerMode.SOURCE_BACKED


# ============================================================
# SERVICE
# ============================================================


class KnowledgeAnswerOrchestrationService:
    """Orquesta respuestas provider-neutral sobre Knowledge.

    Depende únicamente de ``KnowledgeQueryService`` (retrieval y
    procedencia ya existentes) y, opcionalmente, de un
    ``KnowledgeInferenceProvider`` inyectado por el llamador. No
    conoce SQL, HTTP, UI ni un proveedor de IA concreto.

    Sin evidencia recuperable:

    - si ``request.allow_inference`` es ``True`` y hay un
      ``inference_provider`` inyectado, produce INFERENCE_ONLY;
    - en cualquier otro caso produce INSUFFICIENT_EVIDENCE. Nunca
      fabrica una respuesta SOURCE_BACKED ni INFERENCE_ONLY por
      defecto.

    Este servicio no escribe en ``KnowledgeCatalog`` ni en revisiones
    de promoción: ``KnowledgeHumanReviewGateService`` sigue siendo la
    única vía para mutar DISCOVERED -> FOLLOWED y permanece fuera del
    alcance de este módulo.
    """

    def __init__(
        self,
        query_service: KnowledgeQueryService,
        inference_provider: KnowledgeInferenceProvider | None = None,
    ) -> None:
        if not isinstance(query_service, KnowledgeQueryService):
            raise TypeError(
                "query_service debe ser KnowledgeQueryService"
            )

        if (
            inference_provider is not None
            and not isinstance(
                inference_provider, KnowledgeInferenceProvider
            )
        ):
            raise TypeError(
                "inference_provider debe implementar "
                "KnowledgeInferenceProvider"
            )

        self._query_service = query_service
        self._inference_provider = inference_provider

    def answer(
        self,
        request: KnowledgeAnswerRequest,
    ) -> KnowledgeAnswer:
        if not isinstance(request, KnowledgeAnswerRequest):
            raise TypeError(
                "request debe ser KnowledgeAnswerRequest"
            )

        search_result = self._query_service.search(
            request.query,
            source_key=request.source_key,
            as_of=request.as_of,
            limit=request.limit,
        )

        if search_result.hits:
            return self._source_backed(request, search_result)

        return self._without_evidence(request, search_result)

    @staticmethod
    def _source_backed(
        request: KnowledgeAnswerRequest,
        search_result: KnowledgeSearchResult,
    ) -> KnowledgeAnswer:
        citations = tuple(
            hit.provenance for hit in search_result.hits
        )

        # Nunca prosa generada: concatenación de extractos reales ya
        # producidos por KnowledgeQueryService.search (matched_text),
        # con fallback al título/identificador real si el extracto
        # está vacío.
        content_text = "\n\n".join(
            hit.matched_text
            or hit.provenance.document_title
            or hit.provenance.external_id
            for hit in search_result.hits
        )

        return KnowledgeAnswer(
            mode=KnowledgeAnswerMode.SOURCE_BACKED,
            query=request.query,
            source_key=request.source_key,
            as_of=request.as_of,
            content_text=content_text,
            citations=citations,
            temporal_basis=search_result.temporal_basis,
            reason=(
                "Resuelto a partir de evidencia recuperable en "
                "Knowledge."
            ),
        )

    def _without_evidence(
        self,
        request: KnowledgeAnswerRequest,
        search_result: KnowledgeSearchResult,
    ) -> KnowledgeAnswer:
        missing_evidence = [
            "Sin coincidencias recuperables para la consulta "
            f"'{request.query}'"
            + (
                f" en la fuente {request.source_key}"
                if request.source_key
                else ""
            )
        ]

        missing_evidence.extend(
            "Bloque excluido por evidencia temporal insuficiente: "
            f"{block_key} ({status})"
            for block_key, status in search_result.excluded_blocks
        )

        if not request.allow_inference:
            return KnowledgeAnswer(
                mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
                query=request.query,
                source_key=request.source_key,
                as_of=request.as_of,
                missing_evidence=tuple(missing_evidence),
                reason=(
                    "No existe evidencia recuperable en Knowledge "
                    "para esta consulta; no se fabrica una respuesta."
                ),
            )

        if self._inference_provider is None:
            missing_evidence.append(
                "No hay un KnowledgeInferenceProvider configurado: "
                "no puede emitirse INFERENCE_ONLY"
            )

            return KnowledgeAnswer(
                mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
                query=request.query,
                source_key=request.source_key,
                as_of=request.as_of,
                missing_evidence=tuple(missing_evidence),
                reason=(
                    "Se solicitó inferencia pero no hay un motor de "
                    "inferencia configurado; no se fabrica una "
                    "respuesta."
                ),
            )

        outcome = self._inference_provider.infer(request)

        return KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INFERENCE_ONLY,
            query=request.query,
            source_key=request.source_key,
            as_of=request.as_of,
            content_text=outcome.content_text,
            reason=(
                "No se encontró evidencia recuperable en Knowledge; "
                "se solicitó explícitamente una respuesta por "
                "inferencia, separada del corpus documental."
            ),
            inference_disclaimer=INFERENCE_DISCLAIMER,
            engine_label=outcome.engine_label,
        )

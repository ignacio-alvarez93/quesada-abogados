"""Diagnóstico determinista de suficiencia de evidencia sobre KnowledgeAnswer.

Construye sobre ``KnowledgeAnswerOrchestrationService`` (``answer_orchestration.py``)
y reutiliza en exclusiva los contratos de retrieval/query ya existentes
(``KnowledgeQueryService.get_document`` / ``get_document_validity``) y el
catálogo gobernado (``KnowledgeCatalogRepository``). No introduce una ruta
de acceso nueva a los datos: solo interpreta lo que esos contratos ya
exponen.

Qué responde:

    ¿cuántas fuentes respaldan esta respuesta y qué identidad tienen?
    ¿qué tan diversas son (misma fuente/proveedor o varias)?
    ¿qué norma/bloque cubren realmente frente a la estructura completa?
    ¿sigue vigente la fuente, según evidencia estructurada?
    ¿qué evidencia falta o no pudo resolverse, y por qué?
    ¿esta evidencia es cruda (retrieval), ya pasó por revisión humana
    (Human Review Gate / catálogo), o es inferencia externa?

Principios:

- determinista: misma ``KnowledgeAnswer`` + mismo estado de los
  repositorios inyectados siempre produce el mismo informe. No hay
  aleatoriedad, reloj de sistema ni llamadas a red/IA;
- nunca produce un porcentaje ni una puntuación de confianza. La
  clasificación (``KnowledgeEvidenceSufficiencyLevel``) es una categoría
  derivada de conteos reales (número de identidades documentales
  distintas citadas), nunca una heurística de un proveedor de IA
  concreto;
- distingue explícitamente tres cosas que nunca deben confundirse:
  evidencia cruda recuperada del corpus (``is_raw_evidence``), el
  estado de revisión humana declarado por el catálogo gobernado
  (``human_review_status``, vía ``KnowledgeCatalogRepository``, de
  solo lectura) y la inferencia externa (``is_inference``);
- no escribe en ``KnowledgeCatalog`` ni en revisiones de promoción:
  ``KnowledgeHumanReviewGateService`` sigue siendo la única vía para
  mutar DISCOVERED -> FOLLOWED. Este módulo solo lee el catálogo;
- "donde esté disponible": validez temporal y cobertura documental
  dependen de capacidades opcionales de los repositorios inyectados
  en ``KnowledgeQueryService``. Sin ellas, se expone explícitamente
  que no pudieron resolverse, nunca se fabrica un resultado positivo;
- sin SQL, red, UI ni IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .answer_orchestration import KnowledgeAnswer, KnowledgeAnswerMode
from .catalog import KnowledgeCatalogTier
from .catalog_repository import KnowledgeCatalogRepository
from .query import KnowledgeProvenance, KnowledgeQueryService
from .validity import KnowledgeDocumentValidity, KnowledgeValidityStatus


class KnowledgeEvidenceSufficiencyLevel(str, Enum):
    """Categoría determinista, nunca un porcentaje de confianza.

    Deriva exclusivamente de conteos reales de identidades documentales
    distintas citadas en ``KnowledgeAnswer.citations``.
    """

    # INSUFFICIENT_EVIDENCE: no hay citas.
    NO_EVIDENCE = "NO_EVIDENCE"

    # SOURCE_BACKED respaldado por una única identidad documental.
    SINGLE_SOURCE = "SINGLE_SOURCE"

    # SOURCE_BACKED respaldado por dos o más identidades documentales
    # distintas.
    CORROBORATED = "CORROBORATED"

    # INFERENCE_ONLY: por definición no hay evidencia Knowledge que
    # evaluar.
    NOT_EVIDENCE_BASED = "NOT_EVIDENCE_BASED"


@dataclass(frozen=True, slots=True)
class KnowledgeAuthoritativeSourceIdentity:
    """Identidad documental única citada, con su autoridad declarada.

    ``authority`` procede literalmente de ``KnowledgeProvenance.authority``
    (a su vez del registro canónico de fuentes); nunca se reclasifica
    aquí.
    """

    document_canonical_key: str
    source_key: str
    external_id: str
    provider: str
    authority: str


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentCoverage:
    """Cobertura de bloques citados frente a la estructura completa.

    ``resolved=False`` significa que la estructura completa del
    documento no pudo recuperarse para comparar: no es "cobertura
    cero", es "cobertura desconocida".
    """

    document_canonical_key: str

    cited_block_ids: tuple[str, ...] = ()
    total_block_ids: tuple[str, ...] = ()

    resolved: bool = False

    reason: str = ""

    @property
    def cited_block_count(self) -> int:
        return len(self.cited_block_ids)

    @property
    def total_block_count(self) -> int:
        return len(self.total_block_ids)


@dataclass(frozen=True, slots=True)
class KnowledgeHumanReviewStatus:
    """Estado de revisión humana (catálogo gobernado) de una identidad.

    ``is_reviewed is None`` significa "desconocido" (no se inyectó
    ``KnowledgeCatalogRepository`` o la identidad no está catalogada),
    nunca se interpreta como "no revisado".
    """

    document_canonical_key: str

    is_reviewed: bool | None = None
    tier: str = ""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeEvidenceSufficiencyReport:
    """Diagnóstico determinista de suficiencia de evidencia.

    No es una respuesta: es metadata sobre una ``KnowledgeAnswer`` ya
    construida por ``KnowledgeAnswerOrchestrationService``.
    """

    mode: KnowledgeAnswerMode
    level: KnowledgeEvidenceSufficiencyLevel

    authoritative_sources: tuple[
        KnowledgeAuthoritativeSourceIdentity, ...
    ] = ()

    # Diversidad real de fuentes/proveedores, no un índice sintético.
    distinct_source_keys: tuple[str, ...] = ()
    distinct_providers: tuple[str, ...] = ()

    document_coverage: tuple[KnowledgeDocumentCoverage, ...] = ()
    temporal_validity: tuple[KnowledgeDocumentValidity, ...] = ()
    human_review_status: tuple[KnowledgeHumanReviewStatus, ...] = ()

    # Evidencia ausente o no resoluble; nunca fabricada. Para
    # INSUFFICIENT_EVIDENCE es ``KnowledgeAnswer.missing_evidence``
    # verbatim; para SOURCE_BACKED son huecos de cobertura/validez
    # detectados en los repositorios inyectados.
    unresolved_reasons: tuple[str, ...] = ()

    # Mutuamente excluyentes: distinguen evidencia cruda de corpus,
    # revisión humana (ver human_review_status) e inferencia externa.
    is_raw_evidence: bool = False
    is_inference: bool = False

    # True solo si cada hallazgo remite a un KnowledgeProvenance real
    # ya presente en KnowledgeAnswer.citations (nunca a un dato
    # sintetizado por este módulo).
    provenance_linked: bool = False

    reason: str = ""

    @property
    def source_count(self) -> int:
        return len(self.authoritative_sources)

    @property
    def distinct_source_key_count(self) -> int:
        return len(self.distinct_source_keys)

    @property
    def distinct_provider_count(self) -> int:
        return len(self.distinct_providers)


# ============================================================
# SERVICE
# ============================================================


class KnowledgeEvidenceSufficiencyService:
    """Evalúa suficiencia de evidencia sobre un ``KnowledgeAnswer``.

    Depende únicamente de ``KnowledgeQueryService`` (retrieval y
    procedencia ya existentes) y, opcionalmente, de un
    ``KnowledgeCatalogRepository`` de solo lectura para exponer el
    estado de revisión humana (Human Review Gate). No escribe en
    ningún repositorio.
    """

    def __init__(
        self,
        *,
        query_service: KnowledgeQueryService,
        catalog_repository: KnowledgeCatalogRepository | None = None,
    ) -> None:
        if not isinstance(query_service, KnowledgeQueryService):
            raise TypeError(
                "query_service debe ser KnowledgeQueryService"
            )

        if (
            catalog_repository is not None
            and not isinstance(
                catalog_repository, KnowledgeCatalogRepository
            )
        ):
            raise TypeError(
                "catalog_repository debe implementar "
                "KnowledgeCatalogRepository"
            )

        self._query_service = query_service
        self._catalog_repository = catalog_repository

    def evaluate(
        self,
        answer: KnowledgeAnswer,
    ) -> KnowledgeEvidenceSufficiencyReport:
        if not isinstance(answer, KnowledgeAnswer):
            raise TypeError("answer debe ser KnowledgeAnswer")

        if answer.mode is KnowledgeAnswerMode.INFERENCE_ONLY:
            return self._not_evidence_based(answer)

        if answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE:
            return self._no_evidence(answer)

        return self._source_backed(answer)

    @staticmethod
    def _not_evidence_based(
        answer: KnowledgeAnswer,
    ) -> KnowledgeEvidenceSufficiencyReport:
        return KnowledgeEvidenceSufficiencyReport(
            mode=answer.mode,
            level=(
                KnowledgeEvidenceSufficiencyLevel.NOT_EVIDENCE_BASED
            ),
            unresolved_reasons=(
                "La respuesta es INFERENCE_ONLY: no procede de "
                "evidencia recuperable en Knowledge, por lo que la "
                "suficiencia evidencial no aplica.",
            ),
            is_raw_evidence=False,
            is_inference=True,
            provenance_linked=False,
            reason=(
                "INFERENCE_ONLY nunca lleva citations de Knowledge: "
                "evaluar su suficiencia evidencial no tiene sentido "
                "por definición."
            ),
        )

    @staticmethod
    def _no_evidence(
        answer: KnowledgeAnswer,
    ) -> KnowledgeEvidenceSufficiencyReport:
        return KnowledgeEvidenceSufficiencyReport(
            mode=answer.mode,
            level=KnowledgeEvidenceSufficiencyLevel.NO_EVIDENCE,
            unresolved_reasons=answer.missing_evidence,
            is_raw_evidence=False,
            is_inference=False,
            provenance_linked=False,
            reason=answer.reason,
        )

    def _source_backed(
        self,
        answer: KnowledgeAnswer,
    ) -> KnowledgeEvidenceSufficiencyReport:
        citations = answer.citations

        identity_by_key: dict[str, tuple[str, str]] = {}

        for citation in citations:
            identity_by_key.setdefault(
                citation.document_canonical_key,
                (citation.source_key, citation.external_id),
            )

        document_keys = tuple(sorted(identity_by_key))

        citations_by_key: dict[
            str, tuple[KnowledgeProvenance, ...]
        ] = {
            key: tuple(
                citation
                for citation in citations
                if citation.document_canonical_key == key
            )
            for key in document_keys
        }

        authoritative_sources = tuple(
            self._authoritative_identity(
                key, citations_by_key[key][0]
            )
            for key in document_keys
        )

        document_coverage = tuple(
            self._document_coverage(key, citations_by_key[key])
            for key in document_keys
        )

        temporal_validity = tuple(
            self._query_service.get_document_validity(*identity_by_key[key])
            for key in document_keys
        )

        human_review_status = tuple(
            self._human_review_status(key, *identity_by_key[key])
            for key in document_keys
        )

        unresolved_reasons = tuple(
            coverage.reason
            for coverage in document_coverage
            if not coverage.resolved
        ) + tuple(
            validity.reason
            for validity in temporal_validity
            if validity.status is KnowledgeValidityStatus.UNKNOWN
        )

        distinct_source_keys = tuple(
            sorted({citation.source_key for citation in citations})
        )

        distinct_providers = tuple(
            sorted({citation.provider for citation in citations})
        )

        level = (
            KnowledgeEvidenceSufficiencyLevel.CORROBORATED
            if len(document_keys) > 1
            else KnowledgeEvidenceSufficiencyLevel.SINGLE_SOURCE
        )

        return KnowledgeEvidenceSufficiencyReport(
            mode=answer.mode,
            level=level,
            authoritative_sources=authoritative_sources,
            distinct_source_keys=distinct_source_keys,
            distinct_providers=distinct_providers,
            document_coverage=document_coverage,
            temporal_validity=temporal_validity,
            human_review_status=human_review_status,
            unresolved_reasons=unresolved_reasons,
            is_raw_evidence=True,
            is_inference=False,
            provenance_linked=True,
            reason=(
                "Evidencia citada directamente desde retrieval sobre "
                "el corpus Knowledge (KnowledgeQueryService.search): "
                "refleja el catálogo tal como existe, no una "
                "aprobación editorial del Human Review Gate."
            ),
        )

    @staticmethod
    def _authoritative_identity(
        document_key: str,
        citation: KnowledgeProvenance,
    ) -> KnowledgeAuthoritativeSourceIdentity:
        return KnowledgeAuthoritativeSourceIdentity(
            document_canonical_key=document_key,
            source_key=citation.source_key,
            external_id=citation.external_id,
            provider=citation.provider,
            authority=citation.authority,
        )

    def _document_coverage(
        self,
        document_key: str,
        citations: tuple[KnowledgeProvenance, ...],
    ) -> KnowledgeDocumentCoverage:
        cited_block_ids = tuple(
            sorted(
                {
                    citation.block_id
                    for citation in citations
                    if citation.block_id
                }
            )
        )

        source_key = citations[0].source_key
        external_id = citations[0].external_id

        record = self._query_service.get_document(
            source_key, external_id
        )

        if record is None:
            return KnowledgeDocumentCoverage(
                document_canonical_key=document_key,
                cited_block_ids=cited_block_ids,
                resolved=False,
                reason=(
                    "No pudo recuperarse la estructura completa de "
                    f"{document_key} para calcular cobertura de "
                    "bloques: no se asume cobertura total ni parcial."
                ),
            )

        return KnowledgeDocumentCoverage(
            document_canonical_key=document_key,
            cited_block_ids=cited_block_ids,
            total_block_ids=record.block_ids,
            resolved=True,
        )

    def _human_review_status(
        self,
        document_key: str,
        source_key: str,
        external_id: str,
    ) -> KnowledgeHumanReviewStatus:
        if self._catalog_repository is None:
            return KnowledgeHumanReviewStatus(
                document_canonical_key=document_key,
                is_reviewed=None,
                reason=(
                    "No se inyectó KnowledgeCatalogRepository: el "
                    "estado de revisión humana (Human Review Gate) de "
                    f"{document_key} es desconocido, no se asume."
                ),
            )

        entry = self._catalog_repository.get_entry(
            source_key, external_id
        )

        if entry is None:
            return KnowledgeHumanReviewStatus(
                document_canonical_key=document_key,
                is_reviewed=None,
                reason=(
                    f"{document_key} no está en KnowledgeCatalog: no "
                    "se conoce su estado de revisión humana."
                ),
            )

        is_reviewed = entry.tier in (
            KnowledgeCatalogTier.CORE,
            KnowledgeCatalogTier.FOLLOWED,
        )

        return KnowledgeHumanReviewStatus(
            document_canonical_key=document_key,
            is_reviewed=is_reviewed,
            tier=entry.tier.value,
            reason=(
                f"KnowledgeCatalog tier={entry.tier.value}: "
                + (
                    "identidad vigilada (CORE/FOLLOWED), consistente "
                    "con una promoción ya decidida vía catálogo "
                    "gobernado."
                    if is_reviewed
                    else "DISCOVERED: evidencia cruda, aún sin pasar "
                    "por el Human Review Gate hacia FOLLOWED."
                )
            ),
        )

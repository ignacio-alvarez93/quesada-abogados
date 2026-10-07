from datetime import date

import pytest

from backend.knowledge import (
    INFERENCE_DISCLAIMER,
    KnowledgeAnswerOrchestrationService,
    KnowledgeAnswerRequest,
    KnowledgeBlock,
    KnowledgeCatalogTier,
    KnowledgeEvidenceSufficiencyLevel,
    KnowledgeEvidenceSufficiencyService,
    KnowledgeInferenceOutcome,
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeStructuredDocument,
    KnowledgeValidityStatus,
    build_knowledge_block_version,
    build_knowledge_catalog_entry,
    build_knowledge_item,
)
from backend.knowledge.boe_consolidated.validity import (
    resolve_boe_consolidated_validity,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)


CELEX = "32016R0679"
BOE_CONSOLIDATED_ID = "BOE-A-2024-24099"
EUR_LEX_PLAIN_ID = "32016L0680"


# ------------------------------------------------------------
# Dobles en memoria (mismo patrón que
# test_knowledge_answer_orchestration.py).
# ------------------------------------------------------------


class MemoryStructures:
    def __init__(self, *documents):
        self._documents = {
            (d.source_key, d.external_id): d for d in documents
        }

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        return self._documents.get(
            (source_key.strip().upper(), external_id.strip())
        )

    def persist(self, document):
        raise NotImplementedError

    def list_document_identities(self, source_key=None):
        return tuple(
            sorted(
                key
                for key in self._documents
                if source_key is None or key[0] == source_key
            )
        )


class EmptyStructures:
    """Repositorio estructural sin documentos: simula capacidad ausente."""

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        return None

    def persist(self, document):
        raise NotImplementedError

    def list_document_identities(self, source_key=None):
        return ()


class MemoryItems:
    def __init__(self, *items):
        self._items = {i.source_identity: i for i in items}

    def initialize_schema(self):
        pass

    def get_current(self, source_key, external_id):
        return self._items.get((source_key, external_id))

    def persist(self, item, decision):
        raise NotImplementedError

    def list_revisions(self, source_key, external_id):
        return ()


def _v(source, external_id, block_id, position, text, eff, current, **kw):
    return build_knowledge_block_version(
        source_key=source,
        external_id=external_id,
        block_id=block_id,
        version_position=position,
        content_text=text,
        effective_from=eff,
        is_current=current,
        **kw,
    )


def _doc(source, external_id, blocks, versions):
    return KnowledgeStructuredDocument(
        source_key=source,
        external_id=external_id,
        blocks=tuple(
            KnowledgeBlock(
                source_key=source,
                external_id=external_id,
                block_id=block_id,
                position=position,
                title=title,
                canonical_uri=f"https://example.test/{block_id}",
            )
            for block_id, position, title in blocks
        ),
        versions=tuple(versions),
    )


def _eu_consolidated_document():
    s, x = "EUR_LEX_CONSOLIDATED", CELEX

    return _doc(
        s,
        x,
        [("art1", 1, "Artículo 1"), ("art2", 2, "Artículo 2")],
        [
            _v(s, x, "art1", 1, "Plazo ampliado para presentar alegaciones.", date(2018, 5, 25), True),
            _v(s, x, "art2", 1, "Definiciones estables.", date(2016, 5, 24), True),
        ],
    )


def _eu_consolidated_item():
    return build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id=CELEX,
        title="Reglamento General de Protección de Datos",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        canonical_uri="https://eur-lex.europa.eu/eli/reg/2016/679",
        source_revision="rev-1",
        language="es",
    )


def _eu_plain_document():
    s, x = "EUR_LEX", EUR_LEX_PLAIN_ID

    return _doc(
        s,
        x,
        [("art1", 1, "Artículo 1")],
        [
            _v(s, x, "art1", 1, "Plazo de transposición de dos años.", date(2016, 5, 24), True),
        ],
    )


def _eu_plain_item():
    return build_knowledge_item(
        source_key="EUR_LEX",
        external_id=EUR_LEX_PLAIN_ID,
        title="Directiva de protección de datos en materia penal",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        source_revision="rev-1",
        language="es",
    )


def _boe_consolidated_document():
    s, x = "BOE_CONSOLIDATED", BOE_CONSOLIDATED_ID

    return _doc(
        s,
        x,
        [("a1", 1, "Articulo 1")],
        [
            _v(s, x, "a1", 1, "Plazo administrativo de un mes.", date(2024, 1, 1), True),
        ],
    )


def _boe_consolidated_item():
    return build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id=BOE_CONSOLIDATED_ID,
        title="Real Decreto 1155/2024",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        source_revision="rev-1",
        metadata={
            "estatus_derogacion": "N",
            "estatus_anulacion": "N",
            "vigencia_agotada": "N",
            "fecha_vigencia": "20250520",
        },
    )


def _combined_query_service():
    return KnowledgeQueryService(
        MemoryStructures(
            _eu_consolidated_document(),
            _eu_plain_document(),
            _boe_consolidated_document(),
        ),
        MemoryItems(
            _eu_consolidated_item(),
            _eu_plain_item(),
            _boe_consolidated_item(),
        ),
        validity_resolvers={
            "BOE_CONSOLIDATED": resolve_boe_consolidated_validity,
        },
    )


def _single_source_query_service():
    return KnowledgeQueryService(
        MemoryStructures(_eu_consolidated_document()),
        MemoryItems(_eu_consolidated_item()),
    )


class FakeInferenceProvider:
    def __init__(self, content_text="Respuesta de inferencia.", engine_label="TEST_ENGINE"):
        self._content_text = content_text
        self._engine_label = engine_label

    def infer(self, request):
        return KnowledgeInferenceOutcome(
            content_text=self._content_text,
            engine_label=self._engine_label,
        )


def _answer(query_service, *, query, as_of=None, allow_inference=False, inference_provider=None):
    orchestrator = KnowledgeAnswerOrchestrationService(
        query_service, inference_provider=inference_provider
    )

    return orchestrator.answer(
        KnowledgeAnswerRequest(
            query=query, as_of=as_of, allow_inference=allow_inference
        )
    )


def _find(entries, document_canonical_key):
    return next(
        entry
        for entry in entries
        if entry.document_canonical_key == document_canonical_key
    )


def _find_validity(entries, source_key, external_id):
    return next(
        entry
        for entry in entries
        if entry.source_key == source_key and entry.external_id == external_id
    )


# ------------------------------------------------------------
# NO_EVIDENCE / NOT_EVIDENCE_BASED
# ------------------------------------------------------------


def test_insufficient_evidence_yields_no_evidence_level():
    query_service = _single_source_query_service()
    answer = _answer(query_service, query="xenomorfo inexistente")

    service = KnowledgeEvidenceSufficiencyService(query_service=query_service)
    report = service.evaluate(answer)

    assert report.level is KnowledgeEvidenceSufficiencyLevel.NO_EVIDENCE
    assert report.source_count == 0
    assert report.authoritative_sources == ()
    assert report.unresolved_reasons == answer.missing_evidence
    assert report.is_raw_evidence is False
    assert report.is_inference is False
    assert report.provenance_linked is False


def test_inference_only_yields_not_evidence_based_level():
    query_service = _single_source_query_service()
    provider = FakeInferenceProvider()

    answer = _answer(
        query_service,
        query="xenomorfo inexistente",
        allow_inference=True,
        inference_provider=provider,
    )

    service = KnowledgeEvidenceSufficiencyService(query_service=query_service)
    report = service.evaluate(answer)

    assert report.level is KnowledgeEvidenceSufficiencyLevel.NOT_EVIDENCE_BASED
    assert report.source_count == 0
    assert report.is_raw_evidence is False
    assert report.is_inference is True
    assert report.provenance_linked is False
    assert report.unresolved_reasons
    assert answer.inference_disclaimer == INFERENCE_DISCLAIMER


# ------------------------------------------------------------
# SOURCE_BACKED: fuente única
# ------------------------------------------------------------


def test_single_document_citation_is_single_source_level():
    query_service = _single_source_query_service()
    answer = _answer(query_service, query="plazo ampliado", as_of=date(2018, 5, 25))

    service = KnowledgeEvidenceSufficiencyService(query_service=query_service)
    report = service.evaluate(answer)

    assert report.level is KnowledgeEvidenceSufficiencyLevel.SINGLE_SOURCE
    assert report.source_count == 1
    assert report.is_raw_evidence is True
    assert report.is_inference is False
    assert report.provenance_linked is True

    identity = report.authoritative_sources[0]
    assert identity.source_key == "EUR_LEX_CONSOLIDATED"
    assert identity.external_id == CELEX
    assert identity.provider == "EUR_LEX"
    assert identity.authority == "OFFICIAL_SECONDARY"

    coverage = report.document_coverage[0]
    assert coverage.resolved is True
    assert coverage.cited_block_ids == ("art1",)
    assert set(coverage.total_block_ids) == {"art1", "art2"}

    validity = report.temporal_validity[0]
    assert validity.status is KnowledgeValidityStatus.UNKNOWN

    review = report.human_review_status[0]
    assert review.is_reviewed is None
    assert "KnowledgeCatalogRepository" in review.reason

    assert any(
        "resolutor" in reason for reason in report.unresolved_reasons
    )


def test_evaluate_is_deterministic_across_calls():
    query_service = _single_source_query_service()
    answer = _answer(query_service, query="plazo ampliado", as_of=date(2018, 5, 25))

    service = KnowledgeEvidenceSufficiencyService(query_service=query_service)

    assert service.evaluate(answer) == service.evaluate(answer)


# ------------------------------------------------------------
# SOURCE_BACKED: corroboración / diversidad / revisión humana
# ------------------------------------------------------------


def _catalog_repository(tmp_path):
    repository = SQLiteKnowledgeCatalogRepository(tmp_path / "catalog.db")
    repository.initialize_schema()

    repository.upsert(
        build_knowledge_catalog_entry(
            source_key="BOE_CONSOLIDATED",
            external_id=BOE_CONSOLIDATED_ID,
            tier=KnowledgeCatalogTier.FOLLOWED,
            watch_updates=True,
        )
    )

    repository.upsert(
        build_knowledge_catalog_entry(
            source_key="EUR_LEX_CONSOLIDATED",
            external_id=CELEX,
            tier=KnowledgeCatalogTier.DISCOVERED,
            watch_updates=False,
        )
    )

    # EUR_LEX_PLAIN_ID intencionalmente no catalogado.

    return repository


def test_multiple_document_identities_are_corroborated_with_diverse_sources(tmp_path):
    query_service = _combined_query_service()
    answer = _answer(query_service, query="plazo")

    assert len(answer.citations) == 3

    service = KnowledgeEvidenceSufficiencyService(
        query_service=query_service,
        catalog_repository=_catalog_repository(tmp_path),
    )

    report = service.evaluate(answer)

    assert report.level is KnowledgeEvidenceSufficiencyLevel.CORROBORATED
    assert report.source_count == 3
    assert report.distinct_source_keys == (
        "BOE_CONSOLIDATED",
        "EUR_LEX",
        "EUR_LEX_CONSOLIDATED",
    )
    assert report.distinct_providers == ("BOE", "EUR_LEX")

    boe_key = f"BOE_CONSOLIDATED:{BOE_CONSOLIDATED_ID}"
    eu_consolidated_key = f"EUR_LEX_CONSOLIDATED:{CELEX}"
    eu_plain_key = f"EUR_LEX:{EUR_LEX_PLAIN_ID}"

    boe_validity = _find_validity(
        report.temporal_validity, "BOE_CONSOLIDATED", BOE_CONSOLIDATED_ID
    )
    assert boe_validity.status is KnowledgeValidityStatus.IN_FORCE

    eu_consolidated_validity = _find_validity(
        report.temporal_validity, "EUR_LEX_CONSOLIDATED", CELEX
    )
    assert eu_consolidated_validity.status is KnowledgeValidityStatus.UNKNOWN

    eu_plain_validity = _find_validity(
        report.temporal_validity, "EUR_LEX", EUR_LEX_PLAIN_ID
    )
    assert eu_plain_validity.status is KnowledgeValidityStatus.UNKNOWN

    boe_review = _find(report.human_review_status, boe_key)
    assert boe_review.is_reviewed is True
    assert boe_review.tier == "FOLLOWED"

    eu_consolidated_review = _find(report.human_review_status, eu_consolidated_key)
    assert eu_consolidated_review.is_reviewed is False
    assert eu_consolidated_review.tier == "DISCOVERED"

    eu_plain_review = _find(report.human_review_status, eu_plain_key)
    assert eu_plain_review.is_reviewed is None
    assert "no está en KnowledgeCatalog" in eu_plain_review.reason

    for coverage in report.document_coverage:
        assert coverage.resolved is True

    assert all(
        "resolutor" in reason or "Knowledge" in reason
        for reason in report.unresolved_reasons
    )


# ------------------------------------------------------------
# Cobertura no resoluble (capacidad ausente, fail-closed)
# ------------------------------------------------------------


def test_document_coverage_is_unresolved_when_structure_unavailable():
    query_service = _single_source_query_service()
    answer = _answer(query_service, query="plazo ampliado", as_of=date(2018, 5, 25))

    degraded_query_service = KnowledgeQueryService(EmptyStructures())
    service = KnowledgeEvidenceSufficiencyService(query_service=degraded_query_service)

    report = service.evaluate(answer)

    coverage = report.document_coverage[0]
    assert coverage.resolved is False
    assert coverage.total_block_ids == ()
    assert "No pudo recuperarse" in coverage.reason

    assert coverage.reason in report.unresolved_reasons


# ------------------------------------------------------------
# Validación de dependencias
# ------------------------------------------------------------


def test_service_rejects_non_query_service_dependency():
    with pytest.raises(TypeError):
        KnowledgeEvidenceSufficiencyService(query_service=object())


def test_service_rejects_invalid_catalog_repository():
    query_service = _single_source_query_service()

    with pytest.raises(TypeError):
        KnowledgeEvidenceSufficiencyService(
            query_service=query_service, catalog_repository=object()
        )


def test_evaluate_rejects_non_knowledge_answer():
    query_service = _single_source_query_service()
    service = KnowledgeEvidenceSufficiencyService(query_service=query_service)

    with pytest.raises(TypeError):
        service.evaluate(object())

"""E2E: ingestión BOE Consolidado -> KnowledgeQueryService.

Prueba el flujo completo con transporte determinista y fixtures
locales (sin red):

    BoeConsolidatedProvider + _FakeTransport
        -> KnowledgeIngestionService
        -> SQLiteKnowledgeRepository / SQLiteKnowledgeStructureRepository
        -> KnowledgeQueryService (temporal, evidencia, validez,
           horizonte de evidencia)
"""

from datetime import date

from backend.knowledge import (
    KnowledgeQueryService,
    KnowledgeValidityStatus,
    SQLiteKnowledgeStructureRepository,
)
from backend.knowledge.boe_consolidated.provider import (
    BoeConsolidatedProvider,
)
from backend.knowledge.boe_consolidated.validity import (
    resolve_boe_consolidated_validity,
)
from backend.knowledge.evidence_horizon import (
    KnowledgeEvidenceHorizonStatus,
)
from backend.knowledge.ingestion import KnowledgeIngestionService
from backend.knowledge.sqlite_repository import SQLiteKnowledgeRepository

from test_knowledge_boe_consolidated_provider import (
    TARGET,
    _FakeTransport,
)


def _query_service(tmp_path):
    db_path = tmp_path / "boe_query_e2e.db"

    item_repository = SQLiteKnowledgeRepository(db_path)
    structure_repository = SQLiteKnowledgeStructureRepository(db_path)

    item_repository.initialize_schema()
    structure_repository.initialize_schema()

    ingestion = KnowledgeIngestionService(
        item_repository,
        structure_repository=structure_repository,
    )

    provider = BoeConsolidatedProvider(_FakeTransport())

    result = ingestion.discover_and_ingest(
        provider,
        cursor="20260605",
    )

    assert result.written_count == 1
    assert result.structured_written_count == 1

    service = KnowledgeQueryService(
        structure_repository,
        item_repository,
        validity_resolvers={
            "BOE_CONSOLIDATED": (
                resolve_boe_consolidated_validity
            ),
        },
    )

    return service


def test_e2e_resolves_document_before_amendment(tmp_path):
    service = _query_service(tmp_path)

    answer = service.get_effective_version(
        "BOE_CONSOLIDATED",
        TARGET,
        date(2025, 5, 20),
    )

    assert answer.resolved
    assert "Texto antiguo" in answer.content_text
    assert "Texto vigente reformado" not in answer.content_text


def test_e2e_resolves_document_after_amendment(tmp_path):
    service = _query_service(tmp_path)

    answer = service.get_effective_version(
        "BOE_CONSOLIDATED",
        TARGET,
        date(2026, 4, 16),
    )

    assert answer.resolved
    assert "Texto vigente reformado" in answer.content_text
    assert "Texto antiguo" not in answer.content_text


def test_e2e_get_block_carries_structured_provenance(tmp_path):
    service = _query_service(tmp_path)

    answer = service.get_block(
        "BOE_CONSOLIDATED",
        TARGET,
        "a2",
        date(2026, 4, 16),
    )

    assert answer.resolved
    assert answer.provenance is not None
    assert answer.provenance.source_key == "BOE_CONSOLIDATED"
    assert answer.provenance.external_id == TARGET
    assert answer.provenance.block_id == "a2"
    assert answer.provenance.document_title == (
        "Real Decreto 1155/2024, de 19 de noviembre"
    )


def test_e2e_search_finds_ingested_document_by_title(tmp_path):
    service = _query_service(tmp_path)

    result = service.search("Real Decreto 1155")

    assert result.hits
    assert result.hits[0].provenance.external_id == TARGET


def test_e2e_document_validity_confirms_in_force_from_official_flags(
    tmp_path,
):
    service = _query_service(tmp_path)

    validity = service.get_document_validity(
        "BOE_CONSOLIDATED",
        TARGET,
    )

    assert validity.status is KnowledgeValidityStatus.IN_FORCE
    assert validity.evidence


def test_e2e_evidence_horizon_reflects_ingestion(tmp_path):
    service = _query_service(tmp_path)

    horizon = service.get_evidence_horizon(
        "BOE_CONSOLIDATED",
        TARGET,
    )

    assert horizon.status is KnowledgeEvidenceHorizonStatus.CHECKED
    assert horizon.observation_count == 1
    assert horizon.source_revision == "20260605T080848Z"


def test_e2e_uningested_identity_has_no_evidence_horizon(tmp_path):
    service = _query_service(tmp_path)

    horizon = service.get_evidence_horizon(
        "BOE_CONSOLIDATED",
        "BOE-A-1900-00001",
    )

    assert (
        horizon.status
        is KnowledgeEvidenceHorizonStatus.NEVER_INGESTED
    )

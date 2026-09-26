"""E2E: ingestión estructural EUR-Lex -> KnowledgeQueryService.

Dos tramos complementarios:

- ``_history`` / ``_query_service``: construcción manual de historia
  estructural multi-revisión (fixtures XHTML locales), sin pasar por
  ningún provider ni servicio de ingestión;

- ``_provider_query_service``: tramo gobernado real, revisión
  consolidada única ya obtenida (``FakeTransport``):

    FakeTransport
        -> EurLexConsolidatedProvider
        -> KnowledgeIngestionService.discover_and_ingest
        -> KnowledgeQueryService
"""

from datetime import date

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeQueryStatus,
    KnowledgeValidityStatus,
    SQLiteKnowledgeStructureRepository,
    build_knowledge_item,
    classify_knowledge_revision,
)
from backend.knowledge.eurlex import (
    EurLexConsolidatedProvider,
    build_eurlex_article_history,
    parse_eurlex_article_snapshot,
    resolve_eurlex_validity,
)
from backend.knowledge.evidence_horizon import (
    KnowledgeEvidenceHorizonStatus,
)
from backend.knowledge.ingestion import KnowledgeIngestionService
from backend.knowledge.sqlite_repository import SQLiteKnowledgeRepository

from test_knowledge_eurlex_provider import (
    CONSOLIDATED,
    FakeTransport,
    TARGET,
)


CONSOLIDATED_EFFECTIVE_FROM = date(
    2025,
    10,
    12,
)


CELEX = "32016R0399"

D_BEFORE = date(2016, 10, 6)
D_AFTER = date(2017, 4, 7)


def _snapshot(*, revision, body):
    return parse_eurlex_article_snapshot(
        body.encode("utf-8"),
        original_celex=CELEX,
        consolidated_celex=revision,
    )


def _history():
    before = _snapshot(
        revision="02016R0399-20161006",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Duración máxima 90 días.
          </p>
        </body></html>
        """,
    )

    after = _snapshot(
        revision="02016R0399-20170407",
        body="""
        <html><body>
          <p class="title-article-norm">
            Artículo 8
          </p>
          <p class="norm">
            Duración máxima 180 días.
          </p>
        </body></html>
        """,
    )

    return build_eurlex_article_history((before, after))


def _query_service(tmp_path):
    history = _history()
    document = history.document

    item = build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id=history.original_celex,
        title="Reglamento (UE) 2016/399 (versión consolidada)",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text=document.current_content_text,
        source_revision=history.revisions[-1],
    )

    db_path = tmp_path / "eurlex_query_e2e.db"

    item_repository = SQLiteKnowledgeRepository(db_path)
    structure_repository = SQLiteKnowledgeStructureRepository(db_path)

    item_repository.initialize_schema()
    structure_repository.initialize_schema()

    decision = classify_knowledge_revision(
        previous=None,
        current=item,
    )

    write_result = item_repository.persist(item, decision)
    assert write_result.written is True

    structure_result = structure_repository.persist(document)
    assert structure_result.written is True

    return KnowledgeQueryService(
        structure_repository,
        item_repository,
        validity_resolvers={
            "EUR_LEX_CONSOLIDATED": resolve_eurlex_validity,
        },
    )


def test_e2e_resolves_article_before_amendment(tmp_path):
    service = _query_service(tmp_path)

    answer = service.get_block(
        "EUR_LEX_CONSOLIDATED",
        CELEX,
        "article:8",
        D_BEFORE,
    )

    assert answer.resolved
    assert answer.content_text == "Artículo 8 Duración máxima 90 días."
    assert answer.superseded_on == D_AFTER
    assert answer.open_ended is False


def test_e2e_resolves_article_after_amendment(tmp_path):
    service = _query_service(tmp_path)

    answer = service.get_block(
        "EUR_LEX_CONSOLIDATED",
        CELEX,
        "article:8",
        D_AFTER,
    )

    assert answer.resolved
    assert answer.content_text == "Artículo 8 Duración máxima 180 días."
    assert answer.open_ended is True


def test_e2e_get_changes_reports_amendment_event(tmp_path):
    service = _query_service(tmp_path)

    changelog = service.get_changes(
        "EUR_LEX_CONSOLIDATED",
        CELEX,
        D_BEFORE,
        D_AFTER,
    )

    assert len(changelog.events) == 1
    assert changelog.events[0].block_id == "article:8"
    assert changelog.events[0].event == "AMENDED"


def test_e2e_search_finds_document_by_title(tmp_path):
    service = _query_service(tmp_path)

    result = service.search(
        "Reglamento (UE) 2016/399",
        as_of=D_AFTER,
    )

    assert result.hits
    assert result.hits[0].provenance.external_id == CELEX


def test_e2e_validity_is_explicitly_unknown_not_fabricated(tmp_path):
    service = _query_service(tmp_path)

    validity = service.get_document_validity(
        "EUR_LEX_CONSOLIDATED",
        CELEX,
    )

    assert validity.status is KnowledgeValidityStatus.UNKNOWN
    assert validity.in_force is False


def test_e2e_evidence_horizon_reflects_single_ingestion(tmp_path):
    service = _query_service(tmp_path)

    horizon = service.get_evidence_horizon(
        "EUR_LEX_CONSOLIDATED",
        CELEX,
    )

    assert horizon.status is KnowledgeEvidenceHorizonStatus.CHECKED
    assert horizon.observation_count == 1


# ============================================================
# Tramo gobernado: FakeTransport -> EurLexConsolidatedProvider ->
# KnowledgeIngestionService.discover_and_ingest -> KnowledgeQueryService
#
# Cobertura de una única revisión consolidada ya obtenida
# (ARTICLES_ONLY). No implica backfill histórico ni evidencia
# forense.
# ============================================================


def _provider_query_service(tmp_path):
    provider = EurLexConsolidatedProvider(
        FakeTransport()
    )

    db_path = (
        tmp_path
        / "eurlex_query_provider_e2e.db"
    )

    item_repository = SQLiteKnowledgeRepository(
        db_path
    )
    structure_repository = SQLiteKnowledgeStructureRepository(
        db_path
    )

    item_repository.initialize_schema()
    structure_repository.initialize_schema()

    service = KnowledgeIngestionService(
        item_repository,
        structure_repository,
    )

    batch = service.discover_and_ingest(
        provider,
        cursor=TARGET,
    )

    query_service = KnowledgeQueryService(
        structure_repository,
        item_repository,
        validity_resolvers={
            "EUR_LEX_CONSOLIDATED": resolve_eurlex_validity,
        },
    )

    return batch, query_service


def test_provider_e2e_ingestion_writes_structured_document_once(
    tmp_path,
):
    batch, _service = (
        _provider_query_service(
            tmp_path
        )
    )

    assert batch.written_count == 1
    assert (
        batch.structured_written_count
        == 1
    )


def test_provider_e2e_effective_version_resolves_articles(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    answer = service.get_effective_version(
        "EUR_LEX_CONSOLIDATED",
        TARGET,
        CONSOLIDATED_EFFECTIVE_FROM,
    )

    assert answer.resolved

    assert {
        block.block_id
        for block in answer.blocks
    } == {
        "article:1",
        "article:2",
    }


def test_provider_e2e_block_query_resolves_current_article(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    answer = service.get_block(
        "EUR_LEX_CONSOLIDATED",
        TARGET,
        "article:1",
        CONSOLIDATED_EFFECTIVE_FROM,
    )

    assert answer.resolved
    assert (
        "Texto consolidado vigente"
        in answer.content_text
    )

    assert (
        answer.provenance.source_key
        == "EUR_LEX_CONSOLIDATED"
    )
    assert (
        answer.provenance.external_id
        == TARGET
    )
    assert (
        answer.provenance.source_revision
        == CONSOLIDATED
    )


def test_provider_e2e_changes_reports_initial_articles(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    changelog = service.get_changes(
        "EUR_LEX_CONSOLIDATED",
        TARGET,
        date(2025, 1, 1),
        CONSOLIDATED_EFFECTIVE_FROM,
    )

    assert (
        changelog.status
        is KnowledgeQueryStatus.RESOLVED
    )

    assert {
        event.block_id
        for event in changelog.events
    } == {
        "article:1",
        "article:2",
    }

    assert all(
        event.event == "INITIAL"
        for event in changelog.events
    )


def test_provider_e2e_search_finds_document_by_identifier(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    result = service.search(
        TARGET,
        as_of=CONSOLIDATED_EFFECTIVE_FROM,
    )

    assert result.hits
    assert (
        result.hits[0].provenance.external_id
        == TARGET
    )
    assert (
        result.hits[0].provenance.source_key
        == "EUR_LEX_CONSOLIDATED"
    )


def test_provider_e2e_validity_is_unknown_with_reason(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    validity = service.get_document_validity(
        "EUR_LEX_CONSOLIDATED",
        TARGET,
    )

    assert (
        validity.status
        is KnowledgeValidityStatus.UNKNOWN
    )
    assert validity.in_force is False
    assert validity.reason


def test_provider_e2e_evidence_horizon_reflects_single_ingestion(
    tmp_path,
):
    _batch, service = (
        _provider_query_service(
            tmp_path
        )
    )

    horizon = service.get_evidence_horizon(
        "EUR_LEX_CONSOLIDATED",
        TARGET,
    )

    assert (
        horizon.status
        is KnowledgeEvidenceHorizonStatus.CHECKED
    )
    assert horizon.observation_count == 1

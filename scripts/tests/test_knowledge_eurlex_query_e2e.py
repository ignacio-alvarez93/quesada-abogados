"""E2E: ingestión estructural EUR-Lex -> KnowledgeQueryService.

EurLexProvider/EurLexConsolidatedProvider todavía no implementan
``KnowledgeStructuredProvider`` (ver REMAINING_BLOCKERS del informe
KN-2), por lo que este flujo demuestra el tramo que sí existe hoy de
forma determinista y local, sin red:

    parse_eurlex_article_snapshot (fixtures XHTML locales)
        -> build_eurlex_article_history
        -> KnowledgeStructuredDocument
        -> SQLiteKnowledgeRepository / SQLiteKnowledgeStructureRepository
        -> KnowledgeQueryService
"""

from datetime import date

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeValidityStatus,
    SQLiteKnowledgeStructureRepository,
    build_knowledge_item,
    classify_knowledge_revision,
)
from backend.knowledge.eurlex import (
    build_eurlex_article_history,
    parse_eurlex_article_snapshot,
    resolve_eurlex_validity,
)
from backend.knowledge.evidence_horizon import (
    KnowledgeEvidenceHorizonStatus,
)
from backend.knowledge.sqlite_repository import SQLiteKnowledgeRepository


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

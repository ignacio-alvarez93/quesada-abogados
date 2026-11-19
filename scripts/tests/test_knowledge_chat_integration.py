"""WO-KNOW-CHAT-01: integración Chat Knowledge sobre SQLite temporal.

Flujo real sin red:

    BoeConsolidatedProvider + _FakeTransport (fixture existente)
        -> KnowledgeIngestionService -> SQLite temporal
        -> build_knowledge_chat_service(db_path)
        -> KnowledgeChatService + KnowledgeChatContextRepository

El CRM es ficticio y vive en la MISMA base temporal (como en producción,
donde Knowledge y ERP comparten ``database/quesada.db``). Nunca se abre
la base real.

Smoke visual aislado (no forma parte de pytest):

    python scripts/tests/test_knowledge_chat_integration.py --flet-smoke
"""

from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from backend.knowledge import (  # noqa: E402
    KnowledgeQueryService,
    SQLiteKnowledgeStructureRepository,
)
from backend.knowledge.boe_consolidated.provider import (  # noqa: E402
    BoeConsolidatedProvider,
)
from backend.knowledge.boe_consolidated.validity import (  # noqa: E402
    resolve_boe_consolidated_validity,
)
from backend.knowledge.ingestion import KnowledgeIngestionService  # noqa: E402
from backend.knowledge.sqlite_repository import (  # noqa: E402
    SQLiteKnowledgeRepository,
)
from backend.services.knowledge_chat_service import (  # noqa: E402
    KnowledgeChatAnswerKind,
    KnowledgeChatContextStatus,
    KnowledgeChatMode,
    build_knowledge_chat_service,
)

from test_knowledge_boe_consolidated_provider import (  # noqa: E402
    TARGET,
    _FakeTransport,
)
from test_knowledge_chat_context_repository import (  # noqa: E402
    OTHER_EXPEDIENT_MARKER,
    PII_MARKERS,
    create_fictitious_crm,
)


USER = {"id": 7, "username": "operador.ficticio"}
ARTICLE_QUESTION = "¿Qué decía el artículo 2 del Real Decreto 1155/2024?"


def _ingest(db_path: Path) -> None:
    items = SQLiteKnowledgeRepository(db_path)
    structures = SQLiteKnowledgeStructureRepository(db_path)

    items.initialize_schema()
    structures.initialize_schema()

    result = KnowledgeIngestionService(
        items,
        structure_repository=structures,
    ).discover_and_ingest(
        BoeConsolidatedProvider(_FakeTransport()),
        cursor="20260605",
    )

    assert result.written_count == 1
    assert result.structured_written_count == 1


def build_fixture_db(directory: Path) -> Path:
    db_path = directory / "knowledge_chat_ficticio.db"
    _ingest(db_path)
    create_fictitious_crm(db_path)
    return db_path


def _query_service(db_path: Path) -> KnowledgeQueryService:
    return KnowledgeQueryService(
        SQLiteKnowledgeStructureRepository(db_path),
        SQLiteKnowledgeRepository(db_path),
        validity_resolvers={
            "BOE_CONSOLIDATED": resolve_boe_consolidated_validity,
        },
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture_db(tmp_path):
    return build_fixture_db(tmp_path)


# ------------------------------------------------------------
# BOE: identificador, frase natural y temporalidad
# ------------------------------------------------------------


def test_identifier_question_cites_stored_provenance(fixture_db):
    service = build_knowledge_chat_service(fixture_db)
    expected = _query_service(fixture_db).get_document(
        "BOE_CONSOLIDATED", TARGET
    )

    response = service.ask_from_input(question=TARGET, current_user=USER)
    citation = response.citations[0]

    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    assert citation.external_id == TARGET
    assert citation.url == expected.provenance.document_uri
    assert citation.url
    assert citation.is_official_primary is False
    assert citation.validity_status == "IN_FORCE"
    # La publicación oficial (BOE diario) no está ingerida: no hay enlace.
    assert citation.official_publication_url == ""
    assert TARGET in citation.official_publication_note


@pytest.mark.parametrize(
    "as_of, present, absent",
    [
        ("2025-05-20", "Texto antiguo", "reformado"),
        ("2026-04-16", "Texto vigente reformado", "Texto antiguo"),
    ],
)
def test_natural_article_question_is_temporally_exact(
    fixture_db, as_of, present, absent
):
    service = build_knowledge_chat_service(fixture_db)
    expected = _query_service(fixture_db).get_block(
        "BOE_CONSOLIDATED", TARGET, "a2", date.fromisoformat(as_of)
    )

    response = service.ask_from_input(
        question=ARTICLE_QUESTION,
        as_of_text=as_of,
        current_user=USER,
    )
    blocks = [c for c in response.citations if c.block_id]

    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    assert [c.block_id for c in blocks] == ["a2"]
    assert present in blocks[0].excerpt
    assert absent not in response.documentary_text
    assert blocks[0].url == expected.provenance.block_uri
    assert blocks[0].version_key == expected.provenance.version_key


def test_keyword_question_never_returns_future_versions(fixture_db):
    service = build_knowledge_chat_service(fixture_db)

    response = service.ask_from_input(
        question="texto vigente reformado",
        as_of_text="2025-05-20",
        current_user=USER,
    )

    assert all("reformado" not in c.excerpt for c in response.citations)


def test_unknown_norm_is_insufficient_evidence(fixture_db):
    service = build_knowledge_chat_service(fixture_db)

    response = service.ask_from_input(
        question="¿Qué dice la Ley Orgánica 99/2099?",
        current_user=USER,
    )

    assert response.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
    assert response.citations == ()


def test_corpus_status_reports_available_sources(fixture_db):
    status = build_knowledge_chat_service(fixture_db).corpus_status()

    assert status.available is True
    assert dict(status.documents_by_source) == {
        "BOE_CONSOLIDATED": 1,
        "BOE": 0,
    }


# ------------------------------------------------------------
# Fallbacks de corpus: sin excepciones crudas ni creación de ficheros
# ------------------------------------------------------------


def test_missing_database_is_unavailable_and_never_created(tmp_path):
    missing = tmp_path / "no_existe.db"

    response = build_knowledge_chat_service(missing).ask_from_input(
        question="plazo", current_user=USER
    )

    assert response.kind is KnowledgeChatAnswerKind.CORPUS_UNAVAILABLE
    assert not missing.exists()


def test_database_without_knowledge_schema_is_unavailable(tmp_path):
    crm_only = tmp_path / "solo_crm.db"
    create_fictitious_crm(crm_only)

    service = build_knowledge_chat_service(crm_only)
    response = service.ask_from_input(question="plazo", current_user=USER)

    assert response.kind is KnowledgeChatAnswerKind.CORPUS_UNAVAILABLE
    assert "no such table" not in repr(response)
    assert service.corpus_status().available is False


def test_empty_corpus_is_insufficient_evidence(tmp_path):
    empty = tmp_path / "corpus_vacio.db"
    SQLiteKnowledgeRepository(empty).initialize_schema()
    SQLiteKnowledgeStructureRepository(empty).initialize_schema()

    response = build_knowledge_chat_service(empty).ask_from_input(
        question="plazo", current_user=USER
    )

    assert response.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE


# ------------------------------------------------------------
# Contexto CRM ficticio, solo lectura
# ------------------------------------------------------------


def test_context_end_to_end_is_minimal_separated_and_read_only(fixture_db):
    before = _digest(fixture_db)
    service = build_knowledge_chat_service(fixture_db)

    selection = service.resolve_expedient(USER, "EXP-FICT-0001")
    assert selection.status is KnowledgeChatContextStatus.GRANTED

    response = service.ask_from_input(
        question=ARTICLE_QUESTION,
        mode=KnowledgeChatMode.BOE_WITH_EXPEDIENT,
        current_user=USER,
        expediente_id=selection.expediente_id,
        context_confirmed=True,
    )
    crm = response.crm_context
    rendered = repr(response)

    assert crm.status is KnowledgeChatContextStatus.GRANTED
    assert crm.expediente_ref == "EXP-FICT-0001"
    assert ("Tipo de expediente", "ARRAIGO FICTICIO") in crm.facts
    assert response.citations
    assert "ARRAIGO FICTICIO" not in response.documentary_text

    for marker in PII_MARKERS + (OTHER_EXPEDIENT_MARKER,):
        assert marker not in rendered

    assert _digest(fixture_db) == before


@pytest.mark.parametrize(
    "user",
    [
        None,
        {"id": 7, "username": "suplantado"},
        {"id": 8, "username": "inactivo.ficticio"},
    ],
)
def test_context_denied_without_verifiable_active_identity(fixture_db, user):
    service = build_knowledge_chat_service(fixture_db)

    response = service.ask_from_input(
        question=ARTICLE_QUESTION,
        mode=KnowledgeChatMode.BOE_WITH_EXPEDIENT,
        current_user=user,
        expediente_id=11,
        context_confirmed=True,
    )

    assert response.crm_context.status is KnowledgeChatContextStatus.DENIED
    assert response.crm_context.facts == ()
    assert "EXP-FICT-0001" not in repr(response)
    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY


# ------------------------------------------------------------
# Smoke Flet aislado (manual)
# ------------------------------------------------------------


def run_flet_smoke() -> None:  # pragma: no cover - manual
    import tempfile

    import flet as ft

    from frontend.views.knowledge_chat_view import knowledge_chat_view

    directory = Path(tempfile.mkdtemp(prefix="know_chat01_smoke_"))
    db_path = build_fixture_db(directory)
    service = build_knowledge_chat_service(db_path)

    print("[KNOW-CHAT-01-SMOKE] fixture DB:", db_path, flush=True)
    print(
        "[KNOW-CHAT-01-SMOKE] pruebe: "
        f"«{ARTICLE_QUESTION}» con fecha 2025-05-20; "
        "expediente EXP-FICT-0001",
        flush=True,
    )

    def main(page):
        page.title = "Chat Knowledge · SMOKE ficticio"
        page.add(
            knowledge_chat_view(
                page,
                service=service,
                current_user=dict(USER),
            )
        )

    ft.run(main)


if __name__ == "__main__":  # pragma: no cover - manual
    if "--flet-smoke" in sys.argv:
        run_flet_smoke()
    else:
        print(
            "Uso: python scripts/tests/test_knowledge_chat_integration.py "
            "--flet-smoke  (los tests se ejecutan con pytest)"
        )

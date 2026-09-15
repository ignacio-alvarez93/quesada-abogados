from backend.knowledge.boe_consolidated.provider import (
    BoeConsolidatedProvider,
)
from backend.knowledge.ingestion import (
    KnowledgeIngestionService,
)
from backend.knowledge.revisions import (
    KnowledgeRevisionStatus,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)

from test_knowledge_boe_consolidated_provider import (
    TARGET,
    _FakeTransport,
)


def test_generic_ingestion_service_handles_second_provider(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeRepository(
            tmp_path
            / "knowledge.db"
        )
    )

    repository.initialize_schema()

    provider = (
        BoeConsolidatedProvider(
            _FakeTransport()
        )
    )

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    first = (
        service.discover_and_ingest(
            provider,
            cursor="20260605",
        )
    )

    assert (
        first.written_count
        == 1
    )

    assert (
        first.results[0].status
        is KnowledgeRevisionStatus.NEW
    )

    second = (
        service.discover_and_ingest(
            provider,
            cursor="20260605",
        )
    )

    assert (
        second.written_count
        == 0
    )

    assert (
        second.unchanged_count
        == 1
    )

    assert (
        second.results[0].status
        is KnowledgeRevisionStatus.UNCHANGED
    )

    stored = (
        repository.get_current(
            "BOE_CONSOLIDATED",
            TARGET,
        )
    )

    assert stored is not None
    assert (
        stored.source_revision
        == "20260605T080848Z"
    )

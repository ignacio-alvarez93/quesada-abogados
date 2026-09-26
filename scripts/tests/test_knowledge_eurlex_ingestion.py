from backend.knowledge.eurlex import (
    EurLexConsolidatedProvider,
    EurLexProvider,
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

from test_knowledge_eurlex_provider import (
    FakeTransport,
    TARGET,
)


def _service(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeRepository(
            tmp_path
            / "eurlex_knowledge.db"
        )
    )

    repository.initialize_schema()

    return (
        repository,
        KnowledgeIngestionService(
            repository
        ),
    )


def test_original_provider_uses_generic_ingestion_pipeline(
    tmp_path,
):
    repository, service = (
        _service(
            tmp_path
        )
    )

    provider = EurLexProvider(
        FakeTransport()
    )

    first = (
        service.discover_and_ingest(
            provider,
            cursor=TARGET,
        )
    )

    assert (
        first.results[
            0
        ].status
        is KnowledgeRevisionStatus.NEW
    )

    assert (
        first.written_count
        == 1
    )

    second = (
        service.discover_and_ingest(
            provider,
            cursor=TARGET,
        )
    )

    assert (
        second.results[
            0
        ].status
        is KnowledgeRevisionStatus.UNCHANGED
    )

    assert (
        second.written_count
        == 0
    )

    stored = (
        repository.get_current(
            "EUR_LEX",
            TARGET,
        )
    )

    assert stored is not None

    assert (
        stored.source_revision
        == TARGET
    )


def test_consolidated_provider_uses_same_generic_pipeline(
    tmp_path,
):
    repository, service = (
        _service(
            tmp_path
        )
    )

    provider = (
        EurLexConsolidatedProvider(
            FakeTransport()
        )
    )

    first = (
        service.discover_and_ingest(
            provider,
            cursor=TARGET,
        )
    )

    assert (
        first.results[
            0
        ].status
        is KnowledgeRevisionStatus.NEW
    )

    second = (
        service.discover_and_ingest(
            provider,
            cursor=TARGET,
        )
    )

    assert (
        second.results[
            0
        ].status
        is KnowledgeRevisionStatus.UNCHANGED
    )

    stored = (
        repository.get_current(
            "EUR_LEX_CONSOLIDATED",
            TARGET,
        )
    )

    assert stored is not None

    assert (
        stored.source_revision
        == "02016R0399-20251012"
    )

    revisions = (
        repository.list_revisions(
            "EUR_LEX_CONSOLIDATED",
            TARGET,
        )
    )

    # UNCHANGED no crea una revisión histórica adicional.
    assert (
        len(
            revisions
        )
        == 1
    )

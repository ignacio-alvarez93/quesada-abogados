from backend.knowledge import (
    KnowledgeStructuredProvider,
    SQLiteKnowledgeStructureRepository,
)
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


def _service(
    tmp_path,
):
    db_path = (
        tmp_path
        / "structured_ingestion.db"
    )

    item_repository = (
        SQLiteKnowledgeRepository(
            db_path
        )
    )

    structure_repository = (
        SQLiteKnowledgeStructureRepository(
            db_path
        )
    )

    item_repository.initialize_schema()
    structure_repository.initialize_schema()

    service = KnowledgeIngestionService(
        item_repository,
        structure_repository=(
            structure_repository
        ),
    )

    return (
        item_repository,
        structure_repository,
        service,
    )


def test_boe_provider_exposes_optional_structured_capability():
    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    assert isinstance(
        provider,
        KnowledgeStructuredProvider,
    )


def test_structured_ingestion_persists_item_and_structure(
    tmp_path,
):
    (
        item_repository,
        structure_repository,
        service,
    ) = _service(
        tmp_path
    )

    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    reference = provider.discover(
        cursor="20260605"
    ).items[0]

    result = service.ingest_reference(
        provider,
        reference,
    )

    assert (
        result.status
        is KnowledgeRevisionStatus.NEW
    )

    assert result.written is True
    assert result.structure_supported is True
    assert result.structure_written is True

    assert (
        result.structure_block_count
        == 2
    )

    assert (
        result.structure_version_count
        == 3
    )

    item = item_repository.get_current(
        "BOE_CONSOLIDATED",
        TARGET,
    )

    document = (
        structure_repository.get_document(
            "BOE_CONSOLIDATED",
            TARGET,
        )
    )

    assert item is not None
    assert document is not None

    assert (
        document.current_content_text
        == item.content_text
    )


def test_structured_ingestion_second_run_is_fully_idempotent(
    tmp_path,
):
    (
        _,
        structure_repository,
        service,
    ) = _service(
        tmp_path
    )

    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    reference = provider.discover(
        cursor="20260605"
    ).items[0]

    first = service.ingest_reference(
        provider,
        reference,
    )

    second = service.ingest_reference(
        provider,
        reference,
    )

    assert first.written is True
    assert first.structure_written is True

    assert (
        second.status
        is KnowledgeRevisionStatus.UNCHANGED
    )

    assert second.written is False

    assert (
        second.structure_supported
        is True
    )

    assert (
        second.structure_written
        is False
    )

    assert (
        second.structure_block_count
        == 2
    )

    assert (
        second.structure_version_count
        == 3
    )

    loaded = (
        structure_repository.get_document(
            "BOE_CONSOLIDATED",
            TARGET,
        )
    )

    assert loaded is not None
    assert len(loaded.blocks) == 2
    assert len(loaded.versions) == 3


def test_batch_reports_structured_writes(
    tmp_path,
):
    (
        _,
        _,
        service,
    ) = _service(
        tmp_path
    )

    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    first = (
        service.discover_and_ingest(
            provider,
            cursor="20260605",
        )
    )

    second = (
        service.discover_and_ingest(
            provider,
            cursor="20260605",
        )
    )

    assert (
        first.structured_written_count
        == 1
    )

    assert (
        second.structured_written_count
        == 0
    )


def test_existing_ingestion_without_structure_repository_remains_compatible(
    tmp_path,
):
    db_path = (
        tmp_path
        / "legacy_pipeline.db"
    )

    repository = (
        SQLiteKnowledgeRepository(
            db_path
        )
    )

    repository.initialize_schema()

    service = KnowledgeIngestionService(
        repository
    )

    provider = BoeConsolidatedProvider(
        _FakeTransport()
    )

    reference = provider.discover(
        cursor="20260605"
    ).items[0]

    result = service.ingest_reference(
        provider,
        reference,
    )

    assert result.written is True

    # El provider posee capacidad estructural,
    # pero el caller no la activó con un repository.
    assert (
        result.structure_supported
        is True
    )

    assert (
        result.structure_written
        is False
    )

    assert (
        result.structure_block_count
        == 0
    )

    assert (
        result.structure_version_count
        == 0
    )

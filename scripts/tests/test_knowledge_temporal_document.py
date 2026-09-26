from datetime import date

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeStructuredDocument,
    KnowledgeTemporalDocumentStatus,
    build_knowledge_block_version,
    resolve_document_at,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


def _document():
    a1 = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a1",
            version_position=1,
            content_text=(
                "Articulo 1 original."
            ),
            effective_from=date(
                2025,
                5,
                20,
            ),
            is_current=True,
        )
    )

    old = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="dt-5",
            version_position=1,
            content_text=(
                "DT quinta antigua."
            ),
            effective_from=date(
                2025,
                5,
                20,
            ),
            is_current=False,
        )
    )

    current = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="dt-5",
            version_position=2,
            content_text=(
                "DT quinta reformada."
            ),
            effective_from=date(
                2026,
                4,
                16,
            ),
            is_current=True,
        )
    )

    later = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="future",
            version_position=1,
            content_text=(
                "Bloque añadido posteriormente."
            ),
            effective_from=date(
                2026,
                6,
                1,
            ),
            is_current=True,
        )
    )

    return KnowledgeStructuredDocument(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        blocks=(
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="a1",
                position=1,
                current_version_key=(
                    a1.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="dt-5",
                position=2,
                current_version_key=(
                    current.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="future",
                position=3,
                current_version_key=(
                    later.version_key
                ),
            ),
        ),
        versions=(
            a1,
            old,
            current,
            later,
        ),
    )


def test_document_before_first_effective_is_explicit():
    snapshot = resolve_document_at(
        _document(),
        date(
            2025,
            5,
            19,
        ),
    )

    assert (
        snapshot.status
        is KnowledgeTemporalDocumentStatus.BEFORE_DOCUMENT_EFFECTIVE
    )

    assert snapshot.blocks == ()


def test_historical_document_uses_old_block_version():
    snapshot = resolve_document_at(
        _document(),
        date(
            2026,
            1,
            1,
        ),
    )

    assert snapshot.resolved is True

    assert (
        snapshot.content_text
        == (
            "Articulo 1 original.\n\n"
            "DT quinta antigua."
        )
    )

    assert (
        snapshot.omitted_future_blocks
        == (
            "future",
        )
    )


def test_document_changes_exactly_on_effective_date():
    previous = resolve_document_at(
        _document(),
        date(
            2026,
            4,
            15,
        ),
    )

    changed = resolve_document_at(
        _document(),
        date(
            2026,
            4,
            16,
        ),
    )

    assert (
        "DT quinta antigua."
        in previous.content_text
    )

    assert (
        "DT quinta reformada."
        not in previous.content_text
    )

    assert (
        "DT quinta reformada."
        in changed.content_text
    )

    assert (
        "DT quinta antigua."
        not in changed.content_text
    )


def test_future_added_block_appears_only_from_its_effective_date():
    before = resolve_document_at(
        _document(),
        date(
            2026,
            5,
            31,
        ),
    )

    after = resolve_document_at(
        _document(),
        date(
            2026,
            6,
            1,
        ),
    )

    assert (
        "Bloque añadido posteriormente."
        not in before.content_text
    )

    assert (
        "future"
        in before.omitted_future_blocks
    )

    assert (
        "Bloque añadido posteriormente."
        in after.content_text
    )

    assert (
        after.omitted_future_blocks
        == ()
    )


def test_temporal_service_reconstructs_persisted_document(
    tmp_path,
):
    from backend.knowledge import (
        KnowledgeItemKind,
        KnowledgeTemporalService,
        SQLiteKnowledgeStructureRepository,
        build_knowledge_item,
        classify_knowledge_revision,
    )
    from backend.knowledge.sqlite_repository import (
        SQLiteKnowledgeRepository,
    )

    db_path = (
        tmp_path
        / "temporal_document.db"
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

    document = _document()

    item = build_knowledge_item(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        title="Norma temporal",
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=(
            document.current_content_text
        ),
    )

    item_repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )

    structure_repository.persist(
        document
    )

    service = KnowledgeTemporalService(
        structure_repository
    )

    snapshot = (
        service.resolve_document_at(
            SOURCE,
            EXTERNAL_ID,
            date(
                2026,
                1,
                1,
            ),
        )
    )

    assert snapshot.resolved is True

    assert (
        "DT quinta antigua."
        in snapshot.content_text
    )

    assert (
        "DT quinta reformada."
        not in snapshot.content_text
    )

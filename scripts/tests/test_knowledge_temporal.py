from datetime import date

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeStructuredDocument,
    KnowledgeTemporalResolutionStatus,
    build_knowledge_block_version,
    resolve_block_version_at,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


def _document():
    old = build_knowledge_block_version(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id="dt-5",
        version_position=1,
        content_text="Texto antiguo.",
        modifier_external_id=(
            EXTERNAL_ID
        ),
        effective_from=date(
            2025,
            5,
            20,
        ),
        is_current=False,
    )

    current = build_knowledge_block_version(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id="dt-5",
        version_position=2,
        content_text="Texto reformado.",
        modifier_external_id=(
            "BOE-A-2026-8284"
        ),
        effective_from=date(
            2026,
            4,
            16,
        ),
        is_current=True,
    )

    return KnowledgeStructuredDocument(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        blocks=(
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="dt-5",
                position=1,
                title=(
                    "Disposición transitoria quinta"
                ),
                current_version_key=(
                    current.version_key
                ),
            ),
        ),
        versions=(
            old,
            current,
        ),
    )


def test_before_first_effective_fails_closed():
    result = resolve_block_version_at(
        _document(),
        "dt-5",
        date(
            2025,
            5,
            19,
        ),
    )

    assert (
        result.status
        is KnowledgeTemporalResolutionStatus.BEFORE_FIRST_EFFECTIVE
    )

    assert result.version is None


def test_exact_first_effective_date_resolves_old_version():
    result = resolve_block_version_at(
        _document(),
        "dt-5",
        date(
            2025,
            5,
            20,
        ),
    )

    assert result.resolved is True

    assert (
        result.version.version_position
        == 1
    )

    assert (
        result.version.modifier_external_id
        == EXTERNAL_ID
    )


def test_day_before_reform_still_resolves_old_version():
    result = resolve_block_version_at(
        _document(),
        "dt-5",
        date(
            2026,
            4,
            15,
        ),
    )

    assert result.resolved is True

    assert (
        result.version.version_position
        == 1
    )


def test_reform_effective_date_resolves_new_version():
    result = resolve_block_version_at(
        _document(),
        "dt-5",
        date(
            2026,
            4,
            16,
        ),
    )

    assert result.resolved is True

    assert (
        result.version.version_position
        == 2
    )

    assert (
        result.version.modifier_external_id
        == "BOE-A-2026-8284"
    )


def test_missing_effective_date_fails_closed():
    version = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a1",
            version_position=1,
            content_text="Texto.",
            is_current=True,
        )
    )

    document = KnowledgeStructuredDocument(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        blocks=(
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="a1",
                position=1,
                current_version_key=(
                    version.version_key
                ),
            ),
        ),
        versions=(
            version,
        ),
    )

    result = resolve_block_version_at(
        document,
        "a1",
        date(
            2026,
            9,
            15,
        ),
    )

    assert (
        result.status
        is KnowledgeTemporalResolutionStatus.INCOMPLETE_EFFECTIVE_DATES
    )


def test_unknown_block_is_explicit():
    result = resolve_block_version_at(
        _document(),
        "missing",
        date(
            2026,
            9,
            15,
        ),
    )

    assert (
        result.status
        is KnowledgeTemporalResolutionStatus.BLOCK_NOT_FOUND
    )


def test_temporal_service_reads_persisted_structure(
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
        / "temporal.db"
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
        title="RD temporal",
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

    result = service.resolve_block_at(
        SOURCE,
        EXTERNAL_ID,
        "dt-5",
        date(
            2025,
            12,
            1,
        ),
    )

    assert result.resolved is True

    assert (
        result.version.version_position
        == 1
    )

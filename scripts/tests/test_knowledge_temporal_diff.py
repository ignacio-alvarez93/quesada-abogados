from datetime import date

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeStructuredDocument,
    KnowledgeTemporalBlockChangeKind,
    KnowledgeTemporalDiffStatus,
    build_knowledge_block_version,
    compare_document_at_dates,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


def _document():
    stable = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="stable",
            version_position=1,
            content_text="Estable.",
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
            block_id="changed",
            version_position=1,
            content_text="Texto antiguo.",
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
            block_id="changed",
            version_position=2,
            content_text="Texto nuevo.",
            effective_from=date(
                2026,
                4,
                16,
            ),
            is_current=True,
        )
    )

    added = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="added",
            version_position=1,
            content_text="Bloque nuevo.",
            effective_from=date(
                2026,
                4,
                16,
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
                block_id="stable",
                position=1,
                current_version_key=(
                    stable.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="changed",
                position=2,
                current_version_key=(
                    current.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="added",
                position=3,
                current_version_key=(
                    added.version_key
                ),
            ),
        ),
        versions=(
            stable,
            old,
            current,
            added,
        ),
    )


def test_diff_detects_modified_and_added_blocks():
    diff = compare_document_at_dates(
        _document(),
        date(
            2026,
            4,
            15,
        ),
        date(
            2026,
            4,
            16,
        ),
    )

    assert (
        diff.status
        is KnowledgeTemporalDiffStatus.RESOLVED
    )

    assert diff.modified_count == 1
    assert diff.added_count == 1
    assert diff.removed_count == 0
    assert diff.unchanged_count == 1

    kinds = {
        change.block_id: change.kind
        for change
        in diff.changes
    }

    assert (
        kinds["changed"]
        is KnowledgeTemporalBlockChangeKind.MODIFIED
    )

    assert (
        kinds["added"]
        is KnowledgeTemporalBlockChangeKind.ADDED
    )


def test_modified_change_preserves_both_exact_texts():
    diff = compare_document_at_dates(
        _document(),
        date(
            2026,
            4,
            15,
        ),
        date(
            2026,
            4,
            16,
        ),
    )

    change = next(
        item
        for item
        in diff.changes
        if item.block_id
        == "changed"
    )

    assert (
        change.from_content_text
        == "Texto antiguo."
    )

    assert (
        change.to_content_text
        == "Texto nuevo."
    )

    assert (
        change.from_version.version_position
        == 1
    )

    assert (
        change.to_version.version_position
        == 2
    )


def test_reverse_comparison_reports_removed_block():
    diff = compare_document_at_dates(
        _document(),
        date(
            2026,
            4,
            16,
        ),
        date(
            2026,
            4,
            15,
        ),
    )

    kinds = {
        change.block_id: change.kind
        for change
        in diff.changes
    }

    assert (
        kinds["added"]
        is KnowledgeTemporalBlockChangeKind.REMOVED
    )


def test_same_date_has_no_changes():
    diff = compare_document_at_dates(
        _document(),
        date(
            2026,
            4,
            16,
        ),
        date(
            2026,
            4,
            16,
        ),
    )

    assert diff.resolved is True
    assert diff.changes == ()
    assert diff.unchanged_count == 3

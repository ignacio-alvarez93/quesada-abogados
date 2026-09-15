from datetime import date
import sqlite3

import pytest

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeItemKind,
    KnowledgeStructuredDocument,
    KnowledgeStructureRepositoryIntegrityError,
    SQLiteKnowledgeStructureRepository,
    build_knowledge_block_version,
    build_knowledge_item,
    classify_knowledge_revision,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


def _document():
    a1v1 = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a1",
            version_position=1,
            content_text=(
                "Articulo 1 vigente."
            ),
            modifier_external_id=(
                EXTERNAL_ID
            ),
            published_on=date(
                2024,
                11,
                20,
            ),
            effective_from=date(
                2025,
                5,
                20,
            ),
            is_current=True,
        )
    )

    a2v1 = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a2",
            version_position=1,
            content_text=(
                "Articulo 2 antiguo."
            ),
            modifier_external_id=(
                EXTERNAL_ID
            ),
            published_on=date(
                2024,
                11,
                20,
            ),
            effective_from=date(
                2025,
                5,
                20,
            ),
            is_current=False,
        )
    )

    a2v2 = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a2",
            version_position=2,
            content_text=(
                "Articulo 2 vigente."
            ),
            modifier_external_id=(
                "BOE-A-2026-8284"
            ),
            published_on=date(
                2026,
                4,
                15,
            ),
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
                block_id="a1",
                position=1,
                title="Articulo 1",
                current_version_key=(
                    a1v1.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="a2",
                position=2,
                title="Articulo 2",
                current_version_key=(
                    a2v2.version_key
                ),
            ),
        ),
        versions=(
            a1v1,
            a2v1,
            a2v2,
        ),
    )


def _repositories(
    tmp_path,
):
    db_path = (
        tmp_path
        / "structure.db"
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
    # Idempotencia de migración.
    structure_repository.initialize_schema()

    return (
        db_path,
        item_repository,
        structure_repository,
    )


def _persist_parent(
    repository,
    document,
):
    item = build_knowledge_item(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        title="Real Decreto 1155/2024",
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=(
            document.current_content_text
        ),
        source_revision=(
            "20260605T080848Z"
        ),
    )

    repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )


def test_structure_repository_roundtrip_and_idempotency(
    tmp_path,
):
    (
        db_path,
        item_repository,
        repository,
    ) = _repositories(
        tmp_path
    )

    document = _document()

    _persist_parent(
        item_repository,
        document,
    )

    first = repository.persist(
        document
    )

    assert first.written is True
    assert first.block_count == 2
    assert first.version_count == 3
    assert first.inserted_blocks == 2
    assert first.inserted_versions == 3

    second = repository.persist(
        document
    )

    assert second.written is False

    loaded = repository.get_document(
        SOURCE,
        EXTERNAL_ID,
    )

    assert loaded == document

    connection = sqlite3.connect(
        db_path
    )

    try:
        block_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_blocks
            """
        ).fetchone()[0]

        version_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_block_versions
            """
        ).fetchone()[0]

        current_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_block_versions
            WHERE is_current = 1
            """
        ).fetchone()[0]

    finally:
        connection.close()

    assert block_count == 2
    assert version_count == 3
    assert current_count == 2


def test_structure_requires_materialized_parent_item(
    tmp_path,
):
    (
        _,
        _,
        repository,
    ) = _repositories(
        tmp_path
    )

    with pytest.raises(
        KnowledgeStructureRepositoryIntegrityError,
        match="KnowledgeItem materializado",
    ):
        repository.persist(
            _document()
        )


def test_structure_current_view_must_match_parent_item(
    tmp_path,
):
    (
        _,
        item_repository,
        repository,
    ) = _repositories(
        tmp_path
    )

    document = _document()

    wrong_item = build_knowledge_item(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        title="Real Decreto 1155/2024",
        item_kind=(
            KnowledgeItemKind.LEGISLATION
        ),
        content_text=(
            "Contenido distinto."
        ),
    )

    item_repository.persist(
        wrong_item,
        classify_knowledge_revision(
            previous=None,
            current=wrong_item,
        ),
    )

    with pytest.raises(
        KnowledgeStructureRepositoryIntegrityError,
        match="no coincide",
    ):
        repository.persist(
            document
        )



def test_roundtrip_preserves_block_position_instead_of_lexical_block_id(
    tmp_path,
):
    (
        _,
        item_repository,
        repository,
    ) = _repositories(
        tmp_path
    )

    first_version = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="z-first",
            version_position=1,
            content_text="Primero.",
            modifier_external_id=(
                EXTERNAL_ID
            ),
            is_current=True,
        )
    )

    second_version = (
        build_knowledge_block_version(
            source_key=SOURCE,
            external_id=EXTERNAL_ID,
            block_id="a-second",
            version_position=1,
            content_text="Segundo.",
            modifier_external_id=(
                EXTERNAL_ID
            ),
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
                block_id="z-first",
                position=1,
                current_version_key=(
                    first_version.version_key
                ),
            ),
            KnowledgeBlock(
                source_key=SOURCE,
                external_id=EXTERNAL_ID,
                block_id="a-second",
                position=2,
                current_version_key=(
                    second_version.version_key
                ),
            ),
        ),
        versions=(
            first_version,
            second_version,
        ),
    )

    _persist_parent(
        item_repository,
        document,
    )

    first = repository.persist(
        document
    )

    assert first.written is True

    loaded = repository.get_document(
        SOURCE,
        EXTERNAL_ID,
    )

    assert loaded == document

    assert tuple(
        version.block_id
        for version
        in loaded.versions
    ) == (
        "z-first",
        "a-second",
    )

    second = repository.persist(
        document
    )

    assert second.written is False

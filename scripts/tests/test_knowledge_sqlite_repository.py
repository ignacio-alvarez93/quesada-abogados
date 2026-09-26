from dataclasses import replace
from datetime import date

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeRevisionStatus,
    build_knowledge_item,
    classify_knowledge_revision,
)
from backend.knowledge.repository import (
    KnowledgeRepository,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


def _item(**overrides):
    data = {
        "source_key": "BOE",
        "external_id": "BOE-A-2026-15300",
        "title": "Disposición de prueba",
        "item_kind": KnowledgeItemKind.OFFICIAL_PUBLICATION,
        "content_text": (
            "Artículo 1.\n"
            "Contenido jurídico de prueba."
        ),
        "canonical_uri": (
            "https://www.boe.es/eli/es/ai/2026/06/17/(1)"
        ),
        "source_revision": "20260720145601",
        "published_on": date(
            2026,
            7,
            14,
        ),
        "language": "es",
        "metadata": {
            "rango": "Acuerdo Internacional",
            "departamento": "Ministerio de prueba",
        },
    }

    data.update(overrides)

    return build_knowledge_item(
        **data
    )


def _repository(tmp_path):
    repository = SQLiteKnowledgeRepository(
        tmp_path / "knowledge_test.db"
    )
    repository.initialize_schema()
    return repository


def test_sqlite_repository_satisfies_port(tmp_path):
    repository = _repository(
        tmp_path
    )

    assert isinstance(
        repository,
        KnowledgeRepository,
    )


def test_schema_initialization_is_idempotent(tmp_path):
    repository = _repository(
        tmp_path
    )

    repository.initialize_schema()
    repository.initialize_schema()

    assert repository.get_current(
        "BOE",
        "BOE-A-2026-15300",
    ) is None


def test_new_item_round_trip(tmp_path):
    repository = _repository(
        tmp_path
    )
    item = _item()

    decision = classify_knowledge_revision(
        previous=None,
        current=item,
    )

    result = repository.persist(
        item,
        decision,
    )

    assert result.written is True
    assert result.revision_number == 1
    assert (
        result.status
        is KnowledgeRevisionStatus.NEW
    )

    stored = repository.get_current(
        item.source_key,
        item.external_id,
    )

    assert stored == item


def test_unchanged_item_does_not_create_revision(tmp_path):
    repository = _repository(
        tmp_path
    )
    item = _item()

    repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )

    previous = repository.get_current(
        item.source_key,
        item.external_id,
    )

    decision = classify_knowledge_revision(
        previous=previous,
        current=item,
    )

    result = repository.persist(
        item,
        decision,
    )

    assert result.written is False
    assert result.revision_number == 1

    history = repository.list_revisions(
        item.source_key,
        item.external_id,
    )

    assert len(history) == 1


def test_metadata_revision_updates_current_and_keeps_history(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )

    original = _item()

    repository.persist(
        original,
        classify_knowledge_revision(
            previous=None,
            current=original,
        ),
    )

    revised = replace(
        original,
        source_revision="20260721101010",
        title="Disposición corregida",
    )

    decision = classify_knowledge_revision(
        previous=original,
        current=revised,
    )

    result = repository.persist(
        revised,
        decision,
    )

    assert result.revision_number == 2
    assert (
        result.status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )

    assert repository.get_current(
        revised.source_key,
        revised.external_id,
    ) == revised

    history = repository.list_revisions(
        revised.source_key,
        revised.external_id,
    )

    assert [
        snapshot.revision_status
        for snapshot in history
    ] == [
        KnowledgeRevisionStatus.NEW,
        KnowledgeRevisionStatus.METADATA_REVISED,
    ]

    assert history[0].item == original
    assert history[1].item == revised


def test_content_revision_is_persisted_as_new_version(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )

    original = _item()

    repository.persist(
        original,
        classify_knowledge_revision(
            previous=None,
            current=original,
        ),
    )

    revised = replace(
        original,
        content_text=(
            original.content_text
            + "\n\nContenido modificado."
        ),
        source_revision="20260722121212",
    )

    decision = classify_knowledge_revision(
        previous=original,
        current=revised,
    )

    result = repository.persist(
        revised,
        decision,
    )

    assert result.revision_number == 2
    assert (
        result.status
        is KnowledgeRevisionStatus.CONTENT_REVISED
    )

    history = repository.list_revisions(
        revised.source_key,
        revised.external_id,
    )

    assert len(history) == 2
    assert (
        history[0].item.content_sha256
        != history[1].item.content_sha256
    )


def test_repository_survives_reopen(tmp_path):
    db_path = (
        tmp_path
        / "knowledge_test.db"
    )

    first = SQLiteKnowledgeRepository(
        db_path
    )
    first.initialize_schema()

    item = _item()

    first.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )

    second = SQLiteKnowledgeRepository(
        db_path
    )

    stored = second.get_current(
        "BOE",
        "BOE-A-2026-15300",
    )

    assert stored == item

    history = second.list_revisions(
        "BOE",
        "BOE-A-2026-15300",
    )

    assert len(history) == 1
    assert history[0].revision_number == 1


def test_metadata_round_trip_preserves_normalization(tmp_path):
    repository = _repository(
        tmp_path
    )

    item = _item(
        metadata={
            "zeta": " último ",
            "alpha": " primero ",
        }
    )

    repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )

    stored = repository.get_current(
        item.source_key,
        item.external_id,
    )

    assert stored.metadata == (
        ("alpha", "primero"),
        ("zeta", "último"),
    )

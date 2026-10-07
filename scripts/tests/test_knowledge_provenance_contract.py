"""KN-2 — contrato provider-neutral SOURCE → ACQUISITION → NORMALIZATION →
DOCUMENT → VERSION → EVIDENCE.

No introduce contratos nuevos: reutiliza ``KnowledgeItem``,
``classify_knowledge_revision``, ``SQLiteKnowledgeRepository`` y
``resolve_evidence_horizon``, ya validados en KN-1. Este fichero cierra
la matriz de pruebas exigida por KN-2 sobre esos contratos existentes.
"""

from datetime import date

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeRevisionStatus,
    build_knowledge_item,
    classify_knowledge_revision,
    get_knowledge_source,
    knowledge_record_sha256,
    resolve_evidence_horizon,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


def _repository(tmp_path):
    repository = SQLiteKnowledgeRepository(
        tmp_path / "knowledge_provenance_contract.db"
    )
    repository.initialize_schema()
    return repository


def _persist_new(repository, item):
    return repository.persist(
        item,
        classify_knowledge_revision(
            previous=None,
            current=item,
        ),
    )


# ============================================================
# Idempotencia: misma fuente + mismo contenido
# ============================================================


def test_same_source_same_content_repeated_acquisition_is_idempotent(
    tmp_path,
):
    repository = _repository(tmp_path)

    item = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-40001",
        title="Disposición de prueba",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Artículo 1. Contenido estable.",
        source_revision="20260901000000",
    )

    _persist_new(repository, item)

    # Tres adquisiciones idénticas sucesivas no deben crear
    # observaciones lógicas nuevas.
    for _ in range(3):
        previous = repository.get_current(
            item.source_key,
            item.external_id,
        )

        decision = classify_knowledge_revision(
            previous=previous,
            current=item,
        )

        result = repository.persist(item, decision)

        assert result.written is False
        assert result.status is KnowledgeRevisionStatus.UNCHANGED
        assert result.revision_number == 1

    history = repository.list_revisions(
        item.source_key,
        item.external_id,
    )

    assert len(history) == 1


# ============================================================
# Misma fuente + contenido modificado → versión determinista
# ============================================================


def test_same_source_changed_content_produces_new_deterministic_version(
    tmp_path,
):
    repository = _repository(tmp_path)

    original = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-40002",
        title="Disposición de prueba",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Artículo 1. Versión original.",
        source_revision="20260901000000",
    )

    _persist_new(repository, original)

    revised = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-40002",
        title="Disposición de prueba",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Artículo 1. Versión modificada.",
        source_revision="20260902000000",
    )

    decision = classify_knowledge_revision(
        previous=original,
        current=revised,
    )

    result = repository.persist(revised, decision)

    assert result.status is KnowledgeRevisionStatus.CONTENT_REVISED
    assert result.revision_number == 2

    # Repetir la misma adquisición modificada produce el mismo
    # veredicto: la clasificación es determinista, no depende del
    # orden de ejecución ni de estado oculto.
    repeated_decision = classify_knowledge_revision(
        previous=original,
        current=revised,
    )

    assert (
        repeated_decision.current_record_sha256
        == decision.current_record_sha256
    )
    assert repeated_decision.status == decision.status


# ============================================================
# Mismo external_id repetido a través de varias adquisiciones
# ============================================================


def test_same_external_id_across_repeated_acquisition_stays_single_identity(
    tmp_path,
):
    repository = _repository(tmp_path)

    external_id = "BOE-A-2026-40003"

    # (content_text, source_revision): la segunda adquisición repite
    # contenido y revisión exactos; la tercera cambia el contenido.
    acquisitions = [
        ("Artículo 1. Redacción inicial.", "20260901000000"),
        ("Artículo 1. Redacción inicial.", "20260901000000"),
        ("Artículo 1. Redacción corregida.", "20260903000000"),
    ]

    previous_item = None

    for content_text, source_revision in acquisitions:
        item = build_knowledge_item(
            source_key="BOE",
            external_id=external_id,
            title="Disposición de prueba",
            item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
            content_text=content_text,
            source_revision=source_revision,
        )

        decision = classify_knowledge_revision(
            previous=previous_item,
            current=item,
        )

        repository.persist(item, decision)

        previous_item = repository.get_current(
            "BOE",
            external_id,
        )

    history = repository.list_revisions("BOE", external_id)

    # Una única identidad lógica: NEW, UNCHANGED (misma observación),
    # CONTENT_REVISED (contenido distinto). Nunca identidades
    # duplicadas para el mismo (source_key, external_id).
    assert [snapshot.revision_status for snapshot in history] == [
        KnowledgeRevisionStatus.NEW,
        KnowledgeRevisionStatus.CONTENT_REVISED,
    ]

    assert (
        len(
            {
                snapshot.item.canonical_key
                for snapshot in history
            }
        )
        == 1
    )


# ============================================================
# Distintas fuentes, mismo título → identidades independientes
# ============================================================


def test_different_source_same_title_are_independent_identities(
    tmp_path,
):
    repository = _repository(tmp_path)

    shared_title = "Reglamento de protección de datos"

    boe_item = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-40010",
        title=shared_title,
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Contenido publicado por el BOE.",
    )

    eur_lex_item = build_knowledge_item(
        source_key="EUR_LEX",
        external_id="32026R0010",
        title=shared_title,
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="Contenido publicado por EUR-Lex.",
    )

    _persist_new(repository, boe_item)
    _persist_new(repository, eur_lex_item)

    assert boe_item.canonical_key != eur_lex_item.canonical_key

    stored_boe = repository.get_current(
        "BOE",
        "BOE-A-2026-40010",
    )
    stored_eur_lex = repository.get_current(
        "EUR_LEX",
        "32026R0010",
    )

    assert stored_boe == boe_item
    assert stored_eur_lex == eur_lex_item
    assert stored_boe.title == stored_eur_lex.title
    assert (
        stored_boe.content_sha256
        != stored_eur_lex.content_sha256
    )

    # Distinto adaptador de fuente detrás de cada identidad.
    assert (
        get_knowledge_source(stored_boe.source_key).provider
        == "BOE"
    )
    assert (
        get_knowledge_source(stored_eur_lex.source_key).provider
        == "EUR_LEX"
    )


# ============================================================
# Procedencia opcional ausente: nunca se inventa
# ============================================================


def test_missing_optional_provenance_is_preserved_as_empty_not_invented(
    tmp_path,
):
    repository = _repository(tmp_path)

    item = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-40020",
        title="Disposición sin procedencia opcional",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Contenido sin canonical_uri ni source_revision.",
        # canonical_uri, source_revision y published_on quedan
        # deliberadamente sin proporcionar.
    )

    assert item.canonical_uri == ""
    assert item.source_revision == ""
    assert item.published_on is None

    result = _persist_new(repository, item)

    assert result.written is True

    stored = repository.get_current(
        "BOE",
        "BOE-A-2026-40020",
    )

    assert stored.canonical_uri == ""
    assert stored.source_revision == ""
    assert stored.published_on is None

    horizon = resolve_evidence_horizon(
        source_key="BOE",
        external_id="BOE-A-2026-40020",
        revisions=repository.list_revisions(
            "BOE",
            "BOE-A-2026-40020",
        ),
    )

    # La marca de frescura propia de la fuente está ausente: se
    # reporta explícitamente vacía, nunca se fabrica un valor.
    assert horizon.checked
    assert horizon.source_revision == ""


# ============================================================
# Identidad de hash/versión determinista
# ============================================================


def test_content_and_record_hash_are_deterministic_across_rebuilds(
    tmp_path,
):
    def _build():
        return build_knowledge_item(
            source_key="BOE",
            external_id="BOE-A-2026-40030",
            title="Disposición de prueba",
            item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
            content_text="Artículo 1. Contenido reproducible.",
            canonical_uri="https://www.boe.es/eli/es/test/2026/09/01/1",
            source_revision="20260901000000",
            published_on=date(2026, 9, 1),
            metadata={"rango": "Resolución"},
        )

    first = _build()
    second = _build()

    assert first.content_sha256 == second.content_sha256
    assert knowledge_record_sha256(first) == knowledge_record_sha256(
        second
    )

    repository = _repository(tmp_path)

    _persist_new(repository, first)

    stored = repository.get_current(
        "BOE",
        "BOE-A-2026-40030",
    )

    assert stored.content_sha256 == first.content_sha256

    # Reingerir la reconstrucción idéntica no debe alterar la
    # identidad de versión persistida.
    decision = classify_knowledge_revision(
        previous=stored,
        current=second,
    )

    result = repository.persist(second, decision)

    assert result.written is False
    assert result.revision_number == 1


# ============================================================
# Adquisición: cuándo se observó cada revisión
# ============================================================


def test_acquisition_timestamp_advances_with_each_observed_revision(
    tmp_path,
):
    repository = _repository(tmp_path)

    external_id = "BOE-A-2026-40040"

    first = build_knowledge_item(
        source_key="BOE",
        external_id=external_id,
        title="Disposición de prueba",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Artículo 1. Primera observación.",
        source_revision="20260901000000",
    )

    _persist_new(repository, first)

    horizon_after_first = resolve_evidence_horizon(
        source_key="BOE",
        external_id=external_id,
        revisions=repository.list_revisions(
            "BOE",
            external_id,
        ),
    )

    second = build_knowledge_item(
        source_key="BOE",
        external_id=external_id,
        title="Disposición de prueba",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="Artículo 1. Segunda observación.",
        source_revision="20260902000000",
    )

    decision = classify_knowledge_revision(
        previous=first,
        current=second,
    )

    repository.persist(second, decision)

    horizon_after_second = resolve_evidence_horizon(
        source_key="BOE",
        external_id=external_id,
        revisions=repository.list_revisions(
            "BOE",
            external_id,
        ),
    )

    assert horizon_after_first.observation_count == 1
    assert horizon_after_second.observation_count == 2
    assert (
        horizon_after_second.checked_as_of
        >= horizon_after_first.checked_as_of
    )
    assert (
        horizon_after_second.source_revision
        == "20260902000000"
    )

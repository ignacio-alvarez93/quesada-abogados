from datetime import date, datetime

import pytest

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeItemKind,
    KnowledgeQueryCapabilityError,
    KnowledgeQueryService,
    KnowledgeQueryStatus,
    KnowledgeSearchMatchKind,
    KnowledgeStructuredDocument,
    KnowledgeTemporalBlockChangeKind,
    KnowledgeTemporalDiffStatus,
    KnowledgeTemporalDocumentStatus,
    KnowledgeTemporalResolutionStatus,
    SQLiteKnowledgeStructureRepository,
    build_knowledge_block_version,
    build_knowledge_item,
    classify_knowledge_revision,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


CELEX = "32016R0679"
BOE_ID = "BOE-A-2024-24099"

D_2016 = date(2016, 5, 24)
D_2018 = date(2018, 5, 25)
D_2019 = date(2019, 6, 1)
D_2020 = date(2020, 1, 1)


# ------------------------------------------------------------
# Repositorios en memoria: prueban que el servicio no depende de
# SQLite (puerto provider-neutral).
# ------------------------------------------------------------


class MemoryStructures:
    def __init__(self, *documents):
        self._documents = {
            (d.source_key, d.external_id): d
            for d in documents
        }

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        return self._documents.get(
            (source_key.strip().upper(), external_id.strip())
        )

    def persist(self, document):
        raise NotImplementedError

    def list_document_identities(self, source_key=None):
        return tuple(
            sorted(
                key
                for key in self._documents
                if source_key is None or key[0] == source_key
            )
        )


class MemoryStructuresWithoutListing:
    def __init__(self, inner):
        self._inner = inner

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        return self._inner.get_document(source_key, external_id)

    def persist(self, document):
        raise NotImplementedError


class MemoryItems:
    def __init__(self, *items):
        self._items = {i.source_identity: i for i in items}

    def initialize_schema(self):
        pass

    def get_current(self, source_key, external_id):
        return self._items.get((source_key, external_id))

    def persist(self, item, decision):
        raise NotImplementedError

    def list_revisions(self, source_key, external_id):
        return ()


def _v(source, external_id, block_id, position, text, eff, current, **kw):
    return build_knowledge_block_version(
        source_key=source,
        external_id=external_id,
        block_id=block_id,
        version_position=position,
        content_text=text,
        effective_from=eff,
        is_current=current,
        **kw,
    )


def _doc(source, external_id, blocks, versions):
    """blocks: [(block_id, position, title)]"""

    return KnowledgeStructuredDocument(
        source_key=source,
        external_id=external_id,
        blocks=tuple(
            KnowledgeBlock(
                source_key=source,
                external_id=external_id,
                block_id=block_id,
                position=position,
                title=title,
                canonical_uri=f"https://example.test/{block_id}",
            )
            for block_id, position, title in blocks
        ),
        versions=tuple(versions),
    )


def _eu_document():
    s, x = "EUR_LEX_CONSOLIDATED", CELEX

    return _doc(
        s,
        x,
        [("art1", 1, "Artículo 1"), ("art2", 2, "Artículo 2"), ("art3", 3, "Artículo 3")],
        [
            _v(s, x, "art1", 1, "Plazo original de un mes.", D_2016, False),
            _v(
                s, x, "art1", 2, "Plazo ampliado a dos meses.", D_2018, True,
                modifier_external_id="32018R0001",
                published_on=date(2018, 5, 1),
            ),
            _v(s, x, "art2", 1, "Definiciones estables.", D_2016, True),
            _v(s, x, "art3", 1, "Artículo añadido tarde.", D_2019, True),
        ],
    )


def _service(*documents, items=None, listing=True):
    structures = MemoryStructures(*documents)

    if not listing:
        structures = MemoryStructuresWithoutListing(structures)

    return KnowledgeQueryService(structures, items)


def _eu_service():
    item = build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id=CELEX,
        title="Reglamento General de Protección de Datos",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        canonical_uri="https://eur-lex.europa.eu/eli/reg/2016/679",
        source_revision="rev-1",
        language="es",
    )

    return _service(_eu_document(), items=MemoryItems(item))


# ------------------------------------------------------------
# as_of
# ------------------------------------------------------------


def test_as_of_before_first_known_version_fails_explicitly():
    answer = _eu_service().get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", date(2016, 5, 23)
    )

    assert not answer.resolved
    assert answer.status is (
        KnowledgeTemporalResolutionStatus.BEFORE_FIRST_EFFECTIVE
    )
    assert answer.version is None
    assert answer.provenance is None
    assert answer.content_text == ""


def test_as_of_exact_effective_date_returns_new_version():
    answer = _eu_service().get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", D_2018
    )

    assert answer.resolved
    assert answer.content_text == "Plazo ampliado a dos meses."
    assert answer.provenance.effective_from == D_2018


def test_as_of_day_before_boundary_returns_old_version_with_supersession():
    answer = _eu_service().get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", date(2018, 5, 24)
    )

    assert answer.content_text == "Plazo original de un mes."
    assert answer.superseded_on == D_2018
    assert answer.open_ended is False


def test_as_of_after_latest_is_open_ended_and_does_not_claim_end_of_validity():
    service = _eu_service()

    answer = service.get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", date(2099, 1, 1)
    )

    assert answer.resolved
    assert answer.open_ended is True
    assert answer.superseded_on is None

    record = service.get_document("EUR_LEX_CONSOLIDATED", CELEX)

    assert record.end_of_validity_represented is False

    doc_answer = service.get_effective_version(
        "EUR_LEX_CONSOLIDATED", CELEX, date(2099, 1, 1)
    )

    assert doc_answer.end_of_validity_represented is False


def test_no_future_leakage_for_every_probe_date():
    service = _eu_service()

    probes = [
        date(2010, 1, 1), D_2016, date(2017, 1, 1), date(2018, 5, 24),
        D_2018, D_2019, date(2019, 5, 31), D_2020, date(2050, 1, 1),
    ]

    for as_of in probes:
        answer = service.get_effective_version(
            "EUR_LEX_CONSOLIDATED", CELEX, as_of
        )

        for block in answer.blocks:
            assert block.provenance.effective_from <= as_of

        if as_of < D_2018:
            assert "dos meses" not in answer.content_text

        if as_of < D_2019:
            assert "añadido tarde" not in answer.content_text
            assert "art3" in answer.omitted_future_blocks or (
                as_of < D_2016
            )

        if answer.snapshot_effective_from is not None:
            assert answer.snapshot_effective_from <= as_of


def test_document_level_snapshot_mixes_unchanged_and_amended_blocks():
    service = _eu_service()

    old = service.get_effective_version(
        "EUR_LEX_CONSOLIDATED", CELEX, date(2017, 1, 1)
    )

    new = service.get_effective_version(
        "EUR_LEX_CONSOLIDATED", CELEX, D_2020
    )

    assert old.resolved and new.resolved
    assert old.omitted_future_blocks == ("art3",)
    assert new.omitted_future_blocks == ()
    assert old.snapshot_effective_from == D_2016
    assert new.snapshot_effective_from == D_2019

    old_art2 = next(b for b in old.blocks if b.block_id == "art2")
    new_art2 = next(b for b in new.blocks if b.block_id == "art2")

    # Bloque intacto: misma identidad de versión en ambas fechas.
    assert (
        old_art2.provenance.version_key
        == new_art2.provenance.version_key
    )


def test_document_before_any_effective_date_is_not_resolved():
    answer = _eu_service().get_effective_version(
        "EUR_LEX_CONSOLIDATED", CELEX, date(2000, 1, 1)
    )

    assert answer.status is (
        KnowledgeTemporalDocumentStatus.BEFORE_DOCUMENT_EFFECTIVE
    )
    assert answer.blocks == ()
    assert answer.content_text == ""


def test_unknown_identity_and_block_are_explicit():
    service = _eu_service()

    missing_doc = service.get_block(
        "EUR_LEX_CONSOLIDATED", "NOPE", "art1", D_2018
    )

    missing_block = service.get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "nope", D_2018
    )

    assert missing_doc.status is (
        KnowledgeTemporalResolutionStatus.DOCUMENT_NOT_FOUND
    )
    assert missing_block.status is (
        KnowledgeTemporalResolutionStatus.BLOCK_NOT_FOUND
    )
    assert service.get_document("EUR_LEX_CONSOLIDATED", "NOPE") is None
    assert service.get_evidence(
        "EUR_LEX_CONSOLIDATED", "NOPE", "art1", D_2018
    ) is None

    assert service.get_effective_version(
        "EUR_LEX_CONSOLIDATED", "NOPE", D_2018
    ).status is KnowledgeTemporalDocumentStatus.DOCUMENT_NOT_FOUND


def test_datetime_as_of_is_rejected():
    service = _eu_service()

    with pytest.raises(TypeError):
        service.get_block(
            "EUR_LEX_CONSOLIDATED", CELEX, "art1", datetime(2018, 5, 25, 12)
        )

    with pytest.raises(TypeError):
        service.get_effective_version(
            "EUR_LEX_CONSOLIDATED", CELEX, "2018-05-25"
        )


# ------------------------------------------------------------
# Provenance
# ------------------------------------------------------------


def test_provenance_is_complete_and_structured_for_eurlex():
    p = _eu_service().get_evidence(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", D_2020
    )

    assert p.source_key == "EUR_LEX_CONSOLIDATED"
    assert p.provider == "EUR_LEX"
    assert p.identifier_scheme == "CELEX"
    assert p.external_id == CELEX
    assert p.document_canonical_key == f"EUR_LEX_CONSOLIDATED:{CELEX}"
    assert p.block_canonical_key == f"EUR_LEX_CONSOLIDATED:{CELEX}#block:art1"
    assert p.block_uri == "https://example.test/art1"
    assert p.version_position == 2
    assert p.version_canonical_key.endswith(f"@version:{p.version_key}")
    assert len(p.content_sha256) == 64
    assert p.modifier_external_id == "32018R0001"
    assert p.published_on == date(2018, 5, 1)
    assert p.effective_from == D_2018
    assert p.is_current is True
    assert p.document_title == "Reglamento General de Protección de Datos"
    assert p.document_uri.startswith("https://eur-lex.europa.eu")
    assert p.source_revision == "rev-1"
    assert p.representation == "DERIVED_STRUCTURED"
    assert p.authority


def test_provenance_does_not_invent_item_metadata_without_item_repository():
    p = _service(_eu_document()).get_evidence(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", D_2020
    )

    assert p.document_title == ""
    assert p.document_uri == ""
    assert p.source_revision == ""
    assert p.version_key


def test_boe_and_eurlex_share_semantics_but_keep_identity_scheme():
    boe = _doc(
        "BOE_CONSOLIDATED",
        BOE_ID,
        [("a1", 1, "Artículo 1")],
        [
            _v("BOE_CONSOLIDATED", BOE_ID, "a1", 1, "Texto A.", D_2016, False),
            _v("BOE_CONSOLIDATED", BOE_ID, "a1", 2, "Texto B.", D_2018, True),
        ],
    )

    service = _service(boe, _eu_document())

    boe_p = service.get_evidence("BOE_CONSOLIDATED", BOE_ID, "a1", D_2016)
    eu_p = service.get_evidence("EUR_LEX_CONSOLIDATED", CELEX, "art1", D_2016)

    assert boe_p.identifier_scheme == "BOE_ID"
    assert boe_p.provider == "BOE"
    assert eu_p.identifier_scheme == "CELEX"
    assert eu_p.provider == "EUR_LEX"
    assert type(boe_p) is type(eu_p)

    # Misma semántica temporal en ambas fuentes.
    assert service.get_block("BOE_CONSOLIDATED", BOE_ID, "a1", D_2018).content_text == "Texto B."
    assert service.get_block("BOE_CONSOLIDATED", BOE_ID, "a1", date(2018, 5, 24)).content_text == "Texto A."


def test_same_external_id_in_different_sources_never_collides():
    a = _doc("BOE", "X-1", [("b", 1, "")], [_v("BOE", "X-1", "b", 1, "Texto BOE.", D_2016, True)])
    b = _doc(
        "BOE_CONSOLIDATED", "X-1", [("b", 1, "")],
        [_v("BOE_CONSOLIDATED", "X-1", "b", 1, "Texto CONSOLIDADO.", D_2016, True)],
    )

    service = _service(a, b)

    assert service.get_block("BOE", "X-1", "b", D_2016).content_text == "Texto BOE."
    assert (
        service.get_block("BOE_CONSOLIDATED", "X-1", "b", D_2016).content_text
        == "Texto CONSOLIDADO."
    )

    hits = service.search("X-1").hits

    assert [h.provenance.source_key for h in hits] == ["BOE", "BOE_CONSOLIDATED"]


# ------------------------------------------------------------
# History / integrity
# ------------------------------------------------------------


def test_block_history_is_ordered_and_chained():
    history = _eu_service().get_block_history(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1"
    )

    assert history.status is KnowledgeQueryStatus.RESOLVED
    assert history.issues == ()
    assert [e.valid_from for e in history.versions] == [D_2016, D_2018]
    assert [e.superseded_on for e in history.versions] == [D_2018, None]


def test_history_missing_targets_are_explicit():
    service = _eu_service()

    assert service.get_block_history(
        "EUR_LEX_CONSOLIDATED", "NOPE", "art1"
    ).status is KnowledgeQueryStatus.DOCUMENT_NOT_FOUND

    assert service.get_block_history(
        "EUR_LEX_CONSOLIDATED", CELEX, "nope"
    ).status is KnowledgeQueryStatus.BLOCK_NOT_FOUND


def _anomalous_document():
    s, x = "BOE_CONSOLIDATED", "BOE-A-1"

    return _doc(
        s,
        x,
        [("bad", 1, ""), ("undated", 2, ""), ("ok", 3, "")],
        [
            _v(s, x, "bad", 1, "uno", D_2020, False),
            _v(s, x, "bad", 2, "dos", D_2016, True),
            _v(s, x, "undated", 1, "sin fecha", None, True),
            _v(s, x, "ok", 1, "bien", D_2016, True),
        ],
    )


def test_invalid_temporal_evidence_fails_closed_everywhere():
    service = _service(_anomalous_document())
    s, x = "BOE_CONSOLIDATED", "BOE-A-1"

    assert service.get_block(s, x, "bad", D_2020).status is (
        KnowledgeTemporalResolutionStatus.NON_MONOTONIC_TIMELINE
    )
    assert service.get_block(s, x, "undated", D_2020).status is (
        KnowledgeTemporalResolutionStatus.INCOMPLETE_EFFECTIVE_DATES
    )

    assert service.get_block_history(s, x, "bad").issues == (
        "NON_MONOTONIC_TIMELINE",
    )

    assert service.get_block_history(s, x, "undated").status is (
        KnowledgeQueryStatus.INCOMPLETE_TIMELINE
    )

    snapshot = service.get_effective_version(s, x, D_2020)

    assert snapshot.status is KnowledgeTemporalDocumentStatus.INCOMPLETE_TIMELINE
    assert snapshot.unresolved_blocks == ("bad", "undated")


def test_duplicate_version_position_is_rejected_at_construction():
    s, x = "BOE", "DUP-1"

    with pytest.raises(ValueError, match="version_position duplicada"):
        _doc(
            s,
            x,
            [("b", 1, "")],
            [
                _v(s, x, "b", 1, "uno", D_2016, False),
                _v(s, x, "b", 1, "dos", D_2018, True),
            ],
        )


def test_same_effective_date_on_latest_versions_is_ambiguous_not_guessed():
    s, x = "BOE", "AMB-1"

    doc = _doc(
        s,
        x,
        [("b", 1, "")],
        [
            _v(s, x, "b", 1, "uno", D_2016, False),
            _v(s, x, "b", 2, "dos", D_2016, True),
        ],
    )

    service = _service(doc)

    assert service.get_block(s, x, "b", D_2020).status is (
        KnowledgeTemporalResolutionStatus.AMBIGUOUS_EFFECTIVE_DATE
    )
    assert "DUPLICATE_EFFECTIVE_DATE" in service.get_block_history(
        s, x, "b"
    ).issues


# ------------------------------------------------------------
# Compare / changes
# ------------------------------------------------------------


def test_compare_versions_carries_provenance_for_both_sides():
    comparison = _eu_service().compare_versions(
        "EUR_LEX_CONSOLIDATED", CELEX, date(2017, 1, 1), D_2020
    )

    assert comparison.resolved
    assert comparison.diff.unchanged_count == 1

    by_id = {c.block_id: c for c in comparison.changes}

    assert by_id["art1"].kind is KnowledgeTemporalBlockChangeKind.MODIFIED
    assert by_id["art1"].from_provenance.effective_from == D_2016
    assert by_id["art1"].to_provenance.effective_from == D_2018
    assert by_id["art3"].kind is KnowledgeTemporalBlockChangeKind.ADDED
    assert by_id["art3"].from_provenance is None
    assert "art2" not in by_id


def test_compare_versions_on_unknown_document_is_unavailable():
    comparison = _eu_service().compare_versions(
        "EUR_LEX_CONSOLIDATED", "NOPE", D_2016, D_2020
    )

    assert comparison.diff.status is (
        KnowledgeTemporalDiffStatus.FROM_SNAPSHOT_UNAVAILABLE
    )
    assert comparison.changes == ()


def test_get_changes_is_half_open_and_ordered():
    service = _eu_service()

    log = service.get_changes(
        "EUR_LEX_CONSOLIDATED", CELEX, D_2016, D_2020
    )

    assert log.status is KnowledgeQueryStatus.RESOLVED
    assert [(e.effective_from, e.block_id, e.event) for e in log.events] == [
        (D_2018, "art1", "AMENDED"),
        (D_2019, "art3", "INITIAL"),
    ]
    assert log.events[0].provenance.modifier_external_id == "32018R0001"

    # since es exclusivo: lo efectivo en since ya estaba vigente.
    from_2018 = service.get_changes(
        "EUR_LEX_CONSOLIDATED", CELEX, D_2018, D_2018
    )

    assert from_2018.events == ()

    # until es inclusivo.
    to_2018 = service.get_changes(
        "EUR_LEX_CONSOLIDATED", CELEX, date(2017, 1, 1), D_2018
    )

    assert [e.block_id for e in to_2018.events] == ["art1"]


def test_get_changes_agrees_with_compare_versions():
    service = _eu_service()

    since, until = date(2017, 1, 1), D_2020

    changed = {
        e.block_id
        for e in service.get_changes(
            "EUR_LEX_CONSOLIDATED", CELEX, since, until
        ).events
    }

    compared = {
        c.block_id
        for c in service.compare_versions(
            "EUR_LEX_CONSOLIDATED", CELEX, since, until
        ).changes
    }

    assert changed == compared


def test_get_changes_reports_unresolved_blocks_and_validates_range():
    service = _service(_anomalous_document())
    s, x = "BOE_CONSOLIDATED", "BOE-A-1"

    log = service.get_changes(s, x, date(2000, 1, 1), date(2030, 1, 1))

    assert log.status is KnowledgeQueryStatus.INCOMPLETE_TIMELINE
    assert log.unresolved_blocks == ("bad", "undated")
    assert [e.block_id for e in log.events] == ["ok"]

    with pytest.raises(ValueError):
        service.get_changes(s, x, D_2020, D_2016)

    assert service.get_changes(
        s, "NOPE", D_2016, D_2020
    ).status is KnowledgeQueryStatus.DOCUMENT_NOT_FOUND


# ------------------------------------------------------------
# Search
# ------------------------------------------------------------


def _search_service():
    boe = _doc(
        "BOE_CONSOLIDATED",
        BOE_ID,
        [("a1", 1, "Plazo de resolución"), ("a2", 2, "Otro")],
        [
            _v("BOE_CONSOLIDATED", BOE_ID, "a1", 1, "Texto sin más.", D_2016, True),
            _v("BOE_CONSOLIDATED", BOE_ID, "a2", 1, "Se fija un plazo breve.", D_2019, True),
        ],
    )

    item = build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id=BOE_ID,
        title="Real Decreto sobre plazos",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
    )

    return _service(_eu_document(), boe, items=MemoryItems(item))


def test_search_orders_by_rank_then_identity_deterministically():
    result = _search_service().search("plazo")

    assert result.temporal_basis == "LATEST_KNOWN"

    kinds = [h.match_kind for h in result.hits]

    assert kinds == sorted(kinds, key=lambda k: {
        KnowledgeSearchMatchKind.IDENTIFIER: 0,
        KnowledgeSearchMatchKind.DOCUMENT_TITLE: 1,
        KnowledgeSearchMatchKind.BLOCK_TITLE: 2,
        KnowledgeSearchMatchKind.CONTENT: 3,
    }[k])

    assert kinds[0] is KnowledgeSearchMatchKind.DOCUMENT_TITLE
    assert kinds[1] is KnowledgeSearchMatchKind.BLOCK_TITLE

    again = _search_service().search("PLAZO")

    assert [
        (h.match_kind, h.provenance.block_canonical_key)
        for h in again.hits
    ] == [
        (h.match_kind, h.provenance.block_canonical_key)
        for h in result.hits
    ]


def test_search_exact_identifier_is_document_level_and_case_insensitive():
    result = _search_service().search(CELEX.lower())

    assert len(result.hits) == 1
    assert result.hits[0].match_kind is KnowledgeSearchMatchKind.IDENTIFIER
    assert result.hits[0].provenance.block_id == ""
    assert result.hits[0].provenance.identifier_scheme == "CELEX"


def test_search_as_of_never_matches_text_from_the_future():
    service = _search_service()

    early = service.search("dos meses", as_of=date(2017, 1, 1))
    late = service.search("dos meses", as_of=D_2018)

    assert early.temporal_basis == "AS_OF"
    assert early.hits == ()
    assert [h.provenance.block_id for h in late.hits] == ["art1"]

    # Bloque aún inexistente en la fecha: excluido y visible.
    excluded = dict(service.search("plazo", as_of=date(2017, 1, 1)).excluded_blocks)

    assert excluded[f"EUR_LEX_CONSOLIDATED:{CELEX}#block:art3"] == "BEFORE_FIRST_EFFECTIVE"

    # El texto antiguo solo es encontrable en su ventana.
    assert service.search("un mes", as_of=date(2017, 1, 1)).hits
    assert not service.search("un mes", as_of=D_2018).hits


def test_search_source_filter_limit_and_truncation():
    service = _search_service()

    only_boe = service.search("plazo", source_key="BOE_CONSOLIDATED")

    assert {h.provenance.source_key for h in only_boe.hits} == {"BOE_CONSOLIDATED"}

    limited = service.search("plazo", limit=1)

    assert len(limited.hits) == 1
    assert limited.truncated is True


def test_search_requires_listing_capability_and_valid_input():
    service = _service(_eu_document(), listing=False)

    with pytest.raises(KnowledgeQueryCapabilityError):
        service.search("plazo")

    # La consulta por identidad sigue funcionando sin listado.
    assert service.get_block(
        "EUR_LEX_CONSOLIDATED", CELEX, "art1", D_2018
    ).resolved

    with pytest.raises(ValueError):
        _search_service().search("   ")

    with pytest.raises(ValueError):
        _search_service().search("x", limit=0)


# ------------------------------------------------------------
# SQLite adapter behind the same contract
# ------------------------------------------------------------


def test_sqlite_adapter_serves_the_same_query_contract_idempotently(tmp_path):
    db = tmp_path / "q.db"

    items = SQLiteKnowledgeRepository(db)
    structures = SQLiteKnowledgeStructureRepository(db)

    items.initialize_schema()
    structures.initialize_schema()

    document = _eu_document()

    item = build_knowledge_item(
        source_key=document.source_key,
        external_id=document.external_id,
        title="RGPD",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text=document.current_content_text,
        source_revision="rev-1",
    )

    items.persist(
        item,
        classify_knowledge_revision(previous=None, current=item),
    )

    first = structures.persist(document)
    second = structures.persist(document)

    assert first.written is True
    assert second.written is False

    service = KnowledgeQueryService(structures, items)

    assert structures.list_document_identities() == (
        ("EUR_LEX_CONSOLIDATED", CELEX),
    )
    assert structures.list_document_identities("BOE") == ()

    p = service.get_evidence("EUR_LEX_CONSOLIDATED", CELEX, "art1", date(2018, 5, 24))

    assert p.effective_from == D_2016
    assert p.document_title == "RGPD"
    assert p.source_revision == "rev-1"

    assert service.search("un mes", as_of=date(2017, 1, 1)).hits
    assert not service.search("un mes").hits

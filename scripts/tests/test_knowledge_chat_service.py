"""WO-KNOW-CHAT-01: KnowledgeChatService con corpus ficticio en memoria.

Normas, identificadores, URLs y expedientes son ficticios. No se lee el
CRM real, no hay red ni proveedor de IA.
"""

from dataclasses import fields
from datetime import date
import socket
import sqlite3

import pytest

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeStructuredDocument,
    build_knowledge_block_version,
    build_knowledge_item,
)
from backend.knowledge.boe_consolidated.validity import (
    resolve_boe_consolidated_validity,
)
from backend.services.knowledge_chat_service import (
    ANSWER_LABEL_DOCUMENTARY,
    SYNTHESIS_NOT_CONFIGURED,
    ErpSessionParityContextAuthorizer,
    KnowledgeChatAnswerKind,
    KnowledgeChatContextAuthorization,
    KnowledgeChatContextStatus,
    KnowledgeChatMode,
    KnowledgeChatRequest,
    KnowledgeChatService,
    KnowledgeChatSession,
    KnowledgeChatValidationError,
    adapt_question,
    parse_as_of,
)
from backend.repositories.knowledge_chat_context_repository import (
    KnowledgeChatExpedientEvent,
    KnowledgeChatExpedientProjection,
)


RD_ID = "BOE-A-2099-90001"
LEY_ID = "BOE-A-2099-90002"
BOE_ONLY_ID = "BOE-A-2099-90003"

RD_URI = "https://example.test/eli/rd/2099/1155"
LEY_URI = "https://example.test/eli/ley/2099/14"
RD_OFFICIAL_URI = "https://example.test/diario/" + RD_ID
BOE_ONLY_URI = "https://example.test/diario/" + BOE_ONLY_ID

OLD = date(2000, 1, 1)
NEW = date(2030, 1, 1)

USER = {"id": 7, "username": "operador.ficticio"}


# ------------------------------------------------------------
# Repositorios en memoria (mismo doble que los tests Knowledge)
# ------------------------------------------------------------


class MemoryStructures:
    def __init__(self, *documents):
        self.calls = 0
        self._documents = {
            (d.source_key, d.external_id): d for d in documents
        }

    def initialize_schema(self):
        pass

    def get_document(self, source_key, external_id):
        self.calls += 1
        return self._documents.get(
            (source_key.strip().upper(), external_id.strip())
        )

    def persist(self, document):
        raise NotImplementedError

    def list_document_identities(self, source_key=None):
        self.calls += 1
        return tuple(
            sorted(
                key
                for key in self._documents
                if source_key is None or key[0] == source_key
            )
        )


class BrokenStructures(MemoryStructures):
    def list_document_identities(self, source_key=None):
        raise sqlite3.OperationalError(
            "no such table: knowledge_blocks (C:/ruta/privada.db)"
        )


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


def _v(source, external_id, block_id, position, text, eff, current):
    return build_knowledge_block_version(
        source_key=source,
        external_id=external_id,
        block_id=block_id,
        version_position=position,
        content_text=text,
        effective_from=eff,
        is_current=current,
    )


def _doc(source, external_id, blocks, versions):
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
                canonical_uri=f"https://example.test/{external_id}/{block_id}",
            )
            for block_id, position, title in blocks
        ),
        versions=tuple(versions),
    )


def _rd_document():
    s, x = "BOE_CONSOLIDATED", RD_ID

    return _doc(
        s,
        x,
        [
            ("a1", 1, "Artículo 1"),
            ("a2", 2, "Artículo 2"),
            ("a2bis", 3, "Artículo 2 bis"),
            ("a20", 4, "Artículo 20"),
        ],
        [
            _v(s, x, "a1", 1,
               "Artículo 1. Objeto. Este real decreto ficticio regula el "
               "procedimiento de prueba de residencia.", OLD, True),
            _v(s, x, "a2", 1,
               "Artículo 2. Plazo. El plazo de resolución es de tres meses.",
               OLD, False),
            _v(s, x, "a2", 2,
               "Artículo 2. Plazo. El plazo de resolución es de seis meses.",
               NEW, True),
            _v(s, x, "a2bis", 1,
               "Artículo 2 bis. Prórroga extraordinaria ficticia.", OLD, True),
            _v(s, x, "a20", 1,
               "Artículo 20. Silencio administrativo ficticio, según el "
               "artículo 2.", OLD, True),
        ],
    )


def _ley_document():
    s, x = "BOE_CONSOLIDATED", LEY_ID

    return _doc(
        s,
        x,
        [("a1", 1, "Artículo 1"), ("a2", 2, "Artículo 2")],
        [
            _v(s, x, "a1", 1,
               "Artículo 1. Ámbito. Ley ficticia de pruebas documentales.",
               OLD, True),
            _v(s, x, "a2", 1,
               "Artículo 2. Requisitos. Los requisitos de arraigo ficticio "
               "son los previstos en esta ley.", OLD, True),
        ],
    )


def _items():
    rd_item = build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id=RD_ID,
        title="Real Decreto 1155/2099, de prueba ficticia",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        canonical_uri=RD_URI,
        source_revision="rev-1",
        metadata={
            "estatus_derogacion": "N",
            "estatus_anulacion": "N",
            "vigencia_agotada": "N",
        },
    )
    # Sin banderas de vigencia: debe resolverse UNKNOWN.
    ley_item = build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id=LEY_ID,
        title="Ley 14/2099, de pruebas ficticias",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        canonical_uri=LEY_URI,
        source_revision="rev-1",
    )
    rd_official = build_knowledge_item(
        source_key="BOE",
        external_id=RD_ID,
        title="Real Decreto 1155/2099 (publicación oficial ficticia)",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="x",
        canonical_uri=RD_OFFICIAL_URI,
        published_on=date(2099, 11, 20),
    )
    boe_only = build_knowledge_item(
        source_key="BOE",
        external_id=BOE_ONLY_ID,
        title="Orden ficticia solo publicada en BOE diario",
        item_kind=KnowledgeItemKind.OFFICIAL_PUBLICATION,
        content_text="x",
        canonical_uri=BOE_ONLY_URI,
        published_on=date(2099, 12, 1),
    )
    return rd_item, ley_item, rd_official, boe_only


def _service(*, structures=None, items=None, **kwargs):
    structures = structures or MemoryStructures(_rd_document(), _ley_document())
    items = items if items is not None else MemoryItems(*_items())
    query = KnowledgeQueryService(
        structures,
        items,
        validity_resolvers={
            "BOE_CONSOLIDATED": resolve_boe_consolidated_validity,
        },
    )
    return KnowledgeChatService(
        query,
        item_repository=items,
        corpus_listing=structures,
        **kwargs,
    )


def _stored_uris():
    uris = {RD_URI, LEY_URI, RD_OFFICIAL_URI, BOE_ONLY_URI}

    for document in (_rd_document(), _ley_document()):
        uris.update(block.canonical_uri for block in document.blocks)

    return uris


def _stored_texts():
    return [
        version.content_text
        for document in (_rd_document(), _ley_document())
        for version in document.versions
    ]


def _ask(service, question, **kwargs):
    kwargs.setdefault("current_user", USER)
    return service.ask_from_input(question=question, **kwargs)


# ------------------------------------------------------------
# Adaptación de la pregunta
# ------------------------------------------------------------


def test_adapt_question_preserves_identifier_disposition_and_article():
    adapted = adapt_question(
        "¿Qué dice el art. 2 bis del Real Decreto 1155/2099 "
        "(boe-a-2099-90001)?"
    )

    assert [t.needle for t in adapted.identifiers] == [RD_ID]
    assert [(t.rank, t.number) for t in adapted.dispositions] == [
        ("real decreto", "1155/2099")
    ]
    assert [t.article for t in adapted.articles] == ["2 bis"]


def test_adapt_question_is_deterministic_and_bounded():
    question = (
        "¿Cuáles son los requisitos del arraigo social, laboral, "
        "familiar, formativo y sociolaboral para extranjeros?"
    )

    first = adapt_question(question)

    assert first == adapt_question(question)
    assert len(first.keywords) <= 4
    assert all(t.needle not in {"cuales", "son", "los"} for t in first.keywords)


def test_adapt_question_ignores_dates_as_dispositions():
    adapted = adapt_question("plazo vigente a 19/11/2026")

    assert adapted.dispositions == ()


# ------------------------------------------------------------
# 1. Identificador y frase natural -> evidencia real con procedencia
# ------------------------------------------------------------


def test_identifier_question_returns_real_citation_with_stored_urls():
    response = _ask(_service(), f"¿Qué es {RD_ID}?")

    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    citation = response.citations[0]
    assert citation.external_id == RD_ID
    assert citation.url == RD_URI
    assert citation.official_publication_url == RD_OFFICIAL_URI
    assert citation.match_kind == "IDENTIFIER"
    assert response.answer_label == ANSWER_LABEL_DOCUMENTARY


def test_natural_question_returns_literal_excerpts_and_stored_urls_only():
    response = _ask(
        _service(),
        "¿Cuáles son los requisitos de arraigo ficticio?",
    )

    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    assert response.citations
    texts = _stored_texts()

    for citation in response.citations:
        assert citation.url in _stored_uris()
        if citation.excerpt:
            stripped = citation.excerpt.strip("…")
            assert any(stripped in text for text in texts)

    assert response.citations[0].external_id == LEY_ID
    assert response.citations[0].block_id == "a2"


def test_article_query_respects_as_of_and_never_leaks_future_versions():
    service = _service()

    past = _ask(
        service,
        "¿Qué dice el artículo 2 del Real Decreto 1155/2099?",
        as_of_text="2010-01-01",
    )
    latest = _ask(
        service,
        "¿Qué dice el artículo 2 del Real Decreto 1155/2099?",
    )

    past_blocks = [c for c in past.citations if c.block_id]
    assert [c.block_id for c in past_blocks] == ["a2"]
    assert "tres meses" in past_blocks[0].excerpt
    assert "seis meses" not in past.documentary_text
    assert past_blocks[0].version_effective_from == OLD
    assert past.temporal_basis == "AS_OF"

    latest_blocks = [c for c in latest.citations if c.block_id]
    assert "seis meses" in latest_blocks[0].excerpt
    assert latest.temporal_basis == "LATEST_KNOWN"
    assert any("última versión conocida" in item for item in latest.limitations)


def test_article_before_any_version_is_reported_missing_not_invented():
    response = _ask(
        _service(),
        "artículo 2 del Real Decreto 1155/2099",
        as_of_text="1990-01-01",
    )

    assert all("meses" not in c.excerpt for c in response.citations)
    assert all(not c.block_id for c in response.citations)
    assert any("artículo 2" in item for item in response.insufficient_evidence)


# ------------------------------------------------------------
# 2. Sin respaldo / corpus vacío -> INSUFFICIENT_EVIDENCE
# ------------------------------------------------------------


def test_unsupported_question_is_insufficient_evidence_without_fabrication():
    response = _ask(
        _service(),
        "¿Cuál es el régimen del impuesto sobre zanahorias marcianas?",
    )

    assert response.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
    assert response.citations == ()
    assert response.documentary_text == ""
    assert response.insufficient_evidence
    assert "http" not in repr(response)


def test_empty_corpus_is_insufficient_evidence():
    service = _service(structures=MemoryStructures(), items=MemoryItems())

    response = _ask(service, "plazo de resolución")

    assert response.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
    assert service.corpus_status().reason


def test_unknown_identifier_never_falls_back_to_other_norms():
    response = _ask(_service(), "plazo de resolución en BOE-A-1900-99999")

    assert response.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
    assert response.citations == ()
    assert any("BOE-A-1900-99999" in m for m in response.insufficient_evidence)


def test_unknown_article_number_is_not_approximated():
    response = _ask(_service(), "artículo 999 del Real Decreto 1155/2099")

    assert all(c.block_id == "" for c in response.citations)
    assert any("999" in m for m in response.insufficient_evidence)


# ------------------------------------------------------------
# 3. Consolidado != publicación oficial; validez desconocida -> UNKNOWN
# ------------------------------------------------------------


def test_consolidated_is_never_presented_as_official_primary():
    response = _ask(_service(), f"{RD_ID}")
    citation = response.citations[0]

    assert citation.source_key == "BOE_CONSOLIDATED"
    assert citation.is_official_primary is False
    assert citation.authority == "OFFICIAL_SECONDARY"
    assert "no es la publicación oficial" in citation.source_label
    assert citation.validity_status == "IN_FORCE"


def test_validity_without_structured_flags_is_unknown():
    response = _ask(_service(), f"{LEY_ID}")

    assert response.citations[0].validity_status == "UNKNOWN"
    assert response.citations[0].validity_end_date is None


def test_boe_daily_record_is_official_primary_with_unknown_validity():
    response = _ask(_service(), f"{BOE_ONLY_ID}")
    citation = response.citations[0]

    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    assert citation.source_key == "BOE"
    assert citation.is_official_primary is True
    assert citation.url == BOE_ONLY_URI
    assert citation.validity_status == "UNKNOWN"


def test_missing_official_publication_is_declared_without_link():
    response = _ask(_service(), f"{LEY_ID}")
    citation = response.citations[0]

    assert citation.official_publication_url == ""
    assert "no está ingerida" in citation.official_publication_note


# ------------------------------------------------------------
# 4. Deduplicación, límites, validación y precisión
# ------------------------------------------------------------


def test_results_are_deduplicated_by_block_and_version():
    response = _ask(_service(), "plazo de resolución plazo resolución")
    keys = [
        (c.source_key, c.external_id, c.block_id, c.version_key)
        for c in response.citations
    ]

    assert len(keys) == len(set(keys))


def test_limit_is_enforced_and_truncation_declared():
    response = _ask(_service(), "artículo ficticio", limit=1)

    assert len(response.citations) == 1
    assert response.truncated is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "¿?"},
        {"question": "x" * 1001},
        {"question": "plazo", "as_of_text": "31-31-2020"},
        {"question": "plazo", "limit": 0},
        {"question": "plazo", "limit": 21},
        {"question": "plazo", "source_key": "EUR_LEX"},
        {"question": "plazo", "mode": "TODOS_LOS_CLIENTES"},
        {"question": None},
    ],
)
def test_malformed_input_is_rejected_before_any_query(kwargs):
    structures = MemoryStructures(_rd_document())
    service = _service(structures=structures)

    response = service.ask_from_input(current_user=USER, **kwargs)

    assert response.kind is KnowledgeChatAnswerKind.REJECTED
    assert response.message
    assert structures.calls == 0


def test_request_contract_rejects_datetime_and_bad_expedient_ids():
    from datetime import datetime

    with pytest.raises(KnowledgeChatValidationError):
        KnowledgeChatRequest(question="plazo", as_of=datetime(2020, 1, 1))

    with pytest.raises(KnowledgeChatValidationError):
        KnowledgeChatRequest(question="plazo", expediente_id=0)

    with pytest.raises(KnowledgeChatValidationError):
        KnowledgeChatRequest(question="plazo", expediente_id=True)


def test_disposition_number_is_matched_precisely():
    service = _service()

    wrong = _ask(service, "¿Qué establece la Ley 4/2099?")
    right = _ask(service, "¿Qué establece la Ley 14/2099?")

    assert wrong.kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
    assert right.citations[0].external_id == LEY_ID


def test_article_two_does_not_match_article_twenty_or_two_bis():
    response = _ask(_service(), "artículo 2 del Real Decreto 1155/2099")

    assert {c.block_id for c in response.citations if c.block_id} == {"a2"}


def test_parse_as_of_formats():
    assert parse_as_of("") is None
    assert parse_as_of("2026-11-19") == date(2026, 11, 19)
    assert parse_as_of("19/11/2026") == date(2026, 11, 19)

    with pytest.raises(KnowledgeChatValidationError):
        parse_as_of("ayer")


# ------------------------------------------------------------
# Corpus no disponible: mensaje claro, sin excepción cruda
# ------------------------------------------------------------


def test_missing_corpus_is_reported_without_raw_exception():
    response = _ask(KnowledgeChatService(None), "plazo de resolución")

    assert response.kind is KnowledgeChatAnswerKind.CORPUS_UNAVAILABLE
    assert response.message


def test_corpus_schema_error_is_contained_and_sanitized():
    service = _service(structures=BrokenStructures())

    response = _ask(service, "plazo de resolución")
    status = service.corpus_status()

    assert response.kind is KnowledgeChatAnswerKind.CORPUS_UNAVAILABLE
    assert "no such table" not in repr(response)
    assert "privada.db" not in repr(response)
    assert status.available is False


# ------------------------------------------------------------
# 7. Sin proveedor IA: sin red ni texto sintético
# ------------------------------------------------------------


def test_no_ai_provider_no_network_and_documentary_fallback(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("acceso de red prohibido")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    service = _service()
    response = _ask(service, "plazo de resolución")

    assert service.synthesis_status == SYNTHESIS_NOT_CONFIGURED
    assert response.synthesis_status == SYNTHESIS_NOT_CONFIGURED
    assert response.interpretation_text == ""
    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY
    assert "No es una respuesta jurídica generada por IA" in (
        response.documentary_text
    )

    # Cada línea citada del texto documental es un extracto literal.
    texts = _stored_texts()
    quoted = [
        line.strip()[1:-1].strip("…")
        for line in response.documentary_text.splitlines()
        if line.strip().startswith("«")
    ]
    assert quoted
    assert all(any(q in t for t in texts) for q in quoted)


def test_service_exposes_no_inference_or_provider_injection():
    names = {f.name for f in fields(KnowledgeChatRequest)}

    assert "allow_inference" not in names
    assert not hasattr(KnowledgeChatService, "infer")


# ------------------------------------------------------------
# 5/6. Contexto CRM: fail-closed y separación de hechos
# ------------------------------------------------------------


class FakeReader:
    def __init__(self, *, active=True, projection=True):
        self.calls = []
        self.active = active
        self.projection = projection

    def is_active_user(self, user_id, username):
        self.calls.append(("is_active_user", user_id, username))
        return self.active

    def find_expedient_id_by_number(self, numero_expediente):
        self.calls.append(("find", numero_expediente))
        return 11 if numero_expediente == "EXP-FICT-0001" else None

    def get_expedient_projection(self, expediente_id):
        self.calls.append(("projection", expediente_id))

        if not self.projection or expediente_id != 11:
            return None

        return KnowledgeChatExpedientProjection(
            expediente_id=11,
            facts=(
                ("numero_expediente", "Número de expediente", "EXP-FICT-0001"),
                ("tipo_expediente", "Tipo de expediente", "ARRAIGO FICTICIO"),
                ("estado_presentacion", "Estado de presentación", "PRESENTADO"),
            ),
            events=(
                KnowledgeChatExpedientEvent(
                    fecha_evento="2099-01-02",
                    tipo_evento="CAMBIO_ESTADO",
                    estado_anterior="PENDIENTE",
                    estado_nuevo="PRESENTADO",
                ),
            ),
        )


def _context_service(reader=None, *, authorizer="default"):
    reader = reader or FakeReader()

    if authorizer == "default":
        authorizer = ErpSessionParityContextAuthorizer(reader)

    return (
        _service(context_reader=reader, context_authorizer=authorizer),
        reader,
    )


def _ask_context(service, **kwargs):
    kwargs.setdefault("mode", KnowledgeChatMode.BOE_WITH_EXPEDIENT)
    kwargs.setdefault("expediente_id", 11)
    kwargs.setdefault("context_confirmed", True)
    return _ask(service, "plazo de resolución", **kwargs)


def test_boe_mode_never_reads_crm():
    service, reader = _context_service()

    response = _ask(service, "plazo de resolución", expediente_id=11)

    assert response.crm_context.status is KnowledgeChatContextStatus.NOT_REQUESTED
    assert reader.calls == []


@pytest.mark.parametrize(
    "overrides, reason_fragment",
    [
        ({"expediente_id": None}, "expediente"),
        ({"context_confirmed": False}, "confirmado"),
        ({"current_user": None}, "sesión"),
        ({"current_user": {"id": "7", "username": "x"}}, "sesión"),
        ({"current_user": {"id": 7, "username": ""}}, "sesión"),
    ],
)
def test_context_denied_before_any_crm_read(overrides, reason_fragment):
    service, reader = _context_service()

    response = _ask_context(service, **overrides)

    assert response.crm_context.status is KnowledgeChatContextStatus.DENIED
    assert reason_fragment in response.crm_context.reason
    assert response.crm_context.facts == ()
    assert reader.calls == []
    # La modalidad BOE se conserva.
    assert response.kind is KnowledgeChatAnswerKind.DOCUMENTARY


def test_context_denied_without_configured_authorizer():
    service = _service()

    response = _ask_context(service)

    assert response.crm_context.status is KnowledgeChatContextStatus.DENIED
    assert response.crm_context.facts == ()


def test_context_denied_for_inactive_identity_without_reading_expedient():
    service, reader = _context_service(FakeReader(active=False))

    response = _ask_context(service)

    assert response.crm_context.status is KnowledgeChatContextStatus.DENIED
    assert [call[0] for call in reader.calls] == ["is_active_user"]


def test_context_granted_separates_crm_facts_from_boe_basis():
    service, reader = _context_service()

    response = _ask_context(service)
    crm = response.crm_context

    assert crm.status is KnowledgeChatContextStatus.GRANTED
    assert crm.label == "HECHOS_CRM"
    assert response.legal_basis_label == "FUNDAMENTO_BOE"
    assert ("Tipo de expediente", "ARRAIGO FICTICIO") in crm.facts
    assert crm.events == ("2099-01-02 · CAMBIO_ESTADO · PENDIENTE → PRESENTADO",)
    assert crm.authorization_basis == ErpSessionParityContextAuthorizer.BASIS
    # Ningún hecho del CRM se cuela en el fundamento BOE.
    assert "EXP-FICT-0001" not in response.documentary_text
    assert "ARRAIGO FICTICIO" not in response.documentary_text
    assert all("EXP-FICT" not in c.excerpt for c in response.citations)
    # Solo se lee el expediente seleccionado.
    assert [c for c in reader.calls if c[0] == "projection"] == [
        ("projection", 11)
    ]


def test_context_not_found_and_unavailable_are_explicit():
    service, _reader = _context_service(FakeReader(projection=False))
    assert (
        _ask_context(service).crm_context.status
        is KnowledgeChatContextStatus.NOT_FOUND
    )

    class ExplodingReader(FakeReader):
        def get_expedient_projection(self, expediente_id):
            raise sqlite3.OperationalError("no such table: expedientes")

    service, _reader = _context_service(ExplodingReader())
    response = _ask_context(service)

    assert response.crm_context.status is KnowledgeChatContextStatus.UNAVAILABLE
    assert "no such table" not in repr(response)


def test_custom_authorizer_denial_is_respected():
    class DenyAll:
        def authorize(self, session, expediente_id):
            return KnowledgeChatContextAuthorization(
                granted=False, reason="Política ficticia de denegación."
            )

    reader = FakeReader()
    service, reader = _context_service(reader, authorizer=DenyAll())

    response = _ask_context(service)

    assert response.crm_context.status is KnowledgeChatContextStatus.DENIED
    assert "projection" not in [c[0] for c in reader.calls]


def test_resolve_expedient_requires_authenticated_active_session():
    service, reader = _context_service()

    anonymous = service.resolve_expedient(None, "EXP-FICT-0001")
    assert anonymous.status is KnowledgeChatContextStatus.DENIED
    assert reader.calls == []

    selection = service.resolve_expedient(USER, "EXP-FICT-0001")
    assert selection.status is KnowledgeChatContextStatus.GRANTED
    assert selection.expediente_id == 11

    partial = service.resolve_expedient(USER, "EXP-FICT")
    assert partial.status is KnowledgeChatContextStatus.NOT_FOUND
    assert partial.expediente_id is None


def test_session_from_current_user_shapes():
    assert KnowledgeChatSession.from_current_user(USER).authenticated
    assert not KnowledgeChatSession.from_current_user(None).authenticated
    assert not KnowledgeChatSession.from_current_user(
        {"id": True, "username": "x"}
    ).authenticated
    assert not KnowledgeChatSession.from_current_user("operador").authenticated

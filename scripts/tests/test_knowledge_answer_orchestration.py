from datetime import date

import pytest

from backend.knowledge import (
    INFERENCE_DISCLAIMER,
    KnowledgeAnswer,
    KnowledgeAnswerMode,
    KnowledgeAnswerOrchestrationService,
    KnowledgeAnswerRequest,
    KnowledgeBlock,
    KnowledgeInferenceOutcome,
    KnowledgeItemKind,
    KnowledgeProvenance,
    KnowledgeQueryService,
    KnowledgeStructuredDocument,
    build_knowledge_block_version,
    build_knowledge_item,
)


CELEX = "32016R0679"

D_2016 = date(2016, 5, 24)
D_2018 = date(2018, 5, 25)


# ------------------------------------------------------------
# Repositorios en memoria (mismo doble usado en
# test_knowledge_query_service.py): prueban independencia de SQLite.
# ------------------------------------------------------------


class MemoryStructures:
    def __init__(self, *documents):
        self._documents = {
            (d.source_key, d.external_id): d for d in documents
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
        [("art1", 1, "Artículo 1"), ("art2", 2, "Artículo 2")],
        [
            _v(
                s, x, "art1", 1,
                "Plazo original de un mes para presentar alegaciones.",
                D_2016, False,
            ),
            _v(
                s, x, "art1", 2,
                "Plazo ampliado a dos meses para presentar alegaciones.",
                D_2018, True,
            ),
            _v(s, x, "art2", 1, "Definiciones estables.", D_2016, True),
        ],
    )


def _eu_item():
    return build_knowledge_item(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id=CELEX,
        title="Reglamento General de Protección de Datos",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="x",
        canonical_uri="https://eur-lex.europa.eu/eli/reg/2016/679",
        source_revision="rev-1",
        language="es",
    )


def _orchestrator(*, inference_provider=None):
    query_service = KnowledgeQueryService(
        MemoryStructures(_eu_document()),
        MemoryItems(_eu_item()),
    )

    return KnowledgeAnswerOrchestrationService(
        query_service,
        inference_provider=inference_provider,
    )


class FakeInferenceProvider:
    def __init__(self, content_text="Respuesta de inferencia.", engine_label="TEST_ENGINE"):
        self._content_text = content_text
        self._engine_label = engine_label
        self.calls = []

    def infer(self, request):
        self.calls.append(request)

        return KnowledgeInferenceOutcome(
            content_text=self._content_text,
            engine_label=self._engine_label,
        )


# ------------------------------------------------------------
# SOURCE_BACKED
# ------------------------------------------------------------


def test_answer_with_retrievable_evidence_is_source_backed_with_provenance():
    answer = _orchestrator().answer(
        KnowledgeAnswerRequest(query="plazo", as_of=D_2018)
    )

    assert answer.mode is KnowledgeAnswerMode.SOURCE_BACKED
    assert answer.citations
    assert all(
        isinstance(citation, KnowledgeProvenance)
        for citation in answer.citations
    )
    assert answer.content_text.strip()
    assert answer.as_of == D_2018
    assert answer.temporal_basis == "AS_OF"
    assert answer.inference_disclaimer == ""
    assert answer.missing_evidence == ()


def test_source_backed_never_matches_text_from_the_future():
    # "dos meses" solo es cierto desde D_2018: en una fecha anterior
    # no debe aparecer evidencia que aún no era vigente.
    answer = _orchestrator().answer(
        KnowledgeAnswerRequest(query="dos meses", as_of=date(2017, 1, 1))
    )

    assert answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE


def test_source_backed_citation_is_real_provenance_from_the_block():
    answer = _orchestrator().answer(
        KnowledgeAnswerRequest(query="plazo ampliado", as_of=D_2018)
    )

    assert answer.mode is KnowledgeAnswerMode.SOURCE_BACKED

    citation = answer.citations[0]
    assert citation.source_key == "EUR_LEX_CONSOLIDATED"
    assert citation.external_id == CELEX
    assert citation.block_id == "art1"
    assert citation.effective_from == D_2018


# ------------------------------------------------------------
# INSUFFICIENT_EVIDENCE
# ------------------------------------------------------------


def test_answer_without_matches_is_insufficient_evidence_by_default():
    answer = _orchestrator().answer(
        KnowledgeAnswerRequest(query="xenomorfo inexistente")
    )

    assert answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert answer.content_text == ""
    assert answer.citations == ()
    assert answer.reason.strip()
    assert answer.missing_evidence
    assert "xenomorfo inexistente" in answer.missing_evidence[0]


def test_allow_inference_without_configured_provider_stays_insufficient_evidence():
    answer = _orchestrator(inference_provider=None).answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=True
        )
    )

    assert answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert any(
        "no hay un knowledgeinferenceprovider".lower() in entry.lower()
        or "no configurado" in entry.lower()
        for entry in answer.missing_evidence
    )


def test_configured_provider_without_opt_in_stays_insufficient_evidence():
    provider = FakeInferenceProvider()

    answer = _orchestrator(inference_provider=provider).answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=False
        )
    )

    assert answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert provider.calls == []


# ------------------------------------------------------------
# INFERENCE_ONLY
# ------------------------------------------------------------


def test_inference_only_requires_explicit_opt_in_and_configured_provider():
    provider = FakeInferenceProvider(
        content_text="Opinión generada sin respaldo documental.",
        engine_label="TEST_ENGINE",
    )

    answer = _orchestrator(inference_provider=provider).answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=True
        )
    )

    assert answer.mode is KnowledgeAnswerMode.INFERENCE_ONLY
    assert len(provider.calls) == 1
    assert answer.content_text == "Opinión generada sin respaldo documental."
    assert answer.citations == ()
    assert answer.inference_disclaimer == INFERENCE_DISCLAIMER
    assert answer.engine_label == "TEST_ENGINE"


def test_inference_only_is_not_invoked_when_evidence_is_retrievable():
    provider = FakeInferenceProvider()

    answer = _orchestrator(inference_provider=provider).answer(
        KnowledgeAnswerRequest(
            query="plazo", as_of=D_2018, allow_inference=True
        )
    )

    assert answer.mode is KnowledgeAnswerMode.SOURCE_BACKED
    assert provider.calls == []


# ------------------------------------------------------------
# Invariantes estructurales de KnowledgeAnswer (fail-closed)
# ------------------------------------------------------------


def _provenance():
    return KnowledgeProvenance(
        source_key="EUR_LEX_CONSOLIDATED",
        provider="EUR_LEX",
        authority="OFFICIAL_PRIMARY",
        identifier_scheme="CELEX",
        external_id=CELEX,
        document_canonical_key=f"EUR_LEX_CONSOLIDATED:{CELEX}",
    )


def test_source_backed_requires_non_empty_citations():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.SOURCE_BACKED,
            query="q",
            source_key=None,
            as_of=None,
            content_text="texto",
            citations=(),
        )


def test_source_backed_cannot_carry_inference_marks():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.SOURCE_BACKED,
            query="q",
            source_key=None,
            as_of=None,
            content_text="texto",
            citations=(_provenance(),),
            inference_disclaimer=INFERENCE_DISCLAIMER,
        )


def test_insufficient_evidence_cannot_fabricate_content():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
            query="q",
            source_key=None,
            as_of=None,
            content_text="respuesta inventada",
            reason="motivo",
            missing_evidence=("falta algo",),
        )


def test_insufficient_evidence_requires_reason_and_missing_evidence():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
            query="q",
            source_key=None,
            as_of=None,
            reason="",
            missing_evidence=(),
        )


def test_inference_only_cannot_masquerade_as_source_backed_with_citations():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INFERENCE_ONLY,
            query="q",
            source_key=None,
            as_of=None,
            content_text="texto inferido",
            citations=(_provenance(),),
            inference_disclaimer=INFERENCE_DISCLAIMER,
            engine_label="TEST_ENGINE",
        )


def test_inference_only_requires_disclaimer_and_engine_label():
    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INFERENCE_ONLY,
            query="q",
            source_key=None,
            as_of=None,
            content_text="texto inferido",
            inference_disclaimer="",
            engine_label="TEST_ENGINE",
        )

    with pytest.raises(ValueError):
        KnowledgeAnswer(
            mode=KnowledgeAnswerMode.INFERENCE_ONLY,
            query="q",
            source_key=None,
            as_of=None,
            content_text="texto inferido",
            inference_disclaimer=INFERENCE_DISCLAIMER,
            engine_label="",
        )


# ------------------------------------------------------------
# Request validation
# ------------------------------------------------------------


def test_request_rejects_blank_query():
    with pytest.raises(ValueError):
        KnowledgeAnswerRequest(query="   ")


def test_request_rejects_datetime_as_of():
    from datetime import datetime

    with pytest.raises(TypeError):
        KnowledgeAnswerRequest(query="q", as_of=datetime(2020, 1, 1))


def test_request_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        KnowledgeAnswerRequest(query="q", limit=0)


def test_service_rejects_non_query_service_dependency():
    with pytest.raises(TypeError):
        KnowledgeAnswerOrchestrationService(object())


def test_service_rejects_inference_provider_without_infer_method():
    with pytest.raises(TypeError):
        _orchestrator(inference_provider=object())

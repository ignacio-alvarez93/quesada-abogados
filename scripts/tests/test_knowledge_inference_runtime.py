from datetime import date, datetime

import pytest

from backend.knowledge import (
    INFERENCE_DISCLAIMER,
    KnowledgeAnswerMode,
    KnowledgeAnswerRequest,
    KnowledgeBlock,
    KnowledgeGovernedInferenceProvider,
    KnowledgeInferenceAuditEnvelope,
    KnowledgeInferenceOutcome,
    KnowledgeInferencePolicyDecision,
    KnowledgeInferencePolicyService,
    KnowledgeInferenceProviderRegistry,
    KnowledgeInferenceRuntime,
    KnowledgeInferenceRuntimeResult,
    KnowledgeItemKind,
    KnowledgeQueryService,
    KnowledgeStructuredDocument,
    build_inference_provider_descriptor,
    build_knowledge_block_version,
    build_knowledge_item,
    compute_knowledge_inference_request_fingerprint,
)


CELEX = "32016R0679"
D_2016 = date(2016, 5, 24)
D_2018 = date(2018, 5, 25)


# ------------------------------------------------------------
# Dobles en memoria (mismo patrón usado en
# test_knowledge_answer_orchestration.py).
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


def _eu_document():
    s, x = "EUR_LEX_CONSOLIDATED", CELEX

    return KnowledgeStructuredDocument(
        source_key=s,
        external_id=x,
        blocks=(
            KnowledgeBlock(
                source_key=s,
                external_id=x,
                block_id="art1",
                position=1,
                title="Artículo 1",
                canonical_uri="https://example.test/art1",
            ),
        ),
        versions=(
            _v(
                s, x, "art1", 1,
                "Plazo ampliado a dos meses para presentar alegaciones.",
                D_2018, True,
            ),
        ),
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


def _query_service():
    return KnowledgeQueryService(
        MemoryStructures(_eu_document()),
        MemoryItems(_eu_item()),
    )


class FakeRawProvider:
    def __init__(self, content_text="Opinión generada.", engine_label="TEST_ENGINE"):
        self._content_text = content_text
        self._engine_label = engine_label
        self.calls = []

    def infer(self, request):
        self.calls.append(request)

        return KnowledgeInferenceOutcome(
            content_text=self._content_text,
            engine_label=self._engine_label,
        )


def _governed_provider(*, enabled=False, provider=None, provider_key="acme-llm"):
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key=provider_key, engine_label="ACME_LLM"
        )
    )

    if enabled:
        registry.enable(provider_key)

    policy = KnowledgeInferencePolicyService(registry)

    return KnowledgeGovernedInferenceProvider(
        provider_key=provider_key,
        provider=provider or FakeRawProvider(),
        policy_service=policy,
    )


def _runtime(*, enabled=False, provider=None, provider_key="acme-llm"):
    governed = _governed_provider(
        enabled=enabled, provider=provider, provider_key=provider_key
    )

    return KnowledgeInferenceRuntime(_query_service(), governed)


# ------------------------------------------------------------
# Construction guards
# ------------------------------------------------------------


def test_runtime_rejects_non_query_service_dependency():
    governed = _governed_provider(enabled=True)

    with pytest.raises(TypeError):
        KnowledgeInferenceRuntime(object(), governed)


def test_runtime_rejects_non_governed_provider_dependency():
    with pytest.raises(TypeError):
        KnowledgeInferenceRuntime(_query_service(), object())


def test_runtime_rejects_non_request_argument():
    runtime = _runtime(enabled=True)

    with pytest.raises(TypeError):
        runtime.answer(object())


def test_runtime_rejects_non_datetime_requested_at():
    runtime = _runtime(enabled=True)

    with pytest.raises(TypeError):
        runtime.answer(
            KnowledgeAnswerRequest(query="plazo"),
            requested_at="not-a-datetime",
        )


# ------------------------------------------------------------
# SOURCE_BACKED: inference never invoked
# ------------------------------------------------------------


def test_source_backed_answers_never_invoke_inference():
    provider = FakeRawProvider()
    runtime = _runtime(enabled=True, provider=provider)

    result = runtime.answer(
        KnowledgeAnswerRequest(
            query="plazo", as_of=D_2018, allow_inference=True
        )
    )

    assert isinstance(result, KnowledgeInferenceRuntimeResult)
    assert result.answer.mode is KnowledgeAnswerMode.SOURCE_BACKED
    assert result.answer.citations
    assert provider.calls == []
    assert result.audit.outcome_type == "SOURCE_BACKED"
    assert result.audit.policy_decision.allowed is True


# ------------------------------------------------------------
# INSUFFICIENT_EVIDENCE: no silent fallback to inference
# ------------------------------------------------------------


def test_without_opt_in_stays_insufficient_evidence_and_never_calls_provider():
    provider = FakeRawProvider()
    runtime = _runtime(enabled=True, provider=provider)

    result = runtime.answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=False
        )
    )

    assert result.answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert provider.calls == []
    assert result.audit.policy_decision.allowed is False


def test_disabled_provider_fails_closed_to_insufficient_evidence():
    provider = FakeRawProvider()
    runtime = _runtime(enabled=False, provider=provider)

    result = runtime.answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=True
        )
    )

    assert result.answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert provider.calls == []
    assert result.audit.policy_decision.allowed is False
    assert "deshabilitado" in result.audit.policy_decision.reason.lower()
    assert any(
        "denegada por política" in entry.lower()
        for entry in result.answer.missing_evidence
    )


def test_unregistered_provider_fails_closed_to_insufficient_evidence():
    registry = KnowledgeInferenceProviderRegistry()
    policy = KnowledgeInferencePolicyService(registry)
    provider = FakeRawProvider()

    governed = KnowledgeGovernedInferenceProvider(
        provider_key="ghost",
        provider=provider,
        policy_service=policy,
    )
    runtime = KnowledgeInferenceRuntime(_query_service(), governed)

    result = runtime.answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=True
        )
    )

    assert result.answer.mode is KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE
    assert provider.calls == []
    assert "no registrado" in result.audit.policy_decision.reason.lower()


# ------------------------------------------------------------
# INFERENCE_ONLY: governed, disclaimed, zero citations
# ------------------------------------------------------------


def test_enabled_provider_with_opt_in_produces_inference_only():
    provider = FakeRawProvider(
        content_text="Respuesta de inferencia gobernada.",
        engine_label="ACME_LLM",
    )
    runtime = _runtime(enabled=True, provider=provider)

    result = runtime.answer(
        KnowledgeAnswerRequest(
            query="xenomorfo inexistente", allow_inference=True
        )
    )

    answer = result.answer
    assert answer.mode is KnowledgeAnswerMode.INFERENCE_ONLY
    assert answer.citations == ()
    assert answer.inference_disclaimer == INFERENCE_DISCLAIMER
    assert answer.engine_label == "ACME_LLM"
    assert len(provider.calls) == 1

    assert result.audit.outcome_type == "INFERENCE_ONLY"
    assert result.audit.policy_decision.allowed is True
    assert result.audit.provider_key == "ACME-LLM"


# ------------------------------------------------------------
# Audit envelope: deterministic identity, explicit decision,
# no fabricated timestamps.
# ------------------------------------------------------------


def test_audit_envelope_is_attached_to_every_outcome():
    runtime = _runtime(enabled=True)

    result = runtime.answer(KnowledgeAnswerRequest(query="plazo", as_of=D_2018))

    assert isinstance(result.audit, KnowledgeInferenceAuditEnvelope)
    assert isinstance(
        result.audit.policy_decision, KnowledgeInferencePolicyDecision
    )
    assert result.audit.as_of == D_2018
    assert result.audit.requested_at is None


def test_audit_envelope_requested_at_only_set_when_explicitly_injected():
    runtime = _runtime(enabled=True)
    now = datetime(2024, 1, 1, 12, 0, 0)

    result = runtime.answer(
        KnowledgeAnswerRequest(query="plazo", as_of=D_2018),
        requested_at=now,
    )

    assert result.audit.requested_at == now


def test_request_fingerprint_is_deterministic_for_same_inputs():
    request_a = KnowledgeAnswerRequest(query="plazo", as_of=D_2018)
    request_b = KnowledgeAnswerRequest(query="plazo", as_of=D_2018)

    fingerprint_a = compute_knowledge_inference_request_fingerprint(
        request_a, "acme-llm"
    )
    fingerprint_b = compute_knowledge_inference_request_fingerprint(
        request_b, "acme-llm"
    )

    assert fingerprint_a == fingerprint_b


def test_request_fingerprint_changes_with_query_or_provider():
    base = KnowledgeAnswerRequest(query="plazo", as_of=D_2018)
    other_query = KnowledgeAnswerRequest(query="otra consulta", as_of=D_2018)

    fingerprint_base = compute_knowledge_inference_request_fingerprint(
        base, "acme-llm"
    )

    assert fingerprint_base != compute_knowledge_inference_request_fingerprint(
        other_query, "acme-llm"
    )
    assert fingerprint_base != compute_knowledge_inference_request_fingerprint(
        base, "other-provider"
    )


def test_two_runtime_calls_with_same_request_produce_same_fingerprint():
    runtime = _runtime(enabled=True)

    first = runtime.answer(KnowledgeAnswerRequest(query="plazo", as_of=D_2018))
    second = runtime.answer(KnowledgeAnswerRequest(query="plazo", as_of=D_2018))

    assert first.audit.query_fingerprint == second.audit.query_fingerprint


# ------------------------------------------------------------
# KnowledgeInferenceAuditEnvelope: structural invariants
# ------------------------------------------------------------


def test_audit_envelope_requires_non_blank_query_fingerprint():
    decision = KnowledgeInferencePolicyDecision(
        provider_key="acme", allowed=True, reason="motivo"
    )

    with pytest.raises(ValueError):
        KnowledgeInferenceAuditEnvelope(
            provider_key="acme",
            policy_decision=decision,
            query_fingerprint="   ",
            as_of=None,
            outcome_type="SOURCE_BACKED",
        )


def test_audit_envelope_rejects_unknown_outcome_type():
    decision = KnowledgeInferencePolicyDecision(
        provider_key="acme", allowed=True, reason="motivo"
    )

    with pytest.raises(ValueError):
        KnowledgeInferenceAuditEnvelope(
            provider_key="acme",
            policy_decision=decision,
            query_fingerprint="fingerprint",
            as_of=None,
            outcome_type="NOT_A_REAL_OUTCOME",
        )


def test_audit_envelope_rejects_non_policy_decision():
    with pytest.raises(TypeError):
        KnowledgeInferenceAuditEnvelope(
            provider_key="acme",
            policy_decision=object(),
            query_fingerprint="fingerprint",
            as_of=None,
            outcome_type="SOURCE_BACKED",
        )


def test_audit_envelope_rejects_non_datetime_requested_at():
    decision = KnowledgeInferencePolicyDecision(
        provider_key="acme", allowed=True, reason="motivo"
    )

    with pytest.raises(TypeError):
        KnowledgeInferenceAuditEnvelope(
            provider_key="acme",
            policy_decision=decision,
            query_fingerprint="fingerprint",
            as_of=None,
            outcome_type="SOURCE_BACKED",
            requested_at="not-a-datetime",
        )

import pytest

from backend.knowledge import (
    BOE_SOURCE,
    KnowledgeAnswerRequest,
    KnowledgeGovernedInferenceProvider,
    KnowledgeInferenceOutcome,
    KnowledgeInferencePolicyDecision,
    KnowledgeInferencePolicyDenied,
    KnowledgeInferencePolicyService,
    KnowledgeInferenceProviderDescriptor,
    KnowledgeInferenceProviderRegistry,
    build_inference_provider_descriptor,
    knowledge_source_exists,
    list_knowledge_sources,
    normalize_inference_provider_key,
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


def _request(*, allow_inference=True):
    return KnowledgeAnswerRequest(
        query="xenomorfo inexistente",
        allow_inference=allow_inference,
    )


# ------------------------------------------------------------
# Stable key / descriptor
# ------------------------------------------------------------


def test_normalize_inference_provider_key_rejects_blank():
    with pytest.raises(ValueError):
        normalize_inference_provider_key("   ")


def test_normalize_inference_provider_key_is_stable_and_uppercased():
    assert normalize_inference_provider_key(" acme-llm ") == "ACME-LLM"
    assert normalize_inference_provider_key("acme-llm") == "ACME-LLM"


def test_descriptor_disabled_by_default():
    descriptor = build_inference_provider_descriptor(
        key="acme-llm",
        engine_label="ACME_LLM",
    )

    assert descriptor.key == "ACME-LLM"
    assert descriptor.enabled is False


def test_descriptor_rejects_blank_engine_label():
    with pytest.raises(ValueError):
        KnowledgeInferenceProviderDescriptor(key="acme", engine_label="   ")


def test_descriptor_cannot_reuse_a_canonical_knowledge_source_key():
    assert knowledge_source_exists(BOE_SOURCE.key)

    with pytest.raises(ValueError):
        KnowledgeInferenceProviderDescriptor(
            key=BOE_SOURCE.key,
            engine_label="SHOULD_NOT_WORK",
        )


# ------------------------------------------------------------
# Registry: enabled/disabled state
# ------------------------------------------------------------


def test_registry_starts_empty_and_registers_disabled_provider():
    registry = KnowledgeInferenceProviderRegistry()
    descriptor = build_inference_provider_descriptor(
        key="acme-llm", engine_label="ACME_LLM"
    )

    assert registry.is_registered("acme-llm") is False

    registry.register(descriptor)

    assert registry.is_registered("acme-llm") is True
    assert registry.is_enabled("acme-llm") is False


def test_registry_get_unregistered_provider_raises():
    registry = KnowledgeInferenceProviderRegistry()

    with pytest.raises(KeyError):
        registry.get("missing")

    assert registry.try_get("missing") is None


def test_registry_enable_and_disable_round_trip():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )

    enabled = registry.enable("acme-llm")
    assert enabled.enabled is True
    assert registry.is_enabled("acme-llm") is True

    disabled = registry.disable("acme-llm")
    assert disabled.enabled is False
    assert registry.is_enabled("acme-llm") is False


def test_registry_list_descriptors_filters_enabled_only():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(key="a", engine_label="A")
    )
    registry.register(
        build_inference_provider_descriptor(key="b", engine_label="B")
    )
    registry.enable("b")

    assert [d.key for d in registry.list_descriptors()] == ["A", "B"]
    assert [
        d.key for d in registry.list_descriptors(enabled_only=True)
    ] == ["B"]


def test_registering_inference_provider_has_no_effect_on_source_registry():
    before = list_knowledge_sources(enabled_only=False)

    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )
    registry.enable("acme-llm")

    after = list_knowledge_sources(enabled_only=False)

    assert before == after
    assert knowledge_source_exists("acme-llm") is False


# ------------------------------------------------------------
# Policy: deterministic decision + explicit denial reason
# ------------------------------------------------------------


def test_policy_service_rejects_non_registry_dependency():
    with pytest.raises(TypeError):
        KnowledgeInferencePolicyService(object())


def test_policy_denies_without_opt_in():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM", enabled=True
        )
    )
    policy = KnowledgeInferencePolicyService(registry)

    decision = policy.decide("acme-llm", allow_inference=False)

    assert isinstance(decision, KnowledgeInferencePolicyDecision)
    assert decision.allowed is False
    assert decision.reason.strip()


def test_policy_denies_unregistered_provider():
    registry = KnowledgeInferenceProviderRegistry()
    policy = KnowledgeInferencePolicyService(registry)

    decision = policy.decide("ghost", allow_inference=True)

    assert decision.allowed is False
    assert "no registrado" in decision.reason.lower()


def test_policy_denies_disabled_by_default_provider():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )
    policy = KnowledgeInferencePolicyService(registry)

    decision = policy.decide("acme-llm", allow_inference=True)

    assert decision.allowed is False
    assert "deshabilitado" in decision.reason.lower()


def test_policy_allows_enabled_provider_with_opt_in():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )
    registry.enable("acme-llm")
    policy = KnowledgeInferencePolicyService(registry)

    decision = policy.decide("acme-llm", allow_inference=True)

    assert decision.allowed is True
    assert decision.reason.strip()


def test_policy_decision_is_deterministic_for_same_state():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM", enabled=True
        )
    )
    policy = KnowledgeInferencePolicyService(registry)

    first = policy.decide("acme-llm", allow_inference=True)
    second = policy.decide("acme-llm", allow_inference=True)

    assert first == second


def test_policy_decision_requires_explicit_reason():
    with pytest.raises(ValueError):
        KnowledgeInferencePolicyDecision(
            provider_key="acme", allowed=False, reason=""
        )


# ------------------------------------------------------------
# Governed provider: fail-closed adapter over the existing port
# ------------------------------------------------------------


def test_governed_provider_rejects_non_provider_dependency():
    registry = KnowledgeInferenceProviderRegistry()
    policy = KnowledgeInferencePolicyService(registry)

    with pytest.raises(TypeError):
        KnowledgeGovernedInferenceProvider(
            provider_key="acme-llm",
            provider=object(),
            policy_service=policy,
        )


def test_governed_provider_denies_when_disabled_by_default():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )
    policy = KnowledgeInferencePolicyService(registry)
    raw_provider = FakeRawProvider()

    governed = KnowledgeGovernedInferenceProvider(
        provider_key="acme-llm",
        provider=raw_provider,
        policy_service=policy,
    )

    with pytest.raises(KnowledgeInferencePolicyDenied):
        governed.infer(_request(allow_inference=True))

    assert raw_provider.calls == []


def test_governed_provider_denies_without_opt_in_even_if_enabled():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM", enabled=True
        )
    )
    policy = KnowledgeInferencePolicyService(registry)
    raw_provider = FakeRawProvider()

    governed = KnowledgeGovernedInferenceProvider(
        provider_key="acme-llm",
        provider=raw_provider,
        policy_service=policy,
    )

    with pytest.raises(KnowledgeInferencePolicyDenied):
        governed.infer(_request(allow_inference=False))

    assert raw_provider.calls == []


def test_governed_provider_delegates_only_when_enabled_and_opted_in():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM"
        )
    )
    registry.enable("acme-llm")
    policy = KnowledgeInferencePolicyService(registry)
    raw_provider = FakeRawProvider(
        content_text="Respuesta de inferencia gobernada.",
        engine_label="ACME_LLM",
    )

    governed = KnowledgeGovernedInferenceProvider(
        provider_key="acme-llm",
        provider=raw_provider,
        policy_service=policy,
    )

    request = _request(allow_inference=True)
    outcome = governed.infer(request)

    assert len(raw_provider.calls) == 1
    assert raw_provider.calls[0] is request
    assert outcome.content_text == "Respuesta de inferencia gobernada."
    assert outcome.engine_label == "ACME_LLM"


def test_governed_provider_rejects_non_answer_request():
    registry = KnowledgeInferenceProviderRegistry()
    registry.register(
        build_inference_provider_descriptor(
            key="acme-llm", engine_label="ACME_LLM", enabled=True
        )
    )
    policy = KnowledgeInferencePolicyService(registry)

    governed = KnowledgeGovernedInferenceProvider(
        provider_key="acme-llm",
        provider=FakeRawProvider(),
        policy_service=policy,
    )

    with pytest.raises(TypeError):
        governed.infer(object())

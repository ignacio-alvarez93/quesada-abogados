"""Frontera de aplicación gobernada para invocar inferencia externa.

Construye sobre piezas ya existentes, sin reimplementarlas:

``KnowledgeInferenceProvider`` / ``KnowledgeAnswerOrchestrationService``
    (``answer_orchestration.py``) deciden SIEMPRE si corresponde
    producir SOURCE_BACKED, INSUFFICIENT_EVIDENCE o INFERENCE_ONLY.

``KnowledgeGovernedInferenceProvider`` / ``KnowledgeInferencePolicyService``
    (``inference_governance.py``) deciden de forma determinista si una
    invocación de inferencia está permitida (proveedor registrado,
    habilitado, opt-in explícito), con motivo explícito en cada
    decisión.

Este módulo añade la única frontera de aplicación por la que puede
invocarse un ``KnowledgeInferenceProvider`` inyectado:

- envuelve ``KnowledgeAnswerOrchestrationService`` con un
  ``KnowledgeGovernedInferenceProvider`` ya construido por el
  llamador, sin modificar ninguno de los dos módulos;
- nunca permite que una denegación de política se escape como una
  excepción no controlada: la convierte en INSUFFICIENT_EVIDENCE con
  el motivo explícito de la denegación (fail-closed, nunca un
  fallback silencioso hacia una respuesta fabricada);
- produce, junto a cada ``KnowledgeAnswer``, un sobre de auditoría
  (``KnowledgeInferenceAuditEnvelope``) con identidad determinista de
  la petición, la decisión de política aplicada, el contexto temporal
  y el tipo de resultado;
- no incorpora marca de tiempo alguna salvo que el llamador la inyecte
  explícitamente (``requested_at``): este módulo nunca lee el reloj
  del sistema, para permanecer determinista y verificable en tests;
- no implementa ningún SDK/proveedor de IA concreto ni red: sigue
  siendo gobernanza y orquestación pura sobre los puertos existentes;
- no escribe en ``KnowledgeCatalog``, revisiones de promoción ni en el
  corpus Knowledge. ``KnowledgeHumanReviewGateService`` permanece
  fuera del alcance de este módulo y no se referencia aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .answer_orchestration import (
    KnowledgeAnswer,
    KnowledgeAnswerMode,
    KnowledgeAnswerOrchestrationService,
    KnowledgeAnswerRequest,
)
from .inference_governance import (
    KnowledgeGovernedInferenceProvider,
    KnowledgeInferencePolicyDecision,
    KnowledgeInferencePolicyDenied,
    normalize_inference_provider_key,
)
from .items import compute_content_sha256
from .query import KnowledgeQueryService


def compute_knowledge_inference_request_fingerprint(
    request: KnowledgeAnswerRequest,
    provider_key: str,
) -> str:
    """Huella SHA-256 determinista de una petición de respuesta.

    Misma consulta + misma fuente + misma fecha ``as_of`` + mismo
    límite + mismo opt-in de inferencia + mismo proveedor siempre
    produce la misma huella. No depende del reloj del sistema ni de
    ningún estado mutable.
    """

    if not isinstance(request, KnowledgeAnswerRequest):
        raise TypeError("request debe ser KnowledgeAnswerRequest")

    key = normalize_inference_provider_key(provider_key)

    canonical = "|".join(
        [
            key,
            request.query,
            request.source_key or "",
            request.as_of.isoformat() if request.as_of else "",
            str(request.limit),
            str(request.allow_inference),
        ]
    )

    return compute_content_sha256(canonical)


# ============================================================
# AUDIT ENVELOPE
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeInferenceAuditEnvelope:
    """Registro estructurado y determinista de una invocación gobernada.

    ``requested_at`` permanece ``None`` salvo que el llamador lo
    inyecte explícitamente: este sobre nunca fabrica una marca de
    tiempo por su cuenta.
    """

    provider_key: str
    policy_decision: KnowledgeInferencePolicyDecision
    query_fingerprint: str
    as_of: date | None
    outcome_type: str
    requested_at: datetime | None = None

    def __post_init__(self) -> None:
        provider_key = normalize_inference_provider_key(self.provider_key)
        object.__setattr__(self, "provider_key", provider_key)

        if not isinstance(
            self.policy_decision, KnowledgeInferencePolicyDecision
        ):
            raise TypeError(
                "KnowledgeInferenceAuditEnvelope.policy_decision debe "
                "ser KnowledgeInferencePolicyDecision"
            )

        query_fingerprint = str(self.query_fingerprint or "").strip()

        if not query_fingerprint:
            raise ValueError(
                "KnowledgeInferenceAuditEnvelope.query_fingerprint no "
                "puede estar vacío"
            )

        object.__setattr__(self, "query_fingerprint", query_fingerprint)

        if self.as_of is not None and (
            not isinstance(self.as_of, date)
            or isinstance(self.as_of, datetime)
        ):
            raise TypeError(
                "KnowledgeInferenceAuditEnvelope.as_of debe ser "
                "datetime.date"
            )

        outcome_type = str(self.outcome_type or "").strip()
        valid_outcomes = {mode.value for mode in KnowledgeAnswerMode}

        if outcome_type not in valid_outcomes:
            raise ValueError(
                "KnowledgeInferenceAuditEnvelope.outcome_type debe ser "
                f"uno de {sorted(valid_outcomes)}"
            )

        object.__setattr__(self, "outcome_type", outcome_type)

        if self.requested_at is not None and not isinstance(
            self.requested_at, datetime
        ):
            raise TypeError(
                "KnowledgeInferenceAuditEnvelope.requested_at debe ser "
                "datetime.datetime cuando se inyecta"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeInferenceRuntimeResult:
    """Respuesta provider-neutral junto a su sobre de auditoría."""

    answer: KnowledgeAnswer
    audit: KnowledgeInferenceAuditEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.answer, KnowledgeAnswer):
            raise TypeError(
                "KnowledgeInferenceRuntimeResult.answer debe ser "
                "KnowledgeAnswer"
            )

        if not isinstance(self.audit, KnowledgeInferenceAuditEnvelope):
            raise TypeError(
                "KnowledgeInferenceRuntimeResult.audit debe ser "
                "KnowledgeInferenceAuditEnvelope"
            )


# ============================================================
# RUNTIME
# ============================================================


class KnowledgeInferenceRuntime:
    """Única frontera de aplicación para invocar inferencia gobernada.

    Envuelve ``KnowledgeAnswerOrchestrationService`` con el
    ``KnowledgeGovernedInferenceProvider`` recibido: el llamador
    decide qué proveedor concreto, registro y política se aplican
    construyendo ese objeto con ``inference_governance.py``; este
    runtime no conoce proveedores de IA concretos ni mantiene su
    propio registro.

    Una instancia de este runtime queda ligada a un único proveedor de
    inferencia (el envuelto en ``governed_provider``). Cambiar de
    proveedor es construir un nuevo ``KnowledgeGovernedInferenceProvider``
    y un nuevo runtime, nunca mutar este objeto.
    """

    def __init__(
        self,
        query_service: KnowledgeQueryService,
        governed_provider: KnowledgeGovernedInferenceProvider,
    ) -> None:
        if not isinstance(query_service, KnowledgeQueryService):
            raise TypeError(
                "query_service debe ser KnowledgeQueryService"
            )

        if not isinstance(
            governed_provider, KnowledgeGovernedInferenceProvider
        ):
            raise TypeError(
                "governed_provider debe ser "
                "KnowledgeGovernedInferenceProvider"
            )

        self._query_service = query_service
        self._governed_provider = governed_provider
        self._orchestrator = KnowledgeAnswerOrchestrationService(
            query_service,
            inference_provider=governed_provider,
        )

    @property
    def provider_key(self) -> str:
        return self._governed_provider.provider_key

    def answer(
        self,
        request: KnowledgeAnswerRequest,
        *,
        requested_at: datetime | None = None,
    ) -> KnowledgeInferenceRuntimeResult:
        if not isinstance(request, KnowledgeAnswerRequest):
            raise TypeError("request debe ser KnowledgeAnswerRequest")

        if requested_at is not None and not isinstance(
            requested_at, datetime
        ):
            raise TypeError(
                "requested_at debe ser datetime.datetime cuando se "
                "inyecta"
            )

        provider_key = self._governed_provider.provider_key

        # Decisión de política evaluada una vez: se reutiliza tanto
        # para el sobre de auditoría como criterio determinista de lo
        # que el proveedor gobernado ya aplicará internamente. Nunca
        # invoca al proveedor envuelto por sí misma.
        decision = self._governed_provider.policy_service.decide(
            provider_key,
            allow_inference=request.allow_inference,
        )

        try:
            answer = self._orchestrator.answer(request)
        except KnowledgeInferencePolicyDenied:
            # Fail-closed explícito: una denegación de política nunca
            # se propaga como fallo no controlado ni se convierte en
            # un fallback silencioso. Se expresa como la misma
            # respuesta que produciría la orquestación sin proveedor
            # configurado: INSUFFICIENT_EVIDENCE con motivo explícito.
            answer = KnowledgeAnswer(
                mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
                query=request.query,
                source_key=request.source_key,
                as_of=request.as_of,
                missing_evidence=(
                    "Inferencia denegada por política de gobernanza: "
                    f"{decision.reason}",
                ),
                reason=(
                    "Se solicitó inferencia pero la política de "
                    "gobernanza denegó la invocación del proveedor; "
                    "no se fabrica una respuesta."
                ),
            )

        audit = KnowledgeInferenceAuditEnvelope(
            provider_key=provider_key,
            policy_decision=decision,
            query_fingerprint=(
                compute_knowledge_inference_request_fingerprint(
                    request, provider_key
                )
            ),
            as_of=request.as_of,
            outcome_type=answer.mode.value,
            requested_at=requested_at,
        )

        return KnowledgeInferenceRuntimeResult(answer=answer, audit=audit)

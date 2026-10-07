"""Gobernanza provider-neutral de proveedores de inferencia externa.

Construye sobre los contratos ya existentes:

``KnowledgeInferenceProvider`` (``answer_orchestration.py``)
    puerto mínimo que expone ``infer(request) -> KnowledgeInferenceOutcome``.

``KnowledgeAnswerOrchestrationService`` (``answer_orchestration.py``)
    único punto que decide si corresponde invocar inferencia, y solo
    cuando no hay evidencia recuperable y hay opt-in explícito
    (``allow_inference=True``).

``KnowledgeEvidenceSufficiency`` (``evidence_sufficiency.py``)
    clasifica toda respuesta INFERENCE_ONLY como ``NOT_EVIDENCE_BASED``:
    la inferencia nunca cuenta como evidencia Knowledge.

Este módulo NO implementa OpenAI, Claude ni ningún SDK de proveedor de
IA concreto. Añade exclusivamente una capa de gobernanza alrededor del
puerto existente:

- identifica proveedores de inferencia con una clave estable
  (``KnowledgeInferenceProviderDescriptor``);
- los mantiene en un registro en memoria, deliberadamente separado de
  ``source_registry.py`` (``KnowledgeInferenceProviderRegistry``);
- todo proveedor nace deshabilitado (``enabled=False`` por defecto) y
  requiere habilitación explícita;
- decide de forma determinista si procede invocar inferencia
  (``KnowledgeInferencePolicyService.decide``), con motivo de denegación
  explícito en cada decisión, nunca un puntaje;
- adapta un ``KnowledgeInferenceProvider`` real para que la decisión de
  política se aplique siempre antes de invocarlo
  (``KnowledgeGovernedInferenceProvider``), sin modificar
  ``KnowledgeAnswerOrchestrationService``.

Invariantes de diseño:

- ningún proveedor de inferencia registrado aquí se convierte en una
  fuente Knowledge canónica: registrar una clave que ya exista en
  ``source_registry.py`` falla cerrado;
- este módulo nunca escribe en ``KnowledgeCatalog``, en revisiones de
  promoción ni en el corpus Knowledge. Es gobernanza pura sobre el
  puerto de inferencia, sin efectos secundarios sobre el dominio;
- ``KnowledgeHumanReviewGateService`` permanece intacto y es la única
  vía para mutar DISCOVERED -> FOLLOWED; este módulo no lo referencia;
- la inferencia sigue siendo estrictamente de menor autoridad que una
  respuesta SOURCE_BACKED: esta capa solo puede denegar una invocación
  de inferencia que ``KnowledgeAnswerOrchestrationService`` ya habría
  intentado, nunca puede producir ni ampliar evidencia Knowledge;
- cambiar de proveedor de inferencia es cambiar qué objeto concreto se
  envuelve en ``KnowledgeGovernedInferenceProvider``: nunca exige
  rediseñar ``KnowledgeAnswerOrchestrationService`` ni el resto de
  Knowledge;
- determinista: misma clave + mismo estado del registro siempre produce
  la misma decisión. Sin aleatoriedad, reloj de sistema ni llamadas a
  red/IA.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .answer_orchestration import (
    KnowledgeAnswerRequest,
    KnowledgeInferenceOutcome,
    KnowledgeInferenceProvider,
)
from .source_registry import knowledge_source_exists


def normalize_inference_provider_key(value: str) -> str:
    """Normaliza una clave de proveedor de inferencia suministrada."""

    key = str(value or "").strip().upper()

    if not key:
        raise ValueError(
            "Knowledge inference provider key no puede estar vacío"
        )

    return key


# ============================================================
# DESCRIPTOR
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeInferenceProviderDescriptor:
    """Identidad estable de un proveedor de inferencia externo.

    ``engine_label`` es un identificador operativo libre (igual que
    ``KnowledgeInferenceOutcome.engine_label``), nunca el nombre de un
    producto/SDK concreto dentro de un contrato de dominio.

    ``enabled`` nace en ``False``: ningún proveedor queda habilitado por
    el simple hecho de registrarse.
    """

    key: str
    engine_label: str
    enabled: bool = False

    def __post_init__(self) -> None:
        key = normalize_inference_provider_key(self.key)

        if knowledge_source_exists(key):
            raise ValueError(
                "La clave de proveedor de inferencia coincide con una "
                f"fuente Knowledge canónica registrada: {key}. Un "
                "proveedor de inferencia nunca puede identificarse como "
                "fuente Knowledge."
            )

        object.__setattr__(self, "key", key)

        engine_label = str(self.engine_label or "").strip()

        if not engine_label:
            raise ValueError(
                "KnowledgeInferenceProviderDescriptor.engine_label no "
                "puede estar vacío"
            )

        object.__setattr__(self, "engine_label", engine_label)

        if not isinstance(self.enabled, bool):
            raise TypeError(
                "KnowledgeInferenceProviderDescriptor.enabled debe ser "
                "bool"
            )


def build_inference_provider_descriptor(
    *,
    key: str,
    engine_label: str,
    enabled: bool = False,
) -> KnowledgeInferenceProviderDescriptor:
    """Factory pública del descriptor de proveedor de inferencia."""

    return KnowledgeInferenceProviderDescriptor(
        key=key,
        engine_label=engine_label,
        enabled=enabled,
    )


# ============================================================
# REGISTRY
# ============================================================


class KnowledgeInferenceProviderRegistry:
    """Registro en memoria de proveedores de inferencia conocidos.

    Deliberadamente independiente de ``source_registry.py``: nada de lo
    que ocurre aquí escribe en el registro canónico de fuentes Knowledge
    ni en el corpus. Vive mientras viva el proceso que lo instancia.
    """

    def __init__(self) -> None:
        self._descriptors: dict[
            str, KnowledgeInferenceProviderDescriptor
        ] = {}

    def register(
        self,
        descriptor: KnowledgeInferenceProviderDescriptor,
    ) -> KnowledgeInferenceProviderDescriptor:
        if not isinstance(
            descriptor, KnowledgeInferenceProviderDescriptor
        ):
            raise TypeError(
                "descriptor debe ser "
                "KnowledgeInferenceProviderDescriptor"
            )

        self._descriptors[descriptor.key] = descriptor
        return descriptor

    def try_get(
        self,
        provider_key: str,
    ) -> KnowledgeInferenceProviderDescriptor | None:
        key = normalize_inference_provider_key(provider_key)
        return self._descriptors.get(key)

    def get(
        self,
        provider_key: str,
    ) -> KnowledgeInferenceProviderDescriptor:
        descriptor = self.try_get(provider_key)

        if descriptor is None:
            raise KeyError(
                "Proveedor de inferencia no registrado: "
                f"{normalize_inference_provider_key(provider_key)}"
            )

        return descriptor

    def is_registered(self, provider_key: str) -> bool:
        return self.try_get(provider_key) is not None

    def is_enabled(self, provider_key: str) -> bool:
        descriptor = self.try_get(provider_key)
        return descriptor is not None and descriptor.enabled

    def enable(
        self,
        provider_key: str,
    ) -> KnowledgeInferenceProviderDescriptor:
        descriptor = self.get(provider_key)
        enabled_descriptor = dataclasses.replace(descriptor, enabled=True)
        self._descriptors[descriptor.key] = enabled_descriptor
        return enabled_descriptor

    def disable(
        self,
        provider_key: str,
    ) -> KnowledgeInferenceProviderDescriptor:
        descriptor = self.get(provider_key)
        disabled_descriptor = dataclasses.replace(
            descriptor, enabled=False
        )
        self._descriptors[descriptor.key] = disabled_descriptor
        return disabled_descriptor

    def list_descriptors(
        self,
        *,
        enabled_only: bool = False,
    ) -> tuple[KnowledgeInferenceProviderDescriptor, ...]:
        descriptors = sorted(
            self._descriptors.values(), key=lambda item: item.key
        )

        if enabled_only:
            descriptors = [
                descriptor
                for descriptor in descriptors
                if descriptor.enabled
            ]

        return tuple(descriptors)


# ============================================================
# POLICY
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeInferencePolicyDecision:
    """Decisión determinista: permitir o denegar una invocación de inferencia.

    No es un puntaje ni una probabilidad de confianza: es una decisión
    booleana con motivo explícito, derivada únicamente del estado
    declarado del registro de proveedores. ``reason`` es obligatorio
    tanto si se permite como si se deniega.
    """

    provider_key: str
    allowed: bool
    reason: str

    def __post_init__(self) -> None:
        provider_key = normalize_inference_provider_key(
            self.provider_key
        )
        object.__setattr__(self, "provider_key", provider_key)

        if not isinstance(self.allowed, bool):
            raise TypeError(
                "KnowledgeInferencePolicyDecision.allowed debe ser bool"
            )

        reason = str(self.reason or "").strip()

        if not reason:
            raise ValueError(
                "KnowledgeInferencePolicyDecision.reason no puede estar "
                "vacío: toda decisión requiere motivo explícito"
            )

        object.__setattr__(self, "reason", reason)


class KnowledgeInferencePolicyDenied(PermissionError):
    """Fail-closed: invocación de inferencia denegada por la política."""


class KnowledgeInferencePolicyService:
    """Decide determinísticamente si procede invocar un proveedor de inferencia.

    Depende únicamente de ``KnowledgeInferenceProviderRegistry`` (estado
    declarado en memoria). No invoca al proveedor, no lee ni escribe el
    corpus Knowledge, ``KnowledgeCatalog`` ni revisiones de promoción: la
    decisión es previa y externa a cualquier llamada real de inferencia.
    """

    def __init__(
        self,
        registry: KnowledgeInferenceProviderRegistry,
    ) -> None:
        if not isinstance(
            registry, KnowledgeInferenceProviderRegistry
        ):
            raise TypeError(
                "registry debe ser KnowledgeInferenceProviderRegistry"
            )

        self._registry = registry

    def decide(
        self,
        provider_key: str,
        *,
        allow_inference: bool,
    ) -> KnowledgeInferencePolicyDecision:
        key = normalize_inference_provider_key(provider_key)

        if not isinstance(allow_inference, bool):
            raise TypeError("allow_inference debe ser bool")

        if not allow_inference:
            return KnowledgeInferencePolicyDecision(
                provider_key=key,
                allowed=False,
                reason=(
                    "No se solicitó opt-in explícito de inferencia "
                    "(allow_inference=False)."
                ),
            )

        descriptor = self._registry.try_get(key)

        if descriptor is None:
            return KnowledgeInferencePolicyDecision(
                provider_key=key,
                allowed=False,
                reason=(
                    f"Proveedor de inferencia no registrado: {key}."
                ),
            )

        if not descriptor.enabled:
            return KnowledgeInferencePolicyDecision(
                provider_key=key,
                allowed=False,
                reason=(
                    f"Proveedor de inferencia '{key}' está "
                    "deshabilitado (deshabilitado por defecto: "
                    "requiere habilitación explícita vía "
                    "KnowledgeInferenceProviderRegistry.enable)."
                ),
            )

        return KnowledgeInferencePolicyDecision(
            provider_key=key,
            allowed=True,
            reason=(
                f"Proveedor de inferencia '{key}' registrado y "
                "habilitado; opt-in explícito confirmado."
            ),
        )


# ============================================================
# GOVERNED PROVIDER (adaptador sobre el puerto existente)
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeGovernedInferenceProvider:
    """Decora un ``KnowledgeInferenceProvider`` real con esta gobernanza.

    Implementa el mismo puerto que consume
    ``KnowledgeAnswerOrchestrationService`` (``infer``), por lo que puede
    inyectarse en su lugar sin ningún cambio en la orquestación. Nunca
    invoca al proveedor envuelto si la política deniega la decisión
    (fail-closed): la denegación se expresa como
    ``KnowledgeInferencePolicyDenied`` con el motivo explícito de la
    decisión.
    """

    provider_key: str
    provider: KnowledgeInferenceProvider
    policy_service: KnowledgeInferencePolicyService

    def __post_init__(self) -> None:
        provider_key = normalize_inference_provider_key(
            self.provider_key
        )
        object.__setattr__(self, "provider_key", provider_key)

        if not isinstance(self.provider, KnowledgeInferenceProvider):
            raise TypeError(
                "provider debe implementar KnowledgeInferenceProvider"
            )

        if not isinstance(
            self.policy_service, KnowledgeInferencePolicyService
        ):
            raise TypeError(
                "policy_service debe ser "
                "KnowledgeInferencePolicyService"
            )

    def infer(
        self,
        request: KnowledgeAnswerRequest,
    ) -> KnowledgeInferenceOutcome:
        if not isinstance(request, KnowledgeAnswerRequest):
            raise TypeError("request debe ser KnowledgeAnswerRequest")

        decision = self.policy_service.decide(
            self.provider_key,
            allow_inference=request.allow_inference,
        )

        if not decision.allowed:
            raise KnowledgeInferencePolicyDenied(decision.reason)

        return self.provider.infer(request)

"""
Aplicación realtime de llamadas observadas en WhatsApp.

Responsabilidad:
- recibir una WhatsAppCallObservation;
- adaptarla a semántica genérica;
- proyectarla a ProviderCallSnapshot;
- reconciliarla mediante el servicio genérico de llamadas.

No:
- toca SeleniumBase/CDP;
- consulta ningún reloj;
- contiene SQL;
- construye repositories;
- construye CommunicationCallService;
- clasifica outcomes terminales.
"""

from dataclasses import dataclass
from typing import Any

from backend.communications.call_snapshots import (
    ProviderCallSnapshot,
)
from backend.services.whatsapp_call_domain_adapter import (
    WhatsAppCallDomainAdaptation,
    adapt_whatsapp_call_observation,
    project_whatsapp_call_intent_to_provider_snapshot,
)
from backend.services.whatsapp_call_observation import (
    WhatsAppCallObservation,
)


WHATSAPP_CALL_REALTIME_DISABLED = (
    "PERSISTENCE_DISABLED"
)

WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE = (
    "NOT_ACTIONABLE"
)

WHATSAPP_CALL_REALTIME_RECONCILED = (
    "RECONCILED"
)


@dataclass(frozen=True)
class WhatsAppCallRealtimeSyncResult:
    """
    Resultado explícito de una incorporación realtime.

    RECONCILED no intenta distinguir CREATED/REUSED/ADVANCED:
    esa clasificación exigiría una lectura adicional susceptible
    de carrera y no es necesaria para la corrección.
    """

    action: str
    observation: WhatsAppCallObservation

    observed_at: str | None = None

    adaptation: (
        WhatsAppCallDomainAdaptation
        | None
    ) = None

    provider_snapshot: (
        ProviderCallSnapshot
        | None
    ) = None

    persisted_call: Any | None = None


class WhatsAppCallRealtimeService:
    """
    Frontera application provider -> CommunicationCallService.

    call_service es una dependencia externa opcional.
    Nunca se construye implícitamente aquí.
    """

    def __init__(
        self,
        *,
        call_service=None,
    ):
        self.call_service = (
            call_service
        )

    @property
    def enabled(
        self,
    ):
        return (
            self.call_service
            is not None
        )

    def process_observation(
        self,
        observation,
        *,
        observed_at=None,
    ):
        if not isinstance(
            observation,
            WhatsAppCallObservation,
        ):
            raise TypeError(
                "observation debe ser "
                "WhatsAppCallObservation"
            )

        if not self.enabled:
            return WhatsAppCallRealtimeSyncResult(
                action=(
                    WHATSAPP_CALL_REALTIME_DISABLED
                ),
                observation=observation,
                observed_at=None,
                adaptation=None,
                provider_snapshot=None,
                persisted_call=None,
            )

        adaptation = (
            adapt_whatsapp_call_observation(
                observation,
                observed_at=observed_at,
            )
        )

        if not adaptation.ready:
            return WhatsAppCallRealtimeSyncResult(
                action=(
                    WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE
                ),
                observation=observation,
                observed_at=(
                    adaptation.observed_at
                ),
                adaptation=adaptation,
                provider_snapshot=None,
                persisted_call=None,
            )

        provider_snapshot = (
            project_whatsapp_call_intent_to_provider_snapshot(
                adaptation.intent
            )
        )

        persisted_call = (
            self.call_service
            .reconcile_provider_call(
                provider_snapshot
            )
        )

        return WhatsAppCallRealtimeSyncResult(
            action=(
                WHATSAPP_CALL_REALTIME_RECONCILED
            ),
            observation=observation,
            observed_at=(
                adaptation.observed_at
            ),
            adaptation=adaptation,
            provider_snapshot=(
                provider_snapshot
            ),
            persisted_call=(
                persisted_call
            ),
        )

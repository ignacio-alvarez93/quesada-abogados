"""
Adaptación semántica realtime de WhatsApp a dominio de llamadas.

Responsabilidad:
- decidir si una observación WhatsApp es utilizable;
- traducir fases realtime seguras a lifecycle genérico;
- conservar identidad externa del proveedor;
- distinguir observed_at CRM de cualquier timestamp provider.

No:
- consulta el reloj;
- toca SeleniumBase/CDP;
- persiste;
- conoce CommunicationCallService;
- crea CommunicationCall;
- clasifica terminales ambiguos sin evidencia observable;
- inventa estados intermedios ni timestamps provider.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.automation.connectors.whatsapp_call_observer import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
)
from backend.communications.call_snapshots import (
    ProviderCallSnapshot,
)
from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_ANSWERED,
    CALL_STATUS_DIALING,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
)
from backend.communications.models import (
    CHANNEL_WHATSAPP,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_SURFACE_DISAPPEARED,
    CALL_OBSERVATION_UPDATED,
    WhatsAppCallObservation,
)


WHATSAPP_CALL_PROVIDER = "WHATSAPP_WEB"


WHATSAPP_CALL_ADAPT_READY = (
    "READY"
)

WHATSAPP_CALL_ADAPT_UNCHANGED = (
    "UNCHANGED"
)

WHATSAPP_CALL_ADAPT_NO_ACTIVE_SURFACE = (
    "NO_ACTIVE_SURFACE"
)

WHATSAPP_CALL_ADAPT_PHASE_NOT_ACTIONABLE = (
    "PHASE_NOT_ACTIONABLE"
)

WHATSAPP_CALL_ADAPT_VIDEO_UNSUPPORTED = (
    "VIDEO_UNSUPPORTED"
)

WHATSAPP_CALL_ADAPT_DIRECTION_UNKNOWN = (
    "DIRECTION_UNKNOWN"
)

WHATSAPP_CALL_ADAPT_DIRECTION_PHASE_CONFLICT = (
    "DIRECTION_PHASE_CONFLICT"
)

WHATSAPP_CALL_ADAPT_EXTERNAL_KEY_MISSING = (
    "EXTERNAL_CALL_KEY_MISSING"
)

WHATSAPP_CALL_ADAPT_PHONE_MISSING = (
    "PHONE_NUMBER_MISSING"
)


@dataclass(frozen=True)
class WhatsAppCallDomainIntent:
    """
    Hecho realtime seguro listo para la capa de aplicación.

    observed_at representa cuándo lo observó el CRM.

    No afirma que WhatsApp haya proporcionado ese timestamp.
    """

    provider: str
    channel: str
    direction: str
    phone_number: str

    external_call_key: str
    provider_call_id: str | None

    display_name_snapshot: str | None

    status: str
    observed_at: str

    metadata: dict[str, Any]


@dataclass(frozen=True)
class WhatsAppCallDomainAdaptation:
    """Resultado explícito del adaptador provider -> dominio."""

    ready: bool
    reason: str
    observed_at: str

    intent: WhatsAppCallDomainIntent | None = None


def _clean_optional_text(
    value,
):
    normalized = str(
        value
        or ""
    ).strip()

    return (
        normalized
        or None
    )


def _normalize_observed_at(
    value,
):
    """
    observed_at debe ser ISO-8601 con zona horaria.

    El adaptador no consulta ningún reloj.
    """
    raw = str(
        value
        or ""
    ).strip()

    if not raw:
        raise ValueError(
            "observed_at es obligatorio"
        )

    parseable = raw

    if parseable.endswith(
        "Z"
    ):
        parseable = (
            parseable[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            parseable
        )

    except ValueError as exc:
        raise ValueError(
            "observed_at no es ISO-8601 válido"
        ) from exc

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError(
            "observed_at debe incluir zona horaria"
        )

    return raw


def _skip(
    *,
    reason,
    observed_at,
):
    return WhatsAppCallDomainAdaptation(
        ready=False,
        reason=reason,
        observed_at=observed_at,
        intent=None,
    )


def _domain_direction(
    provider_direction,
):
    if (
        provider_direction
        == WHATSAPP_CALL_DIRECTION_INBOUND
    ):
        return CALL_DIRECTION_INBOUND

    if (
        provider_direction
        == WHATSAPP_CALL_DIRECTION_OUTBOUND
    ):
        return CALL_DIRECTION_OUTBOUND

    return None


def _domain_status(
    *,
    phase,
    direction,
):
    if (
        phase
        == WHATSAPP_CALL_PHASE_INCOMING_RINGING
    ):
        if (
            direction
            != CALL_DIRECTION_INBOUND
        ):
            return (
                None,
                WHATSAPP_CALL_ADAPT_DIRECTION_PHASE_CONFLICT,
            )

        return (
            CALL_STATUS_RINGING,
            None,
        )

    if (
        phase
        == WHATSAPP_CALL_PHASE_OUTGOING_DIALING
    ):
        if (
            direction
            != CALL_DIRECTION_OUTBOUND
        ):
            return (
                None,
                WHATSAPP_CALL_ADAPT_DIRECTION_PHASE_CONFLICT,
            )

        return (
            CALL_STATUS_DIALING,
            None,
        )

    if (
        phase
        == WHATSAPP_CALL_PHASE_ACTIVE
    ):
        return (
            CALL_STATUS_ANSWERED,
            None,
        )

    return (
        None,
        WHATSAPP_CALL_ADAPT_PHASE_NOT_ACTIONABLE,
    )


def adapt_whatsapp_call_observation(
    observation,
    *,
    observed_at,
):
    """
    Traduce únicamente hechos realtime seguros.

    Mapping productivo inicial:

    INCOMING_RINGING
        -> RINGING

    OUTGOING_DIALING
        -> DIALING

    ACTIVE
        -> ANSWERED

    INCOMING_RINGING -> ENDED_TRANSIENT
        -> MISSED

    INCOMING_RINGING + desaparición directa de superficie
        -> MISSED

    CONNECTING / SURFACE_PRESENT / ABSENT
        -> sin intent de dominio

    MISSED solo se deriva cuando existe evidencia observable
    de una llamada INBOUND cuyo último estado previo conocido
    fue INCOMING_RINGING y nunca se observó ACTIVE.

    ENDED_TRANSIENT por sí solo no implica MISSED.

    No se infieren aquí REJECTED / BUSY / CANCELLED / FAILED.
    """
    if not isinstance(
        observation,
        WhatsAppCallObservation,
    ):
        raise TypeError(
            "observation debe ser WhatsAppCallObservation"
        )

    clean_observed_at = (
        _normalize_observed_at(
            observed_at
        )
    )

    if not observation.changed:
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_UNCHANGED
            ),
            observed_at=clean_observed_at,
        )

    missed_from_ended_transient = (
        observation.change_type
        == CALL_OBSERVATION_UPDATED
        and observation.previous is not None
        and observation.previous.present
        and observation.previous.phase
        == WHATSAPP_CALL_PHASE_INCOMING_RINGING
        and observation.previous.direction
        == WHATSAPP_CALL_DIRECTION_INBOUND
        and observation.active is not None
        and observation.active.present
        and observation.active.phase
        == WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
        and observation.active.direction
        == WHATSAPP_CALL_DIRECTION_INBOUND
    )

    missed_from_ringing_disappearance = (
        observation.change_type
        == CALL_OBSERVATION_SURFACE_DISAPPEARED
        and observation.disappeared is not None
        and observation.disappeared.present
        and observation.disappeared.phase
        == WHATSAPP_CALL_PHASE_INCOMING_RINGING
        and observation.disappeared.direction
        == WHATSAPP_CALL_DIRECTION_INBOUND
    )

    missed_terminal_inference = (
        missed_from_ended_transient
        or missed_from_ringing_disappearance
    )

    snapshot = (
        observation.active
        if missed_from_ended_transient
        else (
            observation.disappeared
            if missed_from_ringing_disappearance
            else observation.active
        )
    )

    if (
        snapshot is None
        or not snapshot.present
    ):
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_NO_ACTIVE_SURFACE
            ),
            observed_at=clean_observed_at,
        )

    # WA-CALL está implementando primero voz.
    # No incorporamos video accidentalmente antes de
    # verificar específicamente ese transporte/lifecycle.
    if snapshot.is_video is True:
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_VIDEO_UNSUPPORTED
            ),
            observed_at=clean_observed_at,
        )

    direction = (
        _domain_direction(
            snapshot.direction
        )
    )

    if direction is None:
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_DIRECTION_UNKNOWN
            ),
            observed_at=clean_observed_at,
        )

    if missed_terminal_inference:
        status = (
            CALL_STATUS_MISSED
        )

    else:
        (
            status,
            status_error,
        ) = _domain_status(
            phase=snapshot.phase,
            direction=direction,
        )

        if status is None:
            return _skip(
                reason=status_error,
                observed_at=clean_observed_at,
            )

    external_call_key = (
        _clean_optional_text(
            snapshot.external_call_key
        )
    )

    if not external_call_key:
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_EXTERNAL_KEY_MISSING
            ),
            observed_at=clean_observed_at,
        )

    phone_number = (
        _clean_optional_text(
            snapshot.participant_phone
        )
    )

    if not phone_number:
        return _skip(
            reason=(
                WHATSAPP_CALL_ADAPT_PHONE_MISSING
            ),
            observed_at=clean_observed_at,
        )

    provider_call_id = (
        _clean_optional_text(
            snapshot.provider_call_id
        )
    )

    display_name = (
        _clean_optional_text(
            snapshot.participant_display_name
        )
    )

    metadata = {
        "source":
            "whatsapp_realtime_observation",
        "provider_phase":
            snapshot.phase,
    }

    if missed_from_ended_transient:
        metadata[
            "crm_terminal_inference"
        ] = (
            "INCOMING_RINGING_TO_ENDED_TRANSIENT"
        )

        metadata[
            "crm_ended_transient_observed"
        ] = True

    elif missed_from_ringing_disappearance:
        metadata[
            "crm_terminal_inference"
        ] = (
            "INCOMING_RINGING_SURFACE_DISAPPEARED"
        )

        metadata[
            "crm_surface_disappeared"
        ] = True

    participant_lid = (
        _clean_optional_text(
            snapshot.participant_lid
        )
    )

    if participant_lid:
        metadata[
            "participant_lid"
        ] = participant_lid

    participant_phone_id = (
        _clean_optional_text(
            snapshot.participant_phone_id
        )
    )

    if participant_phone_id:
        metadata[
            "participant_phone_id"
        ] = participant_phone_id

    if snapshot.is_video is not None:
        metadata[
            "is_video"
        ] = bool(
            snapshot.is_video
        )

    intent = WhatsAppCallDomainIntent(
        provider=(
            WHATSAPP_CALL_PROVIDER
        ),
        channel=(
            CHANNEL_WHATSAPP
        ),
        direction=direction,
        phone_number=phone_number,
        external_call_key=(
            external_call_key
        ),
        provider_call_id=(
            provider_call_id
        ),
        display_name_snapshot=(
            display_name
        ),
        status=status,
        observed_at=(
            clean_observed_at
        ),
        metadata=metadata,
    )

    return WhatsAppCallDomainAdaptation(
        ready=True,
        reason=(
            WHATSAPP_CALL_ADAPT_READY
        ),
        observed_at=(
            clean_observed_at
        ),
        intent=intent,
    )


def project_whatsapp_call_intent_to_provider_snapshot(
    intent,
):
    """
    Proyecta un intent realtime a ProviderCallSnapshot.

    Regla fundamental:
    observed_at es momento de observación CRM.

    NO se copia automáticamente a:
    - dialed_at;
    - ringing_at;
    - answered_at;
    - ended_at.

    Esos campos quedan reservados a timestamps de lifecycle
    realmente conocidos/reconciliados del proveedor.

    La observación CRM queda en metadata mediante una clave
    específica del estado observado.
    """
    if not isinstance(
        intent,
        WhatsAppCallDomainIntent,
    ):
        raise TypeError(
            "intent debe ser WhatsAppCallDomainIntent"
        )

    observed_key_by_status = {
        CALL_STATUS_DIALING:
            "crm_observed_dialing_at",
        CALL_STATUS_RINGING:
            "crm_observed_ringing_at",
        CALL_STATUS_ANSWERED:
            "crm_observed_answered_at",
        CALL_STATUS_MISSED:
            "crm_observed_missed_at",
    }

    observed_key = (
        observed_key_by_status.get(
            intent.status
        )
    )

    if observed_key is None:
        raise ValueError(
            "Estado realtime no proyectable "
            "a ProviderCallSnapshot"
        )

    metadata = dict(
        intent.metadata
        or {}
    )

    # provider_phase describe la fotografía actual.
    #
    # No la persistimos bajo una única clave mutable porque
    # la reconciliación conserva metadata previa ante conflictos.
    # Una secuencia DIALING -> ACTIVE podría dejar entonces
    # provider_phase=DIALING con status=ANSWERED.
    #
    # Conservamos la evidencia bajo una clave específica
    # del estado observado, que puede acumularse sin conflicto.
    provider_phase = (
        metadata.pop(
            "provider_phase",
            None,
        )
    )

    phase_key_by_status = {
        CALL_STATUS_DIALING:
            "crm_observed_dialing_provider_phase",
        CALL_STATUS_RINGING:
            "crm_observed_ringing_provider_phase",
        CALL_STATUS_ANSWERED:
            "crm_observed_answered_provider_phase",
        CALL_STATUS_MISSED:
            "crm_observed_missed_provider_phase",
    }

    phase_key = (
        phase_key_by_status.get(
            intent.status
        )
    )

    if (
        provider_phase
        and phase_key
    ):
        metadata[
            phase_key
        ] = provider_phase

    metadata[
        observed_key
    ] = intent.observed_at

    return ProviderCallSnapshot(
        provider=intent.provider,
        external_call_key=(
            intent.external_call_key
        ),
        provider_call_id=(
            intent.provider_call_id
        ),
        channel=intent.channel,
        direction=intent.direction,
        phone_number=(
            intent.phone_number
        ),
        display_name_snapshot=(
            intent.display_name_snapshot
        ),
        status=intent.status,

        # observed_at NO es timestamp provider.
        dialed_at=None,
        ringing_at=None,
        answered_at=None,
        ended_at=None,

        metadata=metadata,
    )

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from backend.communications.call_snapshots import (
    ProviderCallSnapshot,
)
from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_CANCELLED,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
    CALL_STATUS_REJECTED,
)
from backend.communications.models import (
    CHANNEL_WHATSAPP,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)


WHATSAPP_CALL_HISTORY_PROVIDER = "WHATSAPP_WEB"


@dataclass(frozen=True)
class WhatsAppHistoricalCallSnapshot:
    provider_call_id: str
    external_call_key: str
    peer_lid: str
    peer_phone_id: str | None
    peer_display_name: str | None
    provider_timestamp: int | None
    call_duration_seconds: int | None
    raw_outcome: str | None
    raw_final_outcome: str | None
    row_state: str | None
    is_video: bool | None = None


def _parse_external_key(value):
    text = str(value or "").strip()

    match = re.match(
        r"^(true|false)_(.+?@lid)_(.+)$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        raise ValueError(
            "external_call_key WhatsApp inválida"
        )

    outbound = (
        match.group(1).lower()
        == "true"
    )

    return (
        CALL_DIRECTION_OUTBOUND
        if outbound
        else CALL_DIRECTION_INBOUND
    )


def _provider_timestamp(value):
    if value is None:
        return None

    return (
        datetime.fromtimestamp(
            int(value),
            tz=timezone.utc,
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _phone_from_id(value):
    raw = str(
        value or ""
    ).strip()

    if raw.endswith("@c.us"):
        raw = raw[:-5]

    normalized = normalize_phone(
        raw
    )

    if not normalized.valid:
        raise ValueError(
            "Teléfono histórico WhatsApp inválido"
        )

    return normalized.e164


def _status(snapshot):
    row_state = (
        str(snapshot.row_state or "")
        .strip()
        .upper()
    )

    outcome = (
        str(snapshot.raw_outcome or "")
        .strip()
        .upper()
    )

    final = (
        str(snapshot.raw_final_outcome or "")
        .strip()
        .upper()
    )

    direction = _parse_external_key(
        snapshot.external_call_key
    )

    # La fila visible "Perdida" es la señal
    # histórica más fuerte para inbound.
    if (
        row_state.startswith("PERDIDA")
        or row_state.startswith("MISSED")
    ):
        return CALL_STATUS_MISSED

    # Historial ya terminal:
    # Completed y AcceptedElsewhere implican
    # llamada atendida/finalizada sin inventar
    # answered_at ni ended_at.
    if (
        outcome == "COMPLETED"
        or final == "COMPLETED"
        or outcome == "ACCEPTEDELSEWHERE"
    ):
        return CALL_STATUS_ENDED

    if outcome == "REJECTED":
        return CALL_STATUS_REJECTED

    # Una salida sin respuesta/cancelada termina
    # como CANCELLED en el dominio CRM.
    if (
        direction == CALL_DIRECTION_OUTBOUND
        and (
            outcome in {
                "MISSED",
                "CANCELED",
            }
            or final == "CANCELED"
        )
    ):
        return CALL_STATUS_CANCELLED

    raise ValueError(
        "Estado histórico WhatsApp "
        "no clasificable de forma segura"
    )

def project_whatsapp_history_snapshot(
    snapshot,
):
    if not isinstance(
        snapshot,
        WhatsAppHistoricalCallSnapshot,
    ):
        raise TypeError(
            "Se requiere "
            "WhatsAppHistoricalCallSnapshot"
        )

    direction = _parse_external_key(
        snapshot.external_call_key
    )

    phone = _phone_from_id(
        snapshot.peer_phone_id
    )

    status = _status(
        snapshot
    )

    provider_at = _provider_timestamp(
        snapshot.provider_timestamp
    )

    duration = (
        int(
            snapshot.call_duration_seconds
        )
        if isinstance(
            snapshot.call_duration_seconds,
            int,
        )
        and snapshot.call_duration_seconds >= 0
        else None
    )

    return ProviderCallSnapshot(
        provider=(
            WHATSAPP_CALL_HISTORY_PROVIDER
        ),
        external_call_key=(
            snapshot.external_call_key
        ),
        provider_call_id=(
            snapshot.provider_call_id
        ),
        channel=CHANNEL_WHATSAPP,
        direction=direction,
        phone_number=phone,
        display_name_snapshot=(
            snapshot.peer_display_name
        ),
        status=status,
        dialed_at=(
            provider_at
            if direction
            == CALL_DIRECTION_OUTBOUND
            else None
        ),
        ringing_at=(
            provider_at
            if direction
            == CALL_DIRECTION_INBOUND
            else None
        ),
        talk_duration_seconds=(
            duration
            if status
            == CALL_STATUS_ENDED
            else None
        ),
        metadata={
            "source":
                "whatsapp_call_history",
            "peer_lid":
                snapshot.peer_lid,
            "raw_outcome":
                snapshot.raw_outcome,
            "raw_final_outcome":
                snapshot.raw_final_outcome,
            "row_state":
                snapshot.row_state,
            "is_video":
                snapshot.is_video,
        },
    )

"""
Snapshots históricos de llamadas de proveedores.

Este módulo es dominio puro.

No persiste.
No conoce SQLite.
No conoce Flet.
No conoce Phone Link.
No conoce WhatsApp Web.

Un ProviderCallSnapshot describe hechos que el proveedor
afirma conocer sobre una llamada. No obliga a fingir que
el CRM observó en realtime cada transición intermedia.
"""

from dataclasses import dataclass, replace
from typing import Any

from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_ANSWERED,
    CALL_STATUS_BUSY,
    CALL_STATUS_CANCELLED,
    CALL_STATUS_CREATED,
    CALL_STATUS_DIALING,
    CALL_STATUS_ENDED,
    CALL_STATUS_FAILED,
    CALL_STATUS_MISSED,
    CALL_STATUS_REJECTED,
    CALL_STATUS_RINGING,
    CALL_TERMINAL_STATUSES,
    CommunicationCall,
    materialize_call_timing,
)


CALL_SNAPSHOT_STATUSES = frozenset(
    {
        CALL_STATUS_CREATED,
        CALL_STATUS_DIALING,
        CALL_STATUS_RINGING,
        CALL_STATUS_ANSWERED,
        CALL_STATUS_ENDED,
        CALL_STATUS_MISSED,
        CALL_STATUS_REJECTED,
        CALL_STATUS_BUSY,
        CALL_STATUS_FAILED,
        CALL_STATUS_CANCELLED,
    }
)


CALL_NON_ANSWERED_TERMINAL_STATUSES = (
    CALL_TERMINAL_STATUSES
    - {
        CALL_STATUS_ENDED,
    }
)


@dataclass(frozen=True)
class ProviderCallSnapshot:
    """
    Hechos consolidados entregados por un proveedor.

    provider + external_call_key constituyen la identidad
    canónica externa que usará la reconciliación.

    Los timestamps y duraciones son opcionales porque distintos
    proveedores pueden exponer distintos niveles de detalle.
    """

    provider: str
    external_call_key: str

    channel: str
    direction: str
    phone_number: str
    status: str

    provider_call_id: str | None = None
    display_name_snapshot: str | None = None

    dialed_at: str | None = None
    ringing_at: str | None = None
    answered_at: str | None = None
    ended_at: str | None = None

    ring_duration_seconds: int | None = None
    talk_duration_seconds: int | None = None
    total_duration_seconds: int | None = None

    metadata: dict[str, Any] | None = None


class InvalidProviderCallSnapshot(
    ValueError
):
    """Snapshot histórico incoherente o insuficiente."""


def _required_text(
    value,
    *,
    field_name,
    upper=False,
):
    normalized = str(
        value
        or ""
    ).strip()

    if not normalized:
        raise InvalidProviderCallSnapshot(
            f"{field_name} es obligatorio"
        )

    if upper:
        normalized = (
            normalized.upper()
        )

    return normalized


def _optional_text(
    value,
    *,
    upper=False,
):
    normalized = str(
        value
        or ""
    ).strip()

    if not normalized:
        return None

    if upper:
        normalized = (
            normalized.upper()
        )

    return normalized


def _optional_duration(
    value,
    *,
    field_name,
):
    if value is None:
        return None

    try:
        normalized = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise InvalidProviderCallSnapshot(
            f"{field_name} no es una duración válida"
        ) from exc

    if normalized < 0:
        raise InvalidProviderCallSnapshot(
            f"{field_name} no puede ser negativa"
        )

    return normalized


def normalize_provider_call_snapshot(
    snapshot,
):
    if not isinstance(
        snapshot,
        ProviderCallSnapshot,
    ):
        raise InvalidProviderCallSnapshot(
            "Se requiere ProviderCallSnapshot"
        )

    provider = _required_text(
        snapshot.provider,
        field_name="provider",
        upper=True,
    )

    external_call_key = (
        _required_text(
            snapshot.external_call_key,
            field_name=(
                "external_call_key"
            ),
        )
    )

    channel = _required_text(
        snapshot.channel,
        field_name="channel",
        upper=True,
    )

    direction = _required_text(
        snapshot.direction,
        field_name="direction",
        upper=True,
    )

    phone_number = _required_text(
        snapshot.phone_number,
        field_name="phone_number",
    )

    status = _required_text(
        snapshot.status,
        field_name="status",
        upper=True,
    )

    if direction not in {
        CALL_DIRECTION_INBOUND,
        CALL_DIRECTION_OUTBOUND,
    }:
        raise InvalidProviderCallSnapshot(
            "Dirección de llamada no válida"
        )

    if status not in (
        CALL_SNAPSHOT_STATUSES
    ):
        raise InvalidProviderCallSnapshot(
            "Estado de llamada no válido"
        )

    if (
        status == CALL_STATUS_DIALING
        and direction
        != CALL_DIRECTION_OUTBOUND
    ):
        raise InvalidProviderCallSnapshot(
            "DIALING solo es válido "
            "para llamadas salientes"
        )

    if (
        direction
        == CALL_DIRECTION_INBOUND
        and snapshot.dialed_at
    ):
        raise InvalidProviderCallSnapshot(
            "Una llamada entrante no debe "
            "tener dialed_at"
        )

    lifecycle_values = (
        snapshot.dialed_at,
        snapshot.ringing_at,
        snapshot.answered_at,
        snapshot.ended_at,
    )

    if (
        status == CALL_STATUS_CREATED
        and any(
            lifecycle_values
        )
    ):
        raise InvalidProviderCallSnapshot(
            "CREATED no admite timestamps "
            "de lifecycle"
        )

    if (
        status == CALL_STATUS_DIALING
        and any(
            (
                snapshot.ringing_at,
                snapshot.answered_at,
                snapshot.ended_at,
            )
        )
    ):
        raise InvalidProviderCallSnapshot(
            "DIALING contiene timestamps "
            "de estados posteriores"
        )

    if (
        status == CALL_STATUS_RINGING
        and any(
            (
                snapshot.answered_at,
                snapshot.ended_at,
            )
        )
    ):
        raise InvalidProviderCallSnapshot(
            "RINGING contiene timestamps "
            "de estados posteriores"
        )

    if (
        status == CALL_STATUS_ANSWERED
        and snapshot.ended_at
    ):
        raise InvalidProviderCallSnapshot(
            "ANSWERED no admite ended_at"
        )

    if (
        status
        in CALL_NON_ANSWERED_TERMINAL_STATUSES
        and snapshot.answered_at
    ):
        raise InvalidProviderCallSnapshot(
            "Una llamada no atendida no "
            "puede tener answered_at"
        )

    ring_duration = (
        _optional_duration(
            snapshot.ring_duration_seconds,
            field_name=(
                "ring_duration_seconds"
            ),
        )
    )

    talk_duration = (
        _optional_duration(
            snapshot.talk_duration_seconds,
            field_name=(
                "talk_duration_seconds"
            ),
        )
    )

    total_duration = (
        _optional_duration(
            snapshot.total_duration_seconds,
            field_name=(
                "total_duration_seconds"
            ),
        )
    )

    if (
        status
        not in CALL_TERMINAL_STATUSES
        and (
            talk_duration is not None
            or total_duration is not None
        )
    ):
        raise InvalidProviderCallSnapshot(
            "Una llamada activa no admite "
            "duraciones finales"
        )

    if (
        status
        in CALL_NON_ANSWERED_TERMINAL_STATUSES
        and talk_duration not in (
            None,
            0,
        )
    ):
        raise InvalidProviderCallSnapshot(
            "Una llamada no atendida debe "
            "tener duración hablada cero"
        )

    if (
        total_duration is not None
        and talk_duration is not None
        and total_duration
        < talk_duration
    ):
        raise InvalidProviderCallSnapshot(
            "La duración total no puede ser "
            "menor que la conversación"
        )

    if (
        total_duration is not None
        and ring_duration is not None
        and total_duration
        < ring_duration
    ):
        raise InvalidProviderCallSnapshot(
            "La duración total no puede ser "
            "menor que el timbrado"
        )

    metadata = snapshot.metadata

    if (
        metadata is not None
        and not isinstance(
            metadata,
            dict,
        )
    ):
        raise InvalidProviderCallSnapshot(
            "metadata debe ser dict o None"
        )

    return replace(
        snapshot,
        provider=provider,
        external_call_key=(
            external_call_key
        ),
        channel=channel,
        direction=direction,
        phone_number=phone_number,
        status=status,
        provider_call_id=(
            _optional_text(
                snapshot.provider_call_id
            )
        ),
        display_name_snapshot=(
            _optional_text(
                snapshot.display_name_snapshot
            )
        ),
        ring_duration_seconds=(
            ring_duration
        ),
        talk_duration_seconds=(
            talk_duration
        ),
        total_duration_seconds=(
            total_duration
        ),
        metadata=(
            dict(metadata)
            if metadata is not None
            else None
        ),
    )


def _merge_provider_duration(
    *,
    field_name,
    derived,
    supplied,
):
    if (
        derived is not None
        and supplied is not None
        and derived != supplied
    ):
        raise InvalidProviderCallSnapshot(
            "La duración calculada no coincide "
            f"con {field_name} del proveedor"
        )

    if derived is not None:
        return derived

    return supplied


def materialize_provider_call_snapshot(
    snapshot,
):
    """
    Convierte hechos históricos en CommunicationCall.

    No reproduce artificialmente transiciones realtime.
    No inventa timestamps ausentes.
    """
    normalized = (
        normalize_provider_call_snapshot(
            snapshot
        )
    )

    call = CommunicationCall(
        id=None,
        channel=normalized.channel,
        direction=normalized.direction,
        phone_number=(
            normalized.phone_number
        ),
        display_name_snapshot=(
            normalized.display_name_snapshot
        ),
        status=normalized.status,
        provider=normalized.provider,
        provider_call_id=(
            normalized.provider_call_id
        ),
        external_call_key=(
            normalized.external_call_key
        ),
        dialed_at=normalized.dialed_at,
        ringing_at=normalized.ringing_at,
        answered_at=normalized.answered_at,
        ended_at=normalized.ended_at,
        metadata=normalized.metadata,
    )

    timed = materialize_call_timing(
        call
    )

    ring_duration = (
        _merge_provider_duration(
            field_name=(
                "ring_duration_seconds"
            ),
            derived=(
                timed.ring_duration_seconds
            ),
            supplied=(
                normalized
                .ring_duration_seconds
            ),
        )
    )

    talk_duration = (
        _merge_provider_duration(
            field_name=(
                "talk_duration_seconds"
            ),
            derived=(
                timed.talk_duration_seconds
            ),
            supplied=(
                normalized
                .talk_duration_seconds
            ),
        )
    )

    total_duration = (
        _merge_provider_duration(
            field_name=(
                "total_duration_seconds"
            ),
            derived=(
                timed.total_duration_seconds
            ),
            supplied=(
                normalized
                .total_duration_seconds
            ),
        )
    )

    if (
        normalized.status
        in CALL_NON_ANSWERED_TERMINAL_STATUSES
        and talk_duration is None
    ):
        # Esto no es un timestamp inventado.
        # Es una consecuencia semántica conocida:
        # una llamada nunca atendida tiene 0 segundos
        # de conversación.
        talk_duration = 0

    return replace(
        timed,
        ring_duration_seconds=(
            ring_duration
        ),
        talk_duration_seconds=(
            talk_duration
        ),
        total_duration_seconds=(
            total_duration
        ),
    )

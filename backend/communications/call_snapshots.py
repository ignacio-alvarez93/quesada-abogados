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
    _parse_call_timestamp,
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


# ============================================================
# RECONCILIACIÓN DE SNAPSHOT CONTRA LLAMADA YA PERSISTIDA
# ============================================================

CALL_RECONCILIATION_ALLOWED_TARGETS = {
    CALL_STATUS_CREATED: CALL_SNAPSHOT_STATUSES,
    CALL_STATUS_DIALING: frozenset(
        {
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
    ),
    CALL_STATUS_RINGING: frozenset(
        {
            CALL_STATUS_RINGING,
            CALL_STATUS_ANSWERED,
            CALL_STATUS_ENDED,
            CALL_STATUS_MISSED,
            CALL_STATUS_REJECTED,
            CALL_STATUS_BUSY,
            CALL_STATUS_FAILED,
            CALL_STATUS_CANCELLED,
        }
    ),
    CALL_STATUS_ANSWERED: frozenset(
        {
            CALL_STATUS_ANSWERED,
            CALL_STATUS_ENDED,
        }
    ),
    CALL_STATUS_ENDED: frozenset(
        {
            CALL_STATUS_ENDED,
        }
    ),
    CALL_STATUS_MISSED: frozenset(
        {
            CALL_STATUS_MISSED,
        }
    ),
    CALL_STATUS_REJECTED: frozenset(
        {
            CALL_STATUS_REJECTED,
        }
    ),
    CALL_STATUS_BUSY: frozenset(
        {
            CALL_STATUS_BUSY,
        }
    ),
    CALL_STATUS_FAILED: frozenset(
        {
            CALL_STATUS_FAILED,
        }
    ),
    CALL_STATUS_CANCELLED: frozenset(
        {
            CALL_STATUS_CANCELLED,
        }
    ),
}


class ProviderCallReconciliationConflict(
    ValueError
):
    """
    El snapshot es válido aisladamente pero contradice
    conocimiento ya persistido de la misma llamada.
    """


def _raise_reconciliation_conflict(
    field_name,
    existing,
    incoming,
):
    raise ProviderCallReconciliationConflict(
        "Conflicto de reconciliación "
        f"en {field_name}: "
        f"{existing!r} != {incoming!r}"
    )


def _merge_strict_optional_value(
    *,
    field_name,
    existing,
    incoming,
):
    if incoming is None:
        return existing

    if existing is None:
        return incoming

    if existing != incoming:
        _raise_reconciliation_conflict(
            field_name,
            existing,
            incoming,
        )

    return existing


def _merge_timestamp_value(
    *,
    field_name,
    existing,
    incoming,
):
    if incoming is None:
        return existing

    if existing is None:
        return incoming

    existing_dt = (
        _parse_call_timestamp(
            existing
        )
    )

    incoming_dt = (
        _parse_call_timestamp(
            incoming
        )
    )

    if existing_dt != incoming_dt:
        _raise_reconciliation_conflict(
            field_name,
            existing,
            incoming,
        )

    # Conservamos la representación ya persistida.
    return existing


def _merge_duration_values(
    *,
    field_name,
    values,
):
    known = [
        int(value)
        for value in values
        if value is not None
    ]

    if not known:
        return None

    first = known[0]

    for value in known[1:]:
        if value != first:
            _raise_reconciliation_conflict(
                field_name,
                first,
                value,
            )

    return first


def _merge_provider_metadata(
    existing,
    incoming,
):
    if existing is None and incoming is None:
        return None

    merged = dict(
        existing
        or {}
    )

    for key, value in (
        incoming
        or {}
    ).items():
        if key not in merged:
            merged[key] = value

        elif merged[key] == value:
            continue

        else:
            # La reconciliación no pisa silenciosamente
            # conocimiento ya materializado en CRM.
            continue

    return merged


def merge_provider_call_snapshot(
    existing,
    snapshot,
):
    """
    Enriquece una CommunicationCall existente con un snapshot.

    Reglas:
    - identidad/canal/dirección son inmutables;
    - contexto CRM nunca se reemplaza;
    - provider_call_id solo puede rellenarse o repetirse;
    - display_name solo rellena un hueco;
    - timestamps conocidos no pueden cambiar;
    - estados no pueden retroceder ni cambiar entre
      terminales incompatibles;
    - metadata existente prevalece en conflictos;
    - no inventa timestamps.
    """
    if not isinstance(
        existing,
        CommunicationCall,
    ):
        raise ProviderCallReconciliationConflict(
            "Se requiere una CommunicationCall "
            "existente"
        )

    incoming = (
        materialize_provider_call_snapshot(
            snapshot
        )
    )

    immutable_fields = (
        "provider",
        "external_call_key",
        "channel",
        "direction",
    )

    for field_name in immutable_fields:
        existing_value = getattr(
            existing,
            field_name,
        )

        incoming_value = getattr(
            incoming,
            field_name,
        )

        if existing_value != incoming_value:
            _raise_reconciliation_conflict(
                field_name,
                existing_value,
                incoming_value,
            )

    current_status = str(
        existing.status
        or ""
    ).strip().upper()

    target_status = str(
        incoming.status
        or ""
    ).strip().upper()

    allowed = (
        CALL_RECONCILIATION_ALLOWED_TARGETS
        .get(
            current_status,
            frozenset(),
        )
    )

    if target_status not in allowed:
        _raise_reconciliation_conflict(
            "status",
            current_status,
            target_status,
        )

    provider_call_id = (
        _merge_strict_optional_value(
            field_name="provider_call_id",
            existing=(
                existing.provider_call_id
            ),
            incoming=(
                incoming.provider_call_id
            ),
        )
    )

    display_name_snapshot = (
        existing.display_name_snapshot
        or incoming.display_name_snapshot
    )

    dialed_at = _merge_timestamp_value(
        field_name="dialed_at",
        existing=existing.dialed_at,
        incoming=incoming.dialed_at,
    )

    ringing_at = _merge_timestamp_value(
        field_name="ringing_at",
        existing=existing.ringing_at,
        incoming=incoming.ringing_at,
    )

    answered_at = _merge_timestamp_value(
        field_name="answered_at",
        existing=existing.answered_at,
        incoming=incoming.answered_at,
    )

    ended_at = _merge_timestamp_value(
        field_name="ended_at",
        existing=existing.ended_at,
        incoming=incoming.ended_at,
    )

    metadata = _merge_provider_metadata(
        existing.metadata,
        incoming.metadata,
    )

    merged = replace(
        existing,
        provider_call_id=provider_call_id,
        display_name_snapshot=(
            display_name_snapshot
        ),
        status=target_status,
        dialed_at=dialed_at,
        ringing_at=ringing_at,
        answered_at=answered_at,
        ended_at=ended_at,
        metadata=metadata,
    )

    timed = materialize_call_timing(
        merged
    )

    ring_duration = (
        _merge_duration_values(
            field_name=(
                "ring_duration_seconds"
            ),
            values=(
                existing
                .ring_duration_seconds,
                incoming
                .ring_duration_seconds,
                timed
                .ring_duration_seconds,
            ),
        )
    )

    talk_duration = (
        _merge_duration_values(
            field_name=(
                "talk_duration_seconds"
            ),
            values=(
                existing
                .talk_duration_seconds,
                incoming
                .talk_duration_seconds,
                timed
                .talk_duration_seconds,
            ),
        )
    )

    total_duration = (
        _merge_duration_values(
            field_name=(
                "total_duration_seconds"
            ),
            values=(
                existing
                .total_duration_seconds,
                incoming
                .total_duration_seconds,
                timed
                .total_duration_seconds,
            ),
        )
    )

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

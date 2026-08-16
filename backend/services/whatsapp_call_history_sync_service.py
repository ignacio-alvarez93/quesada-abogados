from collections import Counter
import re

from backend.communications.call_snapshots import (
    materialize_provider_call_snapshot,
)
from backend.services.whatsapp_call_history_adapter import (
    WhatsAppHistoricalCallSnapshot,
    project_whatsapp_history_snapshot,
)


_EXTERNAL_KEY_RE = re.compile(
    r"^(?:true|false)_(.+?@lid)_(.+)$",
    flags=re.IGNORECASE,
)


def _required_text(
    value,
    *,
    field_name,
):
    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise ValueError(
            f"{field_name} es obligatorio"
        )

    return text


def _peer_lid_from_external_key(
    value,
):
    text = _required_text(
        value,
        field_name="external_call_key",
    )

    match = _EXTERNAL_KEY_RE.match(
        text
    )

    if not match:
        raise ValueError(
            "external_call_key WhatsApp inválida"
        )

    return match.group(1)


def _build_historical_snapshot(
    item,
):
    if not isinstance(
        item,
        dict,
    ):
        raise TypeError(
            "El item histórico debe ser dict"
        )

    external_key = _required_text(
        item.get(
            "external_call_key"
        ),
        field_name="external_call_key",
    )

    peer_lid = _required_text(
        item.get(
            "peer_lid"
        ),
        field_name="peer_lid",
    )

    key_peer_lid = (
        _peer_lid_from_external_key(
            external_key
        )
    )

    if (
        key_peer_lid
        != peer_lid
    ):
        raise ValueError(
            "peer_lid no coincide con "
            "external_call_key"
        )

    return WhatsAppHistoricalCallSnapshot(
        provider_call_id=_required_text(
            item.get(
                "provider_call_id"
            ),
            field_name="provider_call_id",
        ),
        external_call_key=external_key,
        peer_lid=peer_lid,
        peer_phone_id=item.get(
            "peer_phone_id"
        ),
        peer_display_name=item.get(
            "peer_display_name"
        ),
        provider_timestamp=item.get(
            "provider_timestamp"
        ),
        call_duration_seconds=item.get(
            "call_duration_seconds"
        ),
        raw_outcome=item.get(
            "raw_outcome"
        ),
        raw_final_outcome=item.get(
            "raw_final_outcome"
        ),
        row_state=item.get(
            "row_state"
        ),
        is_video=item.get(
            "is_video"
        ),
    )


def build_whatsapp_history_reconciliation_plan(
    history_result,
):
    """
    Construye snapshots reconciliables sin persistir.

    No conoce repositorios.
    No conoce SQLite.
    No llama reconcile_provider_call().
    """
    if not isinstance(
        history_result,
        dict,
    ):
        raise TypeError(
            "history_result debe ser dict"
        )

    raw_items = list(
        history_result.get(
            "items"
        )
        or []
    )

    snapshots = []
    errors = []
    status_counts = Counter()

    for index, item in enumerate(
        raw_items
    ):
        try:
            historical = (
                _build_historical_snapshot(
                    item
                )
            )

            provider_snapshot = (
                project_whatsapp_history_snapshot(
                    historical
                )
            )

            # Validación final mediante el
            # dominio puro existente.
            materialized = (
                materialize_provider_call_snapshot(
                    provider_snapshot
                )
            )

        except Exception as exc:
            errors.append({
                "index":
                    index,
                "external_call_key":
                    (
                        item.get(
                            "external_call_key"
                        )
                        if isinstance(
                            item,
                            dict,
                        )
                        else None
                    ),
                "error_type":
                    type(exc).__name__,
                "message":
                    str(exc),
            })

            continue

        snapshots.append(
            provider_snapshot
        )

        status_counts[
            materialized.status
        ] += 1

    return {
        "source_items":
            len(raw_items),

        "planned":
            len(snapshots),

        "errors":
            errors,

        "status_counts":
            dict(
                sorted(
                    status_counts.items()
                )
            ),

        "snapshots":
            tuple(
                snapshots
            ),
    }

"""
Servicio de aplicación para llamadas de Comunicaciones.

Responsabilidades:
- crear llamadas entrantes y salientes;
- aplicar eventos de lifecycle mediante el dominio;
- persistir estado y timing;
- generar seguimiento operativo para llamadas
  entrantes perdidas;
- exponer el inventario de llamadas pendientes.

No contiene SQL.
No conoce Flet.
No conoce SeleniumBase.
No conoce Enlace móvil.
No controla directamente proveedores.
"""

from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_CREATED,
    CALL_STATUS_MISSED,
    CommunicationCall,
    transition_call_status_at,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)


class CommunicationCallService:
    def __init__(
        self,
        repository=None,
    ):
        self.repository = (
            repository
            or SQLiteCommunicationRepository()
        )

    def ensure_schema(self):
        self.repository.ensure_schema()

    def get_call(
        self,
        call_id,
    ):
        if call_id in (
            None,
            "",
        ):
            return None

        return self.repository.get_call(
            int(call_id)
        )

    @staticmethod
    def _normalize_required_text(
        value,
        *,
        field_name,
    ):
        normalized = str(
            value
            or ""
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} es obligatorio"
            )

        return normalized

    def _create_call(
        self,
        *,
        channel,
        direction,
        phone_number,
        thread_id=None,
        client_id=None,
        expedient_id=None,
        display_name_snapshot=None,
        reason_code=None,
        reason_detail=None,
        provider=None,
        provider_call_id=None,
        external_call_key=None,
        notes=None,
        created_by=None,
        metadata=None,
    ):
        normalized_channel = (
            self._normalize_required_text(
                channel,
                field_name="channel",
            )
            .upper()
        )

        normalized_phone = (
            self._normalize_required_text(
                phone_number,
                field_name="phone_number",
            )
        )

        normalized_direction = str(
            direction
            or ""
        ).strip().upper()

        if normalized_direction not in (
            CALL_DIRECTION_INBOUND,
            CALL_DIRECTION_OUTBOUND,
        ):
            raise ValueError(
                "Dirección de llamada no válida"
            )

        return self.repository.create_call(
            CommunicationCall(
                id=None,
                channel=normalized_channel,
                direction=normalized_direction,
                phone_number=normalized_phone,
                thread_id=(
                    int(thread_id)
                    if thread_id is not None
                    else None
                ),
                client_id=(
                    int(client_id)
                    if client_id is not None
                    else None
                ),
                expedient_id=(
                    int(expedient_id)
                    if expedient_id is not None
                    else None
                ),
                display_name_snapshot=(
                    str(
                        display_name_snapshot
                        or ""
                    ).strip()
                    or None
                ),
                reason_code=(
                    str(
                        reason_code
                        or ""
                    ).strip().upper()
                    or None
                ),
                reason_detail=(
                    str(
                        reason_detail
                        or ""
                    ).strip()
                    or None
                ),
                status=CALL_STATUS_CREATED,
                provider=(
                    str(
                        provider
                        or ""
                    ).strip().upper()
                    or None
                ),
                provider_call_id=(
                    str(
                        provider_call_id
                        or ""
                    ).strip()
                    or None
                ),
                external_call_key=(
                    str(
                        external_call_key
                        or ""
                    ).strip()
                    or None
                ),
                notes=(
                    str(
                        notes
                        or ""
                    ).strip()
                    or None
                ),
                created_by=(
                    str(
                        created_by
                        or ""
                    ).strip()
                    or None
                ),
                metadata=metadata,
            )
        )

    def create_inbound_call(
        self,
        *,
        channel,
        phone_number,
        thread_id=None,
        client_id=None,
        expedient_id=None,
        display_name_snapshot=None,
        reason_code=None,
        reason_detail=None,
        provider=None,
        provider_call_id=None,
        external_call_key=None,
        notes=None,
        created_by=None,
        metadata=None,
    ):
        return self._create_call(
            channel=channel,
            direction=CALL_DIRECTION_INBOUND,
            phone_number=phone_number,
            thread_id=thread_id,
            client_id=client_id,
            expedient_id=expedient_id,
            display_name_snapshot=(
                display_name_snapshot
            ),
            reason_code=reason_code,
            reason_detail=reason_detail,
            provider=provider,
            provider_call_id=provider_call_id,
            external_call_key=(
                external_call_key
            ),
            notes=notes,
            created_by=created_by,
            metadata=metadata,
        )

    def create_outbound_call(
        self,
        *,
        channel,
        phone_number,
        thread_id=None,
        client_id=None,
        expedient_id=None,
        display_name_snapshot=None,
        reason_code=None,
        reason_detail=None,
        provider=None,
        provider_call_id=None,
        external_call_key=None,
        notes=None,
        created_by=None,
        metadata=None,
    ):
        return self._create_call(
            channel=channel,
            direction=CALL_DIRECTION_OUTBOUND,
            phone_number=phone_number,
            thread_id=thread_id,
            client_id=client_id,
            expedient_id=expedient_id,
            display_name_snapshot=(
                display_name_snapshot
            ),
            reason_code=reason_code,
            reason_detail=reason_detail,
            provider=provider,
            provider_call_id=provider_call_id,
            external_call_key=(
                external_call_key
            ),
            notes=notes,
            created_by=created_by,
            metadata=metadata,
        )

    def apply_call_event(
        self,
        call_id,
        *,
        status,
        event_at,
    ):
        """
        Aplica un evento de proveedor sobre una llamada.

        El servicio:
        1. recupera la llamada;
        2. delega transición/timing al dominio;
        3. persiste lifecycle;
        4. si acaba como INBOUND + MISSED,
           crea de forma idempotente su seguimiento PENDING.
        """
        call = self.repository.get_call(
            int(call_id)
        )

        if call is None:
            raise ValueError(
                "Llamada de comunicación "
                "no encontrada"
            )

        transitioned = (
            transition_call_status_at(
                call,
                status,
                event_at,
            )
        )

        persisted = (
            self.repository
            .update_call_state(
                transitioned
            )
        )

        if (
            persisted.direction
            == CALL_DIRECTION_INBOUND
            and persisted.status
            == CALL_STATUS_MISSED
        ):
            (
                self.repository
                .get_or_create_call_follow_up(
                    persisted.id
                )
            )

        return persisted

    def list_pending_follow_ups(
        self,
        *,
        limit=500,
    ):
        return (
            self.repository
            .list_pending_call_follow_ups(
                limit=max(
                    1,
                    int(limit),
                )
            )
        )

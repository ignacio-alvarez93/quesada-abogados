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

from backend.communications.call_snapshots import (
    materialize_provider_call_snapshot,
    merge_provider_call_snapshot,
)
from backend.communications.call_followups import (
    CALL_FOLLOW_UP_IN_PROGRESS,
    CALL_FOLLOW_UP_PENDING,
    CALL_FOLLOW_UP_RESOLVED,
    transition_call_follow_up,
)
from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_BUSY,
    CALL_STATUS_CANCELLED,
    CALL_STATUS_CREATED,
    CALL_STATUS_FAILED,
    CALL_STATUS_MISSED,
    CALL_STATUS_REJECTED,
    CommunicationCall,
    transition_call_status_at,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)


CALLBACK_REQUEUE_STATUSES = frozenset(
    {
        CALL_STATUS_MISSED,
        CALL_STATUS_REJECTED,
        CALL_STATUS_BUSY,
        CALL_STATUS_FAILED,
        CALL_STATUS_CANCELLED,
    }
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

        candidate = CommunicationCall(
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

        persisted, created = (
            self.repository
            .get_or_create_call_with_identity(
                candidate
            )
        )

        if not created:
            if (
                persisted.channel
                != candidate.channel
                or persisted.direction
                != candidate.direction
            ):
                raise ValueError(
                    "Conflicto de identidad externa "
                    "de llamada"
                )

        return persisted

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

    def create_callback_call(
        self,
        source_call_id,
        *,
        channel=None,
        reason_code=None,
        reason_detail=None,
        provider=None,
        notes=None,
        created_by=None,
        metadata=None,
    ):
        """
        Crea un nuevo intento de devolución.

        El dominio valida PENDING -> IN_PROGRESS.

        El repository reclama PENDING mediante compare-and-set
        y persiste atómicamente:

        - follow-up IN_PROGRESS;
        - CommunicationCall OUTBOUND;
        - relación de callback.
        """
        source = self.repository.get_call(
            int(source_call_id)
        )

        if source is None:
            raise ValueError(
                "Llamada origen no encontrada"
            )

        if (
            source.direction
            != CALL_DIRECTION_INBOUND
            or source.status
            != CALL_STATUS_MISSED
        ):
            raise ValueError(
                "La devolución requiere una "
                "llamada entrante perdida"
            )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        if follow_up is None:
            raise ValueError(
                "La llamada perdida no tiene "
                "seguimiento operativo"
            )

        if (
            follow_up.status
            == CALL_FOLLOW_UP_RESOLVED
        ):
            raise ValueError(
                "El seguimiento de llamada "
                "ya está resuelto"
            )

        if (
            follow_up.status
            != CALL_FOLLOW_UP_PENDING
        ):
            raise ValueError(
                "El seguimiento de llamada "
                "ya está en curso"
            )

        active = transition_call_follow_up(
            follow_up,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        callback_channel = (
            self._normalize_required_text(
                (
                    channel
                    or source.channel
                ),
                field_name="channel",
            )
            .upper()
        )

        callback_phone = (
            self._normalize_required_text(
                source.phone_number,
                field_name="phone_number",
            )
        )

        resolved_reason_code = str(
            (
                reason_code
                if reason_code is not None
                else source.reason_code
            )
            or ""
        ).strip().upper() or None

        resolved_reason_detail = str(
            (
                reason_detail
                if reason_detail is not None
                else source.reason_detail
            )
            or ""
        ).strip() or None

        resolved_provider = str(
            (
                provider
                if provider is not None
                else source.provider
            )
            or ""
        ).strip().upper() or None

        callback_candidate = CommunicationCall(
            id=None,
            channel=callback_channel,
            direction=CALL_DIRECTION_OUTBOUND,
            phone_number=callback_phone,
            thread_id=source.thread_id,
            client_id=source.client_id,
            expedient_id=(
                source.expedient_id
            ),
            display_name_snapshot=(
                source.display_name_snapshot
            ),
            reason_code=(
                resolved_reason_code
            ),
            reason_detail=(
                resolved_reason_detail
            ),
            status=CALL_STATUS_CREATED,
            provider=resolved_provider,
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

        (
            callback,
            _relation,
            _claimed_follow_up,
        ) = (
            self.repository
            .create_callback_workflow(
                source_call_id=source.id,
                callback=callback_candidate,
                follow_up=active,
                expected_follow_up_status=(
                    follow_up.status
                ),
            )
        )

        return callback

    def resolve_follow_up(
        self,
        follow_up_id,
        *,
        resolved_at,
    ):
        """
        Marca explícitamente como resuelto un seguimiento.

        No se resuelve automáticamente por el mero hecho
        de que una devolución haya sido contestada.
        """
        follow_up = (
            self.repository
            .get_call_follow_up(
                int(follow_up_id)
            )
        )

        if follow_up is None:
            raise ValueError(
                "Seguimiento de llamada "
                "no encontrado"
            )

        resolved = transition_call_follow_up(
            follow_up,
            CALL_FOLLOW_UP_RESOLVED,
            resolved_at=resolved_at,
        )

        return (
            self.repository
            .update_call_follow_up(
                resolved
            )
        )

    def list_callback_calls(
        self,
        source_call_id,
        *,
        limit=100,
    ):
        return (
            self.repository
            .list_callback_calls(
                int(source_call_id),
                limit=max(
                    1,
                    int(limit),
                ),
            )
        )

    def _requeue_callback_follow_up_if_needed(
        self,
        call,
    ):
        """
        Si una devolución termina sin contacto efectivo,
        vuelve a dejar su seguimiento en PENDING.
        """
        relation = (
            self.repository
            .get_call_callback_by_callback_call(
                call.id
            )
        )

        if relation is None:
            return None

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                relation.source_call_id
            )
        )

        if follow_up is None:
            return None

        if (
            follow_up.status
            == CALL_FOLLOW_UP_RESOLVED
        ):
            return follow_up

        pending = transition_call_follow_up(
            follow_up,
            CALL_FOLLOW_UP_PENDING,
        )

        if pending is follow_up:
            return follow_up

        return (
            self.repository
            .update_call_follow_up(
                pending
            )
        )

    def reconcile_provider_call(
        self,
        snapshot,
    ):
        """
        Incorpora o enriquece un snapshot histórico.

        Una llamada histórica nueva INBOUND + MISSED se crea
        junto a su follow-up en la misma transacción.

        Si una llamada existente avanza a MISSED mediante
        reconciliación, actualización + follow-up también son
        atómicos.
        """
        materialized = (
            materialize_provider_call_snapshot(
                snapshot
            )
        )

        requires_follow_up = (
            materialized.direction
            == CALL_DIRECTION_INBOUND
            and materialized.status
            == CALL_STATUS_MISSED
        )

        persisted, created = (
            self.repository
            .get_or_create_call_with_identity(
                materialized,
                create_follow_up_if_created=(
                    requires_follow_up
                ),
            )
        )

        follow_up_guaranteed = (
            created
            and requires_follow_up
        )

        if not created:
            merged = (
                merge_provider_call_snapshot(
                    persisted,
                    snapshot,
                )
            )

            if merged != persisted:
                if (
                    merged.direction
                    == CALL_DIRECTION_INBOUND
                    and merged.status
                    == CALL_STATUS_MISSED
                ):
                    (
                        persisted,
                        _follow_up,
                    ) = (
                        self.repository
                        .update_call_provider_reconciliation_with_follow_up(
                            merged
                        )
                    )

                    follow_up_guaranteed = True

                else:
                    persisted = (
                        self.repository
                        .update_call_provider_reconciliation(
                            merged
                        )
                    )

        if (
            persisted.direction
            == CALL_DIRECTION_INBOUND
            and persisted.status
            == CALL_STATUS_MISSED
            and not follow_up_guaranteed
        ):
            # Reparación idempotente para llamadas MISSED
            # ya existentes cuyo lifecycle no necesita cambio.
            (
                self.repository
                .get_or_create_call_follow_up(
                    persisted.id
                )
            )

        if (
            persisted.direction
            == CALL_DIRECTION_OUTBOUND
            and persisted.status
            in CALLBACK_REQUEUE_STATUSES
        ):
            (
                self
                ._requeue_callback_follow_up_if_needed(
                    persisted
                )
            )

        return persisted

    def apply_call_event(
        self,
        call_id,
        *,
        status,
        event_at,
    ):
        """
        Aplica un evento realtime de proveedor.

        INBOUND + MISSED se persiste junto a su follow-up
        dentro de una única transacción.
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

        if (
            transitioned.direction
            == CALL_DIRECTION_INBOUND
            and transitioned.status
            == CALL_STATUS_MISSED
        ):
            (
                persisted,
                _follow_up,
            ) = (
                self.repository
                .update_call_state_with_follow_up(
                    transitioned
                )
            )

        else:
            persisted = (
                self.repository
                .update_call_state(
                    transitioned
                )
            )

        if (
            persisted.direction
            == CALL_DIRECTION_OUTBOUND
            and persisted.status
            in CALLBACK_REQUEUE_STATUSES
        ):
            (
                self
                ._requeue_callback_follow_up_if_needed(
                    persisted
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

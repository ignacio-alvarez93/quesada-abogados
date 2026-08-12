"""
Orquestación de salida WhatsApp desde Comunicaciones.

Responsabilidades:
- crear el mensaje local antes de enviar;
- registrar el intento de transporte;
- ejecutar el conector WhatsApp;
- asociar la identidad real del proveedor;
- finalizar estados de mensaje e intento.

No contiene SQL.
No conoce Flet.
"""

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppSendStateUncertainError,
)
from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    MESSAGE_STATUS_ERROR,
    MESSAGE_STATUS_SENDING,
    MESSAGE_STATUS_SENT,
)
from backend.services.communication_service import (
    CommunicationService,
)


WHATSAPP_TRANSPORT = (
    "SELENIUMBASE_WEB"
)

SEND_ERROR_CODE = (
    "SEND_FAILED"
)

SEND_STATE_UNCERTAIN_ERROR_CODE = (
    "SEND_STATE_UNCERTAIN"
)

POST_SEND_PERSISTENCE_ERROR_CODE = (
    "POST_SEND_PERSISTENCE_FAILED"
)

STATE_TRANSITION_ERROR_CODE = (
    "STATE_TRANSITION_FAILED"
)


class WhatsAppOutboundService:
    def __init__(
        self,
        *,
        connector,
        communication_service=None,
    ):
        if connector is None:
            raise ValueError(
                "connector es obligatorio"
            )

        self.connector = connector

        self.communication_service = (
            communication_service
            or CommunicationService()
        )

    def _finish_attempt_error(
        self,
        attempt,
        *,
        error_code,
        error,
        metadata=None,
    ):
        if not attempt:
            return None

        return (
            self.communication_service
            .finish_message_attempt(
                attempt.id,
                status=(
                    ATTEMPT_STATUS_ERROR
                ),
                error_code=(
                    error_code
                ),
                error_message=(
                    str(
                        error
                    )
                ),
                metadata=metadata,
            )
        )

    def send_text_message(
        self,
        *,
        thread_id,
        body_text,
        expedient_id=None,
        created_by=None,
        sent_by=None,
        metadata=None,
        timeout=10,
    ):
        """Envía y persiste un mensaje WhatsApp trazable.

        Nunca reintenta automáticamente un envío incierto.
        """
        message = (
            self.communication_service
            .create_outbound_message(
                thread_id=(
                    thread_id
                ),
                body_text=(
                    body_text
                ),
                expedient_id=(
                    expedient_id
                ),
                created_by=(
                    created_by
                ),
                metadata=(
                    metadata
                ),
            )
        )

        attempt = (
            self.communication_service
            .start_message_attempt(
                message_id=(
                    message.id
                ),
                transport=(
                    WHATSAPP_TRANSPORT
                ),
                metadata={
                    "source":
                        "whatsapp_outbound_service",
                },
            )
        )

        try:
            sending = (
                self.communication_service
                .update_message_status(
                    message.id,
                    MESSAGE_STATUS_SENDING,
                )
            )

        except Exception as exc:
            self._finish_attempt_error(
                attempt,
                error_code=(
                    STATE_TRANSITION_ERROR_CODE
                ),
                error=exc,
            )

            raise

        try:
            snapshot = (
                self.connector
                .send_text_message(
                    sending.body_text,
                    timeout=timeout,
                )
            )

        except WhatsAppSendStateUncertainError as exc:
            finished_attempt = (
                self._finish_attempt_error(
                    attempt,
                    error_code=(
                        SEND_STATE_UNCERTAIN_ERROR_CODE
                    ),
                    error=exc,
                    metadata={
                        "uncertain": True,
                        "automatic_retry":
                            False,
                    },
                )
            )

            # El mensaje permanece SENDING:
            # pudo haberse enviado realmente.
            return {
                "ok": False,
                "uncertain": True,
                "message": (
                    self.communication_service
                    .get_message(
                        message.id
                    )
                ),
                "attempt":
                    finished_attempt,
                "provider_snapshot":
                    None,
                "error":
                    str(exc),
            }

        except Exception as exc:
            try:
                failed_message = (
                    self.communication_service
                    .update_message_status(
                        message.id,
                        MESSAGE_STATUS_ERROR,
                    )
                )
            finally:
                finished_attempt = (
                    self._finish_attempt_error(
                        attempt,
                        error_code=(
                            SEND_ERROR_CODE
                        ),
                        error=exc,
                        metadata={
                            "uncertain": False,
                            "automatic_retry":
                                False,
                        },
                    )
                )

            return {
                "ok": False,
                "uncertain": False,
                "message":
                    failed_message,
                "attempt":
                    finished_attempt,
                "provider_snapshot":
                    None,
                "error":
                    str(exc),
            }

        try:
            (
                self.communication_service
                .attach_message_provider_identity(
                    message.id,
                    provider_message_id=(
                        snapshot
                        .provider_message_id
                    ),
                    provider_timestamp=(
                        snapshot
                        .provider_timestamp
                    ),
                )
            )

            sent_message = (
                self.communication_service
                .update_message_status(
                    message.id,
                    MESSAGE_STATUS_SENT,
                    sent_by=(
                        sent_by
                        or created_by
                    ),
                )
            )

            finished_attempt = (
                self.communication_service
                .finish_message_attempt(
                    attempt.id,
                    status=(
                        ATTEMPT_STATUS_SENT
                    ),
                    metadata={
                        "provider_message_id":
                            snapshot
                            .provider_message_id,
                    },
                )
            )

        except Exception as exc:
            finished_attempt = (
                self._finish_attempt_error(
                    attempt,
                    error_code=(
                        POST_SEND_PERSISTENCE_ERROR_CODE
                    ),
                    error=exc,
                    metadata={
                        "uncertain": True,
                        "automatic_retry":
                            False,
                        "provider_message_id":
                            getattr(
                                snapshot,
                                "provider_message_id",
                                None,
                            ),
                    },
                )
            )

            # El transporte ya confirmó el envío.
            # No marcar ERROR ni reintentar.
            return {
                "ok": False,
                "uncertain": True,
                "message": (
                    self.communication_service
                    .get_message(
                        message.id
                    )
                ),
                "attempt":
                    finished_attempt,
                "provider_snapshot":
                    snapshot,
                "error":
                    str(exc),
            }

        return {
            "ok": True,
            "uncertain": False,
            "message":
                sent_message,
            "attempt":
                finished_attempt,
            "provider_snapshot":
                snapshot,
            "error":
                None,
        }

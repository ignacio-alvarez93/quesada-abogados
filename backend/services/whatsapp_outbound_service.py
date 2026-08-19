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

from pathlib import Path

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppSendStateUncertainError,
)
from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    MESSAGE_STATUS_ERROR,
    MESSAGE_TYPE_DOCUMENT,
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
        reply_to_message_id=None,
        timeout=10,
    ):
        """Envía y persiste un mensaje WhatsApp trazable.

        Puede responder a un mensaje CRM existente mediante
        ``reply_to_message_id``.

        Nunca reintenta automáticamente un envío incierto.
        """
        normalized_metadata = dict(
            metadata
            or {}
        )

        reply_target = None

        if reply_to_message_id not in (
            None,
            "",
        ):
            reply_target = (
                self.communication_service
                .get_message(
                    int(
                        reply_to_message_id
                    )
                )
            )

            if reply_target is None:
                raise ValueError(
                    "Mensaje citado no encontrado"
                )

            if (
                int(
                    reply_target.thread_id
                )
                != int(
                    thread_id
                )
            ):
                raise ValueError(
                    "El mensaje citado pertenece "
                    "a otra conversación"
                )

            provider_id = str(
                reply_target.provider_message_id
                or ""
            ).strip()

            if not provider_id:
                raise ValueError(
                    "El mensaje citado no tiene "
                    "provider_message_id"
                )

            target_metadata = (
                dict(
                    reply_target.metadata
                    or {}
                )
                if isinstance(
                    reply_target.metadata,
                    dict,
                )
                else {}
            )

            sender = str(
                target_metadata.get(
                    "sender"
                )
                or ""
            ).strip()

            if (
                not sender
                and str(
                    getattr(
                        reply_target,
                        "direction",
                        "",
                    )
                    or ""
                ).strip().upper()
                == "OUTBOUND"
            ):
                sender = "Tú"

            # La relación de cita siempre se construye
            # desde el mensaje persistido. El frontend
            # no puede falsificar provider/body/sender.
            normalized_metadata[
                "reply"
            ] = {
                "provider_message_id":
                    provider_id,
                "sender":
                    sender or None,
                "body_text":
                    str(
                        reply_target.body_text
                        or ""
                    ),
            }

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
                    normalized_metadata
                    or None
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
            if reply_target is None:
                snapshot = (
                    self.connector
                    .send_text_message(
                        sending.body_text,
                        timeout=timeout,
                    )
                )

            else:
                snapshot = (
                    self.connector
                    .send_reply_message(
                        sending.body_text,
                        reply_to_provider_message_id=(
                            reply_target
                            .provider_message_id
                        ),
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

    def send_document_message(
        self,
        *,
        thread_id,
        file_path,
        expedient_id=None,
        created_by=None,
        sent_by=None,
        metadata=None,
        timeout=12,
    ):
        """Envía y persiste un documento WhatsApp trazable.

        La ruta local es exclusivamente transitoria:
        nunca se persiste en metadata.

        Igual que send_text_message(), nunca reintenta
        automáticamente un transporte incierto.
        """
        path = Path(
            file_path
        ).expanduser()

        try:
            path = path.resolve(
                strict=True
            )
        except Exception as exc:
            raise FileNotFoundError(
                "El archivo adjunto no existe"
            ) from exc

        if not path.is_file():
            raise ValueError(
                "La ruta del adjunto no es un archivo"
            )

        filename = path.name
        file_size = int(
            path.stat().st_size
        )

        message_metadata = dict(
            metadata
            or {}
        )

        # Campos gobernados:
        # el caller no puede convertir este transporte
        # documental en otro tipo semántico.
        message_metadata[
            "message_type"
        ] = MESSAGE_TYPE_DOCUMENT

        message_metadata[
            "filename"
        ] = filename

        message_metadata[
            "file_size_bytes"
        ] = file_size

        message = (
            self.communication_service
            .create_outbound_message(
                thread_id=thread_id,
                body_text="",
                expedient_id=(
                    expedient_id
                ),
                created_by=(
                    created_by
                ),
                metadata=(
                    message_metadata
                ),
            )
        )

        attempt_metadata = {
            "source":
                "whatsapp_outbound_service",
            "message_type":
                MESSAGE_TYPE_DOCUMENT,
            "filename":
                filename,
        }

        attempt = (
            self.communication_service
            .start_message_attempt(
                message_id=(
                    message.id
                ),
                transport=(
                    WHATSAPP_TRANSPORT
                ),
                metadata=(
                    attempt_metadata
                ),
            )
        )

        try:
            self.communication_service \
                .update_message_status(
                    message.id,
                    MESSAGE_STATUS_SENDING,
                )

        except Exception as exc:
            self._finish_attempt_error(
                attempt,
                error_code=(
                    STATE_TRANSITION_ERROR_CODE
                ),
                error=exc,
                metadata={
                    **attempt_metadata,
                    "uncertain": False,
                    "automatic_retry":
                        False,
                },
            )

            raise

        try:
            snapshot = (
                self.connector
                .send_document_attachment(
                    path,
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
                        **attempt_metadata,
                        "uncertain": True,
                        "automatic_retry":
                            False,
                    },
                )
            )

            # Puede haber llegado realmente a WhatsApp.
            # Permanece SENDING y jamás se reintenta aquí.
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
                            **attempt_metadata,
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
                        **attempt_metadata,
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
                        **attempt_metadata,
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

            # El Connector ya confirmó físicamente el envío.
            # No convertirlo en ERROR ni provocar otro envío.
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

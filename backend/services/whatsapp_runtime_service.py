"""
Runtime persistente de WhatsApp para la aplicación.

Responsabilidades:
- mantener una única instancia de WhatsAppConnector;
- iniciar la sesión de forma perezosa;
- comprobar que WhatsApp Web está READY;
- exponer casos de uso de envío y sincronización;
- mantener vivos los servicios durante la sesión del ERP.

No contiene SQL.
No conoce Flet.
"""

import time

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_NEEDS_LOGIN,
    SESSION_STATUS_READY,
    WhatsAppConnector,
)
from backend.services.communication_service import (
    CommunicationService,
)
from backend.services.whatsapp_outbound_service import (
    WhatsAppOutboundService,
)
from backend.services.whatsapp_sync_service import (
    WhatsAppSyncService,
)


class WhatsAppRuntimeService:
    def __init__(
        self,
        *,
        profile_key="whatsapp_dev",
        headless=False,
        communication_service=None,
        connector_factory=None,
    ):
        self.profile_key = str(
            profile_key
            or "whatsapp_dev"
        ).strip()

        self.headless = bool(
            headless
        )

        self.communication_service = (
            communication_service
            or CommunicationService()
        )

        self.connector_factory = (
            connector_factory
            or WhatsAppConnector
        )

        self._connector = None
        self._outbound_service = None
        self._sync_service = None

    @property
    def connector(self):
        return self._connector

    @property
    def started(self):
        return bool(
            self._connector
            and self._connector.browser
        )

    def _build_connector(
        self,
    ):
        if self._connector is None:
            self._connector = (
                self.connector_factory(
                    profile_key=(
                        self.profile_key
                    ),
                    headless=(
                        self.headless
                    ),
                )
            )

        return self._connector

    def start(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if not connector.browser:
            connector.start()

        return connector

    def get_status(
        self,
    ):
        if not self.started:
            return "NOT_STARTED"

        return (
            self._connector
            .detect_session_status()
        )

    def ensure_ready(
        self,
        *,
        wait_timeout=60,
        poll_interval=1,
    ):
        connector = self.start()

        deadline = (
            time.time()
            + max(
                1,
                int(wait_timeout),
            )
        )

        last_status = None

        while time.time() < deadline:
            last_status = (
                connector
                .detect_session_status()
            )

            if (
                last_status
                == SESSION_STATUS_READY
            ):
                connector.dismiss_known_overlays()

                return connector

            if (
                last_status
                == SESSION_STATUS_NEEDS_LOGIN
            ):
                raise RuntimeError(
                    "WhatsApp Web requiere iniciar sesión"
                )

            time.sleep(
                max(
                    0.1,
                    float(
                        poll_interval
                    ),
                )
            )

        raise RuntimeError(
            "WhatsApp Web no alcanzó estado READY "
            f"(último estado: {last_status})"
        )

    def _get_outbound_service(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if self._outbound_service is None:
            self._outbound_service = (
                WhatsAppOutboundService(
                    connector=connector,
                    communication_service=(
                        self.communication_service
                    ),
                )
            )

        return self._outbound_service

    def _get_sync_service(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if self._sync_service is None:
            self._sync_service = (
                WhatsAppSyncService(
                    connector=connector,
                    communication_service=(
                        self.communication_service
                    ),
                )
            )

        return self._sync_service

    def verify_and_open_thread(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        connector = self.ensure_ready(
            wait_timeout=wait_timeout,
        )

        thread = (
            self.communication_service
            .get_thread(
                thread_id
            )
        )

        if thread is None:
            raise ValueError(
                "Conversación no encontrada"
            )

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            raise ValueError(
                "La conversación no tiene "
                "teléfono WhatsApp verificable"
            )

        routing = (
            connector
            .open_chat_by_phone(
                phone,
                timeout=routing_timeout,
            )
        )

        if not routing.get(
            "verified"
        ):
            reason = (
                routing.get(
                    "reason"
                )
                or
                "IDENTITY_UNVERIFIABLE"
            )

            raise RuntimeError(
                "No se pudo verificar el "
                "destinatario WhatsApp "
                f"({reason})"
            )

        return {
            "thread": thread,
            "routing": routing,
        }

    def send_text_message(
        self,
        *,
        wait_timeout=60,
        routing_timeout=15,
        **kwargs,
    ):
        thread_id = kwargs.get(
            "thread_id"
        )

        if thread_id in (
            None,
            "",
        ):
            raise ValueError(
                "thread_id es obligatorio"
            )

        self.verify_and_open_thread(
            thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=(
                routing_timeout
            ),
        )

        return (
            self._get_outbound_service()
            .send_text_message(
                **kwargs
            )
        )

    def sync_open_chat_messages(
        self,
        *,
        thread_id,
        limit=200,
        wait_timeout=60,
    ):
        self.ensure_ready(
            wait_timeout=wait_timeout,
        )

        return (
            self._get_sync_service()
            .sync_open_chat_messages(
                thread_id=thread_id,
                limit=limit,
            )
        )

    def close(
        self,
    ):
        connector = self._connector

        if connector is None:
            return False

        try:
            return bool(
                connector.close()
            )

        finally:
            self._connector = None
            self._outbound_service = None
            self._sync_service = None

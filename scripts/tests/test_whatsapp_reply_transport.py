from types import SimpleNamespace

import pytest

from backend.automation.connectors.whatsapp_connector import (
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_STATUS_SENT,
    MESSAGE_TYPE_TEXT,
    WhatsAppConnector,
    WhatsAppMessageSnapshot,
)
from backend.services.whatsapp_outbound_service import (
    WhatsAppOutboundService,
)


def _snapshot(
    provider_message_id="NEW-1",
):
    return WhatsAppMessageSnapshot(
        provider_message_id=(
            provider_message_id
        ),
        direction=(
            MESSAGE_DIRECTION_OUTBOUND
        ),
        body_text="Respuesta CRM",
        provider_timestamp=(
            "2026-08-19T09:10:00"
        ),
        message_type=(
            MESSAGE_TYPE_TEXT
        ),
        provider_status=(
            MESSAGE_STATUS_SENT
        ),
        sender=None,
        metadata={
            "reply": {
                "provider_message_id":
                    None,
                "sender":
                    None,
                "body_text":
                    "Mensaje original",
            }
        },
    )


def test_connector_reply_activates_exact_target_then_reuses_text_send():
    connector = WhatsAppConnector()

    connector.browser = object()

    calls = []

    connector._activate_reply_mode = (
        lambda provider_message_id, timeout=2:
            calls.append(
                (
                    "activate",
                    provider_message_id,
                    timeout,
                )
            )
    )

    expected = _snapshot()

    def fake_send(
        text,
        *,
        timeout=10,
    ):
        calls.append(
            (
                "send",
                text,
                timeout,
            )
        )

        return expected

    connector.send_text_message = (
        fake_send
    )

    result = (
        connector.send_reply_message(
            "Respuesta CRM",
            reply_to_provider_message_id=(
                "OLD-1"
            ),
            timeout=7,
        )
    )

    assert result is expected

    assert calls == [
        (
            "activate",
            "OLD-1",
            3,
        ),
        (
            "send",
            "Respuesta CRM",
            7,
        ),
    ]


def test_connector_reply_requires_provider_identity():
    connector = WhatsAppConnector()

    connector.browser = object()

    with pytest.raises(
        ValueError,
        match=(
            "reply_to_provider_message_id"
        ),
    ):
        connector.send_reply_message(
            "Respuesta",
            reply_to_provider_message_id="",
        )


class FakeConnector:
    def __init__(
        self,
    ):
        self.normal_calls = []
        self.reply_calls = []

    def send_text_message(
        self,
        text,
        *,
        timeout=10,
    ):
        self.normal_calls.append(
            (
                text,
                timeout,
            )
        )

        return _snapshot()

    def send_reply_message(
        self,
        text,
        *,
        reply_to_provider_message_id,
        timeout=10,
    ):
        self.reply_calls.append(
            (
                text,
                reply_to_provider_message_id,
                timeout,
            )
        )

        return _snapshot()


class FakeCommunicationService:
    def __init__(
        self,
        *,
        target_thread_id=50,
        target_provider_id="OLD-1",
    ):
        self.target = SimpleNamespace(
            id=10,
            thread_id=(
                target_thread_id
            ),
            client_id=5,
            expedient_id=None,
            direction="INBOUND",
            body_text=(
                "Mensaje original"
            ),
            status="RECEIVED",
            provider_message_id=(
                target_provider_id
            ),
            provider_timestamp=(
                "2026-08-19T09:00:00"
            ),
            created_by=None,
            sent_by=None,
            metadata={
                "sender":
                    "Cliente prueba",
            },
        )

        self.created = None
        self.created_metadata = None

    def get_message(
        self,
        message_id,
    ):
        if int(message_id) == 10:
            return self.target

        if (
            self.created is not None
            and int(message_id)
            == int(
                self.created.id
            )
        ):
            return self.created

        return None

    def create_outbound_message(
        self,
        *,
        thread_id,
        body_text,
        expedient_id=None,
        created_by=None,
        metadata=None,
    ):
        self.created_metadata = (
            dict(
                metadata
                or {}
            )
        )

        self.created = SimpleNamespace(
            id=99,
            thread_id=int(
                thread_id
            ),
            body_text=body_text,
            status="PENDING",
        )

        return self.created

    def start_message_attempt(
        self,
        *,
        message_id,
        transport,
        metadata=None,
    ):
        return SimpleNamespace(
            id=7,
        )

    def update_message_status(
        self,
        message_id,
        status,
        *,
        sent_by=None,
    ):
        return SimpleNamespace(
            id=int(
                message_id
            ),
            thread_id=50,
            body_text=(
                self.created.body_text
            ),
            status=status,
        )

    def attach_message_provider_identity(
        self,
        message_id,
        *,
        provider_message_id,
        provider_timestamp=None,
    ):
        return None

    def finish_message_attempt(
        self,
        attempt_id,
        *,
        status,
        error_code=None,
        error_message=None,
        metadata=None,
    ):
        return SimpleNamespace(
            id=int(
                attempt_id
            ),
            status=status,
        )


def test_outbound_reply_builds_canonical_metadata_and_uses_reply_transport():
    connector = FakeConnector()

    communication = (
        FakeCommunicationService()
    )

    service = WhatsAppOutboundService(
        connector=connector,
        communication_service=(
            communication
        ),
    )

    result = service.send_text_message(
        thread_id=50,
        body_text="Respuesta CRM",
        reply_to_message_id=10,
        created_by="ERP",
        sent_by="ERP",
        metadata={
            "source":
                "communications_view",
            # Intento deliberado de metadata
            # falsa: debe ser sustituida.
            "reply": {
                "provider_message_id":
                    "SPOOF",
            },
        },
    )

    assert result["ok"] is True

    assert connector.normal_calls == []

    assert connector.reply_calls == [
        (
            "Respuesta CRM",
            "OLD-1",
            10,
        )
    ]

    assert communication.created_metadata[
        "source"
    ] == "communications_view"

    assert communication.created_metadata[
        "reply"
    ] == {
        "provider_message_id":
            "OLD-1",
        "sender":
            "Cliente prueba",
        "body_text":
            "Mensaje original",
    }


def test_outbound_reply_rejects_cross_thread_target_before_transport():
    connector = FakeConnector()

    communication = (
        FakeCommunicationService(
            target_thread_id=999,
        )
    )

    service = WhatsAppOutboundService(
        connector=connector,
        communication_service=(
            communication
        ),
    )

    with pytest.raises(
        ValueError,
        match="otra conversación",
    ):
        service.send_text_message(
            thread_id=50,
            body_text="Respuesta CRM",
            reply_to_message_id=10,
        )

    assert connector.reply_calls == []
    assert connector.normal_calls == []


def test_outbound_reply_requires_provider_identity():
    connector = FakeConnector()

    communication = (
        FakeCommunicationService(
            target_provider_id=None,
        )
    )

    service = WhatsAppOutboundService(
        connector=connector,
        communication_service=(
            communication
        ),
    )

    with pytest.raises(
        ValueError,
        match="provider_message_id",
    ):
        service.send_text_message(
            thread_id=50,
            body_text="Respuesta CRM",
            reply_to_message_id=10,
        )

    assert connector.reply_calls == []
    assert connector.normal_calls == []


def test_normal_text_send_remains_unchanged():
    connector = FakeConnector()

    communication = (
        FakeCommunicationService()
    )

    service = WhatsAppOutboundService(
        connector=connector,
        communication_service=(
            communication
        ),
    )

    result = service.send_text_message(
        thread_id=50,
        body_text="Respuesta CRM",
    )

    assert result["ok"] is True

    assert connector.normal_calls == [
        (
            "Respuesta CRM",
            10,
        )
    ]

    assert connector.reply_calls == []

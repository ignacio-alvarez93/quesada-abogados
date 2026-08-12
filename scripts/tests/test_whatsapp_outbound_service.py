import unittest
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppSendStateUncertainError,
)
from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    ATTEMPT_STATUS_STARTED,
    MESSAGE_STATUS_ERROR,
    MESSAGE_STATUS_PENDING,
    MESSAGE_STATUS_SENDING,
    MESSAGE_STATUS_SENT,
)
from backend.services.whatsapp_outbound_service import (
    POST_SEND_PERSISTENCE_ERROR_CODE,
    SEND_ERROR_CODE,
    SEND_STATE_UNCERTAIN_ERROR_CODE,
    WhatsAppOutboundService,
)


class FakeConnector:
    def __init__(
        self,
        *,
        snapshot=None,
        error=None,
    ):
        self.snapshot = (
            snapshot
            or SimpleNamespace(
                provider_message_id=(
                    "WA-OUT-1"
                ),
                provider_timestamp=(
                    "2026-08-12T12:17:00"
                ),
                provider_status=(
                    "UNKNOWN"
                ),
                body_text="Hola",
            )
        )

        self.error = error
        self.calls = []

    def send_text_message(
        self,
        text,
        *,
        timeout=10,
    ):
        self.calls.append(
            {
                "text": text,
                "timeout": timeout,
            }
        )

        if self.error:
            raise self.error

        return self.snapshot


class FakeCommunicationService:
    def __init__(
        self,
        *,
        fail_attach=False,
    ):
        self.fail_attach = bool(
            fail_attach
        )

        self.message = None
        self.attempt = None

        self.calls = []

    def create_outbound_message(
        self,
        **kwargs,
    ):
        self.calls.append(
            (
                "create_message",
                dict(kwargs),
            )
        )

        self.message = SimpleNamespace(
            id=10,
            thread_id=int(
                kwargs["thread_id"]
            ),
            body_text=str(
                kwargs["body_text"]
            ).strip(),
            status=(
                MESSAGE_STATUS_PENDING
            ),
            provider_message_id=None,
            provider_timestamp=None,
            sent_by=None,
        )

        return self.message

    def start_message_attempt(
        self,
        **kwargs,
    ):
        self.calls.append(
            (
                "start_attempt",
                dict(kwargs),
            )
        )

        self.attempt = SimpleNamespace(
            id=20,
            message_id=10,
            attempt_number=1,
            status=(
                ATTEMPT_STATUS_STARTED
            ),
            error_code=None,
            metadata=None,
        )

        return self.attempt

    def update_message_status(
        self,
        message_id,
        status,
        *,
        sent_by=None,
    ):
        self.calls.append(
            (
                "update_status",
                {
                    "message_id":
                        message_id,
                    "status":
                        status,
                    "sent_by":
                        sent_by,
                },
            )
        )

        self.message.status = status

        if sent_by:
            self.message.sent_by = sent_by

        return self.message

    def attach_message_provider_identity(
        self,
        message_id,
        *,
        provider_message_id,
        provider_timestamp=None,
    ):
        self.calls.append(
            (
                "attach_provider",
                {
                    "message_id":
                        message_id,
                    "provider_message_id":
                        provider_message_id,
                    "provider_timestamp":
                        provider_timestamp,
                },
            )
        )

        if self.fail_attach:
            raise RuntimeError(
                "DB attach failed"
            )

        self.message.provider_message_id = (
            provider_message_id
        )

        self.message.provider_timestamp = (
            provider_timestamp
        )

        return self.message

    def finish_message_attempt(
        self,
        attempt_id,
        *,
        status,
        error_code=None,
        error_message=None,
        metadata=None,
    ):
        self.calls.append(
            (
                "finish_attempt",
                {
                    "attempt_id":
                        attempt_id,
                    "status":
                        status,
                    "error_code":
                        error_code,
                    "error_message":
                        error_message,
                    "metadata":
                        metadata,
                },
            )
        )

        self.attempt.status = status
        self.attempt.error_code = (
            error_code
        )
        self.attempt.metadata = metadata

        return self.attempt

    def get_message(
        self,
        message_id,
    ):
        self.calls.append(
            (
                "get_message",
                {
                    "message_id":
                        message_id,
                },
            )
        )

        return self.message


class WhatsAppOutboundServiceTest(
    unittest.TestCase
):
    def test_successful_send_persists_same_message(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        connector = FakeConnector()

        service = WhatsAppOutboundService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = service.send_text_message(
            thread_id=50,
            body_text="Hola",
            expedient_id=100,
            created_by="TEST",
            sent_by="TEST",
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertFalse(
            result["uncertain"]
        )

        self.assertEqual(
            result["message"].id,
            10,
        )

        self.assertEqual(
            result["message"].status,
            MESSAGE_STATUS_SENT,
        )

        self.assertEqual(
            result[
                "message"
            ].provider_message_id,
            "WA-OUT-1",
        )

        self.assertEqual(
            result["attempt"].status,
            ATTEMPT_STATUS_SENT,
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

    def test_definite_transport_failure_marks_message_error(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        connector = FakeConnector(
            error=RuntimeError(
                "Botón Enviar no localizado"
            )
        )

        service = WhatsAppOutboundService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = service.send_text_message(
            thread_id=50,
            body_text="Hola",
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertFalse(
            result["uncertain"]
        )

        self.assertEqual(
            result["message"].status,
            MESSAGE_STATUS_ERROR,
        )

        self.assertEqual(
            result["attempt"].status,
            ATTEMPT_STATUS_ERROR,
        )

        self.assertEqual(
            result["attempt"].error_code,
            SEND_ERROR_CODE,
        )

    def test_uncertain_transport_failure_keeps_sending(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        connector = FakeConnector(
            error=(
                WhatsAppSendStateUncertainError(
                    "No se pudo confirmar"
                )
            )
        )

        service = WhatsAppOutboundService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = service.send_text_message(
            thread_id=50,
            body_text="Hola",
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertTrue(
            result["uncertain"]
        )

        self.assertEqual(
            result["message"].status,
            MESSAGE_STATUS_SENDING,
        )

        self.assertEqual(
            result["attempt"].status,
            ATTEMPT_STATUS_ERROR,
        )

        self.assertEqual(
            result["attempt"].error_code,
            SEND_STATE_UNCERTAIN_ERROR_CODE,
        )

    def test_post_send_persistence_failure_never_retries(
        self,
    ):
        communication = (
            FakeCommunicationService(
                fail_attach=True
            )
        )

        connector = FakeConnector()

        service = WhatsAppOutboundService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = service.send_text_message(
            thread_id=50,
            body_text="Hola",
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertTrue(
            result["uncertain"]
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

        self.assertEqual(
            result["message"].status,
            MESSAGE_STATUS_SENDING,
        )

        self.assertEqual(
            result["attempt"].error_code,
            POST_SEND_PERSISTENCE_ERROR_CODE,
        )

        self.assertEqual(
            result[
                "provider_snapshot"
            ].provider_message_id,
            "WA-OUT-1",
        )

    def test_order_is_pending_attempt_sending_send_attach_sent(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        connector = FakeConnector()

        service = WhatsAppOutboundService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = service.send_text_message(
            thread_id=50,
            body_text="Hola",
        )

        self.assertTrue(
            result["ok"]
        )

        call_names = [
            item[0]
            for item in communication.calls
        ]

        self.assertEqual(
            call_names,
            [
                "create_message",
                "start_attempt",
                "update_status",
                "attach_provider",
                "update_status",
                "finish_attempt",
            ],
        )


if __name__ == "__main__":
    unittest.main()

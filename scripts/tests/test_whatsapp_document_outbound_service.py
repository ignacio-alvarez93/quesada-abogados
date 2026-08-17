from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
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
    MESSAGE_TYPE_DOCUMENT,
)
from backend.services.communication_service import (
    CommunicationService,
)
from backend.services.whatsapp_outbound_service import (
    POST_SEND_PERSISTENCE_ERROR_CODE,
    SEND_ERROR_CODE,
    SEND_STATE_UNCERTAIN_ERROR_CODE,
    WHATSAPP_TRANSPORT,
    WhatsAppOutboundService,
)


class _DomainRepository:
    def __init__(
        self,
    ):
        self.created = []

    def get_thread(
        self,
        thread_id,
    ):
        if int(thread_id) != 7:
            return None

        return SimpleNamespace(
            id=7,
            client_id=3,
        )

    def create_message(
        self,
        message,
    ):
        created = SimpleNamespace(
            **{
                **message.__dict__,
                "id": 10,
            }
        )

        self.created.append(
            created
        )

        return created


class CommunicationDocumentDomainTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.repository = (
            _DomainRepository()
        )

        self.service = (
            CommunicationService(
                repository=(
                    self.repository
                )
            )
        )

    def test_plain_empty_outbound_still_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "no puede estar vacío",
        ):
            self.service.create_outbound_message(
                thread_id=7,
                body_text="",
            )

    def test_document_allows_empty_body_with_filename(
        self,
    ):
        message = (
            self.service
            .create_outbound_message(
                thread_id=7,
                body_text="",
                metadata={
                    "message_type":
                        MESSAGE_TYPE_DOCUMENT,
                    "filename":
                        "documento.pdf",
                    "file_size_bytes":
                        123,
                },
            )
        )

        self.assertEqual(
            message.body_text,
            "",
        )

        self.assertEqual(
            message.status,
            MESSAGE_STATUS_PENDING,
        )

        self.assertEqual(
            message.metadata[
                "message_type"
            ],
            MESSAGE_TYPE_DOCUMENT,
        )

        self.assertEqual(
            message.metadata[
                "filename"
            ],
            "documento.pdf",
        )

    def test_document_requires_filename(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "requiere filename",
        ):
            self.service.create_outbound_message(
                thread_id=7,
                body_text="",
                metadata={
                    "message_type":
                        MESSAGE_TYPE_DOCUMENT,
                },
            )


class _FakeConnector:
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
                    "WA-DOC-1"
                ),
                provider_timestamp=(
                    "2026-08-17T14:30:00"
                ),
            )
        )

        self.error = error
        self.calls = []

    def send_document_attachment(
        self,
        file_path,
        *,
        timeout=12,
    ):
        self.calls.append(
            {
                "file_path":
                    str(
                        file_path
                    ),
                "timeout":
                    timeout,
            }
        )

        if self.error is not None:
            raise self.error

        return self.snapshot


class _FakeCommunicationService:
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
                dict(
                    kwargs
                ),
            )
        )

        self.message = SimpleNamespace(
            id=10,
            thread_id=int(
                kwargs[
                    "thread_id"
                ]
            ),
            body_text=str(
                kwargs.get(
                    "body_text"
                )
                or ""
            ),
            metadata=dict(
                kwargs.get(
                    "metadata"
                )
                or {}
            ),
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
                dict(
                    kwargs
                ),
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
            metadata=dict(
                kwargs.get(
                    "metadata"
                )
                or {}
            ),
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

        self.message.status = (
            status
        )

        if sent_by:
            self.message.sent_by = (
                sent_by
            )

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
                        dict(
                            metadata
                            or {}
                        ),
                },
            )
        )

        self.attempt.status = (
            status
        )

        self.attempt.error_code = (
            error_code
        )

        self.attempt.metadata = dict(
            metadata
            or {}
        )

        return self.attempt

    def get_message(
        self,
        message_id,
    ):
        return self.message


class WhatsAppDocumentOutboundServiceTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.tmp = (
            tempfile.TemporaryDirectory()
        )

        self.file_path = (
            Path(
                self.tmp.name
            )
            / "documento-prueba.pdf"
        )

        self.file_path.write_bytes(
            b"DOCUMENTO QA"
        )

    def tearDown(
        self,
    ):
        self.tmp.cleanup()

    def _service(
        self,
        *,
        connector=None,
        communication=None,
    ):
        connector = (
            connector
            or _FakeConnector()
        )

        communication = (
            communication
            or _FakeCommunicationService()
        )

        service = (
            WhatsAppOutboundService(
                connector=connector,
                communication_service=(
                    communication
                ),
            )
        )

        return (
            service,
            connector,
            communication,
        )

    def test_success_persists_document_and_provider_identity(
        self,
    ):
        (
            service,
            connector,
            communication,
        ) = self._service()

        result = (
            service.send_document_message(
                thread_id=7,
                file_path=(
                    self.file_path
                ),
                expedient_id=99,
                created_by="NACHO",
                sent_by="NACHO",
                metadata={
                    "source":
                        "test",
                },
                timeout=3,
            )
        )

        self.assertTrue(
            result[
                "ok"
            ]
        )

        self.assertFalse(
            result[
                "uncertain"
            ]
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

        self.assertEqual(
            result[
                "message"
            ].status,
            MESSAGE_STATUS_SENT,
        )

        self.assertEqual(
            result[
                "message"
            ].provider_message_id,
            "WA-DOC-1",
        )

        create_call = next(
            payload
            for name, payload
            in communication.calls
            if name
            == "create_message"
        )

        self.assertEqual(
            create_call[
                "body_text"
            ],
            "",
        )

        metadata = (
            create_call[
                "metadata"
            ]
        )

        self.assertEqual(
            metadata[
                "message_type"
            ],
            MESSAGE_TYPE_DOCUMENT,
        )

        self.assertEqual(
            metadata[
                "filename"
            ],
            self.file_path.name,
        )

        self.assertEqual(
            metadata[
                "file_size_bytes"
            ],
            self.file_path.stat().st_size,
        )

        self.assertNotIn(
            "file_path",
            metadata,
        )

        self.assertNotIn(
            str(
                self.file_path
            ),
            repr(
                metadata
            ),
        )

        self.assertEqual(
            result[
                "attempt"
            ].status,
            ATTEMPT_STATUS_SENT,
        )

        self.assertEqual(
            result[
                "attempt"
            ].metadata[
                "provider_message_id"
            ],
            "WA-DOC-1",
        )

    def test_uncertain_transport_remains_sending_and_never_retries(
        self,
    ):
        connector = (
            _FakeConnector(
                error=(
                    WhatsAppSendStateUncertainError(
                        "estado incierto"
                    )
                )
            )
        )

        communication = (
            _FakeCommunicationService()
        )

        service, _, _ = (
            self._service(
                connector=connector,
                communication=communication,
            )
        )

        result = (
            service.send_document_message(
                thread_id=7,
                file_path=self.file_path,
                timeout=0.1,
            )
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertTrue(
            result[
                "uncertain"
            ]
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

        self.assertEqual(
            result[
                "message"
            ].status,
            MESSAGE_STATUS_SENDING,
        )

        self.assertEqual(
            result[
                "attempt"
            ].status,
            ATTEMPT_STATUS_ERROR,
        )

        self.assertEqual(
            result[
                "attempt"
            ].error_code,
            SEND_STATE_UNCERTAIN_ERROR_CODE,
        )

        self.assertFalse(
            result[
                "attempt"
            ].metadata[
                "automatic_retry"
            ]
        )

    def test_ordinary_transport_error_marks_message_error(
        self,
    ):
        connector = (
            _FakeConnector(
                error=RuntimeError(
                    "fallo seguro"
                )
            )
        )

        service, connector, _ = (
            self._service(
                connector=connector,
            )
        )

        result = (
            service.send_document_message(
                thread_id=7,
                file_path=self.file_path,
                timeout=0.1,
            )
        )

        self.assertFalse(
            result[
                "ok"
            ]
        )

        self.assertFalse(
            result[
                "uncertain"
            ]
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

        self.assertEqual(
            result[
                "message"
            ].status,
            MESSAGE_STATUS_ERROR,
        )

        self.assertEqual(
            result[
                "attempt"
            ].error_code,
            SEND_ERROR_CODE,
        )

    def test_post_send_persistence_failure_is_uncertain_without_retry(
        self,
    ):
        connector = (
            _FakeConnector()
        )

        communication = (
            _FakeCommunicationService(
                fail_attach=True,
            )
        )

        service, _, _ = (
            self._service(
                connector=connector,
                communication=communication,
            )
        )

        result = (
            service.send_document_message(
                thread_id=7,
                file_path=self.file_path,
            )
        )

        self.assertFalse(
            result[
                "ok"
            ]
        )

        self.assertTrue(
            result[
                "uncertain"
            ]
        )

        self.assertEqual(
            len(
                connector.calls
            ),
            1,
        )

        self.assertEqual(
            result[
                "message"
            ].status,
            MESSAGE_STATUS_SENDING,
        )

        self.assertEqual(
            result[
                "attempt"
            ].error_code,
            POST_SEND_PERSISTENCE_ERROR_CODE,
        )

        self.assertIsNotNone(
            result[
                "provider_snapshot"
            ]
        )

    def test_missing_file_fails_before_persistence_or_transport(
        self,
    ):
        (
            service,
            connector,
            communication,
        ) = self._service()

        missing = (
            Path(
                self.tmp.name
            )
            / "missing.pdf"
        )

        with self.assertRaises(
            FileNotFoundError
        ):
            service.send_document_message(
                thread_id=7,
                file_path=missing,
            )

        self.assertEqual(
            connector.calls,
            [],
        )

        self.assertEqual(
            communication.calls,
            [],
        )

    def test_attempt_transport_is_governed_whatsapp_transport(
        self,
    ):
        (
            service,
            _connector,
            communication,
        ) = self._service()

        service.send_document_message(
            thread_id=7,
            file_path=self.file_path,
        )

        start = next(
            payload
            for name, payload
            in communication.calls
            if name
            == "start_attempt"
        )

        self.assertEqual(
            start[
                "transport"
            ],
            WHATSAPP_TRANSPORT,
        )

        self.assertEqual(
            start[
                "metadata"
            ][
                "message_type"
            ],
            MESSAGE_TYPE_DOCUMENT,
        )


if __name__ == "__main__":
    unittest.main()

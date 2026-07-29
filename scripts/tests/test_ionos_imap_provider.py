import unittest
from unittest.mock import patch

from backend.services.email_platform.providers.ionos_imap_provider import (
    IonosImapProvider,
)


RAW_MESSAGE = (
    b"From: Notificaciones "
    b"<notificaciones.extranjeria@correo.gob.es>\r\n"
    b"To: despacho@example.com\r\n"
    b"Subject: Expediente\r\n"
    b"Message-ID: <ionos-test-1@example.com>\r\n"
    b"Date: Mon, 27 Jul 2026 10:00:00 +0200\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"ID I33202604680666. "
    b"Numero de Expediente 330020260007765.\r\n"
)


class FakeImap:
    instances = []

    def __init__(
        self,
        host,
        port,
        ssl_context=None,
    ):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.calls = []
        self.logged_out = False
        self.__class__.instances.append(self)

    def login(self, username, password):
        self.calls.append(
            ("login", username, password)
        )
        return "OK", [b""]

    def select(self, folder, readonly=False):
        self.calls.append(
            ("select", folder, readonly)
        )
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append(
            ("uid", command, args)
        )

        if command == "SEARCH":
            return "OK", [b"41 42"]

        if command == "FETCH":
            return "OK", [
                (
                    b"42 (BODY[] {1})",
                    RAW_MESSAGE,
                ),
                b")",
            ]

        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


class IonosImapProviderTest(
    unittest.TestCase
):
    def setUp(self):
        FakeImap.instances.clear()

        self.account = {
            "id": 7,
            "email_address":
                "despacho@example.com",
            "credential_key":
                "QUESADA_IONOS",
            "config_json":
                (
                    '{"host":"imap.ionos.es",'
                    '"port":993,'
                    '"folder":"INBOX",'
                    '"sender_filters":['
                    '"notificaciones.extranjeria'
                    '@correo.gob.es",'
                    '"no-reply-notifica'
                    '@correo.gob.es"]}'
                ),
            "last_sync_cursor": "40",
        }

    @patch.dict(
        "os.environ",
        {
            "QUESADA_IONOS_USERNAME":
                "despacho@example.com",
            "QUESADA_IONOS_PASSWORD":
                "secret",
        },
        clear=False,
    )
    def test_incremental_read_uses_peek(
        self,
    ):
        provider = IonosImapProvider(
            self.account,
            imap_factory=FakeImap,
        )

        with patch(
            "backend.services.email_platform."
            "providers.ionos_imap_provider."
            "email_expedient_sync_service."
            "process_message",
            side_effect=[
                {
                    "status": "PROCESSED",
                    "email_message_id": 1,
                    "expediente_id": 10,
                },
                {
                    "status": "PROCESSED",
                    "email_message_id": 2,
                    "expediente_id": 11,
                },
            ],
        ) as process_message, patch(
            "backend.services.email_platform."
            "providers.ionos_imap_provider."
            "email_account_service."
            "update_sync_success",
        ) as update_success:
            result = provider.sync_incoming()

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["uids_found"],
            2,
        )

        instance = FakeImap.instances[0]

        uid_calls = [
            call
            for call in instance.calls
            if call[0] == "uid"
        ]

        self.assertIn(
            (
                "uid",
                "SEARCH",
                (
                    None,
                    "UID",
                    "41:*",
                    "FROM",
                    (
                        '"notificaciones.'
                        'extranjeria@correo.gob.es"'
                    ),
                ),
            ),
            uid_calls,
        )

        self.assertIn(
            (
                "uid",
                "SEARCH",
                (
                    None,
                    "UID",
                    "41:*",
                    "FROM",
                    (
                        '"no-reply-notifica'
                        '@correo.gob.es"'
                    ),
                ),
            ),
            uid_calls,
        )

        fetch_calls = [
            call
            for call in uid_calls
            if call[1] == "FETCH"
        ]

        self.assertEqual(
            len(fetch_calls),
            2,
        )

        for call in fetch_calls:
            self.assertEqual(
                call[2][1],
                "(BODY.PEEK[])",
            )

        self.assertEqual(
            update_success.call_count,
            2,
        )

        processed_messages = [
            call.args[0]
            for call in process_message.mock_calls
            if call.args
        ]

        self.assertEqual(
            len(processed_messages),
            2,
        )

        for message in processed_messages:
            self.assertEqual(
                message["account_id"],
                7,
            )
        self.assertTrue(
            instance.logged_out
        )


if __name__ == "__main__":
    unittest.main()

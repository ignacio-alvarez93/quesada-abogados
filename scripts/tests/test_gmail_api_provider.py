import base64
import unittest
from unittest.mock import patch

from backend.services.email_platform.providers.gmail_api_provider import (
    GmailApiProvider,
)


RAW_MESSAGE = b"""From: notificaciones.extranjeria@correo.gob.es
To: quesadaabogadosextranjeria@gmail.com
Subject: Expediente de extranjeria
Date: Mon, 20 Jul 2026 10:00:00 +0200
Message-ID: <gmail-test-1@correo.gob.es>
Content-Type: text/plain; charset=utf-8

Identificador Mercurio: 123456789012345
Numero de expediente: 330020260001234
"""


def encoded_raw():
    return (
        base64.urlsafe_b64encode(
            RAW_MESSAGE
        )
        .decode("ascii")
        .rstrip("=")
    )


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeMessages:
    def __init__(self):
        self.list_calls = []
        self.get_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)

        return FakeExecute(
            {
                "messages": [
                    {
                        "id": "gmail-1",
                        "threadId": "thread-1",
                    }
                ]
            }
        )

    def get(self, **kwargs):
        self.get_calls.append(kwargs)

        return FakeExecute(
            {
                "id": "gmail-1",
                "threadId": "thread-1",
                "internalDate": "1784534400000",
                "historyId": "9001",
                "labelIds": ["INBOX"],
                "raw": encoded_raw(),
            }
        )


class FakeUsers:
    def __init__(self):
        self.fake_messages = FakeMessages()

    def messages(self):
        return self.fake_messages

    def getProfile(self, **kwargs):
        return FakeExecute(
            {
                "emailAddress":
                    "quesadaabogadosextranjeria@gmail.com",
                "messagesTotal": 10,
                "historyId": "9001",
            }
        )


class FakeService:
    def __init__(self):
        self.fake_users = FakeUsers()

    def users(self):
        return self.fake_users


class GmailApiProviderTest(
    unittest.TestCase
):
    def account(self):
        return {
            "id": 2,
            "email_address":
                "quesadaabogadosextranjeria@gmail.com",
            "provider": "GMAIL_API",
            "credential_key": "QUESADA_GMAIL",
            "config_json": (
                '{"sender_filter": '
                '"notificaciones.extranjeria@correo.gob.es", '
                '"initial_lookback_days": 30, '
                '"max_results": 100}'
            ),
            "last_sync_cursor":
                "1784534300000",
        }

    def test_connection_checks_account(
        self,
    ):
        provider = GmailApiProvider(
            self.account(),
            service=FakeService(),
        )

        result = provider.test_connection()

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["account_email"],
            "quesadaabogadosextranjeria@gmail.com",
        )

    @patch(
        "backend.services.email_platform."
        "providers.gmail_api_provider."
        "email_account_service."
        "update_sync_success"
    )
    @patch(
        "backend.services.email_platform."
        "providers.gmail_api_provider."
        "email_expedient_sync_service."
        "process_message"
    )
    def test_sync_uses_raw_and_cursor(
        self,
        process_message,
        update_sync_success,
    ):
        process_message.return_value = {
            "status": "PROCESSED",
            "email_message_id": 10,
            "expediente_id": 20,
        }

        service = FakeService()

        provider = GmailApiProvider(
            self.account(),
            service=service,
        )

        result = provider.sync_incoming()

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["uids_found"],
            1,
        )
        self.assertEqual(
            result["processed"][0]["message_id"],
            "gmail-1",
        )

        list_call = (
            service.fake_users
            .fake_messages
            .list_calls[0]
        )

        self.assertIn(
            "from:notificaciones.extranjeria@correo.gob.es",
            list_call["q"],
        )

        get_call = (
            service.fake_users
            .fake_messages
            .get_calls[0]
        )

        self.assertEqual(
            get_call["format"],
            "raw",
        )

        normalized = (
            process_message.call_args.args[0]
        )

        self.assertEqual(
            normalized["provider"],
            "GMAIL_API",
        )
        self.assertEqual(
            normalized["provider_message_id"],
            "gmail-1",
        )
        self.assertEqual(
            normalized["provider_thread_id"],
            "thread-1",
        )
        self.assertEqual(
            normalized["account_id"],
            2,
        )

        update_sync_success.assert_called_with(
            2,
            cursor=1784534400000,
        )


if __name__ == "__main__":
    unittest.main()

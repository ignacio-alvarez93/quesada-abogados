import io
import json
import os
import unittest
from unittest.mock import patch

from backend.services import (
    telegram_service,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    def read(self):
        return json.dumps(
            self.payload
        ).encode(
            "utf-8"
        )


class TelegramServiceTestCase(
    unittest.TestCase
):

    def test_configuration_required(self):
        with patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            with self.assertRaises(
                telegram_service
                .TelegramConfigurationError
            ):
                (
                    telegram_service
                    .get_configuration()
                )

    def test_configuration(self):
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN":
                    "token-test",
                "TELEGRAM_CHAT_ID":
                    "123",
            },
            clear=True,
        ):
            config = (
                telegram_service
                .get_configuration()
            )

        self.assertEqual(
            config["token"],
            "token-test",
        )

        self.assertEqual(
            config["chat_id"],
            "123",
        )

    @patch(
        "urllib.request.urlopen"
    )
    def test_send_message(
        self,
        mock_urlopen,
    ):
        mock_urlopen.return_value = (
            FakeResponse(
                {
                    "ok": True,
                    "result": {
                        "message_id": 1
                    },
                }
            )
        )

        result = (
            telegram_service.send_message(
                "Mensaje de prueba",
                token="token-test",
                chat_id="123",
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            mock_urlopen.call_count,
            1,
        )

    @patch(
        "urllib.request.urlopen"
    )
    def test_api_rejection(
        self,
        mock_urlopen,
    ):
        mock_urlopen.return_value = (
            FakeResponse(
                {
                    "ok": False,
                    "description":
                        "Bad Request",
                }
            )
        )

        with self.assertRaises(
            telegram_service
            .TelegramDeliveryError
        ):
            telegram_service.send_message(
                "Mensaje",
                token="token-test",
                chat_id="123",
            )

    def test_empty_message(self):
        with self.assertRaises(
            ValueError
        ):
            telegram_service.send_message(
                "",
                token="token-test",
                chat_id="123",
            )


if __name__ == "__main__":
    unittest.main()

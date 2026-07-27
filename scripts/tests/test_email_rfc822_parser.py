import unittest

from backend.services.email_platform import (
    email_rfc822_parser,
)


RAW_MESSAGE = (
    b"From: Notificaciones Extranjeria "
    b"<notificaciones.extranjeria@correo.gob.es>\r\n"
    b"To: despacho@example.com\r\n"
    b"Subject: Numero de expediente asignado\r\n"
    b"Message-ID: <message-001@correo.gob.es>\r\n"
    b"Date: Mon, 27 Jul 2026 10:00:00 +0200\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"ID I33202604680666 para el interesado. "
    b"Numero de Expediente 330020260007765.\r\n"
)


class EmailRfc822ParserTest(
    unittest.TestCase
):
    def test_parses_common_message(self):
        result = (
            email_rfc822_parser
            .parse_rfc822_message(
                RAW_MESSAGE,
                provider="IONOS_IMAP",
                account_email=(
                    "despacho@example.com"
                ),
                provider_message_id="123",
            )
        )

        self.assertEqual(
            result["provider"],
            "IONOS_IMAP",
        )
        self.assertEqual(
            result["provider_message_id"],
            "123",
        )
        self.assertEqual(
            result["sender_email"],
            (
                "notificaciones.extranjeria"
                "@correo.gob.es"
            ),
        )
        self.assertEqual(
            result["internet_message_id"],
            "<message-001@correo.gob.es>",
        )
        self.assertIn(
            "I33202604680666",
            result["body_text"],
        )
        self.assertFalse(
            result["has_attachments"]
        )


if __name__ == "__main__":
    unittest.main()

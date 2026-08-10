import unittest

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppChatSnapshot,
    WhatsAppConnector,
    extract_phone_from_profile_text,
)


class FakeElement:
    def __init__(self):
        self.mouse_clicked = False

    def mouse_click(self):
        self.mouse_clicked = True


class FakeBrowser:
    def __init__(self):
        self.element = FakeElement()
        self.evaluate_results = []

    def queue(self, *values):
        self.evaluate_results.extend(
            values
        )

    def evaluate(self, _script):
        if not self.evaluate_results:
            raise AssertionError(
                "No hay resultado evaluate preparado"
            )

        return self.evaluate_results.pop(0)

    def find_element(
        self,
        _selector,
    ):
        return self.element


class WhatsAppChatExtractorTest(
    unittest.TestCase
):
    def test_extract_phone_from_contact_profile(
        self,
    ):
        phone = (
            extract_phone_from_profile_text(
                "Info. del contacto\n"
                "CLIENTE PRUEBA\n"
                "+34 600 123 456\n"
                "Voz\nVideo"
            )
        )

        self.assertEqual(
            phone,
            "+34 600 123 456",
        )

    def test_extract_phone_returns_none(
        self,
    ):
        self.assertIsNone(
            extract_phone_from_profile_text(
                "Info. del contacto\n"
                "CLIENTE SIN TELÉFONO"
            )
        )

    def test_snapshot_is_transport_model(
        self,
    ):
        snapshot = WhatsAppChatSnapshot(
            position=12,
            display_name="CLIENTE",
            primary_detail="19:30",
            preview="Hola",
            unread_count=2,
        )

        self.assertEqual(
            snapshot.position,
            12,
        )

        self.assertEqual(
            snapshot.unread_count,
            2,
        )

    def test_list_visible_chat_snapshots(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "position": 3,
                    "display_name":
                        "CLIENTE",
                    "primary_detail":
                        "19:30",
                    "preview":
                        "Documento enviado",
                    "unread_count":
                        2,
                },
                {
                    "position": 4,
                    "display_name":
                        "+34 600 999 888",
                    "primary_detail":
                        "Ayer",
                    "preview":
                        "Hola",
                    "unread_count":
                        0,
                },
            ]
        )

        connector.browser = browser

        result = (
            connector
            .list_visible_chat_snapshots()
        )

        self.assertEqual(
            len(result),
            2,
        )

        self.assertEqual(
            result[0].display_name,
            "CLIENTE",
        )

        self.assertEqual(
            result[1].position,
            4,
        )

    def test_open_chat_uses_mouse_click(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CLIENTE",
            }
        )

        connector.browser = browser

        result = (
            connector.open_chat(
                0,
                timeout=1,
            )
        )

        self.assertTrue(
            result["opened"]
        )

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_close_contact_profile(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            True,
            False,
        )

        connector.browser = browser

        result = (
            connector
            .close_contact_profile(
                timeout=1,
            )
        )

        self.assertTrue(result)

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_get_open_contact_phone(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            "Info. del contacto\n"
            "CLIENTE\n"
            "+34 611 222 333\n"
            "Voz"
        )

        connector.browser = browser

        self.assertEqual(
            connector
            .get_open_contact_phone(),
            "+34 611 222 333",
        )


if __name__ == "__main__":
    unittest.main()

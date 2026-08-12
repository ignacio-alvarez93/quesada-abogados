import unittest

from backend.automation.connectors.whatsapp_connector import (
    CHAT_KIND_GROUP,
    CHAT_KIND_INDIVIDUAL,
    CHAT_KIND_UNKNOWN,
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_READ,
    MESSAGE_STATUS_RECEIVED,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_TEXT,
    WhatsAppChatSnapshot,
    WhatsAppConnector,
    extract_phone_from_profile_text,
    normalize_chat_identity,
    parse_whatsapp_pre_plain_text,
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
    def test_normalize_chat_identity_removes_visual_symbols(
        self,
    ):
        self.assertEqual(
            normalize_chat_identity(
                "😍Mi Amor❤️♾️"
            ),
            "mi amor",
        )

    def test_normalize_chat_identity_preserves_textual_difference(
        self,
    ):
        self.assertNotEqual(
            normalize_chat_identity(
                "Tatiana"
            ),
            normalize_chat_identity(
                "Tatiana Perez"
            ),
        )

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
                    "virtual_offset":
                        228,
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

        self.assertEqual(
            result[0].virtual_offset,
            228,
        )

    def test_list_snapshots_can_filter_viewport(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "position": 0,
                    "virtual_offset": 0,
                    "in_viewport": True,
                    "display_name":
                        "VISIBLE",
                    "primary_detail": "",
                    "preview": "",
                    "unread_count": 0,
                },
                {
                    "position": 1,
                    "virtual_offset": 76,
                    "in_viewport": False,
                    "display_name":
                        "BUFFER",
                    "primary_detail": "",
                    "preview": "",
                    "unread_count": 0,
                },
            ]
        )

        connector.browser = browser

        result = (
            connector
            .list_visible_chat_snapshots(
                viewport_only=True,
            )
        )

        self.assertEqual(
            len(result),
            1,
        )

        self.assertEqual(
            result[0].display_name,
            "VISIBLE",
        )

    def test_scroll_chat_list_to_ratio(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "moved": True,
                "ratio": 0.5,
                "scroll_top": 100,
                "max_scroll": 200,
            }
        )

        connector.browser = browser

        result = (
            connector
            .scroll_chat_list_to_ratio(
                0.5
            )
        )

        self.assertTrue(
            result["moved"]
        )

        self.assertEqual(
            result["ratio"],
            0.5,
        )

    def test_open_chat_by_virtual_offset(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            True,
            4,
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CLIENTE",
                "active_display_name":
                    "CLIENTE",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_chat_by_virtual_offset(
                304,
                timeout=1,
            )
        )

        self.assertTrue(
            result["opened"]
        )

        self.assertEqual(
            result["position"],
            4,
        )

        self.assertEqual(
            result["virtual_offset"],
            304,
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

    def test_open_chat_rejects_empty_normalized_expected_identity(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        wrong_chat_state = {
            "opened": True,
            "composer_aria_label":
                "Escribir un mensaje",
            "active_display_name":
                "Tatiana",
        }

        browser.queue(
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
            wrong_chat_state,
        )

        connector.browser = browser

        result = (
            connector.open_chat(
                0,
                expected_display_name=(
                    "❤️"
                ),
                timeout=1,
            )
        )

        self.assertFalse(
            result["opened"]
        )

        self.assertEqual(
            result["reason"],
            "CHAT_IDENTITY_MISMATCH",
        )

    def test_open_chat_accepts_normalized_visual_identity(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para Mi Amor",
                "active_display_name":
                    "Mi Amor",
            },
        )

        connector.browser = browser

        result = (
            connector.open_chat(
                0,
                expected_display_name=(
                    "😍Mi Amor❤️♾️"
                ),
                timeout=1,
            )
        )

        self.assertTrue(
            result["opened"]
        )

        self.assertEqual(
            result[
                "active_display_name"
            ],
            "Mi Amor",
        )

    def test_open_chat_rejects_wrong_active_chat(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CHAT ANTERIOR",
                "active_display_name":
                    "CHAT ANTERIOR",
            },
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CHAT ANTERIOR",
                "active_display_name":
                    "CHAT ANTERIOR",
            },
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CHAT ANTERIOR",
                "active_display_name":
                    "CHAT ANTERIOR",
            },
            {
                "opened": True,
                "composer_aria_label":
                    "Escribir un mensaje "
                    "para CHAT ANTERIOR",
                "active_display_name":
                    "CHAT ANTERIOR",
            },
        )

        connector.browser = browser

        result = (
            connector.open_chat(
                7,
                expected_display_name=(
                    "CHAT ACTUAL"
                ),
                timeout=1,
            )
        )

        self.assertFalse(
            result["opened"]
        )

        self.assertEqual(
            result["reason"],
            "CHAT_IDENTITY_MISMATCH",
        )

        self.assertEqual(
            result[
                "active_display_name"
            ],
            "CHAT ANTERIOR",
        )

    def test_open_profile_reuses_expected_drawer(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject": "CLIENTE",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "CLIENTE"
                ),
            )
        )

        self.assertTrue(result)

        self.assertFalse(
            browser
            .element
            .mouse_clicked
        )

    def test_open_profile_does_not_reuse_drawer_for_empty_identity(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "Tatiana",
            },
            True,
            False,
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "❤️",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "❤️"
                ),
                timeout=1,
            )
        )

        self.assertTrue(
            result
        )

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_open_profile_reuses_normalized_visual_identity(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "Mi Amor",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "😍Mi Amor❤️♾️"
                ),
            )
        )

        self.assertTrue(
            result
        )

        self.assertFalse(
            browser
            .element
            .mouse_clicked
        )

    def test_open_profile_refreshes_stale_drawer(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "CHAT ANTERIOR",
            },
            True,
            False,
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "CLIENTE ACTUAL",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "CLIENTE ACTUAL"
                ),
                timeout=1,
            )
        )

        self.assertTrue(result)

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_open_profile_ignores_empty_drawer_container(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": True,
                "has_content": False,
                "recognized": False,
                "header": None,
                "subject": None,
            },
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "CLIENTE",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "CLIENTE"
                ),
                timeout=1,
            )
        )

        self.assertTrue(
            result
        )

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_open_profile_accepts_recognized_drawer_with_different_subject(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            {
                "found": False,
                "has_content": False,
                "recognized": False,
                "header": None,
                "subject": None,
            },
            {
                "found": True,
                "has_content": True,
                "recognized": True,
                "header":
                    "Info. del contacto",
                "subject":
                    "+34 600 123 456",
            },
        )

        connector.browser = browser

        result = (
            connector
            .open_contact_profile(
                expected_display_name=(
                    "CLIENTE GUARDADO"
                ),
                timeout=1,
            )
        )

        self.assertTrue(
            result
        )

        self.assertTrue(
            browser
            .element
            .mouse_clicked
        )

    def test_classify_contact_profile(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            "Info. del contacto\n"
            "CLIENTE\n"
            "+34 600 123 456"
        )

        connector.browser = browser

        result = (
            connector
            .classify_open_profile()
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_INDIVIDUAL,
        )

    def test_classify_group_profile(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            "Info. del grupo\n"
            "GRUPO PRUEBA\n"
            "Grupo · 8 miembros"
        )

        connector.browser = browser

        result = (
            connector
            .classify_open_profile()
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_GROUP,
        )

    def test_classify_unknown_profile(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            "Panel desconocido"
        )

        connector.browser = browser

        result = (
            connector
            .classify_open_profile()
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_UNKNOWN,
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

    def test_parse_message_pre_plain_text(
        self,
    ):
        result = (
            parse_whatsapp_pre_plain_text(
                "[9:23, 12/8/2026] CLIENTE:"
            )
        )

        self.assertEqual(
            result[
                "provider_timestamp"
            ],
            "2026-08-12T09:23:00",
        )

        self.assertEqual(
            result["sender"],
            "CLIENTE",
        )


    def test_visible_message_snapshots_normalize_text_and_status(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "provider_message_id":
                        "AC-IN-1",
                    "pre_plain_text":
                        "[9:22, 12/8/2026] CLIENTE:",
                    "body_text":
                        "Hola 🥰",
                    "meta_text":
                        "9:22",
                    "arias":
                        ["CLIENTE:"],
                    "testids":
                        [
                            "msg-container",
                            "selectable-text",
                            "msg-meta",
                        ],
                    "has_tail_in":
                        True,
                    "has_tail_out":
                        False,
                    "has_sticker":
                        False,
                    "image_info":
                        [],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
                {
                    "provider_message_id":
                        "AC-OUT-1",
                    "pre_plain_text":
                        "[9:23, 12/8/2026] OPERADOR:",
                    "body_text":
                        "Buenos días ❤️",
                    "meta_text":
                        "9:23",
                    "arias":
                        [
                            "Tú:",
                            " Leído ",
                        ],
                    "testids":
                        [
                            "msg-container",
                            "selectable-text",
                            "msg-meta",
                        ],
                    "has_tail_in":
                        False,
                    "has_tail_out":
                        False,
                    "has_sticker":
                        False,
                    "image_info":
                        [],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
            ]
        )

        connector.browser = browser

        messages = (
            connector
            .list_visible_message_snapshots()
        )

        self.assertEqual(
            len(messages),
            2,
        )

        self.assertEqual(
            messages[0].direction,
            MESSAGE_DIRECTION_INBOUND,
        )

        self.assertEqual(
            messages[0].provider_status,
            MESSAGE_STATUS_RECEIVED,
        )

        self.assertEqual(
            messages[0].message_type,
            MESSAGE_TYPE_TEXT,
        )

        self.assertEqual(
            messages[1].direction,
            MESSAGE_DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            messages[1].provider_status,
            MESSAGE_STATUS_READ,
        )

        self.assertEqual(
            messages[1].body_text,
            "Buenos días ❤️",
        )


    def test_sticker_infers_adjacent_date(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "provider_message_id":
                        "AC-TEXT-1",
                    "pre_plain_text":
                        "[9:24, 12/8/2026] CLIENTE:",
                    "body_text":
                        "Texto",
                    "meta_text":
                        "9:24",
                    "arias":
                        ["CLIENTE:"],
                    "testids":
                        [],
                    "has_tail_in":
                        True,
                    "has_tail_out":
                        False,
                    "has_sticker":
                        False,
                    "image_info":
                        [],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
                {
                    "provider_message_id":
                        "AC-STICKER-1",
                    "pre_plain_text":
                        None,
                    "body_text":
                        "",
                    "meta_text":
                        "9:25",
                    "arias":
                        [
                            "Tú:",
                            " Entregado ",
                        ],
                    "testids":
                        [
                            "sticker-container",
                        ],
                    "has_tail_in":
                        False,
                    "has_tail_out":
                        False,
                    "has_sticker":
                        True,
                    "image_info":
                        [
                            {
                                "alt":
                                    "Sticker sin etiquetas",
                                "src":
                                    "blob:test",
                            }
                        ],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
            ]
        )

        connector.browser = browser

        messages = (
            connector
            .list_visible_message_snapshots()
        )

        sticker = messages[1]

        self.assertEqual(
            sticker.message_type,
            MESSAGE_TYPE_STICKER,
        )

        self.assertEqual(
            sticker.direction,
            MESSAGE_DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            sticker.provider_status,
            MESSAGE_STATUS_DELIVERED,
        )

        self.assertEqual(
            sticker.provider_timestamp,
            "2026-08-12T09:25:00",
        )

        self.assertTrue(
            sticker.metadata[
                "timestamp_inferred"
            ]
        )

    def test_sticker_direction_falls_back_to_geometry(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "provider_message_id":
                        "AC-TEXT-GEO-1",
                    "pre_plain_text":
                        "[9:24, 12/8/2026] CLIENTE:",
                    "body_text":
                        "Texto",
                    "meta_text":
                        "9:24",
                    "arias":
                        ["CLIENTE:"],
                    "testids":
                        [],
                    "has_tail_in":
                        True,
                    "has_tail_out":
                        False,
                    "center_ratio":
                        0.22,
                    "has_sticker":
                        False,
                    "image_info":
                        [],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
                {
                    "provider_message_id":
                        "AC-STICKER-GEO-1",
                    "pre_plain_text":
                        None,
                    "body_text":
                        "",
                    "meta_text":
                        "9:25",
                    "arias":
                        ["Sticker sin etiquetas"],
                    "testids":
                        [
                            "sticker-container",
                        ],
                    "has_tail_in":
                        False,
                    "has_tail_out":
                        False,
                    "center_ratio":
                        0.2355,
                    "has_sticker":
                        True,
                    "image_info":
                        [
                            {
                                "alt":
                                    "Sticker sin etiquetas",
                                "src":
                                    "blob:test",
                            }
                        ],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
            ]
        )

        connector.browser = browser

        messages = (
            connector
            .list_visible_message_snapshots()
        )

        sticker = messages[1]

        self.assertEqual(
            sticker.direction,
            MESSAGE_DIRECTION_INBOUND,
        )

        self.assertEqual(
            sticker.provider_status,
            MESSAGE_STATUS_RECEIVED,
        )

        self.assertEqual(
            sticker.message_type,
            MESSAGE_TYPE_STICKER,
        )

        self.assertEqual(
            sticker.metadata[
                "direction_source"
            ],
            "GEOMETRY",
        )

        self.assertEqual(
            sticker.provider_timestamp,
            "2026-08-12T09:25:00",
        )


    def test_geometry_neutral_zone_remains_unknown(
        self,
    ):
        connector = WhatsAppConnector()
        browser = FakeBrowser()

        browser.queue(
            [
                {
                    "provider_message_id":
                        "AC-GEO-NEUTRAL-1",
                    "pre_plain_text":
                        None,
                    "body_text":
                        "",
                    "meta_text":
                        "",
                    "arias":
                        [],
                    "testids":
                        [],
                    "has_tail_in":
                        False,
                    "has_tail_out":
                        False,
                    "center_ratio":
                        0.50,
                    "has_sticker":
                        True,
                    "image_info":
                        [],
                    "video_count":
                        0,
                    "audio_count":
                        0,
                    "reaction_labels":
                        [],
                },
            ]
        )

        connector.browser = browser

        messages = (
            connector
            .list_visible_message_snapshots()
        )

        self.assertEqual(
            len(messages),
            1,
        )

        self.assertEqual(
            messages[0].direction,
            "UNKNOWN",
        )

        self.assertEqual(
            messages[0].provider_status,
            "UNKNOWN",
        )

        self.assertEqual(
            messages[0].metadata[
                "direction_source"
            ],
            "UNKNOWN",
        )


if __name__ == "__main__":
    unittest.main()

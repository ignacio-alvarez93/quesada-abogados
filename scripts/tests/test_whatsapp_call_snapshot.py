import unittest

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ABSENT,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
    WhatsAppCallSnapshot,
    WhatsAppConnector,
)


class FakeBrowser:
    def __init__(
        self,
        result,
    ):
        self.result = result
        self.evaluate_scripts = []

    def evaluate(
        self,
        script,
    ):
        self.evaluate_scripts.append(
            script
        )

        return self.result


class WhatsAppCallSnapshotTest(
    unittest.TestCase
):
    def connector_with(
        self,
        result,
    ):
        connector = WhatsAppConnector()

        browser = FakeBrowser(
            result
        )

        connector.browser = browser

        return (
            connector,
            browser,
        )


    def test_absent_call_surface_returns_absent_snapshot(
        self,
    ):
        connector, browser = (
            self.connector_with({
                "surface_present":
                    False,
            })
        )

        snapshot = (
            connector.read_call_snapshot()
        )

        self.assertIsInstance(
            snapshot,
            WhatsAppCallSnapshot,
        )

        self.assertFalse(
            snapshot.present
        )

        self.assertEqual(
            snapshot.phase,
            WHATSAPP_CALL_PHASE_ABSENT,
        )

        self.assertEqual(
            snapshot.direction,
            WHATSAPP_CALL_DIRECTION_UNKNOWN,
        )

        self.assertFalse(
            snapshot.identity_complete
        )

        self.assertEqual(
            len(
                browser.evaluate_scripts
            ),
            1,
        )


    def test_incoming_ringing_extracts_provider_identity(
        self,
    ):
        connector, _ = (
            self.connector_with({
                "surface_present":
                    True,

                "surface_text":
                    (
                        "Jorge "
                        "Silenciar micrófono "
                        "Rechazar Aceptar"
                    ),

                "participant_name":
                    "Jorge",

                "visible_state":
                    "Llamada",

                "controls":
                    [
                        "Silenciar micrófono",
                        "Rechazar",
                        "Aceptar",
                    ],

                "provider_call_id":
                    (
                        "002F96754F8532D5"
                        "EDAF18A55AFCCBB8"
                    ),

                "external_call_key":
                    (
                        "false_"
                        "29403463581864@lid_"
                        "002F96754F8532D5"
                        "EDAF18A55AFCCBB8"
                    ),

                "participant_lid":
                    "29403463581864@lid",

                "participant_phone_id":
                    "447425929197@c.us",

                "is_video":
                    False,
            })
        )

        snapshot = (
            connector.read_call_snapshot()
        )

        self.assertTrue(
            snapshot.present
        )

        self.assertEqual(
            snapshot.phase,
            (
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
        )

        self.assertEqual(
            snapshot.direction,
            WHATSAPP_CALL_DIRECTION_INBOUND,
        )

        self.assertEqual(
            snapshot.participant_lid,
            "29403463581864@lid",
        )

        self.assertEqual(
            snapshot.participant_phone_id,
            "447425929197@c.us",
        )

        self.assertEqual(
            snapshot.participant_phone,
            "+447425929197",
        )

        self.assertTrue(
            snapshot.can_accept
        )

        self.assertTrue(
            snapshot.can_reject
        )

        self.assertFalse(
            snapshot.can_hangup
        )

        self.assertTrue(
            snapshot.identity_complete
        )

        self.assertFalse(
            snapshot.is_video
        )


    def test_outbound_calling_uses_provider_direction(
        self,
    ):
        connector, _ = (
            self.connector_with({
                "surface_present":
                    True,

                "surface_text":
                    "Jorge Llamando…",

                "participant_name":
                    "Jorge",

                "visible_state":
                    "Llamando…",

                "controls":
                    [
                        "Finalizar llamada",
                    ],

                "provider_call_id":
                    (
                        "00AE2FC193A60C77"
                        "F50BF25C23BD4288"
                    ),

                "external_call_key":
                    (
                        "true_"
                        "29403463581864@lid_"
                        "00AE2FC193A60C77"
                        "F50BF25C23BD4288"
                    ),

                "participant_lid":
                    "29403463581864@lid",

                "participant_phone_id":
                    "447425929197@c.us",

                "is_video":
                    False,
            })
        )

        snapshot = (
            connector.read_call_snapshot()
        )

        self.assertEqual(
            snapshot.phase,
            (
                WHATSAPP_CALL_PHASE_OUTGOING_DIALING
            ),
        )

        self.assertEqual(
            snapshot.direction,
            WHATSAPP_CALL_DIRECTION_OUTBOUND,
        )

        self.assertTrue(
            snapshot.can_hangup
        )

        self.assertTrue(
            snapshot.identity_complete
        )


    def test_timer_marks_answered_call_surface_active(
        self,
    ):
        connector, _ = (
            self.connector_with({
                "surface_present":
                    True,

                "surface_text":
                    "Jorge 0:03",

                "participant_name":
                    "Jorge",

                "visible_state":
                    "0:03",

                "controls":
                    [
                        "Silenciar micrófono",
                        "Finalizar llamada",
                    ],

                "provider_call_id":
                    "CALL-1",

                "external_call_key":
                    (
                        "true_"
                        "29403463581864@lid_"
                        "CALL-1"
                    ),

                "participant_lid":
                    "29403463581864@lid",

                "participant_phone_id":
                    "447425929197@c.us",

                "is_video":
                    False,
            })
        )

        snapshot = (
            connector.read_call_snapshot()
        )

        self.assertEqual(
            snapshot.phase,
            WHATSAPP_CALL_PHASE_ACTIVE,
        )

        self.assertEqual(
            snapshot.visible_state,
            "0:03",
        )

        self.assertEqual(
            snapshot.direction,
            WHATSAPP_CALL_DIRECTION_OUTBOUND,
        )

        self.assertTrue(
            snapshot.can_hangup
        )


    def test_transient_surface_can_exist_before_identity(
        self,
    ):
        connector, _ = (
            self.connector_with({
                "surface_present":
                    True,

                "surface_text":
                    "",

                "participant_name":
                    "",

                "visible_state":
                    "",

                "controls":
                    [
                        "Finalizar llamada",
                    ],

                "provider_call_id":
                    None,

                "external_call_key":
                    None,

                "participant_lid":
                    None,

                "participant_phone_id":
                    None,

                "is_video":
                    None,
            })
        )

        snapshot = (
            connector.read_call_snapshot()
        )

        self.assertTrue(
            snapshot.present
        )

        self.assertEqual(
            snapshot.phase,
            WHATSAPP_CALL_PHASE_CONNECTING,
        )

        self.assertEqual(
            snapshot.direction,
            WHATSAPP_CALL_DIRECTION_UNKNOWN,
        )

        self.assertFalse(
            snapshot.identity_complete
        )

        self.assertIsNone(
            snapshot.provider_call_id
        )

        self.assertIsNone(
            snapshot.participant_phone
        )


    def test_productive_probe_is_single_pass_and_passive(
        self,
    ):
        connector, browser = (
            self.connector_with({
                "surface_present":
                    False,
            })
        )

        connector.read_call_snapshot()

        self.assertEqual(
            len(
                browser.evaluate_scripts
            ),
            1,
        )

        script = (
            browser.evaluate_scripts[
                0
            ]
        )

        self.assertNotIn(
            ".click(",
            script,
        )

        self.assertNotIn(
            "dispatchEvent(",
            script,
        )

        self.assertNotIn(
            "setAttribute(",
            script,
        )


if __name__ == "__main__":
    unittest.main()

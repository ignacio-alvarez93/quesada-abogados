from pathlib import Path
import unittest


ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "communications_view.py"
)


class CommunicationsReplyUIContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )

    def test_reply_target_is_ephemeral_state(
        self,
    ):
        self.assertIn(
            '"reply_target": None',
            self.source,
        )

    def test_message_bubble_exposes_reply_action(
        self,
    ):
        self.assertIn(
            'tooltip="Responder"',
            self.source,
        )

        self.assertIn(
            "_set_reply_target(",
            self.source,
        )

        self.assertIn(
            'icon=ft.Icons.REPLY',
            self.source,
        )

    def test_reply_requires_persisted_provider_identity(
        self,
    ):
        self.assertIn(
            "provider_message_id",
            self.source,
        )

        self.assertIn(
            '"message_id":',
            self.source,
        )

        self.assertIn(
            '"thread_id":',
            self.source,
        )

    def test_reply_target_is_cleared_on_thread_change(
        self,
    ):
        marker = (
            'state["pending_attachments"] = []'
        )

        start = self.source.index(
            marker
        )

        block = self.source[
            start:
            start + 1000
        ]

        self.assertIn(
            'state["reply_target"] = None',
            block,
        )

    def test_reply_preview_is_mounted_above_composer(
        self,
    ):
        self.assertIn(
            "def _build_reply_target(",
            self.source,
        )

        marker = (
            "_build_reply_target(),\n"
            "                                "
            "_build_pending_attachments(),"
        )

        self.assertIn(
            marker,
            self.source,
        )

        self.assertIn(
            'tooltip="Cancelar respuesta"',
            self.source,
        )

    def test_reply_requires_text(
        self,
    ):
        start = self.source.index(
            "if captured_reply_target:"
        )

        block = self.source[
            start:
            start + 1800
        ]

        self.assertIn(
            "if not text_to_send:",
            block,
        )

        self.assertIn(
            '"Escribe un mensaje para responder "',
            block,
        )

        self.assertIn(
            '"a la cita seleccionada."',
            block,
        )

    def test_reply_is_bound_to_selected_thread(
        self,
    ):
        start = self.source.index(
            "if captured_reply_target:"
        )

        block = self.source[
            start:
            start + 2600
        ]

        self.assertIn(
            "reply_thread_id = (",
            block,
        )

        self.assertIn(
            "!= captured_thread_id",
            block,
        )

        self.assertIn(
            '"La respuesta pendiente pertenece "',
            block,
        )

        self.assertIn(
            '"a otra conversación."',
            block,
        )

    def test_runtime_receives_only_crm_message_identity(
        self,
    ):
        self.assertIn(
            "reply_to_message_id=(",
            self.source,
        )

        # El frontend no debe pasar provider ID directamente
        # al connector/runtime para resolver el mensaje citado.
        send_start = self.source.index(
            "whatsapp_runtime\n"
            "                        "
            ".send_text_message("
        )

        send_block = self.source[
            send_start:
            send_start + 800
        ]

        self.assertIn(
            "reply_to_message_id",
            send_block,
        )

        self.assertNotIn(
            "reply_to_provider_message_id",
            send_block,
        )

    def test_reply_intent_is_consumed_before_transport(
        self,
    ):
        sending = self.source.index(
            'state["sending"] = True'
        )

        transport = self.source.index(
            "whatsapp_runtime\n"
            "                        "
            ".send_text_message(",
            sending,
        )

        block = self.source[
            sending:
            transport
        ]

        self.assertIn(
            'state["reply_target"] = None',
            block,
        )


if __name__ == "__main__":
    unittest.main()

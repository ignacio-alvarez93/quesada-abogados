import unittest
from pathlib import Path


class ClientAuthorizationHistoryViewTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "frontend/views/client_detail_view.py"
        ).read_text(
            encoding="utf-8"
        )

    def test_imports_history_service(
        self,
    ):
        self.assertIn(
            "list_client_authorizations",
            self.source,
        )

    def test_contains_history_builder(
        self,
    ):
        self.assertIn(
            "def _build_authorization_history_section(",
            self.source,
        )

        self.assertIn(
            "def _authorization_history_card(",
            self.source,
        )

        self.assertIn(
            "def _authorization_history_status(",
            self.source,
        )

    def test_mounts_new_menu_section(
        self,
    ):
        self.assertIn(
            '"Trayectoria administrativa"',
            self.source,
        )

        self.assertIn(
            '"trayectoria_administrativa"',
            self.source,
        )

        self.assertIn(
            'if section == "trayectoria_administrativa":',
            self.source,
        )

    def test_supports_empty_history(
        self,
    ):
        self.assertIn(
            "Este cliente no tiene autorizaciones ",
            self.source,
        )

        self.assertIn(
            "administrativas registradas",
            self.source,
        )

        self.assertIn(
            "empty_state(",
            self.source,
        )

    def test_highlights_current_and_previous(
        self,
    ):
        self.assertIn(
            "AUTORIZACIÓN ACTUAL",
            self.source,
        )

        self.assertIn(
            "AUTORIZACIÓN ANTERIOR",
            self.source,
        )

        self.assertIn(
            "ANTERIORES:",
            self.source,
        )

    def test_distinguishes_missing_authorization_type(
        self,
    ):
        self.assertIn(
            "sin autorización asociada",
            self.source,
        )

    def test_displays_relevant_dates(
        self,
    ):
        for text in (
            "Vigencia desde",
            "Vigencia hasta",
            "Fecha de concesión",
            "Fecha de notificación",
        ):
            self.assertIn(
                text,
                self.source,
            )

    def test_displays_traceability_fields(
        self,
    ):
        for text in (
            "Motivo de inicio",
            "Motivo de finalización",
            "Expediente administrativo:",
            "Expediente CRM #",
            "Documento CRM #",
        ):
            self.assertIn(
                text,
                self.source,
            )

    def test_history_has_no_edit_actions(
        self,
    ):
        history_start = self.source.find(
            "def _build_authorization_history_section("
        )

        history_end = self.source.find(
            "\ndef _section_card(",
            history_start,
        )

        history_source = self.source[
            history_start:history_end
        ]

        self.assertNotIn(
            "primary_button(",
            history_source,
        )

        for forbidden in (
            "Editar autorización",
            "Eliminar autorización",
            "Guardar autorización",
        ):
            self.assertNotIn(
                forbidden,
                history_source,
            )


if __name__ == "__main__":
    unittest.main()

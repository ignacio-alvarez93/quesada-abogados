import unittest
from pathlib import Path


class ClientAuthorizationOriginActionsTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.main_source = Path(
            "app/main.py"
        ).read_text(
            encoding="utf-8"
        )

        cls.clients_source = Path(
            "frontend/views/clients_view.py"
        ).read_text(
            encoding="utf-8"
        )

        cls.detail_source = Path(
            "frontend/views/client_detail_view.py"
        ).read_text(
            encoding="utf-8"
        )

    def test_main_exposes_navigation_callback(
        self,
    ):
        self.assertIn(
            (
                "on_open_expediente="
                "lambda expediente_id"
            ),
            self.main_source,
        )

        self.assertIn(
            (
                "open_expediente_id="
                "expediente_id"
            ),
            self.main_source,
        )

    def test_clients_view_receives_callback(
        self,
    ):
        self.assertIn(
            "on_open_expediente=None",
            self.clients_source,
        )

        self.assertGreaterEqual(
            self.clients_source.count(
                (
                    "on_open_expediente="
                    "on_open_expediente"
                )
            ),
            2,
        )

    def test_detail_receives_callback(
        self,
    ):
        self.assertIn(
            "def client_detail_view(",
            self.detail_source,
        )

        self.assertIn(
            "on_open_expediente=None",
            self.detail_source,
        )

    def test_imports_document_services(
        self,
    ):
        self.assertIn(
            "get_admin_document",
            self.detail_source,
        )

        self.assertIn(
            "document_viewer_service",
            self.detail_source,
        )

    def test_defines_origin_helpers(
        self,
    ):
        for name in (
            "_open_authorization_resolution",
            "_open_authorization_expedient",
            "_authorization_origin_actions",
        ):
            self.assertIn(
                f"def {name}(",
                self.detail_source,
            )

    def test_displays_origin_actions(
        self,
    ):
        self.assertIn(
            '"Ver resolución"',
            self.detail_source,
        )

        self.assertIn(
            '"Ir al expediente"',
            self.detail_source,
        )

    def test_resolution_uses_origin_document(
        self,
    ):
        self.assertIn(
            '"documento_origen_id"',
            self.detail_source,
        )

        self.assertIn(
            "get_admin_document(",
            self.detail_source,
        )

        self.assertIn(
            (
                "document_viewer_service"
                ".open_document("
            ),
            self.detail_source,
        )

    def test_expedient_uses_origin_callback(
        self,
    ):
        self.assertIn(
            '"expediente_origen_id"',
            self.detail_source,
        )

        self.assertIn(
            "on_open_expediente(",
            self.detail_source,
        )

    def test_actions_are_mounted_twice(
        self,
    ):
        self.assertGreaterEqual(
            self.detail_source.count(
                "_authorization_origin_actions("
            ),
            3,
        )

    def test_handles_missing_origins(
        self,
    ):
        expected_fragments = (
            "resolución de origen vinculada",
            "La resolución vinculada no ",
            "existe o está archivada.",
            "ruta de archivo",
            "expediente de origen vinculado",
        )

        for text in expected_fragments:
            self.assertIn(
                text,
                self.detail_source,
            )


if __name__ == "__main__":
    unittest.main()

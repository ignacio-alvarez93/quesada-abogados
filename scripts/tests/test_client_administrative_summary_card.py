import unittest
from pathlib import Path


class ClientAdministrativeSummaryCardTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "frontend/views/client_detail_view.py"
        ).read_text(
            encoding="utf-8"
        )

    def test_imports_administrative_service(
        self,
    ):
        self.assertIn(
            "get_current_authorization",
            self.source,
        )

        self.assertIn(
            "list_administrative_situations",
            self.source,
        )

    def test_contains_summary_card(
        self,
    ):
        self.assertIn(
            "def _administrative_summary_card(",
            self.source,
        )

        self.assertIn(
            '"Situación administrativa"',
            self.source,
        )

        self.assertIn(
            '"Residencia legal computable para nacionalidad"',
            self.source,
        )

    def test_uses_compact_information_blocks(
        self,
    ):
        self.assertIn(
            "def _administrative_info_block(",
            self.source,
        )

        self.assertIn(
            "tight=True",
            self.source,
        )

        self.assertIn(
            "height=30",
            self.source,
        )

    def test_contains_authorization_alerts(
        self,
    ):
        for text in (
            "AUTORIZACIÓN CADUCADA",
            "CADUCA EN",
            "AUTORIZACIÓN VIGENTE",
            "VIGENCIA NO INFORMADA",
        ):
            self.assertIn(
                text,
                self.source,
            )

    def test_contains_legal_residence_alerts(
        self,
    ):
        for text in (
            "Residencia legal interrumpida",
            "Posible interrupción pendiente de revisión",
            "Continuidad pendiente de verificar",
            "Dato declarado por el cliente",
            "Residencia legal sin acreditar documentalmente",
        ):
            self.assertIn(
                text,
                self.source,
            )

    def test_calculates_seniority_dynamically(
        self,
    ):
        self.assertIn(
            "def _years_months_days_from_date(",
            self.source,
        )

        self.assertIn(
            "date.today()",
            self.source,
        )

        self.assertNotIn(
            '"anios_residencia_legal"',
            self.source,
        )

    def test_mounts_card_below_personal_data(
        self,
    ):
        ficha_position = self.source.find(
            "def build_ficha_section():"
        )

        personal_position = self.source.find(
            'detail_section(\n'
            '                    "Datos personales"',
            ficha_position,
        )

        card_position = self.source.find(
            "_administrative_summary_card(",
            personal_position,
        )

        observations_position = self.source.find(
            'detail_section(\n'
            '                    "Observaciones"',
            personal_position,
        )

        self.assertGreater(
            personal_position,
            ficha_position,
        )

        self.assertGreater(
            card_position,
            personal_position,
        )

        self.assertGreater(
            observations_position,
            card_position,
        )


if __name__ == "__main__":
    unittest.main()

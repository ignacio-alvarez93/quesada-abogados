import unittest
from pathlib import Path


class ClientAdministrativeFormContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "frontend/views/clients_view.py"
        ).read_text(
            encoding="utf-8"
        )

    def test_imports_administrative_services(
        self,
    ):
        for symbol in (
            "list_administrative_situations",
            "list_authorization_types",
            "get_current_authorization",
            "set_current_authorization",
            "update_current_authorization_details",
        ):
            self.assertIn(
                symbol,
                self.source,
            )

    def test_contains_administrative_controls(
        self,
    ):
        for symbol in (
            "numero_soporte_nie",
            "localizacion_actual",
            "pais_localizacion_actual",
            "fecha_entrada_espana",
            "fecha_entrada_espana_aproximada",
            "situacion_administrativa",
            "autorizacion_vigente",
            "autorizacion_vigente_desde",
            "autorizacion_vigente_hasta",
        ):
            self.assertIn(
                symbol,
                self.source,
            )

    def test_uses_autocomplete_for_administrative_fields(
        self,
    ):
        for symbol in (
            "localizacion_actual_autocomplete",
            "pais_localizacion_actual_autocomplete",
            "situacion_administrativa_autocomplete",
            "autorizacion_vigente_autocomplete",
        ):
            self.assertIn(
                symbol,
                self.source,
            )

        self.assertIn(
            "options=pais_options",
            self.source,
        )

        self.assertNotIn(
            'situacion_administrativa = select_input(',
            self.source,
        )

        self.assertNotIn(
            'autorizacion_vigente = select_input(',
            self.source,
        )

    def test_uses_short_and_long_stay_situations(
        self,
    ):
        self.assertIn(
            "ESTANCIA_CORTA_DURACION",
            self.source,
        )

        self.assertIn(
            "ESTANCIA_LARGA_DURACION",
            self.source,
        )

        self.assertNotIn(
            'situation_code == "ESTANCIA_REGULAR"',
            self.source,
        )

        self.assertNotIn(
            '"REGIMEN_COMUNITARIO",',
            self.source,
        )

    def test_filters_authorizations_by_situation(
        self,
    ):
        self.assertIn(
            "authorization_matches_situation",
            self.source,
        )

        self.assertIn(
            "refresh_authorization_options",
            self.source,
        )

        self.assertIn(
            "RESIDENCIA_TEMPORAL",
            self.source,
        )

        self.assertIn(
            "LARGA_DURACION",
            self.source,
        )

    def test_does_not_duplicate_same_authorization(
        self,
    ):
        self.assertIn(
            "same_current = bool(",
            self.source,
        )

        self.assertIn(
            "update_current_authorization_details(",
            self.source,
        )

        self.assertIn(
            "set_current_authorization(",
            self.source,
        )

    def test_uses_full_authorization_meaning(
        self,
    ):
        self.assertIn(
            "autorización de residencia",
            self.source.lower(),
        )

        self.assertIn(
            "reagrupación familiar",
            self.source.lower(),
        )

    def test_contains_legal_residence_controls(
        self,
    ):
        for symbol in (
            "fecha_inicio_residencia_legal",
            "fecha_inicio_residencia_legal_aproximada",
            "continuidad_residencia_legal_autocomplete",
            "estado_verificacion_residencia_legal_autocomplete",
            "fecha_verificacion_residencia_legal",
            "origen_residencia_legal_autocomplete",
            "observaciones_residencia_legal",
            "antiguedad_residencia_legal",
        ):
            self.assertIn(
                symbol,
                self.source,
            )

        self.assertIn(
            "Residencia legal computable para nacionalidad",
            self.source,
        )



if __name__ == "__main__":
    unittest.main()

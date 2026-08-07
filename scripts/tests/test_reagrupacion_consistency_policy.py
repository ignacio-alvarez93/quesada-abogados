import sqlite3
import unittest

from backend.services import (
    expedient_consistency_service as policy,
)


class ReagrupacionConsistencyPolicyTests(
    unittest.TestCase
):
    def test_no_presentado_clears_date(self):
        state, date_value = (
            policy.normalize_presentation_fields(
                "NO PRESENTADO",
                "2026-06-30",
            )
        )

        self.assertEqual(
            state,
            "NO PRESENTADO",
        )
        self.assertIsNone(date_value)

    def test_presentado_requires_date(self):
        with self.assertRaisesRegex(
            ValueError,
            "debe tener fecha",
        ):
            policy.normalize_presentation_fields(
                "PRESENTADO",
                "",
            )

    def test_presentado_preserves_date(self):
        state, date_value = (
            policy.normalize_presentation_fields(
                "PRESENTADO",
                "2026-06-20",
            )
        )

        self.assertEqual(
            state,
            "PRESENTADO",
        )
        self.assertEqual(
            date_value,
            "2026-06-20",
        )

    def test_unknown_presentation_state_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Estado de presentación no válido",
        ):
            policy.normalize_presentation_fields(
                "EN TRÁMITE",
                "2026-06-20",
            )

    def test_presented_expedient_cannot_change_subtype(self):
        with self.assertRaisesRegex(
            ValueError,
            "No se puede cambiar el subtipo",
        ):
            policy.validate_subtype_change_after_presentation(
                8,
                10,
                "PRESENTADO",
            )

    def test_not_presented_expedient_can_change_subtype(self):
        policy.validate_subtype_change_after_presentation(
            8,
            10,
            "NO PRESENTADO",
        )

    def test_initial_subtype_accepts_initial_request(self):
        policy.validate_reagrupacion_request_value(
            "REAGRUPACION_FAMILIAR",
            "INICIAL",
            "REAGRUPACIÓN FAMILIAR INICIAL",
        )

    def test_initial_subtype_rejects_renewal_request(self):
        with self.assertRaisesRegex(
            ValueError,
            "subtipo del expediente es INICIAL",
        ):
            policy.validate_reagrupacion_request_value(
                "REAGRUPACION_FAMILIAR",
                "INICIAL",
                "REAGRUPACIÓN FAMILIAR RENOVACIÓN",
            )

    def test_renewal_subtype_accepts_renewal_request(self):
        policy.validate_reagrupacion_request_value(
            "REAGRUPACION_FAMILIAR",
            "RENOVACION",
            "REAGRUPACIÓN FAMILIAR RENOVACIÓN",
        )

    def test_renewal_subtype_rejects_initial_request(self):
        with self.assertRaisesRegex(
            ValueError,
            "subtipo del expediente es RENOVACIÓN",
        ):
            policy.validate_reagrupacion_request_value(
                "REAGRUPACION_FAMILIAR",
                "RENOVACION",
                "REAGRUPACIÓN FAMILIAR INICIAL",
            )

    def test_other_procedure_is_not_restricted(self):
        policy.validate_reagrupacion_request_value(
            "RESIDENCIA_NO_LUCRATIVA",
            "INICIAL",
            "CUALQUIER VALOR",
        )

    def test_connection_based_validation(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        conn.executescript(
            """
            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL
            );

            CREATE TABLE config_subtipos_expediente (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                codigo TEXT NOT NULL
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                subtipo_expediente_id INTEGER
            );

            INSERT INTO config_tipos_expediente (
                id,
                codigo
            )
            VALUES (
                14,
                'REAGRUPACION_FAMILIAR'
            );

            INSERT INTO config_subtipos_expediente (
                id,
                tipo_expediente_id,
                codigo
            )
            VALUES
                (8, 14, 'INICIAL'),
                (10, 14, 'RENOVACION');

            INSERT INTO expedientes (
                id,
                tipo_expediente_id,
                subtipo_expediente_id
            )
            VALUES (
                31,
                14,
                10
            );
            """
        )

        policy.validate_reagrupacion_request_for_expedient(
            conn,
            31,
            "REAGRUPACIÓN FAMILIAR RENOVACIÓN",
        )

        with self.assertRaises(ValueError):
            policy.validate_reagrupacion_request_for_expedient(
                conn,
                31,
                "REAGRUPACIÓN FAMILIAR INICIAL",
            )

        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

import sqlite3
import unittest
from pathlib import Path


DB = Path("database/quesada.db")


class ReagrupacionRenewalFingerprintsTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(
            f"file:{DB}?mode=ro",
            uri=True,
        )
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _rule(self, code):
        return self.conn.execute(
            """
            SELECT
                r.*,

                tor.codigo AS tipo_origen,
                sor.codigo AS subtipo_origen,

                td.codigo AS tipo_destino,
                sd.codigo AS subtipo_destino

            FROM config_reglas_expediente_derivado r

            LEFT JOIN config_tipos_expediente tor
              ON tor.id =
                 r.tipo_expediente_origen_id

            LEFT JOIN config_subtipos_expediente sor
              ON sor.id =
                 r.subtipo_expediente_origen_id

            LEFT JOIN config_tipos_expediente td
              ON td.id =
                 r.tipo_expediente_destino_id

            LEFT JOIN config_subtipos_expediente sd
              ON sd.id =
                 r.subtipo_expediente_destino_id

            WHERE r.codigo = ?
              AND r.activo = 1
            """,
            (code,),
        ).fetchone()

    def test_initial_approval_still_derives_to_visa(self):
        rule = self._rule(
            "REAGRUPACION_CONCEDIDA_A_VISADO"
        )

        self.assertIsNotNone(rule)

        self.assertEqual(
            rule["tipo_origen"],
            "REAGRUPACION_FAMILIAR",
        )

        self.assertEqual(
            rule["subtipo_origen"],
            "INICIAL",
        )

        self.assertIn(
            "VISADO",
            rule["tipo_destino"],
        )

    def test_renewal_approval_derives_to_fingerprints(self):
        rule = self._rule(
            "REAGRUPACION_RENOVACION_CONCEDIDA_A_HUELLAS"
        )

        self.assertIsNotNone(rule)

        self.assertEqual(
            rule["tipo_origen"],
            "REAGRUPACION_FAMILIAR",
        )

        self.assertEqual(
            rule["subtipo_origen"],
            "RENOVACION",
        )

        self.assertEqual(
            rule["evento_disparador"],
            "RESOLUCION_FAVORABLE",
        )

        self.assertEqual(
            rule["resultado_requerido"],
            "CONCEDIDO",
        )

        self.assertEqual(
            rule["tipo_destino"],
            "TOMA_HUELLAS",
        )

        self.assertIsNone(
            rule["subtipo_destino"],
        )

        self.assertEqual(
            int(rule["creacion_automatica"]),
            0,
        )

        self.assertEqual(
            int(rule["requiere_revision_humana"]),
            1,
        )

    def test_renewal_has_no_active_visa_destination(self):
        rows = self.conn.execute(
            """
            SELECT
                r.codigo,
                td.codigo AS tipo_destino,
                sd.codigo AS subtipo_destino

            FROM config_reglas_expediente_derivado r

            JOIN config_tipos_expediente tor
              ON tor.id =
                 r.tipo_expediente_origen_id

            JOIN config_subtipos_expediente sor
              ON sor.id =
                 r.subtipo_expediente_origen_id

            JOIN config_tipos_expediente td
              ON td.id =
                 r.tipo_expediente_destino_id

            LEFT JOIN config_subtipos_expediente sd
              ON sd.id =
                 r.subtipo_expediente_destino_id

            WHERE tor.codigo =
                  'REAGRUPACION_FAMILIAR'

              AND sor.codigo =
                  'RENOVACION'

              AND r.activo = 1

              AND (
                    UPPER(td.codigo)
                        LIKE '%VISADO%'
                    OR UPPER(
                        COALESCE(
                            sd.codigo,
                            ''
                        )
                    ) LIKE '%VISADO%'
              )
            """
        ).fetchall()

        self.assertEqual(
            len(rows),
            0,
            (
                "Una renovación de reagrupación "
                "no puede derivar a visado."
            ),
        )

    def test_visa_approval_still_derives_to_fingerprints(self):
        rule = self._rule(
            "VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS"
        )

        self.assertIsNotNone(rule)

        self.assertEqual(
            rule["tipo_destino"],
            "TOMA_HUELLAS",
        )

        self.assertIsNone(
            rule["subtipo_destino"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

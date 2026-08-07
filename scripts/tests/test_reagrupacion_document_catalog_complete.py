import sqlite3
import unittest
from pathlib import Path


DB = Path("database/quesada.db")


class ReagrupacionDocumentCatalogCompleteTests(
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

    def _subtype_id(self, code):
        row = self.conn.execute(
            """
            SELECT s.id
            FROM config_subtipos_expediente s
            JOIN config_tipos_expediente t
              ON t.id = s.tipo_expediente_id
            WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
              AND s.codigo = ?
              AND COALESCE(s.activo, 1) = 1
            """,
            (code,),
        ).fetchone()

        self.assertIsNotNone(row)
        return int(row["id"])

    def _group(self, subtype_code, group_code):
        subtype_id = self._subtype_id(
            subtype_code
        )

        row = self.conn.execute(
            """
            SELECT g.*
            FROM config_grupos_requisitos_documentales g
            JOIN config_tipos_expediente t
              ON t.id = g.tipo_expediente_id
            WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
              AND g.subtipo_expediente_id = ?
              AND g.codigo = ?
              AND COALESCE(g.activo, 1) = 1
            """,
            (
                subtype_id,
                group_code,
            ),
        ).fetchone()

        self.assertIsNotNone(
            row,
            (
                f"Falta grupo {group_code} "
                f"para {subtype_code}"
            ),
        )

        return dict(row)

    def _options(self, subtype_code, group_code):
        group = self._group(
            subtype_code,
            group_code,
        )

        return [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT
                    c.codigo,
                    o.rol_documental,
                    o.etiqueta_requisito,
                    o.activo
                FROM config_grupo_requisito_documentos o
                JOIN config_documentos_catalogo c
                  ON c.id = o.documento_catalogo_id
                WHERE o.grupo_id = ?
                  AND COALESCE(o.activo, 1) = 1
                  AND COALESCE(c.activo, 1) = 1
                ORDER BY o.orden, o.id
                """,
                (int(group["id"]),),
            )
        ]

    def test_initial_materialized_rules(self):
        vivienda = self._group(
            "INICIAL",
            "VIVIENDA",
        )
        medios = self._group(
            "INICIAL",
            "MEDIOS_ECONOMICOS",
        )

        self.assertEqual(
            vivienda["regla_cumplimiento"],
            "ANY",
        )
        self.assertEqual(
            medios["regla_cumplimiento"],
            "ANY",
        )

    def test_initial_housing_has_request_alternative(self):
        options = self._options(
            "INICIAL",
            "VIVIENDA",
        )

        codes = {
            row["codigo"]
            for row in options
        }

        self.assertIn(
            "INFORME_DE_VIVIENDA",
            codes,
        )
        self.assertIn(
            "JUSTIFICANTE_SOLICITUD_INFORME_VIVIENDA",
            codes,
        )

    def test_initial_economic_options_are_expanded(self):
        options = self._options(
            "INICIAL",
            "MEDIOS_ECONOMICOS",
        )

        codes = {
            row["codigo"]
            for row in options
        }

        for expected in (
            "NOMINAS",
            "CONTRATO_TRABAJO",
            "VIDA_LABORAL",
            "DECLARACION_IRPF",
            "EXTRACTOS_BANCARIOS",
            "CERTIFICADO_BANCARIO",
        ):
            self.assertIn(
                expected,
                codes,
            )

    def test_renewal_has_expected_groups(self):
        expected = {
            "IDENTIDAD_PARTES",
            "DOMICILIO_CONVIVENCIA",
            "VINCULO_FAMILIAR",
            "MEDIOS_ECONOMICOS",
            "ESCOLARIZACION",
            "ESFUERZO_INTEGRACION",
        }

        subtype_id = self._subtype_id(
            "RENOVACION"
        )

        rows = self.conn.execute(
            """
            SELECT g.codigo
            FROM config_grupos_requisitos_documentales g
            JOIN config_tipos_expediente t
              ON t.id = g.tipo_expediente_id
            WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
              AND g.subtipo_expediente_id = ?
              AND COALESCE(g.activo, 1) = 1
            """,
            (subtype_id,),
        ).fetchall()

        actual = {
            row["codigo"]
            for row in rows
        }

        self.assertTrue(
            expected.issubset(actual),
            expected - actual,
        )

    def test_renewal_identity_has_both_roles(self):
        options = self._options(
            "RENOVACION",
            "IDENTIDAD_PARTES",
        )

        pairs = {
            (
                row["codigo"],
                row["rol_documental"],
            )
            for row in options
        }

        for expected in (
            ("PASAPORTE", "REAGRUPANTE"),
            ("NIE", "REAGRUPANTE"),
            ("PASAPORTE", "REAGRUPADO"),
            ("NIE", "REAGRUPADO"),
        ):
            self.assertIn(
                expected,
                pairs,
            )

    def test_renewal_economic_group_is_required(self):
        group = self._group(
            "RENOVACION",
            "MEDIOS_ECONOMICOS",
        )

        self.assertEqual(
            group["regla_cumplimiento"],
            "ANY",
        )
        self.assertEqual(
            int(group["minimo_documentos"]),
            1,
        )

    def test_contextual_renewal_groups_do_not_block_globally(self):
        for code in (
            "ESCOLARIZACION",
            "ESFUERZO_INTEGRACION",
        ):
            group = self._group(
                "RENOVACION",
                code,
            )

            self.assertEqual(
                group["regla_cumplimiento"],
                "OPTIONAL",
            )
            self.assertEqual(
                int(group["minimo_documentos"]),
                0,
            )

    def test_canonical_nomenclatures_exist_for_renewal(self):
        subtype_id = self._subtype_id(
            "RENOVACION"
        )

        rows = self.conn.execute(
            """
            SELECT
                c.codigo,
                n.rol_documental,
                n.patron_nombre
            FROM config_nomenclaturas_catalogo n
            JOIN config_documentos_catalogo c
              ON c.id = n.documento_catalogo_id
            JOIN config_tipos_expediente t
              ON t.id = n.tipo_expediente_id
            WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
              AND n.subtipo_expediente_id = ?
              AND COALESCE(n.activo, 1) = 1
            """,
            (subtype_id,),
        ).fetchall()

        self.assertGreater(
            len(rows),
            0,
        )

        pairs = {
            (
                row["codigo"],
                row["rol_documental"],
            )
            for row in rows
        }

        self.assertIn(
            ("NIE", "REAGRUPADO"),
            pairs,
        )
        self.assertIn(
            ("PASAPORTE", "REAGRUPADO"),
            pairs,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

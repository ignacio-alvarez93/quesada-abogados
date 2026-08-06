import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SOURCE_DB = ROOT / "database" / "quesada.db"

MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_replace_immigration_procedure_catalog.sql"
)


CANONICAL_CODES = {
    "PRORROGA_ESTANCIA_CORTA_SIN_VISADO",
    "ESTANCIA_ESTUDIOS_SUPERIORES",
    "ESTANCIA_EDUCACION_SECUNDARIA",
    "ESTANCIA_MOVILIDAD_ALUMNOS",
    "ESTANCIA_VOLUNTARIADO",
    "ESTANCIA_ACTIVIDADES_FORMATIVAS",
    "ESTANCIA_FORMACION_SANITARIA",
    "ESTANCIA_FAMILIARES_ESTUDIANTE",
    "PRORROGA_ESTANCIA_LARGA_DURACION",
    "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
    "REAGRUPACION_FAMILIAR",
    "RESIDENCIA_INDEPENDIENTE_REAGRUPADO",
    "RESIDENCIA_INDEPENDIENTE_REAGRUPADO_REFORZADA",
    "RESIDENCIA_TRABAJO_CUENTA_AJENA",
    "RESIDENCIA_TRABAJO_CUENTA_PROPIA",
    "RESIDENCIA_EXCEPCION_AUTORIZACION_TRABAJO",
    "RESIDENCIA_RETORNO_VOLUNTARIO",
    "RESIDENCIA_BUSQUEDA_EMPLEO_PROYECTO_EMPRESARIAL",
    "FAMILIAR_PERSONA_ESPANOLA",
    "RESIDENCIA_INDEPENDIENTE_FAMILIAR_ESPANOL",
    "ARRAIGO_SEGUNDA_OPORTUNIDAD",
    "ARRAIGO_SOCIOLABORAL",
    "ARRAIGO_SOCIAL",
    "ARRAIGO_SOCIOFORMATIVO",
    "ARRAIGO_FAMILIAR",
    "ARRAIGO_SOLICITANTE_PROTECCION_INTERNACIONAL_2026",
    "ARRAIGO_EXTRAORDINARIO_2026",
    "RESIDENCIA_RAZONES_HUMANITARIAS",
    "COLABORACION_AUTORIDADES",
    "VICTIMA_VIOLENCIA_GENERO",
    "VICTIMA_VIOLENCIA_SEXUAL",
    "COLABORACION_RED_ORGANIZADA",
    "VICTIMA_TRATA_SERES_HUMANOS",
    "PRORROGA_CIRCUNSTANCIAS_EXCEPCIONALES",
    "TARJETA_FAMILIAR_CIUDADANO_UE",
    "RESIDENCIA_PERMANENTE_CIUDADANO_UE",
    "TARJETA_PERMANENTE_FAMILIAR_CIUDADANO_UE",
    "CONSERVACION_DERECHO_RESIDENCIA_UE",
    "RESIDENCIA_LARGA_DURACION",
    "RESIDENCIA_LARGA_DURACION_UE",
    "RECUPERACION_LARGA_DURACION",
    "RECUPERACION_LARGA_DURACION_UE",
    "RESIDENCIA_TRABAJO_TEMPORADA",
    "TRABAJADOR_TRANSFRONTERIZO_CUENTA_AJENA",
    "TRABAJADOR_TRANSFRONTERIZO_CUENTA_PROPIA",
    "RESIDENCIA_HIJO_TUTELADO_NACIDO_ESPANA",
    "RESIDENCIA_MENOR_DISCAPACITADO_NO_NACIDO_ESPANA",
    "DESPLAZAMIENTO_MENOR_TRATAMIENTO_MEDICO",
    "DESPLAZAMIENTO_MENOR_VACACIONES_ESCOLARIZACION",
    "RESIDENCIA_MENOR_NO_ACOMPANADO",
    "RENOVACION_MENOR_TUTELADO_MAYORIA_EDAD",
    "MODIFICACION_DESDE_ESTANCIA",
    "MODIFICACION_DESDE_NO_LUCRATIVA",
    "MODIFICACION_DESDE_RESIDENCIA_TEMPORAL",
    "MODIFICACION_DESDE_CIRCUNSTANCIAS_EXCEPCIONALES",
    "MODIFICACION_DESDE_RAZONES_HUMANITARIAS",
    "MODIFICACION_DESDE_FAMILIAR_UE",
    "MODIFICACION_DESDE_FAMILIAR_ESPANOL",
    "MODIFICACION_DESDE_TEMPORADA",
    "MODIFICACION_ALCANCE_AUTORIZACION",
    "MODIFICACION_CUENTA_AJENA_A_PROPIA",
    "MODIFICACION_PROTECCION_TEMPORAL",
}


DEPENDENCY_TABLES = (
    "config_box_rutas",
    "config_documentos_requeridos",
    "config_formularios_expediente",
    "config_grupos_requisitos_documentales",
    "config_presentaciones_asistidas",
    "expedientes",
    "form_mapper_templates",
)


class ImmigrationCatalogReplacementTest(
    unittest.TestCase
):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tempdir.name)
            / "quesada_test.db"
        )

        shutil.copy2(
            SOURCE_DB,
            self.db_path,
        )

        self.conn = sqlite3.connect(
            self.db_path
        )

        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        self.before_dependencies = {
            type_id: self._dependency_snapshot(
                type_id
            )
            for type_id in (13, 14, 15)
        }

        self.before_expedients = {
            type_id: self._expedient_count(type_id)
            for type_id in (13, 14, 15)
        }

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _apply_migration(self):
        self.conn.executescript(
            MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        self.conn.commit()

    def _expedient_count(self, type_id):
        return self.conn.execute(
            """
            SELECT COUNT(*)
            FROM expedientes
            WHERE tipo_expediente_id = ?
            """,
            (type_id,),
        ).fetchone()[0]

    def _dependency_snapshot(self, type_id):
        result = {}

        for table in DEPENDENCY_TABLES:
            columns = {
                row["name"]
                for row in self.conn.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
            }

            if "tipo_expediente_id" not in columns:
                continue

            result[table] = self.conn.execute(
                f"""
                SELECT COUNT(*)
                FROM "{table}"
                WHERE tipo_expediente_id = ?
                """,
                (type_id,),
            ).fetchone()[0]

        return result

    def _type(self, code):
        return self.conn.execute(
            """
            SELECT
                id,
                codigo,
                nombre,
                familia_id,
                workflow_code,
                activo
            FROM config_tipos_expediente
            WHERE codigo = ?
            """,
            (code,),
        ).fetchone()

    def test_migration_is_idempotent(self):
        self._apply_migration()

        first_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM config_tipos_expediente
            """
        ).fetchone()[0]

        self._apply_migration()

        second_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM config_tipos_expediente
            """
        ).fetchone()[0]

        self.assertEqual(
            first_count,
            second_count,
        )

    def test_protected_type_ids_are_preserved(self):
        self._apply_migration()

        expected = {
            13:
                "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
            14:
                "REAGRUPACION_FAMILIAR",
            15:
                "VISADO_REAGRUPACION_FAMILIAR",
        }

        for type_id, code in expected.items():
            row = self.conn.execute(
                """
                SELECT id, codigo
                FROM config_tipos_expediente
                WHERE id = ?
                """,
                (type_id,),
            ).fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(code, row["codigo"])

    def test_protected_subtype_ids_are_preserved(self):
        self._apply_migration()

        expected = {
            6: (
                13,
                "RENOVACION_TITULAR",
            ),
            7: (
                13,
                "RENOVACION_FAMILIAR",
            ),
            8: (
                14,
                "INICIAL",
            ),
        }

        for subtype_id, expected_value in (
            expected.items()
        ):
            row = self.conn.execute(
                """
                SELECT
                    tipo_expediente_id,
                    codigo
                FROM config_subtipos_expediente
                WHERE id = ?
                """,
                (subtype_id,),
            ).fetchone()

            self.assertIsNotNone(row)

            self.assertEqual(
                expected_value,
                (
                    row["tipo_expediente_id"],
                    row["codigo"],
                ),
            )

    def test_protected_expedients_are_preserved(self):
        self._apply_migration()

        after = {
            type_id: self._expedient_count(type_id)
            for type_id in (13, 14, 15)
        }

        self.assertEqual(
            self.before_expedients,
            after,
        )

    def test_protected_dependencies_are_preserved(self):
        self._apply_migration()

        after = {
            type_id: self._dependency_snapshot(
                type_id
            )
            for type_id in (13, 14, 15)
        }

        self.assertEqual(
            self.before_dependencies,
            after,
        )

    def test_all_canonical_types_are_active(self):
        self._apply_migration()

        immigration_family = self.conn.execute(
            """
            SELECT id
            FROM config_familias_expediente
            WHERE codigo = 'EXTRANJERIA'
            """
        ).fetchone()["id"]

        rows = self.conn.execute(
            """
            SELECT
                codigo,
                familia_id,
                workflow_code,
                activo
            FROM config_tipos_expediente
            WHERE codigo IN (
                SELECT codigo
                FROM config_tipos_expediente
            )
            """
        ).fetchall()

        by_code = {
            row["codigo"]: row
            for row in rows
        }

        self.assertTrue(
            CANONICAL_CODES.issubset(
                by_code.keys()
            )
        )

        for code in CANONICAL_CODES:
            row = by_code[code]

            self.assertEqual(
                immigration_family,
                row["familia_id"],
                code,
            )

            self.assertEqual(
                "EXTRANJERIA",
                row["workflow_code"],
                code,
            )

            self.assertEqual(
                1,
                row["activo"],
                code,
            )

    def test_legacy_types_are_inactive(self):
        self._apply_migration()

        legacy_codes = {
            "ESTANCIA_ESTUDIOS",
            "RENOVACION",
            "ESTATUTO_DE_ESPAÑOL",
            "REGULARIZACION_MASIVA_TRANS_20",
            "REGULARIZACION_MASIVA_TRANS_21",
        }

        rows = self.conn.execute(
            """
            SELECT codigo, activo
            FROM config_tipos_expediente
            WHERE codigo IN (
                'ESTANCIA_ESTUDIOS',
                'RENOVACION',
                'ESTATUTO_DE_ESPAÑOL',
                'REGULARIZACION_MASIVA_TRANS_20',
                'REGULARIZACION_MASIVA_TRANS_21'
            )
            """
        ).fetchall()

        self.assertEqual(
            legacy_codes,
            {
                row["codigo"]
                for row in rows
            },
        )

        self.assertTrue(
            all(
                row["activo"] == 0
                for row in rows
            )
        )

    def test_visados_family_is_consolidated(self):
        self._apply_migration()

        old_family = self.conn.execute(
            """
            SELECT activo
            FROM config_familias_expediente
            WHERE codigo = 'VISADOS'
            """
        ).fetchone()

        canonical_family = self.conn.execute(
            """
            SELECT id, activo
            FROM config_familias_expediente
            WHERE codigo =
                'TRAMITES_CONSULARES'
            """
        ).fetchone()

        visa_type = self._type(
            "VISADO_REAGRUPACION_FAMILIAR"
        )

        self.assertEqual(
            0,
            old_family["activo"],
        )

        self.assertEqual(
            1,
            canonical_family["activo"],
        )

        self.assertEqual(
            canonical_family["id"],
            visa_type["familia_id"],
        )

        self.assertEqual(
            15,
            visa_type["id"],
        )

    def test_no_lucrativa_keeps_specialized_subtypes(self):
        self._apply_migration()

        rows = self.conn.execute(
            """
            SELECT codigo, activo
            FROM config_subtipos_expediente
            WHERE tipo_expediente_id = 13
            """
        ).fetchall()

        subtypes = {
            row["codigo"]: row["activo"]
            for row in rows
        }

        self.assertEqual(
            1,
            subtypes["INICIAL"],
        )

        self.assertEqual(
            1,
            subtypes["RENOVACION_TITULAR"],
        )

        self.assertEqual(
            1,
            subtypes["RENOVACION_FAMILIAR"],
        )

    def test_reagrupacion_adds_renewal_without_damage(self):
        self._apply_migration()

        rows = self.conn.execute(
            """
            SELECT id, codigo, activo
            FROM config_subtipos_expediente
            WHERE tipo_expediente_id = 14
            """
        ).fetchall()

        by_code = {
            row["codigo"]: row
            for row in rows
        }

        self.assertEqual(
            8,
            by_code["INICIAL"]["id"],
        )

        self.assertEqual(
            1,
            by_code["INICIAL"]["activo"],
        )

        self.assertEqual(
            1,
            by_code["RENOVACION"]["activo"],
        )


if __name__ == "__main__":
    unittest.main()

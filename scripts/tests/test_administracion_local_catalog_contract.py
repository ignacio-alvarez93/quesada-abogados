import ast
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "expedients_view.py"
)

MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_seed_administracion_local_catalog.sql"
)

DATABASE = (
    ROOT
    / "database"
    / "quesada.db"
)


class AdministracionLocalCatalogContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.view_source = VIEW.read_text(
            encoding="utf-8"
        )

        cls.view_tree = ast.parse(
            cls.view_source
        )

        cls.migration_sql = MIGRATION.read_text(
            encoding="utf-8"
        )

    def function_source(self, name):
        node = next(
            item
            for item in ast.walk(self.view_tree)
            if isinstance(item, ast.FunctionDef)
            and item.name == name
        )

        return ast.get_source_segment(
            self.view_source,
            node,
        )

    def test_migration_defines_family(self):
        self.assertIn(
            "'ADMINISTRACION_LOCAL'",
            self.migration_sql,
        )

        self.assertIn(
            "'ADMINISTRACIÓN LOCAL'",
            self.migration_sql,
        )

    def test_migration_defines_three_types(self):
        for code in (
            "INFORME_VIVIENDA_ADECUADA",
            "INFORME_INTEGRACION_SOCIAL",
            "INFORME_ESFUERZO_INTEGRACION",
        ):
            self.assertIn(
                f"'{code}'",
                self.migration_sql,
            )

    def test_migration_is_idempotent(self):
        self.assertTrue(
            DATABASE.exists(),
            "No existe database/quesada.db",
        )

        with tempfile.TemporaryDirectory() as temp:
            copied_database = (
                Path(temp)
                / "catalog_test.db"
            )

            shutil.copy2(
                DATABASE,
                copied_database,
            )

            connection = sqlite3.connect(
                copied_database
            )

            try:
                connection.executescript(
                    self.migration_sql
                )

                connection.executescript(
                    self.migration_sql
                )

                family_count = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM config_familias_expediente
                        WHERE codigo =
                            'ADMINISTRACION_LOCAL'
                        """
                    ).fetchone()[0]
                )

                type_count = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM config_tipos_expediente
                        WHERE codigo IN (
                            'INFORME_VIVIENDA_ADECUADA',
                            'INFORME_INTEGRACION_SOCIAL',
                            'INFORME_ESFUERZO_INTEGRACION'
                        )
                        """
                    ).fetchone()[0]
                )

                linked_count = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM config_tipos_expediente t
                        JOIN config_familias_expediente f
                          ON f.id = t.familia_id
                        WHERE f.codigo =
                            'ADMINISTRACION_LOCAL'
                          AND t.codigo IN (
                            'INFORME_VIVIENDA_ADECUADA',
                            'INFORME_INTEGRACION_SOCIAL',
                            'INFORME_ESFUERZO_INTEGRACION'
                          )
                        """
                    ).fetchone()[0]
                )
            finally:
                connection.close()

        self.assertEqual(
            family_count,
            1,
        )

        self.assertEqual(
            type_count,
            3,
        )

        self.assertEqual(
            linked_count,
            3,
        )

    def test_family_has_visual_style(self):
        assignment = next(
            (
                node
                for node in ast.walk(self.view_tree)
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Dict)
                and any(
                    isinstance(target, ast.Name)
                    and target.id
                    == "FAMILY_SELECTOR_STYLES"
                    for target in node.targets
                )
            ),
            None,
        )

        self.assertIsNotNone(
            assignment,
            "No existe FAMILY_SELECTOR_STYLES",
        )

        family_keys = {
            key.value
            for key in assignment.value.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        }

        self.assertIn(
            "ADMINISTRACION_LOCAL",
            family_keys,
        )

        self.assertIn(
            "ACCOUNT_BALANCE_OUTLINED",
            self.view_source,
        )

    def test_types_are_grouped_in_two_subfamilies(
        self,
    ):
        source = self.function_source(
            "_expedient_type_catalog_group"
        )

        self.assertIn(
            '"INFORME_VIVIENDA_ADECUADA"',
            source,
        )

        self.assertIn(
            '"Informes de vivienda"',
            source,
        )

        self.assertIn(
            '"INFORME_INTEGRACION_SOCIAL"',
            source,
        )

        self.assertIn(
            '"INFORME_ESFUERZO_INTEGRACION"',
            source,
        )

        self.assertIn(
            '"Informes de integración"',
            source,
        )

    def test_family_routes_through_subfamilies(
        self,
    ):
        source = self.function_source(
            "open_new_for_family"
        )

        self.assertIn(
            '"ADMINISTRACION_LOCAL"',
            source,
        )

        self.assertIn(
            "open_new_expedient_subfamily_catalog",
            source,
        )

    def test_no_specific_form_is_created(self):
        self.assertNotIn(
            "FORM_INFORME_VIVIENDA",
            self.migration_sql,
        )

        self.assertNotIn(
            "config_formularios_expediente",
            self.migration_sql,
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_document_target_service
    as target_service,
)


class ExpedientDocumentTargetTests(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "targets.db"
        )

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                box_folder_path TEXT
            )
            """
        )
        self.box_root = (
            Path(self.temp_dir.name)
            / "EXPEDIENTE 46"
        )
        self.box_root.mkdir()

        conn.execute(
            """
            INSERT INTO expedientes (
                id,
                box_folder_path
            )
            VALUES (?, ?)
            """,
            (
                46,
                str(self.box_root),
            ),
        )
        conn.commit()
        conn.close()

        target_service.ensure_schema(
            db_path=self.db_path
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sets_active_target(self):
        target = target_service.set_target(
            46,
            "PRESENTACION",
            r"DOCUMENTACION\PARA PRESENTAR",
            db_path=self.db_path,
        )

        self.assertEqual(
            target["purpose"],
            "PRESENTACION",
        )
        self.assertEqual(
            target["relative_path"],
            "DOCUMENTACION/PARA PRESENTAR",
        )
        self.assertEqual(
            target["active"],
            1,
        )

    def test_replaces_previous_target_for_purpose(
        self,
    ):
        first = target_service.set_target(
            46,
            "PRESENTACION",
            "DOCUMENTACION/PRIMERA",
            db_path=self.db_path,
        )

        second = target_service.set_target(
            46,
            "PRESENTACION",
            "DOCUMENTACION/SEGUNDA",
            db_path=self.db_path,
        )

        self.assertNotEqual(
            first["id"],
            second["id"],
        )

        active = (
            target_service.get_active_target(
                46,
                "PRESENTACION",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active["relative_path"],
            "DOCUMENTACION/SEGUNDA",
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        historical = conn.execute(
            """
            SELECT active
            FROM expedient_document_targets
            WHERE id = ?
            """,
            (first["id"],),
        ).fetchone()

        conn.close()

        self.assertEqual(
            historical["active"],
            0,
        )

    def test_same_folder_supports_multiple_purposes(
        self,
    ):
        path = "DOCUMENTACION/PAQUETE"

        target_service.set_target(
            46,
            "PRESENTACION",
            path,
            db_path=self.db_path,
        )

        target_service.set_target(
            46,
            "APORTACION",
            path,
            db_path=self.db_path,
        )

        target_service.set_target(
            46,
            "APORTACION_TASAS",
            path,
            db_path=self.db_path,
        )

        targets = (
            target_service.list_targets_for_path(
                46,
                path,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            {
                item["purpose"]
                for item in targets
            },
            {
                "PRESENTACION",
                "APORTACION",
                "APORTACION_TASAS",
            },
        )

    def test_clear_target_preserves_history(self):
        target_service.set_target(
            46,
            "REQUERIMIENTO",
            "DOCUMENTACION/REQUERIMIENTO",
            db_path=self.db_path,
        )

        updated = target_service.clear_target(
            46,
            "REQUERIMIENTO",
            db_path=self.db_path,
        )

        self.assertEqual(updated, 1)

        active = (
            target_service.get_active_target(
                46,
                "REQUERIMIENTO",
                db_path=self.db_path,
            )
        )

        self.assertIsNone(active)

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            target_service.set_target(
                46,
                "PRESENTACION",
                "../OTRA CARPETA",
                db_path=self.db_path,
            )

    def test_sets_target_from_absolute_folder(self):
        folder = (
            self.box_root
            / "DOCUMENTACION"
            / "PARA PRESENTAR"
        )
        folder.mkdir(parents=True)

        target = (
            target_service
            .set_target_from_absolute(
                46,
                "PRESENTACION",
                folder,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            target["relative_path"],
            "DOCUMENTACION/PARA PRESENTAR",
        )

    def test_resolves_active_target_path(self):
        folder = (
            self.box_root
            / "PRESENTACION FINAL"
        )
        folder.mkdir()

        target_service.set_target_from_absolute(
            46,
            "PRESENTACION",
            folder,
            db_path=self.db_path,
        )

        target = (
            target_service
            .resolve_target_path(
                46,
                "PRESENTACION",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            Path(target["absolute_path"]),
            folder.resolve(),
        )

    def test_rejects_folder_outside_expedient(self):
        outside = (
            Path(self.temp_dir.name)
            / "FUERA"
        )
        outside.mkdir()

        with self.assertRaises(ValueError):
            (
                target_service
                .set_target_from_absolute(
                    46,
                    "PRESENTACION",
                    outside,
                    db_path=self.db_path,
                )
            )

    def test_rejects_unknown_purpose(self):
        with self.assertRaises(ValueError):
            target_service.set_target(
                46,
                "NO_VALIDO",
                "DOCUMENTACION",
                db_path=self.db_path,
            )


if __name__ == "__main__":
    unittest.main()

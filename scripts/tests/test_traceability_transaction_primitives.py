import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    expedient_traceability_service,
)


class TraceabilityTransactionPrimitivesTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "traceability.db"
        )

        self.conn = sqlite3.connect(
            self.db_path
        )

        self.conn.row_factory = (
            sqlite3.Row
        )

        self.conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        self.conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                fecha_caducidad_residencia TEXT,
                fecha_caducidad_origen TEXT,
                fecha_caducidad_expediente_id INTEGER,
                fecha_caducidad_documento_id INTEGER,
                fecha_caducidad_actualizada_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                estado_administrativo_id INTEGER,
                estado_presentacion TEXT,
                updated_at TEXT
            );

            CREATE TABLE expediente_eventos (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER NOT NULL,
                cliente_id INTEGER NOT NULL,
                tipo_evento TEXT NOT NULL,
                titulo TEXT NOT NULL,
                descripcion TEXT,
                estado_anterior TEXT,
                estado_nuevo TEXT,
                entidad_relacionada TEXT,
                entidad_relacionada_id INTEGER,
                usuario TEXT,
                fecha_evento TEXT DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE expediente_justificantes (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER NOT NULL,
                cliente_id INTEGER NOT NULL,
                archivo_nombre TEXT,
                archivo_ruta TEXT,
                tipo_justificante TEXT,
                fecha_presentacion TEXT,
                numero_registro TEXT,
                organo_presentacion TEXT,
                fecha_documento TEXT,
                csv_documento TEXT,
                dir3_documento TEXT,
                organo_documento TEXT,
                nie_documento TEXT,
                numero_expediente_documento TEXT,
                metadata_documento_json TEXT,
                procedimiento_detectado TEXT,
                estado_conciliacion TEXT,
                observaciones TEXT,
                activo INTEGER DEFAULT 1
            );

            INSERT INTO clientes (
                id,
                fecha_caducidad_residencia
            )
            VALUES (
                1,
                '2026-01-01'
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                estado_administrativo_id
            )
            VALUES (
                100,
                1,
                1
            );
            """
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_public_functions_accept_conn(self):
        path = Path(
            "backend/services/"
            "expedient_traceability_service.py"
        )

        tree = ast.parse(
            path.read_text(
                encoding="utf-8"
            )
        )

        expected = {
            "registrar_evento",
            "create_justificante",
            "_apply_admin_document_transition",
            "_update_client_residence_expiry_from_resolution",
        }

        found = {}

        for node in tree.body:
            if not isinstance(
                node,
                ast.FunctionDef,
            ):
                continue

            if node.name not in expected:
                continue

            found[node.name] = [
                argument.arg
                for argument in node.args.args
            ]

        self.assertEqual(
            set(found),
            expected,
        )

        for name in expected:
            self.assertIn(
                "conn",
                found[name],
            )

    def test_event_can_be_rolled_back_externally(
        self,
    ):
        self.conn.execute(
            "BEGIN IMMEDIATE"
        )

        event_id = (
            expedient_traceability_service
            .registrar_evento(
                expediente_id=100,
                cliente_id=1,
                tipo_evento="PRUEBA",
                titulo="PRUEBA",
                conn=self.conn,
            )
        )

        self.assertGreater(
            event_id,
            0,
        )

        inside = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM expediente_eventos
            """
        ).fetchone()[0]

        self.assertEqual(
            inside,
            1,
        )

        self.conn.rollback()

        outside = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM expediente_eventos
            """
        ).fetchone()[0]

        self.assertEqual(
            outside,
            0,
        )

    def test_justificante_and_event_rollback_together(
        self,
    ):
        self.conn.execute(
            "BEGIN IMMEDIATE"
        )

        with patch.object(
            expedient_traceability_service,
            "ensure_admin_document_metadata_schema",
            return_value=None,
        ):
            justificante_id = (
                expedient_traceability_service
                .create_justificante(
                    {
                        "expediente_id": 100,
                        "archivo_nombre":
                            "resolucion.pdf",
                        "archivo_ruta":
                            "C:/TEST/resolucion.pdf",
                        "tipo_justificante":
                            "RESOLUCION_FAVORABLE",
                        "metadata_documento": {
                            "fecha_resolucion":
                                "2026-02-01",
                        },
                    },
                    conn=self.conn,
                )
            )

        self.assertGreater(
            justificante_id,
            0,
        )

        justificantes = (
            self.conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_justificantes
                """
            ).fetchone()[0]
        )

        eventos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM expediente_eventos
            """
        ).fetchone()[0]

        self.assertEqual(
            justificantes,
            1,
        )

        self.assertEqual(
            eventos,
            1,
        )

        self.conn.rollback()

        justificantes = (
            self.conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_justificantes
                """
            ).fetchone()[0]
        )

        eventos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM expediente_eventos
            """
        ).fetchone()[0]

        self.assertEqual(
            justificantes,
            0,
        )

        self.assertEqual(
            eventos,
            0,
        )


if __name__ == "__main__":
    unittest.main()

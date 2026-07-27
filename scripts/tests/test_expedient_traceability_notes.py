import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    expedient_traceability_service as service,
)


class ExpedientTraceabilityNotesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "notes.db"

        connection = sqlite3.connect(self.db_path)

        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id)
            );

            CREATE TABLE expediente_eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                fecha_evento TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO clientes (id)
            VALUES (1);

            INSERT INTO expedientes (
                id,
                cliente_id
            )
            VALUES (
                10,
                1
            );
            """
        )

        connection.commit()
        connection.close()

        def test_connect():
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute(
                "PRAGMA foreign_keys = ON"
            )
            return connection

        self.connect_patch = patch.object(
            service,
            "_connect",
            test_connect,
        )
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test_create_and_read_note(self):
        note_id = service.create_expedient_note(
            expediente_id=10,
            titulo="Estrategia inicial",
            contenido="Revisar arraigo y documentación.",
            categoria="JURIDICA",
            autor="Nacho",
        )

        self.assertGreater(note_id, 0)

        notes = service.get_expedient_notes(10)

        self.assertEqual(len(notes), 1)
        self.assertEqual(
            notes[0]["titulo"],
            "Estrategia inicial",
        )
        self.assertEqual(
            notes[0]["categoria"],
            "JURIDICA",
        )

    def test_archive_note(self):
        note_id = service.create_expedient_note(
            expediente_id=10,
            titulo="Incidencia",
            contenido="Documento pendiente.",
        )

        service.archive_expedient_note(note_id)

        self.assertEqual(
            service.get_expedient_notes(10),
            [],
        )


if __name__ == "__main__":
    unittest.main()

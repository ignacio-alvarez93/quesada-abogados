"""WO-DV30-02: notas del visor documental en «Notas del expediente».

Solo SQLite temporal. La base operativa se redirige a una ruta que nunca
debe aparecer. Las notas documentales siguen residiendo únicamente en
document_viewer_notes; la pestaña Notas es una proyección de lectura.
"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.repositories import document_viewer_notes_repository as repository
from backend.services import expedient_traceability_service as service
from database import connection as db_connection


BASE_SQL = """
CREATE TABLE clientes (id INTEGER PRIMARY KEY);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id)
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
    fecha_evento TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE document_inbox_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    expedient_id INTEGER
);
INSERT INTO clientes (id) VALUES (1);
INSERT INTO expedientes (id, cliente_id) VALUES (10, 1), (20, 1);
"""

SHA_A = "a" * 64
SHA_B = "b" * 64


class ExpedientDocumentNotesTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db_path = self.root / "crm.db"

        # Cualquier acceso a la base operativa crearía este fichero.
        self.operational = self.root / "operational.db"
        for target, name in ((db_connection, "DB_PATH"), (service, "DB_PATH")):
            patcher = patch.object(target, name, self.operational)
            patcher.start()
            self.addCleanup(patcher.stop)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(BASE_SQL)
            conn.executescript(repository.MIGRATION_PATH.read_text(encoding="utf-8"))
            conn.row_factory = sqlite3.Row
            service.ensure_expedient_notes_schema(conn)
            conn.commit()

        self.connections = []

        def test_connect():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self.connections.append(conn)
            return conn

        patcher = patch.object(service, "_connect", test_connect)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.addCleanup(
            lambda: self.assertFalse(
                self.operational.exists(),
                "Se ha abierto la base operativa",
            )
        )

    # ------------------------------------------------------------ helpers

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(statement, params)
            conn.commit()
            return cursor.lastrowid

    def inbox_item(self, filename, expedient_id=None):
        return self.sql(
            "INSERT INTO document_inbox_items (original_filename, stored_path, expedient_id) "
            "VALUES (?, ?, ?)",
            (filename, str(self.root / "inbox" / "originals" / filename), expedient_id),
        )

    def note(self, request_id, *, body="Revisar firma", kind="expedient", expediente_id=10,
             relative_path="Identidad/Pasaporte.pdf", inbox_item_id=None, sha=SHA_A,
             author_id=1, author="ana", created_at="2026-11-10T09:00:00+00:00"):
        if kind == "inbox":
            ref = f"inbox:{inbox_item_id}"
            expediente_id = None
            relative_path = None
        else:
            ref = f"expedient:{expediente_id}:{relative_path.lower()}"
        row, created = repository.insert_note({
            "document_kind": kind,
            "document_ref": ref,
            "inbox_item_id": inbox_item_id,
            "expediente_id": expediente_id,
            "relative_path": relative_path,
            "content_sha256": sha,
            "size_bytes": 1234,
            "body": body,
            "author_user_id": author_id,
            "author_username": author,
            "request_id": request_id,
            "created_at": created_at,
        }, db_path=self.db_path)
        return row, created

    def document_notes(self, expediente_id):
        return [
            note for note in service.get_expedient_notes(expediente_id)
            if note.get("origen") == "DOCUMENTO"
        ]

    def schema(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()

    # ------------------------------------------------------------ tests

    def test_expedient_document_note_is_shown_in_its_expedient(self):
        self.note("req-expedient-0001", body="Pasaporte caducado:\nrenovar antes de presentar.")

        notes = self.document_notes(10)

        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note["titulo"], "Documento: Pasaporte.pdf")
        self.assertEqual(note["contenido"], "Pasaporte caducado:\nrenovar antes de presentar.")
        self.assertEqual(note["autor"], "ana")
        self.assertEqual(note["categoria"], "DOCUMENTO")
        self.assertEqual(note["created_at"], "2026-11-10 09:00:00")
        self.assertEqual(note["documento_ruta_relativa"], "Identidad/Pasaporte.pdf")
        self.assertEqual(note["revision_sha256"], SHA_A)
        self.assertIn(SHA_A[:12], note["revision_etiqueta"])
        self.assertEqual(note["request_id"], "req-expedient-0001")
        self.assertEqual(self.document_notes(20), [])

    def test_linked_inbox_note_is_shown_and_follows_current_link(self):
        item_id = self.inbox_item("Contrato.pdf", expedient_id=10)
        self.note("req-inbox-0001", kind="inbox", inbox_item_id=item_id, body="Falta página 3")

        notes = self.document_notes(10)
        self.assertEqual([n["titulo"] for n in notes], ["Documento: Contrato.pdf"])
        self.assertEqual(notes[0]["documento_tipo"], "inbox")
        self.assertEqual(notes[0]["inbox_item_id"], item_id)
        self.assertEqual(self.document_notes(20), [])

        self.sql("UPDATE document_inbox_items SET expedient_id = 20 WHERE id = ?", (item_id,))
        self.assertEqual(self.document_notes(10), [])
        self.assertEqual([n["contenido"] for n in self.document_notes(20)], ["Falta página 3"])

        self.sql("UPDATE document_inbox_items SET expedient_id = NULL WHERE id = ?", (item_id,))
        self.assertEqual(self.document_notes(10), [])
        self.assertEqual(self.document_notes(20), [])

    def test_unlinked_inbox_note_is_not_shown_anywhere(self):
        item_id = self.inbox_item("Sin_vincular.pdf")
        self.note("req-inbox-unlinked", kind="inbox", inbox_item_id=item_id)
        # Mismo nombre que un documento del expediente: no se vincula por nombre.
        self.inbox_item("Pasaporte.pdf")

        self.assertEqual(self.document_notes(10), [])
        self.assertEqual(self.document_notes(20), [])

    def test_other_expedient_notes_are_not_exposed(self):
        self.note("req-exp-20-00001", expediente_id=20, body="Solo del 20")
        # Fila incoherente (document_ref de otro expediente): nunca se proyecta.
        self.sql(
            "INSERT INTO document_viewer_notes (document_kind, document_ref, expediente_id, "
            "relative_path, content_sha256, size_bytes, body, author_user_id, author_username, "
            "request_id, created_at) VALUES ('expedient', 'expedient:20:x.pdf', 10, 'x.pdf', ?, 1, "
            "'Incoherente', 1, 'ana', 'req-mismatch-0001', '2026-11-10T10:00:00+00:00')",
            (SHA_A,),
        )

        self.assertEqual(self.document_notes(10), [])
        self.assertEqual([n["contenido"] for n in self.document_notes(20)], ["Solo del 20"])

    def test_archived_document_notes_are_not_shown(self):
        self.note("req-archived-0001")
        self.sql("UPDATE document_viewer_notes SET status = 'archived'")

        self.assertEqual(self.document_notes(10), [])

    def test_manual_notes_remain_and_order_is_chronological(self):
        manual_id = service.create_expedient_note(
            expediente_id=10,
            titulo="Estrategia",
            contenido="Arraigo social.",
            categoria="ESTRATEGIA",
            autor="Nacho",
        )
        self.sql(
            "UPDATE expediente_notas SET created_at = '2026-11-10 10:00:00' WHERE id = ?",
            (manual_id,),
        )
        self.note("req-order-early1", body="Anterior", created_at="2026-11-10T09:00:00+00:00")
        self.note("req-order-later1", body="Posterior", created_at="2026-11-10T11:00:00+00:00")

        notes = service.get_expedient_notes(10)

        self.assertEqual(
            [(n["origen"], n["contenido"]) for n in notes],
            [
                ("DOCUMENTO", "Posterior"),
                ("MANUAL", "Arraigo social."),
                ("DOCUMENTO", "Anterior"),
            ],
        )
        manual = notes[1]
        self.assertEqual(manual["id"], manual_id)
        self.assertEqual(manual["titulo"], "Estrategia")
        self.assertEqual(manual["categoria"], "ESTRATEGIA")
        self.assertEqual(manual["autor"], "Nacho")

        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM expediente_notas").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM document_viewer_notes").fetchone()[0], 2)

    def test_repeated_reads_and_retries_do_not_duplicate(self):
        first, created_first = self.note("req-retry-000001", body="Una sola vez")
        again, created_again = self.note("req-retry-000001", body="Una sola vez")

        self.assertTrue(created_first)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], again["id"])

        first_read = service.get_expedient_notes(10)
        second_read = service.get_expedient_notes(10)

        self.assertEqual(first_read, second_read)
        self.assertEqual(len(first_read), 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM expediente_notas").fetchone()[0], 0)

    def test_revisions_and_authors_are_preserved(self):
        self.note("req-rev-a-000001", body="Sobre la versión A", sha=SHA_A,
                  created_at="2026-11-10T09:00:00+00:00")
        self.note("req-rev-b-000001", body="Sobre la versión B", sha=SHA_B, author_id=2,
                  author="luis", created_at="2026-11-11T09:00:00+00:00")

        notes = self.document_notes(10)

        self.assertEqual(
            [(n["contenido"], n["autor"], n["revision_sha256"]) for n in notes],
            [("Sobre la versión B", "luis", SHA_B), ("Sobre la versión A", "ana", SHA_A)],
        )
        self.assertNotEqual(notes[0]["revision_etiqueta"], notes[1]["revision_etiqueta"])
        self.assertEqual({n["titulo"] for n in notes}, {"Documento: Pasaporte.pdf"})

    def test_projection_does_not_publish_absolute_paths(self):
        item_id = self.inbox_item("Contrato.pdf", expedient_id=10)
        self.note("req-paths-inbox1", kind="inbox", inbox_item_id=item_id)
        self.note("req-paths-exp001")

        notes = service.get_expedient_notes(10)

        self.assertEqual(len(notes), 2)
        for note in notes:
            self.assertNotIn("stored_path", note)
            for value in note.values():
                text = str(value or "")
                self.assertNotIn(str(self.root), text)
                self.assertFalse(Path(text).is_absolute() and len(text) > 3, text)

    def test_reading_notes_does_no_ddl_and_writes_nothing(self):
        self.note("req-no-ddl-00001")
        before = self.schema()
        with closing(sqlite3.connect(self.db_path)) as conn:
            changes_before = conn.execute("SELECT COUNT(*) FROM document_viewer_notes").fetchone()[0]

        service.get_expedient_notes(10)
        service.get_expedient_notes(20)

        self.assertEqual(self.schema(), before)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM document_viewer_notes").fetchone()[0],
                changes_before,
            )

    def test_missing_document_table_keeps_manual_notes_and_creates_nothing(self):
        self.sql("DROP TABLE document_viewer_notes")
        service.create_expedient_note(expediente_id=10, titulo="Antigua", contenido="Sigue aquí.")
        before = self.schema()

        notes = service.get_expedient_notes(10)

        self.assertEqual([n["titulo"] for n in notes], ["Antigua"])
        self.assertEqual(self.schema(), before)
        self.assertNotIn("document_viewer_notes", {row[1] for row in before})

    def test_repository_reuses_caller_connection_without_closing_it(self):
        self.note("req-conn-000001")
        conn = sqlite3.connect(self.db_path)
        self.addCleanup(conn.close)

        rows = repository.list_expedient_linked_notes(10, conn=conn)

        self.assertEqual([row["request_id"] for row in rows], ["req-conn-000001"])
        self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)

    def test_get_expedient_notes_uses_single_injected_connection(self):
        self.note("req-single-conn1")
        self.connections.clear()

        service.get_expedient_notes(10)

        self.assertEqual(len(self.connections), 1)


if __name__ == "__main__":
    unittest.main()

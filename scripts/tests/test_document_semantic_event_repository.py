import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    document_semantic_event_repository
    as repository,
)


class DocumentSemanticEventRepositoryTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "semantic_repository.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )
        conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id)
            );

            CREATE TABLE box_watch_scan_runs (
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE box_watch_scan_jobs (
                id INTEGER PRIMARY KEY
            );

            INSERT INTO clientes (id)
            VALUES (200);

            INSERT INTO expedientes (
                id,
                cliente_id
            )
            VALUES (100, 200);

            INSERT INTO box_watch_scan_runs (id)
            VALUES (10);

            INSERT INTO box_watch_scan_jobs (id)
            VALUES (20);
            """
        )
        conn.commit()
        conn.close()

        repository.ensure_schema(
            db_path=self.db_path
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def snapshot(
        self,
        fingerprint="fp-1",
        state="PENDIENTE_DOCUMENTACION",
    ):
        return {
            "expediente_id": 100,
            "cliente_id": 200,
            "estado_documental": state,
            "estado_procesal": None,
            "estado_combinado": state,
            "semantico_aplicable": True,
            "motor_activo": "LEGACY",
            "grupos_bloqueantes": 1,
            "ambiguedades_rol": 0,
            "fingerprint": fingerprint,
            "diagnosis_json": (
                '{"estado":"%s"}' % state
            ),
        }

    def event(
        self,
        *,
        key="event-key-1",
        fingerprint="fp-1",
        event_type="INITIAL_SNAPSHOT",
    ):
        return {
            "expediente_id": 100,
            "cliente_id": 200,
            "event_type": event_type,
            "previous_document_state": None,
            "new_document_state": (
                "PENDIENTE_DOCUMENTACION"
            ),
            "previous_process_state": None,
            "new_process_state": None,
            "previous_fingerprint": None,
            "new_fingerprint": fingerprint,
            "idempotency_key": key,
        }

    def test_schema_is_idempotent(self):
        repository.ensure_schema(
            db_path=self.db_path
        )
        repository.ensure_schema(
            db_path=self.db_path
        )

        conn = sqlite3.connect(
            self.db_path
        )

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'document_semantic_snapshots',
                  'document_semantic_events'
              )
            """
        ).fetchone()[0]

        conn.close()

        self.assertEqual(total, 2)

    def test_missing_snapshot_returns_none(self):
        result = repository.get_snapshot(
            100,
            db_path=self.db_path,
        )

        self.assertIsNone(result)

    def test_snapshot_is_inserted(self):
        inserted = repository.upsert_snapshot(
            self.snapshot(),
            db_path=self.db_path,
        )

        self.assertEqual(
            inserted["fingerprint"],
            "fp-1",
        )
        self.assertEqual(
            inserted["estado_documental"],
            "PENDIENTE_DOCUMENTACION",
        )

    def test_snapshot_is_updated_not_duplicated(self):
        repository.upsert_snapshot(
            self.snapshot(),
            db_path=self.db_path,
        )
        repository.upsert_snapshot(
            self.snapshot(
                fingerprint="fp-2",
                state="COMPLETO_SIN_PRESENTAR",
            ),
            db_path=self.db_path,
        )

        conn = sqlite3.connect(
            self.db_path
        )
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT *
            FROM document_semantic_snapshots
            WHERE expediente_id = 100
            """
        ).fetchall()

        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["fingerprint"],
            "fp-2",
        )
        self.assertEqual(
            rows[0]["estado_documental"],
            "COMPLETO_SIN_PRESENTAR",
        )

    def test_event_is_inserted(self):
        result = repository.insert_event(
            self.event(),
            db_path=self.db_path,
        )

        self.assertTrue(result["created"])
        self.assertEqual(
            result["event"]["event_type"],
            "INITIAL_SNAPSHOT",
        )

    def test_duplicate_event_is_ignored(self):
        first = repository.insert_event(
            self.event(),
            db_path=self.db_path,
        )
        second = repository.insert_event(
            self.event(),
            db_path=self.db_path,
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])

        events = repository.list_events(
            expediente_id=100,
            db_path=self.db_path,
        )

        self.assertEqual(len(events), 1)

    def test_source_scan_references_are_stored(self):
        result = repository.insert_event(
            self.event(),
            source_type="BOX_WATCH_SCAN",
            source_scan_run_id=10,
            source_scan_job_id=20,
            db_path=self.db_path,
        )

        stored = result["event"]

        self.assertEqual(
            stored["source_type"],
            "BOX_WATCH_SCAN",
        )
        self.assertEqual(
            stored["source_scan_run_id"],
            10,
        )
        self.assertEqual(
            stored["source_scan_job_id"],
            20,
        )

    def test_events_can_be_filtered(self):
        repository.insert_event(
            self.event(
                key="key-1",
                event_type="INITIAL_SNAPSHOT",
            ),
            db_path=self.db_path,
        )
        repository.insert_event(
            self.event(
                key="key-2",
                fingerprint="fp-2",
                event_type="DOCUMENT_COMPLETE",
            ),
            db_path=self.db_path,
        )

        events = repository.list_events(
            expediente_id=100,
            status="OPEN",
            db_path=self.db_path,
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events[0]["event_type"],
            "DOCUMENT_COMPLETE",
        )

    def test_event_can_be_resolved(self):
        inserted = repository.insert_event(
            self.event(),
            db_path=self.db_path,
        )

        event_id = inserted["event"]["id"]

        changed = repository.resolve_event(
            event_id,
            db_path=self.db_path,
        )
        changed_again = (
            repository.resolve_event(
                event_id,
                db_path=self.db_path,
            )
        )

        self.assertTrue(changed)
        self.assertFalse(changed_again)

        events = repository.list_events(
            expediente_id=100,
            status="RESOLVED",
            db_path=self.db_path,
        )

        self.assertEqual(len(events), 1)

    def test_foreign_keys_are_enforced(self):
        invalid = self.event()
        invalid["expediente_id"] = 999

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            repository.insert_event(
                invalid,
                db_path=self.db_path,
            )

    def test_external_transaction_is_respected(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        repository.upsert_snapshot(
            self.snapshot(),
            conn=conn,
        )
        repository.insert_event(
            self.event(),
            conn=conn,
        )

        conn.rollback()
        conn.close()

        snapshot = repository.get_snapshot(
            100,
            db_path=self.db_path,
        )
        events = repository.list_events(
            expediente_id=100,
            db_path=self.db_path,
        )

        self.assertIsNone(snapshot)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

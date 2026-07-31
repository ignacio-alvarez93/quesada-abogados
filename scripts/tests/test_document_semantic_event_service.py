import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from backend.services import (
    document_semantic_event_repository
    as repository,
)
from backend.services import (
    document_semantic_event_service
    as event_service,
)


def diagnosis(
    *,
    documentary_state="PENDIENTE_DOCUMENTACION",
    blocking=1,
    ambiguities=0,
):
    return {
        "expediente_id": 100,
        "expediente": {
            "cliente_id": 200,
        },
        "estado_sugerido": documentary_state,
        "motor_estado_activo": "LEGACY",
        "estado_documental_semantico": {
            "estado_documental": documentary_state,
            "aplicable": True,
        },
        "estado_procesal_detectado": {
            "estado_procesal": None,
            "detectado": False,
        },
        "decision_semantica": {
            "estado_sugerido": documentary_state,
        },
        "semantic_readiness": {
            "disponible": True,
            "grupos_bloqueantes": blocking,
            "opciones_ambiguas_por_rol": [],
            "grupos": [
                {
                    "codigo": "IDENTIDAD",
                    "estado": (
                        "CUMPLIDO"
                        if blocking == 0
                        else "PENDIENTE"
                    ),
                    "cumplido": blocking == 0,
                    "bloquea_completitud": (
                        blocking > 0
                    ),
                    "documentos_detectados": (
                        1 if blocking == 0 else 0
                    ),
                    "documentos_requeridos": 1,
                    "opciones_ambiguas_por_rol": (
                        ambiguities
                    ),
                }
            ],
        },
        "resumen_inferencia_roles": {
            "ambiguos": ambiguities,
        },
    }


class DocumentSemanticEventServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "semantic_event_service.db"
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
                cliente_id INTEGER
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

    def test_initial_snapshot_creates_no_event_by_default(self):
        result = event_service.process_diagnosis(
            diagnosis(),
            db_path=self.db_path,
        )

        self.assertTrue(result["changed"])
        self.assertTrue(
            result["event_skipped"]
        )
        self.assertIsNone(
            result["event_result"]
        )

        events = repository.list_events(
            expediente_id=100,
            db_path=self.db_path,
        )

        self.assertEqual(events, [])

    def test_initial_event_can_be_requested(self):
        result = event_service.process_diagnosis(
            diagnosis(),
            create_initial_event=True,
            db_path=self.db_path,
        )

        self.assertTrue(
            result["event_result"]["created"]
        )
        self.assertEqual(
            result["event_result"]["event"][
                "event_type"
            ],
            "INITIAL_SNAPSHOT",
        )

    def test_identical_diagnosis_creates_no_event(self):
        event_service.process_diagnosis(
            diagnosis(),
            db_path=self.db_path,
        )

        result = event_service.process_diagnosis(
            diagnosis(),
            db_path=self.db_path,
        )

        self.assertFalse(result["changed"])
        self.assertIsNone(
            result["event_result"]
        )

    def test_pending_to_complete_creates_event(self):
        event_service.process_diagnosis(
            diagnosis(),
            db_path=self.db_path,
        )

        result = event_service.process_diagnosis(
            diagnosis(
                documentary_state=(
                    "COMPLETO_SIN_PRESENTAR"
                ),
                blocking=0,
            ),
            db_path=self.db_path,
        )

        event = result["event_result"]["event"]

        self.assertEqual(
            event["event_type"],
            "DOCUMENT_COMPLETE",
        )
        self.assertEqual(
            event["severity"],
            "INFO",
        )

    def test_complete_to_pending_is_high_severity(self):
        event_service.process_diagnosis(
            diagnosis(
                documentary_state=(
                    "COMPLETO_SIN_PRESENTAR"
                ),
                blocking=0,
            ),
            db_path=self.db_path,
        )

        result = event_service.process_diagnosis(
            diagnosis(
                documentary_state=(
                    "PENDIENTE_DOCUMENTACION"
                ),
                blocking=1,
            ),
            db_path=self.db_path,
        )

        event = result["event_result"]["event"]

        self.assertEqual(
            event["event_type"],
            "DOCUMENT_INCOMPLETE",
        )
        self.assertEqual(
            event["severity"],
            "HIGH",
        )

    def test_scan_source_is_propagated(self):
        event_service.process_diagnosis(
            diagnosis(),
            source_type="BOX_WATCH_SCAN",
            source_scan_run_id=10,
            source_scan_job_id=20,
            db_path=self.db_path,
        )

        result = event_service.process_diagnosis(
            diagnosis(
                documentary_state=(
                    "COMPLETO_SIN_PRESENTAR"
                ),
                blocking=0,
            ),
            source_type="BOX_WATCH_SCAN",
            source_scan_run_id=10,
            source_scan_job_id=20,
            db_path=self.db_path,
        )

        event = result["event_result"]["event"]
        snapshot = result["current_snapshot"]

        self.assertEqual(
            event["source_type"],
            "BOX_WATCH_SCAN",
        )
        self.assertEqual(
            event["source_scan_run_id"],
            10,
        )
        self.assertEqual(
            snapshot["source_scan_job_id"],
            20,
        )

    def test_internal_transaction_rolls_back_event_if_snapshot_fails(self):
        event_service.process_diagnosis(
            diagnosis(),
            db_path=self.db_path,
        )

        original_upsert = (
            repository.upsert_snapshot
        )

        def fail_upsert(*args, **kwargs):
            snapshot = args[0]

            if (
                snapshot.get(
                    "estado_documental"
                )
                == "COMPLETO_SIN_PRESENTAR"
            ):
                raise RuntimeError(
                    "Fallo simulado al guardar snapshot"
                )

            return original_upsert(
                *args,
                **kwargs,
            )

        with patch.object(
            repository,
            "upsert_snapshot",
            side_effect=fail_upsert,
        ):
            with self.assertRaises(
                RuntimeError
            ):
                event_service.process_diagnosis(
                    diagnosis(
                        documentary_state=(
                            "COMPLETO_SIN_PRESENTAR"
                        ),
                        blocking=0,
                    ),
                    db_path=self.db_path,
                )

        snapshot = repository.get_snapshot(
            100,
            db_path=self.db_path,
        )
        events = repository.list_events(
            expediente_id=100,
            db_path=self.db_path,
        )

        self.assertEqual(
            snapshot["estado_documental"],
            "PENDIENTE_DOCUMENTACION",
        )
        self.assertEqual(events, [])

    def test_external_transaction_can_be_rolled_back(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        event_service.process_diagnosis(
            diagnosis(),
            create_initial_event=True,
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

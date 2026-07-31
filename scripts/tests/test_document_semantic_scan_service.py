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
    document_semantic_scan_service
    as scan_service,
)


def diagnosis(
    expediente_id,
    *,
    state="PENDIENTE_DOCUMENTACION",
    blocking=1,
):
    return {
        "expediente_id": expediente_id,
        "expediente": {
            "cliente_id": (
                200 + expediente_id
            ),
        },
        "estado_sugerido": state,
        "motor_estado_activo": "LEGACY",
        "estado_documental_semantico": {
            "estado_documental": state,
            "aplicable": True,
        },
        "estado_procesal_detectado": {
            "estado_procesal": None,
            "detectado": False,
        },
        "decision_semantica": {
            "estado_sugerido": state,
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
                    "cumplido": (
                        blocking == 0
                    ),
                    "bloquea_completitud": (
                        blocking > 0
                    ),
                    "documentos_detectados": (
                        1 if blocking == 0 else 0
                    ),
                    "documentos_requeridos": 1,
                    "opciones_ambiguas_por_rol": 0,
                }
            ],
        },
        "resumen_inferencia_roles": {
            "ambiguos": 0,
        },
    }


class DocumentSemanticScanServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "semantic_scan.db"
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

            CREATE TABLE box_watch_items (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER,
                last_seen_scan_id INTEGER
            );

            CREATE TABLE box_watch_folders (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER,
                last_seen_scan_id INTEGER
            );

            INSERT INTO clientes (id)
            VALUES
                (201),
                (202),
                (203);

            INSERT INTO expedientes (
                id,
                cliente_id
            )
            VALUES
                (1, 201),
                (2, 202),
                (3, 203);

            INSERT INTO box_watch_scan_runs (id)
            VALUES
                (10),
                (20),
                (30);

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

    def test_extracts_run_ids_from_normal_results(self):
        result = (
            scan_service
            .extract_scan_run_ids(
                [
                    {
                        "run_id": 10,
                        "scan_mode": "NORMAL",
                    },
                    {
                        "run_id": 20,
                        "scan_mode": "NORMAL",
                    },
                ]
            )
        )

        self.assertEqual(
            result,
            [10, 20],
        )

    def test_extracts_run_ids_from_massive_results(self):
        result = (
            scan_service
            .extract_scan_run_ids(
                [
                    {
                        "scan_mode": (
                            "BATCH_MASSIVE_ROOT"
                        ),
                        "batches": [
                            {
                                "results": [
                                    {
                                        "run_id": 10,
                                        "batch_status": "OK",
                                    },
                                    {
                                        "run_id": 20,
                                        "batch_status": "OK",
                                    },
                                ]
                            },
                            {
                                "results": [
                                    {
                                        "run_id": 30,
                                        "batch_status": "OK",
                                    }
                                ]
                            },
                        ],
                    }
                ]
            )
        )

        self.assertEqual(
            result,
            [10, 20, 30],
        )

    def test_scan_run_ids_are_deduplicated(self):
        result = (
            scan_service
            .extract_scan_run_ids(
                {
                    "run_id": 10,
                    "results": [
                        {"run_id": 10},
                        {"run_id": "20"},
                        {"run_id": None},
                        {"run_id": "invalid"},
                    ],
                }
            )
        )

        self.assertEqual(
            result,
            [10, 20],
        )

    def test_disabled_result_processing_does_not_create_schema(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            DROP TABLE document_semantic_events
            """
        )
        conn.execute(
            """
            DROP TABLE document_semantic_snapshots
            """
        )
        conn.commit()
        conn.close()

        result = (
            scan_service
            .process_box_scan_results(
                [{"run_id": 10}],
                environ={},
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            result["enabled"]
        )

        conn = sqlite3.connect(
            self.db_path
        )
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        conn.close()

        self.assertNotIn(
            "document_semantic_snapshots",
            tables,
        )
        self.assertNotIn(
            "document_semantic_events",
            tables,
        )

    def test_disabled_result_processing_does_not_read_runs(self):
        result = (
            scan_service
            .process_box_scan_results(
                [
                    {"run_id": 10},
                    {"run_id": 20},
                ],
                source_scan_job_id=99,
                environ={},
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            result["enabled"]
        )
        self.assertEqual(
            result["scan_runs_detected"],
            0,
        )
        self.assertEqual(
            result["processed"],
            0,
        )

    def test_enabled_result_processing_ensures_schema(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            DROP TABLE document_semantic_events
            """
        )
        conn.execute(
            """
            DROP TABLE document_semantic_snapshots
            """
        )
        conn.commit()
        conn.close()

        result = (
            scan_service
            .process_box_scan_results(
                [],
                environ={
                    (
                        "DOCUMENT_SEMANTIC_"
                        "SCAN_EVENTS_ENABLED"
                    ): "1"
                },
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["enabled"]
        )

        conn = sqlite3.connect(
            self.db_path
        )
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        conn.close()

        self.assertIn(
            "document_semantic_snapshots",
            tables,
        )
        self.assertIn(
            "document_semantic_events",
            tables,
        )

    def test_enabled_result_processing_handles_normal_and_massive_runs(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.executescript(
            """
            INSERT INTO box_watch_items (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES
                (1, 1, 10),
                (2, 2, 20);

            INSERT INTO box_watch_folders (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES
                (1, 3, 30);
            """
        )
        conn.commit()
        conn.close()

        results = [
            {
                "run_id": 10,
                "scan_mode": "NORMAL",
            },
            {
                "scan_mode": (
                    "BATCH_MASSIVE_ROOT"
                ),
                "batches": [
                    {
                        "results": [
                            {"run_id": 20},
                            {"run_id": 30},
                        ]
                    }
                ],
            },
        ]

        result = (
            scan_service
            .process_box_scan_results(
                results,
                source_scan_job_id=20,
                diagnosis_provider=(
                    lambda expediente_id:
                    diagnosis(expediente_id)
                ),
                environ={
                    (
                        "DOCUMENT_SEMANTIC_"
                        "SCAN_EVENTS_ENABLED"
                    ): "1"
                },
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["enabled"]
        )
        self.assertEqual(
            result["scan_runs_detected"],
            3,
        )
        self.assertEqual(
            result["scan_runs_processed"],
            3,
        )
        self.assertEqual(
            result["affected_expedients"],
            3,
        )
        self.assertEqual(
            result["processed"],
            3,
        )

    def test_failure_of_one_run_does_not_stop_other_runs(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            INSERT INTO box_watch_items (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES (?, ?, ?)
            """,
            (1, 1, 10),
        )
        conn.commit()
        conn.close()

        original = (
            scan_service
            .process_box_scan_run
        )

        def process_run(
            run_id,
            *args,
            **kwargs,
        ):
            if int(run_id) == 20:
                raise RuntimeError(
                    "Fallo semántico simulado"
                )

            return original(
                run_id,
                *args,
                **kwargs,
            )

        with patch.object(
            scan_service,
            "process_box_scan_run",
            side_effect=process_run,
        ):
            result = (
                scan_service
                .process_box_scan_results(
                    [
                        {"run_id": 10},
                        {"run_id": 20},
                    ],
                    diagnosis_provider=(
                        lambda expediente_id:
                        diagnosis(expediente_id)
                    ),
                    environ={
                        (
                            "DOCUMENT_SEMANTIC_"
                            "SCAN_EVENTS_ENABLED"
                        ): "1"
                    },
                    db_path=self.db_path,
                )
            )

        self.assertEqual(
            result["scan_runs_detected"],
            2,
        )
        self.assertEqual(
            result["scan_runs_processed"],
            1,
        )
        self.assertEqual(
            result["errors"],
            1,
        )
        self.assertTrue(
            result["run_results"][0]["ok"]
        )
        self.assertFalse(
            result["run_results"][1]["ok"]
        )

    def test_semantic_scan_events_are_disabled_by_default(self):
        self.assertFalse(
            scan_service
            .semantic_scan_events_enabled({})
        )

    def test_semantic_scan_events_accept_enabled_values(self):
        for value in [
            "1",
            "true",
            "TRUE",
            "yes",
            "on",
        ]:
            with self.subTest(value=value):
                self.assertTrue(
                    scan_service
                    .semantic_scan_events_enabled(
                        {
                            (
                                "DOCUMENT_SEMANTIC_"
                                "SCAN_EVENTS_ENABLED"
                            ): value
                        }
                    )
                )

    def test_disabled_box_scan_run_does_nothing(self):
        result = (
            scan_service
            .process_box_scan_run(
                10,
                environ={},
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            result["enabled"]
        )
        self.assertEqual(
            result["processed"],
            0,
        )

        snapshot = repository.get_snapshot(
            1,
            db_path=self.db_path,
        )

        self.assertIsNone(snapshot)

    def test_enabled_box_scan_run_processes_affected_expedients(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            INSERT INTO box_watch_items (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES (?, ?, ?)
            """,
            (1, 1, 10),
        )
        conn.commit()
        conn.close()

        result = (
            scan_service
            .process_box_scan_run(
                10,
                diagnosis_provider=(
                    lambda expediente_id:
                    diagnosis(expediente_id)
                ),
                environ={
                    (
                        "DOCUMENT_SEMANTIC_"
                        "SCAN_EVENTS_ENABLED"
                    ): "1"
                },
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["enabled"]
        )
        self.assertEqual(
            result["affected_expedients"],
            1,
        )
        self.assertEqual(
            result["processed"],
            1,
        )

        snapshot = repository.get_snapshot(
            1,
            db_path=self.db_path,
        )

        self.assertIsNotNone(snapshot)

    def test_affected_ids_are_loaded_from_items_and_folders(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.executescript(
            """
            INSERT INTO box_watch_items (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES
                (1, 1, 10),
                (2, 2, 10),
                (3, 2, 10),
                (4, 3, 99),
                (5, NULL, 10);

            INSERT INTO box_watch_folders (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES
                (1, 2, 10),
                (2, 3, 10),
                (3, 1, 99);
            """
        )
        conn.commit()
        conn.close()

        result = (
            scan_service
            .get_affected_expedient_ids(
                10,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result,
            [1, 2, 3],
        )

    def test_invalid_scan_run_returns_empty_list(self):
        self.assertEqual(
            scan_service
            .get_affected_expedient_ids(
                None,
                db_path=self.db_path,
            ),
            [],
        )
        self.assertEqual(
            scan_service
            .get_affected_expedient_ids(
                "invalid",
                db_path=self.db_path,
            ),
            [],
        )

    def test_other_scan_runs_are_excluded(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            INSERT INTO box_watch_items (
                id,
                expediente_id,
                last_seen_scan_id
            )
            VALUES (?, ?, ?)
            """,
            (1, 1, 99),
        )
        conn.commit()
        conn.close()

        result = (
            scan_service
            .get_affected_expedient_ids(
                10,
                db_path=self.db_path,
            )
        )

        self.assertEqual(result, [])

    def test_ids_are_normalized_and_deduplicated(self):
        calls = []

        def provider(expediente_id):
            calls.append(expediente_id)
            return diagnosis(expediente_id)

        result = (
            scan_service
            .process_scanned_expedients(
                [1, "1", 2, None, "x", 0],
                diagnosis_provider=provider,
                db_path=self.db_path,
            )
        )

        self.assertEqual(calls, [1, 2])
        self.assertEqual(
            result["unique_expedients"],
            2,
        )
        self.assertEqual(
            result["processed"],
            2,
        )

    def test_generator_input_is_materialized_once(self):
        calls = []

        def provider(expediente_id):
            calls.append(expediente_id)
            return diagnosis(expediente_id)

        values = (
            value
            for value in [1, 1, 2]
        )

        result = (
            scan_service
            .process_scanned_expedients(
                values,
                diagnosis_provider=provider,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["requested"],
            3,
        )
        self.assertEqual(
            result["unique_expedients"],
            2,
        )
        self.assertEqual(calls, [1, 2])

    def test_initial_scan_creates_snapshots_not_events(self):
        result = (
            scan_service
            .process_scanned_expedients(
                [1, 2],
                diagnosis_provider=(
                    lambda expediente_id:
                    diagnosis(expediente_id)
                ),
                source_scan_run_id=10,
                source_scan_job_id=20,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["processed"],
            2,
        )
        self.assertEqual(
            result["events_created"],
            0,
        )
        self.assertEqual(
            result["events_skipped"],
            2,
        )

        events = repository.list_events(
            db_path=self.db_path,
        )

        self.assertEqual(events, [])

    def test_second_identical_scan_is_unchanged(self):
        provider = (
            lambda expediente_id:
            diagnosis(expediente_id)
        )

        scan_service.process_scanned_expedients(
            [1],
            diagnosis_provider=provider,
            db_path=self.db_path,
        )

        result = (
            scan_service
            .process_scanned_expedients(
                [1],
                diagnosis_provider=provider,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["unchanged"],
            1,
        )
        self.assertEqual(
            result["changed"],
            0,
        )

    def test_document_transition_creates_event(self):
        scan_service.process_scanned_expedients(
            [1],
            diagnosis_provider=(
                lambda expediente_id:
                diagnosis(expediente_id)
            ),
            db_path=self.db_path,
        )

        result = (
            scan_service
            .process_scanned_expedients(
                [1],
                diagnosis_provider=(
                    lambda expediente_id:
                    diagnosis(
                        expediente_id,
                        state=(
                            "COMPLETO_SIN_PRESENTAR"
                        ),
                        blocking=0,
                    )
                ),
                source_scan_run_id=10,
                source_scan_job_id=20,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["events_created"],
            1,
        )
        self.assertEqual(
            result["results"][0][
                "event_type"
            ],
            "DOCUMENT_COMPLETE",
        )

    def test_failure_of_one_expedient_does_not_stop_others(self):
        def provider(expediente_id):
            if expediente_id == 2:
                raise RuntimeError(
                    "Fallo simulado"
                )

            return diagnosis(expediente_id)

        result = (
            scan_service
            .process_scanned_expedients(
                [1, 2, 3],
                diagnosis_provider=provider,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["processed"],
            2,
        )
        self.assertEqual(
            result["errors"],
            1,
        )
        self.assertTrue(
            result["results"][0]["ok"]
        )
        self.assertFalse(
            result["results"][1]["ok"]
        )
        self.assertTrue(
            result["results"][2]["ok"]
        )

    def test_failed_expedient_rolls_back_only_its_own_writes(self):
        scan_service.process_scanned_expedients(
            [1, 2],
            diagnosis_provider=(
                lambda expediente_id:
                diagnosis(expediente_id)
            ),
            db_path=self.db_path,
        )

        original_upsert = (
            repository.upsert_snapshot
        )

        def fail_second_snapshot(
            snapshot,
            *args,
            **kwargs,
        ):
            if (
                snapshot.get("expediente_id")
                == 2
                and snapshot.get(
                    "estado_documental"
                )
                == "COMPLETO_SIN_PRESENTAR"
            ):
                raise RuntimeError(
                    "Fallo simulado expediente 2"
                )

            return original_upsert(
                snapshot,
                *args,
                **kwargs,
            )

        with patch.object(
            repository,
            "upsert_snapshot",
            side_effect=fail_second_snapshot,
        ):
            result = (
                scan_service
                .process_scanned_expedients(
                    [1, 2, 3],
                    diagnosis_provider=(
                        lambda expediente_id:
                        diagnosis(
                            expediente_id,
                            state=(
                                "COMPLETO_SIN_PRESENTAR"
                            ),
                            blocking=0,
                        )
                    ),
                    db_path=self.db_path,
                )
            )

        self.assertEqual(
            result["processed"],
            2,
        )
        self.assertEqual(
            result["errors"],
            1,
        )

        events_1 = repository.list_events(
            expediente_id=1,
            db_path=self.db_path,
        )
        events_2 = repository.list_events(
            expediente_id=2,
            db_path=self.db_path,
        )
        events_3 = repository.list_events(
            expediente_id=3,
            db_path=self.db_path,
        )

        snapshot_2 = repository.get_snapshot(
            2,
            db_path=self.db_path,
        )
        snapshot_3 = repository.get_snapshot(
            3,
            db_path=self.db_path,
        )

        self.assertEqual(
            len(events_1),
            1,
        )
        self.assertEqual(
            events_1[0]["event_type"],
            "DOCUMENT_COMPLETE",
        )

        self.assertEqual(
            events_2,
            [],
        )
        self.assertEqual(
            snapshot_2["estado_documental"],
            "PENDIENTE_DOCUMENTACION",
        )

        self.assertEqual(
            events_3,
            [],
        )
        self.assertIsNotNone(snapshot_3)
        self.assertEqual(
            snapshot_3["estado_documental"],
            "COMPLETO_SIN_PRESENTAR",
        )

    def test_scan_references_reach_snapshot_and_event(self):
        scan_service.process_scanned_expedients(
            [1],
            diagnosis_provider=(
                lambda expediente_id:
                diagnosis(expediente_id)
            ),
            source_scan_run_id=10,
            source_scan_job_id=20,
            db_path=self.db_path,
        )

        scan_service.process_scanned_expedients(
            [1],
            diagnosis_provider=(
                lambda expediente_id:
                diagnosis(
                    expediente_id,
                    state=(
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                    blocking=0,
                )
            ),
            source_scan_run_id=10,
            source_scan_job_id=20,
            db_path=self.db_path,
        )

        snapshot = repository.get_snapshot(
            1,
            db_path=self.db_path,
        )
        events = repository.list_events(
            expediente_id=1,
            db_path=self.db_path,
        )

        self.assertEqual(
            snapshot["source_scan_run_id"],
            10,
        )
        self.assertEqual(
            snapshot["source_scan_job_id"],
            20,
        )
        self.assertEqual(
            events[0]["source_scan_run_id"],
            10,
        )


if __name__ == "__main__":
    unittest.main()

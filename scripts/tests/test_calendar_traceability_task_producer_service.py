import gc
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from backend.services import (
    calendar_traceability_task_producer_service
    as producer,
)
from backend.services import task_service


class CalendarTraceabilityTaskProducerTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "calendar_tax_producer.db"
        )

        self._create_database()

    def tearDown(self):
        gc.collect()

        cleanup_error = None

        for _ in range(5):
            try:
                self.temp_dir.cleanup()
                cleanup_error = None
                break
            except PermissionError as exc:
                cleanup_error = exc
                gc.collect()
                time.sleep(0.05)

        if cleanup_error is not None:
            raise cleanup_error

    def _connect(self):
        conn = sqlite3.connect(
            self.db_path
        )

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn

    def _create_database(self):
        with closing(
            self._connect()
        ) as conn:
            conn.executescript(
                """
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    primer_apellido TEXT,
                    segundo_apellido TEXT
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER NOT NULL,
                    numero_expediente TEXT,
                    responsable TEXT,
                    FOREIGN KEY (cliente_id)
                        REFERENCES clientes(id)
                );

                CREATE TABLE expediente_justificantes (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    cliente_id INTEGER,
                    tipo_justificante TEXT NOT NULL,
                    metadata_documento_json TEXT,
                    fecha_documento TEXT,
                    fecha_presentacion TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (expediente_id)
                        REFERENCES expedientes(id)
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido
                )
                VALUES (
                    1,
                    'CLIENTE',
                    'PRUEBA',
                    ''
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    responsable
                )
                VALUES (
                    1000,
                    1,
                    'EXP-2026-1000',
                    'NACHO'
                );
                """
            )

            conn.commit()

    def _insert_document(
        self,
        event_code,
        metadata=None,
    ):
        with closing(
            self._connect()
        ) as conn:
            cursor = conn.execute(
                """
                INSERT INTO
                    expediente_justificantes (
                        expediente_id,
                        cliente_id,
                        tipo_justificante,
                        metadata_documento_json,
                        fecha_documento,
                        activo
                    )
                VALUES (
                    1000,
                    1,
                    ?,
                    ?,
                    '2026-05-01',
                    1
                )
                """,
                (
                    event_code,
                    json.dumps(
                        metadata or {},
                        ensure_ascii=False,
                    ),
                ),
            )

            conn.commit()

            return int(
                cursor.lastrowid
            )

    def _archive_document(
        self,
        document_id,
    ):
        with closing(
            self._connect()
        ) as conn:
            conn.execute(
                """
                UPDATE expediente_justificantes
                SET
                    activo = 0,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(document_id),
                ),
            )

            conn.commit()

    def _tasks(self):
        return task_service.list_tasks(
            expediente_id=1000,
            include_archived=True,
            db_path=self.db_path,
        )

    def _tax_metadata(self):
        return {
            "tasa_requerida": True,
            "tasa_modelo": "790",
            "tasa_codigo": "052",
            "tasa_importe_centimos":
                3828,
            "plazo_pago_dias_habiles":
                10,
            "plazo_aportacion_dias":
                15,
            "estado_tasa": "PENDIENTE",
        }

    def test_no_admission_means_no_obligation(
        self,
    ):
        result = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["action"],
            "NO_OBLIGATION",
        )

        self.assertIsNone(
            result["task"]
        )

        self.assertEqual(
            len(self._tasks()),
            0,
        )

    def test_admission_without_due_date_creates_operational_task(
        self,
    ):
        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            self._tax_metadata(),
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["action"],
            "CREATED",
        )

        self.assertFalse(
            result[
                "requires_due_date"
            ]
        )

        self.assertEqual(
            result[
                "due_date_source"
            ],
            "OPERATIONAL_DEFAULT",
        )

        task = result["task"]

        self.assertIsNotNone(
            task
        )

        self.assertEqual(
            task["titulo"],
            "Aportar tasa",
        )

        self.assertEqual(
            task["estado"],
            "PENDIENTE",
        )

        # El fixture registra el documento el
        # 01/05/2026. El objetivo operativo interno
        # es +10 días naturales a las 12:00.
        self.assertEqual(
            task["fecha_vencimiento"],
            "2026-05-11 12:00:00",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

        self.assertEqual(
            result["metadata"][
                "plazo_pago_dias_habiles"
            ],
            10,
        )

    def test_confirmed_due_date_creates_tax_task(
        self,
    ):
        admission_id = (
            self._insert_document(
                "ADMISION_TRAMITE_TASA",
                self._tax_metadata(),
            )
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["action"],
            "CREATED",
        )

        task = result["task"]

        self.assertEqual(
            task["titulo"],
            "Aportar tasa",
        )

        self.assertEqual(
            task["tipo"],
            "APORTACION_TASA",
        )

        self.assertEqual(
            task["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            task["prioridad"],
            "ALTA",
        )

        self.assertEqual(
            task["responsable"],
            "NACHO",
        )

        self.assertEqual(
            task["cliente_id"],
            1,
        )

        self.assertEqual(
            task["expediente_id"],
            1000,
        )

        self.assertEqual(
            task["origen_tipo"],
            "TRAZABILIDAD",
        )

        self.assertEqual(
            task["origen_id"],
            str(admission_id),
        )

        self.assertEqual(
            task["source_key"],
            (
                "TRACEABILITY:TASK:"
                "TAX:EXP:1000"
            ),
        )

        self.assertEqual(
            task["fecha_vencimiento"],
            "2099-05-15 12:00:00",
        )

        description = (
            task["descripcion"]
        )

        self.assertIn(
            "790",
            description,
        )

        self.assertIn(
            "052",
            description,
        )

        self.assertIn(
            "38.28",
            description,
        )

        self.assertIn(
            "10 días hábiles",
            description,
        )

        self.assertIn(
            "15 días",
            description,
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

    def test_reprocessing_does_not_duplicate_task(
        self,
    ):
        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            self._tax_metadata(),
        )

        first = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        second = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            first["action"],
            "CREATED",
        )

        self.assertIn(
            second["action"],
            {
                "UPDATED",
                "UNCHANGED",
            },
        )

        tasks = self._tasks()

        self.assertEqual(
            len(tasks),
            1,
        )

        self.assertEqual(
            tasks[0]["id"],
            first["task"]["id"],
        )

        self.assertEqual(
            tasks[0]["source_key"],
            (
                "TRACEABILITY:TASK:"
                "TAX:EXP:1000"
            ),
        )

    def test_tax_submission_completes_existing_task(
        self,
    ):
        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            self._tax_metadata(),
        )

        created = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        task_id = (
            created["task"]["id"]
        )

        self._insert_document(
            "JUSTIFICANTE_APORTACION_TASA",
            {
                "aportacion_tasa_confirmada":
                    True,
                "estado_tasa":
                    "APORTADA",
            },
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "COMPLETED",
        )

        self.assertEqual(
            result["task"]["id"],
            task_id,
        )

        self.assertEqual(
            result["task"]["estado"],
            "COMPLETADA",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

    def test_submission_without_previous_task_is_already_satisfied(
        self,
    ):
        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            self._tax_metadata(),
        )

        self._insert_document(
            "JUSTIFICANTE_APORTACION_TASA",
            {
                "aportacion_tasa_confirmada":
                    True,
                "estado_tasa":
                    "APORTADA",
            },
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "ALREADY_SATISFIED",
        )

        self.assertIsNone(
            result["task"]
        )

        self.assertEqual(
            len(self._tasks()),
            0,
        )

    def test_archived_submission_can_reopen_same_task(
        self,
    ):
        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            self._tax_metadata(),
        )

        created = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        task_id = (
            created["task"]["id"]
        )

        submission_id = (
            self._insert_document(
                "JUSTIFICANTE_APORTACION_TASA",
                {
                    "aportacion_tasa_confirmada":
                        True,
                    "estado_tasa":
                        "APORTADA",
                },
            )
        )

        completed = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            completed["action"],
            "COMPLETED",
        )

        self._archive_document(
            submission_id
        )

        without_due = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            without_due["action"],
            (
                "NEEDS_DUE_DATE_FOR_REOPEN"
            ),
        )

        self.assertTrue(
            without_due[
                "requires_due_date"
            ]
        )

        reopened = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-16 12:00:00",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["action"],
            "REOPENED",
        )

        self.assertEqual(
            reopened["task"]["id"],
            task_id,
        )

        self.assertEqual(
            reopened["task"]["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            reopened["task"][
                "fecha_vencimiento"
            ],
            "2099-05-16 12:00:00",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

    def test_archived_admission_cancels_same_task(
        self,
    ):
        admission_id = (
            self._insert_document(
                "ADMISION_TRAMITE_TASA",
                self._tax_metadata(),
            )
        )

        created = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        task_id = (
            created["task"]["id"]
        )

        self._archive_document(
            admission_id
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "CANCELLED",
        )

        self.assertEqual(
            result["task"]["id"],
            task_id,
        )

        self.assertEqual(
            result["task"]["estado"],
            "CANCELADA",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

    def test_explicit_false_tax_requirement_does_not_create_task(
        self,
    ):
        metadata = (
            self._tax_metadata()
        )

        metadata[
            "tasa_requerida"
        ] = False

        self._insert_document(
            "ADMISION_TRAMITE_TASA",
            metadata,
        )

        result = (
            producer.sync_tax_obligation(
                1000,
                due_at="2099-05-15 12:00:00",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "NO_OBLIGATION",
        )

        self.assertEqual(
            len(self._tasks()),
            0,
        )

    def test_tax_status_without_admission_has_no_obligation(
        self,
    ):
        snapshot = (
            producer
            .get_tax_obligation_status(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            snapshot["ok"]
        )

        self.assertEqual(
            snapshot["status"],
            "NO_OBLIGATION",
        )

        self.assertFalse(
            snapshot[
                "obligation_exists"
            ]
        )

        self.assertFalse(
            snapshot[
                "requires_due_date"
            ]
        )


    def test_tax_status_detects_unsynchronized_obligation(
        self,
    ):
        self._insert_document(
            producer.TAX_ADMISSION_EVENT,
            self._tax_metadata(),
        )

        snapshot = (
            producer
            .get_tax_obligation_status(
                1000,
                db_path=self.db_path,
            )
        )

        # El snapshot es SOLO LECTURA.
        # Al insertar directamente el documento en
        # el fixture, todavía no ha pasado por sync.
        self.assertEqual(
            snapshot["status"],
            "TASK_NOT_CREATED",
        )

        self.assertTrue(
            snapshot[
                "obligation_exists"
            ]
        )

        self.assertFalse(
            snapshot[
                "requires_due_date"
            ]
        )

        self.assertIsNone(
            snapshot["task"]
        )

        self.assertEqual(
            snapshot["metadata"][
                "tasa_codigo"
            ],
            "052",
        )

        # Consultar nunca puede crear la TASK.
        self.assertEqual(
            len(self._tasks()),
            0,
        )


    def test_confirm_tax_due_date_creates_task(
        self,
    ):
        self._insert_document(
            producer.TAX_ADMISSION_EVENT,
            self._tax_metadata(),
        )

        result = (
            producer
            .confirm_tax_due_date(
                1000,
                "2099-05-15T12:30:00",
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "CREATED",
        )

        self.assertEqual(
            result[
                "confirmed_due_at"
            ],
            "2099-05-15 12:30:00",
        )

        self.assertEqual(
            result["task"][
                "fecha_vencimiento"
            ],
            "2099-05-15 12:30:00",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )

        snapshot = (
            producer
            .get_tax_obligation_status(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            snapshot["status"],
            "TASK_ACTIVE",
        )

        self.assertFalse(
            snapshot[
                "requires_due_date"
            ]
        )


    def test_confirm_tax_due_date_updates_existing_task(
        self,
    ):
        self._insert_document(
            producer.TAX_ADMISSION_EVENT,
            self._tax_metadata(),
        )

        created = (
            producer
            .confirm_tax_due_date(
                1000,
                "2099-05-15 12:00:00",
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        task_id = (
            created["task"]["id"]
        )

        updated = (
            producer
            .confirm_tax_due_date(
                1000,
                "2099-05-16 09:45:00",
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            updated["action"],
            "UPDATED",
        )

        self.assertEqual(
            updated["task"]["id"],
            task_id,
        )

        self.assertEqual(
            updated["task"][
                "fecha_vencimiento"
            ],
            "2099-05-16 09:45:00",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )


    def test_tax_status_is_satisfied_after_submission(
        self,
    ):
        self._insert_document(
            producer.TAX_ADMISSION_EVENT,
            self._tax_metadata(),
        )

        self._insert_document(
            producer.TAX_SUBMISSION_EVENT,
            {
                "aportacion_tasa_confirmada":
                    True,
                "estado_tasa":
                    "APORTADA",
            },
        )

        snapshot = (
            producer
            .get_tax_obligation_status(
                1000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            snapshot["status"],
            "SATISFIED",
        )

        self.assertTrue(
            snapshot["satisfied"]
        )

        self.assertFalse(
            snapshot[
                "requires_due_date"
            ]
        )


    def test_confirm_due_date_rejects_satisfied_obligation(
        self,
    ):
        self._insert_document(
            producer.TAX_ADMISSION_EVENT,
            self._tax_metadata(),
        )

        self._insert_document(
            producer.TAX_SUBMISSION_EVENT,
            {
                "aportacion_tasa_confirmada":
                    True,
                "estado_tasa":
                    "APORTADA",
            },
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está satisfecha",
        ):
            (
                producer
                .confirm_tax_due_date(
                    1000,
                    "2099-05-15 12:00:00",
                    usuario="TEST",
                    db_path=self.db_path,
                )
            )

        self.assertEqual(
            len(self._tasks()),
            0,
        )



    def _requirement_metadata(
        self,
        *,
        csv_value="CSV-REQ-001",
    ):
        return {
            "fecha_requerimiento":
                "2026-05-01",
            "csv_requerimiento":
                csv_value,
            "numero_expediente_extranjeria":
                "330020260004082",
            "nie_detectado":
                "X0000000T",
            "plazo_dias":
                10,
            "documentacion_requerida_original":
                "Pasaporte y certificado.",
            "documentacion_requerida_abogado":
                "Pasaporte y certificado.",
            "estado_requerimiento":
                "PENDIENTE",
        }


    def test_requirement_creates_operational_task(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        result = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "CREATED",
        )

        task = result["task"]

        self.assertEqual(
            task["titulo"],
            "Atender requerimiento",
        )

        self.assertEqual(
            task["tipo"],
            "ATENCION_REQUERIMIENTO",
        )

        self.assertEqual(
            task["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            task["fecha_vencimiento"],
            "2026-05-11 12:00:00",
        )

        self.assertEqual(
            task["origen_id"],
            str(requirement_id),
        )

        self.assertEqual(
            task["source_key"],
            (
                "TRACEABILITY:TASK:"
                "REQUIREMENT:EXP:1000:REQ:"
                + str(requirement_id)
            ),
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )


    def test_reprocessing_requirement_does_not_duplicate(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        first = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        second = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            first["action"],
            "CREATED",
        )

        self.assertEqual(
            second["action"],
            "UNCHANGED",
        )

        self.assertEqual(
            first["task"]["id"],
            second["task"]["id"],
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )


    def test_two_requirements_create_two_distinct_tasks(
        self,
    ):
        requirement_a = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-A",
                ),
            )
        )

        requirement_b = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-B",
                ),
            )
        )

        result_a = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_a,
                db_path=self.db_path,
            )
        )

        result_b = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_b,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result_a["action"],
            "CREATED",
        )

        self.assertEqual(
            result_b["action"],
            "CREATED",
        )

        self.assertNotEqual(
            result_a["task"]["id"],
            result_b["task"]["id"],
        )

        self.assertNotEqual(
            result_a["task"]["source_key"],
            result_b["task"]["source_key"],
        )

        self.assertEqual(
            len(self._tasks()),
            2,
        )



    def _document_submission_metadata(
        self,
        *,
        requirement_document_id=None,
    ):
        metadata = {
            "fecha_registro":
                "2026-05-06 10:00:00",
            "fecha_presentacion":
                "2026-05-06 09:59:00",
            "csv_geiser":
                "CSV-APORTACION-DOC-001",
            "numero_registro_regage":
                "REGAGE-APORTACION-001",
            "numero_expediente_extranjeria":
                "330020260004082",
            "nie_detectado":
                "X0000000T",
            "documentos_aportados_texto":
                "Pasaporte y certificado.",
            "estado_aportacion":
                "APORTADA",
        }

        if requirement_document_id is not None:
            metadata[
                "requerimiento_documento_id"
            ] = int(
                requirement_document_id
            )

        return metadata


    def test_document_submission_completes_single_open_requirement(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        created = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        task_id = created["task"]["id"]

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(),
            )
        )

        result = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "COMPLETED",
        )

        self.assertEqual(
            result[
                "requirement_document_id"
            ],
            requirement_id,
        )

        self.assertEqual(
            result["task"]["id"],
            task_id,
        )

        self.assertEqual(
            result["task"]["estado"],
            "COMPLETADA",
        )

        # No ha sido necesario pasar por EN_CURSO.
        self.assertEqual(
            len(self._tasks()),
            1,
        )

        with closing(
            self._connect()
        ) as conn:
            row = conn.execute(
                """
                SELECT metadata_documento_json
                FROM expediente_justificantes
                WHERE id = ?
                """,
                (
                    submission_id,
                ),
            ).fetchone()

        metadata = json.loads(
            row["metadata_documento_json"]
            or "{}"
        )

        self.assertEqual(
            metadata[
                "requerimiento_documento_id"
            ],
            requirement_id,
        )


    def test_document_submission_is_ambiguous_with_two_open_requirements(
        self,
    ):
        requirement_a = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-A",
                ),
            )
        )

        requirement_b = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-B",
                ),
            )
        )

        for requirement_id in (
            requirement_a,
            requirement_b,
        ):
            (
                producer
                .sync_requirement_obligation(
                    1000,
                    event_code=(
                        producer.REQUIREMENT_EVENT
                    ),
                    document_id=requirement_id,
                    db_path=self.db_path,
                )
            )

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(),
            )
        )

        result = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "AMBIGUOUS_REQUIREMENT",
        )

        self.assertEqual(
            sorted(
                result[
                    "candidate_requirement_ids"
                ]
            ),
            sorted(
                [
                    requirement_a,
                    requirement_b,
                ]
            ),
        )

        states = {
            task["estado"]
            for task in self._tasks()
        }

        self.assertEqual(
            states,
            {"PENDIENTE"},
        )


    def test_explicit_requirement_link_completes_correct_task(
        self,
    ):
        requirement_a = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-A",
                ),
            )
        )

        requirement_b = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(
                    csv_value="CSV-REQ-B",
                ),
            )
        )

        created = {}

        for requirement_id in (
            requirement_a,
            requirement_b,
        ):
            result = (
                producer
                .sync_requirement_obligation(
                    1000,
                    event_code=(
                        producer.REQUIREMENT_EVENT
                    ),
                    document_id=requirement_id,
                    db_path=self.db_path,
                )
            )

            created[
                requirement_id
            ] = result["task"]

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_b
                    ),
                ),
            )
        )

        result = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["action"],
            "COMPLETED",
        )

        self.assertEqual(
            result[
                "requirement_document_id"
            ],
            requirement_b,
        )

        tasks = {
            task["id"]: task
            for task in self._tasks()
        }

        self.assertEqual(
            tasks[
                created[
                    requirement_a
                ]["id"]
            ]["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            tasks[
                created[
                    requirement_b
                ]["id"]
            ]["estado"],
            "COMPLETADA",
        )


    def test_archiving_linked_submission_requires_new_due_date(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        created = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        task_id = created["task"]["id"]

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_id
                    ),
                ),
            )
        )

        completed = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            completed["action"],
            "COMPLETED",
        )

        self._archive_document(
            submission_id
        )

        archived = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            archived["action"],
            "NEEDS_DUE_DATE_FOR_REOPEN",
        )

        self.assertTrue(
            archived[
                "requires_due_date"
            ]
        )

        self.assertEqual(
            archived["task"]["id"],
            task_id,
        )

        self.assertEqual(
            archived["task"]["estado"],
            "COMPLETADA",
        )



    def test_confirm_requirement_due_date_reopens_same_task(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        created = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        task_id = created["task"]["id"]

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_id
                    ),
                ),
            )
        )

        completed = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            completed["task"]["estado"],
            "COMPLETADA",
        )

        self._archive_document(
            submission_id
        )

        archived = (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            archived["action"],
            "NEEDS_DUE_DATE_FOR_REOPEN",
        )

        reopened = (
            producer
            .confirm_requirement_due_date(
                1000,
                requirement_id,
                "2099-05-20T09:30:00",
                usuario="TEST",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["action"],
            "REOPENED",
        )

        self.assertEqual(
            reopened["task"]["id"],
            task_id,
        )

        self.assertEqual(
            reopened["task"]["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            reopened["task"][
                "fecha_vencimiento"
            ],
            "2099-05-20 09:30:00",
        )

        self.assertEqual(
            len(self._tasks()),
            1,
        )


    def test_confirm_requirement_due_date_rejects_active_submission(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_id
                    ),
                ),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está atendido",
        ):
            (
                producer
                .confirm_requirement_due_date(
                    1000,
                    requirement_id,
                    "2099-05-20 09:30:00",
                    usuario="TEST",
                    db_path=self.db_path,
                )
            )



    def test_requirement_status_reports_active_task(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        snapshot = (
            producer
            .get_requirement_obligation_status(
                1000,
                requirement_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            snapshot["status"],
            "TASK_ACTIVE",
        )

        self.assertEqual(
            snapshot["task"]["estado"],
            "PENDIENTE",
        )


    def test_requirement_status_reports_satisfied(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_id
                    ),
                ),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        snapshot = (
            producer
            .get_requirement_obligation_status(
                1000,
                requirement_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            snapshot["status"],
            "SATISFIED",
        )

        self.assertEqual(
            snapshot["task"]["estado"],
            "COMPLETADA",
        )


    def test_requirement_status_requires_due_after_archived_submission(
        self,
    ):
        requirement_id = (
            self._insert_document(
                producer.REQUIREMENT_EVENT,
                self._requirement_metadata(),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.REQUIREMENT_EVENT
                ),
                document_id=requirement_id,
                db_path=self.db_path,
            )
        )

        submission_id = (
            self._insert_document(
                producer.DOCUMENT_SUBMISSION_EVENT,
                self._document_submission_metadata(
                    requirement_document_id=(
                        requirement_id
                    ),
                ),
            )
        )

        (
            producer
            .sync_requirement_obligation(
                1000,
                event_code=(
                    producer.DOCUMENT_SUBMISSION_EVENT
                ),
                document_id=submission_id,
                db_path=self.db_path,
            )
        )

        self._archive_document(
            submission_id
        )

        snapshot = (
            producer
            .get_requirement_obligation_status(
                1000,
                requirement_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            snapshot["status"],
            "NEEDS_DUE_DATE_FOR_REOPEN",
        )

        self.assertTrue(
            snapshot["requires_due_date"]
        )

        self.assertEqual(
            snapshot["task"]["estado"],
            "COMPLETADA",
        )



if __name__ == "__main__":
    unittest.main()

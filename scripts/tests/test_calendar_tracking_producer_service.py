import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.services import (
    calendar_alert_service,
    calendar_tracking_producer_service
    as producer,
)


class CalendarTrackingProducerTestCase(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(
                self.temp_dir.name
            )
            / "calendar_tracking.db"
        )

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    primer_apellido TEXT,
                    segundo_apellido TEXT
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER,
                    numero_expediente TEXT
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
                    numero_expediente
                )
                VALUES (
                    10,
                    1,
                    'EXP-TEST-0010'
                );
                """
            )

        (
            calendar_alert_service
            .ensure_calendar_alert_schema(
                db_path=self.db_path
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def result(
        self,
        estado,
        *,
        activo=1,
        changed=True,
    ):
        return {
            "ok": True,
            "changed": changed,
            "created": False,
            "tracking_id": 100,
            "event_id": 200,
            "expediente_id": 10,
            "cliente_id": 1,
            "estado_anterior": "",
            "estado_nuevo": estado,
            "activo": activo,
            "resultado_resolucion": "",
            "reason": "",
            "snapshot": {},
        }

    def alerts(self):
        return (
            calendar_alert_service
            .list_alerts(
                expediente_id=10,
                include_archived=True,
                db_path=self.db_path,
            )
        )

    def test_waiting_number_creates_alert(
        self,
    ):
        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_NUMERO_EXPEDIENTE"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["action"],
            "CREATED",
        )

        alerts = self.alerts()

        self.assertEqual(
            len(alerts),
            1,
        )

        alert = alerts[0]

        self.assertEqual(
            alert["titulo"],
            "En espera de notificación",
        )

        self.assertEqual(
            alert["descripcion"],
            "Esperando número de expediente.",
        )

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

        self.assertEqual(
            alert["source_key"],
            "NOTIFICATION_TRACKING:EXP:10",
        )

    def test_reprocessing_is_idempotent(
        self,
    ):
        producer.sync_from_tracking_result(
            self.result(
                "ESPERA_NUMERO_EXPEDIENTE"
            ),
            db_path=self.db_path,
        )

        second = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_NUMERO_EXPEDIENTE",
                    changed=False,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(
                self.alerts()
            ),
            1,
        )

        self.assertEqual(
            second["action"],
            "UNCHANGED",
        )

    def test_state_transition_updates_same_alert(
        self,
    ):
        first = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_NUMERO_EXPEDIENTE"
                ),
                db_path=self.db_path,
            )
        )

        alert_id = (
            first["alert"]["id"]
        )

        second = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_ADMISION_TRAMITE"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(
                self.alerts()
            ),
            1,
        )

        self.assertEqual(
            second["alert"]["id"],
            alert_id,
        )

        self.assertEqual(
            second["alert"][
                "descripcion"
            ],
            "Esperando admisión a trámite.",
        )

    def test_waiting_resolution_updates_same_alert(
        self,
    ):
        first = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_ADMISION_TRAMITE"
                ),
                db_path=self.db_path,
            )
        )

        alert_id = (
            first["alert"]["id"]
        )

        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_RESOLUCION"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["alert"]["id"],
            alert_id,
        )

        self.assertEqual(
            output["alert"][
                "descripcion"
            ],
            "Esperando resolución.",
        )

    def test_favorable_resolution_resolves_alert(
        self,
    ):
        first = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_RESOLUCION"
                ),
                db_path=self.db_path,
            )
        )

        alert_id = (
            first["alert"]["id"]
        )

        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "CERRADO_FAVORABLE",
                    activo=0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["action"],
            "RESOLVED",
        )

        self.assertEqual(
            output["alert"]["id"],
            alert_id,
        )

        self.assertEqual(
            output["alert"]["estado"],
            "RESUELTO",
        )

    def test_denial_resolves_alert(
        self,
    ):
        producer.sync_from_tracking_result(
            self.result(
                "ESPERA_RESOLUCION"
            ),
            db_path=self.db_path,
        )

        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "CERRADO_DENEGATORIO",
                    activo=0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["alert"]["estado"],
            "RESUELTO",
        )

    def test_presentation_removal_cancels_alert(
        self,
    ):
        producer.sync_from_tracking_result(
            self.result(
                "ESPERA_NUMERO_EXPEDIENTE"
            ),
            db_path=self.db_path,
        )

        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "CANCELADO_SIN_PRESENTACION",
                    activo=0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["action"],
            "CANCELLED",
        )

        self.assertEqual(
            output["alert"]["estado"],
            "CANCELADO",
        )

    def test_closed_tracking_does_not_create_alert(
        self,
    ):
        output = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "CERRADO_FAVORABLE",
                    activo=0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            output["action"],
            "NO_ALERT",
        )

        self.assertEqual(
            self.alerts(),
            [],
        )

    def test_reopened_tracking_reuses_same_alert(
        self,
    ):
        first = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_RESOLUCION"
                ),
                db_path=self.db_path,
            )
        )

        alert_id = (
            first["alert"]["id"]
        )

        producer.sync_from_tracking_result(
            self.result(
                "CERRADO_FAVORABLE",
                activo=0,
            ),
            db_path=self.db_path,
        )

        reopened = (
            producer
            .sync_from_tracking_result(
                self.result(
                    "ESPERA_RESOLUCION"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["action"],
            "REOPENED",
        )

        self.assertEqual(
            reopened["alert"]["id"],
            alert_id,
        )

        self.assertEqual(
            reopened["alert"]["estado"],
            "ACTIVO",
        )

        self.assertEqual(
            len(
                self.alerts()
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()

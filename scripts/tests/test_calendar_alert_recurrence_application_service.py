import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import (
    calendar_alert_service,
    calendar_alert_application_service,
    scheduled_notification_service,
    calendar_alert_recurrence_service,
    calendar_alert_recurrence_application_service
    as recurrence_app,
)


class CalendarAlertRecurrenceApplicationServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "recurrence-app.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                numero_expediente TEXT
            )
            """
        )

        conn.execute(
            """
            INSERT INTO clientes (
                id,
                nombre,
                primer_apellido,
                segundo_apellido
            )
            VALUES (
                31,
                'WENDY VANESSA',
                'RAMIREZ',
                'VELASQUEZ'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente
            )
            VALUES (
                43,
                31,
                'EXP-2026-0026'
            )
            """
        )

        conn.commit()
        conn.close()

        (
            calendar_alert_service
            .ensure_calendar_alert_schema(
                db_path=self.db_path
            )
        )

        (
            scheduled_notification_service
            .ensure_schema(
                db_path=self.db_path
            )
        )

        (
            calendar_alert_recurrence_service
            .ensure_schema(
                db_path=self.db_path
            )
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _event_at(self):
        return datetime(
            2026,
            8,
            15,
            9,
            0,
        )

    def _warning_at(self):
        return datetime(
            2026,
            8,
            9,
            9,
            0,
        )

    def _create_series(
        self,
        *,
        end_type="NEVER",
        end_date=None,
        max_occurrences=None,
    ):
        return (
            recurrence_app
            .create_recurring_alert(
                titulo=(
                    "Renovar documentación"
                ),
                descripcion=(
                    "Aviso recurrente"
                ),
                cliente_id=31,
                expediente_id=43,
                prioridad="ALTA",
                fecha_evento=(
                    self._event_at()
                ),
                fecha_inicio_aviso=(
                    self._warning_at()
                ),
                frequency_unit="DAY",
                interval_value=1,
                end_type=end_type,
                end_date=end_date,
                max_occurrences=(
                    max_occurrences
                ),
                db_path=self.db_path,
            )
        )

    def test_create_series_creates_one_alert_and_rule(
        self,
    ):
        result = self._create_series()

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        alert = result["alert"]

        self.assertEqual(
            alert["cliente_id"],
            31,
        )

        self.assertEqual(
            alert["numero_expediente"],
            "EXP-2026-0026",
        )

        self.assertEqual(
            result["recurrence"][
                "root_alert_id"
            ],
            alert["id"],
        )

        self.assertEqual(
            result["recurrence"][
                "anchor_at"
            ],
            "2026-08-09 09:00:00",
        )

    def test_root_notification_is_first_occurrence(
        self,
    ):
        result = self._create_series()

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            1,
        )

        self.assertEqual(
            notifications[0][
                "scheduled_at"
            ],
            "2026-08-09 09:00:00",
        )

        self.assertEqual(
            len(mappings),
            1,
        )

        self.assertEqual(
            mappings[0][
                "occurrence_index"
            ],
            1,
        )

        legacy_occurrences = (
            calendar_alert_recurrence_service
            .list_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            legacy_occurrences,
            [],
        )


    def test_next_occurrence_reuses_same_alert(
        self,
    ):
        result = self._create_series()

        occurrence = (
            recurrence_app
            .materialize_next_occurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertIsNotNone(
            occurrence
        )

        self.assertEqual(
            occurrence["alert"]["id"],
            result["alert"]["id"],
        )

        self.assertEqual(
            occurrence["scheduled_at"],
            "2026-08-10 09:00:00",
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

    def test_recurrent_notifications_use_root_alert(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            4,
        )

        self.assertTrue(
            all(
                item["source_id"]
                == result["alert"]["id"]
                for item in notifications
            )
        )

    def test_materialize_three_creates_notifications_not_alerts(
        self,
    ):
        result = self._create_series()

        created = (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(created),
            3,
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
            ],
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["occurrence_index"]
                for item in mappings
            ],
            [1, 2, 3, 4],
        )

    def test_event_date_is_natural_limit(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=20,
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
                "2026-08-13 09:00:00",
                "2026-08-14 09:00:00",
                "2026-08-15 09:00:00",
            ],
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            7,
        )

        self.assertEqual(
            recurrence["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            recurrence["activo"],
            1,
        )

        self.assertIsNone(
            recurrence[
                "next_occurrence_at"
            ]
        )

    def test_count_series_stops_exactly(
        self,
    ):
        result = self._create_series(
            end_type="COUNT",
            max_occurrences=3,
        )

        created = (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=20,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(created),
            2,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            3,
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            3,
        )

        self.assertEqual(
            recurrence["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            recurrence["activo"],
            1,
        )

    def test_recurrent_notification_source_keys_are_unique(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(mappings),
            4,
        )

        generated = mappings[1:]

        self.assertEqual(
            [
                item["source_key"]
                for item in generated
            ],
            [
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:2"
                ),
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:3"
                ),
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:4"
                ),
            ],
        )


    def test_materialize_until_event_limit(
        self,
    ):
        result = self._create_series()

        created = (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        # El 09/08 ya existe como primer aviso.
        # Se generan 10, 11, 12, 13, 14 y 15.
        self.assertEqual(
            len(created),
            6,
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
                "2026-08-13 09:00:00",
                "2026-08-14 09:00:00",
                "2026-08-15 09:00:00",
            ],
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            7,
        )

        self.assertEqual(
            recurrence["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            recurrence["activo"],
            1,
        )

        self.assertIsNone(
            recurrence[
                "next_occurrence_at"
            ]
        )



    def test_pause_recurring_alert_pauses_notifications(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        paused = (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            paused["recurrence"]["estado"],
            "PAUSADA",
        )

        self.assertEqual(
            paused["recurrence"]["activo"],
            0,
        )

        self.assertEqual(
            paused["notifications_paused"],
            7,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            {
                item["estado"]
                for item in notifications
            },
            {"PAUSADA"},
        )

        self.assertTrue(
            all(
                item["activo"] == 0
                for item in notifications
            )
        )

        alert = (
            calendar_alert_service
            .get_alert(
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

        self.assertEqual(
            alert["activo"],
            1,
        )

    def test_resume_recurring_alert_omits_past_notifications(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        resumed = (
            recurrence_app
            .resume_recurring_alert(
                result["recurrence"]["id"],
                now=datetime(
                    2026,
                    8,
                    12,
                    9,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            resumed["recurrence"]["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            resumed["recurrence"]["activo"],
            1,
        )

        self.assertEqual(
            resumed["omitted"],
            3,
        )

        self.assertEqual(
            resumed["reactivated"],
            4,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        states = {
            item["scheduled_at"]:
                (
                    item["estado"],
                    item["activo"],
                )
            for item in notifications
        }

        self.assertEqual(
            states[
                "2026-08-09 09:00:00"
            ],
            ("OMITIDA", 0),
        )

        self.assertEqual(
            states[
                "2026-08-10 09:00:00"
            ],
            ("OMITIDA", 0),
        )

        self.assertEqual(
            states[
                "2026-08-11 09:00:00"
            ],
            ("OMITIDA", 0),
        )

        for scheduled_at in (
            "2026-08-12 09:00:00",
            "2026-08-13 09:00:00",
            "2026-08-14 09:00:00",
            "2026-08-15 09:00:00",
        ):
            self.assertEqual(
                states[scheduled_at],
                ("PENDIENTE", 1),
            )

    def test_cancel_recurring_alert_preserves_root_alert(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        cancelled = (
            recurrence_app
            .cancel_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled[
                "recurrence"
            ]["estado"],
            "CANCELADA",
        )

        self.assertEqual(
            cancelled[
                "recurrence"
            ]["activo"],
            0,
        )

        self.assertEqual(
            cancelled[
                "notifications_cancelled"
            ],
            7,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            {
                item["estado"]
                for item in notifications
            },
            {"CANCELADA"},
        )

        alert = (
            calendar_alert_service
            .get_alert(
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

        self.assertEqual(
            alert["activo"],
            1,
        )

    def test_paused_notifications_are_not_due(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        due = (
            scheduled_notification_service
            .list_due_notifications(
                now=datetime(
                    2026,
                    8,
                    20,
                    9,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            due,
            [],
        )

    def test_pause_only_affects_series_notifications(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        extra = (
            scheduled_notification_service
            .create_notification(
                source_type="ALERT",
                source_id=result["alert"]["id"],
                scheduled_at=datetime(
                    2026,
                    8,
                    14,
                    12,
                    0,
                ),
                notification_type=(
                    "AVISO_CALENDARIO"
                ),
                source_key=(
                    "TEST:UNRELATED:"
                    f"{result['alert']['id']}"
                ),
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        by_id = {
            item["id"]: item
            for item in notifications
        }

        unrelated = by_id[
            extra["notification"]["id"]
        ]

        self.assertEqual(
            unrelated["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            unrelated["activo"],
            1,
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        series_ids = {
            item["notification_id"]
            for item in mappings
        }

        self.assertTrue(
            all(
                by_id[item_id]["estado"]
                == "PAUSADA"
                for item_id in series_ids
            )
        )

    def test_resume_restores_error_notification_as_error(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        notification_id = (
            mappings[-1]["notification_id"]
        )

        (
            scheduled_notification_service
            .mark_error(
                notification_id,
                "Error de prueba",
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .resume_recurring_alert(
                result["recurrence"]["id"],
                now=datetime(
                    2026,
                    8,
                    14,
                    9,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        restored = next(
            item
            for item in notifications
            if item["id"] == notification_id
        )

        self.assertEqual(
            restored["estado"],
            "ERROR",
        )

        self.assertEqual(
            restored["activo"],
            1,
        )

        self.assertEqual(
            restored["last_error"],
            "Error de prueba",
        )

    def test_cancel_paused_series_is_definitive(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        cancelled = (
            recurrence_app
            .cancel_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled[
                "recurrence"
            ]["estado"],
            "CANCELADA",
        )

        self.assertEqual(
            cancelled[
                "notifications_cancelled"
            ],
            7,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            {
                item["estado"]
                for item in notifications
            },
            {"CANCELADA"},
        )

        with self.assertRaises(
            ValueError
        ):
            (
                recurrence_app
                .resume_recurring_alert(
                    result["recurrence"]["id"],
                    db_path=self.db_path,
                )
            )

    def test_intermediate_sent_notification_keeps_recurrence_active(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        first = mappings[0]

        sent = (
            recurrence_app
            .mark_recurring_notification_sent(
                first["notification_id"],
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            sent["finalized"]
        )

        self.assertEqual(
            sent["recurrence"]["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            sent["recurrence"]["activo"],
            1,
        )

    def test_last_sent_notification_finishes_recurrence(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        last_result = None

        for mapping in mappings:
            last_result = (
                recurrence_app
                .mark_recurring_notification_sent(
                    mapping[
                        "notification_id"
                    ],
                    db_path=self.db_path,
                )
            )

        self.assertIsNotNone(
            last_result
        )

        self.assertTrue(
            last_result["finalized"]
        )

        self.assertEqual(
            last_result[
                "recurrence"
            ]["estado"],
            "FINALIZADA",
        )

        self.assertEqual(
            last_result[
                "recurrence"
            ]["activo"],
            0,
        )

        notifications = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            {
                item["estado"]
                for item in notifications
            },
            {"ENVIADA"},
        )

    def test_error_notification_prevents_auto_finish(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        error_mapping = mappings[-1]

        (
            scheduled_notification_service
            .mark_error(
                error_mapping[
                    "notification_id"
                ],
                "Error pendiente",
                db_path=self.db_path,
            )
        )

        for mapping in mappings[:-1]:
            (
                recurrence_app
                .mark_recurring_notification_sent(
                    mapping[
                        "notification_id"
                    ],
                    db_path=self.db_path,
                )
            )

        completion = (
            recurrence_app
            .finalize_recurrence_if_complete(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            completion["finalized"]
        )

        self.assertEqual(
            completion[
                "recurrence"
            ]["estado"],
            "ACTIVA",
        )

        self.assertEqual(
            completion[
                "recurrence"
            ]["activo"],
            1,
        )


    def test_active_recurrence_allows_non_schedule_edit(
        self,
    ):
        result = self._create_series()

        alert_id = result["alert"]["id"]

        before_notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert_id,
                titulo="Título actualizado",
                fecha_evento=self._event_at(),
                fecha_inicio_aviso=self._warning_at(),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            updated["alert"]["titulo"],
            "Título actualizado",
        )

        self.assertFalse(
            updated["schedule_changed"]
        )

        after_notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["id"]
                for item in before_notifications
            ],
            [
                item["id"]
                for item in after_notifications
            ],
        )

    def test_active_recurrence_rejects_schedule_change(
        self,
    ):
        result = self._create_series()

        alert_id = result["alert"]["id"]
        recurrence_id = result["recurrence"]["id"]

        before_alert = (
            calendar_alert_service
            .get_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        before_recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                db_path=self.db_path,
            )
        )

        before_notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "recurrencia activa o pausada",
        ):
            (
                calendar_alert_application_service
                .update_calendar_alert(
                    alert_id,
                    fecha_evento=datetime(
                        2026,
                        8,
                        16,
                        9,
                        0,
                    ),
                    db_path=self.db_path,
                )
            )

        after_alert = (
            calendar_alert_service
            .get_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        after_recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                db_path=self.db_path,
            )
        )

        after_notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            before_alert["fecha_evento"],
            after_alert["fecha_evento"],
        )

        self.assertEqual(
            before_recurrence["estado"],
            after_recurrence["estado"],
        )

        self.assertEqual(
            [
                (
                    item["id"],
                    item["estado"],
                    item["activo"],
                )
                for item in before_notifications
            ],
            [
                (
                    item["id"],
                    item["estado"],
                    item["activo"],
                )
                for item in after_notifications
            ],
        )

    def test_paused_recurrence_rejects_schedule_change(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .pause_recurring_alert(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "recurrencia activa o pausada",
        ):
            (
                calendar_alert_application_service
                .update_calendar_alert(
                    result["alert"]["id"],
                    fecha_evento=datetime(
                        2026,
                        8,
                        16,
                        9,
                        0,
                    ),
                    db_path=self.db_path,
                )
            )

    def test_active_recurrence_rejects_root_resolve(
        self,
    ):
        result = self._create_series()

        with self.assertRaisesRegex(
            ValueError,
            "Gestiona primero la serie recurrente",
        ):
            (
                calendar_alert_application_service
                .resolve_calendar_alert(
                    result["alert"]["id"],
                    db_path=self.db_path,
                )
            )

        alert = (
            calendar_alert_service
            .get_alert(
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

    def test_active_recurrence_rejects_root_cancel(
        self,
    ):
        result = self._create_series()

        with self.assertRaisesRegex(
            ValueError,
            "Cancela primero la serie recurrente",
        ):
            (
                calendar_alert_application_service
                .cancel_calendar_alert(
                    result["alert"]["id"],
                    db_path=self.db_path,
                )
            )

        alert = (
            calendar_alert_service
            .get_alert(
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

    def test_cancelled_recurrence_allows_schedule_change(
        self,
    ):
        result = self._create_series()

        recurrence_id = result["recurrence"]["id"]
        alert_id = result["alert"]["id"]

        (
            recurrence_app
            .cancel_recurring_alert(
                recurrence_id,
                db_path=self.db_path,
            )
        )

        new_event = datetime(
            2026,
            8,
            18,
            9,
            0,
        )

        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert_id,
                fecha_evento=new_event,
                fecha_inicio_aviso="",
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            updated["schedule_changed"]
        )

        self.assertEqual(
            updated["alert"]["fecha_evento"],
            "2026-08-18 09:00:00",
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence["estado"],
            "CANCELADA",
        )



if __name__ == "__main__":
    unittest.main()

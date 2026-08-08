import unittest
from datetime import datetime
from unittest.mock import patch

from backend.services import (
    calendar_agenda_summary_service
    as agenda_summary,
)


class CalendarAgendaSummaryServiceTestCase(
    unittest.TestCase
):

    def _items(self):
        return [
            {
                "item_type": "TASK",
                "source_id": 1,
                "title":
                    "Atender requerimiento",
                "description": "",
                "date":
                    "2026-08-07 12:00:00",
                "warning_date": None,
                "priority": "ALTA",
                "status": "PENDIENTE",
                "responsible":
                    "Ignacio Alvarez",
                "cliente_id": 1,
                "client_name":
                    "ANA GUILHERME BORGES",
                "expediente_id": 10,
                "expedient_number":
                    "EXP-001",
                "origin_type": "MANUAL",
                "origin_id": None,
                "source_key": "",
            },
            {
                "item_type": "TASK",
                "source_id": 2,
                "title":
                    "Preparar documentación",
                "description": "",
                "date":
                    "2026-08-08 15:00:00",
                "warning_date": None,
                "priority": "NORMAL",
                "status": "EN_CURSO",
                "responsible": "",
                "cliente_id": 2,
                "client_name":
                    "MOHAMED PRUEBA",
                "expediente_id": 20,
                "expedient_number":
                    "EXP-002",
                "origin_type": "MANUAL",
                "origin_id": None,
                "source_key": "",
            },
            {
                "item_type": "TASK",
                "source_id": 3,
                "title":
                    "Solicitar huellas",
                "description": "",
                "date":
                    "2026-08-12 09:00:00",
                "warning_date": None,
                "priority": "URGENTE",
                "status": "PENDIENTE",
                "responsible":
                    "Ignacio Alvarez",
                "cliente_id": 3,
                "client_name":
                    "CLIENTE FUTURO",
                "expediente_id": 30,
                "expedient_number":
                    "EXP-003",
                "origin_type": "MANUAL",
                "origin_id": None,
                "source_key": "",
            },
            {
                "item_type": "TASK",
                "source_id": 4,
                "title":
                    "Trabajo terminado",
                "description": "",
                "date":
                    "2026-08-08 10:00:00",
                "warning_date": None,
                "priority": "BAJA",
                "status": "COMPLETADA",
                "responsible":
                    "Ignacio Alvarez",
                "cliente_id": None,
                "client_name": "",
                "expediente_id": None,
                "expedient_number": "",
                "origin_type": "MANUAL",
                "origin_id": None,
                "source_key": "",
            },
            {
                "item_type": "ALERT",
                "source_id": 5,
                "title":
                    "Caducan penales",
                "description": "",
                "date":
                    "2026-08-09 10:00:00",
                "warning_date":
                    "2026-08-08 10:00:00",
                "priority": "URGENTE",
                "status": "ACTIVO",
                "responsible": "",
                "cliente_id": 1,
                "client_name":
                    "ANA GUILHERME BORGES",
                "expediente_id": 10,
                "expedient_number":
                    "EXP-001",
                "origin_type": "MANUAL",
                "origin_id": None,
                "source_key": "",
            },
        ]

    def test_snapshot_counts(self):
        snapshot = (
            agenda_summary
            .build_agenda_snapshot(
                now=datetime(
                    2026,
                    8,
                    8,
                    14,
                    0,
                ),
                items=self._items(),
            )
        )

        counts = snapshot[
            "counts"
        ]

        self.assertEqual(
            counts["open_tasks"],
            3,
        )

        self.assertEqual(
            counts["pending_tasks"],
            2,
        )

        self.assertEqual(
            counts[
                "in_progress_tasks"
            ],
            1,
        )

        self.assertEqual(
            counts["overdue_tasks"],
            1,
        )

        self.assertEqual(
            counts["today_tasks"],
            1,
        )

        self.assertEqual(
            counts[
                "next_7_days_tasks"
            ],
            2,
        )

        self.assertEqual(
            counts["active_alerts"],
            1,
        )

    def test_message_contains_operational_data(
        self,
    ):
        snapshot = (
            agenda_summary
            .build_agenda_snapshot(
                now=datetime(
                    2026,
                    8,
                    8,
                    14,
                    0,
                ),
                items=self._items(),
            )
        )

        message = (
            agenda_summary
            .build_agenda_summary_message(
                snapshot
            )
        )

        self.assertIn(
            "QUESADA ABOGADOS",
            message,
        )

        self.assertIn(
            "Atender requerimiento",
            message,
        )

        self.assertIn(
            "Solicitar huellas",
            message,
        )

        self.assertIn(
            "ANA GUILHERME BORGES",
            message,
        )

        self.assertIn(
            "EXP-001",
            message,
        )

        self.assertNotIn(
            "Trabajo terminado",
            message,
        )

    def test_missing_responsible_uses_fallback(
        self,
    ):
        snapshot = (
            agenda_summary
            .build_agenda_snapshot(
                now=datetime(
                    2026,
                    8,
                    8,
                    14,
                    0,
                ),
                items=self._items(),
            )
        )

        message = (
            agenda_summary
            .build_agenda_summary_message(
                snapshot
            )
        )

        self.assertIn(
            "Ignacio Alvarez",
            message,
        )

    def test_message_can_be_split(self):
        text = (
            "Bloque uno\n\n"
            + ("A" * 150)
            + "\n\n"
            + ("B" * 150)
        )

        messages = (
            agenda_summary
            .split_message(
                text,
                max_length=100,
            )
        )

        self.assertGreater(
            len(messages),
            1,
        )

        self.assertTrue(
            all(
                len(item) <= 100
                for item in messages
            )
        )

    @patch(
        "backend.services."
        "calendar_agenda_summary_service."
        "telegram_service."
        "send_message"
    )
    @patch(
        "backend.services."
        "calendar_agenda_summary_service."
        "calendar_service."
        "list_calendar_items"
    )
    def test_send_agenda_summary(
        self,
        list_calendar_items,
        send_message,
    ):
        list_calendar_items.return_value = (
            self._items()
        )

        send_message.return_value = {
            "ok": True,
        }

        result = (
            agenda_summary
            .send_agenda_summary(
                now=datetime(
                    2026,
                    8,
                    8,
                    14,
                    0,
                ),
                token="token-test",
                chat_id="123",
            )
        )

        self.assertGreaterEqual(
            result["sent"],
            1,
        )

        self.assertEqual(
            result["sent"],
            result["message_count"],
        )

        self.assertEqual(
            send_message.call_count,
            result["message_count"],
        )


if __name__ == "__main__":
    unittest.main()

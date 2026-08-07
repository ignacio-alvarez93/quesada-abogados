import unittest
from unittest.mock import patch

from backend.workers import (
    task_notification_worker,
)


class TaskNotificationWorkerTestCase(
    unittest.TestCase
):

    def _notification(self):
        return {
            "id": 1,
            "source_type": "TASK",
            "source_id": 10,
            "delivery_context": {
                "source": {
                    "id": 10,
                    "titulo":
                        "Presentar expediente",
                    "descripcion":
                        "",
                    "cliente_nombre":
                        "MOHAMED",
                    "cliente_primer_apellido":
                        "PRUEBA",
                    "numero_expediente":
                        "EXP-001",
                    "fecha_vencimiento":
                        "2026-01-13 12:00",
                    "prioridad":
                        "ALTA",
                }
            },
        }

    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "list_due_notifications"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "telegram_service."
        "send_message"
    )
    def test_dry_run_does_not_send(
        self,
        send_message,
        list_due,
    ):
        list_due.return_value = [
            self._notification()
        ]

        summary = (
            task_notification_worker
            .process_due_notifications(
                dry_run=True
            )
        )

        self.assertEqual(
            summary["found"],
            1,
        )

        self.assertEqual(
            summary["dry_run"],
            1,
        )

        send_message.assert_not_called()

    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "mark_sent"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "mark_processing"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "list_due_notifications"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "telegram_service."
        "send_message"
    )
    def test_real_delivery(
        self,
        send_message,
        list_due,
        mark_processing,
        mark_sent,
    ):
        list_due.return_value = [
            self._notification()
        ]

        send_message.return_value = {
            "ok": True
        }

        summary = (
            task_notification_worker
            .process_due_notifications(
                dry_run=False
            )
        )

        self.assertEqual(
            summary["sent"],
            1,
        )

        mark_processing \
            .assert_called_once_with(1)

        mark_sent \
            .assert_called_once_with(1)

    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "mark_error"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "mark_processing"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "scheduled_notification_service."
        "list_due_notifications"
    )
    @patch(
        "backend.workers."
        "task_notification_worker."
        "telegram_service."
        "send_message"
    )
    def test_delivery_error(
        self,
        send_message,
        list_due,
        mark_processing,
        mark_error,
    ):
        list_due.return_value = [
            self._notification()
        ]

        send_message.side_effect = (
            RuntimeError(
                "Telegram caído"
            )
        )

        summary = (
            task_notification_worker
            .process_due_notifications(
                dry_run=False
            )
        )

        self.assertEqual(
            summary["failed"],
            1,
        )

        mark_processing \
            .assert_called_once_with(1)

        mark_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()

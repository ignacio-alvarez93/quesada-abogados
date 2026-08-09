import unittest

from backend.services import (
    notification_message_service,
)


class NotificationMessageServiceTestCase(
    unittest.TestCase
):

    def test_task_message(self):
        message = (
            notification_message_service
            .build_notification_message(
                {
                    "source_type": "TASK",
                    "delivery_context": {
                        "source": {
                            "titulo":
                                "Presentar expediente",
                            "descripcion":
                                "Presentación Mercurio",
                            "cliente_nombre":
                                "MOHAMED",
                            "cliente_primer_apellido":
                                "PRUEBA",
                            "cliente_segundo_apellido":
                                "",
                            "numero_expediente":
                                "EXP-001",
                            "fecha_vencimiento":
                                "2026-01-13 12:00:00",
                            "prioridad":
                                "ALTA",
                        }
                    },
                }
            )
        )

        self.assertIn(
            "TAREA",
            message,
        )

        self.assertIn(
            "Presentar expediente",
            message,
        )

        self.assertIn(
            "MOHAMED PRUEBA",
            message,
        )

        self.assertIn(
            "EXP-001",
            message,
        )

        self.assertIn(
            "13/01/2026 12:00",
            message,
        )

    def test_alert_message(self):
        message = (
            notification_message_service
            .build_notification_message(
                {
                    "source_type": "ALERT",
                    "delivery_context": {
                        "source": {
                            "titulo":
                                "Caducan los penales",
                            "cliente_nombre":
                                "MOHAMED",
                            "cliente_primer_apellido":
                                "PRUEBA",
                            "numero_expediente":
                                "EXP-001",
                            "fecha_evento":
                                "2026-01-14 00:00:00",
                            "prioridad":
                                "URGENTE",
                        }
                    },
                }
            )
        )

        self.assertIn(
            "AVISO",
            message,
        )

        self.assertIn(
            "Caducan los penales",
            message,
        )

        self.assertIn(
            "14/01/2026",
            message,
        )

    def test_invalid_source(self):
        with self.assertRaises(
            ValueError
        ):
            (
                notification_message_service
                .build_notification_message(
                    {
                        "source_type":
                            "OTRO",
                        "delivery_context": {
                            "source": {}
                        },
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()

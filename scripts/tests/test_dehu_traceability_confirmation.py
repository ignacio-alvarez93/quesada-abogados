import unittest

from backend.services.email_platform import (
    dehu_notification_service,
)


class DehuTraceabilityConfirmationTest(
    unittest.TestCase
):
    def test_schema_contains_classification_columns(
        self,
    ):
        dehu_notification_service.ensure_dehu_schema()

        from backend.services.email_platform import (
            schema_service,
        )

        with schema_service.connection() as conn:
            columns = {
                row["name"]
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        dehu_notifications
                    )
                    """
                ).fetchall()
            }

        required = {
            "procedural_event_code",
            "procedural_event_label",
            "classification_status",
            "classification_source",
            "confirmed_event_id",
            "confirmed_justificante_id",
            "classification_confirmed_at",
            "classification_confirmed_by",
            "dehu_receipt_path",
            "dehu_receipt_name",
            "dehu_receipt_metadata_json",
        }

        self.assertTrue(
            required.issubset(columns),
            required - columns,
        )


if __name__ == "__main__":
    unittest.main()

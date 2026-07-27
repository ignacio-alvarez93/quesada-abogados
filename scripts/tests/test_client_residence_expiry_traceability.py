import unittest

from backend.services import (
    expedient_traceability_service
    as service,
)


class ClientResidenceExpiryDecisionTest(
    unittest.TestCase
):
    def test_creates_when_client_has_no_date(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "",
                "2031-05-14",
            )
        )

        self.assertEqual(
            result["status"],
            "CREATED",
        )
        self.assertTrue(
            result["should_update"]
        )

    def test_updates_when_new_date_is_later(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "2027-04-23",
                "2031-05-14",
            )
        )

        self.assertEqual(
            result["status"],
            "UPDATED",
        )
        self.assertTrue(
            result["should_update"]
        )

    def test_does_not_update_equal_date(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "2027-04-23",
                "2027-04-23",
            )
        )

        self.assertEqual(
            result["status"],
            "UNCHANGED",
        )
        self.assertFalse(
            result["should_update"]
        )

    def test_rejects_older_date(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "2031-05-14",
                "2027-04-23",
            )
        )

        self.assertEqual(
            result["status"],
            "CONFLICT_OLDER_DATE",
        )
        self.assertFalse(
            result["should_update"]
        )

    def test_accepts_display_date_format(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "",
                "14/05/2031",
            )
        )

        self.assertEqual(
            result["detected_date"],
            "2031-05-14",
        )

    def test_rejects_invalid_date(self):
        result = (
            service
            ._decide_client_residence_expiry_update(
                "",
                "fecha desconocida",
            )
        )

        self.assertEqual(
            result["status"],
            "NO_VALID_DATE",
        )
        self.assertFalse(
            result["should_update"]
        )


if __name__ == "__main__":
    unittest.main()

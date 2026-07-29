import unittest
from unittest.mock import patch

from backend.services.email_platform import (
    email_sync_orchestrator_service
    as orchestrator,
)


IONOS_ACCOUNT = {
    "id": 1,
    "email_address":
        "quesada@abogados-extranjeria.com",
    "provider": "IONOS_IMAP",
    "incoming_enabled": 1,
    "last_sync_cursor": "100",
    "last_sync_at": "",
    "last_sync_status": "OK",
    "last_sync_error": "",
}

GMAIL_ACCOUNT = {
    "id": 6,
    "email_address":
        "quesadaabogadosextranjeria@gmail.com",
    "provider": "GMAIL_API",
    "incoming_enabled": 1,
    "last_sync_cursor":
        "1785147296000",
    "last_sync_at": "",
    "last_sync_status": "OK",
    "last_sync_error": "",
}


class FakeProvider:
    def __init__(self, account):
        self.account = account

    def sync_incoming(self):
        return {
            "ok": True,
            "account_id":
                self.account["id"],
            "account_email":
                self.account[
                    "email_address"
                ],
            "uids_found": 4,
            "processed": [
                {
                    "uid": 101,
                    "status": "PROCESSED",
                    "expediente_id": 20,
                },
                {
                    "uid": 102,
                    "status":
                        "REVIEW_REQUIRED",
                    "expediente_id": None,
                },
                {
                    "uid": 103,
                    "status": "IGNORED",
                    "expediente_id": None,
                },
                {
                    "uid": 104,
                    "status": "PROCESSED",
                    "expediente_id": 21,
                },
            ],
            "errors": [],
            "last_cursor": "104",
        }


class EmailSyncOrchestratorTest(
    unittest.TestCase
):
    @patch(
        "backend.services.email_platform."
        "email_sync_orchestrator_service."
        "email_account_service."
        "get_active_incoming_accounts",
        return_value=[IONOS_ACCOUNT],
    )
    def test_ionos_status_compatibility(
        self,
        mocked_accounts,
    ):
        result = (
            orchestrator.get_ionos_status()
        )

        self.assertEqual(
            result["account_id"],
            1,
        )
        self.assertEqual(
            result["provider"],
            "IONOS_IMAP",
        )
        self.assertEqual(
            result["last_sync_cursor"],
            "100",
        )

        mocked_accounts.assert_called_once_with(
            provider="IONOS_IMAP"
        )

    @patch(
        "backend.services.email_platform."
        "email_sync_orchestrator_service."
        "email_account_service."
        "get_active_incoming_accounts",
        return_value=[GMAIL_ACCOUNT],
    )
    def test_generic_gmail_status(
        self,
        mocked_accounts,
    ):
        result = (
            orchestrator
            .get_provider_status(
                "GMAIL_API"
            )
        )

        self.assertEqual(
            result["account_id"],
            6,
        )
        self.assertEqual(
            result["provider_label"],
            "Gmail",
        )
        self.assertEqual(
            result["last_sync_cursor"],
            "1785147296000",
        )

        mocked_accounts.assert_called_once_with(
            provider="GMAIL_API"
        )

    @patch(
        "backend.services.email_platform."
        "email_sync_orchestrator_service."
        "email_account_service."
        "get_active_incoming_accounts",
        return_value=[IONOS_ACCOUNT],
    )
    def test_ionos_sync_returns_summary(
        self,
        mocked_accounts,
    ):
        result = (
            orchestrator
            .sync_ionos_extranjeria(
                provider_factory=FakeProvider
            )
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["busy"])
        self.assertEqual(
            result["provider"],
            "IONOS_IMAP",
        )
        self.assertEqual(
            result["applied_count"],
            2,
        )
        self.assertEqual(
            result[
                "review_required_count"
            ],
            1,
        )
        self.assertEqual(
            result["ignored_count"],
            1,
        )
        self.assertEqual(
            result["expedient_ids"],
            [20, 21],
        )

    @patch(
        "backend.services.email_platform."
        "email_sync_orchestrator_service."
        "email_account_service."
        "get_active_incoming_accounts",
        return_value=[GMAIL_ACCOUNT],
    )
    def test_gmail_sync_returns_summary(
        self,
        mocked_accounts,
    ):
        result = (
            orchestrator
            .sync_gmail_extranjeria(
                provider_factory=FakeProvider
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["provider"],
            "GMAIL_API",
        )
        self.assertEqual(
            result["provider_label"],
            "Gmail",
        )
        self.assertEqual(
            result["uids_found"],
            4,
        )
        self.assertEqual(
            result["applied_count"],
            2,
        )

    def test_busy_guard_is_shared(
        self,
    ):
        acquired = (
            orchestrator._SYNC_LOCK.acquire(
                blocking=False
            )
        )

        self.assertTrue(acquired)

        try:
            result = (
                orchestrator
                .sync_provider_extranjeria(
                    "GMAIL_API"
                )
            )

            self.assertTrue(
                result["busy"]
            )
            self.assertFalse(
                result["ok"]
            )
            self.assertEqual(
                result["provider"],
                "GMAIL_API",
            )

        finally:
            orchestrator._SYNC_LOCK.release()

    def test_unknown_provider_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            orchestrator.get_provider_status(
                "UNKNOWN"
            )


if __name__ == "__main__":
    unittest.main()

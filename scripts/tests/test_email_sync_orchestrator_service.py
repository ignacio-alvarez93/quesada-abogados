import unittest
from unittest.mock import patch

from backend.services.email_platform import (
    email_sync_orchestrator_service
    as orchestrator,
)


ACCOUNT = {
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


class FakeProvider:
    def __init__(self, account):
        self.account = account

    def sync_incoming(self):
        return {
            "ok": True,
            "account_id": 1,
            "account_email":
                ACCOUNT["email_address"],
            "uids_found": 4,
            "processed": [
                {
                    "uid": 101,
                    "status": "PROCESSED",
                    "expediente_id": 20,
                },
                {
                    "uid": 102,
                    "status": "REVIEW_REQUIRED",
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
        return_value=[ACCOUNT],
    )
    def test_status_uses_configured_account(
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
            result["last_sync_cursor"],
            "100",
        )
        mocked_accounts.assert_called_once()

    @patch(
        "backend.services.email_platform."
        "email_sync_orchestrator_service."
        "email_account_service."
        "get_active_incoming_accounts",
        return_value=[ACCOUNT],
    )
    def test_sync_returns_ui_summary(
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
            result["uids_found"],
            4,
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
        self.assertEqual(
            result["last_cursor"],
            "104",
        )

    def test_busy_guard(self):
        acquired = (
            orchestrator._SYNC_LOCK.acquire(
                blocking=False
            )
        )

        self.assertTrue(acquired)

        try:
            result = (
                orchestrator
                .sync_ionos_extranjeria()
            )

            self.assertTrue(
                result["busy"]
            )
            self.assertFalse(
                result["ok"]
            )
        finally:
            orchestrator._SYNC_LOCK.release()


if __name__ == "__main__":
    unittest.main()

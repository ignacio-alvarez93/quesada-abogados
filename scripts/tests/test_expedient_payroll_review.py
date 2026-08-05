import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_payroll_proposal_service
    as proposal_service,
)
from backend.services import (
    expedient_payroll_review_service
    as review_service,
)


def create_test_database(path):
    conn = sqlite3.connect(path)

    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE expedientes (
            id INTEGER PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            numero_expediente TEXT NOT NULL
        );

        INSERT INTO expedientes (
            id,
            cliente_id,
            numero_expediente
        )
        VALUES (
            45,
            1,
            'EXP-TEST-45'
        );
        """
    )

    conn.commit()
    conn.close()


def sample_bundle():
    return {
        "status": "EXTRACTED",
        "source_path": "nominas.pdf",
        "source_name": "nominas.pdf",
        "source_suffix": ".pdf",
        "sha256": "review-test-sha",
        "page_count": 3,
        "pages_with_text": 3,
        "requires_ocr": False,
        "requires_manual_review": True,
        "payroll_count": 3,
        "unclassified_pages": [],
        "warnings": [],
        "payrolls": [
            {
                "sequence": 1,
                "source_pages": [1],
                "source_page_start": 1,
                "source_page_end": 1,
                "period_year": 2026,
                "period_month": 4,
                "period_key": "2026-04",
                "employee_name": "JUAN PEREZ",
                "company_name": "EMPRESA SL",
                "net_pay_centimos": 120000,
                "confidence": 0.95,
                "field_confidence": {},
                "warnings": [],
                "review_status": (
                    "PENDIENTE_REVISION"
                ),
                "requires_manual_review": True,
            },
            {
                "sequence": 2,
                "source_pages": [2],
                "source_page_start": 2,
                "source_page_end": 2,
                "period_year": 2026,
                "period_month": 5,
                "period_key": "2026-05",
                "employee_name": "JUAN PEREZ",
                "company_name": "EMPRESA SL",
                "net_pay_centimos": 125000,
                "confidence": 0.95,
                "field_confidence": {},
                "warnings": [],
                "review_status": (
                    "PENDIENTE_REVISION"
                ),
                "requires_manual_review": True,
            },
            {
                "sequence": 3,
                "source_pages": [3],
                "source_page_start": 3,
                "source_page_end": 3,
                "period_year": 2026,
                "period_month": 6,
                "period_key": "2026-06",
                "employee_name": "JUAN PEREZ",
                "company_name": "EMPRESA SL",
                "net_pay_centimos": 130000,
                "confidence": 0.95,
                "field_confidence": {},
                "warnings": [],
                "review_status": (
                    "PENDIENTE_REVISION"
                ),
                "requires_manual_review": True,
            },
        ],
    }


class ExpedientPayrollReviewTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "test.db"
        )

        create_test_database(
            self.db_path
        )

        document = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.proposals = document[
            "proposals"
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_lists_expedient_proposals(self):
        items = (
            review_service
            .list_expedient_proposals(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            3,
        )
        self.assertEqual(
            items[0]["source_name"],
            "nominas.pdf",
        )

    def test_updates_period_and_amount(self):
        proposal_id = self.proposals[0][
            "id"
        ]

        result = (
            review_service.update_proposal(
                proposal_id,
                {
                    "period_month": 3,
                    "net_pay_centimos": 118000,
                },
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["period_key"],
            "2026-03",
        )
        self.assertEqual(
            result["net_pay_centimos"],
            118000,
        )

    def test_rejects_invalid_month(self):
        proposal_id = self.proposals[0][
            "id"
        ]

        with self.assertRaises(
            ValueError
        ):
            review_service.update_proposal(
                proposal_id,
                {
                    "period_month": 13,
                },
                db_path=self.db_path,
            )

    def test_rejects_negative_amount(self):
        proposal_id = self.proposals[0][
            "id"
        ]

        with self.assertRaises(
            ValueError
        ):
            review_service.update_proposal(
                proposal_id,
                {
                    "net_pay_centimos": -1,
                },
                db_path=self.db_path,
            )

    def test_confirms_proposal(self):
        proposal_id = self.proposals[0][
            "id"
        ]

        result = (
            review_service.confirm_proposal(
                proposal_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["review_status"],
            "CONFIRMADA",
        )
        self.assertEqual(
            result[
                "requires_manual_review"
            ],
            0,
        )
        self.assertTrue(
            result["reviewed_at"]
        )

    def test_discards_and_reopens_proposal(self):
        proposal_id = self.proposals[0][
            "id"
        ]

        discarded = (
            review_service.discard_proposal(
                proposal_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            discarded["review_status"],
            "DESCARTADA",
        )

        reopened = (
            review_service.reopen_proposal(
                proposal_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["review_status"],
            "PENDIENTE_REVISION",
        )
        self.assertEqual(
            reopened[
                "requires_manual_review"
            ],
            1,
        )

    def test_consolidates_confirmed_payrolls(self):
        for item in self.proposals:
            review_service.confirm_proposal(
                item["id"],
                db_path=self.db_path,
            )

        result = (
            review_service
            .consolidate_expedient_payrolls(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result[
                "confirmed_payroll_count"
            ],
            3,
        )
        self.assertEqual(
            result["periods"],
            [
                "2026-04",
                "2026-05",
                "2026-06",
            ],
        )
        self.assertEqual(
            result[
                "average_net_centimos"
            ],
            125000,
        )
        self.assertEqual(
            result[
                "minimum_net_centimos"
            ],
            120000,
        )
        self.assertEqual(
            result[
                "maximum_net_centimos"
            ],
            130000,
        )
        self.assertEqual(
            result[
                "suggested_monthly_"
                "income_centimos"
            ],
            125000,
        )
        self.assertTrue(
            result[
                "ready_for_application"
            ]
        )
        self.assertFalse(
            result[
                "applied_to_diagnosis"
            ]
        )

    def test_detects_missing_period(self):
        review_service.confirm_proposal(
            self.proposals[0]["id"],
            db_path=self.db_path,
        )
        review_service.confirm_proposal(
            self.proposals[2]["id"],
            db_path=self.db_path,
        )

        result = (
            review_service
            .consolidate_expedient_payrolls(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["missing_periods"],
            ["2026-05"],
        )

    def test_detects_duplicate_period(self):
        review_service.update_proposal(
            self.proposals[1]["id"],
            {
                "period_month": 4,
            },
            db_path=self.db_path,
        )

        review_service.confirm_proposal(
            self.proposals[0]["id"],
            db_path=self.db_path,
        )
        review_service.confirm_proposal(
            self.proposals[1]["id"],
            db_path=self.db_path,
        )

        result = (
            review_service
            .consolidate_expedient_payrolls(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["duplicate_periods"],
            ["2026-04"],
        )
        self.assertIsNone(
            result[
                "suggested_monthly_"
                "income_centimos"
            ]
        )
        self.assertFalse(
            result[
                "ready_for_application"
            ]
        )

    def test_pending_proposals_are_not_averaged(self):
        review_service.confirm_proposal(
            self.proposals[0]["id"],
            db_path=self.db_path,
        )

        result = (
            review_service
            .consolidate_expedient_payrolls(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result[
                "confirmed_payroll_count"
            ],
            1,
        )
        self.assertEqual(
            result[
                "average_net_centimos"
            ],
            120000,
        )
        self.assertEqual(
            result[
                "pending_review_count"
            ],
            2,
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_payroll_proposal_service
    as proposal_service,
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
        "sha256": "abc123",
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
                "field_confidence": {
                    "net_pay_centimos": 0.95,
                },
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


class ExpedientPayrollProposalPersistenceTest(
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

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_schema(self):
        proposal_service.ensure_schema(
            db_path=self.db_path
        )

        conn = sqlite3.connect(
            self.db_path
        )

        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        conn.close()

        self.assertIn(
            (
                "expedient_income_"
                "evidence_documents"
            ),
            tables,
        )
        self.assertIn(
            "expedient_payroll_proposals",
            tables,
        )

    def test_persists_one_document(self):
        result = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            result["already_exists"]
        )
        self.assertEqual(
            result["expediente_id"],
            45,
        )
        self.assertEqual(
            result["payroll_count"],
            3,
        )

    def test_persists_three_proposals(self):
        result = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(result["proposals"]),
            3,
        )
        self.assertEqual(
            [
                item["period_key"]
                for item in result[
                    "proposals"
                ]
            ],
            [
                "2026-04",
                "2026-05",
                "2026-06",
            ],
        )

    def test_preserves_net_values(self):
        result = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["net_pay_centimos"]
                for item in result[
                    "proposals"
                ]
            ],
            [
                120000,
                125000,
                130000,
            ],
        )

    def test_deduplicates_by_expedient_and_hash(
        self,
    ):
        first = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        second = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            first["id"],
            second["id"],
        )
        self.assertTrue(
            second["already_exists"]
        )
        self.assertEqual(
            len(second["proposals"]),
            3,
        )

    def test_rejects_unknown_expedient(self):
        with self.assertRaises(
            ValueError
        ):
            (
                proposal_service
                .persist_payroll_bundle(
                    999,
                    sample_bundle(),
                    db_path=self.db_path,
                )
            )

    def test_requires_sha256(self):
        bundle = sample_bundle()
        bundle["sha256"] = ""

        with self.assertRaises(
            ValueError
        ):
            (
                proposal_service
                .persist_payroll_bundle(
                    45,
                    bundle,
                    db_path=self.db_path,
                )
            )

    def test_does_not_write_diagnosis_fields(self):
        proposal_service.persist_payroll_bundle(
            45,
            sample_bundle(),
            db_path=self.db_path,
        )

        conn = sqlite3.connect(
            self.db_path
        )

        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        conn.close()

        self.assertNotIn(
            "expediente_datos_especificos",
            tables,
        )


    def test_deletes_document_and_proposals(self):
        document = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        result = (
            proposal_service
            .delete_payroll_document(
                document["id"],
                db_path=self.db_path,
            )
        )

        self.assertTrue(result["deleted"])
        self.assertEqual(
            result["deleted_proposal_count"],
            3,
        )
        self.assertFalse(
            result["physical_file_deleted"]
        )

        self.assertIsNone(
            proposal_service.get_document(
                document["id"],
                db_path=self.db_path,
            )
        )

        conn = sqlite3.connect(
            self.db_path
        )

        proposal_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM expedient_payroll_proposals
            WHERE document_id = ?
            """,
            (document["id"],),
        ).fetchone()[0]

        conn.close()

        self.assertEqual(
            proposal_count,
            0,
        )

    def test_allows_reloading_after_delete(self):
        first = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        proposal_service.delete_payroll_document(
            first["id"],
            db_path=self.db_path,
        )

        second = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            second["already_exists"]
        )
        self.assertNotEqual(
            first["id"],
            second["id"],
        )
        self.assertEqual(
            len(second["proposals"]),
            3,
        )

    def test_rejects_deleting_applied_document(self):
        document = (
            proposal_service
            .persist_payroll_bundle(
                45,
                sample_bundle(),
                db_path=self.db_path,
            )
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            UPDATE expedient_payroll_proposals
            SET review_status = 'APLICADA'
            WHERE document_id = ?
            """,
            (document["id"],),
        )

        conn.commit()
        conn.close()

        with self.assertRaisesRegex(
            ValueError,
            "contiene nóminas aplicadas",
        ):
            (
                proposal_service
                .delete_payroll_document(
                    document["id"],
                    db_path=self.db_path,
                )
            )

        self.assertIsNotNone(
            proposal_service.get_document(
                document["id"],
                db_path=self.db_path,
            )
        )


    def test_schema_cache_tracks_database_path(self):
        proposal_service.ensure_schema(
            db_path=self.db_path
        )

        cache_key = (
            proposal_service
            ._schema_cache_key(
                db_path=self.db_path
            )
        )

        self.assertIn(
            cache_key,
            proposal_service
            ._SCHEMA_READY_PATHS,
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

import flet as ft

from backend.services import (
    expedient_payroll_proposal_service
    as proposal_service,
)
from frontend.components import (
    expedient_payroll_panel
    as payroll_panel,
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
        "sha256": "panel-test-sha",
        "page_count": 2,
        "pages_with_text": 2,
        "requires_ocr": False,
        "requires_manual_review": True,
        "payroll_count": 2,
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
                "confidence": 0.90,
                "field_confidence": {},
                "warnings": [],
            },
        ],
    }


class ExpedientPayrollPanelTest(
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

    def test_formats_money(self):
        self.assertEqual(
            payroll_panel._money_centimos(
                125000
            ),
            "1.250,00 €",
        )

    def test_formats_period(self):
        self.assertEqual(
            payroll_panel._period_label(
                {
                    "period_year": 2026,
                    "period_month": 4,
                }
            ),
            "Abril 2026",
        )

    def test_loads_documents_and_proposals(self):
        proposal_service.persist_payroll_bundle(
            45,
            sample_bundle(),
            db_path=self.db_path,
        )

        documents = (
            payroll_panel._load_documents(
                45,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(documents),
            1,
        )
        self.assertEqual(
            len(
                documents[0]["proposals"]
            ),
            2,
        )
        self.assertEqual(
            documents[0]["source_name"],
            "nominas.pdf",
        )

    def test_builds_proposal_card(self):
        control = (
            payroll_panel._proposal_card(
                {
                    "sequence": 1,
                    "period_year": 2026,
                    "period_month": 4,
                    "employee_name": (
                        "JUAN PEREZ"
                    ),
                    "company_name": (
                        "EMPRESA SL"
                    ),
                    "net_pay_centimos": (
                        120000
                    ),
                    "confidence": 0.95,
                    "source_pages": [1],
                    "warnings": [],
                    "review_status": (
                        "PENDIENTE_REVISION"
                    ),
                }
            )
        )

        self.assertIsInstance(
            control,
            ft.Container,
        )


    def test_builds_pending_proposal_actions(self):
        control = payroll_panel._proposal_card(
            {
                "id": 11,
                "sequence": 1,
                "period_year": 2026,
                "period_month": 4,
                "net_pay_centimos": 120000,
                "confidence": 0.95,
                "source_pages": [1],
                "warnings": [],
                "review_status": (
                    "PENDIENTE_REVISION"
                ),
            },
            on_confirm=lambda value: value,
            on_discard=lambda value: value,
            on_reopen=lambda value: value,
        )

        self.assertIsInstance(
            control,
            ft.Container,
        )

        actions_row = (
            control.content.controls[-1]
        )

        self.assertIsInstance(
            actions_row,
            ft.Row,
        )
        self.assertEqual(
            len(actions_row.controls),
            2,
        )

    def test_builds_reopen_action(self):
        control = payroll_panel._proposal_card(
            {
                "id": 12,
                "sequence": 1,
                "period_year": 2026,
                "period_month": 4,
                "net_pay_centimos": 120000,
                "confidence": 0.95,
                "source_pages": [1],
                "warnings": [],
                "review_status": "DESCARTADA",
            },
            on_confirm=lambda value: value,
            on_discard=lambda value: value,
            on_reopen=lambda value: value,
        )

        actions_row = (
            control.content.controls[-1]
        )

        self.assertEqual(
            len(actions_row.controls),
            1,
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_payroll_application_service
    as application_service,
)
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

        CREATE TABLE config_formularios_expediente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_expediente_id INTEGER,
            subtipo_expediente_id INTEGER,
            codigo TEXT,
            nombre TEXT,
            descripcion TEXT,
            orden INTEGER DEFAULT 0,
            activo INTEGER DEFAULT 1
        );

        CREATE TABLE config_campos_formulario_expediente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formulario_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            etiqueta TEXT,
            tipo_campo TEXT,
            obligatorio INTEGER DEFAULT 0,
            opciones_json TEXT,
            placeholder TEXT,
            ayuda TEXT,
            valor_defecto TEXT,
            orden INTEGER DEFAULT 0,
            activo INTEGER DEFAULT 1,
            UNIQUE(formulario_id, codigo),
            FOREIGN KEY (formulario_id)
                REFERENCES config_formularios_expediente(id)
                ON DELETE CASCADE
        );

        CREATE TABLE expediente_datos_especificos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expediente_id INTEGER NOT NULL,
            formulario_id INTEGER NOT NULL,
            campo_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            valor TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(expediente_id, campo_id),
            FOREIGN KEY (expediente_id)
                REFERENCES expedientes(id)
                ON DELETE CASCADE,
            FOREIGN KEY (formulario_id)
                REFERENCES config_formularios_expediente(id),
            FOREIGN KEY (campo_id)
                REFERENCES config_campos_formulario_expediente(id)
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

        INSERT INTO config_formularios_expediente (
            id,
            codigo,
            nombre,
            activo
        )
        VALUES (
            7,
            'EX02',
            'Formulario EX02',
            1
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
        "sha256": "application-test-sha",
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
                "net_pay_centimos": 125000,
                "confidence": 0.95,
                "field_confidence": {},
                "warnings": [],
            },
            {
                "sequence": 3,
                "source_pages": [3],
                "source_page_start": 3,
                "source_page_end": 3,
                "period_year": 2026,
                "period_month": 6,
                "period_key": "2026-06",
                "net_pay_centimos": 130000,
                "confidence": 0.95,
                "field_confidence": {},
                "warnings": [],
            },
        ],
    }


class ExpedientPayrollApplicationTest(
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

        for proposal in self.proposals:
            review_service.confirm_proposal(
                proposal["id"],
                db_path=self.db_path,
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_applies_average_to_ex02(self):
        result = (
            application_service
            .apply_payroll_consolidation_to_expedient(
                45,
                7,
                expected_amount_centimos=125000,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["applied_value_centimos"],
            125000,
        )
        self.assertTrue(
            result["applied_to_diagnosis"]
        )

        conn = sqlite3.connect(
            self.db_path
        )

        value = conn.execute(
            """
            SELECT valor
            FROM expediente_datos_especificos
            WHERE expediente_id = 45
              AND codigo = ?
            """,
            (
                application_service
                .INCOME_FIELD_CODE,
            ),
        ).fetchone()[0]

        conn.close()

        self.assertEqual(
            value,
            "125000",
        )

    def test_marks_proposals_as_applied(self):
        application_service\
            .apply_payroll_consolidation_to_expedient(
                45,
                7,
                expected_amount_centimos=125000,
                db_path=self.db_path,
            )

        conn = sqlite3.connect(
            self.db_path
        )

        states = [
            row[0]
            for row in conn.execute(
                """
                SELECT review_status
                FROM expedient_payroll_proposals
                ORDER BY id
                """
            )
        ]

        conn.close()

        self.assertEqual(
            states,
            [
                "APLICADA",
                "APLICADA",
                "APLICADA",
            ],
        )

    def test_rejects_stale_expected_amount(self):
        with self.assertRaises(
            ValueError
        ):
            application_service\
                .apply_payroll_consolidation_to_expedient(
                    45,
                    7,
                    expected_amount_centimos=124999,
                    db_path=self.db_path,
                )

        conn = sqlite3.connect(
            self.db_path
        )

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM expediente_datos_especificos
            """
        ).fetchone()[0]

        states = [
            row[0]
            for row in conn.execute(
                """
                SELECT review_status
                FROM expedient_payroll_proposals
                ORDER BY id
                """
            )
        ]

        conn.close()

        self.assertEqual(count, 0)
        self.assertEqual(
            states,
            [
                "CONFIRMADA",
                "CONFIRMADA",
                "CONFIRMADA",
            ],
        )

    def test_requires_explicit_overwrite(self):
        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            INSERT INTO config_campos_formulario_expediente (
                formulario_id,
                codigo,
                etiqueta,
                tipo_campo
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                7,
                application_service
                .INCOME_FIELD_CODE,
                "Ingreso",
                "texto",
            ),
        )

        field_id = conn.execute(
            """
            SELECT id
            FROM config_campos_formulario_expediente
            WHERE formulario_id = 7
              AND codigo = ?
            """,
            (
                application_service
                .INCOME_FIELD_CODE,
            ),
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO expediente_datos_especificos (
                expediente_id,
                formulario_id,
                campo_id,
                codigo,
                valor
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                45,
                7,
                field_id,
                application_service
                .INCOME_FIELD_CODE,
                "140000",
            ),
        )

        conn.commit()
        conn.close()

        with self.assertRaises(
            ValueError
        ):
            application_service\
                .apply_payroll_consolidation_to_expedient(
                    45,
                    7,
                    expected_amount_centimos=125000,
                    db_path=self.db_path,
                )

        result = (
            application_service
            .apply_payroll_consolidation_to_expedient(
                45,
                7,
                expected_amount_centimos=125000,
                overwrite_existing=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result[
                "previous_value_centimos"
            ],
            140000,
        )

    def test_rejects_second_active_application(self):
        application_service\
            .apply_payroll_consolidation_to_expedient(
                45,
                7,
                expected_amount_centimos=125000,
                db_path=self.db_path,
            )

        with self.assertRaises(
            ValueError
        ):
            application_service\
                .apply_payroll_consolidation_to_expedient(
                    45,
                    7,
                    expected_amount_centimos=125000,
                    db_path=self.db_path,
                )

    def test_records_application_audit(self):
        result = (
            application_service
            .apply_payroll_consolidation_to_expedient(
                45,
                7,
                expected_amount_centimos=125000,
                applied_by="TEST",
                notes="Aplicación controlada",
                db_path=self.db_path,
            )
        )

        active = (
            application_service
            .get_active_application(
                45,
                7,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active["id"],
            result["id"],
        )
        self.assertEqual(
            active["proposal_ids"],
            [
                item["id"]
                for item in self.proposals
            ],
        )
        self.assertEqual(
            active["periods"],
            [
                "2026-04",
                "2026-05",
                "2026-06",
            ],
        )
        self.assertEqual(
            active["applied_by"],
            "TEST",
        )

    def test_rejects_missing_form(self):
        with self.assertRaises(
            ValueError
        ):
            application_service\
                .apply_payroll_consolidation_to_expedient(
                    45,
                    999,
                    expected_amount_centimos=125000,
                    db_path=self.db_path,
                )


if __name__ == "__main__":
    unittest.main()

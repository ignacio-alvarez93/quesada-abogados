from __future__ import annotations

import gc
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.services import internal_transfer_service
from backend.services import payment_reconciliation_service
from backend.services import profit_and_loss_service
from backend.services import suplido_service


BASE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY, nombre TEXT,
    primer_apellido TEXT, segundo_apellido TEXT
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, numero_expediente TEXT
);
CREATE TABLE eco_cobros (
    id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL,
    importe REAL NOT NULL, tipo_cobro TEXT NOT NULL,
    tipo_fiscal TEXT NOT NULL, fecha_cobro TEXT,
    expediente_id INTEGER, factura_id INTEGER,
    iva_porcentaje REAL DEFAULT 0, irpf_porcentaje REAL DEFAULT 0,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    activo INTEGER NOT NULL DEFAULT 1, updated_at TEXT
);
CREATE TABLE eco_facturas (
    id INTEGER PRIMARY KEY, numero_factura TEXT,
    base_imponible REAL, iva REAL, irpf REAL, total REAL,
    activo INTEGER, estado TEXT
);
CREATE TABLE eco_gastos (
    id INTEGER PRIMARY KEY, fecha_gasto TEXT,
    supplier_name_snapshot TEXT, proveedor TEXT, concepto TEXT,
    categoria TEXT, importe REAL, base_imponible_centimos INTEGER,
    iva_centimos INTEGER, otros_impuestos_centimos INTEGER,
    total_centimos INTEGER, iva_deducible INTEGER,
    porcentaje_deducible REAL, expense_category_code TEXT,
    expense_subcategory_code TEXT, tipo_justificante TEXT,
    activo INTEGER
);
CREATE TABLE worker_payrolls (
    id INTEGER PRIMARY KEY, salary_expense_id INTEGER, active INTEGER
);
CREATE TABLE labor_social_security_periods (
    id INTEGER PRIMARY KEY, employer_expense_id INTEGER, active INTEGER
);
CREATE TABLE eco_movimientos_importados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origen TEXT NOT NULL, importe REAL NOT NULL DEFAULT 0
);
CREATE TABLE bank_movements (
    id INTEGER PRIMARY KEY, amount_centimos INTEGER NOT NULL,
    operation_date TEXT, concept TEXT, bank_name TEXT,
    account_label TEXT, account_iban TEXT,
    review_status TEXT NOT NULL DEFAULT 'PENDING_MANUAL_REVIEW',
    movement_status TEXT NOT NULL DEFAULT 'READY',
    linked_payment_id INTEGER, linked_amount_centimos INTEGER DEFAULT 0,
    ignored_at TEXT, updated_at TEXT
);
CREATE TABLE eco_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad TEXT NOT NULL, entidad_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL, titulo TEXT NOT NULL,
    descripcion TEXT, estado_anterior TEXT, estado_nuevo TEXT,
    usuario TEXT, fecha_evento TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class EconomicIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(BASE_SCHEMA)
            conn.execute("INSERT INTO clientes(id, nombre) VALUES (1, 'Cliente')")
            conn.execute(
                """
                INSERT INTO eco_cobros(
                    id, cliente_id, importe, tipo_cobro, tipo_fiscal,
                    fecha_cobro, estado_conciliacion, activo
                )
                VALUES (
                    10, 1, 100, 'SUPLIDO_ADELANTADO', 'SUPLIDO',
                    '2026-07-23', 'PENDIENTE', 1
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO bank_movements(
                    id, amount_centimos, operation_date, concept,
                    bank_name, account_label, account_iban, review_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_MANUAL_REVIEW')
                """,
                [
                    (1, -12550, "2026-07-20", "Salida", "Santander", "Operativa", "ES01"),
                    (2, 12550, "2026-07-21", "Entrada", "ING", "Ahorro", "ES02"),
                    (3, 12550, "2026-07-21", "Misma", "Santander", "Operativa", "ES01"),
                    (4, 12000, "2026-07-21", "Descuadre", "ING", "Ahorro", "ES02"),
                    (5, -12550, "2026-07-22", "Otra salida", "Santander", "Otra", "ES03"),
                ],
            )
            conn.commit()
        suplido_service.ensure_schema(self.db_path)

    def tearDown(self) -> None:
        gc.collect()
        self.temp_dir.cleanup()

    def _movement(self, movement_id: int) -> sqlite3.Row:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "SELECT * FROM bank_movements WHERE id = ?",
                (movement_id,),
            ).fetchone()

    def test_suplido_payment_partial_complete_and_reversal(self) -> None:
        partial = payment_reconciliation_service.set_application(
            source_type="bank", source_movement_id=20,
            payment_id=10, amount_centimos=4000,
            db_path=self.db_path,
        )
        self.assertEqual(partial["status"], "PARCIAL")
        complete = payment_reconciliation_service.set_application(
            source_type="cashmatic", source_movement_id=21,
            payment_id=10, amount_centimos=6000,
            db_path=self.db_path,
        )
        self.assertEqual(complete["status"], "CONCILIADO")
        repeated = payment_reconciliation_service.sync_payment_status(
            10, db_path=self.db_path
        )
        self.assertEqual(repeated["applied_centimos"], 10000)
        reverted = payment_reconciliation_service.remove_application(
            source_type="cashmatic", source_movement_id=21,
            payment_id=10, db_path=self.db_path,
        )
        self.assertEqual(reverted["status"], "PARCIAL")
        pending = payment_reconciliation_service.remove_application(
            source_type="bank", source_movement_id=20,
            payment_id=10, db_path=self.db_path,
        )
        self.assertEqual(pending["status"], "PENDIENTE")

    def test_bank_reconciliation_is_independent_from_suplido_recovery(self) -> None:
        suplido_id = suplido_service.create_suplido(
            payment_date="2026-07-01", amount_centimos=10000,
            client_id=1, concept="Tasa", db_path=self.db_path,
        )
        payment_reconciliation_service.set_application(
            source_type="bank", source_movement_id=30,
            payment_id=10, amount_centimos=10000,
            db_path=self.db_path,
        )
        untouched = suplido_service.get_suplido(
            suplido_id, db_path=self.db_path
        )
        self.assertEqual(untouched["recovered_amount_centimos"], 0)
        self.assertEqual(untouched["status"], suplido_service.STATUS_PENDING)
        applied = suplido_service.apply_cobro_recovery(
            cobro_id=10, suplido_id=suplido_id,
            amount_centimos=10000, db_path=self.db_path,
        )
        self.assertEqual(
            applied["suplido"]["status"], suplido_service.STATUS_RECOVERED
        )

    def test_links_two_existing_movements(self) -> None:
        transfer = internal_transfer_service.link_existing_movements(
            source_type="bank", source_movement_id=1,
            destination_type="bank", destination_movement_id=2,
            db_path=self.db_path,
        )
        self.assertEqual(transfer["amount_centimos"], 12550)
        self.assertEqual(self._movement(1)["transfer_leg"], "SALIDA")
        self.assertEqual(self._movement(2)["transfer_leg"], "ENTRADA")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM eco_movimientos_importados"
                ).fetchone()[0],
                0,
            )

    def test_rejects_same_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "misma cuenta"):
            internal_transfer_service.link_existing_movements(
                source_type="bank", source_movement_id=1,
                destination_type="bank", destination_movement_id=3,
                db_path=self.db_path,
            )

    def test_rejects_amount_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "no cuadran"):
            internal_transfer_service.link_existing_movements(
                source_type="bank", source_movement_id=1,
                destination_type="bank", destination_movement_id=4,
                db_path=self.db_path,
            )

    def test_rejects_already_linked_movement(self) -> None:
        internal_transfer_service.link_existing_movements(
            source_type="bank", source_movement_id=1,
            destination_type="bank", destination_movement_id=2,
            db_path=self.db_path,
        )
        with self.assertRaisesRegex(ValueError, "ya está vinculado"):
            internal_transfer_service.link_existing_movements(
                source_type="bank", source_movement_id=5,
                destination_type="bank", destination_movement_id=2,
                db_path=self.db_path,
            )

    def test_unlink_restores_previous_states_and_keeps_trace(self) -> None:
        transfer = internal_transfer_service.link_existing_movements(
            source_type="bank", source_movement_id=1,
            destination_type="bank", destination_movement_id=2,
            db_path=self.db_path,
        )
        internal_transfer_service.unlink_internal_transfer(
            transfer["id"], reason="Prueba de reversión",
            db_path=self.db_path,
        )
        self.assertIsNone(self._movement(1)["internal_transfer_id"])
        self.assertIsNone(self._movement(2)["internal_transfer_id"])
        self.assertEqual(
            self._movement(1)["review_status"], "PENDING_MANUAL_REVIEW"
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM eco_eventos
                    WHERE tipo_evento = 'TRASPASO_DESVINCULADO'
                    """
                ).fetchone()[0],
                2,
            )

    def test_transfer_does_not_change_profit_and_loss(self) -> None:
        before = profit_and_loss_service.profit_and_loss_summary(
            db_path=self.db_path
        )
        internal_transfer_service.link_existing_movements(
            source_type="bank", source_movement_id=1,
            destination_type="bank", destination_movement_id=2,
            db_path=self.db_path,
        )
        after = profit_and_loss_service.profit_and_loss_summary(
            db_path=self.db_path
        )
        self.assertEqual(before["income"], after["income"])
        self.assertEqual(before["expenses"], after["expenses"])
        self.assertEqual(before["result_centimos"], after["result_centimos"])


if __name__ == "__main__":
    unittest.main()

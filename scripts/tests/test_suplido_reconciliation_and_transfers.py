from __future__ import annotations

import sqlite3
import tempfile
import unittest
import gc
from contextlib import closing
from pathlib import Path

from backend.services import internal_transfer_service
from backend.services import suplido_reconciliation_service
from backend.services import suplido_service


BASE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT,
    primer_apellido TEXT,
    segundo_apellido TEXT
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY,
    numero_expediente TEXT
);
CREATE TABLE bank_movements (id INTEGER PRIMARY KEY);
CREATE TABLE eco_cobros (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    importe REAL NOT NULL,
    tipo_fiscal TEXT NOT NULL,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    activo INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT
);
CREATE TABLE eco_movimientos_importados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origen TEXT NOT NULL,
    archivo_origen TEXT,
    fecha_operacion TEXT,
    fecha_valor TEXT,
    concepto TEXT,
    importe REAL NOT NULL DEFAULT 0,
    referencia TEXT,
    cuenta TEXT,
    tipo_movimiento TEXT,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    cobro_id INTEGER,
    gasto_id INTEGER,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE eco_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad TEXT NOT NULL,
    entidad_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    usuario TEXT,
    fecha_evento TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class EconomicIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(BASE_SCHEMA)
            conn.execute(
                "INSERT INTO clientes(id, nombre) VALUES (1, 'Cliente')"
            )
            conn.execute(
                """
                INSERT INTO eco_cobros(
                    id, cliente_id, importe, tipo_fiscal,
                    estado_conciliacion, activo
                )
                VALUES (10, 1, 100, 'SUPLIDO', 'PARCIAL', 1)
                """
            )
            conn.commit()
        suplido_service.ensure_schema(self.db_path)

    def tearDown(self) -> None:
        # sqlite3.Connection como context manager confirma/revierte,
        # pero algunos servicios legacy no lo cierran explícitamente.
        gc.collect()
        self.temp_dir.cleanup()

    def test_suplido_only_recovers_after_full_reconciliation(self) -> None:
        suplido_id = suplido_service.create_suplido(
            payment_date="2026-07-23",
            amount_centimos=10000,
            client_id=1,
            concept="Tasa",
            db_path=self.db_path,
        )
        partial = suplido_reconciliation_service.link_cobro_to_suplido(
            cobro_id=10,
            suplido_id=suplido_id,
            amount_centimos=10000,
            db_path=self.db_path,
        )
        self.assertEqual(partial["recovered_centimos"], 0)
        self.assertEqual(partial["status"], suplido_service.STATUS_PENDING)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE eco_cobros
                SET estado_conciliacion = 'CONCILIADO'
                WHERE id = 10
                """
            )
            conn.commit()
        synced = suplido_reconciliation_service.sync_for_cobro(
            10, db_path=self.db_path
        )
        self.assertEqual(synced[0]["status"], suplido_service.STATUS_RECOVERED)
        self.assertEqual(synced[0]["recovered_centimos"], 10000)

        repeated = suplido_reconciliation_service.sync_for_cobro(
            10, db_path=self.db_path
        )
        self.assertEqual(repeated[0]["recovered_centimos"], 10000)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE eco_cobros
                SET estado_conciliacion = 'PARCIAL'
                WHERE id = 10
                """
            )
            conn.commit()
        reverted = suplido_reconciliation_service.sync_for_cobro(
            10, db_path=self.db_path
        )
        self.assertEqual(reverted[0]["status"], suplido_service.STATUS_PENDING)
        self.assertEqual(reverted[0]["recovered_centimos"], 0)

    def test_transfer_has_two_balanced_non_economic_legs(self) -> None:
        source = internal_transfer_service.create_account(
            name="Santander", db_path=self.db_path
        )
        destination = internal_transfer_service.create_account(
            name="ING", db_path=self.db_path
        )
        transfer = internal_transfer_service.register_internal_transfer(
            transfer_date="2026-07-23",
            source_account_id=source,
            destination_account_id=destination,
            amount="125,50",
            reference="T-1",
            db_path=self.db_path,
        )
        self.assertEqual(transfer["amount_centimos"], 12550)
        self.assertEqual(transfer["status"], "CONCILIADO")

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            legs = conn.execute(
                """
                SELECT *
                FROM eco_movimientos_importados
                WHERE internal_transfer_id = ?
                ORDER BY id
                """,
                (transfer["id"],),
            ).fetchall()
            cobros = conn.execute(
                "SELECT COUNT(*) FROM eco_cobros"
            ).fetchone()[0]
        self.assertEqual(len(legs), 2)
        self.assertEqual(round(sum(row["importe"] for row in legs), 2), 0)
        self.assertEqual(
            {row["transfer_leg"] for row in legs}, {"SALIDA", "ENTRADA"}
        )
        self.assertTrue(
            all(row["estado_conciliacion"] == "CONCILIADO" for row in legs)
        )
        self.assertEqual(cobros, 1)

    def test_transfer_rejects_same_account(self) -> None:
        account = internal_transfer_service.create_account(
            name="Santander", db_path=self.db_path
        )
        with self.assertRaisesRegex(ValueError, "distintas"):
            internal_transfer_service.register_internal_transfer(
                transfer_date="2026-07-23",
                source_account_id=account,
                destination_account_id=account,
                amount="10",
                db_path=self.db_path,
            )


if __name__ == "__main__":
    unittest.main()

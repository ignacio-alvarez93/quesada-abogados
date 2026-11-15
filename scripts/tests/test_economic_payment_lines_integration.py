"""
ECO-ML-01C · Auditoría y regresión de cobros multilínea (integración).

Recorre servicio de cobros, conciliación, recuperación de suplidos,
facturación y tarjeta sobre un SQLite temporal. economic_service.DB_PATH
se redirige a un TemporaryDirectory y el resto de servicios recibe
db_path explícito: nunca se toca database/quesada.db.
"""

from __future__ import annotations

import gc
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from backend.services import economic_service
from backend.services import payment_reconciliation_service
from backend.services import suplido_reconciliation_service
from backend.services import suplido_service
from frontend.components import economic_payment_card


REAL_DB_PATH = (
    Path(__file__).resolve().parents[2] / "database" / "quesada.db"
).resolve()

BASE_SCHEMA = """
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY, nombre TEXT,
    primer_apellido TEXT, segundo_apellido TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, numero_expediente TEXT, cliente_id INTEGER
);
"""

FECHA = "2026-11-13"
CLIENTE_ID = 1
EXPEDIENTE_ID = 10
HOJA_ID = 5


def _linea(concepto, importe, tipo_economico, tipo_fiscal):
    return {
        "concepto": concepto,
        "importe": importe,
        "tipo_economico": tipo_economico,
        "tipo_fiscal": tipo_fiscal,
    }


ESCENARIO = [
    _linea("Provisión", "100,00", "PROVISION", "PROVISION"),
    _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
]


class EconomicPaymentLinesIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (Path(self.temp_dir.name) / "eco_ml_int.db").resolve()
        self.assertNotEqual(self.db_path, REAL_DB_PATH)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(BASE_SCHEMA)
            conn.execute(
                "INSERT INTO clientes(id, nombre) VALUES (?, 'Cliente')",
                (CLIENTE_ID,),
            )
            conn.execute(
                "INSERT INTO expedientes(id, numero_expediente, cliente_id) "
                "VALUES (?, 'EXP-1', ?)",
                (EXPEDIENTE_ID, CLIENTE_ID),
            )
            conn.commit()

        self.original_db_path = economic_service.DB_PATH
        economic_service.DB_PATH = self.db_path
        economic_service.initialize_economic_schema()
        from contextlib import closing as _eco_closing
        import sqlite3 as _eco_sqlite3
        from backend.services.economic_reconciliation.bank_import_service import ensure_bank_schema as _eco_ensure_bank_schema
        with _eco_closing(_eco_sqlite3.connect(self.db_path)) as _eco_bank_conn:
            _eco_ensure_bank_schema(_eco_bank_conn)
        # ECO_ML_FIXTURE_LINK_COLUMNS_V1
        from contextlib import closing as _closing
        import sqlite3 as _sqlite3
        from backend.services.economic_reconciliation.bank_link_service import _ensure_link_columns as _ensure_link_columns_test
        with _closing(_sqlite3.connect(self.db_path)) as _db_link_test:
            for _table_link_test in ("bank_movements", "cashmatic_movements"):
                if _db_link_test.execute("SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", ("table", _table_link_test)).fetchone():
                    _ensure_link_columns_test(_db_link_test, _table_link_test)
            _db_link_test.commit()
        suplido_service.ensure_schema(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO eco_hojas_encargo (
                    id, expediente_id, cliente_id, numero_hoja,
                    importe_bruto, importe_neto
                )
                VALUES (?, ?, ?, 'HE-2026-0001', 500, 500)
                """,
                (HOJA_ID, EXPEDIENTE_ID, CLIENTE_ID),
            )
            conn.commit()

    def tearDown(self) -> None:
        economic_service.DB_PATH = self.original_db_path
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _payload(self, **overrides):
        payload = {
            "cliente_id": CLIENTE_ID,
            "expediente_id": EXPEDIENTE_ID,
            "hoja_encargo_id": HOJA_ID,
            "fecha_cobro": FECHA,
            "forma_pago": "TRANSFERENCIA",
            "tipo_cobro": "PAGO_EXPEDIENTE",
            "facturable": 0,
            "iva_porcentaje": "0",
            "irpf_porcentaje": "0",
            "concepto": "",
            "recibo_ruta": "",
            "observaciones": "",
        }
        payload.update(overrides)
        return payload

    def _query(self, sql, params=()):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def _count(self, table, where="1 = 1", params=()):
        return self._query(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params
        )[0]["n"]

    def _cobro_row(self, cobro_id):
        return self._query(
            "SELECT * FROM eco_cobros WHERE id = ?", (cobro_id,)
        )[0]

    def _crear_escenario(self, **overrides):
        return economic_service.create_cobro(
            self._payload(lineas=ESCENARIO, importe="138,28", **overrides)
        )

    def _insert_cobro_legacy(self, importe, tipo_fiscal="PROVISION", **extra):
        """Cobro preexistente escrito antes de ECO-ML-01 (sin detalle)."""
        values = {
            "numero_cobro": "COB-2025-0001",
            "fecha_cobro": "2025-06-01",
            "cliente_id": CLIENTE_ID,
            "expediente_id": EXPEDIENTE_ID,
            "hoja_encargo_id": HOJA_ID,
            "importe": importe,
            "forma_pago": "TRANSFERENCIA",
            "concepto": "PAGO LEGACY",
            "tipo_cobro": "PAGO_EXPEDIENTE",
            "tipo_fiscal": tipo_fiscal,
        }
        values.update(extra)
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                f"INSERT INTO eco_cobros ({columns}) VALUES ({marks})",
                tuple(values.values()),
            )
            conn.commit()
            return cur.lastrowid

    def _insert_factura(self, cobro_id, *, estado, exportada_holded, total):
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                """
                INSERT INTO eco_facturas (
                    numero_factura, fecha_factura, cliente_id,
                    base_imponible, iva, irpf, suplidos, total,
                    estado, exportada_holded, activo
                )
                VALUES ('FRA-2025-0001', '2025-06-01', ?, ?, 0, 0, 0, ?, ?, ?, 1)
                """,
                (CLIENTE_ID, total, total, estado, exportada_holded),
            )
            factura_id = cur.lastrowid
            conn.execute(
                "UPDATE eco_cobros SET factura_id = ? WHERE id = ?",
                (factura_id, cobro_id),
            )
            conn.execute(
                "INSERT INTO eco_factura_cobros (factura_id, cobro_id, importe_asignado) "
                "VALUES (?, ?, ?)",
                (factura_id, cobro_id, total),
            )
            conn.commit()
            return factura_id

    def _factura(self, factura_id):
        return self._query(
            "SELECT total, base_imponible, estado, exportada_holded "
            "FROM eco_facturas WHERE id = ?",
            (factura_id,),
        )[0]

    # ------------------------------------------------------------
    # 1 · E2E escenario vinculante + conciliación única
    # ------------------------------------------------------------

    def test_e2e_alta_y_conciliacion_de_un_solo_cobro(self) -> None:
        cobro_id = self._crear_escenario(facturable=1, iva_porcentaje="21")

        self.assertEqual(self._count("eco_cobros"), 1)
        self.assertEqual(self._count("eco_cobro_lineas", "cobro_id = ?", (cobro_id,)), 2)
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["numero_cobro"], "COB-2026-0001")
        self.assertEqual(row["importe"], 138.28)
        self.assertEqual(row["tipo_fiscal"], "MIXTO")
        self.assertEqual(row["estado_conciliacion"], "PENDIENTE")

        # Una transferencia única de 138,28 contra el recibo de 138,28.
        totals = payment_reconciliation_service.set_application(
            source_type="bank",
            source_movement_id=700,
            payment_id=cobro_id,
            amount_centimos=13828,
            client_id=CLIENTE_ID,
            db_path=self.db_path,
        )
        self.assertEqual(totals["total_centimos"], 13828)
        self.assertEqual(totals["applied_centimos"], 13828)
        self.assertEqual(totals["pending_centimos"], 0)
        self.assertEqual(totals["status"], "CONCILIADO")

        aplicaciones = self._query(
            "SELECT source_type, source_movement_id, payment_id, amount_centimos "
            "FROM economic_reconciliation_applications"
        )
        self.assertEqual(
            aplicaciones,
            [
                {
                    "source_type": "bank",
                    "source_movement_id": 700,
                    "payment_id": cobro_id,
                    "amount_centimos": 13828,
                }
            ],
        )
        self.assertEqual(self._cobro_row(cobro_id)["estado_conciliacion"], "CONCILIADO")

        # Lectura de servicio tras conciliar: desglose intacto y una
        # única factura MIXTO que la conciliación no altera.
        cobro = economic_service.get_cobro(cobro_id)
        self.assertEqual(cobro["num_lineas"], 2)
        self.assertEqual(cobro["importe_centimos"], 13828)
        self.assertEqual(
            sum(l["importe_centimos"] for l in cobro["lineas"]),
            cobro["importe_centimos"],
        )
        self.assertEqual(self._count("eco_facturas"), 1)
        self.assertEqual(
            self._query(
                "SELECT base_imponible, iva, irpf, suplidos, total, tipo_fiscal "
                "FROM eco_facturas WHERE id = ?",
                (self._cobro_row(cobro_id)["factura_id"],),
            )[0],
            {
                "base_imponible": 82.64,
                "iva": 17.36,
                "irpf": 0.0,
                "suplidos": 38.28,
                "total": 138.28,
                "tipo_fiscal": "MIXTO",
            },
        )

        # La tarjeta muestra MIXTO, no PROVISION.
        self.assertEqual(economic_payment_card._fiscal_status(cobro), "MIXTO")
        listado = economic_service.list_cobros()
        self.assertEqual(
            economic_payment_card._fiscal_status(listado[0]), "MIXTO"
        )

    # ------------------------------------------------------------
    # 2 · Retrocompatibilidad legacy
    # ------------------------------------------------------------

    def test_cobro_legacy_preexistente_legible_editable_y_conciliable(self) -> None:
        # REAL heredado con ruido binario: 0.1 + 0.2.
        cobro_id = self._insert_cobro_legacy(0.1 + 0.2)

        cobro = economic_service.get_cobro(cobro_id)
        self.assertTrue(cobro["lineas_sinteticas"])
        self.assertEqual(cobro["num_lineas"], 1)
        self.assertEqual(cobro["importe_centimos"], 30)
        self.assertEqual(cobro["resumen_fiscal"], "PROVISION")
        self.assertEqual(economic_payment_card._fiscal_status(cobro), "PROVISION")

        listado = economic_service.list_cobros()
        self.assertEqual([c["id"] for c in listado], [cobro_id])
        self.assertTrue(listado[0]["lineas_sinteticas"])

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                fecha_cobro="2025-06-01",
                importe="45,10",
                concepto="Pago legacy",
            ),
        )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 45.1)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)

        totals = payment_reconciliation_service.set_application(
            source_type="bank",
            source_movement_id=701,
            payment_id=cobro_id,
            amount_centimos=4510,
            db_path=self.db_path,
        )
        self.assertEqual(totals["status"], "CONCILIADO")

    def test_facturable_invoca_facturacion_una_vez_por_guardado(self) -> None:
        # Comportamiento de develop (1267740) mantenido por Dirección:
        # una invocación por alta/edición facturable, nunca por línea.
        with mock.patch.object(
            economic_service,
            "_crear_factura_automatica_por_cobro",
            wraps=economic_service._crear_factura_automatica_por_cobro,
        ) as auto:
            multilinea = self._crear_escenario(facturable=1, iva_porcentaje="21")
            legacy = economic_service.create_cobro(
                self._payload(importe="50", facturable=1, iva_porcentaje="21")
            )
            economic_service.update_cobro(
                multilinea,
                self._payload(
                    lineas=ESCENARIO
                    + [_linea("Honorarios", "10", "HONORARIOS", "PROVISION")],
                    facturable=1,
                    iva_porcentaje="21",
                ),
            )
            economic_service.update_cobro(
                legacy,
                self._payload(importe="60", facturable=1, iva_porcentaje="21"),
            )

        self.assertEqual(auto.call_count, 4)
        self.assertEqual(self._count("eco_facturas"), 2)
        self.assertEqual(self._count("eco_factura_cobros"), 2)
        self.assertEqual(
            self._count("eco_cobros", "factura_id IS NOT NULL"), 2
        )
        totales = {
            row["cobro_id"]: (row["total"], row["suplidos"], row["tipo_fiscal"])
            for row in self._query(
                "SELECT fc.cobro_id, f.total, f.suplidos, f.tipo_fiscal "
                "FROM eco_factura_cobros fc "
                "JOIN eco_facturas f ON f.id = fc.factura_id"
            )
        }
        self.assertEqual(
            totales,
            {
                multilinea: (148.28, 38.28, "MIXTO"),
                legacy: (60.0, 0.0, "PROVISION"),
            },
        )

    def test_no_facturable_no_invoca_facturacion(self) -> None:
        with mock.patch.object(
            economic_service,
            "_crear_factura_automatica_por_cobro",
            side_effect=AssertionError("facturación sin facturable"),
        ) as auto:
            cobro_id = self._crear_escenario(facturable=0, iva_porcentaje="21")
            economic_service.update_cobro(
                cobro_id,
                self._payload(lineas=ESCENARIO, facturable=0),
            )
        self.assertEqual(auto.call_count, 0)
        self.assertEqual(self._count("eco_facturas"), 0)

    def test_factura_congelada_o_anulada_bloquea_edicion_legacy(self) -> None:
        for estado, exportada in (("APROBADA", 1), ("ANULADA", 0)):
            with self.subTest(estado=estado):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute("DELETE FROM eco_factura_cobros")
                    conn.execute("DELETE FROM eco_cobros")
                    conn.execute("DELETE FROM eco_facturas")
                    conn.commit()
                cobro_id = self._insert_cobro_legacy(75.5)
                factura_id = self._insert_factura(
                    cobro_id, estado=estado, exportada_holded=exportada, total=75.5
                )
                antes = self._factura(factura_id)

                for cambio in (
                    {"importe": "80"},
                    {"importe": "75,50", "observaciones": "solo nota"},
                    {"lineas": ESCENARIO},
                ):
                    with self.assertRaisesRegex(ValueError, estado.lower()):
                        economic_service.update_cobro(
                            cobro_id,
                            self._payload(fecha_cobro="2025-06-01", **cambio),
                        )

                self.assertEqual(self._factura(factura_id), antes)
                self.assertEqual(self._cobro_row(cobro_id)["importe"], 75.5)
                self.assertEqual(self._count("eco_cobro_lineas"), 0)

    def test_factura_pendiente_bloquea_convertir_legacy_a_mixto(self) -> None:
        cobro_id = self._insert_cobro_legacy(138.28)
        factura_id = self._insert_factura(
            cobro_id, estado="EMITIDA", exportada_holded=0, total=138.28
        )
        antes = self._factura(factura_id)

        # Mismo total, pero el desglose fiscal pasaría a MIXTO.
        with self.assertRaisesRegex(ValueError, "no se recalcula"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    fecha_cobro="2025-06-01", lineas=ESCENARIO, importe="138,28"
                ),
            )
        self.assertEqual(self._factura(factura_id), antes)
        self.assertEqual(self._cobro_row(cobro_id)["tipo_fiscal"], "PROVISION")
        self.assertEqual(self._count("eco_cobro_lineas"), 0)

    def test_saldo_de_conciliacion_al_cambiar_total(self) -> None:
        cobro_id = self._crear_escenario()
        payment_reconciliation_service.set_application(
            source_type="bank",
            source_movement_id=702,
            payment_id=cobro_id,
            amount_centimos=10000,
            db_path=self.db_path,
        )
        self.assertEqual(self._cobro_row(cobro_id)["estado_conciliacion"], "PARCIAL")

        # No puede quedar conciliado más que el nuevo total (99,99 < 100,00).
        with self.assertRaisesRegex(ValueError, "conciliados"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    lineas=[
                        _linea("Provisión", "61,71", "PROVISION", "PROVISION"),
                        _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                    ]
                ),
            )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 138.28)
        self.assertEqual(self._count("eco_cobro_lineas"), 2)

        # Igualar exactamente lo conciliado deja el cobro CONCILIADO.
        economic_service.update_cobro(
            cobro_id,
            self._payload(
                lineas=[
                    _linea("Provisión", "61,72", "PROVISION", "PROVISION"),
                    _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                ]
            ),
        )
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 100.0)
        self.assertEqual(row["estado_conciliacion"], "CONCILIADO")
        totals = payment_reconciliation_service.reconciliation_totals(
            cobro_id, db_path=self.db_path
        )
        self.assertEqual(totals["status"], "CONCILIADO")
        self.assertEqual(totals["pending_centimos"], 0)

    def test_iva_no_se_aplica_a_cobros_solo_suplido(self) -> None:
        multilinea = economic_service.create_cobro(
            self._payload(
                hoja_encargo_id=None,
                facturable=1,
                iva_porcentaje="21",
                lineas=[
                    _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                    _linea("Registro", "12,00", "OTRO", "SUPLIDO"),
                ],
            )
        )
        row = self._cobro_row(multilinea)
        self.assertEqual(row["tipo_fiscal"], "SUPLIDO")
        self.assertEqual(row["iva_porcentaje"], 0.0)
        self.assertEqual(row["importe"], 50.28)

        legacy = economic_service.create_cobro(
            self._payload(
                importe="20",
                tipo_fiscal="SUPLIDO",
                facturable=1,
                iva_porcentaje="21",
            )
        )
        self.assertEqual(self._cobro_row(legacy)["iva_porcentaje"], 0.0)

    # ------------------------------------------------------------
    # 3 · Céntimos, integridad y rollback
    # ------------------------------------------------------------

    def test_importe_global_exacto_al_centimo(self) -> None:
        casos = (
            (["0,10", "0,10", "0,10"], 30, 0.3),
            (["1.234,56", "0,01"], 123457, 1234.57),
            (["33,33", "33,33", "33,34"], 10000, 100.0),
        )
        for importes, centimos, euros in casos:
            with self.subTest(importes=importes):
                cobro_id = economic_service.create_cobro(
                    self._payload(
                        lineas=[
                            _linea(f"L{i}", imp, "PROVISION", "PROVISION")
                            for i, imp in enumerate(importes, start=1)
                        ]
                    )
                )
                self.assertEqual(self._cobro_row(cobro_id)["importe"], euros)
                self.assertEqual(
                    self._query(
                        "SELECT SUM(importe_centimos) AS s FROM eco_cobro_lineas "
                        "WHERE cobro_id = ?",
                        (cobro_id,),
                    )[0]["s"],
                    centimos,
                )
                self.assertEqual(
                    economic_service.get_cobro(cobro_id)["importe_centimos"],
                    centimos,
                )

    def test_importe_del_frontend_no_se_confia(self) -> None:
        # El total viene de las líneas; un importe declarado distinto se rechaza.
        for declarado in ("138,27", "138,281", "-138,28"):
            with self.subTest(declarado=declarado):
                with self.assertRaises(ValueError):
                    economic_service.create_cobro(
                        self._payload(lineas=ESCENARIO, importe=declarado)
                    )
        self.assertEqual(self._count("eco_cobros"), 0)

    def test_rollback_si_falla_un_paso_posterior_a_las_lineas(self) -> None:
        with mock.patch.object(
            economic_service,
            "ensure_expediente_cliente",
            side_effect=sqlite3.OperationalError("fallo simulado tras líneas"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self._crear_escenario(facturable=1)

        self.assertEqual(self._count("eco_cobros"), 0)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)
        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_eventos"), 0)

        # La numeración no deja huecos tras el rollback.
        cobro_id = self._crear_escenario()
        self.assertEqual(self._cobro_row(cobro_id)["numero_cobro"], "COB-2026-0001")

    def test_rollback_edicion_si_falla_un_paso_posterior(self) -> None:
        cobro_id = self._crear_escenario()
        with mock.patch.object(
            economic_service,
            "ensure_expediente_cliente",
            side_effect=sqlite3.OperationalError("fallo simulado tras líneas"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                economic_service.update_cobro(
                    cobro_id,
                    self._payload(
                        lineas=[_linea("Provisión", "5", "PROVISION", "PROVISION")]
                    ),
                )

        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 138.28)
        self.assertEqual(row["tipo_fiscal"], "MIXTO")
        self.assertEqual(
            [
                l["importe_centimos"]
                for l in self._query(
                    "SELECT importe_centimos FROM eco_cobro_lineas "
                    "WHERE cobro_id = ? ORDER BY posicion",
                    (cobro_id,),
                )
            ],
            [10000, 3828],
        )

    def test_integridad_referencial_de_lineas(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO eco_cobro_lineas (
                        cobro_id, posicion, concepto,
                        tipo_economico, tipo_fiscal, importe_centimos
                    )
                    VALUES (999, 1, 'Huérfana', 'OTRO', 'PROVISION', 100)
                    """
                )

        cobro_id = self._crear_escenario()
        with closing(sqlite3.connect(self.db_path)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO eco_cobro_lineas (
                        cobro_id, posicion, concepto,
                        tipo_economico, tipo_fiscal, importe_centimos
                    )
                    VALUES (?, 1, 'Duplicada', 'OTRO', 'PROVISION', 100)
                    """,
                    (cobro_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO eco_cobro_lineas (
                        cobro_id, posicion, concepto,
                        tipo_economico, tipo_fiscal, importe_centimos
                    )
                    VALUES (?, 3, 'Mixta', 'OTRO', 'MIXTO', 100)
                    """,
                    (cobro_id,),
                )

    # ------------------------------------------------------------
    # 4 · Lectores que podrían colapsar MIXTO a PROVISION
    # ------------------------------------------------------------

    def test_cobro_mixto_no_entra_en_recuperacion_de_suplidos(self) -> None:
        mixto = self._crear_escenario()
        adelantado = economic_service.create_cobro(
            self._payload(
                tipo_cobro="SUPLIDO_ADELANTADO",
                hoja_encargo_id=None,
                lineas=[
                    _linea("Notaría", "60", "OTRO", "SUPLIDO"),
                    _linea("Registro", "40", "OTRO", "SUPLIDO"),
                ],
            )
        )
        self.assertEqual(self._cobro_row(adelantado)["tipo_fiscal"], "SUPLIDO")

        pendientes = payment_reconciliation_service.list_pending_advanced_payments(
            CLIENTE_ID, db_path=self.db_path
        )
        self.assertEqual([c["id"] for c in pendientes], [adelantado])

        with closing(sqlite3.connect(self.db_path)) as conn:
            suplido_id = conn.execute(
                """
                INSERT INTO economic_suplidos (
                    payment_date, amount_centimos, client_id, concept
                )
                VALUES (?, 3828, ?, 'Tasa adelantada')
                """,
                (FECHA, CLIENTE_ID),
            ).lastrowid
            conn.commit()

        with self.assertRaisesRegex(ValueError, "SUPLIDO_ADELANTADO"):
            suplido_reconciliation_service.link_cobro_to_suplido(
                cobro_id=mixto,
                suplido_id=suplido_id,
                amount_centimos=3828,
                db_path=self.db_path,
            )
        self.assertEqual(
            self._count("economic_suplido_recovery_applications"), 0
        )

    def test_factura_expresa_incoherente_de_cobro_mixto_sin_efectos(self) -> None:
        # 100 + 21 IVA + 38,28 = 159,28 != 138,28 cobrados.
        cobro_id = self._crear_escenario(iva_porcentaje="21")

        with self.assertRaisesRegex(ValueError, "no cuadra"):
            economic_service.create_factura(
                {
                    "cliente_id": CLIENTE_ID,
                    "expediente_id": EXPEDIENTE_ID,
                    "fecha_factura": FECHA,
                    "estado": "BORRADOR",
                    "base_imponible": "100",
                    "iva": "21",
                    "suplidos": "38,28",
                },
                cobro_ids=[cobro_id],
            )

        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_factura_cobros"), 0)
        self.assertIsNone(self._cobro_row(cobro_id)["factura_id"])
        self.assertEqual(self._cobro_row(cobro_id)["tipo_fiscal"], "MIXTO")

    def test_factura_congelada_bloquea_edicion_facturable(self) -> None:
        for estado, exportada in (("APROBADA", 1), ("ANULADA", 0)):
            with self.subTest(estado=estado):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute("DELETE FROM eco_factura_cobros")
                    conn.execute("DELETE FROM eco_cobros")
                    conn.execute("DELETE FROM eco_facturas")
                    conn.commit()
                cobro_id = self._insert_cobro_legacy(75.5, facturable=1)
                factura_id = self._insert_factura(
                    cobro_id, estado=estado, exportada_holded=exportada, total=75.5
                )
                antes = self._factura(factura_id)

                with self.assertRaisesRegex(ValueError, estado.lower()):
                    economic_service.update_cobro(
                        cobro_id,
                        self._payload(
                            fecha_cobro="2025-06-01",
                            facturable=1,
                            iva_porcentaje="21",
                            lineas=ESCENARIO,
                        ),
                    )
                self.assertEqual(self._factura(factura_id), antes)
                self.assertEqual(self._count("eco_facturas"), 1)
                self.assertEqual(self._count("eco_cobro_lineas"), 0)


if __name__ == "__main__":
    unittest.main()

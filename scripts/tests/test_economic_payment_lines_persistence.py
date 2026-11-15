"""
ECO-ML-01A · Persistencia del desglose de cobros.

Todo ocurre en un SQLite temporal: economic_service.DB_PATH se redirige
a un TemporaryDirectory y nunca se toca database/quesada.db.
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


class EconomicPaymentLinesPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (Path(self.temp_dir.name) / "eco_ml.db").resolve()
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

        # Bootstrap existente; dos veces para verificar idempotencia.
        economic_service.initialize_economic_schema()
        economic_service.initialize_economic_schema()

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

    def _lineas(self, cobro_id):
        return self._query(
            """
            SELECT posicion, concepto, tipo_economico, tipo_fiscal,
                   importe_centimos
            FROM eco_cobro_lineas
            WHERE cobro_id = ?
            ORDER BY posicion
            """,
            (cobro_id,),
        )

    def _cobro_row(self, cobro_id):
        return self._query(
            "SELECT * FROM eco_cobros WHERE id = ?", (cobro_id,)
        )[0]

    def _crear_escenario(self, **overrides):
        return economic_service.create_cobro(
            self._payload(lineas=ESCENARIO, importe="138,28", **overrides)
        )

    # ------------------------------------------------------------
    # A · Alta 100 + 38,28 = 138,28
    # ------------------------------------------------------------

    def test_alta_escenario_vinculante_un_solo_cobro(self) -> None:
        cobro_id = self._crear_escenario(facturable=1, iva_porcentaje="21")

        self.assertEqual(self._count("eco_cobros"), 1)
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 138.28)
        self.assertEqual(row["numero_cobro"], "COB-2026-0001")
        self.assertEqual(row["tipo_fiscal"], "MIXTO")
        self.assertEqual(row["concepto"], "PROVISIÓN + TASA")

        # Persistencia leída desde una conexión nueva ("reinicio").
        self.assertEqual(
            self._lineas(cobro_id),
            [
                {
                    "posicion": 1,
                    "concepto": "PROVISIÓN",
                    "tipo_economico": "PROVISION",
                    "tipo_fiscal": "PROVISION",
                    "importe_centimos": 10000,
                },
                {
                    "posicion": 2,
                    "concepto": "TASA",
                    "tipo_economico": "TASA",
                    "tipo_fiscal": "SUPLIDO",
                    "importe_centimos": 3828,
                },
            ],
        )

        # H · facturable emite una única factura MIXTO (comportamiento
        # operativo de develop 1267740 con fiscalidad por línea).
        self.assertIsNotNone(row["factura_id"])
        self.assertEqual(self._count("eco_facturas"), 1)
        self.assertEqual(
            self._factura(row["factura_id"]),
            {
                "base_imponible": 82.64,
                "iva": 17.36,
                "irpf": 0.0,
                "suplidos": 38.28,
                "total": 138.28,
                "tipo_fiscal": "MIXTO",
                "estado": "EMITIDA",
            },
        )
        self.assertEqual(
            self._query(
                "SELECT factura_id, cobro_id, importe_asignado "
                "FROM eco_factura_cobros"
            ),
            [
                {
                    "factura_id": row["factura_id"],
                    "cobro_id": cobro_id,
                    "importe_asignado": 138.28,
                }
            ],
        )

        cobro = economic_service.get_cobro(cobro_id)
        self.assertEqual(cobro["num_lineas"], 2)
        self.assertEqual(cobro["resumen_lineas"], "2 conceptos")
        self.assertFalse(cobro["lineas_sinteticas"])
        self.assertEqual(cobro["importe_centimos"], 13828)
        self.assertEqual(cobro["resumen_fiscal"], "MIXTO")
        self.assertEqual(
            cobro["desglose_fiscal_centimos"],
            {"PROVISION": 10000, "SUPLIDO": 3828},
        )
        self.assertEqual(
            [l["importe_formateado"] for l in cobro["lineas"]],
            ["100,00", "38,28"],
        )

        listado = economic_service.list_cobros()
        self.assertEqual(len(listado), 1)
        self.assertEqual(listado[0]["num_lineas"], 2)

        evento = self._query(
            "SELECT descripcion FROM eco_eventos "
            "WHERE entidad = 'ECO_COBROS' AND tipo_evento = 'CREACION'"
        )
        self.assertEqual(len(evento), 1)
        self.assertIn("138.28", evento[0]["descripcion"])
        self.assertIn("38,28", evento[0]["descripcion"])

    def test_importe_declarado_distinto_de_la_suma_se_rechaza(self) -> None:
        with self.assertRaisesRegex(ValueError, "no coincide"):
            economic_service.create_cobro(
                self._payload(lineas=ESCENARIO, importe="138,29")
            )
        self.assertEqual(self._count("eco_cobros"), 0)

    # ------------------------------------------------------------
    # B · Edición
    # ------------------------------------------------------------

    def test_edicion_modifica_anade_y_elimina_lineas(self) -> None:
        cobro_id = self._crear_escenario()

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                lineas=[
                    _linea("Provisión", "120", "PROVISION", "PROVISION"),
                    _linea("Tasa modelo 790", "38,28", "TASA", "SUPLIDO"),
                    _linea("Honorarios", "10,50", "HONORARIOS", "PROVISION"),
                ]
            ),
        )
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 168.78)
        self.assertEqual(
            [l["importe_centimos"] for l in self._lineas(cobro_id)],
            [12000, 3828, 1050],
        )

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                lineas=[_linea("Provisión", "50", "PROVISION", "PROVISION")]
            ),
        )
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 50.0)
        self.assertEqual(row["tipo_fiscal"], "PROVISION")
        self.assertEqual(len(self._lineas(cobro_id)), 1)
        self.assertEqual(self._count("eco_cobros"), 1)
        self.assertEqual(row["numero_cobro"], "COB-2026-0001")

        eventos = self._query(
            "SELECT descripcion FROM eco_eventos WHERE tipo_evento = 'MODIFICACION'"
        )
        self.assertEqual(len(eventos), 2)
        self.assertIn("desglose anterior", eventos[0]["descripcion"])

    def test_caller_legacy_preserva_desglose_multiconcepto(self) -> None:
        cobro_id = self._crear_escenario()

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                importe="138.28",
                tipo_fiscal="PROVISIÓN",
                observaciones="nota",
            ),
        )
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["tipo_fiscal"], "MIXTO")
        self.assertEqual(row["observaciones"], "nota")
        self.assertEqual(len(self._lineas(cobro_id)), 2)

        with self.assertRaisesRegex(ValueError, "2 conceptos"):
            economic_service.update_cobro(
                cobro_id, self._payload(importe="140,00")
            )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 138.28)

    def test_factura_aprobada_bloquea_edicion(self) -> None:
        cobro_id = self._crear_escenario()
        factura_id = self._insert_factura(exportada_holded=1, estado="APROBADA")
        self._link_factura(cobro_id, factura_id)

        with self.assertRaisesRegex(ValueError, "aprobada"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    lineas=[_linea("Provisión", "1", "PROVISION", "PROVISION")]
                ),
            )
        self.assertEqual(len(self._lineas(cobro_id)), 2)

    def test_factura_pendiente_no_se_recalcula_ni_admite_cambio_economico(self) -> None:
        cobro_id = self._crear_escenario()
        factura_id = self._insert_factura(exportada_holded=0, estado="EMITIDA")
        self._link_factura(cobro_id, factura_id)

        with self.assertRaisesRegex(ValueError, "no se recalcula"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    lineas=[
                        _linea("Provisión", "90", "PROVISION", "PROVISION"),
                        _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                    ]
                ),
            )

        # Cambio no económico permitido; la factura queda intacta.
        economic_service.update_cobro(
            cobro_id,
            self._payload(importe="138,28", observaciones="sin cambio económico"),
        )
        factura = self._query(
            "SELECT total, base_imponible, suplidos FROM eco_facturas WHERE id = ?",
            (factura_id,),
        )[0]
        self.assertEqual(
            factura, {"total": 138.28, "base_imponible": 100.0, "suplidos": 38.28}
        )

    # ------------------------------------------------------------
    # C · Céntimos y formatos
    # ------------------------------------------------------------

    def test_suma_centimetrica_exacta(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                lineas=[
                    _linea("A", "0,01", "PROVISION", "PROVISION"),
                    _linea("B", "0.02", "PROVISION", "PROVISION"),
                ]
            )
        )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 0.03)
        self.assertEqual(economic_service.get_cobro(cobro_id)["importe_centimos"], 3)

    def test_rechazos_no_persisten_nada(self) -> None:
        invalidos = (
            [_linea("A", "0,001", "PROVISION", "PROVISION")],
            [_linea("A", "-1", "PROVISION", "PROVISION")],
            [_linea("A", "0", "PROVISION", "PROVISION")],
            [],
        )
        for lineas in invalidos:
            with self.subTest(lineas=lineas):
                with self.assertRaises(ValueError):
                    economic_service.create_cobro(self._payload(lineas=lineas))
        self.assertEqual(self._count("eco_cobros"), 0)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)

    def test_check_sql_rechaza_importe_no_entero_o_no_positivo(self) -> None:
        cobro_id = self._crear_escenario()
        for value in (0, -5, 1.5):
            with self.subTest(value=value):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(
                            """
                            INSERT INTO eco_cobro_lineas (
                                cobro_id, posicion, concepto,
                                tipo_economico, tipo_fiscal, importe_centimos
                            )
                            VALUES (?, 9, 'X', 'OTRO', 'PROVISION', ?)
                            """,
                            (cobro_id, value),
                        )

    # ------------------------------------------------------------
    # D · TASA y clasificación fiscal
    # ------------------------------------------------------------

    def test_tasa_sin_expediente_se_rechaza(self) -> None:
        with self.assertRaisesRegex(ValueError, "TASA"):
            economic_service.create_cobro(
                self._payload(
                    expediente_id=None,
                    hoja_encargo_id=None,
                    tipo_cobro="CONSULTA",
                    lineas=[_linea("Tasa", "38,28", "TASA", "SUPLIDO")],
                )
            )
        self.assertEqual(self._count("eco_cobros"), 0)

    def test_tasa_no_se_convierte_en_suplido(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                hoja_encargo_id=None,
                lineas=[_linea("Tasa", "38,28", "TASA", "PROVISION")],
            )
        )
        self.assertEqual(self._lineas(cobro_id)[0]["tipo_fiscal"], "PROVISION")
        self.assertEqual(self._cobro_row(cobro_id)["tipo_fiscal"], "PROVISION")

    def test_provision_sin_hoja_se_rechaza(self) -> None:
        with self.assertRaisesRegex(ValueError, "hoja"):
            economic_service.create_cobro(
                self._payload(hoja_encargo_id=None, lineas=ESCENARIO)
            )
        self.assertEqual(self._count("eco_cobros"), 0)

    def test_suplido_adelantado_mixto_se_rechaza(self) -> None:
        with self.assertRaisesRegex(ValueError, "SUPLIDO_ADELANTADO"):
            economic_service.create_cobro(
                self._payload(tipo_cobro="SUPLIDO_ADELANTADO", lineas=ESCENARIO)
            )

    # ------------------------------------------------------------
    # E · Legacy
    # ------------------------------------------------------------

    def test_cobro_legacy_sin_detalle(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                importe="75,50",
                concepto="Pago",
                tipo_fiscal="PROVISIÓN",
                facturable=1,
                iva_porcentaje="21",
            )
        )
        self.assertEqual(self._count("eco_cobro_lineas"), 0)
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 75.5)
        self.assertEqual(row["tipo_fiscal"], "PROVISION")

        # Legacy: factura automática calculada sobre el total del cobro.
        factura_id = row["factura_id"]
        self.assertIsNotNone(factura_id)
        legacy = economic_service._calculate_invoice_from_total(75.5, "21", "0")
        factura = self._factura(factura_id)
        self.assertEqual(factura["base_imponible"], legacy["base_imponible"])
        self.assertEqual(factura["iva"], legacy["iva"])
        self.assertEqual(factura["suplidos"], 0.0)
        self.assertEqual(factura["total"], 75.5)
        self.assertEqual(factura["tipo_fiscal"], "PROVISION")

        cobro = economic_service.get_cobro(cobro_id)
        self.assertTrue(cobro["lineas_sinteticas"])
        self.assertEqual(cobro["num_lineas"], 1)
        self.assertEqual(cobro["lineas"][0]["importe_centimos"], 7550)
        self.assertEqual(cobro["lineas"][0]["concepto"], "PAGO")

        economic_service.update_cobro(
            cobro_id,
            self._payload(importe="80", concepto="Pago", facturable=1, iva_porcentaje="21"),
        )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 80.0)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)

        # La edición recalcula la misma factura: sin duplicados.
        self.assertEqual(self._count("eco_facturas"), 1)
        self.assertEqual(self._count("eco_factura_cobros"), 1)
        self.assertEqual(self._cobro_row(cobro_id)["factura_id"], factura_id)
        legacy = economic_service._calculate_invoice_from_total(80, "21", "0")
        factura = self._factura(factura_id)
        self.assertEqual(factura["base_imponible"], legacy["base_imponible"])
        self.assertEqual(factura["iva"], legacy["iva"])
        self.assertEqual(factura["total"], 80.0)

    def test_legacy_reglas_previas_intactas(self) -> None:
        with self.assertRaisesRegex(ValueError, "TASA"):
            economic_service.create_cobro(
                self._payload(importe="10", tipo_cobro="TASA", expediente_id=None)
            )
        with self.assertRaisesRegex(ValueError, "hoja"):
            economic_service.create_cobro(
                self._payload(importe="10", hoja_encargo_id=None)
            )
        economic_service.create_cobro(
            self._payload(
                importe="10",
                hoja_encargo_id=None,
                expediente_id=None,
                tipo_cobro="SUPLIDO_ADELANTADO",
                tipo_fiscal="PROVISION",
            )
        )

    def test_legacy_convertido_a_multilinea(self) -> None:
        cobro_id = economic_service.create_cobro(self._payload(importe="138,28"))
        economic_service.update_cobro(
            cobro_id, self._payload(lineas=ESCENARIO, importe="138,28")
        )
        self.assertEqual(len(self._lineas(cobro_id)), 2)
        self.assertEqual(self._cobro_row(cobro_id)["tipo_fiscal"], "MIXTO")

    # ------------------------------------------------------------
    # F · Conciliación única
    # ------------------------------------------------------------

    def test_conciliacion_unica_y_cambio_de_total(self) -> None:
        cobro_id = self._crear_escenario()

        totals = payment_reconciliation_service.set_application(
            source_type="bank",
            source_movement_id=900,
            payment_id=cobro_id,
            amount_centimos=13828,
            client_id=CLIENTE_ID,
            db_path=self.db_path,
        )
        self.assertEqual(totals["total_centimos"], 13828)
        self.assertEqual(totals["status"], "CONCILIADO")
        self.assertEqual(
            self._count("economic_reconciliation_applications"), 1
        )

        with self.assertRaisesRegex(ValueError, "conciliados"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    lineas=[
                        _linea("Provisión", "90", "PROVISION", "PROVISION"),
                        _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                    ]
                ),
            )
        self.assertEqual(self._cobro_row(cobro_id)["importe"], 138.28)

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                lineas=ESCENARIO
                + [_linea("Honorarios", "10", "HONORARIOS", "PROVISION")]
            ),
        )
        row = self._cobro_row(cobro_id)
        self.assertEqual(row["importe"], 148.28)
        self.assertEqual(row["estado_conciliacion"], "PARCIAL")
        self.assertEqual(
            payment_reconciliation_service.reconciliation_totals(
                cobro_id, db_path=self.db_path
            )["status"],
            "PARCIAL",
        )

    def test_estado_conciliado_sin_aplicaciones_bloquea_cambio_de_total(self) -> None:
        cobro_id = self._crear_escenario()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE eco_cobros SET estado_conciliacion = 'CONCILIADO' WHERE id = ?",
                (cobro_id,),
            )
            conn.commit()
        with self.assertRaisesRegex(ValueError, "sin aplicaciones"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    lineas=[_linea("Provisión", "1", "PROVISION", "PROVISION")]
                ),
            )

    # ------------------------------------------------------------
    # G · Rollback por fallo de BD en la segunda línea
    # ------------------------------------------------------------

    def _install_fail_on_second_line(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TRIGGER test_fail_second_line
                BEFORE INSERT ON eco_cobro_lineas
                WHEN NEW.posicion = 2
                BEGIN
                    SELECT RAISE(ABORT, 'fallo simulado segunda linea');
                END
                """
            )
            conn.commit()

    def test_rollback_alta_si_falla_segunda_linea(self) -> None:
        self._install_fail_on_second_line()

        with self.assertRaises(sqlite3.DatabaseError):
            self._crear_escenario(facturable=1)

        self.assertEqual(self._count("eco_cobros"), 0)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)
        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_eventos"), 0)
        self.assertEqual(
            self._count("sqlite_sequence", "name = 'eco_cobros'"), 0
        )

    def test_rollback_edicion_si_falla_segunda_linea(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                lineas=[_linea("Provisión", "100", "PROVISION", "PROVISION")]
            )
        )
        self._install_fail_on_second_line()

        with self.assertRaises(sqlite3.DatabaseError):
            economic_service.update_cobro(cobro_id, self._payload(lineas=ESCENARIO))

        self.assertEqual(self._cobro_row(cobro_id)["importe"], 100.0)
        self.assertEqual(
            [l["importe_centimos"] for l in self._lineas(cobro_id)], [10000]
        )

    # ------------------------------------------------------------
    # Numeración
    # ------------------------------------------------------------

    def test_numero_unico_y_correlativo(self) -> None:
        ids = [
            self._crear_escenario(),
            economic_service.create_cobro(self._payload(importe="10")),
            self._crear_escenario(),
        ]
        numeros = [self._cobro_row(i)["numero_cobro"] for i in ids]
        self.assertEqual(
            numeros, ["COB-2026-0001", "COB-2026-0002", "COB-2026-0003"]
        )
        self.assertEqual(self._count("eco_cobros"), 3)
        self.assertEqual(self._count("eco_cobro_lineas"), 4)

    # ------------------------------------------------------------
    # H · Facturación expresa
    # ------------------------------------------------------------

    def test_factura_expresa_de_cobro_mixto_incoherente_se_rechaza(self) -> None:
        # Decisión de Dirección (2026-11-14): la factura MIXTA se emite en
        # CRM; solo se rechaza la que no respeta el desglose (p. ej. el
        # tramo SUPLIDO gravado como base). Holded es asunto de WO-02.
        cobro_id = self._crear_escenario()
        base = {
            "cliente_id": CLIENTE_ID,
            "expediente_id": EXPEDIENTE_ID,
            "fecha_factura": FECHA,
            "estado": "BORRADOR",
        }

        for importes in (
            {"base_imponible": "138,28", "suplidos": "0"},
            {"base_imponible": "100", "iva": "21", "suplidos": "38,28"},
            {"base_imponible": "100", "suplidos": "38,28", "total": "140"},
        ):
            with self.subTest(importes=importes):
                with self.assertRaisesRegex(ValueError, "no cuadra"):
                    economic_service.create_factura(
                        dict(base, **importes),
                        cobro_ids=[cobro_id],
                    )
        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_factura_cobros"), 0)
        self.assertIsNone(self._cobro_row(cobro_id)["factura_id"])

    def test_factura_expresa_de_cobro_mixto_coherente_se_emite_mixto(self) -> None:
        cobro_id = self._crear_escenario(iva_porcentaje="21")
        factura_id = economic_service.create_factura(
            {
                "cliente_id": CLIENTE_ID,
                "expediente_id": EXPEDIENTE_ID,
                "fecha_factura": FECHA,
                "estado": "BORRADOR",
                "base_imponible": "82,64",
                "iva": "17,36",
                "suplidos": "38,28",
                "tipo_fiscal": "PROVISION",
            },
            cobro_ids=[cobro_id],
        )
        factura = self._factura(factura_id)
        self.assertEqual(factura["tipo_fiscal"], "MIXTO")
        self.assertEqual(factura["total"], 138.28)
        self.assertEqual(factura["suplidos"], 38.28)
        self.assertEqual(self._cobro_row(cobro_id)["factura_id"], factura_id)
        self.assertEqual(self._count("eco_factura_cobros"), 1)

    def test_factura_expresa_de_cobro_multilinea_no_mixto_se_permite(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                lineas=[
                    _linea("Provisión", "100", "PROVISION", "PROVISION"),
                    _linea("Honorarios", "21", "HONORARIOS", "PROVISION"),
                ]
            )
        )
        factura_id = economic_service.create_factura(
            {
                "cliente_id": CLIENTE_ID,
                "expediente_id": EXPEDIENTE_ID,
                "fecha_factura": FECHA,
                "estado": "BORRADOR",
                "base_imponible": "121",
            },
            cobro_ids=[cobro_id],
        )
        self.assertEqual(self._cobro_row(cobro_id)["factura_id"], factura_id)

    def test_factura_automatica_mixto_idempotente(self) -> None:
        # Antes: bloqueo indiscriminado de cobros con varias líneas.
        # Ahora: una factura MIXTO; reinvocar no duplica.
        cobro_id = self._crear_escenario(facturable=1, iva_porcentaje="21")
        factura_id = self._cobro_row(cobro_id)["factura_id"]

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(
                economic_service._crear_factura_automatica_por_cobro(
                    conn, cobro_id
                ),
                factura_id,
            )
            conn.commit()

        self.assertEqual(self._count("eco_facturas"), 1)
        self.assertEqual(self._count("eco_factura_cobros"), 1)
        self.assertEqual(self._factura(factura_id)["base_imponible"], 82.64)

    def test_no_facturable_no_emite_factura(self) -> None:
        cobro_id = self._crear_escenario(facturable=0, iva_porcentaje="21")
        economic_service.update_cobro(
            cobro_id,
            self._payload(lineas=ESCENARIO, importe="138,28", observaciones="x"),
        )
        self.assertIsNone(self._cobro_row(cobro_id)["factura_id"])
        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_factura_cobros"), 0)

    def test_matriz_iva_irpf_mixto(self) -> None:
        for iva in ("0", "21"):
            for irpf in ("0", "7", "15"):
                with self.subTest(iva=iva, irpf=irpf):
                    cobro_id = self._crear_escenario(
                        facturable=1, iva_porcentaje=iva, irpf_porcentaje=irpf
                    )
                    factura = self._factura(
                        self._cobro_row(cobro_id)["factura_id"]
                    )
                    legacy = economic_service._calculate_invoice_from_total(
                        100.0, iva, irpf
                    )
                    self.assertEqual(factura["base_imponible"], legacy["base_imponible"])
                    self.assertEqual(factura["iva"], legacy["iva"])
                    self.assertEqual(factura["irpf"], legacy["irpf"])
                    self.assertEqual(factura["suplidos"], 38.28)
                    self.assertEqual(factura["total"], 138.28)
                    self.assertEqual(factura["tipo_fiscal"], "MIXTO")
        self.assertEqual(self._count("eco_facturas"), 6)
        self.assertEqual(self._count("eco_factura_cobros"), 6)

    def test_varias_provisiones_y_suplidos(self) -> None:
        cobro_id = economic_service.create_cobro(
            self._payload(
                facturable=1,
                iva_porcentaje="21",
                irpf_porcentaje="15",
                lineas=[
                    _linea("Provisión A", "60", "PROVISION", "PROVISION"),
                    _linea("Tasa", "30", "TASA", "SUPLIDO"),
                    _linea("Honorarios B", "40", "HONORARIOS", "PROVISION"),
                    _linea("Registro", "8,28", "OTRO", "SUPLIDO"),
                ],
            )
        )
        factura = self._factura(self._cobro_row(cobro_id)["factura_id"])
        legacy = economic_service._calculate_invoice_from_total(100.0, "21", "15")
        self.assertEqual(factura["base_imponible"], legacy["base_imponible"])
        self.assertEqual(factura["iva"], legacy["iva"])
        self.assertEqual(factura["irpf"], legacy["irpf"])
        self.assertEqual(factura["suplidos"], 38.28)
        self.assertEqual(factura["total"], 138.28)

    def test_cobro_simple_provision_y_suplido(self) -> None:
        provision = economic_service.create_cobro(
            self._payload(
                facturable=1,
                iva_porcentaje="21",
                lineas=[_linea("Provisión", "138,28", "PROVISION", "PROVISION")],
            )
        )
        factura = self._factura(self._cobro_row(provision)["factura_id"])
        legacy = economic_service._calculate_invoice_from_total(138.28, "21", "0")
        self.assertEqual(factura["base_imponible"], legacy["base_imponible"])
        self.assertEqual(factura["iva"], legacy["iva"])
        self.assertEqual(factura["suplidos"], 0.0)
        self.assertEqual(factura["tipo_fiscal"], "PROVISION")

        for tipo_cobro in ("PAGO_EXPEDIENTE", "SUPLIDO_ADELANTADO"):
            with self.subTest(tipo_cobro=tipo_cobro):
                suplido = economic_service.create_cobro(
                    self._payload(
                        tipo_cobro=tipo_cobro,
                        hoja_encargo_id=None,
                        facturable=1,
                        iva_porcentaje="21",
                        lineas=[_linea("Tasa", "38,28", "TASA", "SUPLIDO")],
                    )
                )
                row = self._cobro_row(suplido)
                self.assertEqual(row["iva_porcentaje"], 0.0)
                self.assertEqual(
                    self._factura(row["factura_id"]),
                    {
                        "base_imponible": 0.0,
                        "iva": 0.0,
                        "irpf": 0.0,
                        "suplidos": 38.28,
                        "total": 38.28,
                        "tipo_fiscal": "SUPLIDO",
                        "estado": "EMITIDA",
                    },
                )

    def test_edicion_facturable_recalcula_sin_duplicar(self) -> None:
        cobro_id = self._crear_escenario(facturable=1, iva_porcentaje="21")
        factura_id = self._cobro_row(cobro_id)["factura_id"]

        economic_service.update_cobro(
            cobro_id,
            self._payload(
                facturable=1,
                iva_porcentaje="21",
                lineas=[
                    _linea("Provisión", "121", "PROVISION", "PROVISION"),
                    _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
                ],
            ),
        )
        self.assertEqual(self._count("eco_facturas"), 1)
        self.assertEqual(self._count("eco_factura_cobros"), 1)
        self.assertEqual(self._cobro_row(cobro_id)["factura_id"], factura_id)
        factura = self._factura(factura_id)
        self.assertEqual(factura["base_imponible"], 100.0)
        self.assertEqual(factura["iva"], 21.0)
        self.assertEqual(factura["suplidos"], 38.28)
        self.assertEqual(factura["total"], 159.28)
        self.assertEqual(
            self._query("SELECT importe_asignado FROM eco_factura_cobros"),
            [{"importe_asignado": 159.28}],
        )

    def test_factura_aprobada_bloquea_edicion_facturable(self) -> None:
        cobro_id = self._crear_escenario(facturable=1, iva_porcentaje="21")
        factura_id = self._cobro_row(cobro_id)["factura_id"]
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE eco_facturas SET estado = 'APROBADA', "
                "exportada_holded = 1 WHERE id = ?",
                (factura_id,),
            )
            conn.commit()
        antes = self._factura(factura_id)

        with self.assertRaisesRegex(ValueError, "aprobada"):
            economic_service.update_cobro(
                cobro_id,
                self._payload(
                    facturable=1,
                    iva_porcentaje="21",
                    lineas=[_linea("Provisión", "1", "PROVISION", "PROVISION")],
                ),
            )
        self.assertEqual(self._factura(factura_id), antes)
        self.assertEqual(len(self._lineas(cobro_id)), 2)
        self.assertEqual(self._count("eco_facturas"), 1)

    def test_rollback_si_falla_la_factura(self) -> None:
        with mock.patch.object(
            economic_service,
            "renumerar_facturas_por_year",
            side_effect=sqlite3.OperationalError("fallo simulado factura"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self._crear_escenario(facturable=1, iva_porcentaje="21")

        self.assertEqual(self._count("eco_cobros"), 0)
        self.assertEqual(self._count("eco_cobro_lineas"), 0)
        self.assertEqual(self._count("eco_facturas"), 0)
        self.assertEqual(self._count("eco_factura_cobros"), 0)
        self.assertEqual(self._count("eco_eventos"), 0)

    # ------------------------------------------------------------
    # Fixtures de factura
    # ------------------------------------------------------------

    def _factura(self, factura_id):
        return self._query(
            "SELECT base_imponible, iva, irpf, suplidos, total, "
            "tipo_fiscal, estado FROM eco_facturas WHERE id = ?",
            (factura_id,),
        )[0]

    def _insert_factura(self, exportada_holded, estado):
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                """
                INSERT INTO eco_facturas (
                    numero_factura, fecha_factura, cliente_id,
                    base_imponible, iva, irpf, suplidos, total,
                    estado, exportada_holded, activo
                )
                VALUES ('FRA-2026-0001', ?, ?, 100, 0, 0, 38.28, 138.28, ?, ?, 1)
                """,
                (FECHA, CLIENTE_ID, estado, exportada_holded),
            )
            conn.commit()
            return cur.lastrowid

    def _link_factura(self, cobro_id, factura_id):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE eco_cobros SET factura_id = ? WHERE id = ?",
                (factura_id, cobro_id),
            )
            conn.execute(
                "INSERT INTO eco_factura_cobros (factura_id, cobro_id, importe_asignado) "
                "VALUES (?, ?, 138.28)",
                (factura_id, cobro_id),
            )
            conn.commit()


if __name__ == "__main__":
    unittest.main()

"""
ECO-ML-01 · WO-02 · Exportación Holded deshabilitada para suplidos.

Todo ocurre en un SQLite y un directorio XLSX temporales; nunca se toca
database/quesada.db ni se contacta con Holded.
"""

from __future__ import annotations

import gc
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook

from backend.services import holded_invoice_export_service as holded


ROOT = Path(__file__).resolve().parents[2]
REAL_DB_PATH = (ROOT / "database" / "quesada.db").resolve()
ECONOMIC_SCHEMA = ROOT / "database" / "economic_schema.sql"

BASE_SCHEMA = """
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY, nombre TEXT,
    primer_apellido TEXT, segundo_apellido TEXT,
    nif TEXT, direccion TEXT, poblacion TEXT,
    codigo_postal TEXT, provincia TEXT, pais TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, numero_expediente TEXT, cliente_id INTEGER
);
"""

FECHA = "2026-11-13"
CLIENTE_ID = 1
REASON = "SUPLIDO_NO_EXPORTABLE_HOLDED"

MUTABLE_COLUMNS = (
    "estado",
    "exportada_holded",
    "fecha_exportacion",
    "updated_at",
)


class HoldedSuplidoExportGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp = Path(self.temp_dir.name)
        self.db_path = (temp / "eco_holded.db").resolve()
        self.output_dir = temp / "exports"
        self.assertNotEqual(self.db_path, REAL_DB_PATH)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(BASE_SCHEMA)
            conn.executescript(
                ECONOMIC_SCHEMA.read_text(encoding="utf-8")
            )
            conn.execute(
                """
                INSERT INTO clientes (
                    id, nombre, primer_apellido, nif, direccion,
                    poblacion, codigo_postal, provincia, pais
                )
                VALUES (?, 'Ana', 'Pérez', '12345678Z', 'Calle Mayor 1',
                        'Madrid', '28001', 'Madrid', 'España')
                """,
                (CLIENTE_ID,),
            )
            conn.commit()

        self._cobro_seq = 0
        self._factura_seq = 0

    def tearDown(self) -> None:
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def _cobro(
        self,
        importe,
        tipo_fiscal="PROVISION",
        iva=0,
        irpf=0,
        lineas=(),
        tipo_cobro="PAGO_EXPEDIENTE",
    ) -> int:
        self._cobro_seq += 1
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO eco_cobros (
                    numero_cobro, fecha_cobro, cliente_id, importe,
                    forma_pago, tipo_cobro, facturable, tipo_fiscal,
                    iva_porcentaje, irpf_porcentaje
                )
                VALUES (?, ?, ?, ?, 'TRANSFERENCIA', ?, 1, ?, ?, ?)
                """,
                (
                    f"C-{self._cobro_seq:04d}",
                    FECHA,
                    CLIENTE_ID,
                    importe,
                    tipo_cobro,
                    tipo_fiscal,
                    iva,
                    irpf,
                ),
            )
            cobro_id = int(cur.lastrowid)
            for posicion, (tipo_economico, fiscal, centimos) in enumerate(
                lineas, start=1
            ):
                conn.execute(
                    """
                    INSERT INTO eco_cobro_lineas (
                        cobro_id, posicion, concepto, tipo_economico,
                        tipo_fiscal, importe_centimos
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cobro_id,
                        posicion,
                        f"Línea {posicion}",
                        tipo_economico,
                        fiscal,
                        centimos,
                    ),
                )
            conn.commit()
        return cobro_id

    def _factura(
        self,
        *,
        base=0,
        iva=0,
        irpf=0,
        suplidos=0,
        total=0,
        tipo_fiscal="PROVISION",
        cobro_ids=(),
        tipo_factura="NORMAL",
        rectificada_id=None,
        causa=None,
        exportada=0,
        estado="EMITIDA",
    ) -> int:
        self._factura_seq += 1
        prefix = "R" if tipo_factura == "RECTIFICATIVA" else "F"
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO eco_facturas (
                    numero_factura, fecha_factura, cliente_id,
                    base_imponible, iva, irpf, suplidos, total,
                    tipo_fiscal, concepto, tipo_factura,
                    factura_rectificada_id, causa_rectificacion,
                    estado, exportada_holded, fecha_exportacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Servicios', ?, ?, ?,
                        ?, ?, ?)
                """,
                (
                    f"{prefix}-2026-{self._factura_seq:04d}",
                    FECHA,
                    CLIENTE_ID,
                    base,
                    iva,
                    irpf,
                    suplidos,
                    total,
                    tipo_fiscal,
                    tipo_factura,
                    rectificada_id,
                    causa,
                    estado,
                    exportada,
                    "2026-11-01 10:00:00" if exportada else None,
                ),
            )
            factura_id = int(cur.lastrowid)
            for cobro_id in cobro_ids:
                conn.execute(
                    """
                    INSERT INTO eco_factura_cobros (
                        factura_id, cobro_id, importe_asignado
                    )
                    VALUES (?, ?, ?)
                    """,
                    (factura_id, cobro_id, total),
                )
            conn.commit()
        return factura_id

    def _provision(self) -> int:
        cobro = self._cobro(121, iva=21, lineas=[("PROVISION", "PROVISION", 12100)])
        return self._factura(
            base=100, iva=21, total=121, cobro_ids=[cobro]
        )

    def _suplido(self) -> int:
        cobro = self._cobro(
            38.28, tipo_fiscal="SUPLIDO", lineas=[("TASA", "SUPLIDO", 3828)]
        )
        return self._factura(
            suplidos=38.28, total=38.28, tipo_fiscal="SUPLIDO", cobro_ids=[cobro]
        )

    def _mixto(self) -> int:
        cobro = self._cobro(
            138.28,
            tipo_fiscal="MIXTO",
            iva=21,
            lineas=[
                ("PROVISION", "PROVISION", 10000),
                ("TASA", "SUPLIDO", 3828),
            ],
        )
        return self._factura(
            base=82.64,
            iva=17.36,
            suplidos=38.28,
            total=138.28,
            tipo_fiscal="MIXTO",
            cobro_ids=[cobro],
        )

    def _snapshot(self, factura_id) -> dict:
        with self._conn() as conn:
            return dict(
                conn.execute(
                    "SELECT * FROM eco_facturas WHERE id = ?",
                    (factura_id,),
                ).fetchone()
            )

    def _expected_rows(self) -> dict:
        """Filas que genera el constructor legacy, por número de factura."""
        with self._conn() as conn:
            pending = holded._load_pending_invoices(conn)
            return {
                invoice["numero_factura"]: holded._build_holded_row(
                    invoice,
                    holded._load_client(conn, invoice["cliente_id"]),
                )
                for invoice in pending
            }

    def _xlsx_files(self) -> list[Path]:
        if not self.output_dir.exists():
            return []
        return sorted(self.output_dir.glob("*.xlsx"))

    def _xlsx_rows(self, path) -> list[list]:
        workbook = load_workbook(path)
        try:
            rows = [
                list(row)
                for row in workbook["Holded"].iter_rows(values_only=True)
            ]
        finally:
            workbook.close()
        self.assertEqual(rows[0], holded.HOLDED_HEADERS)
        return rows[1:]

    def _export(self, mark_exported=True) -> dict:
        return holded.export_pending_invoices_to_holded(
            db_path=self.db_path,
            output_dir=self.output_dir,
            mark_exported=mark_exported,
        )

    def _export_blocked(self, mark_exported=True):
        with self.assertRaises(holded.HoldedSuplidoExportError) as ctx:
            self._export(mark_exported=mark_exported)
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertIn("suplidos", str(ctx.exception))
        self.assertIn("intervención manual", str(ctx.exception))
        self.assertEqual(self._xlsx_files(), [])
        return ctx.exception

    def _assert_marked(self, factura_id) -> None:
        row = self._snapshot(factura_id)
        self.assertEqual(row["exportada_holded"], 1)
        self.assertEqual(row["estado"], "EXPORTADA")
        self.assertIsNotNone(row["fecha_exportacion"])

    def _assert_skipped(self, result, ids) -> None:
        self.assertEqual(result["skipped_count"], len(ids))
        self.assertEqual(sorted(result["skipped_invoice_ids"]), sorted(ids))
        self.assertEqual(
            {item["reason"] for item in result["skipped"]},
            {REASON} if ids else set(),
        )
        for item in result["skipped"]:
            self.assertTrue(item["detail"])
            self.assertTrue(item["numero_factura"])

    def _assert_single_exported(self, result, factura_id, expected) -> None:
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["invoice_ids"], [factura_id])
        numero = self._snapshot(factura_id)["numero_factura"]
        rows = self._xlsx_rows(result["path"])
        # openpyxl puede releer las celdas "" como None.
        normalize = lambda row: [None if v == "" else v for v in row]
        self.assertEqual(
            [normalize(row) for row in rows],
            [normalize(expected[numero])],
        )

    # ------------------------------------------------------------
    # Paridad PROVISION
    # ------------------------------------------------------------

    def test_solo_provision_paridad_y_marcado(self) -> None:
        factura = self._provision()
        expected = self._expected_rows()

        result = self._export()

        self._assert_single_exported(result, factura, expected)
        self._assert_skipped(result, [])
        self.assertEqual(len(self._xlsx_files()), 1)

        row = expected[self._snapshot(factura)["numero_factura"]]
        self.assertEqual(row[16], 100.0)  # Precio unidad
        self.assertEqual(row[19], 21.0)  # IVA %
        self.assertEqual(row[20], 0.0)  # Retención %
        self.assertEqual(row[24], 121.0)  # Cantidad cobrada
        self.assertEqual(row[27], "CRM-Provision")
        self.assertEqual(row[6], "Ana Pérez")
        self.assertEqual(row[7], "12345678Z")
        self._assert_marked(factura)

    def test_tasa_con_naturaleza_provision_se_exporta(self) -> None:
        cobro = self._cobro(
            138.28, lineas=[("TASA", "PROVISION", 13828)], tipo_cobro="TASA"
        )
        factura = self._factura(base=138.28, total=138.28, cobro_ids=[cobro])
        expected = self._expected_rows()

        result = self._export()

        self._assert_single_exported(result, factura, expected)
        self._assert_skipped(result, [])
        self._assert_marked(factura)

    # ------------------------------------------------------------
    # Exclusión total
    # ------------------------------------------------------------

    def test_solo_suplido_no_genera_archivo_ni_muta(self) -> None:
        factura = self._suplido()
        before = self._snapshot(factura)

        error = self._export_blocked()

        self.assertEqual(error.result["count"], 0)
        self.assertEqual(error.result["invoice_ids"], [])
        self.assertIsNone(error.result["path"])
        self._assert_skipped(error.result, [factura])
        self.assertEqual(self._snapshot(factura), before)

    def test_mixto_100_mas_38_28_no_se_exporta(self) -> None:
        factura = self._mixto()
        before = self._snapshot(factura)

        error = self._export_blocked()

        self._assert_skipped(error.result, [factura])
        after = self._snapshot(factura)
        self.assertEqual(after, before)
        self.assertEqual(after["exportada_holded"], 0)
        self.assertEqual(after["estado"], "EMITIDA")

    # ------------------------------------------------------------
    # Lotes mixtos
    # ------------------------------------------------------------

    def test_lote_provision_suplido_mixto(self) -> None:
        provision = self._provision()
        suplido = self._suplido()
        mixto = self._mixto()
        expected = self._expected_rows()
        before = {fid: self._snapshot(fid) for fid in (suplido, mixto)}

        result = self._export(mark_exported=True)

        self._assert_single_exported(result, provision, expected)
        self._assert_skipped(result, [suplido, mixto])
        self._assert_marked(provision)
        for fid, snapshot in before.items():
            self.assertEqual(self._snapshot(fid), snapshot)

    def test_mark_exported_false_no_cambia_estados(self) -> None:
        provision = self._provision()
        suplido = self._suplido()
        mixto = self._mixto()
        expected = self._expected_rows()
        before = {
            fid: self._snapshot(fid) for fid in (provision, suplido, mixto)
        }

        result = self._export(mark_exported=False)

        self._assert_single_exported(result, provision, expected)
        self._assert_skipped(result, [suplido, mixto])
        for fid, snapshot in before.items():
            self.assertEqual(self._snapshot(fid), snapshot)

    def test_mark_exported_false_todo_excluido(self) -> None:
        suplido = self._suplido()
        mixto = self._mixto()
        before = {fid: self._snapshot(fid) for fid in (suplido, mixto)}

        error = self._export_blocked(mark_exported=False)

        self._assert_skipped(error.result, [suplido, mixto])
        for fid, snapshot in before.items():
            self.assertEqual(self._snapshot(fid), snapshot)

    def test_facturas_ya_exportadas_no_se_tocan(self) -> None:
        exportada = self._factura(
            suplidos=38.28,
            total=38.28,
            tipo_fiscal="SUPLIDO",
            exportada=1,
            estado="EXPORTADA",
        )
        before = self._snapshot(exportada)
        provision = self._provision()
        expected = self._expected_rows()

        result = self._export()

        self._assert_single_exported(result, provision, expected)
        self._assert_skipped(result, [])
        self.assertEqual(self._snapshot(exportada), before)

    # ------------------------------------------------------------
    # Rectificativas
    # ------------------------------------------------------------

    def _original_provision(self) -> int:
        cobro = self._cobro(121, iva=21)
        return self._factura(
            base=100,
            iva=21,
            total=121,
            cobro_ids=[cobro],
            exportada=1,
            estado="EXPORTADA",
        )

    def test_rectificativa_sin_suplidos_paridad(self) -> None:
        original = self._original_provision()
        rectificativa = self._factura(
            base=-100,
            iva=-21,
            total=-121,
            tipo_factura="RECTIFICATIVA",
            rectificada_id=original,
            causa="Error en importe",
        )
        original_before = self._snapshot(original)
        expected = self._expected_rows()

        result = self._export()

        self._assert_single_exported(result, rectificativa, expected)
        self._assert_skipped(result, [])
        row = expected[self._snapshot(rectificativa)["numero_factura"]]
        self.assertEqual(row[16], -100.0)
        self.assertEqual(row[19], -21.0)
        self.assertEqual(row[24], -121.0)
        self.assertIn("Factura rectificativa", row[5])
        self.assertIn(original_before["numero_factura"], row[5])
        self._assert_marked(rectificativa)
        self.assertEqual(self._snapshot(original), original_before)

    def test_rectificativa_con_suplido_negativo_se_excluye(self) -> None:
        # Aunque el tipo fiscal diga PROVISION, el suplido negativo
        # en céntimos basta para excluirla.
        original = self._original_provision()
        rectificativa = self._factura(
            suplidos=-38.28,
            total=-38.28,
            tipo_factura="RECTIFICATIVA",
            rectificada_id=original,
            causa="Suplido",
        )
        before = self._snapshot(rectificativa)

        error = self._export_blocked()

        self._assert_skipped(error.result, [rectificativa])
        self.assertIn("suplidos", error.result["skipped"][0]["detail"])
        self.assertEqual(self._snapshot(rectificativa), before)

    def test_rectificativa_de_factura_mixta_se_excluye(self) -> None:
        cobro = self._cobro(
            138.28,
            tipo_fiscal="MIXTO",
            iva=21,
            lineas=[
                ("PROVISION", "PROVISION", 10000),
                ("TASA", "SUPLIDO", 3828),
            ],
        )
        original = self._factura(
            base=82.64,
            iva=17.36,
            suplidos=38.28,
            total=138.28,
            tipo_fiscal="MIXTO",
            cobro_ids=[cobro],
            exportada=1,
            estado="EXPORTADA",
        )
        for tipo_fiscal in ("MIXTO", "PROVISION"):
            with self.subTest(tipo_fiscal=tipo_fiscal):
                # Solo rectifica honorarios: suplidos 0 en la propia
                # rectificativa, pero la original es mixta.
                rectificativa = self._factura(
                    base=-82.64,
                    iva=-17.36,
                    total=-100,
                    tipo_fiscal=tipo_fiscal,
                    tipo_factura="RECTIFICATIVA",
                    rectificada_id=original,
                    causa="Honorarios",
                )
                before = self._snapshot(rectificativa)

                error = self._export_blocked()

                self.assertIn(rectificativa, error.result["skipped_invoice_ids"])
                self.assertEqual(self._snapshot(rectificativa), before)

                with self._conn() as conn:
                    conn.execute(
                        "UPDATE eco_facturas SET activo = 0 WHERE id = ?",
                        (rectificativa,),
                    )
                    conn.commit()

    # ------------------------------------------------------------
    # Fail closed: datos ambiguos o inconsistentes
    # ------------------------------------------------------------

    def _assert_excluded_alongside_provision(self, factura) -> None:
        provision = self._provision()
        expected = self._expected_rows()
        before = self._snapshot(factura)

        result = self._export()

        self._assert_single_exported(result, provision, expected)
        self._assert_skipped(result, [factura])
        self.assertEqual(self._snapshot(factura), before)

    def test_desglose_con_suplido_y_factura_provision(self) -> None:
        cobro = self._cobro(
            138.28,
            lineas=[
                ("PROVISION", "PROVISION", 10000),
                ("OTRO", "SUPLIDO", 3828),
            ],
        )
        factura = self._factura(base=138.28, total=138.28, cobro_ids=[cobro])
        self._assert_excluded_alongside_provision(factura)

    def test_suplido_en_cobro_vinculado_no_primero(self) -> None:
        provision_cobro = self._cobro(100)
        suplido_cobro = self._cobro(
            38.28, tipo_fiscal="SUPLIDO", lineas=[("TASA", "SUPLIDO", 3828)]
        )
        factura = self._factura(
            base=138.28,
            total=138.28,
            cobro_ids=[provision_cobro, suplido_cobro],
        )
        self._assert_excluded_alongside_provision(factura)

    def test_cobro_legacy_suplido_sin_desglose(self) -> None:
        cobro = self._cobro(38.28, tipo_fiscal="SUPLIDO")
        factura = self._factura(base=38.28, total=38.28, cobro_ids=[cobro])
        self._assert_excluded_alongside_provision(factura)

    def test_suplido_adelantado_sin_naturaleza_fiscal(self) -> None:
        cobro = self._cobro(38.28, tipo_cobro="SUPLIDO_ADELANTADO")
        factura = self._factura(base=38.28, total=38.28, cobro_ids=[cobro])
        self._assert_excluded_alongside_provision(factura)

    def test_total_que_no_cuadra(self) -> None:
        # 38,28 sin declarar: nunca se trata como IVA 0 ordinario.
        factura = self._factura(base=100, iva=0, total=138.28)
        self._assert_excluded_alongside_provision(factura)

    def test_tipo_fiscal_ausente_o_desconocido(self) -> None:
        for tipo_fiscal in ("", "OTRO", "MIXTO"):
            with self.subTest(tipo_fiscal=tipo_fiscal):
                factura = self._factura(
                    base=100, total=100, tipo_fiscal=tipo_fiscal
                )
                before = self._snapshot(factura)

                error = self._export_blocked()

                self.assertEqual(error.result["skipped_invoice_ids"], [factura])
                self.assertEqual(self._snapshot(factura), before)

                with self._conn() as conn:
                    conn.execute(
                        "UPDATE eco_facturas SET activo = 0 WHERE id = ?",
                        (factura,),
                    )
                    conn.commit()

    def test_suplidos_no_numericos(self) -> None:
        factura = self._factura(base=100, total=100, suplidos="38,28")
        self._assert_excluded_alongside_provision(factura)

    def test_suplido_inferior_al_centimo(self) -> None:
        factura = self._factura(base=100, total=100, suplidos=0.004)
        self._assert_excluded_alongside_provision(factura)

    # ------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------

    def test_fallo_al_marcar_hace_rollback_y_no_deja_archivo(self) -> None:
        primera = self._provision()
        segunda = self._provision()
        with self._conn() as conn:
            conn.execute(
                f"""
                CREATE TRIGGER trg_test_fallo_marcado
                BEFORE UPDATE OF exportada_holded ON eco_facturas
                WHEN NEW.id = {segunda} AND NEW.exportada_holded = 1
                BEGIN
                    SELECT RAISE(ABORT, 'fallo simulado');
                END
                """
            )
            conn.commit()
        before = {fid: self._snapshot(fid) for fid in (primera, segunda)}

        with self.assertRaises(sqlite3.DatabaseError):
            self._export(mark_exported=True)

        self.assertEqual(self._xlsx_files(), [])
        for fid, snapshot in before.items():
            self.assertEqual(self._snapshot(fid), snapshot)


if __name__ == "__main__":
    unittest.main()

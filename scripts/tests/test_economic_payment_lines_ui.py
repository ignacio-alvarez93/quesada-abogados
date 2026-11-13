"""
ECO-ML-01B · Formulario «Conceptos del cobro» y tarjeta de cobro.

Controles Flet aislados, sin página, sin base de datos y sin servicios
con efectos: el editor y la tarjeta se instancian en memoria y la vista
se inspecciona de forma estática (AST/texto). Nunca se toca
database/quesada.db.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

import flet as ft

from backend.services import economic_cobro_lineas_service as lineas_domain
from frontend.components.economic_payment_card import economic_payment_card
from frontend.components.economic_payment_lines import PaymentLinesEditor


REPO_ROOT = Path(__file__).resolve().parents[2]
ECONOMIC_VIEW = REPO_ROOT / "frontend" / "views" / "economic_view.py"


def _type(field, value):
    """Simula que el usuario escribe/selecciona y dispara el handler."""
    field.value = value
    field.on_change(None)


def _fill(row, concepto, importe, tipo_economico="PROVISION", tipo_fiscal="PROVISION"):
    _type(row.concepto, concepto)
    _type(row.tipo_economico, tipo_economico)
    _type(row.tipo_fiscal, tipo_fiscal)
    _type(row.importe, importe)


def _texts(control):
    """Todos los textos visibles de un árbol de controles Flet."""
    found = []
    stack = [control]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        if isinstance(current, (list, tuple)):
            stack.extend(current)
            continue
        if isinstance(current, ft.Text) and current.value:
            found.append(str(current.value))
        for attr in ("controls", "content", "title", "subtitle"):
            child = getattr(current, attr, None)
            if child is not None and not isinstance(child, str):
                stack.append(child)
    return found


def _editor_138_28():
    editor = PaymentLinesEditor()
    _fill(editor.rows[0], "Provisión de fondos", "100,00")
    editor.add_button.on_click(None)
    _fill(editor.rows[1], "Tasa", "38,28", tipo_economico="TASA", tipo_fiscal="SUPLIDO")
    return editor


class AddRemoveLinesTest(unittest.TestCase):
    def test_alta_empieza_con_una_fila_que_no_se_puede_eliminar(self) -> None:
        editor = PaymentLinesEditor()

        self.assertEqual(len(editor.rows), 1)
        self.assertTrue(editor.rows[0].remove_button.disabled)
        editor.rows[0].remove_button.on_click(None)
        self.assertEqual(len(editor.rows), 1)
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 0,00 €")
        self.assertEqual(editor.summary_text.value, "1 concepto")

    def test_anadir_sin_limite_de_dos_filas(self) -> None:
        editor = PaymentLinesEditor()
        for _ in range(4):
            editor.add_button.on_click(None)

        self.assertEqual(len(editor.rows), 5)
        self.assertEqual(len(editor.rows_column.controls), 5)
        self.assertEqual(
            [row.position_text.value for row in editor.rows],
            ["1", "2", "3", "4", "5"],
        )
        self.assertEqual(editor.summary_text.value, "5 conceptos")
        self.assertTrue(all(not row.remove_button.disabled for row in editor.rows))

    def test_quitar_fila_renumera_y_recalcula(self) -> None:
        editor = PaymentLinesEditor()
        editor.add_button.on_click(None)
        editor.add_button.on_click(None)
        _type(editor.rows[0].importe, "1,00")
        _type(editor.rows[1].importe, "2,00")
        _type(editor.rows[2].importe, "4,00")
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 7,00 €")

        editor.rows[1].remove_button.on_click(None)

        self.assertEqual(len(editor.rows), 2)
        self.assertEqual([row.position_text.value for row in editor.rows], ["1", "2"])
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 5,00 €")

        editor.rows[0].remove_button.on_click(None)
        self.assertEqual(len(editor.rows), 1)
        self.assertTrue(editor.rows[0].remove_button.disabled)
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 4,00 €")

    def test_on_change_se_notifica_en_cambios_y_no_en_reset(self) -> None:
        callback = Mock()
        editor = PaymentLinesEditor(on_change=callback)
        callback.reset_mock()

        editor.reset()
        callback.assert_not_called()

        editor.add_button.on_click(None)
        _type(editor.rows[1].importe, "3")
        editor.rows[1].remove_button.on_click(None)
        self.assertEqual(callback.call_count, 3)
        callback.assert_called_with(editor)


class TotalsAndFormatTest(unittest.TestCase):
    def test_total_vinculante_138_28(self) -> None:
        editor = _editor_138_28()

        self.assertEqual(editor.total_text.value, "TOTAL COBRO 138,28 €")
        self.assertEqual(editor.total_centimos(), 13828)
        self.assertEqual(editor.summary_text.value, "2 conceptos")

    def test_centimos_exactos_y_formato_espanol(self) -> None:
        editor = PaymentLinesEditor()
        editor.add_button.on_click(None)
        _type(editor.rows[0].importe, "0,01")
        _type(editor.rows[1].importe, "0,02")
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 0,03 €")

        _type(editor.rows[0].importe, "1.234,56")
        _type(editor.rows[1].importe, "0.44")
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 1.235,00 €")

    def test_errores_de_importe_visibles_y_sin_redondeo(self) -> None:
        editor = PaymentLinesEditor()
        casos = {
            "": "importe obligatorio",
            "0": "mayor que cero",
            "-5": "mayor que cero",
            "1,234": "más de dos decimales",
            "abc": "formato de importe no válido",
        }
        for value, expected in casos.items():
            with self.subTest(value=value):
                _type(editor.rows[0].importe, value)
                total, errors = editor.compute()
                self.assertEqual(total, 0)
                self.assertIn(expected, editor.status_text.value)
                self.assertTrue(errors)
                with self.assertRaises(ValueError):
                    editor.payload_for_save()

    def test_total_es_solo_lectura(self) -> None:
        editor = PaymentLinesEditor()
        self.assertIsInstance(editor.total_text, ft.Text)
        inputs = [
            control
            for row in editor.rows
            for control in (row.concepto, row.importe)
        ]
        self.assertNotIn(editor.total_text, inputs)


class SelectionTest(unittest.TestCase):
    def test_opciones_de_tipo_y_naturaleza(self) -> None:
        row = PaymentLinesEditor().rows[0]
        self.assertEqual(
            [option.key for option in row.tipo_economico.options],
            ["PROVISION", "TASA", "HONORARIOS", "OTRO"],
        )
        self.assertEqual(
            [option.key for option in row.tipo_fiscal.options],
            ["PROVISION", "SUPLIDO"],
        )

    def test_naturaleza_fiscal_debe_ser_explicita(self) -> None:
        editor = PaymentLinesEditor()
        self.assertIsNone(editor.rows[0].tipo_fiscal.value)

        _type(editor.rows[0].concepto, "Provisión")
        _type(editor.rows[0].importe, "10")
        self.assertIsNone(editor.resumen_fiscal())
        self.assertIn("naturaleza fiscal", editor.status_text.value)
        with self.assertRaisesRegex(ValueError, "naturaleza fiscal"):
            editor.payload_for_save()

    def test_tasa_no_implica_suplido(self) -> None:
        editor = PaymentLinesEditor()
        _type(editor.rows[0].tipo_economico, "TASA")
        self.assertIsNone(editor.rows[0].tipo_fiscal.value)

        _type(editor.rows[0].tipo_fiscal, "PROVISION")
        self.assertEqual(editor.resumen_fiscal(), "PROVISION")

    def test_resumen_mixto(self) -> None:
        editor = _editor_138_28()
        self.assertEqual(editor.resumen_fiscal(), "MIXTO")

        _type(editor.rows[0].tipo_fiscal, "SUPLIDO")
        self.assertEqual(editor.resumen_fiscal(), "SUPLIDO")


class SavePayloadTest(unittest.TestCase):
    def test_alta_envia_lineas_en_centimos_sin_importe_global(self) -> None:
        payload = _editor_138_28().payload_for_save()

        self.assertEqual(set(payload), {"lineas"})
        self.assertEqual(
            payload["lineas"],
            [
                {
                    "concepto": "Provisión de fondos",
                    "tipo_economico": "PROVISION",
                    "tipo_fiscal": "PROVISION",
                    "importe_centimos": 10000,
                },
                {
                    "concepto": "Tasa",
                    "tipo_economico": "TASA",
                    "tipo_fiscal": "SUPLIDO",
                    "importe_centimos": 3828,
                },
            ],
        )

        # El contrato del servicio acepta exactamente este payload.
        validated = lineas_domain.validate_lineas(payload["lineas"])
        self.assertEqual(lineas_domain.total_centimos(validated), 13828)

    def test_guardar_con_servicio_falso_un_unico_cobro(self) -> None:
        service = Mock()
        service.create_cobro.return_value = 7
        editor = _editor_138_28()

        header = {
            "cliente_id": 1,
            "fecha_cobro": "2026-11-13",
            "forma_pago": "TRANSFERENCIA",
            "tipo_cobro": "PAGO_EXPEDIENTE",
            "recibo_ruta": "recibos/r1.pdf",
            "observaciones": "obs",
        }
        result = service.create_cobro({**header, **editor.payload_for_save()})

        self.assertEqual(result, 7)
        service.create_cobro.assert_called_once()
        sent = service.create_cobro.call_args.args[0]
        self.assertEqual(len(sent["lineas"]), 2)
        for key, value in header.items():
            self.assertEqual(sent[key], value)
        self.assertNotIn("tipo_fiscal", sent)

    def test_edicion_carga_lineas_persistidas(self) -> None:
        editor = PaymentLinesEditor()
        editor.reset(
            [
                {"id": 1, "posicion": 1, "concepto": "Provisión", "tipo_economico": "PROVISION",
                 "tipo_fiscal": "PROVISION", "importe_centimos": 10000},
                {"id": 2, "posicion": 2, "concepto": "Tasa", "tipo_economico": "TASA",
                 "tipo_fiscal": "SUPLIDO", "importe_centimos": 3828},
            ],
            sinteticas=False,
        )

        self.assertEqual(len(editor.rows), 2)
        self.assertEqual(editor.rows[1].importe.value, "38,28")
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 138,28 €")
        self.assertFalse(editor.is_modified())

        _type(editor.rows[1].importe, "40,00")
        editor.add_button.on_click(None)
        _fill(editor.rows[2], "Honorarios", "10", tipo_economico="HONORARIOS")
        payload = editor.payload_for_save()
        self.assertEqual(
            [linea["importe_centimos"] for linea in payload["lineas"]],
            [10000, 4000, 1000],
        )

    def test_legacy_sin_tocar_mantiene_contrato_legacy(self) -> None:
        legacy = lineas_domain.serializar_linea(
            lineas_domain.linea_legacy_desde_cobro(
                {"tipo_cobro": "PAGO_EXPEDIENTE", "tipo_fiscal": "SUPLIDO",
                 "importe": 50.5, "concepto": "Antiguo"}
            )
        )
        editor = PaymentLinesEditor()
        editor.reset([legacy], sinteticas=True)

        self.assertEqual(editor.rows[0].importe.value, "50,50")
        self.assertEqual(
            editor.payload_for_save(importe_legacy=50.5),
            {"importe": 50.5, "tipo_fiscal": "SUPLIDO", "concepto": "Antiguo"},
        )

        _type(editor.rows[0].concepto, "Antiguo corregido")
        payload = editor.payload_for_save(importe_legacy=50.5)
        self.assertEqual(set(payload), {"lineas"})
        self.assertEqual(payload["lineas"][0]["importe_centimos"], 5050)


class ReconciliationPrefillTest(unittest.TestCase):
    def test_prefill_exige_igualdad_con_movimiento(self) -> None:
        editor = PaymentLinesEditor()
        editor.reset(
            [{"concepto": "Cobro generado desde movimiento: X", "tipo_economico": "PROVISION",
              "importe_centimos": 13828}],
            target_centimos=13828,
        )
        self.assertEqual(len(editor.rows), 1)
        self.assertEqual(editor.rows[0].importe.value, "138,28")

        _fill(editor.rows[0], "Provisión", "100,00")
        self.assertIn("Faltan 38,28 €", editor.status_text.value)

        editor.add_button.on_click(None)
        _fill(editor.rows[1], "Tasa", "38,28", tipo_economico="TASA", tipo_fiscal="SUPLIDO")
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 138,28 €")

        payload = editor.payload_for_save()
        self.assertEqual(payload["importe"], "138,28")
        validated = lineas_domain.validate_lineas(payload["lineas"])
        lineas_domain.assert_total_coincide(validated, payload["importe"])

    def test_descuadre_con_movimiento_lo_rechaza_el_contrato(self) -> None:
        editor = PaymentLinesEditor()
        editor.reset(
            [{"concepto": "Mov", "tipo_economico": "PROVISION", "tipo_fiscal": "PROVISION",
              "importe_centimos": 10000}],
            target_centimos=13828,
        )
        payload = editor.payload_for_save()
        validated = lineas_domain.validate_lineas(payload["lineas"])
        with self.assertRaisesRegex(ValueError, "no coincide"):
            lineas_domain.assert_total_coincide(validated, payload["importe"])


class ReopenModalStateTest(unittest.TestCase):
    def test_reabrir_tras_cancelar_o_error_deja_estado_limpio(self) -> None:
        editor = _editor_138_28()
        _type(editor.rows[1].importe, "-1")
        with self.assertRaises(ValueError):
            editor.payload_for_save()
        # Tras el error el estado sigue intacto para corregir.
        self.assertEqual(len(editor.rows), 2)
        self.assertEqual(editor.rows[1].importe.value, "-1")

        editor.reset()
        self.assertEqual(len(editor.rows), 1)
        self.assertEqual(editor.rows[0].concepto.value, "")
        self.assertEqual(editor.rows[0].importe.value, "")
        self.assertFalse(editor.sinteticas)
        self.assertIsNone(editor.target_centimos)
        self.assertFalse(editor.is_modified())
        self.assertEqual(editor.total_text.value, "TOTAL COBRO 0,00 €")

    def test_reabrir_edicion_no_arrastra_contexto_de_conciliacion(self) -> None:
        editor = PaymentLinesEditor()
        editor.reset([{"concepto": "Mov", "importe_centimos": 500}], target_centimos=500)
        editor.reset([{"concepto": "Otro", "tipo_fiscal": "PROVISION", "importe_centimos": 700}])
        self.assertIsNone(editor.target_centimos)
        self.assertNotIn("importe", editor.payload_for_save())


class PaymentCardTest(unittest.TestCase):
    def _cobro(self, **extra):
        base = {
            "id": 1,
            "numero_cobro": "C-2026-0001",
            "nombre": "Ana",
            "fecha_cobro": "2026-11-13",
            "importe": 138.28,
            "forma_pago": "TRANSFERENCIA",
            "tipo_cobro": "PAGO_EXPEDIENTE",
            "tipo_fiscal": "MIXTO",
            "concepto": "Provisión + Tasa",
        }
        base.update(extra)
        return base

    def test_mixto_con_desglose_en_una_sola_tarjeta(self) -> None:
        cobro = self._cobro(
            resumen_fiscal="MIXTO",
            resumen_lineas="2 conceptos",
            lineas=[
                {"posicion": 1, "concepto": "Provisión", "tipo_economico": "PROVISION",
                 "tipo_fiscal": "PROVISION", "importe_centimos": 10000},
                {"posicion": 2, "concepto": "Tasa DGT", "tipo_economico": "TASA",
                 "tipo_fiscal": "SUPLIDO", "importe_centimos": 3828},
            ],
        )
        texts = _texts(economic_payment_card(cobro))
        joined = " | ".join(texts).lower()

        self.assertIn("138,28 €", texts)
        self.assertIn("2 conceptos", texts)
        self.assertIn("mixto", joined)
        self.assertIn("100,00 €", texts)
        self.assertIn("38,28 €", texts)
        self.assertIn("Tasa DGT", texts)
        self.assertIn("tasa · suplido", joined)
        # Desglose dentro de la tarjeta: el total aparece una sola vez.
        self.assertEqual(texts.count("138,28 €"), 1)

    def test_legacy_sin_lineas_conserva_tarjeta_actual(self) -> None:
        cobro = self._cobro(tipo_fiscal="SUPLIDO", importe=50, concepto="Antiguo")
        texts = _texts(economic_payment_card(cobro))
        joined = " | ".join(texts).lower()

        self.assertIn("50,00 €", texts)
        self.assertIn("Antiguo", texts)
        self.assertIn("suplido", joined)
        self.assertNotIn("conceptos", joined)

    def test_mixto_nunca_se_muestra_como_provision(self) -> None:
        cobro = self._cobro(resumen_fiscal=None, tipo_fiscal="MIXTO")
        joined = " | ".join(_texts(economic_payment_card(cobro))).lower()
        self.assertIn("mixto", joined)


class EconomicViewContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ECONOMIC_VIEW.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.FunctionDef)
        }

    def _body(self, name):
        return ast.get_source_segment(self.source, self.functions[name])

    def test_crear_y_editar_usan_el_mismo_componente(self) -> None:
        self.assertEqual(self.source.count("PaymentLinesEditor()"), 2)
        self.assertEqual(self.source.count('"Conceptos del cobro"'), 2)
        self.assertIn("**lineas_payload", self._body("save_cobro"))
        self.assertIn("**lineas_payload", self._body("save_edit_cobro"))

    def test_sin_captura_plana_de_importe_ni_naturaleza(self) -> None:
        for removed in ("cobro_importe", "cobro_tipo_fiscal", "edit_cobro_importe",
                        "edit_cobro_tipo_fiscal", "cobro_concepto"):
            self.assertNotRegex(self.source, rf"\b{removed}\b")

    def test_handlers_de_cobro_sin_sql(self) -> None:
        for name in ("open_cobro_dialog", "save_cobro", "open_manual_cobro_dialog",
                     "cancel_cobro_dialog", "open_edit_cobro_dialog", "save_edit_cobro",
                     "on_edit_cobro_lineas_change"):
            body = self._body(name)
            with self.subTest(handler=name):
                self.assertNotIn("sqlite3", body)
                self.assertNotIn(".execute(", body)

    def test_edicion_conserva_cabecera(self) -> None:
        body = self._body("save_edit_cobro")
        for key in ("fecha_cobro", "cliente_id", "expediente_id", "hoja_encargo_id",
                    "forma_pago", "observaciones", "recibo_ruta"):
            self.assertIn(f'"{key}"', body)

    def test_aviso_de_facturacion_acorde_a_data_004(self) -> None:
        self.assertNotIn("generará", self.source)
        self.assertNotIn("automáticamente una factura si todavía no existe", self.source)
        self.assertIn("No se emite ninguna factura automáticamente", self.source)
        self.assertEqual(self.source.count("COBRO_FACTURABLE_NOTICE"), 3)

    def test_conciliacion_un_unico_movimiento_y_regreso_al_modal(self) -> None:
        cancel = self._body("cancel_cobro_dialog")
        self.assertIn("_reopen_reconciliation_after_generated_cobro()", cancel)
        self.assertIn('state.pop("pending_linked_cobro_from_reconciliation"', cancel)

        manual = self._body("open_manual_cobro_dialog")
        self.assertIn('state.pop("pending_linked_cobro_from_reconciliation"', manual)
        self.assertIn("on_click=open_manual_cobro_dialog", self.source)

        opener = self._body("open_cobro_dialog")
        self.assertIn("target_centimos=linked_amount_centimos", opener)
        self.assertEqual(opener.count("cobro_lineas_editor.reset("), 2)


if __name__ == "__main__":
    unittest.main()

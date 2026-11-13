"""
ECO-ML-01A · Dominio puro del desglose de cobros.

Sin base de datos: solo Decimal/céntimos y reglas de validación.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from backend.services import economic_cobro_lineas_service as lineas_domain


def _linea(concepto, importe, tipo_economico="PROVISION", tipo_fiscal="PROVISION"):
    return {
        "concepto": concepto,
        "importe": importe,
        "tipo_economico": tipo_economico,
        "tipo_fiscal": tipo_fiscal,
    }


class ParseImporteTest(unittest.TestCase):
    def test_formatos_validos(self) -> None:
        casos = {
            "138,28": 13828,
            "138.28": 13828,
            "1.234,56": 123456,
            "1,234.56": 123456,
            "1.234.567": 123456700,
            "100": 10000,
            "0,01": 1,
            "38,2": 3820,
            " 38,28 € ": 3828,
            "1 234,56": 123456,
            Decimal("38.28"): 3828,
            100: 10000,
            38.28: 3828,
        }
        for value, expected in casos.items():
            with self.subTest(value=value):
                self.assertEqual(
                    lineas_domain.parse_importe_centimos(value),
                    expected,
                )

    def test_rechaza_mas_de_dos_decimales_sin_redondear(self) -> None:
        for value in ("0,001", "38,285", Decimal("0.005"), "1.234"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "dos decimales"):
                    lineas_domain.parse_importe_centimos(value)

    def test_rechaza_cero_y_negativos_en_cobro_ordinario(self) -> None:
        for value in ("0", "0,00", "-1", "-0,01", 0, Decimal("-5")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "mayor que cero"):
                    lineas_domain.parse_importe_centimos(value)

    def test_rechaza_formatos_ambiguos_o_vacios(self) -> None:
        for value in ("", "   ", None, True, "abc", "1,2,3", "12.34.5", "1.23,4.5", float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    lineas_domain.parse_importe_centimos(value)

    def test_formato_espanol(self) -> None:
        self.assertEqual(lineas_domain.format_centimos_es(13828), "138,28")
        self.assertEqual(lineas_domain.format_centimos_es(3), "0,03")
        self.assertEqual(lineas_domain.format_centimos_es(123456789), "1.234.567,89")
        self.assertEqual(lineas_domain.format_centimos_es(-100), "-1,00")

    def test_centimos_a_euros_exacto(self) -> None:
        self.assertEqual(lineas_domain.centimos_a_euros(13828), 138.28)
        self.assertEqual(lineas_domain.centimos_a_euros(3), 0.03)


class ValidateLineasTest(unittest.TestCase):
    def test_escenario_vinculante_100_mas_38_28(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [
                _linea("Provisión", "100,00", "PROVISION", "PROVISION"),
                _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
            ]
        )
        self.assertEqual(lineas_domain.total_centimos(lineas), 13828)
        self.assertEqual([l["posicion"] for l in lineas], [1, 2])
        self.assertEqual(lineas[1]["tipo_economico"], "TASA")
        self.assertEqual(
            lineas_domain.desglose_fiscal_centimos(lineas),
            {"PROVISION": 10000, "SUPLIDO": 3828},
        )
        self.assertEqual(lineas_domain.resumen_fiscal(lineas), "MIXTO")

    def test_suma_centimetrica(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [_linea("A", "0,01"), _linea("B", "0,02")]
        )
        self.assertEqual(lineas_domain.total_centimos(lineas), 3)
        self.assertEqual(lineas_domain.centimos_a_euros(3), 0.03)

    def test_tasa_no_implica_suplido(self) -> None:
        sin_fiscal = _linea("Tasa", "38,28", "TASA", "")
        with self.assertRaisesRegex(ValueError, "Línea 1 · naturaleza fiscal"):
            lineas_domain.validate_lineas([sin_fiscal])

        tasa_provision = lineas_domain.validate_lineas(
            [_linea("Tasa", "38,28", "TASA", "PROVISION")]
        )
        self.assertEqual(tasa_provision[0]["tipo_fiscal"], "PROVISION")

    def test_acentos_y_minusculas_normalizados(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [_linea("x", "1", "provisión", "Provisión")]
        )
        self.assertEqual(lineas[0]["tipo_economico"], "PROVISION")
        self.assertEqual(lineas[0]["tipo_fiscal"], "PROVISION")

    def test_errores_identifican_la_linea(self) -> None:
        with self.assertRaisesRegex(ValueError, "Línea 2: el concepto"):
            lineas_domain.validate_lineas([_linea("A", "1"), _linea("  ", "1")])
        with self.assertRaisesRegex(ValueError, "Línea 2"):
            lineas_domain.validate_lineas([_linea("A", "1"), _linea("B", "0")])
        with self.assertRaisesRegex(ValueError, "Línea 1 · tipo económico"):
            lineas_domain.validate_lineas([_linea("A", "1", "IVA")])
        with self.assertRaisesRegex(ValueError, "Línea 1 · naturaleza fiscal"):
            lineas_domain.validate_lineas([_linea("A", "1", "OTRO", "MIXTO")])

    def test_lista_vacia_o_no_lista(self) -> None:
        for value in ([], None, "x", {"concepto": "A"}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    lineas_domain.validate_lineas(value)

    def test_importe_centimos_entero(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [{"concepto": "A", "importe_centimos": 3828, "tipo_economico": "TASA", "tipo_fiscal": "SUPLIDO"}]
        )
        self.assertEqual(lineas[0]["importe_centimos"], 3828)
        with self.assertRaises(ValueError):
            lineas_domain.validate_lineas(
                [{"concepto": "A", "importe_centimos": 38.28, "tipo_economico": "TASA", "tipo_fiscal": "SUPLIDO"}]
            )

    def test_sin_limite_artificial_de_lineas(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [_linea(f"L{i}", "0,01") for i in range(25)]
        )
        self.assertEqual(len(lineas), 25)
        self.assertEqual(lineas_domain.total_centimos(lineas), 25)

    def test_total_declarado_debe_coincidir(self) -> None:
        lineas = lineas_domain.validate_lineas(
            [_linea("A", "100"), _linea("B", "38,28", "TASA", "SUPLIDO")]
        )
        lineas_domain.assert_total_coincide(lineas, "138,28")
        lineas_domain.assert_total_coincide(lineas, None)
        with self.assertRaisesRegex(ValueError, "no coincide"):
            lineas_domain.assert_total_coincide(lineas, "138,27")


class ReglasVinculacionTest(unittest.TestCase):
    def _lineas(self, *items):
        return lineas_domain.validate_lineas(list(items))

    def test_tasa_en_linea_exige_expediente(self) -> None:
        lineas = self._lineas(_linea("Tasa", "38,28", "TASA", "SUPLIDO"))
        with self.assertRaisesRegex(ValueError, "TASA"):
            lineas_domain.validar_reglas_vinculacion("CONSULTA", None, None, lineas)
        lineas_domain.validar_reglas_vinculacion("CONSULTA", 7, None, lineas)

    def test_provision_ordinaria_exige_hoja(self) -> None:
        lineas = self._lineas(
            _linea("Provisión", "100"),
            _linea("Tasa", "38,28", "TASA", "SUPLIDO"),
        )
        with self.assertRaisesRegex(ValueError, "hoja"):
            lineas_domain.validar_reglas_vinculacion("PAGO_EXPEDIENTE", 7, None, lineas)
        lineas_domain.validar_reglas_vinculacion("PAGO_EXPEDIENTE", 7, 3, lineas)

    def test_solo_tasa_y_suplido_no_exigen_hoja(self) -> None:
        lineas = self._lineas(
            _linea("Tasa", "38,28", "TASA", "PROVISION"),
            _linea("Gasto", "10", "OTRO", "SUPLIDO"),
        )
        lineas_domain.validar_reglas_vinculacion("PAGO_EXPEDIENTE", 7, None, lineas)

    def test_suplido_adelantado_no_admite_provision_con_desglose(self) -> None:
        lineas = self._lineas(
            _linea("Gasto", "10", "OTRO", "SUPLIDO"),
            _linea("Provisión", "5"),
        )
        with self.assertRaisesRegex(ValueError, "SUPLIDO_ADELANTADO"):
            lineas_domain.validar_reglas_vinculacion("SUPLIDO_ADELANTADO", 7, None, lineas)

    def test_linea_legacy_mantiene_reglas_legacy(self) -> None:
        legacy = [
            lineas_domain.linea_legacy_desde_cobro(
                {"tipo_cobro": "SUPLIDO_ADELANTADO", "tipo_fiscal": "PROVISION", "importe": 5}
            )
        ]
        lineas_domain.validar_reglas_vinculacion(
            "SUPLIDO_ADELANTADO", None, None, legacy, desglose_explicito=False
        )


class LegacyLecturaTest(unittest.TestCase):
    def test_linea_sintetica(self) -> None:
        resumen = lineas_domain.resumen_desglose(
            {"importe": 138.28, "concepto": "PAGO", "tipo_cobro": "PAGO_EXPEDIENTE", "tipo_fiscal": "PROVISION"},
            [],
        )
        self.assertTrue(resumen["lineas_sinteticas"])
        self.assertEqual(resumen["num_lineas"], 1)
        self.assertEqual(resumen["resumen_lineas"], "1 concepto")
        self.assertEqual(resumen["importe_centimos"], 13828)
        self.assertEqual(resumen["lineas"][0]["tipo_economico"], "PROVISION")
        self.assertEqual(resumen["lineas"][0]["importe_formateado"], "138,28")

    def test_mapeo_tipo_cobro(self) -> None:
        self.assertEqual(lineas_domain.tipo_economico_desde_tipo_cobro("TASA"), "TASA")
        self.assertEqual(lineas_domain.tipo_economico_desde_tipo_cobro("CONSULTA"), "HONORARIOS")
        self.assertEqual(lineas_domain.tipo_economico_desde_tipo_cobro("SUPLIDO_ADELANTADO"), "OTRO")
        self.assertEqual(lineas_domain.tipo_economico_desde_tipo_cobro("PAGO_EXPEDIENTE"), "PROVISION")
        self.assertEqual(lineas_domain.tipo_fiscal_legacy("PROVISIÓN"), "PROVISION")
        self.assertEqual(lineas_domain.tipo_fiscal_legacy("suplido"), "SUPLIDO")

    def test_importe_legacy_ilegible_no_rompe_lectura(self) -> None:
        self.assertEqual(lineas_domain.centimos_desde_importe_legacy("x"), 0)
        self.assertEqual(lineas_domain.centimos_desde_importe_legacy(None), 0)


if __name__ == "__main__":
    unittest.main()

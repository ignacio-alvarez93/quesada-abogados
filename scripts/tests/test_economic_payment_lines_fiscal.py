"""
ECO-ML-01 · RECOVERY-FISCAL-MIXTA · Cálculo fiscal por naturaleza de línea.

Sin base de datos: dominio puro + fórmula legacy _calculate_invoice_from_total.
"""

from __future__ import annotations

import unittest

from backend.services import economic_cobro_lineas_service as lineas_domain
from backend.services.economic_service import _calculate_invoice_from_total


def _linea(concepto, importe, tipo_economico="PROVISION", tipo_fiscal="PROVISION"):
    return {
        "concepto": concepto,
        "importe": importe,
        "tipo_economico": tipo_economico,
        "tipo_fiscal": tipo_fiscal,
    }


ESCENARIO = [
    _linea("Provisión de honorarios", "100,00", "PROVISION", "PROVISION"),
    _linea("Tasa pagada por cuenta del cliente", "38,28", "TASA", "SUPLIDO"),
]


def _fiscal(lineas, iva="0", irpf="0"):
    return lineas_domain.calcular_fiscal_factura(
        lineas_domain.validate_lineas(lineas),
        iva,
        irpf,
        _calculate_invoice_from_total,
    )


def _centimos(value):
    return lineas_domain.centimos_desde_importe_legacy(value)


class CalculoFiscalMixtoTest(unittest.TestCase):
    def _assert_cuadra(self, fiscal, total_centimos):
        self.assertEqual(
            _centimos(fiscal["base_imponible"])
            + _centimos(fiscal["iva"])
            - _centimos(fiscal["irpf"])
            + _centimos(fiscal["suplidos"]),
            total_centimos,
        )
        self.assertEqual(_centimos(fiscal["total"]), total_centimos)

    def test_ejemplo_contractual_iva_21(self) -> None:
        fiscal = _fiscal(ESCENARIO, iva="21", irpf="0")
        self.assertEqual(
            fiscal,
            {
                "base_imponible": 82.64,
                "iva": 17.36,
                "irpf": 0.0,
                "suplidos": 38.28,
                "total": 138.28,
                "tipo_fiscal": "MIXTO",
            },
        )
        self._assert_cuadra(fiscal, 13828)

    def test_provision_usa_exactamente_la_formula_legacy(self) -> None:
        for iva, irpf in (("0", "0"), ("21", "0"), ("21", "15"), ("0", "15"), ("10", "7")):
            with self.subTest(iva=iva, irpf=irpf):
                fiscal = _fiscal(ESCENARIO, iva=iva, irpf=irpf)
                legacy = _calculate_invoice_from_total(100.0, iva, irpf)
                self.assertEqual(fiscal["base_imponible"], legacy["base_imponible"])
                self.assertEqual(fiscal["iva"], legacy["iva"])
                self.assertEqual(fiscal["irpf"], legacy["irpf"])
                self.assertEqual(fiscal["suplidos"], 38.28)
                self._assert_cuadra(fiscal, 13828)

    def test_iva_cero(self) -> None:
        fiscal = _fiscal(ESCENARIO, iva="0", irpf="0")
        self.assertEqual(fiscal["base_imponible"], 100.0)
        self.assertEqual(fiscal["iva"], 0.0)
        self.assertEqual(fiscal["suplidos"], 38.28)
        self._assert_cuadra(fiscal, 13828)

    def test_varios_conceptos_por_naturaleza(self) -> None:
        lineas = [
            _linea("Provisión A", "60", "PROVISION", "PROVISION"),
            _linea("Tasa", "30", "TASA", "SUPLIDO"),
            _linea("Honorarios B", "40", "HONORARIOS", "PROVISION"),
            _linea("Registro", "8,28", "OTRO", "SUPLIDO"),
        ]
        self.assertEqual(_fiscal(lineas, iva="21"), _fiscal(ESCENARIO, iva="21"))

    def test_centimos_residuales(self) -> None:
        lineas = [
            _linea("P1", "33,33"),
            _linea("P2", "33,33"),
            _linea("P3", "33,34"),
            _linea("S1", "0,01", "OTRO", "SUPLIDO"),
        ]
        for iva, irpf in (("21", "0"), ("21", "15"), ("0", "15")):
            with self.subTest(iva=iva, irpf=irpf):
                self._assert_cuadra(_fiscal(lineas, iva=iva, irpf=irpf), 10001)

    def test_homogeneo_provision_igual_a_legacy(self) -> None:
        for importe in ("138,28", "0,01", "1.234,56", "99,99"):
            with self.subTest(importe=importe):
                fiscal = _fiscal([_linea("P", importe)], iva="21", irpf="15")
                total = lineas_domain.centimos_a_euros(
                    lineas_domain.parse_importe_centimos(importe)
                )
                legacy = _calculate_invoice_from_total(total, "21", "15")
                legacy["suplidos"] = 0.0
                legacy["tipo_fiscal"] = "PROVISION"
                self.assertEqual(fiscal, legacy)

    def test_homogeneo_suplido_igual_a_legacy(self) -> None:
        fiscal = _fiscal(
            [_linea("Tasa", "38,28", "TASA", "SUPLIDO")], iva="21", irpf="15"
        )
        self.assertEqual(
            fiscal,
            {
                "base_imponible": 0.0,
                "iva": 0.0,
                "irpf": 0.0,
                "suplidos": 38.28,
                "total": 38.28,
                "tipo_fiscal": "SUPLIDO",
            },
        )

    def test_tasa_no_marcada_como_suplido_tributa(self) -> None:
        lineas = [
            _linea("Provisión", "100", "PROVISION", "PROVISION"),
            _linea("Tasa", "38,28", "TASA", "PROVISION"),
        ]
        fiscal = _fiscal(lineas, iva="21")
        self.assertEqual(fiscal["suplidos"], 0.0)
        self.assertEqual(fiscal["tipo_fiscal"], "PROVISION")
        self.assertEqual(
            fiscal["base_imponible"],
            _calculate_invoice_from_total(138.28, "21", "0")["base_imponible"],
        )

    def test_naturaleza_fiscal_no_se_infiere(self) -> None:
        with self.assertRaisesRegex(ValueError, "PROVISION o SUPLIDO"):
            _fiscal([_linea("Tasa", "38,28", "TASA", "")])


if __name__ == "__main__":
    unittest.main()

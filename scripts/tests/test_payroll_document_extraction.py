import unittest

from backend.services import (
    payroll_document_extraction_service
    as payroll,
)


FULL_PAYROLL_TEXT = """
NÓMINA
EMPRESA: SERVICIOS ASTURIAS SL
CIF: B12345678
TRABAJADOR: JUAN PÉREZ GARCÍA
NIF: 12345678Z
PERIODO: 07/2026

TOTAL DEVENGADO 1.540,00
TOTAL DEDUCCIONES 320,00
BASE DE COTIZACIÓN 1.480,00
RETENCIÓN IRPF 85,00
LÍQUIDO A PERCIBIR 1.220,00
"""


class PayrollDocumentExtractionTest(
    unittest.TestCase
):
    def test_detects_payroll_document(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["document_type"],
            "PAYROLL",
        )

    def test_extracts_employee_name(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["employee_name"],
            "JUAN PÉREZ GARCÍA",
        )

    def test_extracts_employee_identity(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["employee_identity"],
            "12345678Z",
        )

    def test_extracts_company_data(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["company_name"],
            "SERVICIOS ASTURIAS SL",
        )
        self.assertEqual(
            result["company_tax_id"],
            "B12345678",
        )

    def test_extracts_period(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["period_month"],
            7,
        )
        self.assertEqual(
            result["period_year"],
            2026,
        )

    def test_extracts_money_in_centimos(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertEqual(
            result["total_accrued_centimos"],
            154000,
        )
        self.assertEqual(
            result["total_deductions_centimos"],
            32000,
        )
        self.assertEqual(
            result["net_pay_centimos"],
            122000,
        )
        self.assertEqual(
            result["contribution_base_centimos"],
            148000,
        )
        self.assertEqual(
            result["irpf_centimos"],
            8500,
        )

    def test_requires_manual_review(self):
        result = payroll.extract_payroll_text(
            FULL_PAYROLL_TEXT
        )

        self.assertTrue(
            result["requires_manual_review"]
        )
        self.assertEqual(
            result["review_status"],
            "PENDIENTE_REVISION",
        )

    def test_does_not_modify_any_external_state(self):
        result = payroll.extract_payroll_data(
            FULL_PAYROLL_TEXT,
            source_path="nomina_julio.pdf",
        )

        self.assertEqual(
            result["source_path"],
            "nomina_julio.pdf",
        )
        self.assertNotIn(
            "applied_to_diagnosis",
            result,
        )

    def test_detects_month_name_period(self):
        text = """
        RECIBO DE SALARIOS
        Periodo: JULIO DE 2026
        TOTAL DEVENGADO: 1.000,00
        TOTAL DEDUCCIONES: 200,00
        LÍQUIDO A PERCIBIR: 800,00
        """

        result = payroll.extract_payroll_text(text)

        self.assertEqual(
            result["period_month"],
            7,
        )
        self.assertEqual(
            result["period_year"],
            2026,
        )

    def test_unknown_document_produces_warning(self):
        result = payroll.extract_payroll_text(
            "Documento sin información salarial"
        )

        self.assertEqual(
            result["document_type"],
            "UNKNOWN",
        )
        self.assertTrue(result["warnings"])

    def test_missing_net_pay_requires_warning(self):
        text = """
        NÓMINA
        TOTAL DEVENGADO 1.200,00
        TOTAL DEDUCCIONES 200,00
        """

        result = payroll.extract_payroll_text(text)

        self.assertIn(
            (
                "No se ha detectado el líquido "
                "a percibir."
            ),
            result["warnings"],
        )

    def test_extracts_real_ocr_liquidation_period(self):
        text = """
        RECIBO DE SALARIOS
        TRABAJADOR PERSONA DE PRUEBA
        Período de liquidación: MENS del 1 de
        FEBRERO al 28 de FEBRERO de 2026
        A. TOTAL DEVENGADO 1.935,85
        B. TOTAL A DEDUCIR 426,05
        LIQUIDO TOTAL A PERCIBIR (A-B)
        Euros 1.509,80
        BASE DE COTIZACION 1.935,85
        """

        result = payroll.extract_payroll_text(
            text
        )

        self.assertEqual(
            result["document_type"],
            "PAYROLL",
        )
        self.assertEqual(
            result["period_month"],
            2,
        )
        self.assertEqual(
            result["period_year"],
            2026,
        )
        self.assertEqual(
            result["net_pay_centimos"],
            150980,
        )

    def test_detects_ocr_payroll_without_nomina_word(self):
        text = """
        PERIODO DE LIQUIDACION:
        MENS DEL 1 DE ENERO AL 31 DE ENERO DE 2026
        A. TOTAL DEVENGADO 2.071,93
        B. TOTAL A DEDUCIR 453,37
        LIQUIDO TOTAL A PERCIBIR 1.618,56
        CONTINGENCIAS COMUNES 2.071,93
        """

        result = payroll.extract_payroll_text(
            text
        )

        self.assertEqual(
            result["document_type"],
            "PAYROLL",
        )
        self.assertEqual(
            result["period_month"],
            1,
        )
        self.assertEqual(
            result["period_year"],
            2026,
        )
        self.assertEqual(
            result["net_pay_centimos"],
            161856,
        )

    def test_detects_inconsistent_totals(self):
        text = """
        NÓMINA
        PERIODO: 07/2026
        TOTAL DEVENGADO 1.200,00
        TOTAL DEDUCCIONES 200,00
        LÍQUIDO A PERCIBIR 700,00
        """

        result = payroll.extract_payroll_text(text)

        self.assertIn(
            (
                "El líquido detectado no coincide "
                "con devengos menos deducciones."
            ),
            result["warnings"],
        )


if __name__ == "__main__":
    unittest.main()

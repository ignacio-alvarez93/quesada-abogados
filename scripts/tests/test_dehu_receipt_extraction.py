import unittest

from backend.services.dehu_receipt_extraction_service import (
    extract_dehu_receipt_text,
)


SAMPLE_TEXT = """
Aplicación Código CSV Fecha de registro
DEHU DEHU-1637-5b5d-469a-70bf-11d4-526b-46a2-267a 17/07/2026

URL de validación DNI/NIE del interesado
https://run.gob.es/hsblF8yLcR 23010047L

El servicio de Dirección Electrónica Habilitada Única (DEHÚ)
certifica que:

Documento asociado: 23010047L
Nombre/Razón social: ANA BELEN QUESADA SOLER

En calidad de TITULAR para ACEPTAR la notificación
puesta a disposición en la DEHÚ:

Identificador: 52818606a595bcdc2c69
Remitida por: Oficina de Extranjeria en Oviedo
Concepto: not_330020260007641_21314223_10904599

Fecha de puesta a disposición: 17/07/2026 00:31
Fecha de acceso al contenido de la notificación:
17/07/2026 09:49
"""


class DehuReceiptExtractionTest(
    unittest.TestCase
):
    def test_extracts_identifier_and_reference(
        self,
    ):
        result = extract_dehu_receipt_text(
            SAMPLE_TEXT
        )

        self.assertEqual(
            result["document_type"],
            "DEHU_ACCESS_RECEIPT",
        )
        self.assertEqual(
            result["dehu_identifier"],
            "52818606a595bcdc2c69",
        )
        self.assertEqual(
            result["reference_value"],
            "330020260007641",
        )
        self.assertEqual(
            result["concept"],
            (
                "not_330020260007641_"
                "21314223_10904599"
            ),
        )

    def test_extracts_access_data(self):
        result = extract_dehu_receipt_text(
            SAMPLE_TEXT
        )

        self.assertEqual(
            result["action"],
            "ACEPTAR",
        )
        self.assertEqual(
            result["available_at"],
            "2026-07-17 00:31:00",
        )
        self.assertEqual(
            result["accessed_at"],
            "2026-07-17 09:49:00",
        )
        self.assertEqual(
            result[
                "interested_party_document"
            ],
            "23010047L",
        )

    def test_extracts_certificate_data(self):
        result = extract_dehu_receipt_text(
            SAMPLE_TEXT
        )

        self.assertEqual(
            result["registration_csv"],
            (
                "DEHU-1637-5b5d-469a-"
                "70bf-11d4-526b-46a2-267a"
            ),
        )
        self.assertEqual(
            result["validation_url"],
            "https://run.gob.es/hsblF8yLcR",
        )
        self.assertEqual(
            result["relationship_role"],
            "TITULAR",
        )

    def test_handles_broken_pdf_lines(self):
        result = extract_dehu_receipt_text(
            """
            En calidad de TITULAR para
            ACEPTAR
            la notificación.

            Identificador:
            52818606a595bcdc2c69

            Fecha de acceso al contenido
            de la notificación:
            17/07/2026 09:49
            """
        )

        self.assertEqual(
            result["action"],
            "ACEPTAR",
        )
        self.assertEqual(
            result["dehu_identifier"],
            "52818606a595bcdc2c69",
        )
        self.assertEqual(
            result["accessed_at"],
            "2026-07-17 09:49:00",
        )

    def test_handles_reordered_pdf_columns(self):
        result = extract_dehu_receipt_text(
            """
            52818606a595bcdc2c69
            Identificador

            17/07/2026 09:49
            Fecha de acceso al contenido
            de la notificación

            RECHAZAR la notificación
            """
        )

        self.assertEqual(
            result["dehu_identifier"],
            "52818606a595bcdc2c69",
        )
        self.assertEqual(
            result["accessed_at"],
            "2026-07-17 09:49:00",
        )
        self.assertEqual(
            result["action"],
            "RECHAZAR",
        )

    def test_missing_identifier_warns(self):
        result = extract_dehu_receipt_text(
            """
            El servicio de Dirección Electrónica
            Habilitada Única certifica que se produjo
            una comparecencia.
            """
        )

        self.assertFalse(
            result["dehu_identifier"]
        )
        self.assertTrue(
            any(
                "identificador"
                in warning.lower()
                for warning
                in result["warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main()

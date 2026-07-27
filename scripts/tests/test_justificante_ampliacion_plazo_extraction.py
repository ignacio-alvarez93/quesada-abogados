import unittest

from backend.services import (
    justificante_ampliacion_plazo_extraction_service
    as extractor,
)


SAMPLE = """
Código seguro de Verificación :
GEISER-c55a-d89c-bce7-4e88-a9ac-1129-a5d9-7d2d

RECIBO DE PRESENTACIÓN EN OFICINA DE REGISTRO

Fecha y hora de registro en 25/02/2026 09:55:27
Número de registro: REGAGE26e00019933335

Z3923594Y Nombre: HERNANDEZ CRUZ ASHLY DAYANNA

Resumen/Asunto: Se adjunta documentación por Internet
al expte. num.: 390020250007748

Unidad de tramitación destino/Centro directivo:
Oficina de Extranjeria en Santander - EA0040331

Nº. Expediente: 390020250007748

Adjuntos
Nombre: SOLICITUD AMPLIACION_PLAZO.pdf
Validez: Original
Tipo: Documento Adjunto

Observaciones:
SOLICITUD AMPLIACION PLAZO REQUERIMIENTO

Formulario Presentación
"""


class ExtensionReceiptExtractionTest(
    unittest.TestCase
):
    def test_regage_split_by_pdf_layout(self):
        sample = """
        Número de registro:
        REGAGE26 e 00019933335
        SOLICITUD AMPLIACION PLAZO REQUERIMIENTO
        """

        result = (
            extractor
            .extract_extension_receipt_text(
                sample
            )
        )

        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00019933335",
        )


    def test_regage_with_character_separators(self):
        sample = """
        RECIBO DE PRESENTACIÓN

        Número de registro:
        R E G A G E - 2 6 - e - 0 0 0 1 9 9 3 3 3 3 5

        SOLICITUD AMPLIACION PLAZO REQUERIMIENTO
        """

        result = (
            extractor
            .extract_extension_receipt_text(
                sample
            )
        )

        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00019933335",
        )


    def test_extension_receipt(self):
        result = (
            extractor
            .extract_extension_receipt_text(
                SAMPLE
            )
        )

        self.assertEqual(
            result["fecha_hora_registro"],
            "2026-02-25 09:55:27",
        )
        self.assertEqual(
            result["csv_geiser"],
            "GEISER-c55a-d89c-bce7-4e88-a9ac-1129-a5d9-7d2d",
        )
        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00019933335",
        )
        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "390020250007748",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z3923594Y",
        )
        self.assertEqual(
            result["unidad_tramitacion_codigo"],
            "EA0040331",
        )
        self.assertIn(
            "SOLICITUD AMPLIACION_PLAZO.pdf",
            result["documentos_adjuntos"],
        )
        self.assertTrue(
            result[
                "solicitud_ampliacion_confirmada"
            ]
        )


if __name__ == "__main__":
    unittest.main()

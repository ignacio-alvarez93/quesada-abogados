import unittest

from backend.services import (
    justificante_aportacion_documentacion_extraction_service
    as extractor,
)


SAMPLE = """
Código seguro de Verificación :
GEISER-f041-eded-94da-4714-bab5-6c70-ee76-ec78

Fecha y hora de registro en 27/01/2026 19:42:08
Fecha presentación: 27/01/2026 19:42:07
Número de registro: REGAGE26e00008209793

Interesado
Z3933660K Nombre: HOANG QUOC CUONG

Resumen/Asunto:
Se adjunta documentación por Internet al expte. num.:
330020250012022 de tipo: RESIDENCIA TEMPORAL

Delegación del Gobierno en Asturias - EA0040281 /
Ministerio de Política Territorial

Nº. Expediente: 330020250012022

Adjuntos
Nombre: PRUEBAS_2025.pdf
Tamaño (Bytes):
Validez: Original
Tipo: Documento Adjunto
Hash: 0FBE543B8B48373645F77B37E50E7325
Observaciones: PRUEBAS ESTANCIA 2025

Nombre: VIDA_LABORAL_EMPRESA.pdf
Tamaño (Bytes):
Validez: Original
Tipo: Documento Adjunto
Hash: EE7BC417FF9B47FBC954C3F413EE6600
Observaciones: VIDA LABORAL EMPRESA

Formulario Presentación
"""


class DocumentSubmissionExtractionTest(
    unittest.TestCase
):
    def test_geiser_document_submission(self):
        result = (
            extractor
            .extract_document_submission_text(
                SAMPLE
            )
        )

        self.assertEqual(
            result["fecha_registro"],
            "2026-01-27 19:42:08",
        )
        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00008209793",
        )
        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "330020250012022",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z3933660K",
        )
        self.assertEqual(
            result["numero_documentos_aportados"],
            2,
        )
        self.assertEqual(
            result["documentos_aportados"][0][
                "nombre"
            ],
            "PRUEBAS_2025.pdf",
        )
        self.assertIn(
            "VIDA_LABORAL_EMPRESA.pdf",
            result["documentos_aportados_texto"],
        )

    def test_interested_name_is_not_an_attachment(self):
        result = (
            extractor
            .extract_document_submission_text(
                """
                Código seguro de Verificación:
                GEISER-f041-eded-94da-4714-bab5-6c70-ee76-ec78

                Fecha y hora de registro en
                27/01/2026 19:42:08

                Número de registro:
                REGAGE26e00008209793

                Interesado
                Z3933660K Nombre: HOANG QUOC CUONG

                Nº. Expediente: 330020250012022

                Adjuntos
                Nombre: PRUEBAS_2025.pdf
                Tamaño (Bytes):
                Validez: Original
                Tipo: Documento Adjunto
                Hash: 0FBE543B8B48373645F77B37E50E7325
                Observaciones: PRUEBAS ESTANCIA 2025

                Formulario Presentación
                """
            )
        )

        self.assertEqual(
            result["numero_documentos_aportados"],
            1,
        )
        self.assertEqual(
            result["documentos_aportados"][0][
                "nombre"
            ],
            "PRUEBAS_2025.pdf",
        )
        self.assertNotIn(
            "HOANG QUOC CUONG",
            result["documentos_aportados_texto"],
        )


if __name__ == "__main__":
    unittest.main()

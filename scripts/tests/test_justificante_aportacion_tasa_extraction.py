import unittest

from backend.services import (
    justificante_aportacion_tasa_extraction_service
    as extractor,
)


SAMPLE = """
Código seguro de Verificación :
GEISER-e5b0-9d6a-b692-43a2-8ed3-0dbc-4e4c-28fe

RECIBO DE PRESENTACIÓN EN OFICINA DE REGISTRO

Fecha y hora de registro en 30/04/2026 09:11:04
Fecha presentación: 30/04/2026 09:11:02
Número de registro: REGAGE26e00041927758

Interesado
Z4462674N Nombre: URREGO GOMEZ KAREN LISETH

Resumen/Asunto:
Se adjunta documentación por Internet al expte. num.:
330020260003689 de tipo: RESIDENCIA TEMPORAL

Unidad de tramitación destino/Centro directivo:
Delegación del Gobierno en Asturias - EA0040281 /
Ministerio de Política Territorial

Nº. Expediente: 330020260003689

Adjuntos
Nombre: JUST ABONO TASA.pdf
Observaciones: JUST ABONO TASA
"""


class TaxSubmissionExtractionTest(unittest.TestCase):
    def test_geiser_tax_submission(self):
        result = extractor.extract_tax_submission_text(
            SAMPLE
        )

        self.assertEqual(
            result["fecha_registro"],
            "2026-04-30 09:11:04",
        )
        self.assertEqual(
            result["fecha_presentacion"],
            "2026-04-30 09:11:02",
        )
        self.assertEqual(
            result["csv_geiser"],
            "GEISER-e5b0-9d6a-b692-43a2-8ed3-0dbc-4e4c-28fe",
        )
        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00041927758",
        )
        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "330020260003689",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z4462674N",
        )
        self.assertEqual(
            result["unidad_tramitacion_codigo"],
            "EA0040281",
        )
        self.assertEqual(
            result["documento_aportado"],
            "JUST ABONO TASA.pdf",
        )
        self.assertTrue(
            result["aportacion_tasa_confirmada"]
        )
        self.assertEqual(
            result["estado_tasa"],
            "APORTADA",
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.services import (
    admision_tramite_extraction_service as extractor,
)


SAMPLE_TEXT = """
CSV : CNO-03d8-d5df-5f45-a0be-da39-555e-ffca-a344
FIRMANTE(1): SELLO DE ENTIDAD | FECHA : 17/07/2026 15:43
OFICINA DE EXTRANJERÍA
DIR3: EA0040281
EXPEDIENTE: 330020260007750
Solicitante: ALDO ANDRES CACERES FRANCO
NIE: Z5137803E
En fecha ha tenido entrada en esta Oficina la solicitud
de 17/07/2026 RESIDENCIA TEMPORAL.
En su caso: EXPE 330020260007750
"""


class AdmissionExtractionTest(unittest.TestCase):
    def test_standard_document(self):
        result = extractor.extract_admission_text(
            SAMPLE_TEXT
        )

        self.assertEqual(
            result["fecha_admision_tramite"],
            "2026-07-17",
        )
        self.assertEqual(
            result["csv_admision_tramite"],
            "CNO-03d8-d5df-5f45-a0be-da39-555e-ffca-a344",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z5137803E",
        )
        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "330020260007750",
        )
        self.assertEqual(
            result["unidad_tramitacion_codigo"],
            "EA0040281",
        )
        self.assertEqual(
            result["confidence"],
            1.0,
        )
        self.assertEqual(
            result["warnings"],
            [],
        )

    def test_sms_expediente_fallback(self):
        result = extractor.extract_admission_text(
            """
            CSV: ABC-1234-5678-9012-3456-7890
            FECHA: 02/08/2026
            NIE: Y1234567Z
            Para consultar: EXPE 330020260009999
            """
        )

        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "330020260009999",
        )

    def test_missing_nie_is_warning(self):
        result = extractor.extract_admission_text(
            """
            CSV: ABC-1234-5678-9012-3456-7890
            FECHA: 02/08/2026
            EXPEDIENTE: 330020260009999
            """
        )

        self.assertEqual(
            result["nie_detectado"],
            "",
        )
        self.assertIn(
            "No se detectó un NIE en el documento",
            result["warnings"],
        )


if __name__ == "__main__":
    unittest.main()


class AdmissionHistoricalFormatsTest(unittest.TestCase):
    def test_expte_numero_format_may(self):
        result = extractor.extract_admission_text(
            """
            CSV : CNO-0245-e1e1-6ff4-0975-2d0e-f931-e855-e5ae
            FIRMANTE(1): BEATRIZ | FECHA : 22/05/2026 16:10
            REGISTRO GENERAL DE SALIDA
            21/05/26 12:13:33

            Expte Nº 330020260004822
            N.I.E.: Z4583060Q
            Solicitante: D./Dña. ALTAGRACIA LUCAS MARTE

            Fecha 21/05/2026

            COMUNICACIÓN INICIO DE PROCEDIMIENTO
            Fecha de entrada del documento: 20/05/2026
            """
        )

        self.assertEqual(
            result["numero_expediente_extranjeria"],
            "330020260004822",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z4583060Q",
        )
        self.assertEqual(
            result["fecha_admision_tramite"],
            "2026-05-21",
        )

    def test_expte_numero_format_february(self):
        result = extractor.extract_admission_text(
            """
            CSV : CNO-b576-0ac7-8f2b-c87b-51de-0fb0-3a56-4362
            FIRMANTE(1): BEATRIZ | FECHA : 25/02/2026 10:47

            Expte Nº 330020260001789
            N.I.E.: Y8016696Z
            Solicitante: D./Dña. LEIDY JOHANNA ALZATE HINCAPIE

            Fecha 24/02/2026

            COMUNICACIÓN INICIO DE PROCEDIMIENTO
            Fecha de entrada del documento: 23/02/2026
            """
        )

        self.assertEqual(
            result["numero_expediente_extranjeria"],
            "330020260001789",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Y8016696Z",
        )
        self.assertEqual(
            result["fecha_admision_tramite"],
            "2026-02-24",
        )


class AdmissionWithTaxExtractionTest(unittest.TestCase):
    def test_admission_with_attached_tax_forms(self):
        result = extractor.extract_admission_text(
            """
            CSV : EXT-e232-4fa6-0638-d0ff-f027-bac9-a6a0-b0be
            DIR3: EA0040281
            EXPEDIENTE: 330020260004082
            Solicitante: CHOUROUK LAKRIMI
            NIE: Z0637520B
            En fecha 01/05/2026 ha tenido entrada la solicitud.

            Examinada la documentación presentada,
            no consta que se hayan pagado las tasas.

            Se le REQUIERE para que, en el período de
            10 días hábiles, proceda al pago:

            Tasa 790-código 052-CHOUROUK LAKRIMI-38,28 €

            El justificante deberá remitirse en el plazo
            de 15 días desde la fecha del pago.
            """
        )

        self.assertTrue(result["tasa_requerida"])
        self.assertEqual(result["tasa_modelo"], "790")
        self.assertEqual(result["tasa_codigo"], "052")
        self.assertEqual(
            result["tasa_importe_centimos"],
            3828,
        )
        self.assertEqual(
            result["plazo_pago_dias_habiles"],
            10,
        )
        self.assertEqual(
            result["plazo_aportacion_dias"],
            15,
        )
        self.assertEqual(
            result["estado_tasa"],
            "PENDIENTE",
        )

    def test_separate_tax_requirement_same_flow(self):
        result = extractor.extract_admission_text(
            """
            CSV : CNO-4f75-a737-9821-384d-7d0c-aa87-2923-860a
            DIR3 EA0053027
            Asunto: LDE/336020250000347 Y8207757Z
            NIE Y8207757Z
            Expediente Nº 336020250000347
            Fecha Requerimiento 11/12/2025
            REQUERIMIENTO DE TASA

            Se le REQUIERE para que, en el período de
            10 días hábiles, proceda al pago de la tasa:

            Tasa 790-código 052-apartado 2.6
            Autorización de residencia de larga duración-UE
            y autorización de residencia de larga duración nacional
            """
        )

        self.assertTrue(result["tasa_requerida"])
        self.assertEqual(result["tasa_modelo"], "790")
        self.assertEqual(result["tasa_codigo"], "052")
        self.assertEqual(result["tasa_apartado"], "2.6")
        self.assertEqual(
            result["numero_expediente_extranjeria"],
            "336020250000347",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Y8207757Z",
        )

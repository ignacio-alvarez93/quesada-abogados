import unittest

from backend.services import (
    requerimiento_extraction_service as extractor,
)


class RequirementExtractionTest(unittest.TestCase):
    def test_asturias_numbered_requirement(self):
        result = extractor.extract_requirement_text(
            """
            CSV : CNO-710e-c29e-cd4c-7d82-19a0-6f32-b858-3f0d
            Expte Nº 330020250012022
            N.I.E.: Z3933660K
            Solicitante: QUOC CUONG HOANG
            Fecha 14/01/2026

            Se le REQUIERE, para que en un plazo de DIEZ DIAS,
            aporte la documentación que se señala.

            DOCUMENTACIÓN REQUERIDA (ORIGINAL Y COPIA):
            1. Certificado de antecedentes penales de Malta.
            2. Certificado de empadronamiento histórico.
            3. Documentación de permanencia continuada en España.

            EL FUNCIONARIO DE LA OFICINA DE EXTRANJERÍA
            """
        )

        self.assertEqual(
            result["fecha_requerimiento"],
            "2026-01-14",
        )
        self.assertEqual(
            result["numero_expediente_extranjeria"],
            "330020250012022",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z3933660K",
        )
        self.assertEqual(
            result["plazo_dias"],
            10,
        )
        self.assertIn(
            "antecedentes penales",
            result[
                "documentacion_requerida_original"
            ].lower(),
        )

    def test_cantabria_requirement(self):
        result = extractor.extract_requirement_text(
            """
            CSV : CNO-637d-dfac-9d86-f241-ffcc-ea2b-2bec-87cd
            DIR3: EA0040331

            se le requiere para que, en el plazo de diez días,
            subsane la falta o acompañe los documentos.

            DOCUMENTACIÓN REQUERIDA:
            1. Certificado de pareja inscrita.
            2. Certificado de soltería del solicitante.

            @@@390020250007748@@@
            FECHA: 17 de febrero de 2026
            TITULAR: HERNANDEZ CRUZ, ASHLY DAYANNA
            Nº EXPEDIENTE: 390020250007748
            NIE: Z3923594Y
            """
        )

        self.assertEqual(
            result["fecha_requerimiento"],
            "2026-02-17",
        )
        self.assertEqual(
            result["numero_expediente_extranjeria"],
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


if __name__ == "__main__":
    unittest.main()

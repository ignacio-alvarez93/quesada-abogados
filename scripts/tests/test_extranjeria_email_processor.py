import unittest

from backend.services.email_platform.processors import (
    extranjeria_expedient_number_processor
    as processor,
)


SAMPLE_BODY = """
Estimado/a usuario/a,

Le informamos que su solicitud realizada a traves de Mercurio
con ID I33202604680666 para el/la interesado/a con nombre
VICTOR ALFONSO GONZALEZ FERREIRA, ha sido grabada por la
Oficina de Extranjería responsable de su tramitación,
asignándole el número de Expediente 330020260007765.

Reciba un cordial saludo.
"""


class ExtranjeriaEmailProcessorTest(
    unittest.TestCase
):
    def test_extracts_real_email_fields(self):
        result = processor.extract(
            {
                "sender_email":
                    "notificaciones.extranjeria@correo.gob.es",
                "body_text": SAMPLE_BODY,
            }
        )

        self.assertEqual(
            result["status"],
            "EXTRACTED",
        )

        data = result["extracted_data"]

        self.assertEqual(
            data[
                "numero_presentacion_registro"
            ],
            "I33202604680666",
        )

        self.assertEqual(
            data[
                "numero_expediente_extranjeria"
            ],
            "330020260007765",
        )

        self.assertEqual(
            data["nombre_interesado"],
            (
                "VICTOR ALFONSO "
                "GONZALEZ FERREIRA"
            ),
        )

    def test_rejects_unauthorized_sender(self):
        result = processor.extract(
            {
                "sender_email":
                    "persona@example.com",
                "body_text": SAMPLE_BODY,
            }
        )

        self.assertEqual(
            result["status"],
            "NOT_MATCHED",
        )

        self.assertIn(
            "REMITENTE_NO_AUTORIZADO",
            result["missing"],
        )

    def test_requires_mercurio_identifier(self):
        body = SAMPLE_BODY.replace(
            "ID I33202604680666",
            "la solicitud presentada",
        )

        result = processor.extract(
            {
                "sender_email":
                    "notificaciones.extranjeria@correo.gob.es",
                "body_text": body,
            }
        )

        self.assertIn(
            "ID_MERCURIO_NO_DETECTADO",
            result["missing"],
        )

    def test_requires_official_number(self):
        body = SAMPLE_BODY.replace(
            "330020260007765",
            "",
        )

        result = processor.extract(
            {
                "sender_email":
                    "notificaciones.extranjeria@correo.gob.es",
                "body_text": body,
            }
        )

        self.assertIn(
            "NUMERO_OFICIAL_NO_DETECTADO",
            result["missing"],
        )


if __name__ == "__main__":
    unittest.main()

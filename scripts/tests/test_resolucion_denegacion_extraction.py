import unittest

from backend.services import (
    resolucion_denegacion_extraction_service
    as extractor,
)


SAMPLE = """
CSV : CNO-92a0-44b5-bf7d-3b02-59a0-b7fd-6f6d-a22f

DELEGACIÓN DEL GOBIERNO EN ASTURIAS
REGISTRO GENERAL DE SALIDA
25/02/26 08:28:11

Expediente nº: 330020250012022
N.I.E.: Z3933660K

En este caso, no procede la concesión de la autorización
de residencia por circunstancias excepcionales valorando
el número de solicitudes tramitadas por la empresa y el
examen de su vida laboral que pone de manifiesto que la
empresa no mantiene a los trabajadores contratados en su
puesto de trabajo.

No procede la concesión de la autorización de residencia
por cuanto la exigencia del contrato se refiere a la
relación laboral real que subyace tras el mismo.

Vistos los artículos 31 y 38 de la Ley Orgánica 4/2000.

ACUERDA

Primero: DENEGAR LA AUTORIZACIÓN DE RESIDENCIA
TEMPORAL Y TRABAJO POR CIRCUNSTANCIAS EXCEPCIONALES.

Segundo: deberá abandonar el país en el plazo de quince días.

RECURSOS

La presente resolución pone fin a la vía administrativa.
Cabe recurso de reposición en el plazo de un mes o recurso
contencioso-administrativo en el plazo de dos meses.
"""


class DenialResolutionExtractionTest(
    unittest.TestCase
):
    def test_denial_resolution(self):
        result = (
            extractor
            .extract_denial_resolution_text(
                SAMPLE
            )
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
            result["fecha_resolucion"],
            "2026-02-25",
        )
        self.assertTrue(
            result[
                "resolucion_denegatoria_confirmada"
            ]
        )
        self.assertIn(
            "empresa no mantiene",
            result[
                "motivo_denegacion_detectado"
            ],
        )
        self.assertEqual(
            result["plazo_salida_dias"],
            15,
        )
        self.assertEqual(
            result["recurso_reposicion_meses"],
            1,
        )
        self.assertEqual(
            result[
                "recurso_contencioso_meses"
            ],
            2,
        )
        self.assertTrue(
            result["fin_via_administrativa"]
        )


if __name__ == "__main__":
    unittest.main()

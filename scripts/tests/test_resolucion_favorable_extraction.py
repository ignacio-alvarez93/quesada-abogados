import unittest

from backend.services import (
    resolucion_favorable_extraction_service
    as extractor,
)


class FavorableResolutionExtractionTest(
    unittest.TestCase
):
    def test_asturias_familiar(self):
        result = (
            extractor
            .extract_favorable_resolution_text(
                """
                CSV : CNO-2dd8-84d6-d732-53a7-6df3-57dd-2bd1-7d48

                N/REF 330020260004610
                FECHA Oviedo, a 22/06/2026

                RESUELVE

                CONCEDER la RESIDENCIA TEMPORAL DE
                FAMILIAR DE CIUDADANO ESPAÑOL - INICIAL
                solicitada por D. AICARDO DE JESUS
                PRESIGA HERRERA (N.I.E: Z2563487G),
                de nacionalidad COLOMBIANA,
                con validez desde el 15/05/2026
                hasta el 14/05/2031.

                Dicha autorización habilitará para
                trabajar por cuenta ajena o por cuenta
                propia.

                Deberá solicitar personalmente la
                expedición de la Tarjeta de Identidad
                de Extranjero (TIE) en el plazo de un mes.
                """
            )
        )

        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "330020260004610",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z2563487G",
        )
        self.assertEqual(
            result["fecha_resolucion"],
            "2026-06-22",
        )
        self.assertEqual(
            result["fecha_efectos"],
            "2026-05-15",
        )
        self.assertEqual(
            result["fecha_caducidad"],
            "2031-05-14",
        )
        self.assertTrue(
            result["trabajo_cuenta_ajena"]
        )
        self.assertTrue(
            result["trabajo_cuenta_propia"]
        )
        self.assertTrue(
            result["requiere_tie"]
        )

    def test_utex_structured_resolution(self):
        result = (
            extractor
            .extract_favorable_resolution_text(
                """
                CSV : CNO-63c7-5847-55a7-133f-6e43-a136-cd1a-dd24
                DIR3 EA0053027

                NIE Z2589237V
                Expediente Nº 337020260001408
                Apellidos YACOUB Fecha Solicitud 24/04/2026
                Nombre AMIR WELSON SHEHATA
                Fecha Resolución 12/06/2026
                Pasaporte A38284588
                Fecha Efectos 24/04/2026
                Nacionalidad EGIPCIA
                Fecha Caducidad 23/04/2027
                Tipo de Autorización RESIDENCIA TEMPORAL
                POR CIRCUNSTANCIAS EXCEPCIONALES DE LA DA20ª

                RESOLUCIÓN DE CONCESIÓN
                RESUELVO
                CONCEDER a AMIR WELSON SHEHATA YACOUB
                con NIE Z2589237V la autorización.

                Esta autorización habilita a su titular
                a residir y trabajar por cuenta ajena
                y por cuenta propia.
                """
            )
        )

        self.assertEqual(
            result[
                "numero_expediente_extranjeria"
            ],
            "337020260001408",
        )
        self.assertEqual(
            result["nie_detectado"],
            "Z2589237V",
        )
        self.assertEqual(
            result["fecha_resolucion"],
            "2026-06-12",
        )
        self.assertEqual(
            result["fecha_caducidad"],
            "2027-04-23",
        )
        self.assertEqual(
            result[
                "unidad_tramitacion_codigo"
            ],
            "EA0053027",
        )

    def test_conditioned_social_security(self):
        result = (
            extractor
            .extract_favorable_resolution_text(
                """
                CSV : CNO-0f82-76c7-ca50-72bf-7365-75b8-293a-9095
                Nº EXPEDIENTE 240020260000181
                NIE Z4137304T
                FECHA: 18/03/2026

                ACUERDO
                CONCEDER la autorización de RESIDENCIA
                TEMPORAL POR RAZONES DE ARRAIGO
                y una autorización para TRABAJAR.

                La eficacia de esta autorización estará
                condicionada a la posterior afiliación
                y/o alta como trabajador en el Sistema
                de la Seguridad Social en el plazo de
                un mes.
                """
            )
        )

        self.assertTrue(
            result[
                "eficacia_condicionada_alta_ss"
            ]
        )
        self.assertEqual(
            result["plazo_alta_ss_meses"],
            1,
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.services import (
    family_reunification_economic_diagnosis_service
    as diagnosis,
)


class FamilyReunificationEconomicDiagnosisTest(
    unittest.TestCase
):
    def test_one_person_requires_150_percent_iprem(self):
        self.assertEqual(
            diagnosis.calculate_required_iprem_percentage(
                1
            ),
            150,
        )

    def test_each_additional_person_adds_50_percent(self):
        self.assertEqual(
            diagnosis.calculate_required_iprem_percentage(
                2
            ),
            200,
        )
        self.assertEqual(
            diagnosis.calculate_required_iprem_percentage(
                3
            ),
            250,
        )
        self.assertEqual(
            diagnosis.calculate_required_iprem_percentage(
                4
            ),
            300,
        )

    def test_reference_amount_uses_integer_centimos(self):
        result = (
            diagnosis
            .calculate_reference_amount_centimos(
                60000,
                2,
            )
        )

        self.assertEqual(result, 120000)
        self.assertIsInstance(result, int)

    def test_missing_income_returns_no_data(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=1,
            )
        )

        self.assertEqual(
            result["estado"],
            diagnosis.STATUS_NO_DATA,
        )
        self.assertIsNone(
            result["porcentaje_cobertura"]
        )
        self.assertIsNone(
            result["diferencia_centimos"]
        )
        self.assertFalse(
            result["bloquea_presentacion"]
        )

    def test_income_equal_to_reference_is_sufficient(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=1,
                ingresos_mensuales_computables_centimos=90000,
            )
        )

        self.assertEqual(
            result["estado"],
            diagnosis.STATUS_SUFFICIENT,
        )
        self.assertEqual(
            result["porcentaje_cobertura"],
            100.0,
        )
        self.assertEqual(
            result["diferencia_centimos"],
            0,
        )
        self.assertFalse(
            result["requiere_revision_profesional"]
        )

    def test_near_threshold_is_non_blocking(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=2,
                ingresos_mensuales_computables_centimos=115000,
            )
        )

        self.assertEqual(
            result["importe_referencia_centimos"],
            120000,
        )
        self.assertEqual(
            result["estado"],
            diagnosis.STATUS_NEAR_THRESHOLD,
        )
        self.assertEqual(
            result["porcentaje_cobertura"],
            95.83,
        )
        self.assertFalse(
            result["bloquea_presentacion"]
        )
        self.assertTrue(
            result["requiere_revision_profesional"]
        )

    def test_below_threshold_requires_assessment(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=2,
                ingresos_mensuales_computables_centimos=96000,
            )
        )

        self.assertEqual(
            result["estado"],
            (
                diagnosis
                .STATUS_BELOW_WITH_ASSESSMENT
            ),
        )
        self.assertEqual(
            result["porcentaje_cobertura"],
            80.0,
        )
        self.assertTrue(
            result[
                "valoracion_profesional_requerida"
            ]
        )
        self.assertFalse(
            result["bloquea_presentacion"]
        )

    def test_very_low_income_generates_high_warning(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=2,
                ingresos_mensuales_computables_centimos=60000,
            )
        )

        self.assertEqual(
            result["estado"],
            diagnosis.STATUS_VERY_LOW,
        )
        self.assertEqual(
            result["nivel_advertencia"],
            "HIGH",
        )
        self.assertFalse(
            result["bloquea_presentacion"]
        )

    def test_minors_are_reported_but_do_not_change_general_rule(self):
        result = (
            diagnosis
            .evaluate_family_reunification_economic_diagnosis(
                iprem_mensual_centimos=60000,
                numero_personas_reagrupadas=3,
                numero_reagrupados_menores=2,
                ingresos_mensuales_computables_centimos=150000,
            )
        )

        self.assertEqual(
            result["numero_reagrupados_menores"],
            2,
        )
        self.assertEqual(
            result["numero_reagrupados_adultos"],
            1,
        )
        self.assertEqual(
            result["porcentaje_iprem_requerido"],
            250,
        )

    def test_minors_cannot_exceed_total_people(self):
        with self.assertRaises(ValueError):
            (
                diagnosis
                .evaluate_family_reunification_economic_diagnosis(
                    iprem_mensual_centimos=60000,
                    numero_personas_reagrupadas=1,
                    numero_reagrupados_menores=2,
                )
            )

    def test_people_must_be_positive(self):
        with self.assertRaises(ValueError):
            (
                diagnosis
                .calculate_required_iprem_percentage(
                    0
                )
            )

    def test_unsupported_criterion_is_rejected(self):
        with self.assertRaises(ValueError):
            (
                diagnosis
                .evaluate_family_reunification_economic_diagnosis(
                    iprem_mensual_centimos=60000,
                    numero_personas_reagrupadas=1,
                    criterio="DESCONOCIDO",
                )
            )


if __name__ == "__main__":
    unittest.main()

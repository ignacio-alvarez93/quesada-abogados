import unittest

from backend.services import (
    document_state_engine_policy_service
    as engine_policy,
)


def readiness_complete():
    return {
        "disponible": True,
        "completo": True,
        "grupos_bloqueantes": 0,
        "grupos": [
            {
                "codigo": "IDENTIDAD",
                "activo": True,
                "regla_cumplimiento": "ALL",
                "cumplido": True,
                "bloquea_completitud": False,
            }
        ],
    }


def semantic_complete():
    return {
        "aplicable": True,
        "aplicable_documental": True,
        "estado_sugerido": (
            "COMPLETO_SIN_PRESENTAR"
        ),
        "estado_documental": (
            "COMPLETO_SIN_PRESENTAR"
        ),
    }


class DocumentStateEnginePolicyTest(
    unittest.TestCase
):
    def test_configured_mode_defaults_to_legacy(self):
        result = engine_policy.get_configured_mode(
            {}
        )

        self.assertEqual(result, "LEGACY")

    def test_configured_mode_accepts_semantic_eligible(self):
        result = engine_policy.get_configured_mode(
            {
                "DOCUMENT_STATE_ENGINE_MODE": (
                    "semantic_eligible"
                )
            }
        )

        self.assertEqual(
            result,
            "SEMANTIC_ELIGIBLE",
        )

    def test_invalid_configured_mode_is_legacy(self):
        result = engine_policy.get_configured_mode(
            {
                "DOCUMENT_STATE_ENGINE_MODE": (
                    "MODO_INEXISTENTE"
                )
            }
        )

        self.assertEqual(result, "LEGACY")

    def test_default_mode_is_legacy(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode=None,
                legacy_state=(
                    "PENDIENTE_DOCUMENTACION"
                ),
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness=(
                    readiness_complete()
                ),
                semantic_decision=(
                    semantic_complete()
                ),
            )
        )

        self.assertEqual(
            result["modo_configurado"],
            "LEGACY",
        )
        self.assertEqual(
            result["motor_activo"],
            "LEGACY",
        )
        self.assertEqual(
            result["estado_seleccionado"],
            "PENDIENTE_DOCUMENTACION",
        )

    def test_unknown_mode_falls_back_to_legacy(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode="DESCONOCIDO",
                legacy_state="REQUERIDO",
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness=(
                    readiness_complete()
                ),
                semantic_decision=(
                    semantic_complete()
                ),
            )
        )

        self.assertEqual(
            result["modo_configurado"],
            "LEGACY",
        )
        self.assertEqual(
            result["estado_seleccionado"],
            "REQUERIDO",
        )

    def test_eligible_scope_can_use_semantic_engine(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode="SEMANTIC_ELIGIBLE",
                legacy_state=(
                    "PENDIENTE_DOCUMENTACION"
                ),
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness=(
                    readiness_complete()
                ),
                semantic_decision=(
                    semantic_complete()
                ),
            )
        )

        self.assertEqual(
            result["motor_activo"],
            "SEMANTIC",
        )
        self.assertEqual(
            result["estado_seleccionado"],
            "COMPLETO_SIN_PRESENTAR",
        )
        self.assertFalse(
            result[
                "fallback_legacy_aplicado"
            ]
        )

    def test_non_authorized_scope_uses_fallback(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode="SEMANTIC_ELIGIBLE",
                legacy_state="CONCEDIDO",
                tipo_codigo=(
                    "RESIDENCIA_TEMPORAL_"
                    "NO_LUCRATIVA"
                ),
                subtipo_codigo=(
                    "RENOVACION_FAMILIAR"
                ),
                semantic_readiness=(
                    readiness_complete()
                ),
                semantic_decision=(
                    semantic_complete()
                ),
            )
        )

        self.assertEqual(
            result["motor_activo"],
            "LEGACY",
        )
        self.assertEqual(
            result["estado_seleccionado"],
            "CONCEDIDO",
        )
        self.assertTrue(
            result[
                "fallback_legacy_aplicado"
            ]
        )
        self.assertFalse(
            result[
                "elegibilidad_semantica"
            ]["scope_autorizado"]
        )

    def test_missing_groups_uses_fallback(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode="SEMANTIC_ELIGIBLE",
                legacy_state="CONCEDIDO",
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness={
                    "disponible": True,
                    "grupos": [],
                },
                semantic_decision={
                    "aplicable": True,
                    "aplicable_documental": False,
                    "estado_sugerido": "CONCEDIDO",
                },
            )
        )

        self.assertEqual(
            result["motor_activo"],
            "LEGACY",
        )
        self.assertTrue(
            result[
                "fallback_legacy_aplicado"
            ]
        )

    def test_readiness_error_uses_fallback(self):
        result = (
            engine_policy
            .select_document_state_engine(
                mode="SEMANTIC_ELIGIBLE",
                legacy_state="REQUERIDO",
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness={
                    "disponible": False,
                    "error": "Fallo de prueba",
                    "grupos": [],
                },
                semantic_decision={
                    "aplicable": False,
                    "aplicable_documental": False,
                    "estado_sugerido": (
                        "SIN_DIAGNOSTICO"
                    ),
                },
            )
        )

        self.assertEqual(
            result["motor_activo"],
            "LEGACY",
        )
        self.assertEqual(
            result["estado_seleccionado"],
            "REQUERIDO",
        )

    def test_only_optional_groups_are_not_enough(self):
        result = (
            engine_policy
            .evaluate_semantic_eligibility(
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness={
                    "disponible": True,
                    "grupos": [
                        {
                            "codigo": "OBSERVACIONES",
                            "activo": True,
                            "regla_cumplimiento": (
                                "OPTIONAL"
                            ),
                        }
                    ],
                },
                semantic_decision={
                    "aplicable": True,
                    "aplicable_documental": True,
                    "estado_sugerido": (
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                },
            )
        )

        self.assertFalse(result["elegible"])
        self.assertEqual(
            result[
                "grupos_bloqueantes_configurados"
            ],
            0,
        )

    def test_legacy_groups_do_not_grant_eligibility(self):
        result = (
            engine_policy
            .evaluate_semantic_eligibility(
                tipo_codigo="NACIONALIDAD",
                subtipo_codigo="CASO_GENERAL",
                semantic_readiness={
                    "disponible": True,
                    "grupos": [
                        {
                            "codigo": "LEGACY_REQ_1",
                            "activo": True,
                            "regla_cumplimiento": "ALL",
                        }
                    ],
                },
                semantic_decision={
                    "aplicable": True,
                    "aplicable_documental": True,
                    "estado_sugerido": (
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                },
            )
        )

        self.assertFalse(result["elegible"])
        self.assertEqual(
            result["grupos_semanticos"],
            0,
        )

    def test_scope_normalization_is_case_insensitive(self):
        result = (
            engine_policy
            .evaluate_semantic_eligibility(
                tipo_codigo="nacionalidad",
                subtipo_codigo="caso_general",
                semantic_readiness=(
                    readiness_complete()
                ),
                semantic_decision=(
                    semantic_complete()
                ),
            )
        )

        self.assertTrue(result["elegible"])


if __name__ == "__main__":
    unittest.main()

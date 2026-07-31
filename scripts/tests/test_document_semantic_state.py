import unittest

from backend.services import (
    document_semantic_state_service
    as semantic_state,
)


class DocumentSemanticStateTest(unittest.TestCase):
    def test_unavailable_readiness_is_not_applicable(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": False,
            }
        )

        self.assertFalse(result["aplicable"])
        self.assertEqual(
            result["estado_sugerido"],
            "SIN_DIAGNOSTICO",
        )

    def test_without_semantic_groups_is_not_applicable(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "grupos": [],
                "completo": True,
            }
        )

        self.assertFalse(result["aplicable"])

    def test_complete_readiness_suggests_complete(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "completo": True,
                "grupos_bloqueantes": 0,
                "grupos": [
                    {
                        "codigo": "IDENTIDAD",
                        "activo": True,
                        "bloquea_completitud": False,
                        "cumplido": True,
                    }
                ],
            }
        )

        self.assertTrue(result["aplicable"])
        self.assertEqual(
            result["estado_sugerido"],
            "COMPLETO_SIN_PRESENTAR",
        )

    def test_incomplete_readiness_suggests_pending(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "completo": False,
                "grupos_bloqueantes": 2,
                "grupos": [
                    {
                        "codigo": "IDENTIDAD",
                        "activo": True,
                        "bloquea_completitud": True,
                        "cumplido": False,
                    }
                ],
            }
        )

        self.assertEqual(
            result["estado_sugerido"],
            "PENDIENTE_DOCUMENTACION",
        )
        self.assertIn(
            "2 grupo",
            result["motivo"],
        )

    def test_blocking_count_uses_real_group_fields(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "completo": False,
                "grupos_bloqueantes": None,
                "grupos": [
                    {
                        "codigo": "IDENTIDAD",
                        "activo": True,
                        "cumplido": False,
                        "bloquea_completitud": True,
                    },
                    {
                        "codigo": "DOMICILIO",
                        "activo": True,
                        "cumplido": True,
                        "bloquea_completitud": False,
                    },
                    {
                        "codigo": "MEDIOS",
                        "activo": True,
                        "cumplido": False,
                        "bloquea_completitud": True,
                    },
                ],
            }
        )

        self.assertTrue(result["aplicable"])
        self.assertEqual(
            result["estado_sugerido"],
            "PENDIENTE_DOCUMENTACION",
        )
        self.assertIn(
            "2 grupo",
            result["motivo"],
        )

    def test_strong_process_signal_has_priority(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "completo": False,
                "grupos_bloqueantes": 2,
                "grupos": [
                    {
                        "codigo": "IDENTIDAD",
                        "activo": True,
                        "bloquea_completitud": True,
                        "cumplido": False,
                    }
                ],
            },
            has_concesion=True,
        )

        self.assertEqual(
            result["estado_sugerido"],
            "CONCEDIDO",
        )

    def test_legacy_groups_do_not_make_it_applicable(self):
        result = semantic_state.semantic_document_state(
            {
                "disponible": True,
                "completo": False,
                "grupos": [
                    {
                        "codigo": "LEGACY_REQ_1",
                        "activo": True,
                        "bloquea_completitud": True,
                        "cumplido": False,
                    }
                ],
            }
        )

        self.assertFalse(result["aplicable"])

    def test_comparison_detects_coincidence(self):
        semantic = {
            "aplicable": True,
            "estado_sugerido": (
                "COMPLETO_SIN_PRESENTAR"
            ),
            "motivo": "Completo",
        }

        result = (
            semantic_state
            .compare_document_states(
                "COMPLETO_SIN_PRESENTAR",
                semantic,
            )
        )

        self.assertTrue(result["coincide"])
        self.assertFalse(result["divergencia"])
        self.assertEqual(
            result["motor_activo"],
            "LEGACY",
        )

    def test_comparison_detects_divergence(self):
        semantic = {
            "aplicable": True,
            "estado_sugerido": (
                "PENDIENTE_DOCUMENTACION"
            ),
            "motivo": "Faltan grupos",
        }

        result = (
            semantic_state
            .compare_document_states(
                "COMPLETO_SIN_PRESENTAR",
                semantic,
            )
        )

        self.assertFalse(result["coincide"])
        self.assertTrue(result["divergencia"])


if __name__ == "__main__":
    unittest.main()

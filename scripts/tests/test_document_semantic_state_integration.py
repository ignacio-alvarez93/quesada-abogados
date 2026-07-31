import unittest
from unittest.mock import patch

from backend.services import (
    document_semantic_state_service
    as semantic_state,
)
from backend.services import (
    expedient_document_state_service
    as doc_state,
)


class DocumentSemanticStateIntegrationTest(
    unittest.TestCase
):
    def test_parallel_decision_detects_divergence(self):
        semantic_result = {
            "disponible": True,
            "completo": False,
            "grupos_bloqueantes": 2,
            "grupos": [
                {
                    "codigo": "IDENTIDAD",
                    "activo": True,
                    "cumplido": False,
                    "bloquea_completitud": True,
                }
            ],
        }

        decision = (
            semantic_state
            .semantic_document_state(
                semantic_result
            )
        )

        comparison = (
            semantic_state
            .compare_document_states(
                "COMPLETO_SIN_PRESENTAR",
                decision,
            )
        )

        self.assertTrue(
            decision["aplicable"]
        )
        self.assertEqual(
            decision["estado_sugerido"],
            "PENDIENTE_DOCUMENTACION",
        )
        self.assertTrue(
            comparison["divergencia"]
        )
        self.assertEqual(
            comparison["motor_activo"],
            "LEGACY",
        )

    def test_process_signal_aligns_both_engines(self):
        semantic_result = {
            "disponible": True,
            "completo": False,
            "grupos_bloqueantes": 3,
            "grupos": [
                {
                    "codigo": "IDENTIDAD",
                    "activo": True,
                    "cumplido": False,
                    "bloquea_completitud": True,
                }
            ],
        }

        decision = (
            semantic_state
            .semantic_document_state(
                semantic_result,
                has_concesion=True,
            )
        )

        comparison = (
            semantic_state
            .compare_document_states(
                "CONCEDIDO",
                decision,
            )
        )

        self.assertEqual(
            decision["estado_sugerido"],
            "CONCEDIDO",
        )
        self.assertTrue(
            comparison["coincide"]
        )

    def test_unavailable_semantic_engine_keeps_legacy(self):
        decision = (
            semantic_state
            .semantic_document_state(
                {
                    "disponible": False,
                }
            )
        )

        comparison = (
            semantic_state
            .compare_document_states(
                "PENDIENTE_DOCUMENTACION",
                decision,
            )
        )

        self.assertFalse(
            decision["aplicable"]
        )
        self.assertFalse(
            comparison["divergencia"]
        )
        self.assertEqual(
            comparison["motor_activo"],
            "LEGACY",
        )

    def test_semantic_failure_does_not_replace_legacy(self):
        with patch.object(
            semantic_state,
            "semantic_document_state",
            return_value={
                "aplicable": False,
                "estado_sugerido": (
                    "SIN_DIAGNOSTICO"
                ),
                "motivo": "Fallo controlado",
                "fuente": "SEMANTIC_READINESS",
            },
        ):
            decision = (
                semantic_state
                .semantic_document_state({})
            )

        comparison = (
            semantic_state
            .compare_document_states(
                "REQUERIDO",
                decision,
            )
        )

        self.assertEqual(
            comparison["legacy_estado"],
            "REQUERIDO",
        )
        self.assertFalse(
            comparison["semantic_aplicable"]
        )


if __name__ == "__main__":
    unittest.main()

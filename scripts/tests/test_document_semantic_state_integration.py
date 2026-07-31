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


    def test_process_and_document_states_are_independent(self):
        readiness = {
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

        documentary = (
            semantic_state
            .semantic_document_completeness(
                readiness
            )
        )
        process = (
            semantic_state
            .process_state_from_signals(
                has_concesion=True
            )
        )
        combined = (
            semantic_state
            .semantic_document_state(
                readiness,
                has_concesion=True,
            )
        )

        self.assertEqual(
            documentary["estado_documental"],
            "PENDIENTE_DOCUMENTACION",
        )
        self.assertEqual(
            process["estado_procesal"],
            "CONCEDIDO",
        )
        self.assertEqual(
            combined["estado_sugerido"],
            "CONCEDIDO",
        )

    def test_without_process_signal_combined_uses_document_state(self):
        readiness = {
            "disponible": True,
            "completo": True,
            "grupos_bloqueantes": 0,
            "grupos": [
                {
                    "codigo": "IDENTIDAD",
                    "activo": True,
                    "cumplido": True,
                    "bloquea_completitud": False,
                }
            ],
        }

        documentary = (
            semantic_state
            .semantic_document_completeness(
                readiness
            )
        )
        process = (
            semantic_state
            .process_state_from_signals()
        )
        combined = (
            semantic_state
            .semantic_document_state(
                readiness
            )
        )

        self.assertEqual(
            documentary["estado_documental"],
            "COMPLETO_SIN_PRESENTAR",
        )
        self.assertFalse(process["detectado"])
        self.assertEqual(
            combined["estado_sugerido"],
            "COMPLETO_SIN_PRESENTAR",
        )

    def test_combined_state_preserves_process_without_groups(self):
        readiness = {
            "disponible": True,
            "completo": False,
            "grupos_bloqueantes": 0,
            "grupos": [],
        }

        documentary = (
            semantic_state
            .semantic_document_completeness(
                readiness
            )
        )
        process = (
            semantic_state
            .process_state_from_signals(
                has_concesion=True
            )
        )
        combined = (
            semantic_state
            .semantic_document_state(
                readiness,
                has_concesion=True,
            )
        )

        self.assertFalse(
            documentary["aplicable"]
        )
        self.assertEqual(
            documentary["estado_documental"],
            "SIN_DIAGNOSTICO",
        )
        self.assertEqual(
            process["estado_procesal"],
            "CONCEDIDO",
        )
        self.assertTrue(
            combined["aplicable"]
        )
        self.assertFalse(
            combined["aplicable_documental"]
        )
        self.assertEqual(
            combined["estado_sugerido"],
            "CONCEDIDO",
        )

    def test_unavailable_documentary_state_is_explicit(self):
        documentary = (
            semantic_state
            .semantic_document_completeness(
                {
                    "disponible": False,
                }
            )
        )
        process = (
            semantic_state
            .process_state_from_signals()
        )

        self.assertFalse(
            documentary["aplicable"]
        )
        self.assertEqual(
            documentary["estado_documental"],
            "SIN_DIAGNOSTICO",
        )
        self.assertFalse(process["detectado"])


if __name__ == "__main__":
    unittest.main()

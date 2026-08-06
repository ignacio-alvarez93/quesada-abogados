import unittest
from unittest.mock import patch

from backend.services import (
    expedient_traceability_service
    as trace_service,
)


class TraceabilityDerivationIntegrationTest(
    unittest.TestCase
):
    def test_favorable_resolution_maps_to_granted(self):
        expected = {
            "rules_evaluated": 1,
            "proposals": [
                {
                    "proposal": {
                        "id": 100,
                    },
                    "created": True,
                }
            ],
            "skipped": [],
        }

        with patch(
            "backend.services."
            "expedient_evolution_service."
            "evaluate_derivation_rules_for_event",
            return_value=expected,
        ) as evaluator:
            result = (
                trace_service
                ._evaluate_derivations_after_admin_event(
                    expediente_id=25,
                    event_code="RESOLUCION_FAVORABLE",
                    usuario="NACHO",
                )
            )

        evaluator.assert_called_once_with(
            expediente_id=25,
            event_code="RESOLUCION_FAVORABLE",
            resultado="CONCEDIDO",
            usuario="NACHO",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["resultado"],
            "CONCEDIDO",
        )
        self.assertEqual(
            result["rules_evaluated"],
            1,
        )
        self.assertEqual(
            len(result["proposals"]),
            1,
        )

    def test_denial_resolution_maps_to_denied(self):
        with patch(
            "backend.services."
            "expedient_evolution_service."
            "evaluate_derivation_rules_for_event",
            return_value={
                "rules_evaluated": 0,
                "proposals": [],
                "skipped": [],
            },
        ) as evaluator:
            result = (
                trace_service
                ._evaluate_derivations_after_admin_event(
                    expediente_id=25,
                    event_code=(
                        "RESOLUCION_DENEGATORIA"
                    ),
                    usuario="ERP",
                )
            )

        evaluator.assert_called_once_with(
            expediente_id=25,
            event_code="RESOLUCION_DENEGATORIA",
            resultado="DENEGADO",
            usuario="ERP",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["resultado"],
            "DENEGADO",
        )

    def test_non_resolution_event_has_no_invented_result(self):
        with patch(
            "backend.services."
            "expedient_evolution_service."
            "evaluate_derivation_rules_for_event",
            return_value={
                "rules_evaluated": 0,
                "proposals": [],
                "skipped": [],
            },
        ) as evaluator:
            result = (
                trace_service
                ._evaluate_derivations_after_admin_event(
                    expediente_id=25,
                    event_code="ADMISION_TRAMITE",
                )
            )

        evaluator.assert_called_once_with(
            expediente_id=25,
            event_code="ADMISION_TRAMITE",
            resultado=None,
            usuario="ERP",
        )

        self.assertTrue(result["ok"])
        self.assertIsNone(result["resultado"])

    def test_derivation_failure_does_not_propagate(self):
        with patch(
            "backend.services."
            "expedient_evolution_service."
            "evaluate_derivation_rules_for_event",
            side_effect=RuntimeError(
                "fallo controlado"
            ),
        ):
            result = (
                trace_service
                ._evaluate_derivations_after_admin_event(
                    expediente_id=25,
                    event_code="RESOLUCION_FAVORABLE",
                )
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["rules_evaluated"],
            0,
        )
        self.assertEqual(result["proposals"], [])
        self.assertIn(
            "fallo controlado",
            result["error"],
        )


if __name__ == "__main__":
    unittest.main()

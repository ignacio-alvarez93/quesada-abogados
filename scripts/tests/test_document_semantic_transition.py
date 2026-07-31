import unittest

from backend.services import (
    document_semantic_transition_service
    as transition_service,
)


def diagnosis(
    *,
    documentary_state="PENDIENTE_DOCUMENTACION",
    documentary_applicable=True,
    process_state=None,
    blocking=1,
    ambiguities=0,
):
    return {
        "expediente_id": 100,
        "expediente": {
            "cliente_id": 200,
        },
        "estado_sugerido": (
            process_state
            or documentary_state
        ),
        "motor_estado_activo": "LEGACY",
        "estado_documental_semantico": {
            "estado_documental": (
                documentary_state
            ),
            "aplicable": (
                documentary_applicable
            ),
        },
        "estado_procesal_detectado": {
            "estado_procesal": (
                process_state
            ),
            "detectado": bool(
                process_state
            ),
        },
        "decision_semantica": {
            "estado_sugerido": (
                process_state
                or documentary_state
            ),
        },
        "semantic_readiness": {
            "disponible": True,
            "grupos_bloqueantes": blocking,
            "opciones_ambiguas_por_rol": [],
            "grupos": [
                {
                    "codigo": "IDENTIDAD",
                    "estado": (
                        "CUMPLIDO"
                        if blocking == 0
                        else "PENDIENTE"
                    ),
                    "cumplido": blocking == 0,
                    "bloquea_completitud": (
                        blocking > 0
                    ),
                    "documentos_detectados": (
                        1 if blocking == 0 else 0
                    ),
                    "documentos_requeridos": 1,
                    "opciones_ambiguas_por_rol": (
                        ambiguities
                    ),
                }
            ],
        },
        "resumen_inferencia_roles": {
            "ambiguos": ambiguities,
        },
    }


class DocumentSemanticTransitionTest(
    unittest.TestCase
):
    def test_same_diagnosis_has_same_fingerprint(self):
        first = (
            transition_service
            .build_semantic_snapshot(
                diagnosis()
            )
        )
        second = (
            transition_service
            .build_semantic_snapshot(
                diagnosis()
            )
        )

        self.assertEqual(
            first["fingerprint"],
            second["fingerprint"],
        )

    def test_generated_dates_do_not_affect_fingerprint(self):
        first_diagnosis = diagnosis()
        first_diagnosis["generated_at"] = (
            "2026-07-31T10:00:00"
        )

        second_diagnosis = diagnosis()
        second_diagnosis["generated_at"] = (
            "2026-07-31T11:00:00"
        )

        first = (
            transition_service
            .build_semantic_snapshot(
                first_diagnosis
            )
        )
        second = (
            transition_service
            .build_semantic_snapshot(
                second_diagnosis
            )
        )

        self.assertEqual(
            first["fingerprint"],
            second["fingerprint"],
        )

    def test_initial_snapshot_is_detected(self):
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis()
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                None,
                current,
            )
        )

        self.assertTrue(result["changed"])
        self.assertEqual(
            result["event"]["event_type"],
            "INITIAL_SNAPSHOT",
        )

    def test_identical_snapshot_creates_no_event(self):
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis()
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                current,
                current,
            )
        )

        self.assertFalse(result["changed"])
        self.assertIsNone(result["event"])

    def test_pending_to_complete_transition(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "PENDIENTE_DOCUMENTACION"
                    ),
                    blocking=1,
                )
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                    blocking=0,
                )
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            result["event"]["event_type"],
            "DOCUMENT_COMPLETE",
        )

    def test_complete_to_pending_transition(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                    blocking=0,
                )
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "PENDIENTE_DOCUMENTACION"
                    ),
                    blocking=2,
                )
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            result["event"]["event_type"],
            "DOCUMENT_INCOMPLETE",
        )

    def test_new_role_ambiguity_is_detected(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(ambiguities=0)
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(ambiguities=1)
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            result["event"]["event_type"],
            "ROLE_AMBIGUITY_CREATED",
        )

    def test_resolved_role_ambiguity_is_detected(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(ambiguities=2)
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(ambiguities=0)
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            result["event"]["event_type"],
            "ROLE_AMBIGUITY_RESOLVED",
        )

    def test_document_completion_has_priority_over_resolved_ambiguity(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "PENDIENTE_DOCUMENTACION"
                    ),
                    blocking=1,
                    ambiguities=1,
                )
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                    blocking=0,
                    ambiguities=0,
                )
            )
        )

        result = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            result["event"]["event_type"],
            "DOCUMENT_COMPLETE",
        )

    def test_idempotency_key_is_stable(self):
        previous = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(blocking=1)
            )
        )
        current = (
            transition_service
            .build_semantic_snapshot(
                diagnosis(
                    documentary_state=(
                        "COMPLETO_SIN_PRESENTAR"
                    ),
                    blocking=0,
                )
            )
        )

        first = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )
        second = (
            transition_service
            .compare_semantic_snapshots(
                previous,
                current,
            )
        )

        self.assertEqual(
            first["event"]["idempotency_key"],
            second["event"]["idempotency_key"],
        )


if __name__ == "__main__":
    unittest.main()

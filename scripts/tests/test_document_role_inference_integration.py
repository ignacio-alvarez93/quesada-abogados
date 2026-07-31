import unittest

from backend.services import (
    expedient_document_state_service as doc_state,
)


class DocumentRoleInferenceIntegrationTest(
    unittest.TestCase
):
    def test_role_is_inferred_from_filename(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "origen": "box_classifier",
                    }
                ]
            )
        )

        self.assertEqual(len(detections), 1)

        detection = detections[0]

        self.assertEqual(
            detection["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            detection[
                "estado_inferencia_rol"
            ],
            "INFERIDO",
        )
        self.assertEqual(
            detection["roles_candidatos"],
            ["REAGRUPANTE"],
        )

    def test_explicit_role_has_priority(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "rol_documental": (
                            "REAGRUPANTE"
                        ),
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPADO.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "REAGRUPADO/"
                            "PASAPORTE.pdf"
                        ),
                        "patron": (
                            "PASAPORTE_"
                            "REAGRUPANTE"
                        ),
                        "origen": (
                            "nomenclatura_canónica"
                        ),
                    }
                ]
            )
        )

        detection = detections[0]

        self.assertEqual(
            detection["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            detection[
                "estado_inferencia_rol"
            ],
            "EXPLICITO",
        )

    def test_conflicting_evidence_does_not_assign_role(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "REAGRUPADO/"
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "origen": "box_classifier",
                    }
                ]
            )
        )

        detection = detections[0]

        self.assertIsNone(
            detection["rol_documental"]
        )
        self.assertEqual(
            detection[
                "estado_inferencia_rol"
            ],
            "AMBIGUO",
        )
        self.assertEqual(
            set(
                detection[
                    "roles_candidatos"
                ]
            ),
            {
                "REAGRUPANTE",
                "REAGRUPADO",
            },
        )

    def test_generic_filename_remains_without_role(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "archivo": "PASAPORTE.pdf",
                        "ruta": (
                            "EXPEDIENTE/"
                            "IDENTIDAD/"
                            "PASAPORTE.pdf"
                        ),
                        "origen": "box_classifier",
                    }
                ]
            )
        )

        detection = detections[0]

        self.assertIsNone(
            detection["rol_documental"]
        )
        self.assertEqual(
            detection[
                "estado_inferencia_rol"
            ],
            "SIN_EVIDENCIA",
        )

    def test_children_role_uses_canonical_plural(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": (
                            "ACTA_NACIMIENTO"
                        ),
                        "archivo": (
                            "ACTA_NACIMIENTO_"
                            "HIJO_MENOR.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "HIJOS_MENORES/"
                            "ACTA.pdf"
                        ),
                        "origen": "box_classifier",
                    }
                ]
            )
        )

        detection = detections[0]

        self.assertEqual(
            detection["rol_documental"],
            "HIJOS_MENORES",
        )


    def test_role_summary_counts_inference_states(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "origen": "box_classifier",
                    },
                    {
                        "codigo": "NIE",
                        "rol_documental": (
                            "REAGRUPANTE"
                        ),
                        "archivo": "NIE.pdf",
                        "ruta": "EXPEDIENTE/NIE.pdf",
                        "origen": (
                            "nomenclatura_canónica"
                        ),
                    },
                    {
                        "codigo": "PASAPORTE",
                        "archivo": "PASAPORTE.pdf",
                        "ruta": (
                            "EXPEDIENTE/"
                            "IDENTIDAD/"
                            "PASAPORTE.pdf"
                        ),
                        "origen": "box_classifier",
                    },
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "REAGRUPADO/"
                            "PASAPORTE.pdf"
                        ),
                        "origen": "box_classifier",
                    },
                ]
            )
        )

        summary = (
            doc_state
            ._summarize_role_inferences(
                detections
            )
        )

        self.assertEqual(
            summary["total_detecciones"],
            4,
        )
        self.assertEqual(
            summary["roles_inferidos"],
            1,
        )
        self.assertEqual(
            summary["roles_explicitos"],
            1,
        )
        self.assertEqual(
            summary["sin_evidencia"],
            1,
        )
        self.assertEqual(
            summary["ambiguos"],
            1,
        )
        self.assertEqual(
            summary["con_rol"],
            2,
        )
        self.assertEqual(
            summary["sin_rol"],
            2,
        )
        self.assertEqual(
            summary["por_rol"],
            {
                "REAGRUPANTE": 2,
            },
        )
        self.assertEqual(
            len(
                summary[
                    "detecciones_ambiguas"
                ]
            ),
            1,
        )

    def test_duplicate_detection_is_not_counted_twice(self):
        detections = (
            doc_state
            ._build_semantic_detections(
                [
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "origen": "box_classifier",
                    },
                    {
                        "codigo": "PASAPORTE",
                        "archivo": (
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "ruta": (
                            "EXPEDIENTE/"
                            "PASAPORTE_"
                            "REAGRUPANTE.pdf"
                        ),
                        "origen": "box_classifier",
                    },
                ]
            )
        )

        self.assertEqual(len(detections), 1)

        summary = (
            doc_state
            ._summarize_role_inferences(
                detections
            )
        )

        self.assertEqual(
            summary["total_detecciones"],
            1,
        )
        self.assertEqual(
            summary["roles_inferidos"],
            1,
        )


if __name__ == "__main__":
    unittest.main()

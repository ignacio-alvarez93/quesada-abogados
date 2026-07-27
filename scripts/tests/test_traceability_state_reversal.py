import unittest

from backend.services import (
    expedient_traceability_service
    as trace_service,
)


class TraceabilityStateReversalTest(
    unittest.TestCase
):
    def derive(self, event_codes):
        documents = [
            {
                "id": index,
                "tipo_justificante": code,
            }
            for index, code in enumerate(
                event_codes,
                start=1,
            )
        ]

        return (
            trace_service
            ._derive_admin_state_from_documents(
                documents,
                "EXTRANJERIA",
            )
        )

    def test_resolution_removed_returns_to_submission(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "ADMISION_TRAMITE",
                "REQUERIMIENTO",
                "JUSTIFICANTE_APORTACION_DOCUMENTACION",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "REQUERIMIENTO APORTADO",
        )

    def test_submission_removed_returns_to_requirement(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "ADMISION_TRAMITE",
                "REQUERIMIENTO",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "REQUERIDO",
        )

    def test_requirement_removed_returns_to_admission(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "ADMISION_TRAMITE",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "ADMITIDO",
        )

    def test_admission_removed_returns_to_presented(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "PRESENTADO",
        )

    def test_no_state_documents_return_empty(self):
        result = self.derive(
            [
                "OTRO",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "",
        )

    def test_duplicate_resolution_keeps_resolved_state(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "RESOLUCION_DENEGATORIA",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "RESUELTO DENEGADO",
        )

    def test_extension_is_state_producing(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "REQUERIMIENTO",
                "JUSTIFICANTE_AMPLIACION_PLAZO",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "AMPLIACIÓN DE PLAZO SOLICITADA",
        )

    def test_later_active_document_wins(self):
        result = self.derive(
            [
                "JUSTIFICANTE_PRESENTACION",
                "ADMISION_TRAMITE",
                "REQUERIMIENTO",
                "JUSTIFICANTE_APORTACION_DOCUMENTACION",
                "RESOLUCION_FAVORABLE",
            ]
        )

        self.assertEqual(
            result["estado_nuevo"],
            "RESUELTO FAVORABLE",
        )


if __name__ == "__main__":
    unittest.main()

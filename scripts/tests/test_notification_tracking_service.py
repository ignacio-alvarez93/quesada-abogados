import unittest

from backend.services import (
    notification_tracking_service as service,
)


class NotificationTrackingStateTest(
    unittest.TestCase
):
    def base_snapshot(self):
        return {
            "notification_workflow_code":
                "EXTRANJERIA_STANDARD",
            "presentation_exists": True,
            "numero_expediente_extranjeria": "",
            "admission_exists": False,
            "resolution_event_code": "",
        }

    def test_non_applicable_workflow(self):
        snapshot = self.base_snapshot()
        snapshot[
            "notification_workflow_code"
        ] = "RESOLUCION_DIRECTA"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_NO_APLICABLE,
        )
        self.assertEqual(result["activo"], 0)

    def test_without_presentation_is_cancelled(self):
        snapshot = self.base_snapshot()
        snapshot["presentation_exists"] = False

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service
            .ESTADO_CANCELADO_SIN_PRESENTACION,
        )
        self.assertEqual(result["activo"], 0)

    def test_never_presented_derives_cancelled_state(self):
        snapshot = self.base_snapshot()
        snapshot["presentation_exists"] = False

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service
            .ESTADO_CANCELADO_SIN_PRESENTACION,
        )
        self.assertEqual(result["activo"], 0)

    def test_waits_for_official_number(self):
        result = service._derive_tracking_state(
            self.base_snapshot()
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_ESPERA_NUMERO,
        )
        self.assertEqual(result["activo"], 1)

    def test_waits_for_admission_after_number(self):
        snapshot = self.base_snapshot()
        snapshot[
            "numero_expediente_extranjeria"
        ] = "330020260001234"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_ESPERA_ADMISION,
        )

    def test_standard_admission_waits_resolution(self):
        snapshot = self.base_snapshot()
        snapshot["admission_exists"] = True
        snapshot[
            "admission_event_code"
        ] = "ADMISION_TRAMITE"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_ESPERA_RESOLUCION,
        )
        self.assertEqual(result["activo"], 1)

    def test_admission_with_tax_waits_resolution(self):
        snapshot = self.base_snapshot()
        snapshot["admission_exists"] = True
        snapshot[
            "admission_event_code"
        ] = "ADMISION_TRAMITE_TASA"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_ESPERA_RESOLUCION,
        )

    def test_favorable_resolution_closes(self):
        snapshot = self.base_snapshot()
        snapshot[
            "resolution_event_code"
        ] = "RESOLUCION_FAVORABLE"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_CERRADO_FAVORABLE,
        )
        self.assertEqual(result["activo"], 0)
        self.assertEqual(
            result["resultado_resolucion"],
            "FAVORABLE",
        )

    def test_denial_resolution_closes(self):
        snapshot = self.base_snapshot()
        snapshot[
            "resolution_event_code"
        ] = "RESOLUCION_DENEGATORIA"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_CERRADO_DENEGATORIO,
        )
        self.assertEqual(result["activo"], 0)
        self.assertEqual(
            result["resultado_resolucion"],
            "DENEGATORIA",
        )

    def test_resolution_has_priority_over_admission(self):
        snapshot = self.base_snapshot()
        snapshot["admission_exists"] = True
        snapshot[
            "resolution_event_code"
        ] = "RESOLUCION_FAVORABLE"

        result = service._derive_tracking_state(
            snapshot
        )

        self.assertEqual(
            result["estado"],
            service.ESTADO_CERRADO_FAVORABLE,
        )
        self.assertEqual(result["activo"], 0)


if __name__ == "__main__":
    unittest.main()

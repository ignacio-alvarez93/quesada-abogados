import unittest
from unittest.mock import patch

from backend.services import (
    expedient_traceability_service,
)


class TraceabilityAuthorizationIntegrationTest(
    unittest.TestCase
):
    def _base_data(self, event_code):
        return {
            "expediente_id": 100,
            "archivo_nombre":
                "resolucion.pdf",
            "archivo_ruta":
                "C:/TEST/resolucion.pdf",
            "event_code": event_code,
            "usuario": "TEST",
            "favorable_resolution_extraction": {
                "fecha_resolucion":
                    "2026-02-10",
                "fecha_caducidad":
                    "2027-03-01",
                "numero_expediente_extranjeria":
                    "EX-100",
                "unidad_tramitacion_nombre":
                    "OFICINA DE EXTRANJERÍA",
            },
        }

    def _common_patches(self):
        return (
            patch.object(
                expedient_traceability_service,
                "get_expediente_basic",
                return_value={
                    "id": 100,
                    "cliente_id": 1,
                    "unidad_tramitacion_nombre":
                        "OFICINA DE EXTRANJERÍA",
                    "unidad_tramitacion_codigo":
                        "EA000000",
                    "organismo_tramitacion":
                        "DELEGACIÓN DEL GOBIERNO",
                    "organo_presentacion":
                        "",
                },
            ),
            patch.object(
                expedient_traceability_service,
                "create_justificante",
                return_value=500,
            ),
            patch.object(
                expedient_traceability_service,
                "_update_client_residence_expiry_from_resolution",
                return_value={
                    "status": "UPDATED",
                },
            ),
            patch.object(
                expedient_traceability_service,
                "_apply_admin_document_transition",
                return_value={
                    "changed": True,
                    "workflow_code":
                        "EXTRANJERIA",
                    "estado_anterior":
                        "EN TRÁMITE",
                    "estado_nuevo":
                        "RESUELTO FAVORABLE",
                    "estado_nuevo_id": 9,
                },
            ),
            patch.object(
                expedient_traceability_service,
                "registrar_evento",
                return_value=700,
            ),
            patch.object(
                expedient_traceability_service,
                "_evaluate_derivations_after_admin_event",
                return_value={
                    "ok": True,
                    "rules_evaluated": 0,
                    "proposals": [],
                    "skipped": [],
                },
            ),
        )

    def test_favorable_resolution_applies_authorization(
        self,
    ):
        patches = self._common_patches()

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch(
                "backend.services."
                "notification_tracking_service."
                "reconcile_expedient",
                return_value={
                    "ok": True,
                },
            ),
            patch(
                "backend.services."
                "client_authorization_transition_service."
                "apply_favorable_resolution_to_client",
                return_value={
                    "applied": True,
                    "already_applied": False,
                },
            ) as apply_mock,
        ):
            result = (
                expedient_traceability_service
                .create_admin_document_event(
                    self._base_data(
                        "RESOLUCION_FAVORABLE"
                    )
                )
            )

        apply_mock.assert_called_once()

        kwargs = (
            apply_mock.call_args.kwargs
        )

        self.assertEqual(
            kwargs["expediente_id"],
            100,
        )

        self.assertEqual(
            kwargs["documento_id"],
            500,
        )

        self.assertEqual(
            kwargs["resolution_data"][
                "fecha_concesion"
            ],
            "2026-02-10",
        )

        self.assertEqual(
            kwargs["resolution_data"][
                "fecha_vigencia_hasta"
            ],
            "2027-03-01",
        )

        self.assertEqual(
            kwargs["resolution_data"][
                "numero_expediente_administrativo"
            ],
            "EX-100",
        )

        self.assertTrue(
            result[
                "authorization_transition"
            ]["ok"]
        )

        self.assertTrue(
            result[
                "authorization_transition"
            ]["applied"]
        )

    def test_non_favorable_document_does_not_apply(
        self,
    ):
        patches = self._common_patches()

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch(
                "backend.services."
                "notification_tracking_service."
                "reconcile_expedient",
                return_value={
                    "ok": True,
                },
            ),
            patch(
                "backend.services."
                "client_authorization_transition_service."
                "apply_favorable_resolution_to_client",
            ) as apply_mock,
        ):
            data = self._base_data(
                "REQUERIMIENTO"
            )

            data[
                "favorable_resolution_extraction"
            ] = None

            result = (
                expedient_traceability_service
                .create_admin_document_event(
                    data
                )
            )

        apply_mock.assert_not_called()

        self.assertIsNone(
            result[
                "authorization_transition"
            ]
        )

    def test_authorization_error_does_not_lose_document(
        self,
    ):
        patches = self._common_patches()

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch(
                "backend.services."
                "notification_tracking_service."
                "reconcile_expedient",
                return_value={
                    "ok": True,
                },
            ),
            patch(
                "backend.services."
                "client_authorization_transition_service."
                "apply_favorable_resolution_to_client",
                side_effect=ValueError(
                    "Configuración incompleta"
                ),
            ),
        ):
            result = (
                expedient_traceability_service
                .create_admin_document_event(
                    self._base_data(
                        "RESOLUCION_FAVORABLE"
                    )
                )
            )

        self.assertEqual(
            result["justificante_id"],
            500,
        )

        self.assertFalse(
            result[
                "authorization_transition"
            ]["ok"]
        )

        self.assertEqual(
            result[
                "authorization_transition"
            ]["reason"],
            "ERROR_APLICANDO_AUTORIZACION",
        )

        self.assertIn(
            "Configuración incompleta",
            result[
                "authorization_transition"
            ]["error"],
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from backend.services import (
    icpplus_test_reservation_service
    as service
)


class MemoryConfig:
    def __init__(self):
        self.values = {}

    def get_config(
        self,
        key,
        default="",
    ):
        return self.values.get(
            key,
            default,
        )

    def set_config(
        self,
        key,
        value,
    ):
        self.values[
            key
        ] = value


VALID = {
    "provider":
        "ICP_PLUS",

    "province_key":
        "ASTURIAS",

    "procedure_key":
        "POLICIA_TOMA_HUELLAS_TIE",

    "office_key":
        "CNP_OVIEDO_EXPEDICION_TIE",

    "office_text":
        "Oviedo · Expedición TIE",

    "appointment_date":
        "28/08/2026",

    "appointment_time":
        "09:15",
}


class IcpPlusTestReservationServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.memory = (
            MemoryConfig()
        )

        self.get_patch = patch.object(
            service.config_service,
            "get_config",
            side_effect=(
                self.memory.get_config
            ),
        )

        self.set_patch = patch.object(
            service.config_service,
            "set_config",
            side_effect=(
                self.memory.set_config
            ),
        )

        self.get_patch.start()
        self.set_patch.start()


    def tearDown(self):
        self.set_patch.stop()
        self.get_patch.stop()


    def test_initial_count_is_zero(
        self,
    ):
        self.assertEqual(
            service.active_reservation_count(),
            0,
        )


    def test_only_one_active_reservation_is_allowed(
        self,
    ):
        service.register_active_reservation(
            VALID
        )

        self.assertEqual(
            service.active_reservation_count(),
            1,
        )

        with self.assertRaises(
            RuntimeError
        ):
            service.register_active_reservation(
                VALID
            )


    def test_client_reference_is_forbidden(
        self,
    ):
        payload = dict(
            VALID
        )

        payload[
            "client_id"
        ] = 99

        with self.assertRaises(
            ValueError
        ):
            service.register_active_reservation(
                payload
            )


    def test_cancel_returns_to_zero(
        self,
    ):
        service.register_active_reservation(
            VALID
        )

        cancelled = (
            service
            .clear_active_reservation(
                reason=(
                    "Cita liberada para "
                    "posterior gestión"
                )
            )
        )

        self.assertEqual(
            cancelled[
                "status"
            ],
            "CANCELLED",
        )

        self.assertEqual(
            service.active_reservation_count(),
            0,
        )

import json
import unittest
from unittest.mock import patch

from backend.services import (
    icpplus_state_service
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


class IcpPlusStateServiceTest(
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


    def record(
        self,
        result,
        *,
        checked_at,
    ):
        return (
            service.record_result(
                provider="ICP_PLUS",
                flow_key=(
                    "ASTURIAS:"
                    "POLICIA_TOMA_HUELLAS_TIE"
                ),
                province_key="ASTURIAS",
                procedure_key=(
                    "POLICIA_TOMA_HUELLAS_TIE"
                ),
                office_key="CNP_OVIEDO_EXPEDICION_TIE",
                office_text=(
                    "Oviedo · Expedición TIE"
                ),
                result=result,
                checked_at=checked_at,
            )
        )


    def test_available_result_creates_persistent_card(
        self,
    ):
        card = self.record(
            {
                "page":
                    "OFFER_APPOINTMENT",
                "portal_status":
                    "ONLINE",
                "availability_status":
                    "AVAILABLE",
                "result_class":
                    "AVAILABLE",
                "appointments":
                    [
                        {
                            "date":
                                "13/10/2026",
                            "time":
                                "13:00",
                        },
                    ],
            },
            checked_at=(
                "2026-08-21T09:00:00+02:00"
            ),
        )

        self.assertEqual(
            card["current"][
                "availability_status"
            ],
            "AVAILABLE",
        )

        self.assertEqual(
            card["last_valid"][
                "availability_status"
            ],
            "AVAILABLE",
        )

        self.assertEqual(
            len(
                card[
                    "last_known_appointments"
                ]
            ),
            1,
        )

        self.assertEqual(
            len(
                service.list_cards()
            ),
            1,
        )


    def test_blocked_preserves_last_valid_and_appointments(
        self,
    ):
        self.record(
            {
                "page":
                    "OFFER_APPOINTMENT",
                "portal_status":
                    "ONLINE",
                "availability_status":
                    "AVAILABLE",
                "result_class":
                    "AVAILABLE",
                "appointments":
                    [
                        {
                            "date":
                                "13/10/2026",
                            "time":
                                "13:00",
                        },
                    ],
            },
            checked_at=(
                "2026-08-21T09:00:00+02:00"
            ),
        )

        card = self.record(
            {
                "page":
                    "REQUEST_REJECTED",
                "portal_status":
                    "BLOCKED",
                "availability_status":
                    "UNKNOWN",
                "result_class":
                    "PORTAL_BLOCKED",
                "support_id":
                    "6677000000000000000",
                "appointments":
                    [],
            },
            checked_at=(
                "2026-08-21T10:00:00+02:00"
            ),
        )

        self.assertEqual(
            card["current"][
                "portal_status"
            ],
            "BLOCKED",
        )

        self.assertEqual(
            card["last_valid"][
                "availability_status"
            ],
            "AVAILABLE",
        )

        self.assertEqual(
            card[
                "last_known_appointments"
            ][0]["date"],
            "13/10/2026",
        )


    def test_unavailable_does_not_erase_historical_appointments(
        self,
    ):
        self.record(
            {
                "portal_status":
                    "ONLINE",
                "availability_status":
                    "AVAILABLE",
                "appointments":
                    [
                        {
                            "date":
                                "13/10/2026",
                            "time":
                                "13:00",
                        },
                    ],
            },
            checked_at=(
                "2026-08-21T09:00:00+02:00"
            ),
        )

        card = self.record(
            {
                "portal_status":
                    "ONLINE",
                "availability_status":
                    "UNAVAILABLE",
                "appointments":
                    [],
            },
            checked_at=(
                "2026-08-21T11:00:00+02:00"
            ),
        )

        self.assertEqual(
            card["current"][
                "availability_status"
            ],
            "UNAVAILABLE",
        )

        self.assertEqual(
            card["last_valid"][
                "availability_status"
            ],
            "UNAVAILABLE",
        )

        self.assertEqual(
            len(
                card[
                    "last_known_appointments"
                ]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()

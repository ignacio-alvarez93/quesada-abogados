import unittest

from backend.services.icpplus_availability_service import (
    IcpPlusAvailabilityService,
)


PROFILE = {
    "icpplus_nombre":
        "ANA GARCIA",
    "icpplus_nacionalidad":
        "COLOMBIA",
    "icpplus_nie":
        "Y1234567Z",

    "icpplus_telefono":
        "600000000",

    "icpplus_email":
        "test@example.test",
}

CONTACT = {
    "telefono":
        "600000000",
    "email":
        "test@example.test",
}


class FakeRuntime:
    def __init__(self):
        self.requests = []
        self.closed = False

    def check_availability(
        self,
        request,
    ):
        self.requests.append(
            dict(request)
        )

        return {
            "portal_status":
                "ONLINE",
            "availability_status":
                "AVAILABLE",
            "appointments":
                [
                    "13/10/2026 13:00",
                    "14/10/2026 11:30",
                ],
            "result_class":
                "AVAILABLE",
        }

    def close(self):
        self.closed = True
        return True


class IcpPlusAvailabilityServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.runtime = (
            FakeRuntime()
        )

        self.service = (
            IcpPlusAvailabilityService(
                runtime=self.runtime
            )
        )


    def test_asturias_huella_offices_are_exposed(
        self,
    ):
        offices = (
            self.service.list_offices(
                "ASTURIAS",
                "POLICIA_TOMA_HUELLAS_TIE",
            )
        )

        keys = {
            item["key"]
            for item in offices
        }

        self.assertEqual(
            keys,
            {
                "CNP_AVILES",
                "CNP_GIJON",
                "CNP_LUARCA",
                "CNP_OVIEDO_EXPEDICION_TIE",
            },
        )


    def test_single_office_request_is_normalized(
        self,
    ):
        request = (
            self.service.build_request(
                province_key="ASTURIAS",
                procedure_key=(
                    "POLICIA_TOMA_HUELLAS_TIE"
                ),
                office_scope="SINGLE",
                office_key="CNP_AVILES",
                profile=PROFILE,
                contact=CONTACT,
            )
        )

        self.assertEqual(
            request["provider"],
            "ICP_PLUS",
        )

        self.assertEqual(
            request[
                "province"
            ][
                "provider_code"
            ],
            "33",
        )

        self.assertEqual(
            request[
                "procedure"
            ][
                "provider_value"
            ],
            "4010",
        )

        self.assertEqual(
            request[
                "office"
            ][
                "provider_value"
            ],
            "5",
        )

        self.assertEqual(
            request[
                "identity"
            ][
                "nie"
            ],
            "Y1234567Z",
        )


    def test_unknown_office_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            self.service.build_request(
                province_key="ASTURIAS",
                procedure_key=(
                    "POLICIA_TOMA_HUELLAS_TIE"
                ),
                office_scope="SINGLE",
                office_key="NO_EXISTE",
                profile=PROFILE,
                contact=CONTACT,
            )


    def test_check_returns_frontend_contract(
        self,
    ):
        result = (
            self.service.check_availability(
                province_key="ASTURIAS",
                procedure_key=(
                    "POLICIA_TOMA_HUELLAS_TIE"
                ),
                office_scope="SINGLE",
                office_key="CNP_AVILES",
                profile=PROFILE,
                contact=CONTACT,
            )
        )

        self.assertEqual(
            result[
                "portal_status"
            ],
            "ONLINE",
        )

        self.assertEqual(
            result[
                "availability_status"
            ],
            "AVAILABLE",
        )

        self.assertEqual(
            result[
                "appointment_count"
            ],
            2,
        )

        request = (
            self.runtime.requests[0]
        )

        self.assertEqual(
            request[
                "flow_key"
            ],
            "ASTURIAS:"
            "POLICIA_TOMA_HUELLAS_TIE",
        )


if __name__ == "__main__":
    unittest.main()

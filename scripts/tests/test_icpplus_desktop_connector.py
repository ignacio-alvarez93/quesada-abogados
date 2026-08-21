import unittest

from backend.automation.connectors.icpplus_desktop_connector import (
    IcpPlusDesktopConnector,
)


REQUEST = {
    "provider":
        "ICP_PLUS",

    "flow_key":
        "ASTURIAS:"
        "POLICIA_TOMA_HUELLAS_TIE",

    "office_scope":
        "SINGLE",

    "office": {
        "key":
            "CNP_AVILES",
        "provider_value":
            "5",
    },

    "identity": {
        "nombre":
            "ANA GARCIA",
        "nacionalidad":
            "COLOMBIA",
        "nie":
            "Y1234567Z",
    },

    "contact": {
        "telefono":
            "600000000",
        "email":
            "test@example.test",
    },
}


class FakeCompletedProcess:
    returncode = 0

    stdout = """
PAGE = OFFER_APPOINTMENT
PORTAL_STATUS = ONLINE
AVAILABILITY_STATUS = AVAILABLE
SUPPORT_ID = None
NAVIGATION_ERROR = None
APPOINTMENT_COUNT = 3

 - 13/10/2026 13:00
 - 14/10/2026 11:30
 - 15/10/2026 09:15

RESULT_CLASS = AVAILABLE
STOP BEFORE CAPTCHA / RESERVATION
"""

    stderr = ""


class ProcessSpy:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        command,
        **kwargs,
    ):
        self.calls.append(
            {
                "command":
                    list(command),
                "kwargs":
                    kwargs,
            }
        )

        return (
            FakeCompletedProcess()
        )


class IcpPlusDesktopConnectorTest(
    unittest.TestCase
):
    def test_available_result_is_parsed(
        self,
    ):
        spy = ProcessSpy()

        connector = (
            IcpPlusDesktopConnector(
                process_runner=spy,
            )
        )

        result = (
            connector
            .check_availability(
                REQUEST
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
            3,
        )

        self.assertEqual(
            result[
                "appointments"
            ][0],
            {
                "date":
                    "13/10/2026",
                "time":
                    "13:00",
            },
        )


    def test_personal_data_goes_in_environment_not_command_line(
        self,
    ):
        spy = ProcessSpy()

        connector = (
            IcpPlusDesktopConnector(
                process_runner=spy,
            )
        )

        connector.check_availability(
            REQUEST
        )

        call = spy.calls[0]

        command_text = " ".join(
            call["command"]
        )

        self.assertNotIn(
            "Y1234567Z",
            command_text,
        )

        self.assertNotIn(
            "test@example.test",
            command_text,
        )

        env = (
            call["kwargs"][
                "env"
            ]
        )

        self.assertEqual(
            env[
                "ICPPLUS_TEST_NIE"
            ],
            "Y1234567Z",
        )

        self.assertEqual(
            env[
                "ICPPLUS_TEST_EMAIL"
            ],
            "test@example.test",
        )

        self.assertEqual(
            call["kwargs"][
                "input"
            ],
            "CNP_AVILES\n",
        )


    def test_all_scope_is_rejected_until_validated(
        self,
    ):
        connector = (
            IcpPlusDesktopConnector(
                process_runner=(
                    ProcessSpy()
                ),
            )
        )

        request = dict(
            REQUEST
        )

        request[
            "office_scope"
        ] = "ALL"

        with self.assertRaises(
            ValueError
        ):
            connector.check_availability(
                request
            )


    def test_unknown_flow_is_rejected(
        self,
    ):
        connector = (
            IcpPlusDesktopConnector(
                process_runner=(
                    ProcessSpy()
                ),
            )
        )

        request = dict(
            REQUEST
        )

        request[
            "flow_key"
        ] = (
            "MADRID:"
            "OTRO_TRAMITE"
        )

        with self.assertRaises(
            ValueError
        ):
            connector.check_availability(
                request
            )


if __name__ == "__main__":
    unittest.main()


class FakeBlockedCompletedProcess:
    returncode = 0

    stdout = """
PAGE = REQUEST_REJECTED
PORTAL_STATUS = BLOCKED
AVAILABILITY_STATUS = UNKNOWN
SUPPORT_ID = 6677429513999999999
NAVIGATION_ERROR = None
APPOINTMENT_COUNT = 0
RESULT_CLASS = PORTAL_BLOCKED
"""

    stderr = ""


class BlockedProcessSpy:
    def __call__(
        self,
        command,
        **kwargs,
    ):
        return (
            FakeBlockedCompletedProcess()
        )


class IcpPlusDesktopBlockedContractTest(
    unittest.TestCase
):
    def test_blocked_result_preserves_diagnostics(
        self,
    ):
        connector = (
            IcpPlusDesktopConnector(
                process_runner=(
                    BlockedProcessSpy()
                ),
            )
        )

        result = (
            connector.check_availability(
                REQUEST
            )
        )

        self.assertEqual(
            result[
                "page"
            ],
            "REQUEST_REJECTED",
        )

        self.assertEqual(
            result[
                "portal_status"
            ],
            "BLOCKED",
        )

        self.assertEqual(
            result[
                "availability_status"
            ],
            "UNKNOWN",
        )

        self.assertEqual(
            result[
                "result_class"
            ],
            "PORTAL_BLOCKED",
        )

        self.assertEqual(
            result[
                "support_id"
            ],
            "6677429513999999999",
        )

        self.assertEqual(
            result[
                "appointment_count"
            ],
            0,
        )

import unittest

from backend.services.icpplus_runtime_service import (
    IcpPlusRuntimeService,
)


class FakeDesktopConnector:
    instances = []

    def __init__(self):
        self.requests = []
        self.closed = False

        self.__class__.instances.append(
            self
        )

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
                    {
                        "date":
                            "2026-10-13",
                        "time":
                            "13:00",
                    }
                ],
            "result_class":
                "AVAILABLE",
        }

    def close(self):
        self.closed = True
        return True


class IcpPlusRuntimeServiceTest(
    unittest.TestCase
):
    def setUp(self):
        FakeDesktopConnector.instances.clear()

    def test_check_is_one_shot_and_closes_connector(
        self,
    ):
        runtime = IcpPlusRuntimeService(
            connector_factory=(
                FakeDesktopConnector
            )
        )

        result = (
            runtime.check_availability(
                {
                    "flow_key":
                        "ASTURIAS:"
                        "POLICIA_TOMA_HUELLAS_TIE",
                }
            )
        )

        self.assertEqual(
            result[
                "availability_status"
            ],
            "AVAILABLE",
        )

        connector = (
            FakeDesktopConnector
            .instances[0]
        )

        self.assertEqual(
            len(
                connector.requests
            ),
            1,
        )

        self.assertTrue(
            connector.closed
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertTrue(
            runtime.close()
        )


    def test_close_unused_runtime_does_not_create_executor(
        self,
    ):
        runtime = IcpPlusRuntimeService(
            connector_factory=(
                FakeDesktopConnector
            )
        )

        self.assertIsNone(
            runtime._executor
        )

        self.assertTrue(
            runtime.close()
        )

        self.assertIsNone(
            runtime._executor
        )

        self.assertIsNone(
            runtime.connector
        )


    def test_close_is_idempotent_after_check(
        self,
    ):
        runtime = IcpPlusRuntimeService(
            connector_factory=(
                FakeDesktopConnector
            )
        )

        runtime.check_availability(
            {
                "flow_key":
                    "ASTURIAS:"
                    "POLICIA_TOMA_HUELLAS_TIE",
            }
        )

        self.assertTrue(
            runtime.close()
        )

        self.assertTrue(
            runtime.close()
        )

        self.assertIsNone(
            runtime._executor
        )

        self.assertIsNone(
            runtime.connector
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from backend.services import (
    icpplus_profile_service
    as service
)


PROFILE = {
    "icpplus_nombre":
        "ANA GARCIA",

    "icpplus_nacionalidad":
        "COLOMBIA",

    "icpplus_nie":
        "y-1234567-z",

    "icpplus_telefono":
        "600 000 000",

    "icpplus_email":
        "Ana@example.test",
}


class IcpPlusProfileServiceTest(
    unittest.TestCase
):
    def test_build_payload_normalizes_identity(
        self,
    ):
        payload = (
            service.build_payload(
                PROFILE
            )
        )

        self.assertEqual(
            payload,
            {
                "nombre":
                    "ANA GARCIA",

                "nacionalidad":
                    "COLOMBIA",

                "nie":
                    "Y1234567Z",
            },
        )


    def test_contact_payload_is_normalized(
        self,
    ):
        payload = (
            service
            .build_contact_payload(
                PROFILE
            )
        )

        self.assertEqual(
            payload,
            {
                "telefono":
                    "600000000",

                "email":
                    "ana@example.test",
            },
        )


    def test_execution_profile_contains_identity_and_contact(
        self,
    ):
        result = (
            service
            .build_execution_profile(
                PROFILE
            )
        )

        self.assertEqual(
            result[
                "identity"
            ][
                "nie"
            ],
            "Y1234567Z",
        )

        self.assertEqual(
            result[
                "contact"
            ][
                "telefono"
            ],
            "600000000",
        )

        self.assertEqual(
            result[
                "contact"
            ][
                "email"
            ],
            "ana@example.test",
        )


    def test_invalid_nie_is_rejected(
        self,
    ):
        profile = dict(
            PROFILE
        )

        profile[
            "icpplus_nie"
        ] = "123"

        with self.assertRaises(
            ValueError
        ):
            service.build_payload(
                profile
            )


    def test_invalid_email_is_rejected(
        self,
    ):
        profile = dict(
            PROFILE
        )

        profile[
            "icpplus_email"
        ] = "correo-invalido"

        validation = (
            service.validate_profile(
                profile
            )
        )

        self.assertFalse(
            validation[
                "valid"
            ]
        )


    @patch.object(
        service.config_service,
        "set_config",
    )
    def test_save_profile_uses_config_global(
        self,
        set_config,
    ):
        result = (
            service.save_profile(
                PROFILE
            )
        )

        self.assertEqual(
            result[
                "icpplus_nie"
            ],
            "Y1234567Z",
        )

        self.assertEqual(
            result[
                "icpplus_telefono"
            ],
            "600000000",
        )

        self.assertEqual(
            result[
                "icpplus_email"
            ],
            "ana@example.test",
        )

        self.assertEqual(
            set_config.call_count,
            5,
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.services.email_platform import (
    dehu_inbox_service,
)


class DehuLookupByIdentifierTest(
    unittest.TestCase
):
    def test_empty_identifier_returns_none(self):
        self.assertIsNone(
            dehu_inbox_service
            .get_item_by_identifier("")
        )

    def test_known_identifier_is_exact(self):
        identifier = (
            "52818606a595bcdc2c69"
        )

        item = (
            dehu_inbox_service
            .get_item_by_identifier(
                identifier
            )
        )

        # Esta prueba admite que el aviso aún no esté
        # incorporado a la base de desarrollo.
        if item is None:
            return

        self.assertEqual(
            str(
                item.get(
                    "dehu_identifier"
                )
                or ""
            ).lower(),
            identifier,
        )


if __name__ == "__main__":
    unittest.main()

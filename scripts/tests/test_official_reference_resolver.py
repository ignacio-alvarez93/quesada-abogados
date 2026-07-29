import sqlite3
import unittest

from backend.services.email_platform import (
    official_reference_resolver,
)


class OfficialReferenceResolverTest(
    unittest.TestCase
):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        self.conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                numero_expediente TEXT,
                numero_expediente_extranjeria TEXT,
                activo INTEGER DEFAULT 1
            );

            INSERT INTO clientes (
                id,
                nombre,
                primer_apellido
            )
            VALUES (
                1,
                'ANA',
                'QUESADA'
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente,
                numero_expediente_extranjeria,
                activo
            )
            VALUES (
                1,
                1,
                'EXP-1',
                '330020260008196',
                1
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente,
                numero_expediente_extranjeria,
                activo
            )
            VALUES (
                2,
                1,
                'EXP-SIN-NUMERO',
                '',
                1
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_matches_extranjeria_reference(self):
        result = (
            official_reference_resolver.resolve(
                self.conn,
                reference_value=(
                    "330020260008196"
                ),
                reference_type=(
                    "EXTRANJERIA_NUMERIC"
                ),
                family_hint="EXTRANJERIA",
            )
        )

        self.assertEqual(
            result["status"],
            official_reference_resolver
            .STATUS_MATCHED,
        )
        self.assertEqual(
            len(result["candidates"]),
            1,
        )

    def test_nationality_is_not_queried_as_empty(
        self,
    ):
        result = (
            official_reference_resolver.resolve(
                self.conn,
                reference_value="R619648/2025",
                reference_type="NACIONALIDAD_R",
                family_hint="NACIONALIDAD",
            )
        )

        self.assertEqual(
            result["status"],
            official_reference_resolver
            .STATUS_FAMILY_NOT_AVAILABLE,
        )
        self.assertEqual(
            result["candidates"],
            [],
        )

    def test_empty_reference_does_not_match_empty_rows(
        self,
    ):
        result = (
            official_reference_resolver.resolve(
                self.conn,
                reference_value="",
                reference_type="UNKNOWN",
                family_hint="UNKNOWN",
            )
        )

        self.assertEqual(
            result["status"],
            official_reference_resolver
            .STATUS_REFERENCE_NOT_DETECTED,
        )
        self.assertEqual(
            result["candidates"],
            [],
        )


if __name__ == "__main__":
    unittest.main()

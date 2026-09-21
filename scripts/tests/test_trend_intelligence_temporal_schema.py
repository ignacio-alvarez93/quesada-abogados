import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)


class TrendIntelligenceTemporalSchemaTest(
    unittest.TestCase
):
    def test_temporal_migration_is_idempotent(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            db = (
                Path(
                    tmp
                )
                / "temporal_schema.db"
            )

            repo = (
                SQLiteTrendIntelligenceRepository(
                    db
                )
            )

            repo.ensure_schema()
            repo.ensure_schema()

            conn = sqlite3.connect(
                str(
                    db
                )
            )

            try:
                tables = {
                    row[0]
                    for row
                    in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name LIKE 'ti_%'
                        """
                    ).fetchall()
                }

                self.assertIn(
                    "ti_temporal_metrics",
                    tables,
                )

                self.assertIn(
                    "ti_temporal_baselines",
                    tables,
                )

                self.assertEqual(
                    conn.execute(
                        """
                        PRAGMA foreign_key_check
                        """
                    ).fetchall(),
                    [],
                )

                self.assertEqual(
                    conn.execute(
                        """
                        PRAGMA integrity_check
                        """
                    ).fetchone()[0],
                    "ok",
                )

            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

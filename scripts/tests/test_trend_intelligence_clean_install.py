import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)


EXPECTED = {
    "ti_domains",
    "ti_sources",
    "ti_topics",
    "ti_topic_domains",
    "ti_topic_aliases",
    "ti_observations",
    "ti_observation_domains",
    "ti_observation_topics",
    "ti_signals",
    "ti_trends",
    "ti_trend_evidence",
    "ti_temporal_metrics",
    "ti_temporal_baselines",
}


class TrendIntelligenceCleanInstallTest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.db = (
            Path(
                self.tmp.name
            )
            / "ti.db"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_install(
        self,
    ):
        repo = (
            SQLiteTrendIntelligenceRepository(
                self.db
            )
        )

        repo.ensure_schema()
        repo.ensure_schema()

        conn = sqlite3.connect(
            self.db
        )

        try:
            names = {
                row[0]
                for row
                in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

            self.assertTrue(
                EXPECTED.issubset(
                    names
                )
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

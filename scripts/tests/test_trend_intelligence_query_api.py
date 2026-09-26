import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.models import (
    TREND_EMERGING,
    TREND_HOT,
    TREND_RISING,
    TrendSnapshot,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceQueryApiTest(
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
            / "query.db"
        )

        self.service = (
            TrendIntelligenceService(
                repository=(
                    SQLiteTrendIntelligenceRepository(
                        self.db
                    )
                )
            )
        )

        self.service.ensure_schema()

        self.service.create_domain(
            code="GENERIC_DOMAIN",
            name="Generic Domain",
        )

        self.service.create_source(
            code="GENERIC_SOURCE",
            name="Generic Source",
            source_type="WEB",
            collection_mode="HTTP",
        )

        self.service.create_topic(
            topic_key="GENERIC_TOPIC",
            name="Generic Topic",
            domain_codes=(
                "GENERIC_DOMAIN",
            ),
        )

        observation, _ = (
            self.service
            .record_observation(
                source_code=(
                    "GENERIC_SOURCE"
                ),
                observation_type=(
                    "ARTICLE"
                ),
                external_id="QUERY-1",
                title="Query test",
                observed_at=(
                    "2026-09-21T08:00:00+00:00"
                ),
            )
        )

        self.service.classify_observation(
            observation.id,
            domain_code=(
                "GENERIC_DOMAIN"
            ),
            topic_key=(
                "GENERIC_TOPIC"
            ),
        )

        self.service.create_signal(
            observation_id=(
                observation.id
            ),
            domain_code=(
                "GENERIC_DOMAIN"
            ),
            topic_key=(
                "GENERIC_TOPIC"
            ),
            signal_type=(
                "VOLUME_SPIKE"
            ),
            strength=95,
            detected_at=(
                "2026-09-21T08:00:00+00:00"
            ),
        )

        self.result = (
            self.service
            .recalculate_trend(
                domain_code=(
                    "GENERIC_DOMAIN"
                ),
                topic_key=(
                    "GENERIC_TOPIC"
                ),
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_domain_trends(
        self,
    ):
        items = (
            self.service
            .list_domain_trends(
                "GENERIC_DOMAIN"
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        self.assertEqual(
            items[0].id,
            self.result[
                "trend"
            ].id,
        )

    def test_evidence_query(
        self,
    ):
        evidence = (
            self.service
            .get_trend_evidence(
                self.result[
                    "trend"
                ].id
            )
        )

        self.assertEqual(
            len(
                evidence
            ),
            1,
        )

        self.assertIn(
            "VOLUME_SPIKE",
            evidence[0].reason,
        )


class TrendIntelligenceDomainSnapshotQueryTest(
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
            / "snapshot_query.db"
        )

        self.service = (
            TrendIntelligenceService(
                repository=(
                    SQLiteTrendIntelligenceRepository(
                        self.db
                    )
                )
            )
        )

        self.service.ensure_schema()

        self.domain_a = (
            self.service.create_domain(
                code="SNAPSHOT_DOMAIN_A",
                name="Snapshot Domain A",
            )
        )

        self.domain_b = (
            self.service.create_domain(
                code="SNAPSHOT_DOMAIN_B",
                name="Snapshot Domain B",
            )
        )

        self.domain_empty = (
            self.service.create_domain(
                code="SNAPSHOT_DOMAIN_EMPTY",
                name="Snapshot Domain Empty",
            )
        )

        self.topic_1 = (
            self.service.create_topic(
                topic_key="SNAPSHOT_TOPIC_1",
                name="Snapshot Topic 1",
                domain_codes=(
                    "SNAPSHOT_DOMAIN_A",
                    "SNAPSHOT_DOMAIN_B",
                ),
            )
        )

        self.topic_2 = (
            self.service.create_topic(
                topic_key="SNAPSHOT_TOPIC_2",
                name="Snapshot Topic 2",
                domain_codes=(
                    "SNAPSHOT_DOMAIN_A",
                ),
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _save_snapshot(
        self,
        *,
        domain_id,
        topic_id,
        window_start,
        window_end,
        country="",
        language="",
        status=TREND_EMERGING,
        score=0.0,
        velocity=0.0,
        aggregate_signal_count=1,
        observation_count=1,
        source_count=1,
        baseline_observation_mean=1.0,
        metadata=None,
    ):
        return (
            self.service.repository
            .save_trend_snapshot(
                TrendSnapshot(
                    id=None,
                    domain_id=domain_id,
                    topic_id=topic_id,
                    window_start=window_start,
                    window_end=window_end,
                    country=country,
                    language=language,
                    status=status,
                    score=score,
                    velocity=velocity,
                    aggregate_signal_count=(
                        aggregate_signal_count
                    ),
                    observation_count=(
                        observation_count
                    ),
                    source_count=source_count,
                    baseline_observation_mean=(
                        baseline_observation_mean
                    ),
                    metadata=metadata,
                )
            )
        )

    def _row_count(self):
        conn = sqlite3.connect(
            str(
                self.db
            )
        )
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM ti_trend_snapshots"
            ).fetchone()[0]
        finally:
            conn.close()

    def test_latest_snapshot_per_scope_multiple_topics_interleaved_windows(
        self,
    ):
        latest_topic_1 = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-03T00:00:00+00:00",
                window_end="2026-09-03T23:59:59+00:00",
                score=10.0,
            )
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_2.id,
            window_start="2026-09-02T00:00:00+00:00",
            window_end="2026-09-02T23:59:59+00:00",
            score=5.0,
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_1.id,
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-01T23:59:59+00:00",
            score=99.0,
        )

        latest_topic_2 = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_2.id,
                window_start="2026-09-04T00:00:00+00:00",
                window_end="2026-09-04T23:59:59+00:00",
                score=1.0,
            )
        )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A"
            )
        )

        self.assertEqual(
            {
                item.id
                for item
                in items
            },
            {
                latest_topic_1.id,
                latest_topic_2.id,
            },
        )

        by_topic = {
            item.topic_id: item
            for item
            in items
        }

        self.assertEqual(
            by_topic[
                self.topic_1.id
            ].window_end,
            "2026-09-03T23:59:59+00:00",
        )

        self.assertEqual(
            by_topic[
                self.topic_2.id
            ].window_end,
            "2026-09-04T23:59:59+00:00",
        )

    def test_status_filter(
        self,
    ):
        hot_snapshot = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-01T00:00:00+00:00",
                window_end="2026-09-01T23:59:59+00:00",
                status=TREND_HOT,
                score=2.0,
            )
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_1.id,
            window_start="2026-09-02T00:00:00+00:00",
            window_end="2026-09-02T23:59:59+00:00",
            status=TREND_EMERGING,
            score=1.0,
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_2.id,
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-01T23:59:59+00:00",
            status=TREND_RISING,
            score=3.0,
        )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A",
                status="HOT",
            )
        )

        self.assertEqual(
            [
                item.id
                for item
                in items
            ],
            [
                hot_snapshot.id
            ],
        )

    def test_country_filter(
        self,
    ):
        es_snapshot = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-01T00:00:00+00:00",
                window_end="2026-09-01T23:59:59+00:00",
                country="es",
                score=1.0,
            )
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_1.id,
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-01T23:59:59+00:00",
            country="mx",
            score=2.0,
        )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A",
                country="es",
            )
        )

        self.assertEqual(
            [
                item.id
                for item
                in items
            ],
            [
                es_snapshot.id
            ],
        )

        self.assertEqual(
            items[0].country,
            "ES",
        )

    def test_language_filter(
        self,
    ):
        en_snapshot = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-01T00:00:00+00:00",
                window_end="2026-09-01T23:59:59+00:00",
                language="EN",
                score=1.0,
            )
        )

        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_1.id,
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-01T23:59:59+00:00",
            language="FR",
            score=2.0,
        )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A",
                language="en",
            )
        )

        self.assertEqual(
            [
                item.id
                for item
                in items
            ],
            [
                en_snapshot.id
            ],
        )

        self.assertEqual(
            items[0].language,
            "en",
        )

    def test_empty_domain(
        self,
    ):
        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_EMPTY"
            )
        )

        self.assertEqual(
            items,
            [],
        )

    def test_unknown_domain_raises(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            self.service.list_domain_snapshots(
                "SNAPSHOT_DOMAIN_MISSING"
            )

    def test_cross_domain_isolation(
        self,
    ):
        snapshot_a = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-01T00:00:00+00:00",
                window_end="2026-09-01T23:59:59+00:00",
                score=1.0,
            )
        )

        snapshot_b = (
            self._save_snapshot(
                domain_id=self.domain_b.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-02T00:00:00+00:00",
                window_end="2026-09-02T23:59:59+00:00",
                score=2.0,
            )
        )

        items_a = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A"
            )
        )

        items_b = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_B"
            )
        )

        self.assertEqual(
            [
                item.id
                for item
                in items_a
            ],
            [
                snapshot_a.id
            ],
        )

        self.assertEqual(
            [
                item.id
                for item
                in items_b
            ],
            [
                snapshot_b.id
            ],
        )

    def test_metadata_and_components_preserved(
        self,
    ):
        saved = (
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=self.topic_1.id,
                window_start="2026-09-01T00:00:00+00:00",
                window_end="2026-09-01T23:59:59+00:00",
                status=TREND_HOT,
                score=42.5,
                velocity=3.5,
                aggregate_signal_count=7,
                observation_count=11,
                source_count=4,
                baseline_observation_mean=2.25,
                metadata={
                    "note": "preserved",
                },
            )
        )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A"
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        item = items[0]

        self.assertEqual(
            item.id,
            saved.id,
        )

        self.assertEqual(
            item.status,
            TREND_HOT,
        )

        self.assertEqual(
            item.score,
            42.5,
        )

        self.assertEqual(
            item.velocity,
            3.5,
        )

        self.assertEqual(
            item.aggregate_signal_count,
            7,
        )

        self.assertEqual(
            item.observation_count,
            11,
        )

        self.assertEqual(
            item.source_count,
            4,
        )

        self.assertEqual(
            item.baseline_observation_mean,
            2.25,
        )

        self.assertEqual(
            item.metadata,
            {
                "note": "preserved",
            },
        )

    def test_limit_respected(
        self,
    ):
        for offset in range(5):
            self._save_snapshot(
                domain_id=self.domain_a.id,
                topic_id=(
                    self.topic_1.id
                    if offset % 2 == 0
                    else self.topic_2.id
                ),
                window_start=(
                    f"2026-09-{offset + 1:02d}T00:00:00+00:00"
                ),
                window_end=(
                    f"2026-09-{offset + 1:02d}T23:59:59+00:00"
                ),
                country=f"C{offset}",
                score=float(
                    offset
                ),
            )

        items = (
            self.service
            .list_domain_snapshots(
                "SNAPSHOT_DOMAIN_A",
                limit=2,
            )
        )

        self.assertEqual(
            len(
                items
            ),
            2,
        )

    def test_query_performs_no_persistence_mutation(
        self,
    ):
        self._save_snapshot(
            domain_id=self.domain_a.id,
            topic_id=self.topic_1.id,
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-01T23:59:59+00:00",
            score=1.0,
        )

        before = self._row_count()

        self.service.list_domain_snapshots(
            "SNAPSHOT_DOMAIN_A"
        )

        self.service.list_domain_snapshots(
            "SNAPSHOT_DOMAIN_A",
            status="HOT",
            country="es",
            language="en",
            limit=1,
        )

        after = self._row_count()

        self.assertEqual(
            before,
            after,
        )


if __name__ == "__main__":
    unittest.main()

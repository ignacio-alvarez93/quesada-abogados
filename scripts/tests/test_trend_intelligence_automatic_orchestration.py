import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.automatic_signals import (
    TrendAutomaticSignalService,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
)


class AutomaticOrchestrationTest(
    unittest.TestCase
):
    def test_full_automatic_signal_pipeline(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            repo = (
                SQLiteTrendIntelligenceRepository(
                    Path(tmp)
                    / "automatic.db"
                )
            )

            core = (
                TrendIntelligenceService(
                    repository=repo
                )
            )

            core.ensure_schema()

            temporal = (
                TrendTemporalIntelligenceService(
                    repo
                )
            )

            automatic = (
                TrendAutomaticSignalService(
                    repository=repo,
                    temporal_service=temporal,
                )
            )

            core.create_domain(
                code="DOMAIN_X",
                name="Domain X",
            )

            sources = (
                "SOURCE_A",
                "SOURCE_B",
                "SOURCE_C",
                "SOURCE_D",
            )

            for source in sources:
                core.create_source(
                    code=source,
                    name=source,
                    source_type="WEB",
                    collection_mode="HTTP",
                )

            core.create_topic(
                topic_key="TOPIC_X",
                name="Topic X",
                domain_codes=(
                    "DOMAIN_X",
                ),
            )

            sequence = 0

            for day, count in (
                ("2026-09-17", 2),
                ("2026-09-18", 3),
                ("2026-09-19", 2),
            ):
                for index in range(count):
                    sequence += 1

                    observation, created = (
                        core.record_observation(
                            source_code=(
                                sources[
                                    index
                                    % len(sources)
                                ]
                            ),
                            observation_type=(
                                "ARTICLE"
                            ),
                            external_id=(
                                f"H-{sequence}"
                            ),
                            title=(
                                f"H-{sequence}"
                            ),
                            observed_at=(
                                f"{day}T10:00:00+00:00"
                            ),
                        )
                    )

                    self.assertTrue(
                        created
                    )

                    core.classify_observation(
                        observation.id,
                        domain_code="DOMAIN_X",
                        topic_key="TOPIC_X",
                    )

                temporal.materialize_window(
                    domain_code="DOMAIN_X",
                    topic_key="TOPIC_X",
                    window_start=(
                        f"{day}T00:00:00+00:00"
                    ),
                    window_end=(
                        f"{day}T23:59:59+00:00"
                    ),
                )

            for index in range(20):
                observation, created = (
                    core.record_observation(
                        source_code=(
                            sources[
                                index
                                % len(sources)
                            ]
                        ),
                        observation_type="ARTICLE",
                        external_id=(
                            f"NOW-{index}"
                        ),
                        title=(
                            f"NOW-{index}"
                        ),
                        observed_at=(
                            "2026-09-20T10:00:00+00:00"
                        ),
                    )
                )

                self.assertTrue(
                    created
                )

                core.classify_observation(
                    observation.id,
                    domain_code="DOMAIN_X",
                    topic_key="TOPIC_X",
                )

            first = (
                automatic.detect_and_persist(
                    domain_code="DOMAIN_X",
                    topic_key="TOPIC_X",
                    window_start=(
                        "2026-09-20T00:00:00+00:00"
                    ),
                    window_end=(
                        "2026-09-20T23:59:59+00:00"
                    ),
                    lookback_windows=3,
                )
            )

            types = {
                item.signal_type
                for item
                in first.signals
            }

            self.assertEqual(
                types,
                {
                    "VOLUME_SPIKE",
                    "GROWTH",
                    "CROSS_SOURCE",
                    "RECURRENCE",
                },
            )

            second = (
                automatic.detect_and_persist(
                    domain_code="DOMAIN_X",
                    topic_key="TOPIC_X",
                    window_start=(
                        "2026-09-20T00:00:00+00:00"
                    ),
                    window_end=(
                        "2026-09-20T23:59:59+00:00"
                    ),
                    lookback_windows=3,
                )
            )

            self.assertEqual(
                second.persisted_count,
                4,
            )

            domain = (
                repo.get_domain_by_code(
                    "DOMAIN_X"
                )
            )

            topic = (
                repo.get_topic_by_key(
                    "TOPIC_X"
                )
            )

            stored = (
                repo.list_aggregate_signals(
                    domain.id,
                    topic.id,
                )
            )

            self.assertEqual(
                len(stored),
                4,
            )


if __name__ == "__main__":
    unittest.main()

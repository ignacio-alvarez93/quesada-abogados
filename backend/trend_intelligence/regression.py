from backend.trend_intelligence.aggregate_scoring import AggregateTrendScorer
from backend.trend_intelligence.automatic_signals import select_active_signals
from dataclasses import dataclass

from backend.trend_intelligence.models import (
    TREND_DECLINING,
    TREND_DORMANT,
    TREND_EMERGING,
    TREND_HOT,
    TREND_RISING,
    TREND_STABLE,
)


VALID_TREND_STATUSES = {
    TREND_DECLINING,
    TREND_DORMANT,
    TREND_EMERGING,
    TREND_HOT,
    TREND_RISING,
    TREND_STABLE,
}


@dataclass(
    frozen=True,
    slots=True,
)
class RegressionGateResult:
    passed: bool

    snapshot_count: int
    aggregate_signal_count: int

    violations: tuple[
        str,
        ...,
    ]


class TrendRegressionGateService:
    def __init__(
        self,
        *,
        repository,
        temporal_service,
    ):
        self.repository = repository
        self.temporal_service = (
            temporal_service
        )

    def run_scope(
        self,
        *,
        domain_code,
        topic_key,
        country="",
        language="",
    ):
        domain, topic = (
            self.temporal_service
            ._resolve_scope(
                domain_code=domain_code,
                topic_key=topic_key,
            )
        )

        country = (
            str(country or "")
            .strip()
            .upper()
        )

        language = (
            str(language or "")
            .strip()
            .lower()
        )

        snapshots = (
            self.repository
            .list_trend_snapshots(
                domain.id,
                topic.id,
                country=country,
                language=language,
                ascending=True,
            )
        )

        signals = (
            self.repository
            .list_aggregate_signals(
                domain.id,
                topic.id,
                country=country,
                language=language,
            )
        )

        violations = []
        metrics = self.repository.list_temporal_metrics(
            domain.id, topic.id, country=country, language=language,
        )
        if {(m.window_start, m.window_end) for m in metrics} != {(m.window_start, m.window_end) for m in snapshots}:
            violations.append("INCOMPLETE_MATERIALIZATION")
        snapshot_windows = set()
        signal_identities = set()

        previous = None

        for snapshot in snapshots:
            window = (
                snapshot.window_start,
                snapshot.window_end,
            )

            if window in snapshot_windows:
                violations.append(
                    "DUPLICATE_SNAPSHOT_WINDOW"
                )

            snapshot_windows.add(
                window
            )

            if not (
                0.0
                <= snapshot.score
                <= 100.0
            ):
                violations.append(
                    "SNAPSHOT_SCORE_OUT_OF_RANGE"
                )

            if (
                snapshot.status
                not in VALID_TREND_STATUSES
            ):
                violations.append(
                    "INVALID_TREND_STATUS"
                )

            previous = self.repository.get_latest_trend_snapshot_before(
                domain.id, topic.id, before_window_start=snapshot.window_start,
                country=country, language=language,
            )
            metric = self.repository.get_temporal_metric(
                domain.id, topic.id, window_start=snapshot.window_start,
                window_end=snapshot.window_end, country=country, language=language,
            )
            baseline = self.repository.get_temporal_baseline(
                domain.id, topic.id, reference_window_start=snapshot.window_start,
                reference_window_end=snapshot.window_end, country=country, language=language,
                lookback_windows=(snapshot.metadata or {}).get("lookback_windows"),
            )
            if baseline is None or metric is None:
                violations.append("INCOMPLETE_MATERIALIZATION")
            if baseline is not None and snapshot.baseline_observation_mean != baseline.observation_mean:
                violations.append("SNAPSHOT_BASELINE_MISMATCH")
            if metric is not None:
                stats = self.repository.get_temporal_window_stats(
                    domain.id, topic.id, window_start=snapshot.window_start,
                    window_end=snapshot.window_end, country=country, language=language,
                )
                if any(getattr(metric, key) != value for key, value in stats.items()):
                    violations.append("STALE_TEMPORAL_METRIC")
                if (snapshot.observation_count, snapshot.source_count) != (metric.observation_count, metric.source_count):
                    violations.append("SNAPSHOT_METRIC_MISMATCH")
            if previous is not None:
                expected_velocity = round(
                    snapshot.score
                    - previous.score,
                    4,
                )

                actual_velocity = round(
                    snapshot.velocity,
                    4,
                )

                if (
                    actual_velocity
                    != expected_velocity
                ):
                    violations.append(
                        "SNAPSHOT_VELOCITY_MISMATCH"
                    )

            scoped_signals = [
                item
                for item
                in signals
                if (
                    item.window_start
                    == snapshot.window_start
                    and
                    item.window_end
                    == snapshot.window_end
                )
            ]

            scoped_signals = select_active_signals(scoped_signals, (snapshot.metadata or {}).get("active_detector_versions"))
            if (
                snapshot.aggregate_signal_count
                != len(scoped_signals)
            ):
                violations.append(
                    "SNAPSHOT_SIGNAL_COUNT_MISMATCH"
                )

            scored = AggregateTrendScorer(signal_weights=(snapshot.metadata or {}).get("signal_weights")).calculate(
                scoped_signals, prior_score=previous.score if previous else None,
            )
            if (snapshot.score, snapshot.velocity, snapshot.status) != (scored.score, scored.velocity, scored.status):
                violations.append("SNAPSHOT_SCORING_MISMATCH")

        for signal in signals:
            if (signal.window_start, signal.window_end) not in snapshot_windows:
                violations.append("INCOMPLETE_MATERIALIZATION")
            identity = (
                signal.window_start,
                signal.window_end,
                signal.signal_type,
                signal.detector_key,
                signal.detector_version,
            )

            if identity in signal_identities:
                violations.append(
                    "DUPLICATE_AGGREGATE_SIGNAL"
                )

            signal_identities.add(
                identity
            )

            if not (
                0.0
                <= signal.strength
                <= 100.0
            ):
                violations.append(
                    "SIGNAL_STRENGTH_OUT_OF_RANGE"
                )

            if not (
                0.0
                <= signal.confidence
                <= 1.0
            ):
                violations.append(
                    "SIGNAL_CONFIDENCE_OUT_OF_RANGE"
                )

            if not signal.detector_key:
                violations.append(
                    "MISSING_DETECTOR_KEY"
                )

            if not signal.detector_version:
                violations.append(
                    "MISSING_DETECTOR_VERSION"
                )

        return RegressionGateResult(
            passed=(
                len(violations)
                == 0
            ),
            snapshot_count=len(
                snapshots
            ),
            aggregate_signal_count=len(
                signals
            ),
            violations=tuple(
                violations
            ),
        )

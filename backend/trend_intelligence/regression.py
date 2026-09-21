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

            if (
                snapshot.aggregate_signal_count
                != len(scoped_signals)
            ):
                violations.append(
                    "SNAPSHOT_SIGNAL_COUNT_MISMATCH"
                )

            previous = snapshot

        for signal in signals:
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

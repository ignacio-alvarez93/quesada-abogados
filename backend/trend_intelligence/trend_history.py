from dataclasses import dataclass

from backend.trend_intelligence.aggregate_scoring import (
    AggregateTrendScorer,
)
from backend.trend_intelligence.models import (
    TrendSnapshot,
)


@dataclass(
    frozen=True,
    slots=True,
)
class BacktestWindow:
    window_start: str
    window_end: str

    score: float
    velocity: float
    status: str

    observation_count: int
    source_count: int

    signal_types: tuple[
        str,
        ...,
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class TrendBacktestResult:
    domain_code: str
    topic_key: str

    window_count: int

    peak_score: float
    final_score: float

    windows: tuple[
        BacktestWindow,
        ...,
    ]


class TrendSnapshotService:
    def __init__(
        self,
        *,
        repository,
        temporal_service,
        scorer=None,
    ):
        self.repository = repository
        self.temporal_service = (
            temporal_service
        )

        self.scorer = (
            scorer
            or AggregateTrendScorer()
        )

    def materialize(
        self,
        *,
        domain_code,
        topic_key,
        window_start,
        window_end,
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

        country = str(
            country
            or ""
        ).strip().upper()

        language = str(
            language
            or ""
        ).strip().lower()

        metric = (
            self.repository
            .get_temporal_metric(
                domain.id,
                topic.id,
                window_start=window_start,
                window_end=window_end,
                country=country,
                language=language,
            )
        )

        if metric is None:
            raise ValueError(
                "Métrica temporal inexistente"
            )

        signals = [
            item
            for item
            in self.repository
            .list_aggregate_signals(
                domain.id,
                topic.id,
                window_start=window_start,
                window_end=window_end,
                country=country,
                language=language,
            )
            if (
                item.window_start
                == window_start
                and item.window_end
                == window_end
            )
        ]

        previous = (
            self.repository
            .get_latest_trend_snapshot_before(
                domain.id,
                topic.id,
                before_window_start=(
                    window_start
                ),
                country=country,
                language=language,
            )
        )

        scored = (
            self.scorer
            .calculate(
                signals,
                prior_score=(
                    previous.score
                    if previous
                    is not None
                    else None
                ),
            )
        )

        baseline = (
            self.repository
            .get_latest_temporal_baseline(
                domain.id,
                topic.id,
                country=country,
                language=language,
            )
        )

        snapshot = TrendSnapshot(
            id=None,
            domain_id=domain.id,
            topic_id=topic.id,
            window_start=window_start,
            window_end=window_end,
            country=country,
            language=language,
            status=scored.status,
            score=scored.score,
            velocity=scored.velocity,
            aggregate_signal_count=(
                scored.signal_count
            ),
            observation_count=(
                metric.observation_count
            ),
            source_count=(
                metric.source_count
            ),
            baseline_observation_mean=(
                baseline.observation_mean
                if baseline
                is not None
                else 0.0
            ),
            metadata={
                "signal_type_count":
                    scored.signal_type_count,

                "weighted_signal_score":
                    scored.weighted_signal_score,

                "diversity_bonus":
                    scored.diversity_bonus,

                "signal_types":
                    sorted(
                        {
                            item.signal_type
                            for item
                            in signals
                        }
                    ),
            },
        )

        return (
            self.repository
            .save_trend_snapshot(
                snapshot
            )
        )


class TrendBacktestingService:
    def __init__(
        self,
        *,
        repository,
        temporal_service,
        scorer=None,
    ):
        self.repository = repository
        self.temporal_service = (
            temporal_service
        )

        self.scorer = (
            scorer
            or AggregateTrendScorer()
        )

    def run(
        self,
        *,
        domain_code,
        topic_key,
        country="",
        language="",
        limit=90,
    ):
        domain, topic = (
            self.temporal_service
            ._resolve_scope(
                domain_code=domain_code,
                topic_key=topic_key,
            )
        )

        country = str(
            country
            or ""
        ).strip().upper()

        language = str(
            language
            or ""
        ).strip().lower()

        metrics = (
            self.repository
            .list_temporal_metrics(
                domain.id,
                topic.id,
                country=country,
                language=language,
                limit=limit,
                ascending=True,
            )
        )

        windows = []
        prior_score = None

        for metric in metrics:
            signals = [
                item
                for item
                in self.repository
                .list_aggregate_signals(
                    domain.id,
                    topic.id,
                    window_start=(
                        metric.window_start
                    ),
                    window_end=(
                        metric.window_end
                    ),
                    country=country,
                    language=language,
                )
                if (
                    item.window_start
                    == metric.window_start
                    and item.window_end
                    == metric.window_end
                )
            ]

            scored = (
                self.scorer
                .calculate(
                    signals,
                    prior_score=(
                        prior_score
                    ),
                )
            )

            windows.append(
                BacktestWindow(
                    window_start=(
                        metric.window_start
                    ),
                    window_end=(
                        metric.window_end
                    ),
                    score=scored.score,
                    velocity=(
                        scored.velocity
                    ),
                    status=(
                        scored.status
                    ),
                    observation_count=(
                        metric
                        .observation_count
                    ),
                    source_count=(
                        metric.source_count
                    ),
                    signal_types=tuple(
                        sorted(
                            {
                                item.signal_type
                                for item
                                in signals
                            }
                        )
                    ),
                )
            )

            prior_score = (
                scored.score
            )

        scores = [
            item.score
            for item
            in windows
        ]

        return TrendBacktestResult(
            domain_code=str(
                domain_code
            ).strip().upper(),
            topic_key=str(
                topic_key
            ).strip().upper(),
            window_count=len(
                windows
            ),
            peak_score=(
                max(
                    scores
                )
                if scores
                else 0.0
            ),
            final_score=(
                scores[-1]
                if scores
                else 0.0
            ),
            windows=tuple(
                windows
            ),
        )

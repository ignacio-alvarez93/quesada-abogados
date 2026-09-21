from dataclasses import dataclass, fields
import json

from backend.trend_intelligence.automatic_signals import (
    TrendAutomaticSignalService,
)
from backend.trend_intelligence.trend_history import (
    TrendSnapshotService,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ProcessedTrendWindow:
    domain_code: str
    topic_key: str

    window_start: str
    window_end: str

    observation_count: int
    source_count: int

    aggregate_signal_count: int

    score: float
    velocity: float
    status: str

    signal_types: tuple[str, ...]
    materialization_signature: tuple = ()


@dataclass(
    frozen=True,
    slots=True,
)
class TrendReplayResult:
    domain_code: str
    topic_key: str

    processed_windows: int

    windows: tuple[
        ProcessedTrendWindow,
        ...,
    ]

    signature: tuple[
        tuple,
        ...,
    ]


class TrendAutomaticPipelineService:
    def __init__(
        self,
        *,
        repository,
        temporal_service,
        automatic_signal_service=None,
        snapshot_service=None,
    ):
        self.repository = repository
        self.temporal_service = temporal_service

        self.automatic_signal_service = (
            automatic_signal_service
            or TrendAutomaticSignalService(
                repository=repository,
                temporal_service=temporal_service,
            )
        )

        self.snapshot_service = (
            snapshot_service
            or TrendSnapshotService(
                repository=repository,
                temporal_service=temporal_service,
            )
        )

    @staticmethod
    def _signature(
        windows,
    ):
        return tuple(
            (
                item.window_start,
                item.window_end,
                round(item.score, 6),
                round(item.velocity, 6),
                item.status,
                item.observation_count,
                item.source_count,
                item.aggregate_signal_count,
                item.signal_types,
                item.materialization_signature,
            )
            for item
            in windows
        )

    def process_window(self, **kwargs):
        with self.repository.window_transaction():
            return self._process_window(**kwargs)

    def _process_window(
        self,
        *,
        domain_code,
        topic_key,
        window_start,
        window_end,
        lookback_windows=7,
        country="",
        language="",
    ):
        analysis = (
            self.temporal_service
            .analyze_window(
                domain_code=domain_code,
                topic_key=topic_key,
                window_start=window_start,
                window_end=window_end,
                lookback_windows=lookback_windows,
                country=country,
                language=language,
            )
        )

        metric = analysis.metric

        automatic = (
            self.automatic_signal_service
            .detect_and_persist(
                domain_code=domain_code,
                topic_key=topic_key,
                window_start=metric.window_start,
                window_end=metric.window_end,
                lookback_windows=lookback_windows,
                country=metric.country,
                language=metric.language,
            )
        )

        snapshot = (
            self.snapshot_service
            .materialize(
                domain_code=domain_code,
                topic_key=topic_key,
                window_start=metric.window_start,
                window_end=metric.window_end,
                country=metric.country,
                language=metric.language,
                lookback_windows=lookback_windows,
                active_detector_versions=self.automatic_signal_service.active_detector_versions(),
            )
        )

        return ProcessedTrendWindow(
            domain_code=(
                str(domain_code)
                .strip()
                .upper()
            ),
            topic_key=(
                str(topic_key)
                .strip()
                .upper()
            ),
            window_start=metric.window_start,
            window_end=metric.window_end,
            observation_count=(
                metric.observation_count
            ),
            source_count=(
                metric.source_count
            ),
            aggregate_signal_count=(
                snapshot.aggregate_signal_count
            ),
            score=snapshot.score,
            velocity=snapshot.velocity,
            status=snapshot.status,
            materialization_signature=(
                _business_state(metric),
                _business_state(analysis.baseline),
                tuple(sorted(_business_state(s) for s in automatic.signals)),
                _business_state(snapshot),
            ),
            signal_types=tuple(
                sorted(
                    {
                        item.signal_type
                        for item
                        in automatic.signals
                    }
                )
            ),
        )

    def replay_existing_windows(
        self,
        *,
        domain_code,
        topic_key,
        lookback_windows=7,
        country="",
        language="",
        limit=None,
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

        # Replay orders by (start, end). Baselines only use windows ending
        # at/before the current start; overlapping windows are not predecessors.
        existing = (
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

        for metric in existing:
            windows.append(
                self.process_window(
                    domain_code=domain_code,
                    topic_key=topic_key,
                    window_start=(
                        metric.window_start
                    ),
                    window_end=(
                        metric.window_end
                    ),
                    lookback_windows=(
                        lookback_windows
                    ),
                    country=country,
                    language=language,
                )
            )

        windows = tuple(windows)

        return TrendReplayResult(
            domain_code=(
                str(domain_code)
                .strip()
                .upper()
            ),
            topic_key=(
                str(topic_key)
                .strip()
                .upper()
            ),
            processed_windows=len(
                windows
            ),
            windows=windows,
            signature=(
                self._signature(
                    windows
                )
            ),
        )


def _business_state(record):
    return json.dumps({f.name: getattr(record, f.name) for f in fields(record)
        if f.name not in {"id", "created_at", "updated_at"}},
        sort_keys=True, ensure_ascii=False, allow_nan=False)

from dataclasses import dataclass

from backend.trend_intelligence.advanced_detection import (
    CrossSourceRecurrenceDetector,
)
from backend.trend_intelligence.detection import (
    AutomaticVolumeGrowthDetector,
)
from backend.trend_intelligence.models import (
    TrendAggregateSignal,
)


@dataclass(
    frozen=True,
    slots=True,
)
class AutomaticSignalOrchestrationResult:
    persisted_count: int

    signals: tuple[
        TrendAggregateSignal,
        ...,
    ]


class TrendAutomaticSignalService:
    def __init__(
        self,
        *,
        repository,
        temporal_service,
        volume_growth_detector=None,
        advanced_detector=None,
    ):
        self.repository = repository
        self.temporal_service = temporal_service

        self.volume_growth_detector = (
            volume_growth_detector
            or AutomaticVolumeGrowthDetector()
        )

        self.advanced_detector = (
            advanced_detector
            or CrossSourceRecurrenceDetector()
        )

    def active_detector_versions(self):
        return {
            "TEMPORAL_VOLUME_SPIKE": self.volume_growth_detector.DETECTOR_VERSION,
            "TEMPORAL_GROWTH": self.volume_growth_detector.DETECTOR_VERSION,
            "TEMPORAL_CROSS_SOURCE": self.advanced_detector.DETECTOR_VERSION,
            "TEMPORAL_RECURRENCE": self.advanced_detector.DETECTOR_VERSION,
        }

    def detect_and_persist(self, **kwargs):
        with self.repository.window_transaction():
            return self._detect_and_persist(**kwargs)

    def _detect_and_persist(
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
        domain, topic = (
            self.temporal_service
            ._resolve_scope(
                domain_code=domain_code,
                topic_key=topic_key,
            )
        )

        analysis = (
            self.temporal_service
            .analyze_window(
                domain_code=domain_code,
                topic_key=topic_key,
                window_start=window_start,
                window_end=window_end,
                lookback_windows=(
                    lookback_windows
                ),
                country=country,
                language=language,
            )
        )

        history = (
            self.repository
            .list_temporal_metrics_before(
                domain.id,
                topic.id,
                before_window_start=(
                    analysis
                    .metric
                    .window_start
                ),
                country=(
                    analysis
                    .metric
                    .country
                ),
                language=(
                    analysis
                    .metric
                    .language
                ),
                limit=(
                    lookback_windows
                ),
            )
        )

        basic = (
            self.volume_growth_detector
            .detect(
                analysis
            )
        )

        advanced = (
            self.advanced_detector
            .detect(
                current_metric=(
                    analysis.metric
                ),
                historical_metrics=(
                    history
                ),
            )
        )

        candidates = (
            list(
                basic.signals
            )
            + list(
                advanced.signals
            )
        )

        persisted = []

        for candidate in candidates:
            stored = (
                self.repository
                .save_aggregate_signal(
                    TrendAggregateSignal(
                        id=None,
                        domain_id=(
                            domain.id
                        ),
                        topic_id=(
                            topic.id
                        ),
                        signal_type=(
                            candidate.signal_type
                        ),
                        window_start=(
                            analysis
                            .metric
                            .window_start
                        ),
                        window_end=(
                            analysis
                            .metric
                            .window_end
                        ),
                        country=(
                            analysis
                            .metric
                            .country
                        ),
                        language=(
                            analysis
                            .metric
                            .language
                        ),
                        strength=(
                            candidate.strength
                        ),
                        confidence=(
                            candidate.confidence
                        ),
                        numeric_value=(
                            candidate
                            .numeric_value
                        ),
                        detector_key=(
                            candidate
                            .detector_key
                        ),
                        detector_version=(
                            candidate
                            .detector_version
                        ),
                        reason=(
                            candidate.reason
                        ),
                        metadata=(
                            candidate.metadata
                        ),
                    )
                )
            )

            persisted.append(
                stored
            )

        self.repository.reconcile_aggregate_signals(
            analysis.metric, self.active_detector_versions(), persisted,
        )

        return (
            AutomaticSignalOrchestrationResult(
                persisted_count=len(
                    persisted
                ),
                signals=tuple(
                    persisted
                ),
            )
        )


def default_active_detector_versions():
    return {
        "TEMPORAL_VOLUME_SPIKE": AutomaticVolumeGrowthDetector.DETECTOR_VERSION,
        "TEMPORAL_GROWTH": AutomaticVolumeGrowthDetector.DETECTOR_VERSION,
        "TEMPORAL_CROSS_SOURCE": CrossSourceRecurrenceDetector.DETECTOR_VERSION,
        "TEMPORAL_RECURRENCE": CrossSourceRecurrenceDetector.DETECTOR_VERSION,
    }


def resolve_active_detector_versions(signals, versions=None):
    if versions is not None:
        return dict(versions)
    resolved = default_active_detector_versions()
    # Custom persisted detectors with one version remain supported. Ambiguous
    # custom provenance requires explicit selection, never version guessing.
    for key in {s.detector_key for s in signals} - resolved.keys():
        found = {s.detector_version for s in signals if s.detector_key == key}
        if len(found) != 1:
            raise ValueError("Explicit active version required for custom detector")
        resolved[key] = found.pop()
    return resolved


def select_active_signals(signals, versions=None):
    signals = list(signals)
    versions = resolve_active_detector_versions(signals, versions)
    return [s for s in signals if versions.get(s.detector_key) == s.detector_version]

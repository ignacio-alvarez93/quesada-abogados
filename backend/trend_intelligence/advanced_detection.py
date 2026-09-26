from dataclasses import dataclass
from typing import Any

from backend.trend_intelligence.models import (
    canonical_window,
    time_key,
    canonical_country,
    canonical_language,

    SIGNAL_CROSS_SOURCE,
    SIGNAL_RECURRENCE,
    TrendTemporalMetric,
)


@dataclass(
    frozen=True,
    slots=True,
)
class AdvancedDetectionConfig:
    cross_source_min_sources: int = 2
    cross_source_strong_sources: int = 5

    recurrence_min_active_windows: int = 3
    recurrence_lookback_windows: int = 7

    min_observations_per_window: int = 1


@dataclass(
    frozen=True,
    slots=True,
)
class AdvancedDetectedSignal:
    signal_type: str

    strength: float
    confidence: float

    numeric_value: float | None

    detector_key: str
    detector_version: str

    reason: str

    metadata: dict[
        str,
        Any,
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class AdvancedDetectionResult:
    signals: tuple[
        AdvancedDetectedSignal,
        ...,
    ]


def _clamp(
    value,
):
    return max(
        0.0,
        min(
            100.0,
            float(value),
        ),
    )


class CrossSourceRecurrenceDetector:
    DETECTOR_VERSION = "1"

    def __init__(
        self,
        config=None,
    ):
        self.config = (
            config
            or AdvancedDetectionConfig()
        )

    def detect(
        self,
        *,
        current_metric: TrendTemporalMetric,
        historical_metrics,
    ):
        canonical_window(current_metric.window_start, current_metric.window_end)
        historical_metrics = list(historical_metrics)
        seen = set()
        scope = lambda m: (m.domain_id, m.topic_id, canonical_country(m.country), canonical_language(m.language))
        for item in historical_metrics:
            identity = canonical_window(item.window_start, item.window_end)
            if identity in seen or scope(item) != scope(current_metric) or time_key(item.window_end) > time_key(current_metric.window_start):
                raise ValueError("Duplicate, future or out-of-scope recurrence history")
            seen.add(identity)
        historical_metrics.sort(key=lambda m: (time_key(m.window_end), time_key(m.window_start)), reverse=True)
        signals = []

        source_count = int(
            current_metric.source_count
        )

        if (
            source_count
            >= self.config
            .cross_source_min_sources
        ):
            denominator = max(
                1,
                (
                    self.config
                    .cross_source_strong_sources
                    -
                    self.config
                    .cross_source_min_sources
                ),
            )

            normalized = (
                source_count
                -
                self.config
                .cross_source_min_sources
            ) / denominator

            strength = _clamp(
                55.0
                + (
                    min(
                        1.0,
                        max(
                            0.0,
                            normalized,
                        ),
                    )
                    * 45.0
                )
            )

            confidence = min(
                1.0,
                round(
                    0.70
                    + (
                        min(
                            source_count,
                            5,
                        )
                        * 0.06
                    ),
                    4,
                ),
            )

            signals.append(
                AdvancedDetectedSignal(
                    signal_type=(
                        SIGNAL_CROSS_SOURCE
                    ),
                    strength=round(
                        strength,
                        2,
                    ),
                    confidence=confidence,
                    numeric_value=float(
                        source_count
                    ),
                    detector_key=(
                        "TEMPORAL_CROSS_SOURCE"
                    ),
                    detector_version=(
                        self.DETECTOR_VERSION
                    ),
                    reason=(
                        "Topic is active across "
                        "multiple sources"
                    ),
                    metadata={
                        "source_count":
                            source_count,
                        "window_start":
                            current_metric
                            .window_start,
                        "window_end":
                            current_metric
                            .window_end,
                    },
                )
            )

        history = list(
            historical_metrics[
                :
                self.config
                .recurrence_lookback_windows
            ]
        )

        active_history = sum(
            1
            for item
            in history
            if (
                item.observation_count
                >= self.config
                .min_observations_per_window
            )
        )

        current_active = (
            current_metric.observation_count
            >= self.config
            .min_observations_per_window
        )

        active_windows = (
            active_history
            + (
                1
                if current_active
                else 0
            )
        )

        total_windows = (
            len(history)
            + 1
        )

        if (
            current_active
            and active_windows
            >= self.config
            .recurrence_min_active_windows
        ):
            ratio = (
                active_windows
                / total_windows
            )

            strength = _clamp(
                55.0
                + (
                    ratio
                    * 45.0
                )
            )

            confidence = min(
                1.0,
                round(
                    0.65
                    + (
                        ratio
                        * 0.35
                    ),
                    4,
                ),
            )

            signals.append(
                AdvancedDetectedSignal(
                    signal_type=(
                        SIGNAL_RECURRENCE
                    ),
                    strength=round(
                        strength,
                        2,
                    ),
                    confidence=confidence,
                    numeric_value=round(
                        ratio,
                        6,
                    ),
                    detector_key=(
                        "TEMPORAL_RECURRENCE"
                    ),
                    detector_version=(
                        self.DETECTOR_VERSION
                    ),
                    reason=(
                        "Topic remains active across "
                        "multiple temporal windows"
                    ),
                    metadata={
                        "active_windows":
                            active_windows,
                        "total_windows":
                            total_windows,
                        "recurrence_ratio":
                            round(
                                ratio,
                                6,
                            ),
                    },
                )
            )

        return AdvancedDetectionResult(
            signals=tuple(
                signals
            )
        )

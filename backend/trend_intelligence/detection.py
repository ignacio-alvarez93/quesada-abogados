"""
Trend Intelligence · automatic signal detection.

Convierte análisis temporal en señales candidatas explicables.

Esta capa:
- no persiste;
- no conoce SQLite;
- no conoce collectors;
- no conoce UI;
- no depende de verticales concretos.

TI-3B cubre:
- VOLUME_SPIKE;
- GROWTH.

La persistencia/orquestación automática se introduce
en una fase posterior para mantener los detectores puros,
deterministas y fácilmente testeables.
"""

from dataclasses import dataclass
from typing import Any

from backend.trend_intelligence.models import (
    SIGNAL_GROWTH,
    SIGNAL_VOLUME_SPIKE,
)
from backend.trend_intelligence.temporal import (
    TemporalWindowAnalysis,
)


@dataclass(
    frozen=True,
    slots=True,
)
class AutomaticSignalDetectionConfig:
    min_baseline_samples: int = 3
    min_current_observations: int = 3

    volume_spike_growth_percent: float = 100.0
    volume_spike_z_score: float = 2.0

    growth_growth_percent: float = 50.0
    growth_z_score: float = 1.0

    strong_growth_percent: float = 200.0
    strong_z_score: float = 3.0


@dataclass(
    frozen=True,
    slots=True,
)
class DetectedTrendSignal:
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
class AutomaticDetectionResult:
    baseline_ready: bool

    current_observation_count: int
    baseline_observation_mean: float
    baseline_sample_count: int

    signals: tuple[
        DetectedTrendSignal,
        ...,
    ]


def _clamp(
    value,
    minimum=0.0,
    maximum=100.0,
):
    return max(
        minimum,
        min(
            maximum,
            float(
                value
            ),
        ),
    )


def _confidence(
    *,
    baseline_samples,
    source_count,
    growth_percent,
):
    sample_factor = min(
        1.0,
        float(
            baseline_samples
        )
        / 7.0,
    )

    source_factor = min(
        1.0,
        0.70
        + (
            max(
                0,
                int(
                    source_count
                )
                - 1,
            )
            * 0.10
        ),
    )

    growth_factor = min(
        1.0,
        0.70
        + (
            max(
                0.0,
                float(
                    growth_percent
                    or 0.0
                ),
            )
            / 1000.0
        ),
    )

    return round(
        max(
            0.0,
            min(
                1.0,
                (
                    sample_factor
                    * 0.45
                )
                + (
                    source_factor
                    * 0.30
                )
                + (
                    growth_factor
                    * 0.25
                ),
            ),
        ),
        4,
    )


def _volume_strength(
    *,
    growth_percent,
    z_score,
    current_count,
):
    growth_component = min(
        45.0,
        max(
            0.0,
            float(
                growth_percent
                or 0.0
            )
            / 5.0,
        ),
    )

    z_component = min(
        30.0,
        max(
            0.0,
            float(
                z_score
            )
            * 10.0,
        ),
    )

    volume_component = min(
        25.0,
        max(
            0.0,
            float(
                current_count
            )
            * 2.5,
        ),
    )

    return round(
        _clamp(
            growth_component
            + z_component
            + volume_component
        ),
        2,
    )


def _growth_strength(
    *,
    growth_percent,
    z_score,
):
    growth_component = min(
        70.0,
        max(
            0.0,
            float(
                growth_percent
                or 0.0
            )
            / 3.0,
        ),
    )

    z_component = min(
        30.0,
        max(
            0.0,
            float(
                z_score
            )
            * 10.0,
        ),
    )

    return round(
        _clamp(
            growth_component
            + z_component
        ),
        2,
    )


class AutomaticVolumeGrowthDetector:
    DETECTOR_VERSION = "1"

    def __init__(
        self,
        config=None,
    ):
        self.config = (
            config
            or AutomaticSignalDetectionConfig()
        )

        if (
            self.config.min_baseline_samples
            < 1
        ):
            raise ValueError(
                (
                    "min_baseline_samples "
                    "debe ser >= 1"
                )
            )

        if (
            self.config.min_current_observations
            < 1
        ):
            raise ValueError(
                (
                    "min_current_observations "
                    "debe ser >= 1"
                )
            )

    def detect(
        self,
        analysis: TemporalWindowAnalysis,
    ) -> AutomaticDetectionResult:
        metric = analysis.metric
        baseline = analysis.baseline

        baseline_ready = (
            baseline.sample_count
            >= self.config.min_baseline_samples
        )

        if not baseline_ready:
            return (
                AutomaticDetectionResult(
                    baseline_ready=False,
                    current_observation_count=(
                        metric.observation_count
                    ),
                    baseline_observation_mean=(
                        baseline.observation_mean
                    ),
                    baseline_sample_count=(
                        baseline.sample_count
                    ),
                    signals=(),
                )
            )

        if (
            metric.observation_count
            < self.config.min_current_observations
        ):
            return (
                AutomaticDetectionResult(
                    baseline_ready=True,
                    current_observation_count=(
                        metric.observation_count
                    ),
                    baseline_observation_mean=(
                        baseline.observation_mean
                    ),
                    baseline_sample_count=(
                        baseline.sample_count
                    ),
                    signals=(),
                )
            )

        growth_percent = (
            analysis
            .observation_growth_percent
        )

        z_score = (
            analysis
            .observation_z_score
        )

        effective_growth = float(
            growth_percent
            if growth_percent is not None
            else 0.0
        )

        common_metadata = {
            "window_start":
                metric.window_start,

            "window_end":
                metric.window_end,

            "current_observation_count":
                metric.observation_count,

            "current_source_count":
                metric.source_count,

            "baseline_sample_count":
                baseline.sample_count,

            "baseline_observation_mean":
                baseline.observation_mean,

            "baseline_observation_stddev":
                baseline.observation_stddev,

            "observation_growth_percent":
                growth_percent,

            "observation_z_score":
                z_score,
        }

        confidence = _confidence(
            baseline_samples=(
                baseline.sample_count
            ),
            source_count=(
                metric.source_count
            ),
            growth_percent=(
                effective_growth
            ),
        )

        detected = []

        volume_spike = (
            effective_growth
            >= self.config
            .volume_spike_growth_percent
            or
            z_score
            >= self.config
            .volume_spike_z_score
        )

        if volume_spike:
            detected.append(
                DetectedTrendSignal(
                    signal_type=(
                        SIGNAL_VOLUME_SPIKE
                    ),
                    strength=(
                        _volume_strength(
                            growth_percent=(
                                effective_growth
                            ),
                            z_score=(
                                z_score
                            ),
                            current_count=(
                                metric
                                .observation_count
                            ),
                        )
                    ),
                    confidence=(
                        confidence
                    ),
                    numeric_value=(
                        float(
                            metric
                            .observation_count
                        )
                    ),
                    detector_key=(
                        "TEMPORAL_VOLUME_SPIKE"
                    ),
                    detector_version=(
                        self.DETECTOR_VERSION
                    ),
                    reason=(
                        "Current observation volume "
                        "exceeds historical baseline"
                    ),
                    metadata={
                        **common_metadata,
                        "threshold_growth_percent":
                            self.config
                            .volume_spike_growth_percent,
                        "threshold_z_score":
                            self.config
                            .volume_spike_z_score,
                    },
                )
            )

        positive_growth = (
            metric.observation_count
            > baseline.observation_mean
            and (
                effective_growth
                >= self.config
                .growth_growth_percent
                or
                z_score
                >= self.config
                .growth_z_score
            )
        )

        if positive_growth:
            detected.append(
                DetectedTrendSignal(
                    signal_type=(
                        SIGNAL_GROWTH
                    ),
                    strength=(
                        _growth_strength(
                            growth_percent=(
                                effective_growth
                            ),
                            z_score=(
                                z_score
                            ),
                        )
                    ),
                    confidence=(
                        confidence
                    ),
                    numeric_value=(
                        effective_growth
                    ),
                    detector_key=(
                        "TEMPORAL_GROWTH"
                    ),
                    detector_version=(
                        self.DETECTOR_VERSION
                    ),
                    reason=(
                        "Current observation growth "
                        "exceeds historical baseline"
                    ),
                    metadata={
                        **common_metadata,
                        "threshold_growth_percent":
                            self.config
                            .growth_growth_percent,
                        "threshold_z_score":
                            self.config
                            .growth_z_score,
                    },
                )
            )

        return (
            AutomaticDetectionResult(
                baseline_ready=True,
                current_observation_count=(
                    metric.observation_count
                ),
                baseline_observation_mean=(
                    baseline.observation_mean
                ),
                baseline_sample_count=(
                    baseline.sample_count
                ),
                signals=tuple(
                    detected
                ),
            )
        )

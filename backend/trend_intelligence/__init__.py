"""
Trend Intelligence.

Motor transversal:

Domain
→ Source
→ Observation
→ Topic
→ Signal
→ Trend
→ Evidence.
"""

from backend.trend_intelligence.models import (
    ObservationDomain,
    ObservationTopic,
    TopicDomain,
    Trend,
    TrendDomain,
    TrendEvidence,
    TrendObservation,
    TrendSignal,
    TrendSource,
    TrendTemporalBaseline,
    TrendTemporalMetric,
    TrendTopic,
    TrendTopicAlias,
)

__all__ = [
    "ObservationDomain",
    "ObservationTopic",
    "TopicDomain",
    "Trend",
    "TrendDomain",
    "TrendEvidence",
    "TrendObservation",
    "TrendSignal",
    "TrendSource",
    "TrendTemporalBaseline",
    "TrendTemporalMetric",
    "TrendTopic",
    "TrendTopicAlias",
]

from backend.trend_intelligence.detection import (
    AutomaticDetectionResult,
    AutomaticSignalDetectionConfig,
    AutomaticVolumeGrowthDetector,
    DetectedTrendSignal,
)

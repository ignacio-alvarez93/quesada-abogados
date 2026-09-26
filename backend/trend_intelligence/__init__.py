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
    TrendAggregateSignal,
    TrendDomain,
    TrendEvidence,
    TrendObservation,
    TrendSignal,
    TrendSource,
    TrendSnapshot,
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
    "TrendAggregateSignal",
    "TrendDomain",
    "TrendEvidence",
    "TrendObservation",
    "TrendSignal",
    "TrendSource",
    "TrendSnapshot",
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

from backend.trend_intelligence.advanced_detection import (
    AdvancedDetectedSignal,
    AdvancedDetectionConfig,
    AdvancedDetectionResult,
    CrossSourceRecurrenceDetector,
)
from backend.trend_intelligence.automatic_signals import (
    AutomaticSignalOrchestrationResult,
    TrendAutomaticSignalService,
)

from backend.trend_intelligence.aggregate_scoring import (
    AggregateScoreResult,
    AggregateTrendScorer,
)

from backend.trend_intelligence.trend_history import (
    BacktestWindow,
    TrendBacktestResult,
    TrendBacktestingService,
    TrendSnapshotService,
)

from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
)

from backend.trend_intelligence.pipeline import (
    ProcessedTrendWindow,
    TrendAutomaticPipelineService,
    TrendReplayResult,
)

from backend.trend_intelligence.regression import (
    RegressionGateResult,
    TrendRegressionGateService,
)

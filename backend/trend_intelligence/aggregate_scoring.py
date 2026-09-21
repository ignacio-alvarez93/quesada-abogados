from dataclasses import dataclass

from backend.trend_intelligence.models import (
    TREND_DECLINING,
    TREND_DORMANT,
    TREND_EMERGING,
    TREND_HOT,
    TREND_RISING,
    TREND_STABLE,
)


DEFAULT_AGGREGATE_SIGNAL_WEIGHTS = {
    "MENTION": 0.50,
    "QUESTION": 0.80,
    "HIGH_ENGAGEMENT": 1.10,
    "GROWTH": 1.20,
    "RECURRENCE": 0.90,
    "NEW_TOPIC": 0.70,
    "CROSS_SOURCE": 1.15,
    "VOLUME_SPIKE": 1.25,
    "SEARCH_GROWTH": 1.20,
    "SENTIMENT_SHIFT": 0.85,
}


@dataclass(
    frozen=True,
    slots=True,
)
class AggregateScoreResult:
    score: float
    velocity: float
    status: str

    signal_count: int
    signal_type_count: int

    weighted_signal_score: float
    diversity_bonus: float


class AggregateTrendScorer:
    def __init__(
        self,
        *,
        signal_weights=None,
    ):
        self.signal_weights = dict(
            signal_weights
            or DEFAULT_AGGREGATE_SIGNAL_WEIGHTS
        )

    @staticmethod
    def classify_status(
        *,
        score,
        velocity,
        signal_count,
    ):
        if signal_count <= 0:
            return TREND_DORMANT

        if (
            velocity <= -15.0
            and score >= 20.0
        ):
            return TREND_DECLINING

        if score >= 80.0:
            return TREND_HOT

        if score >= 60.0:
            return TREND_RISING

        if score >= 35.0:
            return TREND_EMERGING

        if score >= 20.0:
            return TREND_STABLE

        return TREND_DORMANT

    def calculate(
        self,
        signals,
        *,
        prior_score=None,
    ):
        signals = list(
            signals
        )

        if not signals:
            score = 0.0

            velocity = (
                round(
                    score
                    - float(
                        prior_score
                    ),
                    4,
                )
                if prior_score
                is not None
                else 0.0
            )

            return AggregateScoreResult(
                score=0.0,
                velocity=velocity,
                status=TREND_DORMANT,
                signal_count=0,
                signal_type_count=0,
                weighted_signal_score=0.0,
                diversity_bonus=0.0,
            )

        weighted_total = 0.0
        weight_total = 0.0

        signal_types = set()

        for signal in signals:
            weight = float(
                self.signal_weights.get(
                    signal.signal_type,
                    1.0,
                )
            )

            strength = max(
                0.0,
                min(
                    100.0,
                    float(
                        signal.strength
                    ),
                ),
            )

            confidence = max(
                0.0,
                min(
                    1.0,
                    float(
                        signal.confidence
                    ),
                ),
            )

            weighted_total += (
                strength
                * confidence
                * weight
            )

            weight_total += weight

            signal_types.add(
                signal.signal_type
            )

        weighted_score = (
            weighted_total
            / weight_total
            if weight_total > 0.0
            else 0.0
        )

        diversity_bonus = min(
            10.0,
            max(
                0,
                len(
                    signal_types
                )
                - 1,
            )
            * 2.5,
        )

        score = round(
            min(
                100.0,
                weighted_score
                + diversity_bonus,
            ),
            4,
        )

        velocity = (
            round(
                score
                - float(
                    prior_score
                ),
                4,
            )
            if prior_score
            is not None
            else 0.0
        )

        status = (
            self.classify_status(
                score=score,
                velocity=velocity,
                signal_count=len(
                    signals
                ),
            )
        )

        return AggregateScoreResult(
            score=score,
            velocity=velocity,
            status=status,
            signal_count=len(
                signals
            ),
            signal_type_count=len(
                signal_types
            ),
            weighted_signal_score=round(
                weighted_score,
                4,
            ),
            diversity_bonus=round(
                diversity_bonus,
                4,
            ),
        )

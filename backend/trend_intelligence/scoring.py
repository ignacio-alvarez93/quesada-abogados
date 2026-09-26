"""
Scoring determinista V1.

Provider-neutral.
Domain-neutral.
Explicable.
Reproducible.
Sustituible en futuras versiones.
"""

from dataclasses import dataclass

from backend.trend_intelligence.models import (
    SIGNAL_CROSS_SOURCE,
    SIGNAL_GROWTH,
    SIGNAL_HIGH_ENGAGEMENT,
    SIGNAL_MENTION,
    SIGNAL_NEW_TOPIC,
    SIGNAL_QUESTION,
    SIGNAL_RECURRENCE,
    SIGNAL_SEARCH_GROWTH,
    SIGNAL_SENTIMENT_SHIFT,
    SIGNAL_VOLUME_SPIKE,
    TREND_DECLINING,
    TREND_DORMANT,
    TREND_EMERGING,
    TREND_HOT,
    TREND_RISING,
    TREND_STABLE,
    TrendSignal,
)


SIGNAL_WEIGHTS = {
    SIGNAL_MENTION: 0.50,
    SIGNAL_QUESTION: 0.80,
    SIGNAL_HIGH_ENGAGEMENT: 1.10,
    SIGNAL_GROWTH: 1.20,
    SIGNAL_RECURRENCE: 0.90,
    SIGNAL_NEW_TOPIC: 0.70,
    SIGNAL_CROSS_SOURCE: 1.15,
    SIGNAL_VOLUME_SPIKE: 1.25,
    SIGNAL_SEARCH_GROWTH: 1.20,
    SIGNAL_SENTIMENT_SHIFT: 0.85,
}


@dataclass(frozen=True, slots=True)
class TrendScore:
    score: float
    status: str
    velocity: float


def signal_weight(
    signal_type: str,
) -> float:
    return float(
        SIGNAL_WEIGHTS.get(
            str(
                signal_type
                or ""
            )
            .strip()
            .upper(),
            0.50,
        )
    )


def calculate_score(
    signals: list[TrendSignal],
) -> float:
    if not signals:
        return 0.0

    weighted_sum = 0.0
    maximum_sum = 0.0

    for signal in signals:
        weight = signal_weight(
            signal.signal_type
        )

        strength = min(
            100.0,
            max(
                0.0,
                float(
                    signal.strength
                ),
            ),
        )

        confidence = min(
            1.0,
            max(
                0.0,
                float(
                    signal.confidence
                ),
            ),
        )

        weighted_sum += (
            strength
            * confidence
            * weight
        )

        maximum_sum += (
            100.0
            * weight
        )

    if maximum_sum <= 0:
        return 0.0

    base_score = (
        weighted_sum
        / maximum_sum
        * 100.0
    )

    volume_bonus = min(
        15.0,
        max(
            0,
            len(signals) - 1,
        )
        * 2.0,
    )

    return round(
        min(
            100.0,
            base_score
            + volume_bonus,
        ),
        2,
    )


def calculate_velocity(
    current_score: float,
    previous_score: float | None,
) -> float:
    if previous_score is None:
        return 0.0

    return round(
        float(
            current_score
        )
        - float(
            previous_score
        ),
        2,
    )


def derive_status(
    *,
    score: float,
    velocity: float,
    signal_count: int,
) -> str:
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


def score_trend(
    signals: list[TrendSignal],
    *,
    previous_score: float | None = None,
) -> TrendScore:
    score = calculate_score(
        signals
    )

    velocity = calculate_velocity(
        score,
        previous_score,
    )

    status = derive_status(
        score=score,
        velocity=velocity,
        signal_count=len(
            signals
        ),
    )

    return TrendScore(
        score=score,
        status=status,
        velocity=velocity,
    )

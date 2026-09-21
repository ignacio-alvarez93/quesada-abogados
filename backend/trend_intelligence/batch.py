"""
Batch recalculation para Trend Intelligence.

No descubre tendencias por sí mismo.

Recalcula de forma determinista todos los topics
registrados en un dominio para una ventana temporal.
"""

from dataclasses import dataclass


@dataclass(
    frozen=True,
    slots=True,
)
class TrendBatchItem:
    topic_key: str
    trend_id: int
    status: str
    score: float
    velocity: float
    observation_count: int
    source_count: int
    signal_count: int


@dataclass(
    frozen=True,
    slots=True,
)
class TrendBatchResult:
    domain_code: str
    window_start: str
    window_end: str

    topic_count: int
    calculated_count: int

    items: tuple[
        TrendBatchItem,
        ...,
    ]


class TrendBatchService:
    def __init__(
        self,
        trend_service,
    ):
        self.trend_service = (
            trend_service
        )

    def recalculate_domain(
        self,
        domain_code,
        *,
        window_start,
        window_end,
        country="",
        language="",
        include_empty=True,
    ):
        topics = (
            self.trend_service
            .list_domain_topics(
                domain_code,
                active_only=True,
            )
        )

        items = []

        for topic in topics:
            result = (
                self.trend_service
                .recalculate_trend(
                    domain_code=(
                        domain_code
                    ),
                    topic_key=(
                        topic.topic_key
                    ),
                    window_start=(
                        window_start
                    ),
                    window_end=(
                        window_end
                    ),
                    country=country,
                    language=language,
                    metadata={
                        "calculation_mode":
                            "DOMAIN_BATCH",
                    },
                )
            )

            trend = result[
                "trend"
            ]

            if (
                not include_empty
                and trend.signal_count == 0
            ):
                continue

            items.append(
                TrendBatchItem(
                    topic_key=(
                        topic.topic_key
                    ),
                    trend_id=(
                        trend.id
                    ),
                    status=(
                        trend.status
                    ),
                    score=(
                        trend.score
                    ),
                    velocity=(
                        trend.velocity
                    ),
                    observation_count=(
                        trend
                        .observation_count
                    ),
                    source_count=(
                        trend
                        .source_count
                    ),
                    signal_count=(
                        trend
                        .signal_count
                    ),
                )
            )

        return TrendBatchResult(
            domain_code=str(
                domain_code
            ).strip().upper(),
            window_start=str(
                window_start
            ),
            window_end=str(
                window_end
            ),
            topic_count=len(
                topics
            ),
            calculated_count=len(
                items
            ),
            items=tuple(
                items
            ),
        )

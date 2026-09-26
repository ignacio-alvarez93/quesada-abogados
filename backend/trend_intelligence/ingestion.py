"""
Pipeline de ingestión provider-neutral.

Adapter
    ↓
TrendObservationInput
    ↓
record_observation
    ↓
dedupe
    ↓
optional domain assignment

La clasificación temática y el scoring
permanecen desacoplados.
"""

from dataclasses import dataclass

from backend.trend_intelligence.sources.base import (
    TrendObservationInput,
)


@dataclass(
    frozen=True,
    slots=True,
)
class TrendIngestionReport:
    source_code: str

    total: int
    created: int
    duplicates: int

    observation_ids: tuple[
        int,
        ...,
    ]


class TrendIngestionService:
    def __init__(
        self,
        trend_service,
    ):
        self.trend_service = (
            trend_service
        )

    def ingest(
        self,
        adapter,
        *,
        domain_code=None,
        domain_confidence=1.0,
        domain_detection_method="SOURCE",
    ):
        source_code = str(
            adapter.source_code
        ).strip()

        if not source_code:
            raise ValueError(
                "Adapter sin source_code"
            )

        total = 0
        created = 0
        duplicates = 0
        observation_ids = []

        for candidate in (
            adapter.collect()
        ):
            if not isinstance(
                candidate,
                TrendObservationInput,
            ):
                raise TypeError(
                    (
                        "El adapter debe devolver "
                        "TrendObservationInput"
                    )
                )

            total += 1

            observation, was_created = (
                self.trend_service
                .record_observation(
                    source_code=(
                        source_code
                    ),
                    observation_type=(
                        candidate
                        .observation_type
                    ),
                    external_id=(
                        candidate
                        .external_id
                    ),
                    url=(
                        candidate.url
                    ),
                    title=(
                        candidate.title
                    ),
                    body_text=(
                        candidate.body_text
                    ),
                    author=(
                        candidate.author
                    ),
                    published_at=(
                        candidate
                        .published_at
                    ),
                    observed_at=(
                        candidate
                        .observed_at
                    ),
                    language=(
                        candidate.language
                    ),
                    country=(
                        candidate.country
                    ),
                    metadata=(
                        candidate.metadata
                    ),
                    content_hash=(
                        candidate
                        .content_hash
                    ),
                )
            )

            observation_ids.append(
                observation.id
            )

            if was_created:
                created += 1
            else:
                duplicates += 1

            if domain_code:
                (
                    self.trend_service
                    .assign_observation_domain(
                        observation.id,
                        domain_code,
                        confidence=(
                            domain_confidence
                        ),
                        detection_method=(
                            domain_detection_method
                        ),
                    )
                )

        return TrendIngestionReport(
            source_code=source_code,
            total=total,
            created=created,
            duplicates=duplicates,
            observation_ids=tuple(
                observation_ids
            ),
        )

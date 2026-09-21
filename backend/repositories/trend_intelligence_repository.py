"""
Contrato de persistencia de Trend Intelligence.

El core no depende de SQLite ni PostgreSQL.
"""

from typing import Protocol

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


class TrendIntelligenceRepository(
    Protocol
):
    def ensure_schema(self) -> None:
        ...

    def save_domain(
        self,
        domain: TrendDomain,
    ) -> TrendDomain:
        ...

    def get_domain_by_code(
        self,
        code: str,
    ) -> TrendDomain | None:
        ...

    def list_domains(
        self,
        *,
        active_only: bool = False,
    ) -> list[TrendDomain]:
        ...

    def save_source(
        self,
        source: TrendSource,
    ) -> TrendSource:
        ...

    def get_source_by_code(
        self,
        code: str,
    ) -> TrendSource | None:
        ...

    def save_topic(
        self,
        topic: TrendTopic,
    ) -> TrendTopic:
        ...

    def get_topic_by_key(
        self,
        topic_key: str,
    ) -> TrendTopic | None:
        ...

    def link_topic_domain(
        self,
        link: TopicDomain,
    ) -> TopicDomain:
        ...

    def list_topic_domains(
        self,
        topic_id: int,
    ) -> list[TopicDomain]:
        ...

    def list_topics_for_domain(
        self,
        domain_id: int,
        *,
        active_only: bool = True,
    ) -> list[TrendTopic]:
        ...

    def save_topic_alias(
        self,
        alias: TrendTopicAlias,
    ) -> TrendTopicAlias:
        ...

    def resolve_topic_alias(
        self,
        alias_key: str,
        *,
        language: str = "",
        country: str = "",
    ) -> TrendTopic | None:
        ...

    def list_topic_aliases(
        self,
        topic_id: int,
        *,
        active_only: bool = True,
    ) -> list[TrendTopicAlias]:
        ...

    def link_observation_domain(
        self,
        link: ObservationDomain,
    ) -> ObservationDomain:
        ...

    def list_observation_domains(
        self,
        observation_id: int,
    ) -> list[ObservationDomain]:
        ...

    def get_or_create_observation_with_status(
        self,
        observation: TrendObservation,
    ) -> tuple[
        TrendObservation,
        bool,
    ]:
        ...

    def get_observation(
        self,
        observation_id: int,
    ) -> TrendObservation | None:
        ...

    def link_observation_topic(
        self,
        link: ObservationTopic,
    ) -> ObservationTopic:
        ...

    def save_signal_with_status(
        self,
        signal: TrendSignal,
    ) -> tuple[
        TrendSignal,
        bool,
    ]:
        ...

    def list_signals_for_topic(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str,
        window_end: str,
    ) -> list[TrendSignal]:
        ...

    def get_topic_window_stats(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str,
        window_end: str,
    ) -> dict:
        ...

    def get_temporal_window_stats(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str,
        window_end: str,
        country: str = "",
        language: str = "",
    ) -> dict:
        ...

    def get_temporal_metric(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str,
        window_end: str,
        country: str = "",
        language: str = "",
    ) -> TrendTemporalMetric | None:
        ...

    def list_temporal_metrics(
        self,
        domain_id: int,
        topic_id: int,
        *,
        country: str = "",
        language: str = "",
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[TrendTemporalMetric]:
        ...

    def save_temporal_metric(
        self,
        metric: TrendTemporalMetric,
    ) -> TrendTemporalMetric:
        ...

    def list_temporal_metrics_before(
        self,
        domain_id: int,
        topic_id: int,
        *,
        before_window_start: str,
        country: str = "",
        language: str = "",
        limit: int = 7,
    ) -> list[TrendTemporalMetric]:
        ...

    def save_temporal_baseline(
        self,
        baseline: TrendTemporalBaseline,
    ) -> TrendTemporalBaseline:
        ...

    def get_temporal_baseline(
        self,
        domain_id: int,
        topic_id: int,
        *,
        reference_window_start: str,
        reference_window_end: str,
        country: str = "",
        language: str = "",
        lookback_windows: int | None = None,
    ) -> TrendTemporalBaseline | None:
        ...

    def get_latest_temporal_baseline(
        self,
        domain_id: int,
        topic_id: int,
        *,
        country: str = "",
        language: str = "",
    ) -> TrendTemporalBaseline | None:
        ...

    def save_aggregate_signal(
        self,
        signal: TrendAggregateSignal,
    ) -> TrendAggregateSignal:
        ...

    def list_aggregate_signals(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str | None = None,
        window_end: str | None = None,
        country: str = "",
        language: str = "",
    ) -> list[TrendAggregateSignal]:
        ...

    def delete_aggregate_signals_for_detector(
        self,
        domain_id: int,
        topic_id: int,
        *,
        window_start: str,
        window_end: str,
        country: str,
        language: str,
        detector_key: str,
        detector_version: str,
    ) -> None:
        ...

    def save_trend_snapshot(
        self,
        snapshot: TrendSnapshot,
    ) -> TrendSnapshot:
        ...

    def list_trend_snapshots(
        self,
        domain_id: int,
        topic_id: int,
        *,
        country: str = "",
        language: str = "",
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[TrendSnapshot]:
        ...

    def get_latest_trend_snapshot_before(
        self,
        domain_id: int,
        topic_id: int,
        *,
        before_window_start: str,
        country: str = "",
        language: str = "",
    ) -> TrendSnapshot | None:
        ...

    def get_latest_trend_before(
        self,
        domain_id: int,
        topic_id: int,
        *,
        country: str,
        language: str,
        before_window_start: str,
    ) -> Trend | None:
        ...

    def save_trend_with_evidence(
        self,
        trend: Trend,
        evidence: list[TrendEvidence],
    ) -> Trend:
        ...

    def get_trend(
        self,
        trend_id: int,
    ) -> Trend | None:
        ...

    def list_trends(
        self,
        *,
        domain_id: int,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Trend]:
        ...

    def list_trend_evidence(
        self,
        trend_id: int,
    ) -> list[TrendEvidence]:
        ...

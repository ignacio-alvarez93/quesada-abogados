"""
Trend Intelligence · cross-source explainability V1.

Builds deterministic, read-only explanation evidence for an already
scored ``Trend`` or ``TrendSnapshot``: which sources/signals
contributed, how diverse those sources are, which provenance produced
them, which contributing sources currently look degraded, and what the
already-persisted scoring/recurrence history shows.

This module is not a second scoring engine: it never recomputes
score, status or velocity. It only reads data already produced by the
existing scoring (scoring.py / aggregate_scoring.py), temporal
(temporal.py) and acquisition (acquisition/health.py,
acquisition/provenance.py) infrastructure, and groups/counts it. It
never writes to persistence.

Ordering is always deterministic (sorted by stable keys) so repeated
calls over unchanged data produce identical output.

Domain-neutral and provider-neutral: no vertical-specific assumptions.
"""

from dataclasses import dataclass

from backend.trend_intelligence.acquisition.health import (
    HEALTH_FAILED,
    HEALTH_STALE,
    build_source_freshness_report,
)
from backend.trend_intelligence.acquisition.provenance import PROVENANCE_KEY
from backend.trend_intelligence.models import time_key


@dataclass(frozen=True, slots=True)
class SignalTypeContribution:
    signal_type: str
    signal_count: int
    source_count: int


@dataclass(frozen=True, slots=True)
class SourceContribution:
    source_id: int
    source_code: str
    source_name: str
    provider: str | None
    collection_mode: str

    observation_count: int
    signal_count: int
    signal_types: tuple[str, ...]

    first_seen_at: str | None
    last_seen_at: str | None

    health_state: str
    consecutive_failures: int
    last_failure_reason: str | None


@dataclass(frozen=True, slots=True)
class ProvenanceReference:
    collector_key: str
    collector_version: str
    provider: str
    source_identity: str
    observation_count: int


@dataclass(frozen=True, slots=True)
class RecurrenceEntry:
    window_start: str
    window_end: str
    score: float
    velocity: float
    status: str


@dataclass(frozen=True, slots=True)
class TrendExplanation:
    domain_id: int
    topic_id: int

    window_start: str
    window_end: str
    country: str
    language: str

    status: str
    score: float
    velocity: float

    signal_count: int
    source_count: int

    contributing_sources: tuple[SourceContribution, ...]
    signal_type_counts: tuple[SignalTypeContribution, ...]
    scoring_components: tuple

    provenance: tuple[ProvenanceReference, ...]
    # Contributing sources whose current collector health is STALE/FAILED:
    # their presence here does not already prove missing data, only that
    # this window's coverage from them may be incomplete going forward.
    partial_sources: tuple[str, ...]

    recurrence: tuple[RecurrenceEntry, ...]
    previous_score: float | None
    previous_velocity: float | None
    previous_status: str | None


def _acquisition_provenance(metadata):
    if not isinstance(metadata, dict):
        return None
    provenance = metadata.get(PROVENANCE_KEY)
    if not isinstance(provenance, dict):
        return None
    return provenance


def _build_contributions(service, raw_signals):
    """Group already-persisted raw signals by their physical source.

    Reads only: the observations/sources already reachable from
    ``raw_signals`` (itself produced by the existing
    ``list_signals_for_topic`` query for one domain/topic/window/
    country/language scope). Grouping and counting here is bookkeeping,
    never scoring: no weight, strength, confidence or status is derived.
    """
    repository = service.repository

    observation_cache = {}
    source_cache = {}

    by_source = {}
    by_signal_type = {}
    by_provenance = {}

    for signal in raw_signals:
        observation = observation_cache.get(signal.observation_id)
        if observation is None:
            observation = repository.get_observation(signal.observation_id)
            observation_cache[signal.observation_id] = observation
        if observation is None:
            continue

        source = source_cache.get(observation.source_id)
        if source is None:
            source = repository.get_source_by_id(observation.source_id)
            source_cache[observation.source_id] = source
        if source is None:
            continue

        bucket = by_source.setdefault(
            source.id,
            {
                "source": source,
                "observation_ids": set(),
                "signal_count": 0,
                "signal_types": set(),
                "first_seen_at": signal.detected_at,
                "last_seen_at": signal.detected_at,
            },
        )
        bucket["observation_ids"].add(observation.id)
        bucket["signal_count"] += 1
        bucket["signal_types"].add(signal.signal_type)
        if time_key(signal.detected_at) < time_key(bucket["first_seen_at"]):
            bucket["first_seen_at"] = signal.detected_at
        if time_key(signal.detected_at) > time_key(bucket["last_seen_at"]):
            bucket["last_seen_at"] = signal.detected_at

        type_bucket = by_signal_type.setdefault(
            signal.signal_type,
            {"count": 0, "source_ids": set()},
        )
        type_bucket["count"] += 1
        type_bucket["source_ids"].add(source.id)

        provenance = _acquisition_provenance(observation.metadata)
        if provenance is not None:
            key = (
                str(provenance.get("collector_key", "")),
                str(provenance.get("collector_version", "")),
                str(provenance.get("provider", "")),
                str(provenance.get("source_identity", "")),
            )
            by_provenance.setdefault(key, set()).add(observation.id)

    contributions = []
    for bucket in by_source.values():
        source = bucket["source"]
        report = build_source_freshness_report(service, source.code)
        contributions.append(
            SourceContribution(
                source_id=source.id,
                source_code=source.code,
                source_name=source.name,
                provider=source.provider,
                collection_mode=source.collection_mode,
                observation_count=len(bucket["observation_ids"]),
                signal_count=bucket["signal_count"],
                signal_types=tuple(sorted(bucket["signal_types"])),
                first_seen_at=bucket["first_seen_at"],
                last_seen_at=bucket["last_seen_at"],
                health_state=report.health_state,
                consecutive_failures=report.consecutive_failures,
                last_failure_reason=report.last_failure_reason,
            )
        )

    contributions.sort(key=lambda item: (item.source_code, item.source_id))

    signal_type_counts = tuple(
        SignalTypeContribution(
            signal_type=signal_type,
            signal_count=data["count"],
            source_count=len(data["source_ids"]),
        )
        for signal_type, data in sorted(by_signal_type.items())
    )

    provenance_refs = tuple(
        ProvenanceReference(
            collector_key=key[0],
            collector_version=key[1],
            provider=key[2],
            source_identity=key[3],
            observation_count=len(observation_ids),
        )
        for key, observation_ids in sorted(by_provenance.items())
    )

    partial_sources = tuple(
        sorted(
            item.source_code
            for item in contributions
            if item.health_state in (HEALTH_FAILED, HEALTH_STALE)
        )
    )

    return (
        tuple(contributions),
        signal_type_counts,
        provenance_refs,
        partial_sources,
    )


def explain_trend(service, trend):
    """Deterministic explanation for an already scored ``Trend``.

    Reuses the exact evidence already persisted by
    ``TrendIntelligenceService.recalculate_trend`` (``ti_trend_evidence``,
    via ``list_trend_evidence``) as the scoring components, and the same
    ``list_signals_for_topic`` query that produced that evidence to
    enumerate contributing sources/provenance. Never recomputes score,
    status or velocity.
    """
    repository = service.repository

    raw_signals = repository.list_signals_for_topic(
        trend.domain_id,
        trend.topic_id,
        window_start=trend.window_start,
        window_end=trend.window_end,
        country=trend.country,
        language=trend.language,
    )

    signal_types_by_id = {signal.id: signal.signal_type for signal in raw_signals}

    evidence = (
        repository.list_trend_evidence(trend.id) if trend.id is not None else ()
    )

    scoring_components = tuple(
        {
            "signal_id": item.signal_id,
            "signal_type": signal_types_by_id.get(item.signal_id, ""),
            "weight": item.weight,
            "reason": item.reason,
        }
        for item in evidence
    )

    previous = repository.get_latest_trend_before(
        trend.domain_id,
        trend.topic_id,
        country=trend.country,
        language=trend.language,
        before_window_start=trend.window_start,
    )

    contributing_sources, signal_type_counts, provenance, partial_sources = (
        _build_contributions(service, raw_signals)
    )

    recurrence = (
        (
            RecurrenceEntry(
                window_start=previous.window_start,
                window_end=previous.window_end,
                score=previous.score,
                velocity=previous.velocity,
                status=previous.status,
            ),
        )
        if previous is not None
        else ()
    )

    return TrendExplanation(
        domain_id=trend.domain_id,
        topic_id=trend.topic_id,
        window_start=trend.window_start,
        window_end=trend.window_end,
        country=trend.country,
        language=trend.language,
        status=trend.status,
        score=trend.score,
        velocity=trend.velocity,
        signal_count=trend.signal_count,
        source_count=trend.source_count,
        contributing_sources=contributing_sources,
        signal_type_counts=signal_type_counts,
        scoring_components=scoring_components,
        provenance=provenance,
        partial_sources=partial_sources,
        recurrence=recurrence,
        previous_score=previous.score if previous is not None else None,
        previous_velocity=previous.velocity if previous is not None else None,
        previous_status=previous.status if previous is not None else None,
    )


def explain_snapshot(service, snapshot, *, history_limit=5):
    """Deterministic explanation for an already materialized ``TrendSnapshot``.

    Reuses the aggregate-scoring evidence already embedded in
    ``snapshot.metadata`` by ``TrendSnapshotService`` (``components``,
    ``signal_types``, ``signal_weights``, baseline sample count) and the
    same raw-signal query that feeds the temporal metrics behind that
    window (``list_signals_for_topic``) to enumerate contributing
    sources/provenance. Never recomputes score, status or velocity.
    """
    repository = service.repository
    metadata = snapshot.metadata or {}

    raw_signals = repository.list_signals_for_topic(
        snapshot.domain_id,
        snapshot.topic_id,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        country=snapshot.country,
        language=snapshot.language,
    )

    scoring_components = tuple(metadata.get("components") or ())

    previous = repository.get_latest_trend_snapshot_before(
        snapshot.domain_id,
        snapshot.topic_id,
        before_window_start=snapshot.window_start,
        country=snapshot.country,
        language=snapshot.language,
    )

    cutoff = time_key(snapshot.window_start)
    history = sorted(
        (
            item
            for item in repository.list_trend_snapshots(
                snapshot.domain_id,
                snapshot.topic_id,
                country=snapshot.country,
                language=snapshot.language,
                limit=None,
                ascending=True,
            )
            if time_key(item.window_end) <= cutoff
        ),
        key=lambda item: (time_key(item.window_end), time_key(item.window_start)),
    )

    history_limit = max(0, int(history_limit))
    recurrence = tuple(
        RecurrenceEntry(
            window_start=item.window_start,
            window_end=item.window_end,
            score=item.score,
            velocity=item.velocity,
            status=item.status,
        )
        for item in (history[-history_limit:] if history_limit else [])
    )

    contributing_sources, signal_type_counts, provenance, partial_sources = (
        _build_contributions(service, raw_signals)
    )

    return TrendExplanation(
        domain_id=snapshot.domain_id,
        topic_id=snapshot.topic_id,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        country=snapshot.country,
        language=snapshot.language,
        status=snapshot.status,
        score=snapshot.score,
        velocity=snapshot.velocity,
        signal_count=snapshot.aggregate_signal_count,
        source_count=snapshot.source_count,
        contributing_sources=contributing_sources,
        signal_type_counts=signal_type_counts,
        scoring_components=scoring_components,
        provenance=provenance,
        partial_sources=partial_sources,
        recurrence=recurrence,
        previous_score=previous.score if previous is not None else None,
        previous_velocity=previous.velocity if previous is not None else None,
        previous_status=previous.status if previous is not None else None,
    )

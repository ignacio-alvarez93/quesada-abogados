"""Bounded read-only projection of persisted Trend Intelligence snapshots.

Only reuses existing contracts: the selected domain comes from the Instagram
Collector settings port, snapshots from TrendIntelligenceService.
list_domain_snapshots and explanations from explain_snapshot. It never
scores, creates storage, writes, runs migrations or touches the browser.
"""
from dataclasses import dataclass
import json

# Same key as instagram_collector_configuration_service.SETTINGS_KEY; that module
# is not imported because it pulls the SeleniumBase browser stack.
SETTINGS_KEY = "IT_INSTAGRAM_COLLECTOR_V1"

STATUS_NO_STORE = "NO_STORE"
STATUS_SCHEMA_INCOMPLETE = "SCHEMA_INCOMPLETE"
STATUS_NO_DOMAIN = "NO_DOMAIN"
STATUS_EMPTY = "EMPTY"
STATUS_READY = "READY"
STATUS_ERROR = "ERROR"

REASON_NOT_CONFIGURED = "NOT_CONFIGURED"
REASON_NOT_REGISTERED = "NOT_REGISTERED"
ERROR_INVALID_SETTINGS = "INVALID_SETTINGS"
ERROR_READ_FAILED = "READ_FAILED"

EXPLANATION_READY = "READY"
EXPLANATION_NOT_REQUESTED = "NOT_REQUESTED"
EXPLANATION_FAILED = "FAILED"

MAX_SNAPSHOTS = 20
MAX_EXPLANATIONS = 3
MAX_HISTORY = 3

# Tables read by list_domain_topics, list_domain_snapshots and explain_snapshot.
REQUIRED_TABLES = (
    "ti_collector_runs",
    "ti_domains",
    "ti_observation_domains",
    "ti_observations",
    "ti_signals",
    "ti_sources",
    "ti_topic_domains",
    "ti_topics",
    "ti_trend_snapshots",
)


@dataclass(frozen=True)
class TrendDashboardRow:
    snapshot: object
    topic: object | None
    # Persisted baseline mean only when the snapshot recorded a baseline;
    # TrendSnapshot defaults it to 0.0 otherwise, which is not a measurement.
    baseline_mean: float | None
    baseline_samples: int | None
    explanation: object | None
    explanation_status: str


@dataclass(frozen=True)
class TrendDashboardState:
    status: str
    reason: str | None = None
    domain_code: str | None = None
    domain_name: str | None = None
    rows: tuple = ()
    missing_tables: tuple = ()
    partial_sources: tuple = ()


def _bounded(value, ceiling):
    return max(0, min(ceiling, int(value)))


def _baseline(snapshot):
    metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else {}
    if metadata.get("lookback_windows") is None:
        return None, None
    samples = metadata.get("baseline_sample_count")
    return snapshot.baseline_observation_mean, samples if type(samples) is int else None


class TrendIntelligenceDashboardService:
    def __init__(self, *, settings, trends, snapshot_limit=MAX_SNAPSHOTS,
                 explanation_limit=MAX_EXPLANATIONS, history_limit=MAX_HISTORY,
                 store_unavailable_errors=()):
        self.settings = settings
        self.trends = trends
        # Provider-neutral boundary: the composition root supplies the exception
        # classes its store raises when absent; anything else stays ERROR.
        self.store_unavailable_errors = tuple(store_unavailable_errors)
        self.snapshot_limit = max(1, _bounded(snapshot_limit, MAX_SNAPSHOTS))
        self.explanation_limit = _bounded(explanation_limit, MAX_EXPLANATIONS)
        self.history_limit = _bounded(history_limit, MAX_HISTORY)

    def _domain_code(self):
        raw = self.settings.get_config(SETTINGS_KEY)
        if raw is None:
            return None
        settings = json.loads(raw)
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        domain = settings.get("domain_code")
        if domain is None:
            return None
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("domain_code must be a code or null")
        return domain.strip()

    def state(self):
        try:
            return self._state()
        except self.store_unavailable_errors:
            return TrendDashboardState(STATUS_NO_STORE)
        except Exception:
            return TrendDashboardState(STATUS_ERROR, reason=ERROR_READ_FAILED)

    def _state(self):
        repository = self.trends.repository
        missing = repository.missing_tables(REQUIRED_TABLES)
        if missing:
            return TrendDashboardState(STATUS_SCHEMA_INCOMPLETE, missing_tables=missing)

        try:
            code = self._domain_code()
        except (ValueError, TypeError):
            return TrendDashboardState(STATUS_ERROR, reason=ERROR_INVALID_SETTINGS)
        if code is None:
            return TrendDashboardState(STATUS_NO_DOMAIN, reason=REASON_NOT_CONFIGURED)

        domain = repository.get_domain_by_code(code)
        if domain is None:
            return TrendDashboardState(STATUS_NO_DOMAIN, reason=REASON_NOT_REGISTERED,
                                       domain_code=code)

        snapshots = self.trends.list_domain_snapshots(domain.code, limit=self.snapshot_limit)
        if not snapshots:
            return TrendDashboardState(STATUS_EMPTY, domain_code=domain.code,
                                       domain_name=domain.name)

        topics = {
            topic.id: topic
            for topic in self.trends.list_domain_topics(domain.code, active_only=False)
        }
        rows, partial = [], set()
        # Snapshots arrive ranked by the existing query (score DESC); only the
        # top explanation_limit are explained to keep per-row reads bounded.
        for index, snapshot in enumerate(snapshots[:self.snapshot_limit]):
            explanation, explanation_status = None, EXPLANATION_NOT_REQUESTED
            if index < self.explanation_limit:
                try:
                    explanation = self.trends.explain_snapshot(
                        snapshot, history_limit=self.history_limit,
                    )
                    explanation_status = EXPLANATION_READY
                    partial.update(explanation.partial_sources)
                except self.store_unavailable_errors:
                    raise
                except Exception:
                    explanation_status = EXPLANATION_FAILED
            baseline_mean, baseline_samples = _baseline(snapshot)
            rows.append(TrendDashboardRow(
                snapshot=snapshot,
                topic=topics.get(snapshot.topic_id),
                baseline_mean=baseline_mean,
                baseline_samples=baseline_samples,
                explanation=explanation,
                explanation_status=explanation_status,
            ))
        return TrendDashboardState(
            STATUS_READY,
            domain_code=domain.code,
            domain_name=domain.name,
            rows=tuple(rows),
            partial_sources=tuple(sorted(partial)),
        )


def create_crm_trend_dashboard():
    """Compose lazily: constructors perform no reads; every read is mode=ro."""
    from backend.repositories.sqlite_trend_intelligence_repository import (
        ReadOnlyStoreUnavailable, SQLiteTrendIntelligenceReadOnlyLookup,
        SQLiteTrendIntelligenceRepository,
    )
    from backend.services.config_service import DB_PATH
    from backend.trend_intelligence.service import TrendIntelligenceService

    return TrendIntelligenceDashboardService(
        settings=SQLiteTrendIntelligenceReadOnlyLookup(DB_PATH),
        trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(DB_PATH, readonly=True)),
        store_unavailable_errors=(ReadOnlyStoreUnavailable,),
    )

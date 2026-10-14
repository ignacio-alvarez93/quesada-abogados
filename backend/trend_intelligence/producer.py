"""
Trend Intelligence · productor incremental de tendencias (TI-4C.1).

Invocable, sin disparador: ni scheduler, ni worker, ni hook del Collector,
ni integración en app/main. Dos fases independientes:

1. classify_pending: observaciones YA vinculadas a un dominio -> topic por
   coincidencia exacta de metadata.hashtags con topic/alias activos del
   propio dominio (resolvedor existente). Solo enlace de topic: el vínculo
   de dominio y su detection_method (p.ej. SOURCE) no se reescriben.
2. process_windows: ventanas diarias UTC completas, una a una, mediante
   TrendAutomaticPipelineService.process_window (BEGIN IMMEDIATE existente).
   Los snapshots resultantes son los persistidos por el motor existente.

Repositorio-agnóstico: no abre la base en el constructor ni contiene SQL.
La única composición concreta es create_trend_producer, perezosa y
existing-only (SQLite URI mode=rw, nunca crea el fichero ni aplica DDL).
"""

from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from backend.trend_intelligence.service import (
    _normalize_key,
)


STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_NO_STORE = "NO_STORE"
STATUS_SCHEMA_INCOMPLETE = "SCHEMA_INCOMPLETE"
STATUS_NO_DOMAIN = "NO_DOMAIN"
STATUS_UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"
STATUS_DOMAIN_INACTIVE = "DOMAIN_INACTIVE"
STATUS_INVALID_TOPIC = "INVALID_TOPIC"

OUTCOME_CLASSIFIED = "CLASSIFIED"
OUTCOME_ALREADY_CLASSIFIED = "ALREADY_CLASSIFIED"
OUTCOME_UNMATCHED = "UNMATCHED"
OUTCOME_AMBIGUOUS = "AMBIGUOUS"

WINDOW_OK = "OK"
WINDOW_FAILED = "FAILED"
WINDOW_NOT_ATTEMPTED = "NOT_ATTEMPTED"
WINDOW_SKIPPED_NO_DATA = "SKIPPED_NO_DATA"

DETECTION_METHOD = "HASHTAG_EXACT"

DEFAULT_CLASSIFY_LIMIT = 100
MAX_CLASSIFY_LIMIT = 200

LOOKBACK_WINDOWS = 7
WINDOW_DAYS = 1
DEFAULT_MAX_WINDOWS = 28
MAX_WINDOWS_HARD_CAP = 28

# Tables read or written by both phases (incl. the reused pipeline engines).
REQUIRED_TABLES = (
    "ti_aggregate_signals",
    "ti_domains",
    "ti_observation_domains",
    "ti_observation_topics",
    "ti_observations",
    "ti_signals",
    "ti_sources",
    "ti_temporal_baselines",
    "ti_temporal_metrics",
    "ti_topic_aliases",
    "ti_topic_domains",
    "ti_topics",
    "ti_trend_snapshots",
)


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    observation_id: int
    outcome: str
    topic_key: str | None = None


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: str
    domain_code: str | None
    after_id: int
    next_after_id: int
    processed: int = 0
    classified: int = 0
    already_classified: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    exhausted: bool = False
    outcomes: tuple[ObservationOutcome, ...] = ()
    missing_tables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WindowOutcome:
    topic_key: str
    window_start: str
    window_end: str
    status: str
    result: object | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WindowProcessingResult:
    status: str
    domain_code: str | None
    window_from: str
    window_to: str
    lookback_windows: int = LOOKBACK_WINDOWS
    windows: tuple[WindowOutcome, ...] = ()
    ok: int = 0
    failed: int = 0
    not_attempted: int = 0
    skipped: int = 0
    invalid_topics: tuple[str, ...] = ()
    missing_tables: tuple[str, ...] = ()
    signature: tuple = ()


def _plain_int(value, name):
    if type(value) is not int:
        raise ValueError(f"{name} debe ser entero")
    return value


def _utc_midnight(value, name):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError(f"{name} obligatorio")

    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{name} debe ser UTC explícito")

    parsed = parsed.astimezone(timezone.utc)

    if (parsed.hour, parsed.minute, parsed.second, parsed.microsecond) != (0, 0, 0, 0):
        raise ValueError(f"{name} debe estar alineado a 00:00 UTC")

    return parsed


def _hashtags(observation):
    metadata = observation.metadata if isinstance(observation.metadata, dict) else {}
    values = metadata.get("hashtags")

    if not isinstance(values, (list, tuple)):
        return ()

    return tuple(
        value.strip().lstrip("#")
        for value in values
        if isinstance(value, str) and value.strip().lstrip("#")
    )


class TrendProducerService:
    def __init__(
        self,
        *,
        trend_service,
        pipeline,
        store_unavailable_errors=(),
        clock=None,
    ):
        if pipeline.repository is not trend_service.repository:
            raise ValueError("pipeline y trend_service deben compartir repositorio")

        self.trend_service = trend_service
        self.pipeline = pipeline
        self.repository = trend_service.repository
        # Provider-neutral: the composition root supplies the exception
        # classes its store raises when absent (never created).
        self.store_unavailable_errors = tuple(store_unavailable_errors)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _preflight(self, domain_code):
        """(status, domain, missing_tables); never writes nor creates storage."""
        if not isinstance(domain_code, str) or not domain_code.strip():
            return STATUS_NO_DOMAIN, None, ()

        try:
            code = _normalize_key(domain_code)
        except ValueError:
            return STATUS_UNKNOWN_DOMAIN, None, ()

        missing = self.repository.missing_tables(REQUIRED_TABLES)
        if missing:
            return STATUS_SCHEMA_INCOMPLETE, None, tuple(missing)

        domain = self.repository.get_domain_by_code(code)
        if domain is None:
            return STATUS_UNKNOWN_DOMAIN, None, ()

        if not domain.is_active:
            return STATUS_DOMAIN_INACTIVE, domain, ()

        return STATUS_OK, domain, ()

    # ------------------------------------------------------------------
    # Phase 1 · topic classification
    # ------------------------------------------------------------------

    def classify_pending(
        self,
        domain_code,
        *,
        after_id=0,
        limit=DEFAULT_CLASSIFY_LIMIT,
    ):
        after_id = _plain_int(after_id, "after_id")
        limit = _plain_int(limit, "limit")

        if after_id < 0:
            raise ValueError("after_id debe ser >= 0")

        if not 1 <= limit <= MAX_CLASSIFY_LIMIT:
            raise ValueError(f"limit debe estar entre 1 y {MAX_CLASSIFY_LIMIT}")

        counts = dict(processed=0, classified=0, already_classified=0, unmatched=0, ambiguous=0)
        outcomes = []
        next_after_id = after_id
        domain = None

        try:
            status, domain, missing = self._preflight(domain_code)

            if status != STATUS_OK:
                return ClassificationResult(
                    status=status,
                    domain_code=domain.code if domain else None,
                    after_id=after_id,
                    next_after_id=after_id,
                    missing_tables=missing,
                )

            batch = self.repository.list_domain_observations(
                domain.id,
                after_id=after_id,
                limit=limit,
            )

            domain_topic_ids = {
                topic.id
                for topic in self.repository.list_topics_for_domain(domain.id, active_only=False)
            }
            active_topics = {
                topic.id: topic
                for topic in self.repository.list_topics_for_domain(domain.id, active_only=True)
            }
            resolved = {}

            for observation, linked_topic_ids in batch:
                outcome, counter = self._classify_observation(
                    observation, linked_topic_ids, domain, domain_topic_ids, active_topics, resolved,
                )
                # Only a completed observation is counted and moves the
                # cursor (last completed one, whatever its outcome).
                counts["processed"] += 1
                counts[counter] += 1
                outcomes.append(outcome)
                next_after_id = observation.id

        except self.store_unavailable_errors:
            # Store vanished (never re-created). The cursor stays on the last
            # completed observation, so the failed one is retried; writes are
            # idempotent (upsert + ALREADY_CLASSIFIED).
            return ClassificationResult(
                status=STATUS_NO_STORE,
                domain_code=domain.code if domain else None,
                after_id=after_id,
                next_after_id=next_after_id,
                outcomes=tuple(outcomes),
                **counts,
            )

        return ClassificationResult(
            status=STATUS_OK,
            domain_code=domain.code,
            after_id=after_id,
            next_after_id=next_after_id,
            exhausted=len(batch) < limit,
            outcomes=tuple(outcomes),
            **counts,
        )

    def _classify_observation(self, observation, linked_topic_ids, domain, domain_topic_ids,
                              active_topics, resolved):
        """(ObservationOutcome, counter) once the observation is fully settled."""
        if domain_topic_ids.intersection(linked_topic_ids):
            return ObservationOutcome(observation.id, OUTCOME_ALREADY_CLASSIFIED), "already_classified"

        candidates = {
            topic.id: topic
            for topic in (
                self._resolve_hashtag(tag, observation, active_topics, resolved)
                for tag in _hashtags(observation)
            )
            if topic is not None
        }

        if not candidates:
            return ObservationOutcome(observation.id, OUTCOME_UNMATCHED), "unmatched"

        if len(candidates) > 1:
            return ObservationOutcome(observation.id, OUTCOME_AMBIGUOUS), "ambiguous"

        (topic,) = candidates.values()
        self.trend_service.assign_observation_topic(
            observation.id,
            domain_code=domain.code,
            topic_key=topic.topic_key,
            detection_method=DETECTION_METHOD,
        )
        return ObservationOutcome(observation.id, OUTCOME_CLASSIFIED, topic.topic_key), "classified"

    def _resolve_hashtag(self, tag, observation, active_topics, resolved):
        """Exact resolution through TrendIntelligenceService.resolve_topic.

        resolve_topic answers a topic_key directly even when inactive, and an
        alias regardless of domain; only active topics linked to the domain
        are accepted. No fuzzy matching and no topic/alias creation.
        """
        try:
            key = _normalize_key(tag)
        except ValueError:
            return None

        cache_key = (key, observation.language or "", observation.country or "")

        if cache_key not in resolved:
            topic = self.trend_service.resolve_topic(
                key,
                language=observation.language or "",
                country=observation.country or "",
            )
            resolved[cache_key] = (
                topic
                if topic is not None and topic.is_active and topic.id in active_topics
                else None
            )

        return resolved[cache_key]

    # ------------------------------------------------------------------
    # Phase 2 · window processing
    # ------------------------------------------------------------------

    def process_windows(
        self,
        domain_code,
        topic_keys,
        window_from,
        window_to,
        *,
        max_windows=DEFAULT_MAX_WINDOWS,
    ):
        start = _utc_midnight(window_from, "window_from")
        end = _utc_midnight(window_to, "window_to")

        if start >= end:
            raise ValueError("Se requiere window_from < window_to")

        # Only complete windows: the in-progress day would be re-scored with
        # partial counts and could raise spurious signals.
        if end > self.clock():
            raise ValueError("window_to no puede superar el instante actual")

        max_windows = _plain_int(max_windows, "max_windows")

        if not 1 <= max_windows <= MAX_WINDOWS_HARD_CAP:
            raise ValueError(f"max_windows debe estar entre 1 y {MAX_WINDOWS_HARD_CAP}")

        if isinstance(topic_keys, str):
            raise ValueError("topic_keys debe ser una colección")

        keys = tuple(dict.fromkeys(_normalize_key(key) for key in topic_keys))

        if not keys:
            raise ValueError("topic_keys obligatorio")

        days = (end - start).days
        if len(keys) * days > max_windows:
            raise ValueError(
                f"{len(keys) * days} pares topic-ventana superan max_windows={max_windows}"
            )

        bounds = tuple(
            (
                (start + timedelta(days=offset)).isoformat(),
                (start + timedelta(days=offset + WINDOW_DAYS)).isoformat(),
            )
            for offset in range(days)
        )

        base = dict(window_from=start.isoformat(), window_to=end.isoformat())
        outcomes = []
        domain = None

        try:
            status, domain, missing = self._preflight(domain_code)

            if status != STATUS_OK:
                return WindowProcessingResult(
                    status=status,
                    domain_code=domain.code if domain else None,
                    missing_tables=missing,
                    **base,
                )

            topics, invalid = self._domain_topics(domain, keys)

            if invalid:
                return WindowProcessingResult(
                    status=STATUS_INVALID_TOPIC,
                    domain_code=domain.code,
                    invalid_topics=invalid,
                    **base,
                )

            for topic in topics:
                outcomes.extend(self._process_topic(domain, topic, bounds, base))

        except self.store_unavailable_errors:
            return self._window_result(STATUS_NO_STORE, domain, outcomes, base)

        failed = any(item.status == WINDOW_FAILED for item in outcomes)
        return self._window_result(STATUS_PARTIAL if failed else STATUS_OK, domain, outcomes, base)

    def _domain_topics(self, domain, keys):
        topics, invalid = [], []

        for key in keys:
            topic = self.repository.get_topic_by_key(key)
            linked = (
                topic is not None
                and domain.id in {item.domain_id for item in self.repository.list_topic_domains(topic.id)}
            )

            if linked and topic.is_active:
                topics.append(topic)
            else:
                invalid.append(key)

        return tuple(topics), tuple(invalid)

    def _process_topic(self, domain, topic, bounds, base):
        # A topic never materialized and without observations in the range
        # has no evidence at all: no metrics/snapshots are fabricated for it.
        # With prior history, empty windows are real (e.g. decline).
        stats = self.repository.get_temporal_window_stats(
            domain.id,
            topic.id,
            window_start=base["window_from"],
            window_end=base["window_to"],
        )

        if not stats["observation_count"] and not self.repository.list_temporal_metrics(
            domain.id, topic.id, limit=1,
        ):
            return [
                WindowOutcome(topic.topic_key, window_start, window_end, WINDOW_SKIPPED_NO_DATA)
                for window_start, window_end in bounds
            ]

        outcomes = []
        failure = False

        for window_start, window_end in bounds:
            if failure:
                # Later windows depend on this one as baseline history; they
                # are left for an explicit retry of the same range.
                outcomes.append(WindowOutcome(topic.topic_key, window_start, window_end, WINDOW_NOT_ATTEMPTED))
                continue

            try:
                processed = self.pipeline.process_window(
                    domain_code=domain.code,
                    topic_key=topic.topic_key,
                    window_start=window_start,
                    window_end=window_end,
                    lookback_windows=LOOKBACK_WINDOWS,
                    country="",
                    language="",
                )
            except self.store_unavailable_errors:
                raise
            except Exception as error:
                failure = True
                outcomes.append(WindowOutcome(
                    topic.topic_key, window_start, window_end, WINDOW_FAILED,
                    error=f"{type(error).__name__}: {error}",
                ))
                continue

            outcomes.append(WindowOutcome(topic.topic_key, window_start, window_end, WINDOW_OK, result=processed))

        return outcomes

    def _window_result(self, status, domain, outcomes, base):
        processed = [item.result for item in outcomes if item.status == WINDOW_OK]

        return WindowProcessingResult(
            status=status,
            domain_code=domain.code if domain else None,
            windows=tuple(outcomes),
            ok=len(processed),
            failed=sum(item.status == WINDOW_FAILED for item in outcomes),
            not_attempted=sum(item.status == WINDOW_NOT_ATTEMPTED for item in outcomes),
            skipped=sum(item.status == WINDOW_SKIPPED_NO_DATA for item in outcomes),
            signature=self.pipeline._signature(processed),
            **base,
        )


def create_trend_producer(db_path, *, clock=None):
    """Lazy composition over an EXISTING store; nothing is opened here.

    db_path is mandatory (no default to the operational database). Every
    connection is SQLite URI mode=rw: an absent file yields NO_STORE and is
    never created; no ensure_schema/DDL is ever invoked.
    """
    if db_path is None or not str(db_path).strip():
        raise ValueError("db_path obligatorio")

    from backend.repositories.sqlite_trend_intelligence_repository import (
        ExistingStoreUnavailable,
        SQLiteTrendIntelligenceRepository,
    )
    from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService
    from backend.trend_intelligence.service import TrendIntelligenceService
    from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService

    repository = SQLiteTrendIntelligenceRepository.existing(db_path)

    return TrendProducerService(
        trend_service=TrendIntelligenceService(repository),
        pipeline=TrendAutomaticPipelineService(
            repository=repository,
            temporal_service=TrendTemporalIntelligenceService(repository),
        ),
        store_unavailable_errors=(ExistingStoreUnavailable,),
        clock=clock,
    )

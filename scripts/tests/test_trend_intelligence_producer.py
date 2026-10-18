"""TI-4C.1 producer contracts on temporary file-backed SQLite only.

No browser, network, scheduler or operational database: every store is
created under tmp_path by the existing ensure_schema() fixture path.
"""
import ast
import hashlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import (
    ExistingOnlyRepositoryError,
    ExistingStoreUnavailable,
    ReadOnlyRepositoryError,
    ReadOnlyStoreUnavailable,
    SQLiteTrendIntelligenceReadOnlyLookup,
    SQLiteTrendIntelligenceRepository,
)
from backend.services.trend_intelligence_dashboard_service import (
    SETTINGS_KEY,
    TrendIntelligenceDashboardService,
)
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.models import ObservationTopic
from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService
from backend.trend_intelligence.producer import (
    MAX_WINDOWS_HARD_CAP,
    OUTCOME_ALREADY_CLASSIFIED,
    OUTCOME_AMBIGUOUS,
    OUTCOME_CLASSIFIED,
    OUTCOME_UNMATCHED,
    ObservationOutcome,
    TrendProducerService,
    create_trend_producer,
)
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.instagram import (
    InstagramRawObservation,
    InstagramTrendSourceAdapter,
)
from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService

ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PATH = ROOT / "backend" / "trend_intelligence" / "producer.py"

DOMAIN = "IT_DOMAIN"
OTHER = "OTHER_DOMAIN"
SOURCE = "IG_TEST"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
DAY0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
STATE_TABLES = (
    "ti_observations", "ti_observation_domains", "ti_observation_topics",
    "ti_temporal_metrics", "ti_temporal_baselines", "ti_aggregate_signals",
    "ti_trend_snapshots", "ti_topics", "ti_topic_aliases", "ti_domains",
)


def clock():
    return NOW


def day(offset):
    return (DAY0 + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------- fixtures

def build_store(path):
    """Temporary store via the existing default RW repository + ensure_schema."""
    core = TrendIntelligenceService(SQLiteTrendIntelligenceRepository(path))
    core.ensure_schema()
    core.create_domain(code=DOMAIN, name="Inmigración")
    core.create_domain(code=OTHER, name="Other")
    core.create_domain(code="DORMANT_DOMAIN", name="Dormant", is_active=False)
    core.create_topic(topic_key="ARRAIGO", name="Arraigo", domain_codes=(DOMAIN,))
    core.create_topic(topic_key="NACIONALIDAD", name="Nacionalidad", domain_codes=(DOMAIN,))
    core.create_topic(topic_key="FOREIGN", name="Foreign", domain_codes=(OTHER,))
    retired = core.create_topic(topic_key="RETIRED", name="Retired", domain_codes=(DOMAIN,))
    core.repository.save_topic(replace(retired, id=None, is_active=False))
    core.register_topic_alias("ARRAIGO", "arraigosocial")
    core.register_topic_alias("NACIONALIDAD", "nacionalidadespanola")
    core.register_topic_alias("ARRAIGO", "aliasviejo", is_active=False)
    core.register_topic_alias("FOREIGN", "extranjero")
    core.register_topic_alias("RETIRED", "retiradoalias")
    core.create_source(code=SOURCE, name="Instagram", source_type="SOCIAL",
                       collection_mode="SELENIUM", provider="instagram")
    return core


def ingest(path, posts, *, domain_code=DOMAIN):
    """Real ingestion path (Instagram adapter -> TrendIngestionService)."""
    core = TrendIntelligenceService(SQLiteTrendIntelligenceRepository(path))
    raws = [
        InstagramRawObservation(
            source_account="cuenta", external_id=external_id,
            canonical_url=f"https://www.instagram.com/p/{external_id}/",
            content_type="POST", observed_at=observed_at,
            hashtags=tuple(tags), collection_run_id="run-1",
        )
        for external_id, observed_at, tags in posts
    ]
    return TrendIngestionService(core).ingest(
        InstagramTrendSourceAdapter(SOURCE, raws), domain_code=domain_code,
    )


def dump(path, tables=STATE_TABLES):
    conn = sqlite3.connect(str(path))
    try:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables}
    finally:
        conn.close()


def count(path, table):
    return len(dump(path, (table,))[table])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configure_dashboard(path, domain_code=DOMAIN):
    # Test-only fixture: the Collector settings table lives outside TI.
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS config_global (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        conn.execute("INSERT OR REPLACE INTO config_global (key, value) VALUES (?, ?)",
                     (SETTINGS_KEY, json.dumps({"domain_code": domain_code})))
        conn.commit()
    finally:
        conn.close()


def dashboard_state(path):
    return TrendIntelligenceDashboardService(
        settings=SQLiteTrendIntelligenceReadOnlyLookup(path),
        trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(path, readonly=True)),
        store_unavailable_errors=(ReadOnlyStoreUnavailable,),
    ).state()


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "ti.db"
    build_store(path)
    yield path
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        conn.close()


def producer(path):
    return create_trend_producer(path, clock=clock)


def topic_link(path, observation_id):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(
            "SELECT t.topic_key, ot.detection_method FROM ti_observation_topics ot "
            "JOIN ti_topics t ON t.id = ot.topic_id WHERE ot.observation_id = ?",
            (observation_id,),
        ).fetchall()
    finally:
        conn.close()


# ------------------------------------------------- gate 1 · domain guards

@pytest.mark.parametrize("domain_code,expected", [
    (None, "NO_DOMAIN"), ("", "NO_DOMAIN"), ("   ", "NO_DOMAIN"),
    ("NOT_REGISTERED", "UNKNOWN_DOMAIN"), ("!!!", "UNKNOWN_DOMAIN"),
    ("DORMANT_DOMAIN", "DOMAIN_INACTIVE"),
])
def test_domain_guards_never_write(store, domain_code, expected):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    before, file_digest = dump(store), digest(store)
    service = producer(store)
    assert service.classify_pending(domain_code).status == expected
    windows = service.process_windows(domain_code, ["ARRAIGO"], day(0), day(2))
    assert windows.status == expected
    assert windows.windows == ()
    assert dump(store) == before
    assert digest(store) == file_digest
    assert service.repository.get_domain_by_code("NOT_REGISTERED") is None


# --------------------------------------- gate 2 · store / schema guards

def test_absent_store_is_no_store_and_never_created(tmp_path):
    path = tmp_path / "absent.db"
    service = producer(path)  # constructor performs no IO
    assert list(tmp_path.iterdir()) == []
    result = service.classify_pending(DOMAIN)
    assert (result.status, result.processed, result.next_after_id) == ("NO_STORE", 0, 0)
    assert service.process_windows(DOMAIN, ["ARRAIGO"], day(0), day(1)).status == "NO_STORE"
    with pytest.raises(ExistingOnlyRepositoryError):
        service.repository.ensure_schema()
    assert list(tmp_path.iterdir()) == []


def test_store_vanishing_between_preflight_and_open_is_not_recreated(store):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    service = producer(store)
    original = service.repository.missing_tables

    def preflight_then_vanish(names):
        result = original(names)
        os.remove(store)
        return result

    with patch.object(service.repository, "missing_tables", side_effect=preflight_then_vanish):
        result = service.classify_pending(DOMAIN)
    assert result.status == "NO_STORE"
    assert not store.exists()
    assert list(store.parent.iterdir()) == []
    assert service.process_windows(DOMAIN, ["ARRAIGO"], day(0), day(1)).status == "NO_STORE"
    assert not store.exists()
    with pytest.raises(ExistingStoreUnavailable):
        service.repository.get_domain_by_code(DOMAIN)
    assert not store.exists()


def test_window_store_vanishing_after_preflight(store):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    service = producer(store)
    service.classify_pending(DOMAIN)
    original = service.repository.missing_tables

    def preflight_then_vanish(names):
        result = original(names)
        os.remove(store)
        return result

    with patch.object(service.repository, "missing_tables", side_effect=preflight_then_vanish):
        assert service.process_windows(DOMAIN, ["ARRAIGO"], day(0), day(1)).status == "NO_STORE"
    assert not store.exists()


def test_incomplete_schema_is_reported_without_ddl(tmp_path):
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ti_domains (id INTEGER PRIMARY KEY, code TEXT)")
    conn.commit()
    conn.close()
    schema_before, file_digest = dump(path, ("sqlite_master",)), digest(path)
    service = producer(path)
    result = service.classify_pending(DOMAIN)
    assert result.status == "SCHEMA_INCOMPLETE"
    assert "ti_observation_topics" in result.missing_tables
    assert "ti_domains" not in result.missing_tables
    assert service.process_windows(DOMAIN, ["ARRAIGO"], day(0), day(1)).status == "SCHEMA_INCOMPLETE"
    assert dump(path, ("sqlite_master",)) == schema_before
    assert digest(path) == file_digest


def test_existing_only_is_opt_in_and_previous_consumers_unchanged(store, tmp_path):
    # Default constructor signature and create-if-missing behaviour unchanged.
    assert list(inspect.signature(SQLiteTrendIntelligenceRepository).parameters) == ["db_path", "readonly"]
    default = SQLiteTrendIntelligenceRepository(tmp_path / "default.db")
    assert default.existing_only is False and default.readonly is False
    default.ensure_schema()
    assert (tmp_path / "default.db").is_file()
    # Existing-only writes through mode=rw on an existing store.
    existing = SQLiteTrendIntelligenceRepository.existing(store)
    assert (existing.existing_only, existing.readonly) == (True, False)
    with existing.window_transaction():
        assert existing.get_domain_by_code(DOMAIN) is not None
    # RO still refuses writes on the same store.
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    producer(store).classify_pending(DOMAIN)
    before = digest(store)
    readonly = SQLiteTrendIntelligenceRepository(store, readonly=True)
    pipeline = TrendAutomaticPipelineService(
        repository=readonly, temporal_service=TrendTemporalIntelligenceService(readonly))
    with pytest.raises(ReadOnlyRepositoryError):
        pipeline.process_window(domain_code=DOMAIN, topic_key="ARRAIGO",
                                window_start=day(0), window_end=day(1))
    assert digest(store) == before


def test_service_requires_shared_repository(store):
    repo_a = SQLiteTrendIntelligenceRepository.existing(store)
    repo_b = SQLiteTrendIntelligenceRepository.existing(store)
    with pytest.raises(ValueError):
        TrendProducerService(
            trend_service=TrendIntelligenceService(repo_a),
            pipeline=TrendAutomaticPipelineService(
                repository=repo_b, temporal_service=TrendTemporalIntelligenceService(repo_b)),
        )


# ------------------------------------ gate 3 · empty / unmatched paths

def test_zero_observations_produce_nothing_and_dashboard_stays_empty(store):
    configure_dashboard(store)
    assert dashboard_state(store).status == "EMPTY"
    service = producer(store)
    result = service.classify_pending(DOMAIN)
    assert (result.status, result.processed, result.classified, result.exhausted) == ("OK", 0, 0, True)
    windows = service.process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(7))
    assert windows.status == "OK"
    assert (windows.ok, windows.skipped) == (0, 14)
    assert count(store, "ti_trend_snapshots") == 0
    assert count(store, "ti_temporal_metrics") == 0
    assert dashboard_state(store).status == "EMPTY"


def test_unmatched_cases_are_not_classified(store):
    configure_dashboard(store)
    ingest(store, [
        ("no_tags", day(0), []),
        ("inactive_alias", day(0), ["aliasviejo"]),
        ("other_domain", day(0), ["extranjero"]),
        ("other_domain_key", day(0), ["#foreign"]),
        ("inactive_topic_key", day(0), ["retired"]),
        ("inactive_topic_alias", day(0), ["retiradoalias"]),
        ("fuzzy", day(0), ["arraigo_social_2026"]),
        ("garbage", day(0), ["###", "!!!"]),
    ])
    result = producer(store).classify_pending(DOMAIN)
    assert (result.processed, result.unmatched, result.classified, result.ambiguous) == (8, 8, 0, 0)
    assert {item.outcome for item in result.outcomes} == {OUTCOME_UNMATCHED}
    assert count(store, "ti_observation_topics") == 0
    assert producer(store).process_windows(DOMAIN, ["ARRAIGO"], day(0), day(3)).skipped == 3
    assert count(store, "ti_trend_snapshots") == 0
    assert dashboard_state(store).status == "EMPTY"


def test_observations_without_domain_are_never_listed(store):
    ingest(store, [("orphan", day(0), ["arraigosocial"])], domain_code=None)
    ingest(store, [("foreign", day(0), ["arraigosocial"])], domain_code=OTHER)
    result = producer(store).classify_pending(DOMAIN)
    assert result.processed == 0
    assert count(store, "ti_observation_topics") == 0


# ------------------------- gate 4 · exact match, ambiguity, provenance

def test_exact_match_classifies_and_preserves_provenance(store):
    ingest(store, [
        ("exact_alias", day(0), ["#ArraigoSocial"]),
        ("exact_key", day(0), ["nacionalidad"]),
        ("same_topic_twice", day(0), ["arraigosocial", "#arraigo"]),
        ("ambiguous", day(0), ["arraigosocial", "nacionalidadespanola"]),
        ("match_plus_noise", day(0), ["nacionalidadespanola", "extranjero", "aliasviejo"]),
    ])
    before = dump(store)
    result = producer(store).classify_pending(DOMAIN)
    assert (result.processed, result.classified, result.ambiguous, result.unmatched) == (5, 4, 1, 0)
    by_outcome = {item.observation_id: (item.outcome, item.topic_key) for item in result.outcomes}
    ids = [row[0] for row in before["ti_observations"]]
    assert by_outcome[ids[0]] == (OUTCOME_CLASSIFIED, "ARRAIGO")
    assert by_outcome[ids[1]] == (OUTCOME_CLASSIFIED, "NACIONALIDAD")
    assert by_outcome[ids[2]] == (OUTCOME_CLASSIFIED, "ARRAIGO")
    assert by_outcome[ids[3]] == (OUTCOME_AMBIGUOUS, None)
    assert by_outcome[ids[4]] == (OUTCOME_CLASSIFIED, "NACIONALIDAD")
    assert topic_link(store, ids[0]) == [("ARRAIGO", "HASHTAG_EXACT")]
    assert topic_link(store, ids[3]) == []

    after = dump(store)
    # Observation rows (id, source_id, external_id, observed_at, metadata,
    # created_at) and domain links (detection_method=SOURCE, timestamps)
    # are byte-identical.
    assert after["ti_observations"] == before["ti_observations"]
    assert after["ti_observation_domains"] == before["ti_observation_domains"]
    repo = SQLiteTrendIntelligenceRepository(store, readonly=True)
    for observation_id in ids:
        assert [d.detection_method for d in repo.list_observation_domains(observation_id)] == ["SOURCE"]
        observation = repo.get_observation(observation_id)
        assert observation.metadata["collection_run_id"] == "run-1"
        assert observation.external_id is not None

    # Producer retry from scratch: pure no-op.
    again = producer(store).classify_pending(DOMAIN)
    assert again.classified == 0
    assert again.already_classified == 4 and again.ambiguous == 1
    assert dump(store) == after

    # Duplicated ingestion: no new observation/topic rows. The pre-existing
    # ingestion re-upserts the SOURCE domain link (updated_at only).
    report = ingest(store, [("exact_alias", day(0), ["#ArraigoSocial"])])
    assert (report.created, report.duplicates) == (0, 1)
    reingested = dump(store)
    assert {k: v for k, v in reingested.items() if k != "ti_observation_domains"} == \
        {k: v for k, v in after.items() if k != "ti_observation_domains"}
    assert [row[:4] for row in reingested["ti_observation_domains"]] == \
        [row[:4] for row in after["ti_observation_domains"]]
    assert producer(store).classify_pending(DOMAIN).classified == 0
    assert dump(store) == reingested


def test_existing_manual_classification_is_respected(store):
    ingest(store, [("manual", day(0), ["arraigosocial"])])
    core = TrendIntelligenceService(SQLiteTrendIntelligenceRepository(store))
    obs_id = dump(store)["ti_observations"][0][0]
    core.repository.link_observation_topic(ObservationTopic(
        observation_id=obs_id, topic_id=core.repository.get_topic_by_key("NACIONALIDAD").id,
        detection_method="MANUAL"))
    before = dump(store)
    result = producer(store).classify_pending(DOMAIN)
    assert [item.outcome for item in result.outcomes] == [OUTCOME_ALREADY_CLASSIFIED]
    assert dump(store) == before


def test_topic_only_assignment_rejects_out_of_scope(store):
    ingest(store, [("p1", day(0), [])])
    ingest(store, [("orphan", day(0), [])], domain_code=None)
    core = TrendIntelligenceService(SQLiteTrendIntelligenceRepository.existing(store))
    ids = [row[0] for row in dump(store)["ti_observations"]]
    before = dump(store)
    for kwargs in (dict(topic_key="FOREIGN"), dict(topic_key="RETIRED"), dict(topic_key="MISSING")):
        with pytest.raises(ValueError):
            core.assign_observation_topic(ids[0], domain_code=DOMAIN, **kwargs)
    with pytest.raises(ValueError):
        core.assign_observation_topic(ids[1], domain_code=DOMAIN, topic_key="ARRAIGO")
    assert dump(store) == before
    # Pre-existing classify_observation semantics untouched (rewrites method).
    core.classify_observation(ids[0], domain_code=DOMAIN, topic_key="ARRAIGO")
    assert [d.detection_method for d in core.repository.list_observation_domains(ids[0])] == ["MANUAL"]


# ------------------------------------------- gate 5 · cursor and limits

def test_cursor_batches_and_restart(store):
    posts = [(f"p{index:03d}", day(index % 3), ["arraigosocial"] if index % 2 else [])
             for index in range(205)]
    report = ingest(store, posts)
    ids = list(report.observation_ids)

    first = producer(store).classify_pending(DOMAIN, limit=1)
    assert (first.processed, first.next_after_id, first.exhausted) == (1, ids[0], False)
    second = producer(store).classify_pending(DOMAIN, after_id=first.next_after_id, limit=1)
    assert (second.processed, second.next_after_id) == (1, ids[1])

    hundred = producer(store).classify_pending(DOMAIN, after_id=second.next_after_id, limit=100)
    assert (hundred.processed, hundred.next_after_id) == (100, ids[101])
    # Process restart: brand-new producer/repository, cursor carried by caller.
    restarted = create_trend_producer(store, clock=clock)
    rest = restarted.classify_pending(DOMAIN, after_id=hundred.next_after_id, limit=200)
    assert (rest.processed, rest.next_after_id, rest.exhausted) == (103, ids[-1], True)
    done = restarted.classify_pending(DOMAIN, after_id=rest.next_after_id, limit=200)
    assert (done.processed, done.next_after_id, done.exhausted) == (0, ids[-1], True)

    total = [first, second, hundred, rest]
    assert sum(r.processed for r in total) == 205
    assert sum(r.classified for r in total) == 102
    assert sum(r.unmatched for r in total) == 103
    assert count(store, "ti_observation_topics") == 102

    full = producer(store).classify_pending(DOMAIN, limit=200)
    assert (full.processed, full.next_after_id, full.exhausted) == (200, ids[199], False)
    assert full.classified == 0


@pytest.mark.parametrize("kwargs", [
    dict(limit=0), dict(limit=201), dict(limit=True), dict(limit="5"), dict(limit=1.0),
    dict(after_id=-1), dict(after_id="0"), dict(after_id=None),
])
def test_invalid_cursor_arguments_rejected_before_io(tmp_path, kwargs):
    with pytest.raises(ValueError):
        producer(tmp_path / "absent.db").classify_pending(DOMAIN, **kwargs)
    assert list(tmp_path.iterdir()) == []


def test_repository_batch_bounds(store):
    repo = SQLiteTrendIntelligenceRepository.existing(store)
    for kwargs in (dict(limit=0), dict(limit=201), dict(after_id=-1)):
        with pytest.raises(ValueError):
            repo.list_domain_observations(1, **kwargs)


@pytest.mark.parametrize("window_from,window_to,kwargs", [
    (day(1), day(1), {}),
    (day(2), day(1), {}),
    ("2026-10-01T01:00:00+00:00", day(1), {}),
    ("2026-10-01T00:00:00.000001+00:00", day(1), {}),
    ("2026-10-01T00:00:00", day(1), {}),
    ("2026-10-01T00:00:00+02:00", day(1), {}),
    (day(0), "2026-10-15T00:00:00+00:00", {}),
    (day(0), day(29), dict(max_windows=28)),
    (day(0), day(5), dict(max_windows=29)),
    (day(0), day(5), dict(max_windows=0)),
    (day(0), day(5), dict(max_windows=4)),
    (day(0), day(5), dict(max_windows=True)),
    ("", day(1), {}),
    (None, day(1), {}),
])
def test_invalid_window_ranges_rejected_before_io(tmp_path, window_from, window_to, kwargs):
    with pytest.raises(ValueError):
        producer(tmp_path / "absent.db").process_windows(DOMAIN, ["ARRAIGO"], window_from, window_to, **kwargs)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("topic_keys", ["ARRAIGO", [], ["!!!"]])
def test_invalid_topic_arguments_rejected(tmp_path, topic_keys):
    with pytest.raises(ValueError):
        producer(tmp_path / "absent.db").process_windows(DOMAIN, topic_keys, day(0), day(1))


def test_pair_budget_counts_topics_and_hard_cap(store):
    assert MAX_WINDOWS_HARD_CAP == 28
    with pytest.raises(ValueError):
        producer(store).process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(13), max_windows=25)
    yesterday = (NOW.replace(hour=0) - timedelta(days=1)).isoformat()
    today = NOW.replace(hour=0).isoformat()
    # The last complete UTC day is accepted.
    assert producer(store).process_windows(DOMAIN, ["ARRAIGO"], yesterday, today).status == "OK"


def test_topics_outside_domain_or_inactive_rejected_without_writes(store):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    producer(store).classify_pending(DOMAIN)
    before = dump(store)
    result = producer(store).process_windows(DOMAIN, ["ARRAIGO", "FOREIGN", "RETIRED", "MISSING"], day(0), day(1))
    assert result.status == "INVALID_TOPIC"
    assert result.invalid_topics == ("FOREIGN", "RETIRED", "MISSING")
    assert dump(store) == before


# ------------------------------ gate 6 · real windows and dashboard RO

DAILY_COUNTS = (1, 1, 1, 2, 1, 1, 1, 6, 0)


def seed_history(path):
    posts = []
    for offset, amount in enumerate(DAILY_COUNTS):
        for index in range(amount):
            posts.append((f"a{offset}-{index}", (DAY0 + timedelta(days=offset, hours=9, minutes=index)).isoformat(),
                          ["arraigosocial"]))
        posts.append((f"n{offset}", (DAY0 + timedelta(days=offset, hours=23, minutes=59)).isoformat(),
                      ["nacionalidadespanola"]))
    return ingest(path, posts)


def test_complete_utc_windows_feed_dashboard_from_real_snapshots(store):
    configure_dashboard(store)
    seed_history(store)
    service = producer(store)
    assert service.classify_pending(DOMAIN, limit=200).classified == sum(DAILY_COUNTS) + len(DAILY_COUNTS)
    assert dashboard_state(store).status == "EMPTY"

    result = service.process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(9), max_windows=18)
    assert (result.status, result.ok, result.failed) == ("OK", 18, 0)
    assert result.lookback_windows == 7
    for item in result.windows:
        start = datetime.fromisoformat(item.window_start)
        assert start.tzinfo == timezone.utc and start.time().isoformat() == "00:00:00"
        assert datetime.fromisoformat(item.window_end) - start == timedelta(days=1)
    arraigo = [item.result for item in result.windows if item.topic_key == "ARRAIGO"]
    assert [item.observation_count for item in arraigo] == list(DAILY_COUNTS)
    # Country/language are empty on Instagram observations: aggregate scope.
    repo = SQLiteTrendIntelligenceRepository(store, readonly=True)
    domain = repo.get_domain_by_code(DOMAIN)
    topic = repo.get_topic_by_key("ARRAIGO")
    snapshots = repo.list_trend_snapshots(domain.id, topic.id)
    assert len(snapshots) == len(DAILY_COUNTS)
    assert {(s.country, s.language) for s in snapshots} == {("", "")}
    assert all(s.metadata["lookback_windows"] == 7 for s in snapshots)
    assert [(s.score, s.status) for s in snapshots] == [(w.score, w.status) for w in arraigo]

    state = dashboard_state(store)
    assert state.status == "READY"
    assert {row.topic.topic_key for row in state.rows} == {"ARRAIGO", "NACIONALIDAD"}
    latest = {row.topic.topic_key: row.snapshot for row in state.rows}
    assert latest["ARRAIGO"] == snapshots[-1]
    assert latest["ARRAIGO"].window_start == day(8)

    # Same range again: identical signature and persisted state.
    before = dump(store)
    again = producer(store).process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(9), max_windows=18)
    assert again.signature == result.signature
    assert dump(store) == before


def test_first_windows_do_not_require_signals(store):
    ingest(store, [("only", (DAY0 + timedelta(hours=1)).isoformat(), ["arraigosocial"])])
    producer(store).classify_pending(DOMAIN)
    result = producer(store).process_windows(DOMAIN, ["ARRAIGO"], day(0), day(1))
    assert result.status == "OK" and result.ok == 1
    assert result.windows[0].result.observation_count == 1


# ---------------------------------- gate 7 · failure in window k + retry

def test_failure_in_window_k_rolls_back_k_and_retry_converges(store):
    seed_history(store)
    producer(store).classify_pending(DOMAIN, limit=200)
    service = producer(store)
    snapshot_service = service.pipeline.snapshot_service
    original = snapshot_service.materialize
    failing_start = day(2)

    def fail_on_k(**kwargs):
        if kwargs["topic_key"] == "ARRAIGO" and kwargs["window_start"] == failing_start:
            raise RuntimeError("injected failure")
        return original(**kwargs)

    with patch.object(snapshot_service, "materialize", side_effect=fail_on_k):
        result = service.process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(5), max_windows=10)

    assert result.status == "PARTIAL"
    arraigo = [item for item in result.windows if item.topic_key == "ARRAIGO"]
    assert [item.status for item in arraigo] == ["OK", "OK", "FAILED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]
    assert "injected failure" in arraigo[2].error
    # Independent topic keeps going.
    assert [item.status for item in result.windows if item.topic_key == "NACIONALIDAD"] == ["OK"] * 5
    assert (result.ok, result.failed, result.not_attempted) == (7, 1, 2)

    repo = SQLiteTrendIntelligenceRepository(store, readonly=True)
    domain, topic = repo.get_domain_by_code(DOMAIN), repo.get_topic_by_key("ARRAIGO")
    # Windows before k persisted; k left no metric/baseline/snapshot at all.
    assert [m.window_start for m in repo.list_temporal_metrics(domain.id, topic.id)] == [day(0), day(1)]
    assert [s.window_start for s in repo.list_trend_snapshots(domain.id, topic.id)] == [day(0), day(1)]
    assert repo.get_temporal_baseline(domain.id, topic.id, reference_window_start=day(2),
                                      reference_window_end=day(3), lookback_windows=7) is None
    assert repo.list_aggregate_signals(domain.id, topic.id, window_start=day(2), window_end=day(3)) == []

    retry = producer(store).process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(5), max_windows=10)
    assert (retry.status, retry.ok, retry.failed) == ("OK", 10, 0)
    assert len(repo.list_temporal_metrics(domain.id, topic.id)) == 5
    assert len(repo.list_trend_snapshots(domain.id, topic.id)) == 5
    settled = dump(store)

    second = producer(store).process_windows(DOMAIN, ["ARRAIGO", "NACIONALIDAD"], day(0), day(5), max_windows=10)
    assert second.signature == retry.signature
    assert dump(store) == settled

    replay = producer(store).pipeline.replay_existing_windows(domain_code=DOMAIN, topic_key="ARRAIGO")
    retried_arraigo = [item.result for item in retry.windows if item.topic_key == "ARRAIGO"]
    assert replay.signature == TrendAutomaticPipelineService._signature(retried_arraigo)
    assert dump(store) == settled


# ------------------- gate 7b · store loss mid-batch keeps a safe cursor

def fail_once_on(target, method, should_fail):
    """patch.object over target.method raising ExistingStoreUnavailable once."""
    original = getattr(target, method)
    state = dict(calls=0, failed=False)

    def wrapper(*args, **kwargs):
        state["calls"] += 1
        if not state["failed"] and should_fail(state["calls"], *args, **kwargs):
            state["failed"] = True
            raise ExistingStoreUnavailable("injected store loss")
        return original(*args, **kwargs)

    return patch.object(target, method, side_effect=wrapper), state


def test_store_loss_on_first_topic_link_keeps_original_cursor(store):
    report = ingest(store, [("p1", day(0), ["arraigosocial"])])
    (obs_id,) = report.observation_ids
    service = producer(store)
    patcher, state = fail_once_on(service.trend_service, "assign_observation_topic",
                                  lambda calls, observation_id, **_: observation_id == obs_id)
    with patcher:
        result = service.classify_pending(DOMAIN, after_id=0)
    assert state["failed"]
    assert (result.status, result.processed, result.classified) == ("NO_STORE", 0, 0)
    assert result.outcomes == ()
    assert result.next_after_id == result.after_id == 0
    assert topic_link(store, obs_id) == []

    retry = producer(store).classify_pending(DOMAIN, after_id=result.next_after_id)
    assert (retry.status, retry.processed, retry.classified) == ("OK", 1, 1)
    assert retry.outcomes == (ObservationOutcome(obs_id, OUTCOME_CLASSIFIED, "ARRAIGO"),)
    assert topic_link(store, obs_id) == [("ARRAIGO", "HASHTAG_EXACT")]
    repo = SQLiteTrendIntelligenceRepository(store, readonly=True)
    assert [d.detection_method for d in repo.list_observation_domains(obs_id)] == ["SOURCE"]


def test_store_loss_on_second_topic_link_resumes_and_converges(store, tmp_path):
    posts = [("p1", day(0), ["arraigosocial"]), ("p2", day(0), ["nacionalidadespanola"]),
             ("p3", day(0), [])]
    first_id, second_id, third_id = ingest(store, posts).observation_ids
    service = producer(store)
    patcher, state = fail_once_on(service.trend_service, "assign_observation_topic",
                                  lambda calls, observation_id, **_: observation_id == second_id)
    with patcher:
        result = service.classify_pending(DOMAIN)
    assert state["failed"]
    assert (result.status, result.processed, result.classified) == ("NO_STORE", 1, 1)
    assert result.next_after_id == first_id
    assert result.outcomes == (ObservationOutcome(first_id, OUTCOME_CLASSIFIED, "ARRAIGO"),)
    assert topic_link(store, first_id) == [("ARRAIGO", "HASHTAG_EXACT")]
    assert topic_link(store, second_id) == []

    retry = producer(store).classify_pending(DOMAIN, after_id=result.next_after_id)
    assert (retry.status, retry.processed, retry.classified, retry.unmatched) == ("OK", 2, 1, 1)
    assert [item.observation_id for item in retry.outcomes] == [second_id, third_id]
    assert retry.next_after_id == third_id

    # Converges with an uninterrupted run over an identical temporary store.
    clean = tmp_path / "clean.db"
    build_store(clean)
    assert ingest(clean, posts).observation_ids == (first_id, second_id, third_id)
    full = producer(clean).classify_pending(DOMAIN)
    assert full.outcomes == result.outcomes + retry.outcomes
    for obs_id in (first_id, second_id, third_id):
        assert topic_link(store, obs_id) == topic_link(clean, obs_id)
    assert count(store, "ti_observation_topics") == count(clean, "ti_observation_topics") == 2
    assert [row[:4] for row in dump(store, ("ti_observation_domains",))["ti_observation_domains"]] == \
        [row[:4] for row in dump(clean, ("ti_observation_domains",))["ti_observation_domains"]]


def test_store_loss_while_resolving_hashtag_is_not_counted(store):
    posts = [("p1", day(0), ["arraigosocial"]), ("p2", day(0), []),
             ("p3", day(0), ["nacionalidadespanola"]), ("p4", day(0), ["#arraigo"])]
    ids = ingest(store, posts).observation_ids
    service = producer(store)
    # Distinct hashtags: the second resolve_topic call belongs to p3.
    patcher, state = fail_once_on(service.trend_service, "resolve_topic",
                                  lambda calls, *args, **kwargs: calls == 2)
    with patcher:
        result = service.classify_pending(DOMAIN)
    assert state["failed"]
    assert (result.status, result.processed, result.classified, result.unmatched) == ("NO_STORE", 2, 1, 1)
    assert result.next_after_id == ids[1]
    assert [item.observation_id for item in result.outcomes] == [ids[0], ids[1]]
    assert topic_link(store, ids[2]) == []

    retry = producer(store).classify_pending(DOMAIN, after_id=result.next_after_id)
    assert (retry.status, retry.processed, retry.classified, retry.exhausted) == ("OK", 2, 2, True)
    assert retry.outcomes == (ObservationOutcome(ids[2], OUTCOME_CLASSIFIED, "NACIONALIDAD"),
                              ObservationOutcome(ids[3], OUTCOME_CLASSIFIED, "ARRAIGO"))
    assert count(store, "ti_observation_topics") == 3
    again = producer(store).classify_pending(DOMAIN)
    assert (again.classified, again.already_classified, again.unmatched) == (0, 3, 1)


def test_non_store_errors_are_not_reported_as_no_store(store):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    service = producer(store)
    with patch.object(service.trend_service, "assign_observation_topic",
                      side_effect=RuntimeError("real failure")):
        with pytest.raises(RuntimeError):
            service.classify_pending(DOMAIN)


# --------------------------------------------- gate 8 · static contracts

FORBIDDEN_MODULES = ("sqlite3", "flet", "seleniumbase", "selenium", "socket", "requests",
                     "urllib", "http", "subprocess", "threading", "sched", "asyncio")
SQL_PATTERN = re.compile(
    r"\b(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
    r"CREATE\s+(TABLE|INDEX|TRIGGER|VIEW)|ALTER\s+TABLE|DROP\s+(TABLE|INDEX))\b",
    re.IGNORECASE | re.DOTALL,
)


def test_producer_has_no_sql_storage_ui_or_network():
    source = PRODUCER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not SQL_PATTERN.search(node.value), node.value
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"ensure_schema", "execute", "executescript", "connect", "_connection"}
    assert not {name for name in imported
                if name.split(".")[0] in FORBIDDEN_MODULES}
    assert "rwc" not in source
    # Only the lazy factory names the concrete SQLite repository.
    module_level = {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert not any("sqlite" in module for module in module_level)


def test_existing_only_connection_uses_mode_rw_helper():
    repo_source = (ROOT / "backend" / "repositories" / "sqlite_trend_intelligence_repository.py").read_text(encoding="utf-8")
    assert "rwc" not in repo_source
    assert "get_existing_connection(" in repo_source


def test_importing_producer_pulls_no_ui_browser_or_app():
    code = ("import sys, backend.trend_intelligence.producer as p;"
            "bad=[m for m in sys.modules if m.split('.')[0] in "
            "('flet','seleniumbase','selenium','main','app','frontend','requests')];"
            "print(bad)")
    output = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    assert output == "[]"


# TI-4C.3E3-G1: strict allowlist instead of a global ban. Only the producer
# itself, the manual CLI and ONE future application service may name the
# producer; that service may only classify (classify_pending), never run
# windows, and nothing may call it yet (E3A2 must widen the allowlist).
CLI_REL = "scripts/trend_producer_run.py"
POST_COLLECTION_REL = "backend/services/trend_post_collection_service.py"
PRODUCER_REL = "backend/trend_intelligence/producer.py"
RUN_SERVICE_REL = "backend/services/trend_producer_run_service.py"
PRODUCER_ALLOWLIST = frozenset({PRODUCER_REL, CLI_REL, POST_COLLECTION_REL})
POST_COLLECTION_ALLOWLIST = frozenset({POST_COLLECTION_REL, PRODUCER_REL})
POST_COLLECTION_CALLERS = frozenset()
GUARDED_FOLDERS = ("backend", "frontend", "database", "app", "scripts")

PRODUCER_TOKENS = ("trend_intelligence.producer", "create_trend_producer", "TrendProducerService")
# Split-string / relative-import disguises of the producer module or factory.
DISGUISED_FRAGMENTS = frozenset({"producer", ".producer", "producer.py", "create_trend", "create_trend_",
                                 "_trend_producer", "trend_producer", "_producer"})
DYNAMIC_IMPORT_NAMES = frozenset({"importlib", "__import__", "import_module", "runpy", "run_path",
                                  "run_module", "spec_from_file_location", "exec", "eval"})
# What the post-collection service may take from the producer module.
POST_COLLECTION_PRODUCER_IMPORTS = frozenset({
    "create_trend_producer", "DEFAULT_CLASSIFY_LIMIT", "MAX_CLASSIFY_LIMIT",
    "STATUS_OK", "STATUS_PARTIAL", "STATUS_NO_STORE", "STATUS_SCHEMA_INCOMPLETE", "STATUS_NO_DOMAIN",
    "STATUS_UNKNOWN_DOMAIN", "STATUS_DOMAIN_INACTIVE",
    "OUTCOME_CLASSIFIED", "OUTCOME_ALREADY_CLASSIFIED", "OUTCOME_UNMATCHED", "OUTCOME_AMBIGUOUS",
})
# Windows / snapshot phases and every path that bundles them.
POST_COLLECTION_FORBIDDEN_NAMES = frozenset({
    "process_windows", "process_window", "run_once", "TrendProducerRunService", "trend_producer_run_service",
    "TrendAutomaticPipelineService", "pipeline", "save_trend_snapshot", "trend_producer_run",
})
POST_COLLECTION_FORBIDDEN_MODULES = frozenset({
    "scripts", "frontend", "app", "main", "flet", "seleniumbase", "selenium", "sqlite3", "threading",
    "multiprocessing", "subprocess", "sched", "asyncio", "concurrent", "socket", "requests", "urllib", "http",
    "backend.trend_intelligence.pipeline", "backend.services.trend_producer_run_service",
})
ATTRIBUTE_BUILTINS = frozenset({"getattr", "setattr", "delattr", "hasattr"})


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def _guarded_sources():
    """(rel path, source) of every production-side module, tests excluded."""
    paths = [path for folder in GUARDED_FOLDERS for path in (ROOT / folder).rglob("*.py")]
    paths += list(ROOT.glob("*.py"))
    for path in sorted(set(paths)):
        rel = _rel(path)
        if rel.startswith("scripts/tests/") or "/__pycache__/" in rel:
            continue
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def _names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.alias):
            yield from node.name.split(".")
            if node.asname:
                yield node.asname


def _strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield ("." * node.level) + (node.module or "")


def _producer_imports(tree):
    """Names imported from the producer module, however spelled (abs/rel/module)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("trend_intelligence.producer"):
                    yield "<module>"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module.endswith("trend_intelligence.producer") or (node.level and module == "producer"):
                    yield alias.name
                elif module.endswith("trend_intelligence") and alias.name == "producer":
                    yield "<module>"
                elif node.level and not module and alias.name == "producer":
                    yield "<module>"


def _references(tree, module_token, name_prefix):
    """Imports of a module containing module_token, or names starting with name_prefix."""
    return (any(module_token in module for module in _imported_modules(tree))
            or any(name.startswith(name_prefix) or module_token in name for name in _names(tree)))


def producer_reference_violations(rel, source):
    """Reasons why `rel` may not reference the producer / trigger services."""
    if rel in (PRODUCER_REL, CLI_REL):
        return []  # The engine itself and the existing manual composition root.
    if rel == POST_COLLECTION_REL:
        return post_collection_service_violations(source)

    operator_script = rel.startswith("scripts/")
    reasons = [f"token:{token}" for token in PRODUCER_TOKENS if token in source]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Legacy one-off scripts/fixes may not parse; production code must.
        return reasons if operator_script else reasons + ["unparseable"]

    strings = [value.strip() for value in _strings(tree)]
    reasons += [f"string:{token}" for token in PRODUCER_TOKENS if any(token in value for value in strings)]
    reasons += [f"import:{name}" for name in _producer_imports(tree)]
    reasons += [f"fragment:{value.lower()}" for value in strings if value.lower() in DISGUISED_FRAGMENTS]
    # Operator scripts legitimately load sibling dev fixtures by path.
    dynamic = not operator_script and bool(set(_names(tree)) & DYNAMIC_IMPORT_NAMES)
    if dynamic and any(marker in value.lower() for value in strings if not re.search(r"\s", value)
                       for marker in ("producer", "trend_intelligence", "trend_post_collection")):
        reasons.append("dynamic-import")

    if rel not in POST_COLLECTION_ALLOWLIST | POST_COLLECTION_CALLERS and _references(
            tree, "trend_post_collection_service", "TrendPostCollection"):
        reasons.append("caller:trend_post_collection_service")

    # The bundled classify+windows service stays reachable only from scripts/ (CLI).
    if rel != RUN_SERVICE_REL and not rel.startswith("scripts/") and _references(
            tree, "trend_producer_run", "TrendProducerRun"):
        reasons.append("caller:trend_producer_run")
    return reasons


def post_collection_service_violations(source):
    """The single authorized exception: governed classify_pending only."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["unparseable"]

    reasons = []
    names = set(_names(tree))
    strings = list(_strings(tree))
    reasons += [f"forbidden-name:{name}" for name in sorted(names & POST_COLLECTION_FORBIDDEN_NAMES)]
    reasons += [f"forbidden-string:{token}" for token in sorted(POST_COLLECTION_FORBIDDEN_NAMES)
                if any(token in value for value in strings)]
    reasons += [f"dynamic:{name}" for name in sorted(names & DYNAMIC_IMPORT_NAMES)]
    reasons += [f"module:{module}" for module in sorted(set(_imported_modules(tree)))
                if module.startswith(".") or any(module == bad or module.startswith(bad + ".")
                                                 for bad in POST_COLLECTION_FORBIDDEN_MODULES)]
    reasons += [f"producer-import:{name}" for name in _producer_imports(tree)
                if name not in POST_COLLECTION_PRODUCER_IMPORTS]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ATTRIBUTE_BUILTINS:
            attr = node.args[1] if len(node.args) > 1 else None
            if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)) \
                    or attr.value in POST_COLLECTION_FORBIDDEN_NAMES or attr.value.startswith("_"):
                reasons.append(f"dynamic-attribute:{node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr in {"__dict__", "__getattribute__"}:
            reasons.append(f"dynamic-attribute:{node.attr}")
    return reasons


def test_no_production_trigger_references_producer():
    hits = {rel: reasons for rel, source in _guarded_sources()
            if (reasons := producer_reference_violations(rel, source))}
    assert hits == {}


GOVERNED_INJECTED = '''
from backend.trend_intelligence.process_lock import ProcessLockBusy, acquire_process_lock


class TrendPostCollectionService:
    def __init__(self, producer_factory):
        self.producer_factory = producer_factory

    def classify_after_collection(self, db_path, domain_code, *, collection_ok, browser_closed):
        if not (collection_ok and browser_closed):
            return "SKIPPED"
        release = acquire_process_lock(db_path)
        try:
            return self.producer_factory(db_path).classify_pending(domain_code, after_id=0, limit=100)
        finally:
            release()
'''

GOVERNED_FACTORY = '''
from backend.trend_intelligence.producer import DEFAULT_CLASSIFY_LIMIT, create_trend_producer


def classify(db_path, domain_code):
    producer = create_trend_producer(db_path)
    if not callable(getattr(producer, "classify_pending", None)):
        raise ValueError("classify_pending")
    return producer.classify_pending(domain_code, limit=DEFAULT_CLASSIFY_LIMIT)
'''


@pytest.mark.parametrize("source", [GOVERNED_INJECTED, GOVERNED_FACTORY])
def test_guard_accepts_governed_post_collection_service(source):
    assert post_collection_service_violations(source) == []
    assert producer_reference_violations(POST_COLLECTION_REL, source) == []


@pytest.mark.parametrize("source,reason", [
    ("def f(p):\n    return p.process_windows('D', ['A'], 'x', 'y')\n", "forbidden-name:process_windows"),
    ("def f(p):\n    p.classify_pending('D')\n    p.process_windows('D', ['A'], 'x', 'y')\n",
     "forbidden-name:process_windows"),
    ("def f(p):\n    return getattr(p, 'process_' + 'windows')('D')\n", "dynamic-attribute:getattr"),
    ("def f(p):\n    return getattr(p, 'process_windows')('D')\n", "forbidden-string:process_windows"),
    ("def f(p):\n    return p.__dict__['x']\n", "dynamic-attribute:__dict__"),
    ("def f(p):\n    return p.pipeline.process_window()\n", "forbidden-name:process_window"),
    ("from backend.services.trend_producer_run_service import TrendProducerRunService\n",
     "module:backend.services.trend_producer_run_service"),
    ("def f(s):\n    return s.run_once()\n", "forbidden-name:run_once"),
    ("from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService\n",
     "module:backend.trend_intelligence.pipeline"),
    ("from backend.trend_intelligence.producer import TrendProducerService\n",
     "producer-import:TrendProducerService"),
    ("import backend.trend_intelligence.producer as p\n", "producer-import:<module>"),
    ("from backend.trend_intelligence import producer\n", "producer-import:<module>"),
    ("from ..trend_intelligence import producer\n", "module:..trend_intelligence"),
    ("import importlib\nm = importlib.import_module('backend.trend_intelligence.producer')\n",
     "dynamic:importlib"),
    ("m = __import__('backend.trend_intelligence.producer')\n", "dynamic:__import__"),
    ("exec('p.process_' + 'windows()')\n", "dynamic:exec"),
    ("import threading\n", "module:threading"),
    ("from frontend.views import x\n", "module:frontend.views"),
    ("from scripts import trend_producer_run\n", "module:scripts"),
    ("import sqlite3\n", "module:sqlite3"),
])
def test_guard_rejects_ungoverned_post_collection_service(source, reason):
    assert reason in post_collection_service_violations(source)
    assert reason in producer_reference_violations(POST_COLLECTION_REL, source)


@pytest.mark.parametrize("rel", [
    "backend/services/instagram_collector_control_service.py",
    "backend/services/other_service.py",
    "frontend/views/trend_view.py",
    "app/main_window.py",
    "database/migrate.py",
    "main.py",
    "scripts/dev/some_tool.py",
])
@pytest.mark.parametrize("source,reason", [
    ("from backend.trend_intelligence.producer import create_trend_producer\n",
     "token:trend_intelligence.producer"),
    ("from backend.trend_intelligence import producer\n", "import:<module>"),
    ("from backend.trend_intelligence import producer as p\np.create_trend_producer\n",
     "token:create_trend_producer"),
    ("import importlib\nm = importlib.import_module('backend.trend_intelligence' + '.producer')\n",
     "fragment:.producer"),
    ("import importlib\nm = importlib.import_module('backend.trend_intelligence.prod' 'ucer')\n",
     "string:trend_intelligence.producer"),
    ("import importlib\nname = 'backend.trend_intelligence.%s' % 'pro' 'ducer'\nimportlib.import_module(name)\n",
     "fragment:producer"),
    ("import importlib\nname = 'backend.trend_intelligence.%s' % 'prod'\nimportlib.import_module(name + 'ucer')\n",
     "dynamic-import"),
    ("f = getattr(__import__('backend.trend_intelligence', fromlist=['x']), 'pro' + 'ducer')\n",
     "dynamic-import"),
    ("from backend.services.trend_post_collection_service import TrendPostCollectionService\n",
     "caller:trend_post_collection_service"),
    ("import backend.services.trend_post_collection_service as s\n", "caller:trend_post_collection_service"),
    ("def hook(svc):\n    return svc.TrendPostCollectionService\n", "caller:trend_post_collection_service"),
    ("from backend.services.trend_producer_run_service import TrendProducerRunService\n",
     "caller:trend_producer_run"),
])
def test_guard_rejects_references_outside_allowlist(rel, source, reason):
    reasons = producer_reference_violations(rel, source)
    if rel.startswith("scripts/") and reason in ("caller:trend_producer_run", "dynamic-import"):
        # scripts/ is the operator domain: the CLI names the run service and dev
        # tools load fixtures by path; tokens, imports and fragments still apply.
        assert reason not in reasons
    else:
        assert reason in reasons, reasons


def test_guard_rejects_relative_producer_imports_inside_package():
    rel = "backend/trend_intelligence/batch.py"
    assert "import:create_trend_producer" in producer_reference_violations(
        rel, "from .producer import create_trend_producer\n")
    assert "import:<module>" in producer_reference_violations(rel, "from . import producer\n")


def test_guard_allowlist_is_exact_and_still_covers_real_tree():
    assert PRODUCER_ALLOWLIST == {PRODUCER_REL, CLI_REL, POST_COLLECTION_REL}
    assert POST_COLLECTION_CALLERS == frozenset()
    scanned = dict(_guarded_sources())
    # The authorized exception does not physically exist yet (E3A2).
    assert POST_COLLECTION_REL not in scanned
    assert {PRODUCER_REL, CLI_REL, "backend/services/instagram_collector_control_service.py"} <= set(scanned)
    assert any(rel.startswith("frontend/") for rel in scanned)
    assert not any(rel.startswith("scripts/tests/") for rel in scanned)
    # Unrelated identifiers that merely end in "_producer" are not flagged.
    assert producer_reference_violations("frontend/views/x.py", "traceability_task_producer = 1\n") == []


def test_factory_requires_explicit_path_and_does_no_io(tmp_path):
    for value in (None, "", "  "):
        with pytest.raises(ValueError):
            create_trend_producer(value)
    create_trend_producer(tmp_path / "x.db")
    assert list(tmp_path.iterdir()) == []

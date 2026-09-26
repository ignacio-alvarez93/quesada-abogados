"""Adversarial TI contracts on native temporary file-backed SQLite."""
from dataclasses import replace
from unittest.mock import patch
import sqlite3

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import SQLiteTrendIntelligenceRepository
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService
from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService
from backend.trend_intelligence.trend_history import TrendSnapshotService, TrendBacktestingService
from backend.trend_intelligence.regression import TrendRegressionGateService
from backend.trend_intelligence.aggregate_scoring import AggregateTrendScorer
from backend.trend_intelligence.advanced_detection import CrossSourceRecurrenceDetector
from backend.trend_intelligence.models import TrendTemporalMetric, TrendAggregateSignal

START = "2026-09-20T00:00:00+00:00"
END = "2026-09-21T00:00:00+00:00"
SCOPE = dict(domain_code="D", topic_key="T")
WINDOW = dict(**SCOPE, window_start=START, window_end=END)


@pytest.fixture
def env(tmp_path):
    repo = SQLiteTrendIntelligenceRepository(tmp_path / "native.db")
    core = TrendIntelligenceService(repository=repo)
    core.ensure_schema()
    core.ensure_schema()
    core.create_domain(code="D", name="Domain")
    core.create_topic(topic_key="T", name="Topic", domain_codes=("D",))
    core.create_source(code="S", name="Source", source_type="WEB", collection_mode="HTTP")
    temporal = TrendTemporalIntelligenceService(repo)
    pipeline = TrendAutomaticPipelineService(repository=repo, temporal_service=temporal)
    yield repo, core, temporal, pipeline
    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert repo.db_path.is_file()


def observe(env, *, source="S", observed=START, country=None, language=None, title="item", published=None):
    obs, created = env[1].record_observation(source_code=source, observation_type="ARTICLE",
        title=title, observed_at=observed, published_at=published, country=country, language=language)
    env[1].classify_observation(obs.id, **SCOPE)
    return obs, created


def metric(env, start=START, end=END, **kwargs):
    repo = env[0]
    return TrendTemporalMetric(id=None, domain_id=repo.get_domain_by_code("D").id,
        topic_id=repo.get_topic_by_key("T").id, window_start=start, window_end=end,
        observation_count=kwargs.pop("observation_count", 2), source_count=1, signal_count=0, **kwargs)


def signal(env, version="1"):
    m = metric(env)
    return TrendAggregateSignal(id=None, domain_id=m.domain_id, topic_id=m.topic_id,
        window_start=START, window_end=END, signal_type="CROSS_SOURCE", strength=90,
        confidence=1, detector_key="TEMPORAL_CROSS_SOURCE", detector_version=version, reason="test")


def state(repo):
    with repo._connection() as conn:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("ti_temporal_metrics", "ti_temporal_baselines", "ti_aggregate_signals", "ti_trend_snapshots")}


def test_offset_observation_window_identity(env):
    obs, _ = observe(env, observed="2026-09-20T02:00:00+02:00")
    assert obs.observed_at == START
    assert env[2].materialize_window(**WINDOW).observation_count == 1


def test_offset_content_deduplication(env):
    first, _ = observe(env, published="2026-09-20T02:00:00.123456+02:00")
    second, created = observe(env, published="2026-09-20T00:00:00.123456Z")
    assert not created
    assert first.id == second.id
    assert first.content_hash == second.content_hash


def test_microseconds_preserved(env):
    obs, _ = observe(env, observed="2026-09-20T02:00:00.123456+02:00")
    assert obs.observed_at == "2026-09-20T00:00:00.123456+00:00"


@pytest.mark.parametrize("start,end", [
    ("2026-09-20T00:00:00.9Z", "2026-09-20T00:00:00.1Z"),
    (START, START),
    ("2026-09-20T00:00:00.0000001Z", END),
])
def test_invalid_original_window_rejected(env, start, end):
    with pytest.raises(ValueError):
        env[2].materialize_window(**SCOPE, window_start=start, window_end=end)


def test_half_open_adjacent_windows(env):
    observe(env, observed=START, title="start")
    observe(env, observed=END, title="boundary")
    left = env[2].materialize_window(**WINDOW)
    right = env[2].materialize_window(**SCOPE, window_start=END, window_end="2026-09-22T00:00:00Z")
    assert (left.observation_count, right.observation_count) == (1, 1)


def test_fractional_half_open_boundary(env):
    observe(env, observed="2026-09-20T00:00:00.000001Z")
    m = env[2].materialize_window(**SCOPE, window_start=START, window_end="2026-09-20T00:00:00.000001Z")
    assert m.observation_count == 0


def test_canonical_direct_snapshot_lookup(env):
    env[3].process_window(**WINDOW)
    snapshot = TrendSnapshotService(repository=env[0], temporal_service=env[2]).materialize(
        **SCOPE, window_start="2026-09-20T02:00:00+02:00", window_end="2026-09-21T00:00:00Z")
    assert snapshot.window_start == START
    assert len(state(env[0])["ti_trend_snapshots"]) == 1


def test_raw_repository_canonical_identity(env):
    first = env[0].save_temporal_metric(metric(env, "2026-09-20T02:00:00+02:00", "2026-09-21T02:00:00+02:00"))
    second = env[0].save_temporal_metric(metric(env))
    assert first.id == second.id
    assert first.window_start == START


def test_raw_repository_invalid_timestamp(env):
    with pytest.raises(ValueError):
        env[0].save_temporal_metric(metric(env, "garbage"))


def test_future_baseline_excluded_with_legacy_offset(env):
    stored = env[0].save_temporal_metric(metric(env, "2026-09-18T00:00:00Z", "2026-09-19T00:00:00Z"))
    with sqlite3.connect(env[0].db_path) as conn:
        conn.execute("UPDATE ti_temporal_metrics SET window_end=? WHERE id=?", ("2026-09-19T23:30:00-02:00", stored.id))
    baseline = env[2].calculate_baseline(**SCOPE, reference_window_start=START, reference_window_end=END)
    assert baseline.sample_count == 0


@pytest.mark.parametrize("field,value,expected", [("country", " es ", "ES"), ("language", " ES ", "es")])
def test_locale_ingestion_canonical(env, field, value, expected):
    obs, _ = observe(env, **{field: value})
    assert getattr(obs, field) == expected


@pytest.mark.parametrize("country,language", [("FR", "es"), ("ES", "fr")])
def test_legacy_recalculate_locale_isolation(env, country, language):
    obs, _ = observe(env, country=country, language=language)
    env[1].create_signal(observation_id=obs.id, **SCOPE, signal_type="MENTION", strength=100, detected_at=START)
    trend = env[1].recalculate_trend(**WINDOW, country=" es ", language=" ES ")["trend"]
    assert trend.score == 0
    assert trend.signal_count == 0
    assert env[0].list_trend_evidence(trend.id) == []


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_blank_scope_intentionally_all_locales(env, blank):
    obs, _ = observe(env, country="FR", language="fr")
    env[1].create_signal(observation_id=obs.id, **SCOPE, signal_type="MENTION", strength=100, detected_at=START)
    trend = env[1].recalculate_trend(**WINDOW, country=blank, language=blank)["trend"]
    assert trend.signal_count == 1
    assert trend.score > 0


@pytest.mark.parametrize("method", ["save_temporal_metric", "save_temporal_baseline", "save_aggregate_signal", "reconcile_aggregate_signals", "save_trend_snapshot"])
@pytest.mark.parametrize("existing", [False, True])
def test_per_window_rollback_injected_failure(env, method, existing):
    if existing:
        env[3].process_window(**WINDOW)
    observe(env)
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", title="other")
    before = state(env[0])
    original = getattr(env[0], method)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        other = SQLiteTrendIntelligenceRepository(env[0].db_path)
        assert state(other) == before
        raise RuntimeError("injected publication failure")
    with patch.object(env[0], method, side_effect=fail), pytest.raises(RuntimeError):
        env[3].process_window(**WINDOW)
    assert state(env[0]) == before


def test_identical_replay_preserves_ids_and_timestamps(env):
    observe(env)
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", title="other")
    env[3].process_window(**WINDOW)
    before = state(env[0])
    first = env[3].replay_existing_windows(**SCOPE)
    second = env[3].replay_existing_windows(**SCOPE)
    assert first.signature == second.signature
    assert state(env[0]) == before
    assert before["ti_aggregate_signals"]


@pytest.mark.parametrize("reverse", [False, True])
def test_history_ties_use_business_fields(env, reverse):
    windows = [("2026-09-18T00:00:00Z", 3), ("2026-09-19T00:00:00Z", 7)]
    for start, count in windows[:: -1 if reverse else 1]:
        env[0].save_temporal_metric(metric(env, start, START, observation_count=count))
    m = metric(env)
    history = env[0].list_temporal_metrics_before(m.domain_id, m.topic_id, before_window_start=START)
    assert [h.observation_count for h in history] == [7, 3]


@pytest.mark.parametrize("distinct", [False, True])
def test_physical_source_diversity(env, distinct):
    for code, provider, url in [("A", " Example ", "HTTPS://EXAMPLE.COM:443/feed/"),
            ("B", "example", "https://other.example/feed" if distinct else "https://example.com/feed")]:
        env[1].create_source(code=code, name=code, source_type="WEB", collection_mode="HTTP", provider=provider, base_url=url)
        observe(env, source=code, title=code)
    result = env[3].process_window(**WINDOW)
    assert result.source_count == (2 if distinct else 1)
    assert ("CROSS_SOURCE" in result.signal_types) == distinct


def test_old_version_excluded_and_provenance_preserved(env):
    observe(env)
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", title="other")
    env[3].process_window(**WINDOW)
    old = state(env[0])["ti_aggregate_signals"]
    detector = env[3].automatic_signal_service.advanced_detector
    with patch.object(detector, "DETECTOR_VERSION", "2"):
        result = env[3].process_window(**WINDOW)
        first = state(env[0])
        env[3].replay_existing_windows(**SCOPE)
        assert state(env[0]) == first
    m = metric(env)
    rows = env[0].list_aggregate_signals(m.domain_id, m.topic_id)
    assert {s.detector_version for s in rows if s.signal_type == "CROSS_SOURCE"} == {"1", "2"}
    assert result.aggregate_signal_count < len(rows)
    assert set(old).issubset(set(state(env[0])["ti_aggregate_signals"]))
    assert TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE).passed


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["strength", "confidence"])
def test_nonfinite_signal_rejected(env, value, field):
    bad = replace(signal(env), **{field: value})
    with pytest.raises(ValueError):
        env[0].save_aggregate_signal(bad)
    with pytest.raises(ValueError):
        AggregateTrendScorer().calculate([bad])


@pytest.mark.parametrize("weights", [{"MENTION": -1}, {"MENTION": float("nan")}, {"MENTION": float("inf")}, {}, [], {"MENTION": 0}])
def test_invalid_scoring_configuration(weights):
    with pytest.raises(ValueError):
        AggregateTrendScorer(signal_weights=weights)


def test_incomplete_metric_only_gate(env):
    env[2].materialize_window(**WINDOW)
    gate = TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE)
    assert not gate.passed
    assert "INCOMPLETE_MATERIALIZATION" in gate.violations


@pytest.mark.parametrize("kind", ["duplicate", "future", "scope"])
def test_recurrence_rejects_malformed_history(env, kind):
    old = metric(env, "2026-09-18T00:00:00Z", "2026-09-19T00:00:00Z")
    history = [old, old] if kind == "duplicate" else [metric(env)] if kind == "future" else [replace(old, country="FR")]
    with pytest.raises(ValueError):
        CrossSourceRecurrenceDetector().detect(current_metric=metric(env), historical_metrics=history)


def test_reverse_processing_replay_matches_chronological(env):
    repo, _, temporal, pipeline = env
    windows = [("2026-09-18T00:00:00Z", "2026-09-19T00:00:00Z"),
        ("2026-09-19T00:00:00Z", START), (START, END)]
    for index, (start, end) in enumerate(windows):
        for count in range(index + 1):
            observe(env, observed=start, title=f"{index}-{count}")
    for start, end in reversed(windows):
        pipeline.process_window(**SCOPE, window_start=start, window_end=end)
    reverse_replay = pipeline.replay_existing_windows(**SCOPE)
    chronological = [pipeline.process_window(**SCOPE, window_start=start, window_end=end)
        for start, end in windows]
    assert reverse_replay.signature == pipeline._signature(chronological)
    assert pipeline.replay_existing_windows(**SCOPE).signature == reverse_replay.signature


def test_stale_signal_reconciliation_preserves_historical_versions(env):
    repo, _, _, pipeline = env
    historical = repo.save_aggregate_signal(signal(env, version="0"))
    stale = repo.save_aggregate_signal(signal(env))
    pipeline.process_window(**WINDOW)
    m = metric(env)
    rows = repo.list_aggregate_signals(m.domain_id, m.topic_id)
    assert [s.id for s in rows] == [historical.id]
    assert stale.id not in [s.id for s in rows]


def test_rollback_after_actual_stale_deletion(env):
    repo = env[0]
    repo.save_aggregate_signal(signal(env))
    before = state(repo)
    with patch.object(repo, "save_trend_snapshot", side_effect=RuntimeError("snapshot")), pytest.raises(RuntimeError):
        env[3].process_window(**WINDOW)
    assert state(repo) == before


def test_source_deletion_detected_by_gate(env):
    observe(env)
    env[3].process_window(**WINDOW)
    with sqlite3.connect(env[0].db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM ti_sources WHERE code='S'")
    gate = TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE)
    assert "STALE_TEMPORAL_METRIC" in gate.violations


def test_single_source_many_observations_has_no_diversity(env):
    for i in range(100):
        observe(env, title=f"item-{i}")
    result = env[3].process_window(**WINDOW)
    assert result.source_count == 1
    assert "CROSS_SOURCE" not in result.signal_types


def test_repository_locale_scope_identity(env):
    first = env[0].save_temporal_metric(metric(env, country=" es ", language=" ES "))
    second = env[0].save_temporal_metric(metric(env, country="ES", language="es"))
    assert first.id == second.id
    found = env[0].get_temporal_metric(first.domain_id, first.topic_id,
        window_start=START, window_end=END, country=" es ", language=" ES ")
    assert found == second


def test_legacy_equivalent_repository_write_retains_identity(env):
    stored = env[0].save_temporal_metric(metric(env))
    with sqlite3.connect(env[0].db_path) as conn:
        conn.execute("UPDATE ti_temporal_metrics SET window_start=?, window_end=? WHERE id=?",
            ("2026-09-20T02:00:00+02:00", "2026-09-21T02:00:00+02:00", stored.id))
    canonical = env[0].save_temporal_metric(metric(env))
    assert canonical.id == stored.id
    assert canonical.window_start == START
    assert len(state(env[0])["ti_temporal_metrics"]) == 1


def test_deterministic_latest_baseline(env):
    env[2].calculate_baseline(**SCOPE, reference_window_start=START, reference_window_end=END, lookback_windows=3)
    env[2].calculate_baseline(**SCOPE, reference_window_start=START, reference_window_end=END, lookback_windows=7)
    m = metric(env)
    latest = env[0].get_latest_temporal_baseline(m.domain_id, m.topic_id)
    assert latest.lookback_windows == 7


def test_signal_end_boundary_excluded(env):
    obs, _ = observe(env)
    env[1].create_signal(observation_id=obs.id, **SCOPE, signal_type="MENTION", strength=100, detected_at=END)
    result = env[1].recalculate_trend(**WINDOW)
    assert result["trend"].signal_count == 0
    assert env[2].materialize_window(**WINDOW).signal_count == 0


@pytest.mark.parametrize("kind", ["baseline", "signal", "snapshot"])
def test_other_repository_temporal_writes_canonical(env, kind):
    repo = env[0]
    env[3].process_window(**WINDOW)
    m = metric(env)
    if kind == "baseline":
        original = repo.get_latest_temporal_baseline(m.domain_id, m.topic_id)
        saved = repo.save_temporal_baseline(replace(original,
            reference_window_start="2026-09-20T02:00:00+02:00", reference_window_end="2026-09-21T00:00:00Z"))
        assert saved.reference_window_start == START
    elif kind == "signal":
        saved = repo.save_aggregate_signal(replace(signal(env), window_start="2026-09-20T02:00:00+02:00", window_end="2026-09-21T00:00:00Z"))
        assert saved.window_start == START
    else:
        original = repo.list_trend_snapshots(m.domain_id, m.topic_id)[0]
        saved = repo.save_trend_snapshot(replace(original,
            window_start="2026-09-20T02:00:00+02:00", window_end="2026-09-21T00:00:00Z"))
        assert saved.id == original.id
        assert saved.window_start == START


def test_overlapping_window_replay_has_deterministic_order(env):
    windows = [(START, END), (START, "2026-09-22T00:00:00Z"),
        ("2026-09-19T00:00:00Z", END)]
    for start, end in reversed(windows):
        env[3].process_window(**SCOPE, window_start=start, window_end=end)
    first = env[3].replay_existing_windows(**SCOPE)
    second = env[3].replay_existing_windows(**SCOPE)
    assert first.signature == second.signature
    assert [(w.window_start, w.window_end) for w in first.windows] == sorted(
        (w.window_start, w.window_end) for w in first.windows)
    assert TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE).passed


def test_signature_includes_detector_provenance(env):
    observe(env)
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", title="other")
    first = env[3].process_window(**WINDOW)
    with patch.object(env[3].automatic_signal_service.advanced_detector, "DETECTOR_VERSION", "2"):
        second = env[3].process_window(**WINDOW)
    assert first.score == second.score
    assert env[3]._signature([first]) != env[3]._signature([second])


def test_large_finite_weights_do_not_overflow(env):
    result = AggregateTrendScorer(signal_weights={"CROSS_SOURCE": 1e308}).calculate([signal(env)])
    assert result.score == 90


def test_missing_baseline_gate(env):
    env[3].process_window(**WINDOW)
    with sqlite3.connect(env[0].db_path) as conn:
        conn.execute("DELETE FROM ti_temporal_baselines")
    gate = TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE)
    assert "INCOMPLETE_MATERIALIZATION" in gate.violations


def test_blank_materialization_scope_is_distinct_from_locale_scope(env):
    observe(env, country="ES", language="es")
    env[3].process_window(**WINDOW, country=None, language=None)
    env[3].process_window(**WINDOW, country=" es ", language=" ES ")
    m = metric(env)
    assert len(env[0].list_trend_snapshots(m.domain_id, m.topic_id, country=None, language=None)) == 1
    assert len(env[0].list_trend_snapshots(m.domain_id, m.topic_id, country="ES", language="es")) == 1


def test_gate_respects_configured_scoring_weights(env):
    observe(env)
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", title="other")
    env[3].snapshot_service.scorer = AggregateTrendScorer(signal_weights={"CROSS_SOURCE": 0.1, "GROWTH": 5})
    env[3].process_window(**WINDOW)
    assert TrendRegressionGateService(repository=env[0], temporal_service=env[2]).run_scope(**SCOPE).passed


def test_fix2_stale_historical_baseline_is_rejected_without_writes(env):
    earlier = dict(**SCOPE, window_start="2026-09-19T00:00:00Z", window_end=START)
    env[3].process_window(**earlier)
    env[3].process_window(**WINDOW)
    observe(env, observed=earlier["window_start"])
    env[3].process_window(**earlier)
    m = metric(env)
    baseline = env[0].get_temporal_baseline(m.domain_id, m.topic_id,
        reference_window_start=START, reference_window_end=END)
    assert baseline.observation_mean == 0.0
    history = env[0].list_temporal_metrics_before(m.domain_id, m.topic_id,
        before_window_start=START, limit=baseline.lookback_windows)
    assert [h.observation_count for h in history] == [1]
    before = state(env[0])
    gate = TrendRegressionGateService(repository=env[0], temporal_service=env[2])
    result = gate.run_scope(**SCOPE)
    assert state(env[0]) == before
    assert not result.passed
    assert "STALE_TEMPORAL_BASELINE" in result.violations
    assert gate.run_scope(**SCOPE) == result


def test_fix2_exact_overlapping_audit_reproduction(env):
    windows = [("2026-09-18T00:00:00Z", START), ("2026-09-19T00:00:00Z", END)]
    observe(env, observed=windows[0][0])
    env[1].create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, source="B", observed=windows[0][0], title="other")
    for start, end in windows:
        env[3].process_window(**SCOPE, window_start=start, window_end=end)
    replay = env[3].replay_existing_windows(**SCOPE)
    backtest = TrendBacktestingService(repository=env[0], temporal_service=env[2]).run(**SCOPE)
    assert tuple(w.velocity for w in replay.windows) == (0.0, 0.0)
    assert tuple(w.score for w in replay.windows) == (45.1, 0.0)
    assert tuple(w.score for w in backtest.windows) == tuple(w.score for w in replay.windows)
    assert tuple(w.velocity for w in backtest.windows) == (0.0, 0.0)


@pytest.mark.parametrize("history,expected", [
    ([("18", "20", 70)], -40.0),  # Adjacent.
    ([("18", "21", 70)], 0.0),  # Overlapping; no eligible predecessor.
    ([("17", "19", 70)], -40.0),  # Gap.
    ([("16", "20", 60), ("17", "19", 70), ("18", "20", 80),
      ("19", "21", 90)], -50.0),  # End first, then start; skip overlap.
    ([], 0.0),
])
def test_fix2_backtest_predecessor_selection(env, history, expected):
    for start, end, strength in history + [("20", "22", 30)]:
        start, end = f"2026-09-{start}T00:00:00Z", f"2026-09-{end}T00:00:00Z"
        env[0].save_temporal_metric(metric(env, start, end))
        env[0].save_aggregate_signal(replace(signal(env), window_start=start, window_end=end, strength=strength))
    service = TrendBacktestingService(repository=env[0], temporal_service=env[2])
    result = service.run(**SCOPE)
    assert result.windows[-1].score == 30.0
    assert result.windows[-1].velocity == expected
    assert service.run(**SCOPE) == result


def test_fix2_predecessor_subsecond_and_offset_boundary(env):
    windows = [
        ("2026-09-19T00:00:00Z", "2026-09-20T02:00:00+02:00", 70),
        ("2026-09-19T12:00:00Z", "2026-09-20T00:00:00.000002Z", 90),
        ("2026-09-20T00:00:00.000001Z", END, 30),
    ]
    for start, end, strength in windows:
        env[0].save_temporal_metric(metric(env, start, end))
        env[0].save_aggregate_signal(replace(signal(env), window_start=start, window_end=end, strength=strength))
    result = TrendBacktestingService(repository=env[0], temporal_service=env[2]).run(**SCOPE)
    assert result.windows[-1].velocity == -40.0


@pytest.mark.parametrize("active,unused", [(1e-100, 1e308), (5e-324, 1.0),
    (1e308, 1.0), (1.15, 1e308)])
def test_fix2_active_weight_extremes_and_unused_weight(env, active, unused):
    result = AggregateTrendScorer(signal_weights={"CROSS_SOURCE": active, "GROWTH": unused}).calculate([signal(env)])
    assert result.score == 90.0
    assert result.weighted_signal_score == 90.0
    assert result == AggregateTrendScorer(signal_weights={"CROSS_SOURCE": active}).calculate([signal(env)])


@pytest.mark.parametrize("weights,expected", [
    ({"CROSS_SOURCE": 1e-100, "GROWTH": 1e308}, 20.0),
    ({"CROSS_SOURCE": 1e308, "GROWTH": 1e308}, 55.0),
    ({"CROSS_SOURCE": 5e-324, "GROWTH": 5e-324}, 55.0),
    ({"CROSS_SOURCE": 1.15, "GROWTH": 1.2}, 54.2553),
])
def test_fix2_mixed_active_weights(env, weights, expected):
    signals = [signal(env), replace(signal(env), signal_type="GROWTH", strength=20)]
    result = AggregateTrendScorer(signal_weights=weights).calculate(signals)
    assert result.weighted_signal_score == expected
    assert result.score == round(expected + 2.5, 4)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_fix2_nonfinite_unused_weight_rejected(env, value):
    with pytest.raises(ValueError):
        AggregateTrendScorer(signal_weights={"CROSS_SOURCE": 1.15, "GROWTH": value}).calculate([signal(env)])

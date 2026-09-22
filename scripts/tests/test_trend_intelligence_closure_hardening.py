"""Closure hardening: historical no-leak, backtest bounds, explainability, edge cases."""
from types import SimpleNamespace
import sqlite3

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import SQLiteTrendIntelligenceRepository
from backend.trend_intelligence.aggregate_scoring import AggregateTrendScorer
from backend.trend_intelligence.models import TrendAggregateSignal, TrendTemporalMetric
from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService
from backend.trend_intelligence.trend_history import TrendBacktestingService

SCOPE = dict(domain_code="D", topic_key="T")


def day(n):
    return f"2026-09-{n:02d}T00:00:00Z"


@pytest.fixture
def env(tmp_path):
    repo = SQLiteTrendIntelligenceRepository(tmp_path / "closure.db")
    core = TrendIntelligenceService(repository=repo)
    core.ensure_schema()
    core.create_domain(code="D", name="Domain")
    core.create_topic(topic_key="T", name="Topic", domain_codes=("D",))
    core.create_source(code="S", name="Source", source_type="WEB", collection_mode="HTTP")
    temporal = TrendTemporalIntelligenceService(repo)
    pipeline = TrendAutomaticPipelineService(repository=repo, temporal_service=temporal)
    backtest = TrendBacktestingService(repository=repo, temporal_service=temporal)
    yield repo, core, pipeline, backtest
    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def observe(env, observed, title, source="S"):
    obs, _ = env[1].record_observation(source_code=source, observation_type="ARTICLE",
        title=title, observed_at=observed)
    env[1].classify_observation(obs.id, **SCOPE)
    return obs


def seed_window(env, start, end, strength):
    repo = env[0]
    domain, topic = repo.get_domain_by_code("D"), repo.get_topic_by_key("T")
    repo.save_temporal_metric(TrendTemporalMetric(id=None, domain_id=domain.id, topic_id=topic.id,
        window_start=start, window_end=end, observation_count=2, source_count=1, signal_count=0))
    repo.save_aggregate_signal(TrendAggregateSignal(id=None, domain_id=domain.id, topic_id=topic.id,
        window_start=start, window_end=end, signal_type="CROSS_SOURCE", strength=strength,
        confidence=1, detector_key="TEMPORAL_CROSS_SOURCE", detector_version="1", reason="seed"))


def seed_series(env, strengths, first_day=17):
    for offset, strength in enumerate(strengths):
        seed_window(env, day(first_day + offset), day(first_day + offset + 1), strength)


def stub(signal_type="CROSS_SOURCE", strength=50, confidence=1, key="K", reason="r"):
    return SimpleNamespace(signal_type=signal_type, strength=strength, confidence=confidence,
        detector_key=key, detector_version="1", reason=reason)


# --- historical correctness -------------------------------------------------

def test_backtest_as_of_excludes_later_windows(env):
    seed_series(env, [70, 40, 90])
    full = env[3].run(**SCOPE)
    as_of = env[3].run(**SCOPE, as_of=day(19))
    assert as_of.windows == full.windows[:2]
    assert as_of.final_score == 40.0
    # Offset spelling of the same instant is inclusive of the boundary window.
    assert env[3].run(**SCOPE, as_of="2026-09-19T02:00:00+02:00") == as_of
    # One microsecond earlier cuts the boundary window.
    assert env[3].run(**SCOPE, as_of="2026-09-18T23:59:59.999999Z").window_count == 1


def test_backtest_as_of_result_ignores_future_data(env):
    seed_series(env, [70, 40])
    before = env[3].run(**SCOPE, as_of=day(19))
    seed_window(env, day(19), day(20), 100)
    assert env[3].run(**SCOPE, as_of=day(19)) == before


def test_backtest_limit_keeps_latest_windows_with_continuity(env):
    seed_series(env, [10, 50, 30, 80])
    full = env[3].run(**SCOPE)
    tail = env[3].run(**SCOPE, limit=2)
    assert tail.windows == full.windows[-2:]
    assert tail.window_count == 2
    assert tail.final_score == full.final_score == 80.0
    assert tail.windows[0].velocity == -20.0  # predecessor outside the tail still counts


def test_backtest_empty_scope_is_safe(env):
    result = env[3].run(**SCOPE)
    assert (result.window_count, result.peak_score, result.final_score, result.windows) == (0, 0.0, 0.0, ())
    assert env[3].run(**SCOPE, as_of=day(1)) == result


def test_snapshot_not_affected_by_later_windows(env):
    _, _, pipeline, _ = env
    observe(env, day(18), "a")
    observe(env, day(19), "b")
    pipeline.process_window(**SCOPE, window_start=day(18), window_end=day(19))
    first = pipeline.process_window(**SCOPE, window_start=day(19), window_end=day(20))
    for i in range(5):
        observe(env, day(20), f"late-{i}")
    pipeline.process_window(**SCOPE, window_start=day(20), window_end=day(21))
    again = pipeline.process_window(**SCOPE, window_start=day(19), window_end=day(20))
    assert again == first
    assert again.materialization_signature == first.materialization_signature


def test_snapshot_baseline_and_history_use_only_prior_windows(env):
    _, _, pipeline, _ = env
    for n, count in ((18, 1), (19, 2), (20, 9)):
        for i in range(count):
            observe(env, day(n), f"{n}-{i}")
    results = [pipeline.process_window(**SCOPE, window_start=day(n), window_end=day(n + 1)) for n in (18, 19, 20)]
    domain, topic = env[0].get_domain_by_code("D"), env[0].get_topic_by_key("T")
    snapshots = env[0].list_trend_snapshots(domain.id, topic.id)
    assert [s.baseline_observation_mean for s in snapshots] == [0.0, 1.0, 1.5]
    assert [r.observation_count for r in results] == [1, 2, 9]


def test_empty_window_is_dormant_and_replay_stable(env):
    _, _, pipeline, _ = env
    first = pipeline.process_window(**SCOPE, window_start=day(20), window_end=day(21))
    assert (first.score, first.status, first.observation_count, first.aggregate_signal_count) == (0.0, "DORMANT", 0, 0)
    assert pipeline.process_window(**SCOPE, window_start=day(20), window_end=day(21)) == first


def test_observation_at_window_end_belongs_to_next_window(env):
    _, _, pipeline, _ = env
    observe(env, day(21), "boundary")
    assert pipeline.process_window(**SCOPE, window_start=day(20), window_end=day(21)).observation_count == 0
    assert pipeline.process_window(**SCOPE, window_start=day(21), window_end=day(22)).observation_count == 1


def test_malformed_observation_timestamp_fails_safe(env):
    with pytest.raises(ValueError):
        env[1].record_observation(source_code="S", observation_type="ARTICLE", title="bad", observed_at="not-a-date")
    domain, topic = env[0].get_domain_by_code("D"), env[0].get_topic_by_key("T")
    stats = env[0].get_temporal_window_stats(domain.id, topic.id, window_start=day(1), window_end=day(30))
    assert stats["observation_count"] == 0


# --- scoring edge cases -----------------------------------------------------

def test_scoring_clamps_degenerate_metrics():
    scorer = AggregateTrendScorer()
    assert scorer.calculate([stub(strength=500, confidence=2)]).score == 100.0
    negative = scorer.calculate([stub(strength=-50)])
    assert (negative.score, negative.status, negative.signal_count) == (0.0, "DORMANT", 1)
    assert scorer.calculate([stub(strength=90, confidence=0)]).score == 0.0


def test_scoring_order_independent_and_repeatable():
    signals = [stub("GROWTH", 30, 0.7, "A"), stub("CROSS_SOURCE", 85, 0.9, "B"), stub("MENTION", 10, 1, "C")]
    expected = AggregateTrendScorer().calculate(signals)
    assert AggregateTrendScorer().calculate(list(reversed(signals))) == expected
    assert AggregateTrendScorer().calculate(iter(signals)) == expected


@pytest.mark.parametrize("prior", [float("nan"), float("inf"), "x"])
def test_scoring_rejects_malformed_prior(prior):
    with pytest.raises(ValueError):
        AggregateTrendScorer().calculate([stub()], prior_score=prior)


def test_empty_signals_velocity_reflects_prior():
    result = AggregateTrendScorer().calculate([], prior_score=42.5)
    assert (result.score, result.velocity, result.status, result.components) == (0.0, -42.5, "DORMANT", ())


# --- explainability ---------------------------------------------------------

def test_components_explain_the_score():
    result = AggregateTrendScorer().calculate([stub("GROWTH", 30, 0.7, "A", "grew"), stub("CROSS_SOURCE", 85, 0.9, "B", "wide")])
    assert [c["signal_type"] for c in result.components] == ["CROSS_SOURCE", "GROWTH"]
    assert sum(c["contribution"] for c in result.components) == pytest.approx(result.weighted_signal_score, abs=1e-3)
    assert {c["reason"] for c in result.components} == {"grew", "wide"}
    assert result.score == pytest.approx(result.weighted_signal_score + result.diversity_bonus, abs=1e-3)


def test_snapshot_persists_components_and_baseline_provenance(env):
    _, core, pipeline, _ = env
    core.create_source(code="B", name="B", source_type="WEB", collection_mode="HTTP")
    observe(env, day(20), "one")
    observe(env, day(20), "two", source="B")
    pipeline.process_window(**SCOPE, window_start=day(20), window_end=day(21))
    domain, topic = env[0].get_domain_by_code("D"), env[0].get_topic_by_key("T")
    metadata = env[0].list_trend_snapshots(domain.id, topic.id)[0].metadata
    assert "CROSS_SOURCE" in {c["signal_type"] for c in metadata["components"]}
    assert all(c["detector_key"] and c["detector_version"] for c in metadata["components"])
    assert metadata["baseline_sample_count"] == 0
    assert metadata["active_detector_versions"]["TEMPORAL_CROSS_SOURCE"]

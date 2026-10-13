import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.repositories.sqlite_trend_intelligence_repository import (
    ReadOnlyStoreUnavailable,
    SQLiteTrendIntelligenceReadOnlyLookup,
    SQLiteTrendIntelligenceRepository,
)
from backend.services.trend_intelligence_dashboard_service import (
    MAX_EXPLANATIONS,
    MAX_HISTORY,
    MAX_SNAPSHOTS,
    SETTINGS_KEY,
    TrendDashboardState,
    TrendIntelligenceDashboardService,
    create_crm_trend_dashboard,
)
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK, RUN_STATUS_FAILED
from backend.trend_intelligence.acquisition.provenance import build_provenance, with_provenance
from backend.trend_intelligence.models import TrendAggregateSignal
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService
from backend.trend_intelligence.trend_history import TrendSnapshotService

DOMAIN = "GENERIC_DOMAIN"
TOPICS = ("TOPIC_A", "TOPIC_B", "TOPIC_C", "TOPIC_D", "TOPIC_E")


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
    finally:
        conn.close()


def _create_config(path, settings):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS config_global (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        if settings is not None:
            conn.execute("INSERT OR REPLACE INTO config_global (key, value) VALUES (?, ?)",
                         (SETTINGS_KEY, json.dumps(settings)))
        conn.commit()
    finally:
        conn.close()


def _dashboard(path, **kwargs):
    return TrendIntelligenceDashboardService(
        settings=SQLiteTrendIntelligenceReadOnlyLookup(path),
        trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(path, readonly=True)),
        store_unavailable_errors=(ReadOnlyStoreUnavailable,),
        **kwargs,
    )


class _TempDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "trends.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _files(self):
        return sorted(p.name for p in Path(self.tmp.name).iterdir())


class DashboardPopulatedTest(_TempDb):
    def setUp(self):
        super().setUp()
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()
        self.service.create_domain(code=DOMAIN, name="Generic Domain")
        self.service.create_source(code="SOURCE_X", name="Source X", source_type="RSS",
                                   provider="FEEDLY", collection_mode="HTTP")
        temporal = TrendTemporalIntelligenceService(self.repository)
        snapshots = TrendSnapshotService(repository=self.repository, temporal_service=temporal)
        domain = self.repository.get_domain_by_code(DOMAIN)
        provenance = build_provenance(collector_key="RSS_COLLECTOR", collector_version="1.0",
                                      provider="FEEDLY", source_identity="feedly:source-x")
        for index, key in enumerate(TOPICS):
            self.service.create_topic(topic_key=key, name=f"Topic {key[-1]}", domain_codes=(DOMAIN,))
            topic = self.repository.get_topic_by_key(key)
            for day in ("2026-09-21", "2026-09-22"):
                start, end = f"{day}T00:00:00+00:00", f"{day}T23:59:59+00:00"
                observation, _ = self.service.record_observation(
                    source_code="SOURCE_X", observation_type="ARTICLE", external_id=f"{key}-{day}",
                    title=key, observed_at=f"{day}T08:00:00+00:00",
                    metadata=with_provenance(None, provenance))
                self.service.classify_observation(observation.id, domain_code=DOMAIN, topic_key=key)
                self.service.create_signal(observation_id=observation.id, domain_code=DOMAIN,
                                           topic_key=key, signal_type="MENTION", strength=50 + index,
                                           detected_at=f"{day}T08:00:00+00:00")
                temporal.materialize_window(domain_code=DOMAIN, topic_key=key,
                                            window_start=start, window_end=end)
                if index % 2 == 0:
                    temporal.calculate_baseline(domain_code=DOMAIN, topic_key=key,
                                                reference_window_start=start,
                                                reference_window_end=end, lookback_windows=3)
                self.repository.save_aggregate_signal(TrendAggregateSignal(
                    id=None, domain_id=domain.id, topic_id=topic.id, signal_type="RECURRENCE",
                    window_start=start, window_end=end, strength=40.0 + 10 * index, confidence=0.9,
                    detector_key="FIXTURE", detector_version="1", reason="fixture"))
                snapshots.materialize(domain_code=DOMAIN, topic_key=key,
                                      window_start=start, window_end=end)
        _create_config(self.db, {"enabled": False, "domain_code": DOMAIN})

    def test_ready_reuses_existing_snapshot_order_scores_and_explanations(self):
        state = _dashboard(self.db).state()
        self.assertEqual(state.status, "READY")
        self.assertEqual((state.domain_code, state.domain_name), (DOMAIN, "Generic Domain"))
        expected = self.service.list_domain_snapshots(DOMAIN, limit=MAX_SNAPSHOTS)
        self.assertEqual(len(expected), len(TOPICS))
        self.assertEqual([row.snapshot for row in state.rows], expected)
        self.assertEqual([r.snapshot.score for r in state.rows],
                         sorted((r.snapshot.score for r in state.rows), reverse=True))
        for index, row in enumerate(state.rows):
            self.assertEqual(row.topic.id, row.snapshot.topic_id)
            if index < MAX_EXPLANATIONS:
                self.assertEqual(row.explanation_status, "READY")
                self.assertEqual(row.explanation,
                                 self.service.explain_snapshot(row.snapshot, history_limit=MAX_HISTORY))
                self.assertEqual(row.explanation.score, row.snapshot.score)
                self.assertEqual([p.source_identity for p in row.explanation.provenance], ["feedly:source-x"])
                self.assertLessEqual(len(row.explanation.recurrence), MAX_HISTORY)
            else:
                self.assertEqual((row.explanation, row.explanation_status), (None, "NOT_REQUESTED"))

    def test_baseline_only_when_persisted(self):
        rows = {row.topic.topic_key: row for row in _dashboard(self.db).state().rows}
        for index, key in enumerate(TOPICS):
            if index % 2 == 0:
                self.assertEqual(rows[key].baseline_mean, rows[key].snapshot.baseline_observation_mean)
                self.assertIsInstance(rows[key].baseline_samples, int)
            else:
                self.assertEqual(rows[key].snapshot.baseline_observation_mean, 0.0)
                self.assertIsNone(rows[key].baseline_mean)
                self.assertIsNone(rows[key].baseline_samples)

    def test_partial_sources_reported_from_explainability(self):
        run = self.service.start_collector_run(source_code="SOURCE_X", collector_key="RSS_COLLECTOR",
                                               collector_version="1.0",
                                               started_at="2026-09-21T07:00:00+00:00")
        self.service.complete_collector_run(run, status=RUN_STATUS_FAILED, items_seen=1, items_accepted=0,
                                            items_rejected=1, error_classification=ERROR_NETWORK,
                                            error_message="upstream unreachable",
                                            completed_at="2026-09-21T07:00:05+00:00")
        state = _dashboard(self.db).state()
        self.assertEqual(state.partial_sources, ("SOURCE_X",))
        self.assertEqual(state.rows[0].explanation.partial_sources, ("SOURCE_X",))

    def test_reads_never_write_or_change_schema(self):
        before, schema = _digest(self.db), _schema(self.db)
        files = self._files()
        dashboard = _dashboard(self.db)
        for _ in range(3):
            self.assertEqual(dashboard.state().status, "READY")
        self.assertEqual(_digest(self.db), before)
        self.assertEqual(_schema(self.db), schema)
        self.assertEqual(self._files(), files)

    def test_every_connection_is_sqlite_mode_ro(self):
        real = sqlite3.connect
        targets = []

        def spy(target, *args, **kwargs):
            targets.append((str(target), kwargs.get("uri")))
            return real(target, *args, **kwargs)

        with patch("sqlite3.connect", side_effect=spy):
            self.assertEqual(_dashboard(self.db).state().status, "READY")
        self.assertTrue(targets)
        self.assertTrue(all(t.endswith("?mode=ro") and uri is True for t, uri in targets), targets)

    def test_no_network_during_state(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            self.assertEqual(_dashboard(self.db).state().status, "READY")

    def test_empty_domain_is_legitimate(self):
        self.service.create_domain(code="OTHER_DOMAIN", name="Other")
        _create_config(self.db, {"domain_code": "OTHER_DOMAIN"})
        state = _dashboard(self.db).state()
        self.assertEqual((state.status, state.domain_code, state.rows), ("EMPTY", "OTHER_DOMAIN", ()))

    def test_no_domain_states(self):
        for settings, reason in (({"domain_code": None}, "NOT_CONFIGURED"),
                                 ({"enabled": True}, "NOT_CONFIGURED"),
                                 ({"domain_code": "UNKNOWN"}, "NOT_REGISTERED")):
            _create_config(self.db, settings)
            state = _dashboard(self.db).state()
            self.assertEqual((state.status, state.reason, state.rows), ("NO_DOMAIN", reason, ()))

    def test_missing_settings_key_is_no_domain(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("DELETE FROM config_global")
        conn.commit()
        conn.close()
        self.assertEqual(_dashboard(self.db).state().status, "NO_DOMAIN")

    def test_invalid_settings_is_explicit_error(self):
        for raw in ("not json", "[]", json.dumps({"domain_code": 7}), json.dumps({"domain_code": " "})):
            conn = sqlite3.connect(str(self.db))
            conn.execute("UPDATE config_global SET value = ? WHERE key = ?", (raw, SETTINGS_KEY))
            conn.commit()
            conn.close()
            state = _dashboard(self.db).state()
            self.assertEqual((state.status, state.reason), ("ERROR", "INVALID_SETTINGS"))

    def test_file_removed_after_check_stays_missing(self):
        # Race: the store disappears between the schema probe and later reads.
        lookup = SQLiteTrendIntelligenceReadOnlyLookup(self.db)
        settings = Mock()

        def vanish(key, default=None):
            value = lookup.get_config(key, default)
            self.db.unlink()
            return value

        settings.get_config.side_effect = vanish
        dashboard = TrendIntelligenceDashboardService(
            settings=settings,
            trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(self.db, readonly=True)),
            store_unavailable_errors=(ReadOnlyStoreUnavailable,))
        self.assertEqual(dashboard.state().status, "NO_STORE")
        self.assertFalse(self.db.exists())
        self.assertEqual(self._files(), [])


class DashboardUnavailableStoreTest(_TempDb):
    def test_missing_database_stays_missing(self):
        state = _dashboard(self.db).state()
        self.assertEqual((state.status, state.rows), ("NO_STORE", ()))
        self.assertFalse(self.db.exists())
        self.assertEqual(self._files(), [])

    def test_missing_tables_stay_missing(self):
        _create_config(self.db, {"domain_code": DOMAIN})
        before, schema = _digest(self.db), _schema(self.db)
        state = _dashboard(self.db).state()
        self.assertEqual(state.status, "SCHEMA_INCOMPLETE")
        self.assertIn("ti_trend_snapshots", state.missing_tables)
        self.assertEqual(_digest(self.db), before)
        self.assertEqual(_schema(self.db), schema)

    def test_unexpected_failure_is_safe_error(self):
        trends = Mock()
        trends.repository.missing_tables.side_effect = RuntimeError("boom /secret/path")
        state = TrendIntelligenceDashboardService(settings=Mock(), trends=trends).state()
        self.assertEqual((state.status, state.reason, state.rows), ("ERROR", "READ_FAILED", ()))

    def test_default_factory_maps_missing_store_without_creating_it(self):
        with patch("backend.services.config_service.DB_PATH", self.db):
            dashboard = create_crm_trend_dashboard()
        self.assertEqual(dashboard.store_unavailable_errors, (ReadOnlyStoreUnavailable,))
        state = dashboard.state()
        self.assertEqual((state.status, state.reason, state.rows), ("NO_STORE", None, ()))
        self.assertFalse(self.db.exists())
        self.assertEqual(self._files(), [])

    def test_default_factory_keeps_schema_incomplete_without_mutation(self):
        _create_config(self.db, {"domain_code": DOMAIN})
        before, schema = _digest(self.db), _schema(self.db)
        with patch("backend.services.config_service.DB_PATH", self.db):
            dashboard = create_crm_trend_dashboard()
        self.assertEqual(dashboard.state().status, "SCHEMA_INCOMPLETE")
        self.assertEqual((_digest(self.db), _schema(self.db)), (before, schema))
        self.assertEqual(self._files(), ["trends.db"])

    def test_missing_store_without_injected_boundary_is_not_masked(self):
        # Without the composition root's boundary the service knows no store
        # exception, so a missing store stays a genuine read error.
        dashboard = TrendIntelligenceDashboardService(
            settings=SQLiteTrendIntelligenceReadOnlyLookup(self.db),
            trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(self.db, readonly=True)))
        state = dashboard.state()
        self.assertEqual((state.status, state.reason), ("ERROR", "READ_FAILED"))
        self.assertFalse(self.db.exists())


class _StoreGone(Exception):
    """Provider-neutral stand-in for a store-specific 'unavailable' error."""


class DashboardNeutralBoundaryTest(unittest.TestCase):
    def _fake(self):
        trends = Mock()
        trends.repository.missing_tables.return_value = ()
        trends.repository.get_domain_by_code.return_value = SimpleNamespace(code=DOMAIN, name="Generic")
        trends.list_domain_snapshots.return_value = [
            SimpleNamespace(topic_id=1, metadata=None, baseline_observation_mean=0.0)]
        trends.list_domain_topics.return_value = []
        trends.explain_snapshot.return_value = SimpleNamespace(partial_sources=())
        settings = Mock()
        settings.get_config.return_value = json.dumps({"domain_code": DOMAIN})
        return trends, settings

    def _state(self, trends, settings):
        return TrendIntelligenceDashboardService(settings=settings, trends=trends,
                                                 store_unavailable_errors=(_StoreGone,)).state()

    def test_injected_store_error_is_no_store_at_every_read(self):
        reads = {
            "missing_tables": lambda t, s: t.repository.missing_tables,
            "settings": lambda t, s: s.get_config,
            "get_domain_by_code": lambda t, s: t.repository.get_domain_by_code,
            "list_domain_snapshots": lambda t, s: t.list_domain_snapshots,
            "list_domain_topics": lambda t, s: t.list_domain_topics,
            # A store vanishing mid-explanation aborts the read instead of FAILED rows.
            "explain_snapshot": lambda t, s: t.explain_snapshot,
        }
        for name, read in reads.items():
            trends, settings = self._fake()
            read(trends, settings).side_effect = _StoreGone()
            self.assertEqual(self._state(trends, settings), TrendDashboardState("NO_STORE"), name)

    def test_other_errors_are_not_masked_as_no_store(self):
        for error in (RuntimeError("boom"), OSError("disk"), sqlite3.OperationalError("locked"),
                      ReadOnlyStoreUnavailable("not injected")):
            trends, settings = self._fake()
            trends.repository.missing_tables.side_effect = error
            state = self._state(trends, settings)
            self.assertEqual((state.status, state.reason), ("ERROR", "READ_FAILED"), error)
        trends, settings = self._fake()
        trends.explain_snapshot.side_effect = RuntimeError("boom")
        state = self._state(trends, settings)
        self.assertEqual((state.status, [r.explanation_status for r in state.rows]), ("READY", ["FAILED"]))

    def test_non_store_statuses_unchanged_with_boundary(self):
        trends, settings = self._fake()
        trends.repository.missing_tables.return_value = ("ti_trend_snapshots",)
        self.assertEqual(self._state(trends, settings).status, "SCHEMA_INCOMPLETE")
        trends, settings = self._fake()
        settings.get_config.return_value = None
        self.assertEqual(self._state(trends, settings).reason, "NOT_CONFIGURED")
        settings.get_config.return_value = "not json"
        self.assertEqual(self._state(trends, settings).reason, "INVALID_SETTINGS")
        trends, settings = self._fake()
        trends.repository.get_domain_by_code.return_value = None
        self.assertEqual(self._state(trends, settings).reason, "NOT_REGISTERED")
        trends, settings = self._fake()
        trends.list_domain_snapshots.return_value = []
        self.assertEqual(self._state(trends, settings).status, "EMPTY")
        trends, settings = self._fake()
        self.assertEqual(self._state(trends, settings).status, "READY")

    def test_service_module_has_no_top_level_repository_import(self):
        import ast
        source = Path(__file__).resolve().parents[2].joinpath(
            "backend", "services", "trend_intelligence_dashboard_service.py").read_text(encoding="utf-8")
        top_level = [n for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom))]
        names = [getattr(n, "module", None) or "" for n in top_level]
        names += [a.name for n in top_level for a in n.names]
        self.assertFalse([n for n in names if any(t in n.lower()
                                                  for t in ("sqlite", "repositor", "database"))], names)
        self.assertNotIn("ReadOnlyStoreUnavailable", source.split("def create_crm_trend_dashboard")[0])


class DashboardBoundsTest(unittest.TestCase):
    def _fake(self, count):
        trends = Mock()
        trends.repository.missing_tables.return_value = ()
        trends.repository.get_domain_by_code.return_value = SimpleNamespace(code=DOMAIN, name="Generic")
        trends.list_domain_snapshots.side_effect = lambda code, limit: [
            SimpleNamespace(topic_id=i, metadata=None, baseline_observation_mean=0.0)
            for i in range(min(count, limit))]
        trends.list_domain_topics.return_value = []
        trends.explain_snapshot.return_value = SimpleNamespace(partial_sources=())
        settings = Mock()
        settings.get_config.return_value = json.dumps({"domain_code": DOMAIN})
        return trends, settings

    def test_reads_are_bounded_and_not_n_plus_one(self):
        trends, settings = self._fake(100)
        state = TrendIntelligenceDashboardService(
            settings=settings, trends=trends, snapshot_limit=500, explanation_limit=50,
            history_limit=99).state()
        self.assertEqual(len(state.rows), MAX_SNAPSHOTS)
        trends.list_domain_snapshots.assert_called_once_with(DOMAIN, limit=MAX_SNAPSHOTS)
        trends.list_domain_topics.assert_called_once_with(DOMAIN, active_only=False)
        self.assertEqual(trends.explain_snapshot.call_count, MAX_EXPLANATIONS)
        for call in trends.explain_snapshot.call_args_list:
            self.assertEqual(call.kwargs, {"history_limit": MAX_HISTORY})
        self.assertEqual(trends.repository.get_domain_by_code.call_count, 1)

    def test_explanation_failure_keeps_snapshot_without_invented_data(self):
        trends, settings = self._fake(2)
        trends.explain_snapshot.side_effect = RuntimeError("boom")
        state = TrendIntelligenceDashboardService(settings=settings, trends=trends).state()
        self.assertEqual(state.status, "READY")
        self.assertEqual([r.explanation_status for r in state.rows], ["FAILED", "FAILED"])
        self.assertTrue(all(r.explanation is None and r.baseline_mean is None for r in state.rows))

    def test_construction_reads_nothing(self):
        trends, settings = Mock(), Mock()
        TrendIntelligenceDashboardService(settings=settings, trends=trends)
        self.assertEqual((trends.mock_calls, settings.mock_calls), ([], []))


class DashboardIsolationTest(unittest.TestCase):
    def test_settings_key_matches_collector_contract(self):
        from backend.services.instagram_collector_configuration_service import SETTINGS_KEY as COLLECTOR_KEY
        self.assertEqual(SETTINGS_KEY, COLLECTOR_KEY)

    def test_import_and_factory_do_not_load_browser_or_open_storage(self):
        code = (
            "import sqlite3, sys\n"
            "opened = []\n"
            "real = sqlite3.connect\n"
            "sqlite3.connect = lambda *a, **k: opened.append(a) or real(*a, **k)\n"
            "from backend.services.trend_intelligence_dashboard_service import create_crm_trend_dashboard\n"
            "create_crm_trend_dashboard()\n"
            # sources.instagram is the pure (re/dataclasses) adapter loaded by the
            # TI sources package; the browser stack and collector runtime must not load.
            "bad = [m for m in sys.modules if any(t in m.lower() for t in ("
            "'selenium', 'instagram_browser', 'backend.automation', 'instagram_collector'))]\n"
            "assert not bad, bad\n"
            "assert not opened, opened\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_factory_uses_readonly_repository(self):
        dashboard = __import__("backend.services.trend_intelligence_dashboard_service",
                               fromlist=["create_crm_trend_dashboard"]).create_crm_trend_dashboard()
        self.assertTrue(dashboard.trends.repository.readonly)
        self.assertIsInstance(dashboard.settings, SQLiteTrendIntelligenceReadOnlyLookup)


if __name__ == "__main__":
    unittest.main()

"""TI-4C.2A on-demand producer run: service + manual operator CLI.

Injected doubles and temporary SQLite stores (tmp_path, existing TI-4C.1
fixtures) only. No operational database, browser, network or scheduler.
"""
import ast
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import SQLiteTrendIntelligenceRepository
from backend.services.trend_producer_run_service import (
    MAX_CLASSIFY_BATCHES_HARD_CAP,
    STATUS_BUSY,
    STATUS_CLASSIFY_INCOMPLETE,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    TrendProducerRunService,
)
from backend.trend_intelligence.pipeline import TrendAutomaticPipelineService
from backend.trend_intelligence.producer import create_trend_producer
from scripts import trend_producer_run as cli
from scripts.tests.test_trend_intelligence_producer import (
    DAILY_COUNTS,
    DAY0,
    DOMAIN,
    NOW,
    build_store,
    count,
    digest,
    dump,
    ingest,
    seed_history,
    topic_link,
)
from scripts.tests.test_trend_intelligence_producer import (
    POST_COLLECTION_REL,
    PRODUCER_ALLOWLIST,
    RUN_SERVICE_REL,
    post_collection_service_violations,
    producer_reference_violations,
    test_no_production_trigger_references_producer as _producer_guard,
)

ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "backend" / "services" / "trend_producer_run_service.py"
CLI_PATH = ROOT / "scripts" / "trend_producer_run.py"


def clock():
    return NOW


def day(offset):
    return DAY0 + timedelta(days=offset)


def args(**overrides):
    values = dict(domain_code=DOMAIN, topic_keys=("ARRAIGO",), window_from=day(0), window_to=day(1))
    values.update(overrides)
    return values


# ---------------------------------------------------------------- doubles

def batch(status="OK", next_after_id=0, exhausted=True, processed=0, classified=0,
          already_classified=0, unmatched=0, ambiguous=0, missing_tables=()):
    return SimpleNamespace(status=status, next_after_id=next_after_id, exhausted=exhausted,
                           processed=processed, classified=classified,
                           already_classified=already_classified, unmatched=unmatched,
                           ambiguous=ambiguous, missing_tables=missing_tables)


def window_result(status="OK", ok=1, failed=0, not_attempted=0, skipped=0, windows=None,
                  invalid_topics=(), missing_tables=()):
    if windows is None:
        windows = tuple(
            SimpleNamespace(topic_key="ARRAIGO", window_start=day(0).isoformat(),
                            window_end=day(1).isoformat(), status="OK", error=None)
            for _ in range(ok)
        )
    return SimpleNamespace(status=status, ok=ok, failed=failed, not_attempted=not_attempted,
                           skipped=skipped, windows=windows, lookback_windows=7,
                           invalid_topics=invalid_topics, missing_tables=missing_tables)


class FakeProducer:
    def __init__(self, classifications=(), windows=None):
        self.calls = []
        self.classifications = list(classifications)
        self.windows = window_result() if windows is None else windows

    def classify_pending(self, domain_code, *, after_id=0, limit=100):
        self.calls.append(("classify", domain_code, after_id, limit))
        item = self.classifications.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def process_windows(self, domain_code, topic_keys, window_from, window_to, *, max_windows=28):
        self.calls.append(("windows", domain_code, tuple(topic_keys), window_from, window_to, max_windows))
        if isinstance(self.windows, BaseException):
            raise self.windows
        return self.windows


class ExplodingProducer:
    def classify_pending(self, *args, **kwargs):
        raise AssertionError("producer must not be called")

    def process_windows(self, *args, **kwargs):
        raise AssertionError("producer must not be called")


def service_for(producer):
    return TrendProducerRunService(producer, clock=clock)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "ti.db"
    build_store(path)
    return path


def real_service(path):
    return TrendProducerRunService(create_trend_producer(path, clock=clock), clock=clock)


# ------------------------------------------------ import / static contract

FORBIDDEN_MODULES = ("sqlite3", "flet", "seleniumbase", "selenium", "socket", "requests", "urllib",
                     "http", "subprocess", "sched", "asyncio", "concurrent", "multiprocessing",
                     "database", "frontend", "app", "main")
SQL_PATTERN = re.compile(
    r"\b(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
    r"CREATE\s+(TABLE|INDEX|TRIGGER|VIEW)|ALTER\s+TABLE|DROP\s+(TABLE|INDEX))\b",
    re.IGNORECASE | re.DOTALL,
)


def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def test_service_has_no_sql_storage_ui_producer_or_background_work():
    source = SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = _imports(tree)
    assert not {name for name in imported if name.split(".")[0] in FORBIDDEN_MODULES}
    assert not {name for name in imported if name.startswith("backend")}
    assert imported <= {"dataclasses", "datetime", "re", "threading"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not SQL_PATTERN.search(node.value), node.value
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"execute", "executescript", "connect", "ensure_schema", "Thread",
                                     "Timer", "ThreadPoolExecutor", "start_new_thread"}
            if isinstance(node.value, ast.Name) and node.value.id == "threading":
                assert node.attr == "Lock"
        elif isinstance(node, ast.Name):
            assert node.id not in {"open", "Path"}
    for token in ("trend_intelligence.producer", "create_trend_producer", "quesada.db", "fabric", "runner"):
        assert token not in source.lower()


def test_cli_static_contract():
    source = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = _imports(tree)
    forbidden = {"sqlite3", "flet", "seleniumbase", "selenium", "socket", "requests", "urllib", "http",
                 "subprocess", "threading", "sched", "asyncio", "concurrent", "multiprocessing"}
    assert not {name for name in imported if name.split(".")[0] in forbidden}
    # The producer is composed only lazily inside run(), never at module level.
    assert "backend.trend_intelligence.producer" in imported
    assert "backend.trend_intelligence.producer" not in {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert 'if __name__ == "__main__":' in source
    assert "fabric" not in source.lower() and "runner" not in source.lower()
    assert "load_config" not in source and "config_global" not in source


def test_importing_service_and_cli_does_no_io_nor_composition(tmp_path):
    code = (
        "import sys, os, backend.services.trend_producer_run_service, scripts.trend_producer_run;"
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        "('sqlite3','flet','seleniumbase','selenium','frontend','app','main','requests','database')"
        " or m=='backend.trend_intelligence.producer'];"
        "print(bad)"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    before = set(ROOT.iterdir())
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                               capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == "[]"
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []
    assert set(ROOT.iterdir()) == before


def test_constructor_validates_shape_and_performs_no_calls(tmp_path):
    with pytest.raises(ValueError):
        TrendProducerRunService(object())
    producer = FakeProducer()
    TrendProducerRunService(producer)
    assert producer.calls == []
    # Real lazy composition: constructing both performs no I/O.
    real_service(tmp_path / "absent.db")
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------- argument prevalidation

INVALID = [
    dict(domain_code=""), dict(domain_code=None), dict(domain_code="   "),
    dict(topic_keys="ARRAIGO"), dict(topic_keys=()), dict(topic_keys=None),
    dict(topic_keys=("ARRAIGO", "arraigo")), dict(topic_keys=("ARRAIGO", " ARRAIGO ")),
    dict(topic_keys=("!!!",)), dict(topic_keys=("ARRAIGO SOCIAL",)), dict(topic_keys=("",)),
    dict(topic_keys=(None,)), dict(topic_keys=("_ARRAIGO",)),
    dict(window_from=day(1), window_to=day(1)), dict(window_from=day(2), window_to=day(1)),
    dict(window_from=day(0).replace(tzinfo=None)),
    dict(window_from=day(0) + timedelta(hours=1)),
    dict(window_from=day(0) + timedelta(microseconds=1)),
    dict(window_from=datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=2)))),
    dict(window_from=day(0).isoformat()), dict(window_to=None),
    # The in-progress UTC day (NOW is 12:00 on day 13) is never processed.
    dict(window_to=day(14)), dict(window_from=day(13), window_to=day(14)),
    dict(after_id=-1), dict(after_id=True), dict(after_id="0"), dict(after_id=None), dict(after_id=1.0),
    dict(classify_limit=0), dict(classify_limit=201), dict(classify_limit=True),
    dict(max_classify_batches=0), dict(max_classify_batches=MAX_CLASSIFY_BATCHES_HARD_CAP + 1),
    dict(max_classify_batches=None), dict(max_classify_batches=float("inf")),
    dict(max_windows=0), dict(max_windows=29), dict(max_windows=False),
    dict(window_to=day(5), max_windows=4),
    dict(topic_keys=("ARRAIGO", "NACIONALIDAD"), window_to=day(13), max_windows=25),
    dict(topic_keys=("ARRAIGO", "NACIONALIDAD", "OTHER"), window_to=day(10)),
]


@pytest.mark.parametrize("overrides", INVALID)
def test_invalid_arguments_rejected_before_any_io(tmp_path, overrides):
    with pytest.raises(ValueError):
        service_for(ExplodingProducer()).run_once(**args(**overrides))
    with pytest.raises(ValueError):
        real_service(tmp_path / "absent.db").run_once(**args(**overrides))
    assert list(tmp_path.iterdir()) == []


def test_last_complete_utc_day_and_canonical_topics_accepted():
    producer = FakeProducer([batch()])
    result = service_for(producer).run_once(**args(topic_keys=(" arraigo ",), window_from=day(12),
                                                   window_to=day(13)))
    assert result.status == STATUS_OK
    assert result.topic_keys == ("ARRAIGO",)
    assert producer.calls[-1] == ("windows", DOMAIN, ("ARRAIGO",), day(12), day(13), 28)


# ------------------------------------------- ordering, cursor and limits

def test_classification_batches_then_windows_in_order():
    producer = FakeProducer([
        batch(next_after_id=10, exhausted=False, processed=5, classified=2, unmatched=3),
        batch(next_after_id=20, exhausted=False, processed=5, already_classified=5),
        batch(next_after_id=23, exhausted=True, processed=3, ambiguous=1, classified=2),
    ], windows=window_result(ok=4))
    result = service_for(producer).run_once(**args(after_id=7, classify_limit=5, window_to=day(4),
                                                   max_windows=4))
    assert [call[:4] for call in producer.calls[:3]] == [
        ("classify", DOMAIN, 7, 5), ("classify", DOMAIN, 10, 5), ("classify", DOMAIN, 20, 5)]
    assert producer.calls[3][0] == "windows" and len(producer.calls) == 4
    assert (result.status, result.after_id, result.next_after_id) == (STATUS_OK, 7, 23)
    assert (result.classify_batches, result.classify_exhausted) == (3, True)
    assert (result.processed, result.classified, result.already_classified,
            result.unmatched, result.ambiguous) == (13, 4, 5, 3, 1)
    assert (result.windows_attempted, result.windows_ok, result.failed_phase) == (True, 4, None)
    assert result.succeeded and not result.retryable


def test_batch_budget_exhausted_returns_incomplete_without_windows():
    producer = FakeProducer([batch(next_after_id=5, exhausted=False, processed=5),
                             batch(next_after_id=9, exhausted=False, processed=5)])
    result = service_for(producer).run_once(**args(max_classify_batches=2, classify_limit=5))
    assert result.status == STATUS_CLASSIFY_INCOMPLETE
    assert (result.next_after_id, result.classify_batches, result.classify_exhausted) == (9, 2, False)
    assert [call[0] for call in producer.calls] == ["classify", "classify"]
    assert not result.windows_attempted and result.retryable and not result.succeeded


@pytest.mark.parametrize("status", ["NO_STORE", "SCHEMA_INCOMPLETE", "UNKNOWN_DOMAIN",
                                    "DOMAIN_INACTIVE", "NO_DOMAIN"])
def test_classification_status_propagated_and_no_windows(status):
    producer = FakeProducer([batch(next_after_id=3, exhausted=False, processed=3),
                             batch(status=status, next_after_id=4, processed=1,
                                   missing_tables=("ti_x",) if status == "SCHEMA_INCOMPLETE" else ())])
    result = service_for(producer).run_once(**args())
    assert result.status == status != STATUS_OK
    assert (result.classification_status, result.failed_phase, result.next_after_id) == (status, "CLASSIFY", 4)
    assert result.processed == 4
    assert [call[0] for call in producer.calls] == ["classify", "classify"]
    assert not result.windows_attempted and not result.succeeded
    if status == "SCHEMA_INCOMPLETE":
        assert result.missing_tables == ("ti_x",)


@pytest.mark.parametrize("windows,expected", [
    (window_result(status="PARTIAL", ok=1, failed=1, not_attempted=2), STATUS_PARTIAL),
    (window_result(status="INVALID_TOPIC", ok=0, invalid_topics=("FOREIGN",)), "INVALID_TOPIC"),
    (window_result(status="NO_STORE", ok=0), "NO_STORE"),
    (window_result(status="SCHEMA_INCOMPLETE", ok=0, missing_tables=("ti_x",)), "SCHEMA_INCOMPLETE"),
    (window_result(status="OK", ok=0, skipped=1), STATUS_EMPTY),
])
def test_window_status_propagated_honestly(windows, expected):
    result = service_for(FakeProducer([batch()], windows=windows)).run_once(**args())
    assert result.status == expected
    assert result.windows_status == windows.status
    assert result.invalid_topics == windows.invalid_topics
    assert result.missing_tables == windows.missing_tables
    assert result.succeeded == (expected == STATUS_EMPTY)
    assert result.failed_phase == (None if expected == STATUS_EMPTY else "WINDOWS")


def test_exception_keeps_safe_cursor_and_releases_lock():
    producer = FakeProducer([batch(next_after_id=5, exhausted=False, processed=5),
                             RuntimeError("boom private text")])
    service = service_for(producer)
    result = service.run_once(**args())
    assert (result.status, result.next_after_id, result.failed_phase) == (STATUS_ERROR, 5, "CLASSIFY")
    assert result.error_type == "RuntimeError" and result.retryable
    assert [call[0] for call in producer.calls] == ["classify", "classify"]
    assert not service._lock.locked()

    producer.classifications = [batch(next_after_id=8)]
    producer.windows = RuntimeError("window boom")
    result = service.run_once(**args(after_id=5))
    assert (result.status, result.next_after_id, result.failed_phase) == (STATUS_ERROR, 8, "WINDOWS")
    assert result.classify_exhausted and result.windows_attempted
    assert not service._lock.locked()


@pytest.mark.parametrize("phase", ["classify", "windows"])
def test_base_exceptions_propagate_and_release_lock(phase):
    if phase == "classify":
        producer = FakeProducer([KeyboardInterrupt()])
    else:
        producer = FakeProducer([batch()], windows=KeyboardInterrupt())
    service = service_for(producer)
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**args())
    assert not service._lock.locked()
    producer.classifications, producer.windows = [batch()], window_result()
    assert service.run_once(**args()).status == STATUS_OK


def test_concurrent_run_on_same_object_is_busy_without_blocking():
    entered, release = threading.Event(), threading.Event()

    class SlowProducer(FakeProducer):
        def classify_pending(self, domain_code, **kwargs):
            entered.set()
            assert release.wait(10)
            return super().classify_pending(domain_code, **kwargs)

    producer = SlowProducer([batch(next_after_id=4)])
    service = service_for(producer)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault("result", service.run_once(**args())))
    worker.start()
    try:
        assert entered.wait(10)
        busy = service.run_once(**args(after_id=3))
        assert (busy.status, busy.next_after_id, busy.after_id) == (STATUS_BUSY, 3, 3)
        assert busy.retryable and not busy.windows_attempted
        # Invalid arguments are still rejected while busy.
        with pytest.raises(ValueError):
            service.run_once(**args(after_id=-1))
        # Exclusion is per service object only (no cross-process claim).
        other = service_for(FakeProducer([batch()]))
        assert other.run_once(**args()).status == STATUS_OK
    finally:
        release.set()
        worker.join(10)
    assert outcome["result"].status == STATUS_OK
    assert [call[0] for call in producer.calls] == ["classify", "windows"]
    assert not service._lock.locked()


# ------------------------------------------- real temporary SQLite stores

def test_real_run_feeds_windows_and_preserves_source(store):
    report = seed_history(store)
    before = dump(store)
    result = real_service(store).run_once(**args(topic_keys=("ARRAIGO", "NACIONALIDAD"),
                                                 window_to=day(9), classify_limit=200, max_windows=18))
    assert (result.status, result.windows_ok, result.windows_failed) == (STATUS_OK, 18, 0)
    assert result.classified == sum(DAILY_COUNTS) + len(DAILY_COUNTS)
    assert result.next_after_id == report.observation_ids[-1]
    assert result.lookback_windows == 7
    after = dump(store)
    assert after["ti_observations"] == before["ti_observations"]
    assert after["ti_observation_domains"] == before["ti_observation_domains"]
    repo = SQLiteTrendIntelligenceRepository(store, readonly=True)
    for observation_id in report.observation_ids:
        assert [d.detection_method for d in repo.list_observation_domains(observation_id)] == ["SOURCE"]
        assert [method for _, method in topic_link(store, observation_id)] == ["HASHTAG_EXACT"]
    assert count(store, "ti_trend_snapshots") == 18


def test_real_cursor_limit_and_manual_resume_across_invocations(store):
    ids = ingest(store, [(f"p{i:02d}", day(0).isoformat(), ["arraigosocial"]) for i in range(25)]).observation_ids
    first = real_service(store).run_once(**args(classify_limit=5, max_classify_batches=2))
    assert (first.status, first.next_after_id, first.classified) == (STATUS_CLASSIFY_INCOMPLETE, ids[9], 10)
    assert count(store, "ti_observation_topics") == 10
    assert count(store, "ti_temporal_metrics") == count(store, "ti_trend_snapshots") == 0

    # New process-equivalent: fresh producer + service, cursor carried manually.
    resumed = real_service(store).run_once(**args(after_id=first.next_after_id, classify_limit=5,
                                                  max_classify_batches=MAX_CLASSIFY_BATCHES_HARD_CAP))
    assert (resumed.status, resumed.next_after_id, resumed.classified) == (STATUS_OK, ids[-1], 15)
    assert (resumed.classify_batches, resumed.windows_ok) == (4, 1)
    assert count(store, "ti_observation_topics") == 25
    settled = dump(store)

    # Restarting from 0 with the same small budget is not promised to finish.
    again = real_service(store).run_once(**args(classify_limit=5, max_classify_batches=2))
    assert (again.status, again.classified, again.already_classified) == (STATUS_CLASSIFY_INCOMPLETE, 0, 10)
    assert dump(store) == settled
    # Resuming from the last reported cursor is an idempotent no-op classification.
    final = real_service(store).run_once(**args(after_id=resumed.next_after_id))
    assert (final.status, final.processed, final.next_after_id) == (STATUS_OK, 0, ids[-1])


def test_real_partial_window_failure_then_retry(store):
    seed_history(store)
    original = TrendAutomaticPipelineService.process_window

    def fail_on_k(self, **kwargs):
        if kwargs["topic_key"] == "ARRAIGO" and kwargs["window_start"] == day(2).isoformat():
            raise RuntimeError("injected failure")
        return original(self, **kwargs)

    kwargs = args(topic_keys=("ARRAIGO", "NACIONALIDAD"), window_to=day(5), classify_limit=200,
                  max_windows=10)
    with patch.object(TrendAutomaticPipelineService, "process_window", autospec=True, side_effect=fail_on_k):
        partial = real_service(store).run_once(**kwargs)
    assert partial.status == STATUS_PARTIAL and partial.retryable
    assert (partial.windows_ok, partial.windows_failed, partial.windows_not_attempted) == (7, 1, 2)
    arraigo = [item.status for item in partial.windows if item.topic_key == "ARRAIGO"]
    assert arraigo == ["OK", "OK", "FAILED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]

    retry = real_service(store).run_once(**dict(kwargs, after_id=partial.next_after_id))
    assert (retry.status, retry.windows_ok, retry.windows_failed, retry.processed) == (STATUS_OK, 10, 0, 0)
    assert count(store, "ti_trend_snapshots") == 10


def test_real_absent_store_is_no_store_and_never_created(tmp_path):
    path = tmp_path / "absent.db"
    result = real_service(path).run_once(**args())
    assert (result.status, result.next_after_id, result.windows_attempted) == ("NO_STORE", 0, False)
    assert result.retryable and not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_real_incomplete_schema_reported_without_ddl(tmp_path):
    import sqlite3
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ti_domains (id INTEGER PRIMARY KEY, code TEXT)")
    conn.commit()
    conn.close()
    file_digest = digest(path)
    result = real_service(path).run_once(**args())
    assert result.status == "SCHEMA_INCOMPLETE"
    assert "ti_observation_topics" in result.missing_tables
    assert not result.windows_attempted
    assert digest(path) == file_digest


@pytest.mark.parametrize("domain_code,expected", [("NOT_REGISTERED", "UNKNOWN_DOMAIN"),
                                                  ("DORMANT_DOMAIN", "DOMAIN_INACTIVE")])
def test_real_domain_guards_never_write(store, domain_code, expected):
    ingest(store, [("p1", day(0).isoformat(), ["arraigosocial"])])
    file_digest = digest(store)
    result = real_service(store).run_once(**args(domain_code=domain_code))
    assert result.status == expected and not result.windows_attempted
    assert digest(store) == file_digest


def test_real_invalid_topic_and_empty_range(store):
    ingest(store, [("p1", day(0).isoformat(), ["arraigosocial"])])
    invalid = real_service(store).run_once(**args(topic_keys=("ARRAIGO", "FOREIGN", "MISSING")))
    assert invalid.status == "INVALID_TOPIC"
    assert invalid.invalid_topics == ("FOREIGN", "MISSING")
    assert count(store, "ti_trend_snapshots") == 0

    empty = real_service(store).run_once(**args(topic_keys=("NACIONALIDAD",), window_to=day(3)))
    assert (empty.status, empty.windows_ok, empty.windows_skipped) == (STATUS_EMPTY, 0, 3)
    assert empty.succeeded
    assert count(store, "ti_trend_snapshots") == 0


# --------------------------------------------------------------- CLI

def cli_args(path, *extra, topics=("ARRAIGO",), from_date="2026-10-01", to_date="2026-10-02"):
    argv = ["--db-path", str(path), "--domain-code", DOMAIN, "--from-date", from_date, "--to-date", to_date]
    for topic in topics:
        argv += ["--topic", topic]
    return argv + list(extra)


def no_composition():
    return patch("backend.trend_intelligence.producer.create_trend_producer",
                 side_effect=AssertionError("producer must not be composed"))


@pytest.mark.parametrize("argv", [
    [],
    ["--domain-code", DOMAIN, "--topic", "ARRAIGO", "--from-date", "2026-10-01", "--to-date", "2026-10-02",
     "--execute"],
    "relative",
    ["--db-path", "   ", "--domain-code", DOMAIN, "--topic", "ARRAIGO", "--from-date", "2026-10-01",
     "--to-date", "2026-10-02", "--execute"],
])
def test_cli_requires_explicit_absolute_db_path(tmp_path, argv):
    if argv == "relative":
        argv = cli_args("relative.db", "--execute")
    with no_composition():
        code, report = cli.run(argv)
    assert (code, report["status"], report["executed"]) == (2, "INVALID_ARGUMENTS", False)
    assert not Path("relative.db").exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extra,kwargs", [
    ((), dict(from_date="2026-10-1")),
    ((), dict(from_date="2026-10-01T00:00")),
    ((), dict(from_date="2026/10/01")),
    ((), dict(to_date="2999-01-01")),
    ((), dict(from_date="2026-10-02", to_date="2026-10-02")),
    ((), dict(topics=("ARRAIGO", "arraigo"))),
    ((), dict(topics=("ARRAIGO SOCIAL",))),
    (("--after-id", "-1"), {}),
    (("--after-id", "x"), {}),
    (("--classify-limit", "201"), {}),
    (("--max-classify-batches", "21"), {}),
    (("--max-windows", "29"), {}),
    (("--max-windows", "1"), dict(to_date="2026-10-03")),
])
def test_cli_invalid_arguments_rejected_before_io(tmp_path, extra, kwargs):
    path = tmp_path / "absent.db"
    with no_composition():
        code, report = cli.run(cli_args(path, "--execute", *extra, **kwargs))
    assert (code, report["status"]) == (2, "INVALID_ARGUMENTS")
    assert list(tmp_path.iterdir()) == []


def test_cli_requires_execute_and_touches_nothing(store, tmp_path):
    file_digest = digest(store)
    with no_composition():
        code, report = cli.run(cli_args(store))
        absent_code, _ = cli.run(cli_args(tmp_path / "absent.db"))
    assert (code, report["status"], report["executed"]) == (2, "EXECUTE_REQUIRED", False)
    assert absent_code == 2 and not (tmp_path / "absent.db").exists()
    assert report["request"]["window_from"] == "2026-10-01T00:00:00+00:00"
    assert "classification" not in report
    assert digest(store) == file_digest


def test_cli_known_operational_path_refused_without_opening():
    operational = ROOT / "database" / "quesada.db"
    existed = operational.exists()
    with no_composition():
        code, report = cli.run(cli_args(operational, "--execute"))
    assert (code, report["status"], report["executed"]) == (2, "OPERATIONAL_DB_REFUSED", False)
    assert operational.exists() == existed


def test_cli_operational_guard_not_bypassed_by_copy_name_and_requires_both_flags(tmp_path):
    path = tmp_path / "QUESADA.db"
    build_store(path)
    ingest(path, [("p1", day(0).isoformat(), ["arraigosocial"])])
    file_digest = digest(path)
    with no_composition():
        refused, report = cli.run(cli_args(path, "--execute"))
        not_executed, _ = cli.run(cli_args(path, "--allow-operational-db"))
    assert (refused, report["status"]) == (2, "OPERATIONAL_DB_REFUSED")
    assert not_executed == 2
    assert digest(path) == file_digest
    code, report = cli.run(cli_args(path, "--execute", "--allow-operational-db"))
    assert (code, report["status"], report["executed"]) == (0, "OK", True)


def test_cli_incomplete_then_manual_resume_from_report(store):
    ids = ingest(store, [(f"p{i:02d}", day(0).isoformat(), ["arraigosocial"]) for i in range(12)]).observation_ids
    code, report = cli.run(cli_args(store, "--execute", "--classify-limit", "5", "--max-classify-batches", "1"))
    assert (code, report["status"]) == (3, "CLASSIFY_INCOMPLETE")
    assert report["retry"] == {"recommended": True, "resume_after_id": ids[4]}
    assert report["windows"]["attempted"] is False
    code, report = cli.run(cli_args(store, "--execute", "--classify-limit", "5",
                                    "--after-id", str(report["retry"]["resume_after_id"])))
    assert (code, report["status"], report["classification"]["classified"]) == (0, "OK", 7)
    assert report["classification"]["next_after_id"] == ids[-1]


def test_cli_partial_is_failure_and_hides_error_messages(store):
    seed_history(store)
    original = TrendAutomaticPipelineService.process_window

    def fail(self, **kwargs):
        if kwargs["window_start"] == day(1).isoformat():
            raise RuntimeError("secret arraigosocial cuenta")
        return original(self, **kwargs)

    with patch.object(TrendAutomaticPipelineService, "process_window", autospec=True, side_effect=fail):
        code, report = cli.run(cli_args(store, "--execute", "--classify-limit", "200",
                                        to_date="2026-10-04"))
    assert (code, report["status"], report["failed_phase"]) == (1, "PARTIAL", "WINDOWS")
    assert report["retry"]["recommended"] is True
    items = report["windows"]["items"]
    assert [item["status"] for item in items] == ["OK", "FAILED", "NOT_ATTEMPTED"]
    assert items[1]["error_type"] == "RuntimeError"
    assert "secret" not in json.dumps(report)


def run_cli(*argv, cwd):
    completed = subprocess.run([sys.executable, str(CLI_PATH), *argv], cwd=cwd,
                               capture_output=True, text=True, timeout=120)
    return completed.returncode, completed.stdout, completed.stderr


def test_cli_subprocess_end_to_end_json_is_deterministic_and_safe(store, tmp_path):
    seed_history(store)
    argv = cli_args(store, "--execute", "--classify-limit", "200", "--max-windows", "18",
                    topics=("ARRAIGO", "NACIONALIDAD"), to_date="2026-10-10")
    code, stdout, stderr = run_cli(*argv, cwd=tmp_path)
    assert (code, stderr) == (0, "")
    report = json.loads(stdout)
    assert stdout == json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    assert (report["status"], report["executed"], report["contract"]) == (
        "OK", True, "TI4C2A_ON_DEMAND_PRODUCER_RUN_V1")
    assert report["date_semantics"] == "UTC_COLLECTION_DATE"
    assert report["windows"]["ok"] == 18 and report["windows"]["lookback_windows"] == 7
    assert report["classification"]["exhausted"] is True
    assert set(report["windows"]["items"][0]) == {"topic_key", "window_start", "window_end", "status",
                                                  "error_type"}
    for leaked in ("instagram.com", "cuenta", "run-1", "arraigosocial", "a0-0", str(store), "detected"):
        assert leaked.lower() not in stdout.lower()
    # Nothing is created next to the caller.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ti.db"]

    # Retry of the same range: idempotent, same windows, nothing reclassified.
    settled = dump(store)
    code, again, _ = run_cli(*argv, cwd=tmp_path)
    assert code == 0
    second = json.loads(again)
    assert second["windows"] == report["windows"]
    assert second["classification"]["classified"] == 0
    assert dump(store) == settled


def test_cli_subprocess_no_store_and_no_arguments(tmp_path):
    absent = tmp_path / "absent.db"
    code, stdout, _ = run_cli(*cli_args(absent, "--execute"), cwd=tmp_path)
    report = json.loads(stdout)
    assert (code, report["status"], report["executed"]) == (1, "NO_STORE", True)
    assert report["retry"]["resume_after_id"] == 0
    assert list(tmp_path.iterdir()) == []

    code, stdout, _ = run_cli(cwd=tmp_path)
    assert (code, json.loads(stdout)["status"]) == (2, "INVALID_ARGUMENTS")
    assert list(tmp_path.iterdir()) == []


# ----------------------------------------------------- guard regression
# TI-4C.3E3-G1: the git-diff immutability pin on the guard file is replaced by
# semantic checks of what the guard must keep enforcing.

def test_producer_guard_still_passes():
    _producer_guard()


@pytest.mark.parametrize("rel", [
    "backend/services/instagram_collector_control_service.py",
    "backend/services/trend_intelligence_dashboard_service.py",
    "frontend/views/trend_view.py",
    "app/trigger.py",
    "main.py",
])
def test_guard_still_rejects_producer_and_run_service_outside_allowlist(rel):
    for source in ("from backend.trend_intelligence.producer import create_trend_producer\n",
                   "from backend.trend_intelligence import producer\n",
                   "from backend.services.trend_producer_run_service import TrendProducerRunService\n",
                   "from backend.services.trend_post_collection_service import TrendPostCollectionService\n"):
        assert producer_reference_violations(rel, source), (rel, source)
    # The guarded tree includes the real Collector and the run service itself is clean.
    assert producer_reference_violations(RUN_SERVICE_REL, SERVICE_PATH.read_text(encoding="utf-8")) == []


def test_guard_keeps_the_single_exception_classification_only():
    assert PRODUCER_ALLOWLIST == {"backend/trend_intelligence/producer.py", "scripts/trend_producer_run.py",
                                  POST_COLLECTION_REL}
    governed = ("from backend.trend_intelligence.producer import create_trend_producer\n"
                "def classify(path, domain):\n"
                "    return create_trend_producer(path).classify_pending(domain)\n")
    assert post_collection_service_violations(governed) == []
    for windows in ("def f(p):\n    return p.process_windows('D', ['A'], 'x', 'y')\n",
                    "def f(s):\n    return s.run_once(domain_code='D')\n",
                    "def f(p):\n    return getattr(p, 'process_' + 'windows')()\n"):
        assert post_collection_service_violations(windows), windows


@pytest.mark.parametrize("window_to", [day(13), NOW, NOW + timedelta(days=1)])
def test_incomplete_utc_day_still_rejected_by_service_and_producer(tmp_path, window_to):
    # NOW is 2026-10-14T12:00Z: any window_to past it includes the in-progress day.
    service = TrendProducerRunService(ExplodingProducer(), clock=clock)
    if window_to == day(13):
        assert service.validate(**args(window_to=window_to)).window_to == day(13)
        return
    with pytest.raises(ValueError):
        service.validate(**args(window_to=window_to))
    with pytest.raises(ValueError):
        create_trend_producer(tmp_path / "absent.db", clock=clock).process_windows(
            DOMAIN, ["ARRAIGO"], day(0), window_to)
    assert list(tmp_path.iterdir()) == []


def test_cli_lock_is_the_shared_backend_lock_and_fails_closed():
    from backend.trend_intelligence import process_lock

    assert cli._acquire_process_lock is process_lock.acquire_process_lock
    assert cli._LockBusy is process_lock.ProcessLockBusy
    assert cli.LOCK_SCOPE == process_lock.LOCK_SCOPE == "SAME_USER_SAME_HOST"
    source = CLI_PATH.read_text(encoding="utf-8")
    body = source[source.index("def run(argv=None):"):source.index("def _lock_report(")]
    # validate -> --execute -> operational guard -> lock -> compose/open.
    order = [body.index(marker) for marker in (
        ".validate(**kwargs)", "if not args.execute", "_is_operational_db(resolved)",
        "_acquire_process_lock(resolved)", "create_trend_producer(resolved", "release_lock()")]
    assert order == sorted(order)
    assert "except _LockBusy:" in body and "STATUS_LOCK_ERROR" in body and "finally:" in body

"""TI-4C.3E3A2 post-collection classification service.

Temporary file-backed stores under tmp_path (existing ensure_schema fixture
path), synthetic posts and the REAL shared OS lock redirected to a temporary
per-user dir (LOCALAPPDATA / XDG_RUNTIME_DIR). Cross-process interop with the
manual CLI uses a child process that holds the CLI alias of the lock and is
synchronized by stdin/stdout, never by sleeping. No operational database,
browser, network or scheduler.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.services.trend_post_collection_service import (
    MAX_BATCHES_HARD_CAP,
    PostCollectionClassification,
    TrendPostCollectionService,
)
from backend.trend_intelligence import process_lock
from backend.trend_intelligence.producer import (
    ClassificationResult,
    ObservationOutcome,
    create_trend_producer,
)
from scripts.tests.test_trend_intelligence_producer import (
    DOMAIN,
    build_store,
    count,
    day,
    dump,
    ingest,
    topic_link,
)

ROOT = Path(__file__).resolve().parents[2]
SAFETY_TIMEOUT = 120
ANALYTICS_TABLES = ("ti_trend_snapshots", "ti_temporal_metrics", "ti_temporal_baselines", "ti_aggregate_signals")

# hold <db>: CLI alias takes the lock, prints HELD, waits for GO.
# probe <db>: CLI alias prints ACQUIRED or BUSY and releases.
HARNESS = r"""
import sys
from pathlib import Path
root, mode, db = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
from scripts import trend_producer_run as cli
try:
    release = cli._acquire_process_lock(Path(db).resolve())
except cli._LockBusy:
    print("BUSY")
    sys.exit(0)
if mode == "hold":
    sys.stdout.write("HELD\n")
    sys.stdout.flush()
    if sys.stdin.readline().strip() != "GO":
        sys.exit(9)
release()
print("ACQUIRED" if mode == "probe" else "RELEASED")
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    lock_root = tmp_path / "lockroot"
    lock_root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(lock_root))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(lock_root))
    data = tmp_path / "data"
    data.mkdir()
    return SimpleNamespace(lock_root=lock_root, data=data, db=data / "ti.db",
                           vars=dict(os.environ))


@pytest.fixture
def store(env):
    build_store(env.db)
    return env.db


def probe(db, env):
    completed = subprocess.run([sys.executable, "-c", HARNESS, str(ROOT), "probe", str(db)], env=env.vars,
                               cwd=env.data, capture_output=True, text=True, timeout=SAFETY_TIMEOUT)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


class CliHolder:
    def __init__(self, db, env):
        self.proc = subprocess.Popen([sys.executable, "-c", HARNESS, str(ROOT), "hold", str(db)], env=env.vars,
                                     cwd=env.data, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)

    def __enter__(self):
        line = self.proc.stdout.readline()
        assert line == "HELD\n", (line, self.proc.stderr.read() if self.proc.poll() is not None else "")
        return self

    def finish(self):
        stdout, stderr = self.proc.communicate("GO\n", timeout=SAFETY_TIMEOUT)
        assert (self.proc.returncode, stdout.strip(), stderr) == (0, "RELEASED", "")

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate(timeout=SAFETY_TIMEOUT)


def after_collection(service, db, ids, **kwargs):
    return service.classify_after_collection(db_path=db, domain_code=kwargs.pop("domain_code", DOMAIN),
                                             collection_ok=kwargs.pop("collection_ok", True),
                                             browser_closed=kwargs.pop("browser_closed", True),
                                             observation_ids=ids, **kwargs)


def assert_sanitized(result):
    text = json.dumps(result.projection())
    for leaked in ("instagram.com", "http", "/p/", "cuenta", "caption", "cookie", "password", "\\", "secret"):
        assert leaked not in text, leaked
    assert result.projection()["provisional"] is True
    assert result.projection()["trend_scoring"] == "NOT_COMPUTED"


def assert_no_analytics(db):
    for table in ANALYTICS_TABLES:
        assert count(db, table) == 0, table


def lock_is_free(db):
    release = process_lock.acquire_process_lock(Path(db).resolve())
    release()
    return True


class FakeProducer:
    """Scripted classify_pending results; any window call fails the test."""

    def __init__(self, results):
        self.results, self.calls = list(results), []

    def classify_pending(self, domain_code, *, after_id, limit):
        self.calls.append((domain_code, after_id, limit))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def process_windows(self, *args, **kwargs):
        raise AssertionError("ventanas prohibidas")


def batch(after_id, outcomes, *, status="OK", exhausted=True):
    counters = dict(classified=0, already_classified=0, unmatched=0, ambiguous=0)
    for item in outcomes:
        counters[item.outcome.lower()] += 1
    return ClassificationResult(status=status, domain_code=DOMAIN, after_id=after_id,
                                next_after_id=outcomes[-1].observation_id if outcomes else after_id,
                                processed=len(outcomes), exhausted=exhausted, outcomes=tuple(outcomes),
                                **counters)


# ------------------------------------------------ real store, real lock

def test_classifies_this_run_and_reports_sanitized_provisional_counts(store):
    ids = ingest(store, [
        ("exact", day(0), ["#ArraigoSocial"]),
        ("key", day(0), ["nacionalidad"]),
        ("ambiguous", day(0), ["arraigosocial", "nacionalidadespanola"]),
        ("unmatched", day(0), ["otra_cosa"]),
        ("no_tags", day(0), []),
    ]).observation_ids
    before = dump(store)
    result = after_collection(TrendPostCollectionService(), store, ids + ids[:1])

    assert (result.status, result.domain_code, result.exhausted, result.batches) == ("OK", DOMAIN, True, 1)
    assert (result.run_observations, result.run_classified, result.run_ambiguous, result.run_unmatched,
            result.run_not_reached) == (5, 2, 1, 2, 0)
    assert (result.scan_processed, result.scan_classified) == (5, 2)
    assert topic_link(store, ids[0]) == [("ARRAIGO", "HASHTAG_EXACT")]
    assert topic_link(store, ids[2]) == []
    after = dump(store)
    # Only topic links are written; observations and SOURCE domain links untouched.
    assert after["ti_observations"] == before["ti_observations"]
    assert after["ti_observation_domains"] == before["ti_observation_domains"]
    assert_no_analytics(store)
    assert_sanitized(result)
    projection = result.projection()
    assert projection["run"] == dict(observations=5, classified=2, already_classified=0, unmatched=2,
                                     ambiguous=1, not_reached=0)
    assert "topics" not in projection and "score" not in json.dumps(projection)
    assert lock_is_free(store)


def test_history_is_never_attributed_to_the_run(store):
    history = ingest(store, [("h1", day(0), ["arraigosocial"]), ("h2", day(0), ["nacionalidad"])]).observation_ids
    new = ingest(store, [("r1", day(1), ["arraigosocial"]), ("r2", day(1), [])]).observation_ids
    # The run re-saw h2 (duplicate) and collected r1/r2: h1 stays out of the walk.
    result = after_collection(TrendPostCollectionService(), store, (history[1],) + new)
    assert result.after_id == history[1] - 1
    assert (result.scan_processed, result.scan_classified) == (3, 2)
    assert (result.run_observations, result.run_classified, result.run_unmatched) == (3, 2, 1)
    assert topic_link(store, history[0]) == []

    # A second run that only collected r2 sees r1/h2 as scan, never as its own.
    again = after_collection(TrendPostCollectionService(), store, new[1:])
    assert (again.scan_processed, again.scan_already_classified, again.scan_unmatched) == (1, 0, 1)
    assert (again.run_observations, again.run_unmatched, again.run_classified) == (1, 1, 0)


def test_recovery_without_collection_is_idempotent(store):
    ids = ingest(store, [("a", day(0), ["arraigosocial"]), ("b", day(0), ["nacionalidadespanola"]),
                         ("c", day(0), [])]).observation_ids
    service = TrendPostCollectionService()
    first = service.reclassify_existing(db_path=store, domain_code=DOMAIN)
    assert (first.status, first.scan_classified, first.scan_unmatched, first.run_observations) == ("OK", 2, 1, 0)
    settled = dump(store)
    second = service.reclassify_existing(db_path=store, domain_code=DOMAIN)
    assert (second.scan_classified, second.scan_already_classified, second.scan_unmatched) == (0, 2, 1)
    assert dump(store) == settled
    run = after_collection(service, store, ids)
    assert (run.run_classified, run.run_already_classified, run.run_unmatched) == (0, 2, 1)
    assert dump(store) == settled
    assert_no_analytics(store)
    with pytest.raises(ValueError):
        service.reclassify_existing(db_path=store, domain_code=DOMAIN, after_id=-1)


def test_zero_posts_run(store):
    result = after_collection(TrendPostCollectionService(), store, ())
    assert (result.status, result.after_id, result.scan_processed, result.run_observations,
            result.run_not_reached, result.exhausted) == ("OK", 0, 0, 0, 0, True)
    assert_no_analytics(store)


def test_bounded_cursor_reports_incomplete_and_resumes(store):
    ids = ingest(store, [(f"p{i:02d}", day(0), ["arraigosocial"]) for i in range(25)]).observation_ids
    service = TrendPostCollectionService(limit=10, max_batches=2)
    result = after_collection(service, store, ids)
    assert (result.status, result.batches, result.exhausted) == ("INCOMPLETE", 2, False)
    assert (result.scan_processed, result.next_after_id) == (20, ids[19])
    assert (result.run_classified, result.run_not_reached) == (20, 5)
    rest = service.reclassify_existing(db_path=store, domain_code=DOMAIN, after_id=result.next_after_id)
    assert (rest.status, rest.scan_classified, rest.exhausted) == ("OK", 5, True)
    assert count(store, "ti_observation_topics") == 25


@pytest.mark.parametrize("kwargs", [dict(limit=0), dict(limit=201), dict(limit=True), dict(limit="5"),
                                    dict(max_batches=0), dict(max_batches=MAX_BATCHES_HARD_CAP + 1),
                                    dict(max_batches=1.0)])
def test_bounds_are_validated_at_construction(kwargs):
    with pytest.raises(ValueError):
        TrendPostCollectionService(**kwargs)


@pytest.mark.parametrize("domain_code,expected", [
    ("NOT_REGISTERED", "UNKNOWN_DOMAIN"), ("DORMANT_DOMAIN", "DOMAIN_INACTIVE"),
])
def test_producer_domain_statuses_are_published_without_writes(store, domain_code, expected):
    ingest(store, [("p1", day(0), ["arraigosocial"])])
    before = dump(store)
    result = after_collection(TrendPostCollectionService(), store, (1,), domain_code=domain_code)
    assert result.status == expected
    assert dump(store) == before


def test_absent_store_is_no_store_and_never_created(env):
    result = after_collection(TrendPostCollectionService(), env.db, (1,))
    assert (result.status, result.run_not_reached) == ("NO_STORE", 1)
    assert list(env.data.iterdir()) == []
    assert lock_is_free(env.db)


def test_incomplete_schema_is_reported(env):
    conn = sqlite3.connect(str(env.db))
    conn.execute("CREATE TABLE ti_domains (id INTEGER PRIMARY KEY, code TEXT)")
    conn.commit()
    conn.close()
    result = after_collection(TrendPostCollectionService(), env.db, ())
    assert result.status == "SCHEMA_INCOMPLETE"
    assert "ti_observation_topics" in result.projection()["missing_tables"]


# --------------------------------------------- preconditions, no I/O

@pytest.mark.parametrize("collection_ok,browser_closed", [
    (False, True), (True, False), (False, False), (1, True), (True, "yes"), (None, None),
])
def test_never_classifies_before_success_and_release(tmp_path, collection_ok, browser_closed):
    factory, lock = Mock(), Mock()
    service = TrendPostCollectionService(producer_factory=factory, lock=lock)
    result = after_collection(service, tmp_path / "ti.db", (1,), collection_ok=collection_ok,
                              browser_closed=browser_closed)
    assert result.status == "SKIPPED"
    factory.assert_not_called()
    lock.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("db_path,domain_code,expected", [
    ("relative/ti.db", DOMAIN, "INVALID_STORE"), ("", DOMAIN, "INVALID_STORE"), (None, DOMAIN, "INVALID_STORE"),
    ("ABS", None, "NO_DOMAIN"), ("ABS", "  ", "NO_DOMAIN"),
])
def test_invalid_store_or_missing_domain_take_no_lock(tmp_path, db_path, domain_code, expected):
    factory, lock = Mock(), Mock()
    service = TrendPostCollectionService(producer_factory=factory, lock=lock)
    path = tmp_path / "ti.db" if db_path == "ABS" else db_path
    assert after_collection(service, path, (), domain_code=domain_code).status == expected
    factory.assert_not_called()
    lock.assert_not_called()


@pytest.mark.parametrize("ids", [("1",), (0,), (-3,), (True,), (1.0,)])
def test_invalid_run_ids_rejected_before_lock(tmp_path, ids):
    lock = Mock()
    with pytest.raises(ValueError):
        after_collection(TrendPostCollectionService(producer_factory=Mock(), lock=lock), tmp_path / "x.db", ids)
    lock.assert_not_called()


# --------------------------------------------- lock: BUSY / fail closed

def test_cli_holding_same_canonical_store_yields_busy(store, env):
    before = dump(store)
    alias = env.data / ".." / "data" / "ti.db"  # Same canonical store, other spelling.
    factory = Mock(side_effect=AssertionError("no producer while BUSY"))
    with CliHolder(store, env) as holder:
        result = after_collection(TrendPostCollectionService(producer_factory=factory), alias, (1,))
        holder.finish()
    assert (result.status, result.batches) == ("BUSY", 0)
    factory.assert_not_called()
    assert dump(store) == before
    assert after_collection(TrendPostCollectionService(), alias, ()).status == "OK"


def test_service_holds_the_lock_while_classifying(store, env):
    seen = []

    def factory(path):
        assert path == store.resolve()
        seen.append(probe(store, env))
        return create_trend_producer(path)

    result = after_collection(TrendPostCollectionService(producer_factory=factory), store, ())
    assert (result.status, seen) == ("OK", ["BUSY"])
    assert probe(store, env) == "ACQUIRED"


def test_lock_released_when_producer_fails(store, env):
    producer = FakeProducer([RuntimeError("caption secreta https://www.instagram.com/p/x C:\\secret")])
    result = after_collection(TrendPostCollectionService(producer_factory=lambda path: producer), store, (5,))
    assert (result.status, result.error_type, result.run_not_reached) == ("ERROR", "RuntimeError", 1)
    assert_sanitized(result)
    assert probe(store, env) == "ACQUIRED"


def test_lock_released_when_factory_fails(store, env):
    def factory(path):
        raise OSError("C:\\secret")

    result = after_collection(TrendPostCollectionService(producer_factory=factory), store, ())
    assert (result.status, result.error_type) == ("ERROR", "OSError")
    assert probe(store, env) == "ACQUIRED"


def test_lock_preparation_error_fails_closed(store):
    def broken(path):
        raise PermissionError("C:/secret/path")

    factory = Mock()
    result = after_collection(TrendPostCollectionService(producer_factory=factory, lock=broken), store, (1,))
    assert (result.status, result.error_type) == ("LOCK_ERROR", "PermissionError")
    assert_sanitized(result)
    factory.assert_not_called()


def test_missing_per_user_lock_dir_fails_closed(store, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "relative")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "relative")
    monkeypatch.setenv("XDG_CACHE_HOME", "relative")
    before = dump(store)
    factory = Mock()
    result = after_collection(TrendPostCollectionService(producer_factory=factory), store, (1,))
    assert result.status == "LOCK_ERROR"
    factory.assert_not_called()
    assert dump(store) == before


# ------------------------------------------- producer contract (fakes)

def test_only_classify_pending_is_called_with_bounded_cursor(tmp_path):
    first = [ObservationOutcome(11, "CLASSIFIED", "ARRAIGO"), ObservationOutcome(12, "UNMATCHED")]
    second = [ObservationOutcome(13, "AMBIGUOUS"), ObservationOutcome(14, "ALREADY_CLASSIFIED")]
    producer = FakeProducer([batch(10, first, exhausted=False), batch(12, second)])
    lock_calls = []
    service = TrendPostCollectionService(producer_factory=lambda path: producer, limit=2,
                                         lock=lambda path: lock_calls.append(path) or (lambda: None))
    result = after_collection(service, tmp_path / "ti.db", (14, 11, 99))
    assert producer.calls == [(DOMAIN, 10, 2), (DOMAIN, 12, 2)]
    assert lock_calls == [(tmp_path / "ti.db").resolve()]
    assert (result.status, result.batches, result.next_after_id) == ("OK", 2, 14)
    assert (result.scan_processed, result.scan_classified, result.scan_unmatched, result.scan_ambiguous,
            result.scan_already_classified) == (4, 1, 1, 1, 1)
    assert (result.run_observations, result.run_classified, result.run_already_classified,
            result.run_not_reached) == (3, 1, 1, 1)


def test_store_loss_mid_walk_keeps_partial_counts_and_safe_cursor(tmp_path):
    lost = ClassificationResult(status="NO_STORE", domain_code=DOMAIN, after_id=12, next_after_id=12)
    producer = FakeProducer([batch(0, [ObservationOutcome(11, "CLASSIFIED", "A"),
                                       ObservationOutcome(12, "CLASSIFIED", "A")], exhausted=False), lost])
    service = TrendPostCollectionService(producer_factory=lambda path: producer, limit=2,
                                         lock=lambda path: (lambda: None))
    result = service.reclassify_existing(db_path=tmp_path / "ti.db", domain_code=DOMAIN)
    assert (result.status, result.batches, result.next_after_id, result.scan_classified) == ("NO_STORE", 2, 12, 2)


def test_result_type_and_projection_shape():
    projection = PostCollectionClassification("OK", DOMAIN).projection()
    assert set(projection) == {"status", "provisional", "trend_scoring", "domain_code", "cursor", "scan", "run",
                               "missing_tables", "error_type"}
    assert all(type(value) in (int, bool) for part in ("cursor", "scan", "run") for value in projection[part].values())


def test_import_is_inert():
    code = ("import sys, backend.services.trend_post_collection_service as s;"
            "bad=[m for m in sys.modules if m.split('.')[0] in "
            "('flet','seleniumbase','selenium','main','app','frontend','requests','scripts') "
            "or m.endswith('trend_producer_run_service')];"
            "print(bad)")
    output = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    assert output == "[]"

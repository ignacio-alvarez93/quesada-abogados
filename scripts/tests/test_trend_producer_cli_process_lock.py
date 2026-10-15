"""TI-4C.2B inter-process lock of the manual producer CLI.

Real processes (subprocess) over temporary SQLite files and stub producers
only; the per-user lock dir is redirected to a temporary directory through
LOCALAPPDATA / XDG_RUNTIME_DIR. Synchronization is event-driven (the holder
prints ENTERED and blocks on stdin), never sleep-based. No operational
database, browser, network or scheduler.
"""
import ast
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import trend_producer_run as cli
from scripts.tests.test_trend_intelligence_producer import (
    DOMAIN,
    build_store,
    test_no_production_trigger_references_producer as _producer_guard,
)

ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "scripts" / "trend_producer_run.py"
LOCK_SUBDIR = Path("quesada-abogados") / "locks" / "trend-producer"
# Safety net only (never used for synchronization).
SAFETY_TIMEOUT = 120
# SQLite busy_timeout the second process must NOT wait for.
SQLITE_BUSY_TIMEOUT_SECONDS = 30

# Child harness: real CLI module with a stub producer factory (no SQLite).
#   probe <db>  -> tries the same OS lock, prints ACQUIRED/BUSY, releases.
#   hold <argv> -> runs cli.run; inside classify prints ENTERED and blocks on stdin.
#   run <argv>  -> runs cli.run; reports composition and whether sqlite3 got loaded.
HARNESS = r"""
import json, sys, types
from pathlib import Path
from types import SimpleNamespace
root, mode, payload = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.path.insert(0, root)
from scripts import trend_producer_run as cli

if mode == "probe":
    try:
        release = cli._acquire_process_lock(Path(payload).resolve())
    except cli._LockBusy:
        print("BUSY")
    else:
        release()
        print("ACQUIRED")
    sys.exit(0)

composed = []

class Producer:
    def classify_pending(self, domain_code, *, after_id=0, limit=100):
        if mode == "hold":
            sys.stdout.write("ENTERED\n")
            sys.stdout.flush()
            if sys.stdin.readline().strip() != "GO":
                raise SystemExit(9)
        return SimpleNamespace(status="OK", next_after_id=after_id, exhausted=True, processed=0,
                               classified=0, already_classified=0, unmatched=0, ambiguous=0,
                               missing_tables=())

    def process_windows(self, domain_code, topic_keys, window_from, window_to, *, max_windows=28):
        return SimpleNamespace(status="OK", ok=0, failed=0, not_attempted=0, skipped=1, windows=(),
                               lookback_windows=7, invalid_topics=(), missing_tables=())

def create_trend_producer(path, clock=None):
    composed.append(1)
    return Producer()

fake = types.ModuleType("backend.trend_intelligence.producer")
fake.create_trend_producer = create_trend_producer
sys.modules["backend.trend_intelligence.producer"] = fake
code, report = cli.run(payload)
print(json.dumps({"code": code, "report": report, "composed": len(composed),
                  "sqlite3_loaded": "sqlite3" in sys.modules}))
"""


# ---------------------------------------------------------------- helpers

def cli_args(path, *extra, topics=("ARRAIGO",), from_date="2026-10-01", to_date="2026-10-02"):
    argv = ["--db-path", str(path), "--domain-code", DOMAIN, "--from-date", from_date, "--to-date", to_date]
    for topic in topics:
        argv += ["--topic", topic]
    return argv + list(extra)


def lock_env(lock_root):
    return dict(os.environ, LOCALAPPDATA=str(lock_root), XDG_RUNTIME_DIR=str(lock_root))


def harness(mode, payload, env, cwd, **kwargs):
    return [sys.executable, "-c", HARNESS, str(ROOT), mode, json.dumps(payload)], dict(
        env=env, cwd=cwd, text=True, **kwargs)


def probe(db_path, env, cwd):
    command, options = harness("probe", str(db_path), env, cwd)
    completed = subprocess.run(command, capture_output=True, timeout=SAFETY_TIMEOUT, **options)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def run_harness(argv, env, cwd):
    command, options = harness("run", argv, env, cwd)
    completed = subprocess.run(command, capture_output=True, timeout=SAFETY_TIMEOUT, **options)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def run_cli(argv, env, cwd):
    completed = subprocess.run([sys.executable, str(CLI_PATH), *argv], cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=SAFETY_TIMEOUT)
    return completed.returncode, completed.stdout, completed.stderr


class Holder:
    """Child process holding the lock inside classify_pending until released."""

    def __init__(self, argv, env, cwd):
        command, options = harness("hold", argv, env, cwd)
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, **options)

    def __enter__(self):
        line = self.proc.stdout.readline()
        assert line == "ENTERED\n", (line, self.proc.stderr.read() if self.proc.poll() is not None else "")
        return self

    def finish(self):
        stdout, stderr = self.proc.communicate("GO\n", timeout=SAFETY_TIMEOUT)
        assert (self.proc.returncode, stderr) == (0, "")
        return json.loads(stdout)

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate(timeout=SAFETY_TIMEOUT)


def make_sqlite(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO marker (value) VALUES ('x')")
    conn.commit()
    conn.close()
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_files(lock_root):
    return sorted(p for p in lock_root.rglob("*") if p.is_file())


@pytest.fixture
def env(tmp_path, monkeypatch):
    lock_root = tmp_path / "lockroot"
    lock_root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(lock_root))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(lock_root))
    data = tmp_path / "data"
    data.mkdir()
    work = tmp_path / "cwd"
    work.mkdir()
    return SimpleNamespace(lock_root=lock_root, data=data, cwd=work, vars=lock_env(lock_root))


def assert_safe(text, *secrets):
    for secret in secrets:
        assert str(secret).lower() not in text.lower()


# ------------------------------------------------- static / import contract

def test_cli_imports_lock_backends_lazily_and_adds_no_forbidden_modules():
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    top_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level.add(node.module)
    assert not top_level & {"msvcrt", "fcntl", "sqlite3", "threading", "subprocess", "multiprocessing"}
    assert {"errno", "hashlib"} <= top_level


def test_import_is_inert_no_lock_file_no_sqlite(env):
    code = ("import sys, scripts.trend_producer_run;"
            "print([m for m in ('sqlite3', 'backend.trend_intelligence.producer') if m in sys.modules])")
    completed = subprocess.run([sys.executable, "-c", code], cwd=env.cwd,
                               env=dict(env.vars, PYTHONPATH=str(ROOT)),
                               capture_output=True, text=True, check=True, timeout=SAFETY_TIMEOUT)
    assert (completed.stdout.strip(), completed.stderr) == ("[]", "")
    assert list(env.lock_root.iterdir()) == [] and list(env.cwd.iterdir()) == []


def test_cli_protocol_and_exit_codes_preserved():
    assert (cli.EXIT_OK, cli.EXIT_FAILURE, cli.EXIT_REFUSED, cli.EXIT_INCOMPLETE) == (0, 1, 2, 3)
    assert cli.CONTRACT == "TI4C2A_ON_DEMAND_PRODUCER_RUN_V1"
    parser_options = set()
    with patch.object(cli._Parser, "parse_args", lambda self, argv: parser_options.update(
            opt for action in self._actions for opt in action.option_strings)):
        cli._parse_args([])
    assert parser_options == {
        "-h", "--help", "--db-path", "--domain-code", "--topic", "--from-date", "--to-date", "--after-id",
        "--classify-limit", "--max-classify-batches", "--max-windows", "--execute", "--allow-operational-db"}


# ----------------------------------------- refusals happen before the lock

@pytest.mark.parametrize("name,extra,kwargs,status", [
    ("ti.db", ("--execute",), dict(from_date="2026/10/01"), "INVALID_ARGUMENTS"),
    ("ti.db", ("--execute", "--max-windows", "29"), {}, "INVALID_ARGUMENTS"),
    ("ti.db", (), {}, "EXECUTE_REQUIRED"),
    ("ti.db", ("--allow-operational-db",), {}, "EXECUTE_REQUIRED"),
    ("quesada.db", ("--execute",), {}, "OPERATIONAL_DB_REFUSED"),
])
def test_refusals_never_create_lock_nor_compose(env, name, extra, kwargs, status):
    path = env.data / name
    with patch("backend.trend_intelligence.producer.create_trend_producer",
               side_effect=AssertionError("producer must not be composed")):
        code, report = cli.run(cli_args(path, *extra, **kwargs))
    assert (code, report["status"], report["executed"]) == (2, status, False)
    assert list(env.lock_root.iterdir()) == []
    assert list(env.data.iterdir()) == []


def test_relative_db_path_rejected_before_lock(env):
    code, report = cli.run(cli_args("relative.db", "--execute"))
    assert (code, report["status"]) == (2, "INVALID_ARGUMENTS")
    assert list(env.lock_root.iterdir()) == []


def test_refusals_win_over_busy_while_lock_held(env):
    held = env.data / "quesada.db"
    with Holder(cli_args(held, "--execute", "--allow-operational-db"), env.vars, env.cwd) as holder:
        for argv, status in [
            (cli_args(held, "--execute", from_date="bad"), "INVALID_ARGUMENTS"),
            (cli_args(held), "EXECUTE_REQUIRED"),
            (cli_args(held, "--execute"), "OPERATIONAL_DB_REFUSED"),
        ]:
            code, stdout, stderr = run_cli(argv, env.vars, env.cwd)
            assert (code, json.loads(stdout)["status"], stderr) == (2, status, "")
        assert probe(held, env.vars, env.cwd) == "BUSY"
        assert holder.finish()["report"]["status"] == "EMPTY"
    assert not held.exists()


# ------------------------------------------------ two processes, same store

def test_same_store_second_process_busy_fast_without_db_io(env):
    db = make_sqlite(env.data / "ti.db")
    before = digest(db)
    with Holder(cli_args(db, "--execute"), env.vars, env.cwd) as holder:
        started = time.monotonic()
        code, stdout, stderr = run_cli(cli_args(db, "--execute"), env.vars, env.cwd)
        elapsed = time.monotonic() - started
        report = json.loads(stdout)
        assert (code, stderr) == (1, "")
        assert (report["status"], report["executed"], report["lock_scope"]) == ("BUSY", False, "SAME_USER_SAME_HOST")
        assert "classification" not in report and "windows" not in report
        assert stdout == json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        # Exits without waiting on SQLite's busy_timeout (no connection is ever opened).
        assert elapsed < SQLITE_BUSY_TIMEOUT_SECONDS
        key = hashlib.sha256(os.path.normcase(str(db.resolve())).encode("utf-8")).hexdigest()
        assert_safe(stdout, db, env.data, env.lock_root, key, "quesada-abogados")

        # Same, observed from inside the second process: never composed, sqlite3 never loaded.
        inner = run_harness(cli_args(db, "--execute"), env.vars, env.cwd)
        assert (inner["code"], inner["report"]["status"]) == (1, "BUSY")
        assert (inner["composed"], inner["sqlite3_loaded"]) == (0, False)
        assert probe(db, env.vars, env.cwd) == "BUSY"
        assert digest(db) == before

        finished = holder.finish()
    assert (finished["code"], finished["report"]["status"], finished["composed"]) == (0, "EMPTY", 1)
    assert sorted(p.name for p in env.data.iterdir()) == ["ti.db"]
    assert digest(db) == before
    assert probe(db, env.vars, env.cwd) == "ACQUIRED"


def test_busy_on_absent_store_does_not_create_it(env):
    absent = env.data / "absent.db"
    with Holder(cli_args(absent, "--execute"), env.vars, env.cwd) as holder:
        code, stdout, _ = run_cli(cli_args(absent, "--execute"), env.vars, env.cwd)
        assert (code, json.loads(stdout)["status"]) == (1, "BUSY")
        assert not absent.exists()
        holder.finish()
    assert list(env.data.iterdir()) == [] and list(env.cwd.iterdir()) == []


def test_non_canonical_alias_of_same_store_is_busy(env):
    db = make_sqlite(env.data / "ti.db")
    (env.data / "sub").mkdir()
    alias = env.data / "sub" / ".." / "ti.db"
    with Holder(cli_args(db, "--execute"), env.vars, env.cwd) as holder:
        assert probe(alias, env.vars, env.cwd) == "BUSY"
        code, stdout, _ = run_cli(cli_args(alias, "--execute"), env.vars, env.cwd)
        assert (code, json.loads(stdout)["status"]) == (1, "BUSY")
        holder.finish()


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive (normcase); "
                                            "POSIX case variants are distinct files")
def test_windows_case_variants_share_the_lock(env):
    db = make_sqlite(env.data / "ti.db")
    variant = Path(str(db).upper())
    with Holder(cli_args(db, "--execute"), env.vars, env.cwd) as holder:
        assert probe(variant, env.vars, env.cwd) == "BUSY"
        code, stdout, _ = run_cli(cli_args(variant, "--execute"), env.vars, env.cwd)
        assert (code, json.loads(stdout)["status"]) == (1, "BUSY")
        holder.finish()


def test_distinct_stores_do_not_block_each_other(env):
    first = make_sqlite(env.data / "a.db")
    other = env.data / "b.db"
    with Holder(cli_args(first, "--execute"), env.vars, env.cwd) as holder:
        assert probe(other, env.vars, env.cwd) == "ACQUIRED"
        inner = run_harness(cli_args(other, "--execute"), env.vars, env.cwd)
        assert (inner["code"], inner["report"]["status"], inner["composed"]) == (0, "EMPTY", 1)
        # Real CLI on the other (absent) store runs the producer: NO_STORE, not BUSY.
        code, stdout, _ = run_cli(cli_args(other, "--execute"), env.vars, env.cwd)
        assert (code, json.loads(stdout)["status"], json.loads(stdout)["executed"]) == (1, "NO_STORE", True)
        assert probe(first, env.vars, env.cwd) == "BUSY"
        holder.finish()
    assert not other.exists()
    assert len(lock_files(env.lock_root)) == 2


def test_abrupt_termination_releases_lock(env):
    db = make_sqlite(env.data / "ti.db")
    holder = Holder(cli_args(db, "--execute"), env.vars, env.cwd)
    with holder:
        assert probe(db, env.vars, env.cwd) == "BUSY"
        holder.proc.kill()  # TerminateProcess / SIGKILL: no finally runs.
        holder.proc.communicate(timeout=SAFETY_TIMEOUT)
        assert holder.proc.returncode != 0
    # The OS released it with the handles; no PID files nor manual cleanup.
    assert probe(db, env.vars, env.cwd) == "ACQUIRED"
    inner = run_harness(cli_args(db, "--execute"), env.vars, env.cwd)
    assert inner["report"]["status"] == "EMPTY"
    # The lock file may remain: harmless and reused.
    assert len(lock_files(env.lock_root)) == 1


# ------------------------------- release in finally for every outcome

def batch(status="OK", exhausted=True, next_after_id=0):
    return SimpleNamespace(status=status, next_after_id=next_after_id, exhausted=exhausted, processed=0,
                           classified=0, already_classified=0, unmatched=0, ambiguous=0, missing_tables=())


def windows(status="OK", ok=1, failed=0):
    return SimpleNamespace(status=status, ok=ok, failed=failed, not_attempted=0, skipped=0, windows=(),
                           lookback_windows=7, invalid_topics=(), missing_tables=())


OUTCOMES = {
    "OK": (batch(), windows(), (0, "OK")),
    "EMPTY": (batch(), windows(ok=0), (0, "EMPTY")),
    "PARTIAL": (batch(), windows("PARTIAL", ok=0, failed=1), (1, "PARTIAL")),
    "NO_STORE": (batch("NO_STORE", exhausted=False), None, (1, "NO_STORE")),
    "CLASSIFY_INCOMPLETE": (batch(exhausted=False), None, (3, "CLASSIFY_INCOMPLETE")),
    "ERROR": (RuntimeError("secret content"), None, (1, "ERROR")),
    "KEYBOARD_INTERRUPT": (KeyboardInterrupt(), None, KeyboardInterrupt),
    "FACTORY_RAISES": (None, None, RuntimeError),
}


@pytest.mark.parametrize("outcome", list(OUTCOMES))
def test_lock_held_through_both_phases_and_released_for_every_outcome(env, outcome):
    classified, windowed, expected = OUTCOMES[outcome]
    db = env.data / "ti.db"
    seen = []

    class Producer:
        def classify_pending(self, domain_code, *, after_id=0, limit=100):
            seen.append(("classify", probe(db, env.vars, env.cwd)))
            if isinstance(classified, BaseException):
                raise classified
            return classified

        def process_windows(self, *args, **kwargs):
            seen.append(("windows", probe(db, env.vars, env.cwd)))
            return windowed

    def factory(path, clock=None):
        if outcome == "FACTORY_RAISES":
            raise RuntimeError("factory boom")
        return Producer()

    argv = cli_args(db, "--execute", "--max-classify-batches", "1")
    with patch("backend.trend_intelligence.producer.create_trend_producer", side_effect=factory):
        if isinstance(expected, type):
            with pytest.raises(expected):
                cli.run(argv)
        else:
            code, report = cli.run(argv)
            assert (code, report["status"], report["executed"]) == (*expected, True)
            assert "secret" not in json.dumps(report)

    assert all(state == "BUSY" for _, state in seen)
    if outcome in ("OK", "EMPTY", "PARTIAL"):
        assert [phase for phase, _ in seen] == ["classify", "windows"]
    assert probe(db, env.vars, env.cwd) == "ACQUIRED"
    assert list(env.data.iterdir()) == []


# ---------------------------------------------------------- fail closed

def test_unusable_lock_dir_fails_closed_without_executing(env, tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    db = make_sqlite(env.data / "ti.db")
    before = digest(db)
    code, stdout, stderr = run_cli(cli_args(db, "--execute"), lock_env(blocker), env.cwd)
    report = json.loads(stdout)
    assert (code, stderr) == (1, "")
    assert (report["status"], report["executed"], report["lock_scope"]) == ("LOCK_ERROR", False, "SAME_USER_SAME_HOST")
    assert report["status"] != "BUSY" and "classification" not in report
    assert_safe(stdout, db, env.data, blocker, tmp_path)
    assert digest(db) == before


@pytest.mark.parametrize("value", ["", "relative/dir"])
def test_missing_or_relative_lock_base_fails_closed(env, monkeypatch, value):
    monkeypatch.setenv("LOCALAPPDATA", value)
    monkeypatch.setenv("XDG_RUNTIME_DIR", value)
    monkeypatch.setenv("XDG_CACHE_HOME", value)
    monkeypatch.setenv("HOME", value)
    with patch("backend.trend_intelligence.producer.create_trend_producer",
               side_effect=AssertionError("producer must not be composed")):
        code, report = cli.run(cli_args(env.data / "ti.db", "--execute"))
    assert (code, report["status"], report["executed"]) == (1, "LOCK_ERROR", False)
    assert list(env.data.iterdir()) == []
    assert not Path("relative").exists()


def test_platform_without_os_locking_fails_closed(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with patch("backend.trend_intelligence.producer.create_trend_producer",
               side_effect=AssertionError("producer must not be composed")):
        code, report = cli.run(cli_args(env.data / "ti.db", "--execute"))
    assert (code, report["status"], report["executed"]) == (1, "LOCK_ERROR", False)
    assert report["error"].startswith("No se pudo preparar el lock")
    assert "ModuleNotFoundError" in report["error"]
    assert list(env.data.iterdir()) == []


# ------------------------------------------------ lock file placement

def test_lock_file_is_private_hashed_and_outside_repo_and_store_dir(env):
    db = env.data / "ti.db"
    release = cli._acquire_process_lock(db.resolve())
    try:
        files = lock_files(env.lock_root)
        key = hashlib.sha256(os.path.normcase(str(db.resolve())).encode("utf-8")).hexdigest()
        assert files == [env.lock_root / LOCK_SUBDIR / f"{key}.lock"]
        assert "ti.db" not in str(files[0].relative_to(env.lock_root))
        assert ROOT not in files[0].parents
        assert list(env.data.iterdir()) == []
        if os.name != "nt":
            assert files[0].stat().st_mode & 0o077 == 0
            assert (env.lock_root / LOCK_SUBDIR).stat().st_mode & 0o077 == 0
    finally:
        release()


# --------------------------------------- real CLI over a real temp store

def test_real_cli_over_temporary_store_still_runs_and_releases(env):
    db = env.data / "ti.db"
    build_store(db)
    code, stdout, stderr = run_cli(cli_args(db, "--execute"), env.vars, env.cwd)
    report = json.loads(stdout)
    assert (code, stderr, report["status"], report["executed"]) == (0, "", "EMPTY", True)
    assert "lock_scope" not in report
    assert_safe(stdout, db, env.lock_root)
    assert list(env.cwd.iterdir()) == []
    assert probe(db, env.vars, env.cwd) == "ACQUIRED"


def test_producer_guard_still_passes_unmodified():
    _producer_guard()

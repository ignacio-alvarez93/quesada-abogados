"""TI-4C.3E3-G1 shared inter-process lock (backend.trend_intelligence.process_lock).

The CLI and any future backend caller must take the SAME OS lock for the same
store. Real processes (subprocess) over temporary files and stubbed OS lock
backends only; the per-user lock dir is redirected to a temporary directory
through LOCALAPPDATA / XDG_RUNTIME_DIR. Synchronization is event-driven (the
holder prints HELD and blocks on stdin), never sleep-based. No operational
database, browser, network or scheduler.
"""
import ast
import errno
import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.trend_intelligence import process_lock
from scripts import trend_producer_run as cli

ROOT = Path(__file__).resolve().parents[2]
LOCK_MODULE_PATH = ROOT / "backend" / "trend_intelligence" / "process_lock.py"
CLI_PATH = ROOT / "scripts" / "trend_producer_run.py"
LOCK_SUBDIR = Path("quesada-abogados") / "locks" / "trend-producer"
SAFETY_TIMEOUT = 120

# Child harness.
#   hold-backend <db> -> backend module takes the lock, prints HELD, waits for GO.
#   hold-cli <db>     -> CLI private alias takes the lock, prints HELD, waits for GO.
#   probe-backend/probe-cli <db> -> prints ACQUIRED or BUSY and releases.
HARNESS = r"""
import sys
from pathlib import Path
root, mode, db = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
if mode.endswith("cli"):
    from scripts import trend_producer_run as cli
    acquire, busy = cli._acquire_process_lock, cli._LockBusy
else:
    from backend.trend_intelligence import process_lock
    acquire, busy = process_lock.acquire_process_lock, process_lock.ProcessLockBusy
try:
    release = acquire(Path(db).resolve())
except busy:
    print("BUSY")
    sys.exit(0)
if mode.startswith("hold"):
    sys.stdout.write("HELD\n")
    sys.stdout.flush()
    if sys.stdin.readline().strip() != "GO":
        sys.exit(9)
release()
print("ACQUIRED" if mode.startswith("probe") else "RELEASED")
"""


def lock_env(lock_root):
    return dict(os.environ, LOCALAPPDATA=str(lock_root), XDG_RUNTIME_DIR=str(lock_root))


def probe(mode, db, env, cwd):
    completed = subprocess.run([sys.executable, "-c", HARNESS, str(ROOT), mode, str(db)], env=env, cwd=cwd,
                               capture_output=True, text=True, timeout=SAFETY_TIMEOUT)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


class Holder:
    def __init__(self, mode, db, env, cwd):
        self.proc = subprocess.Popen([sys.executable, "-c", HARNESS, str(ROOT), mode, str(db)], env=env, cwd=cwd,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True)

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


def cli_args(path):
    return ["--db-path", str(path), "--domain-code", "IT_DOMAIN", "--topic", "ARRAIGO",
            "--from-date", "2026-10-01", "--to-date", "2026-10-02", "--execute"]


def run_cli(argv, env, cwd):
    completed = subprocess.run([sys.executable, str(CLI_PATH), *argv], cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=SAFETY_TIMEOUT)
    return completed.returncode, json.loads(completed.stdout), completed.stderr


def lock_files(lock_root):
    return sorted(p for p in lock_root.rglob("*") if p.is_file())


def fd_is_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


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


@pytest.fixture
def fake_backend(monkeypatch):
    """Stub msvcrt AND fcntl: lock/unlock behaviour scripted per test."""
    state = SimpleNamespace(lock_error=None, unlock_error=None, locked=[], unlocked=[])

    def lock(fd, *args):
        state.locked.append(fd)
        if state.lock_error is not None:
            raise state.lock_error

    def unlock(fd):
        state.unlocked.append(fd)
        if state.unlock_error is not None:
            raise state.unlock_error

    msvcrt = types.ModuleType("msvcrt")
    msvcrt.LK_NBLCK, msvcrt.LK_UNLCK = 2, 0
    msvcrt.locking = lambda fd, mode, size: (lock if mode == msvcrt.LK_NBLCK else unlock)(fd)
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX, fcntl.LOCK_NB, fcntl.LOCK_UN = 2, 4, 8
    fcntl.flock = lambda fd, op: (unlock if op == fcntl.LOCK_UN else lock)(fd)
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    monkeypatch.setitem(sys.modules, "fcntl", fcntl)
    return state


# ------------------------------------------------ single implementation

def test_cli_private_api_is_the_shared_module():
    assert cli._acquire_process_lock is process_lock.acquire_process_lock
    assert cli._LockBusy is process_lock.ProcessLockBusy
    assert cli._lock_dir is process_lock.lock_dir
    assert cli._LOCK_BUSY_ERRNOS is process_lock.LOCK_BUSY_ERRNOS
    assert cli.LOCK_SCOPE == process_lock.LOCK_SCOPE == "SAME_USER_SAME_HOST"
    assert process_lock.LOCK_BUSY_ERRNOS == {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK}
    # No second copy of the OS calls in the CLI code (its docstring may describe them).
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.update(node.name.split("."))
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
    for token in ("msvcrt", "fcntl", "hashlib", "LK_NBLCK", "locking", "flock", "sha256"):
        assert token not in names
    defined = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    assert not defined & {"_acquire_process_lock", "_LockBusy", "_lock_dir"}


def test_module_has_no_sql_store_io_scripts_or_eager_backends():
    tree = ast.parse(LOCK_MODULE_PATH.read_text(encoding="utf-8"))
    top_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level.add(node.module)
    assert top_level == {"errno", "hashlib", "os", "pathlib"}
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"errno", "hashlib", "os", "msvcrt", "fcntl"}
    assert not any(isinstance(node, ast.ImportFrom) and node.module not in {"pathlib"} for node in ast.walk(tree))
    source = LOCK_MODULE_PATH.read_text(encoding="utf-8").lower()
    for token in ("sqlite3", "select ", "insert ", "execute(", "connect(", "import scripts", "from scripts"):
        assert token not in source


def test_import_is_inert(env):
    code = ("import sys, backend.trend_intelligence.process_lock;"
            "print([m for m in sys.modules if m.split('.')[0] in ('sqlite3', 'scripts', 'msvcrt', 'fcntl')"
            " or m == 'backend.trend_intelligence.producer'])")
    completed = subprocess.run([sys.executable, "-c", code], cwd=env.cwd, env=dict(env.vars, PYTHONPATH=str(ROOT)),
                               capture_output=True, text=True, check=True, timeout=SAFETY_TIMEOUT)
    # msvcrt may be preloaded by the Windows interpreter itself; fcntl is never imported eagerly here.
    loaded = [m for m in json.loads(completed.stdout.replace("'", '"')) if m != "msvcrt"]
    assert (loaded, completed.stderr) == ([], "")
    assert list(env.lock_root.iterdir()) == [] and list(env.cwd.iterdir()) == []


def test_lock_file_path_matches_cli_key_and_layout(env):
    db = (env.data / "ti.db").resolve()
    key = hashlib.sha256(os.path.normcase(str(db)).encode("utf-8")).hexdigest()
    assert process_lock.lock_key(db) == key
    assert process_lock.lock_file_path(db) == env.lock_root / LOCK_SUBDIR / f"{key}.lock"
    assert list(env.lock_root.iterdir()) == []  # Computing the path creates nothing.
    release = process_lock.acquire_process_lock(db)
    try:
        assert lock_files(env.lock_root) == [process_lock.lock_file_path(db)]
        assert list(env.data.iterdir()) == []  # The store itself is never touched.
    finally:
        release()


# ------------------------------- interoperability across processes

@pytest.mark.parametrize("holder_mode,probe_mode", [
    ("hold-backend", "probe-cli"),
    ("hold-cli", "probe-backend"),
    ("hold-backend", "probe-backend"),
])
def test_same_store_is_busy_across_cli_and_backend(env, holder_mode, probe_mode):
    db = env.data / "ti.db"
    with Holder(holder_mode, db, env.vars, env.cwd) as holder:
        assert probe(probe_mode, db, env.vars, env.cwd) == "BUSY"
        holder.finish()
    assert probe(probe_mode, db, env.vars, env.cwd) == "ACQUIRED"
    assert not db.exists()


def test_backend_holder_makes_real_cli_report_busy_without_composing(env):
    db = env.data / "ti.db"
    with Holder("hold-backend", db, env.vars, env.cwd) as holder:
        code, report, stderr = run_cli(cli_args(db), env.vars, env.cwd)
        assert (code, stderr, report["status"], report["executed"]) == (1, "", "BUSY", False)
        assert report["lock_scope"] == process_lock.LOCK_SCOPE
        assert "classification" not in report
        holder.finish()
    assert not db.exists()


def test_alias_of_same_store_is_busy(env):
    (env.data / "sub").mkdir()
    db = env.data / "ti.db"
    with Holder("hold-cli", db, env.vars, env.cwd) as holder:
        assert probe("probe-backend", env.data / "sub" / ".." / "ti.db", env.vars, env.cwd) == "BUSY"
        if os.name == "nt":
            assert probe("probe-backend", Path(str(db).upper()), env.vars, env.cwd) == "BUSY"
        holder.finish()


def test_distinct_store_does_not_block(env):
    with Holder("hold-backend", env.data / "a.db", env.vars, env.cwd) as holder:
        assert probe("probe-cli", env.data / "b.db", env.vars, env.cwd) == "ACQUIRED"
        assert probe("probe-backend", env.data / "b.db", env.vars, env.cwd) == "ACQUIRED"
        assert probe("probe-cli", env.data / "a.db", env.vars, env.cwd) == "BUSY"
        holder.finish()
    assert len(lock_files(env.lock_root)) == 2


def test_other_lock_dir_is_a_different_scope(env, tmp_path):
    other_root = tmp_path / "other_user"
    other_root.mkdir()
    db = env.data / "ti.db"
    with Holder("hold-backend", db, env.vars, env.cwd) as holder:
        # Documented limitation: another per-user dir (other user) is not excluded.
        assert probe("probe-cli", db, lock_env(other_root), env.cwd) == "ACQUIRED"
        holder.finish()


def test_killed_holder_releases_lock(env):
    db = env.data / "ti.db"
    holder = Holder("hold-backend", db, env.vars, env.cwd)
    with holder:
        assert probe("probe-cli", db, env.vars, env.cwd) == "BUSY"
        holder.proc.kill()  # TerminateProcess / SIGKILL: no finally runs.
        holder.proc.communicate(timeout=SAFETY_TIMEOUT)
        assert holder.proc.returncode != 0
    assert probe("probe-cli", db, env.vars, env.cwd) == "ACQUIRED"
    assert probe("probe-backend", db, env.vars, env.cwd) == "ACQUIRED"
    assert len(lock_files(env.lock_root)) == 1


# ------------------------------------------------ in-process semantics

def test_second_acquire_in_same_process_is_busy_and_release_frees(env):
    db = (env.data / "ti.db").resolve()
    release = process_lock.acquire_process_lock(db)
    try:
        with pytest.raises(process_lock.ProcessLockBusy):
            process_lock.acquire_process_lock(db)
        with pytest.raises(cli._LockBusy):
            cli._acquire_process_lock(db)
    finally:
        release()
    process_lock.acquire_process_lock(db)()
    assert probe("probe-cli", db, env.vars, env.cwd) == "ACQUIRED"


@pytest.mark.parametrize("code", sorted(process_lock.LOCK_BUSY_ERRNOS))
def test_busy_errnos_map_to_busy_and_close_handle(env, fake_backend, code):
    fake_backend.lock_error = OSError(code, "held")
    with pytest.raises(process_lock.ProcessLockBusy) as raised:
        process_lock.acquire_process_lock(env.data / "ti.db")
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert not fd_is_open(fake_backend.locked[0])


@pytest.mark.parametrize("error", [OSError(errno.EIO, "io"), OSError(errno.ENOLCK, "nolck"),
                                   RuntimeError("boom"), KeyboardInterrupt()])
def test_other_lock_errors_propagate_as_non_busy_and_close_handle(env, fake_backend, error):
    fake_backend.lock_error = error
    with pytest.raises(type(error)) as raised:
        process_lock.acquire_process_lock(env.data / "ti.db")
    assert not isinstance(raised.value, process_lock.ProcessLockBusy)
    assert not fd_is_open(fake_backend.locked[0])


def test_failed_unlock_still_closes_handle(env, fake_backend):
    fake_backend.unlock_error = OSError(errno.EIO, "unlock")
    release = process_lock.acquire_process_lock(env.data / "ti.db")
    fd = fake_backend.locked[0]
    assert fd_is_open(fd)
    release()
    assert fake_backend.unlocked == [fd] and not fd_is_open(fd)


def test_platform_without_os_locking_fails_closed(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with pytest.raises(ModuleNotFoundError):
        process_lock.acquire_process_lock(env.data / "ti.db")
    assert list(env.lock_root.iterdir()) == []


@pytest.mark.parametrize("value", ["", "   ", "relative/dir"])
def test_missing_or_relative_lock_base_fails_closed(env, monkeypatch, value):
    for name in ("LOCALAPPDATA", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME", "HOME"):
        monkeypatch.setenv(name, value)
    with pytest.raises(OSError) as raised:
        process_lock.acquire_process_lock(env.data / "ti.db")
    assert not isinstance(raised.value, process_lock.ProcessLockBusy)
    assert not Path("relative").exists()


def test_unusable_lock_dir_fails_closed(env, tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(blocker))
    with pytest.raises(OSError) as raised:
        process_lock.acquire_process_lock(env.data / "ti.db")
    assert not isinstance(raised.value, process_lock.ProcessLockBusy)
    assert blocker.read_text() == "x"


def test_posix_dir_and_file_are_private(env):
    db = env.data / "ti.db"
    release = process_lock.acquire_process_lock(db.resolve())
    try:
        (path,) = lock_files(env.lock_root)
        assert ROOT not in path.parents and env.data not in path.parents
        if os.name != "nt":
            assert path.stat().st_mode & 0o077 == 0
            assert path.parent.stat().st_mode & 0o077 == 0
    finally:
        release()

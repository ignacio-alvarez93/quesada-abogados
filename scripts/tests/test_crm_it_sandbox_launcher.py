"""Launcher del sandbox CRM IT: solo tmp_path, git y subprocesos simulados."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest


LAUNCHER_PATH = Path("scripts/dev/crm_it_sandbox_launcher.py")
SHA = "a" * 40


def _load_launcher():
    spec = importlib.util.spec_from_file_location("crm_it_sandbox_launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = _load_launcher()


@pytest.fixture
def connect_spy(monkeypatch, tmp_path):
    """Todo sqlite3.connect debe apuntar dentro de tmp_path."""
    real_connect = sqlite3.connect
    targets = []

    def spy(database, *args, **kwargs):
        text = str(database).replace("\\", "/").lower()
        targets.append(text)
        assert tmp_path.as_posix().lower() in text, text
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    return targets


def _fake_worktree(path):
    (path / "app").mkdir(parents=True)
    (path / "database").mkdir()
    (path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    (path / "app" / "main.py").write_text(
        Path("app/main.py").read_text(encoding="utf-8"), encoding="utf-8",
    )
    return path


class FakeGit:
    def __init__(self, repo, *, main_source=None, status="", head=SHA, detached=True):
        self.repo = repo
        self.main_source = main_source or Path("app/main.py").read_text(encoding="utf-8")
        self.status, self.head, self.detached = status, head, detached
        self.extra_worktrees = []
        self.calls = []

    def __call__(self, args, *, cwd, check=True):
        self.calls.append(list(args))
        code, out = 0, ""
        if args[:2] == ["worktree", "list"]:
            out = "".join(f"worktree {p.as_posix()}\n" for p in [self.repo, *self.extra_worktrees])
        elif args[0] == "rev-parse" and "--verify" in args:
            out = SHA + "\n"
        elif args[0] == "show":
            out = self.main_source
        elif args[:2] == ["worktree", "add"]:
            _fake_worktree(Path(args[3]))
            self.extra_worktrees.append(Path(args[3]))
        elif args == ["rev-parse", "HEAD"]:
            out = self.head + "\n"
        elif args[0] == "symbolic-ref":
            code = 1 if self.detached else 0
        elif args[0] == "status":
            out = self.status
        else:
            raise AssertionError(f"git inesperado: {args}")
        if check and code:
            raise L.SandboxError("GIT_FAILED")
        return subprocess.CompletedProcess(["git", *args], code, out, "")


class FakeInternal:
    """Ejecuta el bootstrap real en proceso sobre la BD de tmp_path."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.calls = []
        self.probe_override = None

    def __call__(self, mode, worktree, *, stdin_text=""):
        from database import connection

        self.calls.append(mode)
        db_path = Path(worktree) / L.DB_RELATIVE
        if mode == "--internal-bootstrap":
            username, password = stdin_text.splitlines()[:2]
            self.monkeypatch.setattr(connection, "DB_PATH", str(db_path))
            L.bootstrap_database(db_path, username=username, password=password)
            return "BOOTSTRAP_OK\n"
        if mode == "--internal-probe":
            paths = {f"{m}.{a}": str(db_path.resolve()) for m, a in L.PROBED_DB_PATHS}
            paths["browser_session.project_root"] = str(Path(worktree).resolve())
            paths.update(self.probe_override or {})
            return json.dumps(paths)
        raise AssertionError(mode)


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch, connect_spy):
    repo = tmp_path / "repo"
    repo.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    git = FakeGit(repo)
    internal = FakeInternal(monkeypatch)
    monkeypatch.setattr(L, "temp_root", lambda: temp)
    monkeypatch.setattr(L, "_git", git)
    monkeypatch.setattr(L, "run_internal", internal)

    def no_popen(*args, **kwargs):
        raise AssertionError("el CRM no debe arrancarse")

    monkeypatch.setattr(subprocess, "Popen", no_popen)
    return dict(repo=repo, temp=temp, git=git, internal=internal, dest=temp / "sbx")


# ------------------------------------------------------------
# Preflight de destino
# ------------------------------------------------------------

def test_destination_must_be_new_or_empty(tmp_path):
    dest = tmp_path / "sbx"
    assert L.validate_new_destination(dest, root=tmp_path, checkouts=[]) == dest.resolve()
    dest.mkdir()
    assert L.validate_new_destination(dest, root=tmp_path, checkouts=[]) == dest.resolve()
    (dest / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(L.SandboxError, match="DEST_NOT_EMPTY"):
        L.validate_new_destination(dest, root=tmp_path, checkouts=[])


def test_destination_rejects_files_relative_and_missing_parent(tmp_path):
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(L.SandboxError, match="DEST_NOT_DIRECTORY"):
        L.validate_new_destination(tmp_path / "file", root=tmp_path, checkouts=[])
    with pytest.raises(L.SandboxError, match="DEST_NOT_ABSOLUTE"):
        L.validate_new_destination(Path("relative/sbx"), root=tmp_path, checkouts=[])
    with pytest.raises(L.SandboxError, match="DEST_PARENT_MISSING"):
        L.validate_new_destination(tmp_path / "a" / "b", root=tmp_path, checkouts=[])


def test_destination_must_be_strictly_under_temp(tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    with pytest.raises(L.SandboxError, match="DEST_OUTSIDE_TEMP"):
        L.validate_new_destination(tmp_path / "other", root=temp, checkouts=[])
    with pytest.raises(L.SandboxError, match="DEST_OUTSIDE_TEMP"):
        L.validate_new_destination(temp, root=temp, checkouts=[])


def test_destination_rejects_repository_and_checkouts():
    with pytest.raises(L.SandboxError, match="DEST_OUTSIDE_TEMP"):
        L.validate_new_destination(L.REPO_ROOT / "sbx", root=L.temp_root(), checkouts=[])


def test_destination_rejects_overlap_with_checkouts(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with pytest.raises(L.SandboxError, match="DEST_OVERLAPS_CHECKOUT"):
        L.validate_new_destination(checkout / "sbx", root=tmp_path, checkouts=[checkout])
    nested = tmp_path / "outer" / "checkout"
    with pytest.raises(L.SandboxError, match="DEST_OVERLAPS_CHECKOUT"):
        L.validate_new_destination(tmp_path / "outer", root=tmp_path, checkouts=[nested])


def test_destination_rejects_git_ancestor(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".git").mkdir()
    with pytest.raises(L.SandboxError, match="DEST_INSIDE_GIT_CHECKOUT"):
        L.validate_new_destination(clone / "sbx", root=tmp_path, checkouts=[])


def test_destination_rejects_links_and_reparse_points(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    monkeypatch.setattr(L, "_is_link_or_reparse", lambda p: Path(p) == parent)
    with pytest.raises(L.SandboxError, match="DEST_LINK_OR_REPARSE"):
        L.validate_new_destination(parent / "sbx", root=tmp_path, checkouts=[])


def test_destination_rejects_ambiguous_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(L.os.path, "abspath", lambda p: str(tmp_path / "elsewhere"))
    with pytest.raises(L.SandboxError, match="DEST_PATH_AMBIGUOUS"):
        L.validate_new_destination(tmp_path / "sbx", root=tmp_path, checkouts=[])


# ------------------------------------------------------------
# Escaneo de worktree y guard de app/main.py
# ------------------------------------------------------------

def test_scan_rejects_env_db_profiles_and_credentials(tmp_path):
    worktree = _fake_worktree(tmp_path / "crm")
    assert L.scan_forbidden_files(worktree, expect_db=False) == []
    (worktree / ".env.example").write_text("", encoding="utf-8")
    assert L.scan_forbidden_files(worktree, expect_db=False) == []

    (worktree / ".env.local").write_text("", encoding="utf-8")
    (worktree / "database" / "quesada.db").write_bytes(b"")
    (worktree / "data" / "browser_profiles").mkdir(parents=True)
    (worktree / "token.json").write_text("{}", encoding="utf-8")
    problems = L.scan_forbidden_files(worktree, expect_db=False)
    assert "ENV_FILE:.env.local" in problems
    assert "DB_FILE:database/quesada.db" in problems
    assert "FORBIDDEN_DIR:data/browser_profiles" in problems
    assert "CREDENTIAL_FILE:token.json" in problems


def test_scan_allows_only_the_sandbox_db_after_bootstrap(tmp_path):
    worktree = _fake_worktree(tmp_path / "crm")
    (worktree / "database" / "quesada.db").write_bytes(b"")
    (worktree / "database" / "quesada.db-wal").write_bytes(b"")
    assert L.scan_forbidden_files(worktree, expect_db=True) == []
    (worktree / "app" / "other.sqlite").write_bytes(b"")
    assert L.scan_forbidden_files(worktree, expect_db=True) == ["DB_FILE:app/other.sqlite"]


def test_main_guard_detection():
    assert L.main_supports_sandbox(Path("app/main.py").read_text(encoding="utf-8"))
    legacy = 'from dotenv import load_dotenv\nload_dotenv(".env.local")\n'
    assert not L.main_supports_sandbox(legacy)
    partial = (
        "def resolve_sandbox_mode(e, p, c):\n    return False\n"
        "SANDBOX_MODE = resolve_sandbox_mode({}, '', '')\n"
        "load_dotenv('.env.local')\n"
    )
    assert not L.main_supports_sandbox(partial)
    assert not L.main_supports_sandbox("def broken(:\n")


def test_repository_db_paths_are_file_or_cwd_relative():
    assert L.scan_db_path_definitions(Path(".")) == []


def test_db_path_scan_flags_absolute_and_env_paths(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "x.py").write_text(
        'import os\nDB_PATH = "C:/prod/quesada.db"\nOTHER_DB_PATH = os.getenv("DB")\n',
        encoding="utf-8",
    )
    assert L.scan_db_path_definitions(tmp_path) == ["backend/x.py:2", "backend/x.py:3"]


# ------------------------------------------------------------
# BD sintética
# ------------------------------------------------------------

def _bootstrap(tmp_path, monkeypatch):
    from database import connection

    db_path = tmp_path / "database" / "quesada.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(connection, "DB_PATH", str(db_path))
    username, password = L.generate_credentials()
    L.bootstrap_database(db_path, username=username, password=password)
    return db_path, username, password


def test_bootstrap_creates_login_and_it_schema_only_in_tmp(tmp_path, monkeypatch, connect_spy):
    db_path, _, _ = _bootstrap(tmp_path, monkeypatch)
    report = L.inspect_database(db_path)
    assert report == dict(missing_tables=(), users=1, collector_configured=False)
    assert connect_spy and all(tmp_path.as_posix().lower() in t for t in connect_spy)


def test_synthetic_user_authenticates_without_fixed_credentials(tmp_path, monkeypatch, connect_spy):
    from backend.services.auth_service import authenticate_user

    _, username, password = _bootstrap(tmp_path, monkeypatch)
    assert username.startswith("sandbox_") and username != "admin"
    assert password != "1234" and len(password) >= 20
    assert authenticate_user(username, password)["username"] == username
    assert authenticate_user(username, password + "x") is None
    assert authenticate_user("admin", "1234") is None
    assert L.generate_credentials() != L.generate_credentials()


def test_bootstrap_refuses_existing_db_and_mismatched_paths(tmp_path, monkeypatch, connect_spy):
    from database import connection

    db_path = tmp_path / "quesada.db"
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "other.db"))
    with pytest.raises(L.SandboxError, match="DB_PATH_MISMATCH"):
        L.bootstrap_database(db_path, username="sandbox_x", password="p" * 24)

    monkeypatch.setattr(connection, "DB_PATH", str(db_path))
    db_path.write_bytes(b"")
    with pytest.raises(L.SandboxError, match="DB_ALREADY_EXISTS"):
        L.bootstrap_database(db_path, username="sandbox_x", password="p" * 24)
    assert db_path.read_bytes() == b""

    db_path.unlink()
    with pytest.raises(L.SandboxError, match="CREDENTIALS_INVALID"):
        L.bootstrap_database(db_path, username="admin", password="1234")
    assert not db_path.exists()
    assert connect_spy == []


def test_bootstrapped_db_opens_it_view_services_read_only(tmp_path, monkeypatch, connect_spy):
    from backend.services import config_service
    from backend.services.instagram_collector_control_service import create_crm_instagram_control
    from backend.services.trend_intelligence_dashboard_service import (
        STATUS_NO_DOMAIN, create_crm_trend_dashboard,
    )

    db_path, _, _ = _bootstrap(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "DB_PATH", db_path)
    assert create_crm_trend_dashboard().state().status == STATUS_NO_DOMAIN
    control = create_crm_instagram_control()
    control.runtime_factory = lambda: pytest.fail("runtime no permitido")
    state = control.state()
    assert state["effective"] == "NOT_CONFIGURED" and state["problem"] is None


def test_config_global_ddl_matches_config_service():
    source = Path("backend/services/config_service.py").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE IF NOT EXISTS config_global \((.*?)\)\s*\"\"\"", source, re.S)
    normalize = lambda text: " ".join(text.split())
    assert normalize(L.CONFIG_GLOBAL_DDL) == normalize(
        f"CREATE TABLE IF NOT EXISTS config_global ({match.group(1)})"
    )


# ------------------------------------------------------------
# --prepare
# ------------------------------------------------------------

def test_prepare_builds_sealed_sandbox_without_launching(sandbox_env):
    result = L.prepare(sandbox_env["dest"], SHA[:12], repo_root=sandbox_env["repo"])
    dest = sandbox_env["dest"].resolve()
    worktree = dest / L.WORKTREE_NAME

    assert result["worktree"] == worktree and result["sha"] == SHA
    assert ["worktree", "add", "--detach", str(worktree), SHA] in sandbox_env["git"].calls
    assert sandbox_env["internal"].calls == ["--internal-bootstrap"]
    assert sorted(p.name for p in dest.iterdir()) == ["crm", L.SEAL_NAME]

    seal = json.loads((dest / L.SEAL_NAME).read_text(encoding="utf-8"))
    assert seal["sha"] == SHA and seal["worktree"] == str(worktree)
    assert seal["db_path"] == str(worktree / L.DB_RELATIVE)
    # La contraseña no se escribe en ningún fichero del sandbox.
    for path in dest.rglob("*"):
        if path.is_file():
            assert result["password"].encode() not in path.read_bytes()
    assert not any(m == "app" or m.startswith("app.") for m in sys.modules)


def test_prepare_rejects_non_empty_destination_before_git(sandbox_env):
    sandbox_env["dest"].mkdir()
    (sandbox_env["dest"] / "quesada.db").write_bytes(b"")
    with pytest.raises(L.SandboxError, match="DEST_NOT_EMPTY"):
        L.prepare(sandbox_env["dest"], SHA, repo_root=sandbox_env["repo"])
    assert all(call[:2] != ["worktree", "add"] for call in sandbox_env["git"].calls)


def test_prepare_rejects_sha_without_sandbox_guard(sandbox_env):
    sandbox_env["git"].main_source = 'from dotenv import load_dotenv\nload_dotenv(".env.local")\n'
    with pytest.raises(L.SandboxError, match="SHA_WITHOUT_SANDBOX_GUARD"):
        L.prepare(sandbox_env["dest"], SHA, repo_root=sandbox_env["repo"])
    assert not sandbox_env["dest"].exists()


@pytest.mark.parametrize("sha", ["", "HEAD", "develop", "zz" * 20, "abc"])
def test_prepare_rejects_ambiguous_sha(sandbox_env, sha):
    with pytest.raises(L.SandboxError, match="SHA_INVALID"):
        L.prepare(sandbox_env["dest"], sha, repo_root=sandbox_env["repo"])
    assert not sandbox_env["dest"].exists()


def test_prepare_aborts_on_dirty_or_attached_worktree(sandbox_env):
    sandbox_env["git"].status = "?? stray.txt\n"
    with pytest.raises(L.SandboxError, match="WORKTREE_DIRTY"):
        L.prepare(sandbox_env["dest"], SHA, repo_root=sandbox_env["repo"])
    assert sandbox_env["internal"].calls == []


def test_prepare_refuses_preexisting_db_in_worktree(sandbox_env, monkeypatch):
    real_fake = _fake_worktree

    def with_db(path):
        real_fake(path)
        (path / "database" / "quesada.db").write_bytes(b"")
        return path

    monkeypatch.setitem(globals(), "_fake_worktree", with_db)
    with pytest.raises(L.SandboxError, match="DB_FILE:database/quesada.db"):
        L.prepare(sandbox_env["dest"], SHA, repo_root=sandbox_env["repo"])
    assert sandbox_env["internal"].calls == []


def test_cli_prepare_requires_dest_and_sha(capsys):
    assert L.main(["--prepare"]) == 2
    assert L.main(["--prepare", "--dest", str(L.temp_root() / "unused-sbx")]) == 2
    assert "SHA_REQUIRED" in capsys.readouterr().err


# ------------------------------------------------------------
# --launch
# ------------------------------------------------------------

def _prepared(sandbox_env):
    L.prepare(sandbox_env["dest"], SHA, repo_root=sandbox_env["repo"])
    return sandbox_env["dest"].resolve()


def test_launch_revalidates_and_marks_sandbox(sandbox_env):
    dest = _prepared(sandbox_env)
    calls = []
    process = L.launch(dest, repo_root=sandbox_env["repo"],
                       popen=lambda *a, **k: calls.append((a, k)) or "PROC")
    assert process == "PROC"
    (cmd,), kwargs = calls[0]
    assert cmd == [sys.executable, "-E", "-B", "-m", "app.main"]
    assert kwargs["cwd"] == str(dest / L.WORKTREE_NAME)
    env = kwargs["env"]
    assert env["QUESADA_SANDBOX"] == "1" and env["QUESADA_SANDBOX_ROOT"] == str(dest)
    assert sandbox_env["internal"].calls == ["--internal-bootstrap", "--internal-probe"]


@pytest.mark.parametrize("damage, error", [
    (lambda d: (d / "crm" / ".env.local").write_text("X=1", encoding="utf-8"), "ENV_FILE:.env.local"),
    (lambda d: (d / L.SEAL_NAME).write_text("{}", encoding="utf-8"), "SEAL_MISMATCH"),
    (lambda d: (d / L.SEAL_NAME).unlink(), "SEAL_MISSING"),
    (lambda d: (d / "crm" / L.DB_RELATIVE).unlink(), "SANDBOX_DB_MISSING"),
    (lambda d: (d / "crm" / "copia.db").write_bytes(b""), "DB_FILE:copia.db"),
])
def test_launch_aborts_on_tampered_sandbox(sandbox_env, damage, error):
    dest = _prepared(sandbox_env)
    damage(dest)
    with pytest.raises(L.SandboxError, match=re.escape(error)):
        L.launch(dest, repo_root=sandbox_env["repo"], popen=lambda *a, **k: pytest.fail("popen"))


def test_launch_aborts_when_effective_path_leaves_sandbox(sandbox_env, tmp_path):
    dest = _prepared(sandbox_env)
    sandbox_env["internal"].probe_override = {
        "backend.services.config_service.DB_PATH": str(tmp_path / "repo" / "database" / "quesada.db"),
    }
    with pytest.raises(L.SandboxError, match="EFFECTIVE_PATH_OUTSIDE_SANDBOX"):
        L.launch(dest, repo_root=sandbox_env["repo"], popen=lambda *a, **k: pytest.fail("popen"))


def test_launch_aborts_on_head_mismatch(sandbox_env):
    dest = _prepared(sandbox_env)
    sandbox_env["git"].head = "b" * 40
    with pytest.raises(L.SandboxError, match="WORKTREE_SHA_MISMATCH"):
        L.launch(dest, repo_root=sandbox_env["repo"], popen=lambda *a, **k: pytest.fail("popen"))


def test_effective_db_paths_must_match_sandbox_db(tmp_path):
    worktree = tmp_path / "crm"
    db = (worktree / L.DB_RELATIVE).resolve()
    L.check_effective_paths({"x.DB_PATH": str(db)}, dest=tmp_path, worktree=worktree)
    with pytest.raises(L.SandboxError, match="EFFECTIVE_DB_PATH_MISMATCH"):
        L.check_effective_paths({"x.DB_PATH": str(worktree / "other.db")}, dest=tmp_path, worktree=worktree)


def test_sandbox_env_is_allowlisted():
    source = {
        "PATH": "p", "SystemRoot": "s", "TEMP": "t",
        "PYTHONPATH": "evil", "QUESADA_CALL_UI_SMOKE": "1", "HUBSPOT_TOKEN": "x",
        "TELEGRAM_BOT_TOKEN": "x", "QUESADA_SANDBOX": "0",
    }
    assert L.build_sandbox_env(source) == {"PATH": "p", "SYSTEMROOT": "s", "TEMP": "t"}
    env = L.build_sandbox_env(source, Path("D"))
    assert env["QUESADA_SANDBOX"] == "1" and env["QUESADA_SANDBOX_ROOT"] == "D"


# ------------------------------------------------------------
# Contrato estático del launcher
# ------------------------------------------------------------

def test_launcher_never_imports_crm_or_providers_at_module_level():
    tree = ast.parse(LAUNCHER_PATH.read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add(node.module.split(".")[0])
    assert not top & {"app", "flet", "backend", "database", "frontend", "seleniumbase", "dotenv"}
    every = {
        (n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    } | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(name == "app" or name.startswith("app.") for name in every)


def test_launcher_has_no_operational_paths_or_fixed_credentials():
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    assert "create_admin" not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            assert getattr(node.func, "id", getattr(node.func, "attr", None)) != "load_dotenv"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not re.match(r"^[A-Za-z]:[\\/]", node.value), node.value
            assert "Desktop" not in node.value and "IGNACIO" not in node.value

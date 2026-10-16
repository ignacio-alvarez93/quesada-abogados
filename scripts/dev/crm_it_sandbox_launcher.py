"""
Lanzador aislado del CRM limitado a Login -> Marketing -> IT / Tendencias.

VERSIÓN DE DESARROLLO (WO TI-4C.3C). Fail-closed.

--prepare --dest DIR --sha SHA
    Crea DIR (nuevo/vacío, bajo el TEMP local del usuario), un git
    worktree DESACOPLADO en DIR/crm al SHA indicado y una BD sintética
    en DIR/crm/database/quesada.db con los servicios existentes
    (schema.sql, migraciones Trend Intelligence y config_global).
    Genera un usuario ficticio con contraseña aleatoria que se muestra
    UNA sola vez por consola y no se guarda en ningún fichero.
    Nunca arranca el CRM.

--launch --dest DIR
    Revalida sello, worktree, rutas efectivas de BD y ausencia de
    .env.local y arranca `python -m app.main` con QUESADA_SANDBOX=1,
    cwd en el worktree temporal y un entorno mínimo (allowlist).

Limitaciones (no es aislamiento del sistema operativo):
- El proceso CRM corre con el usuario actual: puede leer cualquier
  fichero accesible para ese usuario y tiene acceso de red.
- El aislamiento descansa en que todas las rutas de BD del código se
  resuelven desde __file__ o desde el cwd, ambos dentro de DIR/crm, y
  en las inhibiciones de app/main.py bajo QUESADA_SANDBOX=1.
- Flet puede usar su caché habitual del perfil de usuario.
- `git worktree add` registra el worktree en el .git del repositorio
  origen (sin ramas nuevas). Para retirarlo:
  `git worktree remove --force DIR/crm` y borrar DIR.
"""

import argparse
import ast
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import warnings


REPO_ROOT = Path(__file__).resolve().parents[2]

# Deben coincidir con app/main.py.
SANDBOX_ENV = "QUESADA_SANDBOX"
SANDBOX_ROOT_ENV = "QUESADA_SANDBOX_ROOT"
SEAL_NAME = "quesada_sandbox_seal.json"

SEAL_KIND = "QUESADA_CRM_IT_SANDBOX"
SEAL_VERSION = 1
WORKTREE_NAME = "crm"
DB_RELATIVE = Path("database") / "quesada.db"
DB_SIDECAR_SUFFIXES = ("", "-wal", "-shm", "-journal")
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal")

# Misma DDL que backend/services/config_service.ensure_config_runtime_schema;
# aquel camino migra además todo el dominio de configuración.
CONFIG_GLOBAL_DDL = """
            CREATE TABLE IF NOT EXISTS config_global (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """

# Mismo valor que instagram_collector_configuration_service.SETTINGS_KEY.
COLLECTOR_SETTINGS_KEY = "IT_INSTAGRAM_COLLECTOR_V1"

REQUIRED_TABLES = (
    "users",
    "config_global",
    "ti_collector_runs",
    "ti_domains",
    "ti_observation_domains",
    "ti_observations",
    "ti_signals",
    "ti_sources",
    "ti_topic_domains",
    "ti_topics",
    "ti_trend_snapshots",
)

# Rutas efectivas conocidas del recorrido Login -> IT.
PROBED_DB_PATHS = (
    ("database.connection", "DB_PATH"),
    ("backend.services.config_service", "DB_PATH"),
    ("backend.services.sqlite_runtime_service", "DEFAULT_DB_PATH"),
    ("backend.repositories.sqlite_trend_intelligence_repository", "DEFAULT_DB_PATH"),
    ("backend.repositories.sqlite_communication_repository", "DEFAULT_DB_PATH"),
)

FORBIDDEN_DIRS = (
    Path("data") / "browser_profiles",
    Path("runtime"),
)

CREDENTIAL_FILE_NAMES = {
    "credentials.json",
    "token.json",
    "cookies",
    "login data",
}

SUSPICIOUS_DB_PATH_TOKENS = (
    "getenv",
    "environ",
    "home(",
    "expanduser",
    "gettempdir",
    "APPDATA",
)

ENV_ALLOWLIST = (
    "APPDATA",
    "COMMONPROGRAMFILES",
    "COMPUTERNAME",
    "COMSPEC",
    "DISPLAY",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WAYLAND_DISPLAY",
    "WINDIR",
    "XDG_RUNTIME_DIR",
)

SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")
FULL_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class SandboxError(RuntimeError):
    pass


# ============================================================
# Rutas
# ============================================================

def temp_root():
    return Path(tempfile.gettempdir()).resolve()


def _is_within(child, parent):
    child, parent = Path(child), Path(parent)
    return child == parent or parent in child.parents


def _same_path(a, b):
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _is_link_or_reparse(path):
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & reparse)


def validate_location(dest, *, root, checkouts):
    """Ruta absoluta, sin enlaces, estrictamente bajo TEMP y fuera de checkouts."""
    raw = Path(dest)
    if not raw.is_absolute():
        raise SandboxError("DEST_NOT_ABSOLUTE")

    root = Path(root).resolve()
    absolute = Path(os.path.abspath(raw))
    resolved = raw.resolve()
    if not _same_path(absolute, resolved):
        raise SandboxError("DEST_PATH_AMBIGUOUS")

    if resolved == root or not _is_within(resolved, root):
        raise SandboxError("DEST_OUTSIDE_TEMP")

    current = root
    for part in resolved.relative_to(root).parts:
        current = current / part
        if not os.path.lexists(current):
            break
        if _is_link_or_reparse(current):
            raise SandboxError("DEST_LINK_OR_REPARSE")
        if current != resolved and (current / ".git").exists():
            raise SandboxError("DEST_INSIDE_GIT_CHECKOUT")

    for checkout in checkouts:
        checkout = Path(checkout).resolve()
        if _is_within(resolved, checkout) or _is_within(checkout, resolved):
            raise SandboxError("DEST_OVERLAPS_CHECKOUT")

    return resolved


def validate_new_destination(dest, *, root, checkouts):
    resolved = validate_location(dest, root=root, checkouts=checkouts)

    if os.path.lexists(resolved):
        if not resolved.is_dir():
            raise SandboxError("DEST_NOT_DIRECTORY")
        if any(resolved.iterdir()):
            raise SandboxError("DEST_NOT_EMPTY")
    elif not resolved.parent.is_dir():
        raise SandboxError("DEST_PARENT_MISSING")

    return resolved


def create_private_directory(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700)
    if os.name != "nt":
        os.chmod(path, 0o700)
        if path.stat().st_mode & 0o077:
            raise SandboxError("DEST_NOT_PRIVATE")
    # Windows: hereda la ACL del TEMP del usuario (privado por defecto).
    return path


# ============================================================
# Git
# ============================================================

def _git(args, *, cwd, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        raise SandboxError(f"GIT_FAILED: git {args[0]}: {result.stderr.strip()}")
    return result


def list_checkouts(repo_root):
    output = _git(["worktree", "list", "--porcelain"], cwd=repo_root).stdout
    paths = [Path(repo_root).resolve()]
    for line in output.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree "):]).resolve())
    return paths


def resolve_commit(repo_root, sha):
    sha = str(sha or "").strip().lower()
    if not SHA_PATTERN.fullmatch(sha):
        raise SandboxError("SHA_INVALID")
    full = _git(
        ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
        cwd=repo_root,
    ).stdout.strip()
    if not FULL_SHA_PATTERN.fullmatch(full) or not full.startswith(sha):
        raise SandboxError("SHA_UNRESOLVED")
    return full


def main_supports_sandbox(source):
    """app/main.py valida QUESADA_SANDBOX y solo carga .env.local fuera de él."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assigned = {
        target.id
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    if "resolve_sandbox_mode" not in names or "SANDBOX_MODE" not in assigned:
        return False

    guarded = set()
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and ast.unparse(node.test) == "not SANDBOX_MODE"
        ):
            guarded.update(id(n) for n in ast.walk(node))

    dotenv_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_dotenv"
    ]
    return bool(dotenv_calls) and all(id(call) in guarded for call in dotenv_calls)


# ============================================================
# Worktree
# ============================================================

def _allowed_db_files(worktree):
    db = Path(worktree) / DB_RELATIVE
    return {Path(str(db) + suffix) for suffix in DB_SIDECAR_SUFFIXES}


def scan_forbidden_files(worktree, *, expect_db):
    """Solo nombres de fichero; nunca abre su contenido."""
    worktree = Path(worktree)
    allowed = _allowed_db_files(worktree) if expect_db else set()
    problems = []

    for relative in FORBIDDEN_DIRS:
        if os.path.lexists(worktree / relative):
            problems.append(f"FORBIDDEN_DIR:{relative.as_posix()}")

    for current, dirs, files in os.walk(worktree):
        current = Path(current)
        if current == worktree and ".git" in files:
            files = [f for f in files if f != ".git"]
        for name in dirs + files:
            path = current / name
            relative = path.relative_to(worktree).as_posix()
            if _is_link_or_reparse(path):
                problems.append(f"LINK_OR_REPARSE:{relative}")
                continue
            if name in dirs:
                continue
            lowered = name.lower()
            if lowered.startswith(".env") and lowered != ".env.example":
                problems.append(f"ENV_FILE:{relative}")
            elif lowered.endswith(DB_SUFFIXES) and path not in allowed:
                problems.append(f"DB_FILE:{relative}")
            elif lowered in CREDENTIAL_FILE_NAMES or lowered.endswith(".holded-token"):
                problems.append(f"CREDENTIAL_FILE:{relative}")
        dirs[:] = [d for d in dirs if not _is_link_or_reparse(current / d)]

    return problems


def verify_worktree(worktree, sha, *, expect_db):
    worktree = Path(worktree)
    if not worktree.is_dir() or _is_link_or_reparse(worktree):
        raise SandboxError("WORKTREE_MISSING")
    if not (worktree / ".git").is_file():
        raise SandboxError("WORKTREE_NOT_LINKED")

    head = _git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if head != sha:
        raise SandboxError("WORKTREE_SHA_MISMATCH")
    if _git(["symbolic-ref", "-q", "HEAD"], cwd=worktree, check=False).returncode == 0:
        raise SandboxError("WORKTREE_NOT_DETACHED")
    status = _git(
        ["status", "--porcelain", "--untracked-files=all"], cwd=worktree,
    ).stdout.strip()
    if status:
        raise SandboxError("WORKTREE_DIRTY")

    problems = scan_forbidden_files(worktree, expect_db=expect_db)
    if problems:
        raise SandboxError("WORKTREE_FORBIDDEN_FILES: " + ", ".join(problems[:10]))

    db = worktree / DB_RELATIVE
    if expect_db and not db.is_file():
        raise SandboxError("SANDBOX_DB_MISSING")
    if not expect_db and os.path.lexists(db):
        raise SandboxError("SANDBOX_DB_PREEXISTING")

    main_path = worktree / "app" / "main.py"
    if not main_supports_sandbox(main_path.read_text(encoding="utf-8")):
        raise SandboxError("MAIN_WITHOUT_SANDBOX_GUARD")


def scan_db_path_definitions(worktree):
    """Toda DB_PATH a nivel de módulo debe depender de __file__ o ser relativa."""
    worktree = Path(worktree)
    problems = []
    for package in ("backend", "database", "frontend", "app"):
        for path in sorted((worktree / package).rglob("*.py")):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                problems.append(f"UNPARSEABLE:{path.relative_to(worktree).as_posix()}")
                continue
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(t, ast.Name) and t.id.endswith("DB_PATH") for t in targets):
                    continue
                text = ast.unparse(node.value)
                absolute = any(
                    isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and (Path(c.value).is_absolute() or re.match(r"^[A-Za-z]:", c.value))
                    for c in ast.walk(node.value)
                )
                if absolute or any(token in text for token in SUSPICIOUS_DB_PATH_TOKENS):
                    problems.append(f"{path.relative_to(worktree).as_posix()}:{node.lineno}")
    return problems


# ============================================================
# Base de datos sintética
# ============================================================

def generate_credentials():
    return (
        f"sandbox_{secrets.token_hex(4)}",
        secrets.token_urlsafe(18),
    )


def bootstrap_database(db_path, *, username, password):
    """Login + IT con los servicios existentes; nunca sobre una BD previa."""
    from database import connection
    from backend.services import auth_service
    from backend.repositories.sqlite_trend_intelligence_repository import (
        SQLiteTrendIntelligenceRepository,
    )

    db_path = Path(db_path).resolve()
    if Path(connection.DB_PATH).resolve() != db_path:
        raise SandboxError("DB_PATH_MISMATCH")
    if os.path.lexists(db_path):
        raise SandboxError("DB_ALREADY_EXISTS")
    if not username or not password or username == "admin" or password == "1234":
        raise SandboxError("CREDENTIALS_INVALID")

    connection.initialize_database()
    SQLiteTrendIntelligenceRepository(db_path).ensure_schema()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(CONFIG_GLOBAL_DDL)
        conn.commit()

    if not auth_service.create_user(username, password):
        raise SandboxError("USER_CREATE_FAILED")


def inspect_database(db_path):
    """Lectura mode=ro de la BD sintética recién creada dentro del sandbox."""
    db_path = Path(db_path).resolve()
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if "users" in tables else 0
        collector = conn.execute(
            "SELECT 1 FROM config_global WHERE key = ?",
            (COLLECTOR_SETTINGS_KEY,),
        ).fetchone() if "config_global" in tables else None
    return dict(
        missing_tables=tuple(t for t in REQUIRED_TABLES if t not in tables),
        users=users,
        # El Collector queda sin configurar: NOT_CONFIGURED, nunca enabled.
        collector_configured=collector is not None,
    )


# ============================================================
# Subprocesos internos sobre el worktree
# ============================================================

def build_sandbox_env(source, dest=None):
    upper = {key.upper(): value for key, value in source.items()}
    env = {key: upper[key] for key in ENV_ALLOWLIST if key in upper}
    if dest is not None:
        env[SANDBOX_ENV] = "1"
        env[SANDBOX_ROOT_ENV] = str(dest)
    return env


def _import_from_worktree(root, modules):
    root = Path(root).resolve()
    if Path.cwd().resolve() != root:
        raise SandboxError("INTERNAL_CWD_MISMATCH")
    sys.path.insert(0, str(root))
    loaded = {}
    for name in modules:
        module = __import__(name, fromlist=["_"])
        if not _is_within(Path(module.__file__).resolve(), root):
            raise SandboxError(f"MODULE_OUTSIDE_WORKTREE:{name}")
        loaded[name] = module
    return root, loaded


def _internal_bootstrap(root):
    root, _ = _import_from_worktree(root, (
        "database.connection",
        "backend.services.auth_service",
        "backend.repositories.sqlite_trend_intelligence_repository",
    ))
    lines = sys.stdin.read().splitlines()
    if len(lines) < 2:
        raise SandboxError("CREDENTIALS_MISSING")
    bootstrap_database(root / DB_RELATIVE, username=lines[0], password=lines[1])
    print("BOOTSTRAP_OK", flush=True)


def _internal_probe(root):
    root, loaded = _import_from_worktree(root, [m for m, _ in PROBED_DB_PATHS] + [
        "backend.automation.browser_session",
    ])
    paths = {
        f"{name}.{attr}": str(Path(getattr(loaded[name], attr)).resolve())
        for name, attr in PROBED_DB_PATHS
    }
    paths["browser_session.project_root"] = str(
        loaded["backend.automation.browser_session"].get_project_root()
    )
    print(json.dumps(paths), flush=True)


def run_internal(mode, worktree, *, stdin_text=""):
    result = subprocess.run(
        [sys.executable, "-E", "-B", str(Path(__file__).resolve()), mode, str(worktree)],
        cwd=str(worktree),
        env=build_sandbox_env(os.environ),
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        # stderr nunca contiene la contraseña: solo viaja por stdin.
        raise SandboxError(f"INTERNAL_{mode.strip('-').upper()}_FAILED: {result.stderr.strip()[-600:]}")
    return result.stdout


def check_effective_paths(paths, *, dest, worktree):
    expected_db = (Path(worktree) / DB_RELATIVE).resolve()
    for key, value in paths.items():
        value = Path(value)
        if not _is_within(value, dest):
            raise SandboxError(f"EFFECTIVE_PATH_OUTSIDE_SANDBOX:{key}")
        if key.endswith("DB_PATH") and value != expected_db:
            raise SandboxError(f"EFFECTIVE_DB_PATH_MISMATCH:{key}")


# ============================================================
# Sello
# ============================================================

def write_seal(dest, *, sha, worktree, db_path, username):
    seal = dict(
        kind=SEAL_KIND,
        version=SEAL_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sha=sha,
        dest=str(dest),
        worktree=str(worktree),
        db_path=str(db_path),
        username=username,
    )
    with open(Path(dest) / SEAL_NAME, "x", encoding="utf-8") as handle:
        json.dump(seal, handle, indent=2)
    return seal


def read_seal(dest):
    path = Path(dest) / SEAL_NAME
    if not path.is_file() or _is_link_or_reparse(path):
        raise SandboxError("SEAL_MISSING")
    try:
        seal = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise SandboxError("SEAL_INVALID") from None
    worktree = Path(dest) / WORKTREE_NAME
    if (
        not isinstance(seal, dict)
        or seal.get("kind") != SEAL_KIND
        or seal.get("version") != SEAL_VERSION
        or seal.get("dest") != str(dest)
        or seal.get("worktree") != str(worktree)
        or seal.get("db_path") != str(worktree / DB_RELATIVE)
        or not FULL_SHA_PATTERN.fullmatch(str(seal.get("sha") or ""))
    ):
        raise SandboxError("SEAL_MISMATCH")
    return seal


# ============================================================
# Modos
# ============================================================

def prepare(dest, sha, *, repo_root=REPO_ROOT):
    """Prepara el sandbox. Nunca arranca el CRM."""
    checkouts = list_checkouts(repo_root)
    dest = validate_new_destination(dest, root=temp_root(), checkouts=checkouts)
    full_sha = resolve_commit(repo_root, sha)

    main_source = _git(["show", f"{full_sha}:app/main.py"], cwd=repo_root).stdout
    if not main_supports_sandbox(main_source):
        raise SandboxError("SHA_WITHOUT_SANDBOX_GUARD")

    create_private_directory(dest)
    worktree = dest / WORKTREE_NAME
    _git(["worktree", "add", "--detach", str(worktree), full_sha], cwd=repo_root)
    verify_worktree(worktree, full_sha, expect_db=False)

    username, password = generate_credentials()
    run_internal("--internal-bootstrap", worktree, stdin_text=f"{username}\n{password}\n")

    db_path = worktree / DB_RELATIVE
    report = inspect_database(db_path)
    if report["missing_tables"] or report["users"] != 1 or report["collector_configured"]:
        raise SandboxError(f"BOOTSTRAP_INCOMPLETE: {report}")
    verify_worktree(worktree, full_sha, expect_db=True)

    write_seal(dest, sha=full_sha, worktree=worktree, db_path=db_path, username=username)
    return dict(dest=dest, worktree=worktree, sha=full_sha, db_path=db_path,
                username=username, password=password)


def validate_launch(dest, *, repo_root=REPO_ROOT):
    raw = Path(dest)
    worktree = raw.resolve() / WORKTREE_NAME if raw.is_absolute() else None
    checkouts = [
        c for c in list_checkouts(repo_root)
        if worktree is None or not _same_path(c, worktree)
    ]
    dest = validate_location(dest, root=temp_root(), checkouts=checkouts)
    if not dest.is_dir():
        raise SandboxError("DEST_MISSING")
    seal = read_seal(dest)
    worktree = dest / WORKTREE_NAME

    verify_worktree(worktree, seal["sha"], expect_db=True)
    if os.path.lexists(worktree / ".env.local"):
        raise SandboxError("ENV_LOCAL_PRESENT")
    problems = scan_db_path_definitions(worktree)
    if problems:
        raise SandboxError("DB_PATH_DEFINITIONS_UNSAFE: " + ", ".join(problems[:10]))

    paths = json.loads(run_internal("--internal-probe", worktree))
    check_effective_paths(paths, dest=dest, worktree=worktree)
    return dest, worktree


def launch(dest, *, repo_root=REPO_ROOT, popen=subprocess.Popen):
    dest, worktree = validate_launch(dest, repo_root=repo_root)
    return popen(
        [sys.executable, "-E", "-B", "-m", "app.main"],
        cwd=str(worktree),
        env=build_sandbox_env(os.environ, dest),
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Sandbox de desarrollo CRM Login -> Marketing -> IT (fail-closed).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--launch", action="store_true")
    mode.add_argument("--internal-bootstrap", metavar="ROOT", help=argparse.SUPPRESS)
    mode.add_argument("--internal-probe", metavar="ROOT", help=argparse.SUPPRESS)
    parser.add_argument("--dest", help="Directorio nuevo bajo el TEMP local del usuario")
    parser.add_argument("--sha", help="Commit fijo (obligatorio en --prepare)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.internal_bootstrap:
            _internal_bootstrap(args.internal_bootstrap)
            return 0
        if args.internal_probe:
            _internal_probe(args.internal_probe)
            return 0
        if not args.dest:
            raise SandboxError("DEST_REQUIRED")
        if args.prepare:
            if not args.sha:
                raise SandboxError("SHA_REQUIRED")
            result = prepare(args.dest, args.sha)
            print("SANDBOX_PREPARED=YES")
            print(f"DEST={result['dest']}")
            print(f"WORKTREE={result['worktree']}")
            print(f"SHA={result['sha']}")
            print(f"DB={result['db_path']}")
            print(f"USUARIO={result['username']}")
            # Única aparición de la contraseña: no se guarda en disco.
            print(f"CONTRASENA_TEMPORAL={result['password']}")
            print("CRM_LAUNCHED=NO")
            return 0
        process = launch(args.dest)
        return process.wait()
    except SandboxError as exc:
        print(f"SANDBOX_ABORTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

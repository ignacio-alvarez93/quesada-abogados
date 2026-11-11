"""
Smoke visual aislado del visor documental DV25 (WO-DV25-C2-C3 · C3). Fail-closed.

--check
    Solo lectura: no crea archivos, no abre bases de datos, no importa el CRM ni
    arranca Flet. Comprueba rama y HEAD del worktree, la puerta del archivo en Box
    cerrada en el código (EXECUTION_ENABLED = False, APPROVED_CONTRACT = None), el
    destino que usaría --launch (directorio nuevo bajo el TEMP local, fuera de todo
    checkout), el entorno mínimo del proceso hijo, las guardas en seco y que cada
    ruta de BD o de escritura definida a nivel de módulo en el cierre de
    importaciones del visor esté redirigida o revisada. Imprime CHECK=PASS (0) o
    CHECK=BLOCKED (2) con los motivos.

--launch
    Solo por acción humana. Repite --check; si pasa, crea un directorio NUEVO bajo
    TEMP y arranca un proceso hijo (entorno mínimo, cwd en ese directorio) que:
    1. instala las guardas (SQLite, escrituras, red, procesos) ANTES de importar
       el CRM;
    2. redirige toda DB_PATH cargada, la Bandeja, la caché de previsualizaciones y
       la carpeta de herramientas PDF al sandbox;
    3. genera 10 PDF sintéticos, una Bandeja sintética, una raíz Box simulada y una
       BD SQLite sintética, y verifica las rutas efectivas;
    4. solo entonces abre Flet con el visor REAL (open_document_viewer_modal con
       comparador, notas, vinculación y revisión de archivo).
    Si algo falla antes del paso 4 imprime BLOCKED y Flet no se abre.

No: app.main, login, quesada.db, Box Drive, red, perfiles reales, .env ni
credenciales. El archivo en Box sigue cerrado: el diálogo solo revisa. Las
herramientas PDF se muestran sin manejadores (deshabilitadas, con su motivo).

Límites (no es aislamiento del sistema operativo):
- las guardas actúan dentro del proceso Python del smoke; el cliente de escritorio
  de Flet es otro proceso y puede usar su caché del perfil (~/.flet) y el TEMP;
- el proceso corre con el usuario actual y puede LEER lo que este puede leer;
- las rutas de BD ligadas como argumento por defecto de una función no se
  redirigen: las cubre la guarda de sqlite3.connect, que rechaza cualquier BD
  fuera del sandbox;
- las importaciones diferidas del backend no se recorren en --check (podrían
  arrastrar todo el CRM): también las cubren las guardas en tiempo de ejecución;
- la guarda de red cubre socket.connect y la resolución de nombres; las conexiones
  solapadas de asyncio en Windows y los procesos lanzados por asyncio no pasan por
  esas funciones y no quedan interceptados.
"""

import argparse
import ast
import builtins
from contextlib import closing
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import url2pathname


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "dev" / "crm_it_sandbox_launcher.py"
HABITUAL_DB = REPO_ROOT / "database" / "quesada.db"
ARCHIVE_SERVICE = REPO_ROOT / "backend" / "services" / "document_viewer_box_archive_service.py"
PERMISSION_SERVICE = REPO_ROOT / "backend" / "services" / "document_viewer_archive_permission_service.py"

EXPECTED_BRANCH = "feature/document-viewer-dv25-seleccion-nomenclatura"
PROTECTED_BRANCHES = ("main", "master")
SANDBOX_PREFIX = "dv25_smoke_"
SEAL_NAME = "dv25_smoke_sandbox.json"
SEAL_KIND = "QUESADA_DV25_DOCUMENTAL_SMOKE"
DOC_COUNT = 10
# Usuario sintético de la BD de prueba (fixture DV24), nunca uno real.
ACTOR = {"id": 1, "username": "ana"}

# Raíces del cierre estático de --check y módulos que carga --launch.
ENTRY_MODULES = (
    "database.connection",
    "backend.services.document_inbox_service",
    "backend.services.document_viewer_service",
    "backend.services.document_viewer_notes_service",
    "backend.services.document_viewer_box_archive_service",
    "frontend.components.document_viewer_modal",
    "frontend.components.document_viewer_multidoc",
    "frontend.components.document_viewer_notes_panel",
    "frontend.components.document_viewer_link_dialog",
    "frontend.components.document_viewer_archive_dialog",
    "frontend.components.pdf_tools_toolbar_adapter",
    "frontend.components.bulk_action_bar",
)
PROJECT_PACKAGES = ("backend", "database", "frontend")
# Solo las importaciones diferidas de los componentes del visor forman parte del recorrido.
LAZY_FOLLOWED = ("frontend.components.document_viewer_",)
# (módulo, atributo, ruta relativa al sandbox): todo lo que el visor puede escribir.
WRITE_REDIRECTS = (
    ("backend.services.document_inbox_service", "INBOX_ROOT", "bandeja"),
    ("backend.services.document_inbox_service", "INBOX_ORIGINALS", "bandeja/originals"),
    ("backend.services.document_inbox_service", "INBOX_PROCESSED", "bandeja/processed"),
    ("backend.services.document_inbox_service", "INBOX_REJECTED", "bandeja/rejected"),
    ("backend.services.document_inbox_service", "INBOX_TMP", "bandeja/tmp"),
    ("backend.services.document_viewer_service", "PREVIEW_DIR", "previews"),
    ("backend.services.document_tools.safe_file_service", "DOCUMENT_TOOLS_ROOT", "document_tools"),
)
DB_NAME = re.compile(r"DB_PATH$")
PATH_NAME = re.compile(r"(_PATH|_DIR|_DIRS|_ROOT|_ROOTS|_FOLDER|_ORIGINALS|_PROCESSED|_REJECTED|_TMP)$")
# Ubicaciones de código o recursos de solo lectura (esquemas y migraciones).
READ_ONLY_NAME = re.compile(r"^(PROJECT_ROOT|REPO_ROOT|BASE_DIR)$|(SCHEMA|MIGRATION)_PATH$")
SENSITIVE_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|BOX_|QUESADA_DB", re.I)
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
DDL_ACTIONS = frozenset(getattr(sqlite3, name) for name in (
    "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW",
    "SQLITE_ALTER_TABLE", "SQLITE_DROP_TABLE", "SQLITE_DROP_INDEX", "SQLITE_DROP_TRIGGER",
    "SQLITE_DROP_VIEW") if hasattr(sqlite3, name))
# DDL idempotente (CREATE ... IF NOT EXISTS) de ensure_document_inbox_schema(): al abrir el visor,
# la actividad de notas lee get_inbox_events(), que lo ejecuta (comportamiento productivo previo a
# DV25). Es el único DDL tolerado al navegar y nunca cambia el esquema (schema_snapshot).
INBOX_SCHEMA_DDL = frozenset(
    [(sqlite3.SQLITE_CREATE_TABLE, name) for name in ("document_inbox_items", "document_inbox_events")]
    + [(sqlite3.SQLITE_CREATE_INDEX, name) for name in (
        "idx_document_inbox_status", "idx_document_inbox_expedient", "idx_document_inbox_client")])

# Contrato de las suites certificadas: CRM_SQL (DV24) + CATALOG_SQL (DV25-P3A).
# test_dv25_documental_smoke comprueba que es idéntico a esas fixtures.
SANDBOX_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users (id, username, password_hash, is_active)
VALUES (1, 'ana', 'x', 1), (2, 'luis', 'x', 1), (3, 'baja', 'x', 0);
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT, activo INTEGER DEFAULT 1);
INSERT INTO clientes VALUES (7, 'Cliente Siete', 1), (8, 'Cliente Ocho', 1);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, cliente_id INTEGER, numero_expediente TEXT, activo INTEGER DEFAULT 1
);
INSERT INTO expedientes VALUES
    (42, 7, 'EXP-42', 1), (43, 7, 'EXP-43', 1), (50, 8, 'EXP-50', 1),
    (51, 7, 'EXP-51', 0), (52, NULL, 'EXP-52', 1);

CREATE TABLE config_tipos_expediente (id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT);
CREATE TABLE config_subtipos_expediente (
    id INTEGER PRIMARY KEY, tipo_expediente_id INTEGER, codigo TEXT, nombre TEXT);
CREATE TABLE config_documentos_catalogo (
    id INTEGER PRIMARY KEY, codigo TEXT NOT NULL UNIQUE, nombre TEXT, descripcion TEXT,
    categoria TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE config_nomenclaturas_catalogo (
    id INTEGER PRIMARY KEY, tipo_expediente_id INTEGER, subtipo_expediente_id INTEGER,
    documento_catalogo_id INTEGER, rol_documental TEXT, prioridad INTEGER DEFAULT 100,
    activo INTEGER DEFAULT 1);
CREATE TABLE config_nomenclaturas_procedimentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT, documento_catalogo_id INTEGER NOT NULL,
    patron_nombre TEXT NOT NULL, extension_permitida TEXT NOT NULL DEFAULT 'pdf,jpg,jpeg,png',
    prioridad INTEGER NOT NULL DEFAULT 100, activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT, updated_at TEXT);
ALTER TABLE expedientes ADD COLUMN tipo_expediente_id INTEGER;
ALTER TABLE expedientes ADD COLUMN subtipo_expediente_id INTEGER;
ALTER TABLE expedientes ADD COLUMN box_folder_path TEXT;
INSERT INTO config_tipos_expediente VALUES (1, 'ARRAIGO', 'Arraigo'), (2, 'NACIONALIDAD', 'Nacionalidad');
INSERT INTO config_subtipos_expediente VALUES (10, 1, 'SOCIAL', 'Social'), (11, 1, 'LABORAL', 'Laboral');
INSERT INTO config_documentos_catalogo (id, codigo, nombre, categoria, activo) VALUES
    (100, 'PASAPORTE', 'PASAPORTE', 'IDENTIDAD', 1),
    (101, 'CONTRATO', 'CONTRATO DE TRABAJO', 'LABORAL', 1),
    (102, 'VIDA_LABORAL', 'VIDA LABORAL', 'LABORAL', 1),
    (103, 'CERT_NACIMIENTO', 'CERTIFICADO DE NACIMIENTO', 'REGISTRO', 1),
    (104, 'RETIRADO', 'DOCUMENTO RETIRADO', 'OTROS', 0),
    (200, 'ADMISION_TRAMITE', 'ADMISIÓN A TRÁMITE', 'TRAMITACION', 1),
    (201, 'RESOLUCION_CONCESION', 'RESOLUCIÓN DE CONCESIÓN', 'RESOLUCION', 1);
-- family (tipo) wide, subtype only, a repeated pattern, another role, another family, inactive.
INSERT INTO config_nomenclaturas_catalogo
    (tipo_expediente_id, subtipo_expediente_id, documento_catalogo_id, rol_documental, prioridad) VALUES
    (1, NULL, 100, 'SOLICITANTE', 10), (1, NULL, 100, 'SOLICITANTE', 20), (1, 10, 101, NULL, 30),
    (1, 11, 102, NULL, 5), (1, NULL, 100, 'FAMILIAR', 40), (2, NULL, 103, NULL, 10),
    (1, NULL, 104, NULL, 1);
INSERT INTO config_nomenclaturas_procedimentales (documento_catalogo_id, patron_nombre, prioridad)
VALUES (200, 'ADMISION A TRAMITE', 10), (201, 'RESOLUCION DE CONCESION', 20);
UPDATE expedientes SET tipo_expediente_id = 1, subtipo_expediente_id = 10 WHERE id = 42;
UPDATE expedientes SET tipo_expediente_id = 1, subtipo_expediente_id = 11 WHERE id = 43;
UPDATE expedientes SET tipo_expediente_id = 2 WHERE id = 50;
"""

# id: (nombre visible, estado, cliente, expediente). Todo sintético.
DOCUMENTS = {
    1: ("Pasaporte", "linked", 7, 42),
    2: ("NIE", "linked", 7, 42),
    3: ("Contrato de trabajo", "linked", 7, 42),
    4: ("Nomina enero", "linked", 7, 42),
    5: ("Nomina febrero", "pending", 7, None),
    6: ("Vida laboral", "pending", 7, None),
    7: ("Empadronamiento", "linked", 7, 43),
    8: ("Certificado de nacimiento", "pending", None, None),
    9: ("Resolucion", "linked", 7, 42),
    10: ("Requerimiento", "pending", 7, None),
}
BOX_FOLDERS = ("EXP-42/01 IDENTIDAD", "EXP-42/02 LABORAL/Contratos", "EXP-43/Requerimientos")
BOX_EXISTING = "EXP-42/01 IDENTIDAD/PASAPORTE SOLICITANTE.pdf"


class SmokeBlocked(RuntimeError):
    pass


class SandboxViolation(PermissionError):
    """Acceso fuera del sandbox rechazado por las guardas del smoke."""


# ============================================================
# Rutas
# ============================================================

def _inside(child, parent):
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


def db_target(database, uri=False):
    """Archivo que abriría ``sqlite3.connect``; None para memoria."""
    text = os.fsdecode(database) if isinstance(database, bytes) else os.fspath(database)
    if text in ("", ":memory:"):
        return None
    if uri or text.startswith("file:"):
        parsed = urlparse(text)
        if "mode=memory" in parsed.query:
            return None
        return Path(url2pathname(parsed.path))
    return Path(text)


def _launcher():
    """crm_it_sandbox_launcher: TEMP, destino nuevo, checkouts y entorno mínimo (reutilizados)."""
    spec = importlib.util.spec_from_file_location("crm_it_sandbox_launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readonly_temp_root():
    """TEMP del usuario sin tocar disco: tempfile.gettempdir() crea un archivo de prueba la primera vez."""
    for name in ("TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value and Path(value).is_dir():
            return Path(value).resolve()
    raise SmokeBlocked("TEMP_UNDEFINED")


def flet_write_roots():
    """Escrituras permitidas además del sandbox: TEMP y la caché de Flet del perfil."""
    return (Path(tempfile.gettempdir()), Path.home() / ".flet")


def flet_exec_roots():
    """Ejecutables que el smoke puede lanzar: solo el cliente de escritorio de Flet."""
    roots = [Path.home() / ".flet"]
    for name in ("flet_desktop", "flet"):
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.origin:
            roots.append(Path(spec.origin).parent)
    return tuple(roots)


# ============================================================
# Guardas
# ============================================================

class Guards:
    """Ganchos fail-closed del proceso del smoke; se instalan antes de importar el CRM.

    ``navigation`` marca la fase posterior a la preparación: cualquier DDL que se
    intente desde entonces queda registrado en ``ddl`` (sin bloquearlo).
    """

    def __init__(self, sandbox, *, write_roots=(), exec_roots=()):
        self.sandbox = Path(sandbox).resolve()
        self.write_roots = tuple(Path(p).resolve() for p in (self.sandbox, *write_roots))
        self.exec_roots = tuple(Path(p).resolve() for p in exec_roots)
        self.violations = []
        self.connections = []
        self.ddl = []
        self.navigation = False
        self._saved = []

    # ------------------------------------------------------------ predicados

    def db_allowed(self, database, uri=False):
        target = db_target(database, uri)
        return target is None or _inside(target, self.sandbox)

    def write_allowed(self, path):
        if isinstance(path, int):
            return True  # descriptor ya abierto
        try:
            target = Path(os.fsdecode(os.fspath(path)))
        except TypeError:
            return False
        return any(_inside(target, root) for root in self.write_roots)

    def exec_allowed(self, args):
        program = args if isinstance(args, (str, bytes, os.PathLike)) else (list(args) or [""])[0]
        try:
            target = Path(os.fsdecode(os.fspath(program)))
        except TypeError:
            return False
        return target.is_absolute() and any(_inside(target, root) for root in self.exec_roots)

    @staticmethod
    def host_allowed(address):
        if not isinstance(address, tuple):
            return True  # AF_UNIX: comunicación local entre procesos
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if host in ("", "localhost"):
            return True
        try:
            ip = ipaddress.ip_address(str(host).split("%")[0])
        except ValueError:
            return False
        return ip.is_loopback or ip.is_unspecified  # 0.0.0.0/:: solo sirven para escuchar en local

    # ------------------------------------------------------------ instalación

    def refuse(self, kind, target):
        self.violations.append((kind, str(target)))
        print(f"DV25_SMOKE_GUARD: {kind} rechazado: {target}", file=sys.stderr, flush=True)
        raise SandboxViolation(f"Smoke DV25: {kind} fuera del sandbox: {target}")

    def _swap(self, owner, name, value):
        # Un atributo heredado (socket.socket.connect) se retira al desinstalar, no se copia.
        self._saved.append((owner, name, getattr(owner, name), name in vars(owner)))
        setattr(owner, name, value)

    def _authorizer(self, action, *_args):
        if self.navigation and action in DDL_ACTIONS:
            self.ddl.append((action, _args[0] if _args else None))
        return sqlite3.SQLITE_OK

    def install(self):
        if self._saved:
            raise SmokeBlocked("GUARDS_ALREADY_INSTALLED")
        guards = self
        real_connect = sqlite3.connect

        def connect(database, *args, **kwargs):
            if not guards.db_allowed(database, kwargs.get("uri", False)):
                guards.refuse("sqlite3.connect", database)
            target = db_target(database, kwargs.get("uri", False))
            guards.connections.append(str(target) if target is not None else ":memory:")
            conn = real_connect(database, *args, **kwargs)
            conn.set_authorizer(guards._authorizer)
            return conn

        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wxa+") and not guards.write_allowed(file):
                guards.refuse("open", file)
            return real_open(file, mode, *args, **kwargs)

        real_os_open = os.open

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & WRITE_FLAGS and not guards.write_allowed(path):
                guards.refuse("os.open", path)
            return real_os_open(path, flags, *args, **kwargs)

        def path_guard(name, original, positions=(0,)):
            def wrapper(*args, **kwargs):
                for index in positions:
                    if index < len(args) and not guards.write_allowed(args[index]):
                        guards.refuse(f"os.{name}", args[index])
                return original(*args, **kwargs)
            return wrapper

        def refuse_always(name):
            def wrapper(*args, **kwargs):
                guards.refuse(name, args[0] if args else "")
            return wrapper

        real_popen = subprocess.Popen

        class GuardedPopen(real_popen):
            def __init__(self, args, *rest, **kwargs):
                if not guards.exec_allowed(args):
                    guards.refuse("subprocess", args)
                super().__init__(args, *rest, **kwargs)

        real_sock_connect = socket.socket.connect
        real_sock_connect_ex = socket.socket.connect_ex
        real_getaddrinfo = socket.getaddrinfo

        def sock_connect(sock, address):
            if not guards.host_allowed(address):
                guards.refuse("socket.connect", address)
            return real_sock_connect(sock, address)

        def sock_connect_ex(sock, address):
            if not guards.host_allowed(address):
                guards.refuse("socket.connect", address)
            return real_sock_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            if host is not None and not guards.host_allowed((host, 0)):
                guards.refuse("socket.getaddrinfo", host)
            return real_getaddrinfo(host, *args, **kwargs)

        self._swap(sqlite3, "connect", connect)
        self._swap(builtins, "open", guarded_open)
        self._swap(io, "open", guarded_open)
        self._swap(os, "open", guarded_os_open)
        for name in ("mkdir", "rmdir", "remove", "unlink", "truncate", "utime", "chmod", "removedirs"):
            if hasattr(os, name):
                self._swap(os, name, path_guard(name, getattr(os, name)))
        for name in ("rename", "renames", "replace", "symlink", "link"):
            if hasattr(os, name):
                self._swap(os, name, path_guard(name, getattr(os, name), positions=(0, 1)))
        if hasattr(os, "startfile"):
            self._swap(os, "startfile", refuse_always("os.startfile"))
        self._swap(subprocess, "Popen", GuardedPopen)
        self._swap(socket.socket, "connect", sock_connect)
        self._swap(socket.socket, "connect_ex", sock_connect_ex)
        self._swap(socket, "getaddrinfo", getaddrinfo)
        return self

    def uninstall(self):
        while self._saved:
            owner, name, value, own = self._saved.pop()
            if own:
                setattr(owner, name, value)
            else:
                delattr(owner, name)


# ============================================================
# --check (solo lectura)
# ============================================================

@dataclass
class CheckReport:
    lines: list
    blockers: list

    @property
    def ok(self):
        return not self.blockers

    def text(self):
        status = "CHECK=PASS" if self.ok else "CHECK=BLOCKED"
        out = [status, *self.lines]
        out += [f"BLOCKER={reason}" for reason in self.blockers]
        out += ["FLET_LAUNCHED=NO", "WRITES=NONE"]
        return "\n".join(out)


def _git(args, runner=subprocess.run):
    # GIT_OPTIONAL_LOCKS=0: ninguna lectura refresca el índice en disco.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    result = runner(["git", *args], cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
                    encoding="utf-8")
    return result.returncode, (result.stdout or "").strip()


def git_state(expect_head=None, runner=subprocess.run):
    """(líneas, bloqueos) de rama y HEAD."""
    code, branch = _git(["symbolic-ref", "--short", "-q", "HEAD"], runner)
    head_code, head = _git(["rev-parse", "--verify", "HEAD"], runner)
    lines = [f"BRANCH={branch if code == 0 else '(detached)'}", f"HEAD={head if head_code == 0 else '?'}"]
    blockers = []
    if head_code != 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        blockers.append("HEAD_UNRESOLVED")
    if code != 0 or not branch:
        blockers.append("BRANCH_DETACHED")
    elif branch in PROTECTED_BRANCHES:
        blockers.append(f"BRANCH_PROTECTED:{branch}")
    elif branch != EXPECTED_BRANCH:
        blockers.append(f"BRANCH_UNEXPECTED:{branch}")
    if expect_head and head != str(expect_head).strip().lower():
        blockers.append("HEAD_MISMATCH")
    return lines, blockers


def literal_assignments(path, name):
    """Valores literales asignados a ``name`` a nivel de módulo ("<expr>" si no son literales)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    values = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            values.append(node.value.value if isinstance(node.value, ast.Constant) else "<expr>")
    return values


def gate_state():
    """(EXECUTION_ENABLED, APPROVED_CONTRACT) leídos del código, sin importarlo."""
    execution = literal_assignments(ARCHIVE_SERVICE, "EXECUTION_ENABLED")
    contract = literal_assignments(PERMISSION_SERVICE, "APPROVED_CONTRACT")
    return (execution[0] if len(execution) == 1 else "<ambiguo>",
            contract[0] if len(contract) == 1 else "<ambiguo>")


def module_file(name, root=REPO_ROOT):
    base = Path(root).joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _resolve_import(node, module, root, package=False):
    """Módulos del proyecto que importa un nodo Import/ImportFrom (``package``: el módulo es un __init__.py)."""
    names = []
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        base = node.module or ""
        if node.level:
            # En un __init__.py el nivel 1 es el propio paquete; en un módulo, el paquete que lo contiene.
            parts = module.split(".")
            parent = parts[:len(parts) - node.level + (1 if package else 0)]
            base = ".".join(parent + ([base] if base else []))
        for alias in node.names:
            child = f"{base}.{alias.name}" if base else alias.name
            names.append(child if module_file(child, root) else base)
    return [n for n in names if n and n.split(".")[0] in (*PROJECT_PACKAGES, "app")]


def _top_level_nodes(tree):
    """Nodos ejecutados al importar (cuerpo del módulo, incluidos if/try), sin funciones, en orden."""
    nodes, pending = [], list(tree.body)
    while pending:
        node = pending.pop()
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody", "handlers"):
            pending.extend(getattr(node, field, None) or ())
    return sorted(nodes, key=lambda node: (node.lineno, node.col_offset))


def _is_path_expr(node, known):
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in {"Path", "__file__", *known}:
            return True
        if isinstance(child, ast.Attribute) and child.attr in ("path", "parent", "parents"):
            return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and re.search(r"[\\/]", child.value):
            return True
    return False


def closure_report(entry_modules=ENTRY_MODULES, root=REPO_ROOT):
    """Cierre de importaciones del visor y clasificación de cada constante de ruta."""
    redirects = {(module, attr) for module, attr, _ in WRITE_REDIRECTS}
    seen, pending, constants, problems = set(), list(entry_modules), [], []
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        parts = module.split(".")
        # Importar a.b.c ejecuta también a/__init__.py y a/b/__init__.py.
        pending.extend(".".join(parts[:index]) for index in range(1, len(parts)))
        path = module_file(module, root)
        if path is None:
            if not Path(root).joinpath(*parts).is_dir():  # un paquete de espacio de nombres no ejecuta nada
                problems.append(f"MODULE_NOT_FOUND:{module}")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top = _top_level_nodes(tree)
        nodes = list(ast.walk(tree)) if module.startswith(LAZY_FOLLOWED) else top
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                pending.extend(_resolve_import(node, module, root, package=path.name == "__init__.py"))
        known = set()
        for node in top:
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, ast.AnnAssign) and node.value is not None else [])
            for target in targets:
                name = getattr(target, "id", None)
                if not name or not (DB_NAME.search(name) or PATH_NAME.search(name)):
                    continue
                if not _is_path_expr(node.value, known):
                    continue
                known.add(name)
                if DB_NAME.search(name):
                    kind = "db-redirect"
                elif (module, name) in redirects:
                    kind = "write-redirect"
                elif READ_ONLY_NAME.search(name):
                    kind = "read-only"
                else:
                    kind = "UNREVIEWED"
                constants.append((module, name, kind))
    if any(m == "app" or m.startswith("app.") for m in seen):
        problems.append("APP_IN_CLOSURE")
    found = {(module, name) for module, name, _ in constants}
    problems += [f"REDIRECT_TARGET_MISSING:{m}.{a}" for m, a in sorted(redirects - found)]
    problems += [f"UNREVIEWED_PATH_CONSTANT:{m}.{n}" for m, n, kind in constants if kind == "UNREVIEWED"]
    for required in (("database.connection", "DB_PATH"), ("backend.services.expedient_service", "DB_PATH")):
        if required not in found:
            problems.append(f"REQUIRED_DB_PATH_MISSING:{required[0]}.{required[1]}")
    return sorted(seen), sorted(constants), problems


def dry_guard_problems(candidate):
    """Predicados de las guardas sobre el destino previsto, sin instalarlas ni escribir."""
    guards = Guards(candidate)
    expectations = (
        (guards.db_allowed(HABITUAL_DB), False, "DB_HABITUAL"),
        (guards.db_allowed(HABITUAL_DB.as_uri() + "?mode=ro", uri=True), False, "DB_HABITUAL_URI"),
        (guards.db_allowed(os.fsencode(HABITUAL_DB)), False, "DB_HABITUAL_BYTES"),
        (guards.db_allowed(":memory:"), True, "DB_MEMORY"),
        (guards.db_allowed(Path(candidate) / "crm.db"), True, "DB_SANDBOX"),
        (guards.write_allowed(REPO_ROOT / "data" / "document_previews" / "x.png"), False, "WRITE_REPO"),
        (guards.write_allowed(Path(candidate) / "previews" / "x.png"), True, "WRITE_SANDBOX"),
        (guards.host_allowed(("203.0.113.7", 443)), False, "NET_EXTERNAL"),
        (guards.host_allowed(("box.com", 443)), False, "NET_NAME"),
        (guards.host_allowed(("127.0.0.1", 8550)), True, "NET_LOOPBACK"),
        (guards.exec_allowed(["explorer.exe", "x.pdf"]), False, "EXEC_SYSTEM_VIEWER"),
    )
    return [f"GUARD_PREDICATE:{name}" for value, expected, name in expectations if value is not expected]


def run_check(expect_head=None, runner=subprocess.run):
    lines, blockers = [], []
    git_lines, git_blockers = git_state(expect_head, runner)
    lines += git_lines
    blockers += git_blockers

    execution, contract = gate_state()
    lines.append(f"GATE=EXECUTION_ENABLED={execution} APPROVED_CONTRACT={contract}")
    if execution is not False:
        blockers.append("GATE_OPEN_IN_CODE:EXECUTION_ENABLED")
    if contract is not None:
        blockers.append("GATE_OPEN_IN_CODE:APPROVED_CONTRACT")

    try:
        launcher = _launcher()
        root = readonly_temp_root()
        candidate = root / f"{SANDBOX_PREFIX}{secrets.token_hex(6)}"
        launcher.validate_new_destination(candidate, root=root, checkouts=launcher.list_checkouts(REPO_ROOT))
        lines.append(f"SANDBOX_PARENT={root}")
        if _inside(HABITUAL_DB, root):
            blockers.append("HABITUAL_DB_UNDER_TEMP")
        env = launcher.build_sandbox_env(os.environ)
        extra = sorted(set(env) - set(launcher.ENV_ALLOWLIST))
        sensitive = sorted(key for key in env if SENSITIVE_ENV.search(key))
        lines.append(f"CHILD_ENV_KEYS={len(env)}")
        blockers += [f"CHILD_ENV_NOT_ALLOWED:{key}" for key in extra]
        blockers += [f"CHILD_ENV_SENSITIVE:{key}" for key in sensitive]
        blockers += dry_guard_problems(candidate)
    except Exception as exc:  # SandboxError del launcher u otra causa: fail-closed
        blockers.append(f"SANDBOX_LOCATION:{exc}")

    try:
        modules, constants, problems = closure_report()
        lines.append(f"CLOSURE_MODULES={len(modules)}")
        for module, name, kind in constants:
            lines.append(f"PATH_CONSTANT={module}.{name}:{kind}")
        blockers += problems
    except (OSError, SyntaxError) as exc:
        blockers.append(f"CLOSURE_UNREADABLE:{exc}")
    return CheckReport(lines, blockers)


# ============================================================
# Sandbox (solo dentro del proceso del smoke o de sus tests)
# ============================================================

@dataclass
class SmokeContext:
    sandbox: Path
    db: Path
    box: Path
    items: list


def import_crm():
    """Carga los módulos del visor; las guardas ya deben estar instaladas."""
    return {name: importlib.import_module(name) for name in ENTRY_MODULES}


def redirect(sandbox, db):
    """Redirige toda DB_PATH cargada y las rutas de escritura; devuelve lo necesario para restaurar."""
    sandbox, saved = Path(sandbox).resolve(), []

    def swap(module, name, value):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    for name, module in sorted(sys.modules.items()):
        if module is None or name.split(".")[0] not in PROJECT_PACKAGES:
            continue
        for attr, value in sorted(vars(module).items()):
            if DB_NAME.search(attr) and isinstance(value, (str, Path)):
                swap(module, attr, str(db) if isinstance(value, str) else Path(db))
    for module_name, attr, relative in WRITE_REDIRECTS:
        module = sys.modules.get(module_name) or importlib.import_module(module_name)
        swap(module, attr, sandbox.joinpath(*relative.split("/")))
    return saved


def restore(saved):
    for module, name, value in reversed(saved):
        setattr(module, name, value)


def effective_path_problems(sandbox, db):
    """Rutas efectivas tras redirigir: todas dentro del sandbox, las dos BD obligatorias en la sintética."""
    db, problems = Path(db).resolve(), []
    for name, module in sorted(sys.modules.items()):
        if module is None or name.split(".")[0] not in PROJECT_PACKAGES:
            continue
        for attr, value in vars(module).items():
            if DB_NAME.search(attr) and isinstance(value, (str, Path)) and Path(value).resolve() != db:
                problems.append(f"DB_PATH_NOT_REDIRECTED:{name}.{attr}")
    for module_name, attr, _ in WRITE_REDIRECTS:
        if not _inside(getattr(sys.modules[module_name], attr), sandbox):
            problems.append(f"WRITE_PATH_NOT_REDIRECTED:{module_name}.{attr}")
    for module_name in ("database.connection", "backend.services.expedient_service"):
        module = sys.modules.get(module_name)
        if module is None or Path(module.DB_PATH).resolve() != db:
            problems.append(f"REQUIRED_DB_PATH:{module_name}")
    return problems


def schema_snapshot(db):
    """(tipo, nombre, sql) de sqlite_master: se compara antes y después de navegar."""
    with closing(sqlite3.connect(db)) as conn:
        return sorted(conn.execute("SELECT type, name, COALESCE(sql, '') FROM sqlite_master"))


def make_pdf(path, title, pages):
    import fitz  # PyMuPDF, ya dependencia del visor

    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for number in range(pages):
            page = document.new_page(width=420, height=595)
            page.insert_text((40, 60), "DOCUMENTO SINTETICO - SMOKE DV25", fontsize=14)
            page.insert_text((40, 90), f"{title} - pagina {number + 1} de {pages}", fontsize=12)
            page.insert_text((40, 120), "Sin datos reales. Generado bajo TEMP.", fontsize=10)
        document.save(str(path))


def build_sandbox_data(sandbox):
    """10 PDF, Bandeja, Box simulado y BD sintéticos; todo bajo ``sandbox`` (ya redirigido)."""
    from backend.services import document_inbox_service as inbox
    from backend.services import document_viewer_notes_service as notes_service

    sandbox = Path(sandbox).resolve()
    db, box = sandbox / "crm.db", sandbox / "box"
    if os.path.lexists(db):
        raise SmokeBlocked("SANDBOX_DB_PREEXISTING")
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(SANDBOX_SQL)
        conn.commit()
    for folder in BOX_FOLDERS:
        box.joinpath(*folder.split("/")).mkdir(parents=True)
    make_pdf(box.joinpath(*BOX_EXISTING.split("/")), "Pasaporte ya archivado en Box simulado", 1)
    with closing(sqlite3.connect(db)) as conn:
        for expedient_id, folder in ((42, "EXP-42"), (43, "EXP-43")):
            conn.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = ?",
                         (str(box / folder), expedient_id))
        conn.commit()

    inbox.ensure_document_inbox_schema()  # tablas de Bandeja en la BD sintética, carpetas bajo sandbox
    items = []
    with closing(sqlite3.connect(db)) as conn:
        for item_id, (name, status, client_id, expedient_id) in DOCUMENTS.items():
            path = Path(inbox.INBOX_ORIGINALS) / f"{item_id:04d}_{name.replace(' ', '_')}.pdf"
            make_pdf(path, name, 2 + item_id % 3)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            conn.execute(
                "INSERT INTO document_inbox_items (id, original_filename, stored_filename, stored_path, "
                "file_ext, size_bytes, sha256, status, client_id, expedient_id, notes, updated_at) "
                "VALUES (?, ?, ?, ?, 'pdf', ?, ?, ?, ?, ?, ?, ?)",
                (item_id, f"{name}.pdf", path.name, str(path), path.stat().st_size, digest, status,
                 client_id, expedient_id, f"Documento sintético {item_id}", "2026-11-11 09:00:00"))
            items.append({"id": item_id, "path": str(path), "name": f"{name}.pdf", "status": status})
        conn.commit()
    # Migración de notas (DV24-P2) aplicada ahora, antes de Flet: navegar no hace DDL.
    notes_service.load_document_notes(ACTOR, {"inbox_item_id": 1, "path": items[0]["path"]}, db_path=str(db))
    return SmokeContext(sandbox=sandbox, db=db, box=box, items=items)


def prepare_runtime(sandbox, guards):
    """Importa, redirige, construye y verifica. Cualquier fallo: SmokeBlocked (Flet no se abre)."""
    sandbox = Path(sandbox).resolve()
    import_crm()
    saved = redirect(sandbox, sandbox / "crm.db")
    context = build_sandbox_data(sandbox)
    problems = effective_path_problems(sandbox, context.db)
    problems += [f"GUARD_VIOLATION:{kind}:{target}" for kind, target in guards.violations]
    problems += [f"CONNECTION_OUTSIDE:{target}" for target in guards.connections
                 if target != ":memory:" and not _inside(target, sandbox)]
    if problems:
        raise SmokeBlocked("; ".join(problems))
    return context, saved


# ============================================================
# Visor real sobre la Bandeja sintética
# ============================================================

def viewer_api():
    """Los componentes reales del CRM que usa el smoke (sin copias ni maquetas)."""
    from backend.services import document_inbox_service
    from backend.services import document_viewer_box_archive_service
    from frontend.components.bulk_action_bar import bulk_action_bar
    from frontend.components.document_viewer_link_dialog import ViewerLinking
    from frontend.components.document_viewer_modal import open_document_viewer_modal
    from frontend.components.document_viewer_multidoc import marked_queue, view_selected_action
    from frontend.components.document_viewer_notes_panel import ViewerNotes
    from frontend.components.pdf_tools_toolbar_adapter import PdfToolsToolbarAdapter

    return dict(open=open_document_viewer_modal, marked_queue=marked_queue,
                view_selected_action=view_selected_action, bulk_action_bar=bulk_action_bar,
                ViewerNotes=ViewerNotes, ViewerLinking=ViewerLinking,
                PdfToolsToolbarAdapter=PdfToolsToolbarAdapter, inbox=document_inbox_service,
                archive=document_viewer_box_archive_service)


class SmokeHarness:
    """Listado mínimo de la Bandeja sintética: marca documentos y abre con ellos el visor REAL.

    No imita el visor: solo construye la cola marcada (marked_queue, como la Bandeja) y llama
    a open_document_viewer_modal con notas, vinculación y la barra PDF reales.
    """

    def __init__(self, page, context, guards, *, run=None, near_window=3):
        import flet as ft

        self.ft, self.page, self.context, self.guards = ft, page, context, guards
        self.near_window = near_window
        self.api = viewer_api()
        self.marked = set()
        self.dialog = None
        self.visible = [{"path": item["path"], "name": item["name"], "key": f"inbox:{item['id']}",
                         "inbox_item_id": item["id"]} for item in context.items]
        self.notes = self.api["ViewerNotes"](actor=ACTOR, db_path=str(context.db), run=run)
        self.linking = self.api["ViewerLinking"](actor=ACTOR, on_linked=lambda result: self.refresh(),
                                                 db_path=str(context.db))
        self.status = ft.Text("", size=12, color="#B42318")
        self.counters = ft.Text("", size=12, color="#475467")
        self.bar = ft.Container()
        self.rows = ft.Column(spacing=2)

    def control(self):
        from frontend.components.app_button import secondary_button

        ft, archive = self.ft, self.api["archive"]
        gate = archive.execution_blocker() or "abierta"
        self.refresh(update=False)
        return ft.Column(spacing=10, controls=[
            ft.Text("Smoke documental DV25 · SANDBOX", size=22, weight=ft.FontWeight.BOLD, color="#003B7A"),
            ft.Text(f"Directorio: {self.context.sandbox}", size=12, selectable=True),
            ft.Text("BD sintética · Bandeja sintética · Box simulado bajo TEMP · sin CRM habitual ni red.",
                    size=12),
            ft.Text(f"Archivo en Box: EXECUTION_ENABLED = {archive.EXECUTION_ENABLED} · {gate}", size=12,
                    color="#B54708"),
            ft.Row(wrap=True, spacing=8, controls=[
                secondary_button("Marcar 2", lambda e: self.mark(2)),
                secondary_button("Marcar 4", lambda e: self.mark(4)),
                secondary_button(f"Marcar todos ({DOC_COUNT})", lambda e: self.mark(DOC_COUNT)),
                secondary_button("Limpiar", lambda e: self.mark(0)),
                secondary_button("Actualizar contadores", lambda e: self.refresh()),
            ]),
            self.bar, self.counters, self.status, self.rows,
        ])

    def refresh(self, update=True):
        ft = self.ft
        queue = self.queue()
        self.bar.content = self.api["bulk_action_bar"](
            title="Bandeja sintética", selected_count=len(self.marked),
            actions=[self.api["view_selected_action"](self.open_selected, len(queue))])
        self.rows.controls = [
            ft.Checkbox(label=f"#{entry['inbox_item_id']} · {entry['name']} · "
                              f"{self.context.items[index]['status']}",
                        value=entry["key"] in self.marked,
                        on_change=lambda e, key=entry["key"]: self.toggle(key, e.control.value))
            for index, entry in enumerate(self.visible)]
        idempotent = sum(1 for entry in self.guards.ddl if entry in INBOX_SCHEMA_DDL)
        self.counters.value = (f"DDL idempotente de Bandeja (actividad de notas): {idempotent} · "
                               f"Otro DDL tras abrir Flet: {len(self.guards.ddl) - idempotent} · "
                               f"Accesos bloqueados: {len(self.guards.violations)}")
        if update:
            self.page.update()

    def mark(self, count):
        self.marked = {entry["key"] for entry in self.visible[:count]}
        self.refresh()

    def toggle(self, key, value):
        (self.marked.add if value else self.marked.discard)(key)
        self.refresh()

    def queue(self):
        return self.api["marked_queue"](self.visible, self.marked)

    def show_error(self, exc):
        self.status.value = str(exc)
        self.page.update()

    def open_selected(self, e=None):
        queue = self.queue()
        if not queue:
            self.show_error("Marca uno o más documentos.")
            return None
        inbox = self.api["inbox"]
        items = {entry["path"]: inbox.get_inbox_item(entry["inbox_item_id"]) for entry in queue}
        toolbar = self.api["PdfToolsToolbarAdapter"](
            lambda request: items.get(str(request.path)), {}, self.show_error)
        self.dialog = self.api["open"](
            self.page, queue[0]["path"], title=queue[0]["name"], queue=queue, queue_index=0,
            notes=self.notes.with_inbox_items([(entry["path"], entry["inbox_item_id"]) for entry in queue]),
            linking=self.linking.with_inbox_items(items.items()), toolbar_actions=toolbar,
            on_error=self.show_error, near_window=self.near_window)
        return self.dialog


def flet_main(context, guards):
    def main(page):
        import flet as ft

        page.title = "DV25 · Smoke documental (SANDBOX)"
        page.padding = 16
        page.scroll = ft.ScrollMode.AUTO
        try:
            page.window.maximized = True
        except Exception:
            pass
        page.add(SmokeHarness(page, context, guards).control())
    return main


# ============================================================
# Modos
# ============================================================

def write_seal(dest, sha):
    seal = dict(kind=SEAL_KIND, dest=str(dest), sha=sha, repo=str(REPO_ROOT))
    with open(Path(dest) / SEAL_NAME, "x", encoding="utf-8") as handle:
        json.dump(seal, handle, indent=2)


def read_seal(dest):
    path = Path(dest) / SEAL_NAME
    try:
        seal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SmokeBlocked("SEAL_MISSING") from None
    if not isinstance(seal, dict) or seal.get("kind") != SEAL_KIND or seal.get("dest") != str(dest):
        raise SmokeBlocked("SEAL_MISMATCH")
    return seal


def launch(expect_head=None, popen=subprocess.Popen):
    report = run_check(expect_head)
    print(report.text())
    if not report.ok:
        print("LAUNCH=BLOCKED", file=sys.stderr)
        return 2
    launcher = _launcher()
    root = launcher.temp_root()
    dest = launcher.validate_new_destination(root / f"{SANDBOX_PREFIX}{secrets.token_hex(6)}", root=root,
                                             checkouts=launcher.list_checkouts(REPO_ROOT))
    launcher.create_private_directory(dest)
    head = next(line.split("=", 1)[1] for line in report.lines if line.startswith("HEAD="))
    write_seal(dest, head)
    print(f"SANDBOX={dest}")
    process = popen([sys.executable, "-E", "-B", str(Path(__file__).resolve()), "--internal-run", str(dest)],
                    cwd=str(dest), env=launcher.build_sandbox_env(os.environ))
    return process.wait()


def internal_run(dest):
    dest = Path(dest).resolve()
    try:
        read_seal(dest)
        if Path.cwd().resolve() != dest:
            raise SmokeBlocked("CWD_NOT_SANDBOX")
        if any(entry.name != SEAL_NAME for entry in dest.iterdir()):
            raise SmokeBlocked("SANDBOX_NOT_FRESH")
    except SmokeBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    guards = Guards(dest, write_roots=flet_write_roots(), exec_roots=flet_exec_roots()).install()
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        context, _saved = prepare_runtime(dest, guards)
        import flet as ft
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("FLET_LAUNCHED=NO")
        return 2
    print(f"SANDBOX_READY=YES DB={context.db} BOX={context.box} DOCS={len(context.items)}")
    schema = schema_snapshot(context.db)
    print("FLET_LAUNCHED=YES")
    guards.navigation = True
    ft.run(flet_main(context, guards))
    unexpected = [entry for entry in guards.ddl if entry not in INBOX_SCHEMA_DDL]
    print(f"DDL_AFTER_LAUNCH={len(guards.ddl)} UNEXPECTED_DDL={len(unexpected)} "
          f"SCHEMA_CHANGED={'YES' if schema_snapshot(context.db) != schema else 'NO'} "
          f"BLOCKED_ACCESSES={len(guards.violations)}")
    for action, name in unexpected:
        print(f"UNEXPECTED_DDL={action}:{name}")
    for kind, target in guards.violations:
        print(f"BLOCKED_ACCESS={kind}:{target}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Smoke visual aislado del visor documental DV25 (fail-closed).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Solo lectura: no lanza Flet ni escribe.")
    mode.add_argument("--launch", action="store_true", help="Solo por acción humana: sandbox TEMP + Flet.")
    mode.add_argument("--internal-run", metavar="DIR", help=argparse.SUPPRESS)
    parser.add_argument("--expect-head", metavar="SHA", help="HEAD exacto exigido (opcional).")
    return parser


def main(argv=None):
    sys.dont_write_bytecode = True  # --check no deja ni __pycache__
    args = build_parser().parse_args(argv)
    if args.internal_run:
        return internal_run(args.internal_run)
    if args.launch:
        return launch(args.expect_head)
    report = run_check(args.expect_head)
    print(report.text())
    return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())

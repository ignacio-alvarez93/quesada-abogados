"""WO-KNOW-CHAT-01: lectura mínima del CRM para el Chat Knowledge.

BD SQLite temporal con datos FICTICIOS: los marcadores ``PII-*-FICT``
representan campos personales que nunca deben salir del adaptador.
Nunca se abre ``database/quesada.db``.
"""

import ast
import hashlib
from pathlib import Path
import sqlite3

import pytest

from backend.repositories import knowledge_chat_context_repository as module
from backend.repositories.knowledge_chat_context_repository import (
    MAX_EXPEDIENT_EVENTS,
    KnowledgeChatContextRepository,
    KnowledgeChatContextUnavailable,
)
from database.connection import get_readonly_connection


MODULE_PATH = Path(module.__file__)

PII_MARKERS = (
    "PII-NOMBRE-FICT",
    "PII-APELLIDO-FICT",
    "PII-NIE-FICT",
    "PII-PASAPORTE-FICT",
    "PII-DNI-FICT",
    "PII-TEL-FICT",
    "PII-EMAIL-FICT",
    "PII-IBAN-FICT",
    "PII-RESPONSABLE-FICT",
    "PII-REGISTRO-FICT",
    "PII-OBS-FICT",
    "PII-OBSINT-FICT",
    "PII-BOX-FICT",
    "PII-TITULO-EVENTO-FICT",
    "PII-DESC-EVENTO-FICT",
    "PII-USUARIO-EVENTO-FICT",
)

OTHER_EXPEDIENT_MARKER = "OTRO-EXPEDIENTE-FICT"

CRM_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    primer_apellido TEXT,
    nie TEXT,
    pasaporte TEXT,
    dni TEXT,
    telefono TEXT,
    email TEXT,
    iban TEXT
);
CREATE TABLE config_tipos_expediente (
    id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT NOT NULL
);
CREATE TABLE config_estados_documentales (
    id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT NOT NULL
);
CREATE TABLE config_estados_administrativos (
    id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT NOT NULL
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    numero_expediente TEXT NOT NULL UNIQUE,
    tipo_expediente_id INTEGER,
    estado_documental_id INTEGER,
    estado_administrativo_id INTEGER,
    estado_presentacion TEXT,
    responsable TEXT,
    fecha_apertura TEXT,
    fecha_presentacion TEXT,
    fecha_resolucion TEXT,
    numero_registro TEXT,
    organo_presentacion TEXT,
    provincia TEXT,
    observaciones TEXT,
    observaciones_internas TEXT,
    box_folder_path TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE expediente_eventos (
    id INTEGER PRIMARY KEY,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    usuario TEXT,
    fecha_evento TEXT NOT NULL
);
"""


def create_fictitious_crm(db_path, *, with_events=True, event_count=2):
    """Crea un CRM mínimo y ficticio en ``db_path`` (solo para tests)."""

    connection = sqlite3.connect(db_path)

    try:
        schema = CRM_SCHEMA

        if not with_events:
            schema = schema.split("CREATE TABLE expediente_eventos")[0]

        connection.executescript(schema)
        connection.executemany(
            "INSERT INTO users (id, username, password_hash, is_active) "
            "VALUES (?, ?, ?, ?)",
            [
                (7, "operador.ficticio", "hash-ficticio", 1),
                (8, "inactivo.ficticio", "hash-ficticio", 0),
            ],
        )
        connection.executemany(
            "INSERT INTO clientes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "PII-NOMBRE-FICT", "PII-APELLIDO-FICT", "PII-NIE-FICT",
                 "PII-PASAPORTE-FICT", "PII-DNI-FICT", "PII-TEL-FICT",
                 "PII-EMAIL-FICT", "PII-IBAN-FICT"),
                (2, OTHER_EXPEDIENT_MARKER, None, None, None, None, None,
                 None, None),
            ],
        )
        connection.execute(
            "INSERT INTO config_tipos_expediente VALUES (1, 'ARR', "
            "'ARRAIGO FICTICIO')"
        )
        connection.execute(
            "INSERT INTO config_estados_documentales VALUES (1, 'COMP', "
            "'DOCUMENTACIÓN COMPLETA')"
        )
        connection.execute(
            "INSERT INTO config_estados_administrativos VALUES (1, 'TRAM', "
            "'EN TRÁMITE')"
        )
        connection.executemany(
            "INSERT INTO expedientes (id, cliente_id, numero_expediente, "
            "tipo_expediente_id, estado_documental_id, "
            "estado_administrativo_id, estado_presentacion, responsable, "
            "fecha_apertura, fecha_presentacion, fecha_resolucion, "
            "numero_registro, organo_presentacion, provincia, "
            "observaciones, observaciones_internas, box_folder_path, activo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (11, 1, "EXP-FICT-0001", 1, 1, 1, "PRESENTADO",
                 "PII-RESPONSABLE-FICT", "2099-01-01", "2099-01-15", None,
                 "PII-REGISTRO-FICT", "OFICINA FICTICIA", "PROVINCIA FICTICIA",
                 "PII-OBS-FICT", "PII-OBSINT-FICT", "C:/PII-BOX-FICT", 1),
                (12, 2, "EXP-FICT-0002", 1, 1, 1, OTHER_EXPEDIENT_MARKER,
                 OTHER_EXPEDIENT_MARKER, "2099-02-01", None, None, None,
                 OTHER_EXPEDIENT_MARKER, OTHER_EXPEDIENT_MARKER,
                 OTHER_EXPEDIENT_MARKER, None, None, 1),
                (13, 1, "EXP-FICT-0003", 1, 1, 1, "ARCHIVADO", None,
                 "2098-01-01", None, None, None, None, None, None, None,
                 None, 0),
            ],
        )

        if with_events:
            connection.executemany(
                "INSERT INTO expediente_eventos (expediente_id, cliente_id, "
                "tipo_evento, titulo, descripcion, estado_anterior, "
                "estado_nuevo, usuario, fecha_evento) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (11, 1, "CAMBIO_ESTADO", "PII-TITULO-EVENTO-FICT",
                     "PII-DESC-EVENTO-FICT", "PENDIENTE", "PRESENTADO",
                     "PII-USUARIO-EVENTO-FICT", f"2099-01-{day:02d}")
                    for day in range(1, event_count + 1)
                ]
                + [
                    (12, 2, OTHER_EXPEDIENT_MARKER, OTHER_EXPEDIENT_MARKER,
                     None, None, None, None, "2099-02-02"),
                ],
            )

        connection.commit()
    finally:
        connection.close()


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def crm_db(tmp_path):
    path = tmp_path / "crm_ficticio.db"
    create_fictitious_crm(path)
    return path


class TracingConnect:
    """Envuelve get_readonly_connection y registra cada sentencia."""

    def __init__(self):
        self.statements = []

    def __call__(self, db_path=None):
        connection = get_readonly_connection(db_path)
        connection.set_trace_callback(self.statements.append)
        return connection


# ------------------------------------------------------------
# Proyección mínima
# ------------------------------------------------------------


def test_projection_contains_only_allowlisted_facts(crm_db):
    repository = KnowledgeChatContextRepository(crm_db)

    projection = repository.get_expedient_projection(11)

    facts = {key: value for key, _label, value in projection.facts}
    assert facts == {
        "numero_expediente": "EXP-FICT-0001",
        "tipo_expediente": "ARRAIGO FICTICIO",
        "estado_documental": "DOCUMENTACIÓN COMPLETA",
        "estado_administrativo": "EN TRÁMITE",
        "estado_presentacion": "PRESENTADO",
        "fecha_apertura": "2099-01-01",
        "fecha_presentacion": "2099-01-15",
        "organo_presentacion": "OFICINA FICTICIA",
        "provincia": "PROVINCIA FICTICIA",
    }
    assert projection.numero_expediente == "EXP-FICT-0001"


def test_projection_never_exposes_personal_or_free_text_fields(crm_db):
    projection = KnowledgeChatContextRepository(crm_db).get_expedient_projection(11)
    rendered = repr(projection)

    for marker in PII_MARKERS:
        assert marker not in rendered


def test_events_expose_only_dates_types_and_states(crm_db):
    projection = KnowledgeChatContextRepository(crm_db).get_expedient_projection(11)

    assert [event.fecha_evento for event in projection.events] == [
        "2099-01-02",
        "2099-01-01",
    ]
    event = projection.events[0]
    assert (event.tipo_evento, event.estado_anterior, event.estado_nuevo) == (
        "CAMBIO_ESTADO",
        "PENDIENTE",
        "PRESENTADO",
    )


def test_only_the_selected_expedient_is_read(crm_db):
    projection = KnowledgeChatContextRepository(crm_db).get_expedient_projection(11)

    assert OTHER_EXPEDIENT_MARKER not in repr(projection)
    assert "EXP-FICT-0002" not in repr(projection)


def test_inactive_or_unknown_expedient_is_none(crm_db):
    repository = KnowledgeChatContextRepository(crm_db)

    assert repository.get_expedient_projection(13) is None
    assert repository.get_expedient_projection(999) is None


def test_events_are_bounded(tmp_path):
    path = tmp_path / "muchos_eventos.db"
    create_fictitious_crm(path, event_count=MAX_EXPEDIENT_EVENTS + 5)

    projection = KnowledgeChatContextRepository(path).get_expedient_projection(11)

    assert len(projection.events) == MAX_EXPEDIENT_EVENTS
    assert projection.events_truncated is True


def test_missing_events_table_still_projects_expedient(tmp_path):
    path = tmp_path / "sin_eventos.db"
    create_fictitious_crm(path, with_events=False)

    projection = KnowledgeChatContextRepository(path).get_expedient_projection(11)

    assert projection.events == ()
    assert projection.numero_expediente == "EXP-FICT-0001"


@pytest.mark.parametrize("bad", [0, -1, True, "11", None])
def test_invalid_expedient_ids_are_rejected(crm_db, bad):
    with pytest.raises(ValueError):
        KnowledgeChatContextRepository(crm_db).get_expedient_projection(bad)


# ------------------------------------------------------------
# Resolución exacta, sin búsqueda transversal
# ------------------------------------------------------------


@pytest.mark.parametrize(
    "numero, expected",
    [
        ("EXP-FICT-0001", 11),
        ("  EXP-FICT-0001  ", 11),
        ("EXP-FICT", None),
        ("EXP-FICT-%", None),
        ("%", None),
        ("exp-fict-0001", None),
        ("EXP-FICT-0003", None),
        ("", None),
        ("X" * 65, None),
    ],
)
def test_find_by_number_is_exact_and_active_only(crm_db, numero, expected):
    repository = KnowledgeChatContextRepository(crm_db)

    assert repository.find_expedient_id_by_number(numero) == expected


def test_repository_offers_no_listing_or_search_api():
    public = {
        name
        for name in dir(KnowledgeChatContextRepository)
        if not name.startswith("_")
    }

    assert public == {
        "is_active_user",
        "find_expedient_id_by_number",
        "get_expedient_projection",
    }


# ------------------------------------------------------------
# Identidad de sesión
# ------------------------------------------------------------


def test_active_user_requires_matching_id_username_and_active_flag(crm_db):
    repository = KnowledgeChatContextRepository(crm_db)

    assert repository.is_active_user(7, "operador.ficticio") is True
    assert repository.is_active_user(7, "otro.nombre") is False
    assert repository.is_active_user(8, "inactivo.ficticio") is False
    assert repository.is_active_user(999, "operador.ficticio") is False
    assert repository.is_active_user(7, "") is False


# ------------------------------------------------------------
# Solo lectura: sin DML/DDL/PRAGMA, sin crear ficheros
# ------------------------------------------------------------


def test_reads_never_modify_the_database(crm_db):
    before = _digest(crm_db)
    tracer = TracingConnect()
    repository = KnowledgeChatContextRepository(crm_db, connect=tracer)

    repository.is_active_user(7, "operador.ficticio")
    repository.find_expedient_id_by_number("EXP-FICT-0001")
    repository.get_expedient_projection(11)

    assert _digest(crm_db) == before
    assert tracer.statements

    for statement in tracer.statements:
        assert statement.lstrip().upper().startswith("SELECT"), statement
        assert "SELECT *" not in statement.upper()


def test_readonly_connection_rejects_writes(crm_db):
    connection = get_readonly_connection(crm_db)

    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM expedientes")
    finally:
        connection.close()


def test_missing_database_is_unavailable_and_not_created(tmp_path):
    missing = tmp_path / "no_existe.db"
    repository = KnowledgeChatContextRepository(missing)

    with pytest.raises(KnowledgeChatContextUnavailable) as raised:
        repository.get_expedient_projection(11)

    assert not missing.exists()
    assert str(missing) not in str(raised.value)


def test_missing_schema_is_unavailable_without_leaking_sql(tmp_path):
    empty = tmp_path / "vacia.db"
    sqlite3.connect(empty).close()

    with pytest.raises(KnowledgeChatContextUnavailable) as raised:
        KnowledgeChatContextRepository(empty).get_expedient_projection(11)

    assert "SELECT" not in str(raised.value)
    assert "no such table" not in str(raised.value)


def test_sql_constants_are_parameterized_selects_without_pii_columns():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    statements = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.endswith("_SQL")
    }

    assert set(statements) == {
        "_EXPEDIENT_SQL",
        "_EVENTS_SQL",
        "_EXPEDIENT_ID_BY_NUMBER_SQL",
        "_ACTIVE_USER_SQL",
    }

    forbidden = (
        "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "PRAGMA",
        "ATTACH", "REPLACE", "LIKE", "SELECT *", "CLIENTES", "NIE",
        "PASAPORTE", "DNI", "TELEFONO", "EMAIL", "IBAN", "RESPONSABLE",
        "NUMERO_REGISTRO", "OBSERVACIONES", "BOX_FOLDER_PATH", "TITULO",
        "DESCRIPCION", "USUARIO", "PASSWORD",
    )

    for name, sql in statements.items():
        upper = sql.upper()
        assert upper.lstrip().startswith("SELECT"), name
        assert "?" in sql, name

        for word in forbidden:
            assert word not in upper, (name, word)


def test_module_uses_readonly_adapter_and_no_write_connection():
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert ("database.connection", "get_readonly_connection") in imported
    assert ("database.connection", "get_connection") not in imported
    assert "sqlite3.connect" not in source
    assert ".commit(" not in source
    assert "executescript" not in source

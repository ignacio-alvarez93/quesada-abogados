"""
Persistencia de notas del visor documental (DV24-P2).

Responsabilidades:
- aplicar la migración aditiva e idempotente de document_viewer_notes;
- leer el usuario autenticado para verificar autoría;
- listar e insertar notas por identidad documental;
- leer las notas vinculadas a un expediente (DV30-02, solo lectura).

Solo abre bases SQLite ya existentes (mode=rw): una base ausente es un
error, nunca se crea. No valida rutas ni permisos: eso es del servicio.
No escribe en document_inbox_items, expedientes ni Box; de Bandeja solo
lee expedient_id y original_filename para la proyección al expediente.
"""

import sqlite3
from functools import wraps
from pathlib import Path

from database.connection import get_existing_connection


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20261109_01_create_document_viewer_notes.sql"
)

NOTE_COLUMNS = (
    "id, document_kind, document_ref, inbox_item_id, expediente_id, relative_path, "
    "content_sha256, size_bytes, body, author_user_id, author_username, status, "
    "request_id, created_at"
)


class NotesStorageError(Exception):
    """Base ausente, esquema no aplicable o error SQLite."""


def _storage(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except sqlite3.Error as exc:
            raise NotesStorageError(str(exc)) from exc
    return wrapped


def _connect(db_path=None):
    conn = get_existing_connection(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _dict(row):
    return dict(row) if row else None


@_storage
def ensure_schema(*, db_path=None):
    """Aplica la migración; idempotente."""
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    conn = _connect(db_path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


@_storage
def get_user(user_id, *, db_path=None):
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, username, is_active FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        return _dict(row)
    finally:
        conn.close()


@_storage
def list_notes(document_ref, *, content_sha256=None, db_path=None):
    """Notas activas de un documento, la más reciente primero.

    Con ``content_sha256`` solo las de esa revisión del archivo.
    """
    sql = f"SELECT {NOTE_COLUMNS} FROM document_viewer_notes WHERE document_ref = ? AND status = 'active'"
    params = [document_ref]
    if content_sha256 is not None:
        sql += " AND content_sha256 = ?"
        params.append(content_sha256)
    sql += " ORDER BY id DESC"
    conn = _connect(db_path)
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@_storage
def count_other_revisions(document_ref, content_sha256, *, db_path=None):
    """Notas activas del mismo documento sobre otra revisión del archivo."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM document_viewer_notes
            WHERE document_ref = ? AND content_sha256 != ? AND status = 'active'
            """,
            (document_ref, content_sha256),
        ).fetchone()
        return int(row["total"] or 0)
    finally:
        conn.close()


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


@_storage
def list_expedient_linked_notes(expediente_id, *, conn=None, db_path=None):
    """Notas activas vinculadas de forma verificada a un expediente (DV30-02).

    Solo lectura: nunca crea esquema. Si document_viewer_notes no existe
    devuelve una lista vacía. Incluye:
    - notas ``expedient`` cuyo expediente_id y document_ref son de este expediente;
    - notas ``inbox`` cuyo ítem de Bandeja tiene hoy expedient_id = este expediente.
    La vinculación de Bandeja se lee en cada consulta: si cambia, cambia la
    proyección. Nunca se vincula por nombre ni ruta.

    Con ``conn`` reutiliza la conexión del llamador y no la cierra.
    """
    expediente_id = int(expediente_id)
    owns_connection = conn is None
    if owns_connection:
        conn = _connect(db_path)
    try:
        if not _table_exists(conn, "document_viewer_notes"):
            return []
        expedient_prefix = f"expedient:{expediente_id}:"
        sql = f"""
            SELECT {NOTE_COLUMNS}, NULL AS inbox_original_filename
            FROM document_viewer_notes
            WHERE status = 'active'
              AND document_kind = 'expedient'
              AND expediente_id = ?
              AND substr(document_ref, 1, ?) = ?
        """
        params = [expediente_id, len(expedient_prefix), expedient_prefix]
        if _table_exists(conn, "document_inbox_items"):
            sql += """
            UNION ALL
            SELECT n.id, n.document_kind, n.document_ref, n.inbox_item_id,
                   n.expediente_id, n.relative_path, n.content_sha256,
                   n.size_bytes, n.body, n.author_user_id, n.author_username,
                   n.status, n.request_id, n.created_at,
                   i.original_filename AS inbox_original_filename
            FROM document_viewer_notes n
            JOIN document_inbox_items i ON i.id = n.inbox_item_id
            WHERE n.status = 'active'
              AND n.document_kind = 'inbox'
              AND n.document_ref = 'inbox:' || n.inbox_item_id
              AND i.expedient_id = ?
            """
            params.append(expediente_id)
        sql += " ORDER BY created_at ASC, id ASC"
        cursor = conn.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if owns_connection:
            conn.close()


@_storage
def insert_note(note, *, db_path=None):
    """Inserta una nota; un request_id repetido no crea otra fila.

    Devuelve (fila guardada para ese request_id, creada ahora).
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO document_viewer_notes (
                document_kind, document_ref, inbox_item_id, expediente_id,
                relative_path, content_sha256, size_bytes, body,
                author_user_id, author_username, status, request_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(request_id) DO NOTHING
            """,
            (
                note["document_kind"],
                note["document_ref"],
                note.get("inbox_item_id"),
                note.get("expediente_id"),
                note.get("relative_path"),
                note["content_sha256"],
                int(note["size_bytes"]),
                note["body"],
                int(note["author_user_id"]),
                note["author_username"],
                note["request_id"],
                note["created_at"],
            ),
        )
        created = cursor.rowcount == 1
        conn.commit()
        row = conn.execute(
            f"SELECT {NOTE_COLUMNS} FROM document_viewer_notes WHERE request_id = ?",
            (note["request_id"],),
        ).fetchone()
        return _dict(row), created
    finally:
        conn.close()

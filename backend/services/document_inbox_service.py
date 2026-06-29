from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INBOX_ROOT = PROJECT_ROOT / "data" / "document_inbox"
INBOX_ORIGINALS = INBOX_ROOT / "originals"
INBOX_PROCESSED = INBOX_ROOT / "processed"
INBOX_REJECTED = INBOX_ROOT / "rejected"
INBOX_TMP = INBOX_ROOT / "tmp"

VALID_STATUSES = {
    "pending",
    "linked",
    "copied_to_box",
    "reviewed",
    "discarded",
    "duplicate",
    "error",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dirs() -> None:
    for folder in (INBOX_ROOT, INBOX_ORIGINALS, INBOX_PROCESSED, INBOX_REJECTED, INBOX_TMP):
        folder.mkdir(parents=True, exist_ok=True)


def _dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _safe_filename(name: str) -> str:
    name = (name or "documento").strip()
    name = name.replace("\\", "_").replace("/", "_").replace(":", "_")
    name = "".join(ch for ch in name if ch not in '<>"|?*')
    return name or "documento"


def _unique_destination(folder: Path, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(filename)
    candidate = folder / filename

    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2

    while True:
        alt = folder / f"{stem}_{counter}{suffix}"
        if not alt.exists():
            return alt
        counter += 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_columns(conn, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}
    except Exception:
        return set()


def _connect():
    """
    Helper local de conexión para las funciones añadidas de Bandeja Documental.

    Se usa como compatibilidad interna para no acoplar las nuevas funciones
    al nombre exacto del helper de conexión usado por otros servicios.
    """
    try:
        from database.connection import get_connection
        return get_connection()
    except ImportError:
        from database.connection import get_db_connection
        return get_db_connection()


def _dict_row_factory(cursor, row):
    """
    Convierte filas sqlite3 en diccionarios.

    Helper local usado por las funciones de Bandeja Documental que necesitan
    devolver estructuras dict limpias al frontend.
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def ensure_document_inbox_schema() -> None:
    _ensure_dirs()

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                source_type TEXT DEFAULT 'manual',
                source_label TEXT,

                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,

                file_ext TEXT,
                mime_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,

                status TEXT DEFAULT 'pending',

                client_id INTEGER,
                expedient_id INTEGER,

                linked_document_path TEXT,
                copied_to_box_path TEXT,
                copied_to_box_at TEXT,

                notes TEXT,
                detected_text TEXT,
                metadata_json TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_at TEXT DEFAULT CURRENT_TIMESTAMP,
                message TEXT,
                metadata_json TEXT,
                FOREIGN KEY (item_id) REFERENCES document_inbox_items(id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_status
            ON document_inbox_items(status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_expedient
            ON document_inbox_items(expedient_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_client
            ON document_inbox_items(client_id)
            """
        )
        conn.commit()


def _record_event(
    conn,
    item_id: int,
    event_type: str,
    message: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO document_inbox_events (
            item_id, event_type, event_at, message, metadata_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(item_id),
            event_type,
            _now(),
            message or "",
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )



def _norm_document_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _metadata_dict(value) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    return {}


def _find_existing_inbox_item_for_source(
    source_path: Path,
    original_filename: str = "",
    source_type: str = "",
    client_id=None,
    expedient_id=None,
    sha256: str = "",
    size_bytes: int = 0,
) -> Dict[str, Any]:
    """
    Evita duplicados reales en Bandeja Documental.

    Criterios:
    - misma ruta de origen en metadata imported_from / box_original_path;
    - mismo stored_path, especialmente si intentan reimportar desde data/document_inbox;
    - mismo SHA256 global;
    - fallback: mismo nombre + tamaño + source_type + expediente.
    """
    ensure_document_inbox_schema()

    src_norm = _norm_document_path(str(source_path))
    digest = str(sha256 or "").strip().lower()
    filename_norm = str(original_filename or "").strip().lower()
    source_type_norm = str(source_type or "manual").strip().lower()
    expedient_key = str(expedient_id or "")

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM document_inbox_items
            ORDER BY id DESC
            """
        ).fetchall()

        for row in rows:
            item = dict(row)
            metadata = _metadata_dict(item.get("metadata_json") or "")

            item_stored = _norm_document_path(item.get("stored_path") or "")
            item_imported_from = _norm_document_path(
                metadata.get("imported_from")
                or metadata.get("box_original_path")
                or metadata.get("source_path")
                or ""
            )
            item_sha = str(
                item.get("sha256")
                or metadata.get("sha256")
                or metadata.get("file_sha256")
                or ""
            ).strip().lower()

            if src_norm and item_stored and src_norm == item_stored:
                item["already_imported"] = True
                item["dedupe_reason"] = "stored_path"
                return item

            if src_norm and item_imported_from and src_norm == item_imported_from:
                item["already_imported"] = True
                item["dedupe_reason"] = "imported_from"
                return item

            if digest and item_sha and digest == item_sha:
                item["already_imported"] = True
                item["dedupe_reason"] = "sha256"
                return item

            same_name = filename_norm and filename_norm == str(item.get("original_filename") or "").strip().lower()
            same_size = bool(size_bytes) and int(item.get("size_bytes") or 0) == int(size_bytes)
            same_source = source_type_norm == str(item.get("source_type") or "manual").strip().lower()
            same_expedient = expedient_key == str(item.get("expedient_id") or "")

            if same_name and same_size and same_source and same_expedient:
                item["already_imported"] = True
                item["dedupe_reason"] = "filename_size_source_expedient"
                return item

    return {}


def import_file_to_inbox(
    file_path: str,
    source_type: str = "manual",
    source_label: str = "",
    notes: str = "",
    client_id=None,
    expedient_id=None,
    metadata=None,
    metadata_json=None,
) -> Dict[str, Any]:
    ensure_document_inbox_schema()

    src = Path(str(file_path or "")).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"No existe el archivo indicado: {file_path}")

    original_filename = src.name
    source_stat = src.stat()
    source_digest = _sha256(src)

    existing = _find_existing_inbox_item_for_source(
        source_path=src,
        original_filename=original_filename,
        source_type=source_type or "manual",
        client_id=client_id,
        expedient_id=expedient_id,
        sha256=source_digest,
        size_bytes=source_stat.st_size,
    )
    if existing:
        return existing

    stored_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_filename(original_filename)}"
    dest = _unique_destination(INBOX_ORIGINALS, stored_filename)

    shutil.copy2(src, dest)

    size_bytes = dest.stat().st_size
    digest = _sha256(dest)
    mime_type = mimetypes.guess_type(str(dest))[0] or ""
    file_ext = dest.suffix.lower().lstrip(".")

    metadata_payload = {}
    metadata_payload.update(_metadata_dict(metadata))
    metadata_payload.update(_metadata_dict(metadata_json))
    metadata_payload.setdefault("imported_from", str(src))
    metadata_payload.setdefault("source_path", str(src))
    metadata_payload["sha256"] = digest
    metadata_payload["file_sha256"] = digest
    metadata_payload["size_bytes"] = size_bytes
    metadata_payload["source_size_bytes"] = source_stat.st_size
    metadata_payload["source_modified_at"] = source_stat.st_mtime

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO document_inbox_items (
                created_at, updated_at,
                source_type, source_label,
                original_filename, stored_filename, stored_path,
                file_ext, mime_type, size_bytes, sha256,
                status, notes, metadata_json,
                client_id, expedient_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                _now(),
                _now(),
                source_type or "manual",
                source_label or "",
                original_filename,
                dest.name,
                str(dest),
                file_ext,
                mime_type,
                size_bytes,
                digest,
                notes or "",
                json.dumps(metadata_payload, ensure_ascii=False),
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
            ),
        )
        item_id = int(cur.lastrowid)
        _record_event(
            conn,
            item_id,
            "imported",
            f"Documento importado desde {source_type or 'manual'}",
            {
                "source_path": str(src),
                "stored_path": str(dest),
                "sha256": digest,
                "already_imported": False,
            },
        )
        conn.commit()

    return get_inbox_item(item_id)



# === QUESADA DOCUMENT INBOX BATCHES START ===

def ensure_document_inbox_batch_schema():
    """
    Crea las tablas de grupos documentales de Bandeja.

    Un grupo documental es un lote lógico interno:
    - no toca Box;
    - no mueve documentos;
    - agrupa items de document_inbox_items para trabajo posterior:
      PDF tools, preparación, revisión y eventual copia a Box.
    """
    ensure_document_inbox_schema()

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                client_id INTEGER,
                expedient_id INTEGER,
                target_box_folder TEXT,
                notes TEXT,
                metadata_json TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_batch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                inbox_item_id INTEGER NOT NULL,
                order_index INTEGER DEFAULT 0,
                role TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(batch_id, inbox_item_id),
                FOREIGN KEY (batch_id) REFERENCES document_inbox_batches(id),
                FOREIGN KEY (inbox_item_id) REFERENCES document_inbox_items(id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_batches_status
            ON document_inbox_batches(status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_batches_expedient
            ON document_inbox_batches(expedient_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_batch_items_batch
            ON document_inbox_batch_items(batch_id)
            """
        )

        conn.commit()


def create_document_inbox_batch(
    name: str,
    inbox_item_ids=None,
    client_id=None,
    expedient_id=None,
    target_box_folder: str = "",
    notes: str = "",
    status: str = "draft",
):
    """
    Crea un grupo documental y opcionalmente añade items seleccionados.
    """
    import json
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("El grupo documental necesita un nombre.")

    item_ids = []
    for raw_id in inbox_item_ids or []:
        try:
            item_id = int(raw_id)
        except Exception:
            continue
        if item_id not in item_ids:
            item_ids.append(item_id)

    now = datetime.now().isoformat(timespec="seconds")

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO document_inbox_batches (
                created_at, updated_at, name, status,
                client_id, expedient_id, target_box_folder,
                notes, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                clean_name,
                status or "draft",
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
                str(target_box_folder or "").strip(),
                str(notes or "").strip(),
                json.dumps({"source": "document_inbox"}, ensure_ascii=False),
            ),
        )

        batch_id = int(cur.lastrowid)

        for index, item_id in enumerate(item_ids, start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO document_inbox_batch_items (
                    batch_id, inbox_item_id, order_index, role, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (batch_id, item_id, index, "", "", now),
            )

            try:
                _record_event(
                    conn,
                    item_id,
                    "batch_add",
                    f"Documento añadido al grupo documental #{batch_id}: {clean_name}",
                    {"batch_id": batch_id, "batch_name": clean_name},
                )
            except TypeError:
                try:
                    _record_event(
                        conn,
                        item_id,
                        "batch_add",
                        f"Documento añadido al grupo documental #{batch_id}: {clean_name}",
                    )
                except Exception:
                    pass
            except Exception:
                pass

        conn.commit()

    return get_document_inbox_batch(batch_id)


def list_document_inbox_batches(status=None, expedient_id=None, client_id=None, limit=200):
    """
    Lista grupos documentales con contador de documentos.
    """
    ensure_document_inbox_batch_schema()

    where = []
    params = []

    if status and status != "all":
        where.append("b.status = ?")
        params.append(status)

    if expedient_id:
        where.append("b.expedient_id = ?")
        params.append(int(expedient_id))

    if client_id:
        where.append("b.client_id = ?")
        params.append(int(client_id))

    sql = """
        SELECT
            b.*,
            COUNT(bi.id) AS item_count
        FROM document_inbox_batches b
        LEFT JOIN document_inbox_batch_items bi ON bi.batch_id = b.id
    """

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += """
        GROUP BY b.id
        ORDER BY b.updated_at DESC, b.id DESC
        LIMIT ?
    """
    params.append(int(limit or 200))

    with _connect() as conn:
        conn.row_factory = _dict_row_factory
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def get_document_inbox_batch(batch_id: int):
    """
    Devuelve un grupo documental con sus documentos.
    """
    ensure_document_inbox_batch_schema()

    with _connect() as conn:
        conn.row_factory = _dict_row_factory

        batch = conn.execute(
            "SELECT * FROM document_inbox_batches WHERE id = ?",
            (int(batch_id),),
        ).fetchone()

        if not batch:
            raise ValueError(f"No existe el grupo documental #{batch_id}")

        items = conn.execute(
            """
            SELECT
                bi.id AS batch_item_id,
                bi.batch_id,
                bi.inbox_item_id,
                bi.order_index,
                bi.role,
                bi.notes AS batch_item_notes,
                i.*
            FROM document_inbox_batch_items bi
            JOIN document_inbox_items i ON i.id = bi.inbox_item_id
            WHERE bi.batch_id = ?
            ORDER BY bi.order_index ASC, bi.id ASC
            """,
            (int(batch_id),),
        ).fetchall()

        result = dict(batch)
        result["items"] = [dict(row) for row in items]
        result["item_count"] = len(result["items"])
        return result


def add_items_to_document_inbox_batch(batch_id: int, inbox_item_ids):
    """
    Añade documentos a un grupo existente.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    now = datetime.now().isoformat(timespec="seconds")
    clean_ids = []

    for raw_id in inbox_item_ids or []:
        try:
            item_id = int(raw_id)
        except Exception:
            continue
        if item_id not in clean_ids:
            clean_ids.append(item_id)

    if not clean_ids:
        return get_document_inbox_batch(batch_id)

    with _connect() as conn:
        current_max = conn.execute(
            """
            SELECT COALESCE(MAX(order_index), 0)
            FROM document_inbox_batch_items
            WHERE batch_id = ?
            """,
            (int(batch_id),),
        ).fetchone()[0] or 0

        for offset, item_id in enumerate(clean_ids, start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO document_inbox_batch_items (
                    batch_id, inbox_item_id, order_index, role, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(batch_id), item_id, int(current_max) + offset, "", "", now),
            )

        conn.execute(
            """
            UPDATE document_inbox_batches
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, int(batch_id)),
        )

        conn.commit()

    return get_document_inbox_batch(batch_id)


def update_document_inbox_batch_status(batch_id: int, status: str):
    """
    Cambia estado del grupo documental.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    clean_status = str(status or "").strip() or "draft"
    now = datetime.now().isoformat(timespec="seconds")

    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_inbox_batches
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (clean_status, now, int(batch_id)),
        )
        conn.commit()

    return get_document_inbox_batch(batch_id)


# === QUESADA DOCUMENT INBOX BATCHES END ===


def _inbox_items_filter_sql(status: Optional[str] = None):
    """
    Construye WHERE compartido para listado y conteo de Bandeja.
    """
    where = []
    params = []

    if status and status != "all":
        where.append("status = ?")
        params.append(status)

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    return where_sql, params


def count_inbox_items(status: Optional[str] = None) -> int:
    """
    Cuenta documentos de Bandeja aplicando los mismos filtros que el listado.
    """
    ensure_document_inbox_schema()

    where_sql, params = _inbox_items_filter_sql(status)

    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM document_inbox_items
            {where_sql}
            """,
            params,
        ).fetchone()

        if row is None:
            return 0

        try:
            return int(row["total"])
        except Exception:
            return int(row[0])



def count_inbox_items_by_status() -> Dict[str, int]:
    """
    Devuelve contadores agregados de Bandeja Documental por estado.

    Evita cargar documentos en frontend solo para pintar chips.
    """
    ensure_document_inbox_schema()

    conn = _connect()
    conn.row_factory = _dict_row_factory
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(status, 'pending') AS status, COUNT(*) AS total
            FROM document_inbox_items
            GROUP BY COALESCE(status, 'pending')
            """
        ).fetchall()

        counts: Dict[str, int] = {}
        total = 0

        for row in rows:
            status = str(row["status"] or "pending")
            value = int(row["total"] or 0)
            counts[status] = value
            total += value

        counts["all"] = total
        return counts
    finally:
        conn.close()


def _inbox_duplicate_key(item: Dict[str, Any]):
    metadata = _metadata_dict(item.get("metadata_json") or "")

    origin_path = _norm_document_path(
        metadata.get("imported_from")
        or metadata.get("box_original_path")
        or metadata.get("source_path")
        or ""
    )
    digest = str(
        item.get("sha256")
        or metadata.get("sha256")
        or metadata.get("file_sha256")
        or ""
    ).strip().lower()
    filename = str(item.get("original_filename") or "").strip().lower()
    size = str(item.get("size_bytes") or "").strip()

    if origin_path:
        return ("origin_path", origin_path)

    if digest:
        return ("sha256", digest)

    if filename and size:
        return ("filename_size", filename, size)

    return None


def _annotate_inbox_duplicates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Marca duplicados históricos sin borrar ni modificar datos.

    Conserva como principal el item con ID menor.
    """
    seen = {}

    for item in sorted(items, key=lambda x: int(x.get("id") or 0)):
        item["is_duplicate"] = False
        item["duplicate_of_id"] = None
        item["duplicate_reason"] = ""

        key = _inbox_duplicate_key(item)
        if not key:
            continue

        if key in seen:
            item["is_duplicate"] = True
            item["duplicate_of_id"] = seen[key]
            item["duplicate_reason"] = str(key[0])
        else:
            seen[key] = int(item.get("id") or 0)

    return items


def list_inbox_items(
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Lista documentos de Bandeja con paginación real.

    limit:
        Número máximo de registros a devolver.

    offset:
        Desplazamiento SQL. Página 1 con tamaño 10 = offset 0.
        Página 2 con tamaño 10 = offset 10.
    """
    ensure_document_inbox_schema()

    safe_limit = max(1, min(int(limit or 200), 500))
    safe_offset = max(0, int(offset or 0))

    where_sql, params = _inbox_items_filter_sql(status)

    with _connect() as conn:
        try:
            conn.row_factory = _dict_row_factory
        except NameError:
            conn.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

        rows = conn.execute(
            f"""
            SELECT *
            FROM document_inbox_items
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            OFFSET ?
            """,
            [*params, safe_limit, safe_offset],
        ).fetchall()

        items = [dict(row) for row in rows]
        return _annotate_inbox_duplicates(items)


def get_inbox_item(item_id: int) -> Dict[str, Any]:
    ensure_document_inbox_schema()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM document_inbox_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()

    item = _dict(row)
    if not item:
        raise ValueError("No existe el documento de bandeja indicado.")
    return item


def get_inbox_events(item_id: int) -> List[Dict[str, Any]]:
    ensure_document_inbox_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM document_inbox_events
            WHERE item_id = ?
            ORDER BY id DESC
            """,
            (int(item_id),),
        ).fetchall()

    return [dict(row) for row in rows]


def update_inbox_item_status(item_id: int, status: str, notes: str = "") -> Dict[str, Any]:
    ensure_document_inbox_schema()

    status = (status or "").strip()
    if status not in VALID_STATUSES:
        raise ValueError(f"Estado de bandeja no permitido: {status}")

    with get_connection() as conn:
        item = conn.execute(
            "SELECT * FROM document_inbox_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        if not item:
            raise ValueError("No existe el documento de bandeja indicado.")

        conn.execute(
            """
            UPDATE document_inbox_items
            SET status = ?,
                notes = CASE WHEN ? != '' THEN ? ELSE notes END,
                updated_at = ?
            WHERE id = ?
            """,
            (status, notes or "", notes or "", _now(), int(item_id)),
        )
        _record_event(conn, int(item_id), "status_changed", f"Estado cambiado a {status}", {"notes": notes or ""})
        conn.commit()

    return get_inbox_item(item_id)


def link_inbox_item(
    item_id: int,
    client_id: Optional[int] = None,
    expedient_id: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_document_inbox_schema()

    with get_connection() as conn:
        item = conn.execute(
            "SELECT * FROM document_inbox_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        if not item:
            raise ValueError("No existe el documento de bandeja indicado.")

        if client_id:
            client = conn.execute("SELECT id FROM clientes WHERE id = ?", (int(client_id),)).fetchone()
            if not client:
                raise ValueError("No existe el cliente indicado.")

        if expedient_id:
            expedient_columns = _table_columns(conn, "expedientes")
            if "cliente_id" in expedient_columns:
                expedient = conn.execute(
                    "SELECT id, cliente_id FROM expedientes WHERE id = ?",
                    (int(expedient_id),),
                ).fetchone()
            else:
                expedient = conn.execute(
                    "SELECT id FROM expedientes WHERE id = ?",
                    (int(expedient_id),),
                ).fetchone()

            if not expedient:
                raise ValueError("No existe el expediente indicado.")

            if not client_id and "cliente_id" in expedient.keys() and expedient["cliente_id"]:
                client_id = int(expedient["cliente_id"])

        conn.execute(
            """
            UPDATE document_inbox_items
            SET client_id = COALESCE(?, client_id),
                expedient_id = COALESCE(?, expedient_id),
                status = CASE WHEN ? IS NOT NULL OR ? IS NOT NULL THEN 'linked' ELSE status END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
                _now(),
                int(item_id),
            ),
        )
        _record_event(
            conn,
            int(item_id),
            "linked",
            "Documento vinculado",
            {"client_id": client_id, "expedient_id": expedient_id},
        )
        conn.commit()

    return get_inbox_item(item_id)


def _get_expedient_for_box(conn, expedient_id: int) -> Dict[str, Any]:
    columns = _table_columns(conn, "expedientes")
    wanted = ["id"]

    for col in ["cliente_id", "numero_expediente", "tipo_expediente", "box_folder_path"]:
        if col in columns:
            wanted.append(col)

    row = conn.execute(
        f"SELECT {', '.join(wanted)} FROM expedientes WHERE id = ?",
        (int(expedient_id),),
    ).fetchone()

    expedient = _dict(row)
    if not expedient:
        raise ValueError("No existe el expediente indicado.")

    box_path = str(expedient.get("box_folder_path") or "").strip()
    if not box_path:
        raise ValueError("El expediente no tiene carpeta Box vinculada.")

    return expedient


def copy_inbox_item_to_expedient_box(
    item_id: int,
    expedient_id: Optional[int] = None,
    subfolder: str = "",
) -> Dict[str, Any]:
    """
    Copia segura desde la bandeja interna del ERP hacia la carpeta Box vinculada al expediente.

    No modifica, mueve, renombra ni borra documentos ya existentes en Box.
    Si existe un archivo con el mismo nombre, genera un nombre alternativo.
    """
    ensure_document_inbox_schema()

    with get_connection() as conn:
        item = conn.execute(
            "SELECT * FROM document_inbox_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        if not item:
            raise ValueError("No existe el documento de bandeja indicado.")

        item = dict(item)
        expedient_id = int(expedient_id or item.get("expedient_id") or 0)
        if not expedient_id:
            raise ValueError("Vincula o indica un expediente antes de copiar a Box.")

        expedient = _get_expedient_for_box(conn, expedient_id)

        src = Path(str(item.get("stored_path") or ""))
        if not src.exists() or not src.is_file():
            raise FileNotFoundError("El archivo interno de bandeja no existe.")

        base_box_folder = Path(str(expedient.get("box_folder_path") or ""))
        if not base_box_folder.exists() or not base_box_folder.is_dir():
            raise FileNotFoundError("La carpeta Box vinculada al expediente no existe en este equipo.")

        safe_subfolder = str(subfolder or "").strip().replace("\\", "/").strip("/")
        if safe_subfolder:
            dest_folder = base_box_folder / safe_subfolder
            dest_folder.mkdir(parents=True, exist_ok=True)
        else:
            dest_folder = base_box_folder

        dest = _unique_destination(dest_folder, item.get("original_filename") or src.name)
        shutil.copy2(src, dest)

        conn.execute(
            """
            UPDATE document_inbox_items
            SET expedient_id = ?,
                client_id = COALESCE(client_id, ?),
                copied_to_box_path = ?,
                copied_to_box_at = ?,
                linked_document_path = ?,
                status = 'copied_to_box',
                updated_at = ?
            WHERE id = ?
            """,
            (
                expedient_id,
                expedient.get("cliente_id"),
                str(dest),
                _now(),
                str(dest),
                _now(),
                int(item_id),
            ),
        )
        _record_event(
            conn,
            int(item_id),
            "copied_to_box",
            "Documento copiado a carpeta Box del expediente",
            {
                "expedient_id": expedient_id,
                "source_path": str(src),
                "destination_path": str(dest),
                "subfolder": safe_subfolder,
            },
        )
        conn.commit()

    return get_inbox_item(item_id)


def open_inbox_item(item_id: int) -> Dict[str, Any]:
    item = get_inbox_item(item_id)
    path = Path(str(item.get("stored_path") or ""))
    if not path.exists():
        raise FileNotFoundError("El archivo de bandeja no existe.")

    os.startfile(str(path))
    return {"ok": True, "path": str(path)}


def list_clients_for_inbox(limit: int = 500) -> List[Dict[str, Any]]:
    """
    Clientes mínimos para selector/autocomplete de bandeja documental.
    """
    ensure_document_inbox_schema()

    with get_connection() as conn:
        columns = _table_columns(conn, "clientes")
        wanted = ["id"]

        for col in [
            "nombre",
            "primer_apellido",
            "segundo_apellido",
            "nie",
            "pasaporte",
            "dni",
            "telefono",
            "email",
            "activo",
        ]:
            if col in columns:
                wanted.append(col)

        activo_filter = "WHERE COALESCE(activo, 1) = 1" if "activo" in columns else ""

        rows = conn.execute(
            f"""
            SELECT {", ".join(wanted)}
            FROM clientes
            {activo_filter}
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit or 500),),
        ).fetchall()

    return [dict(row) for row in rows]


def _client_display_name(client: Dict[str, Any]) -> str:
    nombre = " ".join(
        str(client.get(part) or "").strip()
        for part in ["nombre", "primer_apellido", "segundo_apellido"]
    ).strip()
    documento = client.get("nie") or client.get("pasaporte") or client.get("dni") or ""
    if documento:
        return f"#{client.get('id')} · {nombre or 'SIN NOMBRE'} · {documento}"
    return f"#{client.get('id')} · {nombre or 'SIN NOMBRE'}"


def client_autocomplete_options(limit: int = 500) -> List[Dict[str, Any]]:
    clients = list_clients_for_inbox(limit=limit)
    return [
        {
            "id": int(client.get("id")),
            "label": _client_display_name(client),
            "client": client,
        }
        for client in clients
    ]


def list_expedients_for_client(client_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Expedientes de un cliente para selector de bandeja documental.

    Es defensivo con nombres de columnas porque la tabla expedientes ha ido
    evolucionando durante el proyecto.
    """
    ensure_document_inbox_schema()

    if not client_id:
        return []

    with get_connection() as conn:
        columns = _table_columns(conn, "expedientes")
        wanted = ["id"]

        for col in [
            "cliente_id",
            "numero_expediente",
            "numero_expediente_mercurio",
            "tipo_expediente",
            "tipo",
            "procedimiento",
            "subtipo_expediente",
            "tipo_expediente_id",
            "estado_documental",
            "estado_administrativo",
            "box_folder_path",
            "created_at",
            "fecha_apertura",
        ]:
            if col in columns:
                wanted.append(col)

        if "cliente_id" not in columns:
            return []

        rows = conn.execute(
            f"""
            SELECT {", ".join(wanted)}
            FROM expedientes
            WHERE cliente_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(client_id), int(limit or 200)),
        ).fetchall()

    return [dict(row) for row in rows]


def _expedient_display_name(expedient: Dict[str, Any]) -> str:
    number = (
        expedient.get("numero_expediente")
        or expedient.get("numero_expediente_mercurio")
        or f"EXP-{expedient.get('id')}"
    )
    kind = (
        expedient.get("tipo_expediente")
        or expedient.get("tipo")
        or expedient.get("procedimiento")
        or expedient.get("subtipo_expediente")
        or expedient.get("tipo_expediente_id")
        or "Sin tipo"
    )
    status = (
        expedient.get("estado_administrativo")
        or expedient.get("estado_documental")
        or ""
    )
    box = "BOX OK" if str(expedient.get("box_folder_path") or "").strip() else "SIN BOX"

    suffix = f" · {status}" if status else ""
    return f"#{expedient.get('id')} · {number} · {kind}{suffix} · {box}"


def expedient_autocomplete_options_for_client(client_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    expedients = list_expedients_for_client(client_id=client_id, limit=limit)
    return [
        {
            "id": int(expedient.get("id")),
            "label": _expedient_display_name(expedient),
            "expedient": expedient,
        }
        for expedient in expedients
    ]


# === QUESADA DOCUMENT INBOX BOX IMPORT START ===

def _safe_relative_to(child_path: Path, parent_path: Path) -> bool:
    try:
        child_path.resolve().relative_to(parent_path.resolve())
        return True
    except Exception:
        return False


def _get_expedient_box_context(expedient_id: int) -> Dict[str, Any]:
    """
    Devuelve contexto mínimo del expediente para trabajar con su carpeta Box vinculada.
    No modifica Box.
    """
    with _connect() as conn:
        expedient = _get_expedient_for_box(conn, int(expedient_id))

    box_folder = Path(str(expedient.get("box_folder_path") or "")).expanduser()
    if not box_folder.exists() or not box_folder.is_dir():
        raise FileNotFoundError(f"La carpeta Box del expediente no existe o no es accesible: {box_folder}")

    return {
        "expedient": expedient,
        "box_folder": box_folder,
        "client_id": expedient.get("cliente_id") or expedient.get("client_id"),
        "expedient_id": int(expedient_id),
    }


def list_expedient_box_files_for_inbox(expedient_id: int, max_files: int = 500) -> List[Dict[str, Any]]:
    """
    Lista archivos físicos de la carpeta Box vinculada al expediente.
    Se usa para elegir qué documentos copiar a Bandeja Documental.
    No copia ni modifica nada.
    """
    ctx = _get_expedient_box_context(int(expedient_id))
    base_folder: Path = ctx["box_folder"]

    allowed_extensions = {
        ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
        ".doc", ".docx", ".xls", ".xlsx", ".txt",
    }

    result = []
    for file_path in base_folder.rglob("*"):
        if len(result) >= int(max_files or 500):
            break

        try:
            if not file_path.is_file():
                continue
            if file_path.name.startswith("~$"):
                continue
            if file_path.suffix.lower() not in allowed_extensions:
                continue

            stat = file_path.stat()
            relative_path = str(file_path.relative_to(base_folder))

            already_imported = False
            dedupe_reason = ""
            inbox_item_id = None

            try:
                file_sha256 = _calculate_file_sha256(file_path)
                existing = _find_existing_box_inbox_item(
                    expedient_id=int(ctx["expedient_id"]),
                    box_original_path=str(file_path),
                    box_relative_path=relative_path,
                    sha256=file_sha256,
                )
                if existing:
                    already_imported = True
                    dedupe_reason = str(existing.get("dedupe_reason") or "")
                    inbox_item_id = existing.get("id")
            except Exception:
                file_sha256 = ""

            result.append({
                "path": str(file_path),
                "relative_path": relative_path,
                "filename": file_path.name,
                "extension": file_path.suffix.lower(),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "sha256": file_sha256,
                "file_sha256": file_sha256,
                "already_imported": already_imported,
                "dedupe_reason": dedupe_reason,
                "inbox_item_id": inbox_item_id,
                "client_id": ctx["client_id"],
                "expedient_id": ctx["expedient_id"],
                "box_folder_path": str(base_folder),
            })
        except Exception:
            continue

    result.sort(key=lambda item: str(item.get("relative_path") or "").lower())
    return result



def _calculate_file_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    Calcula SHA256 para deduplicación documental.
    Lee por bloques para no cargar documentos grandes en memoria.
    """
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()


def _find_existing_box_inbox_item(
    expedient_id: int,
    box_original_path: str = "",
    box_relative_path: str = "",
    sha256: str = "",
) -> Dict[str, Any]:
    """
    Busca si un archivo de Box ya fue importado a Bandeja Documental.

    Estrategia:
    - Primero por expediente + metadata_json con ruta original/relativa.
    - Después por expediente + SHA256.
    """
    ensure_document_inbox_schema()

    original = str(box_original_path or "").replace("\\", "/").strip()
    relative = str(box_relative_path or "").replace("\\", "/").strip()
    digest = str(sha256 or "").strip().lower()

    with _connect() as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT *
            FROM document_inbox_items
            WHERE expedient_id = ?
              AND source_type = 'box'
            ORDER BY id DESC
            """,
            (int(expedient_id),),
        ).fetchall()

        for row in rows:
            item = dict(row)
            raw_metadata = item.get("metadata_json") or ""
            try:
                metadata = json.loads(raw_metadata) if raw_metadata else {}
            except Exception:
                metadata = {}

            item_original = str(metadata.get("box_original_path") or "").replace("\\", "/").strip()
            item_relative = str(metadata.get("box_relative_path") or "").replace("\\", "/").strip()
            item_imported_from = str(metadata.get("imported_from") or "").replace("\\", "/").strip()
            item_sha = str(metadata.get("sha256") or metadata.get("file_sha256") or "").strip().lower()

            if original and item_original and original.lower() == item_original.lower():
                item["already_imported"] = True
                item["dedupe_reason"] = "box_original_path"
                return item

            if original and item_imported_from and original.lower() == item_imported_from.lower():
                item["already_imported"] = True
                item["dedupe_reason"] = "legacy_imported_from"
                return item

            if relative and item_relative and relative.lower() == item_relative.lower():
                item["already_imported"] = True
                item["dedupe_reason"] = "box_relative_path"
                return item

            if digest and item_sha and digest == item_sha:
                item["already_imported"] = True
                item["dedupe_reason"] = "sha256"
                return item

    return {}


def import_box_file_to_inbox(
    box_file_path: str,
    expedient_id: int,
    source_label: str = "Box expediente",
) -> Dict[str, Any]:
    """
    Copia un archivo existente en la carpeta Box vinculada del expediente a Bandeja.
    No mueve ni modifica el archivo original de Box.
    """
    ctx = _get_expedient_box_context(int(expedient_id))
    base_folder: Path = ctx["box_folder"]

    source_path = Path(str(box_file_path or "")).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"No existe el archivo Box indicado: {source_path}")

    if not _safe_relative_to(source_path, base_folder):
        raise ValueError("Por seguridad, solo se pueden copiar a Bandeja archivos dentro de la carpeta Box vinculada al expediente.")

    stat = source_path.stat()
    box_relative_path = str(source_path.relative_to(base_folder))
    file_sha256 = _calculate_file_sha256(source_path)

    metadata = {
        "box_original_path": str(source_path),
        "box_relative_path": box_relative_path,
        "box_folder_path": str(base_folder),
        "origin": "expedient_box",
        "sha256": file_sha256,
        "file_sha256": file_sha256,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }

    existing = _find_existing_box_inbox_item(
        expedient_id=int(expedient_id),
        box_original_path=str(source_path),
        box_relative_path=box_relative_path,
        sha256=file_sha256,
    )
    if existing:
        return existing

    # import_file_to_inbox ha ido evolucionando. Pasamos solo los argumentos que acepte.
    import inspect
    sig = inspect.signature(import_file_to_inbox)
    candidate_kwargs = {
        "source_type": "box",
        "source_label": source_label or "Box expediente",
        "client_id": ctx["client_id"],
        "expedient_id": ctx["expedient_id"],
        "notes": f"Copiado desde Box: {metadata['box_relative_path']}",
        "metadata": metadata,
        "metadata_json": metadata,
    }
    kwargs = {key: value for key, value in candidate_kwargs.items() if key in sig.parameters}

    item = import_file_to_inbox(str(source_path), **kwargs)

    # Si la firma actual no soportaba metadata, al menos dejamos un evento adicional si existe _record_event compatible.
    try:
        item_id = int(item.get("id"))
        with _connect() as conn:
            _record_event(
                conn,
                item_id,
                "box_copied_to_inbox",
                f"Copiado desde Box a bandeja: {metadata['box_relative_path']}",
                metadata,
            )
            conn.commit()
    except Exception:
        pass

    return item


def bulk_import_box_files_to_inbox(
    expedient_id: int,
    box_file_paths: List[str],
    source_label: str = "Box expediente",
) -> Dict[str, Any]:
    """
    Copia varios archivos de Box a Bandeja.
    Devuelve resultado agregado para UI/dialogs.
    """
    imported = []
    errors = []

    for file_path in box_file_paths or []:
        try:
            imported.append(import_box_file_to_inbox(
                file_path,
                expedient_id=int(expedient_id),
                source_label=source_label,
            ))
        except Exception as exc:
            errors.append({
                "path": str(file_path),
                "error": str(exc),
            })

    return {
        "imported_count": len(imported),
        "error_count": len(errors),
        "imported": imported,
        "errors": errors,
    }

# === QUESADA DOCUMENT INBOX BOX IMPORT END ===


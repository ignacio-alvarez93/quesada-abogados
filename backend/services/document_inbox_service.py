from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import stat as _stat
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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


def _safe_filename(filename: str, fallback: str = "documento") -> str:
    """
    Nombre seguro para Windows/Box. No crea rutas, solo nombre de archivo.
    Acepta fallback para mantener compatibilidad con copias renombradas.
    """
    value = str(filename or "").strip()
    if not value:
        value = str(fallback or "documento").strip() or "documento"

    for ch in '<>:"/\\|?*':
        value = value.replace(ch, "_")

    value = value.strip(" ._")
    fallback_value = str(fallback or "documento").strip(" ._") or "documento"
    return value or fallback_value


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

    # Exclusive creation prevents a concurrent import from overwriting a copy.
    with src.open("rb") as source_file, dest.open("xb") as target_file:
        shutil.copyfileobj(source_file, target_file)

    size_bytes = dest.stat().st_size
    digest = _sha256(dest)
    if size_bytes != source_stat.st_size or digest != source_digest:
        raise ValueError("La copia no coincide con el original; no se ha registrado.")
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


DOCUMENT_INBOX_BATCH_STATUSES = {
    "draft",
    "reviewed",
    "copied_to_box",
    "partial",
    "error",
    "archived",
}

DOCUMENT_INBOX_BATCH_STATUS_LABELS = {
    "draft": "Borrador",
    "reviewed": "Revisado",
    "copied_to_box": "Copiado a Box",
    "partial": "Parcial",
    "error": "Error",
    "archived": "Archivado",
}


def _normalize_document_inbox_batch_status(status):
    """
    Normaliza estados de grupos documentales.

    Evita estados libres inconsistentes en la cabecera del grupo.
    """
    clean_status = str(status or "draft").strip().lower() or "draft"

    aliases = {
        "borrador": "draft",
        "pendiente": "draft",
        "revisado": "reviewed",
        "review": "reviewed",
        "copiado": "copied_to_box",
        "copied": "copied_to_box",
        "copy": "copied_to_box",
        "box": "copied_to_box",
        "parcial": "partial",
        "partial_copy": "partial",
        "error_copy": "error",
        "archivado": "archived",
        "archive": "archived",
    }

    clean_status = aliases.get(clean_status, clean_status)

    if clean_status not in DOCUMENT_INBOX_BATCH_STATUSES:
        allowed = ", ".join(sorted(DOCUMENT_INBOX_BATCH_STATUSES))
        raise ValueError(f"Estado de grupo documental no válido: {clean_status}. Permitidos: {allowed}")

    return clean_status



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

    raw_item_ids = []
    for raw_id in inbox_item_ids or []:
        try:
            item_id = int(raw_id)
        except Exception:
            continue
        if item_id not in raw_item_ids:
            raw_item_ids.append(item_id)

    item_ids = []
    skipped_items = []

    if raw_item_ids:
        placeholders = ", ".join("?" for _ in raw_item_ids)
        with _connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, status, client_id, expedient_id, original_filename
                FROM document_inbox_items
                WHERE id IN ({placeholders})
                """,
                tuple(raw_item_ids),
            ).fetchall()

        by_id = {int(row["id"]): dict(row) for row in rows}

        for item_id in raw_item_ids:
            item = by_id.get(int(item_id))
            if not item:
                skipped_items.append({
                    "id": item_id,
                    "reason": "not_found",
                })
                continue

            status_value = str(item.get("status") or "").strip().lower()
            if status_value in {"duplicate", "discarded"}:
                skipped_items.append({
                    "id": item_id,
                    "reason": f"status_{status_value}",
                    "filename": item.get("original_filename"),
                })
                continue

            item_ids.append(item_id)

    if raw_item_ids and not item_ids:
        raise ValueError("No hay documentos válidos para crear el grupo. Se omiten duplicados y descartados.")

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
                _normalize_document_inbox_batch_status(status),
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
                str(target_box_folder or "").strip(),
                str(notes or "").strip(),
                json.dumps(
                    {
                        "source": "document_inbox",
                        "skipped_on_create": skipped_items,
                        "original_selection_count": len(raw_item_ids),
                        "accepted_selection_count": len(item_ids),
                    },
                    ensure_ascii=False,
                ),
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


def list_document_inbox_batches(status=None, expedient_id=None, client_id=None, search=None, limit=200, offset=0):
    """
    Lista grupos documentales con contador de documentos.

    Filtros:
    - status
    - expedient_id
    - client_id
    - search: busca en nombre, notas y carpeta destino.
    """
    ensure_document_inbox_batch_schema()

    where = []
    params = []

    if status and status != "all":
        where.append("b.status = ?")
        params.append(str(status).strip())

    if expedient_id:
        where.append("b.expedient_id = ?")
        params.append(int(expedient_id))

    if client_id:
        where.append("b.client_id = ?")
        params.append(int(client_id))

    clean_search = str(search or "").strip()
    if clean_search:
        like_value = f"%{clean_search}%"
        where.append(
            "("
            "b.name LIKE ? OR "
            "b.notes LIKE ? OR "
            "b.target_box_folder LIKE ? OR "
            "CAST(b.id AS TEXT) LIKE ?"
            ")"
        )
        params.extend([like_value, like_value, like_value, like_value])

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
        LIMIT ? OFFSET ?
    """
    params.append(int(limit or 200))
    params.append(max(0, int(offset or 0)))

    with _connect() as conn:
        conn.row_factory = _dict_row_factory
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def count_document_inbox_batches(status=None, expedient_id=None, client_id=None, search=None):
    """
    Cuenta grupos documentales aplicando los mismos filtros de listado.

    No agrupa por estado; sirve para paginación.
    """
    ensure_document_inbox_batch_schema()

    where = []
    params = []

    if status and status != "all":
        where.append("status = ?")
        params.append(str(status).strip())

    if expedient_id:
        where.append("expedient_id = ?")
        params.append(int(expedient_id))

    if client_id:
        where.append("client_id = ?")
        params.append(int(client_id))

    clean_search = str(search or "").strip()
    if clean_search:
        like_value = f"%{clean_search}%"
        where.append(
            "("
            "name LIKE ? OR "
            "notes LIKE ? OR "
            "target_box_folder LIKE ? OR "
            "CAST(id AS TEXT) LIKE ?"
            ")"
        )
        params.extend([like_value, like_value, like_value, like_value])

    sql = "SELECT COUNT(*) AS total FROM document_inbox_batches"

    if where:
        sql += " WHERE " + " AND ".join(where)

    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0)


def count_document_inbox_batches_by_status():
    """
    Devuelve contadores de grupos documentales por estado oficial.
    """
    ensure_document_inbox_batch_schema()

    counts = {status: 0 for status in DOCUMENT_INBOX_BATCH_STATUSES}
    counts["all"] = 0

    with _connect() as conn:
        conn.row_factory = _dict_row_factory
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM document_inbox_batches
            GROUP BY status
            """
        ).fetchall()

    for row in rows:
        raw_status = row["status"] or "draft"
        try:
            status = _normalize_document_inbox_batch_status(raw_status)
        except Exception:
            status = "error"

        total = int(row["total"] or 0)
        counts[status] = counts.get(status, 0) + total
        counts["all"] += total

    return counts


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

    Reglas:
    - No borra ni mueve documentos.
    - No añade duplicate/discarded.
    - No duplica documentos ya presentes en el grupo.
    - Registra evento batch_add en cada documento realmente añadido.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    now = datetime.now().isoformat(timespec="seconds")
    raw_ids = []

    for raw_id in inbox_item_ids or []:
        try:
            item_id = int(raw_id)
        except Exception:
            continue
        if item_id not in raw_ids:
            raw_ids.append(item_id)

    if not raw_ids:
        result = get_document_inbox_batch(batch_id)
        result["add_result"] = {
            "added_count": 0,
            "skipped_count": 0,
            "added": [],
            "skipped": [],
        }
        return result

    added = []
    skipped = []

    with _connect() as conn:
        conn.row_factory = _dict_row_factory

        batch = conn.execute(
            "SELECT * FROM document_inbox_batches WHERE id = ?",
            (int(batch_id),),
        ).fetchone()
        if not batch:
            raise ValueError(f"No existe el grupo documental #{batch_id}")

        existing_rows = conn.execute(
            """
            SELECT inbox_item_id
            FROM document_inbox_batch_items
            WHERE batch_id = ?
            """,
            (int(batch_id),),
        ).fetchall()
        existing_ids = {int(row["inbox_item_id"]) for row in existing_rows}

        placeholders = ", ".join("?" for _ in raw_ids)
        item_rows = conn.execute(
            f"""
            SELECT id, status, original_filename
            FROM document_inbox_items
            WHERE id IN ({placeholders})
            """,
            tuple(raw_ids),
        ).fetchall()
        by_id = {int(row["id"]): dict(row) for row in item_rows}

        current_max_row = conn.execute(
            """
            SELECT COALESCE(MAX(order_index), 0) AS current_max
            FROM document_inbox_batch_items
            WHERE batch_id = ?
            """,
            (int(batch_id),),
        ).fetchone()
        current_max = int(current_max_row["current_max"] or 0) if current_max_row else 0

        next_index = int(current_max)

        for item_id in raw_ids:
            item = by_id.get(int(item_id))
            if not item:
                skipped.append({
                    "id": item_id,
                    "reason": "not_found",
                })
                continue

            if item_id in existing_ids:
                skipped.append({
                    "id": item_id,
                    "reason": "already_in_batch",
                    "filename": item.get("original_filename"),
                })
                continue

            status_value = str(item.get("status") or "").strip().lower()
            if status_value in {"duplicate", "discarded"}:
                skipped.append({
                    "id": item_id,
                    "reason": f"status_{status_value}",
                    "filename": item.get("original_filename"),
                })
                continue

            next_index += 1
            conn.execute(
                """
                INSERT OR IGNORE INTO document_inbox_batch_items (
                    batch_id, inbox_item_id, order_index, role, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(batch_id), item_id, next_index, "", "", now),
            )

            added.append({
                "id": item_id,
                "filename": item.get("original_filename"),
            })

            try:
                _record_event(
                    conn,
                    item_id,
                    "batch_add",
                    f"Documento añadido al grupo documental #{int(batch_id)}: {batch['name']}",
                    {"batch_id": int(batch_id), "batch_name": batch["name"]},
                )
            except TypeError:
                try:
                    _record_event(
                        conn,
                        item_id,
                        "batch_add",
                        f"Documento añadido al grupo documental #{int(batch_id)}: {batch['name']}",
                    )
                except Exception:
                    pass
            except Exception:
                pass

        conn.execute(
            """
            UPDATE document_inbox_batches
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, int(batch_id)),
        )

        conn.commit()

    result = get_document_inbox_batch(batch_id)
    result["add_result"] = {
        "added_count": len(added),
        "skipped_count": len(skipped),
        "added": added,
        "skipped": skipped,
    }
    return result


def remove_item_from_document_inbox_batch(batch_id: int, inbox_item_id: int):
    """
    Quita un documento de un grupo documental.

    No borra el documento de Bandeja.
    No borra el archivo.
    Solo elimina la relación grupo-documento.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    now = datetime.now().isoformat(timespec="seconds")

    with _connect() as conn:
        conn.row_factory = _dict_row_factory

        batch = conn.execute(
            "SELECT * FROM document_inbox_batches WHERE id = ?",
            (int(batch_id),),
        ).fetchone()
        if not batch:
            raise ValueError(f"No existe el grupo documental #{batch_id}")

        relation = conn.execute(
            """
            SELECT id
            FROM document_inbox_batch_items
            WHERE batch_id = ? AND inbox_item_id = ?
            """,
            (int(batch_id), int(inbox_item_id)),
        ).fetchone()

        if not relation:
            raise ValueError("El documento no pertenece a este grupo.")

        conn.execute(
            """
            DELETE FROM document_inbox_batch_items
            WHERE batch_id = ? AND inbox_item_id = ?
            """,
            (int(batch_id), int(inbox_item_id)),
        )

        conn.execute(
            """
            UPDATE document_inbox_batches
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, int(batch_id)),
        )

        try:
            _record_event(
                conn,
                int(inbox_item_id),
                "batch_remove",
                f"Documento quitado del grupo documental #{int(batch_id)}: {batch['name']}",
                {"batch_id": int(batch_id), "batch_name": batch["name"]},
            )
        except TypeError:
            try:
                _record_event(
                    conn,
                    int(inbox_item_id),
                    "batch_remove",
                    f"Documento quitado del grupo documental #{int(batch_id)}: {batch['name']}",
                )
            except Exception:
                pass
        except Exception:
            pass

        conn.commit()

    return get_document_inbox_batch(batch_id)



def update_document_inbox_batch(
    batch_id: int,
    name: str = "",
    notes: str = "",
    client_id=None,
    expedient_id=None,
    target_box_folder: str = "",
    status: str = "draft",
):
    """
    Actualiza metadatos de un grupo documental.

    No borra documentos.
    No mueve archivos.
    No copia a Box.
    Solo actualiza la cabecera del grupo y registra trazabilidad.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("El nombre del grupo documental es obligatorio.")

    clean_status = _normalize_document_inbox_batch_status(status)
    now = datetime.now().isoformat(timespec="seconds")

    with _connect() as conn:
        conn.row_factory = _dict_row_factory

        batch = conn.execute(
            "SELECT * FROM document_inbox_batches WHERE id = ?",
            (int(batch_id),),
        ).fetchone()

        if not batch:
            raise ValueError(f"No existe el grupo documental #{batch_id}")

        conn.execute(
            """
            UPDATE document_inbox_batches
            SET updated_at = ?,
                name = ?,
                notes = ?,
                client_id = ?,
                expedient_id = ?,
                target_box_folder = ?,
                status = ?
            WHERE id = ?
            """,
            (
                now,
                clean_name,
                str(notes or "").strip(),
                int(client_id) if client_id else None,
                int(expedient_id) if expedient_id else None,
                str(target_box_folder or "").strip(),
                clean_status,
                int(batch_id),
            ),
        )

        item_rows = conn.execute(
            """
            SELECT inbox_item_id
            FROM document_inbox_batch_items
            WHERE batch_id = ?
            """,
            (int(batch_id),),
        ).fetchall()

        for row in item_rows:
            try:
                item_id = int(row["inbox_item_id"])
            except Exception:
                continue

            try:
                _record_event(
                    conn,
                    item_id,
                    "batch_update",
                    f"Grupo documental #{int(batch_id)} actualizado: {clean_name}",
                    {
                        "batch_id": int(batch_id),
                        "batch_name": clean_name,
                        "client_id": int(client_id) if client_id else None,
                        "expedient_id": int(expedient_id) if expedient_id else None,
                        "target_box_folder": str(target_box_folder or "").strip(),
                        "status": clean_status,
                    },
                )
            except TypeError:
                try:
                    _record_event(
                        conn,
                        item_id,
                        "batch_update",
                        f"Grupo documental #{int(batch_id)} actualizado: {clean_name}",
                    )
                except Exception:
                    pass
            except Exception:
                pass

        conn.commit()

    return get_document_inbox_batch(batch_id)


def update_document_inbox_batch_status(batch_id: int, status: str):
    """
    Cambia estado del grupo documental.
    """
    from datetime import datetime

    ensure_document_inbox_batch_schema()

    clean_status = _normalize_document_inbox_batch_status(status)
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
    return _query_inbox_items(status, limit, offset)


def _query_inbox_items(status, limit, offset) -> List[Dict[str, Any]]:
    """Consulta de ``list_inbox_items`` sin inicializar esquema ni carpetas (lectores, DV25-P3B3)."""
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



def mark_detected_inbox_duplicates(status_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    Marca como duplicate los items detectados como duplicados históricos.

    No borra archivos.
    No mueve documentos.
    No toca el item principal.
    """
    items = list_inbox_items(status=status_filter, limit=500, offset=0)

    marked = []
    skipped = []
    errors = []

    for item in items:
        item_id = int(item.get("id") or 0)
        if not item_id:
            continue

        if not item.get("is_duplicate"):
            skipped.append(item_id)
            continue

        duplicate_of_id = item.get("duplicate_of_id")
        duplicate_reason = item.get("duplicate_reason") or "detected_duplicate"

        already_duplicate_status = str(item.get("status") or "") == "duplicate"

        try:
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM document_inbox_items WHERE id = ?",
                    (item_id,),
                ).fetchone()

                if not row:
                    errors.append({"id": item_id, "error": "No existe el item"})
                    continue

                current = dict(row)
                metadata = _metadata_dict(current.get("metadata_json") or "")
                metadata["duplicate_of_id"] = duplicate_of_id
                metadata["duplicate_reason"] = duplicate_reason
                metadata["duplicate_marked_at"] = _now()

                conn.execute(
                    """
                    UPDATE document_inbox_items
                    SET status = 'duplicate',
                        updated_at = ?,
                        metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        _now(),
                        json.dumps(metadata, ensure_ascii=False),
                        item_id,
                    ),
                )

                event_exists = conn.execute(
                    """
                    SELECT 1
                    FROM document_inbox_events
                    WHERE item_id = ?
                      AND event_type = 'duplicate_marked'
                    LIMIT 1
                    """,
                    (item_id,),
                ).fetchone()

                if not event_exists:
                    _record_event(
                        conn,
                        item_id,
                        "duplicate_marked",
                        f"Documento marcado como duplicado de #{duplicate_of_id}",
                        {
                            "duplicate_of_id": duplicate_of_id,
                            "duplicate_reason": duplicate_reason,
                            "repaired": already_duplicate_status,
                        },
                    )

                conn.commit()

            if already_duplicate_status:
                skipped.append(item_id)
            else:
                marked.append(item_id)
        except Exception as exc:
            errors.append({"id": item_id, "error": str(exc)})

    return {
        "marked_count": len(marked),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "marked": marked,
        "skipped": skipped,
        "errors": errors,
    }



def _annotate_single_inbox_duplicate(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Anota un item individual con datos de duplicado.

    Prioridad:
    - metadata_json.duplicate_of_id si ya fue marcado como duplicate;
    - detección dinámica frente al conjunto completo si aún no está marcado.
    """
    if not item:
        return item

    metadata = _metadata_dict(item.get("metadata_json") or "")

    duplicate_of_id = metadata.get("duplicate_of_id")
    duplicate_reason = metadata.get("duplicate_reason") or ""

    if duplicate_of_id:
        item["is_duplicate"] = True
        item["duplicate_of_id"] = duplicate_of_id
        item["duplicate_reason"] = duplicate_reason or "metadata"
        return item

    try:
        items = _query_inbox_items("all", 500, 0)
        for candidate in items:
            if int(candidate.get("id") or 0) == int(item.get("id") or 0):
                item["is_duplicate"] = bool(candidate.get("is_duplicate"))
                item["duplicate_of_id"] = candidate.get("duplicate_of_id")
                item["duplicate_reason"] = candidate.get("duplicate_reason") or ""
                return item
    except Exception:
        pass

    item["is_duplicate"] = False
    item["duplicate_of_id"] = None
    item["duplicate_reason"] = ""
    return item


def get_inbox_item(item_id: int) -> Dict[str, Any]:
    # Lector: no aplica esquema ni crea carpetas (DV25-P3B3, H6). Sin tabla no hay ítem.
    with get_connection() as conn:
        try:
            row = conn.execute(
                "SELECT * FROM document_inbox_items WHERE id = ?",
                (int(item_id),),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None

    item = _dict(row)
    if not item:
        raise ValueError("No existe el documento de bandeja indicado.")
    return _annotate_single_inbox_duplicate(item)


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


def update_inbox_item_filename(item_id: int, original_filename: str) -> Dict[str, Any]:
    """
    Renombra el nombre visible/canónico del documento en Bandeja.
    No renombra el archivo físico ni stored_path para no romper trazabilidad/previews.
    """
    item_id = int(item_id or 0)
    if not item_id:
        raise ValueError("Item ID obligatorio.")

    clean_name = _safe_filename(str(original_filename or "").strip())
    if not clean_name:
        raise ValueError("El nombre del documento es obligatorio.")

    with get_connection() as conn:
        current = conn.execute(
            "SELECT id FROM document_inbox_items WHERE id = ?",
            (item_id,),
        ).fetchone()

        if not current:
            raise ValueError(f"No existe documento de bandeja con ID {item_id}.")

        conn.execute(
            """
            UPDATE document_inbox_items
            SET original_filename = ?
            WHERE id = ?
            """,
            (clean_name, item_id),
        )
        conn.commit()

    return get_inbox_item(item_id)


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


def get_expedient(expedient_id: int) -> Dict[str, Any]:
    """
    Wrapper interno para Bandeja Documental.

    La vista document_inbox_view usa el término inglés `expedient`,
    pero el servicio principal del CRM expone `get_expediente`.
    Devolvemos siempre dict para que la UI pueda usar .get().
    """
    expedient_id = int(expedient_id or 0)
    if not expedient_id:
        return {}

    try:
        from backend.services import expedient_service

        expediente = expedient_service.get_expediente(expedient_id) or {}
        if isinstance(expediente, dict):
            return expediente

        try:
            return dict(expediente)
        except Exception:
            return {}
    except Exception:
        pass

    # Fallback directo a SQLite por si el import del servicio falla.
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM expedientes WHERE id = ?",
            (expedient_id,),
        ).fetchone()

    return dict(row) if row else {}


# ---------------------------------------------------------------------- copia Box gobernada (DV25-P3B1)
#
# DOC-003: COPY -> VERIFY -> REGISTER. Solo se crean archivos nuevos en Box (creación
# exclusiva); nunca se borra, mueve, renombra ni sobrescribe nada en Box ni el original.

_BOX_COPY_CHUNK = 1024 * 1024
_BOX_COPY_MAX_CANDIDATES = 500

_box_copy_locks: Dict[int, threading.Lock] = {}
_box_copy_locks_guard = threading.Lock()


class BoxCopyRejected(ValueError):
    """Copia rechazada antes de crear ningún archivo en Box."""


class BoxCopyStaleDestination(BoxCopyRejected):
    """La carpeta destino revisada ya no existe tal cual: no se recrea (DV25-P3B3, H4)."""

    code = "STALE_DESTINATION"


class BoxCopyIncomplete(RuntimeError):
    """
    Hay un archivo en Box que no ha quedado registrado; requiere revisión humana.

    ``stage``: "write" (escritura interrumpida), "verify" (tamaño/SHA-256/destino no
    coinciden) o "register" (copia verificada, fallo de la base de datos).
    ``written_path``: ese archivo; ``created`` indica si lo creó esta llamada. Nunca se borra.
    """

    def __init__(self, message: str, written_path, stage: str, created: bool = True):
        super().__init__(message)
        self.written_path = str(written_path or "")
        self.stage = stage
        self.created = created


def _filing_plan():
    # Importación diferida: el servicio de archivo del visor importa este módulo.
    from backend.services import document_viewer_filing_plan_service

    return document_viewer_filing_plan_service


def _box_copy_lock(item_id: int) -> threading.Lock:
    with _box_copy_locks_guard:
        return _box_copy_locks.setdefault(int(item_id), threading.Lock())


def _reparse_redirects(st) -> bool:
    """Enlace simbólico, unión o reparse point que no sea un marcador de nube (política única P3A/P3B1)."""
    return _filing_plan().reparse_redirects(st)


def _redirects(path: Path) -> bool:
    try:
        return _reparse_redirects(path.lstat())
    except OSError:
        return True


def _box_subfolder(value) -> str:
    filing_plan = _filing_plan()
    try:
        return filing_plan.check_subfolder(str(value or ""))
    except filing_plan.FilingPlanError as exc:
        raise BoxCopyRejected(str(exc)) from None


def _authorized_box_root(raw) -> Path:
    """Carpeta Box configurada del expediente, resuelta; local, real y existente."""
    text = str(raw or "").strip()
    if not text or "\x00" in text:
        raise ValueError("El expediente no tiene carpeta Box vinculada.")
    if text.startswith(("\\\\", "//", "\\/", "/\\")):
        raise BoxCopyRejected("La carpeta Box del expediente es una ruta de red o de dispositivo: no se copia.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise BoxCopyRejected("La carpeta Box del expediente no es una ruta absoluta: no se copia.")
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError("La carpeta Box vinculada al expediente no existe en este equipo.")
    if _redirects(path):
        raise BoxCopyRejected("La carpeta Box del expediente es un enlace o una unión: no se copia.")
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise BoxCopyRejected("No se puede verificar la carpeta Box del expediente: no se copia.") from None


def _verified_inbox_source(item: Dict[str, Any]) -> Path:
    """Archivo interno de Bandeja (bajo INBOX_ROOT, sin enlaces); no se modifica nunca."""
    raw = str(item.get("stored_path") or "")
    src = Path(raw)
    if not raw or not src.exists() or not src.is_file():
        raise FileNotFoundError("El archivo interno de bandeja no existe.")
    if _redirects(src) or not _safe_relative_to(src, Path(INBOX_ROOT)):
        raise BoxCopyRejected("El origen no es un archivo interno de Bandeja: no se copia.")
    return src.resolve(strict=True)


def _box_destination_folder(root: Path, relative: str, create_missing: bool = True):
    """
    (carpeta, carpetas creadas). Cada componente existente debe ser una carpeta real dentro
    de la raíz; los que faltan se crean de uno en uno (nunca se reorganiza lo existente).
    Con ``create_missing=False`` un componente ausente es ``BoxCopyStaleDestination``.
    """
    inside = _filing_plan()._inside
    current, walked, created = root, [], []
    for part in relative.split("/") if relative else ():
        current = current / part
        walked.append(part)
        if not os.path.lexists(current):
            if not create_missing:
                raise BoxCopyStaleDestination(
                    "La carpeta destino revisada ya no existe en Box: no se recrea ni se copia."
                )
            try:
                current.mkdir()
                created.append("/".join(walked))
            except FileExistsError:
                pass
            except OSError as exc:
                raise BoxCopyRejected("No se pudo crear la subcarpeta destino en Box.") from exc
        if _redirects(current) or not inside(root, "/".join(walked)):
            raise BoxCopyRejected(
                "La subcarpeta destino no es una carpeta real dentro de la carpeta Box del expediente."
            )
    return current, created


# H3 (DV28): handle de carpeta que impide borrarla, renombrarla o sustituirla por una unión.
# Windows no aplica el modo de compartición a un handle abierto solo con FILE_READ_ATTRIBUTES
# (IoCheckShareAccess lo ignora): sin FILE_LIST_DIRECTORY la carpeta se podría borrar o renombrar.
_FILE_LIST_DIRECTORY = 0x0001
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ_WRITE = 0x0001 | 0x0002  # sin FILE_SHARE_DELETE
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x0010
_FILE_ATTRIBUTE_TAG_INFO = 9
_kernel32_api = None


def _kernel32():
    global _kernel32_api
    if _kernel32_api is None:
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        api.CreateFileW.restype = wintypes.HANDLE
        api.GetFileInformationByHandleEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                                     wintypes.DWORD)
        api.GetFileInformationByHandleEx.restype = wintypes.BOOL
        api.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                                  wintypes.DWORD)
        api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        api.CloseHandle.restype = wintypes.BOOL
        _kernel32_api = api
    return _kernel32_api


def _pin_directory(path: Path):
    """
    (handle, atributos, etiqueta reparse) de la carpeta abierta sin FILE_SHARE_DELETE y sin
    seguir enlaces: mientras el handle siga abierto nadie puede borrarla ni renombrarla.
    """
    import ctypes
    from ctypes import wintypes

    api = _kernel32()
    handle = api.CreateFileW(
        str(path), _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES, _FILE_SHARE_READ_WRITE, None, _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT, None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "No se puede fijar la carpeta", str(path))
    info = (wintypes.DWORD * 2)()  # FILE_ATTRIBUTE_TAG_INFO: atributos, etiqueta
    if not api.GetFileInformationByHandleEx(handle, _FILE_ATTRIBUTE_TAG_INFO, ctypes.byref(info),
                                            ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        api.CloseHandle(handle)
        raise OSError(error, "No se pueden leer los atributos de la carpeta", str(path))
    return handle, info[0], info[1]


def _pinned_final_path(handle) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = _kernel32().GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not 0 < length < len(buffer):
        raise OSError(ctypes.get_last_error(), "Ruta final de la carpeta no disponible")
    final = buffer.value
    if final.startswith("\\\\?\\UNC\\"):
        return "\\\\" + final[8:]
    return final[4:] if final.startswith("\\\\?\\") else final


@contextmanager
def _pinned_box_folder(root: Path, folder: Path):
    """
    H3 (DV28): durante COPY y VERIFY la raíz Box del expediente y cada carpeta hasta el
    destino quedan abiertas sin compartir el borrado, así que no se pueden borrar,
    renombrar ni sustituir por una unión mientras se escribe. Se comprueba lo realmente
    abierto (atributos del handle y su ruta final), no el nombre; si no se puede fijar o
    no coincide, ``BoxCopyRejected`` sin crear nada. Fuera de Windows no hay fijación y
    la salida de la carpeta solo se detecta en VERIFY.
    """
    if os.name != "nt":
        yield
        return
    changed = "La carpeta destino en Box cambió o no se puede fijar durante la copia: no se copia."
    try:
        parts = folder.relative_to(root).parts
    except ValueError:
        raise BoxCopyRejected(changed) from None
    handles = []
    try:
        for depth in range(len(parts) + 1):
            try:
                handle, attributes, tag = _pin_directory(root.joinpath(*parts[:depth]))
            except OSError:
                raise BoxCopyRejected(changed) from None
            handles.append(handle)
            pinned = SimpleNamespace(st_mode=_stat.S_IFDIR, st_file_attributes=attributes, st_reparse_tag=tag)
            if not attributes & _FILE_ATTRIBUTE_DIRECTORY or _reparse_redirects(pinned):
                raise BoxCopyRejected(changed)
        try:
            final = _pinned_final_path(handles[-1])
        except OSError:
            raise BoxCopyRejected(changed) from None
        if os.path.normcase(os.path.normpath(final)) != os.path.normcase(os.path.normpath(str(folder))):
            raise BoxCopyRejected(changed)
        yield
    finally:
        for handle in reversed(handles):
            _kernel32().CloseHandle(handle)


def _box_target_name(item, src: Path, target_filename: str, nomenclature_key: str, expedient_id: int):
    """(nombre final, opción de catálogo o None); validado en backend, nunca saneado en silencio."""
    filing_plan = _filing_plan()
    try:
        if nomenclature_key:
            if target_filename:
                raise BoxCopyRejected("Indica una nomenclatura o un nombre de archivo, no ambos.")
            option = filing_plan.nomenclature_option(expedient_id, nomenclature_key)
            return filing_plan.nomenclature_filename(option, src.suffix), option
        if target_filename:
            return filing_plan.check_filename(target_filename, src.suffix), None
        default_name = _safe_filename(item.get("original_filename") or src.name)
        return filing_plan.check_filename(default_name, src.suffix), None
    except filing_plan.FilingPlanError as exc:
        raise BoxCopyRejected(str(exc)) from None


def _box_candidate_names(name: str):
    """Misma serie que ``_unique_destination`` y la previsualización P3A: nombre, nombre_2..."""
    path = Path(name)
    yield name
    for counter in range(2, _BOX_COPY_MAX_CANDIDATES + 1):
        yield f"{path.stem}_{counter}{path.suffix}"


def _identical_box_file(path: Path, size: int, digest: str) -> bool:
    try:
        st = path.lstat()
        if _reparse_redirects(st) or not _stat.S_ISREG(st.st_mode) or st.st_size != size:
            return False
        return _sha256(path) == digest
    except OSError:
        return False


def _stream_into(src: Path, handle):
    """Copia por bloques; devuelve (bytes, SHA-256, stat del origen antes, después)."""
    digest = hashlib.sha256()
    size = 0
    with src.open("rb") as source:
        before = os.fstat(source.fileno())
        for chunk in iter(lambda: source.read(_BOX_COPY_CHUNK), b""):
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(source.fileno())
    handle.flush()
    os.fsync(handle.fileno())
    return size, digest.hexdigest(), before, after


def _verify_box_copy(dest: Path, folder: Path, source_stat, source_digest: str, streamed) -> None:
    size, digest, before, after = streamed

    def fail(reason):
        raise BoxCopyIncomplete(
            f"Copia en Box sin verificar ({reason}): «{dest.name}» queda sin registrar.", dest, "verify"
        )

    if (size, digest) != (source_stat.st_size, source_digest) or not (
        source_stat.st_mtime_ns == before.st_mtime_ns == after.st_mtime_ns
        and source_stat.st_size == before.st_size == after.st_size
    ):
        fail("el archivo de Bandeja cambió durante la copia")
    try:
        real = dest.resolve(strict=True)
        written = dest.lstat()
        written_digest = _sha256(dest)
    except (OSError, RuntimeError):
        fail("no se puede releer la copia")
    if _reparse_redirects(written) or os.path.normcase(str(real.parent)) != os.path.normcase(str(folder)):
        fail("el destino salió de la carpeta del expediente")
    if (written.st_size, written_digest) != (source_stat.st_size, source_digest):
        fail("tamaño o SHA-256 distintos del origen")


def _create_box_copy(src: Path, folder: Path, name: str, source_stat, source_digest: str):
    """
    (destino, decisión de colisión). Creación exclusiva ("xb"): un nombre ocupado nunca se
    sobrescribe; si el ocupante es idéntico (tamaño + SHA-256) se reutiliza, si no se prueba
    el siguiente de la serie.
    """
    for index, candidate in enumerate(_box_candidate_names(name)):
        dest = folder / candidate
        try:
            handle = dest.open("xb")
        except FileExistsError:
            if _identical_box_file(dest, source_stat.st_size, source_digest):
                return dest, "reused_identical"
            continue
        except PermissionError as exc:
            if os.path.lexists(dest):  # Windows: una carpeta con ese nombre
                continue
            raise BoxCopyRejected("Sin permiso para crear el archivo en la carpeta Box.") from exc
        except OSError as exc:
            raise BoxCopyRejected("No se pudo crear el archivo en la carpeta Box.") from exc

        try:
            with handle:
                streamed = _stream_into(src, handle)
        except Exception as exc:
            raise BoxCopyIncomplete(
                f"Fallo de escritura en Box: «{dest.name}» queda incompleto y sin registrar.", dest, "write"
            ) from exc
        _verify_box_copy(dest, folder, source_stat, source_digest, streamed)
        return dest, "none" if index == 0 else "renamed"

    raise BoxCopyRejected("Demasiados archivos con ese nombre en la carpeta destino: no se copia.")


def _register_box_copy(
    item_id: int,
    expedient_id: int,
    client_id,
    dest: Path,
    previous_path: str,
    trace: Dict[str, Any],
) -> None:
    """
    Único punto que marca ``copied_to_box``; solo tras la verificación. Si otra operación
    registró otra copia desde que se leyó el ítem (``previous_path``), no se pisa.
    """
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT status, copied_to_box_path FROM document_inbox_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        if not current:
            raise ValueError("No existe el documento de bandeja indicado.")
        if str(current["copied_to_box_path"] or "") not in (previous_path, str(dest)):
            raise ValueError("Otra operación registró otra copia en Box para este documento.")

        copied_at = _now()
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
            (expedient_id, client_id, str(dest), copied_at, str(dest), copied_at, int(item_id)),
        )
        message = {
            "own_unregistered_copy": "Copia propia ya verificada en Box registrada sin duplicarla",
            "preexisting_unverified": (
                "Archivo idéntico ya existente en Box registrado sin duplicarlo; "
                "no lo creó esta operación y su procedencia no está acreditada"
            ),
        }.get(trace.get("provenance"), "Documento copiado a carpeta Box del expediente")
        _record_event(
            conn,
            int(item_id),
            "copied_to_box",
            message,
            {**trace, "registered_at": copied_at},
        )
        conn.commit()


def _box_copy_provenance(item_id: int, dest: Path, digest: str, decision: str) -> str:
    """
    Quién creó el archivo registrado (DV25-P3B3, H5). Un archivo idéntico reutilizado solo
    es propio si un fallo de REGISTER de este mismo ítem dejó trazado ese destino, ese
    SHA-256 y que lo había creado él o era ya propio; si no (incluidas trazas anteriores a
    P3B3, sin procedencia), es anterior y no se atribuye a esta copia.
    """
    if decision != "reused_identical":
        return "created"
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT metadata_json FROM document_inbox_events "
                "WHERE item_id = ? AND event_type = 'copy_to_box_failed'",
                (int(item_id),),
            ).fetchall()
    except sqlite3.Error:
        rows = []
    for row in rows:
        failure = _metadata_dict(row["metadata_json"])
        if (failure.get("result") == "failed_register"
                and failure.get("destination_path") == str(dest)
                and failure.get("destination_sha256") == digest
                and failure.get("provenance") in ("created", "own_unregistered_copy")):
            return "own_unregistered_copy"
    return "preexisting_unverified"


def _record_box_copy_failure(item_id: int, trace: Dict[str, Any]) -> None:
    """Traza del fallo; no toca estado ni rutas del ítem. Si la BD tampoco responde, se omite."""
    try:
        with get_connection() as conn:
            _record_event(conn, int(item_id), "copy_to_box_failed", "Copia a Box no registrada", trace)
            conn.commit()
    except Exception:
        pass


def copy_inbox_item_to_expedient_box(
    item_id: int,
    expedient_id: Optional[int] = None,
    subfolder: str = "",
    target_filename: str = "",
    *,
    nomenclature_key: str = "",
) -> Dict[str, Any]:
    """
    Copia gobernada desde la bandeja interna del ERP hacia la carpeta Box vinculada al expediente.

    COPY -> VERIFY -> REGISTER:
    - Origen: archivo interno de Bandeja; destino: subcarpeta relativa dentro de la raíz Box
      del expediente, sin enlaces ni uniones. Nombre: ``target_filename`` o la nomenclatura
      ``nomenclature_key`` del catálogo del expediente (P3A), validado y con la extensión real.
    - Solo crea archivos nuevos; no modifica, mueve, renombra, sobrescribe ni borra nada en Box.
      Si el nombre existe se usa ``nombre_2``...; un archivo idéntico de esa serie se reutiliza.
    - ``copied_to_box`` y ``linked_document_path`` solo se escriben tras verificar tamaño y SHA-256.
    - Un ítem ya copiado cuya copia registrada sigue intacta no se vuelve a copiar.

    Errores: ``ValueError`` (incl. ``BoxCopyRejected``) o ``FileNotFoundError`` sin archivo nuevo
    en Box; ``BoxCopyIncomplete`` si queda un archivo sin registrar (``written_path``).
    Devuelve el ítem actualizado con ``box_copy`` (resultado de la operación).
    """
    ensure_document_inbox_schema()

    with _box_copy_lock(int(item_id)):
        return _copy_inbox_item_to_box(
            int(item_id), expedient_id, subfolder, str(target_filename or "").strip(),
            str(nomenclature_key or "").strip(),
        )


def _copy_inbox_item_to_box(item_id, expedient_id, subfolder, target_filename, nomenclature_key):
    relative = _box_subfolder(subfolder)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM document_inbox_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            raise ValueError("No existe el documento de bandeja indicado.")

        item = dict(row)
        expedient_id = int(expedient_id or item.get("expedient_id") or 0)
        if not expedient_id:
            raise ValueError("Vincula o indica un expediente antes de copiar a Box.")

        expedient = _get_expedient_for_box(conn, expedient_id)

    client_id = expedient.get("cliente_id")
    if item.get("client_id") and client_id and int(item["client_id"]) != int(client_id):
        raise BoxCopyRejected("El documento está vinculado a un cliente distinto del titular del expediente.")

    src = _verified_inbox_source(item)
    root = _authorized_box_root(expedient.get("box_folder_path"))
    final_name, option = _box_target_name(item, src, target_filename, nomenclature_key, expedient_id)

    source_stat = src.stat()
    source_digest = _sha256(src)
    recorded_digest = str(item.get("sha256") or "").strip().lower()
    if recorded_digest and recorded_digest != source_digest:
        raise BoxCopyRejected("El archivo de Bandeja no coincide con el SHA-256 registrado al importarlo: no se copia.")

    trace = {
        "expedient_id": expedient_id,
        "client_id": client_id,
        "source_path": str(src),
        "source_size_bytes": source_stat.st_size,
        "source_sha256": source_digest,
        "box_root": str(root),
        "subfolder": relative,
        "target_filename": target_filename,
        "nomenclature_key": nomenclature_key,
        "nomenclature_code": option.codigo if option else "",
        "rol_documental": (option.rol_documental or "") if option else "",
        "requested_filename": final_name,
    }

    previous = str(item.get("copied_to_box_path") or "")
    if item.get("status") == "copied_to_box" and previous:
        previous_path = Path(previous)
        if _identical_box_file(previous_path, source_stat.st_size, source_digest) and _safe_relative_to(previous_path, root):
            updated = get_inbox_item(item_id)
            updated["box_copy"] = {**trace, "result": "already_copied", "destination_path": previous}
            return updated
        if os.path.lexists(previous_path):
            raise BoxCopyRejected(
                "El documento ya tiene una copia registrada en Box que no coincide con esta: requiere revisión."
            )
        # Copia registrada ausente: se permite una copia nueva (recuperación).

    # Por nomenclatura (flujo del visor): la carpeta se eligió entre las existentes revisadas
    # por P3A; si desapareció no se recrea (H4).
    folder, created_folders = _box_destination_folder(root, relative, create_missing=not nomenclature_key)
    trace["created_folders"] = created_folders

    try:
        with _pinned_box_folder(root, folder):
            dest, decision = _create_box_copy(src, folder, final_name, source_stat, source_digest)
    except BoxCopyIncomplete as exc:
        _record_box_copy_failure(item_id, {
            **trace, "result": f"failed_{exc.stage}", "destination_path": exc.written_path,
            "failed_at": _now(), "error": str(exc),
        })
        raise

    trace.update({
        "destination_path": str(dest),
        "final_filename": dest.name,
        "destination_size_bytes": source_stat.st_size,
        "destination_sha256": source_digest,
        "collision_decision": decision,
        "verified_at": _now(),
        "result": "reused_identical" if decision == "reused_identical" else "copied",
    })
    provenance = _box_copy_provenance(item_id, dest, source_digest, decision)
    trace.update({
        "provenance": provenance,
        "created_by_this_operation": provenance == "created",
    })

    try:
        _register_box_copy(item_id, expedient_id, client_id, dest, previous, trace)
    except Exception as exc:
        incomplete = BoxCopyIncomplete(
            f"La copia «{dest.name}» está verificada en Box pero no se pudo registrar; "
            "reintentar la misma copia la registra sin duplicarla.",
            dest, "register", created=decision != "reused_identical",
        )
        _record_box_copy_failure(item_id, {
            **trace, "result": "failed_register", "failed_at": _now(), "error": str(exc),
        })
        raise incomplete from exc

    updated = get_inbox_item(item_id)
    updated["box_copy"] = trace
    return updated



def _batch_item_dedupe_key(item: Dict[str, Any]):
    """
    Clave defensiva para evitar copiar el mismo documento dos veces dentro de un grupo.
    """
    digest = str(item.get("sha256") or "").strip().lower()
    stored_path = _norm_document_path(item.get("stored_path") or item.get("linked_document_path") or "")
    filename = str(item.get("original_filename") or "").strip().lower()
    size = str(item.get("size_bytes") or "").strip()

    if digest:
        return ("sha256", digest)
    if stored_path:
        return ("stored_path", stored_path)
    if filename and size:
        return ("filename_size", filename, size)
    return None


def copy_document_inbox_batch_to_expedient_box(
    batch_id: int,
    expedient_id: Optional[int] = None,
    subfolder: str = "",
    target_filenames_by_item_id: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """
    Copia segura de un grupo documental a la carpeta Box de un expediente.

    No borra originales.
    No mueve documentos.
    No copia documentos descartados ni duplicados.
    No copia dos veces el mismo documento dentro del mismo grupo.
    """
    ensure_document_inbox_schema()
    ensure_document_inbox_batch_schema()

    batch = get_document_inbox_batch(int(batch_id))
    batch_expedient_id = int(expedient_id or batch.get("expedient_id") or 0)

    if not batch_expedient_id:
        raise ValueError("Indica un expediente destino para copiar el grupo a Box.")

    # Misma validación que la copia individual, antes de copiar nada ni guardarla en el grupo.
    safe_subfolder = _box_subfolder(subfolder or batch.get("target_box_folder") or "")

    copied = []
    skipped = []
    errors = []
    seen_keys = set()
    target_filenames_by_item_id = target_filenames_by_item_id or {}

    for item in batch.get("items") or []:
        item_id = int(item.get("id") or item.get("inbox_item_id") or 0)
        if not item_id:
            continue

        status = str(item.get("status") or "").strip().lower()

        if status in {"duplicate", "discarded"}:
            skipped.append({
                "id": item_id,
                "reason": f"status_{status}",
                "filename": item.get("original_filename"),
            })
            continue

        key = _batch_item_dedupe_key(item)
        if key and key in seen_keys:
            skipped.append({
                "id": item_id,
                "reason": "duplicate_inside_batch",
                "filename": item.get("original_filename"),
            })
            continue

        if key:
            seen_keys.add(key)

        src = Path(str(item.get("stored_path") or item.get("linked_document_path") or ""))
        if not src.exists() or not src.is_file():
            skipped.append({
                "id": item_id,
                "reason": "missing_file",
                "filename": item.get("original_filename"),
                "path": str(src),
            })
            continue

        try:
            target_filename = (
                target_filenames_by_item_id.get(item_id)
                or target_filenames_by_item_id.get(str(item_id))
                or ""
            )

            updated = copy_inbox_item_to_expedient_box(
                item_id,
                expedient_id=batch_expedient_id,
                subfolder=safe_subfolder,
                target_filename=target_filename,
            )
            copied.append({
                "id": item_id,
                "filename": updated.get("original_filename"),
                "destination_path": updated.get("copied_to_box_path"),
                "target_filename": str(target_filename or "").strip(),
            })
        except Exception as exc:
            errors.append({
                "id": item_id,
                "filename": item.get("original_filename"),
                "error": str(exc),
            })

    if errors and copied:
        batch_status = "partial"
    elif errors and not copied:
        batch_status = "error"
    elif copied:
        batch_status = "copied_to_box"
    else:
        batch_status = "partial"

    metadata = _metadata_dict(batch.get("metadata_json") or "")
    metadata["last_copy_to_box"] = {
        "at": _now(),
        "expedient_id": batch_expedient_id,
        "subfolder": safe_subfolder,
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "target_filenames_by_item_id": {
            str(k): v for k, v in (target_filenames_by_item_id or {}).items() if str(v or "").strip()
        },
    }

    with get_connection() as conn:
        expedient = _get_expedient_for_box(conn, batch_expedient_id)

        conn.execute(
            """
            UPDATE document_inbox_batches
            SET status = ?,
                expedient_id = ?,
                client_id = COALESCE(client_id, ?),
                target_box_folder = ?,
                metadata_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                batch_status,
                batch_expedient_id,
                expedient.get("cliente_id"),
                safe_subfolder,
                json.dumps(metadata, ensure_ascii=False),
                _now(),
                int(batch_id),
            ),
        )
        conn.commit()

    refreshed = get_document_inbox_batch(int(batch_id))
    refreshed["copy_result"] = {
        "batch_id": int(batch_id),
        "status": batch_status,
        "expedient_id": batch_expedient_id,
        "subfolder": safe_subfolder,
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
    }
    return refreshed


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
    Solo lee ``clientes``: no inicializa el esquema de Bandeja (DV25-P3B3, H6).
    """
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
    evolucionando durante el proyecto. Solo lee: no inicializa el esquema de Bandeja.
    """
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



def _resolve_expedient_type_label(conn, expedient: Dict[str, Any]) -> str:
    """
    Devuelve el TIPO de expediente para etiquetas UI.

    Regla:
    - Usar tipo_expediente / tipo / procedimiento si existen.
    - Si solo hay tipo_expediente_id, intentar resolverlo contra tablas conocidas.
    - Nunca usar subtipo_expediente como sustituto del tipo.
    """
    for key in ["tipo_expediente", "tipo", "procedimiento"]:
        value = str(expedient.get(key) or "").strip()
        if value:
            return value

    tipo_id = expedient.get("tipo_expediente_id")
    if not tipo_id:
        return ""

    candidate_tables = [
        "config_tipos_expediente",
        "tipos_expediente",
        "tipo_expediente",
        "expedient_types",
        "expediente_tipos",
    ]

    candidate_name_cols = [
        "nombre",
        "name",
        "codigo",
        "code",
        "descripcion",
        "description",
        "label",
    ]

    for table in candidate_tables:
        try:
            columns = _table_columns(conn, table)
        except Exception:
            continue

        if "id" not in columns:
            continue

        name_col = None
        for col in candidate_name_cols:
            if col in columns:
                name_col = col
                break

        if not name_col:
            continue

        try:
            row = conn.execute(
                f"SELECT {name_col} FROM {table} WHERE id = ?",
                (int(tipo_id),),
            ).fetchone()
        except Exception:
            continue

        if row:
            try:
                value = str(row[name_col] or "").strip()
            except Exception:
                value = str(row[0] or "").strip()

            if value:
                return value

    return ""


def expedient_autocomplete_options_for_client(client_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Opciones de expedientes para AppAutocomplete.

    La etiqueta debe mostrar el TIPO del expediente, no el subtipo.
    Solo lee: no inicializa el esquema de Bandeja.
    """
    expedients = list_expedients_for_client(client_id, limit=limit)
    options = []

    with get_connection() as conn:
        for expedient in expedients:
            expedient_id = int(expedient.get("id"))
            numero = (
                expedient.get("numero_expediente")
                or expedient.get("numero_expediente_mercurio")
                or f"EXPEDIENTE #{expedient_id}"
            )

            tipo_label = _resolve_expedient_type_label(conn, expedient)
            if not tipo_label:
                tipo_label = "Tipo pendiente"

            estado = (
                expedient.get("estado_documental")
                or expedient.get("estado_administrativo")
                or ""
            )

            parts = [
                f"#{expedient_id}",
                str(numero).strip(),
                str(tipo_label).strip(),
            ]

            if str(estado or "").strip():
                parts.append(str(estado).strip())

            label = " · ".join(part for part in parts if part)

            options.append(
                {
                    "id": expedient_id,
                    "label": label,
                    "expedient": expedient,
                }
            )

    return options


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


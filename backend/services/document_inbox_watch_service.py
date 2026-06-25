from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services import document_inbox_service


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect():
    return document_inbox_service._connect()


def _row_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def ensure_watch_schema() -> None:
    """
    Crea las tablas de vigilancia de carpetas.

    La vigilancia no modifica la carpeta original.
    Solo registra huellas de archivos y copia archivos nuevos a Bandeja Documental.
    """
    document_inbox_service.ensure_document_inbox_schema()

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_watch_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                name TEXT NOT NULL,
                folder_path TEXT NOT NULL UNIQUE,
                source_type TEXT DEFAULT 'folder_watch',
                source_label TEXT DEFAULT 'Vigilancia carpeta',
                is_active INTEGER DEFAULT 1,
                recursive INTEGER DEFAULT 0,
                notes TEXT,
                metadata_json TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_inbox_watch_seen_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_folder_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_ext TEXT,
                size_bytes INTEGER,
                modified_at TEXT,
                fingerprint TEXT NOT NULL,
                inbox_item_id INTEGER,
                status TEXT DEFAULT 'imported',
                error_message TEXT,
                UNIQUE(watch_folder_id, fingerprint),
                FOREIGN KEY (watch_folder_id) REFERENCES document_inbox_watch_folders(id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_watch_seen_folder
            ON document_inbox_watch_seen_files(watch_folder_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_inbox_watch_seen_path
            ON document_inbox_watch_seen_files(file_path)
            """
        )

        conn.commit()


def default_downloads_folder() -> str:
    """
    Devuelve la carpeta Descargas del usuario actual.
    """
    downloads = Path.home() / "Downloads"
    return str(downloads)


def upsert_watch_folder(
    folder_path: str,
    name: str | None = None,
    source_label: str = "Vigilancia carpeta",
    recursive: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    ensure_watch_schema()

    folder = Path(folder_path).expanduser()
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"La carpeta no existe o no es válida: {folder}")

    clean_path = str(folder.resolve())
    clean_name = str(name or folder.name or "Carpeta vigilada").strip()
    now = _now()

    with _connect() as conn:
        conn.row_factory = _row_factory

        existing = conn.execute(
            """
            SELECT *
            FROM document_inbox_watch_folders
            WHERE folder_path = ?
            """,
            (clean_path,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE document_inbox_watch_folders
                SET updated_at = ?,
                    name = ?,
                    source_label = ?,
                    recursive = ?,
                    notes = ?,
                    is_active = 1
                WHERE id = ?
                """,
                (
                    now,
                    clean_name,
                    source_label,
                    1 if recursive else 0,
                    notes,
                    int(existing["id"]),
                ),
            )
            watch_id = int(existing["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO document_inbox_watch_folders (
                    created_at, updated_at, name, folder_path,
                    source_type, source_label, is_active,
                    recursive, notes, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    now,
                    clean_name,
                    clean_path,
                    "folder_watch",
                    source_label,
                    1,
                    1 if recursive else 0,
                    notes,
                    json.dumps({"created_by": "document_inbox_watch_service"}, ensure_ascii=False),
                ),
            )
            watch_id = int(cur.lastrowid)

        conn.commit()

    return get_watch_folder(watch_id)


def list_watch_folders(active_only: bool = False) -> list[dict[str, Any]]:
    ensure_watch_schema()

    sql = """
        SELECT *
        FROM document_inbox_watch_folders
    """
    params: list[Any] = []

    if active_only:
        sql += " WHERE is_active = 1"

    sql += " ORDER BY updated_at DESC, id DESC"

    with _connect() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def get_watch_folder(watch_folder_id: int) -> dict[str, Any]:
    ensure_watch_schema()

    with _connect() as conn:
        conn.row_factory = _row_factory
        row = conn.execute(
            """
            SELECT *
            FROM document_inbox_watch_folders
            WHERE id = ?
            """,
            (int(watch_folder_id),),
        ).fetchone()

        if not row:
            raise ValueError(f"No existe la carpeta vigilada #{watch_folder_id}")

        return dict(row)


def _iter_candidate_files(folder: Path, recursive: bool, max_files: int):
    pattern = "**/*" if recursive else "*"
    count = 0

    for path in folder.glob(pattern):
        if count >= max_files:
            break

        if not path.is_file:
            continue

        if not path.is_file():
            continue

        if path.name.startswith("~$"):
            continue

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        count += 1
        yield path


def _fingerprint(path: Path) -> tuple[str, int, str]:
    stat = path.stat()
    size = int(stat.st_size or 0)
    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    fingerprint = f"{str(path.resolve())}|{size}|{modified_at}"
    return fingerprint, size, modified_at


def _import_file_to_inbox_compatible(path: Path, source_label: str) -> dict[str, Any]:
    """
    Llama a import_file_to_inbox filtrando kwargs según la firma real.
    Esto evita romper si la función cambia ligeramente.
    """
    fn = document_inbox_service.import_file_to_inbox
    sig = inspect.signature(fn)
    params = sig.parameters

    kwargs: dict[str, Any] = {}

    if "source_type" in params:
        kwargs["source_type"] = "folder_watch"

    if "source_label" in params:
        kwargs["source_label"] = source_label

    if "notes" in params:
        kwargs["notes"] = "Importado automáticamente desde carpeta vigilada."

    return fn(str(path), **kwargs)


def scan_watch_folder(watch_folder_id: int, max_files: int = 300) -> dict[str, Any]:
    """
    Escanea una carpeta vigilada e importa archivos nuevos a Bandeja.

    No modifica la carpeta origen.

    Importante:
    - No mantiene una transacción abierta mientras import_file_to_inbox()
      copia el archivo, porque ese servicio usa su propia conexión SQLite.
    - Los archivos con status='error' pueden reintentarse.
    """
    ensure_watch_schema()

    watch = get_watch_folder(watch_folder_id)

    if not int(watch.get("is_active") or 0):
        return {
            "watch_folder": watch,
            "imported": [],
            "skipped": [],
            "errors": ["La carpeta vigilada está inactiva."],
        }

    folder = Path(watch["folder_path"])
    recursive = bool(int(watch.get("recursive") or 0))
    source_label = watch.get("source_label") or "Vigilancia carpeta"

    imported = []
    skipped = []
    errors = []

    for file_path in _iter_candidate_files(folder, recursive=recursive, max_files=max_files):
        try:
            fingerprint, size, modified_at = _fingerprint(file_path)
            file_name = file_path.name
            file_ext = file_path.suffix.lower()
            resolved_path = str(file_path.resolve())

            # 1) Comprobar si ya fue importado. Si quedó en error, se reintenta.
            with _connect() as conn:
                conn.row_factory = _row_factory
                seen = conn.execute(
                    """
                    SELECT *
                    FROM document_inbox_watch_seen_files
                    WHERE watch_folder_id = ?
                      AND fingerprint = ?
                    """,
                    (int(watch_folder_id), fingerprint),
                ).fetchone()

            if seen and str(seen.get("status") or "") == "imported":
                skipped.append(
                    {
                        "file_path": resolved_path,
                        "reason": "already_seen",
                        "inbox_item_id": seen.get("inbox_item_id"),
                    }
                )
                continue

            try:
                # 2) Importar sin mantener conexión de vigilancia abierta.
                item = _import_file_to_inbox_compatible(file_path, source_label=source_label)
                inbox_item_id = item.get("id") if isinstance(item, dict) else None

                # 3) Registrar éxito.
                with _connect() as conn:
                    if seen:
                        conn.execute(
                            """
                            UPDATE document_inbox_watch_seen_files
                            SET updated_at = ?,
                                file_path = ?,
                                file_name = ?,
                                file_ext = ?,
                                size_bytes = ?,
                                modified_at = ?,
                                inbox_item_id = ?,
                                status = ?,
                                error_message = ?
                            WHERE id = ?
                            """,
                            (
                                _now(),
                                resolved_path,
                                file_name,
                                file_ext,
                                size,
                                modified_at,
                                inbox_item_id,
                                "imported",
                                "",
                                int(seen["id"]),
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO document_inbox_watch_seen_files (
                                watch_folder_id, created_at, updated_at,
                                file_path, file_name, file_ext,
                                size_bytes, modified_at, fingerprint,
                                inbox_item_id, status, error_message
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(watch_folder_id),
                                _now(),
                                _now(),
                                resolved_path,
                                file_name,
                                file_ext,
                                size,
                                modified_at,
                                fingerprint,
                                inbox_item_id,
                                "imported",
                                "",
                            ),
                        )
                    conn.commit()

                imported.append(
                    {
                        "file_path": resolved_path,
                        "file_name": file_name,
                        "inbox_item_id": inbox_item_id,
                    }
                )

            except Exception as exc:
                error_message = str(exc)

                # 4) Registrar error sin bloquear siguientes archivos.
                with _connect() as conn:
                    if seen:
                        conn.execute(
                            """
                            UPDATE document_inbox_watch_seen_files
                            SET updated_at = ?,
                                file_path = ?,
                                file_name = ?,
                                file_ext = ?,
                                size_bytes = ?,
                                modified_at = ?,
                                status = ?,
                                error_message = ?
                            WHERE id = ?
                            """,
                            (
                                _now(),
                                resolved_path,
                                file_name,
                                file_ext,
                                size,
                                modified_at,
                                "error",
                                error_message,
                                int(seen["id"]),
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO document_inbox_watch_seen_files (
                                watch_folder_id, created_at, updated_at,
                                file_path, file_name, file_ext,
                                size_bytes, modified_at, fingerprint,
                                inbox_item_id, status, error_message
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(watch_folder_id),
                                _now(),
                                _now(),
                                resolved_path,
                                file_name,
                                file_ext,
                                size,
                                modified_at,
                                fingerprint,
                                None,
                                "error",
                                error_message,
                            ),
                        )
                    conn.commit()

                errors.append(f"{file_name}: {error_message}")

        except Exception as exc:
            errors.append(f"{file_path}: {exc}")

    return {
        "watch_folder": watch,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def ensure_default_downloads_watch_folder() -> dict[str, Any]:
    """
    Crea o reactiva la vigilancia de Descargas.
    """
    downloads = default_downloads_folder()

    return upsert_watch_folder(
        downloads,
        name="Descargas",
        source_label="Descargas vigiladas",
        recursive=False,
        notes="Carpeta Descargas del usuario. El ERP copia archivos nuevos a Bandeja Documental.",
    )

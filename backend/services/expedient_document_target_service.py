"""
Targets documentales asociados a carpetas Box de un expediente.

El servicio:
- guarda rutas relativas a la raíz Box;
- permite un target activo por finalidad;
- no crea, mueve, renombra ni elimina carpetas físicas;
- conserva histórico desactivando targets anteriores.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260804_create_expedient_document_targets.sql"
)

VALID_PURPOSES = {
    "PRESENTACION",
    "APORTACION",
    "APORTACION_TASAS",
    "REQUERIMIENTO",
    "RECURSO",
}


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def _connection(
    db_path: str | Path = DEFAULT_DB_PATH,
):
    conn = _connect(db_path)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(
            f"No existe la migración: {MIGRATION_PATH}"
        )

    with _connection(db_path) as conn:
        conn.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )


def _normalize_purpose(value) -> str:
    purpose = (
        str(value or "")
        .strip()
        .upper()
        .replace(" ", "_")
    )

    if purpose not in VALID_PURPOSES:
        raise ValueError(
            "Finalidad documental no válida: "
            f"{purpose or '-'}"
        )

    return purpose


def _normalize_relative_path(value) -> str:
    raw = (
        str(value or "")
        .strip()
        .replace("\\", "/")
    )

    while "//" in raw:
        raw = raw.replace("//", "/")

    raw = raw.strip("/")

    if not raw:
        raise ValueError(
            "La ruta relativa no puede estar vacía"
        )

    parts = [
        part.strip()
        for part in raw.split("/")
        if part.strip()
    ]

    if any(part == ".." for part in parts):
        raise ValueError(
            "La ruta relativa no puede salir "
            "de la carpeta del expediente"
        )

    return "/".join(parts)


def _require_expedient(
    conn: sqlite3.Connection,
    expediente_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            id,
            box_folder_path
        FROM expedientes
        WHERE id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No existe el expediente indicado"
        )

    return row


def _row_to_dict(row):
    return dict(row) if row else None


def set_target(
    expediente_id: int,
    purpose: str,
    relative_path: str,
    *,
    created_by: str = "ERP",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    ensure_schema(db_path=db_path)

    expediente_id = int(expediente_id)
    purpose = _normalize_purpose(purpose)
    relative_path = _normalize_relative_path(
        relative_path
    )

    with _connection(db_path) as conn:
        _require_expedient(
            conn,
            expediente_id,
        )

        existing = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE expediente_id = ?
              AND purpose = ?
              AND active = 1
            LIMIT 1
            """,
            (
                expediente_id,
                purpose,
            ),
        ).fetchone()

        if (
            existing
            and existing["relative_path"]
            == relative_path
        ):
            return _row_to_dict(existing)

        conn.execute(
            """
            UPDATE expedient_document_targets
            SET active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE expediente_id = ?
              AND purpose = ?
              AND active = 1
            """,
            (
                expediente_id,
                purpose,
            ),
        )

        cursor = conn.execute(
            """
            INSERT INTO expedient_document_targets (
                expediente_id,
                purpose,
                relative_path,
                active,
                created_by
            )
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                expediente_id,
                purpose,
                relative_path,
                str(created_by or "ERP"),
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE id = ?
            """,
            (int(cursor.lastrowid),),
        ).fetchone()

        return _row_to_dict(row)


def get_active_target(
    expediente_id: int,
    purpose: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    ensure_schema(db_path=db_path)

    purpose = _normalize_purpose(purpose)

    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE expediente_id = ?
              AND purpose = ?
              AND active = 1
            LIMIT 1
            """,
            (
                int(expediente_id),
                purpose,
            ),
        ).fetchone()

        return _row_to_dict(row)


def list_active_targets(
    expediente_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE expediente_id = ?
              AND active = 1
            ORDER BY purpose, id
            """,
            (int(expediente_id),),
        ).fetchall()

        return [
            _row_to_dict(row)
            for row in rows
        ]


def list_targets_for_path(
    expediente_id: int,
    relative_path: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    ensure_schema(db_path=db_path)

    relative_path = _normalize_relative_path(
        relative_path
    )

    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE expediente_id = ?
              AND relative_path = ?
              AND active = 1
            ORDER BY purpose
            """,
            (
                int(expediente_id),
                relative_path,
            ),
        ).fetchall()

        return [
            _row_to_dict(row)
            for row in rows
        ]


def clear_target(
    expediente_id: int,
    purpose: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    ensure_schema(db_path=db_path)

    purpose = _normalize_purpose(purpose)

    with _connection(db_path) as conn:
        return conn.execute(
            """
            UPDATE expedient_document_targets
            SET active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE expediente_id = ?
              AND purpose = ?
              AND active = 1
            """,
            (
                int(expediente_id),
                purpose,
            ),
        ).rowcount


def clear_targets_for_path(
    expediente_id: int,
    relative_path: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    ensure_schema(db_path=db_path)

    relative_path = _normalize_relative_path(
        relative_path
    )

    with _connection(db_path) as conn:
        return conn.execute(
            """
            UPDATE expedient_document_targets
            SET active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE expediente_id = ?
              AND relative_path = ?
              AND active = 1
            """,
            (
                int(expediente_id),
                relative_path,
            ),
        ).rowcount


def relative_path_from_absolute(
    expediente_id: int,
    folder_path: str | Path,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str:
    """
    Convierte una carpeta absoluta en una ruta relativa segura
    respecto de la raíz Box vinculada al expediente.
    """
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        expediente = _require_expedient(
            conn,
            int(expediente_id),
        )

        root_value = str(
            expediente["box_folder_path"]
            or ""
        ).strip()

    if not root_value:
        raise ValueError(
            "El expediente no tiene una ruta Box vinculada"
        )

    root = Path(root_value).expanduser().resolve()
    folder = Path(
        str(folder_path or "").strip()
    ).expanduser().resolve()

    if not folder.exists():
        raise FileNotFoundError(
            f"No existe la carpeta seleccionada: {folder}"
        )

    if not folder.is_dir():
        raise NotADirectoryError(
            f"La ruta seleccionada no es una carpeta: {folder}"
        )

    try:
        relative = folder.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "La carpeta seleccionada no pertenece "
            "a la ruta Box del expediente"
        ) from exc

    relative_text = str(
        relative
    ).replace("\\", "/").strip("/")

    if not relative_text or relative_text == ".":
        raise ValueError(
            "La carpeta raíz del expediente no puede "
            "utilizarse como target documental"
        )

    return _normalize_relative_path(
        relative_text
    )


def set_target_from_absolute(
    expediente_id: int,
    purpose: str,
    folder_path: str | Path,
    *,
    created_by: str = "ERP",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    relative_path = relative_path_from_absolute(
        expediente_id,
        folder_path,
        db_path=db_path,
    )

    return set_target(
        expediente_id,
        purpose,
        relative_path,
        created_by=created_by,
        db_path=db_path,
    )


def resolve_target_path(
    expediente_id: int,
    purpose: str,
    *,
    require_exists: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    """
    Resuelve el target activo sin permitir que salga de la raíz
    Box del expediente.
    """
    ensure_schema(db_path=db_path)

    purpose = _normalize_purpose(
        purpose
    )

    with _connection(db_path) as conn:
        expediente = _require_expedient(
            conn,
            int(expediente_id),
        )

        row = conn.execute(
            """
            SELECT *
            FROM expedient_document_targets
            WHERE expediente_id = ?
              AND purpose = ?
              AND active = 1
            LIMIT 1
            """,
            (
                int(expediente_id),
                purpose,
            ),
        ).fetchone()

    if not row:
        return None

    root_value = str(
        expediente["box_folder_path"]
        or ""
    ).strip()

    if not root_value:
        raise ValueError(
            "El expediente no tiene una ruta Box vinculada"
        )

    root = Path(root_value).expanduser().resolve()
    relative = _normalize_relative_path(
        row["relative_path"]
    )
    resolved = (
        root
        / Path(relative)
    ).resolve()

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "El target guardado sale de la ruta Box "
            "del expediente"
        ) from exc

    if require_exists:
        if not resolved.exists():
            raise FileNotFoundError(
                f"No existe la carpeta target: {resolved}"
            )

        if not resolved.is_dir():
            raise NotADirectoryError(
                f"El target no es una carpeta: {resolved}"
            )

    result = _row_to_dict(row)
    result["absolute_path"] = str(
        resolved
    )

    return result

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260723_create_internal_transfers.sql"
)
SOURCES = {"bank", "cashmatic"}


def _connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _ensure_columns(
    conn: sqlite3.Connection, table: str, additions: dict[str, str]
) -> None:
    columns = _columns(conn, table)
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    _ensure_columns(
        conn,
        "economic_internal_transfers",
        {
            "source_type": "TEXT",
            "destination_type": "TEXT",
            "source_movement_ref_id": "INTEGER",
            "destination_movement_ref_id": "INTEGER",
            "source_account_key": "TEXT",
            "destination_account_key": "TEXT",
            "source_previous_review_status": "TEXT",
            "destination_previous_review_status": "TEXT",
            "notes": "TEXT",
        },
    )
    for table in ("bank_movements", "cashmatic_movements"):
        if _table_exists(conn, table):
            _ensure_columns(
                conn,
                table,
                {
                    "internal_transfer_id": "INTEGER",
                    "transfer_leg": "TEXT",
                },
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_internal_transfer
                ON {table}(internal_transfer_id, transfer_leg)
                """
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_source_ref
        ON economic_internal_transfers(source_type, source_movement_ref_id)
        WHERE source_type IS NOT NULL AND source_movement_ref_id IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_destination_ref
        ON economic_internal_transfers(destination_type, destination_movement_ref_id)
        WHERE destination_type IS NOT NULL
          AND destination_movement_ref_id IS NOT NULL
        """
    )


def _normalize_source(source: str) -> str:
    source = str(source or "").strip().lower()
    if source not in SOURCES:
        raise ValueError("El origen del movimiento no es válido.")
    return source


def _movement(
    conn: sqlite3.Connection, source: str, movement_id: int
) -> dict[str, Any]:
    source = _normalize_source(source)
    table = "bank_movements" if source == "bank" else "cashmatic_movements"
    if not _table_exists(conn, table):
        raise ValueError(f"No existe la tabla de movimientos {source}.")
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?",
        (int(movement_id),),
    ).fetchone()
    if not row:
        raise ValueError("No existe el movimiento seleccionado.")
    data = dict(row)
    if source == "bank":
        amount = int(data.get("amount_centimos") or 0)
        movement_date = str(data.get("operation_date") or "")
        account_key = str(
            data.get("account_iban")
            or data.get("account_label")
            or data.get("bank_name")
            or ""
        ).strip().upper()
        account_label = str(
            data.get("account_label")
            or data.get("account_iban")
            or data.get("bank_name")
            or "Cuenta bancaria"
        ).strip()
        concept = str(data.get("concept") or "")
    else:
        amount = int(
            data.get("requested_centimos")
            or data.get("net_amount_centimos")
            or 0
        )
        movement_date = str(data.get("start_time") or "")[:10]
        account_key = str(
            data.get("source_raw") or "CASHMATIC"
        ).strip().upper()
        account_label = str(
            data.get("source_raw") or "Cashmatic"
        ).strip()
        concept = str(data.get("reason_raw") or data.get("reference_raw") or "")
    return {
        **data,
        "source": source,
        "table": table,
        "amount_centimos_normalized": amount,
        "movement_date_normalized": movement_date,
        "account_key_normalized": account_key,
        "account_label_normalized": account_label,
        "concept_normalized": concept,
    }


def _date_distance(left: str, right: str) -> int:
    try:
        return abs((date.fromisoformat(left[:10]) - date.fromisoformat(right[:10])).days)
    except (TypeError, ValueError):
        return 999999


def list_transfer_candidates(
    *,
    source_type: str,
    source_movement_id: int,
    max_date_distance_days: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        origin = _movement(conn, source_type, source_movement_id)
        origin_amount = int(origin["amount_centimos_normalized"])
        if origin_amount >= 0:
            raise ValueError("El movimiento origen debe ser negativo.")
        if origin.get("internal_transfer_id"):
            raise ValueError("El movimiento ya está vinculado a un traspaso.")
        result: list[dict[str, Any]] = []
        for candidate_source, table in (
            ("bank", "bank_movements"),
            ("cashmatic", "cashmatic_movements"),
        ):
            if not _table_exists(conn, table):
                continue
            for row in conn.execute(
                f"""
                SELECT id
                FROM {table}
                WHERE COALESCE(internal_transfer_id, 0) = 0
                ORDER BY id DESC
                """
            ).fetchall():
                candidate = _movement(conn, candidate_source, int(row["id"]))
                if int(candidate["amount_centimos_normalized"]) <= 0:
                    continue
                if (
                    abs(int(candidate["amount_centimos_normalized"]))
                    != abs(origin_amount)
                ):
                    continue
                if (
                    candidate["account_key_normalized"]
                    == origin["account_key_normalized"]
                ):
                    continue
                distance = _date_distance(
                    origin["movement_date_normalized"],
                    candidate["movement_date_normalized"],
                )
                if (
                    max_date_distance_days is not None
                    and distance > int(max_date_distance_days)
                ):
                    continue
                result.append({**candidate, "date_distance_days": distance})
        return sorted(
            result,
            key=lambda item: (
                int(item["date_distance_days"]),
                item["movement_date_normalized"],
                int(item["id"]),
            ),
        )


def _account_id(
    conn: sqlite3.Connection, key: str, label: str
) -> int:
    row = conn.execute(
        """
        SELECT id FROM economic_accounts
        WHERE UPPER(TRIM(name)) = UPPER(TRIM(?))
           OR UPPER(TRIM(COALESCE(iban, ''))) = UPPER(TRIM(?))
        ORDER BY id LIMIT 1
        """,
        (label, key),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO economic_accounts(name, iban) VALUES (?, NULLIF(?, ''))",
        (label or key, key if key.startswith("ES") else ""),
    )
    return int(cursor.lastrowid)


def link_existing_movements(
    *,
    source_type: str,
    source_movement_id: int,
    destination_type: str,
    destination_movement_id: int,
    notes: str = "",
    created_by: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        origin = _movement(conn, source_type, source_movement_id)
        destination = _movement(
            conn, destination_type, destination_movement_id
        )
        origin_amount = int(origin["amount_centimos_normalized"])
        destination_amount = int(destination["amount_centimos_normalized"])
        if origin_amount >= 0 or destination_amount <= 0:
            raise ValueError("El traspaso requiere una salida negativa y una entrada positiva.")
        if abs(origin_amount) != abs(destination_amount):
            raise ValueError("Los importes de salida y entrada no cuadran.")
        if origin["account_key_normalized"] == destination["account_key_normalized"]:
            raise ValueError("Los movimientos pertenecen a la misma cuenta.")
        if origin.get("internal_transfer_id") or destination.get("internal_transfer_id"):
            raise ValueError("Uno de los movimientos ya está vinculado a un traspaso.")

        source_account_id = _account_id(
            conn,
            origin["account_key_normalized"],
            origin["account_label_normalized"],
        )
        destination_account_id = _account_id(
            conn,
            destination["account_key_normalized"],
            destination["account_label_normalized"],
        )
        cursor = conn.execute(
            """
            INSERT INTO economic_internal_transfers(
                transfer_date, source_account_id, destination_account_id,
                amount_centimos, concept, reference, status, created_by,
                source_type, destination_type,
                source_movement_ref_id, destination_movement_ref_id,
                source_account_key, destination_account_key,
                source_previous_review_status,
                destination_previous_review_status, notes
            )
            VALUES (?, ?, ?, ?, ?, '', 'CONCILIADO', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                destination["movement_date_normalized"]
                or origin["movement_date_normalized"],
                source_account_id,
                destination_account_id,
                abs(origin_amount),
                (
                    "Traspaso interno: "
                    f"{origin['account_label_normalized']} → "
                    f"{destination['account_label_normalized']}"
                ),
                str(created_by or "").strip(),
                origin["source"],
                destination["source"],
                int(origin["id"]),
                int(destination["id"]),
                origin["account_key_normalized"],
                destination["account_key_normalized"],
                str(origin.get("review_status") or ""),
                str(destination.get("review_status") or ""),
                str(notes or "").strip(),
            ),
        )
        transfer_id = int(cursor.lastrowid)
        for movement, leg in ((origin, "SALIDA"), (destination, "ENTRADA")):
            conn.execute(
                f"""
                UPDATE {movement['table']}
                SET internal_transfer_id = ?, transfer_leg = ?,
                    review_status = 'MANUALLY_LINKED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (transfer_id, leg, int(movement["id"])),
            )
            conn.execute(
                """
                INSERT INTO eco_eventos(
                    entidad, entidad_id, tipo_evento, titulo,
                    descripcion, estado_anterior, estado_nuevo, usuario
                )
                VALUES (?, ?, 'TRASPASO_VINCULADO',
                        'MOVIMIENTO VINCULADO COMO TRASPASO',
                        ?, ?, 'CONCILIADO', ?)
                """,
                (
                    movement["table"].upper(),
                    int(movement["id"]),
                    f"Traspaso interno #{transfer_id}; pata {leg}",
                    str(movement.get("review_status") or ""),
                    str(created_by or "").strip(),
                ),
            )
        conn.commit()
    return get_internal_transfer(transfer_id, db_path=db_path)


def unlink_internal_transfer(
    transfer_id: int,
    *,
    reason: str,
    user: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Debes indicar el motivo para eliminar el vínculo.")
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM economic_internal_transfers WHERE id = ?",
            (int(transfer_id),),
        ).fetchone()
        if not row:
            raise ValueError("No existe el traspaso.")
        transfer = dict(row)
        legs = (
            (
                transfer["source_type"],
                transfer["source_movement_ref_id"],
                transfer.get("source_previous_review_status"),
                "SALIDA",
            ),
            (
                transfer["destination_type"],
                transfer["destination_movement_ref_id"],
                transfer.get("destination_previous_review_status"),
                "ENTRADA",
            ),
        )
        for source, movement_id, previous_status, leg in legs:
            movement = _movement(conn, source, int(movement_id))
            conn.execute(
                f"""
                UPDATE {movement['table']}
                SET internal_transfer_id = NULL, transfer_leg = NULL,
                    review_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND internal_transfer_id = ?
                """,
                (
                    str(previous_status or "PENDING_MANUAL_REVIEW"),
                    int(movement_id),
                    int(transfer_id),
                ),
            )
            conn.execute(
                """
                INSERT INTO eco_eventos(
                    entidad, entidad_id, tipo_evento, titulo,
                    descripcion, estado_anterior, estado_nuevo, usuario
                )
                VALUES (?, ?, 'TRASPASO_DESVINCULADO',
                        'VÍNCULO DE TRASPASO ELIMINADO',
                        ?, 'CONCILIADO', ?, ?)
                """,
                (
                    movement["table"].upper(),
                    int(movement_id),
                    f"Traspaso interno #{transfer_id}; pata {leg}. Motivo: {reason}",
                    str(previous_status or "PENDING_MANUAL_REVIEW"),
                    str(user or "").strip(),
                ),
            )
        conn.execute(
            "DELETE FROM economic_internal_transfers WHERE id = ?",
            (int(transfer_id),),
        )
        conn.commit()
        return transfer


def get_internal_transfer(
    transfer_id: int, *, db_path: str | Path = DEFAULT_DB_PATH
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM economic_internal_transfers WHERE id = ?",
            (int(transfer_id),),
        ).fetchone()
        if not row:
            raise ValueError("No existe el traspaso.")
        return dict(row)

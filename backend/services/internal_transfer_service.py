from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260723_create_internal_transfers.sql"
)


def _connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    movement_columns = _columns(conn, "eco_movimientos_importados")
    additions = {
        "account_id": "INTEGER",
        "internal_transfer_id": "INTEGER",
        "transfer_leg": "TEXT",
    }
    for column, definition in additions.items():
        if column not in movement_columns:
            conn.execute(
                f"ALTER TABLE eco_movimientos_importados "
                f"ADD COLUMN {column} {definition}"
            )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_eco_movimientos_internal_transfer
        ON eco_movimientos_importados(internal_transfer_id, transfer_leg)
        """
    )


def _money_to_centimos(value: Any) -> int:
    raw = str(value or "").strip().replace("€", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return int(
            (Decimal(raw) * Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("El importe del traspaso no es válido.") from exc


def create_account(
    *,
    name: str,
    bank_name: str = "",
    iban: str = "",
    currency: str = "EUR",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    name = str(name or "").strip()
    bank_name = str(bank_name or "").strip()
    iban = "".join(str(iban or "").upper().split())
    currency = str(currency or "EUR").strip().upper()
    if not name:
        raise ValueError("La cuenta debe tener un nombre.")
    with _connect(db_path) as conn:
        ensure_schema(conn)
        cursor = conn.execute(
            """
            INSERT INTO economic_accounts(name, bank_name, iban, currency)
            VALUES (?, ?, NULLIF(?, ''), ?)
            """,
            (name, bank_name, iban, currency),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_or_create_account(
    name: str, *, db_path: str | Path = DEFAULT_DB_PATH
) -> int:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Debes indicar la cuenta.")
    with _connect(db_path) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT id FROM economic_accounts
            WHERE active = 1 AND UPPER(TRIM(name)) = UPPER(TRIM(?))
            """,
            (name,),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = conn.execute(
            "INSERT INTO economic_accounts(name) VALUES (?)",
            (name,),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_accounts(
    *, active_only: bool = True, db_path: str | Path = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM economic_accounts
            WHERE (? = 0 OR active = 1)
            ORDER BY name, id
            """,
            (1 if active_only else 0,),
        ).fetchall()
        return [dict(row) for row in rows]


def register_internal_transfer(
    *,
    transfer_date: str,
    source_account_id: int,
    destination_account_id: int,
    amount: Any,
    concept: str = "Traspaso entre cuentas",
    reference: str = "",
    created_by: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    source_account_id = int(source_account_id)
    destination_account_id = int(destination_account_id)
    if source_account_id == destination_account_id:
        raise ValueError("Las cuentas de origen y destino deben ser distintas.")
    amount_centimos = _money_to_centimos(amount)
    if amount_centimos <= 0:
        raise ValueError("El importe del traspaso debe ser mayor que cero.")
    transfer_date = str(transfer_date or "").strip()
    concept = str(concept or "").strip() or "Traspaso entre cuentas"
    reference = str(reference or "").strip()

    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        accounts = conn.execute(
            """
            SELECT id, name, currency
            FROM economic_accounts
            WHERE id IN (?, ?) AND active = 1
            """,
            (source_account_id, destination_account_id),
        ).fetchall()
        by_id = {int(row["id"]): row for row in accounts}
        if source_account_id not in by_id or destination_account_id not in by_id:
            raise ValueError("La cuenta de origen o destino no existe o está inactiva.")
        source = by_id[source_account_id]
        destination = by_id[destination_account_id]
        if source["currency"] != destination["currency"]:
            raise ValueError("Las dos cuentas deben utilizar la misma moneda.")

        cursor = conn.execute(
            """
            INSERT INTO economic_internal_transfers(
                transfer_date, source_account_id, destination_account_id,
                amount_centimos, currency, concept, reference, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transfer_date,
                source_account_id,
                destination_account_id,
                amount_centimos,
                source["currency"],
                concept,
                reference,
                str(created_by or "").strip(),
            ),
        )
        transfer_id = int(cursor.lastrowid)

        def insert_leg(
            *, account_id: int, account_name: str, amount_euros: Decimal, leg: str
        ) -> int:
            leg_cursor = conn.execute(
                """
                INSERT INTO eco_movimientos_importados(
                    origen, fecha_operacion, concepto, importe, referencia,
                    cuenta, tipo_movimiento, estado_conciliacion,
                    observaciones, activo, account_id,
                    internal_transfer_id, transfer_leg
                )
                VALUES (
                    'TRASPASO_INTERNO', ?, ?, ?, ?, ?,
                    ?, 'CONCILIADO', ?, 1, ?, ?, ?
                )
                """,
                (
                    transfer_date,
                    concept,
                    float(amount_euros),
                    reference,
                    account_name,
                    f"TRASPASO_{leg}",
                    f"Traspaso interno #{transfer_id}; no computa como ingreso ni gasto",
                    account_id,
                    transfer_id,
                    leg,
                ),
            )
            return int(leg_cursor.lastrowid)

        euros = Decimal(amount_centimos) / Decimal("100")
        outgoing_id = insert_leg(
            account_id=source_account_id,
            account_name=str(source["name"]),
            amount_euros=-euros,
            leg="SALIDA",
        )
        incoming_id = insert_leg(
            account_id=destination_account_id,
            account_name=str(destination["name"]),
            amount_euros=euros,
            leg="ENTRADA",
        )
        conn.execute(
            """
            UPDATE economic_internal_transfers
            SET outgoing_movement_id = ?, incoming_movement_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (outgoing_id, incoming_id, transfer_id),
        )
        for movement_id, title in (
            (outgoing_id, "SALIDA DE TRASPASO"),
            (incoming_id, "ENTRADA DE TRASPASO"),
        ):
            conn.execute(
                """
                INSERT INTO eco_eventos(
                    entidad, entidad_id, tipo_evento, titulo, descripcion,
                    estado_nuevo, usuario
                )
                VALUES ('ECO_MOVIMIENTOS_IMPORTADOS', ?, 'TRASPASO',
                        ?, ?, 'CONCILIADO', ?)
                """,
                (
                    movement_id,
                    title,
                    f"Traspaso interno #{transfer_id}",
                    str(created_by or "").strip(),
                ),
            )
        conn.commit()

    return get_internal_transfer(transfer_id, db_path=db_path)


def get_internal_transfer(
    transfer_id: int, *, db_path: str | Path = DEFAULT_DB_PATH
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT t.*, src.name AS source_account_name,
                   dst.name AS destination_account_name
            FROM economic_internal_transfers t
            JOIN economic_accounts src ON src.id = t.source_account_id
            JOIN economic_accounts dst ON dst.id = t.destination_account_id
            WHERE t.id = ?
            """,
            (int(transfer_id),),
        ).fetchone()
        if not row:
            raise ValueError("No existe el traspaso.")
        return dict(row)

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("database/quesada.db")

VALID_GROUP_TYPES = {
    "CASH_RECEIPT",
    "BANK_TRANSFER",
    "CARD_SETTLEMENT",
    "STRIPE_SETTLEMENT",
    "MIXED_REVIEW",
}

VALID_GROUP_STATUSES = {
    "DRAFT",
    "BALANCED",
    "UNBALANCED",
    "REVIEWED",
    "IGNORED",
}

VALID_SOURCE_TYPES = {
    "PHYSICAL_RECEIPT",
    "COBRO",
    "CASHMATIC_MOVEMENT",
    "BANK_MOVEMENT",
    "MANUAL_ADJUSTMENT",
}

VALID_ROLES = {
    "EXPECTED",
    "ACTUAL",
}


@dataclass(frozen=True)
class ReconciliationGroup:
    id: int
    group_type: str
    status: str
    title: str
    description: str
    expected_amount_centimos: int
    actual_amount_centimos: int
    difference_centimos: int
    group_date: str
    reviewed_by_user_id: int | None
    reviewed_at: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReconciliationGroupItem:
    id: int
    group_id: int
    source_type: str
    source_id: int | None
    role: str
    amount_centimos: int
    label: str
    notes: str
    created_at: str


@dataclass(frozen=True)
class ReconciliationGroupDetail:
    group: ReconciliationGroup
    items: list[ReconciliationGroupItem]


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cents_to_eur(value: int | None) -> float:
    return round((int(value or 0) / 100), 2)


def _row_to_group(row: sqlite3.Row) -> ReconciliationGroup:
    return ReconciliationGroup(
        id=int(row["id"]),
        group_type=str(row["group_type"] or ""),
        status=str(row["status"] or ""),
        title=str(row["title"] or ""),
        description=str(row["description"] or ""),
        expected_amount_centimos=int(row["expected_amount_centimos"] or 0),
        actual_amount_centimos=int(row["actual_amount_centimos"] or 0),
        difference_centimos=int(row["difference_centimos"] or 0),
        group_date=str(row["group_date"] or ""),
        reviewed_by_user_id=(
            int(row["reviewed_by_user_id"])
            if row["reviewed_by_user_id"] is not None
            else None
        ),
        reviewed_at=str(row["reviewed_at"] or ""),
        notes=str(row["notes"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def _row_to_item(row: sqlite3.Row) -> ReconciliationGroupItem:
    return ReconciliationGroupItem(
        id=int(row["id"]),
        group_id=int(row["group_id"]),
        source_type=str(row["source_type"] or ""),
        source_id=int(row["source_id"]) if row["source_id"] is not None else None,
        role=str(row["role"] or ""),
        amount_centimos=int(row["amount_centimos"] or 0),
        label=str(row["label"] or ""),
        notes=str(row["notes"] or ""),
        created_at=str(row["created_at"] or ""),
    )


def _validate_group_type(group_type: str) -> str:
    value = str(group_type or "").strip().upper()
    if value not in VALID_GROUP_TYPES:
        raise ValueError(f"group_type inválido: {group_type!r}. Válidos: {sorted(VALID_GROUP_TYPES)}")
    return value


def _validate_source_type(source_type: str) -> str:
    value = str(source_type or "").strip().upper()
    if value not in VALID_SOURCE_TYPES:
        raise ValueError(f"source_type inválido: {source_type!r}. Válidos: {sorted(VALID_SOURCE_TYPES)}")
    return value


def _validate_role(role: str) -> str:
    value = str(role or "").strip().upper()
    if value not in VALID_ROLES:
        raise ValueError(f"role inválido: {role!r}. Válidos: {sorted(VALID_ROLES)}")
    return value


def ensure_manual_reconciliation_schema(conn: sqlite3.Connection) -> None:
    migration = Path("database/migrations/20260707_create_manual_reconciliation_groups.sql")
    if migration.exists():
        conn.executescript(migration.read_text(encoding="utf-8"))


def create_reconciliation_group(
    *,
    group_type: str,
    title: str = "",
    description: str = "",
    group_date: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    group_type = _validate_group_type(group_type)

    with connect(db_path) as conn:
        ensure_manual_reconciliation_schema(conn)
        conn.execute(
            """
            INSERT INTO economic_reconciliation_groups (
                group_type,
                status,
                title,
                description,
                group_date,
                notes
            )
            VALUES (?, 'DRAFT', ?, ?, ?, ?)
            """,
            (
                group_type,
                str(title or "").strip(),
                str(description or "").strip(),
                str(group_date or "").strip(),
                str(notes or "").strip(),
            ),
        )
        group_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        conn.commit()
        return group_id


def get_reconciliation_group(
    group_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ReconciliationGroup | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM economic_reconciliation_groups
            WHERE id = ?
            LIMIT 1
            """,
            (int(group_id),),
        ).fetchone()

    return _row_to_group(row) if row else None


def list_reconciliation_groups(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    status: str | None = None,
    group_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ReconciliationGroup]:
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(str(status).strip().upper())

    if group_type:
        clauses.append("group_type = ?")
        params.append(str(group_type).strip().upper())

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    params.extend([max(1, int(limit or 100)), max(0, int(offset or 0))])

    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM economic_reconciliation_groups
            {where}
            ORDER BY COALESCE(group_date, '') DESC, id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()

    return [_row_to_group(row) for row in rows]


def add_reconciliation_group_item(
    *,
    group_id: int,
    source_type: str,
    role: str,
    amount_centimos: int,
    source_id: int | None = None,
    label: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    source_type = _validate_source_type(source_type)
    role = _validate_role(role)

    with connect(db_path) as conn:
        ensure_manual_reconciliation_schema(conn)

        group = conn.execute(
            "SELECT id FROM economic_reconciliation_groups WHERE id = ? LIMIT 1",
            (int(group_id),),
        ).fetchone()
        if not group:
            raise ValueError(f"No existe grupo de conciliación #{group_id}")

        conn.execute(
            """
            INSERT INTO economic_reconciliation_group_items (
                group_id,
                source_type,
                source_id,
                role,
                amount_centimos,
                label,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(group_id),
                source_type,
                int(source_id) if source_id is not None else None,
                role,
                int(amount_centimos or 0),
                str(label or "").strip(),
                str(notes or "").strip(),
            ),
        )
        item_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        _recalculate_group_in_conn(conn, int(group_id))
        conn.commit()
        return item_id


def remove_reconciliation_group_item(
    item_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT group_id
            FROM economic_reconciliation_group_items
            WHERE id = ?
            LIMIT 1
            """,
            (int(item_id),),
        ).fetchone()

        if not row:
            return False

        group_id = int(row["group_id"])

        conn.execute(
            "DELETE FROM economic_reconciliation_group_items WHERE id = ?",
            (int(item_id),),
        )
        _recalculate_group_in_conn(conn, group_id)
        conn.commit()
        return True


def _recalculate_group_in_conn(conn: sqlite3.Connection, group_id: int) -> ReconciliationGroup:
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN role = 'EXPECTED' THEN amount_centimos ELSE 0 END), 0) AS expected_amount_centimos,
            COALESCE(SUM(CASE WHEN role = 'ACTUAL' THEN amount_centimos ELSE 0 END), 0) AS actual_amount_centimos
        FROM economic_reconciliation_group_items
        WHERE group_id = ?
        """,
        (int(group_id),),
    ).fetchone()

    expected = int(totals["expected_amount_centimos"] or 0)
    actual = int(totals["actual_amount_centimos"] or 0)
    difference = actual - expected

    if expected == 0 and actual == 0:
        status = "DRAFT"
    elif difference == 0:
        status = "BALANCED"
    else:
        status = "UNBALANCED"

    conn.execute(
        """
        UPDATE economic_reconciliation_groups
        SET expected_amount_centimos = ?,
            actual_amount_centimos = ?,
            difference_centimos = ?,
            status = CASE
                WHEN status IN ('REVIEWED', 'IGNORED') THEN status
                ELSE ?
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (expected, actual, difference, status, int(group_id)),
    )

    row = conn.execute(
        """
        SELECT *
        FROM economic_reconciliation_groups
        WHERE id = ?
        LIMIT 1
        """,
        (int(group_id),),
    ).fetchone()

    if not row:
        raise ValueError(f"No existe grupo de conciliación #{group_id}")

    return _row_to_group(row)


def recalculate_reconciliation_group(
    group_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ReconciliationGroup:
    with connect(db_path) as conn:
        group = _recalculate_group_in_conn(conn, int(group_id))
        conn.commit()
        return group


def get_reconciliation_group_detail(
    group_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ReconciliationGroupDetail | None:
    with connect(db_path) as conn:
        group_row = conn.execute(
            """
            SELECT *
            FROM economic_reconciliation_groups
            WHERE id = ?
            LIMIT 1
            """,
            (int(group_id),),
        ).fetchone()

        if not group_row:
            return None

        item_rows = conn.execute(
            """
            SELECT *
            FROM economic_reconciliation_group_items
            WHERE group_id = ?
            ORDER BY role, id
            """,
            (int(group_id),),
        ).fetchall()

    return ReconciliationGroupDetail(
        group=_row_to_group(group_row),
        items=[_row_to_item(row) for row in item_rows],
    )


def mark_reconciliation_group_reviewed(
    group_id: int,
    *,
    reviewed_by_user_id: int | None = None,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM economic_reconciliation_groups WHERE id = ? LIMIT 1",
            (int(group_id),),
        ).fetchone()
        if not existing:
            return False

        conn.execute(
            """
            UPDATE economic_reconciliation_groups
            SET status = 'REVIEWED',
                reviewed_by_user_id = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                notes = CASE
                    WHEN ? = '' THEN notes
                    WHEN notes IS NULL OR notes = '' THEN ?
                    ELSE notes || char(10) || ?
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(reviewed_by_user_id) if reviewed_by_user_id is not None else None,
                str(notes or "").strip(),
                str(notes or "").strip(),
                str(notes or "").strip(),
                int(group_id),
            ),
        )
        conn.commit()
        return True


def add_bank_movement_to_group(
    *,
    group_id: int,
    bank_movement_id: int,
    role: str = "ACTUAL",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """
    Añade un movimiento bancario real al grupo.

    No crea cobros.
    No crea facturas.
    No vincula automáticamente cliente/expediente.
    Solo copia importe/concepto al grupo de conciliación manual.
    """
    role = _validate_role(role)

    with connect(db_path) as conn:
        movement = conn.execute(
            """
            SELECT
                id,
                bank_name,
                operation_date,
                concept,
                amount_centimos,
                movement_type,
                movement_status
            FROM bank_movements
            WHERE id = ?
            LIMIT 1
            """,
            (int(bank_movement_id),),
        ).fetchone()

    if not movement:
        raise ValueError(f"No existe bank_movement #{bank_movement_id}")

    amount = int(movement["amount_centimos"] or 0)
    label = (
        f'{movement["bank_name"] or "BANK"} '
        f'{movement["operation_date"] or ""} '
        f'{movement["movement_type"] or ""} '
        f'{amount / 100:.2f} EUR | '
        f'{str(movement["concept"] or "")[:120]}'
    ).strip()

    return add_reconciliation_group_item(
        group_id=group_id,
        source_type="BANK_MOVEMENT",
        source_id=int(bank_movement_id),
        role=role,
        amount_centimos=amount,
        label=label,
        notes=notes,
        db_path=db_path,
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _sql_optional_column(columns: set[str], column_name: str, alias: str) -> str:
    if column_name in columns:
        return f"{column_name} AS {alias}"
    return f"'' AS {alias}"


def _cashmatic_amount_expr_for_select(conn: sqlite3.Connection) -> str:
    columns = _table_columns(conn, "cashmatic_movements")

    if "net_centimos" in columns:
        return "COALESCE(net_centimos, 0)"

    if "candidate_net_centimos" in columns:
        return "COALESCE(candidate_net_centimos, 0)"

    if {"inserted_centimos", "dispensed_centimos"}.issubset(columns):
        return "(COALESCE(inserted_centimos, 0) - COALESCE(dispensed_centimos, 0))"

    if {"inserted_amount_centimos", "dispensed_amount_centimos"}.issubset(columns):
        return "(COALESCE(inserted_amount_centimos, 0) - COALESCE(dispensed_amount_centimos, 0))"

    if "inserted_centimos" in columns:
        return "COALESCE(inserted_centimos, 0)"

    if "requested_centimos" in columns:
        return "COALESCE(requested_centimos, 0)"

    if "amount_centimos" in columns:
        return "COALESCE(amount_centimos, 0)"

    raise RuntimeError(
        "No se encontró columna de importe compatible en cashmatic_movements. "
        f"Columnas disponibles: {sorted(columns)}"
    )


def add_cashmatic_movement_to_group(
    *,
    group_id: int,
    cashmatic_movement_id: int,
    role: str = "ACTUAL",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """
    Añade un movimiento Cashmatic real al grupo.

    Uso normal:
    - recibo físico/cobro interno = EXPECTED
    - movimiento Cashmatic = ACTUAL

    El SELECT es tolerante al schema real de staging.
    """
    role = _validate_role(role)

    with connect(db_path) as conn:
        columns = _table_columns(conn, "cashmatic_movements")
        amount_expr = _cashmatic_amount_expr_for_select(conn)

        start_time_expr = _sql_optional_column(columns, "start_time", "start_time")
        operation_expr = _sql_optional_column(columns, "operation", "operation")

        # En los CSV oficiales Cashmatic pueden existir como REASON/REFERENCE normalizados
        # con otros nombres según la evolución del staging.
        reason_expr = (
            _sql_optional_column(columns, "reason", "reason")
            if "reason" in columns
            else _sql_optional_column(columns, "raw_reason", "reason")
            if "raw_reason" in columns
            else _sql_optional_column(columns, "source_reason", "reason")
            if "source_reason" in columns
            else "'' AS reason"
        )
        reference_expr = (
            _sql_optional_column(columns, "reference", "reference")
            if "reference" in columns
            else _sql_optional_column(columns, "raw_reference", "reference")
            if "raw_reference" in columns
            else _sql_optional_column(columns, "source_reference", "reference")
            if "source_reference" in columns
            else "'' AS reference"
        )

        movement = conn.execute(
            f"""
            SELECT
                id,
                {start_time_expr},
                {operation_expr},
                movement_status,
                {reason_expr},
                {reference_expr},
                {amount_expr} AS amount_centimos
            FROM cashmatic_movements
            WHERE id = ?
            LIMIT 1
            """,
            (int(cashmatic_movement_id),),
        ).fetchone()

    if not movement:
        raise ValueError(f"No existe cashmatic_movement #{cashmatic_movement_id}")

    amount = int(movement["amount_centimos"] or 0)
    label_parts = [
        "CASHMATIC",
        str(movement["start_time"] or ""),
        str(movement["operation"] or ""),
        str(movement["movement_status"] or ""),
        f"{amount / 100:.2f} EUR",
    ]

    reason = str(movement["reason"] or "").strip()
    reference = str(movement["reference"] or "").strip()
    if reason:
        label_parts.append(reason[:80])
    if reference:
        label_parts.append(reference[:80])

    label = " | ".join(x for x in label_parts if x).strip()

    return add_reconciliation_group_item(
        group_id=group_id,
        source_type="CASHMATIC_MOVEMENT",
        source_id=int(cashmatic_movement_id),
        role=role,
        amount_centimos=amount,
        label=label,
        notes=notes,
        db_path=db_path,
    )


def group_detail_to_dict(detail: ReconciliationGroupDetail) -> dict[str, Any]:
    return {
        "group": asdict(detail.group),
        "items": [asdict(item) for item in detail.items],
        "amounts_eur": {
            "expected": cents_to_eur(detail.group.expected_amount_centimos),
            "actual": cents_to_eur(detail.group.actual_amount_centimos),
            "difference": cents_to_eur(detail.group.difference_centimos),
        },
    }

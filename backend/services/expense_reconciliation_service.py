from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    }


def _table_exists(
    conn: sqlite3.Connection,
    table_name: str,
) -> bool:
    return bool(
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (table_name,),
        ).fetchone()
    )


def ensure_schema(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with _connect(db_path) as conn:
        if not _table_exists(
            conn,
            "bank_movements",
        ):
            raise RuntimeError(
                "No existe la tabla bank_movements."
            )

        if not _table_exists(
            conn,
            "eco_gastos",
        ):
            raise RuntimeError(
                "No existe la tabla eco_gastos."
            )

        movement_columns = _columns(
            conn,
            "bank_movements",
        )

        migrations = {
            "linked_gasto_id": (
                "ALTER TABLE bank_movements "
                "ADD COLUMN linked_gasto_id INTEGER"
            ),
            "linked_amount_centimos": (
                "ALTER TABLE bank_movements "
                "ADD COLUMN linked_amount_centimos "
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "linked_target_type": (
                "ALTER TABLE bank_movements "
                "ADD COLUMN linked_target_type TEXT"
            ),
        }

        for column, sql in migrations.items():
            if column not in movement_columns:
                conn.execute(sql)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            economic_expense_reconciliation_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL DEFAULT 'bank',
                source_movement_id INTEGER NOT NULL,
                expense_id INTEGER NOT NULL,
                amount_centimos INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                CHECK (amount_centimos > 0),

                UNIQUE (
                    source_type,
                    source_movement_id,
                    expense_id
                )
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eera_source
            ON economic_expense_reconciliation_applications (
                source_type,
                source_movement_id
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eera_expense
            ON economic_expense_reconciliation_applications (
                expense_id
            )
            """
        )

        conn.commit()


def _movement_total_centimos(
    row: sqlite3.Row,
) -> int:
    return abs(
        int(row["amount_centimos"] or 0)
    )


def _expense_total_centimos(
    row: sqlite3.Row,
) -> int:
    total = int(
        row["total_centimos"] or 0
    )

    if total:
        return abs(total)

    return abs(
        int(
            round(
                float(row["importe"] or 0)
                * 100
            )
        )
    )


def get_movement_summary(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        movement = conn.execute(
            """
            SELECT *
            FROM bank_movements
            WHERE id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        if not movement:
            raise ValueError(
                "No existe el movimiento bancario."
            )

        amount_centimos = int(
            movement["amount_centimos"] or 0
        )

        if amount_centimos >= 0:
            raise ValueError(
                "Solo pueden conciliarse como gasto "
                "los movimientos bancarios negativos."
            )

        rows = conn.execute(
            """
            SELECT
                a.*,
                g.fecha_gasto,
                g.concepto,
                g.numero_factura,
                g.supplier_name_snapshot,
                g.proveedor,
                g.total_centimos,
                g.importe,
                g.estado_conciliacion
            FROM economic_expense_reconciliation_applications a
            JOIN eco_gastos g
              ON g.id = a.expense_id
            WHERE a.source_type = 'bank'
              AND a.source_movement_id = ?
            ORDER BY a.created_at, a.id
            """,
            (int(movement_id),),
        ).fetchall()

        total = _movement_total_centimos(
            movement
        )
        applied = sum(
            int(row["amount_centimos"] or 0)
            for row in rows
        )
        pending = max(0, total - applied)

        if applied <= 0:
            status = "PENDIENTE"
        elif applied < total:
            status = "PARCIAL"
        elif applied == total:
            status = "CONCILIADO"
        else:
            status = "SOBRANTE_REVISION"

        return {
            "movement": dict(movement),
            "applications": [
                dict(row)
                for row in rows
            ],
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": pending,
            "status": status,
        }


def get_expense_summary(
    expense_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        expense = conn.execute(
            """
            SELECT *
            FROM eco_gastos
            WHERE id = ?
            """,
            (int(expense_id),),
        ).fetchone()

        if not expense:
            raise ValueError(
                "No existe el gasto."
            )

        rows = conn.execute(
            """
            SELECT
                a.*,
                b.bank_name,
                b.operation_date,
                b.concept AS movement_concept,
                b.amount_centimos
            FROM economic_expense_reconciliation_applications a
            JOIN bank_movements b
              ON b.id = a.source_movement_id
            WHERE a.source_type = 'bank'
              AND a.expense_id = ?
            ORDER BY a.created_at, a.id
            """,
            (int(expense_id),),
        ).fetchall()

        total = _expense_total_centimos(
            expense
        )
        applied = sum(
            int(row["amount_centimos"] or 0)
            for row in rows
        )
        pending = max(0, total - applied)

        if applied <= 0:
            status = "PENDIENTE"
        elif applied < total:
            status = "PARCIAL"
        elif applied == total:
            status = "CONCILIADO"
        else:
            status = "SOBRANTE_REVISION"

        return {
            "expense": dict(expense),
            "applications": [
                dict(row)
                for row in rows
            ],
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": pending,
            "status": status,
        }


def _sync_movement(
    conn: sqlite3.Connection,
    movement_id: int,
) -> None:
    movement = conn.execute(
        """
        SELECT *
        FROM bank_movements
        WHERE id = ?
        """,
        (int(movement_id),),
    ).fetchone()

    if not movement:
        return

    summary = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount_centimos), 0)
                AS applied_centimos,
            MIN(expense_id)
                AS first_expense_id
        FROM economic_expense_reconciliation_applications
        WHERE source_type = 'bank'
          AND source_movement_id = ?
        """,
        (int(movement_id),),
    ).fetchone()

    applied = int(
        summary["applied_centimos"] or 0
    )
    first_expense_id = (
        summary["first_expense_id"]
    )
    total = _movement_total_centimos(
        movement
    )

    if applied <= 0:
        review_status = (
            "PENDING_MANUAL_REVIEW"
        )
        linked_target_type = None
        linked_at_sql = "NULL"
    elif applied < total:
        review_status = "MANUALLY_LINKED"
        linked_target_type = "GASTO"
        linked_at_sql = "CURRENT_TIMESTAMP"
    else:
        review_status = "MANUALLY_LINKED"
        linked_target_type = "GASTO"
        linked_at_sql = "CURRENT_TIMESTAMP"

    conn.execute(
        f"""
        UPDATE bank_movements
        SET linked_gasto_id = ?,
            linked_amount_centimos = ?,
            linked_target_type = ?,
            review_status = ?,
            linked_at = {linked_at_sql},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            first_expense_id,
            applied,
            linked_target_type,
            review_status,
            int(movement_id),
        ),
    )


def _sync_expense(
    conn: sqlite3.Connection,
    expense_id: int,
) -> None:
    expense = conn.execute(
        """
        SELECT *
        FROM eco_gastos
        WHERE id = ?
        """,
        (int(expense_id),),
    ).fetchone()

    if not expense:
        return

    summary = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount_centimos), 0)
                AS applied_centimos,
            MIN(source_movement_id)
                AS first_movement_id
        FROM economic_expense_reconciliation_applications
        WHERE source_type = 'bank'
          AND expense_id = ?
        """,
        (int(expense_id),),
    ).fetchone()

    applied = int(
        summary["applied_centimos"] or 0
    )
    first_movement_id = (
        summary["first_movement_id"]
    )
    total = _expense_total_centimos(
        expense
    )

    if applied <= 0:
        status = "PENDIENTE"
        first_movement_id = None
    elif applied < total:
        status = "PARCIAL"
    elif applied == total:
        status = "CONCILIADO"
    else:
        status = "SOBRANTE_REVISION"

    conn.execute(
        """
        UPDATE eco_gastos
        SET estado_conciliacion = ?,
            bank_movement_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            first_movement_id,
            int(expense_id),
        ),
    )


def apply_expense_reconciliation(
    *,
    movement_id: int,
    expense_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    movement_id = int(movement_id)
    expense_id = int(expense_id)
    amount_centimos = int(
        amount_centimos or 0
    )
    notes = str(notes or "").strip()

    if amount_centimos <= 0:
        raise ValueError(
            "El importe aplicado debe ser mayor que cero."
        )

    with _connect(db_path) as conn:
        movement = conn.execute(
            """
            SELECT *
            FROM bank_movements
            WHERE id = ?
            """,
            (movement_id,),
        ).fetchone()

        if not movement:
            raise ValueError(
                "No existe el movimiento bancario."
            )

        if int(
            movement["amount_centimos"] or 0
        ) >= 0:
            raise ValueError(
                "El movimiento no es una salida bancaria."
            )

        if str(
            movement["review_status"] or ""
        ).upper() == "IGNORED":
            raise ValueError(
                "No se puede conciliar un movimiento ignorado."
            )

        if str(
            movement["movement_status"] or ""
        ).upper() == "QUARANTINE":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "en cuarentena."
            )

        expense = conn.execute(
            """
            SELECT *
            FROM eco_gastos
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (expense_id,),
        ).fetchone()

        if not expense:
            raise ValueError(
                "No existe el gasto activo seleccionado."
            )

        movement_total = (
            _movement_total_centimos(
                movement
            )
        )
        expense_total = (
            _expense_total_centimos(
                expense
            )
        )

        movement_applied = int(
            conn.execute(
                """
                SELECT
                    COALESCE(
                        SUM(amount_centimos),
                        0
                    )
                FROM economic_expense_reconciliation_applications
                WHERE source_type = 'bank'
                  AND source_movement_id = ?
                """,
                (movement_id,),
            ).fetchone()[0]
            or 0
        )

        expense_applied = int(
            conn.execute(
                """
                SELECT
                    COALESCE(
                        SUM(amount_centimos),
                        0
                    )
                FROM economic_expense_reconciliation_applications
                WHERE source_type = 'bank'
                  AND expense_id = ?
                """,
                (expense_id,),
            ).fetchone()[0]
            or 0
        )

        existing = conn.execute(
            """
            SELECT *
            FROM economic_expense_reconciliation_applications
            WHERE source_type = 'bank'
              AND source_movement_id = ?
              AND expense_id = ?
            """,
            (
                movement_id,
                expense_id,
            ),
        ).fetchone()

        existing_amount = (
            int(existing["amount_centimos"])
            if existing
            else 0
        )

        movement_pending = max(
            0,
            movement_total
            - movement_applied,
        )
        expense_pending = max(
            0,
            expense_total
            - expense_applied,
        )

        allowed = min(
            movement_pending,
            expense_pending,
        )

        if amount_centimos > allowed:
            raise ValueError(
                "El importe supera el pendiente disponible. "
                f"Máximo aplicable: {allowed / 100:.2f} €"
            )

        new_amount = (
            existing_amount
            + amount_centimos
        )

        if existing:
            conn.execute(
                """
                UPDATE economic_expense_reconciliation_applications
                SET amount_centimos = ?,
                    notes = CASE
                        WHEN ? = '' THEN notes
                        WHEN notes IS NULL
                          OR TRIM(notes) = ''
                            THEN ?
                        ELSE notes
                          || char(10)
                          || ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_amount,
                    notes,
                    notes,
                    notes,
                    int(existing["id"]),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO
                economic_expense_reconciliation_applications (
                    source_type,
                    source_movement_id,
                    expense_id,
                    amount_centimos,
                    notes
                )
                VALUES (
                    'bank',
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    movement_id,
                    expense_id,
                    amount_centimos,
                    notes,
                ),
            )

        _sync_movement(
            conn,
            movement_id,
        )
        _sync_expense(
            conn,
            expense_id,
        )

        conn.commit()

    return {
        "movement": get_movement_summary(
            movement_id,
            db_path=db_path,
        ),
        "expense": get_expense_summary(
            expense_id,
            db_path=db_path,
        ),
    }


def remove_expense_reconciliation(
    application_id: int,
    *,
    reason: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    application_id = int(application_id)
    reason = str(reason or "").strip()

    with _connect(db_path) as conn:
        application = conn.execute(
            """
            SELECT *
            FROM economic_expense_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        if not application:
            raise ValueError(
                "No existe la aplicación de conciliación."
            )

        movement_id = int(
            application["source_movement_id"]
        )
        expense_id = int(
            application["expense_id"]
        )

        if reason:
            movement_note = (
                "Aplicación de gasto retirada: "
                + reason
            )

            conn.execute(
                """
                UPDATE bank_movements
                SET link_notes = CASE
                    WHEN link_notes IS NULL
                      OR TRIM(link_notes) = ''
                        THEN ?
                    ELSE link_notes
                      || char(10)
                      || ?
                END,
                updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    movement_note,
                    movement_note,
                    movement_id,
                ),
            )

        conn.execute(
            """
            DELETE FROM
            economic_expense_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        )

        _sync_movement(
            conn,
            movement_id,
        )
        _sync_expense(
            conn,
            expense_id,
        )

        conn.commit()

    return {
        "movement": get_movement_summary(
            movement_id,
            db_path=db_path,
        ),
        "expense": get_expense_summary(
            expense_id,
            db_path=db_path,
        ),
    }


def list_reconcilable_expenses(
    *,
    search: str = "",
    limit: int = 500,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    search = str(search or "").strip()
    clauses = [
        "COALESCE(g.activo, 1) = 1",
    ]
    params: list[Any] = []

    if search:
        like = f"%{search}%"
        clauses.append(
            """
            (
                COALESCE(
                    g.supplier_name_snapshot,
                    g.proveedor,
                    ''
                ) LIKE ?
                OR COALESCE(g.concepto, '') LIKE ?
                OR COALESCE(
                    g.numero_factura,
                    ''
                ) LIKE ?
                OR CAST(g.id AS TEXT) LIKE ?
            )
            """
        )
        params.extend(
            [like, like, like, like]
        )

    where_sql = " AND ".join(clauses)
    params.append(max(1, int(limit)))

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                g.*,
                COALESCE(
                    NULLIF(
                        g.supplier_name_snapshot,
                        ''
                    ),
                    NULLIF(g.proveedor, ''),
                    'Sin proveedor'
                ) AS supplier_display_name,
                COALESCE(
                    (
                        SELECT SUM(
                            a.amount_centimos
                        )
                        FROM economic_expense_reconciliation_applications a
                        WHERE a.source_type = 'bank'
                          AND a.expense_id = g.id
                    ),
                    0
                ) AS applied_centimos,
                CASE
                    WHEN COALESCE(
                        g.total_centimos,
                        0
                    ) <> 0
                        THEN g.total_centimos
                    ELSE CAST(
                        ROUND(
                            COALESCE(g.importe, 0)
                            * 100
                        )
                        AS INTEGER
                    )
                END AS effective_total_centimos
            FROM eco_gastos g
            WHERE {where_sql}
            ORDER BY
                g.fecha_gasto DESC,
                g.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    result = []

    for row in rows:
        item = dict(row)

        total = abs(
            int(
                item.get(
                    "effective_total_centimos"
                )
                or 0
            )
        )
        applied = int(
            item.get("applied_centimos")
            or 0
        )
        pending = max(
            0,
            total - applied,
        )

        if pending <= 0:
            continue

        item["pending_centimos"] = pending
        result.append(item)

    return result

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")


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


def _status(
    total_centimos: int,
    applied_centimos: int,
) -> str:
    total = max(0, int(total_centimos or 0))
    applied = max(0, int(applied_centimos or 0))

    if applied <= 0:
        return "PENDIENTE"

    if applied < total:
        return "PARCIAL"

    if applied == total:
        return "CONCILIADA"

    return "EXCESO_REVISION"


def _sum_source_applications(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    movement_id: int,
) -> int:
    if not _table_exists(conn, table_name):
        return 0

    row = conn.execute(
        f"""
        SELECT COALESCE(
            SUM(amount_centimos),
            0
        ) AS applied_centimos
        FROM {table_name}
        WHERE LOWER(
            COALESCE(source_type, '')
        ) = 'bank'
          AND source_movement_id = ?
        """,
        (int(movement_id),),
    ).fetchone()

    return max(
        0,
        int(row["applied_centimos"] or 0),
    )


def _modern_movement_consumption(
    conn: sqlite3.Connection,
    movement_id: int,
    *,
    exclude_payroll_application_id: int | None = None,
) -> dict[str, int]:
    result = {
        "payments_centimos": 0,
        "expenses_centimos": 0,
        "payrolls_centimos": 0,
        "social_security_centimos": 0,
    }

    result["payments_centimos"] = (
        _sum_source_applications(
            conn,
            table_name=(
                "economic_reconciliation_applications"
            ),
            movement_id=movement_id,
        )
    )

    result["expenses_centimos"] = (
        _sum_source_applications(
            conn,
            table_name=(
                "economic_expense_reconciliation_applications"
            ),
            movement_id=movement_id,
        )
    )

    if _table_exists(
        conn,
        "labor_payroll_reconciliation_applications",
    ):
        params: list[Any] = [
            int(movement_id),
        ]
        exclusion_sql = ""

        if exclude_payroll_application_id is not None:
            exclusion_sql = " AND id <> ?"
            params.append(
                int(exclude_payroll_application_id)
            )

        row = conn.execute(
            f"""
            SELECT COALESCE(
                SUM(amount_centimos),
                0
            ) AS applied_centimos
            FROM labor_payroll_reconciliation_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND source_movement_id = ?
              {exclusion_sql}
            """,
            params,
        ).fetchone()

        result["payrolls_centimos"] = max(
            0,
            int(row["applied_centimos"] or 0),
        )

    result["social_security_centimos"] = (
        _sum_source_applications(
            conn,
            table_name=(
                "labor_social_security_"
                "reconciliation_applications"
            ),
            movement_id=movement_id,
        )
    )

    result["total_centimos"] = sum(
        result.values()
    )

    return result


def get_movement_snapshot(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
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

        raw_amount = int(
            movement["amount_centimos"] or 0
        )

        if raw_amount >= 0:
            raise ValueError(
                "La conciliación laboral solo admite "
                "movimientos bancarios negativos."
            )

        if str(
            movement["review_status"] or ""
        ).upper() == "IGNORED":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "ignorado."
            )

        if str(
            movement["movement_status"] or ""
        ).upper() == "QUARANTINE":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "en cuarentena."
            )

        total = abs(raw_amount)
        consumption = (
            _modern_movement_consumption(
                conn,
                int(movement_id),
            )
        )
        applied = int(
            consumption["total_centimos"]
        )
        pending = max(
            0,
            total - applied,
        )

        return {
            "movement": dict(movement),
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": pending,
            "status": _status(
                total,
                applied,
            ),
            "consumption": consumption,
        }


def get_payroll_snapshot(
    payroll_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        payroll = conn.execute(
            """
            SELECT
                p.*,
                w.worker_code,
                w.first_name,
                w.last_name_1,
                w.last_name_2,
                w.tax_id
            FROM worker_payrolls p
            JOIN workers w
              ON w.id = p.worker_id
            WHERE p.id = ?
              AND COALESCE(p.active, 1) = 1
            """,
            (int(payroll_id),),
        ).fetchone()

        if not payroll:
            raise ValueError(
                "No existe la nómina activa."
            )

        applications = conn.execute(
            """
            SELECT
                a.*,
                b.bank_name,
                b.operation_date,
                b.value_date,
                b.concept AS movement_concept,
                b.amount_centimos
                    AS movement_amount_centimos
            FROM labor_payroll_reconciliation_applications a
            JOIN bank_movements b
              ON b.id = a.source_movement_id
            WHERE LOWER(
                COALESCE(a.source_type, '')
            ) = 'bank'
              AND a.payroll_id = ?
            ORDER BY
                a.created_at,
                a.id
            """,
            (int(payroll_id),),
        ).fetchall()

        total = max(
            0,
            int(
                payroll[
                    "net_salary_centimos"
                ]
                or 0
            ),
        )
        applied = sum(
            max(
                0,
                int(
                    row["amount_centimos"]
                    or 0
                ),
            )
            for row in applications
        )
        pending = max(
            0,
            total - applied,
        )

        return {
            "payroll": dict(payroll),
            "applications": [
                dict(row)
                for row in applications
            ],
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": pending,
            "status": _status(
                total,
                applied,
            ),
        }


def list_payroll_candidates(
    *,
    search: str = "",
    limit: int = 500,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    search = str(search or "").strip()

    clauses = [
        "COALESCE(p.active, 1) = 1",
    ]
    params: list[Any] = []

    if search:
        like = f"%{search}%"
        clauses.append(
            """
            (
                COALESCE(w.worker_code, '') LIKE ?
                OR COALESCE(w.first_name, '') LIKE ?
                OR COALESCE(w.last_name_1, '') LIKE ?
                OR COALESCE(w.last_name_2, '') LIKE ?
                OR COALESCE(w.tax_id, '') LIKE ?
                OR (
                    printf(
                        '%02d/%04d',
                        p.period_month,
                        p.period_year
                    ) LIKE ?
                )
            )
            """
        )
        params.extend(
            [
                like,
                like,
                like,
                like,
                like,
                like,
            ]
        )

    where_sql = " AND ".join(clauses)
    params.append(
        max(1, int(limit))
    )

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                w.worker_code,
                w.first_name,
                w.last_name_1,
                w.last_name_2,
                w.tax_id,
                COALESCE(
                    (
                        SELECT SUM(
                            a.amount_centimos
                        )
                        FROM labor_payroll_reconciliation_applications a
                        WHERE LOWER(
                            COALESCE(
                                a.source_type,
                                ''
                            )
                        ) = 'bank'
                          AND a.payroll_id = p.id
                    ),
                    0
                ) AS applied_centimos
            FROM worker_payrolls p
            JOIN workers w
              ON w.id = p.worker_id
            WHERE {where_sql}
            ORDER BY
                p.period_year DESC,
                p.period_month DESC,
                w.last_name_1,
                w.last_name_2,
                w.first_name,
                p.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    result = []

    for row in rows:
        item = dict(row)
        total = max(
            0,
            int(
                item.get(
                    "net_salary_centimos"
                )
                or 0
            ),
        )
        applied = max(
            0,
            int(
                item.get(
                    "applied_centimos"
                )
                or 0
            ),
        )
        pending = max(
            0,
            total - applied,
        )

        if pending <= 0:
            continue

        item["pending_centimos"] = pending
        item["reconciliation_status"] = (
            _status(
                total,
                applied,
            )
        )
        result.append(item)

    return result


def apply_payroll_reconciliation(
    *,
    movement_id: int,
    payroll_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    movement_id = int(movement_id)
    payroll_id = int(payroll_id)
    amount_centimos = int(
        amount_centimos or 0
    )
    notes = str(notes or "").strip()

    if amount_centimos <= 0:
        raise ValueError(
            "El importe aplicado debe ser "
            "superior a cero."
        )

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

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

        raw_amount = int(
            movement["amount_centimos"] or 0
        )

        if raw_amount >= 0:
            raise ValueError(
                "El movimiento no es una salida "
                "bancaria."
            )

        if str(
            movement["review_status"] or ""
        ).upper() == "IGNORED":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "ignorado."
            )

        if str(
            movement["movement_status"] or ""
        ).upper() == "QUARANTINE":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "en cuarentena."
            )

        payroll = conn.execute(
            """
            SELECT *
            FROM worker_payrolls
            WHERE id = ?
              AND COALESCE(active, 1) = 1
            """,
            (payroll_id,),
        ).fetchone()

        if not payroll:
            raise ValueError(
                "No existe la nómina activa "
                "seleccionada."
            )

        existing = conn.execute(
            """
            SELECT *
            FROM labor_payroll_reconciliation_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND source_movement_id = ?
              AND payroll_id = ?
            """,
            (
                movement_id,
                payroll_id,
            ),
        ).fetchone()

        existing_id = (
            int(existing["id"])
            if existing
            else None
        )
        existing_amount = (
            int(
                existing["amount_centimos"]
                or 0
            )
            if existing
            else 0
        )

        movement_total = abs(raw_amount)
        consumption = (
            _modern_movement_consumption(
                conn,
                movement_id,
                exclude_payroll_application_id=(
                    existing_id
                ),
            )
        )
        movement_available = max(
            0,
            movement_total
            - int(
                consumption["total_centimos"]
            ),
        )

        payroll_total = max(
            0,
            int(
                payroll[
                    "net_salary_centimos"
                ]
                or 0
            ),
        )

        row = conn.execute(
            """
            SELECT COALESCE(
                SUM(amount_centimos),
                0
            ) AS applied_centimos
            FROM labor_payroll_reconciliation_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND payroll_id = ?
              AND (
                    ? IS NULL
                    OR id <> ?
                  )
            """,
            (
                payroll_id,
                existing_id,
                existing_id,
            ),
        ).fetchone()

        payroll_applied_without_current = max(
            0,
            int(
                row["applied_centimos"]
                or 0
            ),
        )
        payroll_available = max(
            0,
            payroll_total
            - payroll_applied_without_current,
        )

        maximum = min(
            movement_available,
            payroll_available,
        )

        if amount_centimos > maximum:
            raise ValueError(
                "El importe supera el máximo "
                "disponible. "
                f"Máximo aplicable: "
                f"{maximum / 100:.2f} €."
            )

        if existing:
            conn.execute(
                """
                UPDATE labor_payroll_reconciliation_applications
                SET amount_centimos = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    amount_centimos,
                    notes,
                    existing_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO
                labor_payroll_reconciliation_applications (
                    source_type,
                    source_movement_id,
                    payroll_id,
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
                    payroll_id,
                    amount_centimos,
                    notes,
                ),
            )

        conn.commit()

    return {
        "movement": get_movement_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "payroll": get_payroll_snapshot(
            payroll_id,
            db_path=db_path,
        ),
    }


def remove_payroll_reconciliation(
    application_id: int,
    *,
    reason: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    application_id = int(application_id)
    reason = str(reason or "").strip()

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        application = conn.execute(
            """
            SELECT *
            FROM labor_payroll_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        if not application:
            raise ValueError(
                "No existe la aplicación de "
                "conciliación laboral."
            )

        movement_id = int(
            application["source_movement_id"]
        )
        payroll_id = int(
            application["payroll_id"]
        )

        if reason:
            note = (
                "Conciliación de nómina retirada: "
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
                    note,
                    note,
                    movement_id,
                ),
            )

        conn.execute(
            """
            DELETE FROM
            labor_payroll_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        )

        conn.commit()

    return {
        "movement": get_movement_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "payroll": get_payroll_snapshot(
            payroll_id,
            db_path=db_path,
        ),
    }


def get_social_security_period_snapshot(
    social_security_period_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        period = conn.execute(
            """
            SELECT
                p.*,
                g.concepto AS employer_expense_concept,
                g.total_centimos
                    AS employer_expense_total_centimos
            FROM labor_social_security_periods p
            LEFT JOIN eco_gastos g
              ON g.id = p.employer_expense_id
            WHERE p.id = ?
              AND COALESCE(p.active, 1) = 1
            """,
            (int(social_security_period_id),),
        ).fetchone()

        if not period:
            raise ValueError(
                "No existe el periodo activo de "
                "Seguridad Social."
            )

        applications = conn.execute(
            """
            SELECT
                a.*,
                b.bank_name,
                b.operation_date,
                b.value_date,
                b.concept AS movement_concept,
                b.amount_centimos
                    AS movement_amount_centimos
            FROM
                labor_social_security_reconciliation_applications a
            JOIN bank_movements b
              ON b.id = a.source_movement_id
            WHERE LOWER(
                COALESCE(a.source_type, '')
            ) = 'bank'
              AND a.social_security_period_id = ?
            ORDER BY
                a.created_at,
                a.id
            """,
            (int(social_security_period_id),),
        ).fetchall()

        total = max(
            0,
            int(
                period["total_payable_centimos"]
                or 0
            ),
        )
        applied = sum(
            max(
                0,
                int(
                    row["amount_centimos"]
                    or 0
                ),
            )
            for row in applications
        )
        pending = max(
            0,
            total - applied,
        )

        return {
            "period": dict(period),
            "applications": [
                dict(row)
                for row in applications
            ],
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": pending,
            "status": _status(
                total,
                applied,
            ),
        }


def list_social_security_candidates(
    *,
    search: str = "",
    limit: int = 120,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    search = str(search or "").strip()

    clauses = [
        "COALESCE(p.active, 1) = 1",
        "COALESCE(p.total_payable_centimos, 0) > 0",
    ]
    params: list[Any] = []

    if search:
        like = f"%{search}%"
        clauses.append(
            """
            (
                printf(
                    '%02d/%04d',
                    p.period_month,
                    p.period_year
                ) LIKE ?
                OR COALESCE(p.notes, '') LIKE ?
                OR COALESCE(p.document_path, '') LIKE ?
            )
            """
        )
        params.extend(
            [
                like,
                like,
                like,
            ]
        )

    where_sql = " AND ".join(clauses)
    params.append(
        max(1, int(limit))
    )

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                COALESCE(
                    (
                        SELECT SUM(
                            a.amount_centimos
                        )
                        FROM
                            labor_social_security_reconciliation_applications a
                        WHERE LOWER(
                            COALESCE(
                                a.source_type,
                                ''
                            )
                        ) = 'bank'
                          AND
                            a.social_security_period_id = p.id
                    ),
                    0
                ) AS applied_centimos
            FROM labor_social_security_periods p
            WHERE {where_sql}
            ORDER BY
                p.period_year DESC,
                p.period_month DESC,
                p.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    result = []

    for row in rows:
        item = dict(row)

        total = max(
            0,
            int(
                item.get(
                    "total_payable_centimos"
                )
                or 0
            ),
        )
        applied = max(
            0,
            int(
                item.get(
                    "applied_centimos"
                )
                or 0
            ),
        )
        pending = max(
            0,
            total - applied,
        )

        if pending <= 0:
            continue

        item["pending_centimos"] = pending
        item["reconciliation_status"] = (
            _status(
                total,
                applied,
            )
        )
        result.append(item)

    return result


def apply_social_security_reconciliation(
    *,
    movement_id: int,
    social_security_period_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    movement_id = int(movement_id)
    social_security_period_id = int(
        social_security_period_id
    )
    amount_centimos = int(
        amount_centimos or 0
    )
    notes = str(notes or "").strip()

    if amount_centimos <= 0:
        raise ValueError(
            "El importe aplicado debe ser "
            "superior a cero."
        )

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

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

        raw_amount = int(
            movement["amount_centimos"] or 0
        )

        if raw_amount >= 0:
            raise ValueError(
                "El movimiento no es una salida "
                "bancaria."
            )

        if str(
            movement["review_status"] or ""
        ).upper() == "IGNORED":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "ignorado."
            )

        if str(
            movement["movement_status"] or ""
        ).upper() == "QUARANTINE":
            raise ValueError(
                "No se puede conciliar un movimiento "
                "en cuarentena."
            )

        period = conn.execute(
            """
            SELECT *
            FROM labor_social_security_periods
            WHERE id = ?
              AND COALESCE(active, 1) = 1
            """,
            (social_security_period_id,),
        ).fetchone()

        if not period:
            raise ValueError(
                "No existe el periodo activo de "
                "Seguridad Social."
            )

        existing = conn.execute(
            """
            SELECT *
            FROM
                labor_social_security_reconciliation_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND source_movement_id = ?
              AND social_security_period_id = ?
            """,
            (
                movement_id,
                social_security_period_id,
            ),
        ).fetchone()

        existing_id = (
            int(existing["id"])
            if existing
            else None
        )

        consumption = (
            _modern_movement_consumption(
                conn,
                movement_id,
            )
        )

        current_tgss_amount = (
            int(
                existing["amount_centimos"]
                or 0
            )
            if existing
            else 0
        )

        movement_consumed_without_current = max(
            0,
            int(
                consumption["total_centimos"]
            )
            - current_tgss_amount,
        )

        movement_total = abs(raw_amount)
        movement_available = max(
            0,
            movement_total
            - movement_consumed_without_current,
        )

        period_total = max(
            0,
            int(
                period["total_payable_centimos"]
                or 0
            ),
        )

        row = conn.execute(
            """
            SELECT COALESCE(
                SUM(amount_centimos),
                0
            ) AS applied_centimos
            FROM
                labor_social_security_reconciliation_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND social_security_period_id = ?
              AND (
                    ? IS NULL
                    OR id <> ?
                  )
            """,
            (
                social_security_period_id,
                existing_id,
                existing_id,
            ),
        ).fetchone()

        period_applied_without_current = max(
            0,
            int(
                row["applied_centimos"]
                or 0
            ),
        )

        period_available = max(
            0,
            period_total
            - period_applied_without_current,
        )

        maximum = min(
            movement_available,
            period_available,
        )

        if amount_centimos > maximum:
            raise ValueError(
                "El importe supera el máximo "
                "disponible. "
                f"Máximo aplicable: "
                f"{maximum / 100:.2f} €."
            )

        if existing:
            conn.execute(
                """
                UPDATE
                    labor_social_security_reconciliation_applications
                SET amount_centimos = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    amount_centimos,
                    notes,
                    existing_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO
                    labor_social_security_reconciliation_applications (
                        source_type,
                        source_movement_id,
                        social_security_period_id,
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
                    social_security_period_id,
                    amount_centimos,
                    notes,
                ),
            )

        conn.commit()

    return {
        "movement": get_movement_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "social_security": (
            get_social_security_period_snapshot(
                social_security_period_id,
                db_path=db_path,
            )
        ),
    }


def remove_social_security_reconciliation(
    application_id: int,
    *,
    reason: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    application_id = int(application_id)
    reason = str(reason or "").strip()

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        application = conn.execute(
            """
            SELECT *
            FROM
                labor_social_security_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        if not application:
            raise ValueError(
                "No existe la aplicación de "
                "conciliación TGSS."
            )

        movement_id = int(
            application["source_movement_id"]
        )
        social_security_period_id = int(
            application[
                "social_security_period_id"
            ]
        )

        if reason:
            note = (
                "Conciliación TGSS retirada: "
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
                    note,
                    note,
                    movement_id,
                ),
            )

        conn.execute(
            """
            DELETE FROM
                labor_social_security_reconciliation_applications
            WHERE id = ?
            """,
            (application_id,),
        )

        conn.commit()

    return {
        "movement": get_movement_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "social_security": (
            get_social_security_period_snapshot(
                social_security_period_id,
                db_path=db_path,
            )
        ),
    }


def list_movement_labor_applications(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, list[dict[str, Any]]]:
    movement_id = int(movement_id)

    with _connect(db_path) as conn:
        movement = conn.execute(
            """
            SELECT id
            FROM bank_movements
            WHERE id = ?
            """,
            (movement_id,),
        ).fetchone()

        if not movement:
            raise ValueError(
                "No existe el movimiento bancario."
            )

        payroll_applications = conn.execute(
            """
            SELECT
                a.id,
                a.source_type,
                a.source_movement_id,
                a.payroll_id,
                a.amount_centimos,
                a.notes,
                a.created_at,
                a.updated_at,
                p.period_year,
                p.period_month,
                p.net_salary_centimos,
                w.id AS worker_id,
                w.worker_code,
                w.first_name,
                w.last_name_1,
                w.last_name_2,
                w.tax_id
            FROM
                labor_payroll_reconciliation_applications a
            JOIN worker_payrolls p
              ON p.id = a.payroll_id
            JOIN workers w
              ON w.id = p.worker_id
            WHERE LOWER(
                COALESCE(a.source_type, '')
            ) = 'bank'
              AND a.source_movement_id = ?
            ORDER BY
                a.created_at,
                a.id
            """,
            (movement_id,),
        ).fetchall()

        social_security_applications = conn.execute(
            """
            SELECT
                a.id,
                a.source_type,
                a.source_movement_id,
                a.social_security_period_id,
                a.amount_centimos,
                a.notes,
                a.created_at,
                a.updated_at,
                p.period_year,
                p.period_month,
                p.employee_amount_centimos,
                p.employer_amount_centimos,
                p.other_amount_centimos,
                p.total_payable_centimos,
                p.status AS period_status
            FROM
                labor_social_security_reconciliation_applications a
            JOIN labor_social_security_periods p
              ON p.id = a.social_security_period_id
            WHERE LOWER(
                COALESCE(a.source_type, '')
            ) = 'bank'
              AND a.source_movement_id = ?
            ORDER BY
                a.created_at,
                a.id
            """,
            (movement_id,),
        ).fetchall()

    return {
        "payrolls": [
            dict(row)
            for row in payroll_applications
        ],
        "social_security": [
            dict(row)
            for row in social_security_applications
        ],
    }

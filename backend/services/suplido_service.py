from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

STATUS_PENDING = "PENDIENTE_RECUPERAR"
STATUS_PARTIAL = "PARCIALMENTE_RECUPERADO"
STATUS_RECOVERED = "RECUPERADO"
STATUS_CANCELLED = "ANULADO"


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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS economic_suplidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_date TEXT NOT NULL,
                amount_centimos INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                expedient_id INTEGER,
                concept TEXT NOT NULL,
                provider_name TEXT,
                document_path TEXT,
                status TEXT NOT NULL
                    DEFAULT 'PENDIENTE_RECUPERAR',
                recovered_amount_centimos INTEGER NOT NULL
                    DEFAULT 0,
                notes TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                CHECK (amount_centimos > 0),
                CHECK (recovered_amount_centimos >= 0),
                CHECK (
                    status IN (
                        'PENDIENTE_RECUPERAR',
                        'PARCIALMENTE_RECUPERADO',
                        'RECUPERADO',
                        'ANULADO'
                    )
                )
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_economic_suplidos_client
            ON economic_suplidos (
                client_id,
                status,
                active
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_economic_suplidos_expedient
            ON economic_suplidos (
                expedient_id,
                active
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            economic_suplido_payment_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL DEFAULT 'bank',
                source_movement_id INTEGER NOT NULL,
                suplido_id INTEGER NOT NULL,
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
                    suplido_id
                )
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_espa_source
            ON economic_suplido_payment_applications (
                source_type,
                source_movement_id
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_espa_suplido
            ON economic_suplido_payment_applications (
                suplido_id
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            economic_suplido_recovery_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                suplido_id INTEGER NOT NULL,
                amount_centimos INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                CHECK (amount_centimos > 0),

                UNIQUE (
                    source_type,
                    source_id,
                    suplido_id
                )
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_esra_source
            ON economic_suplido_recovery_applications (
                source_type,
                source_id
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_esra_suplido
            ON economic_suplido_recovery_applications (
                suplido_id
            )
            """
        )

        conn.commit()


def create_suplido(
    *,
    payment_date: str,
    amount_centimos: int,
    client_id: int,
    concept: str,
    expedient_id: int | None = None,
    provider_name: str = "",
    document_path: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    ensure_schema(db_path)

    payment_date = str(payment_date or "").strip()
    concept = str(concept or "").strip()
    amount_centimos = int(amount_centimos or 0)
    client_id = int(client_id)

    if not payment_date:
        raise ValueError(
            "La fecha de pago es obligatoria."
        )

    if amount_centimos <= 0:
        raise ValueError(
            "El importe del suplido debe ser mayor que cero."
        )

    if client_id <= 0:
        raise ValueError(
            "El cliente es obligatorio."
        )

    if not concept:
        raise ValueError(
            "El concepto del suplido es obligatorio."
        )

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO economic_suplidos (
                payment_date,
                amount_centimos,
                client_id,
                expedient_id,
                concept,
                provider_name,
                document_path,
                status,
                recovered_amount_centimos,
                notes,
                active
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                'PENDIENTE_RECUPERAR',
                0,
                ?,
                1
            )
            """,
            (
                payment_date,
                amount_centimos,
                client_id,
                (
                    int(expedient_id)
                    if expedient_id
                    else None
                ),
                concept,
                str(provider_name or "").strip(),
                str(document_path or "").strip(),
                str(notes or "").strip(),
            ),
        )

        suplido_id = int(cursor.lastrowid)
        conn.commit()

    return suplido_id


def get_suplido(
    suplido_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                s.*,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                e.numero_expediente,
                (
                    SELECT COALESCE(
                        SUM(a.amount_centimos),
                        0
                    )
                    FROM economic_suplido_payment_applications a
                    WHERE a.suplido_id = s.id
                ) AS paid_application_centimos,
                (
                    SELECT COALESCE(
                        SUM(r.amount_centimos),
                        0
                    )
                    FROM economic_suplido_recovery_applications r
                    WHERE r.suplido_id = s.id
                ) AS recovered_application_centimos
            FROM economic_suplidos s
            LEFT JOIN clientes c
              ON c.id = s.client_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE s.id = ?
            """,
            (int(suplido_id),),
        ).fetchone()

    if not row:
        return None

    data = dict(row)
    total = int(data["amount_centimos"] or 0)
    recovered = int(
        data["recovered_application_centimos"]
        or 0
    )

    data["pending_recovery_centimos"] = max(
        0,
        total - recovered,
    )

    return data


def list_suplidos(
    *,
    active_only: bool = True,
    client_id: int | None = None,
    status: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    conditions = ["1 = 1"]
    params: list[Any] = []

    if active_only:
        conditions.append(
            "COALESCE(s.active, 1) = 1"
        )

    if client_id:
        conditions.append(
            "s.client_id = ?"
        )
        params.append(int(client_id))

    if status:
        conditions.append(
            "UPPER(s.status) = ?"
        )
        params.append(
            str(status).strip().upper()
        )

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                s.*,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                e.numero_expediente,
                (
                    SELECT COALESCE(
                        SUM(a.amount_centimos),
                        0
                    )
                    FROM economic_suplido_payment_applications a
                    WHERE a.suplido_id = s.id
                ) AS paid_application_centimos,
                (
                    SELECT COALESCE(
                        SUM(r.amount_centimos),
                        0
                    )
                    FROM economic_suplido_recovery_applications r
                    WHERE r.suplido_id = s.id
                ) AS recovered_application_centimos
            FROM economic_suplidos s
            LEFT JOIN clientes c
              ON c.id = s.client_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE {' AND '.join(conditions)}
            ORDER BY
                s.payment_date DESC,
                s.id DESC
            """,
            params,
        ).fetchall()

    result = []

    for row in rows:
        data = dict(row)
        total = int(
            data["amount_centimos"] or 0
        )
        recovered = int(
            data["recovered_application_centimos"]
            or 0
        )
        data["pending_recovery_centimos"] = max(
            0,
            total - recovered,
        )
        result.append(data)

    return result


def _sum_movement_applications(
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


def _movement_consumption(
    conn: sqlite3.Connection,
    movement_id: int,
) -> dict[str, int]:
    tables = {
        "payments_centimos": (
            "economic_reconciliation_applications"
        ),
        "expenses_centimos": (
            "economic_expense_reconciliation_applications"
        ),
        "payrolls_centimos": (
            "labor_payroll_reconciliation_applications"
        ),
        "social_security_centimos": (
            "labor_social_security_"
            "reconciliation_applications"
        ),
        "suplidos_centimos": (
            "economic_suplido_payment_applications"
        ),
    }

    result = {
        key: _sum_movement_applications(
            conn,
            table_name=table_name,
            movement_id=movement_id,
        )
        for key, table_name in tables.items()
    }

    result["total_centimos"] = sum(
        result.values()
    )

    return result


def get_movement_payment_snapshot(
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
                "El movimiento no es una salida bancaria."
            )

        total_centimos = abs(amount_centimos)

        consumption = _movement_consumption(
            conn,
            int(movement_id),
        )

        applied_centimos = int(
            consumption["total_centimos"]
            or 0
        )

        pending_centimos = max(
            0,
            total_centimos - applied_centimos,
        )

        applications = conn.execute(
            """
            SELECT
                a.*,
                s.payment_date,
                s.amount_centimos
                    AS suplido_amount_centimos,
                s.concept,
                s.provider_name,
                s.status,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                e.numero_expediente
            FROM economic_suplido_payment_applications a
            JOIN economic_suplidos s
              ON s.id = a.suplido_id
            LEFT JOIN clientes c
              ON c.id = s.client_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE LOWER(
                COALESCE(a.source_type, '')
            ) = 'bank'
              AND a.source_movement_id = ?
            ORDER BY a.id
            """,
            (int(movement_id),),
        ).fetchall()

    return {
        "movement": dict(movement),
        "total_centimos": total_centimos,
        "applied_centimos": applied_centimos,
        "pending_centimos": pending_centimos,
        "consumption": consumption,
        "suplido_applications": [
            dict(row)
            for row in applications
        ],
    }


def apply_suplido_payment(
    *,
    movement_id: int,
    suplido_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    movement_id = int(movement_id)
    suplido_id = int(suplido_id)
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

        suplido = conn.execute(
            """
            SELECT *
            FROM economic_suplidos
            WHERE id = ?
              AND COALESCE(active, 1) = 1
              AND UPPER(
                    COALESCE(status, '')
                  ) <> 'ANULADO'
            """,
            (suplido_id,),
        ).fetchone()

        if not suplido:
            raise ValueError(
                "No existe el suplido activo seleccionado."
            )

        movement_total = abs(
            int(
                movement["amount_centimos"]
                or 0
            )
        )

        consumption = _movement_consumption(
            conn,
            movement_id,
        )

        movement_applied = int(
            consumption["total_centimos"]
            or 0
        )

        suplido_applied = int(
            conn.execute(
                """
                SELECT COALESCE(
                    SUM(amount_centimos),
                    0
                )
                FROM economic_suplido_payment_applications
                WHERE suplido_id = ?
                """,
                (suplido_id,),
            ).fetchone()[0]
            or 0
        )

        existing = conn.execute(
            """
            SELECT *
            FROM economic_suplido_payment_applications
            WHERE LOWER(
                COALESCE(source_type, '')
            ) = 'bank'
              AND source_movement_id = ?
              AND suplido_id = ?
            """,
            (
                movement_id,
                suplido_id,
            ),
        ).fetchone()

        existing_amount = (
            int(existing["amount_centimos"])
            if existing
            else 0
        )

        movement_pending = max(
            0,
            movement_total - movement_applied,
        )

        suplido_pending = max(
            0,
            int(
                suplido["amount_centimos"]
                or 0
            )
            - suplido_applied,
        )

        allowed = min(
            movement_pending,
            suplido_pending,
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
                UPDATE economic_suplido_payment_applications
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
                economic_suplido_payment_applications (
                    source_type,
                    source_movement_id,
                    suplido_id,
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
                    suplido_id,
                    amount_centimos,
                    notes,
                ),
            )

        updated_snapshot = _movement_consumption(
            conn,
            movement_id,
        )

        movement_linked = int(
            updated_snapshot["total_centimos"]
            or 0
        )

        if movement_linked <= 0:
            movement_status = (
                "PENDING_MANUAL_REVIEW"
            )
            linked_target_type = None
        elif movement_linked < movement_total:
            movement_status = "PARTIALLY_LINKED"
            linked_target_type = "MIXED"
        else:
            movement_status = "LINKED"
            linked_target_type = (
                "SUPLIDO"
                if (
                    updated_snapshot[
                        "suplidos_centimos"
                    ]
                    == movement_total
                )
                else "MIXED"
            )

        conn.execute(
            """
            UPDATE bank_movements
            SET linked_amount_centimos = ?,
                linked_target_type = ?,
                review_status = ?,
                linked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                movement_linked,
                linked_target_type,
                movement_status,
                movement_id,
            ),
        )

        conn.commit()

    return {
        "movement": get_movement_payment_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "suplido": get_suplido(
            suplido_id,
            db_path=db_path,
        ),
    }


def remove_suplido_payment(
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
            FROM economic_suplido_payment_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        if not application:
            raise ValueError(
                "No existe la aplicación del suplido."
            )

        movement_id = int(
            application["source_movement_id"]
        )
        suplido_id = int(
            application["suplido_id"]
        )

        conn.execute(
            """
            DELETE FROM economic_suplido_payment_applications
            WHERE id = ?
            """,
            (application_id,),
        )

        movement = conn.execute(
            """
            SELECT amount_centimos
            FROM bank_movements
            WHERE id = ?
            """,
            (movement_id,),
        ).fetchone()

        movement_total = abs(
            int(
                movement["amount_centimos"]
                or 0
            )
        )

        consumption = _movement_consumption(
            conn,
            movement_id,
        )

        linked_centimos = int(
            consumption["total_centimos"]
            or 0
        )

        if linked_centimos <= 0:
            review_status = (
                "PENDING_MANUAL_REVIEW"
            )
            linked_target_type = None
            linked_at = None
        elif linked_centimos < movement_total:
            review_status = "PARTIALLY_LINKED"
            linked_target_type = "MIXED"
            linked_at = "CURRENT_TIMESTAMP"
        else:
            review_status = "LINKED"
            linked_target_type = "MIXED"
            linked_at = "CURRENT_TIMESTAMP"

        if linked_at is None:
            conn.execute(
                """
                UPDATE bank_movements
                SET linked_amount_centimos = ?,
                    linked_target_type = ?,
                    review_status = ?,
                    linked_at = NULL,
                    link_notes = CASE
                        WHEN ? = '' THEN link_notes
                        ELSE ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    linked_centimos,
                    linked_target_type,
                    review_status,
                    reason,
                    reason,
                    movement_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE bank_movements
                SET linked_amount_centimos = ?,
                    linked_target_type = ?,
                    review_status = ?,
                    linked_at = CURRENT_TIMESTAMP,
                    link_notes = CASE
                        WHEN ? = '' THEN link_notes
                        ELSE ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    linked_centimos,
                    linked_target_type,
                    review_status,
                    reason,
                    reason,
                    movement_id,
                ),
            )

        conn.commit()

    return {
        "movement": get_movement_payment_snapshot(
            movement_id,
            db_path=db_path,
        ),
        "suplido": get_suplido(
            suplido_id,
            db_path=db_path,
        ),
    }


def list_reconcilable_suplidos(
    *,
    limit: int = 2000,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    limit = max(
        1,
        min(int(limit or 2000), 5000),
    )

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.*,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                e.numero_expediente,
                COALESCE(
                    (
                        SELECT SUM(
                            a.amount_centimos
                        )
                        FROM economic_suplido_payment_applications a
                        WHERE a.suplido_id = s.id
                    ),
                    0
                ) AS paid_application_centimos
            FROM economic_suplidos s
            LEFT JOIN clientes c
              ON c.id = s.client_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE COALESCE(s.active, 1) = 1
              AND UPPER(
                    COALESCE(s.status, '')
                  ) <> 'ANULADO'
            ORDER BY
                s.payment_date DESC,
                s.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []

    for row in rows:
        data = dict(row)

        total = int(
            data["amount_centimos"] or 0
        )
        applied = int(
            data["paid_application_centimos"]
            or 0
        )

        data["pending_payment_centimos"] = max(
            0,
            total - applied,
        )

        if data["pending_payment_centimos"] <= 0:
            continue

        result.append(data)

    return result


def create_suplido_from_movement(
    *,
    movement_id: int,
    client_id: int,
    concept: str,
    amount_centimos: int,
    expedient_id: int | None = None,
    provider_name: str = "",
    document_path: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    movement_id = int(movement_id)
    amount_centimos = int(
        amount_centimos or 0
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

        payment_date = str(
            movement["operation_date"]
            or movement["value_date"]
            or ""
        ).strip()

    if not payment_date:
        raise ValueError(
            "El movimiento no tiene fecha válida."
        )

    suplido_id = create_suplido(
        payment_date=payment_date,
        amount_centimos=amount_centimos,
        client_id=int(client_id),
        expedient_id=(
            int(expedient_id)
            if expedient_id
            else None
        ),
        concept=concept,
        provider_name=provider_name,
        document_path=document_path,
        notes=notes,
        db_path=db_path,
    )

    try:
        return apply_suplido_payment(
            movement_id=movement_id,
            suplido_id=suplido_id,
            amount_centimos=amount_centimos,
            notes=notes,
            db_path=db_path,
        )

    except Exception:
        with _connect(db_path) as conn:
            conn.execute(
                """
                UPDATE economic_suplidos
                SET active = 0,
                    status = 'ANULADO',
                    notes = CASE
                        WHEN TRIM(
                            COALESCE(notes, '')
                        ) = ''
                            THEN ?
                        ELSE notes
                          || char(10)
                          || ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    (
                        "Creación anulada porque no pudo "
                        "aplicarse al movimiento."
                    ),
                    (
                        "Creación anulada porque no pudo "
                        "aplicarse al movimiento."
                    ),
                    suplido_id,
                ),
            )
            conn.commit()

        raise


# ============================================================
# RECUPERACIÓN DE SUPLIDOS DESDE COBROS
# ============================================================

RECOVERY_SOURCE_PAYMENT = "payment"


def _sync_suplido_recovery_status(
    conn: sqlite3.Connection,
    suplido_id: int,
) -> dict[str, int | str]:
    suplido_id = int(suplido_id)

    suplido = conn.execute(
        """
        SELECT
            id,
            amount_centimos,
            active
        FROM economic_suplidos
        WHERE id = ?
        """,
        (suplido_id,),
    ).fetchone()

    if not suplido:
        raise ValueError("No existe el suplido.")

    total_centimos = int(
        suplido["amount_centimos"] or 0
    )

    recovered_centimos = int(
        conn.execute(
            """
            SELECT COALESCE(
                SUM(amount_centimos),
                0
            ) AS total
            FROM economic_suplido_recovery_applications
            WHERE suplido_id = ?
            """,
            (suplido_id,),
        ).fetchone()["total"]
        or 0
    )

    if recovered_centimos > total_centimos:
        raise ValueError(
            "La recuperación supera el importe "
            "total del suplido."
        )

    if not int(suplido["active"] or 0):
        status = STATUS_CANCELLED
    elif recovered_centimos <= 0:
        status = STATUS_PENDING
    elif recovered_centimos < total_centimos:
        status = STATUS_PARTIAL
    else:
        status = STATUS_RECOVERED

    conn.execute(
        """
        UPDATE economic_suplidos
        SET recovered_amount_centimos = ?,
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            recovered_centimos,
            status,
            suplido_id,
        ),
    )

    return {
        "total_centimos": total_centimos,
        "recovered_centimos": recovered_centimos,
        "pending_centimos": max(
            0,
            total_centimos - recovered_centimos,
        ),
        "status": status,
    }


def _get_cobro_recovery_totals(
    conn: sqlite3.Connection,
    cobro_id: int,
) -> dict[str, int]:
    cobro_id = int(cobro_id)

    cobro = conn.execute(
        """
        SELECT
            id,
            importe
        FROM eco_cobros
        WHERE id = ?
          AND COALESCE(activo, 1) = 1
        """,
        (cobro_id,),
    ).fetchone()

    if not cobro:
        raise ValueError(
            "No existe el cobro o está inactivo."
        )

    total_centimos = int(
        round(
            float(cobro["importe"] or 0)
            * 100
        )
    )

    applied_centimos = int(
        conn.execute(
            """
            SELECT COALESCE(
                SUM(amount_centimos),
                0
            ) AS total
            FROM economic_suplido_recovery_applications
            WHERE source_type = ?
              AND source_id = ?
            """,
            (
                RECOVERY_SOURCE_PAYMENT,
                cobro_id,
            ),
        ).fetchone()["total"]
        or 0
    )

    return {
        "total_centimos": total_centimos,
        "applied_centimos": applied_centimos,
        "pending_centimos": max(
            0,
            total_centimos - applied_centimos,
        ),
    }


def get_cobro_recovery_snapshot(
    cobro_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    cobro_id = int(cobro_id)

    with _connect(db_path) as conn:
        cobro = conn.execute(
            """
            SELECT
                c.*,
                cl.nombre,
                cl.primer_apellido,
                cl.segundo_apellido,
                e.numero_expediente,
                f.numero_factura
            FROM eco_cobros c
            LEFT JOIN clientes cl
              ON cl.id = c.cliente_id
            LEFT JOIN expedientes e
              ON e.id = c.expediente_id
            LEFT JOIN eco_facturas f
              ON f.id = c.factura_id
            WHERE c.id = ?
            """,
            (cobro_id,),
        ).fetchone()

        if not cobro:
            raise ValueError("No existe el cobro.")

        totals = _get_cobro_recovery_totals(
            conn,
            cobro_id,
        )

        applications = conn.execute(
            """
            SELECT
                r.*,
                s.payment_date,
                s.amount_centimos
                    AS suplido_amount_centimos,
                s.concept,
                s.provider_name,
                s.status,
                s.client_id,
                s.expedient_id,
                e.numero_expediente
            FROM economic_suplido_recovery_applications r
            JOIN economic_suplidos s
              ON s.id = r.suplido_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE r.source_type = ?
              AND r.source_id = ?
            ORDER BY
                r.created_at ASC,
                r.id ASC
            """,
            (
                RECOVERY_SOURCE_PAYMENT,
                cobro_id,
            ),
        ).fetchall()

    return {
        "cobro": dict(cobro),
        **totals,
        "recovery_applications": [
            dict(row)
            for row in applications
        ],
    }


def list_recoverable_suplidos(
    client_id: int,
    *,
    limit: int = 2000,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    client_id = int(client_id)
    limit = max(
        1,
        min(int(limit or 2000), 5000),
    )

    if client_id <= 0:
        return []

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.*,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                e.numero_expediente,
                COALESCE(
                    (
                        SELECT SUM(
                            r.amount_centimos
                        )
                        FROM economic_suplido_recovery_applications r
                        WHERE r.suplido_id = s.id
                    ),
                    0
                ) AS recovered_application_centimos
            FROM economic_suplidos s
            LEFT JOIN clientes c
              ON c.id = s.client_id
            LEFT JOIN expedientes e
              ON e.id = s.expedient_id
            WHERE s.client_id = ?
              AND COALESCE(s.active, 1) = 1
              AND UPPER(
                    COALESCE(s.status, '')
                  ) <> 'ANULADO'
            ORDER BY
                s.payment_date ASC,
                s.id ASC
            LIMIT ?
            """,
            (
                client_id,
                limit,
            ),
        ).fetchall()

    result = []

    for row in rows:
        data = dict(row)

        total_centimos = int(
            data["amount_centimos"] or 0
        )
        recovered_centimos = int(
            data[
                "recovered_application_centimos"
            ]
            or 0
        )

        data["pending_recovery_centimos"] = max(
            0,
            total_centimos - recovered_centimos,
        )

        if (
            data["pending_recovery_centimos"]
            <= 0
        ):
            continue

        result.append(data)

    return result


def apply_cobro_recovery(
    *,
    cobro_id: int,
    suplido_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    cobro_id = int(cobro_id)
    suplido_id = int(suplido_id)
    amount_centimos = int(
        amount_centimos or 0
    )
    notes = str(notes or "").strip()

    if amount_centimos <= 0:
        raise ValueError(
            "El importe recuperado debe ser "
            "mayor que cero."
        )

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        cobro = conn.execute(
            """
            SELECT
                id,
                cliente_id,
                importe,
                tipo_fiscal,
                activo
            FROM eco_cobros
            WHERE id = ?
            """,
            (cobro_id,),
        ).fetchone()

        if not cobro or not int(
            cobro["activo"] or 0
        ):
            raise ValueError(
                "No existe el cobro o está inactivo."
            )

        if (
            str(
                cobro["tipo_fiscal"] or ""
            ).strip().upper()
            != "SUPLIDO"
        ):
            raise ValueError(
                "Solo un cobro fiscal de tipo "
                "SUPLIDO puede recuperar un suplido."
            )

        suplido = conn.execute(
            """
            SELECT
                id,
                client_id,
                amount_centimos,
                status,
                active
            FROM economic_suplidos
            WHERE id = ?
            """,
            (suplido_id,),
        ).fetchone()

        if not suplido or not int(
            suplido["active"] or 0
        ):
            raise ValueError(
                "No existe el suplido o está inactivo."
            )

        if int(
            cobro["cliente_id"] or 0
        ) != int(
            suplido["client_id"] or 0
        ):
            raise ValueError(
                "El cobro y el suplido pertenecen "
                "a clientes distintos."
            )

        cobro_totals = _get_cobro_recovery_totals(
            conn,
            cobro_id,
        )

        if amount_centimos > int(
            cobro_totals["pending_centimos"]
        ):
            raise ValueError(
                "El importe supera el pendiente "
                "disponible del cobro."
            )

        suplido_total = int(
            suplido["amount_centimos"] or 0
        )

        suplido_recovered = int(
            conn.execute(
                """
                SELECT COALESCE(
                    SUM(amount_centimos),
                    0
                ) AS total
                FROM economic_suplido_recovery_applications
                WHERE suplido_id = ?
                """,
                (suplido_id,),
            ).fetchone()["total"]
            or 0
        )

        suplido_pending = max(
            0,
            suplido_total - suplido_recovered,
        )

        if amount_centimos > suplido_pending:
            raise ValueError(
                "El importe supera el pendiente "
                "de recuperación del suplido."
            )

        existing = conn.execute(
            """
            SELECT
                id,
                amount_centimos
            FROM economic_suplido_recovery_applications
            WHERE source_type = ?
              AND source_id = ?
              AND suplido_id = ?
            """,
            (
                RECOVERY_SOURCE_PAYMENT,
                cobro_id,
                suplido_id,
            ),
        ).fetchone()

        if existing:
            new_amount = (
                int(
                    existing["amount_centimos"]
                    or 0
                )
                + amount_centimos
            )

            conn.execute(
                """
                UPDATE economic_suplido_recovery_applications
                SET amount_centimos = ?,
                    notes = CASE
                        WHEN ? = '' THEN notes
                        ELSE ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_amount,
                    notes,
                    notes,
                    int(existing["id"]),
                ),
            )

            application_id = int(
                existing["id"]
            )

        else:
            cursor = conn.execute(
                """
                INSERT INTO
                economic_suplido_recovery_applications (
                    source_type,
                    source_id,
                    suplido_id,
                    amount_centimos,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    RECOVERY_SOURCE_PAYMENT,
                    cobro_id,
                    suplido_id,
                    amount_centimos,
                    notes,
                ),
            )

            application_id = int(
                cursor.lastrowid
            )

        _sync_suplido_recovery_status(
            conn,
            suplido_id,
        )

        conn.commit()

    return {
        "application_id": application_id,
        "cobro": get_cobro_recovery_snapshot(
            cobro_id,
            db_path=db_path,
        ),
        "suplido": get_suplido(
            suplido_id,
            db_path=db_path,
        ),
    }


def remove_cobro_recovery(
    application_id: int,
    *,
    reason: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    application_id = int(application_id)
    reason = str(reason or "").strip()

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        application = conn.execute(
            """
            SELECT *
            FROM economic_suplido_recovery_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        if not application:
            raise ValueError(
                "No existe la aplicación de recuperación."
            )

        if (
            str(
                application["source_type"] or ""
            ).strip().lower()
            != RECOVERY_SOURCE_PAYMENT
        ):
            raise ValueError(
                "La aplicación no procede de un cobro."
            )

        cobro_id = int(
            application["source_id"]
        )
        suplido_id = int(
            application["suplido_id"]
        )

        conn.execute(
            """
            DELETE FROM
            economic_suplido_recovery_applications
            WHERE id = ?
            """,
            (application_id,),
        )

        sync = _sync_suplido_recovery_status(
            conn,
            suplido_id,
        )

        if reason:
            conn.execute(
                """
                UPDATE economic_suplidos
                SET notes = CASE
                    WHEN TRIM(
                        COALESCE(notes, '')
                    ) = ''
                        THEN ?
                    ELSE notes
                      || char(10)
                      || ?
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    reason,
                    reason,
                    suplido_id,
                ),
            )

        conn.commit()

    return {
        "removed_application_id": application_id,
        "suplido_sync": sync,
        "cobro": get_cobro_recovery_snapshot(
            cobro_id,
            db_path=db_path,
        ),
        "suplido": get_suplido(
            suplido_id,
            db_path=db_path,
        ),
    }

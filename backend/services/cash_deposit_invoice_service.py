from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

MIGRATION_PATH = Path(
    "database/migrations/"
    "20260714_create_cash_deposit_invoice_allocations.sql"
)


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(
            f"No existe la migración: {MIGRATION_PATH}"
        )

    conn.executescript(
        MIGRATION_PATH.read_text(encoding="utf-8")
    )


def _cash_deposit_row(
    conn: sqlite3.Connection,
    movement_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            id,
            bank_name,
            operation_date,
            concept,
            amount_centimos,
            ignored_at,
            movement_status,
            invoiceability_status
        FROM bank_movements
        WHERE id = ?
        """,
        (int(movement_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            f"No existe movimiento bancario #{movement_id}."
        )

    bank_name = str(
        row["bank_name"] or ""
    ).strip().upper()

    concept = str(
        row["concept"] or ""
    ).strip().upper()

    if (
        bank_name != "CAJA_RURAL"
        or concept != "INGRESO EN EFECTIVO"
        or int(row["amount_centimos"] or 0) <= 0
    ):
        raise ValueError(
            "El movimiento seleccionado no es un ingreso "
            "en efectivo de Caja Rural."
        )

    if row["ignored_at"] is not None:
        raise ValueError(
            "No se pueden aplicar facturas a un movimiento "
            "bancario ignorado."
        )

    if str(
        row["movement_status"] or ""
    ).strip().upper() == "QUARANTINE":
        raise ValueError(
            "No se pueden aplicar facturas a un movimiento "
            "en cuarentena."
        )

    if str(
        row["invoiceability_status"] or "PENDING"
    ).strip().upper() == "NON_INVOICEABLE":
        raise ValueError(
            "El movimiento está marcado como no facturable."
        )

    return row


def is_cash_deposit(
    movement: Any,
) -> bool:
    if isinstance(movement, dict):
        bank_name = movement.get("bank_name")
        concept = movement.get("concept")
        amount = movement.get("amount_centimos")
    else:
        bank_name = getattr(movement, "bank_name", "")
        concept = getattr(movement, "concept", "")
        amount = getattr(movement, "amount_centimos", 0)

    return (
        str(bank_name or "").strip().upper()
        == "CAJA_RURAL"
        and str(concept or "").strip().upper()
        == "INGRESO EN EFECTIVO"
        and int(amount or 0) > 0
    )


def direct_invoice_amounts_by_bank_movement(
    conn: sqlite3.Connection,
) -> dict[int, int]:
    ensure_schema(conn)

    rows = conn.execute(
        """
        SELECT
            bank_movement_id,
            COALESCE(SUM(amount_centimos), 0)
                AS amount_centimos
        FROM economic_cash_deposit_invoice_allocations
        GROUP BY bank_movement_id
        """
    ).fetchall()

    return {
        int(row["bank_movement_id"]): max(
            int(row["amount_centimos"] or 0),
            0,
        )
        for row in rows
    }


def _payment_invoiced_for_movement(
    conn: sqlite3.Connection,
    movement_id: int,
) -> int:
    """
    Importe ya acreditado mediante:
        movimiento bancario
        -> cobro conciliado
        -> factura aprobada
    """

    rows = conn.execute(
        """
        SELECT
            era.amount_centimos AS applied_centimos,
            COALESCE(
                (
                    SELECT SUM(
                        CASE
                            WHEN COALESCE(fc.importe_asignado, 0) > 0
                            THEN fc.importe_asignado
                            ELSE 0
                        END
                    )
                    FROM eco_factura_cobros fc
                    JOIN eco_facturas f
                      ON f.id = fc.factura_id
                    WHERE fc.cobro_id = era.payment_id
                      AND COALESCE(f.activo, 1) = 1
                      AND (
                            UPPER(
                                COALESCE(f.estado, '')
                            ) = 'APROBADA'
                            OR COALESCE(
                                f.exportada_holded,
                                0
                            ) = 1
                          )
                ),
                0
            ) AS approved_eur
        FROM economic_reconciliation_applications era
        WHERE LOWER(
            COALESCE(era.source_type, '')
        ) = 'bank'
          AND era.source_movement_id = ?
        """,
        (int(movement_id),),
    ).fetchall()

    total = 0

    for row in rows:
        applied = max(
            int(row["applied_centimos"] or 0),
            0,
        )
        approved = max(
            int(
                round(
                    float(row["approved_eur"] or 0)
                    * 100
                )
            ),
            0,
        )

        total += min(applied, approved)

    return total


def _invoice_bank_reconciled_amounts(
    conn: sqlite3.Connection,
) -> dict[int, int]:
    """
    Calcula qué parte de cada factura aprobada ya está
    representada por cobros conciliados con movimientos bancarios.

    Distribución:
        factura
        -> eco_factura_cobros
        -> cobro
        -> economic_reconciliation_applications

    Para evitar doble cómputo, el importe bancario disponible de
    cada cobro se consume una sola vez y se distribuye entre sus
    facturas por orden de relación.
    """

    tables = {
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    }

    required = {
        "economic_reconciliation_applications",
        "eco_factura_cobros",
        "eco_facturas",
    }

    if not required.issubset(tables):
        return {}

    bank_rows = conn.execute(
        """
        SELECT
            payment_id,
            COALESCE(SUM(amount_centimos), 0)
                AS reconciled_centimos
        FROM economic_reconciliation_applications
        WHERE LOWER(COALESCE(source_type, '')) = 'bank'
          AND COALESCE(amount_centimos, 0) > 0
        GROUP BY payment_id
        """
    ).fetchall()

    remaining_by_payment = {
        int(row["payment_id"]): max(
            int(row["reconciled_centimos"] or 0),
            0,
        )
        for row in bank_rows
    }

    if not remaining_by_payment:
        return {}

    assignment_rows = conn.execute(
        """
        SELECT
            fc.factura_id,
            fc.cobro_id,
            CAST(
                ROUND(
                    COALESCE(fc.importe_asignado, 0) * 100
                )
                AS INTEGER
            ) AS assigned_centimos
        FROM eco_factura_cobros fc
        JOIN eco_facturas f
          ON f.id = fc.factura_id
        WHERE COALESCE(f.activo, 1) = 1
          AND (
                UPPER(COALESCE(f.estado, '')) IN (
                    'EMITIDA',
                    'APROBADA',
                    'EXPORTADA'
                )
                OR COALESCE(f.exportada_holded, 0) = 1
              )
          AND COALESCE(fc.importe_asignado, 0) > 0
        ORDER BY
            fc.cobro_id ASC,
            fc.id ASC
        """
    ).fetchall()

    result: dict[int, int] = {}

    for row in assignment_rows:
        payment_id = int(row["cobro_id"])
        invoice_id = int(row["factura_id"])

        remaining = max(
            int(
                remaining_by_payment.get(
                    payment_id,
                    0,
                )
            ),
            0,
        )

        if remaining <= 0:
            continue

        assigned = max(
            int(row["assigned_centimos"] or 0),
            0,
        )

        consumed = min(
            assigned,
            remaining,
        )

        if consumed <= 0:
            continue

        result[invoice_id] = (
            result.get(invoice_id, 0)
            + consumed
        )

        remaining_by_payment[payment_id] = (
            remaining - consumed
        )

    return result


def _invoice_directly_applied_centimos(
    conn: sqlite3.Connection,
    invoice_id: int,
) -> int:
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount_centimos), 0)
                AS amount_centimos
        FROM economic_cash_deposit_invoice_allocations
        WHERE invoice_id = ?
        """,
        (int(invoice_id),),
    ).fetchone()

    return max(
        int((row or {"amount_centimos": 0})[
            "amount_centimos"
        ] or 0),
        0,
    )


def list_candidate_invoices(
    movement_id: int,
    *,
    search: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        movement = _cash_deposit_row(
            conn,
            movement_id,
        )

        params: list[Any] = [
            str(movement["operation_date"] or ""),
        ]

        where = [
            "COALESCE(f.activo, 1) = 1",
            "COALESCE(f.total, 0) > 0",
            "f.fecha_factura <= ?",
            """
            (
                UPPER(COALESCE(f.estado, '')) IN (
                    'EMITIDA',
                    'APROBADA',
                    'EXPORTADA'
                )
                OR COALESCE(f.exportada_holded, 0) = 1
            )
            """,
            """
            UPPER(
                COALESCE(f.tipo_factura, 'NORMAL')
            ) != 'RECTIFICATIVA'
            """,
            """
            UPPER(
                COALESCE(f.estado, '')
            ) NOT IN (
                'ANULADA',
                'RECTIFICADA'
            )
            """,
        ]

        search = str(search or "").strip()

        if search:
            like = f"%{search}%"
            where.append(
                """
                (
                    f.numero_factura LIKE ?
                    OR f.fecha_factura LIKE ?
                    OR COALESCE(f.concepto, '') LIKE ?
                    OR TRIM(
                        COALESCE(c.nombre, '') || ' ' ||
                        COALESCE(c.primer_apellido, '') || ' ' ||
                        COALESCE(c.segundo_apellido, '')
                    ) LIKE ?
                )
                """
            )
            params.extend(
                [like, like, like, like]
            )

        rows = conn.execute(
            f"""
            SELECT
                f.id,
                f.numero_factura,
                f.fecha_factura,
                f.cliente_id,
                f.expediente_id,
                f.total,
                f.estado,
                f.exportada_holded,
                f.concepto,
                TRIM(
                    COALESCE(c.nombre, '') || ' ' ||
                    COALESCE(c.primer_apellido, '') || ' ' ||
                    COALESCE(c.segundo_apellido, '')
                ) AS cliente
            FROM eco_facturas f
            LEFT JOIN clientes c
              ON c.id = f.cliente_id
            WHERE {" AND ".join(where)}
            ORDER BY
                f.fecha_factura DESC,
                f.id DESC
            """,
            params,
        ).fetchall()

        bank_reconciled_by_invoice = (
            _invoice_bank_reconciled_amounts(conn)
        )

        result = []

        for row in rows:
            invoice_id = int(row["id"])
            total_centimos = max(
                int(
                    round(
                        float(row["total"] or 0)
                        * 100
                    )
                ),
                0,
            )

            bank_reconciled_centimos = max(
                int(
                    bank_reconciled_by_invoice.get(
                        invoice_id,
                        0,
                    )
                ),
                0,
            )

            allocated_centimos = (
                _invoice_directly_applied_centimos(
                    conn,
                    invoice_id,
                )
            )

            available_centimos = max(
                total_centimos
                - bank_reconciled_centimos
                - allocated_centimos,
                0,
            )

            if available_centimos <= 0:
                continue

            item = dict(row)
            item.update(
                {
                    "total_centimos": total_centimos,
                    "bank_reconciled_centimos": (
                        bank_reconciled_centimos
                    ),
                    "allocated_centimos": (
                        allocated_centimos
                    ),
                    "available_centimos": (
                        available_centimos
                    ),
                }
            )
            result.append(item)

        return result


def get_cash_deposit_allocations(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        _cash_deposit_row(conn, movement_id)

        rows = conn.execute(
            """
            SELECT
                a.id,
                a.bank_movement_id,
                a.invoice_id,
                a.amount_centimos,
                a.cash_collection_date,
                a.notes,
                a.created_at,
                a.updated_at,

                f.numero_factura,
                f.fecha_factura,
                f.total,
                f.estado,
                f.exportada_holded,
                f.concepto,

                TRIM(
                    COALESCE(c.nombre, '') || ' ' ||
                    COALESCE(c.primer_apellido, '') || ' ' ||
                    COALESCE(c.segundo_apellido, '')
                ) AS cliente

            FROM economic_cash_deposit_invoice_allocations a
            JOIN eco_facturas f
              ON f.id = a.invoice_id
            LEFT JOIN clientes c
              ON c.id = f.cliente_id
            WHERE a.bank_movement_id = ?
            ORDER BY
                f.fecha_factura ASC,
                a.id ASC
            """,
            (int(movement_id),),
        ).fetchall()

        return [dict(row) for row in rows]


def get_cash_deposit_snapshot(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with closing(_connect(db_path)) as conn:
        movement = _cash_deposit_row(
            conn,
            movement_id,
        )

        original = max(
            int(movement["amount_centimos"] or 0),
            0,
        )

        payment_invoiced = min(
            _payment_invoiced_for_movement(
                conn,
                movement_id,
            ),
            original,
        )

        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount_centimos), 0)
                    AS amount_centimos
            FROM economic_cash_deposit_invoice_allocations
            WHERE bank_movement_id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        direct_invoiced = max(
            int(row["amount_centimos"] or 0),
            0,
        )

        direct_invoiced = min(
            direct_invoiced,
            max(original - payment_invoiced, 0),
        )

        justified = min(
            payment_invoiced + direct_invoiced,
            original,
        )

        pending = max(
            original - justified,
            0,
        )

        if pending <= 0 and justified > 0:
            status = "FACTURADO"
        elif justified > 0:
            status = "PARCIAL"
        else:
            status = "PENDIENTE"

        return {
            "movement_id": int(movement_id),
            "original_centimos": original,
            "payment_invoiced_centimos": (
                payment_invoiced
            ),
            "direct_invoice_centimos": (
                direct_invoiced
            ),
            "justified_centimos": justified,
            "pending_centimos": pending,
            "status": status,
            "allocations": get_cash_deposit_allocations(
                movement_id,
                db_path=db_path,
            ),
        }


def add_invoice_allocation(
    *,
    movement_id: int,
    invoice_id: int,
    amount_centimos: int,
    cash_collection_date: str | None = None,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    amount_centimos = int(
        amount_centimos or 0
    )

    if amount_centimos <= 0:
        raise ValueError(
            "El importe aplicado debe ser superior a cero."
        )

    with closing(_connect(db_path)) as conn:
        movement = _cash_deposit_row(
            conn,
            movement_id,
        )

        invoice = conn.execute(
            """
            SELECT
                id,
                numero_factura,
                fecha_factura,
                total,
                estado,
                exportada_holded,
                tipo_factura,
                activo
            FROM eco_facturas
            WHERE id = ?
            """,
            (int(invoice_id),),
        ).fetchone()

        if not invoice:
            raise ValueError(
                f"No existe factura #{invoice_id}."
            )

        if not int(invoice["activo"] or 0):
            raise ValueError(
                "No se puede aplicar una factura inactiva."
            )

        invoice_status = str(
            invoice["estado"] or ""
        ).strip().upper()

        if (
            invoice_status
            not in {
                "EMITIDA",
                "APROBADA",
                "EXPORTADA",
            }
            and not int(
                invoice["exportada_holded"] or 0
            )
        ):
            raise ValueError(
                "La factura debe estar emitida o aprobada."
            )

        if str(
            invoice["tipo_factura"] or "NORMAL"
        ).strip().upper() == "RECTIFICATIVA":
            raise ValueError(
                "No se pueden aplicar facturas rectificativas "
                "a un ingreso de efectivo."
            )

        if str(
            invoice["fecha_factura"] or ""
        ) > str(
            movement["operation_date"] or ""
        ):
            raise ValueError(
                "La factura no puede ser posterior al ingreso "
                "bancario de efectivo."
            )

        resolved_cash_date = str(
            cash_collection_date or ""
        ).strip()

        if (
            resolved_cash_date
            and resolved_cash_date
            > str(movement["operation_date"] or "")
        ):
            raise ValueError(
                "La fecha del cobro en efectivo no puede ser "
                "posterior al ingreso bancario."
            )

        original = max(
            int(movement["amount_centimos"] or 0),
            0,
        )

        payment_invoiced = min(
            _payment_invoiced_for_movement(
                conn,
                movement_id,
            ),
            original,
        )

        existing_allocation = conn.execute(
            """
            SELECT id, amount_centimos
            FROM economic_cash_deposit_invoice_allocations
            WHERE bank_movement_id = ?
              AND invoice_id = ?
            """,
            (
                int(movement_id),
                int(invoice_id),
            ),
        ).fetchone()

        existing_amount = max(
            int(
                (
                    existing_allocation
                    or {"amount_centimos": 0}
                )["amount_centimos"]
                or 0
            ),
            0,
        )

        direct_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount_centimos), 0)
                    AS amount_centimos
            FROM economic_cash_deposit_invoice_allocations
            WHERE bank_movement_id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        direct_applied = max(
            int(direct_row["amount_centimos"] or 0),
            0,
        )

        # Al editar una relación, su importe actual vuelve
        # provisionalmente a estar disponible.
        direct_applied_without_current = max(
            direct_applied - existing_amount,
            0,
        )

        movement_available = max(
            original
            - payment_invoiced
            - direct_applied_without_current,
            0,
        )

        invoice_total = max(
            int(
                round(
                    float(invoice["total"] or 0)
                    * 100
                )
            ),
            0,
        )

        bank_reconciled_by_invoice = (
            _invoice_bank_reconciled_amounts(conn)
        )

        bank_reconciled_invoice = max(
            int(
                bank_reconciled_by_invoice.get(
                    int(invoice_id),
                    0,
                )
            ),
            0,
        )

        invoice_applied = (
            _invoice_directly_applied_centimos(
                conn,
                invoice_id,
            )
        )

        invoice_applied_without_current = max(
            invoice_applied - existing_amount,
            0,
        )

        invoice_available = max(
            invoice_total
            - bank_reconciled_invoice
            - invoice_applied_without_current,
            0,
        )

        maximum = min(
            movement_available,
            invoice_available,
        )

        if amount_centimos > maximum:
            raise ValueError(
                "El importe supera el máximo disponible. "
                f"Máximo aplicable: {maximum / 100:.2f} €."
            )

        conn.execute(
            """
            INSERT INTO
            economic_cash_deposit_invoice_allocations (
                bank_movement_id,
                invoice_id,
                amount_centimos,
                cash_collection_date,
                notes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(
                bank_movement_id,
                invoice_id
            )
            DO UPDATE SET
                amount_centimos = excluded.amount_centimos,
                cash_collection_date =
                    excluded.cash_collection_date,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(movement_id),
                int(invoice_id),
                amount_centimos,
                resolved_cash_date or None,
                str(notes or "").strip(),
            ),
        )

        conn.commit()

    return get_cash_deposit_snapshot(
        movement_id,
        db_path=db_path,
    )


def remove_invoice_allocation(
    allocation_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT bank_movement_id
            FROM economic_cash_deposit_invoice_allocations
            WHERE id = ?
            """,
            (int(allocation_id),),
        ).fetchone()

        if not row:
            raise ValueError(
                f"No existe aplicación #{allocation_id}."
            )

        movement_id = int(
            row["bank_movement_id"]
        )

        conn.execute(
            """
            DELETE FROM
            economic_cash_deposit_invoice_allocations
            WHERE id = ?
            """,
            (int(allocation_id),),
        )
        conn.commit()

    return get_cash_deposit_snapshot(
        movement_id,
        db_path=db_path,
    )

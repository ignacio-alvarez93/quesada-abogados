from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")


@dataclass(frozen=True)
class InvoicingObligationMovement:
    source_type: str
    source_label: str
    source_id: int
    obligation_date: str
    concept: str

    # amount_centimos representa el importe todavía pendiente
    # para mantener compatibilidad con la vista existente.
    amount_centimos: int

    original_amount_centimos: int
    invoiced_centimos: int
    invoicing_status: str

    movement_type: str
    movement_status: str


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    columns = {
        row["name"]
        for row in conn.execute(
            'PRAGMA table_info("bank_movements")'
        ).fetchall()
    }

    migrations = [
        (
            "invoiceability_status",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_status
            TEXT NOT NULL DEFAULT 'PENDING'
            """,
        ),
        (
            "invoiceability_reason",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_reason TEXT
            """,
        ),
        (
            "invoiceability_updated_at",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_updated_at TEXT
            """,
        ),
    ]

    for column, sql in migrations:
        if column not in columns:
            conn.execute(sql)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_bank_movements_invoiceability_status
        ON bank_movements(invoiceability_status)
        """
    )
    conn.commit()

    return conn


def cents_to_eur(value: int | None) -> float:
    return round(int(value or 0) / 100, 2)


def _clean_date(value: Any) -> str:
    raw = str(value or "").strip()
    return raw[:10] if len(raw) >= 10 else ""


def _approved_invoice_amounts_by_bank_movement(
    conn: sqlite3.Connection,
) -> dict[int, int]:
    """
    Devuelve el importe facturado y aprobado imputable a cada
    movimiento bancario.

    Circuito:
        bank_movements
        → economic_reconciliation_applications
        → eco_cobros
        → eco_factura_cobros
        → eco_facturas aprobadas

    Cuando un cobro está conciliado con varios movimientos,
    el importe aprobado se distribuye siguiendo el orden de las
    aplicaciones de conciliación, sin superar nunca el importe
    aplicado a cada movimiento.
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

    approved_rows = conn.execute(
        """
        SELECT
            fc.cobro_id,
            CAST(
                ROUND(
                    SUM(
                        CASE
                            WHEN COALESCE(fc.importe_asignado, 0) > 0
                            THEN fc.importe_asignado
                            ELSE 0
                        END
                    ) * 100
                )
                AS INTEGER
            ) AS approved_centimos
        FROM eco_factura_cobros fc
        JOIN eco_facturas f
          ON f.id = fc.factura_id
        WHERE COALESCE(f.activo, 1) = 1
          AND (
                UPPER(COALESCE(f.estado, '')) = 'APROBADA'
                OR COALESCE(f.exportada_holded, 0) = 1
              )
        GROUP BY fc.cobro_id
        """
    ).fetchall()

    approved_by_payment = {
        int(row["cobro_id"]): max(
            int(row["approved_centimos"] or 0),
            0,
        )
        for row in approved_rows
    }

    if not approved_by_payment:
        return {}

    application_rows = conn.execute(
        """
        SELECT
            id,
            payment_id,
            source_movement_id,
            amount_centimos
        FROM economic_reconciliation_applications
        WHERE LOWER(COALESCE(source_type, '')) = 'bank'
          AND COALESCE(amount_centimos, 0) > 0
        ORDER BY
            payment_id ASC,
            id ASC
        """
    ).fetchall()

    remaining_by_payment = dict(approved_by_payment)
    invoiced_by_movement: dict[int, int] = {}

    for row in application_rows:
        payment_id = int(row["payment_id"])
        movement_id = int(row["source_movement_id"])
        application_amount = max(
            int(row["amount_centimos"] or 0),
            0,
        )

        remaining = max(
            int(remaining_by_payment.get(payment_id, 0)),
            0,
        )

        if remaining <= 0:
            continue

        allocated = min(
            application_amount,
            remaining,
        )

        if allocated <= 0:
            continue

        invoiced_by_movement[movement_id] = (
            invoiced_by_movement.get(movement_id, 0)
            + allocated
        )

        remaining_by_payment[payment_id] = (
            remaining - allocated
        )

    return invoiced_by_movement


def _bank_movements(
    conn: sqlite3.Connection,
) -> list[InvoicingObligationMovement]:
    rows = conn.execute(
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
        WHERE amount_centimos > 0
          AND movement_status != 'QUARANTINE'
          AND ignored_at IS NULL
          AND COALESCE(
                invoiceability_status,
                'PENDING'
              ) != 'NON_INVOICEABLE'
        ORDER BY operation_date DESC, id DESC
        """
    ).fetchall()

    invoiced_by_movement = (
        _approved_invoice_amounts_by_bank_movement(conn)
    )

    source_labels = {
        "CAJA_RURAL": "Caja Rural",
        "SANTANDER": "Santander",
        "ING": "ING",
    }

    result = []

    for row in rows:
        movement_id = int(row["id"])
        bank_name = str(
            row["bank_name"] or ""
        ).strip().upper()

        obligation_date = _clean_date(
            row["operation_date"]
        )

        if not obligation_date:
            continue

        original_amount = max(
            int(row["amount_centimos"] or 0),
            0,
        )

        invoiced_amount = min(
            max(
                int(
                    invoiced_by_movement.get(
                        movement_id,
                        0,
                    )
                ),
                0,
            ),
            original_amount,
        )

        pending_amount = max(
            original_amount - invoiced_amount,
            0,
        )

        if pending_amount <= 0:
            invoicing_status = "FACTURADO"
        elif invoiced_amount > 0:
            invoicing_status = "PARCIAL"
        else:
            invoicing_status = "PENDIENTE"

        # Los movimientos totalmente facturados permanecen
        # visibles para conservar la trazabilidad del día.
        #
        # amount_centimos continúa representando únicamente
        # el importe pendiente, por lo que los totales de
        # Obligaciones no vuelven a sumar lo ya facturado.
        result.append(
            InvoicingObligationMovement(
                source_type=bank_name,
                source_label=source_labels.get(
                    bank_name,
                    bank_name.replace("_", " ").title(),
                ),
                source_id=movement_id,
                obligation_date=obligation_date,
                concept=str(
                    row["concept"] or ""
                ).strip().upper(),
                amount_centimos=pending_amount,
                original_amount_centimos=original_amount,
                invoiced_centimos=invoiced_amount,
                invoicing_status=invoicing_status,
                movement_type=str(
                    row["movement_type"] or ""
                ),
                movement_status=str(
                    row["movement_status"] or ""
                ),
            )
        )

    return result


def _cashmatic_movements(
    conn: sqlite3.Connection,
) -> list[InvoicingObligationMovement]:
    rows = conn.execute(
        """
        SELECT
            id,
            cashmatic_id,
            start_time,
            reason_raw,
            reference_raw,
            net_amount_centimos,
            requested_centimos,
            movement_status,
            operation,
            result,
            end_type
        FROM cashmatic_movements
        WHERE candidate_payment = 1
          AND net_amount_centimos > 0
          AND ignored_at IS NULL
          AND movement_status != 'QUARANTINE'
        ORDER BY start_time DESC, id DESC
        """
    ).fetchall()

    # Un mismo pago puede estar presente en varios exports.
    # Conservamos una sola fila lógica por cashmatic_id.
    unique: dict[str, sqlite3.Row] = {}
    without_id: list[sqlite3.Row] = []

    for row in rows:
        cashmatic_id = str(row["cashmatic_id"] or "").strip()

        if cashmatic_id:
            previous = unique.get(cashmatic_id)

            if previous is None:
                unique[cashmatic_id] = row
                continue

            # Preferimos la fila con hora más precisa y mayor id.
            previous_time = str(previous["start_time"] or "")
            current_time = str(row["start_time"] or "")

            previous_score = (
                1 if len(previous_time) >= 19
                and previous_time[17:19] != "00"
                else 0,
                int(previous["id"]),
            )
            current_score = (
                1 if len(current_time) >= 19
                and current_time[17:19] != "00"
                else 0,
                int(row["id"]),
            )

            if current_score > previous_score:
                unique[cashmatic_id] = row
        else:
            without_id.append(row)

    selected = list(unique.values()) + without_id
    result = []

    for row in selected:
        obligation_date = _clean_date(row["start_time"])

        if not obligation_date:
            continue

        concept_parts = [
            str(row["reason_raw"] or "").strip(),
            str(row["reference_raw"] or "").strip(),
        ]
        concept = " · ".join(
            part for part in concept_parts if part
        )

        if not concept:
            concept = (
                f"PAGO CASHMATIC "
                f"{str(row['cashmatic_id'] or row['id']).strip()}"
            )

        result.append(
            InvoicingObligationMovement(
                source_type="CASHMATIC",
                source_label="Efectivo",
                source_id=int(row["id"]),
                obligation_date=obligation_date,
                concept=concept.upper(),
                amount_centimos=int(
                    row["net_amount_centimos"] or 0
                ),
                original_amount_centimos=int(
                    row["net_amount_centimos"] or 0
                ),
                invoiced_centimos=0,
                invoicing_status="PENDIENTE",
                movement_type=str(row["operation"] or ""),
                movement_status=str(
                    row["movement_status"] or ""
                ),
            )
        )

    return result


def list_invoicing_obligation_movements(
    *,
    month: str | None = None,
    source_type: str | None = None,
    search: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[InvoicingObligationMovement]:
    with _connect(db_path) as conn:
        # Las obligaciones de facturación se generan únicamente
        # desde ingresos bancarios positivos.
        #
        # El efectivo cobrado mediante Cashmatic no se suma aquí:
        # se tendrá en cuenta cuando sea ingresado posteriormente
        # en una cuenta bancaria, evitando así doble cómputo.
        movements = _bank_movements(conn)

    month = str(month or "").strip()
    source_type = str(source_type or "").strip().upper()
    search_tokens = [
        token
        for token in str(search or "").strip().lower().split()
        if token
    ]

    result = []

    for movement in movements:
        if month and not movement.obligation_date.startswith(month):
            continue

        if source_type and source_type not in ("ALL", "TODOS"):
            if movement.source_type != source_type:
                continue

        if search_tokens:
            blob = " ".join(
                [
                    movement.obligation_date,
                    movement.source_type,
                    movement.source_label,
                    movement.concept,
                    str(movement.source_id),
                    str(movement.amount_centimos),
                ]
            ).lower()

            if not all(token in blob for token in search_tokens):
                continue

        result.append(movement)

    return sorted(
        result,
        key=lambda item: (
            item.obligation_date,
            item.source_type,
            item.source_id,
        ),
        reverse=True,
    )


def daily_invoicing_obligations(
    *,
    month: str | None = None,
    source_type: str | None = None,
    search: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    movements = list_invoicing_obligation_movements(
        month=month,
        source_type=source_type,
        search=search,
        db_path=db_path,
    )

    grouped: dict[str, list[InvoicingObligationMovement]] = (
        defaultdict(list)
    )

    for movement in movements:
        grouped[movement.obligation_date].append(movement)

    result = []

    for obligation_date, items in grouped.items():
        source_totals: dict[str, dict[str, Any]] = {}

        for item in items:
            source = source_totals.setdefault(
                item.source_type,
                {
                    "source_type": item.source_type,
                    "source_label": item.source_label,
                    "movements": 0,
                    "amount_centimos": 0,
                },
            )
            source["movements"] += 1
            source["amount_centimos"] += item.amount_centimos

        total_centimos = sum(
            item.amount_centimos
            for item in items
        )

        result.append(
            {
                "obligation_date": obligation_date,
                "total_centimos": total_centimos,
                "movement_count": len(items),
                "source_totals": sorted(
                    source_totals.values(),
                    key=lambda source: source["source_label"],
                ),
                "movements": items,
            }
        )

    return sorted(
        result,
        key=lambda item: item["obligation_date"],
        reverse=True,
    )


def invoicing_obligations_summary(
    *,
    month: str | None = None,
    source_type: str | None = None,
    search: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    days = daily_invoicing_obligations(
        month=month,
        source_type=source_type,
        search=search,
        db_path=db_path,
    )

    total_centimos = sum(
        int(day["total_centimos"] or 0)
        for day in days
    )
    movement_count = sum(
        int(day["movement_count"] or 0)
        for day in days
    )

    by_source: dict[str, dict[str, Any]] = {}

    for day in days:
        for source in day["source_totals"]:
            current = by_source.setdefault(
                source["source_type"],
                {
                    "source_type": source["source_type"],
                    "source_label": source["source_label"],
                    "amount_centimos": 0,
                    "movements": 0,
                },
            )

            current["amount_centimos"] += int(
                source["amount_centimos"] or 0
            )
            current["movements"] += int(
                source["movements"] or 0
            )

    return {
        "total_centimos": total_centimos,
        "pending_centimos": total_centimos,
        "invoiced_centimos": 0,
        "excluded_centimos": 0,
        "movement_count": movement_count,
        "days_count": len(days),
        "by_source": sorted(
            by_source.values(),
            key=lambda source: source["source_label"],
        ),
    }


def available_obligation_months(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    movements = list_invoicing_obligation_movements(
        db_path=db_path,
    )

    return sorted(
        {
            movement.obligation_date[:7]
            for movement in movements
            if len(movement.obligation_date) >= 7
        },
        reverse=True,
    )

def bank_movement_invoicing_snapshot(
    movement_ids=None,
) -> dict[int, dict]:
    """
    Estado real de facturación de movimientos bancarios.

    No modifica invoiceability_status. Devuelve un estado
    calculado independiente:

        PENDIENTE
        PARCIAL
        FACTURADO
        NO_FACTURABLE
    """

    requested_ids = {
        int(value)
        for value in (movement_ids or [])
        if value is not None
    }

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                amount_centimos,
                COALESCE(
                    invoiceability_status,
                    'PENDING'
                ) AS invoiceability_status
            FROM bank_movements
            WHERE amount_centimos > 0
            """
        ).fetchall()

        invoiced_by_movement = (
            _approved_invoice_amounts_by_bank_movement(conn)
        )

    result = {}

    for row in rows:
        movement_id = int(row["id"])

        if requested_ids and movement_id not in requested_ids:
            continue

        original = max(
            int(row["amount_centimos"] or 0),
            0,
        )

        invoiceability = str(
            row["invoiceability_status"] or "PENDING"
        ).strip().upper()

        if invoiceability == "NON_INVOICEABLE":
            invoiced = 0
            pending = 0
            status = "NO_FACTURABLE"
        else:
            invoiced = min(
                max(
                    int(
                        invoiced_by_movement.get(
                            movement_id,
                            0,
                        )
                    ),
                    0,
                ),
                original,
            )

            pending = max(
                original - invoiced,
                0,
            )

            if pending <= 0 and invoiced > 0:
                status = "FACTURADO"
            elif invoiced > 0:
                status = "PARCIAL"
            else:
                status = "PENDIENTE"

        result[movement_id] = {
            "movement_id": movement_id,
            "original_centimos": original,
            "invoiced_centimos": invoiced,
            "pending_centimos": pending,
            "status": status,
            "invoiceability_status": invoiceability,
        }

    return result

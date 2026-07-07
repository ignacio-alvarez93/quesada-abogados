from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.economic_reconciliation.bank_santander_parser_service import (
    SantanderBankDiagnosticReport,
    SantanderBankDiagnosticRow,
    diagnose_santander_bank_file,
)
from backend.services.economic_reconciliation.bank_caja_rural_parser_service import (
    CajaRuralBankDiagnosticReport,
    CajaRuralBankDiagnosticRow,
    diagnose_caja_rural_bank_file,
)
from backend.services.economic_reconciliation.cashmatic_import_service import (
    DEFAULT_DB_PATH,
    connect,
    ensure_schema as ensure_cashmatic_schema,
)


BANK_MIGRATION_PATH = Path("database/migrations/20260706_create_bank_reconciliation_staging.sql")


@dataclass(frozen=True)
class BankImportResult:
    batch_id: int
    batch_created: bool
    source_file: str
    file_sha256: str
    total_rows: int
    inserted_rows: int
    duplicate_rows: int
    income_rows: int
    expense_rows: int
    quarantine_rows: int
    manual_linking_policy: str


def ensure_bank_schema(conn: sqlite3.Connection) -> None:
    # economic_import_batches vive en la migración Cashmatic; la reutilizamos.
    ensure_cashmatic_schema(conn)

    if not BANK_MIGRATION_PATH.exists():
        raise FileNotFoundError(f"No existe migración bancaria: {BANK_MIGRATION_PATH}")

    conn.executescript(BANK_MIGRATION_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _insert_or_get_bank_batch(
    conn: sqlite3.Connection,
    *,
    source_file_path: Path,
    report: SantanderBankDiagnosticReport | CajaRuralBankDiagnosticReport,
    source_type: str,
    bank_label: str,
) -> tuple[int, bool]:
    existing = conn.execute(
        """
        SELECT id
        FROM economic_import_batches
        WHERE source_type = ?
          AND file_sha256 = ?
        LIMIT 1
        """,
        (source_type, report.file_sha256),
    ).fetchone()

    if existing:
        return int(existing["id"]), False

    conn.execute(
        """
        INSERT INTO economic_import_batches (
            source_type,
            source_file_name,
            source_file_path,
            file_sha256,
            detected_format,
            total_rows,
            valid_rows,
            quarantine_rows,
            candidate_payment_rows,
            total_candidate_requested_centimos,
            total_candidate_inserted_centimos,
            total_candidate_dispensed_centimos,
            total_candidate_net_centimos,
            first_start_time,
            last_start_time,
            status,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_type,
            report.source_file,
            str(source_file_path),
            report.file_sha256,
            report.detected_format,
            report.total_rows,
            report.valid_rows,
            report.quarantine_rows,
            report.income_rows,
            0,
            0,
            0,
            report.net_amount_centimos,
            report.first_operation_date,
            report.last_operation_date,
            "IMPORTED",
            (
                f"Banco {bank_label} importado como movimiento bancario bruto. "
                "No crea cobros, facturas ni vínculos automáticos."
            ),
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]), True


def _insert_bank_movement(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    row: SantanderBankDiagnosticRow | CajaRuralBankDiagnosticRow,
    bank_name: str,
) -> bool:
    before = conn.total_changes

    statement_number = getattr(row, "statement_number", "")
    account_label = f"apunte:{statement_number}" if statement_number else None

    conn.execute(
        """
        INSERT OR IGNORE INTO bank_movements (
            batch_id,
            row_number,
            row_hash,
            bank_name,
            account_label,
            account_iban,
            operation_date,
            value_date,
            concept,
            amount_centimos,
            balance_centimos,
            currency,
            movement_type,
            movement_status,
            warnings_json,
            linked_client_id,
            linked_expedient_id,
            linked_payment_id,
            linked_by_user_id,
            linked_at,
            link_notes,
            review_status,
            ignored_at,
            ignored_reason
        )
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            NULL, NULL, NULL, NULL, NULL, NULL,
            ?, NULL, NULL
        )
        """,
        (
            batch_id,
            row.row_number,
            row.row_hash,
            bank_name,
            account_label,
            None,
            row.operation_date,
            row.value_date,
            row.concept,
            row.amount_centimos,
            row.balance_centimos,
            "EUR",
            row.movement_type,
            row.movement_status,
            __import__("json").dumps(row.warnings, ensure_ascii=False),
            "PENDING_MANUAL_REVIEW",
        ),
    )

    return conn.total_changes > before


def import_santander_bank_file(
    file_path: str | Path,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> BankImportResult:
    source_file_path = Path(file_path)
    report = diagnose_santander_bank_file(source_file_path)

    inserted = 0
    duplicates = 0

    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        batch_id, batch_created = _insert_or_get_bank_batch(
            conn,
            source_file_path=source_file_path,
            report=report,
            source_type="BANK_SANTANDER",
            bank_label="Santander",
        )

        for row in report.rows:
            if _insert_bank_movement(conn, batch_id=batch_id, row=row, bank_name="SANTANDER"):
                inserted += 1
            else:
                duplicates += 1

        conn.commit()

    return BankImportResult(
        batch_id=batch_id,
        batch_created=batch_created,
        source_file=report.source_file,
        file_sha256=report.file_sha256,
        total_rows=report.total_rows,
        inserted_rows=inserted,
        duplicate_rows=duplicates,
        income_rows=report.income_rows,
        expense_rows=report.expense_rows,
        quarantine_rows=report.quarantine_rows,
        manual_linking_policy=(
            "El banco se importa como movimiento bruto. "
            "No crea cobros, facturas ni vínculos automáticos."
        ),
    )


def import_caja_rural_bank_file(
    file_path: str | Path,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> BankImportResult:
    source_file_path = Path(file_path)
    report = diagnose_caja_rural_bank_file(source_file_path)

    inserted = 0
    duplicates = 0

    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        batch_id, batch_created = _insert_or_get_bank_batch(
            conn,
            source_file_path=source_file_path,
            report=report,
            source_type="BANK_CAJA_RURAL",
            bank_label="Caja Rural",
        )

        for row in report.rows:
            if _insert_bank_movement(conn, batch_id=batch_id, row=row, bank_name="CAJA_RURAL"):
                inserted += 1
            else:
                duplicates += 1

        conn.commit()

    return BankImportResult(
        batch_id=batch_id,
        batch_created=batch_created,
        source_file=report.source_file,
        file_sha256=report.file_sha256,
        total_rows=report.total_rows,
        inserted_rows=inserted,
        duplicate_rows=duplicates,
        income_rows=report.income_rows,
        expense_rows=report.expense_rows,
        quarantine_rows=report.quarantine_rows,
        manual_linking_policy=(
            "Caja Rural se importa como movimiento bruto. "
            "No crea cobros, facturas ni vínculos automáticos."
        ),
    )


def get_bank_import_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        batches = conn.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COALESCE(SUM(total_rows), 0) AS total_rows,
                COALESCE(SUM(candidate_payment_rows), 0) AS income_rows,
                COALESCE(SUM(quarantine_rows), 0) AS quarantine_rows
            FROM economic_import_batches
            WHERE source_type IN ('BANK_SANTANDER', 'BANK_CAJA_RURAL')
            """
        ).fetchone()

        movements_by_status = conn.execute(
            """
            SELECT movement_status, COUNT(*) AS total
            FROM bank_movements
            GROUP BY movement_status
            ORDER BY movement_status
            """
        ).fetchall()

        movements_by_type = conn.execute(
            """
            SELECT movement_type, COUNT(*) AS total
            FROM bank_movements
            GROUP BY movement_type
            ORDER BY movement_type
            """
        ).fetchall()

        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_unique_movements,
                COALESCE(SUM(CASE WHEN amount_centimos > 0 THEN 1 ELSE 0 END), 0) AS income_movements,
                COALESCE(SUM(CASE WHEN amount_centimos < 0 THEN 1 ELSE 0 END), 0) AS expense_movements,
                COALESCE(SUM(CASE WHEN amount_centimos > 0 THEN amount_centimos ELSE 0 END), 0) AS total_income_centimos,
                COALESCE(SUM(CASE WHEN amount_centimos < 0 THEN amount_centimos ELSE 0 END), 0) AS total_expense_centimos,
                COALESCE(SUM(amount_centimos), 0) AS net_amount_centimos,
                COALESCE(SUM(CASE WHEN linked_client_id IS NOT NULL OR linked_expedient_id IS NOT NULL OR linked_payment_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS manual_links_total
            FROM bank_movements
            """
        ).fetchone()

        return {
            "batches": dict(batches or {}),
            "totals": dict(totals or {}),
            "movements_by_status": [dict(row) for row in movements_by_status],
            "movements_by_type": [dict(row) for row in movements_by_type],
        }

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.economic_reconciliation.cashmatic_parser_service import (
    CashmaticDiagnosticReport,
    CashmaticDiagnosticRow,
    diagnose_cashmatic_file,
)


DEFAULT_DB_PATH = Path("database/quesada.db")
DEFAULT_MIGRATION_PATH = Path(
    "database/migrations/20260706_create_cashmatic_reconciliation_staging.sql"
)


@dataclass(frozen=True)
class CashmaticImportResult:
    db_path: str
    file_path: str
    file_sha256: str
    batch_id: int
    batch_created: bool
    total_rows: int
    inserted_rows: int
    duplicate_rows: int
    candidate_payment_rows: int
    quarantine_rows: int
    manual_linking_policy: str


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_schema(
    conn: sqlite3.Connection,
    migration_path: str | Path = DEFAULT_MIGRATION_PATH,
) -> None:
    path = Path(migration_path)
    if not path.exists():
        raise FileNotFoundError(f"No existe la migración: {path}")

    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def _insert_or_get_batch(
    conn: sqlite3.Connection,
    report: CashmaticDiagnosticReport,
) -> tuple[int, bool]:
    existing = conn.execute(
        """
        SELECT id
        FROM economic_import_batches
        WHERE source_type = ? AND file_sha256 = ?
        """,
        ("CASHMATIC", report.file_sha256),
    ).fetchone()

    if existing:
        return int(existing["id"]), False

    cursor = conn.execute(
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
            "CASHMATIC",
            report.file_name,
            report.file_path,
            report.file_sha256,
            report.detected_format,
            report.total_rows,
            report.valid_rows,
            report.quarantine_rows,
            report.candidate_payment_rows,
            report.total_candidate_requested_centimos,
            report.total_candidate_inserted_centimos,
            report.total_candidate_dispensed_centimos,
            report.total_candidate_net_centimos,
            report.first_start_time,
            report.last_start_time,
            "IMPORTED",
            report.manual_linking_policy,
        ),
    )

    return int(cursor.lastrowid), True


def _canonical_movement_hash(row: CashmaticDiagnosticRow) -> str:
    """Hash canónico del movimiento económico Cashmatic.

    Cashmatic puede exportar rangos solapados. Si el mismo movimiento aparece
    en dos exportaciones distintas, debe figurar una sola vez en staging.

    No usamos row_number ni batch_id porque pertenecen al archivo exportado,
    no al movimiento económico real.
    """
    payload = {
        "cashmatic_id": row.cashmatic_id,
        "operation": row.operation,
        "result": row.result,
        "end_type": row.end_type,
        "requested_centimos": row.requested_centimos,
        "inserted_centimos": row.inserted_centimos,
        "dispensed_centimos": row.dispensed_centimos,
        "not_dispensed_centimos": row.not_dispensed_centimos,
        "net_amount_centimos": row.net_amount_centimos,
        "currency": row.currency,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "source_raw": row.source_raw,
        "reason_raw": row.reason_raw,
        "reference_raw": row.reference_raw,
        "user_username": row.user_username,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _insert_movement(
    conn: sqlite3.Connection,
    batch_id: int,
    row: CashmaticDiagnosticRow,
) -> bool:
    before = conn.total_changes
    canonical_row_hash = _canonical_movement_hash(row)

    # Dedupe global Cashmatic:
    # Los exports diarios/mensuales pueden solaparse. El mismo movimiento puede
    # venir con segundos reales en un CSV y redondeado al minuto en otro.
    # Por eso, si Cashmatic trae ID propio, ese ID es la clave lógica principal.
    cashmatic_id = str(row.cashmatic_id or "").strip()

    if cashmatic_id:
        existing = conn.execute(
            """
            SELECT id
            FROM cashmatic_movements
            WHERE TRIM(COALESCE(cashmatic_id, '')) = ?
            LIMIT 1
            """,
            (cashmatic_id,),
        ).fetchone()

        if existing:
            return False

    # Fallback para filas sin cashmatic_id.
    existing = conn.execute(
        "SELECT id FROM cashmatic_movements WHERE row_hash = ? LIMIT 1",
        (canonical_row_hash,),
    ).fetchone()

    # Regla crítica:
    # Si el movimiento ya existe, NO se actualiza la fila.
    # Esto preserva conciliaciones manuales y todos los campos linked_*:
    # cliente, expediente, cobro, gasto, importe vinculado, notas y estado.
    if existing:
        return False

    conn.execute(
        """
        INSERT OR IGNORE INTO cashmatic_movements (
            batch_id,
            row_number,
            row_hash,
            cashmatic_id,
            operation,
            result,
            end_type,
            movement_status,
            requested_centimos,
            inserted_centimos,
            dispensed_centimos,
            not_dispensed_centimos,
            net_amount_centimos,
            currency,
            start_time,
            end_time,
            source_raw,
            reason_raw,
            reference_raw,
            user_username,
            candidate_payment,
            warnings_json,

            linked_client_id,
            linked_expedient_id,
            linked_payment_id,
            linked_by_user_id,
            linked_at,
            link_notes,

            review_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?)
        """,
        (
            batch_id,
            row.row_number,
            canonical_row_hash,
            row.cashmatic_id,
            row.operation,
            row.result,
            row.end_type,
            row.status,
            row.requested_centimos,
            row.inserted_centimos,
            row.dispensed_centimos,
            row.not_dispensed_centimos,
            row.net_amount_centimos,
            row.currency,
            row.start_time,
            row.end_time,
            row.source_raw,
            row.reason_raw,
            row.reference_raw,
            row.user_username,
            1 if row.candidate_payment else 0,
            json.dumps(row.warnings, ensure_ascii=False),
            "PENDING_MANUAL_REVIEW",
        ),
    )

    return conn.total_changes > before


def import_cashmatic_file(
    file_path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
    ensure_db_schema: bool = True,
) -> CashmaticImportResult:
    report, rows = diagnose_cashmatic_file(file_path)

    with connect(db_path) as conn:
        if ensure_db_schema:
            ensure_schema(conn)

        batch_id, batch_created = _insert_or_get_batch(conn, report)

        inserted_rows = 0
        duplicate_rows = 0

        for row in rows:
            inserted = _insert_movement(conn, batch_id, row)
            if inserted:
                inserted_rows += 1
            else:
                duplicate_rows += 1

        conn.commit()

    return CashmaticImportResult(
        db_path=str(db_path),
        file_path=str(file_path),
        file_sha256=report.file_sha256,
        batch_id=batch_id,
        batch_created=batch_created,
        total_rows=len(rows),
        inserted_rows=inserted_rows,
        duplicate_rows=duplicate_rows,
        candidate_payment_rows=report.candidate_payment_rows,
        quarantine_rows=report.quarantine_rows,
        manual_linking_policy=(
            "La vinculación con cliente, expediente o cobro NO es automática. "
            "Todos los campos linked_* quedan NULL tras la importación."
        ),
    )


def get_cashmatic_import_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        ensure_schema(conn)

        batches = conn.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COALESCE(SUM(total_rows), 0) AS total_rows,
                COALESCE(SUM(candidate_payment_rows), 0) AS candidate_payment_rows,
                COALESCE(SUM(quarantine_rows), 0) AS quarantine_rows
            FROM economic_import_batches
            WHERE source_type = 'CASHMATIC'
            """
        ).fetchone()

        movements_by_status = conn.execute(
            """
            SELECT movement_status, COUNT(*) AS total
            FROM cashmatic_movements
            GROUP BY movement_status
            ORDER BY movement_status
            """
        ).fetchall()

        manual_links = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM cashmatic_movements
            WHERE linked_client_id IS NOT NULL
               OR linked_expedient_id IS NOT NULL
               OR linked_payment_id IS NOT NULL
            """
        ).fetchone()

        return {
            "batches": dict(batches or {}),
            "movements_by_status": [dict(row) for row in movements_by_status],
            "manual_links_total": int((manual_links or {"total": 0})["total"]),
        }

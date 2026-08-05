"""
Persistencia de documentos de prueba económica y propuestas de nómina.

Este servicio:
- guarda un PDF contenedor por expediente;
- guarda varias nóminas por documento;
- evita duplicados por expediente + sha256;
- no aplica importes al diagnóstico económico.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "20260804_create_expedient_payroll_proposals.sql"
)

VALID_REVIEW_STATUSES = {
    "PENDIENTE_REVISION",
    "CONFIRMADA",
    "DESCARTADA",
    "APLICADA",
}

_SCHEMA_READY_PATHS = set()
_SCHEMA_LOCK = Lock()


def _json_dumps(value):
    return json.dumps(
        value,
        ensure_ascii=False,
    )


def _json_loads(value, default=None):
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def _connect(
    db_path=DEFAULT_DB_PATH,
):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(
        "PRAGMA foreign_keys = ON"
    )
    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )
    return conn


@contextmanager
def _connection(
    db_path=DEFAULT_DB_PATH,
):
    conn = _connect(db_path)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _schema_cache_key(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    raw_path = ""

    if conn is not None:
        try:
            rows = conn.execute(
                "PRAGMA database_list"
            ).fetchall()

            for row in rows:
                if str(row[1] or "") == "main":
                    raw_path = str(
                        row[2] or ""
                    )
                    break
        except Exception:
            raw_path = ""
    else:
        raw_path = str(
            db_path or ""
        )

    if not raw_path or raw_path == ":memory:":
        return None

    return str(
        Path(raw_path).resolve()
    )


def ensure_schema(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    cache_key = _schema_cache_key(
        conn,
        db_path,
    )

    if (
        cache_key
        and cache_key in _SCHEMA_READY_PATHS
    ):
        return

    with _SCHEMA_LOCK:
        if (
            cache_key
            and cache_key in _SCHEMA_READY_PATHS
        ):
            return

        owns_connection = conn is None
        connection = conn or _connect(
            db_path
        )

        try:
            if not MIGRATION_PATH.exists():
                raise FileNotFoundError(
                    "No existe la migración: "
                    f"{MIGRATION_PATH}"
                )

            connection.executescript(
                MIGRATION_PATH.read_text(
                    encoding="utf-8"
                )
            )

            if owns_connection:
                connection.commit()

            if cache_key:
                _SCHEMA_READY_PATHS.add(
                    cache_key
                )
        finally:
            if owns_connection:
                connection.close()


def _document_row_to_dict(row):
    if not row:
        return None

    data = dict(row)

    data["unclassified_pages"] = (
        _json_loads(
            data.get(
                "unclassified_pages_json"
            ),
            [],
        )
    )
    data["warnings"] = _json_loads(
        data.get("warnings_json"),
        [],
    )
    data["raw_extraction"] = _json_loads(
        data.get("raw_extraction_json"),
        {},
    )

    return data


def _proposal_row_to_dict(row):
    if not row:
        return None

    data = dict(row)

    data["source_pages"] = _json_loads(
        data.get("source_pages_json"),
        [],
    )
    data["field_confidence"] = (
        _json_loads(
            data.get(
                "field_confidence_json"
            ),
            {},
        )
    )
    data["warnings"] = _json_loads(
        data.get("warnings_json"),
        [],
    )
    data["raw_extraction"] = _json_loads(
        data.get("raw_extraction_json"),
        {},
    )

    return data


def _require_expedient(
    conn,
    expediente_id,
):
    row = conn.execute(
        """
        SELECT id
        FROM expedientes
        WHERE id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No existe el expediente indicado"
        )


def get_document(
    document_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM expedient_income_evidence_documents
            WHERE id = ?
            """,
            (int(document_id),),
        ).fetchone()

    return _document_row_to_dict(row)


def get_document_by_hash(
    expediente_id,
    sha256,
    *,
    db_path=DEFAULT_DB_PATH,
):
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM expedient_income_evidence_documents
            WHERE expediente_id = ?
              AND sha256 = ?
            """,
            (
                int(expediente_id),
                str(sha256 or "").strip(),
            ),
        ).fetchone()

    return _document_row_to_dict(row)


def list_document_proposals(
    document_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM expedient_payroll_proposals
            WHERE document_id = ?
            ORDER BY sequence, id
            """,
            (int(document_id),),
        ).fetchall()

    return [
        _proposal_row_to_dict(row)
        for row in rows
    ]


def list_expedient_documents(
    expediente_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM expedient_income_evidence_documents
            WHERE expediente_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(expediente_id),),
        ).fetchall()

    return [
        _document_row_to_dict(row)
        for row in rows
    ]


def persist_payroll_bundle(
    expediente_id,
    bundle,
    *,
    db_path=DEFAULT_DB_PATH,
):
    bundle = dict(bundle or {})

    sha256 = str(
        bundle.get("sha256") or ""
    ).strip()

    if not sha256:
        raise ValueError(
            "El bundle debe incluir sha256"
        )

    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        _require_expedient(
            conn,
            expediente_id,
        )

        existing = conn.execute(
            """
            SELECT *
            FROM expedient_income_evidence_documents
            WHERE expediente_id = ?
              AND sha256 = ?
            """,
            (
                int(expediente_id),
                sha256,
            ),
        ).fetchone()

        if existing:
            document = (
                _document_row_to_dict(existing)
            )
            document["already_exists"] = True
            document["proposals"] = (
                list_document_proposals(
                    document["id"],
                    db_path=db_path,
                )
            )
            return document

        cursor = conn.execute(
            """
            INSERT INTO expedient_income_evidence_documents (
                expediente_id,
                source_path,
                source_name,
                source_suffix,
                sha256,
                page_count,
                pages_with_text,
                payroll_count,
                extraction_status,
                requires_ocr,
                requires_manual_review,
                unclassified_pages_json,
                warnings_json,
                raw_extraction_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                int(expediente_id),
                str(
                    bundle.get(
                        "source_path"
                    )
                    or ""
                ),
                str(
                    bundle.get(
                        "source_name"
                    )
                    or ""
                ),
                str(
                    bundle.get(
                        "source_suffix"
                    )
                    or ""
                ),
                sha256,
                int(
                    bundle.get(
                        "page_count"
                    )
                    or 0
                ),
                int(
                    bundle.get(
                        "pages_with_text"
                    )
                    or 0
                ),
                int(
                    bundle.get(
                        "payroll_count"
                    )
                    or 0
                ),
                str(
                    bundle.get("status")
                    or "PENDIENTE_REVISION"
                ),
                1
                if bundle.get(
                    "requires_ocr"
                )
                else 0,
                1
                if bundle.get(
                    "requires_manual_review",
                    True,
                )
                else 0,
                _json_dumps(
                    bundle.get(
                        "unclassified_pages"
                    )
                    or []
                ),
                _json_dumps(
                    bundle.get("warnings")
                    or []
                ),
                _json_dumps(bundle),
            ),
        )

        document_id = int(
            cursor.lastrowid
        )

        for position, payroll in enumerate(
            bundle.get("payrolls") or [],
            start=1,
        ):
            payroll = dict(payroll or {})

            sequence = int(
                payroll.get("sequence")
                or position
            )

            conn.execute(
                """
                INSERT INTO expedient_payroll_proposals (
                    document_id,
                    sequence,
                    source_page_start,
                    source_page_end,
                    source_pages_json,
                    period_year,
                    period_month,
                    period_key,
                    employee_name,
                    employee_identity,
                    company_name,
                    company_tax_id,
                    total_accrued_centimos,
                    total_deductions_centimos,
                    net_pay_centimos,
                    contribution_base_centimos,
                    irpf_centimos,
                    confidence,
                    field_confidence_json,
                    warnings_json,
                    raw_extraction_json,
                    review_status,
                    requires_manual_review
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    document_id,
                    sequence,
                    payroll.get(
                        "source_page_start"
                    ),
                    payroll.get(
                        "source_page_end"
                    ),
                    _json_dumps(
                        payroll.get(
                            "source_pages"
                        )
                        or []
                    ),
                    payroll.get(
                        "period_year"
                    ),
                    payroll.get(
                        "period_month"
                    ),
                    str(
                        payroll.get(
                            "period_key"
                        )
                        or ""
                    ),
                    str(
                        payroll.get(
                            "employee_name"
                        )
                        or ""
                    ),
                    str(
                        payroll.get(
                            "employee_identity"
                        )
                        or ""
                    ),
                    str(
                        payroll.get(
                            "company_name"
                        )
                        or ""
                    ),
                    str(
                        payroll.get(
                            "company_tax_id"
                        )
                        or ""
                    ),
                    payroll.get(
                        "total_accrued_centimos"
                    ),
                    payroll.get(
                        "total_deductions_centimos"
                    ),
                    payroll.get(
                        "net_pay_centimos"
                    ),
                    payroll.get(
                        "contribution_base_centimos"
                    ),
                    payroll.get(
                        "irpf_centimos"
                    ),
                    float(
                        payroll.get(
                            "confidence"
                        )
                        or 0
                    ),
                    _json_dumps(
                        payroll.get(
                            "field_confidence"
                        )
                        or {}
                    ),
                    _json_dumps(
                        payroll.get(
                            "warnings"
                        )
                        or []
                    ),
                    _json_dumps(payroll),
                    str(
                        payroll.get(
                            "review_status"
                        )
                        or "PENDIENTE_REVISION"
                    ),
                    1
                    if payroll.get(
                        "requires_manual_review",
                        True,
                    )
                    else 0,
                ),
            )

    document = get_document(
        document_id,
        db_path=db_path,
    )
    document["already_exists"] = False
    document["proposals"] = (
        list_document_proposals(
            document_id,
            db_path=db_path,
        )
    )

    return document


def delete_payroll_document(
    document_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    """
    Elimina un PDF de nóminas registrado y sus propuestas.

    No elimina el archivo físico. La eliminación se rechaza
    cuando alguna propuesta está aplicada o participa en una
    aplicación económica activa.
    """
    ensure_schema(db_path=db_path)

    with _connection(db_path) as conn:
        document = conn.execute(
            """
            SELECT *
            FROM expedient_income_evidence_documents
            WHERE id = ?
            """,
            (int(document_id),),
        ).fetchone()

        if not document:
            raise ValueError(
                "No existe el documento de nóminas"
            )

        applied_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM expedient_payroll_proposals
            WHERE document_id = ?
              AND review_status = 'APLICADA'
            """,
            (int(document_id),),
        ).fetchone()[0]

        if int(applied_count or 0) > 0:
            raise ValueError(
                "No se puede eliminar el PDF porque "
                "contiene nóminas aplicadas. Revierte "
                "primero la aplicación económica."
            )

        proposal_ids = [
            int(row["id"])
            for row in conn.execute(
                """
                SELECT id
                FROM expedient_payroll_proposals
                WHERE document_id = ?
                """,
                (int(document_id),),
            ).fetchall()
        ]

        if proposal_ids:
            application_table = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'expedient_payroll_applications'
                """
            ).fetchone()

            if application_table:
                active_rows = conn.execute(
                    """
                    SELECT id, proposal_ids_json
                    FROM expedient_payroll_applications
                    WHERE application_status = 'APPLIED'
                    """
                ).fetchall()

                proposal_id_set = set(proposal_ids)

                for row in active_rows:
                    active_ids = set(
                        int(value)
                        for value in (
                            _json_loads(
                                row["proposal_ids_json"],
                                [],
                            )
                            or []
                        )
                    )

                    if proposal_id_set & active_ids:
                        raise ValueError(
                            "No se puede eliminar el PDF porque "
                            "sus nóminas participan en una "
                            "aplicación económica activa."
                        )

        proposal_count = len(proposal_ids)
        document_data = _document_row_to_dict(
            document
        )

        conn.execute(
            """
            DELETE FROM expedient_income_evidence_documents
            WHERE id = ?
            """,
            (int(document_id),),
        )

    return {
        "deleted": True,
        "document_id": int(document_id),
        "expediente_id": int(
            document_data["expediente_id"]
        ),
        "source_name": (
            document_data.get("source_name")
            or ""
        ),
        "deleted_proposal_count": proposal_count,
        "physical_file_deleted": False,
    }

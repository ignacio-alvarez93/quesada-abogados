"""
Persistencia y recuperación de resultados de inteligencia documental.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .document_page_result import (
    DocumentPageResult,
)
from .document_text_result import (
    DocumentTextResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "20260804_create_document_intelligence_cache.sql"
)


def _json_dumps(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _json_loads(value, default):
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
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
    db_path: str | Path = DEFAULT_DB_PATH,
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


def ensure_schema(
    conn=None,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(
            f"No existe la migración: {MIGRATION_PATH}"
        )

    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        connection.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def _page_row_to_result(row):
    return DocumentPageResult(
        page_number=row["page_number"],
        text=row["text"],
        text_source=row["text_source"],
        confidence=row["confidence"],
        requires_ocr=bool(
            row["requires_ocr"]
        ),
        rotation=row["rotation"],
        language=row["language"] or "",
        warnings=_json_loads(
            row["warnings_json"],
            [],
        ),
        metadata=_json_loads(
            row["metadata_json"],
            {},
        ),
    )


def _run_to_result(
    run_row,
    page_rows,
):
    if not run_row:
        return None

    return DocumentTextResult(
        status=run_row["status"],
        source_path=run_row["source_path"],
        source_name=run_row["source_name"],
        source_suffix=run_row["source_suffix"],
        sha256=run_row["source_sha256"],
        mime_type=run_row["mime_type"] or "",
        pages=[
            _page_row_to_result(row)
            for row in page_rows
        ],
        warnings=_json_loads(
            run_row["warnings_json"],
            [],
        ),
        errors=_json_loads(
            run_row["errors_json"],
            [],
        ),
        metadata={
            **_json_loads(
                run_row["metadata_json"],
                {},
            ),
            "cache": {
                "run_id": run_row["id"],
                "pipeline_version": (
                    run_row["pipeline_version"]
                ),
                "native_extractor": (
                    run_row["native_extractor"]
                ),
                "ocr_engine": (
                    run_row["ocr_engine"]
                ),
                "ocr_engine_version": (
                    run_row["ocr_engine_version"]
                ),
                "ocr_language": (
                    run_row["ocr_language"]
                ),
                "render_dpi": (
                    run_row["render_dpi"]
                ),
                "policy_fingerprint": (
                    run_row["policy_fingerprint"]
                ),
                "cache_hit": True,
            },
        },
    )


def get_cached_result(
    *,
    source_sha256,
    pipeline_version,
    native_extractor,
    ocr_engine,
    ocr_engine_version,
    ocr_language,
    render_dpi,
    policy_fingerprint,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    ensure_schema(
        db_path=db_path
    )

    with _connection(db_path) as conn:
        run_row = conn.execute(
            """
            SELECT *
            FROM document_intelligence_runs
            WHERE source_sha256 = ?
              AND pipeline_version = ?
              AND native_extractor = ?
              AND ocr_engine = ?
              AND ocr_engine_version = ?
              AND ocr_language = ?
              AND render_dpi = ?
              AND policy_fingerprint = ?
            """,
            (
                str(source_sha256),
                str(pipeline_version),
                str(native_extractor),
                str(ocr_engine),
                str(ocr_engine_version),
                str(ocr_language),
                int(render_dpi),
                str(policy_fingerprint),
            ),
        ).fetchone()

        if not run_row:
            return None

        page_rows = conn.execute(
            """
            SELECT *
            FROM document_intelligence_pages
            WHERE run_id = ?
            ORDER BY page_number
            """,
            (int(run_row["id"]),),
        ).fetchall()

    return _run_to_result(
        run_row,
        page_rows,
    )


def persist_result(
    document_result: DocumentTextResult,
    *,
    pipeline_version,
    native_extractor,
    ocr_engine,
    ocr_engine_version,
    ocr_language,
    render_dpi,
    policy_fingerprint,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    if not isinstance(
        document_result,
        DocumentTextResult,
    ):
        raise TypeError(
            "document_result debe ser "
            "DocumentTextResult"
        )

    if not document_result.sha256:
        raise ValueError(
            "El resultado documental debe incluir sha256"
        )

    ensure_schema(
        db_path=db_path
    )

    with _connection(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM document_intelligence_runs
            WHERE source_sha256 = ?
              AND pipeline_version = ?
              AND native_extractor = ?
              AND ocr_engine = ?
              AND ocr_engine_version = ?
              AND ocr_language = ?
              AND render_dpi = ?
              AND policy_fingerprint = ?
            """,
            (
                document_result.sha256,
                str(pipeline_version),
                str(native_extractor),
                str(ocr_engine),
                str(ocr_engine_version),
                str(ocr_language),
                int(render_dpi),
                str(policy_fingerprint),
            ),
        ).fetchone()

        if existing:
            run_id = int(existing["id"])

            conn.execute(
                """
                DELETE FROM document_intelligence_pages
                WHERE run_id = ?
                """,
                (run_id,),
            )

            conn.execute(
                """
                UPDATE document_intelligence_runs
                SET source_path = ?,
                    source_name = ?,
                    source_suffix = ?,
                    mime_type = ?,
                    status = ?,
                    page_count = ?,
                    native_text_pages = ?,
                    ocr_text_pages = ?,
                    requires_ocr = ?,
                    warnings_json = ?,
                    errors_json = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    document_result.source_path,
                    document_result.source_name,
                    document_result.source_suffix,
                    document_result.mime_type,
                    document_result.status,
                    document_result.page_count,
                    document_result.native_text_pages,
                    document_result.ocr_text_pages,
                    int(
                        document_result.requires_ocr
                    ),
                    _json_dumps(
                        document_result.warnings
                    ),
                    _json_dumps(
                        document_result.errors
                    ),
                    _json_dumps(
                        document_result.metadata
                    ),
                    run_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO document_intelligence_runs (
                    source_sha256,
                    source_path,
                    source_name,
                    source_suffix,
                    mime_type,
                    pipeline_version,
                    native_extractor,
                    ocr_engine,
                    ocr_engine_version,
                    ocr_language,
                    render_dpi,
                    policy_fingerprint,
                    status,
                    page_count,
                    native_text_pages,
                    ocr_text_pages,
                    requires_ocr,
                    warnings_json,
                    errors_json,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    document_result.sha256,
                    document_result.source_path,
                    document_result.source_name,
                    document_result.source_suffix,
                    document_result.mime_type,
                    str(pipeline_version),
                    str(native_extractor),
                    str(ocr_engine),
                    str(ocr_engine_version),
                    str(ocr_language),
                    int(render_dpi),
                    str(policy_fingerprint),
                    document_result.status,
                    document_result.page_count,
                    document_result.native_text_pages,
                    document_result.ocr_text_pages,
                    int(
                        document_result.requires_ocr
                    ),
                    _json_dumps(
                        document_result.warnings
                    ),
                    _json_dumps(
                        document_result.errors
                    ),
                    _json_dumps(
                        document_result.metadata
                    ),
                ),
            )

            run_id = int(
                cursor.lastrowid
            )

        for page in document_result.pages:
            conn.execute(
                """
                INSERT INTO document_intelligence_pages (
                    run_id,
                    page_number,
                    text,
                    text_source,
                    confidence,
                    requires_ocr,
                    rotation,
                    language,
                    warnings_json,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    page.page_number,
                    page.text,
                    page.text_source,
                    page.confidence,
                    int(page.requires_ocr),
                    page.rotation,
                    page.language,
                    _json_dumps(
                        page.warnings
                    ),
                    _json_dumps(
                        page.metadata
                    ),
                ),
            )

    return get_cached_result(
        source_sha256=document_result.sha256,
        pipeline_version=pipeline_version,
        native_extractor=native_extractor,
        ocr_engine=ocr_engine,
        ocr_engine_version=ocr_engine_version,
        ocr_language=ocr_language,
        render_dpi=render_dpi,
        policy_fingerprint=policy_fingerprint,
        db_path=db_path,
    )


def delete_cached_result(
    run_id,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    ensure_schema(
        db_path=db_path
    )

    with _connection(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM document_intelligence_runs
            WHERE id = ?
            """,
            (int(run_id),),
        )

        return cursor.rowcount > 0

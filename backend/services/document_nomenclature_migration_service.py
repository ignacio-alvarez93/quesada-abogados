"""
Migración de nomenclaturas documentales legacy al catálogo canónico.

Características:
- no modifica config_nomenclaturas_documentales;
- conserva tipo, subtipo, patrón, extensión y estado;
- resuelve el documento legacy contra config_documentos_catalogo;
- conserva el ámbito NULL del subtipo;
- registra origen_legacy_id;
- es idempotente;
- no toca Box.
"""

import sqlite3
from pathlib import Path

from backend.services import (
    document_requirement_legacy_migration_service
    as document_migration,
)


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_canonical_document_nomenclatures.sql"
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _legacy_rows(conn):
    return conn.execute(
        """
        SELECT
            n.id AS nomenclatura_legacy_id,
            n.documento_id AS documento_legacy_id,
            n.tipo_expediente_id,
            n.subtipo_expediente_id,
            n.patron_nombre,
            n.extension_permitida,
            n.activo,
            d.codigo_documento,
            d.nombre_documento
        FROM config_nomenclaturas_documentales n
        LEFT JOIN config_documentos_requeridos d
          ON d.id = n.documento_id
        ORDER BY n.id
        """
    ).fetchall()


def _normalize_extensions(value):
    raw = str(
        value or "pdf,jpg,jpeg,png"
    ).lower().replace(";", ",")

    values = []

    for item in raw.split(","):
        extension = item.strip().lstrip(".")

        if extension and extension not in values:
            values.append(extension)

    return ",".join(values) or "pdf,jpg,jpeg,png"


def _resolve_canonical_document(conn, row):
    if row["codigo_documento"] is None:
        raise ValueError(
            "La nomenclatura legacy "
            f"#{row['nomenclatura_legacy_id']} "
            "no tiene documento legacy asociado"
        )

    canonical = (
        document_migration
        ._canonical_definition(
            {
                "codigo_documento": row[
                    "codigo_documento"
                ],
                "nombre_documento": row[
                    "nombre_documento"
                ],
            }
        )
    )

    catalog_row = conn.execute(
        """
        SELECT id, codigo
        FROM config_documentos_catalogo
        WHERE codigo = ?
        """,
        (canonical["codigo"],),
    ).fetchone()

    if not catalog_row:
        raise ValueError(
            "No existe el documento canónico "
            f"{canonical['codigo']} para la nomenclatura "
            f"legacy #{row['nomenclatura_legacy_id']}"
        )

    return {
        "documento_catalogo_id": int(
            catalog_row["id"]
        ),
        "codigo_canonico": catalog_row["codigo"],
        "rol_documental": canonical[
            "rol_documental"
        ],
    }


def preview_nomenclature_migration():
    conn = _connect()

    try:
        preview = []

        for row in _legacy_rows(conn):
            canonical = _resolve_canonical_document(
                conn,
                row,
            )

            preview.append(
                {
                    "nomenclatura_legacy_id": int(
                        row["nomenclatura_legacy_id"]
                    ),
                    "documento_legacy_id": int(
                        row["documento_legacy_id"]
                    ),
                    "codigo_legacy": row[
                        "codigo_documento"
                    ],
                    "documento_catalogo_id": canonical[
                        "documento_catalogo_id"
                    ],
                    "codigo_canonico": canonical[
                        "codigo_canonico"
                    ],
                    "tipo_expediente_id": int(
                        row["tipo_expediente_id"]
                    ),
                    "subtipo_expediente_id": (
                        int(row["subtipo_expediente_id"])
                        if row["subtipo_expediente_id"]
                        is not None
                        else None
                    ),
                    "rol_documental": canonical[
                        "rol_documental"
                    ],
                    "patron_nombre": str(
                        row["patron_nombre"]
                    ).strip(),
                    "extension_permitida":
                        _normalize_extensions(
                            row["extension_permitida"]
                        ),
                    "activo": int(row["activo"] or 0),
                }
            )

        return preview

    finally:
        conn.close()


def migrate_document_nomenclatures():
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"No existe el esquema: {SCHEMA_PATH}"
        )

    conn = _connect()

    try:
        conn.executescript(
            SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )

        summary = {
            "legacy_rows": 0,
            "created": 0,
            "reused": 0,
            "updated": 0,
        }

        rows = _legacy_rows(conn)
        summary["legacy_rows"] = len(rows)

        for row in rows:
            canonical = _resolve_canonical_document(
                conn,
                row,
            )

            legacy_id = int(
                row["nomenclatura_legacy_id"]
            )
            tipo_id = int(
                row["tipo_expediente_id"]
            )
            subtipo_id = (
                int(row["subtipo_expediente_id"])
                if row["subtipo_expediente_id"]
                is not None
                else None
            )
            role = canonical["rol_documental"]
            pattern = str(
                row["patron_nombre"]
            ).strip()
            extensions = _normalize_extensions(
                row["extension_permitida"]
            )
            active = int(row["activo"] or 0)

            existing = conn.execute(
                """
                SELECT *
                FROM config_nomenclaturas_catalogo
                WHERE origen_legacy_id = ?
                """,
                (legacy_id,),
            ).fetchone()

            values = (
                canonical["documento_catalogo_id"],
                tipo_id,
                subtipo_id,
                role,
                pattern,
                extensions,
                active,
            )

            if existing:
                changed = any(
                    [
                        int(
                            existing[
                                "documento_catalogo_id"
                            ]
                        )
                        != values[0],
                        int(
                            existing[
                                "tipo_expediente_id"
                            ]
                        )
                        != values[1],
                        existing[
                            "subtipo_expediente_id"
                        ]
                        != values[2],
                        (
                            existing["rol_documental"]
                            or None
                        )
                        != values[3],
                        existing["patron_nombre"]
                        != values[4],
                        existing[
                            "extension_permitida"
                        ]
                        != values[5],
                        int(existing["activo"])
                        != values[6],
                    ]
                )

                conn.execute(
                    """
                    UPDATE config_nomenclaturas_catalogo
                    SET
                        documento_catalogo_id = ?,
                        tipo_expediente_id = ?,
                        subtipo_expediente_id = ?,
                        rol_documental = ?,
                        patron_nombre = ?,
                        extension_permitida = ?,
                        activo = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    values + (int(existing["id"]),),
                )

                summary[
                    "updated"
                    if changed
                    else "reused"
                ] += 1
                continue

            conn.execute(
                """
                INSERT INTO config_nomenclaturas_catalogo (
                    documento_catalogo_id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    rol_documental,
                    patron_nombre,
                    extension_permitida,
                    prioridad,
                    activo,
                    origen_legacy_id
                )
                VALUES (?, ?, ?, ?, ?, ?, 100, ?, ?)
                """,
                values + (legacy_id,),
            )

            summary["created"] += 1

        conn.commit()
        return summary

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

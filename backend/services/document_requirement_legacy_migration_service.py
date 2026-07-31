"""
Migración del modelo legacy de documentos requeridos al modelo
agrupado y canónico.

Características:
- no elimina ni modifica datos legacy;
- no toca tablas, rutas o inventarios de Box;
- deduplica documentos canónicos;
- conserva tipo, subtipo, obligatoriedad, orden y estado;
- traduce variantes por persona a roles documentales;
- es idempotente.
"""

import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_grouped_document_requirements.sql"
)


CANONICAL_OVERRIDES = {
    "AAPP": {
        "codigo": "ANTECEDENTES_PENALES",
        "nombre": "ANTECEDENTES PENALES",
        "categoria": "ANTECEDENTES",
    },
    "ACTA_DE_NACIMIENTO_DEL_PAIS_DE_ORIGEN": {
        "codigo": "ACTA_NACIMIENTO",
        "nombre": "ACTA DE NACIMIENTO",
        "categoria": "ESTADO_CIVIL",
        "rol": "SOLICITANTE",
    },
    "ACTA_DE_NACIMIENTO_DE_LOS_HIJOS_MENORES_DE_EDAD": {
        "codigo": "ACTA_NACIMIENTO",
        "nombre": "ACTA DE NACIMIENTO",
        "categoria": "ESTADO_CIVIL",
        "rol": "HIJOS_MENORES",
    },
    "ACTA_DE_NACIMIENTO": {
        "codigo": "ACTA_NACIMIENTO",
        "nombre": "ACTA DE NACIMIENTO",
        "categoria": "ESTADO_CIVIL",
        "rol": "SOLICITANTE",
    },
    "PASAPORTE_REAGRUPANTE": {
        "codigo": "PASAPORTE",
        "nombre": "PASAPORTE",
        "categoria": "IDENTIDAD",
        "rol": "REAGRUPANTE",
    },
    "PASAPORTE_REAGRUPADO": {
        "codigo": "PASAPORTE",
        "nombre": "PASAPORTE",
        "categoria": "IDENTIDAD",
        "rol": "REAGRUPADO",
    },
    "PASAPORTE": {
        "codigo": "PASAPORTE",
        "nombre": "PASAPORTE",
        "categoria": "IDENTIDAD",
        "rol": "TITULAR",
    },
    "NIE_REAGRUPANTE": {
        "codigo": "NIE",
        "nombre": "NIE",
        "categoria": "IDENTIDAD",
        "rol": "REAGRUPANTE",
    },
    "NIE": {
        "codigo": "NIE",
        "nombre": "NIE",
        "categoria": "IDENTIDAD",
        "rol": "TITULAR",
    },
    "DNI_DE_REPRESENTANTE": {
        "codigo": "DNI",
        "nombre": "DNI",
        "categoria": "IDENTIDAD",
        "rol": "REPRESENTANTE",
    },
    "PODER_O_MANDATO_ACREDITATIVO_DE_REPRESENTACION": {
        "codigo": "PODER_REPRESENTACION",
        "nombre": "PODER O MANDATO DE REPRESENTACIÓN",
        "categoria": "REPRESENTACION",
        "rol": "REPRESENTANTE",
    },
    "PODER": {
        "codigo": "PODER_REPRESENTACION",
        "nombre": "PODER O MANDATO DE REPRESENTACIÓN",
        "categoria": "REPRESENTACION",
        "rol": "REPRESENTANTE",
    },
    "EMPADRONAMIENTO": {
        "codigo": "EMPADRONAMIENTO",
        "nombre": "EMPADRONAMIENTO",
        "categoria": "DOMICILIO",
        "rol": "TITULAR",
    },
    "EMPADRONAMIENTO_CONJUNTO": {
        "codigo": "EMPADRONAMIENTO_CONJUNTO",
        "nombre": "EMPADRONAMIENTO CONJUNTO",
        "categoria": "DOMICILIO",
    },
    "MEDIOS_ECONOMICOS": {
        "codigo": "ACREDITACION_MEDIOS_ECONOMICOS",
        "nombre": "ACREDITACIÓN DE MEDIOS ECONÓMICOS",
        "categoria": "LEGACY_AGGREGATE",
    },
    "PRUEBAS_DE_PERMANENCIA": {
        "codigo": "ACREDITACION_PERMANENCIA",
        "nombre": "ACREDITACIÓN DE PERMANENCIA",
        "categoria": "LEGACY_AGGREGATE",
    },
}


CATEGORY_BY_CODE = {
    "CCSE": "NACIONALIDAD",
    "DELE": "NACIONALIDAD",
    "TASA_790016": "TASA",
    "CONTRATO": "LABORAL",
    "INFORME_DE_VULNERABILIDAD": "INFORME",
    "SEGURO_DE_SALUD": "SEGURO",
    "CERTIFICADO_MATRIMONIO": "ESTADO_CIVIL",
    "INFORME_DE_VIVIENDA": "VIVIENDA",
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalize_code(value):
    return (
        str(value or "")
        .strip()
        .upper()
        .replace(" ", "_")
    )


def _normalize_name(value):
    return str(value or "").strip().upper()


def _legacy_rows(conn):
    return conn.execute(
        """
        SELECT
            d.id,
            d.codigo_documento,
            d.nombre_documento,
            d.tipo_expediente_id,
            d.subtipo_expediente_id,
            d.obligatorio,
            d.orden,
            d.activo
        FROM config_documentos_requeridos d
        ORDER BY d.id
        """
    ).fetchall()


def _canonical_definition(row):
    legacy_code = _normalize_code(row["codigo_documento"])
    override = CANONICAL_OVERRIDES.get(legacy_code, {})

    code = override.get("codigo") or legacy_code
    name = (
        override.get("nombre")
        or _normalize_name(row["nombre_documento"])
        or code.replace("_", " ")
    )
    category = (
        override.get("categoria")
        or CATEGORY_BY_CODE.get(legacy_code)
        or "OTROS"
    )
    role = override.get("rol")

    return {
        "codigo": code,
        "nombre": name,
        "categoria": category,
        "rol_documental": role,
    }


def preview_legacy_document_requirement_migration():
    """
    Devuelve la transformación prevista sin escribir en la base.
    """
    conn = _connect()
    try:
        rows = _legacy_rows(conn)
        preview = []

        for row in rows:
            canonical = _canonical_definition(row)
            preview.append(
                {
                    "legacy_id": int(row["id"]),
                    "legacy_codigo": row["codigo_documento"],
                    "tipo_expediente_id": int(
                        row["tipo_expediente_id"]
                    ),
                    "subtipo_expediente_id": (
                        int(row["subtipo_expediente_id"])
                        if row["subtipo_expediente_id"] is not None
                        else None
                    ),
                    "documento_codigo": canonical["codigo"],
                    "documento_nombre": canonical["nombre"],
                    "categoria": canonical["categoria"],
                    "rol_documental": canonical[
                        "rol_documental"
                    ],
                    "regla_cumplimiento": (
                        "ALL"
                        if int(row["obligatorio"] or 0) == 1
                        else "OPTIONAL"
                    ),
                    "activo": int(row["activo"] or 0),
                }
            )

        return preview
    finally:
        conn.close()


def _get_or_create_catalog_document(conn, canonical):
    row = conn.execute(
        """
        SELECT id
        FROM config_documentos_catalogo
        WHERE codigo = ?
        """,
        (canonical["codigo"],),
    ).fetchone()

    if row:
        conn.execute(
            """
            UPDATE config_documentos_catalogo
            SET
                nombre = ?,
                categoria = ?,
                activo = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                canonical["nombre"],
                canonical["categoria"],
                int(row["id"]),
            ),
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO config_documentos_catalogo (
            codigo,
            nombre,
            descripcion,
            categoria,
            activo
        )
        VALUES (?, ?, ?, ?, 1)
        """,
        (
            canonical["codigo"],
            canonical["nombre"],
            "Migrado desde configuración documental legacy",
            canonical["categoria"],
        ),
    )
    return int(cursor.lastrowid), True


def _legacy_group_code(row):
    legacy_code = _normalize_code(row["codigo_documento"])
    return f"LEGACY_REQ_{int(row['id'])}_{legacy_code}"


def _get_or_create_group(conn, row):
    code = _legacy_group_code(row)
    tipo_id = int(row["tipo_expediente_id"])
    subtipo_id = (
        int(row["subtipo_expediente_id"])
        if row["subtipo_expediente_id"] is not None
        else None
    )
    rule = (
        "ALL"
        if int(row["obligatorio"] or 0) == 1
        else "OPTIONAL"
    )
    minimum = 0 if rule == "OPTIONAL" else 1

    existing = conn.execute(
        """
        SELECT id
        FROM config_grupos_requisitos_documentales
        WHERE tipo_expediente_id = ?
          AND codigo = ?
          AND (
                subtipo_expediente_id = ?
                OR (
                    subtipo_expediente_id IS NULL
                    AND ? IS NULL
                )
          )
        """,
        (
            tipo_id,
            code,
            subtipo_id,
            subtipo_id,
        ),
    ).fetchone()

    values = (
        _normalize_name(row["nombre_documento"]),
        (
            "Migrado desde config_documentos_requeridos "
            f"#{int(row['id'])}"
        ),
        rule,
        minimum,
        int(row["orden"] or 0),
        int(row["activo"] or 0),
    )

    if existing:
        conn.execute(
            """
            UPDATE config_grupos_requisitos_documentales
            SET
                nombre = ?,
                descripcion = ?,
                regla_cumplimiento = ?,
                minimo_documentos = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values + (int(existing["id"]),),
        )
        return int(existing["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO config_grupos_requisitos_documentales (
            tipo_expediente_id,
            subtipo_expediente_id,
            codigo,
            nombre,
            descripcion,
            regla_cumplimiento,
            minimo_documentos,
            orden,
            activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tipo_id,
            subtipo_id,
            code,
        )
        + values,
    )
    return int(cursor.lastrowid), True


def _get_or_create_option(
    conn,
    group_id,
    document_id,
    canonical,
    row,
):
    role = canonical["rol_documental"]

    existing = conn.execute(
        """
        SELECT id
        FROM config_grupo_requisito_documentos
        WHERE grupo_id = ?
          AND documento_catalogo_id = ?
          AND COALESCE(rol_documental, '') =
              COALESCE(?, '')
        """,
        (
            int(group_id),
            int(document_id),
            role,
        ),
    ).fetchone()

    label = _normalize_name(row["nombre_documento"])
    description = (
        "Migrado desde requisito documental legacy "
        f"#{int(row['id'])}"
    )

    if existing:
        conn.execute(
            """
            UPDATE config_grupo_requisito_documentos
            SET
                etiqueta_requisito = ?,
                descripcion_requisito = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                label,
                description,
                int(row["orden"] or 0),
                int(row["activo"] or 0),
                int(existing["id"]),
            ),
        )
        return int(existing["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO config_grupo_requisito_documentos (
            grupo_id,
            documento_catalogo_id,
            rol_documental,
            etiqueta_requisito,
            descripcion_requisito,
            orden,
            activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(group_id),
            int(document_id),
            role,
            label,
            description,
            int(row["orden"] or 0),
            int(row["activo"] or 0),
        ),
    )
    return int(cursor.lastrowid), True


def migrate_legacy_document_requirements():
    """
    Copia la configuración legacy al nuevo modelo.

    No elimina ni modifica config_documentos_requeridos.
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"No existe el esquema agrupado: {SCHEMA_PATH}"
        )

    conn = _connect()
    try:
        conn.executescript(
            SCHEMA_PATH.read_text(encoding="utf-8")
        )

        summary = {
            "legacy_rows": 0,
            "catalog_created": 0,
            "catalog_reused": 0,
            "groups_created": 0,
            "groups_reused": 0,
            "options_created": 0,
            "options_reused": 0,
        }

        rows = _legacy_rows(conn)
        summary["legacy_rows"] = len(rows)

        for row in rows:
            canonical = _canonical_definition(row)

            document_id, created = (
                _get_or_create_catalog_document(
                    conn,
                    canonical,
                )
            )
            summary[
                "catalog_created"
                if created
                else "catalog_reused"
            ] += 1

            group_id, created = _get_or_create_group(
                conn,
                row,
            )
            summary[
                "groups_created"
                if created
                else "groups_reused"
            ] += 1

            _, created = _get_or_create_option(
                conn,
                group_id,
                document_id,
                canonical,
                row,
            )
            summary[
                "options_created"
                if created
                else "options_reused"
            ] += 1

        conn.commit()
        return summary

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

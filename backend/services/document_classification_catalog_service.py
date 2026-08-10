"""
Catálogo de clasificación documental contextual por expediente.

Responsabilidades:
- resolver tipo y subtipo del expediente;
- cargar nomenclaturas canónicas específicas;
- deduplicar patrones equivalentes a nivel documental;
- conservar el rol documental;
- añadir documentos procedimentales transversales;
- devolver opciones aptas para UI.

No modifica expedientes.
No modifica documentos.
No toca Box.
"""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260810_create_procedural_document_nomenclatures.sql"
)


@contextmanager
def _connection(
    db_path: str | Path = DEFAULT_DB_PATH,
):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
    finally:
        conn.close()


def _dict(row):
    return dict(row) if row else None


def ensure_schema(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(
            f"No existe la migración: {MIGRATION_PATH}"
        )

    with closing(
        sqlite3.connect(str(db_path))
    ) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )
        conn.commit()


def _get_expedient(
    conn,
    expediente_id,
):
    row = conn.execute(
        """
        SELECT
            e.id,
            e.tipo_expediente_id,
            e.subtipo_expediente_id,
            te.codigo AS tipo_codigo,
            te.nombre AS tipo_nombre,
            st.codigo AS subtipo_codigo,
            st.nombre AS subtipo_nombre
        FROM expedientes e
        LEFT JOIN config_tipos_expediente te
          ON te.id = e.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente st
          ON st.id = e.subtipo_expediente_id
        WHERE e.id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No existe el expediente indicado"
        )

    return _dict(row)


def _specific_options(
    conn,
    expediente,
):
    tipo_id = expediente.get(
        "tipo_expediente_id"
    )
    subtipo_id = expediente.get(
        "subtipo_expediente_id"
    )

    if not tipo_id:
        return []

    rows = conn.execute(
        """
        SELECT
            n.documento_catalogo_id,
            n.rol_documental,
            MIN(n.prioridad) AS prioridad,
            d.codigo,
            d.nombre,
            d.descripcion,
            d.categoria
        FROM config_nomenclaturas_catalogo n
        JOIN config_documentos_catalogo d
          ON d.id = n.documento_catalogo_id
        WHERE n.tipo_expediente_id = ?
          AND COALESCE(n.activo, 1) = 1
          AND COALESCE(d.activo, 1) = 1
          AND (
                n.subtipo_expediente_id IS NULL
                OR n.subtipo_expediente_id = ?
          )
        GROUP BY
            n.documento_catalogo_id,
            COALESCE(n.rol_documental, ''),
            d.codigo,
            d.nombre,
            d.descripcion,
            d.categoria
        ORDER BY
            MIN(n.prioridad),
            d.nombre,
            n.documento_catalogo_id
        """,
        (
            int(tipo_id),
            (
                int(subtipo_id)
                if subtipo_id
                else -1
            ),
        ),
    ).fetchall()

    result = []

    for row in rows:
        data = _dict(row)

        role = str(
            data.get("rol_documental")
            or ""
        ).strip()

        base_name = str(
            data.get("nombre")
            or data.get("codigo")
            or ""
        ).strip()

        label = (
            f"{base_name} · {role}"
            if role
            else base_name
        )

        result.append(
            {
                "documento_catalogo_id": int(
                    data["documento_catalogo_id"]
                ),
                "codigo": str(
                    data.get("codigo")
                    or ""
                ),
                "nombre": base_name,
                "label": label,
                "rol_documental": (
                    role or None
                ),
                "categoria": str(
                    data.get("categoria")
                    or ""
                ),
                "descripcion": str(
                    data.get("descripcion")
                    or ""
                ),
                "origen": "EXPEDIENTE",
                "prioridad": int(
                    data.get("prioridad")
                    or 100
                ),
            }
        )

    return result


def _procedural_options(
    conn,
):
    rows = conn.execute(
        """
        SELECT
            p.documento_catalogo_id,
            MIN(p.prioridad) AS prioridad,
            d.codigo,
            d.nombre,
            d.descripcion,
            d.categoria
        FROM config_nomenclaturas_procedimentales p
        JOIN config_documentos_catalogo d
          ON d.id = p.documento_catalogo_id
        WHERE COALESCE(p.activo, 1) = 1
          AND COALESCE(d.activo, 1) = 1
        GROUP BY
            p.documento_catalogo_id,
            d.codigo,
            d.nombre,
            d.descripcion,
            d.categoria
        ORDER BY
            MIN(p.prioridad),
            d.nombre,
            p.documento_catalogo_id
        """
    ).fetchall()

    result = []

    for row in rows:
        data = _dict(row)

        result.append(
            {
                "documento_catalogo_id": int(
                    data["documento_catalogo_id"]
                ),
                "codigo": str(
                    data.get("codigo")
                    or ""
                ),
                "nombre": str(
                    data.get("nombre")
                    or data.get("codigo")
                    or ""
                ),
                "label": str(
                    data.get("nombre")
                    or data.get("codigo")
                    or ""
                ),
                "rol_documental": None,
                "categoria": str(
                    data.get("categoria")
                    or ""
                ),
                "descripcion": str(
                    data.get("descripcion")
                    or ""
                ),
                "origen": "PROCEDIMIENTO",
                "prioridad": int(
                    data.get("prioridad")
                    or 100
                ),
            }
        )

    return result


def list_options_for_expedient(
    expediente_id,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    """
    Devuelve opciones de clasificación documental para un expediente.

    Orden:
    1. documentos específicos de tipo/subtipo;
    2. documentos procedimentales transversales.

    Las nomenclaturas específicas se deduplican por
    documento_catalogo_id + rol_documental.
    """

    ensure_schema(
        db_path=db_path,
    )

    with _connection(db_path) as conn:
        expediente = _get_expedient(
            conn,
            expediente_id,
        )

        specific = _specific_options(
            conn,
            expediente,
        )

        procedural = _procedural_options(
            conn,
        )

    return {
        "expediente": expediente,
        "specific": specific,
        "procedural": procedural,
        "options": [
            *specific,
            *procedural,
        ],
    }

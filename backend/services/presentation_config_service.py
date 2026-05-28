import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row):
    return dict(row) if row else None


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _safe_json_dict(raw):
    if not str(raw or "").strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _build_reglas_json(data):
    reglas = _safe_json_dict(data.get("reglas_json"))

    tipo_formulario = str(data.get("tipo_formulario_objetivo") or "").strip().upper()
    mapper_codigo = str(data.get("mapper_codigo") or "").strip().upper()

    if tipo_formulario:
        reglas["tipo_formulario_objetivo"] = tipo_formulario
    else:
        reglas.pop("tipo_formulario_objetivo", None)

    if mapper_codigo:
        reglas["mapper_codigo"] = mapper_codigo
    else:
        reglas.pop("mapper_codigo", None)

    return json.dumps(reglas, ensure_ascii=False) if reglas else None

def get_presentacion_config(tipo_id, subtipo_id=None):
    with _connect() as conn:
        if subtipo_id:
            row = conn.execute(
                "SELECT * FROM config_presentaciones_asistidas WHERE tipo_expediente_id=? AND subtipo_expediente_id=? AND activo=1",
                (tipo_id, subtipo_id)
            ).fetchone()
            if row:
                return dict(row)

        row = conn.execute(
            "SELECT * FROM config_presentaciones_asistidas WHERE tipo_expediente_id=? AND subtipo_expediente_id IS NULL AND activo=1",
            (tipo_id,)
        ).fetchone()

        return dict(row) if row else None


def get_presentacion_reglas(tipo_id, subtipo_id=None):
    """
    Devuelve reglas_json de config_presentaciones_asistidas como dict.

    Busca primero configuración específica tipo+subtipo.
    Si no existe, usa configuración general del tipo.
    Si no hay reglas_json válido, devuelve {}.
    """
    config = get_presentacion_config(tipo_id, subtipo_id=subtipo_id)
    if not config:
        return {}

    raw = config.get("reglas_json") or ""
    if not str(raw).strip():
        return {}

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

def list_presentacion_configs(active_only=False):
    sql = """
        SELECT
            p.*,
            t.nombre AS tipo_expediente_nombre,
            t.codigo AS tipo_expediente_codigo,
            s.nombre AS subtipo_expediente_nombre,
            s.codigo AS subtipo_expediente_codigo
        FROM config_presentaciones_asistidas p
        JOIN config_tipos_expediente t ON t.id = p.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s ON s.id = p.subtipo_expediente_id
    """
    params = []
    if active_only:
        sql += " WHERE p.activo = ?"
        params.append(1)
    sql += " ORDER BY t.nombre ASC, s.orden ASC, s.nombre ASC, p.nombre_configuracion ASC"

    with _connect() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]

    for row in rows:
        reglas = _safe_json_dict(row.get("reglas_json"))
        row["tipo_formulario_objetivo"] = reglas.get("tipo_formulario_objetivo") or ""
        row["mapper_codigo"] = reglas.get("mapper_codigo") or ""

    return rows


def get_presentacion_config_by_id(config_id):
    with _connect() as conn:
        row = _row_to_dict(
            conn.execute(
                "SELECT * FROM config_presentaciones_asistidas WHERE id = ?",
                (int(config_id),),
            ).fetchone()
        )

    if row:
        reglas = _safe_json_dict(row.get("reglas_json"))
        row["tipo_formulario_objetivo"] = reglas.get("tipo_formulario_objetivo") or ""
        row["mapper_codigo"] = reglas.get("mapper_codigo") or ""

    return row


def create_presentacion_config(data):
    reglas_json = _build_reglas_json(data)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_presentaciones_asistidas (
                tipo_expediente_id,
                subtipo_expediente_id,
                nombre_configuracion,
                url_presentacion,
                portal,
                flujo,
                reglas_json,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(data["tipo_expediente_id"]),
                _int_or_none(data.get("subtipo_expediente_id")),
                str(data.get("nombre_configuracion") or "").strip(),
                str(data.get("url_presentacion") or "").strip(),
                str(data.get("portal") or "MERCURIO").strip().upper(),
                str(data.get("flujo") or "").strip(),
                reglas_json,
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_presentacion_config(config_id, data):
    reglas_json = _build_reglas_json(data)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_presentaciones_asistidas
            SET tipo_expediente_id = ?,
                subtipo_expediente_id = ?,
                nombre_configuracion = ?,
                url_presentacion = ?,
                portal = ?,
                flujo = ?,
                reglas_json = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(data["tipo_expediente_id"]),
                _int_or_none(data.get("subtipo_expediente_id")),
                str(data.get("nombre_configuracion") or "").strip(),
                str(data.get("url_presentacion") or "").strip(),
                str(data.get("portal") or "MERCURIO").strip().upper(),
                str(data.get("flujo") or "").strip(),
                reglas_json,
                int(data.get("activo", 1)),
                int(config_id),
            ),
        )
        conn.commit()


def delete_presentacion_config(config_id):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM config_presentaciones_asistidas WHERE id = ?",
            (int(config_id),),
        )
        conn.commit()


def save_presentacion_config(data):
    return create_presentacion_config(data)


def seed_presentaciones_asistidas_defaults():
    """
    Inserta configuraciones base de presentación asistida Mercurio.

    No borra configuraciones existentes.
    No toca expedientes.
    No toca SeleniumBase.
    Solo garantiza mínimos conocidos para que el mapper pueda resolver
    formulario Mercurio objetivo desde config_presentaciones_asistidas.
    """
    defaults = [
        {
            "tipo_codigo": "REAGRUPACION_FAMILIAR",
            "subtipo_codigo": "CONYUGE",
            "nombre_configuracion": "Mercurio EX02 - Reagrupación familiar cónyuge",
            "portal": "MERCURIO",
            "flujo": "BI_PRESENTAR_NUEVA_SOLICITUD",
            "reglas": {
                "tipo_formulario_objetivo": "EX02",
                "mapper_codigo": "MERCURIO_EX02",
            },
        },
    ]

    with _connect() as conn:
        for item in defaults:
            tipo = conn.execute(
                """
                SELECT id
                FROM config_tipos_expediente
                WHERE codigo = ?
                   OR REPLACE(UPPER(nombre), ' ', '_') = ?
                LIMIT 1
                """,
                (item["tipo_codigo"], item["tipo_codigo"]),
            ).fetchone()

            if not tipo:
                continue

            subtipo = conn.execute(
                """
                SELECT id
                FROM config_subtipos_expediente
                WHERE tipo_expediente_id = ?
                  AND (
                    codigo = ?
                    OR REPLACE(UPPER(nombre), ' ', '_') = ?
                  )
                LIMIT 1
                """,
                (tipo["id"], item["subtipo_codigo"], item["subtipo_codigo"]),
            ).fetchone()

            subtipo_id = subtipo["id"] if subtipo else None
            reglas_json = json.dumps(item["reglas"], ensure_ascii=False)

            existing = conn.execute(
                """
                SELECT id
                FROM config_presentaciones_asistidas
                WHERE tipo_expediente_id = ?
                  AND (
                    subtipo_expediente_id = ?
                    OR (
                        subtipo_expediente_id IS NULL
                        AND ? IS NULL
                    )
                  )
                LIMIT 1
                """,
                (tipo["id"], subtipo_id, subtipo_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE config_presentaciones_asistidas
                    SET nombre_configuracion = ?,
                        portal = ?,
                        flujo = ?,
                        reglas_json = ?,
                        activo = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        item["nombre_configuracion"],
                        item["portal"],
                        item["flujo"],
                        reglas_json,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO config_presentaciones_asistidas (
                        tipo_expediente_id,
                        subtipo_expediente_id,
                        nombre_configuracion,
                        portal,
                        flujo,
                        reglas_json,
                        activo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        tipo["id"],
                        subtipo_id,
                        item["nombre_configuracion"],
                        item["portal"],
                        item["flujo"],
                        reglas_json,
                    ),
                )

        conn.commit()

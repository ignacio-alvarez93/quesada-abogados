import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def save_presentacion_config(data):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO config_presentaciones_asistidas
            (tipo_expediente_id, subtipo_expediente_id, nombre_configuracion, url_presentacion, flujo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["tipo_expediente_id"],
                data.get("subtipo_expediente_id"),
                data["nombre_configuracion"],
                data.get("url_presentacion"),
                data.get("flujo"),
            ),
        )
        conn.commit()


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

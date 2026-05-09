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

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    tipo_cols = columns(conn, "config_tipos_expediente")
    estado_cols = columns(conn, "config_estados_administrativos")

    if "workflow_code" not in tipo_cols:
        conn.execute("ALTER TABLE config_tipos_expediente ADD COLUMN workflow_code TEXT")

    conn.execute("""
        UPDATE config_tipos_expediente
        SET workflow_code = CASE
            WHEN UPPER(TRIM(codigo)) = 'NACIONALIDAD' THEN 'NACIONALIDAD'
            ELSE 'EXTRANJERIA'
        END
    """)

    new_states = [
        ("INADMITIDO", "INADMITIDO", 11),
        ("ADMITIDO_TASA", "ADMITIDO CON TASA", 12),
        ("TASA_APORTADA", "TASA APORTADA", 13),
        ("REQUERIMIENTO_APORTADO", "REQUERIMIENTO APORTADO", 14),
        ("AMPLIACION_PLAZO_SOLICITADA", "AMPLIACIÓN DE PLAZO SOLICITADA", 15),
    ]

    for codigo, nombre, orden in new_states:
        exists = conn.execute(
            """
            SELECT id
            FROM config_estados_administrativos
            WHERE UPPER(TRIM(nombre)) = UPPER(TRIM(?))
               OR UPPER(TRIM(codigo)) = UPPER(TRIM(?))
            LIMIT 1
            """,
            (nombre, codigo),
        ).fetchone()

        if exists:
            continue

        insert_cols = ["codigo", "nombre"]
        values = [codigo, nombre]

        if "orden" in estado_cols:
            insert_cols.append("orden")
            values.append(orden)

        if "activo" in estado_cols:
            insert_cols.append("activo")
            values.append(1)

        placeholders = ", ".join("?" for _ in insert_cols)
        conn.execute(
            f"""
            INSERT INTO config_estados_administrativos ({", ".join(insert_cols)})
            VALUES ({placeholders})
            """,
            values,
        )

    conn.commit()
    conn.close()
    print("Migración aplicada: workflows por tipo de expediente")


if __name__ == "__main__":
    main()

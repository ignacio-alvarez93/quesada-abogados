import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import get_connection


def run():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS presentation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expediente_id INTEGER NOT NULL,
                numero_expediente TEXT,
                cliente_nombre TEXT,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                prioridad INTEGER NOT NULL DEFAULT 100,
                intentos INTEGER NOT NULL DEFAULT 0,
                process_pid INTEGER,
                last_error TEXT,
                usuario TEXT,
                notas TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (expediente_id) REFERENCES expedientes(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_presentation_queue_estado
            ON presentation_queue(estado, prioridad, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_presentation_queue_expediente
            ON presentation_queue(expediente_id)
            """
        )
        conn.commit()


if __name__ == "__main__":
    run()
    print("Migración presentation_queue aplicada")

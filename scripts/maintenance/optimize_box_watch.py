"""
Optimización SQLite para Vigilancia Box.

Ejecutar:
python -m app.optimize_box_watch

No toca Box.
Solo crea índices en SQLite para acelerar consultas del módulo documental.
"""

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_activo ON box_watch_items(activo)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_ruta ON box_watch_items(ruta)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_nombre ON box_watch_items(nombre_archivo)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_estado ON box_watch_items(estado)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_tipo ON box_watch_items(tipo_detectado)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_extension ON box_watch_items(extension)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_updated ON box_watch_items(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_items_fecha_mod ON box_watch_items(fecha_modificacion)",

    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_activo ON box_watch_folders(activo)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_ruta ON box_watch_folders(ruta)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_nombre ON box_watch_folders(nombre_carpeta)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_tipo ON box_watch_folders(tipo_detectado)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_nivel ON box_watch_folders(nivel)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_actividad ON box_watch_folders(fecha_ultima_actividad)",

    "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_estado ON box_watch_alerts(estado)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_severidad ON box_watch_alerts(severidad)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_created ON box_watch_alerts(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_box_watch_runs_id ON box_watch_scan_runs(id)",
]


def main():
    with sqlite3.connect(DB_PATH, timeout=60) as conn:
        conn.execute("PRAGMA busy_timeout = 60000")
        for sql in INDEXES:
            conn.execute(sql)
        conn.execute("ANALYZE")
        conn.commit()

    print("Vigilancia Box optimizada correctamente. Índices creados/actualizados.")


if __name__ == "__main__":
    main()

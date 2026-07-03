from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("database/quesada.db")


def configure_sqlite_runtime(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """
    Configuración defensiva para reducir errores 'database is locked'.

    WAL permite mejor convivencia lectura/escritura en SQLite.
    busy_timeout hace que SQLite espere antes de fallar por bloqueo.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return

    con = sqlite3.connect(db_path, timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.commit()
    finally:
        con.close()

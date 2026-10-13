import sqlite3
import os
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "quesada.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_existing_connection(db_path=None, timeout=30):
    """
    Abre una base SQLite ya existente sin crearla ni tocar su esquema.

    URI mode=rw hace que SQLite falle (sqlite3.OperationalError) si el fichero
    no existe, en lugar de crearlo como haría connect() sobre una ruta simple.
    """
    path = Path(DB_PATH if db_path is None else db_path).resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn


def get_readonly_connection(db_path=None, timeout=30):
    """
    Abre una base SQLite ya existente en modo estrictamente de solo lectura.

    URI mode=ro nunca crea el fichero (sqlite3.OperationalError si no existe,
    también si desaparece entre una comprobación previa y la apertura) y el
    motor rechaza cualquier escritura o DDL. query_only refuerza el contrato.
    """
    path = Path(DB_PATH if db_path is None else db_path).resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=timeout)
    try:
        conn.execute("PRAGMA query_only = ON")
    except BaseException:
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")

    with open(schema_path, "r", encoding="utf-8") as f:
        cursor.executescript(f.read())

    conn.commit()
    conn.close()
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "database" / "economic_consultas_schema.sql"

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    print("Consultas previas basadas en cobros inicializadas correctamente.")

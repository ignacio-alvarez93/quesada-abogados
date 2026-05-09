"""
Limpieza segura de inventario Box escaneado.

Uso:
python -m app.clean_box_watch_inventory

Qué limpia:
- box_watch_items
- box_watch_folders
- box_watch_alerts
- box_watch_scan_runs

Qué NO limpia:
- rutas configuradas
- reglas documentales
- clientes
- expedientes
- económico
- Box físico

Después puedes volver a escanear desde Vigilancia Box.
"""

from pathlib import Path
import sqlite3


DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"


def table_exists(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def main():
    print("=" * 80)
    print("LIMPIEZA INVENTARIO VIGILANCIA BOX")
    print("=" * 80)
    print(f"DB: {DB_PATH}")
    print("")
    print("Se limpiarán SOLO datos de escaneos Box.")
    print("No se toca Box físico.")
    print("No se borran clientes, expedientes ni rutas configuradas.")
    print("")

    confirm = input("Escribe LIMPIAR para continuar: ").strip().upper()
    if confirm != "LIMPIAR":
        print("Cancelado.")
        return

    tables = [
        "box_watch_alerts",
        "box_watch_items",
        "box_watch_folders",
        "box_watch_scan_runs",
    ]

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF")

        for table in tables:
            if table_exists(conn, table):
                count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                conn.execute(f"DELETE FROM {table}")
                try:
                    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                except Exception:
                    pass
                print(f"{table}: {count} registros eliminados")
            else:
                print(f"{table}: no existe")

        conn.commit()

    print("")
    print("Inventario Box limpiado correctamente.")
    print("Ahora ejecuta:")
    print("python -m app.main")


if __name__ == "__main__":
    main()

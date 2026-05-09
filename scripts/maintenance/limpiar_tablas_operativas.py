import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"


TABLAS_OPERATIVAS = [
    # Económico
    "eco_eventos",
    "eco_factura_cobros",
    "eco_movimientos_importados",
    "eco_gastos",
    "eco_facturas",
    "eco_cobros",
    "eco_hojas_encargo",

    # Trazabilidad expedientes
    "expediente_consultas_aplicadas",
    "consultas_previas",
    "hojas_encargo",
    "expediente_justificantes",
    "expediente_eventos",

    # Relación multi-cliente expediente
    "expediente_clientes",

    # Expedientes y clientes
    "expedientes",
    "clientes",
]


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def main():
    if not DB_PATH.exists():
        raise RuntimeError(f"No existe la base de datos: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = OFF")

        borradas = []

        for table in TABLAS_OPERATIVAS:
            if table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")
                borradas.append(table)

                try:
                    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                except sqlite3.OperationalError:
                    pass

        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()

        print("Tablas operativas limpiadas correctamente.")
        print("")
        print("Tablas borradas:")
        for table in borradas:
            print(f"- {table}")

        print("")
        print("Se mantienen:")
        print("- configuración config_*")
        print("- datos maestros")
        print("- estructura de base de datos")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()

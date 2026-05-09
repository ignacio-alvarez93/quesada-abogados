import csv
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(__file__).resolve().parent / "quesada.db"

CSV_CANDIDATES = [
    Path(__file__).resolve().parent / "data",
    Path(__file__).resolve().parent,
    PROJECT_ROOT,
]


TIPOS_VIA = [
    "Calle",
    "Avenida",
    "Plaza",
    "Paseo",
    "Camino",
    "Carretera",
    "Ronda",
    "Travesía",
    "Urbanización",
    "Polígono",
    "Lugar",
    "Barrio",
    "Otro",
]


ESTADOS_CIVILES = [
    "Soltero/a",
    "Casado/a",
    "Divorciado/a",
    "Separado/a",
    "Viudo/a",
    "Pareja de hecho",
    "No consta",
]


def find_csv(filename):
    for folder in CSV_CANDIDATES:
        path = folder / filename
        if path.exists():
            return path

    raise FileNotFoundError(
        f"No se encontró {filename}. Colócalo en database/data/, database/ o en la raíz del proyecto."
    )


def read_csv(filename):
    path = find_csv(filename)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def drop_and_create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = OFF")

    cursor.execute("DROP TABLE IF EXISTS localidades")
    cursor.execute("DROP TABLE IF EXISTS provincias")
    cursor.execute("DROP TABLE IF EXISTS comunidades_autonomas")
    cursor.execute("DROP TABLE IF EXISTS paises")
    cursor.execute("DROP TABLE IF EXISTS tipos_via")
    cursor.execute("DROP TABLE IF EXISTS estados_civiles")

    cursor.execute("""
        CREATE TABLE paises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT,
            nombre TEXT NOT NULL,
            nacionalidad TEXT,
            codigo_iso TEXT,
            codigo_iso3 TEXT,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE comunidades_autonomas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT,
            nombre TEXT NOT NULL,
            codigo_comunidad TEXT,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE provincias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT,
            comunidad_id INTEGER,
            nombre TEXT NOT NULL,
            codigo_provincia TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (comunidad_id) REFERENCES comunidades_autonomas(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE localidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT,
            provincia_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            codigo_localidad TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (provincia_id) REFERENCES provincias(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE tipos_via (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE estados_civiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("CREATE INDEX idx_paises_nombre ON paises(nombre)")
    cursor.execute("CREATE INDEX idx_comunidades_external_id ON comunidades_autonomas(external_id)")
    cursor.execute("CREATE INDEX idx_provincias_external_id ON provincias(external_id)")
    cursor.execute("CREATE INDEX idx_provincias_nombre ON provincias(nombre)")
    cursor.execute("CREATE INDEX idx_localidades_provincia_id ON localidades(provincia_id)")
    cursor.execute("CREATE INDEX idx_localidades_nombre ON localidades(nombre)")

    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON")


def seed_paises(conn, paises_rows):
    cursor = conn.cursor()

    for row in paises_rows:
        nombre = (row.get("nombre") or "").strip()
        if not nombre:
            continue

        cursor.execute(
            """
            INSERT INTO paises (
                external_id,
                nombre,
                nacionalidad,
                codigo_iso,
                codigo_iso3,
                activo
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                row.get("id"),
                nombre,
                nombre,
                row.get("codigo_iso"),
                row.get("codigo_iso3"),
            ),
        )

    conn.commit()


def seed_comunidades_y_provincias(conn, comunidades_rows):
    cursor = conn.cursor()

    comunidad_db_ids = {}

    for row in comunidades_rows:
        if str(row.get("nivel")) != "1":
            continue

        nombre = (row.get("nombre") or "").strip()
        external_id = row.get("id")

        if not nombre or not external_id:
            continue

        cursor.execute(
            """
            INSERT INTO comunidades_autonomas (
                external_id,
                nombre,
                codigo_comunidad,
                activo
            )
            VALUES (?, ?, ?, 1)
            """,
            (
                external_id,
                nombre,
                row.get("codigo_subdivision"),
            ),
        )

        comunidad_db_ids[external_id] = cursor.lastrowid

    provincia_db_ids = {}

    for row in comunidades_rows:
        if str(row.get("nivel")) != "2":
            continue

        nombre = (row.get("nombre") or "").strip()
        external_id = row.get("id")
        parent_id = row.get("parent_id")
        comunidad_id = comunidad_db_ids.get(parent_id)

        if not nombre or not external_id:
            continue

        cursor.execute(
            """
            INSERT INTO provincias (
                external_id,
                comunidad_id,
                nombre,
                codigo_provincia,
                activo
            )
            VALUES (?, ?, ?, ?, 1)
            """,
            (
                external_id,
                comunidad_id,
                nombre,
                row.get("codigo_subdivision"),
            ),
        )

        provincia_db_ids[external_id] = cursor.lastrowid

    conn.commit()
    return provincia_db_ids


def seed_localidades(conn, localidades_rows, provincia_db_ids):
    cursor = conn.cursor()
    insertadas = 0
    omitidas = 0

    for row in localidades_rows:
        nombre = (row.get("nombre") or "").strip()
        external_id = row.get("id")
        subdivision_id = row.get("subdivision_id")

        provincia_id = provincia_db_ids.get(subdivision_id)

        if not nombre or not provincia_id:
            omitidas += 1
            continue

        cursor.execute(
            """
            INSERT INTO localidades (
                external_id,
                provincia_id,
                nombre,
                codigo_localidad,
                activo
            )
            VALUES (?, ?, ?, ?, 1)
            """,
            (
                external_id,
                provincia_id,
                nombre,
                row.get("codigo_localidad"),
            ),
        )

        insertadas += 1

    conn.commit()
    return insertadas, omitidas


def seed_auxiliares(conn):
    cursor = conn.cursor()

    cursor.executemany(
        "INSERT INTO tipos_via (nombre, activo) VALUES (?, 1)",
        [(item,) for item in TIPOS_VIA],
    )

    cursor.executemany(
        "INSERT INTO estados_civiles (nombre, activo) VALUES (?, 1)",
        [(item,) for item in ESTADOS_CIVILES],
    )

    conn.commit()


def print_counts(conn):
    cursor = conn.cursor()

    for table in [
        "paises",
        "comunidades_autonomas",
        "provincias",
        "localidades",
        "tipos_via",
        "estados_civiles",
    ]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"{table}: {count}")


def main():
    print("Leyendo CSV...")
    paises_rows = read_csv("paises.csv")
    comunidades_rows = read_csv("comunidades.csv")
    localidades_rows = read_csv("localidades.csv")

    conn = sqlite3.connect(DB_PATH)

    try:
        print("Reconstruyendo tablas maestras...")
        drop_and_create_tables(conn)

        print("Cargando países...")
        seed_paises(conn, paises_rows)

        print("Cargando comunidades y provincias...")
        provincia_db_ids = seed_comunidades_y_provincias(conn, comunidades_rows)

        print("Cargando localidades...")
        insertadas, omitidas = seed_localidades(conn, localidades_rows, provincia_db_ids)

        print("Cargando tipos de vía y estados civiles...")
        seed_auxiliares(conn)

        print("")
        print("Datos maestros cargados correctamente.")
        print(f"Localidades insertadas: {insertadas}")
        print(f"Localidades omitidas: {omitidas}")
        print("")
        print_counts(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "quesada.db"


PAISES = [
    ("España", "Española"),
    ("Marruecos", "Marroquí"),
    ("Argelia", "Argelina"),
    ("Colombia", "Colombiana"),
    ("Venezuela", "Venezolana"),
    ("Ecuador", "Ecuatoriana"),
    ("Perú", "Peruana"),
    ("Bolivia", "Boliviana"),
    ("Argentina", "Argentina"),
    ("Chile", "Chilena"),
    ("Paraguay", "Paraguaya"),
    ("Uruguay", "Uruguaya"),
    ("Brasil", "Brasileña"),
    ("Cuba", "Cubana"),
    ("República Dominicana", "Dominicana"),
    ("Honduras", "Hondureña"),
    ("Nicaragua", "Nicaragüense"),
    ("El Salvador", "Salvadoreña"),
    ("Guatemala", "Guatemalteca"),
    ("México", "Mexicana"),
    ("China", "China"),
    ("Pakistán", "Pakistaní"),
    ("India", "India"),
    ("Bangladés", "Bangladesí"),
    ("Senegal", "Senegalesa"),
    ("Nigeria", "Nigeriana"),
    ("Mali", "Maliense"),
    ("Gambia", "Gambiana"),
    ("Ucrania", "Ucraniana"),
    ("Rusia", "Rusa"),
    ("Rumanía", "Rumana"),
    ("Italia", "Italiana"),
    ("Francia", "Francesa"),
    ("Portugal", "Portuguesa"),
    ("Reino Unido", "Británica"),
    ("Estados Unidos", "Estadounidense"),
]

PROVINCIAS = [
    "A Coruña", "Álava", "Albacete", "Alicante", "Almería", "Asturias", "Ávila",
    "Badajoz", "Barcelona", "Burgos", "Cáceres", "Cádiz", "Cantabria", "Castellón",
    "Ciudad Real", "Córdoba", "Cuenca", "Girona", "Granada", "Guadalajara",
    "Gipuzkoa", "Huelva", "Huesca", "Illes Balears", "Jaén", "La Rioja", "Las Palmas",
    "León", "Lleida", "Lugo", "Madrid", "Málaga", "Murcia", "Navarra", "Ourense",
    "Palencia", "Pontevedra", "Salamanca", "Santa Cruz de Tenerife", "Segovia",
    "Sevilla", "Soria", "Tarragona", "Teruel", "Toledo", "Valencia", "Valladolid",
    "Bizkaia", "Zamora", "Zaragoza", "Ceuta", "Melilla",
]

LOCALIDADES_INICIALES = {
    "Murcia": [
        "Murcia",
        "Cartagena",
        "Lorca",
        "Molina de Segura",
        "Alcantarilla",
        "Cieza",
        "Yecla",
        "Águilas",
        "Torre-Pacheco",
        "San Javier",
        "San Pedro del Pinatar",
        "Mazarrón",
        "Totana",
        "Caravaca de la Cruz",
        "Jumilla",
    ],
    "Alicante": [
        "Alicante",
        "Elche",
        "Torrevieja",
        "Orihuela",
        "Benidorm",
        "Alcoy",
        "Elda",
        "Denia",
        "Villena",
    ],
    "Almería": [
        "Almería",
        "Roquetas de Mar",
        "El Ejido",
        "Níjar",
        "Vícar",
        "Adra",
    ],
    "Madrid": [
        "Madrid",
        "Alcalá de Henares",
        "Móstoles",
        "Fuenlabrada",
        "Leganés",
        "Getafe",
        "Parla",
        "Alcorcón",
    ],
    "Barcelona": [
        "Barcelona",
        "L'Hospitalet de Llobregat",
        "Badalona",
        "Terrassa",
        "Sabadell",
        "Mataró",
    ],
}

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


def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            nacionalidad TEXT,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS provincias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS localidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provincia_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            UNIQUE (provincia_id, nombre),
            FOREIGN KEY (provincia_id) REFERENCES provincias(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tipos_via (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estados_civiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.commit()


def insert_master_data(conn):
    cursor = conn.cursor()

    cursor.executemany(
        "INSERT OR IGNORE INTO paises (nombre, nacionalidad) VALUES (?, ?)",
        PAISES,
    )

    cursor.executemany(
        "INSERT OR IGNORE INTO provincias (nombre) VALUES (?)",
        [(provincia,) for provincia in PROVINCIAS],
    )

    cursor.executemany(
        "INSERT OR IGNORE INTO tipos_via (nombre) VALUES (?)",
        [(tipo,) for tipo in TIPOS_VIA],
    )

    cursor.executemany(
        "INSERT OR IGNORE INTO estados_civiles (nombre) VALUES (?)",
        [(estado,) for estado in ESTADOS_CIVILES],
    )

    for provincia, localidades in LOCALIDADES_INICIALES.items():
        cursor.execute("SELECT id FROM provincias WHERE nombre = ?", (provincia,))
        row = cursor.fetchone()

        if not row:
            continue

        provincia_id = row[0]

        cursor.executemany(
            """
            INSERT OR IGNORE INTO localidades (provincia_id, nombre)
            VALUES (?, ?)
            """,
            [(provincia_id, localidad) for localidad in localidades],
        )

    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)

    try:
        create_tables(conn)
        insert_master_data(conn)
        print("Datos maestros cargados correctamente.")
        print(f"Base de datos: {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

-- DATOS MAESTROS DESDE CSV
-- ERP Quesada Abogados

CREATE TABLE IF NOT EXISTS paises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    nombre TEXT NOT NULL UNIQUE,
    nacionalidad TEXT,
    codigo_iso TEXT,
    codigo_iso3 TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS comunidades_autonomas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    nombre TEXT NOT NULL UNIQUE,
    codigo_comunidad TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS provincias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    comunidad_id INTEGER,
    nombre TEXT NOT NULL UNIQUE,
    codigo_provincia TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (comunidad_id) REFERENCES comunidades_autonomas(id)
);

CREATE TABLE IF NOT EXISTS localidades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    provincia_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    codigo_localidad TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE (provincia_id, nombre),
    FOREIGN KEY (provincia_id) REFERENCES provincias(id)
);

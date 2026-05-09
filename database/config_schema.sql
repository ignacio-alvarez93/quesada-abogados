-- database/config_schema.sql
-- Módulo de Configuración Operativa - Fase 1
-- Ejecutar una vez contra database/quesada.db

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS config_tipos_expediente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config_documentos_requeridos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    codigo_documento TEXT NOT NULL,
    nombre_documento TEXT NOT NULL,
    obligatorio INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id) ON DELETE CASCADE,
    UNIQUE(tipo_expediente_id, codigo_documento)
);

CREATE TABLE IF NOT EXISTS config_box_rutas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    ruta_box TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id) ON DELETE CASCADE,
    UNIQUE(tipo_expediente_id, ruta_box)
);

CREATE TABLE IF NOT EXISTS config_nomenclaturas_documentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    patron_nombre TEXT NOT NULL,
    extension_permitida TEXT DEFAULT 'pdf,jpg,jpeg,png',
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id) ON DELETE CASCADE,
    FOREIGN KEY (documento_id) REFERENCES config_documentos_requeridos(id) ON DELETE CASCADE,
    UNIQUE(tipo_expediente_id, documento_id, patron_nombre)
);

CREATE TABLE IF NOT EXISTS config_estados_expediente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    color TEXT DEFAULT '#0057B8',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS config_prioridades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    color TEXT DEFAULT '#0057B8',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS config_columnas_tabla (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla TEXT NOT NULL,
    campo TEXT NOT NULL,
    visible INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL DEFAULT 0,
    ancho INTEGER NOT NULL DEFAULT 160,
    UNIQUE(tabla, campo)
);

CREATE INDEX IF NOT EXISTS idx_config_documentos_tipo ON config_documentos_requeridos(tipo_expediente_id);
CREATE INDEX IF NOT EXISTS idx_config_rutas_tipo ON config_box_rutas(tipo_expediente_id);
CREATE INDEX IF NOT EXISTS idx_config_nomenclaturas_tipo ON config_nomenclaturas_documentales(tipo_expediente_id);

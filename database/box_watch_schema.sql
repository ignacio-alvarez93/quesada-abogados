-- database/box_watch_schema.sql
-- Módulo Vigilancia Box - Fase 1
-- Solo lectura: inventario, alertas y trazabilidad documental.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS box_watch_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta TEXT NOT NULL UNIQUE,
    nombre_carpeta TEXT NOT NULL,
    ruta_padre TEXT,
    nivel INTEGER NOT NULL DEFAULT 0,
    total_archivos INTEGER NOT NULL DEFAULT 0,
    total_subcarpetas INTEGER NOT NULL DEFAULT 0,
    tamano_total_bytes INTEGER NOT NULL DEFAULT 0,
    fecha_ultima_actividad TEXT,
    cliente_id INTEGER,
    expediente_id INTEGER,
    tipo_detectado TEXT,
    estado TEXT NOT NULL DEFAULT 'OK',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id)
);

CREATE TABLE IF NOT EXISTS box_watch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    extension TEXT,
    tipo_detectado TEXT,
    cliente_id INTEGER,
    expediente_id INTEGER,
    hoja_encargo_id INTEGER,
    tamano_bytes INTEGER DEFAULT 0,
    fecha_modificacion TEXT,
    hash_archivo TEXT,
    estado TEXT NOT NULL DEFAULT 'SIN CLASIFICAR',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id),
    UNIQUE(ruta, nombre_archivo)
);

CREATE TABLE IF NOT EXISTS box_watch_scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_inicio TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_fin TEXT,
    ruta_base TEXT NOT NULL,
    total_archivos INTEGER NOT NULL DEFAULT 0,
    total_carpetas INTEGER NOT NULL DEFAULT 0,
    nuevos INTEGER NOT NULL DEFAULT 0,
    modificados INTEGER NOT NULL DEFAULT 0,
    sin_clasificar INTEGER NOT NULL DEFAULT 0,
    alertas INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'OK',
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS box_watch_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    expediente_id INTEGER,
    cliente_id INTEGER,
    tipo_alerta TEXT NOT NULL,
    severidad TEXT NOT NULL DEFAULT 'MEDIA',
    mensaje TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'ABIERTA',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    FOREIGN KEY (item_id) REFERENCES box_watch_items(id),
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS box_watch_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER,
    codigo_documento TEXT NOT NULL,
    patron_nombre TEXT NOT NULL,
    extension_permitida TEXT DEFAULT 'pdf,jpg,jpeg,png',
    obligatorio INTEGER NOT NULL DEFAULT 1,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id),
    UNIQUE(tipo_expediente_id, codigo_documento, patron_nombre)
);

CREATE INDEX IF NOT EXISTS idx_box_watch_folders_ruta ON box_watch_folders(ruta);
CREATE INDEX IF NOT EXISTS idx_box_watch_folders_estado ON box_watch_folders(estado);
CREATE INDEX IF NOT EXISTS idx_box_watch_folders_expediente ON box_watch_folders(expediente_id);
CREATE INDEX IF NOT EXISTS idx_box_watch_items_hash ON box_watch_items(hash_archivo);
CREATE INDEX IF NOT EXISTS idx_box_watch_items_estado ON box_watch_items(estado);
CREATE INDEX IF NOT EXISTS idx_box_watch_items_expediente ON box_watch_items(expediente_id);
CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_estado ON box_watch_alerts(estado);
CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_tipo ON box_watch_alerts(tipo_alerta);
CREATE INDEX IF NOT EXISTS idx_box_watch_rules_tipo ON box_watch_rules(tipo_expediente_id);

CREATE TABLE IF NOT EXISTS config_presentaciones_asistidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    subtipo_expediente_id INTEGER,
    nombre_configuracion TEXT NOT NULL,
    url_presentacion TEXT,
    portal TEXT DEFAULT 'MERCURIO',
    flujo TEXT,
    selectores_json TEXT,
    reglas_json TEXT,
    documentos_json TEXT,
    activo INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

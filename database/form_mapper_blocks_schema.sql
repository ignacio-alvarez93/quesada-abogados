CREATE TABLE IF NOT EXISTS form_mapper_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    mapper_json TEXT NOT NULL,
    required_fields_json TEXT,
    activo INTEGER DEFAULT 1,
    version INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_form_mapper_blocks_activo
ON form_mapper_blocks(activo);

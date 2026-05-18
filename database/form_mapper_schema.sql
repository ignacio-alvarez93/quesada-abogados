CREATE TABLE IF NOT EXISTS form_mapper_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,

    tipo_destino TEXT NOT NULL,
    activo INTEGER DEFAULT 1,

    tipo_expediente_id INTEGER,
    subtipo_expediente_id INTEGER,

    mapper_json TEXT NOT NULL,

    required_fields_json TEXT,

    version INTEGER DEFAULT 1,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_form_mapper_tipo
ON form_mapper_templates(tipo_destino);

CREATE INDEX IF NOT EXISTS idx_form_mapper_expediente
ON form_mapper_templates(tipo_expediente_id, subtipo_expediente_id);
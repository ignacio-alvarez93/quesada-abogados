-- Motor general de plantillas documentales.
-- Incluye EX oficiales, designaciones, autorizaciones, hojas de encargo,
-- escritos y cualquier documento interno/generado.

CREATE TABLE IF NOT EXISTS document_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    nombre_oficial TEXT,
    descripcion TEXT,
    categoria TEXT NOT NULL DEFAULT 'GENERAL',
    tipo_destino TEXT NOT NULL DEFAULT 'DOCUMENTO',
    template_type TEXT NOT NULL DEFAULT 'docx',
    template_path TEXT,
    fields_json_path TEXT,
    metadata_json_path TEXT,
    mapper_destino TEXT,
    requiere_expediente INTEGER NOT NULL DEFAULT 1,
    activo INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_document_templates_categoria
ON document_templates(categoria, activo, orden, nombre);

CREATE INDEX IF NOT EXISTS idx_document_templates_tipo_destino
ON document_templates(tipo_destino, activo, orden, nombre);

CREATE INDEX IF NOT EXISTS idx_document_templates_mapper_destino
ON document_templates(mapper_destino, activo);

CREATE INDEX IF NOT EXISTS idx_document_templates_requiere_expediente
ON document_templates(requiere_expediente, activo);

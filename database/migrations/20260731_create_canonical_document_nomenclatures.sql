PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS
config_nomenclaturas_catalogo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    documento_catalogo_id INTEGER NOT NULL,
    tipo_expediente_id INTEGER NOT NULL,
    subtipo_expediente_id INTEGER,

    rol_documental TEXT,
    patron_nombre TEXT NOT NULL,
    extension_permitida TEXT
        NOT NULL DEFAULT 'pdf,jpg,jpeg,png',

    prioridad INTEGER NOT NULL DEFAULT 100,
    activo INTEGER NOT NULL DEFAULT 1,

    origen_legacy_id INTEGER,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (documento_catalogo_id)
        REFERENCES config_documentos_catalogo(id),

    FOREIGN KEY (tipo_expediente_id)
        REFERENCES config_tipos_expediente(id),

    FOREIGN KEY (subtipo_expediente_id)
        REFERENCES config_subtipos_expediente(id),

    FOREIGN KEY (origen_legacy_id)
        REFERENCES config_nomenclaturas_documentales(id),

    CHECK (TRIM(patron_nombre) <> ''),
    CHECK (prioridad >= 0),
    CHECK (activo IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS
idx_nomenclaturas_catalogo_semantic_unique
ON config_nomenclaturas_catalogo (
    documento_catalogo_id,
    tipo_expediente_id,
    COALESCE(subtipo_expediente_id, -1),
    COALESCE(rol_documental, ''),
    UPPER(TRIM(patron_nombre)),
    LOWER(TRIM(extension_permitida))
);

CREATE UNIQUE INDEX IF NOT EXISTS
idx_nomenclaturas_catalogo_origen_legacy
ON config_nomenclaturas_catalogo (
    origen_legacy_id
)
WHERE origen_legacy_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
idx_nomenclaturas_catalogo_tipo_subtipo
ON config_nomenclaturas_catalogo (
    tipo_expediente_id,
    subtipo_expediente_id,
    activo,
    prioridad
);

CREATE INDEX IF NOT EXISTS
idx_nomenclaturas_catalogo_documento
ON config_nomenclaturas_catalogo (
    documento_catalogo_id,
    activo
);

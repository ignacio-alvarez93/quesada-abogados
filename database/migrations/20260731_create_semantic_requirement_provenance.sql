PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS
config_grupos_requisitos_origen_legacy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_semantico_id INTEGER NOT NULL,
    grupo_legacy_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (grupo_semantico_id)
        REFERENCES config_grupos_requisitos_documentales(id)
        ON DELETE CASCADE,

    FOREIGN KEY (grupo_legacy_id)
        REFERENCES config_grupos_requisitos_documentales(id),

    UNIQUE (grupo_semantico_id, grupo_legacy_id),
    UNIQUE (grupo_legacy_id),

    CHECK (grupo_semantico_id <> grupo_legacy_id)
);

CREATE INDEX IF NOT EXISTS
idx_grupos_requisitos_origen_semantico
ON config_grupos_requisitos_origen_legacy (
    grupo_semantico_id
);

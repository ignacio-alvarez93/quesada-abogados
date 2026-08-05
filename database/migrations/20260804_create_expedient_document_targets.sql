PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expedient_document_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    relative_path TEXT NOT NULL,

    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    CHECK (
        purpose IN (
            'PRESENTACION',
            'APORTACION',
            'APORTACION_TASAS',
            'REQUERIMIENTO',
            'RECURSO'
        )
    ),

    CHECK (active IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS
idx_expedient_document_targets_active_purpose
ON expedient_document_targets (
    expediente_id,
    purpose
)
WHERE active = 1;

CREATE INDEX IF NOT EXISTS
idx_expedient_document_targets_path
ON expedient_document_targets (
    expediente_id,
    relative_path,
    active
);

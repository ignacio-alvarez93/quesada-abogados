PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expediente_notas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    contenido TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT 'GENERAL',
    autor TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_expediente_notas_expediente
    ON expediente_notas(expediente_id, created_at DESC);

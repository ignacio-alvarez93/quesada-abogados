CREATE TABLE IF NOT EXISTS expediente_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    source_hash TEXT,
    validated INTEGER DEFAULT 0,
    created_by TEXT DEFAULT 'ERP',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id),
    UNIQUE(expediente_id, version)
);

CREATE INDEX IF NOT EXISTS idx_expediente_snapshots_expediente
ON expediente_snapshots(expediente_id);

CREATE INDEX IF NOT EXISTS idx_expediente_snapshots_created_at
ON expediente_snapshots(created_at);
PRAGMA foreign_keys = ON;


CREATE TABLE IF NOT EXISTS document_semantic_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL,

    estado_documental TEXT NOT NULL,
    estado_procesal TEXT,
    estado_combinado TEXT,

    semantico_aplicable INTEGER NOT NULL DEFAULT 0,
    motor_activo TEXT,
    grupos_bloqueantes INTEGER NOT NULL DEFAULT 0,
    ambiguedades_rol INTEGER NOT NULL DEFAULT 0,

    fingerprint TEXT NOT NULL,
    diagnosis_json TEXT NOT NULL,

    source_type TEXT NOT NULL DEFAULT 'MANUAL_DIAGNOSIS',
    source_scan_run_id INTEGER,
    source_scan_job_id INTEGER,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    FOREIGN KEY (source_scan_run_id)
        REFERENCES box_watch_scan_runs(id)
        ON DELETE SET NULL,

    FOREIGN KEY (source_scan_job_id)
        REFERENCES box_watch_scan_jobs(id)
        ON DELETE SET NULL,

    UNIQUE (expediente_id)
);


CREATE INDEX IF NOT EXISTS
idx_document_semantic_snapshots_fingerprint
ON document_semantic_snapshots(fingerprint);


CREATE INDEX IF NOT EXISTS
idx_document_semantic_snapshots_state
ON document_semantic_snapshots(estado_documental);


CREATE TABLE IF NOT EXISTS document_semantic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER,

    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',

    previous_document_state TEXT,
    new_document_state TEXT,

    previous_process_state TEXT,
    new_process_state TEXT,

    previous_fingerprint TEXT,
    new_fingerprint TEXT NOT NULL,

    idempotency_key TEXT NOT NULL,

    source_type TEXT NOT NULL DEFAULT 'MANUAL_DIAGNOSIS',
    source_scan_run_id INTEGER,
    source_scan_job_id INTEGER,

    title TEXT NOT NULL,
    description TEXT,

    metadata_json TEXT NOT NULL DEFAULT '{}',

    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE SET NULL,

    FOREIGN KEY (source_scan_run_id)
        REFERENCES box_watch_scan_runs(id)
        ON DELETE SET NULL,

    FOREIGN KEY (source_scan_job_id)
        REFERENCES box_watch_scan_jobs(id)
        ON DELETE SET NULL,

    UNIQUE (idempotency_key)
);


CREATE INDEX IF NOT EXISTS
idx_document_semantic_events_expediente
ON document_semantic_events(
    expediente_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_document_semantic_events_status
ON document_semantic_events(
    status,
    severity,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_document_semantic_events_type
ON document_semantic_events(
    event_type,
    created_at DESC
);

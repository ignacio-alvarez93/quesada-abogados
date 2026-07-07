-- Cashmatic / conciliación económica - staging seguro
-- Regla funcional:
--   La vinculación con cliente, expediente o cobro NO es automática.
--   Estos movimientos se importan como datos brutos/normalizados y se vinculan manualmente en fase posterior.

CREATE TABLE IF NOT EXISTS economic_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_file_name TEXT NOT NULL,
    source_file_path TEXT,
    file_sha256 TEXT NOT NULL,
    detected_format TEXT,
    total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    quarantine_rows INTEGER NOT NULL DEFAULT 0,
    candidate_payment_rows INTEGER NOT NULL DEFAULT 0,
    total_candidate_requested_centimos INTEGER NOT NULL DEFAULT 0,
    total_candidate_inserted_centimos INTEGER NOT NULL DEFAULT 0,
    total_candidate_dispensed_centimos INTEGER NOT NULL DEFAULT 0,
    total_candidate_net_centimos INTEGER NOT NULL DEFAULT 0,
    first_start_time TEXT,
    last_start_time TEXT,
    status TEXT NOT NULL DEFAULT 'IMPORTED',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, file_sha256)
);

CREATE TABLE IF NOT EXISTS cashmatic_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,

    row_number INTEGER NOT NULL,
    row_hash TEXT NOT NULL,

    cashmatic_id TEXT,
    operation TEXT,
    result TEXT,
    end_type TEXT,
    movement_status TEXT NOT NULL,

    requested_centimos INTEGER NOT NULL DEFAULT 0,
    inserted_centimos INTEGER NOT NULL DEFAULT 0,
    dispensed_centimos INTEGER NOT NULL DEFAULT 0,
    not_dispensed_centimos INTEGER NOT NULL DEFAULT 0,
    net_amount_centimos INTEGER NOT NULL DEFAULT 0,

    currency TEXT,
    start_time TEXT,
    end_time TEXT,
    source_raw TEXT,
    reason_raw TEXT,
    reference_raw TEXT,
    user_username TEXT,

    candidate_payment INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',

    -- Vinculación manual posterior.
    -- No se rellena en importación.
    linked_client_id INTEGER NULL,
    linked_expedient_id INTEGER NULL,
    linked_payment_id INTEGER NULL,
    linked_by_user_id INTEGER NULL,
    linked_at TEXT NULL,
    link_notes TEXT NULL,

    review_status TEXT NOT NULL DEFAULT 'PENDING_MANUAL_REVIEW',
    ignored_at TEXT NULL,
    ignored_reason TEXT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(batch_id) REFERENCES economic_import_batches(id),
    UNIQUE(row_hash)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_cashmatic_movements_row_hash
ON cashmatic_movements(row_hash);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_batch_id
ON cashmatic_movements(batch_id);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_status
ON cashmatic_movements(movement_status);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_candidate
ON cashmatic_movements(candidate_payment);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_start_time
ON cashmatic_movements(start_time);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_reason_raw
ON cashmatic_movements(reason_raw);

CREATE INDEX IF NOT EXISTS idx_cashmatic_movements_manual_links
ON cashmatic_movements(linked_client_id, linked_expedient_id, linked_payment_id);

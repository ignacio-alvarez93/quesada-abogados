-- Banco / conciliación económica - staging seguro
-- Regla funcional:
--   Los movimientos bancarios se importan como datos brutos/normalizados.
--   NO crean cobros, NO crean facturas y NO se vinculan automáticamente.

CREATE TABLE IF NOT EXISTS bank_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,

    row_number INTEGER NOT NULL,
    row_hash TEXT NOT NULL,

    bank_name TEXT NOT NULL,
    account_label TEXT,
    account_iban TEXT,

    operation_date TEXT,
    value_date TEXT,
    concept TEXT NOT NULL,

    amount_centimos INTEGER NOT NULL DEFAULT 0,
    balance_centimos INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'EUR',

    movement_type TEXT NOT NULL,
    movement_status TEXT NOT NULL,

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

CREATE UNIQUE INDEX IF NOT EXISTS ux_bank_movements_row_hash
ON bank_movements(row_hash);

CREATE INDEX IF NOT EXISTS idx_bank_movements_batch_id
ON bank_movements(batch_id);

CREATE INDEX IF NOT EXISTS idx_bank_movements_bank_name
ON bank_movements(bank_name);

CREATE INDEX IF NOT EXISTS idx_bank_movements_operation_date
ON bank_movements(operation_date);

CREATE INDEX IF NOT EXISTS idx_bank_movements_movement_status
ON bank_movements(movement_status);

CREATE INDEX IF NOT EXISTS idx_bank_movements_movement_type
ON bank_movements(movement_type);

CREATE INDEX IF NOT EXISTS idx_bank_movements_review_status
ON bank_movements(review_status);

CREATE INDEX IF NOT EXISTS idx_bank_movements_amount
ON bank_movements(amount_centimos);

CREATE INDEX IF NOT EXISTS idx_bank_movements_manual_links
ON bank_movements(linked_client_id, linked_expedient_id, linked_payment_id);

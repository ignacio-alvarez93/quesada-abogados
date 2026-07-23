PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS economic_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bank_name TEXT,
    iban TEXT,
    currency TEXT NOT NULL DEFAULT 'EUR',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (TRIM(name) <> ''),
    CHECK (TRIM(currency) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_economic_accounts_iban
ON economic_accounts(iban)
WHERE iban IS NOT NULL AND TRIM(iban) <> '';

CREATE TABLE IF NOT EXISTS economic_internal_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_date TEXT NOT NULL,
    source_account_id INTEGER NOT NULL,
    destination_account_id INTEGER NOT NULL,
    amount_centimos INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    concept TEXT NOT NULL,
    reference TEXT,
    outgoing_movement_id INTEGER,
    incoming_movement_id INTEGER,
    source_type TEXT,
    destination_type TEXT,
    source_movement_ref_id INTEGER,
    destination_movement_ref_id INTEGER,
    source_account_key TEXT,
    destination_account_key TEXT,
    source_previous_review_status TEXT,
    destination_previous_review_status TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'CONCILIADO',
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_account_id) REFERENCES economic_accounts(id),
    FOREIGN KEY(destination_account_id) REFERENCES economic_accounts(id),
    FOREIGN KEY(outgoing_movement_id) REFERENCES eco_movimientos_importados(id),
    FOREIGN KEY(incoming_movement_id) REFERENCES eco_movimientos_importados(id),
    CHECK (source_account_id <> destination_account_id),
    CHECK (amount_centimos > 0),
    CHECK (status IN ('BORRADOR', 'CONCILIADO', 'ANULADO'))
);

CREATE INDEX IF NOT EXISTS idx_internal_transfers_date
ON economic_internal_transfers(transfer_date);

CREATE INDEX IF NOT EXISTS idx_internal_transfers_accounts
ON economic_internal_transfers(source_account_id, destination_account_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_outgoing
ON economic_internal_transfers(outgoing_movement_id)
WHERE outgoing_movement_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_incoming
ON economic_internal_transfers(incoming_movement_id)
WHERE incoming_movement_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_source_ref
ON economic_internal_transfers(source_type, source_movement_ref_id)
WHERE source_type IS NOT NULL AND source_movement_ref_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_internal_transfer_destination_ref
ON economic_internal_transfers(destination_type, destination_movement_ref_id)
WHERE destination_type IS NOT NULL
  AND destination_movement_ref_id IS NOT NULL;

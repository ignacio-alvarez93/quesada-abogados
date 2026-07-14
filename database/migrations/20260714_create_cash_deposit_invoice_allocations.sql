CREATE TABLE IF NOT EXISTS economic_cash_deposit_invoice_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    bank_movement_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,

    amount_centimos INTEGER NOT NULL
        CHECK (amount_centimos > 0),

    cash_collection_date TEXT,
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (bank_movement_id)
        REFERENCES bank_movements(id)
        ON DELETE CASCADE,

    FOREIGN KEY (invoice_id)
        REFERENCES eco_facturas(id)
        ON DELETE RESTRICT,

    UNIQUE(bank_movement_id, invoice_id)
);

CREATE INDEX IF NOT EXISTS
idx_cash_deposit_allocations_movement
ON economic_cash_deposit_invoice_allocations(
    bank_movement_id
);

CREATE INDEX IF NOT EXISTS
idx_cash_deposit_allocations_invoice
ON economic_cash_deposit_invoice_allocations(
    invoice_id
);

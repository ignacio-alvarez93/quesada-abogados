CREATE TABLE IF NOT EXISTS economic_expense_reconciliation_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL DEFAULT 'bank',
    source_movement_id INTEGER NOT NULL,
    expense_id INTEGER NOT NULL,
    amount_centimos INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (amount_centimos > 0),

    UNIQUE (
        source_type,
        source_movement_id,
        expense_id
    )
);

CREATE INDEX IF NOT EXISTS idx_eera_source
ON economic_expense_reconciliation_applications (
    source_type,
    source_movement_id
);

CREATE INDEX IF NOT EXISTS idx_eera_expense
ON economic_expense_reconciliation_applications (
    expense_id
);

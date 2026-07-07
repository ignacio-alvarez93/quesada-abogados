CREATE TABLE IF NOT EXISTS economic_reconciliation_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    group_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',

    title TEXT,
    description TEXT,

    expected_amount_centimos INTEGER NOT NULL DEFAULT 0,
    actual_amount_centimos INTEGER NOT NULL DEFAULT 0,
    difference_centimos INTEGER NOT NULL DEFAULT 0,

    group_date TEXT,
    reviewed_by_user_id INTEGER,
    reviewed_at TEXT,

    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_groups_type
ON economic_reconciliation_groups(group_type);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_groups_status
ON economic_reconciliation_groups(status);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_groups_date
ON economic_reconciliation_groups(group_date);


CREATE TABLE IF NOT EXISTS economic_reconciliation_group_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    group_id INTEGER NOT NULL,

    source_type TEXT NOT NULL,
    source_id INTEGER,

    role TEXT NOT NULL,
    amount_centimos INTEGER NOT NULL DEFAULT 0,

    label TEXT,
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(group_id)
        REFERENCES economic_reconciliation_groups(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_group_items_group
ON economic_reconciliation_group_items(group_id);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_group_items_source
ON economic_reconciliation_group_items(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_economic_reconciliation_group_items_role
ON economic_reconciliation_group_items(role);

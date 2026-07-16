CREATE TABLE IF NOT EXISTS economic_expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS economic_expense_subcategories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    default_iva_rate REAL NOT NULL DEFAULT 0,
    default_irpf_rate REAL NOT NULL DEFAULT 0,
    default_deductible_irpf INTEGER NOT NULL DEFAULT 1,
    default_iva_deductible INTEGER NOT NULL DEFAULT 0,
    default_document_type TEXT NOT NULL DEFAULT 'BANK_STATEMENT',
    sort_order INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id)
        REFERENCES economic_expense_categories(id)
);

CREATE TABLE IF NOT EXISTS economic_counterparties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    counterparty_type TEXT NOT NULL,
    legal_name TEXT NOT NULL,
    trade_name TEXT,
    tax_id TEXT,
    bank_name TEXT,
    supplier_id INTEGER,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_id)
        REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS economic_movement_classification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'bank',
    bank_name TEXT,
    match_type TEXT NOT NULL DEFAULT 'CONTAINS',
    pattern TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    counterparty_id INTEGER,
    category_id INTEGER NOT NULL,
    subcategory_id INTEGER NOT NULL,
    suggested_concept TEXT,
    tax_model TEXT,
    confidence REAL NOT NULL DEFAULT 1,
    requires_confirmation INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (counterparty_id)
        REFERENCES economic_counterparties(id),
    FOREIGN KEY (category_id)
        REFERENCES economic_expense_categories(id),
    FOREIGN KEY (subcategory_id)
        REFERENCES economic_expense_subcategories(id)
);

CREATE INDEX IF NOT EXISTS idx_expense_subcategories_category
ON economic_expense_subcategories(category_id);

CREATE INDEX IF NOT EXISTS idx_counterparties_type
ON economic_counterparties(counterparty_type);

CREATE INDEX IF NOT EXISTS idx_classification_rules_priority
ON economic_movement_classification_rules(
    active,
    priority,
    id
);

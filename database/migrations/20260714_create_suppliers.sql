PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    supplier_code TEXT UNIQUE,

    entity_type TEXT NOT NULL DEFAULT 'COMPANY',
    supplier_type TEXT NOT NULL DEFAULT 'OTHER',

    legal_name TEXT NOT NULL,
    trade_name TEXT,

    document_type TEXT,
    tax_id TEXT,

    first_name TEXT,
    last_name_1 TEXT,
    last_name_2 TEXT,

    category TEXT,
    subcategory TEXT,
    services_description TEXT,

    phone TEXT,
    secondary_phone TEXT,
    email TEXT,
    website TEXT,

    contact_person TEXT,
    contact_position TEXT,

    address TEXT,
    postal_code TEXT,
    city TEXT,
    province TEXT,
    country TEXT DEFAULT 'España',

    usual_payment_method TEXT,
    payment_terms_days INTEGER NOT NULL DEFAULT 0,
    iban TEXT,

    usual_vat_rate REAL NOT NULL DEFAULT 21,
    usual_irpf_rate REAL NOT NULL DEFAULT 0,

    issues_invoice INTEGER NOT NULL DEFAULT 1,
    usual_document_type TEXT NOT NULL DEFAULT 'INVOICE',

    recurring INTEGER NOT NULL DEFAULT 0,
    preferred INTEGER NOT NULL DEFAULT 0,

    customer_reference TEXT,
    contract_reference TEXT,
    external_reference TEXT,

    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_suppliers_legal_name
ON suppliers(legal_name);

CREATE INDEX IF NOT EXISTS idx_suppliers_tax_id
ON suppliers(tax_id);

CREATE INDEX IF NOT EXISTS idx_suppliers_category
ON suppliers(category);

CREATE INDEX IF NOT EXISTS idx_suppliers_supplier_type
ON suppliers(supplier_type);

CREATE INDEX IF NOT EXISTS idx_suppliers_active
ON suppliers(active);

CREATE INDEX IF NOT EXISTS idx_suppliers_preferred
ON suppliers(preferred);

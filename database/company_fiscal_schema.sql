CREATE TABLE IF NOT EXISTS company_fiscal_years (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    fiscal_year INTEGER NOT NULL,
    accounting_close_date TEXT,
    net_revenue TEXT,
    operating_result TEXT,
    profit_before_tax TEXT,
    profit_after_tax TEXT,
    equity TEXT,
    assets_total TEXT,
    liabilities_total TEXT,
    average_employees TEXT,
    source_document_id INTEGER,
    verified INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id) REFERENCES company_tax_documents(id) ON DELETE SET NULL,
    UNIQUE(company_id, fiscal_year)
);

CREATE TABLE IF NOT EXISTS company_tax_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    fiscal_year INTEGER,
    period TEXT,
    document_type TEXT NOT NULL,
    model_number TEXT,
    document_date TEXT,
    filing_date TEXT,
    valid_until TEXT,
    box_path TEXT,
    file_name TEXT,
    file_hash TEXT,
    status TEXT DEFAULT 'pendiente',
    verified INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_company_tax_documents_company ON company_tax_documents(company_id);
CREATE INDEX IF NOT EXISTS idx_company_tax_documents_year ON company_tax_documents(company_id, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_company_tax_documents_type ON company_tax_documents(document_type, model_number);

CREATE TABLE IF NOT EXISTS company_financial_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    fiscal_year INTEGER,
    tax_document_id INTEGER,
    metric_key TEXT NOT NULL,
    metric_label TEXT,
    metric_value TEXT,
    metric_unit TEXT,
    source_page INTEGER,
    confidence REAL,
    reviewed INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (tax_document_id) REFERENCES company_tax_documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_company_financial_metrics_company ON company_financial_metrics(company_id, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_company_financial_metrics_document ON company_financial_metrics(tax_document_id);

CREATE TABLE IF NOT EXISTS expedient_company_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expedient_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    tax_document_id INTEGER NOT NULL,
    contract_id INTEGER,
    usage_type TEXT DEFAULT 'fiscal',
    required_for TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expedient_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (tax_document_id) REFERENCES company_tax_documents(id) ON DELETE CASCADE,
    FOREIGN KEY (contract_id) REFERENCES expedient_contracts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_expedient_company_documents_expedient ON expedient_company_documents(expedient_id);
CREATE INDEX IF NOT EXISTS idx_expedient_company_documents_company ON expedient_company_documents(company_id);
CREATE INDEX IF NOT EXISTS idx_expedient_company_documents_document ON expedient_company_documents(tax_document_id);

-- Entidades empleadoras / empresas / autónomos / personas físicas empleadoras
-- Fase 1: entidad maestra + vínculo cliente-empresa + contrato por expediente.

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT DEFAULT 'juridica',
    name TEXT NOT NULL,
    trade_name TEXT,
    document_type TEXT,
    tax_id TEXT,
    first_name TEXT,
    last_name_1 TEXT,
    last_name_2 TEXT,
    company_type TEXT,
    cnae_code TEXT,
    cnae_description TEXT,
    main_activity TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    address TEXT,
    tipo_via TEXT,
    nombre_via TEXT,
    numero TEXT,
    piso TEXT,
    puerta TEXT,
    escalera TEXT,
    postal_code TEXT,
    city TEXT,
    province TEXT,
    country TEXT DEFAULT 'España',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_companies_tax_id ON companies(tax_id COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_companies_entity_type ON companies(entity_type);

CREATE TABLE IF NOT EXISTS company_representatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    document_type TEXT,
    document_number TEXT,
    position TEXT,
    phone TEXT,
    email TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_company_representatives_company_id ON company_representatives(company_id);
CREATE INDEX IF NOT EXISTS idx_company_representatives_document ON company_representatives(document_number COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS client_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    representative_id INTEGER,
    relationship_type TEXT DEFAULT 'empleador',
    start_date TEXT,
    end_date TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (representative_id) REFERENCES company_representatives(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_client_companies_client_id ON client_companies(client_id);
CREATE INDEX IF NOT EXISTS idx_client_companies_company_id ON client_companies(company_id);
CREATE INDEX IF NOT EXISTS idx_client_companies_active ON client_companies(client_id, is_active);

CREATE TABLE IF NOT EXISTS expedient_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expedient_id INTEGER NOT NULL,
    client_company_id INTEGER NOT NULL,
    is_primary INTEGER DEFAULT 1,
    contract_type TEXT,
    contract_position TEXT,
    contract_cno_code TEXT,
    contract_cno_description TEXT,
    contract_start_date TEXT,
    contract_end_date TEXT,
    contract_hours TEXT,
    salary_amount TEXT,
    salary_period TEXT,
    work_center_address TEXT,
    work_center_tipo_via TEXT,
    work_center_nombre_via TEXT,
    work_center_numero TEXT,
    work_center_piso TEXT,
    work_center_puerta TEXT,
    work_center_escalera TEXT,
    work_center_postal_code TEXT,
    work_center_city TEXT,
    work_center_province TEXT,
    box_contract_path TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expedient_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (client_company_id) REFERENCES client_companies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_expedient_contracts_expedient_id ON expedient_contracts(expedient_id);
CREATE INDEX IF NOT EXISTS idx_expedient_contracts_client_company_id ON expedient_contracts(client_company_id);
CREATE INDEX IF NOT EXISTS idx_expedient_contracts_primary ON expedient_contracts(expedient_id, is_primary);

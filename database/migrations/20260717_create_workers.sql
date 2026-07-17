PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    worker_code TEXT UNIQUE,

    first_name TEXT NOT NULL,
    last_name_1 TEXT,
    last_name_2 TEXT,

    document_type TEXT,
    tax_id TEXT UNIQUE,
    birth_date TEXT,
    social_security_number TEXT,

    phone TEXT,
    secondary_phone TEXT,
    email TEXT,

    address TEXT,
    postal_code TEXT,
    city TEXT,
    province TEXT,
    country TEXT NOT NULL DEFAULT 'España',

    iban TEXT,

    position TEXT,
    department TEXT,
    workplace TEXT,

    professional_category TEXT,
    collective_agreement TEXT,

    hire_date TEXT,
    termination_date TEXT,

    employment_status TEXT NOT NULL DEFAULT 'ACTIVE',
    active INTEGER NOT NULL DEFAULT 1,

    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workers_name
ON workers(first_name, last_name_1, last_name_2);

CREATE INDEX IF NOT EXISTS idx_workers_tax_id
ON workers(tax_id);

CREATE INDEX IF NOT EXISTS idx_workers_status
ON workers(employment_status);

CREATE INDEX IF NOT EXISTS idx_workers_department
ON workers(department);

CREATE INDEX IF NOT EXISTS idx_workers_active
ON workers(active);


CREATE TABLE IF NOT EXISTS worker_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    worker_id INTEGER NOT NULL,

    contract_code TEXT,
    contract_type TEXT NOT NULL DEFAULT 'INDEFINITE',

    start_date TEXT NOT NULL,
    end_date TEXT,
    trial_period_end_date TEXT,

    workday_type TEXT NOT NULL DEFAULT 'FULL_TIME',
    weekly_hours REAL NOT NULL DEFAULT 40,

    gross_salary_centimos INTEGER NOT NULL DEFAULT 0,
    salary_periodicity TEXT NOT NULL DEFAULT 'ANNUAL',
    payments_per_year INTEGER NOT NULL DEFAULT 14,

    contribution_group TEXT,
    professional_category TEXT,
    collective_agreement TEXT,

    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (worker_id)
        REFERENCES workers(id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_worker_contracts_worker
ON worker_contracts(worker_id);

CREATE INDEX IF NOT EXISTS idx_worker_contracts_dates
ON worker_contracts(start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_worker_contracts_active
ON worker_contracts(active);

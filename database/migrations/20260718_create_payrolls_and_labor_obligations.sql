PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS worker_payrolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    contract_id INTEGER,

    period_year INTEGER NOT NULL,
    period_month INTEGER NOT NULL,
    accrual_date TEXT NOT NULL,
    payment_due_date TEXT,

    gross_salary_centimos INTEGER NOT NULL DEFAULT 0,
    employee_social_security_centimos INTEGER NOT NULL DEFAULT 0,
    irpf_centimos INTEGER NOT NULL DEFAULT 0,
    other_deductions_centimos INTEGER NOT NULL DEFAULT 0,
    net_salary_centimos INTEGER NOT NULL DEFAULT 0,

    employer_social_security_centimos INTEGER NOT NULL DEFAULT 0,
    total_employer_cost_centimos INTEGER NOT NULL DEFAULT 0,

    salary_expense_id INTEGER,
    document_path TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (worker_id)
        REFERENCES workers(id)
        ON DELETE CASCADE,

    FOREIGN KEY (contract_id)
        REFERENCES worker_contracts(id)
        ON DELETE SET NULL,

    FOREIGN KEY (salary_expense_id)
        REFERENCES eco_gastos(id)
        ON DELETE SET NULL,

    CHECK (period_month BETWEEN 1 AND 12),
    CHECK (gross_salary_centimos >= 0),
    CHECK (employee_social_security_centimos >= 0),
    CHECK (irpf_centimos >= 0),
    CHECK (other_deductions_centimos >= 0),
    CHECK (net_salary_centimos >= 0),
    CHECK (employer_social_security_centimos >= 0),
    CHECK (total_employer_cost_centimos >= 0),

    UNIQUE (
        worker_id,
        period_year,
        period_month,
        active
    )
);

CREATE INDEX IF NOT EXISTS idx_worker_payrolls_worker
ON worker_payrolls(worker_id);

CREATE INDEX IF NOT EXISTS idx_worker_payrolls_period
ON worker_payrolls(period_year, period_month);

CREATE INDEX IF NOT EXISTS idx_worker_payrolls_expense
ON worker_payrolls(salary_expense_id);


CREATE TABLE IF NOT EXISTS labor_social_security_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    period_year INTEGER NOT NULL,
    period_month INTEGER NOT NULL,
    payment_due_date TEXT,

    employee_amount_centimos INTEGER NOT NULL DEFAULT 0,
    employer_amount_centimos INTEGER NOT NULL DEFAULT 0,
    other_amount_centimos INTEGER NOT NULL DEFAULT 0,
    total_payable_centimos INTEGER NOT NULL DEFAULT 0,

    employer_expense_id INTEGER,
    document_path TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (employer_expense_id)
        REFERENCES eco_gastos(id)
        ON DELETE SET NULL,

    CHECK (period_month BETWEEN 1 AND 12),
    CHECK (employee_amount_centimos >= 0),
    CHECK (employer_amount_centimos >= 0),
    CHECK (other_amount_centimos >= 0),
    CHECK (total_payable_centimos >= 0),

    UNIQUE (
        period_year,
        period_month,
        active
    )
);

CREATE INDEX IF NOT EXISTS idx_labor_ss_period
ON labor_social_security_periods(
    period_year,
    period_month
);

CREATE INDEX IF NOT EXISTS idx_labor_ss_expense
ON labor_social_security_periods(
    employer_expense_id
);


CREATE TABLE IF NOT EXISTS labor_payroll_reconciliation_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_type TEXT NOT NULL DEFAULT 'bank',
    source_movement_id INTEGER NOT NULL,
    payroll_id INTEGER NOT NULL,
    amount_centimos INTEGER NOT NULL,

    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (payroll_id)
        REFERENCES worker_payrolls(id)
        ON DELETE CASCADE,

    CHECK (amount_centimos > 0),

    UNIQUE (
        source_type,
        source_movement_id,
        payroll_id
    )
);

CREATE INDEX IF NOT EXISTS idx_lpra_source
ON labor_payroll_reconciliation_applications(
    source_type,
    source_movement_id
);

CREATE INDEX IF NOT EXISTS idx_lpra_payroll
ON labor_payroll_reconciliation_applications(
    payroll_id
);


CREATE TABLE IF NOT EXISTS labor_social_security_reconciliation_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_type TEXT NOT NULL DEFAULT 'bank',
    source_movement_id INTEGER NOT NULL,
    social_security_period_id INTEGER NOT NULL,
    amount_centimos INTEGER NOT NULL,

    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (social_security_period_id)
        REFERENCES labor_social_security_periods(id)
        ON DELETE CASCADE,

    CHECK (amount_centimos > 0),

    UNIQUE (
        source_type,
        source_movement_id,
        social_security_period_id
    )
);

CREATE INDEX IF NOT EXISTS idx_lssra_source
ON labor_social_security_reconciliation_applications(
    source_type,
    source_movement_id
);

CREATE INDEX IF NOT EXISTS idx_lssra_period
ON labor_social_security_reconciliation_applications(
    social_security_period_id
);

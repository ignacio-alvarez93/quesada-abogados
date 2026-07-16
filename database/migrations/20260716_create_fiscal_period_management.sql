CREATE TABLE IF NOT EXISTS fiscal_period_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    fiscal_year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    model_number TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'OPEN',

    compensation_previous_centimos INTEGER NOT NULL DEFAULT 0,

    payment_rate REAL NOT NULL DEFAULT 20,
    previous_positive_payments_centimos INTEGER NOT NULL DEFAULT 0,

    apply_difficult_to_justify_expenses INTEGER NOT NULL DEFAULT 1,
    difficult_expense_rate REAL NOT NULL DEFAULT 5,
    difficult_expense_annual_limit_centimos INTEGER NOT NULL DEFAULT 200000,

    advisory_reduction_centimos INTEGER NOT NULL DEFAULT 0,
    other_adjustments_centimos INTEGER NOT NULL DEFAULT 0,

    notes TEXT,

    reviewed_at TEXT,
    closed_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (quarter BETWEEN 1 AND 4),
    CHECK (model_number IN ('303', '130')),
    CHECK (status IN ('OPEN', 'REVIEWED', 'CLOSED')),

    CHECK (compensation_previous_centimos >= 0),
    CHECK (payment_rate >= 0 AND payment_rate <= 100),
    CHECK (previous_positive_payments_centimos >= 0),

    CHECK (
        apply_difficult_to_justify_expenses IN (0, 1)
    ),

    CHECK (
        difficult_expense_rate >= 0
        AND difficult_expense_rate <= 100
    ),

    CHECK (
        difficult_expense_annual_limit_centimos >= 0
    ),

    CHECK (advisory_reduction_centimos >= 0),

    UNIQUE (
        fiscal_year,
        quarter,
        model_number
    )
);

CREATE TABLE IF NOT EXISTS fiscal_advisory_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    fiscal_year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    model_number TEXT NOT NULL,

    crm_confirmed_result_centimos INTEGER,
    crm_provisional_result_centimos INTEGER,

    advisory_result_centimos INTEGER,
    difference_centimos INTEGER,

    advisory_result_type TEXT,

    explanation TEXT,
    advisory_notes TEXT,

    document_path TEXT,
    document_name TEXT,

    compared_at TEXT,
    reviewed_by TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (quarter BETWEEN 1 AND 4),
    CHECK (model_number IN ('303', '130')),

    CHECK (
        advisory_result_type IS NULL
        OR advisory_result_type IN (
            'A_PAGAR',
            'A_COMPENSAR',
            'A_DEVOLVER',
            'CERO',
            'OTRO'
        )
    ),

    UNIQUE (
        fiscal_year,
        quarter,
        model_number
    )
);

CREATE INDEX IF NOT EXISTS idx_fiscal_period_settings_period
ON fiscal_period_settings (
    fiscal_year,
    quarter,
    model_number
);

CREATE INDEX IF NOT EXISTS idx_fiscal_period_settings_status
ON fiscal_period_settings (
    status,
    fiscal_year,
    quarter
);

CREATE INDEX IF NOT EXISTS idx_fiscal_advisory_period
ON fiscal_advisory_comparisons (
    fiscal_year,
    quarter,
    model_number
);

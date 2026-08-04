PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expedient_income_evidence_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL,

    source_path TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_suffix TEXT,

    sha256 TEXT NOT NULL,

    page_count INTEGER NOT NULL DEFAULT 0,
    pages_with_text INTEGER NOT NULL DEFAULT 0,
    payroll_count INTEGER NOT NULL DEFAULT 0,

    extraction_status TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION',
    requires_ocr INTEGER NOT NULL DEFAULT 0,
    requires_manual_review INTEGER NOT NULL DEFAULT 1,

    unclassified_pages_json TEXT,
    warnings_json TEXT,
    raw_extraction_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    CHECK (page_count >= 0),
    CHECK (pages_with_text >= 0),
    CHECK (payroll_count >= 0),
    CHECK (requires_ocr IN (0, 1)),
    CHECK (requires_manual_review IN (0, 1)),

    UNIQUE (
        expediente_id,
        sha256
    )
);

CREATE INDEX IF NOT EXISTS idx_eied_expediente
ON expedient_income_evidence_documents(
    expediente_id
);

CREATE INDEX IF NOT EXISTS idx_eied_status
ON expedient_income_evidence_documents(
    extraction_status
);

CREATE INDEX IF NOT EXISTS idx_eied_sha256
ON expedient_income_evidence_documents(
    sha256
);


CREATE TABLE IF NOT EXISTS expedient_payroll_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    document_id INTEGER NOT NULL,

    sequence INTEGER NOT NULL,

    source_page_start INTEGER,
    source_page_end INTEGER,
    source_pages_json TEXT,

    period_year INTEGER,
    period_month INTEGER,
    period_key TEXT,

    employee_name TEXT,
    employee_identity TEXT,

    company_name TEXT,
    company_tax_id TEXT,

    total_accrued_centimos INTEGER,
    total_deductions_centimos INTEGER,
    net_pay_centimos INTEGER,

    contribution_base_centimos INTEGER,
    irpf_centimos INTEGER,

    confidence REAL NOT NULL DEFAULT 0,

    field_confidence_json TEXT,
    warnings_json TEXT,
    raw_extraction_json TEXT,

    review_status TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION',
    requires_manual_review INTEGER NOT NULL DEFAULT 1,

    reviewed_at TEXT,
    applied_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (document_id)
        REFERENCES expedient_income_evidence_documents(id)
        ON DELETE CASCADE,

    CHECK (sequence > 0),
    CHECK (
        period_month IS NULL
        OR period_month BETWEEN 1 AND 12
    ),
    CHECK (
        total_accrued_centimos IS NULL
        OR total_accrued_centimos >= 0
    ),
    CHECK (
        total_deductions_centimos IS NULL
        OR total_deductions_centimos >= 0
    ),
    CHECK (
        net_pay_centimos IS NULL
        OR net_pay_centimos >= 0
    ),
    CHECK (
        contribution_base_centimos IS NULL
        OR contribution_base_centimos >= 0
    ),
    CHECK (
        irpf_centimos IS NULL
        OR irpf_centimos >= 0
    ),
    CHECK (
        confidence >= 0
        AND confidence <= 1
    ),
    CHECK (
        requires_manual_review IN (0, 1)
    ),

    UNIQUE (
        document_id,
        sequence
    )
);

CREATE INDEX IF NOT EXISTS idx_epp_document
ON expedient_payroll_proposals(
    document_id
);

CREATE INDEX IF NOT EXISTS idx_epp_period
ON expedient_payroll_proposals(
    period_year,
    period_month
);

CREATE INDEX IF NOT EXISTS idx_epp_review_status
ON expedient_payroll_proposals(
    review_status
);

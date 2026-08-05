PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expedient_payroll_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL,
    formulario_id INTEGER NOT NULL,

    field_code TEXT NOT NULL DEFAULT
        'ingresos_mensuales_computables_centimos',

    previous_value_centimos INTEGER,
    applied_value_centimos INTEGER NOT NULL,

    confirmed_payroll_count INTEGER NOT NULL,
    proposal_ids_json TEXT NOT NULL,
    periods_json TEXT NOT NULL,
    consolidation_json TEXT NOT NULL,

    application_status TEXT NOT NULL DEFAULT 'APPLIED',
    applied_by TEXT,
    notes TEXT,

    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reverted_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    FOREIGN KEY (formulario_id)
        REFERENCES config_formularios_expediente(id)
        ON DELETE RESTRICT,

    CHECK (applied_value_centimos >= 0),
    CHECK (confirmed_payroll_count > 0),
    CHECK (
        previous_value_centimos IS NULL
        OR previous_value_centimos >= 0
    ),
    CHECK (
        application_status IN (
            'APPLIED',
            'REVERTED'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_epa_expediente
ON expedient_payroll_applications(
    expediente_id,
    applied_at
);

CREATE INDEX IF NOT EXISTS idx_epa_status
ON expedient_payroll_applications(
    application_status
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_epa_single_active
ON expedient_payroll_applications(
    expediente_id,
    formulario_id,
    field_code
)
WHERE application_status = 'APPLIED';

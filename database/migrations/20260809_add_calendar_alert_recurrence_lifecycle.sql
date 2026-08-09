PRAGMA foreign_keys = ON;

ALTER TABLE calendar_alert_recurrences
ADD COLUMN estado TEXT NOT NULL
    DEFAULT 'ACTIVA'
    CHECK (
        estado IN (
            'ACTIVA',
            'PAUSADA',
            'CANCELADA',
            'FINALIZADA'
        )
    );

CREATE INDEX IF NOT EXISTS
    idx_calendar_alert_recurrences_estado
ON calendar_alert_recurrences(
    estado,
    activo,
    next_occurrence_at
);

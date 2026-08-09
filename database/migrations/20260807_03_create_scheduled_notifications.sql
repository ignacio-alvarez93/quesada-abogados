PRAGMA foreign_keys = ON;

-- Outbox universal de notificaciones programadas.
--
-- No contiene FK polimórfica porque source_id puede apuntar
-- a distintos dominios. La integridad de origen se valida
-- desde scheduled_notification_service.
--
-- source_type:
--   TASK
--   ALERT

CREATE TABLE IF NOT EXISTS scheduled_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_type TEXT NOT NULL
        CHECK (
            source_type IN (
                'TASK',
                'ALERT'
            )
        ),

    source_id INTEGER NOT NULL,

    canal TEXT NOT NULL DEFAULT 'TELEGRAM'
        CHECK (
            canal IN (
                'TELEGRAM'
            )
        ),

    notification_type TEXT NOT NULL,

    scheduled_at TEXT NOT NULL,

    estado TEXT NOT NULL DEFAULT 'PENDIENTE'
        CHECK (
            estado IN (
                'PENDIENTE',
                'PROCESANDO',
                'ENVIADA',
                'ERROR',
                'PAUSADA',
                'OMITIDA',
                'CANCELADA'
            )
        ),

    attempt_count INTEGER NOT NULL DEFAULT 0,

    sent_at TEXT,
    last_attempt_at TEXT,
    last_error TEXT,

    source_key TEXT NOT NULL,

    activo INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_scheduled_notifications_source_key
ON scheduled_notifications(source_key);

CREATE INDEX IF NOT EXISTS
    idx_scheduled_notifications_due
ON scheduled_notifications(
    activo,
    estado,
    scheduled_at
);

CREATE INDEX IF NOT EXISTS
    idx_scheduled_notifications_source
ON scheduled_notifications(
    source_type,
    source_id
);

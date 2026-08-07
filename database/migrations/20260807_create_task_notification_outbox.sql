PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS task_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    task_id INTEGER NOT NULL,

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
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id)
        REFERENCES tasks(id)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_task_notifications_source_key
ON task_notifications(source_key);

CREATE INDEX IF NOT EXISTS
    idx_task_notifications_due
ON task_notifications(
    activo,
    estado,
    scheduled_at
);

CREATE INDEX IF NOT EXISTS
    idx_task_notifications_task
ON task_notifications(task_id);

PRAGMA foreign_keys = ON;

-- ============================================================
-- COMUNICACIONES · SEGUIMIENTO DE LLAMADAS PERDIDAS
-- 2026-08-14
--
-- El lifecycle telefónico permanece en communication_calls.
--
-- Esta migración modela exclusivamente trabajo operativo:
--   - llamadas pendientes de devolver;
--   - estado del seguimiento;
--   - múltiples intentos de devolución.
--
-- Solo utiliza CREATE ... IF NOT EXISTS para que pueda
-- ejecutarse repetidamente por ensure_schema().
-- ============================================================


CREATE TABLE IF NOT EXISTS communication_call_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_call_id INTEGER NOT NULL,

    status TEXT NOT NULL
        DEFAULT 'PENDING',

    resolved_at TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (source_call_id)
        REFERENCES communication_calls(id)
        ON DELETE CASCADE,

    UNIQUE (source_call_id),

    CHECK (
        status IN (
            'PENDING',
            'IN_PROGRESS',
            'RESOLVED'
        )
    ),

    CHECK (
        (
            status = 'RESOLVED'
            AND resolved_at IS NOT NULL
        )
        OR
        (
            status IN (
                'PENDING',
                'IN_PROGRESS'
            )
            AND resolved_at IS NULL
        )
    )
);


CREATE INDEX IF NOT EXISTS
    idx_communication_call_followups_status
ON communication_call_followups(status);


CREATE INDEX IF NOT EXISTS
    idx_communication_call_followups_created
ON communication_call_followups(created_at);


CREATE TABLE IF NOT EXISTS communication_call_callbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_call_id INTEGER NOT NULL,
    callback_call_id INTEGER NOT NULL,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (source_call_id)
        REFERENCES communication_call_followups(
            source_call_id
        )
        ON DELETE CASCADE,

    FOREIGN KEY (callback_call_id)
        REFERENCES communication_calls(id)
        ON DELETE CASCADE,

    UNIQUE (
        source_call_id,
        callback_call_id
    ),

    UNIQUE (
        callback_call_id
    ),

    CHECK (
        source_call_id <> callback_call_id
    )
);


CREATE INDEX IF NOT EXISTS
    idx_communication_call_callbacks_source
ON communication_call_callbacks(
    source_call_id
);


CREATE INDEX IF NOT EXISTS
    idx_communication_call_callbacks_callback
ON communication_call_callbacks(
    callback_call_id
);

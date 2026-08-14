PRAGMA foreign_keys = ON;

-- ============================================================
-- COMUNICACIONES · LLAMADAS
-- 2026-08-14
--
-- Persistencia independiente de proveedor.
--
-- No altera communication_threads, communication_messages
-- ni communication_message_attempts.
--
-- Los vínculos a thread, cliente y expediente son opcionales:
-- una llamada debe poder registrarse aunque el interlocutor
-- todavía no esté identificado en el CRM.
-- ============================================================

CREATE TABLE IF NOT EXISTS communication_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    thread_id INTEGER,
    client_id INTEGER,
    expedient_id INTEGER,

    channel TEXT NOT NULL,
    direction TEXT NOT NULL,

    phone_number TEXT NOT NULL,
    display_name_snapshot TEXT,

    reason_code TEXT,
    reason_detail TEXT,

    status TEXT NOT NULL DEFAULT 'CREATED',
    outcome_code TEXT,

    provider TEXT,
    provider_call_id TEXT,
    external_call_key TEXT,

    dialed_at TEXT,
    ringing_at TEXT,
    answered_at TEXT,
    ended_at TEXT,

    ring_duration_seconds INTEGER,
    talk_duration_seconds INTEGER,
    total_duration_seconds INTEGER,

    notes TEXT,
    created_by TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (thread_id)
        REFERENCES communication_threads(id)
        ON DELETE SET NULL,

    FOREIGN KEY (client_id)
        REFERENCES clientes(id)
        ON DELETE SET NULL,

    FOREIGN KEY (expedient_id)
        REFERENCES expedientes(id)
        ON DELETE SET NULL,

    CHECK (
        ring_duration_seconds IS NULL
        OR ring_duration_seconds >= 0
    ),

    CHECK (
        talk_duration_seconds IS NULL
        OR talk_duration_seconds >= 0
    ),

    CHECK (
        total_duration_seconds IS NULL
        OR total_duration_seconds >= 0
    )
);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_thread
ON communication_calls(thread_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_client
ON communication_calls(client_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_expedient
ON communication_calls(expedient_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_status
ON communication_calls(status);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_created
ON communication_calls(created_at);


CREATE INDEX IF NOT EXISTS
    idx_communication_calls_external
ON communication_calls(
    provider,
    external_call_key
);

PRAGMA foreign_keys = ON;

-- ============================================================
-- CUENTAS DE COMUNICACIÓN
-- ============================================================

CREATE TABLE IF NOT EXISTS communication_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    code TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    display_name TEXT NOT NULL,
    transport TEXT NOT NULL,

    environment TEXT NOT NULL DEFAULT 'DEVELOPMENT',
    profile_key TEXT,

    is_active INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,

    metadata_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (is_active IN (0, 1)),
    CHECK (is_default IN (0, 1))
);


-- ============================================================
-- CONVERSACIONES
-- ============================================================

CREATE TABLE IF NOT EXISTS communication_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    account_id INTEGER NOT NULL,
    client_id INTEGER,

    external_thread_key TEXT NOT NULL,
    external_address TEXT,
    external_display_name TEXT,

    match_status TEXT NOT NULL DEFAULT 'UNMATCHED',
    is_archived INTEGER NOT NULL DEFAULT 0,

    last_message_at TEXT,
    metadata_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (account_id)
        REFERENCES communication_accounts(id),

    FOREIGN KEY (client_id)
        REFERENCES clientes(id),

    UNIQUE(account_id, external_thread_key),

    CHECK (is_archived IN (0, 1))
);


-- ============================================================
-- MENSAJES
-- ============================================================

CREATE TABLE IF NOT EXISTS communication_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    thread_id INTEGER NOT NULL,

    client_id INTEGER,
    expedient_id INTEGER,

    direction TEXT NOT NULL,
    body_text TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'PENDING',

    provider_message_id TEXT,
    provider_timestamp TEXT,

    created_by TEXT,
    sent_by TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,

    FOREIGN KEY (thread_id)
        REFERENCES communication_threads(id),

    FOREIGN KEY (client_id)
        REFERENCES clientes(id),

    FOREIGN KEY (expedient_id)
        REFERENCES expedientes(id)
);


-- ============================================================
-- INTENTOS DE ENVÍO
-- ============================================================

CREATE TABLE IF NOT EXISTS communication_message_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    message_id INTEGER NOT NULL,

    transport TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,

    status TEXT NOT NULL,

    started_at TEXT,
    finished_at TEXT,

    error_code TEXT,
    error_message TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (message_id)
        REFERENCES communication_messages(id)
        ON DELETE CASCADE,

    UNIQUE(message_id, attempt_number),

    CHECK (attempt_number > 0)
);


-- ============================================================
-- ÍNDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS
    idx_communication_threads_account
ON communication_threads(account_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_threads_client
ON communication_threads(client_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_threads_last_message
ON communication_threads(last_message_at);


CREATE INDEX IF NOT EXISTS
    idx_communication_messages_thread
ON communication_messages(thread_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_messages_client
ON communication_messages(client_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_messages_expedient
ON communication_messages(expedient_id);


CREATE INDEX IF NOT EXISTS
    idx_communication_messages_status
ON communication_messages(status);


CREATE INDEX IF NOT EXISTS
    idx_communication_attempts_message
ON communication_message_attempts(message_id);

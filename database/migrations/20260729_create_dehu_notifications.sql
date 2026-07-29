PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dehu_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    dehu_identifier TEXT NOT NULL UNIQUE,
    concept TEXT,

    email_expedient_number TEXT,
    dehu_expedient_number TEXT,

    expediente_id INTEGER,
    cliente_id INTEGER,

    primary_email_message_id INTEGER,

    recipient_name TEXT,
    recipient_document_masked TEXT,

    issuer_name TEXT,
    issuer_dir3 TEXT,
    relationship_type TEXT,

    deadline_at TEXT,

    portal_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    verification_status TEXT NOT NULL DEFAULT 'EMAIL_ONLY',
    download_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED',

    document_inbox_batch_id INTEGER,

    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    accepted_at TEXT,
    rejected_at TEXT,
    downloaded_at TEXT,

    last_error TEXT,

    raw_email_data_json TEXT,
    raw_dehu_data_json TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id),

    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id),

    FOREIGN KEY (primary_email_message_id)
        REFERENCES email_messages(id)
);

CREATE TABLE IF NOT EXISTS
    dehu_notification_email_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        dehu_notification_id INTEGER NOT NULL,
        email_message_id INTEGER NOT NULL,

        provider TEXT,
        account_id INTEGER,

        detected_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (dehu_notification_id)
            REFERENCES dehu_notifications(id),

        FOREIGN KEY (email_message_id)
            REFERENCES email_messages(id),

        UNIQUE(
            dehu_notification_id,
            email_message_id
        )
    );

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_expedient
ON dehu_notifications(expediente_id);

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_number
ON dehu_notifications(email_expedient_number);

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_status
ON dehu_notifications(
    portal_status,
    verification_status,
    download_status
);

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_deadline
ON dehu_notifications(deadline_at);

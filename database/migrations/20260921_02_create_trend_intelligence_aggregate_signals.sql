PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ti_aggregate_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    domain_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    signal_type TEXT NOT NULL,

    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    country TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',

    strength REAL NOT NULL
        CHECK (
            strength >= 0.0
            AND strength <= 100.0
        ),

    confidence REAL NOT NULL
        CHECK (
            confidence >= 0.0
            AND confidence <= 1.0
        ),

    numeric_value REAL,
    text_value TEXT,

    detector_key TEXT NOT NULL,
    detector_version TEXT NOT NULL,

    reason TEXT NOT NULL,

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        domain_id,
        topic_id,
        signal_type,
        country,
        language,
        window_start,
        window_end,
        detector_key,
        detector_version
    ),

    FOREIGN KEY (
        domain_id
    )
    REFERENCES ti_domains(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS
    idx_ti_aggregate_signals_scope
ON ti_aggregate_signals(
    domain_id,
    topic_id,
    country,
    language,
    window_start,
    window_end
);

CREATE INDEX IF NOT EXISTS
    idx_ti_aggregate_signals_detector
ON ti_aggregate_signals(
    detector_key,
    detector_version,
    window_end
);

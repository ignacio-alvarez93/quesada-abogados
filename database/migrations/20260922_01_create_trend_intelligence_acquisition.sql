PRAGMA foreign_keys = ON;

-- ============================================================
-- TREND INTELLIGENCE · SOURCE ACQUISITION V1
--
-- Deterministic collector run lifecycle.
--
-- Source health is derived by querying this table; it is not
-- duplicated into a separate mutable health table.
--
-- No secrets are stored here: credentials/tokens live in collector
-- configuration outside of run state.
-- ============================================================


CREATE TABLE IF NOT EXISTS ti_collector_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL,

    collector_key TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    provider TEXT,

    started_at TEXT NOT NULL,
    completed_at TEXT,

    status TEXT NOT NULL
        DEFAULT 'RUNNING'
        CHECK (
            status IN (
                'RUNNING',
                'SUCCESS',
                'PARTIAL',
                'FAILED'
            )
        ),

    items_seen INTEGER NOT NULL
        DEFAULT 0,

    items_accepted INTEGER NOT NULL
        DEFAULT 0,

    items_rejected INTEGER NOT NULL
        DEFAULT 0,

    error_classification TEXT NOT NULL
        DEFAULT 'NONE'
        CHECK (
            error_classification IN (
                'NONE',
                'NETWORK',
                'AUTH',
                'RATE_LIMIT',
                'PARSE',
                'UNKNOWN'
            )
        ),

    error_message TEXT,

    cursor_value TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        source_id
    )
    REFERENCES ti_sources(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_collector_runs_source_started
ON ti_collector_runs(
    source_id,
    collector_key,
    started_at DESC
);

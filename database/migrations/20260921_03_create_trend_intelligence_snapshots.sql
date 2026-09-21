PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ti_trend_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    domain_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    country TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL
        CHECK (
            status IN (
                'EMERGING',
                'RISING',
                'HOT',
                'STABLE',
                'DECLINING',
                'DORMANT'
            )
        ),

    score REAL NOT NULL
        DEFAULT 0.0
        CHECK (
            score >= 0.0
            AND score <= 100.0
        ),

    velocity REAL NOT NULL
        DEFAULT 0.0,

    aggregate_signal_count INTEGER NOT NULL
        DEFAULT 0
        CHECK (
            aggregate_signal_count >= 0
        ),

    observation_count INTEGER NOT NULL
        DEFAULT 0
        CHECK (
            observation_count >= 0
        ),

    source_count INTEGER NOT NULL
        DEFAULT 0
        CHECK (
            source_count >= 0
        ),

    baseline_observation_mean REAL NOT NULL
        DEFAULT 0.0,

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        domain_id,
        topic_id,
        country,
        language,
        window_start,
        window_end
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
    idx_ti_trend_snapshots_scope
ON ti_trend_snapshots(
    domain_id,
    topic_id,
    country,
    language,
    window_end DESC
);


CREATE INDEX IF NOT EXISTS
    idx_ti_trend_snapshots_status
ON ti_trend_snapshots(
    domain_id,
    status,
    window_end DESC
);

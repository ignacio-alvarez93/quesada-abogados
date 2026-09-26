PRAGMA foreign_keys = ON;

-- ============================================================
-- TREND INTELLIGENCE · TEMPORAL INTELLIGENCE V1
--
-- Persiste:
-- - métricas por ventana temporal;
-- - baselines históricos;
-- - estadísticas necesarias para detección posterior.
--
-- No contiene lógica específica de ningún vertical.
-- ============================================================


CREATE TABLE IF NOT EXISTS ti_temporal_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    domain_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    country TEXT NOT NULL
        DEFAULT '',

    language TEXT NOT NULL
        DEFAULT '',

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

    signal_count INTEGER NOT NULL
        DEFAULT 0
        CHECK (
            signal_count >= 0
        ),

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
    idx_ti_temporal_metrics_lookup
ON ti_temporal_metrics(
    domain_id,
    topic_id,
    country,
    language,
    window_start,
    window_end
);


CREATE INDEX IF NOT EXISTS
    idx_ti_temporal_metrics_history
ON ti_temporal_metrics(
    domain_id,
    topic_id,
    window_end DESC
);


CREATE TABLE IF NOT EXISTS ti_temporal_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    domain_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    reference_window_start TEXT NOT NULL,
    reference_window_end TEXT NOT NULL,

    lookback_windows INTEGER NOT NULL
        CHECK (
            lookback_windows >= 1
        ),

    sample_count INTEGER NOT NULL
        DEFAULT 0
        CHECK (
            sample_count >= 0
        ),

    country TEXT NOT NULL
        DEFAULT '',

    language TEXT NOT NULL
        DEFAULT '',

    observation_mean REAL NOT NULL
        DEFAULT 0.0,

    observation_stddev REAL NOT NULL
        DEFAULT 0.0,

    source_mean REAL NOT NULL
        DEFAULT 0.0,

    source_stddev REAL NOT NULL
        DEFAULT 0.0,

    signal_mean REAL NOT NULL
        DEFAULT 0.0,

    signal_stddev REAL NOT NULL
        DEFAULT 0.0,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        domain_id,
        topic_id,
        country,
        language,
        reference_window_start,
        reference_window_end,
        lookback_windows
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
    idx_ti_temporal_baselines_lookup
ON ti_temporal_baselines(
    domain_id,
    topic_id,
    country,
    language,
    reference_window_start,
    reference_window_end
);

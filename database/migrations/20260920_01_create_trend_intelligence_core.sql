PRAGMA foreign_keys = ON;

-- ============================================================
-- TREND INTELLIGENCE · CORE V1
--
-- Motor transversal.
--
-- El núcleo no depende de ningún vertical funcional
-- ni de consumidores, interfaces o collectors concretos.
--
-- Los dominios son datos configurables.
-- ============================================================


CREATE TABLE IF NOT EXISTS ti_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,

    is_active INTEGER NOT NULL
        DEFAULT 1
        CHECK (
            is_active IN (0, 1)
        ),

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(code)
);


CREATE INDEX IF NOT EXISTS
    idx_ti_domains_active
ON ti_domains(
    is_active,
    name
);


CREATE TABLE IF NOT EXISTS ti_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    code TEXT NOT NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,

    provider TEXT,
    base_url TEXT,

    collection_mode TEXT NOT NULL
        DEFAULT 'MANUAL'
        CHECK (
            collection_mode IN (
                'API',
                'HTTP',
                'MANUAL',
                'IMPORT',
                'QCC',
                'SELENIUM'
            )
        ),

    country TEXT,
    language TEXT,

    is_active INTEGER NOT NULL
        DEFAULT 1
        CHECK (
            is_active IN (0, 1)
        ),

    configuration_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(code)
);


CREATE INDEX IF NOT EXISTS
    idx_ti_sources_active
ON ti_sources(
    is_active,
    source_type
);


CREATE TABLE IF NOT EXISTS ti_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    topic_key TEXT NOT NULL,
    name TEXT NOT NULL,

    description TEXT,
    category TEXT,

    parent_topic_id INTEGER,

    is_active INTEGER NOT NULL
        DEFAULT 1
        CHECK (
            is_active IN (0, 1)
        ),

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(topic_key),

    FOREIGN KEY (
        parent_topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE SET NULL
);


CREATE INDEX IF NOT EXISTS
    idx_ti_topics_parent
ON ti_topics(
    parent_topic_id
);


CREATE TABLE IF NOT EXISTS ti_topic_domains (
    topic_id INTEGER NOT NULL,
    domain_id INTEGER NOT NULL,

    relevance REAL NOT NULL
        DEFAULT 1.0
        CHECK (
            relevance >= 0.0
            AND relevance <= 1.0
        ),

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        topic_id,
        domain_id
    ),

    FOREIGN KEY (
        topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        domain_id
    )
    REFERENCES ti_domains(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_topic_domains_domain
ON ti_topic_domains(
    domain_id,
    topic_id
);


CREATE TABLE IF NOT EXISTS ti_topic_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    topic_id INTEGER NOT NULL,

    alias_key TEXT NOT NULL,
    alias_text TEXT NOT NULL,

    language TEXT NOT NULL
        DEFAULT '',

    country TEXT NOT NULL
        DEFAULT '',

    confidence REAL NOT NULL
        DEFAULT 1.0
        CHECK (
            confidence >= 0.0
            AND confidence <= 1.0
        ),

    is_active INTEGER NOT NULL
        DEFAULT 1
        CHECK (
            is_active IN (0, 1)
        ),

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        alias_key,
        language,
        country
    ),

    FOREIGN KEY (
        topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_topic_aliases_topic
ON ti_topic_aliases(
    topic_id,
    is_active
);


CREATE INDEX IF NOT EXISTS
    idx_ti_topic_aliases_lookup
ON ti_topic_aliases(
    alias_key,
    language,
    country,
    is_active
);


CREATE TABLE IF NOT EXISTS ti_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_id INTEGER NOT NULL,

    external_id TEXT,
    observation_type TEXT NOT NULL,

    url TEXT,
    title TEXT,
    body_text TEXT,
    author TEXT,

    published_at TEXT,
    observed_at TEXT NOT NULL,

    language TEXT,
    country TEXT,

    content_hash TEXT,

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        source_id
    )
    REFERENCES ti_sources(id)
    ON DELETE CASCADE
);


CREATE UNIQUE INDEX IF NOT EXISTS
    ux_ti_observations_external
ON ti_observations(
    source_id,
    external_id
)
WHERE
    external_id IS NOT NULL
    AND TRIM(external_id) <> '';


CREATE UNIQUE INDEX IF NOT EXISTS
    ux_ti_observations_hash
ON ti_observations(
    source_id,
    content_hash
)
WHERE
    content_hash IS NOT NULL
    AND TRIM(content_hash) <> '';


CREATE INDEX IF NOT EXISTS
    idx_ti_observations_source_time
ON ti_observations(
    source_id,
    observed_at
);


CREATE TABLE IF NOT EXISTS ti_observation_domains (
    observation_id INTEGER NOT NULL,
    domain_id INTEGER NOT NULL,

    confidence REAL NOT NULL
        DEFAULT 1.0
        CHECK (
            confidence >= 0.0
            AND confidence <= 1.0
        ),

    detection_method TEXT NOT NULL
        DEFAULT 'MANUAL',

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        observation_id,
        domain_id
    ),

    FOREIGN KEY (
        observation_id
    )
    REFERENCES ti_observations(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        domain_id
    )
    REFERENCES ti_domains(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_observation_domains_domain
ON ti_observation_domains(
    domain_id,
    observation_id
);


CREATE TABLE IF NOT EXISTS ti_observation_topics (
    observation_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    confidence REAL NOT NULL
        DEFAULT 1.0
        CHECK (
            confidence >= 0.0
            AND confidence <= 1.0
        ),

    detection_method TEXT NOT NULL
        DEFAULT 'MANUAL',

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        observation_id,
        topic_id
    ),

    FOREIGN KEY (
        observation_id
    )
    REFERENCES ti_observations(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_observation_topics_topic
ON ti_observation_topics(
    topic_id,
    observation_id
);


CREATE TABLE IF NOT EXISTS ti_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    observation_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

    signal_type TEXT NOT NULL
        CHECK (
            signal_type IN (
                'MENTION',
                'QUESTION',
                'HIGH_ENGAGEMENT',
                'GROWTH',
                'RECURRENCE',
                'NEW_TOPIC',
                'CROSS_SOURCE',
                'VOLUME_SPIKE',
                'SEARCH_GROWTH',
                'SENTIMENT_SHIFT'
            )
        ),

    strength REAL NOT NULL
        CHECK (
            strength >= 0.0
            AND strength <= 100.0
        ),

    confidence REAL NOT NULL
        DEFAULT 1.0
        CHECK (
            confidence >= 0.0
            AND confidence <= 1.0
        ),

    numeric_value REAL,
    text_value TEXT,

    detected_at TEXT NOT NULL,

    metadata_json TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        observation_id,
        topic_id,
        signal_type
    ),

    FOREIGN KEY (
        observation_id
    )
    REFERENCES ti_observations(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        topic_id
    )
    REFERENCES ti_topics(id)
    ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_ti_signals_topic_time
ON ti_signals(
    topic_id,
    detected_at
);


CREATE TABLE IF NOT EXISTS ti_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    domain_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,

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
        CHECK (
            score >= 0.0
            AND score <= 100.0
        ),

    velocity REAL NOT NULL
        DEFAULT 0.0,

    observation_count INTEGER NOT NULL
        DEFAULT 0,

    source_count INTEGER NOT NULL
        DEFAULT 0,

    signal_count INTEGER NOT NULL
        DEFAULT 0,

    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    country TEXT NOT NULL
        DEFAULT '',

    language TEXT NOT NULL
        DEFAULT '',

    first_seen_at TEXT,
    last_seen_at TEXT,

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
    idx_ti_trends_domain_score
ON ti_trends(
    domain_id,
    status,
    score DESC
);


CREATE INDEX IF NOT EXISTS
    idx_ti_trends_topic_window
ON ti_trends(
    topic_id,
    window_end DESC
);


CREATE TABLE IF NOT EXISTS ti_trend_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    trend_id INTEGER NOT NULL,
    signal_id INTEGER NOT NULL,

    weight REAL NOT NULL
        CHECK (
            weight >= 0.0
        ),

    reason TEXT NOT NULL,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        trend_id,
        signal_id
    ),

    FOREIGN KEY (
        trend_id
    )
    REFERENCES ti_trends(id)
    ON DELETE CASCADE,

    FOREIGN KEY (
        signal_id
    )
    REFERENCES ti_signals(id)
    ON DELETE CASCADE
);

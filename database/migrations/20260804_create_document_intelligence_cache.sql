PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS document_intelligence_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_sha256 TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_suffix TEXT,
    mime_type TEXT,

    pipeline_version TEXT NOT NULL,
    native_extractor TEXT NOT NULL,

    ocr_engine TEXT NOT NULL,
    ocr_engine_version TEXT NOT NULL,
    ocr_language TEXT NOT NULL,

    render_dpi INTEGER NOT NULL,
    policy_fingerprint TEXT NOT NULL,

    status TEXT NOT NULL,

    page_count INTEGER NOT NULL DEFAULT 0,
    native_text_pages INTEGER NOT NULL DEFAULT 0,
    ocr_text_pages INTEGER NOT NULL DEFAULT 0,
    requires_ocr INTEGER NOT NULL DEFAULT 0,

    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (page_count >= 0),
    CHECK (native_text_pages >= 0),
    CHECK (ocr_text_pages >= 0),
    CHECK (render_dpi >= 72),
    CHECK (requires_ocr IN (0, 1)),

    CHECK (
        status IN (
            'NATIVE_TEXT',
            'PARTIAL_OCR_REQUIRED',
            'OCR_REQUIRED',
            'EMPTY_DOCUMENT',
            'UNSUPPORTED',
            'ERROR'
        )
    ),

    UNIQUE (
        source_sha256,
        pipeline_version,
        native_extractor,
        ocr_engine,
        ocr_engine_version,
        ocr_language,
        render_dpi,
        policy_fingerprint
    )
);

CREATE INDEX IF NOT EXISTS
    idx_document_intelligence_runs_sha256
ON document_intelligence_runs(
    source_sha256
);

CREATE INDEX IF NOT EXISTS
    idx_document_intelligence_runs_status
ON document_intelligence_runs(
    status
);

CREATE INDEX IF NOT EXISTS
    idx_document_intelligence_runs_created
ON document_intelligence_runs(
    created_at
);


CREATE TABLE IF NOT EXISTS document_intelligence_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,

    text TEXT NOT NULL DEFAULT '',
    text_source TEXT NOT NULL DEFAULT 'NONE',
    confidence REAL NOT NULL DEFAULT 0,
    requires_ocr INTEGER NOT NULL DEFAULT 0,

    rotation INTEGER NOT NULL DEFAULT 0,
    language TEXT,

    warnings_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id)
        REFERENCES document_intelligence_runs(id)
        ON DELETE CASCADE,

    CHECK (page_number > 0),

    CHECK (
        text_source IN (
            'NATIVE',
            'OCR',
            'NONE'
        )
    ),

    CHECK (
        confidence >= 0
        AND confidence <= 1
    ),

    CHECK (
        requires_ocr IN (0, 1)
    ),

    UNIQUE (
        run_id,
        page_number
    )
);

CREATE INDEX IF NOT EXISTS
    idx_document_intelligence_pages_run
ON document_intelligence_pages(
    run_id
);

CREATE INDEX IF NOT EXISTS
    idx_document_intelligence_pages_source
ON document_intelligence_pages(
    text_source
);

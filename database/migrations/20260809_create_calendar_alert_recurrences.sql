PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS
    calendar_alert_recurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        root_alert_id INTEGER NOT NULL,

        frequency_unit TEXT NOT NULL
            CHECK (
                frequency_unit IN (
                    'DAY',
                    'WEEK',
                    'MONTH',
                    'YEAR'
                )
            ),

        interval_value INTEGER NOT NULL
            DEFAULT 1
            CHECK (
                interval_value >= 1
            ),

        end_type TEXT NOT NULL
            DEFAULT 'NEVER'
            CHECK (
                end_type IN (
                    'NEVER',
                    'DATE',
                    'COUNT'
                )
            ),

        end_date TEXT,

        max_occurrences INTEGER,

        anchor_at TEXT NOT NULL,
        anchor_day INTEGER,

        next_occurrence_at TEXT,
        last_occurrence_at TEXT,

        occurrences_generated INTEGER NOT NULL
            DEFAULT 1,

        activo INTEGER NOT NULL
            DEFAULT 1,

        created_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        updated_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (root_alert_id)
            REFERENCES calendar_alerts(id)
    );

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alert_recurrences_root
ON calendar_alert_recurrences(
    root_alert_id
);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alert_recurrences_next
ON calendar_alert_recurrences(
    activo,
    next_occurrence_at
);

CREATE TABLE IF NOT EXISTS
    calendar_alert_recurrence_occurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        recurrence_id INTEGER NOT NULL,
        alert_id INTEGER NOT NULL,

        occurrence_index INTEGER NOT NULL,
        occurrence_at TEXT NOT NULL,

        created_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (recurrence_id)
            REFERENCES calendar_alert_recurrences(id),

        FOREIGN KEY (alert_id)
            REFERENCES calendar_alerts(id)
    );

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alert_recurrence_occurrence_index
ON calendar_alert_recurrence_occurrences(
    recurrence_id,
    occurrence_index
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alert_recurrence_occurrence_alert
ON calendar_alert_recurrence_occurrences(
    alert_id
);

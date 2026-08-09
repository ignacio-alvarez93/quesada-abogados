PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS
    calendar_alert_recurrence_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        recurrence_id INTEGER NOT NULL,

        notification_id INTEGER NOT NULL,

        occurrence_index INTEGER NOT NULL,

        scheduled_at TEXT NOT NULL,

        created_at TEXT
            NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (
            recurrence_id
        )
        REFERENCES calendar_alert_recurrences(id),

        FOREIGN KEY (
            notification_id
        )
        REFERENCES scheduled_notifications(id)
    );

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alert_recurrence_notification_index
ON calendar_alert_recurrence_notifications(
    recurrence_id,
    occurrence_index
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alert_recurrence_notification_id
ON calendar_alert_recurrence_notifications(
    notification_id
);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alert_recurrence_notification_schedule
ON calendar_alert_recurrence_notifications(
    recurrence_id,
    scheduled_at
);

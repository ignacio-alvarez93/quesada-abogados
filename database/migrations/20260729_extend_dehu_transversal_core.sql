PRAGMA foreign_keys = ON;

ALTER TABLE dehu_notifications
    ADD COLUMN item_type TEXT NOT NULL
        DEFAULT 'UNKNOWN';

ALTER TABLE dehu_notifications
    ADD COLUMN concept_type TEXT NOT NULL
        DEFAULT 'UNKNOWN';

ALTER TABLE dehu_notifications
    ADD COLUMN reference_value TEXT;

ALTER TABLE dehu_notifications
    ADD COLUMN reference_type TEXT NOT NULL
        DEFAULT 'UNKNOWN';

ALTER TABLE dehu_notifications
    ADD COLUMN family_hint TEXT NOT NULL
        DEFAULT 'UNKNOWN';

ALTER TABLE dehu_notifications
    ADD COLUMN direct_access_url TEXT;

ALTER TABLE dehu_notification_email_sources
    ADD COLUMN source_folder TEXT;

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_item_type
ON dehu_notifications(item_type);

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_reference
ON dehu_notifications(
    reference_type,
    reference_value
);

CREATE INDEX IF NOT EXISTS
    idx_dehu_notification_family
ON dehu_notifications(
    family_hint,
    verification_status
);

CREATE INDEX IF NOT EXISTS
    idx_dehu_source_origin
ON dehu_notification_email_sources(
    provider,
    account_id,
    source_folder
);

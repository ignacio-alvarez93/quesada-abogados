PRAGMA foreign_keys = ON;

ALTER TABLE expedientes
    ADD COLUMN fecha_admision_tramite TEXT;

ALTER TABLE expedientes
    ADD COLUMN csv_admision_tramite TEXT;

ALTER TABLE expedientes
    ADD COLUMN admision_tramite_sha256 TEXT;

ALTER TABLE expedientes
    ADD COLUMN admision_extraction_status TEXT;

ALTER TABLE expedientes
    ADD COLUMN admision_extraction_json TEXT;

ALTER TABLE expedientes
    ADD COLUMN admision_extracted_at TEXT;

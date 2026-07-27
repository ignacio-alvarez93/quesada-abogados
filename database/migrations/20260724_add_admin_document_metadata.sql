PRAGMA foreign_keys = ON;

ALTER TABLE expediente_justificantes
    ADD COLUMN fecha_documento TEXT;

ALTER TABLE expediente_justificantes
    ADD COLUMN csv_documento TEXT;

ALTER TABLE expediente_justificantes
    ADD COLUMN dir3_documento TEXT;

ALTER TABLE expediente_justificantes
    ADD COLUMN organo_documento TEXT;

ALTER TABLE expediente_justificantes
    ADD COLUMN metadata_documento_json TEXT;

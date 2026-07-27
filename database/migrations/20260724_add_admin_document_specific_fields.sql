PRAGMA foreign_keys = ON;

ALTER TABLE expediente_justificantes
    ADD COLUMN nie_documento TEXT;

ALTER TABLE expediente_justificantes
    ADD COLUMN numero_expediente_documento TEXT;

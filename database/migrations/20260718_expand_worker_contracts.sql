PRAGMA foreign_keys = ON;

ALTER TABLE worker_contracts
ADD COLUMN contract_position TEXT;

ALTER TABLE worker_contracts
ADD COLUMN contract_cno_code TEXT;

ALTER TABLE worker_contracts
ADD COLUMN contract_cno_description TEXT;

ALTER TABLE worker_contracts
ADD COLUMN document_path TEXT;

CREATE INDEX IF NOT EXISTS idx_worker_contracts_cno
ON worker_contracts(contract_cno_code);

ALTER TABLE worker_contracts
ADD COLUMN contract_cno_catalog_id TEXT;

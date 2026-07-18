PRAGMA foreign_keys = ON;

ALTER TABLE worker_payrolls
ADD COLUMN liquidation_start_date TEXT;

ALTER TABLE worker_payrolls
ADD COLUMN liquidation_end_date TEXT;

ALTER TABLE worker_payrolls
ADD COLUMN liquidation_days INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN contribution_common_base_centimos INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN contribution_accident_base_centimos INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN irpf_base_centimos INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN irpf_rate_basis_points INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN total_deductions_centimos INTEGER NOT NULL DEFAULT 0;

ALTER TABLE worker_payrolls
ADD COLUMN contract_code_snapshot TEXT;

ALTER TABLE worker_payrolls
ADD COLUMN contribution_group_snapshot TEXT;

ALTER TABLE worker_payrolls
ADD COLUMN professional_group_snapshot TEXT;

-- Evolución compatible del maestro de gastos.
-- La aplicación aplica estas columnas mediante expense_service.ensure_schema()
-- para permitir reejecución segura en SQLite.

ALTER TABLE eco_gastos ADD COLUMN supplier_id INTEGER;
ALTER TABLE eco_gastos ADD COLUMN supplier_name_snapshot TEXT;
ALTER TABLE eco_gastos ADD COLUMN supplier_tax_id_snapshot TEXT;

ALTER TABLE eco_gastos ADD COLUMN numero_factura TEXT;
ALTER TABLE eco_gastos ADD COLUMN fecha_factura TEXT;
ALTER TABLE eco_gastos ADD COLUMN tipo_justificante TEXT NOT NULL DEFAULT 'INVOICE';

ALTER TABLE eco_gastos ADD COLUMN base_imponible_centimos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN iva_centimos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN irpf_centimos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN otros_impuestos_centimos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN total_centimos INTEGER NOT NULL DEFAULT 0;

ALTER TABLE eco_gastos ADD COLUMN iva_porcentaje REAL NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN irpf_porcentaje REAL NOT NULL DEFAULT 0;
ALTER TABLE eco_gastos ADD COLUMN porcentaje_deducible REAL NOT NULL DEFAULT 100;

ALTER TABLE eco_gastos ADD COLUMN estado_documental TEXT NOT NULL DEFAULT 'SIN_JUSTIFICANTE';
ALTER TABLE eco_gastos ADD COLUMN estado_fiscal TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION';
ALTER TABLE eco_gastos ADD COLUMN iva_deducible INTEGER NOT NULL DEFAULT 1;
ALTER TABLE eco_gastos ADD COLUMN deducible_irpf INTEGER NOT NULL DEFAULT 1;

ALTER TABLE eco_gastos ADD COLUMN periodo_desde TEXT;
ALTER TABLE eco_gastos ADD COLUMN periodo_hasta TEXT;
ALTER TABLE eco_gastos ADD COLUMN fecha_vencimiento TEXT;

ALTER TABLE eco_gastos ADD COLUMN bank_movement_id INTEGER;
ALTER TABLE eco_gastos ADD COLUMN client_id INTEGER;
ALTER TABLE eco_gastos ADD COLUMN documento_ruta TEXT;

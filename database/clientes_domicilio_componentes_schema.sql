-- Añade componentes estructurados de domicilio del cliente.
-- Ejecutar una sola vez sobre bases existentes.
ALTER TABLE clientes ADD COLUMN tipo_via TEXT;
ALTER TABLE clientes ADD COLUMN nombre_via TEXT;

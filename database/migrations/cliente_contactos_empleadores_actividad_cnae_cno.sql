-- Migración quirúrgica para ampliar empleadores vinculados al cliente.
-- Ejecutar solo si se gestionan migraciones manuales; la vista también crea/actualiza columnas de forma defensiva.

ALTER TABLE cliente_contactos ADD COLUMN actividad TEXT;
ALTER TABLE cliente_contactos ADD COLUMN cnae TEXT;
ALTER TABLE cliente_contactos ADD COLUMN cno_sepe TEXT;

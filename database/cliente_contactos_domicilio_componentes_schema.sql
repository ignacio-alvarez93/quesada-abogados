-- Añade domicilio estructurado a contactos y empresas vinculadas al cliente.
-- Campos pensados para mappers de EX/PDF/Mercurio.

ALTER TABLE cliente_contactos ADD COLUMN tipo_via TEXT;
ALTER TABLE cliente_contactos ADD COLUMN nombre_via TEXT;
ALTER TABLE cliente_contactos ADD COLUMN numero TEXT;
ALTER TABLE cliente_contactos ADD COLUMN piso TEXT;

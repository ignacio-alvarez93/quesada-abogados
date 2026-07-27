-- Datos obtenidos del recibo GEISER/REGAGE de presentación.
-- numero_presentacion_registro es el identificador I33...
-- numero_expediente_extranjeria será recibido posteriormente por email.

ALTER TABLE expedientes ADD COLUMN numero_presentacion_registro TEXT;
ALTER TABLE expedientes ADD COLUMN numero_expediente_extranjeria TEXT;
ALTER TABLE expedientes ADD COLUMN fecha_hora_presentacion TEXT;
ALTER TABLE expedientes ADD COLUMN fecha_hora_registro TEXT;
ALTER TABLE expedientes ADD COLUMN numero_registro_regage TEXT;
ALTER TABLE expedientes ADD COLUMN oficina_registro_nombre TEXT;
ALTER TABLE expedientes ADD COLUMN oficina_registro_codigo TEXT;
ALTER TABLE expedientes ADD COLUMN unidad_tramitacion_nombre TEXT;
ALTER TABLE expedientes ADD COLUMN unidad_tramitacion_codigo TEXT;
ALTER TABLE expedientes ADD COLUMN organismo_tramitacion TEXT;
ALTER TABLE expedientes ADD COLUMN registro_ambito_prefijo TEXT;
ALTER TABLE expedientes ADD COLUMN registro_csv_geiser TEXT;
ALTER TABLE expedientes ADD COLUMN justificante_presentacion_sha256 TEXT;
ALTER TABLE expedientes ADD COLUMN justificante_extraction_status TEXT;
ALTER TABLE expedientes ADD COLUMN justificante_extraction_json TEXT;
ALTER TABLE expedientes ADD COLUMN justificante_extracted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_expedientes_numero_presentacion
ON expedientes(numero_presentacion_registro);

CREATE INDEX IF NOT EXISTS idx_expedientes_numero_extranjeria
ON expedientes(numero_expediente_extranjeria);

CREATE INDEX IF NOT EXISTS idx_expedientes_regage
ON expedientes(numero_registro_regage);

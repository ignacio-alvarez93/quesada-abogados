PRAGMA foreign_keys = ON;

-- Normalización histórica de Reagrupación Familiar.
--
-- Modelo canónico:
--   tipo 14    = REAGRUPACION_FAMILIAR
--   subtipo 8  = INICIAL
--
-- CONYUGE no es una modalidad procedimental. Es una relación familiar
-- que deberá modelarse separadamente cuando se desarrolle el dominio
-- de familias y miembros vinculados al expediente.

-- El documento INFORME DE VIVIENDA estaba vinculado por error al
-- subtipo 3, que pertenece al tipo ESTATUTO DE ESPAÑOL.
UPDATE config_documentos_requeridos
SET subtipo_expediente_id = 8
WHERE id = 29
  AND tipo_expediente_id = 14
  AND subtipo_expediente_id = 3
  AND codigo_documento = 'INFORME_DE_VIVIENDA';

-- Sincronizar el texto legacy con el subtipo canónico.
-- No se modifica subtipo_expediente_id porque ya es correcto.
UPDATE expedientes
SET subtipo_expediente = 'INICIAL'
WHERE tipo_expediente_id = 14
  AND subtipo_expediente_id = 8
  AND UPPER(TRIM(COALESCE(subtipo_expediente, ''))) = 'CONYUGE';

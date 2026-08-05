-- Las plantillas auxiliares de Reagrupación no deben competir
-- con EX02 como mapper PDF principal del tipo de expediente 14.

UPDATE form_mapper_templates
SET
    tipo_expediente_id = NULL,
    subtipo_expediente_id = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo IN (
    'DEC_CONYUGE',
    'DESIG_REAGRUPANTE'
);

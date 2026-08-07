-- Cierre final de Reagrupación Familiar.
--
-- Sanea únicamente los registros ficticios detectados durante la auditoría.
-- No altera justificantes, eventos históricos, documentos ni rutas de Box.
--
-- La migración es idempotente y utiliza el número público del expediente,
-- evitando depender de IDs internos de una instalación concreta.

BEGIN TRANSACTION;

-- EXP-2026-0013:
-- Existe transición acreditada NO PRESENTADO → PRESENTADO
-- el 17/06/2026.
UPDATE expedientes
SET
    estado_presentacion = 'PRESENTADO',
    fecha_presentacion = '2026-06-17',
    updated_at = CURRENT_TIMESTAMP
WHERE numero_expediente = 'EXP-2026-0013'
  AND (
      UPPER(TRIM(COALESCE(estado_presentacion, '')))
          != 'PRESENTADO'
      OR NULLIF(TRIM(COALESCE(fecha_presentacion, '')), '')
          IS NULL
  );

-- EXP-2026-0014:
-- Existe evento PRESENTACION_ASISTIDA y justificante de presentación
-- el 20/06/2026.
UPDATE expedientes
SET
    estado_presentacion = 'PRESENTADO',
    fecha_presentacion = '2026-06-20',
    updated_at = CURRENT_TIMESTAMP
WHERE numero_expediente = 'EXP-2026-0014'
  AND (
      UPPER(TRIM(COALESCE(estado_presentacion, '')))
          != 'PRESENTADO'
      OR NULLIF(TRIM(COALESCE(fecha_presentacion, '')), '')
          IS NULL
  );

-- EXP-2026-0014:
-- Sus datos específicos EX02 indican expresamente RENOVACIÓN.
UPDATE expedientes
SET
    subtipo_expediente_id = (
        SELECT s.id
        FROM config_subtipos_expediente s
        JOIN config_tipos_expediente t
          ON t.id = s.tipo_expediente_id
        WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
          AND s.codigo = 'RENOVACION'
          AND COALESCE(t.activo, 1) = 1
          AND COALESCE(s.activo, 1) = 1
        LIMIT 1
    ),
    subtipo_expediente = 'RENOVACIÓN',
    updated_at = CURRENT_TIMESTAMP
WHERE numero_expediente = 'EXP-2026-0014'
  AND EXISTS (
      SELECT 1
      FROM config_subtipos_expediente s
      JOIN config_tipos_expediente t
        ON t.id = s.tipo_expediente_id
      WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
        AND s.codigo = 'RENOVACION'
        AND COALESCE(t.activo, 1) = 1
        AND COALESCE(s.activo, 1) = 1
  )
  AND COALESCE(
      (
          SELECT UPPER(de.valor)
          FROM expediente_datos_especificos de
          WHERE de.expediente_id = expedientes.id
            AND de.codigo = 'tipo_de_solicitud'
          ORDER BY de.id DESC
          LIMIT 1
      ),
      ''
  ) LIKE '%RENOV%';

-- EXP-2026-0015:
-- El último justificante de presentación fue archivado y la trazabilidad
-- revirtió expresamente PRESENTADO → NO PRESENTADO.
UPDATE expedientes
SET
    estado_presentacion = 'NO PRESENTADO',
    fecha_presentacion = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE numero_expediente = 'EXP-2026-0015'
  AND (
      UPPER(TRIM(COALESCE(estado_presentacion, '')))
          != 'NO PRESENTADO'
      OR NULLIF(TRIM(COALESCE(fecha_presentacion, '')), '')
          IS NOT NULL
  );

COMMIT;

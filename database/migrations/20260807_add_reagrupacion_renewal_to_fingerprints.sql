-- Reagrupación Familiar / Renovación favorable
-- ------------------------------------------------------------
-- Una renovación favorable NO genera visado consular.
--
-- Flujo:
-- REAGRUPACION_FAMILIAR / RENOVACION
--   -> RESOLUCION_FAVORABLE / CONCEDIDO
--   -> DOCUMENTACION_EXTRANJEROS / TOMA_HUELLAS
--
-- La regla toma:
-- - origen/base de REAGRUPACION_CONCEDIDA_A_VISADO;
-- - destino/base de VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS.
--
-- Esto evita duplicar IDs o depender de valores hardcodeados.

INSERT INTO config_reglas_expediente_derivado (
    codigo,
    nombre,
    familia_origen_id,
    tipo_expediente_origen_id,
    subtipo_expediente_origen_id,
    evento_disparador,
    resultado_requerido,
    familia_destino_id,
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    tipo_relacion,
    obligatorio,
    creacion_automatica,
    requiere_revision_humana,
    plazo_dias,
    orden,
    activo,
    observaciones
)
SELECT
    'REAGRUPACION_RENOVACION_CONCEDIDA_A_HUELLAS',
    'Reagrupación renovación favorable → toma de huellas',

    origen.familia_origen_id,
    origen.tipo_expediente_origen_id,

    renovacion.id,

    origen.evento_disparador,
    origen.resultado_requerido,

    huellas.familia_destino_id,
    huellas.tipo_expediente_destino_id,
    huellas.subtipo_expediente_destino_id,

    'ACTUACION_POSTERIOR',

    0,
    0,
    1,

    NULL,
    20,
    1,

    'La renovación favorable de reagrupación familiar '
    || 'deriva directamente a toma de huellas. '
    || 'No genera visado consular.'

FROM config_reglas_expediente_derivado origen

JOIN config_subtipos_expediente renovacion
  ON renovacion.tipo_expediente_id =
     origen.tipo_expediente_origen_id
 AND renovacion.codigo = 'RENOVACION'
 AND COALESCE(renovacion.activo, 1) = 1

CROSS JOIN config_reglas_expediente_derivado huellas

WHERE origen.codigo =
      'REAGRUPACION_CONCEDIDA_A_VISADO'

  AND huellas.codigo =
      'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'

  AND NOT EXISTS (
      SELECT 1
      FROM config_reglas_expediente_derivado existing
      WHERE existing.codigo =
            'REAGRUPACION_RENOVACION_CONCEDIDA_A_HUELLAS'
  );


-- Reconciliación idempotente.
--
-- Si la regla ya existiese, actualizamos sus referencias
-- contra los contratos canónicos actuales.

UPDATE config_reglas_expediente_derivado

SET
    nombre =
        'Reagrupación renovación favorable → toma de huellas',

    familia_origen_id = (
        SELECT familia_origen_id
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'REAGRUPACION_CONCEDIDA_A_VISADO'
    ),

    tipo_expediente_origen_id = (
        SELECT tipo_expediente_origen_id
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'REAGRUPACION_CONCEDIDA_A_VISADO'
    ),

    subtipo_expediente_origen_id = (
        SELECT s.id
        FROM config_subtipos_expediente s
        JOIN config_tipos_expediente t
          ON t.id = s.tipo_expediente_id
        WHERE t.codigo =
              'REAGRUPACION_FAMILIAR'
          AND s.codigo =
              'RENOVACION'
          AND COALESCE(s.activo, 1) = 1
        LIMIT 1
    ),

    evento_disparador = (
        SELECT evento_disparador
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'REAGRUPACION_CONCEDIDA_A_VISADO'
    ),

    resultado_requerido = (
        SELECT resultado_requerido
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'REAGRUPACION_CONCEDIDA_A_VISADO'
    ),

    familia_destino_id = (
        SELECT familia_destino_id
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
    ),

    tipo_expediente_destino_id = (
        SELECT tipo_expediente_destino_id
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
    ),

    subtipo_expediente_destino_id = (
        SELECT subtipo_expediente_destino_id
        FROM config_reglas_expediente_derivado
        WHERE codigo =
              'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
    ),

    tipo_relacion = 'ACTUACION_POSTERIOR',
    obligatorio = 0,
    creacion_automatica = 0,
    requiere_revision_humana = 1,
    plazo_dias = NULL,
    orden = 20,
    activo = 1,

    observaciones =
        'La renovación favorable de reagrupación familiar '
        || 'deriva directamente a toma de huellas. '
        || 'No genera visado consular.',

    updated_at = CURRENT_TIMESTAMP

WHERE codigo =
      'REAGRUPACION_RENOVACION_CONCEDIDA_A_HUELLAS';

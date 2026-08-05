PRAGMA foreign_keys = ON;

-- Segunda cadena funcional real:
-- Visado de reagrupación familiar concedido
-- → propuesta de expediente de toma de huellas.

INSERT INTO config_familias_expediente (
    codigo,
    nombre,
    descripcion,
    notification_workflow_code,
    orden,
    activo
)
SELECT
    'POLICIA_NACIONAL',
    'POLICÍA NACIONAL',
    (
        'Actuaciones realizadas ante Policía Nacional, '
        || 'incluidas toma de huellas, recogida de TIE, '
        || 'certificados y antecedentes policiales.'
    ),
    'RESOLUCION_DIRECTA',
    80,
    1
WHERE NOT EXISTS (
    SELECT 1
    FROM config_familias_expediente
    WHERE codigo = 'POLICIA_NACIONAL'
);

UPDATE config_familias_expediente
SET
    nombre = 'POLICÍA NACIONAL',
    descripcion = (
        'Actuaciones realizadas ante Policía Nacional, '
        || 'incluidas toma de huellas, recogida de TIE, '
        || 'certificados y antecedentes policiales.'
    ),
    notification_workflow_code = 'RESOLUCION_DIRECTA',
    orden = 80,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'POLICIA_NACIONAL';


INSERT INTO config_tipos_expediente (
    codigo,
    nombre,
    descripcion,
    activo,
    url_presentacion,
    workflow_code,
    familia_id
)
SELECT
    'TOMA_HUELLAS',
    'TOMA DE HUELLAS',
    (
        'Solicitud, preparación y seguimiento de la cita '
        || 'de toma de huellas para la expedición de la TIE.'
    ),
    1,
    NULL,
    'POLICIA_NACIONAL',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'POLICIA_NACIONAL'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo = 'TOMA_HUELLAS'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'TOMA DE HUELLAS',
    descripcion = (
        'Solicitud, preparación y seguimiento de la cita '
        || 'de toma de huellas para la expedición de la TIE.'
    ),
    activo = 1,
    workflow_code = 'POLICIA_NACIONAL',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'POLICIA_NACIONAL'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'TOMA_HUELLAS';


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
    'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS',
    (
        'Visado de reagrupación concedido '
        || 'a toma de huellas'
    ),
    fo.id,
    torigen.id,
    NULL,
    'RESOLUCION_FAVORABLE',
    'CONCEDIDO',
    fd.id,
    tdestino.id,
    NULL,
    'ACTUACION_POSTERIOR',
    0,
    0,
    1,
    NULL,
    20,
    1,
    (
        'Genera una propuesta revisable de toma de huellas. '
        || 'No crea automáticamente el expediente policial.'
    )
FROM config_familias_expediente fo
JOIN config_tipos_expediente torigen
  ON torigen.familia_id = fo.id
JOIN config_familias_expediente fd
  ON fd.codigo = 'POLICIA_NACIONAL'
JOIN config_tipos_expediente tdestino
  ON tdestino.familia_id = fd.id
WHERE fo.codigo = 'TRAMITES_CONSULARES'
  AND torigen.codigo =
      'VISADO_REAGRUPACION_FAMILIAR'
  AND tdestino.codigo = 'TOMA_HUELLAS'
  AND NOT EXISTS (
      SELECT 1
      FROM config_reglas_expediente_derivado r
      WHERE r.codigo =
          'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
  );

UPDATE config_reglas_expediente_derivado
SET
    nombre = (
        'Visado de reagrupación concedido '
        || 'a toma de huellas'
    ),
    familia_origen_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'TRAMITES_CONSULARES'
    ),
    tipo_expediente_origen_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo =
            'VISADO_REAGRUPACION_FAMILIAR'
    ),
    subtipo_expediente_origen_id = NULL,
    evento_disparador = 'RESOLUCION_FAVORABLE',
    resultado_requerido = 'CONCEDIDO',
    familia_destino_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'POLICIA_NACIONAL'
    ),
    tipo_expediente_destino_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo = 'TOMA_HUELLAS'
    ),
    subtipo_expediente_destino_id = NULL,
    tipo_relacion = 'ACTUACION_POSTERIOR',
    obligatorio = 0,
    creacion_automatica = 0,
    requiere_revision_humana = 1,
    orden = 20,
    activo = 1,
    observaciones = (
        'Genera una propuesta revisable de toma de huellas. '
        || 'No crea automáticamente el expediente policial.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo =
    'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS';

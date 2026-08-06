PRAGMA foreign_keys = ON;

INSERT OR IGNORE INTO config_transiciones_autorizacion (
    codigo,
    nombre,
    autorizacion_origen_id,
    familia_destino_id,
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    autorizacion_resultado_id,
    tipo_transicion,
    requiere_resolucion_favorable,
    requiere_autorizacion_vigente,
    requiere_cliente_en_espana,
    requiere_cliente_en_origen,
    orden,
    activo,
    observaciones
)
SELECT
    'REAGRUPACION_FAMILIAR_INICIAL_CONCEDIDA',
    'Reagrupación familiar inicial concedida',
    NULL,
    f.id,
    t.id,
    s.id,
    a.id,
    'INICIAL',
    1,
    0,
    0,
    0,
    100,
    1,
    'Crea la autorización inicial de residencia temporal por reagrupación familiar.'
FROM config_familias_expediente f
JOIN config_tipos_expediente t
  ON t.familia_id = f.id
JOIN config_subtipos_expediente s
  ON s.tipo_expediente_id = t.id
JOIN config_tipos_autorizacion a
  ON a.codigo =
     'RESIDENCIA_TEMPORAL_REAGRUPACION_FAMILIAR'
WHERE f.codigo = 'EXTRANJERIA'
  AND t.codigo = 'REAGRUPACION_FAMILIAR'
  AND s.codigo = 'INICIAL';

INSERT OR IGNORE INTO config_transiciones_autorizacion (
    codigo,
    nombre,
    autorizacion_origen_id,
    familia_destino_id,
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    autorizacion_resultado_id,
    tipo_transicion,
    requiere_resolucion_favorable,
    requiere_autorizacion_vigente,
    requiere_cliente_en_espana,
    requiere_cliente_en_origen,
    orden,
    activo,
    observaciones
)
SELECT
    'REAGRUPACION_FAMILIAR_RENOVACION_CONCEDIDA',
    'Renovación de reagrupación familiar concedida',
    a.id,
    f.id,
    t.id,
    s.id,
    a.id,
    'RENOVACION',
    1,
    1,
    1,
    0,
    110,
    1,
    'Finaliza la autorización anterior y crea una nueva vigencia renovada.'
FROM config_familias_expediente f
JOIN config_tipos_expediente t
  ON t.familia_id = f.id
JOIN config_subtipos_expediente s
  ON s.tipo_expediente_id = t.id
JOIN config_tipos_autorizacion a
  ON a.codigo =
     'RESIDENCIA_TEMPORAL_REAGRUPACION_FAMILIAR'
WHERE f.codigo = 'EXTRANJERIA'
  AND t.codigo = 'REAGRUPACION_FAMILIAR'
  AND s.codigo = 'RENOVACION';

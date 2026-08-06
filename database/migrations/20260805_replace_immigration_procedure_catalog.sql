PRAGMA foreign_keys = ON;

-- Sustitución incremental y no destructiva del catálogo de Extranjería.
--
-- Registros protegidos:
--   tipo 13 = RESIDENCIA_TEMPORAL_NO_LUCRATIVA
--   tipo 14 = REAGRUPACION_FAMILIAR
--   tipo 15 = VISADO_REAGRUPACION_FAMILIAR
--   subtipo 6 = RENOVACION_TITULAR
--   subtipo 7 = RENOVACION_FAMILIAR
--   subtipo 8 = INICIAL de REAGRUPACION_FAMILIAR
--
-- No se eliminan tipos, subtipos ni configuraciones históricas.
-- Las entradas sustituidas quedan desactivadas.

-- ------------------------------------------------------------------
-- 1. PRECONDICIONES DE SEGURIDAD
-- ------------------------------------------------------------------

DROP TABLE IF EXISTS temp._immigration_catalog_assertion;

CREATE TEMP TABLE _immigration_catalog_assertion (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 13
          AND codigo =
              'RESIDENCIA_TEMPORAL_NO_LUCRATIVA'
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 14
          AND codigo = 'REAGRUPACION_FAMILIAR'
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 15
          AND codigo =
              'VISADO_REAGRUPACION_FAMILIAR'
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_subtipos_expediente
        WHERE id = 6
          AND tipo_expediente_id = 13
          AND codigo = 'RENOVACION_TITULAR'
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_subtipos_expediente
        WHERE id = 7
          AND tipo_expediente_id = 13
          AND codigo = 'RENOVACION_FAMILIAR'
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_subtipos_expediente
        WHERE id = 8
          AND tipo_expediente_id = 14
          AND codigo = 'INICIAL'
    )
    THEN 1
    ELSE 0
END;

-- ------------------------------------------------------------------
-- 2. NORMALIZACIÓN DE FAMILIAS
-- ------------------------------------------------------------------

UPDATE config_familias_expediente
SET
    nombre = 'EXTRANJERÍA',
    descripcion = (
        'Autorizaciones de estancia, residencia temporal, '
        || 'circunstancias excepcionales, régimen comunitario, '
        || 'larga duración, menores, autorizaciones especiales '
        || 'y modificaciones del régimen general.'
    ),
    notification_workflow_code =
        'EXTRANJERIA_STANDARD',
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'EXTRANJERIA';

UPDATE config_familias_expediente
SET
    activo = 0,
    descripcion = (
        'Familia histórica sustituida por '
        || 'TRAMITES_CONSULARES.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'VISADOS';

UPDATE config_familias_expediente
SET
    nombre = 'TRÁMITES CONSULARES',
    descripcion = (
        'Visados y procedimientos tramitados ante consulados, '
        || 'oficinas consulares o proveedores consulares.'
    ),
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'TRAMITES_CONSULARES';

-- ------------------------------------------------------------------
-- 3. CATÁLOGO CANÓNICO DE TIPOS DE EXTRANJERÍA
-- ------------------------------------------------------------------

DROP TABLE IF EXISTS temp._immigration_type_seed;

CREATE TEMP TABLE _immigration_type_seed (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    descripcion TEXT NOT NULL
);

INSERT INTO _immigration_type_seed (
    codigo,
    nombre,
    descripcion
)
VALUES
-- I. ESTANCIA
(
    'PRORROGA_ESTANCIA_CORTA_SIN_VISADO',
    'PRÓRROGA DE ESTANCIA DE CORTA DURACIÓN SIN VISADO',
    'Prórroga de estancia de corta duración sin visado.'
),
(
    'ESTANCIA_ESTUDIOS_SUPERIORES',
    'ESTANCIA POR ESTUDIOS SUPERIORES',
    'Estancia de larga duración para estudios superiores.'
),
(
    'ESTANCIA_EDUCACION_SECUNDARIA',
    'ESTANCIA POR EDUCACIÓN SECUNDARIA POSTOBLIGATORIA',
    'Estancia de larga duración para educación secundaria postobligatoria.'
),
(
    'ESTANCIA_MOVILIDAD_ALUMNOS',
    'ESTANCIA POR MOVILIDAD DE ALUMNOS',
    'Estancia de larga duración por programas de movilidad de alumnos.'
),
(
    'ESTANCIA_VOLUNTARIADO',
    'ESTANCIA POR SERVICIO DE VOLUNTARIADO',
    'Estancia de larga duración por servicio de voluntariado.'
),
(
    'ESTANCIA_ACTIVIDADES_FORMATIVAS',
    'ESTANCIA POR ACTIVIDADES FORMATIVAS',
    'Idiomas, aptitud técnica, certificados profesionales y auxiliares de conversación.'
),
(
    'ESTANCIA_FORMACION_SANITARIA',
    'ESTANCIA POR FORMACIÓN SANITARIA ESPECIALIZADA',
    'Estancia de larga duración para formación sanitaria especializada.'
),
(
    'ESTANCIA_FAMILIARES_ESTUDIANTE',
    'ESTANCIA DE FAMILIARES DE ESTUDIANTE',
    'Estancia de familiares de titulares de estancia por estudios superiores.'
),
(
    'PRORROGA_ESTANCIA_LARGA_DURACION',
    'PRÓRROGA DE ESTANCIA DE LARGA DURACIÓN',
    'Prórroga de una autorización de estancia de larga duración.'
),

-- II. RÉGIMEN GENERAL
(
    'RESIDENCIA_TEMPORAL_NO_LUCRATIVA',
    'RESIDENCIA TEMPORAL NO LUCRATIVA',
    'Autorización de residencia temporal no lucrativa.'
),
(
    'REAGRUPACION_FAMILIAR',
    'REAGRUPACIÓN FAMILIAR',
    'Autorización de residencia temporal por reagrupación familiar.'
),
(
    'RESIDENCIA_INDEPENDIENTE_REAGRUPADO',
    'RESIDENCIA INDEPENDIENTE DE FAMILIAR REAGRUPADO',
    'Residencia independiente por medios propios, trabajo o ruptura del vínculo.'
),
(
    'RESIDENCIA_INDEPENDIENTE_REAGRUPADO_REFORZADA',
    'RESIDENCIA INDEPENDIENTE REFORZADA DE FAMILIAR REAGRUPADO',
    'Residencia independiente por fallecimiento, violencia, trata u otros supuestos reforzados.'
),
(
    'RESIDENCIA_TRABAJO_CUENTA_AJENA',
    'RESIDENCIA TEMPORAL Y TRABAJO POR CUENTA AJENA',
    'Autorización de residencia temporal y trabajo por cuenta ajena.'
),
(
    'RESIDENCIA_TRABAJO_CUENTA_PROPIA',
    'RESIDENCIA TEMPORAL Y TRABAJO POR CUENTA PROPIA',
    'Autorización de residencia temporal y trabajo por cuenta propia.'
),
(
    'RESIDENCIA_EXCEPCION_AUTORIZACION_TRABAJO',
    'RESIDENCIA CON EXCEPCIÓN DE AUTORIZACIÓN DE TRABAJO',
    'Residencia temporal con excepción de la autorización de trabajo.'
),
(
    'RESIDENCIA_RETORNO_VOLUNTARIO',
    'RESIDENCIA DEL EXTRANJERO RETORNADO VOLUNTARIAMENTE',
    'Residencia temporal tras retorno voluntario.'
),
(
    'RESIDENCIA_BUSQUEDA_EMPLEO_PROYECTO_EMPRESARIAL',
    'RESIDENCIA PARA BÚSQUEDA DE EMPLEO O PROYECTO EMPRESARIAL',
    'Residencia para búsqueda de empleo o emprendimiento tras estudios de nivel 6 MEC.'
),

-- III. FAMILIARES DE PERSONAS ESPAÑOLAS
(
    'FAMILIAR_PERSONA_ESPANOLA',
    'RESIDENCIA DE FAMILIAR DE PERSONA ESPAÑOLA',
    'Autorización temporal de residencia de familiar de persona española.'
),
(
    'RESIDENCIA_INDEPENDIENTE_FAMILIAR_ESPANOL',
    'RESIDENCIA INDEPENDIENTE DE FAMILIAR DE PERSONA ESPAÑOLA',
    'Conservación o residencia independiente tras fallecimiento, cese, nulidad o divorcio.'
),

-- IV. CIRCUNSTANCIAS EXCEPCIONALES
(
    'ARRAIGO_SEGUNDA_OPORTUNIDAD',
    'ARRAIGO DE SEGUNDA OPORTUNIDAD',
    'Residencia temporal por circunstancias excepcionales por arraigo de segunda oportunidad.'
),
(
    'ARRAIGO_SOCIOLABORAL',
    'ARRAIGO SOCIOLABORAL',
    'Residencia temporal por circunstancias excepcionales por arraigo sociolaboral.'
),
(
    'ARRAIGO_SOCIAL',
    'ARRAIGO SOCIAL',
    'Residencia temporal por circunstancias excepcionales por arraigo social.'
),
(
    'ARRAIGO_SOCIOFORMATIVO',
    'ARRAIGO SOCIOFORMATIVO',
    'Residencia temporal por circunstancias excepcionales por arraigo socioformativo.'
),
(
    'ARRAIGO_FAMILIAR',
    'ARRAIGO FAMILIAR',
    'Arraigo familiar para los supuestos jurídicamente comprendidos en el régimen vigente.'
),
(
    'ARRAIGO_SOLICITANTE_PROTECCION_INTERNACIONAL_2026',
    'ARRAIGO DE SOLICITANTE DE PROTECCIÓN INTERNACIONAL 2026',
    'Procedimiento excepcional y temporal vinculado al Real Decreto 316/2026.'
),
(
    'ARRAIGO_EXTRAORDINARIO_2026',
    'ARRAIGO EXTRAORDINARIO 2026',
    'Procedimiento excepcional y temporal de arraigo extraordinario.'
),
(
    'RESIDENCIA_RAZONES_HUMANITARIAS',
    'RESIDENCIA POR RAZONES HUMANITARIAS',
    'Residencia por enfermedad grave, peligro en origen u otros supuestos humanitarios.'
),
(
    'COLABORACION_AUTORIDADES',
    'RESIDENCIA POR COLABORACIÓN CON AUTORIDADES',
    'Colaboración con autoridades, seguridad nacional o interés público.'
),
(
    'VICTIMA_VIOLENCIA_GENERO',
    'RESIDENCIA DE VÍCTIMA DE VIOLENCIA DE GÉNERO',
    'Autorización provisional o definitiva para víctimas de violencia de género.'
),
(
    'VICTIMA_VIOLENCIA_SEXUAL',
    'RESIDENCIA DE VÍCTIMA DE VIOLENCIA SEXUAL',
    'Autorización provisional o definitiva para víctimas de violencia sexual.'
),
(
    'COLABORACION_RED_ORGANIZADA',
    'RESIDENCIA POR COLABORACIÓN CONTRA REDES ORGANIZADAS',
    'Autorización por colaboración contra redes organizadas.'
),
(
    'VICTIMA_TRATA_SERES_HUMANOS',
    'RESIDENCIA DE VÍCTIMA DE TRATA DE SERES HUMANOS',
    'Periodo de restablecimiento y autorizaciones provisional y definitiva.'
),
(
    'PRORROGA_CIRCUNSTANCIAS_EXCEPCIONALES',
    'PRÓRROGA DE AUTORIZACIÓN POR CIRCUNSTANCIAS EXCEPCIONALES',
    'Prórroga de una autorización por circunstancias excepcionales.'
),

-- V. RÉGIMEN COMUNITARIO
(
    'TARJETA_FAMILIAR_CIUDADANO_UE',
    'TARJETA DE FAMILIAR DE CIUDADANO DE LA UNIÓN',
    'Reconocimiento temporal del derecho de residencia de familiar no comunitario.'
),
(
    'RESIDENCIA_PERMANENTE_CIUDADANO_UE',
    'RESIDENCIA PERMANENTE DE CIUDADANO DE LA UNIÓN',
    'Reconocimiento del derecho de residencia permanente de ciudadano de la Unión.'
),
(
    'TARJETA_PERMANENTE_FAMILIAR_CIUDADANO_UE',
    'TARJETA PERMANENTE DE FAMILIAR DE CIUDADANO DE LA UNIÓN',
    'Reconocimiento permanente del derecho de residencia de familiar no comunitario.'
),
(
    'CONSERVACION_DERECHO_RESIDENCIA_UE',
    'CONSERVACIÓN DEL DERECHO DE RESIDENCIA EN RÉGIMEN COMUNITARIO',
    'Conservación del derecho tras fallecimiento, salida, divorcio o cese del vínculo.'
),

-- VI. LARGA DURACIÓN
(
    'RESIDENCIA_LARGA_DURACION',
    'RESIDENCIA DE LARGA DURACIÓN',
    'Autorización de residencia de larga duración nacional.'
),
(
    'RESIDENCIA_LARGA_DURACION_UE',
    'RESIDENCIA DE LARGA DURACIÓN-UE',
    'Autorización de larga duración-UE con movilidad europea.'
),
(
    'RECUPERACION_LARGA_DURACION',
    'RECUPERACIÓN DE RESIDENCIA DE LARGA DURACIÓN',
    'Recuperación de la titularidad de la residencia de larga duración nacional.'
),
(
    'RECUPERACION_LARGA_DURACION_UE',
    'RECUPERACIÓN DE RESIDENCIA DE LARGA DURACIÓN-UE',
    'Recuperación de la titularidad de la residencia de larga duración-UE.'
),

-- VII. AUTORIZACIONES ESPECIALES
(
    'RESIDENCIA_TRABAJO_TEMPORADA',
    'RESIDENCIA Y TRABAJO PARA ACTIVIDADES DE TEMPORADA',
    'Autorización plurianual para actividades de temporada.'
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_AJENA',
    'TRABAJADOR TRANSFRONTERIZO POR CUENTA AJENA',
    'Autorización de trabajo transfronterizo por cuenta ajena.'
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_PROPIA',
    'TRABAJADOR TRANSFRONTERIZO POR CUENTA PROPIA',
    'Autorización de trabajo transfronterizo por cuenta propia.'
),
(
    'RESIDENCIA_HIJO_TUTELADO_NACIDO_ESPANA',
    'RESIDENCIA DE HIJO O TUTELADO NACIDO EN ESPAÑA',
    'Residencia del hijo o tutelado de residente nacido en España.'
),
(
    'RESIDENCIA_MENOR_DISCAPACITADO_NO_NACIDO_ESPANA',
    'RESIDENCIA DE MENOR O PERSONA CON DISCAPACIDAD NO NACIDA EN ESPAÑA',
    'Residencia de persona acompañada menor o con discapacidad no nacida en España.'
),
(
    'DESPLAZAMIENTO_MENOR_TRATAMIENTO_MEDICO',
    'DESPLAZAMIENTO TEMPORAL DE MENOR PARA TRATAMIENTO MÉDICO',
    'Desplazamiento temporal de menores para tratamiento médico.'
),
(
    'DESPLAZAMIENTO_MENOR_VACACIONES_ESCOLARIZACION',
    'DESPLAZAMIENTO TEMPORAL DE MENOR POR VACACIONES O ESCOLARIZACIÓN',
    'Desplazamiento temporal de menores con fines vacacionales o escolares.'
),
(
    'RESIDENCIA_MENOR_NO_ACOMPANADO',
    'RESIDENCIA DE MENOR EXTRANJERO NO ACOMPAÑADO',
    'Residencia del menor extranjero no acompañado tutelado.'
),
(
    'RENOVACION_MENOR_TUTELADO_MAYORIA_EDAD',
    'RENOVACIÓN DE RESIDENCIA DE MENOR TUTELADO AL ALCANZAR LA MAYORÍA DE EDAD',
    'Continuidad de residencia de menor tutelado al alcanzar la mayoría de edad.'
),

-- VIII. MODIFICACIONES
(
    'MODIFICACION_DESDE_ESTANCIA',
    'MODIFICACIÓN DESDE ESTANCIA DE LARGA DURACIÓN',
    'Modificación desde estancia a residencia y trabajo o excepción de trabajo.'
),
(
    'MODIFICACION_DESDE_NO_LUCRATIVA',
    'MODIFICACIÓN DESDE RESIDENCIA NO LUCRATIVA',
    'Modificación desde residencia no lucrativa a residencia y trabajo.'
),
(
    'MODIFICACION_DESDE_RESIDENCIA_TEMPORAL',
    'MODIFICACIÓN DESDE RESIDENCIA TEMPORAL',
    'Modificación desde residencia temporal a otra residencia y trabajo.'
),
(
    'MODIFICACION_DESDE_CIRCUNSTANCIAS_EXCEPCIONALES',
    'MODIFICACIÓN DESDE CIRCUNSTANCIAS EXCEPCIONALES',
    'Modificación desde arraigo u otra circunstancia excepcional al régimen general.'
),
(
    'MODIFICACION_DESDE_RAZONES_HUMANITARIAS',
    'MODIFICACIÓN DESDE RAZONES HUMANITARIAS',
    'Modificación desde razones humanitarias al régimen general.'
),
(
    'MODIFICACION_DESDE_FAMILIAR_UE',
    'MODIFICACIÓN DESDE TARJETA DE FAMILIAR DE CIUDADANO UE',
    'Modificación por cese del vínculo desde régimen comunitario.'
),
(
    'MODIFICACION_DESDE_FAMILIAR_ESPANOL',
    'MODIFICACIÓN DESDE RESIDENCIA DE FAMILIAR DE PERSONA ESPAÑOLA',
    'Modificación o conservación por cese del vínculo con persona española.'
),
(
    'MODIFICACION_DESDE_TEMPORADA',
    'MODIFICACIÓN DESDE ACTIVIDADES DE TEMPORADA',
    'Modificación tras el cumplimiento del ciclo plurianual de temporada.'
),
(
    'MODIFICACION_ALCANCE_AUTORIZACION',
    'MODIFICACIÓN DEL ALCANCE DE LA AUTORIZACIÓN',
    'Modificación de ocupación, sector o ámbito territorial.'
),
(
    'MODIFICACION_CUENTA_AJENA_A_PROPIA',
    'MODIFICACIÓN DE CUENTA AJENA A CUENTA PROPIA',
    'Modificación de residencia y trabajo por cuenta ajena a cuenta propia.'
),
(
    'MODIFICACION_PROTECCION_TEMPORAL',
    'MODIFICACIÓN DESDE PROTECCIÓN TEMPORAL',
    'Modificación desde protección temporal al régimen general.'
);

-- Insertar únicamente tipos inexistentes.

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
    seed.codigo,
    seed.nombre,
    seed.descripcion,
    1,
    NULL,
    'EXTRANJERIA',
    familia.id
FROM _immigration_type_seed seed
JOIN config_familias_expediente familia
  ON familia.codigo = 'EXTRANJERIA'
WHERE NOT EXISTS (
    SELECT 1
    FROM config_tipos_expediente current_type
    WHERE current_type.codigo = seed.codigo
);

-- Normalizar todos los tipos canónicos sin cambiar sus IDs.

UPDATE config_tipos_expediente
SET
    nombre = (
        SELECT seed.nombre
        FROM _immigration_type_seed seed
        WHERE seed.codigo =
            config_tipos_expediente.codigo
    ),
    descripcion = (
        SELECT seed.descripcion
        FROM _immigration_type_seed seed
        WHERE seed.codigo =
            config_tipos_expediente.codigo
    ),
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'EXTRANJERIA'
    ),
    workflow_code = 'EXTRANJERIA',
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo IN (
    SELECT codigo
    FROM _immigration_type_seed
);

-- ------------------------------------------------------------------
-- 4. SUBTIPOS PROTEGIDOS Y FASES INICIALES
-- ------------------------------------------------------------------

-- No lucrativa: se conservan los subtipos avanzados y se añade INICIAL.

INSERT INTO config_subtipos_expediente (
    tipo_expediente_id,
    codigo,
    nombre,
    descripcion,
    orden,
    activo
)
SELECT
    id,
    'INICIAL',
    'INICIAL',
    'Autorización inicial de residencia temporal no lucrativa.',
    10,
    1
FROM config_tipos_expediente
WHERE codigo =
    'RESIDENCIA_TEMPORAL_NO_LUCRATIVA'
  AND NOT EXISTS (
      SELECT 1
      FROM config_subtipos_expediente subtype
      WHERE subtype.tipo_expediente_id =
            config_tipos_expediente.id
        AND subtype.codigo = 'INICIAL'
  );

UPDATE config_subtipos_expediente
SET
    nombre = 'RENOVACIÓN TITULAR',
    descripcion = (
        'Renovación de residencia temporal '
        || 'no lucrativa del titular.'
    ),
    orden = 20,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 6
  AND tipo_expediente_id = 13
  AND codigo = 'RENOVACION_TITULAR';

UPDATE config_subtipos_expediente
SET
    nombre = 'RENOVACIÓN FAMILIAR',
    descripcion = (
        'Renovación de residencia temporal no lucrativa '
        || 'de familiar vinculado al titular.'
    ),
    orden = 30,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 7
  AND tipo_expediente_id = 13
  AND codigo = 'RENOVACION_FAMILIAR';

-- Reagrupación: conservar INICIAL y añadir RENOVACION.

UPDATE config_subtipos_expediente
SET
    nombre = 'INICIAL',
    descripcion = (
        'Autorización inicial de residencia '
        || 'por reagrupación familiar.'
    ),
    orden = 10,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 8
  AND tipo_expediente_id = 14
  AND codigo = 'INICIAL';

INSERT INTO config_subtipos_expediente (
    tipo_expediente_id,
    codigo,
    nombre,
    descripcion,
    orden,
    activo
)
SELECT
    id,
    'RENOVACION',
    'RENOVACIÓN',
    'Renovación de residencia temporal por reagrupación familiar.',
    20,
    1
FROM config_tipos_expediente
WHERE codigo = 'REAGRUPACION_FAMILIAR'
  AND NOT EXISTS (
      SELECT 1
      FROM config_subtipos_expediente subtype
      WHERE subtype.tipo_expediente_id =
            config_tipos_expediente.id
        AND subtype.codigo = 'RENOVACION'
  );

-- Subtipos generales para los principales tipos ordinarios.

DROP TABLE IF EXISTS temp._immigration_subtype_seed;

CREATE TEMP TABLE _immigration_subtype_seed (
    tipo_codigo TEXT NOT NULL,
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    orden INTEGER NOT NULL,
    PRIMARY KEY (tipo_codigo, codigo)
);

INSERT INTO _immigration_subtype_seed (
    tipo_codigo,
    codigo,
    nombre,
    descripcion,
    orden
)
VALUES
(
    'RESIDENCIA_TRABAJO_CUENTA_AJENA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'RESIDENCIA_TRABAJO_CUENTA_AJENA',
    'RENOVACION',
    'RENOVACIÓN',
    'Renovación de la autorización.',
    20
),
(
    'RESIDENCIA_TRABAJO_CUENTA_PROPIA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'RESIDENCIA_TRABAJO_CUENTA_PROPIA',
    'RENOVACION',
    'RENOVACIÓN',
    'Renovación de la autorización.',
    20
),
(
    'RESIDENCIA_EXCEPCION_AUTORIZACION_TRABAJO',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'RESIDENCIA_EXCEPCION_AUTORIZACION_TRABAJO',
    'PRORROGA',
    'PRÓRROGA',
    'Prórroga de la autorización.',
    20
),
(
    'FAMILIAR_PERSONA_ESPANOLA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'FAMILIAR_PERSONA_ESPANOLA',
    'RENOVACION',
    'RENOVACIÓN',
    'Renovación de la autorización.',
    20
),
(
    'TARJETA_FAMILIAR_CIUDADANO_UE',
    'INICIAL',
    'INICIAL',
    'Reconocimiento inicial.',
    10
),
(
    'TARJETA_FAMILIAR_CIUDADANO_UE',
    'CONSERVACION',
    'CONSERVACIÓN',
    'Conservación del derecho de residencia.',
    20
),
(
    'RESIDENCIA_TRABAJO_TEMPORADA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial plurianual.',
    10
),
(
    'RESIDENCIA_TRABAJO_TEMPORADA',
    'PRORROGA',
    'PRÓRROGA',
    'Prórroga de la autorización.',
    20
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_AJENA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_AJENA',
    'PRORROGA',
    'PRÓRROGA',
    'Prórroga de la autorización.',
    20
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_PROPIA',
    'INICIAL',
    'INICIAL',
    'Autorización inicial.',
    10
),
(
    'TRABAJADOR_TRANSFRONTERIZO_CUENTA_PROPIA',
    'PRORROGA',
    'PRÓRROGA',
    'Prórroga de la autorización.',
    20
),
(
    'VICTIMA_VIOLENCIA_GENERO',
    'PROVISIONAL',
    'PROVISIONAL',
    'Autorización provisional.',
    10
),
(
    'VICTIMA_VIOLENCIA_GENERO',
    'DEFINITIVA',
    'DEFINITIVA',
    'Autorización definitiva.',
    20
),
(
    'VICTIMA_VIOLENCIA_SEXUAL',
    'PROVISIONAL',
    'PROVISIONAL',
    'Autorización provisional.',
    10
),
(
    'VICTIMA_VIOLENCIA_SEXUAL',
    'DEFINITIVA',
    'DEFINITIVA',
    'Autorización definitiva.',
    20
),
(
    'COLABORACION_RED_ORGANIZADA',
    'PROVISIONAL',
    'PROVISIONAL',
    'Autorización provisional.',
    10
),
(
    'COLABORACION_RED_ORGANIZADA',
    'DEFINITIVA',
    'DEFINITIVA',
    'Autorización definitiva.',
    20
),
(
    'VICTIMA_TRATA_SERES_HUMANOS',
    'RESTABLECIMIENTO_REFLEXION',
    'PERIODO DE RESTABLECIMIENTO Y REFLEXIÓN',
    'Periodo de restablecimiento y reflexión.',
    10
),
(
    'VICTIMA_TRATA_SERES_HUMANOS',
    'PROVISIONAL',
    'PROVISIONAL',
    'Autorización provisional.',
    20
),
(
    'VICTIMA_TRATA_SERES_HUMANOS',
    'DEFINITIVA',
    'DEFINITIVA',
    'Autorización definitiva.',
    30
);

INSERT INTO config_subtipos_expediente (
    tipo_expediente_id,
    codigo,
    nombre,
    descripcion,
    orden,
    activo
)
SELECT
    type_row.id,
    subtype_seed.codigo,
    subtype_seed.nombre,
    subtype_seed.descripcion,
    subtype_seed.orden,
    1
FROM _immigration_subtype_seed subtype_seed
JOIN config_tipos_expediente type_row
  ON type_row.codigo =
     subtype_seed.tipo_codigo
WHERE NOT EXISTS (
    SELECT 1
    FROM config_subtipos_expediente current_subtype
    WHERE current_subtype.tipo_expediente_id =
          type_row.id
      AND current_subtype.codigo =
          subtype_seed.codigo
);

-- ------------------------------------------------------------------
-- 5. DESACTIVACIÓN DEL CATÁLOGO SUSTITUIDO
-- ------------------------------------------------------------------

-- Entradas genéricas sustituidas por tipos canónicos.

UPDATE config_tipos_expediente
SET
    activo = 0,
    descripcion = (
        COALESCE(descripcion || ' ', '')
        || '[HISTÓRICO] Sustituido por el catálogo '
        || 'normalizado de Extranjería.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo IN (
    'ESTANCIA_ESTUDIOS',
    'RENOVACION',
    'ESTATUTO_DE_ESPAÑOL'
);

-- Procedimientos históricos que deben seguir consultables,
-- pero no seleccionables para nuevas altas.

UPDATE config_tipos_expediente
SET
    activo = 0,
    descripcion = (
        COALESCE(descripcion || ' ', '')
        || '[HISTÓRICO] Procedimiento temporal cerrado.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo IN (
    'REGULARIZACION_MASIVA_TRANS_20',
    'REGULARIZACION_MASIVA_TRANS_21'
);

-- Desactivar también sus subtipos para nuevas altas.
-- No se eliminan porque pueden ser necesarios para trazabilidad histórica.

UPDATE config_subtipos_expediente
SET
    activo = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE tipo_expediente_id IN (
    SELECT id
    FROM config_tipos_expediente
    WHERE codigo IN (
        'ESTATUTO_DE_ESPAÑOL',
        'REGULARIZACION_MASIVA_TRANS_20',
        'REGULARIZACION_MASIVA_TRANS_21'
    )
);

-- ------------------------------------------------------------------
-- 6. NORMALIZACIÓN DEL VISADO DE REAGRUPACIÓN
-- ------------------------------------------------------------------

UPDATE config_tipos_expediente
SET
    nombre = 'VISADO DE REAGRUPACIÓN FAMILIAR',
    descripcion = (
        'Visado consular posterior a la concesión '
        || 'de una autorización de reagrupación familiar.'
    ),
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'TRAMITES_CONSULARES'
    ),
    workflow_code = 'TRAMITES_CONSULARES',
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 15
  AND codigo =
      'VISADO_REAGRUPACION_FAMILIAR';

-- ------------------------------------------------------------------
-- 7. POSTCONDICIONES DE SEGURIDAD
-- ------------------------------------------------------------------

DELETE FROM _immigration_catalog_assertion;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 13
          AND codigo =
              'RESIDENCIA_TEMPORAL_NO_LUCRATIVA'
          AND activo = 1
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 14
          AND codigo = 'REAGRUPACION_FAMILIAR'
          AND activo = 1
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM config_tipos_expediente
        WHERE id = 15
          AND codigo =
              'VISADO_REAGRUPACION_FAMILIAR'
          AND familia_id = (
              SELECT id
              FROM config_familias_expediente
              WHERE codigo =
                  'TRAMITES_CONSULARES'
          )
    )
    THEN 1
    ELSE 0
END;

INSERT INTO _immigration_catalog_assertion (valid)
SELECT CASE
    WHEN (
        SELECT COUNT(*)
        FROM config_tipos_expediente
        WHERE codigo IN (
            SELECT codigo
            FROM _immigration_type_seed
        )
          AND activo = 1
          AND familia_id = (
              SELECT id
              FROM config_familias_expediente
              WHERE codigo = 'EXTRANJERIA'
          )
    ) = (
        SELECT COUNT(*)
        FROM _immigration_type_seed
    )
    THEN 1
    ELSE 0
END;

DROP TABLE IF EXISTS temp._immigration_subtype_seed;
DROP TABLE IF EXISTS temp._immigration_type_seed;
DROP TABLE IF EXISTS temp._immigration_catalog_assertion;

-- =========================================
-- TABLA CLIENTES
-- =========================================

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    nombre TEXT NOT NULL,
    primer_apellido TEXT,
    segundo_apellido TEXT,

    nacionalidad TEXT,
    nie TEXT,
    pasaporte TEXT,
    dni TEXT,

    fecha_nacimiento TEXT,
    localidad_nacimiento TEXT,
    pais_nacimiento TEXT,

    nombre_padre TEXT,
    nombre_madre TEXT,

    estado_civil TEXT,

    telefono TEXT,
    email TEXT,

    domicilio_espana TEXT,
    localidad TEXT,
    codigo_postal TEXT,
    provincia TEXT,
    numero TEXT,
    piso TEXT,

    estado_cliente TEXT DEFAULT 'Asesoramiento inicial',
    fecha_alta TEXT,
    origen_cliente TEXT,
    responsable_interno TEXT,

    observaciones TEXT,
    observaciones_internas TEXT,

    activo INTEGER DEFAULT 1,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
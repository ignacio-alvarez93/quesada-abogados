CREATE TABLE IF NOT EXISTS config_formularios_expediente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    subtipo_expediente_id INTEGER,
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    orden INTEGER DEFAULT 0,
    activo INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (subtipo_expediente_id) REFERENCES config_subtipos_expediente(id),
    UNIQUE(tipo_expediente_id, subtipo_expediente_id, codigo)
);

CREATE TABLE IF NOT EXISTS config_campos_formulario_expediente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formulario_id INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    etiqueta TEXT NOT NULL,
    tipo_campo TEXT DEFAULT 'texto',
    obligatorio INTEGER DEFAULT 0,
    opciones_json TEXT,
    placeholder TEXT,
    ayuda TEXT,
    valor_defecto TEXT,
    orden INTEGER DEFAULT 0,
    activo INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (formulario_id) REFERENCES config_formularios_expediente(id) ON DELETE CASCADE,
    UNIQUE(formulario_id, codigo)
);

CREATE TABLE IF NOT EXISTS expediente_datos_especificos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    formulario_id INTEGER NOT NULL,
    campo_id INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    valor TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (formulario_id) REFERENCES config_formularios_expediente(id),
    FOREIGN KEY (campo_id) REFERENCES config_campos_formulario_expediente(id),
    UNIQUE(expediente_id, campo_id)
);

CREATE INDEX IF NOT EXISTS idx_cfg_form_exp_context
ON config_formularios_expediente(tipo_expediente_id, subtipo_expediente_id, activo, orden);

CREATE INDEX IF NOT EXISTS idx_cfg_campos_formulario
ON config_campos_formulario_expediente(formulario_id, activo, orden);

CREATE INDEX IF NOT EXISTS idx_exp_datos_especificos_exp
ON expediente_datos_especificos(expediente_id, formulario_id);

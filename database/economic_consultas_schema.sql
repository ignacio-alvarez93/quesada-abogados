-- database/economic_consultas_schema.sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS eco_consultas_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cobro_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    expediente_id INTEGER,
    hoja_encargo_id INTEGER,
    importe_aplicado REAL NOT NULL DEFAULT 0,
    fecha_aplicacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cobro_id) REFERENCES eco_cobros(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE SET NULL,
    FOREIGN KEY (hoja_encargo_id) REFERENCES eco_hojas_encargo(id) ON DELETE SET NULL,
    UNIQUE(cobro_id, expediente_id, hoja_encargo_id)
);

CREATE INDEX IF NOT EXISTS idx_eco_consultas_aplicadas_cobro ON eco_consultas_aplicadas(cobro_id);
CREATE INDEX IF NOT EXISTS idx_eco_consultas_aplicadas_cliente ON eco_consultas_aplicadas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_eco_consultas_aplicadas_expediente ON eco_consultas_aplicadas(expediente_id);
CREATE INDEX IF NOT EXISTS idx_eco_consultas_aplicadas_hoja ON eco_consultas_aplicadas(hoja_encargo_id);

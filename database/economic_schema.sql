-- database/economic_schema.sql
-- Módulo Económico - Fase 1
-- Hojas de encargo, cobros, facturas, gastos y movimientos para conciliación futura.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS eco_hojas_encargo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER,
    cliente_id INTEGER NOT NULL,
    numero_hoja TEXT,
    fecha_firma TEXT,
    procedimiento TEXT,
    importe_bruto REAL NOT NULL DEFAULT 0,
    descuento_manual REAL NOT NULL DEFAULT 0,
    descuento_consultas_previas REAL NOT NULL DEFAULT 0,
    importe_neto REAL NOT NULL DEFAULT 0,
    forma_pago_pactada TEXT,
    numero_plazos INTEGER DEFAULT 1,
    fecha_maxima_pago TEXT,
    documento_ruta TEXT,
    estado TEXT NOT NULL DEFAULT 'PENDIENTE FIRMA',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE SET NULL,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eco_cobros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_cobro TEXT NOT NULL UNIQUE,
    fecha_cobro TEXT NOT NULL,
    cliente_id INTEGER NOT NULL,
    expediente_id INTEGER,
    hoja_encargo_id INTEGER,
    importe REAL NOT NULL DEFAULT 0,
    forma_pago TEXT NOT NULL,
    concepto TEXT,
    tipo_cobro TEXT NOT NULL DEFAULT 'PAGO_EXPEDIENTE',
    facturable INTEGER NOT NULL DEFAULT 0,
    tipo_fiscal TEXT NOT NULL DEFAULT 'PROVISION',
    iva_porcentaje REAL NOT NULL DEFAULT 0,
    irpf_porcentaje REAL NOT NULL DEFAULT 0,
    factura_id INTEGER,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    recibo_ruta TEXT,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE SET NULL,
    FOREIGN KEY (hoja_encargo_id) REFERENCES eco_hojas_encargo(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS eco_configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT,
    descripcion TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eco_facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_factura TEXT NOT NULL UNIQUE,
    fecha_factura TEXT NOT NULL,
    cliente_id INTEGER NOT NULL,
    expediente_id INTEGER,
    hoja_encargo_id INTEGER,
    base_imponible REAL NOT NULL DEFAULT 0,
    iva REAL NOT NULL DEFAULT 0,
    irpf REAL NOT NULL DEFAULT 0,
    suplidos REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    tipo_fiscal TEXT NOT NULL DEFAULT 'PROVISION',
    concepto TEXT,
    tipo_factura TEXT NOT NULL DEFAULT 'NORMAL',
    factura_rectificada_id INTEGER,
    metodo_rectificacion TEXT,
    codigo_causa_rectificacion TEXT,
    causa_rectificacion TEXT,
    estado TEXT NOT NULL DEFAULT 'BORRADOR',
    -- Compatibilidad temporal:
    -- exportada_holded=1 significa factura aprobada/congelada.
    -- fecha_exportacion actúa como fecha de aprobación.
    exportada_holded INTEGER NOT NULL DEFAULT 0,
    fecha_exportacion TEXT,
    documento_ruta TEXT,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE SET NULL,
    FOREIGN KEY (hoja_encargo_id) REFERENCES eco_hojas_encargo(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS eco_factura_cobros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factura_id INTEGER NOT NULL,
    cobro_id INTEGER NOT NULL,
    importe_asignado REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (factura_id) REFERENCES eco_facturas(id) ON DELETE CASCADE,
    FOREIGN KEY (cobro_id) REFERENCES eco_cobros(id) ON DELETE CASCADE,
    UNIQUE(factura_id, cobro_id)
);

CREATE TABLE IF NOT EXISTS eco_gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_gasto TEXT NOT NULL,
    proveedor TEXT,
    concepto TEXT NOT NULL,
    categoria TEXT,
    importe REAL NOT NULL DEFAULT 0,
    forma_pago TEXT,
    deducible INTEGER NOT NULL DEFAULT 1,
    factura_recibida_ruta TEXT,
    expediente_id INTEGER,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS eco_movimientos_importados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origen TEXT NOT NULL,
    archivo_origen TEXT,
    fecha_operacion TEXT,
    fecha_valor TEXT,
    concepto TEXT,
    importe REAL NOT NULL DEFAULT 0,
    referencia TEXT,
    cuenta TEXT,
    tipo_movimiento TEXT,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    cobro_id INTEGER,
    gasto_id INTEGER,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cobro_id) REFERENCES eco_cobros(id) ON DELETE SET NULL,
    FOREIGN KEY (gasto_id) REFERENCES eco_gastos(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS eco_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad TEXT NOT NULL,
    entidad_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    usuario TEXT,
    fecha_evento TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eco_hojas_cliente ON eco_hojas_encargo(cliente_id);
CREATE INDEX IF NOT EXISTS idx_eco_hojas_expediente ON eco_hojas_encargo(expediente_id);
CREATE INDEX IF NOT EXISTS idx_eco_cobros_fecha ON eco_cobros(fecha_cobro);
CREATE INDEX IF NOT EXISTS idx_eco_cobros_cliente ON eco_cobros(cliente_id);
CREATE INDEX IF NOT EXISTS idx_eco_cobros_hoja ON eco_cobros(hoja_encargo_id);
CREATE INDEX IF NOT EXISTS idx_eco_facturas_fecha ON eco_facturas(fecha_factura);
CREATE INDEX IF NOT EXISTS idx_eco_facturas_tipo ON eco_facturas(tipo_factura);
CREATE INDEX IF NOT EXISTS idx_eco_facturas_rectificada ON eco_facturas(factura_rectificada_id);
CREATE INDEX IF NOT EXISTS idx_eco_gastos_fecha ON eco_gastos(fecha_gasto);
CREATE INDEX IF NOT EXISTS idx_eco_movimientos_origen ON eco_movimientos_importados(origen);

-- ============================================================
-- Una factura rectificativa inmoviliza su factura original.
-- ============================================================
CREATE TRIGGER IF NOT EXISTS
trg_eco_facturas_mark_original_rectified
AFTER INSERT ON eco_facturas
WHEN NEW.factura_rectificada_id IS NOT NULL
     AND UPPER(
            COALESCE(NEW.tipo_factura, 'NORMAL')
         ) = 'RECTIFICATIVA'
BEGIN
    UPDATE eco_facturas
    SET estado = 'RECTIFICADA',
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.factura_rectificada_id
      AND UPPER(
            COALESCE(tipo_factura, 'NORMAL')
          ) != 'RECTIFICATIVA';
END;



-- ============================================================
-- Integración Holded API
-- ============================================================

CREATE TABLE IF NOT EXISTS eco_holded_contact_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL UNIQUE,
    holded_contact_id TEXT NOT NULL,
    vat_number TEXT,
    contact_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eco_holded_contact_links_remote
    ON eco_holded_contact_links(holded_contact_id);

CREATE TABLE IF NOT EXISTS eco_holded_invoice_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factura_id INTEGER NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL,
    holded_contact_id TEXT,
    holded_document_id TEXT,
    holded_document_number TEXT,
    sync_status TEXT NOT NULL DEFAULT 'PENDING',
    requires_manual_review INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    payload_json TEXT,
    response_json TEXT,
    synced_at TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (factura_id)
        REFERENCES eco_facturas(id)
        ON DELETE CASCADE,
    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eco_holded_invoice_sync_status
    ON eco_holded_invoice_sync(sync_status);

CREATE INDEX IF NOT EXISTS idx_eco_holded_invoice_sync_remote
    ON eco_holded_invoice_sync(holded_document_id);

-- BANK MOVEMENT INVOICEABILITY
-- Migración runtime gestionada por bank_query_service.py.
-- Campos de bank_movements:
--   invoiceability_status TEXT NOT NULL DEFAULT 'PENDING'
--   invoiceability_reason TEXT
--   invoiceability_updated_at TEXT
-- Estados soportados:
--   PENDING
--   NON_INVOICEABLE
--   FACTURABLE
-- Índice:
--   idx_bank_movements_invoiceability_status

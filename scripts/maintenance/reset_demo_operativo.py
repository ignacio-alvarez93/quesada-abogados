import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    tablas = [
        "eco_factura_cobros",
        "eco_movimientos_importados",
        "eco_gastos",
        "eco_facturas",
        "eco_cobros",
        "eco_hojas_encargo",
        "expediente_consultas_aplicadas",
        "consultas_previas",
        "expediente_justificantes",
        "expediente_eventos",
        "expedientes",
        "clientes",
    ]

    for tabla in tablas:
        existe = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tabla,),
        ).fetchone()
        if existe:
            conn.execute(f"DELETE FROM {tabla}")

    conn.execute("PRAGMA foreign_keys = ON")

    cliente_id = conn.execute("""
        INSERT INTO clientes (
            nombre, primer_apellido, segundo_apellido, nie, nacionalidad,
            telefono, email, estado_cliente, activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        "CLIENTE",
        "DEMO",
        "ERP",
        "X1234567Y",
        "MARRUECOS",
        "600000000",
        "cliente.demo@quesada.local",
        "Expediente abierto",
    )).lastrowid

    tipo_id = conn.execute("SELECT id FROM config_tipos_expediente LIMIT 1").fetchone()["id"]
    prioridad_id = conn.execute("SELECT id FROM config_prioridades LIMIT 1").fetchone()["id"]
    estado_doc_id = conn.execute("SELECT id FROM config_estados_documentales LIMIT 1").fetchone()["id"]
    estado_admin_id = conn.execute("SELECT id FROM config_estados_administrativos LIMIT 1").fetchone()["id"]

    expediente_id = conn.execute("""
        INSERT INTO expedientes (
            cliente_id, numero_expediente, tipo_expediente_id,
            subtipo_expediente, estado_documental_id,
            estado_administrativo_id, estado_presentacion,
            prioridad_id, responsable, fecha_apertura,
            fecha_presentacion, numero_registro, provincia, activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        cliente_id,
        "EXP-2026-0001",
        tipo_id,
        "ARRAIGO SOCIAL DEMO",
        estado_doc_id,
        estado_admin_id,
        "PRESENTADO",
        prioridad_id,
        "NACHO",
        "2026-05-01",
        "2026-05-02",
        "REG-DEMO-2026-0001",
        "ALMERÍA",
    )).lastrowid

    hoja_id = conn.execute("""
        INSERT INTO eco_hojas_encargo (
            expediente_id, cliente_id, numero_hoja, fecha_firma,
            procedimiento, importe_bruto, descuento_manual,
            descuento_consultas_previas, importe_neto,
            forma_pago_pactada, numero_plazos, estado, activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        expediente_id,
        cliente_id,
        "HE-2026-0001",
        "2026-05-01",
        "ARRAIGO SOCIAL",
        700,
        0,
        50,
        650,
        "FRACCIONADO",
        2,
        "FIRMADA",
    )).lastrowid

    cobro_id = conn.execute("""
        INSERT INTO eco_cobros (
            numero_cobro, fecha_cobro, cliente_id, expediente_id,
            hoja_encargo_id, importe, forma_pago, concepto,
            tipo_cobro, facturable, estado_conciliacion, activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        "COB-20260001",
        "2026-05-03",
        cliente_id,
        expediente_id,
        hoja_id,
        350,
        "TRANSFERENCIA",
        "PRIMER PAGO ARRAIGO SOCIAL",
        "PAGO_EXPEDIENTE",
        1,
        "CONCILIADO",
    )).lastrowid

    factura_id = conn.execute("""
        INSERT INTO eco_facturas (
            numero_factura, fecha_factura, cliente_id, expediente_id,
            hoja_encargo_id, base_imponible, iva, irpf, total,
            estado, exportada_holded, activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        "FRA-20260001",
        "2026-05-03",
        cliente_id,
        expediente_id,
        hoja_id,
        350,
        0,
        0,
        350,
        "EMITIDA",
        0,
    )).lastrowid

    conn.execute("""
        INSERT INTO eco_factura_cobros (factura_id, cobro_id, importe_asignado)
        VALUES (?, ?, ?)
    """, (factura_id, cobro_id, 350))

    conn.execute("""
        UPDATE eco_cobros
        SET factura_id = ?
        WHERE id = ?
    """, (factura_id, cobro_id))

    conn.commit()
    conn.close()

    print("Base limpiada y demo creada correctamente.")
    print(f"Cliente: {cliente_id}")
    print(f"Expediente: {expediente_id}")
    print(f"Hoja encargo: {hoja_id}")
    print(f"Cobro: COB-20260001")
    print(f"Factura: FRA-20260001")


if __name__ == "__main__":
    main()
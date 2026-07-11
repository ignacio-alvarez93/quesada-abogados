import csv
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _text(value):
    return (value or "").strip().upper()


def _raw(value):
    return (value or "").strip()


def _float(value):
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(".", "").replace(",", ".") if "," in str(value) else str(value))
    except ValueError:
        return 0.0


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _date(value):
    value = _raw(value)
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def initialize_expediente_clientes_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expediente_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expediente_id INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            rol TEXT NOT NULL DEFAULT 'RELACIONADO',
            es_principal INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
            UNIQUE(expediente_id, cliente_id, rol)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_clientes_expediente ON expediente_clientes(expediente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_clientes_cliente ON expediente_clientes(cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_clientes_rol ON expediente_clientes(rol)")

    if _table_exists(conn, "expedientes"):
        conn.execute(
            """
            INSERT OR IGNORE INTO expediente_clientes (
                expediente_id, cliente_id, rol, es_principal, activo
            )
            SELECT id, cliente_id, 'CLIENTE_PRINCIPAL', 1, 1
            FROM expedientes
            WHERE cliente_id IS NOT NULL
            """
        )


def _ensure_column(conn, table, column, definition):
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }

    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def initialize_economic_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "economic_schema.sql"
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))

        _ensure_column(
            conn,
            "eco_cobros",
            "tipo_fiscal",
            "TEXT NOT NULL DEFAULT 'PROVISION'",
        )
        _ensure_column(
            conn,
            "eco_cobros",
            "iva_porcentaje",
            "REAL NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "eco_cobros",
            "irpf_porcentaje",
            "REAL NOT NULL DEFAULT 0",
        )

        initialize_expediente_clientes_schema(conn)
        initialize_economic_consultas_schema(conn)
        conn.commit()


def ensure_expediente_cliente(conn, expediente_id, cliente_id, rol="RELACIONADO", es_principal=0):
    if not expediente_id or not cliente_id:
        return
    initialize_expediente_clientes_schema(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO expediente_clientes (
            expediente_id, cliente_id, rol, es_principal, activo
        )
        VALUES (?, ?, ?, ?, 1)
        """,
        (int(expediente_id), int(cliente_id), _text(rol), int(es_principal)),
    )


def registrar_evento(entidad, entidad_id, tipo_evento, titulo, descripcion="", estado_anterior="", estado_nuevo="", usuario=""):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_eventos (
                entidad, entidad_id, tipo_evento, titulo, descripcion,
                estado_anterior, estado_nuevo, usuario
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _text(entidad),
                int(entidad_id),
                _text(tipo_evento),
                _text(titulo),
                _raw(descripcion),
                _text(estado_anterior),
                _text(estado_nuevo),
                _text(usuario),
            ),
        )
        conn.commit()
        return cur.lastrowid


def _number_prefix(prefix, year):
    return f"{prefix}-{year}-"


def _format_number(prefix, year, seq):
    return f"{prefix}-{year}-{str(seq).zfill(4)}"


def _next_number(table, number_field, prefix, date_value):
    fecha = _date(date_value)
    year = fecha[:4] if fecha else datetime.today().strftime("%Y")
    number_prefix = _number_prefix(prefix, year)

    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT {number_field}
            FROM {table}
            WHERE {number_field} LIKE ?
            ORDER BY {number_field} DESC
            LIMIT 1
            """,
            (number_prefix + "%",),
        ).fetchone()

    if not row or not row[number_field]:
        return _format_number(prefix, year, 1)

    last = row[number_field]
    try:
        seq = int(str(last).split("-")[-1])
    except Exception:
        seq = 0

    return _format_number(prefix, year, seq + 1)


def _renumerar_por_fecha(conn, table, id_field, number_field, date_field, prefix, year):
    """
    Renumera por año y fecha real en dos fases para evitar UNIQUE.

    Formato:
        COB-2026-0001
        FRA-2026-0001
    """
    rows = conn.execute(
        f"""
        SELECT {id_field} AS id
        FROM {table}
        WHERE COALESCE(activo, 1) = 1
          AND substr(COALESCE({date_field}, ''), 1, 4) = ?
        ORDER BY {date_field} ASC, {id_field} ASC
        """,
        (str(year),),
    ).fetchall()

    # Fase 1: numeración temporal única para no pisar valores existentes.
    for row in rows:
        conn.execute(
            f"""
            UPDATE {table}
            SET {number_field} = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE {id_field} = ?
            """,
            (f"TMP-{prefix}-{int(row['id'])}", int(row["id"])),
        )

    # Fase 2: numeración definitiva.
    for index, row in enumerate(rows, start=1):
        conn.execute(
            f"""
            UPDATE {table}
            SET {number_field} = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE {id_field} = ?
            """,
            (_format_number(prefix, year, index), int(row["id"])),
        )


def renumerar_cobros_por_year(conn, year):
    _renumerar_por_fecha(
        conn=conn,
        table="eco_cobros",
        id_field="id",
        number_field="numero_cobro",
        date_field="fecha_cobro",
        prefix="COB",
        year=year,
    )


def renumerar_facturas_por_year(conn, year):
    _renumerar_por_fecha(
        conn=conn,
        table="eco_facturas",
        id_field="id",
        number_field="numero_factura",
        date_field="fecha_factura",
        prefix="FRA",
        year=year,
    )


def _calculate_invoice_from_total(
    total,
    iva_porcentaje=0,
    irpf_porcentaje=0,
):
    total = round(float(total or 0), 2)
    iva_porcentaje = float(iva_porcentaje or 0)
    irpf_porcentaje = float(irpf_porcentaje or 0)

    if iva_porcentaje < 0 or irpf_porcentaje < 0:
        raise ValueError("IVA e IRPF no pueden ser negativos")

    divisor = 1 + (iva_porcentaje / 100) - (irpf_porcentaje / 100)

    if divisor <= 0:
        raise ValueError(
            "La combinación de IVA e IRPF no permite calcular la factura"
        )

    base = round(total / divisor, 2)
    iva = round(base * iva_porcentaje / 100, 2)
    irpf = round(base * irpf_porcentaje / 100, 2)

    # El total definitivo debe coincidir con el importe cobrado.
    diferencia = round(total - (base + iva - irpf), 2)

    if diferencia:
        base = round(base + diferencia, 2)
        iva = round(base * iva_porcentaje / 100, 2)
        irpf = round(base + iva - total, 2)

    return {
        "base_imponible": base,
        "iva": iva,
        "irpf": irpf,
        "total": total,
    }


def _crear_factura_automatica_por_cobro(conn, cobro_id):
    cobro = _dict(
        conn.execute(
            "SELECT * FROM eco_cobros WHERE id = ? AND activo = 1",
            (int(cobro_id),),
        ).fetchone()
    )

    if not cobro:
        raise ValueError("Cobro no encontrado para facturar")

    if not int(cobro.get("facturable") or 0):
        return None

    fecha = cobro.get("fecha_cobro") or datetime.today().strftime("%Y-%m-%d")
    year = fecha[:4]
    importe = float(cobro.get("importe") or 0)

    iva_porcentaje = cobro.get("iva_porcentaje")

    if str(cobro.get("tipo_fiscal") or "").upper() == "SUPLIDO":
        iva_porcentaje = 0

    fiscal = _calculate_invoice_from_total(
        importe,
        iva_porcentaje,
        cobro.get("irpf_porcentaje"),
    )

    factura_id = cobro.get("factura_id")

    if factura_id:
        conn.execute(
            """
            UPDATE eco_facturas
            SET fecha_factura = ?,
                cliente_id = ?,
                expediente_id = ?,
                hoja_encargo_id = ?,
                base_imponible = ?,
                iva = ?,
                irpf = ?,
                total = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (
                fecha,
                cobro["cliente_id"],
                cobro.get("expediente_id"),
                cobro.get("hoja_encargo_id"),
                fiscal["base_imponible"],
                fiscal["iva"],
                fiscal["irpf"],
                fiscal["total"],
                int(factura_id),
            ),
        )

        conn.execute(
            """
            UPDATE eco_factura_cobros
            SET importe_asignado = ?
            WHERE factura_id = ?
              AND cobro_id = ?
            """,
            (importe, int(factura_id), int(cobro_id)),
        )

        renumerar_facturas_por_year(conn, year)
        return int(factura_id)

    numero_factura = next_numero_factura(fecha)

    cur = conn.execute(
        """
        INSERT INTO eco_facturas (
            numero_factura,
            fecha_factura,
            cliente_id,
            expediente_id,
            hoja_encargo_id,
            base_imponible,
            iva,
            irpf,
            total,
            estado,
            exportada_holded,
            documento_ruta,
            observaciones,
            activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            numero_factura,
            fecha,
            cobro["cliente_id"],
            cobro.get("expediente_id"),
            cobro.get("hoja_encargo_id"),
            fiscal["base_imponible"],
            fiscal["iva"],
            fiscal["irpf"],
            fiscal["total"],
            "EMITIDA",
            0,
            "",
            (
                "Factura automática generada desde cobro "
                f"{cobro.get('numero_cobro') or cobro_id}"
            ),
        ),
    )

    factura_id = cur.lastrowid

    conn.execute(
        """
        UPDATE eco_cobros
        SET factura_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (factura_id, int(cobro_id)),
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO eco_factura_cobros (
            factura_id,
            cobro_id,
            importe_asignado
        )
        VALUES (?, ?, ?)
        """,
        (factura_id, int(cobro_id), importe),
    )

    renumerar_facturas_por_year(conn, year)
    return factura_id


def next_numero_hoja(fecha_firma):
    return _next_number("eco_hojas_encargo", "numero_hoja", "HE", fecha_firma)


def next_numero_cobro(fecha_cobro):
    """
    Genera el siguiente número de cobro siguiendo la secuencia global del año.

    Regla:
    - COB-YYYY-0001, COB-YYYY-0002, ...
    - No debe reiniciarse ni retroceder por mes/día de fecha_cobro.
    - Debe mirar todos los numero_cobro existentes del mismo año y tomar MAX + 1.

    Motivo:
    En conciliación bancaria puede generarse un cobro con fecha de movimiento anterior
    a la fecha actual. Aun así, el número del cobro debe continuar la secuencia general.
    """
    import re

    fecha = _date(fecha_cobro)
    year = fecha[:4] if fecha else datetime.today().strftime("%Y")
    prefix = f"COB-{year}-"

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT numero_cobro
            FROM eco_cobros
            WHERE numero_cobro LIKE ?
            """,
            (prefix + "%",),
        ).fetchall()

    max_number = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")

    for row in rows:
        value = row["numero_cobro"] if hasattr(row, "keys") else row[0]
        match = pattern.match(str(value or "").strip())
        if not match:
            continue

        try:
            max_number = max(max_number, int(match.group(1)))
        except Exception:
            continue

    return f"{prefix}{max_number + 1:04d}"


def next_numero_factura(fecha_factura):
    return _next_number("eco_facturas", "numero_factura", "FRA", fecha_factura)


def get_clientes_for_select():
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, nombre, primer_apellido, segundo_apellido, nie, pasaporte, dni
            FROM clientes
            WHERE COALESCE(activo, 1) = 1
            ORDER BY nombre ASC, primer_apellido ASC, segundo_apellido ASC
            """
        ).fetchall()

    result = []
    for r in rows:
        item = _dict(r)
        nombre = " ".join(
            [item.get("nombre") or "", item.get("primer_apellido") or "", item.get("segundo_apellido") or ""]
        ).strip() or f"CLIENTE {item['id']}"
        doc = item.get("nie") or item.get("pasaporte") or item.get("dni") or ""
        item["display"] = f"{item['id']} - {nombre}" + (f" · {doc}" if doc else "")
        result.append(item)
    return result


def get_expedientes_for_select(cliente_id=None):
    with _connect() as conn:
        initialize_expediente_clientes_schema(conn)
        sql = """
            SELECT DISTINCT
                e.id,
                e.numero_expediente,
                e.cliente_id,
                t.nombre AS tipo_nombre
            FROM expedientes e
            LEFT JOIN config_tipos_expediente t ON t.id = e.tipo_expediente_id
            LEFT JOIN expediente_clientes ec ON ec.expediente_id = e.id AND ec.activo = 1
            WHERE e.activo = 1
        """
        params = []

        if cliente_id:
            sql += " AND (e.cliente_id = ? OR ec.cliente_id = ?)"
            params.extend([int(cliente_id), int(cliente_id)])

        sql += " ORDER BY e.created_at DESC, e.id DESC"
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            **_dict(r),
            "display": f"{r['id']} - {r['numero_expediente']} · {r['tipo_nombre'] or ''}",
        }
        for r in rows
    ]


def get_hojas_for_select(cliente_id=None, expediente_id=None):
    sql = """
        SELECT DISTINCT
            h.*,
            e.numero_expediente
        FROM eco_hojas_encargo h
        LEFT JOIN expedientes e ON e.id = h.expediente_id
        LEFT JOIN expediente_clientes ec
            ON ec.expediente_id = h.expediente_id
           AND ec.activo = 1
        WHERE h.activo = 1
    """
    params = []

    if expediente_id:
        sql += " AND h.expediente_id = ?"
        params.append(int(expediente_id))

    if cliente_id:
        sql += """
            AND (
                h.cliente_id = ?
                OR e.cliente_id = ?
                OR ec.cliente_id = ?
            )
        """
        params.extend([int(cliente_id), int(cliente_id), int(cliente_id)])

    sql += " ORDER BY h.created_at DESC, h.id DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        neto = float(item.get("importe_neto") or 0)
        item["display"] = (
            f"{item['id']} - {item.get('numero_hoja') or 'HOJA'}"
            f" · {item.get('numero_expediente') or ''}"
            f" · Importe {neto:.2f} €"
        )
        result.append(item)

    return result


def create_hoja_encargo(data):
    numero_hoja = _text(data.get("numero_hoja")) or next_numero_hoja(data.get("fecha_firma"))
    importe_bruto = _float(data.get("importe_bruto"))
    descuento_manual = _float(data.get("descuento_manual"))
    descuento_consultas = _float(data.get("descuento_consultas_previas"))
    importe_neto = max(0, importe_bruto - descuento_manual - descuento_consultas)
    expediente_id = _int_or_none(data.get("expediente_id"))
    cliente_id = int(data.get("cliente_id"))

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_hojas_encargo (
                expediente_id, cliente_id, numero_hoja, fecha_firma, procedimiento,
                importe_bruto, descuento_manual, descuento_consultas_previas, importe_neto,
                forma_pago_pactada, numero_plazos, fecha_maxima_pago, documento_ruta,
                estado, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                expediente_id,
                cliente_id,
                numero_hoja,
                _date(data.get("fecha_firma")),
                _text(data.get("procedimiento")),
                importe_bruto,
                descuento_manual,
                descuento_consultas,
                importe_neto,
                _text(data.get("forma_pago_pactada")),
                int(data.get("numero_plazos") or 1),
                _date(data.get("fecha_maxima_pago")),
                _raw(data.get("documento_ruta")),
                _text(data.get("estado") or "PENDIENTE FIRMA"),
                _raw(data.get("observaciones")),
            ),
        )
        hoja_id = cur.lastrowid
        ensure_expediente_cliente(conn, expediente_id, cliente_id, rol="PAGADOR", es_principal=0)
        conn.commit()

    registrar_evento("eco_hojas_encargo", hoja_id, "CREACION", "HOJA DE ENCARGO CREADA", f"Neto: {importe_neto:.2f}")
    return hoja_id


def list_hojas_encargo(active_only=True):
    sql = """
        SELECT h.*, c.nombre, c.primer_apellido, c.segundo_apellido, e.numero_expediente
        FROM eco_hojas_encargo h
        JOIN clientes c ON c.id = h.cliente_id
        LEFT JOIN expedientes e ON e.id = h.expediente_id
    """
    if active_only:
        sql += " WHERE h.activo = 1"
    sql += " ORDER BY h.created_at DESC, h.id DESC"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql).fetchall()]


def create_cobro(data):
    fecha_cobro = _date(data.get("fecha_cobro"))
    year = fecha_cobro[:4] if fecha_cobro else datetime.today().strftime("%Y")
    # La numeración de cobros debe ser única, correlativa y gobernada por backend.
    # No aceptamos numero_cobro desde formularios para evitar arrastres de UI,
    # duplicados o reinicios por fecha de movimiento.
    numero = next_numero_cobro(fecha_cobro)
    tipo_cobro = _text(data.get("tipo_cobro") or "PAGO_EXPEDIENTE")
    facturable = int(data.get("facturable", 0))

    raw_tipo_fiscal = _text(
        data.get("tipo_fiscal") or "PROVISION"
    ).strip().upper()

    tipo_fiscal = (
        "SUPLIDO"
        if raw_tipo_fiscal == "SUPLIDO"
        else "PROVISION"
    )

    iva_porcentaje = (
        _float(data.get("iva_porcentaje"))
        if facturable
        else 0.0
    )
    irpf_porcentaje = (
        _float(data.get("irpf_porcentaje"))
        if facturable
        else 0.0
    )

    # Regla fiscal de negocio:
    # los suplidos no soportan IVA.
    if tipo_fiscal == "SUPLIDO":
        iva_porcentaje = 0.0
    expediente_id = _int_or_none(data.get("expediente_id"))
    hoja_id = _int_or_none(data.get("hoja_encargo_id"))
    cliente_id = int(data.get("cliente_id"))

    if tipo_cobro != "CONSULTA" and not hoja_id:
        raise ValueError("Los cobros de expediente deben estar asociados a una hoja de encargo")

    with _connect() as conn:
        if hoja_id:
            hoja = _dict(
                conn.execute(
                    "SELECT * FROM eco_hojas_encargo WHERE id = ?",
                    (hoja_id,),
                ).fetchone()
            )
            if not hoja:
                raise ValueError("Hoja de encargo no encontrada")
            if not expediente_id:
                expediente_id = hoja.get("expediente_id")

        cur = conn.execute(
            """
            INSERT INTO eco_cobros (
                numero_cobro, fecha_cobro, cliente_id, expediente_id, hoja_encargo_id,
                importe, forma_pago, concepto, tipo_cobro, facturable,
                tipo_fiscal, iva_porcentaje, irpf_porcentaje,
                estado_conciliacion,
                recibo_ruta, observaciones, activo
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, 1
            )
            """,
            (
                numero,
                fecha_cobro,
                cliente_id,
                expediente_id,
                hoja_id,
                _float(data.get("importe")),
                _text(data.get("forma_pago")),
                _text(data.get("concepto")),
                tipo_cobro,
                facturable,
                tipo_fiscal,
                iva_porcentaje,
                irpf_porcentaje,
                _text(data.get("estado_conciliacion") or "PENDIENTE"),
                _raw(data.get("recibo_ruta")),
                _raw(data.get("observaciones")),
            ),
        )
        cobro_id = cur.lastrowid

        ensure_expediente_cliente(conn, expediente_id, cliente_id, rol="PAGADOR", es_principal=0)

        renumerar_cobros_por_year(conn, year)

        if facturable:
            _crear_factura_automatica_por_cobro(conn, cobro_id)

        conn.commit()

    registrar_evento(
        "eco_cobros",
        cobro_id,
        "CREACION",
        "COBRO REGISTRADO",
        f"{numero} · {_float(data.get('importe')):.2f}",
    )

    return cobro_id

def update_cobro(cobro_id, data):
    cobro_id = int(cobro_id)
    fecha_cobro = _date(data.get("fecha_cobro"))
    year = fecha_cobro[:4] if fecha_cobro else datetime.today().strftime("%Y")
    tipo_cobro = _text(data.get("tipo_cobro") or "PAGO_EXPEDIENTE")
    facturable = int(data.get("facturable", 0))

    raw_tipo_fiscal = _text(
        data.get("tipo_fiscal") or "PROVISION"
    ).strip().upper()

    tipo_fiscal = (
        "SUPLIDO"
        if raw_tipo_fiscal == "SUPLIDO"
        else "PROVISION"
    )

    iva_porcentaje = (
        _float(data.get("iva_porcentaje"))
        if facturable
        else 0.0
    )
    irpf_porcentaje = (
        _float(data.get("irpf_porcentaje"))
        if facturable
        else 0.0
    )

    # Regla fiscal de negocio:
    # los suplidos no soportan IVA.
    if tipo_fiscal == "SUPLIDO":
        iva_porcentaje = 0.0
    expediente_id = _int_or_none(data.get("expediente_id"))
    hoja_id = _int_or_none(data.get("hoja_encargo_id"))

    if tipo_cobro != "CONSULTA" and not hoja_id:
        raise ValueError("Los cobros de expediente deben estar asociados a una hoja de encargo")

    with _connect() as conn:
        old = _dict(
            conn.execute(
                "SELECT * FROM eco_cobros WHERE id = ? AND activo = 1",
                (cobro_id,),
            ).fetchone()
        )
        if not old:
            raise ValueError("Cobro no encontrado")

        if hoja_id:
            hoja = _dict(
                conn.execute(
                    "SELECT * FROM eco_hojas_encargo WHERE id = ?",
                    (hoja_id,),
                ).fetchone()
            )
            if not hoja:
                raise ValueError("Hoja de encargo no encontrada")
            if not expediente_id:
                expediente_id = hoja.get("expediente_id")

        conn.execute(
            """
            UPDATE eco_cobros
            SET fecha_cobro = ?,
                expediente_id = ?,
                hoja_encargo_id = ?,
                importe = ?,
                forma_pago = ?,
                concepto = ?,
                tipo_cobro = ?,
                facturable = ?,
                tipo_fiscal = ?,
                iva_porcentaje = ?,
                irpf_porcentaje = ?,
                recibo_ruta = ?,
                observaciones = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                fecha_cobro,
                expediente_id,
                hoja_id,
                _float(data.get("importe")),
                _text(data.get("forma_pago")),
                _text(data.get("concepto")),
                tipo_cobro,
                facturable,
                tipo_fiscal,
                iva_porcentaje,
                irpf_porcentaje,
                _raw(data.get("recibo_ruta")),
                _raw(data.get("observaciones")),
                cobro_id,
            ),
        )

        ensure_expediente_cliente(conn, expediente_id, old["cliente_id"], rol="PAGADOR", es_principal=0)

        years = {year}
        if old.get("fecha_cobro"):
            years.add(str(old["fecha_cobro"])[:4])
        for y in years:
            renumerar_cobros_por_year(conn, y)

        if facturable:
            _crear_factura_automatica_por_cobro(conn, cobro_id)

        conn.commit()

    registrar_evento(
        "eco_cobros",
        cobro_id,
        "MODIFICACION",
        "COBRO MODIFICADO",
        f"Cobro {cobro_id} modificado",
    )
    return cobro_id

def list_cobros(active_only=True):
    sql = """
        SELECT cob.*, c.nombre, c.primer_apellido, c.segundo_apellido,
               e.numero_expediente, h.numero_hoja, f.numero_factura
        FROM eco_cobros cob
        JOIN clientes c ON c.id = cob.cliente_id
        LEFT JOIN expedientes e ON e.id = cob.expediente_id
        LEFT JOIN eco_hojas_encargo h ON h.id = cob.hoja_encargo_id
        LEFT JOIN eco_facturas f ON f.id = cob.factura_id
    """
    if active_only:
        sql += " WHERE cob.activo = 1"
    sql += " ORDER BY cob.fecha_cobro DESC, cob.id DESC"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql).fetchall()]


def create_factura(data, cobro_ids=None):
    fecha = _date(data.get("fecha_factura"))
    year = fecha[:4] if fecha else datetime.today().strftime("%Y")
    numero = _text(data.get("numero_factura")) or next_numero_factura(fecha)
    base = _float(data.get("base_imponible"))
    iva = _float(data.get("iva"))
    irpf = _float(data.get("irpf"))
    total = _float(data.get("total")) or (base + iva - irpf)
    expediente_id = _int_or_none(data.get("expediente_id"))
    hoja_id = _int_or_none(data.get("hoja_encargo_id"))
    cliente_id = int(data.get("cliente_id"))

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_facturas (
                numero_factura, fecha_factura, cliente_id, expediente_id, hoja_encargo_id,
                base_imponible, iva, irpf, total, estado, exportada_holded,
                documento_ruta, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                numero,
                fecha,
                cliente_id,
                expediente_id,
                hoja_id,
                base,
                iva,
                irpf,
                total,
                _text(data.get("estado") or "EMITIDA"),
                int(data.get("exportada_holded", 0)),
                _raw(data.get("documento_ruta")),
                _raw(data.get("observaciones")),
            ),
        )
        factura_id = cur.lastrowid
        ensure_expediente_cliente(conn, expediente_id, cliente_id, rol="PAGADOR", es_principal=0)

        for cobro_id in cobro_ids or []:
            cobro = conn.execute(
                "SELECT importe FROM eco_cobros WHERE id = ?",
                (int(cobro_id),),
            ).fetchone()
            importe = float(cobro["importe"]) if cobro else 0
            conn.execute(
                """
                INSERT OR IGNORE INTO eco_factura_cobros (factura_id, cobro_id, importe_asignado)
                VALUES (?, ?, ?)
                """,
                (factura_id, int(cobro_id), importe),
            )
            conn.execute(
                """
                UPDATE eco_cobros
                SET factura_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (factura_id, int(cobro_id)),
            )

        renumerar_facturas_por_year(conn, year)
        conn.commit()

    registrar_evento(
        "eco_facturas",
        factura_id,
        "CREACION",
        "FACTURA CREADA",
        f"{numero} · {total:.2f}",
    )

    return factura_id

def list_facturas(active_only=True):
    sql = """
        SELECT f.*, c.nombre, c.primer_apellido, c.segundo_apellido,
               e.numero_expediente, h.numero_hoja
        FROM eco_facturas f
        JOIN clientes c ON c.id = f.cliente_id
        LEFT JOIN expedientes e ON e.id = f.expediente_id
        LEFT JOIN eco_hojas_encargo h ON h.id = f.hoja_encargo_id
    """
    if active_only:
        sql += " WHERE f.activo = 1"
    sql += " ORDER BY f.fecha_factura DESC, f.id DESC"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql).fetchall()]


def create_gasto(data):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_gastos (
                fecha_gasto, proveedor, concepto, categoria, importe, forma_pago,
                deducible, factura_recibida_ruta, expediente_id, estado_conciliacion,
                observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                _date(data.get("fecha_gasto")),
                _text(data.get("proveedor")),
                _text(data.get("concepto")),
                _text(data.get("categoria")),
                _float(data.get("importe")),
                _text(data.get("forma_pago")),
                int(data.get("deducible", 1)),
                _raw(data.get("factura_recibida_ruta")),
                _int_or_none(data.get("expediente_id")),
                _text(data.get("estado_conciliacion") or "PENDIENTE"),
                _raw(data.get("observaciones")),
            ),
        )
        conn.commit()
        gasto_id = cur.lastrowid

    registrar_evento("eco_gastos", gasto_id, "CREACION", "GASTO REGISTRADO", f"{_float(data.get('importe')):.2f}")
    return gasto_id


def list_gastos(active_only=True):
    sql = """
        SELECT g.*, e.numero_expediente
        FROM eco_gastos g
        LEFT JOIN expedientes e ON e.id = g.expediente_id
    """
    if active_only:
        sql += " WHERE g.activo = 1"
    sql += " ORDER BY g.fecha_gasto DESC, g.id DESC"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql).fetchall()]


def create_movimiento_importado(data):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_movimientos_importados (
                origen, archivo_origen, fecha_operacion, fecha_valor,
                concepto, importe, referencia, cuenta, tipo_movimiento,
                estado_conciliacion, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                _text(data.get("origen")),
                _raw(data.get("archivo_origen")),
                _date(data.get("fecha_operacion")),
                _date(data.get("fecha_valor")),
                _raw(data.get("concepto")),
                _float(data.get("importe")),
                _raw(data.get("referencia")),
                _text(data.get("cuenta")),
                _text(data.get("tipo_movimiento")),
                _text(data.get("estado_conciliacion") or "PENDIENTE"),
                _raw(data.get("observaciones")),
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_movimientos(active_only=True):
    sql = "SELECT * FROM eco_movimientos_importados"
    if active_only:
        sql += " WHERE activo = 1"
    sql += " ORDER BY fecha_operacion DESC, id DESC"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql).fetchall()]


def conciliar_movimiento_con_cobro(movimiento_id, cobro_id):
    with _connect() as conn:
        mov = _dict(conn.execute("SELECT * FROM eco_movimientos_importados WHERE id = ?", (int(movimiento_id),)).fetchone())
        cob = _dict(conn.execute("SELECT * FROM eco_cobros WHERE id = ?", (int(cobro_id),)).fetchone())
        if not mov or not cob:
            raise ValueError("Movimiento o cobro no encontrado")

        conn.execute(
            """
            UPDATE eco_movimientos_importados
            SET cobro_id = ?, estado_conciliacion = 'CONCILIADO', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(cobro_id), int(movimiento_id)),
        )
        conn.execute(
            """
            UPDATE eco_cobros
            SET estado_conciliacion = 'CONCILIADO', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(cobro_id),),
        )
        conn.commit()

    registrar_evento("eco_cobros", cobro_id, "CONCILIACION", "COBRO CONCILIADO", f"Movimiento {movimiento_id}")



def get_deuda_cliente(cliente_id):
    """
    Calcula deuda pendiente por cliente usando SOLO hojas de encargo y cobros activos.

    deuda = SUM(eco_hojas_encargo.importe_neto) - SUM(eco_cobros.importe)

    No usa facturas.
    Devuelve total y desglose por expediente/trámite.
    """
    cliente_id = int(cliente_id)
    resumen = {
        "cliente_id": cliente_id,
        "importe_hojas": 0.0,
        "importe_cobros": 0.0,
        "deuda_total": 0.0,
        "tramites": [],
    }

    with _connect() as conn:
        if not _table_exists(conn, "eco_hojas_encargo") or not _table_exists(conn, "eco_cobros"):
            return resumen

        hojas = conn.execute(
            """
            SELECT
                COALESCE(h.expediente_id, 0) AS expediente_key,
                h.expediente_id,
                COALESCE(e.numero_expediente, 'SIN EXPEDIENTE') AS numero_expediente,
                COALESCE(t.nombre, h.procedimiento, 'SIN TRÁMITE') AS tramite,
                COALESCE(SUM(h.importe_neto), 0) AS importe_hojas
            FROM eco_hojas_encargo h
            LEFT JOIN expedientes e ON e.id = h.expediente_id
            LEFT JOIN config_tipos_expediente t ON t.id = e.tipo_expediente_id
            WHERE h.cliente_id = ?
              AND COALESCE(h.activo, 1) = 1
            GROUP BY COALESCE(h.expediente_id, 0), h.expediente_id, e.numero_expediente, t.nombre, h.procedimiento
            """,
            (cliente_id,),
        ).fetchall()

        cobros = conn.execute(
            """
            SELECT
                COALESCE(c.expediente_id, h.expediente_id, 0) AS expediente_key,
                COALESCE(c.expediente_id, h.expediente_id) AS expediente_id,
                COALESCE(e.numero_expediente, 'SIN EXPEDIENTE') AS numero_expediente,
                COALESCE(t.nombre, h.procedimiento, 'SIN TRÁMITE') AS tramite,
                COALESCE(SUM(c.importe), 0) AS importe_cobros
            FROM eco_cobros c
            LEFT JOIN eco_hojas_encargo h ON h.id = c.hoja_encargo_id
            LEFT JOIN expedientes e ON e.id = COALESCE(c.expediente_id, h.expediente_id)
            LEFT JOIN config_tipos_expediente t ON t.id = e.tipo_expediente_id
            WHERE c.cliente_id = ?
              AND COALESCE(c.activo, 1) = 1
            GROUP BY COALESCE(c.expediente_id, h.expediente_id, 0), COALESCE(c.expediente_id, h.expediente_id), e.numero_expediente, t.nombre, h.procedimiento
            """,
            (cliente_id,),
        ).fetchall()

    by_key = {}
    for row in hojas:
        key = row["expediente_key"]
        by_key.setdefault(key, {"expediente_id": row["expediente_id"], "numero_expediente": row["numero_expediente"], "tramite": row["tramite"], "importe_hojas": 0.0, "importe_cobros": 0.0, "deuda": 0.0})
        by_key[key]["importe_hojas"] += float(row["importe_hojas"] or 0)

    for row in cobros:
        key = row["expediente_key"]
        by_key.setdefault(key, {"expediente_id": row["expediente_id"], "numero_expediente": row["numero_expediente"], "tramite": row["tramite"], "importe_hojas": 0.0, "importe_cobros": 0.0, "deuda": 0.0})
        by_key[key]["importe_cobros"] += float(row["importe_cobros"] or 0)

    tramites = []
    for item in by_key.values():
        item["deuda"] = round(float(item["importe_hojas"] or 0) - float(item["importe_cobros"] or 0), 2)
        item["importe_hojas"] = round(float(item["importe_hojas"] or 0), 2)
        item["importe_cobros"] = round(float(item["importe_cobros"] or 0), 2)
        tramites.append(item)

    tramites.sort(key=lambda item: (item.get("numero_expediente") or "", item.get("tramite") or ""))
    resumen["tramites"] = tramites
    resumen["importe_hojas"] = round(sum(item["importe_hojas"] for item in tramites), 2)
    resumen["importe_cobros"] = round(sum(item["importe_cobros"] for item in tramites), 2)
    resumen["deuda_total"] = round(resumen["importe_hojas"] - resumen["importe_cobros"], 2)
    return resumen

def resumen_economico():
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE((SELECT SUM(importe) FROM eco_cobros WHERE activo = 1), 0) AS total_cobros,
                COALESCE((SELECT SUM(total) FROM eco_facturas WHERE activo = 1), 0) AS total_facturas,
                COALESCE((SELECT SUM(importe) FROM eco_gastos WHERE activo = 1), 0) AS total_gastos,
                COALESCE((SELECT COUNT(*) FROM eco_movimientos_importados WHERE activo = 1 AND estado_conciliacion = 'PENDIENTE'), 0) AS movimientos_pendientes
            """
        ).fetchone()
    return _dict(row)

# --- Consultas previas basadas en cobros reales ---

def initialize_economic_consultas_schema(conn):
    conn.execute(
        """
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
            UNIQUE(cobro_id, expediente_id, hoja_encargo_id)
        )
        """
    )


def get_clientes_expediente_for_select(expediente_id):
    with _connect() as conn:
        initialize_expediente_clientes_schema(conn)
        rows = conn.execute(
            """
            SELECT DISTINCT
                c.id,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido,
                c.nie,
                c.pasaporte,
                c.dni,
                COALESCE(ec.rol, 'CLIENTE_PRINCIPAL') AS rol
            FROM clientes c
            JOIN (
                SELECT cliente_id, 'CLIENTE_PRINCIPAL' AS rol
                FROM expedientes
                WHERE id = ?

                UNION

                SELECT cliente_id, rol
                FROM expediente_clientes
                WHERE expediente_id = ?
                  AND activo = 1
            ) ec ON ec.cliente_id = c.id
            WHERE COALESCE(c.activo, 1) = 1
            ORDER BY c.nombre ASC, c.primer_apellido ASC, c.segundo_apellido ASC
            """,
            (int(expediente_id), int(expediente_id)),
        ).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        nombre = " ".join(
            [
                item.get("nombre") or "",
                item.get("primer_apellido") or "",
                item.get("segundo_apellido") or "",
            ]
        ).strip() or f"CLIENTE {item['id']}"
        doc = item.get("nie") or item.get("pasaporte") or item.get("dni") or ""
        rol = item.get("rol") or "RELACIONADO"
        item["display"] = f"{item['id']} - {nombre}" + (f" · {doc}" if doc else "") + f" · {rol}"
        result.append(item)

    return result


def list_consulta_cobros_disponibles(cliente_id):
    with _connect() as conn:
        initialize_economic_consultas_schema(conn)
        rows = conn.execute(
            """
            SELECT cob.*
            FROM eco_cobros cob
            LEFT JOIN eco_consultas_aplicadas app
              ON app.cobro_id = cob.id
             AND app.activo = 1
            WHERE cob.cliente_id = ?
              AND cob.tipo_cobro = 'CONSULTA'
              AND cob.activo = 1
              AND app.id IS NULL
            ORDER BY cob.fecha_cobro DESC, cob.id DESC
            """,
            (int(cliente_id),),
        ).fetchall()

    return [_dict(row) for row in rows]


def aplicar_cobro_consulta_a_hoja(
    cobro_id,
    expediente_id,
    hoja_encargo_id,
    importe_aplicado=None,
    observaciones="",
):
    with _connect() as conn:
        initialize_economic_consultas_schema(conn)

        cobro = _dict(
            conn.execute(
                "SELECT * FROM eco_cobros WHERE id = ? AND activo = 1",
                (int(cobro_id),),
            ).fetchone()
        )

        if not cobro:
            raise ValueError("Cobro de consulta no encontrado")

        if cobro.get("tipo_cobro") != "CONSULTA":
            raise ValueError("El cobro seleccionado no es de tipo CONSULTA")

        already = conn.execute(
            """
            SELECT id
            FROM eco_consultas_aplicadas
            WHERE cobro_id = ?
              AND activo = 1
            LIMIT 1
            """,
            (int(cobro_id),),
        ).fetchone()

        if already:
            raise ValueError("Esta consulta ya está aplicada")

        hoja = _dict(
            conn.execute(
                "SELECT * FROM eco_hojas_encargo WHERE id = ? AND activo = 1",
                (int(hoja_encargo_id),),
            ).fetchone()
        )

        if not hoja:
            raise ValueError("Hoja de encargo no encontrada")

        expediente_id = _int_or_none(expediente_id) or hoja.get("expediente_id")
        importe = _float(
            importe_aplicado
            if importe_aplicado not in (None, "")
            else cobro.get("importe")
        )

        conn.execute(
            """
            INSERT INTO eco_consultas_aplicadas (
                cobro_id,
                cliente_id,
                expediente_id,
                hoja_encargo_id,
                importe_aplicado,
                observaciones,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                int(cobro_id),
                int(cobro["cliente_id"]),
                _int_or_none(expediente_id),
                int(hoja_encargo_id),
                importe,
                _raw(observaciones),
            ),
        )

        nuevo_descuento = float(hoja.get("descuento_consultas_previas") or 0) + importe
        nuevo_neto = max(
            0.0,
            float(hoja.get("importe_bruto") or 0)
            - float(hoja.get("descuento_manual") or 0)
            - nuevo_descuento,
        )

        conn.execute(
            """
            UPDATE eco_hojas_encargo
            SET descuento_consultas_previas = ?,
                importe_neto = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                nuevo_descuento,
                nuevo_neto,
                int(hoja_encargo_id),
            ),
        )

        conn.execute(
            """
            UPDATE eco_cobros
            SET expediente_id = ?,
                hoja_encargo_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _int_or_none(expediente_id),
                int(hoja_encargo_id),
                int(cobro_id),
            ),
        )

        ensure_expediente_cliente(conn, expediente_id, cobro["cliente_id"], rol="PAGADOR", es_principal=0)
        conn.commit()

    registrar_evento(
        "eco_cobros",
        int(cobro_id),
        "CONSULTA_APLICADA",
        "CONSULTA PREVIA APLICADA",
        f"Consulta aplicada a hoja {hoja_encargo_id} por importe {importe:.2f}",
    )

    return True


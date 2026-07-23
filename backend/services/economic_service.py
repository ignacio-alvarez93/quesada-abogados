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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eco_configuracion (
                clave TEXT PRIMARY KEY,
                valor TEXT,
                descripcion TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

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
        _ensure_column(
            conn,
            "eco_facturas",
            "suplidos",
            "REAL NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "eco_facturas",
            "tipo_fiscal",
            "TEXT NOT NULL DEFAULT 'PROVISION'",
        )
        _ensure_column(
            conn,
            "eco_facturas",
            "concepto",
            "TEXT",
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
    """
    Renumera únicamente facturas normales no aprobadas.

    Las facturas aprobadas conservan su número.
    Las rectificativas nunca participan en la serie FRA.
    """
    year = str(year or "").strip()[:4]

    if not year.isdigit():
        raise ValueError(
            "El ejercicio de facturación no es válido"
        )

    prefix = f"FRA-{year}-"

    # --------------------------------------------------------
    # Las facturas normales aprobadas son inmutables.
    # --------------------------------------------------------
    # --------------------------------------------------------
    # Números definitivamente reservados.
    #
    # Nunca se reutilizan:
    # - los números de facturas aprobadas;
    # - los números de facturas inactivas.
    #
    # El índice UNIQUE de SQLite también incluye las filas
    # inactivas, por lo que ignorarlas provoca colisiones.
    # --------------------------------------------------------
    reserved_rows = conn.execute(
        """
        SELECT numero_factura
        FROM eco_facturas
        WHERE numero_factura LIKE ?
          AND (
              COALESCE(exportada_holded, 0) = 1
              OR COALESCE(activo, 1) = 0
          )
          AND factura_rectificada_id IS NULL
          AND UPPER(
                COALESCE(tipo_factura, 'NORMAL')
              ) != 'RECTIFICATIVA'
        """,
        (prefix + "%",),
    ).fetchall()

    max_reserved_sequence = 0
    reserved_numbers = set()

    for row in reserved_rows:
        number = str(
            row["numero_factura"] or ""
        ).strip()

        if not number:
            continue

        reserved_numbers.add(number)

        try:
            sequence = int(
                number.rsplit("-", 1)[-1]
            )
        except (TypeError, ValueError):
            continue

        max_reserved_sequence = max(
            max_reserved_sequence,
            sequence,
        )

    # --------------------------------------------------------
    # Solo se renumeran las facturas normales no aprobadas.
    # --------------------------------------------------------
    pending_rows = conn.execute(
        """
        SELECT
            id,
            numero_factura,
            fecha_factura
        FROM eco_facturas
        WHERE COALESCE(activo, 1) = 1
          AND COALESCE(exportada_holded, 0) = 0
          AND substr(fecha_factura, 1, 4) = ?
          AND factura_rectificada_id IS NULL
          AND UPPER(
                COALESCE(tipo_factura, 'NORMAL')
              ) != 'RECTIFICATIVA'
        ORDER BY
            fecha_factura ASC,
            id ASC
        """,
        (year,),
    ).fetchall()

    assignments = []
    sequence = max_reserved_sequence + 1

    for row in pending_rows:
        candidate = (
            f"{prefix}{sequence:04d}"
        )

        while candidate in reserved_numbers:
            sequence += 1
            candidate = (
                f"{prefix}{sequence:04d}"
            )

        assignments.append(
            (
                int(row["id"]),
                candidate,
            )
        )

        reserved_numbers.add(candidate)
        sequence += 1

    # Números temporales para no colisionar con UNIQUE.
    for invoice_id, final_number in assignments:
        conn.execute(
            """
            UPDATE eco_facturas
            SET numero_factura = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND COALESCE(exportada_holded, 0) = 0
              AND factura_rectificada_id IS NULL
              AND UPPER(
                    COALESCE(tipo_factura, 'NORMAL')
                  ) != 'RECTIFICATIVA'
            """,
            (
                f"TMP-FRA-{year}-{invoice_id}",
                invoice_id,
            ),
        )

    for invoice_id, final_number in assignments:
        conn.execute(
            """
            UPDATE eco_facturas
            SET numero_factura = ?,
                tipo_factura = 'NORMAL',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND COALESCE(exportada_holded, 0) = 0
              AND factura_rectificada_id IS NULL
              AND UPPER(
                    COALESCE(tipo_factura, 'NORMAL')
                  ) != 'RECTIFICATIVA'
            """,
            (
                final_number,
                invoice_id,
            ),
        )

    return [
        {
            "factura_id": invoice_id,
            "numero_factura": number,
        }
        for invoice_id, number in assignments
    ]



INVOICE_CLOSURE_SETTING_KEY = "invoice_closed_until"


def get_economic_setting(key, default=None):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT valor
            FROM eco_configuracion
            WHERE clave = ?
            """,
            (_text(key),),
        ).fetchone()

    if not row:
        return default

    value = row["valor"]

    if value is None or str(value).strip() == "":
        return default

    return value


def set_economic_setting(key, value, description=None):
    key = _text(key)

    if not key:
        raise ValueError("Clave de configuración no válida")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO eco_configuracion (
                clave,
                valor,
                descripcion,
                updated_at
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(clave) DO UPDATE SET
                valor = excluded.valor,
                descripcion = COALESCE(
                    excluded.descripcion,
                    eco_configuracion.descripcion
                ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key,
                _raw(value),
                _raw(description),
            ),
        )
        conn.commit()

    return value


def get_invoice_closure_date():
    """
    La fecha de cierre no se configura manualmente.

    Se obtiene de la factura activa con fecha más reciente que ya
    haya sido exportada a Holded.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT MAX(fecha_factura) AS closure_date
            FROM eco_facturas
            WHERE COALESCE(activo, 1) = 1
              AND COALESCE(exportada_holded, 0) = 1
            """
        ).fetchone()

    if not row:
        return None

    return row["closure_date"] or None

def set_invoice_closure_date(value):
    new_date = _date(value)

    if not new_date:
        raise ValueError("Indica una fecha de cierre válida")

    current_date = get_invoice_closure_date()

    if current_date and new_date < current_date:
        raise ValueError(
            "La fecha de cierre no puede retroceder. "
            f"El periodo ya está cerrado hasta {current_date}"
        )

    set_economic_setting(
        INVOICE_CLOSURE_SETTING_KEY,
        new_date,
        (
            "Último día cerrado para creación, modificación "
            "y eliminación de facturas"
        ),
    )

    registrar_evento(
        "eco_configuracion",
        0,
        "MODIFICACION",
        "CIERRE DE FACTURACION",
        f"Facturación cerrada hasta {new_date}",
    )

    return new_date


def is_invoice_date_closed(value):
    closure_date = get_invoice_closure_date()

    if not closure_date:
        return False

    invoice_date = _date(value)

    if not invoice_date:
        return False

    # El día de la última factura aprobada sigue abierto.
    # Solo quedan cerradas las fechas anteriores.
    return invoice_date < closure_date


def assert_invoice_date_open(value, action="modificar"):
    closure_date = get_invoice_closure_date()

    if not closure_date:
        return

    invoice_date = _date(value)

    if invoice_date and invoice_date < closure_date:
        raise ValueError(
            f"No se puede {action} una factura con fecha "
            f"{invoice_date}. Las fechas anteriores a "
            f"{closure_date} están cerradas. Se permite "
            f"seguir facturando el día {closure_date}"
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

    divisor = (
        1
        + (iva_porcentaje / 100)
        - (irpf_porcentaje / 100)
    )

    if divisor <= 0:
        raise ValueError(
            "La combinación de IVA e IRPF no permite calcular la factura"
        )

    base = round(total / divisor, 2)
    iva = round(base * iva_porcentaje / 100, 2)
    irpf = round(base * irpf_porcentaje / 100, 2)

    diferencia = round(
        total - (base + iva - irpf),
        2,
    )

    if diferencia:
        if iva_porcentaje:
            # El céntimo residual se ajusta en la cuota de IVA.
            iva = round(iva + diferencia, 2)

        elif irpf_porcentaje:
            # El IRPF se resta del total.
            irpf = round(irpf - diferencia, 2)

        else:
            base = round(base + diferencia, 2)

    # Un porcentaje del 0 % nunca genera importe fiscal.
    if iva_porcentaje == 0:
        iva = 0.0

    if irpf_porcentaje == 0:
        irpf = 0.0

    calculated_total = round(
        base + iva - irpf,
        2,
    )

    if calculated_total != total:
        raise ValueError(
            "No se pudo cuadrar el cálculo fiscal con el total cobrado"
        )

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
    assert_invoice_date_open(
        fecha,
        action="crear o recalcular",
    )
    year = fecha[:4]
    importe = float(cobro.get("importe") or 0)

    tipo_fiscal = str(
        cobro.get("tipo_fiscal") or "PROVISION"
    ).strip().upper()

    if tipo_fiscal == "SUPLIDO":
        fiscal = {
            "base_imponible": 0.0,
            "iva": 0.0,
            "irpf": 0.0,
            "suplidos": round(importe, 2),
            "total": round(importe, 2),
        }
    else:
        fiscal = _calculate_invoice_from_total(
            importe,
            cobro.get("iva_porcentaje"),
            cobro.get("irpf_porcentaje"),
        )
        fiscal["suplidos"] = 0.0

    factura_id = cobro.get("factura_id")

    if factura_id:
        existing_invoice = _dict(
            conn.execute(
                """
                SELECT id, numero_factura, exportada_holded
                FROM eco_facturas
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (int(factura_id),),
            ).fetchone()
        )

        if existing_invoice and int(
            existing_invoice.get("exportada_holded") or 0
        ):
            raise ValueError(
                "La factura está aprobada y permanece congelada"
            )

        existing_invoice_full = _dict(
            conn.execute(
                """
                SELECT fecha_factura
                FROM eco_facturas
                WHERE id = ?
                """,
                (int(factura_id),),
            ).fetchone()
        )

        if existing_invoice_full:
            assert_invoice_date_open(
                existing_invoice_full.get("fecha_factura"),
                action="modificar",
            )

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
                suplidos = ?,
                total = ?,
                tipo_fiscal = ?,
                concepto = ?,
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
                fiscal["suplidos"],
                fiscal["total"],
                tipo_fiscal,
                _text(cobro.get("concepto")),
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
            suplidos,
            total,
            tipo_fiscal,
            concepto,
            estado,
            exportada_holded,
            documento_ruta,
            observaciones,
            activo
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, 1
        )
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
            fiscal["suplidos"],
            fiscal["total"],
            tipo_fiscal,
            _text(cobro.get("concepto")),
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



def next_numero_rectificativa(
    fecha_factura,
    conn=None,
):
    """
    Devuelve el siguiente número de la serie rectificativa.

    La secuencia:
    - es independiente de FRA;
    - se calcula por ejercicio;
    - incluye registros activos, inactivos, pendientes y exportados;
    - nunca reutiliza un número previamente asignado;
    - puede utilizar la conexión transaccional de creación.
    """
    fecha = _date(fecha_factura)
    year = fecha[:4]
    prefix = f"R-{year}-"

    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        rows = conn.execute(
            """
            SELECT numero_factura
            FROM eco_facturas
            WHERE numero_factura LIKE ?
            """,
            (prefix + "%",),
        ).fetchall()

        max_sequence = 0

        for row in rows:
            raw_number = str(
                row["numero_factura"] or ""
            ).strip()

            if not raw_number.startswith(prefix):
                continue

            raw_sequence = raw_number[len(prefix):]

            if not raw_sequence.isdigit():
                continue

            max_sequence = max(
                max_sequence,
                int(raw_sequence),
            )

        return (
            f"{prefix}{max_sequence + 1:04d}"
        )

    finally:
        if owns_connection:
            conn.close()


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
    descuento_consultas = 0.0
    importe_neto = max(
        0,
        importe_bruto - descuento_manual,
    )
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
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


def get_hoja_encargo(hoja_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM eco_hojas_encargo
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (int(hoja_id),),
        ).fetchone()

    return _dict(row) if row else None


def update_hoja_encargo(hoja_id, data):
    hoja_id = int(hoja_id)

    with _connect() as conn:
        current = conn.execute(
            """
            SELECT *
            FROM eco_hojas_encargo
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (hoja_id,),
        ).fetchone()

        if not current:
            raise ValueError("Hoja de encargo no encontrada")

        current = _dict(current)

        cliente_id = int(
            data.get("cliente_id")
            or current.get("cliente_id")
        )

        expediente_id = _int_or_none(
            data.get("expediente_id")
        )

        importe_bruto = _float(
            data.get("importe_bruto")
        )
        descuento_manual = _float(
            data.get("descuento_manual")
        )
        descuento_consultas = 0.0

        importe_neto = max(
            0.0,
            importe_bruto
            - descuento_manual,
        )

        numero_hoja = (
            _text(data.get("numero_hoja"))
            or current.get("numero_hoja")
            or next_numero_hoja(data.get("fecha_firma"))
        )

        conn.execute(
            """
            UPDATE eco_hojas_encargo
            SET
                expediente_id = ?,
                cliente_id = ?,
                numero_hoja = ?,
                fecha_firma = ?,
                procedimiento = ?,
                importe_bruto = ?,
                descuento_manual = ?,
                descuento_consultas_previas = ?,
                importe_neto = ?,
                forma_pago_pactada = ?,
                numero_plazos = ?,
                fecha_maxima_pago = ?,
                documento_ruta = ?,
                estado = ?,
                observaciones = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
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
                _text(
                    data.get("estado")
                    or "PENDIENTE FIRMA"
                ),
                _raw(data.get("observaciones")),
                hoja_id,
            ),
        )

        ensure_expediente_cliente(
            conn,
            expediente_id,
            cliente_id,
            rol="PAGADOR",
            es_principal=0,
        )

        conn.commit()

    registrar_evento(
        "eco_hojas_encargo",
        hoja_id,
        "ACTUALIZACION",
        "HOJA DE ENCARGO ACTUALIZADA",
        f"Neto: {importe_neto:.2f}",
    )

    return True


def list_hojas_encargo(active_only=True):
    """
    Devuelve las hojas de encargo con contexto económico agregado.

    Los LEFT JOIN preservan hojas históricas aunque el cliente o el
    expediente original ya no estén disponibles.
    """
    sql = """
        SELECT
            h.*,
            c.nombre,
            c.primer_apellido,
            c.segundo_apellido,
            e.numero_expediente,

            (
                SELECT COUNT(*)
                FROM eco_cobros cob
                WHERE cob.hoja_encargo_id = h.id
                  AND COALESCE(cob.activo, 1) = 1
            ) AS cobros_count,

            (
                SELECT COUNT(*)
                FROM eco_facturas fac
                WHERE fac.hoja_encargo_id = h.id
                  AND COALESCE(fac.activo, 1) = 1
            ) AS facturas_count,

            COALESCE(
                (
                    SELECT SUM(cob.importe)
                    FROM eco_cobros cob
                    WHERE cob.hoja_encargo_id = h.id
                      AND COALESCE(cob.activo, 1) = 1
                ),
                0
            ) AS total_cobrado

        FROM eco_hojas_encargo h

        LEFT JOIN clientes c
          ON c.id = h.cliente_id

        LEFT JOIN expedientes e
          ON e.id = h.expediente_id
    """

    if active_only:
        sql += " WHERE COALESCE(h.activo, 1) = 1"

    sql += " ORDER BY h.created_at DESC, h.id DESC"

    with _connect() as conn:
        rows = conn.execute(sql).fetchall()

    result = []

    for row in rows:
        item = _dict(row)

        client_name = " ".join(
            part
            for part in [
                str(item.get("nombre") or "").strip(),
                str(item.get("primer_apellido") or "").strip(),
                str(item.get("segundo_apellido") or "").strip(),
            ]
            if part
        )

        if not client_name:
            client_name = (
                f"Cliente no disponible "
                f"(ID {item.get('cliente_id') or '-'})"
            )

        try:
            importe_neto = float(
                item.get("importe_neto") or 0
            )
        except (TypeError, ValueError):
            importe_neto = 0.0

        try:
            total_cobrado = float(
                item.get("total_cobrado") or 0
            )
        except (TypeError, ValueError):
            total_cobrado = 0.0

        item["cliente_nombre_completo"] = client_name
        item["total_cobrado"] = round(total_cobrado, 2)
        item["importe_pendiente"] = round(
            importe_neto - total_cobrado,
            2,
        )

        result.append(item)

    return result


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
    cliente_id = _int_or_none(
        data.get("cliente_id")
    )
    expediente_id = _int_or_none(data.get("expediente_id"))
    hoja_id = _int_or_none(data.get("hoja_encargo_id"))

    if not cliente_id:
        raise ValueError(
            "El cobro debe tener un cliente válido"
        )
    cliente_id = int(data.get("cliente_id"))

    if (
        tipo_cobro == "TASA"
        and not expediente_id
    ):
        raise ValueError(
            "Los cobros de tipo TASA deben estar "
            "asociados a un expediente"
        )

    if (
        tipo_cobro not in {
            "CONSULTA",
            "SUPLIDO_ADELANTADO",
            "TASA",
        }
        and tipo_fiscal != "SUPLIDO"
        and not hoja_id
    ):
        raise ValueError(
            "Los cobros ordinarios de expediente "
            "deben estar asociados a una hoja "
            "de encargo"
        )

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

    cliente_id = _int_or_none(
        data.get("cliente_id")
    )
    expediente_id = _int_or_none(
        data.get("expediente_id")
    )
    hoja_id = _int_or_none(
        data.get("hoja_encargo_id")
    )

    if not cliente_id:
        raise ValueError(
            "El cobro debe tener un cliente válido"
        )

    if (
        tipo_cobro == "TASA"
        and not expediente_id
    ):
        raise ValueError(
            "Los cobros de tipo TASA deben estar "
            "asociados a un expediente"
        )

    if (
        tipo_cobro not in {
            "CONSULTA",
            "SUPLIDO_ADELANTADO",
            "TASA",
        }
        and tipo_fiscal != "SUPLIDO"
        and not hoja_id
    ):
        raise ValueError(
            "Los cobros ordinarios de expediente "
            "deben estar asociados a una hoja "
            "de encargo"
        )

    with _connect() as conn:
        locked_invoice = _dict(
            conn.execute(
                """
                SELECT
                    f.id,
                    f.numero_factura,
                    f.estado,
                    f.exportada_holded
                FROM eco_cobros cob
                JOIN eco_facturas f
                  ON f.id = cob.factura_id
                WHERE cob.id = ?
                  AND COALESCE(cob.activo, 1) = 1
                  AND COALESCE(f.activo, 1) = 1
                  AND (
                      COALESCE(f.exportada_holded, 0) = 1
                      OR UPPER(
                          COALESCE(f.estado, '')
                      ) IN (
                          'APROBADA',
                          'ANULADA'
                      )
                  )
                """,
                (cobro_id,),
            ).fetchone()
        )

        if locked_invoice:
            estado_factura = _text(
                locked_invoice.get("estado")
                or ""
            ).upper()

            if int(
                locked_invoice.get(
                    "exportada_holded"
                )
                or 0
            ) or estado_factura == "APROBADA":
                raise ValueError(
                    "El cobro está vinculado a la factura "
                    f"{locked_invoice.get('numero_factura') or ''}, "
                    "que ya está aprobada y no puede modificarse"
                )

            raise ValueError(
                "El cobro está vinculado a la factura "
                f"{locked_invoice.get('numero_factura') or ''}, "
                "que está anulada y no puede modificarse"
            )

        linked_invoice = _dict(
            conn.execute(
                """
                SELECT f.id,
                       f.numero_factura,
                       f.fecha_factura
                FROM eco_cobros cob
                JOIN eco_facturas f
                  ON f.id = cob.factura_id
                WHERE cob.id = ?
                  AND COALESCE(cob.activo, 1) = 1
                  AND COALESCE(f.activo, 1) = 1
                """,
                (cobro_id,),
            ).fetchone()
        )

        if linked_invoice:
            assert_invoice_date_open(
                linked_invoice.get("fecha_factura"),
                action="modificar",
            )

        new_invoice_date = _date(data.get("fecha_cobro"))

        if linked_invoice and new_invoice_date:
            assert_invoice_date_open(
                new_invoice_date,
                action="mover",
            )

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
            SET cliente_id = ?,
                fecha_cobro = ?,
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
                cliente_id,
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

        ensure_expediente_cliente(
            conn,
            expediente_id,
            cliente_id,
            rol="PAGADOR",
            es_principal=0,
        )

        if linked_invoice:
            conn.execute(
                """
                UPDATE eco_facturas
                SET cliente_id = ?,
                    expediente_id = ?,
                    hoja_encargo_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (
                    cliente_id,
                    expediente_id,
                    hoja_id,
                    linked_invoice["id"],
                ),
            )

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


def get_cobro(cobro_id):
    sql = """
        SELECT cob.*,
               c.nombre,
               c.primer_apellido,
               c.segundo_apellido,
               e.numero_expediente,
               h.numero_hoja,
               f.numero_factura,
               f.estado AS factura_estado,
               COALESCE(
                   f.exportada_holded,
                   0
               ) AS factura_exportada_holded
        FROM eco_cobros cob
        JOIN clientes c
          ON c.id = cob.cliente_id
        LEFT JOIN expedientes e
          ON e.id = cob.expediente_id
        LEFT JOIN eco_hojas_encargo h
          ON h.id = cob.hoja_encargo_id
        LEFT JOIN eco_facturas f
          ON f.id = cob.factura_id
        WHERE cob.id = ?
          AND COALESCE(cob.activo, 1) = 1
    """

    with _connect() as conn:
        return _dict(
            conn.execute(sql, (int(cobro_id),)).fetchone()
        )


RECTIFICATION_CAUSE_CODES = {
    "ERROR_IMPORTE",
    "ERROR_DATOS",
    "DEVOLUCION",
    "DESCUENTO_POSTERIOR",
    "ANULACION_OPERACION",
    "OTRA",
}


def get_rectification_balance(factura_original_id):
    factura_original_id = int(factura_original_id)

    with _connect() as conn:
        original = _dict(
            conn.execute(
                """
                SELECT *
                FROM eco_facturas
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (factura_original_id,),
            ).fetchone()
        )

        if not original:
            raise ValueError("Factura original no encontrada")

        totals = _dict(
            conn.execute(
                """
                SELECT
                    COALESCE(SUM(base_imponible), 0) AS rect_base,
                    COALESCE(SUM(iva), 0) AS rect_iva,
                    COALESCE(SUM(irpf), 0) AS rect_irpf,
                    COALESCE(SUM(suplidos), 0) AS rect_suplidos,
                    COALESCE(SUM(total), 0) AS rect_total
                FROM eco_facturas
                WHERE factura_rectificada_id = ?
                  AND COALESCE(activo, 1) = 1
                  AND UPPER(
                        COALESCE(tipo_factura, 'NORMAL')
                      ) = 'RECTIFICATIVA'
                """,
                (factura_original_id,),
            ).fetchone()
        ) or {}

    return {
        "original": original,
        "rectificado": {
            "base_imponible": round(
                _float(totals.get("rect_base")),
                2,
            ),
            "iva": round(
                _float(totals.get("rect_iva")),
                2,
            ),
            "irpf": round(
                _float(totals.get("rect_irpf")),
                2,
            ),
            "suplidos": round(
                _float(totals.get("rect_suplidos")),
                2,
            ),
            "total": round(
                _float(totals.get("rect_total")),
                2,
            ),
        },
    }


def create_factura_rectificativa(
    factura_original_id,
    data,
):
    factura_original_id = int(factura_original_id)
    data = dict(data or {})

    fecha = _date(data.get("fecha_factura"))
    assert_invoice_date_open(
        fecha,
        action="crear factura rectificativa",
    )

    codigo_causa = _text(
        data.get("codigo_causa_rectificacion")
        or "OTRA"
    ).upper()

    causa = _text(data.get("causa_rectificacion"))

    if codigo_causa not in RECTIFICATION_CAUSE_CODES:
        raise ValueError(
            "La causa seleccionada no es válida"
        )

    if not causa:
        raise ValueError(
            "Debes indicar el motivo de la rectificación"
        )

    base = round(
        _float(data.get("base_imponible")),
        2,
    )
    iva = round(
        _float(data.get("iva")),
        2,
    )
    irpf = round(
        _float(data.get("irpf")),
        2,
    )
    suplidos = round(
        _float(data.get("suplidos")),
        2,
    )

    total = round(
        base + iva - irpf + suplidos,
        2,
    )

    if (
        base == 0
        and iva == 0
        and irpf == 0
        and suplidos == 0
    ):
        raise ValueError(
            "La rectificativa no puede tener todos "
            "los importes a cero"
        )

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        original = _dict(
            conn.execute(
                """
                SELECT *
                FROM eco_facturas
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (factura_original_id,),
            ).fetchone()
        )

        if not original:
            raise ValueError(
                "Factura original no encontrada"
            )

        if not int(
            original.get("exportada_holded") or 0
        ):
            raise ValueError(
                "La factura todavía no está aprobada. "
                "Debes modificarla directamente."
            )

        if (
            _text(
                original.get("tipo_factura")
                or "NORMAL"
            ).upper()
            == "RECTIFICATIVA"
        ):
            raise ValueError(
                "No se puede generar desde aquí una "
                "rectificativa de otra rectificativa"
            )

        accumulated = _dict(
            conn.execute(
                """
                SELECT
                    COALESCE(SUM(base_imponible), 0) AS base,
                    COALESCE(SUM(iva), 0) AS iva,
                    COALESCE(SUM(irpf), 0) AS irpf,
                    COALESCE(SUM(suplidos), 0) AS suplidos,
                    COALESCE(SUM(total), 0) AS total
                FROM eco_facturas
                WHERE factura_rectificada_id = ?
                  AND COALESCE(activo, 1) = 1
                  AND UPPER(
                        COALESCE(tipo_factura, 'NORMAL')
                      ) = 'RECTIFICATIVA'
                """,
                (factura_original_id,),
            ).fetchone()
        ) or {}

        resulting_base = round(
            _float(original.get("base_imponible"))
            + _float(accumulated.get("base"))
            + base,
            2,
        )
        resulting_iva = round(
            _float(original.get("iva"))
            + _float(accumulated.get("iva"))
            + iva,
            2,
        )
        resulting_irpf = round(
            _float(original.get("irpf"))
            + _float(accumulated.get("irpf"))
            + irpf,
            2,
        )
        resulting_suplidos = round(
            _float(original.get("suplidos"))
            + _float(accumulated.get("suplidos"))
            + suplidos,
            2,
        )
        resulting_total = round(
            _float(original.get("total"))
            + _float(accumulated.get("total"))
            + total,
            2,
        )

        if resulting_base < -0.01:
            raise ValueError(
                "La rectificación supera la base pendiente"
            )

        if resulting_iva < -0.01:
            raise ValueError(
                "La rectificación supera el IVA pendiente"
            )

        if resulting_irpf < -0.01:
            raise ValueError(
                "La rectificación supera el IRPF pendiente"
            )

        if resulting_suplidos < -0.01:
            raise ValueError(
                "La rectificación supera los suplidos pendientes"
            )

        if resulting_total < -0.01:
            raise ValueError(
                "La rectificación supera el total de "
                "la factura original"
            )

        numero = next_numero_rectificativa(
            fecha,
            conn=conn,
        )

        concepto = _text(
            data.get("concepto")
        ) or (
            f"Rectificación de "
            f"{original.get('numero_factura')}: {causa}"
        )

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
                suplidos,
                total,
                tipo_fiscal,
                concepto,
                tipo_factura,
                factura_rectificada_id,
                metodo_rectificacion,
                codigo_causa_rectificacion,
                causa_rectificacion,
                estado,
                exportada_holded,
                documento_ruta,
                observaciones,
                activo
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                'RECTIFICATIVA',
                ?,
                'DIFERENCIAS',
                ?,
                ?,
                'EMITIDA',
                0,
                NULL,
                ?,
                1
            )
            """,
            (
                numero,
                fecha,
                int(original["cliente_id"]),
                original.get("expediente_id"),
                original.get("hoja_encargo_id"),
                base,
                iva,
                irpf,
                suplidos,
                total,
                _text(
                    original.get("tipo_fiscal")
                    or "PROVISION"
                ).upper(),
                concepto,
                factura_original_id,
                codigo_causa,
                causa,
                _text(data.get("observaciones")),
            ),
        )

        rectificativa_id = int(cur.lastrowid)
        conn.commit()

    registrar_evento(
        "eco_facturas",
        rectificativa_id,
        "RECTIFICACION",
        "FACTURA RECTIFICATIVA CREADA",
        (
            f"{numero} rectifica "
            f"{original.get('numero_factura')} · "
            f"{total:.2f} € · {causa}"
        ),
    )

    registrar_evento(
        "eco_facturas",
        factura_original_id,
        "RECTIFICADA",
        "FACTURA RECTIFICADA",
        (
            f"{numero} · {total:.2f} € · {causa}"
        ),
    )

    return rectificativa_id


def get_factura(factura_id):
    sql = """
        SELECT f.*,
               c.nombre,
               c.primer_apellido,
               c.segundo_apellido,
               e.numero_expediente,
               h.numero_hoja,
               fc.cobro_id,
               cob.numero_cobro,
               original.numero_factura
                   AS numero_factura_rectificada
        FROM eco_facturas f
        JOIN clientes c
          ON c.id = f.cliente_id
        LEFT JOIN expedientes e
          ON e.id = f.expediente_id
        LEFT JOIN eco_hojas_encargo h
          ON h.id = f.hoja_encargo_id
        LEFT JOIN eco_factura_cobros fc
          ON fc.id = (
              SELECT fc2.id
              FROM eco_factura_cobros fc2
              WHERE fc2.factura_id = f.id
              ORDER BY fc2.id
              LIMIT 1
          )
        LEFT JOIN eco_cobros cob
          ON cob.id = fc.cobro_id
        LEFT JOIN eco_facturas original
          ON original.id = f.factura_rectificada_id
        WHERE f.id = ?
          AND COALESCE(f.activo, 1) = 1
    """

    with _connect() as conn:
        return _dict(
            conn.execute(sql, (int(factura_id),)).fetchone()
        )


def approve_factura(factura_id):
    """
    Aprueba y congela definitivamente una factura.

    Compatibilidad temporal:
    - exportada_holded = 1 representa factura aprobada;
    - fecha_exportacion representa fecha de aprobación.

    Una factura aprobada:
    - conserva definitivamente su numeración;
    - no puede editarse ni eliminarse;
    - solo puede corregirse mediante rectificativa.

    Regla temporal:
    - se permite aprobar más facturas en la misma fecha;
    - solo se bloquean fechas estrictamente anteriores.
    """
    factura_id = int(factura_id)

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        factura = _dict(
            conn.execute(
                """
                SELECT *
                FROM eco_facturas
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (factura_id,),
            ).fetchone()
        )

        if not factura:
            raise ValueError("Factura no encontrada")

        if int(factura.get("exportada_holded") or 0):
            raise ValueError(
                "La factura ya está aprobada y congelada"
            )

        numero = _text(
            factura.get("numero_factura")
        )
        fecha = _text(
            factura.get("fecha_factura")
        )
        cliente_id = factura.get("cliente_id")

        if not numero:
            raise ValueError(
                "La factura no tiene numeración"
            )

        if not fecha:
            raise ValueError(
                "La factura no tiene fecha"
            )

        if not cliente_id:
            raise ValueError(
                "La factura no tiene cliente"
            )

        # Regla centralizada:
        # la misma fecha permanece abierta y únicamente
        # quedan bloqueadas las fechas anteriores.
        assert_invoice_date_open(
            fecha,
            action="aprobar",
        )

        duplicate = conn.execute(
            """
            SELECT id
            FROM eco_facturas
            WHERE numero_factura = ?
              AND id != ?
              AND COALESCE(activo, 1) = 1
            LIMIT 1
            """,
            (
                numero,
                factura_id,
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "Ya existe otra factura activa "
                f"con el número {numero}"
            )

        base = round(
            _float(factura.get("base_imponible")),
            2,
        )
        iva = round(
            _float(factura.get("iva")),
            2,
        )
        irpf = round(
            _float(factura.get("irpf")),
            2,
        )
        suplidos = round(
            _float(factura.get("suplidos")),
            2,
        )
        stored_total = round(
            _float(factura.get("total")),
            2,
        )
        calculated_total = round(
            base + iva - irpf + suplidos,
            2,
        )

        if abs(stored_total - calculated_total) > 0.01:
            raise ValueError(
                "Los importes de la factura no cuadran: "
                f"total registrado {stored_total:.2f} €, "
                f"total calculado {calculated_total:.2f} €"
            )

        cursor = conn.execute(
            """
            UPDATE eco_facturas
            SET exportada_holded = 1,
                estado = 'APROBADA',
                fecha_exportacion = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND COALESCE(exportada_holded, 0) = 0
              AND COALESCE(activo, 1) = 1
            """,
            (factura_id,),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                "No se pudo aprobar la factura"
            )

        conn.commit()

    registrar_evento(
        "eco_facturas",
        factura_id,
        "APROBACION",
        "FACTURA APROBADA Y CONGELADA",
        (
            f"{numero} · numeración y contenido "
            "congelados"
        ),
    )

    return factura_id


def approve_all_pending_facturas():
    """
    Aprueba y congela conjuntamente todas las facturas normales
    activas que todavía estén pendientes.

    Esta operación sirve para cerrar la serie completa y evita
    congelaciones parciales. Conserva la numeración existente.

    Se excluyen:
    - facturas anuladas;
    - facturas inactivas;
    - facturas rectificativas;
    - facturas ya aprobadas.
    """
    approved = []

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        facturas = [
            _dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM eco_facturas
                WHERE COALESCE(activo, 1) = 1
                  AND COALESCE(exportada_holded, 0) = 0
                  AND UPPER(
                        COALESCE(estado, 'EMITIDA')
                      ) != 'ANULADA'
                  AND factura_rectificada_id IS NULL
                  AND UPPER(
                        COALESCE(tipo_factura, 'NORMAL')
                      ) != 'RECTIFICATIVA'
                ORDER BY
                    fecha_factura ASC,
                    id ASC
                """
            ).fetchall()
        ]

        if not facturas:
            raise ValueError(
                "No hay facturas pendientes de aprobación"
            )

        seen_numbers = set()

        for factura in facturas:
            factura_id = int(factura["id"])
            numero = _text(
                factura.get("numero_factura")
            )
            fecha = _text(
                factura.get("fecha_factura")
            )
            cliente_id = factura.get("cliente_id")

            if not numero:
                raise ValueError(
                    f"La factura #{factura_id} no tiene numeración"
                )

            if numero in seen_numbers:
                raise ValueError(
                    "La operación contiene numeración duplicada: "
                    f"{numero}"
                )

            seen_numbers.add(numero)

            if not fecha:
                raise ValueError(
                    f"La factura {numero} no tiene fecha"
                )

            if not cliente_id:
                raise ValueError(
                    f"La factura {numero} no tiene cliente"
                )

            base = round(
                _float(
                    factura.get("base_imponible")
                ),
                2,
            )
            iva = round(
                _float(factura.get("iva")),
                2,
            )
            irpf = round(
                _float(factura.get("irpf")),
                2,
            )
            suplidos = round(
                _float(factura.get("suplidos")),
                2,
            )
            stored_total = round(
                _float(factura.get("total")),
                2,
            )
            calculated_total = round(
                base + iva - irpf + suplidos,
                2,
            )

            if (
                abs(
                    stored_total
                    - calculated_total
                )
                > 0.01
            ):
                raise ValueError(
                    f"La factura {numero} no cuadra: "
                    f"total guardado {stored_total:.2f} €, "
                    f"total calculado {calculated_total:.2f} €"
                )

            duplicate = conn.execute(
                """
                SELECT id
                FROM eco_facturas
                WHERE numero_factura = ?
                  AND id != ?
                LIMIT 1
                """,
                (
                    numero,
                    factura_id,
                ),
            ).fetchone()

            if duplicate:
                raise ValueError(
                    "Ya existe otra factura con el número "
                    f"{numero}"
                )

        for factura in facturas:
            factura_id = int(factura["id"])

            conn.execute(
                """
                UPDATE eco_facturas
                SET estado = 'APROBADA',
                    exportada_holded = 1,
                    fecha_exportacion = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                  AND COALESCE(exportada_holded, 0) = 0
                """,
                (factura_id,),
            )

            approved.append(
                {
                    "id": factura_id,
                    "numero_factura": factura.get(
                        "numero_factura"
                    ),
                    "fecha_factura": factura.get(
                        "fecha_factura"
                    ),
                }
            )

        conn.commit()

    for factura in approved:
        registrar_evento(
            "eco_facturas",
            factura["id"],
            "APROBACION",
            "FACTURA APROBADA",
            (
                f"{factura['numero_factura']} · "
                "aprobación masiva de la serie"
            ),
        )

    return {
        "count": len(approved),
        "facturas": approved,
    }

def mark_factura_exportada_holded(factura_id):
    """
    Alias temporal para compatibilidad con código anterior.
    """
    return approve_factura(factura_id)


def delete_factura(factura_id):
    factura_id = int(factura_id)

    with _connect() as conn:
        factura = _dict(
            conn.execute(
                """
                SELECT *
                FROM eco_facturas
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (factura_id,),
            ).fetchone()
        )

        if not factura:
            raise ValueError("Factura no encontrada")

        if int(factura.get("exportada_holded") or 0):
            raise ValueError(
                "La factura está aprobada y congelada "
                "y no puede eliminarse"
            )

        assert_invoice_date_open(
            factura.get("fecha_factura"),
            action="eliminar",
        )

        cobro_rows = conn.execute(
            """
            SELECT cobro_id
            FROM eco_factura_cobros
            WHERE factura_id = ?
            """,
            (factura_id,),
        ).fetchall()

        cobro_ids = [
            int(row["cobro_id"])
            for row in cobro_rows
            if row["cobro_id"] is not None
        ]

        conn.execute(
            """
            DELETE FROM eco_factura_cobros
            WHERE factura_id = ?
            """,
            (factura_id,),
        )

        if cobro_ids:
            placeholders = ", ".join("?" for _ in cobro_ids)

            conn.execute(
                f"""
                UPDATE eco_cobros
                SET factura_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                  AND factura_id = ?
                """,
                (*cobro_ids, factura_id),
            )

        conn.execute(
            """
            UPDATE eco_facturas
            SET activo = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (factura_id,),
        )

        year = str(
            factura.get("fecha_factura")
            or datetime.today().strftime("%Y")
        )[:4]

        renumerar_facturas_por_year(conn, year)
        conn.commit()

    registrar_evento(
        "eco_facturas",
        factura_id,
        "ELIMINACION",
        "FACTURA ELIMINADA",
        (
            f"{factura.get('numero_factura') or factura_id} · "
            "cobro conservado y desvinculado"
        ),
    )

    return factura_id


def create_factura(data, cobro_ids=None):
    fecha = _date(data.get("fecha_factura"))
    assert_invoice_date_open(
        fecha,
        action="crear",
    )
    year = fecha[:4] if fecha else datetime.today().strftime("%Y")
    numero = _text(data.get("numero_factura")) or next_numero_factura(fecha)
    base = _float(data.get("base_imponible"))
    iva = _float(data.get("iva"))
    irpf = _float(data.get("irpf"))
    suplidos = _float(data.get("suplidos"))
    raw_tipo_fiscal = _text(
        data.get("tipo_fiscal") or "PROVISION"
    ).strip().upper()
    tipo_fiscal = (
        "SUPLIDO"
        if raw_tipo_fiscal == "SUPLIDO"
        else "PROVISION"
    )
    concepto = _text(data.get("concepto"))
    total = (
        _float(data.get("total"))
        or (base + iva - irpf + suplidos)
    )
    expediente_id = _int_or_none(data.get("expediente_id"))
    hoja_id = _int_or_none(data.get("hoja_encargo_id"))
    cliente_id = int(data.get("cliente_id"))

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO eco_facturas (
                numero_factura, fecha_factura, cliente_id, expediente_id, hoja_encargo_id,
                base_imponible, iva, irpf, suplidos, total,
                tipo_fiscal, concepto, estado, exportada_holded,
                documento_ruta, observaciones, activo
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, 1
            )
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
                suplidos,
                total,
                tipo_fiscal,
                concepto,
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
        SELECT f.*,
               c.nombre,
               c.primer_apellido,
               c.segundo_apellido,
               e.numero_expediente,
               h.numero_hoja,
               fc.cobro_id,
               cob.numero_cobro,
               original.numero_factura
                   AS numero_factura_rectificada
        FROM eco_facturas f
        JOIN clientes c
          ON c.id = f.cliente_id
        LEFT JOIN expedientes e
          ON e.id = f.expediente_id
        LEFT JOIN eco_hojas_encargo h
          ON h.id = f.hoja_encargo_id
        LEFT JOIN eco_factura_cobros fc
          ON fc.id = (
              SELECT fc2.id
              FROM eco_factura_cobros fc2
              WHERE fc2.factura_id = f.id
              ORDER BY fc2.id
              LIMIT 1
          )
        LEFT JOIN eco_cobros cob
          ON cob.id = fc.cobro_id
        LEFT JOIN eco_facturas original
          ON original.id = f.factura_rectificada_id
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

    from backend.services.suplido_reconciliation_service import (
        sync_for_cobro,
    )

    sync_for_cobro(int(cobro_id), db_path=DB_PATH)
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


def list_consulta_cobros_disponibles(cliente_id=None):
    params = []
    cliente_filter = ""

    if cliente_id not in (None, ""):
        cliente_filter = " AND cob.cliente_id = ?"
        params.append(int(cliente_id))

    with _connect() as conn:
        initialize_economic_consultas_schema(conn)

        rows = conn.execute(
            f"""
            SELECT
                cob.*,
                cli.nombre,
                cli.primer_apellido,
                cli.segundo_apellido
            FROM eco_cobros cob
            LEFT JOIN clientes cli
              ON cli.id = cob.cliente_id
            LEFT JOIN eco_consultas_aplicadas app
              ON app.cobro_id = cob.id
             AND app.activo = 1
            WHERE cob.tipo_cobro = 'CONSULTA'
              AND cob.activo = 1
              AND app.id IS NULL
              AND cob.hoja_encargo_id IS NULL
              {cliente_filter}
            ORDER BY cob.fecha_cobro DESC, cob.id DESC
            """,
            tuple(params),
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

        hoja_expediente_id = _int_or_none(
            hoja.get("expediente_id")
        )
        expediente_solicitado = _int_or_none(
            expediente_id
        )

        if (
            hoja_expediente_id
            and expediente_solicitado
            and hoja_expediente_id != expediente_solicitado
        ):
            raise ValueError(
                "El expediente indicado no coincide con el de la hoja"
            )

        expediente_id = (
            hoja_expediente_id
            or expediente_solicitado
        )

        importe_cobro = _float(
            cobro.get("importe")
        )
        importe = _float(
            importe_aplicado
            if importe_aplicado not in (None, "")
            else importe_cobro
        )

        if importe <= 0:
            raise ValueError(
                "El importe de la consulta debe ser mayor que cero"
            )

        if importe > importe_cobro:
            raise ValueError(
                "No se puede aplicar un importe superior al cobro"
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

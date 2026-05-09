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
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def initialize_traceability_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "expedient_traceability_schema.sql"
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def get_expediente_basic(expediente_id):
    with _connect() as conn:
        return _dict(
            conn.execute(
                """
                SELECT e.*, c.nombre, c.primer_apellido, c.segundo_apellido
                FROM expedientes e
                JOIN clientes c ON c.id = e.cliente_id
                WHERE e.id = ?
                """,
                (int(expediente_id),),
            ).fetchone()
        )


def registrar_evento(
    expediente_id,
    cliente_id,
    tipo_evento,
    titulo,
    descripcion="",
    estado_anterior="",
    estado_nuevo="",
    entidad_relacionada="",
    entidad_relacionada_id=None,
    usuario="",
):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO expediente_eventos (
                expediente_id, cliente_id, tipo_evento, titulo, descripcion,
                estado_anterior, estado_nuevo, entidad_relacionada,
                entidad_relacionada_id, usuario
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(expediente_id),
                int(cliente_id),
                _text(tipo_evento),
                _text(titulo),
                _raw(descripcion),
                _text(estado_anterior),
                _text(estado_nuevo),
                _text(entidad_relacionada),
                entidad_relacionada_id,
                _text(usuario),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_eventos_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM expediente_eventos
                WHERE expediente_id = ?
                ORDER BY fecha_evento DESC, id DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]


def create_justificante(data):
    expediente_id = int(data.get("expediente_id"))
    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    cliente_id = expediente["cliente_id"]

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO expediente_justificantes (
                expediente_id, cliente_id, archivo_nombre, archivo_ruta,
                tipo_justificante, fecha_presentacion, numero_registro,
                organo_presentacion, procedimiento_detectado,
                estado_conciliacion, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                expediente_id,
                cliente_id,
                _raw(data.get("archivo_nombre")),
                _raw(data.get("archivo_ruta")),
                _text(data.get("tipo_justificante") or "PRESENTACION"),
                _raw(data.get("fecha_presentacion")),
                _text(data.get("numero_registro")),
                _text(data.get("organo_presentacion")),
                _text(data.get("procedimiento_detectado")),
                _text(data.get("estado_conciliacion") or "PENDIENTE"),
                _raw(data.get("observaciones")),
            ),
        )
        justificante_id = cur.lastrowid
        conn.commit()

    registrar_evento(
        expediente_id=expediente_id,
        cliente_id=cliente_id,
        tipo_evento="JUSTIFICANTE",
        titulo="JUSTIFICANTE CARGADO",
        descripcion=f"Justificante registrado: {_raw(data.get('archivo_nombre')) or _raw(data.get('archivo_ruta'))}",
        entidad_relacionada="expediente_justificantes",
        entidad_relacionada_id=justificante_id,
    )

    return justificante_id


def conciliar_justificante(justificante_id, actualizar_expediente=True):
    with _connect() as conn:
        justificante = _dict(
            conn.execute(
                "SELECT * FROM expediente_justificantes WHERE id = ?",
                (int(justificante_id),),
            ).fetchone()
        )

        if not justificante:
            raise ValueError("Justificante no encontrado")

        conn.execute(
            """
            UPDATE expediente_justificantes
            SET estado_conciliacion = 'CONCILIADO',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(justificante_id),),
        )

        if actualizar_expediente:
            conn.execute(
                """
                UPDATE expedientes
                SET fecha_presentacion = COALESCE(?, fecha_presentacion),
                    numero_registro = COALESCE(NULLIF(?, ''), numero_registro),
                    organo_presentacion = COALESCE(NULLIF(?, ''), organo_presentacion),
                    estado_presentacion = 'PRESENTADO',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    justificante.get("fecha_presentacion"),
                    justificante.get("numero_registro") or "",
                    justificante.get("organo_presentacion") or "",
                    justificante["expediente_id"],
                ),
            )

        conn.commit()

    registrar_evento(
        expediente_id=justificante["expediente_id"],
        cliente_id=justificante["cliente_id"],
        tipo_evento="CONCILIACION_DOCUMENTAL",
        titulo="JUSTIFICANTE CONCILIADO",
        descripcion="El justificante queda vinculado al expediente presentado.",
        estado_anterior="PENDIENTE",
        estado_nuevo="CONCILIADO",
        entidad_relacionada="expediente_justificantes",
        entidad_relacionada_id=justificante_id,
    )


def get_justificantes_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM expediente_justificantes
                WHERE expediente_id = ? AND activo = 1
                ORDER BY created_at DESC, id DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]


def create_consulta_previa(data):
    cliente_id = int(data.get("cliente_id"))
    importe = _float(data.get("importe"))

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO consultas_previas (
                cliente_id, fecha_consulta, importe, forma_pago,
                profesional_responsable, descontable, estado,
                observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                cliente_id,
                _raw(data.get("fecha_consulta")),
                importe,
                _text(data.get("forma_pago")),
                _text(data.get("profesional_responsable")),
                int(data.get("descontable", 1)),
                "DISPONIBLE" if int(data.get("descontable", 1)) else "NO DESCONTABLE",
                _raw(data.get("observaciones")),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_consultas_cliente(cliente_id, only_available=False):
    sql = """
        SELECT *
        FROM consultas_previas
        WHERE cliente_id = ? AND activo = 1
    """
    params = [int(cliente_id)]

    if only_available:
        sql += " AND descontable = 1 AND estado = 'DISPONIBLE'"

    sql += " ORDER BY fecha_consulta DESC, id DESC"

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def create_hoja_encargo(data):
    expediente_id = int(data.get("expediente_id"))
    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    cliente_id = expediente["cliente_id"]
    importe_bruto = _float(data.get("importe_bruto"))
    descuento_manual = _float(data.get("descuento_manual"))
    descuento_consultas = _float(data.get("descuento_consultas_previas"))
    importe_neto = max(0, importe_bruto - descuento_manual - descuento_consultas)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO hojas_encargo (
                expediente_id, cliente_id, numero_hoja, fecha_firma,
                procedimiento, importe_bruto, descuento_manual,
                descuento_consultas_previas, importe_neto,
                forma_pago_pactada, numero_plazos, fecha_maxima_pago,
                documento_ruta, estado_firma, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                expediente_id,
                cliente_id,
                _text(data.get("numero_hoja")),
                _raw(data.get("fecha_firma")),
                _text(data.get("procedimiento")),
                importe_bruto,
                descuento_manual,
                descuento_consultas,
                importe_neto,
                _text(data.get("forma_pago_pactada")),
                int(data.get("numero_plazos") or 1),
                _raw(data.get("fecha_maxima_pago")),
                _raw(data.get("documento_ruta")),
                _text(data.get("estado_firma") or "PENDIENTE FIRMA"),
                _raw(data.get("observaciones")),
            ),
        )
        hoja_id = cur.lastrowid
        conn.commit()

    registrar_evento(
        expediente_id=expediente_id,
        cliente_id=cliente_id,
        tipo_evento="HOJA_ENCARGO",
        titulo="HOJA DE ENCARGO REGISTRADA",
        descripcion=f"Importe bruto: {importe_bruto:.2f} · Neto: {importe_neto:.2f}",
        entidad_relacionada="hojas_encargo",
        entidad_relacionada_id=hoja_id,
    )

    return hoja_id


def get_hojas_encargo_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM hojas_encargo
                WHERE expediente_id = ? AND activo = 1
                ORDER BY created_at DESC, id DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]


def aplicar_consulta_a_expediente(expediente_id, consulta_previa_id, hoja_encargo_id=None, importe_aplicado=None, observaciones=""):
    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    with _connect() as conn:
        consulta = _dict(
            conn.execute(
                """
                SELECT *
                FROM consultas_previas
                WHERE id = ? AND activo = 1
                """,
                (int(consulta_previa_id),),
            ).fetchone()
        )

        if not consulta:
            raise ValueError("Consulta previa no encontrada")

        if consulta["estado"] != "DISPONIBLE":
            raise ValueError("La consulta previa no está disponible")

        if int(consulta["cliente_id"]) != int(expediente["cliente_id"]):
            raise ValueError("La consulta previa pertenece a otro cliente")

        importe = _float(importe_aplicado if importe_aplicado is not None else consulta["importe"])

        cur = conn.execute(
            """
            INSERT INTO expediente_consultas_aplicadas (
                expediente_id, cliente_id, consulta_previa_id,
                hoja_encargo_id, importe_aplicado, observaciones
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(expediente_id),
                int(expediente["cliente_id"]),
                int(consulta_previa_id),
                _int_or_none(hoja_encargo_id),
                importe,
                _raw(observaciones),
            ),
        )

        conn.execute(
            """
            UPDATE consultas_previas
            SET estado = 'APLICADA',
                expediente_id_aplicado = ?,
                fecha_aplicacion = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(expediente_id), int(consulta_previa_id)),
        )

        if hoja_encargo_id:
            conn.execute(
                """
                UPDATE hojas_encargo
                SET descuento_consultas_previas = descuento_consultas_previas + ?,
                    importe_neto = MAX(0, importe_bruto - descuento_manual - (descuento_consultas_previas + ?)),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (importe, importe, int(hoja_encargo_id)),
            )

        conn.commit()
        applied_id = cur.lastrowid

    registrar_evento(
        expediente_id=expediente_id,
        cliente_id=expediente["cliente_id"],
        tipo_evento="CONSULTA_PREVIA",
        titulo="CONSULTA PREVIA APLICADA",
        descripcion=f"Consulta previa descontada por importe {importe:.2f}",
        entidad_relacionada="expediente_consultas_aplicadas",
        entidad_relacionada_id=applied_id,
    )

    return applied_id


def get_resumen_trazabilidad(expediente_id):
    justificantes = get_justificantes_expediente(expediente_id)
    hojas = get_hojas_encargo_expediente(expediente_id)
    eventos = get_eventos_expediente(expediente_id)

    with _connect() as conn:
        consultas_aplicadas = [
            _dict(r)
            for r in conn.execute(
                """
                SELECT a.*, c.fecha_consulta, c.importe AS importe_original
                FROM expediente_consultas_aplicadas a
                JOIN consultas_previas c ON c.id = a.consulta_previa_id
                WHERE a.expediente_id = ?
                ORDER BY a.created_at DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]

    return {
        "justificantes": justificantes,
        "hojas_encargo": hojas,
        "consultas_aplicadas": consultas_aplicadas,
        "eventos": eventos,
    }

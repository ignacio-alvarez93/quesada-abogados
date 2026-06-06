

UPPERCASE_CLIENT_FIELDS = {
    'nombre',
    'primer_apellido',
    'segundo_apellido',
    'nie',
    'pasaporte',
    'dni',
    'nacionalidad',
    'estado_cliente',
    'tipo_via',
    'nombre_via',
    'domicilio_espana',
    'localidad',
    'provincia',
    'codigo_postal',
    'numero',
    'piso',
    'localidad_nacimiento',
    'pais_nacimiento',
    'nombre_padre',
    'nombre_madre',
    'estado_civil',
    'sexo',
    'observaciones',
    'observaciones_internas',
}


def normalize_upper(value):
    if value is None:
        return ''
    return str(value).strip().upper()


def normalize_client_data(data):
    normalized = dict(data)

    for field in UPPERCASE_CLIENT_FIELDS:
        if field in normalized:
            normalized[field] = normalize_upper(normalized.get(field))

    if 'email' in normalized:
        normalized['email'] = (normalized.get('email') or '').strip().lower()

    if 'telefono' in normalized:
        normalized['telefono'] = (normalized.get('telefono') or '').strip()

    return normalized


from database.connection import get_connection
from datetime import datetime


CLIENT_CONTACT_SYNC_FIELDS = [
    "nombre", "primer_apellido", "segundo_apellido", "nacionalidad",
    "nie", "pasaporte", "dni", "fecha_nacimiento", "localidad_nacimiento",
    "pais_nacimiento", "nombre_padre", "nombre_madre", "estado_civil",
    "telefono", "email", "tipo_via", "nombre_via", "domicilio_espana",
    "localidad", "codigo_postal", "provincia", "numero", "piso",
    "estado_cliente", "observaciones", "observaciones_internas", "sexo",
]


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(cursor, table_name):
    try:
        rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()


def _sync_linked_contact_rows_for_client(cursor, client_id, data):
    """
    Mantiene actualizadas las copias denormalizadas en cliente_contactos para
    compatibilidad con snapshots, formularios y pantallas antiguas.

    La fuente canónica sigue siendo clientes cuando existe cliente_referenciado_id.
    """
    if not client_id:
        return
    if not _table_exists(cursor, "cliente_contactos"):
        return

    columns = _table_columns(cursor, "cliente_contactos")
    fields = [field for field in CLIENT_CONTACT_SYNC_FIELDS if field in columns]
    if not fields:
        return

    cursor.execute(
        f"""
        UPDATE cliente_contactos
        SET {", ".join(f"{field} = ?" for field in fields)},
            updated_at = CURRENT_TIMESTAMP
        WHERE cliente_referenciado_id = ?
          AND COALESCE(activo, 1) = 1
        """,
        [data.get(field) for field in fields] + [int(client_id)],
    )


def create_client(data):
    data = normalize_client_data(data)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO clientes (
            nombre, primer_apellido, segundo_apellido,
            nacionalidad, nie, pasaporte, dni,
            fecha_nacimiento, localidad_nacimiento, pais_nacimiento,
            nombre_padre, nombre_madre,
            estado_civil,
            telefono, email,
            tipo_via, nombre_via, domicilio_espana, localidad, codigo_postal, provincia, numero, piso,
            estado_cliente, fecha_alta, origen_cliente, responsable_interno,
            observaciones, observaciones_internas, sexo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("nombre"),
        data.get("primer_apellido"),
        data.get("segundo_apellido"),
        data.get("nacionalidad"),
        data.get("nie"),
        data.get("pasaporte"),
        data.get("dni"),
        data.get("fecha_nacimiento"),
        data.get("localidad_nacimiento"),
        data.get("pais_nacimiento"),
        data.get("nombre_padre"),
        data.get("nombre_madre"),
        data.get("estado_civil"),
        data.get("telefono"),
        data.get("email"),
        data.get("tipo_via"),
        data.get("nombre_via"),
        data.get("domicilio_espana"),
        data.get("localidad"),
        data.get("codigo_postal"),
        data.get("provincia"),
        data.get("numero"),
        data.get("piso"),
        data.get("estado_cliente", "Asesoramiento inicial"),
        datetime.now().strftime("%Y-%m-%d"),
        data.get("origen_cliente"),
        data.get("responsable_interno"),
        data.get("observaciones"),
        data.get("observaciones_internas"),
        data.get("sexo"),
    ))

    conn.commit()
    conn.close()


def get_all_clients():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes WHERE activo = 1 ORDER BY id DESC")
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_client_by_id(client_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes WHERE id = ?", (client_id,))
    row = cursor.fetchone()

    conn.close()
    return dict(row) if row else None


def update_client(client_id, data):
    data = normalize_client_data(data)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE clientes
        SET
            nombre = ?,
            primer_apellido = ?,
            segundo_apellido = ?,
            nacionalidad = ?,
            nie = ?,
            pasaporte = ?,
            dni = ?,
            fecha_nacimiento = ?,
            localidad_nacimiento = ?,
            pais_nacimiento = ?,
            nombre_padre = ?,
            nombre_madre = ?,
            estado_civil = ?,
            telefono = ?,
            email = ?,
            tipo_via = ?,
            nombre_via = ?,
            domicilio_espana = ?,
            localidad = ?,
            codigo_postal = ?,
            provincia = ?,
            numero = ?,
            piso = ?,
            estado_cliente = ?,
            origen_cliente = ?,
            responsable_interno = ?,
            observaciones = ?,
            observaciones_internas = ?,
            sexo = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        data.get("nombre"),
        data.get("primer_apellido"),
        data.get("segundo_apellido"),
        data.get("nacionalidad"),
        data.get("nie"),
        data.get("pasaporte"),
        data.get("dni"),
        data.get("fecha_nacimiento"),
        data.get("localidad_nacimiento"),
        data.get("pais_nacimiento"),
        data.get("nombre_padre"),
        data.get("nombre_madre"),
        data.get("estado_civil"),
        data.get("telefono"),
        data.get("email"),
        data.get("tipo_via"),
        data.get("nombre_via"),
        data.get("domicilio_espana"),
        data.get("localidad"),
        data.get("codigo_postal"),
        data.get("provincia"),
        data.get("numero"),
        data.get("piso"),
        data.get("estado_cliente"),
        data.get("origen_cliente"),
        data.get("responsable_interno"),
        data.get("observaciones"),
        data.get("observaciones_internas"),
        data.get("sexo"),
        client_id,
    ))

    _sync_linked_contact_rows_for_client(cursor, client_id, data)

    conn.commit()
    conn.close()


def archive_client(client_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE clientes
        SET activo = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (client_id,))

    conn.commit()
    conn.close()


def search_clients(search_text):
    conn = get_connection()
    cursor = conn.cursor()

    pattern = f"%{search_text}%"

    cursor.execute("""
        SELECT *
        FROM clientes
        WHERE activo = 1
        AND (
            nombre LIKE ?
            OR primer_apellido LIKE ?
            OR segundo_apellido LIKE ?
            OR nie LIKE ?
            OR pasaporte LIKE ?
            OR dni LIKE ?
            OR telefono LIKE ?
            OR email LIKE ?
        )
        ORDER BY id DESC
    """, (
        pattern, pattern, pattern, pattern,
        pattern, pattern, pattern, pattern
    ))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]
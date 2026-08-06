

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

    if 'fecha_caducidad_residencia' in normalized:
        normalized['fecha_caducidad_residencia'] = (
            normalized.get('fecha_caducidad_residencia')
            or ''
        ).strip()

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
    "hubspot_id", "hubspot_url", "hubspot_imported_at",
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


def ensure_client_hubspot_columns(cursor):
    """
    Migración defensiva del modelo de clientes.

    Conserva el nombre histórico de la función para no romper llamadas
    existentes, aunque actualmente también asegura los campos de vigencia
    y procedencia de la autorización de residencia.
    """
    if not _table_exists(cursor, "clientes"):
        return

    columns = _table_columns(cursor, "clientes")
    required = {
        "hubspot_id": "TEXT",
        "hubspot_url": "TEXT",
        "hubspot_imported_at": "TEXT",
        "fecha_caducidad_residencia": "TEXT",
        "fecha_caducidad_origen": "TEXT",
        "fecha_caducidad_expediente_id": "INTEGER",
        "fecha_caducidad_documento_id": "INTEGER",
        "fecha_caducidad_actualizada_at": "TEXT",
    }

    for column, column_type in required.items():
        if column not in columns:
            cursor.execute(
                f"ALTER TABLE clientes "
                f"ADD COLUMN {column} {column_type}"
            )


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

    from backend.services import (
        client_administrative_status_service
    )

    client_administrative_status_service.ensure_client_administrative_schema(
        conn=conn
    )
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

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
            observaciones, observaciones_internas, sexo,
            hubspot_id, hubspot_url, hubspot_imported_at,
            fecha_caducidad_residencia,
            fecha_caducidad_origen,
            fecha_caducidad_actualizada_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?
        )
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
        data.get("hubspot_id"),
        data.get("hubspot_url"),
        data.get("hubspot_imported_at"),
        data.get("fecha_caducidad_residencia") or None,
        (
            "MANUAL"
            if data.get("fecha_caducidad_residencia")
            else None
        ),
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if data.get("fecha_caducidad_residencia")
            else None
        ),
    ))

    client_id = int(
        cursor.lastrowid
    )

    client_administrative_status_service.update_client_administrative_snapshot(
        client_id=client_id,
        data=data,
        conn=conn,
    )

    conn.commit()

    return_client_id = client_id
    conn.close()

    return return_client_id


def get_all_clients():
    conn = get_connection()
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

    cursor.execute("SELECT * FROM clientes WHERE activo = 1 ORDER BY id DESC")
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_client_by_id(client_id):
    conn = get_connection()
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

    cursor.execute("SELECT * FROM clientes WHERE id = ?", (client_id,))
    row = cursor.fetchone()

    conn.close()
    return dict(row) if row else None


def update_client(client_id, data):
    data = normalize_client_data(data)
    conn = get_connection()

    from backend.services import (
        client_administrative_status_service
    )

    client_administrative_status_service.ensure_client_administrative_schema(
        conn=conn
    )
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

    existing = cursor.execute(
        """
        SELECT
            fecha_caducidad_residencia,
            fecha_caducidad_origen,
            fecha_caducidad_expediente_id,
            fecha_caducidad_documento_id,
            fecha_caducidad_actualizada_at
        FROM clientes
        WHERE id = ?
        """,
        (int(client_id),),
    ).fetchone()

    existing_expiry = (
        existing["fecha_caducidad_residencia"]
        if existing
        else None
    )

    new_expiry = (
        data.get("fecha_caducidad_residencia")
        or None
    )

    expiry_changed = (
        (existing_expiry or "")
        !=
        (new_expiry or "")
    )

    expiry_origin = (
        "MANUAL"
        if expiry_changed and new_expiry
        else (
            None
            if expiry_changed
            else (
                existing["fecha_caducidad_origen"]
                if existing
                else None
            )
        )
    )

    expiry_expediente_id = (
        None
        if expiry_changed
        else (
            existing["fecha_caducidad_expediente_id"]
            if existing
            else None
        )
    )

    expiry_documento_id = (
        None
        if expiry_changed
        else (
            existing["fecha_caducidad_documento_id"]
            if existing
            else None
        )
    )

    expiry_updated_at = (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if expiry_changed
        else (
            existing["fecha_caducidad_actualizada_at"]
            if existing
            else None
        )
    )

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
            hubspot_id = ?,
            hubspot_url = ?,
            hubspot_imported_at = ?,
            fecha_caducidad_residencia = ?,
            fecha_caducidad_origen = ?,
            fecha_caducidad_expediente_id = ?,
            fecha_caducidad_documento_id = ?,
            fecha_caducidad_actualizada_at = ?,
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
        data.get("hubspot_id"),
        data.get("hubspot_url"),
        data.get("hubspot_imported_at"),
        new_expiry,
        expiry_origin,
        expiry_expediente_id,
        expiry_documento_id,
        expiry_updated_at,
        client_id,
    ))

    _sync_linked_contact_rows_for_client(cursor, client_id, data)


    client_administrative_status_service.update_client_administrative_snapshot(
        client_id=client_id,
        data=data,
        conn=conn,
    )

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


def find_client_duplicates(data, exclude_client_id=None):
    """
    Busca posibles duplicados por HubSpot ID, NIE, pasaporte o email.
    Devuelve clientes activos con el campo de coincidencia.
    """
    data = normalize_client_data(data)
    checks = []

    if data.get("hubspot_id"):
        checks.append(("hubspot_id", data.get("hubspot_id")))
    if data.get("nie"):
        checks.append(("nie", data.get("nie")))
    if data.get("pasaporte"):
        checks.append(("pasaporte", data.get("pasaporte")))
    if data.get("email"):
        checks.append(("email", data.get("email")))

    if not checks:
        return []

    conn = get_connection()
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

    duplicates = []
    seen_ids = set()

    for field, value in checks:
        query = f"""
            SELECT *
            FROM clientes
            WHERE activo = 1
              AND {field} = ?
        """
        params = [value]

        if exclude_client_id:
            query += " AND id <> ?"
            params.append(int(exclude_client_id))

        rows = cursor.execute(query, params).fetchall()
        for row in rows:
            item = dict(row)
            item["_duplicate_field"] = field
            if item.get("id") not in seen_ids:
                duplicates.append(item)
                seen_ids.add(item.get("id"))

    conn.close()
    return duplicates


def format_duplicate_clients(duplicates):
    if not duplicates:
        return ""

    lines = ["Posible cliente duplicado detectado:"]

    label_by_field = {
        "hubspot_id": "HubSpot ID",
        "nie": "NIE",
        "pasaporte": "Pasaporte",
        "email": "Email",
    }

    for client in duplicates:
        field = client.get("_duplicate_field")
        label = label_by_field.get(field, field or "campo")
        name = " ".join(
            part for part in [
                client.get("nombre"),
                client.get("primer_apellido"),
                client.get("segundo_apellido"),
            ]
            if part
        ).strip()

        lines.append(
            f"- #{client.get('id')} {name or 'Sin nombre'} "
            f"({label}: {client.get(field) or ''})"
        )

    lines.append("Revisa la ficha existente antes de crear otro cliente.")
    return "\n".join(lines)


def search_clients(search_text):
    conn = get_connection()
    cursor = conn.cursor()
    ensure_client_hubspot_columns(cursor)

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
            OR hubspot_id LIKE ?
        )
        ORDER BY id DESC
    """, (
        pattern, pattern, pattern, pattern,
        pattern, pattern, pattern, pattern, pattern
    ))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

# Alias retrocompatible
find_duplicate_clients = find_client_duplicates

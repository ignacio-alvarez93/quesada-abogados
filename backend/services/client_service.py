from database.connection import get_connection
from datetime import datetime


def create_client(data):
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
            domicilio_espana, localidad, codigo_postal, provincia, numero, piso,
            estado_cliente, fecha_alta, origen_cliente, responsable_interno,
            observaciones, observaciones_internas
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ))

    conn.commit()
    conn.close()


def get_all_clients():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes ORDER BY id DESC")
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
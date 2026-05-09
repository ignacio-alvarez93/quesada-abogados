"""
PARCHE PARA backend/services/client_service.py

Añadir estas funciones auxiliares cerca de los imports.
"""

UPPERCASE_FIELDS = [
    "nombre",
    "apellidos",
    "nombre_completo",
    "nacionalidad",
    "pais_nacimiento",
    "localidad",
    "provincia",
    "domicilio",
    "direccion",
    "nombre_padre",
    "nombre_madre",
    "estado_civil",
    "nie",
    "dni",
    "pasaporte",
    "observaciones",
    "observaciones_internas",
]


def normalize_upper(value):
    if value is None:
        return ""

    return str(value).strip().upper()


def normalize_client_data(data):
    normalized = dict(data)

    for field in UPPERCASE_FIELDS:
        if field in normalized:
            normalized[field] = normalize_upper(normalized.get(field))

    return normalized


"""
EN create_client():

ANTES DEL INSERT:
"""

client_data = normalize_client_data(client_data)


"""
EN update_client():

ANTES DEL UPDATE:
"""

client_data = normalize_client_data(client_data)

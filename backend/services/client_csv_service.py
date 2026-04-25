import csv
from backend.services.client_service import create_client
from datetime import datetime


HUBSPOT_COLUMN_MAP = {
    "nombre": ["Nombre", "First Name", "Name"],
    "apellidos": ["Apellidos", "Last Name", "Surname"],
    "email": ["Correo", "Email", "Correo electrónico"],
    "telefono": ["Número de teléfono", "Número de móvil", "Número de teléfono de WhatsApp", "Phone", "Mobile"],
    "nie": ["NIE"],
    "pasaporte": ["Pasaporte", "Passport"],
    "dni": ["DNI"],
    "nacionalidad": ["Nacionalidad", "Nacionalidad de origen"],
    "fecha_nacimiento": ["Fecha de nacimiento"],
    "localidad_nacimiento": ["Lugar de nacimiento"],
    "pais_nacimiento": ["País de nacimiento"],
    "nombre_padre": ["Nombre del padre"],
    "nombre_madre": ["Nombre de la madre"],
    "estado_civil": ["Estado civil"],
    "domicilio_espana": ["Tipo de vía y nombre"],
    "numero": ["Número de la calle"],
    "piso": ["Bloque / Esc / Piso y puerta"],
    "localidad": ["Ciudad"],
    "provincia": ["Estado o región"],
    "codigo_postal": ["Código postal"],
}


def format_date_to_sql(date_str):
    if not date_str:
        return ""

    try:
        # formato HubSpot / humano
        date_obj = datetime.strptime(date_str, "%d/%m/%Y")
        return date_obj.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def clean_value(value):
    if value is None:
        return ""
    return str(value).strip()


def split_apellidos(apellidos):
    apellidos = clean_value(apellidos)

    if not apellidos:
        return "", ""

    parts = apellidos.split()

    if len(parts) == 1:
        return parts[0], ""

    return parts[0], " ".join(parts[1:])


def get_value(row, possible_columns):
    for column in possible_columns:
        if column in row:
            value = clean_value(row.get(column))
            if value:
                return value
    return ""


def transform_hubspot_row(row):
    apellidos = get_value(row, HUBSPOT_COLUMN_MAP["apellidos"])
    primer_apellido, segundo_apellido = split_apellidos(apellidos)

    telefono = get_value(row, HUBSPOT_COLUMN_MAP["telefono"])

    return {
        "nombre": get_value(row, HUBSPOT_COLUMN_MAP["nombre"]),
        "primer_apellido": primer_apellido,
        "segundo_apellido": segundo_apellido,
        "email": get_value(row, HUBSPOT_COLUMN_MAP["email"]),
        "telefono": telefono,
        "nie": get_value(row, HUBSPOT_COLUMN_MAP["nie"]),
        "pasaporte": get_value(row, HUBSPOT_COLUMN_MAP["pasaporte"]),
        "dni": get_value(row, HUBSPOT_COLUMN_MAP["dni"]),
        "nacionalidad": get_value(row, HUBSPOT_COLUMN_MAP["nacionalidad"]),
        "fecha_nacimiento": format_date_to_sql(
    get_value(row, HUBSPOT_COLUMN_MAP["fecha_nacimiento"])
),
        "localidad_nacimiento": get_value(row, HUBSPOT_COLUMN_MAP["localidad_nacimiento"]),
        "pais_nacimiento": get_value(row, HUBSPOT_COLUMN_MAP["pais_nacimiento"]),
        "nombre_padre": get_value(row, HUBSPOT_COLUMN_MAP["nombre_padre"]),
        "nombre_madre": get_value(row, HUBSPOT_COLUMN_MAP["nombre_madre"]),
        "estado_civil": get_value(row, HUBSPOT_COLUMN_MAP["estado_civil"]),
        "domicilio_espana": get_value(row, HUBSPOT_COLUMN_MAP["domicilio_espana"]),
        "numero": get_value(row, HUBSPOT_COLUMN_MAP["numero"]),
        "piso": get_value(row, HUBSPOT_COLUMN_MAP["piso"]),
        "localidad": get_value(row, HUBSPOT_COLUMN_MAP["localidad"]),
        "provincia": get_value(row, HUBSPOT_COLUMN_MAP["provincia"]),
        "codigo_postal": get_value(row, HUBSPOT_COLUMN_MAP["codigo_postal"]),
        "estado_cliente": "Importado desde HubSpot",
        "origen_cliente": "HubSpot CSV",
    }


def validate_client_import(client):
    errors = []

    if not client.get("nombre"):
        errors.append("Falta nombre")

    return errors


def preview_clients_from_csv(file_path):
    results = []

    with open(file_path, mode="r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)

        for index, row in enumerate(reader, start=1):
            client = transform_hubspot_row(row)
            errors = validate_client_import(client)

            results.append({
                "row_number": index,
                "client": client,
                "errors": errors,
                "valid": len(errors) == 0,
            })

    return results


def import_clients_from_csv(file_path):
    preview = preview_clients_from_csv(file_path)

    imported = 0
    skipped = 0
    errors = []

    for item in preview:
        if item["valid"]:
            create_client(item["client"])
            imported += 1
        else:
            skipped += 1
            errors.append({
                "row_number": item["row_number"],
                "errors": item["errors"],
            })

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


HUBSPOT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "pasaporte",
    "nie",
    "dni",
    "phone",
    "date_of_birth",
    "sexo",
    "lugar_de_nacimiento",
    "pais_de_nacimiento",
    "nacionalidad",
    "address",
    "city",
    "zip",
    "marital_status",
    "nombre_de_la_madre",
    "nombre_del_padre",
    "tramite",
    "via_nombre",
    "numero_calle",
    "piso_y_puerta",
    "state",
    "importe_deuda",
]


class HubSpotImportError(Exception):
    pass


def extract_contact_id(value: str) -> str:
    """
    Acepta un ID directo o una URL de contacto de HubSpot.
    """
    raw = (value or "").strip()

    if not raw:
        raise HubSpotImportError("Pega una URL o ID de HubSpot")

    if raw.isdigit():
        return raw

    # Caso habitual: URL terminada en /contact/<id> o /<id>
    matches = re.findall(r"(\d{5,})", raw)
    if not matches:
        raise HubSpotImportError(f"No se pudo extraer el ID de HubSpot de: {raw}")

    return matches[-1]


def _read_env_file(path: Path) -> dict:
    values = {}

    if not path.exists() or not path.is_file():
        return values

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()

            if not raw or raw.startswith("#") or "=" not in raw:
                continue

            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                values[key] = value
    except Exception:
        return values

    return values


def _local_env_candidates() -> list[Path]:
    candidates = [
        Path.cwd() / ".env.local",
        Path.cwd() / ".env",
    ]

    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "QuesadaAbogados" / ".env")

    return candidates


def _get_config_value(key: str) -> str:
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value

    for candidate in _local_env_candidates():
        values = _read_env_file(candidate)
        if values.get(key):
            return values[key].strip()

    return ""


def _access_token() -> str:
    token = _get_config_value("HUBSPOT_ACCESS_TOKEN")

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise HubSpotImportError(
            "No está configurado HUBSPOT_ACCESS_TOKEN. "
            "Define la variable de entorno, crea .env.local o configura "
            "%APPDATA%/QuesadaAbogados/.env."
        )

    return token


def fetch_contact(contact_id: str) -> dict:
    params = urllib.parse.urlencode({
        "properties": ",".join(HUBSPOT_PROPERTIES),
    })

    url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}?{params}"

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HubSpotImportError(f"HubSpot respondió {exc.code}: {body}") from exc
    except Exception as exc:
        raise HubSpotImportError(f"No se pudo consultar HubSpot: {exc}") from exc


def _clean(value, upper=False):
    value = "" if value is None else str(value).strip()
    return value.upper() if upper else value


def _split_lastname(lastname: str) -> tuple[str, str]:
    parts = _clean(lastname, upper=True).split()

    if not parts:
        return "", ""

    return parts[0], " ".join(parts[1:])


def _format_date(value: str) -> str:
    raw = _clean(value)

    if not raw:
        return ""

    # HubSpot a veces puede venir como timestamp en ms.
    if raw.isdigit() and len(raw) >= 11:
        try:
            dt = datetime.fromtimestamp(int(raw) / 1000)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return ""

    # ISO: 1990-01-31 o 1990-01-31T00:00:00Z
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"

    # DD/MM/YYYY o DD-MM-YYYY
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", raw)
    if m:
        year = m.group(3)
        if len(year) == 2:
            year = "19" + year
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{year}"

    return raw


def _normalize_sex(value: str) -> str:
    raw = _clean(value, upper=True)

    if raw in {"H", "HOMBRE", "M", "MASCULINO", "MALE"}:
        return "HOMBRE"

    if raw in {"M", "MUJER", "F", "FEMENINO", "FEMALE"}:
        return "MUJER"

    if raw in {"X", "OTRO", "OTHER"}:
        return "X"

    return raw


def normalize_contact_properties(props: dict, contact_id: str = "") -> dict:
    apellido1, apellido2 = _split_lastname(props.get("lastname"))

    # HubSpot antiguo usa via_nombre como vía completa; si viene vacío usamos address.
    nombre_via = _clean(props.get("via_nombre") or props.get("address"), upper=True)

    return {
        "hubspot_id": contact_id,
        "hubspot_url": "",
        "nombre": _clean(props.get("firstname"), upper=True),
        "primer_apellido": apellido1,
        "segundo_apellido": apellido2,
        "email": _clean(props.get("email")),
        "telefono": _clean(props.get("phone")),
        "pasaporte": _clean(props.get("pasaporte"), upper=True),
        "nie": _clean(props.get("nie"), upper=True).replace(" ", ""),
        "dni": _clean(props.get("dni"), upper=True).replace(" ", ""),
        "fecha_nacimiento": _format_date(props.get("date_of_birth")),
        "sexo": _normalize_sex(props.get("sexo")),
        "localidad_nacimiento": _clean(props.get("lugar_de_nacimiento"), upper=True),
        "pais_nacimiento": _clean(props.get("pais_de_nacimiento"), upper=True),
        "nacionalidad": _clean(props.get("nacionalidad"), upper=True),
        "nombre_via": nombre_via,
        "numero": _clean(props.get("numero_calle")),
        "piso": _clean(props.get("piso_y_puerta"), upper=True),
        "localidad": _clean(props.get("city"), upper=True),
        "codigo_postal": _clean(props.get("zip")),
        "provincia": _clean(props.get("state"), upper=True),
        "nombre_padre": _clean(props.get("nombre_del_padre"), upper=True),
        "nombre_madre": _clean(props.get("nombre_de_la_madre"), upper=True),
        "estado_civil": _clean(props.get("marital_status"), upper=True),
        "tramite_hubspot": _clean(props.get("tramite")),
        "importe_deuda_hubspot": _clean(props.get("importe_deuda")),
    }


def preview_contact_import(value: str) -> dict:
    contact_id = extract_contact_id(value)
    payload = fetch_contact(contact_id)
    props = payload.get("properties") or {}
    data = normalize_contact_properties(props, contact_id=contact_id)
    data["hubspot_url"] = (value or "").strip()
    return data

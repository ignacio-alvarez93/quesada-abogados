"""
Mapper Mercurio completo.

Convierte expediente + cliente en JSON reutilizable para Presentación Asistida.

IMPORTANTE:
- Ya NO fija códigos de país manualmente para Mercurio.
- En datos_mercurio.json guarda texto normalizado y texto original.
- El runner selecciona países/provincias/municipios buscando el texto real en los <option> de Mercurio.
"""

import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from backend.services import config_service
from backend.services import presentation_config_service
from backend.services import expedient_snapshot_service as snapshot_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_ROOT = PROJECT_ROOT / "exports" / "presentaciones_asistidas"

DEFAULT_MERCURIO_PROVINCIA_CODIGO = "33"  # Asturias provisional


PROVINCIA_NOMBRE_A_CODIGO = {
    "A CORUNA": "15", "A CORUÑA": "15",
    "ALBACETE": "02",
    "ALICANTE": "03",
    "ALMERIA": "04", "ALMERÍA": "04",
    "ARABA": "01", "ALAVA": "01", "ÁLAVA": "01",
    "ASTURIAS": "33",
    "AVILA": "05", "ÁVILA": "05",
    "BADAJOZ": "06",
    "BARCELONA": "08",
    "BIZKAIA": "48", "VIZCAYA": "48",
    "BURGOS": "09",
    "CACERES": "10", "CÁCERES": "10",
    "CADIZ": "11", "CÁDIZ": "11",
    "CANTABRIA": "39",
    "CASTELLON": "12", "CASTELLÓN": "12",
    "CEUTA": "51",
    "CIUDAD REAL": "13",
    "CORDOBA": "14", "CÓRDOBA": "14",
    "CUENCA": "16",
    "GIPUZKOA": "20", "GUIPUZCOA": "20",
    "GIRONA": "17", "GERONA": "17",
    "GRANADA": "18",
    "GUADALAJARA": "19",
    "HUELVA": "21",
    "HUESCA": "22",
    "ILLES BALEARS": "07", "BALEARES": "07",
    "JAEN": "23", "JAÉN": "23",
    "LA RIOJA": "26",
    "LAS PALMAS": "35",
    "LEON": "24", "LEÓN": "24",
    "LLEIDA": "25", "LERIDA": "25", "LÉRIDA": "25",
    "LUGO": "27",
    "MADRID": "28",
    "MALAGA": "29", "MÁLAGA": "29",
    "MELILLA": "52",
    "MURCIA": "30",
    "NAVARRA": "31",
    "OURENSE": "32", "ORENSE": "32",
    "PALENCIA": "34",
    "PONTEVEDRA": "36",
    "SALAMANCA": "37",
    "SEGOVIA": "40",
    "SEVILLA": "41",
    "SORIA": "42",
    "TARRAGONA": "43",
    "TENERIFE": "38", "SANTA CRUZ DE TENERIFE": "38",
    "TERUEL": "44",
    "TOLEDO": "45",
    "VALENCIA": "46",
    "VALLADOLID": "47",
    "ZAMORA": "49",
    "ZARAGOZA": "50",
}


ESTADO_CIVIL_A_CODIGO = {
    "CASADO": "C", "CASADO/A": "C", "CASADA": "C",
    "DESCONOCIDO": "E",
    "DIVORCIADO": "D", "DIVORCIADO/A": "D", "DIVORCIADA": "D",
    "SEPARADO": "P", "SEPARADO/A": "P", "SEPARADA": "P",
    "SOLTERO": "S", "SOLTERO/A": "S", "SOLTERA": "S",
    "UNION DE HECHO": "U", "UNIÓN DE HECHO": "U", "PAREJA DE HECHO": "U",
    "VIUDO": "V", "VIUDO/A": "V", "VIUDA": "V",
}


SEXO_A_CODIGO = {
    "HOMBRE": "0",
    "VARON": "0",
    "VARÓN": "0",
    "M": "0",
    "MASCULINO": "0",
    "MUJER": "1",
    "F": "1",
    "FEMENINO": "1",
    "INDEFINIDO": "X",
    "X": "X",
}


TIPO_VIA_A_CODIGO = {
    # Valores típicos. Si Mercurio tiene texto distinto, el runner intentará buscar por texto.
    "CALLE": "CL",
    "C/": "CL",
    "AVENIDA": "AV",
    "AVDA": "AV",
    "PLAZA": "PZ",
    "PASEO": "PS",
    "CAMINO": "CM",
    "CARRETERA": "CT",
    "RONDA": "RD",
    "TRAVESIA": "TR",
    "TRAVESÍA": "TR",
    "URBANIZACION": "UR",
    "URBANIZACIÓN": "UR",
    "SIN TIPO": "ZZ",
    "OTROS": "ZZ",
}


CODIGO_A_TIPO_VIA = {
    "CL": "CALLE",
    "AV": "AVENIDA",
    "PZ": "PLAZA",
    "PS": "PASEO",
    "CM": "CAMINO",
    "CT": "CARRETERA",
    "RD": "RONDA",
    "TR": "TRAVESIA",
    "UR": "URBANIZACION",
    "ZZ": "OTROS",
}

def limpiar_piso(value):
    value = "" if value is None else str(value).strip()
    if not value:
        return ""

    normalized = normalize(value)

    # Mercurio necesita el bajo exterior en el campo piso con esta forma.
    if normalized in {"BJ", "BAJO", "BAJO EXT", "BJ EXT", "BJO", "BJO EXT"}:
        return "BJ EXT"

    if normalized in {"ENT", "ENTRESUELO", "ENTRESUELO EXT", "ENT EXT"}:
        return "ENT EXT"

    # Pisos numéricos: "5 C", "PISO 5", "05" -> "05".
    m = re.search(r"\d+", normalized)
    if m:
        return m.group(0).zfill(2)

    return normalized

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _dict(row):
    return dict(row) if row else None


def normalize(value):
    value = "" if value is None else str(value)
    value = value.strip().upper()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value)
    return value


def safe_folder_name(value):
    value = normalize(value) or "EXPEDIENTE"
    value = re.sub(r"[^A-Z0-9_\-]+", "_", value)
    return value.strip("_") or "EXPEDIENTE"


def format_date_es(value):
    value = "" if value is None else str(value).strip()
    if not value:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        y, m, d = value.split("-")
        return f"{d}/{m}/{y}"
    if re.match(r"^\d{2}/\d{2}/\d{4}$", value):
        return value
    return value


def first(*values):
    for value in values:
        if value not in (None, "", "None"):
            return value
    return ""


def map_provincia(value):
    value = first(value)
    if not value:
        return DEFAULT_MERCURIO_PROVINCIA_CODIGO
    text = normalize(value)
    if text.isdigit():
        return text.zfill(2) if len(text) == 1 else text
    return PROVINCIA_NOMBRE_A_CODIGO.get(text, DEFAULT_MERCURIO_PROVINCIA_CODIGO)


def map_estado_civil(value):
    value = first(value)
    if not value:
        return ""
    text = normalize(value)
    if text in {"C", "E", "D", "P", "S", "U", "V"}:
        return text
    return ESTADO_CIVIL_A_CODIGO.get(text, "")


def map_estado_civil_mercurio(value):
    """
    Estado civil para Mercurio.
    Si falta en cliente, usa S como fallback provisional.
    """
    mapped = map_estado_civil(value)
    return mapped or "S"


def map_estado_civil_reagrupante(value):
    """
    La pestaña Datos del familiar de EX01 usa X para SEPARADO/A,
    mientras otros bloques históricos usan P.
    """
    text = normalize(value)
    if text in {"SEPARADO", "SEPARADO/A", "SEPARADA", "P"}:
        return "X"
    return map_estado_civil_mercurio(value)


def map_parentesco_ex01_familiar(value):
    text = normalize(value)
    if not text:
        return ""
    if text in {"CO", "CONYUGE", "CONYUGE", "CONYUGE/PAREJA", "ESPOSO", "ESPOSA"}:
        return "CO"
    if "CONYUGE" in text or "CONYUGE" in text or "ESPOS" in text:
        return "CO"
    if "PAREJA" in text:
        return "P1"
    if "HIJO" in text or "HIJA" in text or "DESCEND" in text:
        return "AS"
    if "PADRE" in text or "MADRE" in text or "ASCEND" in text:
        return "HI"
    if "TUTEL" in text:
        return "TU"
    return ""


def map_tipo_documento_reagrupante(cliente):
    cliente = cliente or {}
    if str(cliente.get("nie") or "").strip():
        return "TU"
    if str(cliente.get("dni") or "").strip():
        return "NF"
    return ""


def map_documento_reagrupante(cliente):
    cliente = cliente or {}
    return first(cliente.get("nie"), cliente.get("dni"))


def map_sexo(value):
    value = first(value)
    if not value:
        return ""
    text = normalize(value)
    if text in {"0", "1", "X"}:
        return text
    return SEXO_A_CODIGO.get(text, "")


def infer_tipo_via(domicilio):
    text = normalize(domicilio)
    if not text:
        return ""

    for label, code in TIPO_VIA_A_CODIGO.items():
        if text.startswith(normalize(label) + " ") or text == normalize(label):
            return code

    # Default razonable para España si la ficha no separa tipo de vía.
    return "CL"


def parse_domicilio(domicilio, numero=None, piso=None):
    """
    Separa domicilio completo en piezas Mercurio.

    Reglas críticas:
    - El número final se elimina siempre del nombre de vía, aunque ya venga
      informado en la columna numero.
    - El piso se toma de la columna piso si existe; si no, de la parte tras coma.
    - "BJ", "BAJO" y variantes se normalizan a "BJ EXT".
    """
    raw = "" if domicilio is None else str(domicilio).strip()
    cleaned = raw

    tipo_via_codigo = infer_tipo_via(raw)

    # Quitar tipo vía al inicio.
    for label in sorted(TIPO_VIA_A_CODIGO.keys(), key=len, reverse=True):
        nlabel = normalize(label)
        if normalize(cleaned).startswith(nlabel + " "):
            cleaned = cleaned[len(label):].strip(" ,.-")
            break

    parsed_numero = "" if numero is None else str(numero).strip()
    parsed_piso = "" if piso is None else str(piso).strip()

    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    main_part = parts[0] if parts else cleaned.strip()
    rest_parts = parts[1:]

    if rest_parts:
        first_rest = rest_parts[0]
        rest_number_match = re.match(r"^(\d+[A-Z]?)\b\s*(.*)$", first_rest, re.IGNORECASE)

        if rest_number_match:
            rest_number = rest_number_match.group(1).strip()
            remainder = rest_number_match.group(2).strip(" ,.-")
            if not parsed_numero:
                parsed_numero = rest_number

            piso_candidates = []
            if remainder:
                piso_candidates.append(remainder)
            if len(rest_parts) > 1:
                piso_candidates.extend(rest_parts[1:])

            if not parsed_piso and piso_candidates:
                parsed_piso = ", ".join(part for part in piso_candidates if part).strip()
        elif not parsed_piso:
            parsed_piso = ", ".join(rest_parts).strip()

    # Último token numérico/letra como número: "GENERAL ELORZA 11" -> 11.
    # Importante: se elimina del domicilio aunque parsed_numero ya venga informado.
    m = re.search(r"\b(\d+[A-Z]?)\b\s*$", main_part, re.IGNORECASE)
    if m:
        trailing_numero = m.group(1).strip()
        if not parsed_numero:
            parsed_numero = trailing_numero
        main_part = main_part[:m.start()].strip(" ,.-")

    parsed_domicilio = main_part.strip() or cleaned
    parsed_piso = limpiar_piso(parsed_piso)

    return {
        "tipo_via_codigo": tipo_via_codigo,
        "domicilio": parsed_domicilio,
        "numero": parsed_numero,
        "piso": parsed_piso,
    }


def get_expediente_full(expediente_id):
    sql = """
        SELECT
            e.*,
            c.id AS cliente_id_real,
            c.nombre AS cliente_nombre,
            c.primer_apellido AS cliente_primer_apellido,
            c.segundo_apellido AS cliente_segundo_apellido,
            c.nacionalidad AS cliente_nacionalidad,
            c.nie AS cliente_nie,
            c.pasaporte AS cliente_pasaporte,
            c.dni AS cliente_dni,
            c.fecha_nacimiento AS cliente_fecha_nacimiento,
            c.localidad_nacimiento AS cliente_localidad_nacimiento,
            c.pais_nacimiento AS cliente_pais_nacimiento,
            c.nombre_padre AS cliente_nombre_padre,
            c.nombre_madre AS cliente_nombre_madre,
            c.estado_civil AS cliente_estado_civil,
            c.sexo AS cliente_sexo,
            c.telefono AS cliente_telefono,
            c.email AS cliente_email,
            c.domicilio_espana AS cliente_domicilio_espana,
            c.localidad AS cliente_localidad,
            c.codigo_postal AS cliente_codigo_postal,
            c.provincia AS cliente_provincia,
            c.numero AS cliente_numero,
            c.piso AS cliente_piso,
            te.nombre AS tipo_expediente_nombre,
            te.codigo AS tipo_expediente_codigo,
            st.nombre AS subtipo_expediente_nombre,
            st.codigo AS subtipo_expediente_codigo
        FROM expedientes e
        JOIN clientes c ON c.id = e.cliente_id
        LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente st ON st.id = e.subtipo_expediente_id
        WHERE e.id = ?
    """
    with _connect() as conn:
        return _dict(conn.execute(sql, (int(expediente_id),)).fetchone())


def get_presentacion_folder(expediente):
    numero = first(expediente.get("numero_expediente"), f"EXPEDIENTE_{expediente.get('id')}")
    folder = EXPORT_ROOT / safe_folder_name(numero)
    (folder / "html").mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)
    return folder



def _id_or_none(value):
    """Normaliza IDs para comparar expediente actual vs snapshot."""
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except Exception:
        return str(value).strip()


def _identity_label(expediente_like):
    expediente_like = expediente_like or {}
    tipo = first(
        expediente_like.get("tipo_expediente_codigo"),
        expediente_like.get("tipo_expediente_nombre"),
    )
    subtipo = first(
        expediente_like.get("subtipo_expediente_codigo"),
        expediente_like.get("subtipo_expediente"),
        expediente_like.get("subtipo_expediente_nombre"),
    )
    return f"{tipo or 'SIN_TIPO'} / {subtipo or 'SIN_SUBTIPO'}"


def validate_snapshot_matches_current_expediente(expediente_id, snapshot):
    """
    Bloquea snapshots obsoletos antes de generar datos Mercurio.

    Mercurio consume el snapshot congelado, no la ficha viva. Por seguridad,
    si alguien reutiliza o modifica un expediente después de crear snapshot,
    no se permite generar/exportar datos con tipo, subtipo o cliente antiguos.
    """
    current = get_expediente_full(expediente_id)
    if not current:
        raise ValueError(f"No existe expediente id={expediente_id}")

    snapshot = snapshot or {}
    snap_exp = _snapshot_expediente(snapshot)
    snap_cli = _snapshot_cliente(snapshot)

    checks = [
        ("expediente_id", _id_or_none(current.get("id")), _id_or_none(snap_exp.get("id"))),
        ("cliente_id", _id_or_none(current.get("cliente_id_real") or current.get("cliente_id")), _id_or_none(snap_cli.get("id"))),
        ("tipo_expediente_id", _id_or_none(current.get("tipo_expediente_id")), _id_or_none(snap_exp.get("tipo_expediente_id"))),
        ("subtipo_expediente_id", _id_or_none(current.get("subtipo_expediente_id")), _id_or_none(snap_exp.get("subtipo_expediente_id"))),
    ]

    mismatches = [(field, actual, frozen) for field, actual, frozen in checks if actual != frozen]

    if not mismatches:
        return True

    details = "; ".join(
        f"{field}: actual={actual!r}, snapshot={frozen!r}"
        for field, actual, frozen in mismatches
    )
    metadata = snapshot.get("metadata") or {}

    raise ValueError(
        "Snapshot Mercurio obsoleto para expediente "
        f"{expediente_id}. "
        f"Actual: {_identity_label(current)}. "
        f"Snapshot: {_identity_label(snap_exp)}. "
        f"Diferencias: {details}. "
        f"Snapshot versión: {metadata.get('snapshot_db_version') or metadata.get('snapshot_version') or 'N/D'}, "
        f"creado: {metadata.get('snapshot_db_created_at') or metadata.get('generated_at') or 'N/D'}. "
        "Regenera un snapshot validado antes de lanzar Presentación Asistida."
    )


def load_snapshot_for_mercurio(expediente_id):
    """
    Carga un snapshot validado y vigente para Mercurio.

    Mercurio consume snapshot congelado, pero no debe quedarse anclado a una
    versión antigua si el expediente o los datos dinámicos han cambiado. Por eso
    antes de exportar se garantiza una versión actual, igual que en el flujo de
    formularios/previews.
    """
    latest = snapshot_service.ensure_current_snapshot(
        expediente_id,
        created_by="MERCURIO_AUTO_REFRESH",
    )

    if not latest:
        raise ValueError(
            "No se pudo generar snapshot para este expediente. "
            "Revisa la ficha y vuelve a intentarlo."
        )

    if int(latest.get("validated") or 0) != 1:
        result = latest.get("generation_result") or {}
        errors = result.get("errors") or []
        details = "\n- " + "\n- ".join(errors) if errors else ""
        raise ValueError(
            "El snapshot actual del expediente tiene advertencias. "
            "Corrige los datos antes de iniciar Mercurio."
            + details
        )

    snapshot = latest.get("snapshot") or {}
    snapshot.setdefault("metadata", {})["snapshot_db_id"] = latest.get("id")
    snapshot.setdefault("metadata", {})["snapshot_db_version"] = latest.get("version")
    snapshot.setdefault("metadata", {})["snapshot_db_hash"] = latest.get("source_hash")
    snapshot.setdefault("metadata", {})["snapshot_db_created_at"] = latest.get("created_at")
    snapshot.setdefault("metadata", {})["snapshot_generated_now"] = bool(latest.get("generated_now"))

    # Defensa final: si incluso tras refrescar no coincide, se bloquea.
    validate_snapshot_matches_current_expediente(expediente_id, snapshot)

    return snapshot


def _snapshot_cliente(snapshot):
    return dict((snapshot or {}).get("cliente") or {})


def _snapshot_expediente(snapshot):
    return dict((snapshot or {}).get("expediente") or {})


def _snapshot_representante(snapshot):
    return dict((snapshot or {}).get("representante") or {})

def build_datos_cliente(expediente, snapshot=None):
    cliente_snapshot = _snapshot_cliente(snapshot)
    if cliente_snapshot:
        return {
            "id": cliente_snapshot.get("id") or "",
            "nombre": cliente_snapshot.get("nombre") or "",
            "primer_apellido": cliente_snapshot.get("primer_apellido") or "",
            "segundo_apellido": cliente_snapshot.get("segundo_apellido") or "",
            "nacionalidad": cliente_snapshot.get("nacionalidad") or "",
            "nie": cliente_snapshot.get("nie") or "",
            "pasaporte": cliente_snapshot.get("pasaporte") or "",
            "dni": cliente_snapshot.get("dni") or "",
            "fecha_nacimiento": cliente_snapshot.get("fecha_nacimiento") or "",
            "localidad_nacimiento": cliente_snapshot.get("localidad_nacimiento") or "",
            "pais_nacimiento": cliente_snapshot.get("pais_nacimiento") or "",
            "estado_civil": cliente_snapshot.get("estado_civil") or "",
            "sexo": cliente_snapshot.get("sexo") or "",
            "telefono": cliente_snapshot.get("telefono") or "",
            "email": cliente_snapshot.get("email") or "",
            "domicilio_espana": cliente_snapshot.get("domicilio_espana") or "",
            "localidad": cliente_snapshot.get("localidad") or "",
            "codigo_postal": cliente_snapshot.get("codigo_postal") or "",
            "provincia": cliente_snapshot.get("provincia") or "",
            "numero": cliente_snapshot.get("numero") or "",
            "piso": cliente_snapshot.get("piso") or "",
            "nombre_padre": cliente_snapshot.get("nombre_padre") or "",
            "nombre_madre": cliente_snapshot.get("nombre_madre") or "",
        }

    # Compatibilidad interna para pruebas unitarias antiguas.
    # El flujo Mercurio real llama siempre con snapshot.
    return {
        "id": expediente.get("cliente_id_real") or expediente.get("cliente_id"),
        "nombre": expediente.get("cliente_nombre") or "",
        "primer_apellido": expediente.get("cliente_primer_apellido") or "",
        "segundo_apellido": expediente.get("cliente_segundo_apellido") or "",
        "nacionalidad": expediente.get("cliente_nacionalidad") or "",
        "nie": expediente.get("cliente_nie") or "",
        "pasaporte": expediente.get("cliente_pasaporte") or "",
        "dni": expediente.get("cliente_dni") or "",
        "fecha_nacimiento": expediente.get("cliente_fecha_nacimiento") or "",
        "localidad_nacimiento": expediente.get("cliente_localidad_nacimiento") or "",
        "pais_nacimiento": expediente.get("cliente_pais_nacimiento") or "",
        "estado_civil": expediente.get("cliente_estado_civil") or "",
        "sexo": expediente.get("cliente_sexo") or "",
        "telefono": expediente.get("cliente_telefono") or "",
        "email": expediente.get("cliente_email") or "",
        "domicilio_espana": expediente.get("cliente_domicilio_espana") or "",
        "localidad": expediente.get("cliente_localidad") or "",
        "codigo_postal": expediente.get("cliente_codigo_postal") or "",
        "provincia": expediente.get("cliente_provincia") or "",
        "numero": expediente.get("cliente_numero") or "",
        "piso": expediente.get("cliente_piso") or "",
        "nombre_padre": expediente.get("cliente_nombre_padre") or "",
        "nombre_madre": expediente.get("cliente_nombre_madre") or "",
    }


def build_datos_expediente(expediente, snapshot=None):
    expediente_snapshot = _snapshot_expediente(snapshot)
    cliente_snapshot = _snapshot_cliente(snapshot)

    if expediente_snapshot:
        provincia_codigo = map_provincia(first(
            expediente_snapshot.get("mercurio_provincia_codigo"),
            expediente_snapshot.get("provincia_codigo"),
            expediente_snapshot.get("codigo_provincia"),
            expediente_snapshot.get("provincia"),
            cliente_snapshot.get("provincia"),
        ))

        return {
            "id": expediente_snapshot.get("id"),
            "numero_expediente": expediente_snapshot.get("numero_expediente") or "",
            "numero_expediente_mercurio": expediente_snapshot.get("numero_expediente_mercurio") or "",
            "tipo_expediente_id": expediente_snapshot.get("tipo_expediente_id"),
            "tipo_expediente_nombre": expediente_snapshot.get("tipo_expediente_nombre") or "",
            "tipo_expediente_codigo": expediente_snapshot.get("tipo_expediente_codigo") or "",
            "subtipo_expediente_id": expediente_snapshot.get("subtipo_expediente_id"),
            "subtipo_expediente": expediente_snapshot.get("subtipo_expediente") or expediente_snapshot.get("subtipo_expediente_nombre") or "",
            "subtipo_expediente_codigo": expediente_snapshot.get("subtipo_expediente_codigo") or "",
            "organo_presentacion": expediente_snapshot.get("organo_presentacion") or "",
            "provincia": first(expediente_snapshot.get("provincia"), cliente_snapshot.get("provincia")),
            "provincia_codigo_mercurio": provincia_codigo,
            "box_folder_path": expediente_snapshot.get("box_folder_path") or "",
        }

    # Compatibilidad interna para pruebas unitarias antiguas.
    provincia_codigo = map_provincia(first(
        expediente.get("mercurio_provincia_codigo"),
        expediente.get("provincia_codigo"),
        expediente.get("codigo_provincia"),
        expediente.get("provincia"),
        expediente.get("cliente_provincia"),
    ))

    return {
        "id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente"),
        "numero_expediente_mercurio": expediente.get("numero_expediente_mercurio") or "",
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_expediente_nombre": expediente.get("tipo_expediente_nombre"),
        "tipo_expediente_codigo": expediente.get("tipo_expediente_codigo"),
        "subtipo_expediente_id": expediente.get("subtipo_expediente_id"),
        "subtipo_expediente": expediente.get("subtipo_expediente") or expediente.get("subtipo_expediente_nombre"),
        "subtipo_expediente_codigo": expediente.get("subtipo_expediente_codigo"),
        "organo_presentacion": expediente.get("organo_presentacion") or "",
        "provincia": first(expediente.get("provincia"), expediente.get("cliente_provincia")),
        "provincia_codigo_mercurio": provincia_codigo,
        "box_folder_path": expediente.get("box_folder_path") or "",
    }



def _snapshot_datos_especificos(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    datos = snapshot.get("datos_especificos") or {}
    return datos if isinstance(datos, dict) else {}


def _truthy_mercurio_flag(value):
    """Normaliza valores Sí/No del snapshot a bandera booleana para Mercurio."""
    text = normalize(value)
    return text in {"SI", "S", "TRUE", "1", "YES", "Y"}


def _first_dynamic_value(datos_especificos, *keys):
    for key in keys:
        value = datos_especificos.get(key)
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _extract_leading_id(value):
    """Extrae el id inicial de valores tipo '11 - Nombre · Documento'."""
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^\s*(\d+)\s*(?:[-·|:]|$)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _get_cliente_contacto(contacto_id):
    if not contacto_id:
        return None
    with _connect() as conn:
        return _dict(conn.execute(
            """
            SELECT *
            FROM cliente_contactos
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            LIMIT 1
            """,
            (int(contacto_id),),
        ).fetchone())


def _contacto_id_from_representante_legal_datos(datos):
    """
    Resuelve el id vivo del contacto seleccionado como representante/familiar.

    Prioridad:
    1. Campos técnicos derivados guardados por el autocomplete.
    2. Valor visible del autocomplete: "11 - Nombre · Documento".
    """
    datos = datos or {}

    explicit_id = _first_dynamic_value(
        datos,
        "representante_legal_contacto_id",
        "representante_legal_id",
        "rep_legal_contacto_id",
        "rep_legal_id",
    )
    if explicit_id:
        try:
            return int(str(explicit_id).strip())
        except Exception:
            pass

    autocomplete_value = _first_dynamic_value(
        datos,
        "representante_legal",
        "rep_legal",
        "representante_legal_contacto",
    )
    return _extract_leading_id(autocomplete_value)


def _get_representante_legal_contacto_from_datos(datos):
    contacto_id = _contacto_id_from_representante_legal_datos(datos)
    return _get_cliente_contacto(contacto_id)


def _full_name_from_contacto(contacto):
    contacto = contacto or {}
    return " ".join([
        str(contacto.get("nombre") or "").strip(),
        str(contacto.get("primer_apellido") or "").strip(),
        str(contacto.get("segundo_apellido") or "").strip(),
    ]).strip()


def _documento_from_contacto(contacto):
    contacto = contacto or {}
    return first(
        contacto.get("nie"),
        contacto.get("dni"),
        contacto.get("pasaporte"),
    )


def _tipo_documento_from_contacto(contacto):
    contacto = contacto or {}
    if str(contacto.get("nie") or "").strip():
        return "TU"
    if str(contacto.get("dni") or "").strip():
        return "NI"
    if str(contacto.get("pasaporte") or "").strip():
        return "PA"
    return ""


def _fill_missing(merged, key, value):
    if str(merged.get(key) or "").strip():
        return
    if str(value or "").strip():
        merged[key] = str(value).strip()


def _overlay_representante_legal_from_contacto_autocomplete(merged, datos):
    """
    Si hay contacto seleccionado, resuelve SIEMPRE el registro vivo en BD.

    Esto evita que Mercurio use derivados antiguos guardados en
    expediente_datos_especificos, por ejemplo un parentesco anterior.
    """
    contacto = _get_representante_legal_contacto_from_datos(datos)
    if not contacto:
        return merged

    # Campos estructurados críticos: se sobrescriben desde BD viva.
    # Los derivados persistidos pueden quedar obsoletos si se edita el contacto.
    merged["representante_legal_contacto_id"] = str(contacto.get("id") or "")
    merged["representante_legal_nombre"] = _full_name_from_contacto(contacto)
    merged["representante_legal_tipo_documento"] = _tipo_documento_from_contacto(contacto)
    merged["representante_legal_documento"] = _documento_from_contacto(contacto)
    merged["representante_legal_titulo"] = str(contacto.get("parentesco") or "").strip()
    merged["representante_legal_parentesco"] = str(contacto.get("parentesco") or "").strip()
    merged["representante_legal_telefono_movil"] = str(contacto.get("telefono") or "").strip()
    merged["representante_legal_email"] = str(contacto.get("email") or "").strip()

    # Domicilio/localización del representante legal.
    merged["representante_legal_domicilio_espana"] = str(contacto.get("domicilio_espana") or "").strip()
    merged["representante_legal_tipo_via"] = str(contacto.get("tipo_via") or "").strip()
    merged["representante_legal_nombre_via"] = str(contacto.get("nombre_via") or "").strip()
    merged["representante_legal_numero"] = str(contacto.get("numero") or "").strip()
    merged["representante_legal_piso"] = str(contacto.get("piso") or "").strip()
    merged["representante_legal_puerta"] = str(contacto.get("puerta") or "").strip()
    merged["representante_legal_escalera"] = str(contacto.get("escalera") or "").strip()
    merged["representante_legal_provincia"] = str(contacto.get("provincia") or "").strip()
    merged["representante_legal_localidad"] = str(contacto.get("localidad") or "").strip()
    merged["representante_legal_municipio"] = str(contacto.get("localidad") or "").strip()
    merged["representante_legal_codigo_postal"] = str(contacto.get("codigo_postal") or "").strip()

    # Datos auxiliares para diagnóstico/exportación.
    merged["representante_legal_nie"] = str(contacto.get("nie") or "").strip()
    merged["representante_legal_dni"] = str(contacto.get("dni") or "").strip()
    merged["representante_legal_pasaporte"] = str(contacto.get("pasaporte") or "").strip()

    return merged


def _overlay_representante_legal_from_datos_especificos(rep, snapshot):
    """
    Permite que los formularios dinámicos alimenten los campos Mercurio
    del representante legal sin endurecer un bloque fijo en la UI.

    Convención recomendada de códigos en formulario dinámico:
    representante_legal_nombre, representante_legal_documento,
    representante_legal_tipo_documento, representante_legal_titulo,
    representante_legal_telefono_movil, representante_legal_email.
    """
    datos = _snapshot_datos_especificos(snapshot)
    if not datos:
        return rep

    merged = dict(rep or {})

    # Prioridad correcta: si existe nombre_completo derivado del autocomplete,
    # debe ganar sobre nombre para no perder apellidos al guardar derivados.
    nombre = _first_dynamic_value(
        datos,
        "representante_legal_nombre_completo",
        "rep_legal_nombre_completo",
        "representante_legal_nombre",
        "rep_legal_nombre",
    )
    if not nombre:
        nombre_parts = [
            _first_dynamic_value(datos, "representante_legal_nombre_pila", "rep_legal_nombre_pila"),
            _first_dynamic_value(datos, "representante_legal_primer_apellido", "rep_legal_primer_apellido"),
            _first_dynamic_value(datos, "representante_legal_segundo_apellido", "rep_legal_segundo_apellido"),
        ]
        nombre = " ".join(part for part in nombre_parts if part).strip()

    explicit_values = {
        "representante_legal_nombre": nombre,
        "representante_legal_tipo_documento": _first_dynamic_value(datos, "representante_legal_tipo_documento", "rep_legal_tipo_documento"),
        "representante_legal_documento": _first_dynamic_value(datos, "representante_legal_documento", "rep_legal_documento", "representante_legal_nie", "rep_legal_nie"),
        "representante_legal_titulo": _first_dynamic_value(datos, "representante_legal_titulo", "rep_legal_titulo", "representante_legal_parentesco", "rep_legal_parentesco"),
        "representante_legal_telefono_movil": _first_dynamic_value(datos, "representante_legal_telefono_movil", "rep_legal_telefono_movil", "representante_legal_telefono", "rep_legal_telefono"),
        "representante_legal_email": _first_dynamic_value(datos, "representante_legal_email", "rep_legal_email"),
        "representante_legal_provincia": _first_dynamic_value(datos, "representante_legal_provincia", "rep_legal_provincia"),
        "representante_legal_municipio": _first_dynamic_value(datos, "representante_legal_municipio", "rep_legal_municipio", "representante_legal_localidad", "rep_legal_localidad"),
        "representante_legal_localidad": _first_dynamic_value(datos, "representante_legal_localidad", "rep_legal_localidad", "representante_legal_municipio", "rep_legal_municipio"),
        "representante_legal_codigo_postal": _first_dynamic_value(datos, "representante_legal_codigo_postal", "rep_legal_codigo_postal"),
        "representante_legal_domicilio_espana": _first_dynamic_value(datos, "representante_legal_domicilio_espana", "rep_legal_domicilio_espana"),
    }

    for key, value in explicit_values.items():
        if value:
            merged[key] = value

    # Fallback quirúrgico: si solo existe el valor visible del autocomplete
    # representante_legal = "11 - Nombre · Documento", resolver el contacto.
    return _overlay_representante_legal_from_contacto_autocomplete(merged, datos)

def build_datos_representante(snapshot=None):
    """
    Lee el representante desde el snapshot del expediente.

    Fallback a Settings solo para compatibilidad interna si se llama sin snapshot.
    """
    rep = _overlay_representante_legal_from_datos_especificos(
        _snapshot_representante(snapshot) or config_service.get_representante_config(),
        snapshot,
    )

    tipo_via = rep.get("representante_tipo_via") or ""
    piso = limpiar_piso(rep.get("representante_piso") or "")
    nombre_presentador = rep.get("representante_nombre_razon_social") or " ".join([
        rep.get("representante_nombre") or "",
        rep.get("representante_apellido1") or "",
        rep.get("representante_apellido2") or "",
    ]).strip()

    return {
        # Identidad del presentador
        "preNombrePresentador": nombre_presentador,
        "preTipodocumentoPresentador": rep.get("representante_tipo_documento") or "",
        "preNiePresentador": rep.get("representante_documento") or "",

        # Domicilio del presentador
        "preTipoViaPresentador": tipo_via,
        "preTipoViaPresentador_text": CODIGO_A_TIPO_VIA.get(tipo_via, tipo_via),
        "preDomicilioPresentador": rep.get("representante_domicilio") or "",
        "preNumeroPresentador": rep.get("representante_numero") or "",
        "prePisoPresentador": piso,
        "preLetraPresentador": rep.get("representante_letra") or "",
        "preEscaleraPresentador": rep.get("representante_escalera") or "",
        "preBloquePresentador": rep.get("representante_bloque") or "",
        "preKilometroPresentador": rep.get("representante_kilometro") or "",
        "preHectometroPresentador": rep.get("representante_hectometro") or "",
        "preCodigoProvinciaPresentador": map_provincia(rep.get("representante_provincia") or ""),
        "preCodigoProvinciaPresentador_text": rep.get("representante_provincia") or "",
        "preCodigoMunicipioPresentador_text": rep.get("representante_municipio") or "",
        "preCodigoLocalidadPresentador_text": rep.get("representante_localidad") or "",
        "preCodigoPostalPresentador": rep.get("representante_codigo_postal") or "",

        # Contacto
        "preTelefonoPresentador": rep.get("representante_telefono") or "",
        "preTelefonoMovilPresentador": rep.get("representante_telefono_movil") or rep.get("representante_telefono") or "",
        "preEmailPresentador": rep.get("representante_email") or "",

        # Representante legal del presentador, si procede
        "preNombreRepresentantePresentador": rep.get("representante_legal_nombre") or "",
        "preTipodocumentoRepresentantePresentador": rep.get("representante_legal_tipo_documento") or "",
        "preNieRepresentantePresentador": rep.get("representante_legal_documento") or "",
        "preTituloRepresentantePresentador": rep.get("representante_legal_titulo") or "",
        "preTelefonoMovilRepLegalPresentador": rep.get("representante_legal_telefono_movil") or "",
        "preEmailRepLegalPresentador": rep.get("representante_legal_email") or "",

        # Representante legal estructurado resuelto desde formulario dinámico/autocomplete
        "representante_legal_contacto_id": rep.get("representante_legal_contacto_id") or "",
        "representante_legal_nombre": rep.get("representante_legal_nombre") or "",
        "representante_legal_tipo_documento": rep.get("representante_legal_tipo_documento") or "",
        "representante_legal_documento": rep.get("representante_legal_documento") or "",
        "representante_legal_titulo": rep.get("representante_legal_titulo") or "",
        "representante_legal_telefono_movil": rep.get("representante_legal_telefono_movil") or "",
        "representante_legal_email": rep.get("representante_legal_email") or "",
        "representante_legal_provincia": rep.get("representante_legal_provincia") or "",
        "representante_legal_municipio": rep.get("representante_legal_municipio") or rep.get("representante_legal_localidad") or "",
        "representante_legal_localidad": rep.get("representante_legal_localidad") or rep.get("representante_legal_municipio") or "",
        "representante_legal_codigo_postal": rep.get("representante_legal_codigo_postal") or "",
        "representante_legal_domicilio_espana": rep.get("representante_legal_domicilio_espana") or "",

        # Datos auxiliares ERP / Box para fases posteriores
        "ruta_box_dni_representante": rep.get("representante_ruta_box_dni") or "",
        "representante_csv": rep.get("representante_csv") or "",
        "representante_opcion_notarial": rep.get("representante_opcion_notarial") or "",
        "representante_codigo_notario": rep.get("representante_codigo_notario") or "",
        "representante_codigo_notaria": rep.get("representante_codigo_notaria") or "",
        "representante_fecha_escritura": rep.get("representante_fecha_escritura") or "",
        "representante_num_protocolo": rep.get("representante_num_protocolo") or "",
        "representante_num_bis": rep.get("representante_num_bis") or "",
    }



def _contacto_id_from_prefixed_datos(datos, prefix, *extra_value_keys):
    """Resuelve el id de un contacto guardado con un prefijo técnico."""
    datos = datos or {}
    candidates = [
        f"{prefix}_contacto_id",
        f"{prefix}_id",
        *extra_value_keys,
    ]
    explicit_id = _first_dynamic_value(datos, *candidates)
    if explicit_id:
        try:
            return int(str(explicit_id).strip())
        except Exception:
            pass

    autocomplete_value = _first_dynamic_value(datos, prefix, f"{prefix}_contacto")
    return _extract_leading_id(autocomplete_value)


def _get_contacto_from_prefixed_datos(datos, prefix, *extra_value_keys):
    return _get_cliente_contacto(_contacto_id_from_prefixed_datos(datos, prefix, *extra_value_keys))


def _overlay_prefixed_contact_as_representante_legal(merged, datos, prefix):
    """Convierte un contacto seleccionado con prefijo propio en campos representante_legal_*."""
    contacto = _get_contacto_from_prefixed_datos(datos, prefix)
    if not contacto:
        return merged

    merged["representante_legal_contacto_id"] = str(contacto.get("id") or "")
    merged["representante_legal_nombre"] = _full_name_from_contacto(contacto)
    merged["representante_legal_tipo_documento"] = _tipo_documento_from_contacto(contacto)
    merged["representante_legal_documento"] = _documento_from_contacto(contacto)
    merged["representante_legal_titulo"] = str(contacto.get("parentesco") or contacto.get("tipo_contacto") or "").strip()
    merged["representante_legal_parentesco"] = str(contacto.get("parentesco") or "").strip()
    merged["representante_legal_telefono_movil"] = str(contacto.get("telefono") or "").strip()
    merged["representante_legal_email"] = str(contacto.get("email") or "").strip()
    merged["representante_legal_provincia"] = str(contacto.get("provincia") or "").strip()
    merged["representante_legal_municipio"] = str(contacto.get("localidad") or "").strip()
    merged["representante_legal_localidad"] = str(contacto.get("localidad") or "").strip()
    merged["representante_legal_codigo_postal"] = str(contacto.get("codigo_postal") or "").strip()
    merged["representante_legal_domicilio_espana"] = str(contacto.get("domicilio_espana") or "").strip()
    merged["representante_legal_nie"] = str(contacto.get("nie") or "").strip()
    merged["representante_legal_dni"] = str(contacto.get("dni") or "").strip()
    merged["representante_legal_pasaporte"] = str(contacto.get("pasaporte") or "").strip()

    return merged


def _overlay_solicitante_representante_legal_from_datos_especificos(rep, snapshot):
    """
    Lee el representante legal real del solicitante.

    Nuevo bloque independiente:
    solicitante_representante_legal_*

    No usa representante_legal_* porque ese prefijo histórico ya alimenta el
    familiar/titular de medios económicos de EX01 familiar.
    """
    datos = _snapshot_datos_especificos(snapshot)
    if not datos:
        return rep

    merged = dict(rep or {})

    prefix = "solicitante_representante_legal"
    nombre = _first_dynamic_value(
        datos,
        f"{prefix}_nombre_completo",
        f"{prefix}_nombre",
    )
    if not nombre:
        nombre_parts = [
            _first_dynamic_value(datos, f"{prefix}_nombre_pila"),
            _first_dynamic_value(datos, f"{prefix}_primer_apellido"),
            _first_dynamic_value(datos, f"{prefix}_segundo_apellido"),
        ]
        nombre = " ".join(part for part in nombre_parts if part).strip()

    explicit_values = {
        "representante_legal_nombre": nombre,
        "representante_legal_tipo_documento": _first_dynamic_value(datos, f"{prefix}_tipo_documento"),
        "representante_legal_documento": _first_dynamic_value(datos, f"{prefix}_documento", f"{prefix}_nie", f"{prefix}_dni", f"{prefix}_pasaporte"),
        "representante_legal_titulo": _first_dynamic_value(datos, f"{prefix}_titulo", f"{prefix}_parentesco", f"{prefix}_tipo_contacto"),
        "representante_legal_parentesco": _first_dynamic_value(datos, f"{prefix}_parentesco"),
        "representante_legal_telefono_movil": _first_dynamic_value(datos, f"{prefix}_telefono_movil", f"{prefix}_telefono"),
        "representante_legal_email": _first_dynamic_value(datos, f"{prefix}_email"),
        "representante_legal_provincia": _first_dynamic_value(datos, f"{prefix}_provincia"),
        "representante_legal_municipio": _first_dynamic_value(datos, f"{prefix}_municipio", f"{prefix}_localidad"),
        "representante_legal_localidad": _first_dynamic_value(datos, f"{prefix}_localidad", f"{prefix}_municipio"),
        "representante_legal_codigo_postal": _first_dynamic_value(datos, f"{prefix}_codigo_postal"),
        "representante_legal_domicilio_espana": _first_dynamic_value(datos, f"{prefix}_domicilio_espana"),
    }

    for key, value in explicit_values.items():
        if value:
            merged[key] = value

    # Si existe contacto seleccionado, manda el contacto vivo de BD.
    return _overlay_prefixed_contact_as_representante_legal(merged, datos, prefix)


def build_representante_legal_extranjero(snapshot=None):
    """
    Construye los campos de representante legal del extranjero/a.

    En EX01 familiar estos campos pertenecen a la primera pestaña
    "Datos del extranjero/a" (prefijo ext*), no a "Datos del presentador"
    (prefijo pre*).

    Usa el bloque nuevo solicitante_representante_legal_* para no mezclarlo
    con el familiar/titular de medios económicos.
    """
    rep = _overlay_solicitante_representante_legal_from_datos_especificos({}, snapshot)
    if not rep:
        return {}

    titulo = first(
        rep.get("representante_legal_titulo"),
        rep.get("representante_legal_parentesco"),
    )

    return {
        "extNombreRepresentante": rep.get("representante_legal_nombre") or "",
        "extTipodocumentoRepresentante": rep.get("representante_legal_tipo_documento") or "",
        "extNieRepresentante": rep.get("representante_legal_documento") or "",
        "extTituloRepresentante": titulo,
        "extVinculoRepresentante": titulo,
    }


def sanitize_presentador_for_ex01_familiar(representante):
    """
    Evita que el representante legal del solicitante se vuelque en la pestaña
    del presentador profesional.
    """
    representante = dict(representante or {})
    for key in (
        "preNombreRepresentantePresentador",
        "preTipodocumentoRepresentantePresentador",
        "preNieRepresentantePresentador",
        "preTituloRepresentantePresentador",
        "preTelefonoMovilRepLegalPresentador",
        "preEmailRepLegalPresentador",
    ):
        representante[key] = ""
    return representante



def _build_familiar_source_from_contacto(cliente, contacto):
    """
    Fuente base para la pestaña Datos del familiar de EX01 familiar.

    Si hay contacto/familiar seleccionado en Datos específicos, Mercurio debe
    usar sus datos vivos. Si falta algún dato del contacto, conserva fallback al
    cliente para no romper expedientes antiguos.
    """
    cliente = cliente or {}
    contacto = contacto or {}
    if not contacto:
        return dict(cliente)

    keys = [
        "pasaporte", "nie", "dni",
        "primer_apellido", "segundo_apellido", "nombre",
        "sexo", "fecha_nacimiento", "estado_civil",
        "localidad_nacimiento", "pais_nacimiento", "nacionalidad",
        "nombre_padre", "nombre_madre",
        "domicilio_espana", "numero", "piso",
        "provincia", "localidad", "codigo_postal",
        "telefono", "email",
    ]

    merged = dict(cliente)
    for key in keys:
        value = contacto.get(key)
        if str(value or "").strip():
            merged[key] = str(value).strip()

    return merged


def _overlay_familiar_source_from_datos_especificos(familiar, datos):
    """
    Aplica sobre el familiar los derivados congelados en datos_especificos.

    Motivo:
    - El contacto vivo puede tener numero/piso antiguos o vacíos.
    - El autocomplete/datos específicos puede traer el domicilio completo
      correcto, por ejemplo: "CARRETERA PRIMO DE RIVERA 1, 01".
    - Si se sustituye domicilio_espana, hay que sustituir también numero/piso
      aunque vengan vacíos, para que parse_domicilio los extraiga del texto y
      no conserve un numero/piso antiguo del contacto.
    """
    familiar = dict(familiar or {})
    datos = datos or {}

    field_map = {
        "pasaporte": ("representante_legal_pasaporte",),
        "nie": ("representante_legal_nie", "representante_legal_documento"),
        "dni": ("representante_legal_dni",),
        "primer_apellido": ("representante_legal_primer_apellido",),
        "segundo_apellido": ("representante_legal_segundo_apellido",),
        "nombre": ("representante_legal_nombre",),
        "sexo": ("representante_legal_sexo",),
        "fecha_nacimiento": ("representante_legal_fecha_nacimiento",),
        "estado_civil": ("representante_legal_estado_civil",),
        "localidad_nacimiento": ("representante_legal_localidad_nacimiento",),
        "pais_nacimiento": ("representante_legal_pais_nacimiento",),
        "nacionalidad": ("representante_legal_nacionalidad",),
        "nombre_padre": ("representante_legal_nombre_padre",),
        "nombre_madre": ("representante_legal_nombre_madre",),
        "provincia": ("representante_legal_provincia",),
        "localidad": ("representante_legal_localidad", "representante_legal_municipio"),
        "codigo_postal": ("representante_legal_codigo_postal",),
        "telefono": ("representante_legal_telefono", "representante_legal_telefono_movil"),
        "email": ("representante_legal_email",),
    }

    for target_key, source_keys in field_map.items():
        value = _first_dynamic_value(datos, *source_keys)
        if value:
            familiar[target_key] = value

    domicilio = _first_dynamic_value(datos, "representante_legal_domicilio_espana")
    if domicilio:
        familiar["domicilio_espana"] = domicilio
        # Importante: estos campos deben poder quedar vacíos para que
        # parse_domicilio extraiga numero/piso desde el domicilio completo.
        familiar["numero"] = str(datos.get("representante_legal_numero") or "").strip()
        familiar["piso"] = str(datos.get("representante_legal_piso") or "").strip()

    return familiar

def build_datos_familiar_ex01(cliente, snapshot=None):
    """
    Construye la pestaña Mercurio "Datos del familiar" para EX01 familiar.

    En esta variante:
    - extranjero = cliente/solicitante del expediente.
    - familiar = contacto seleccionado como familiar/titular de medios
      en datos específicos, con datos vivos de BD.
    """
    cliente = cliente or {}
    datos = _snapshot_datos_especificos(snapshot)

    contacto_representante = _get_representante_legal_contacto_from_datos(datos)
    familiar = _build_familiar_source_from_contacto(cliente, contacto_representante)
    familiar = _overlay_familiar_source_from_datos_especificos(familiar, datos)

    domicilio_parts = parse_domicilio(
        familiar.get("domicilio_espana") or "",
        numero=familiar.get("numero") or "",
        piso=familiar.get("piso") or "",
    )
    tipo_via_codigo = domicilio_parts["tipo_via_codigo"]
    tipo_via_text = CODIGO_A_TIPO_VIA.get(tipo_via_codigo, tipo_via_codigo)

    parentesco = ""
    if contacto_representante:
        parentesco = str(contacto_representante.get("parentesco") or "").strip()
    if not parentesco:
        parentesco = _first_dynamic_value(
            datos,
            "representante_legal_parentesco",
            "familiar_parentesco",
            "parentesco",
        )

    return {
        "reaPasaporteReagrupante": familiar.get("pasaporte") or "",
        "reaTipoDocumentoReagrupante": map_tipo_documento_reagrupante(familiar),
        "reaDocumentoReagrupante": map_documento_reagrupante(familiar),
        "reaApellido1Reagrupante": familiar.get("primer_apellido") or "",
        "reaApellido2Reagrupante": familiar.get("segundo_apellido") or "",
        "reaNombreReagrupante": familiar.get("nombre") or "",
        "reaSexoReagrupante": map_sexo(familiar.get("sexo")),
        "reaFechaNacimientoReagrupante": format_date_es(familiar.get("fecha_nacimiento")),
        "reaEstadoCivilReagrupante": map_estado_civil_reagrupante(familiar.get("estado_civil")),
        "reaEstadoCivilReagrupante_text": familiar.get("estado_civil") or "",
        "reaLugarNacimientoReagrupante": familiar.get("localidad_nacimiento") or "",
        "reaCodigoPaisNacimientoReagrupante_text": familiar.get("pais_nacimiento") or "",
        "reaCodigoNacionalidadReagrupante_text": familiar.get("nacionalidad") or "",
        "reaPadreReagrupante": familiar.get("nombre_padre") or "",
        "reaMadreReagrupante": familiar.get("nombre_madre") or "",
        "reaTipoViaReagrupante": tipo_via_codigo,
        "reaTipoViaReagrupante_text": tipo_via_text,
        "reaDomicilioReagrupante": domicilio_parts["domicilio"],
        "reaNumeroReagrupante": domicilio_parts["numero"],
        "reaPisoReagrupante": domicilio_parts["piso"],
        "reaLetraReagrupante": "",
        "reaEscaleraReagrupante": "",
        "reaBloqueReagrupante": "",
        "reaKilometroReagrupante": "",
        "reaHectometroReagrupante": "",
        "reaCodigoProvinciaReagrupante": map_provincia(familiar.get("provincia")),
        "reaCodigoProvinciaReagrupante_text": familiar.get("provincia") or "",
        "reaCodigoMunicipioReagrupante_text": familiar.get("localidad") or "",
        "reaCodigoLocalidadReagrupante_text": familiar.get("localidad") or "",
        "reaCodigoPostalReagrupante": familiar.get("codigo_postal") or "",
        "reaTelefonoReagrupante": familiar.get("telefono") or "",
        "reaTelefonoMovilReagrupante": familiar.get("telefono") or "",
        "reaEmailReagrupante": familiar.get("email") or "",
        "reaNombreRepresentanteReagrupante": "",
        "reaTipodocumentoRepresentanteReagrupante": "",
        "reaNieRepresentanteReagrupante": "",
        "reaTituloRepresentanteReagrupante": "",
        "reaParentescoReagrupante": map_parentesco_ex01_familiar(parentesco),
        "reaParentescoReagrupante_text": parentesco,
    }



def get_presentacion_reglas_for_expediente(expediente_json):
    expediente_json = expediente_json or {}
    tipo_id = expediente_json.get("tipo_expediente_id")
    if not tipo_id:
        return {}

    return presentation_config_service.get_presentacion_reglas(
        tipo_id,
        subtipo_id=expediente_json.get("subtipo_expediente_id"),
    )


def resolve_tipo_formulario_objetivo(expediente_json):
    """
    Resuelve el formulario Mercurio objetivo sin tocar SeleniumBase.

    Prioridad:
    1. Configuración explícita en config_presentaciones_asistidas.reglas_json.
    2. Si el tipo/subtipo ya contiene un código EX explícito, lo respeta.
    3. Si no, aplica equivalencias mínimas conocidas del proyecto.
    4. Fallback conservador: EX32, para no romper el flujo que ya funciona.
    """
    expediente_json = expediente_json or {}

    raw_values = [
        expediente_json.get("tipo_expediente_codigo"),
        expediente_json.get("tipo_expediente_nombre"),
        expediente_json.get("subtipo_expediente_codigo"),
        expediente_json.get("subtipo_expediente_nombre"),
        expediente_json.get("subtipo_expediente"),
    ]

    normalized_values = [normalize(value) for value in raw_values if value]
    joined = " ".join(normalized_values)

    # 1. Configuración explícita en config_presentaciones_asistidas.
    reglas = get_presentacion_reglas_for_expediente(expediente_json)
    configured_form = str(reglas.get("tipo_formulario_objetivo") or "").strip().upper()
    if configured_form:
        return configured_form

    # Si la configuración ya trae un código EX explícito, lo usamos.
    match = re.search(r"\bEX[\s\-_]?(\d{2})\b", joined)
    if match:
        return f"EX{match.group(1)}"

    # Equivalencias mínimas conocidas del proyecto.
    if "REAGRUPACION FAMILIAR" in joined:
        return "EX02"

    if "NO LUCRATIVA" in joined or "NO_LUCRATIVA" in joined:
        return "EX01"

    # Fallback conservador: mantiene el comportamiento actual.
    return "EX32"


def resolve_mapper_codigo(expediente_json, tipo_formulario_objetivo=None):
    """
    Resuelve el mapper interno de Mercurio desde reglas_json.

    El formulario objetivo es lo que selecciona el abogado en Mercurio
    (EX01, EX02, EX32...). El mapper_codigo permite distinguir variantes
    internas del ERP, como MERCURIO_EX01_FAMILIAR, sin inventar modelos
    Mercurio que no existen.
    """
    reglas = get_presentacion_reglas_for_expediente(expediente_json)
    configured_mapper = str(reglas.get("mapper_codigo") or "").strip().upper()
    if configured_mapper:
        return configured_mapper

    tipo = str(tipo_formulario_objetivo or resolve_tipo_formulario_objetivo(expediente_json) or "").strip().upper()
    if tipo:
        return f"MERCURIO_{tipo}"

    return ""

def build_datos_mercurio(expediente, snapshot=None):
    if snapshot is None:
        snapshot = load_snapshot_for_mercurio(expediente.get("id"))

    cliente = build_datos_cliente(expediente, snapshot=snapshot)
    expediente_json = build_datos_expediente(expediente, snapshot=snapshot)

    domicilio = cliente["domicilio_espana"]
    domicilio_parts = parse_domicilio(
        domicilio,
        numero=cliente["numero"],
        piso=cliente["piso"],
    )
    tipo_via_codigo = domicilio_parts["tipo_via_codigo"]
    tipo_via_text = CODIGO_A_TIPO_VIA.get(tipo_via_codigo, "")
    domicilio_limpio = domicilio_parts["domicilio"]
    numero_limpio = domicilio_parts["numero"]
    piso_limpio = domicilio_parts["piso"]

    pais_nacimiento_texto = cliente["pais_nacimiento"]
    nacionalidad_texto = cliente["nacionalidad"]

    tipo_formulario_objetivo = resolve_tipo_formulario_objetivo(expediente_json)
    mapper_codigo = resolve_mapper_codigo(expediente_json, tipo_formulario_objetivo)
    is_ex01_familiar = mapper_codigo == "MERCURIO_EX01_FAMILIAR"

    extranjero = {
        "extPasaporte": cliente["pasaporte"],
        "extNie": cliente["nie"],
        "extApellido1": cliente["primer_apellido"],
        "extApellido2": cliente["segundo_apellido"],
        "extNombre": cliente["nombre"],
        "extSexo": map_sexo(first(cliente.get("sexo"), expediente.get("cliente_sexo"), expediente.get("sexo"))),
        "extFechaNacimiento": format_date_es(cliente["fecha_nacimiento"]),
        "extEstadoCivil": map_estado_civil_mercurio(cliente["estado_civil"]),
        "extLugarNacimiento": cliente["localidad_nacimiento"],
        "extCodigoPaisNacimiento_text": pais_nacimiento_texto,
        "extCodigoNacionalidad_text": nacionalidad_texto,
        "extPadre": cliente["nombre_padre"],
        "extMadre": cliente["nombre_madre"],
        "chkHijosCargo": "true" if _truthy_mercurio_flag(
            _snapshot_datos_especificos(snapshot).get("hijos_menores_edad_escolarizacion")
        ) else "",
    }

    representante = build_datos_representante(snapshot=snapshot)

    if is_ex01_familiar:
        # En EX01 familiar el representante legal del solicitante pertenece
        # a Datos del extranjero/a (ext*), no a Datos del presentador (pre*).
        extranjero.update(build_representante_legal_extranjero(snapshot=snapshot))
        representante = sanitize_presentador_for_ex01_familiar(representante)

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "Quesada Abogados ERP",
            "version": 3,
            "source_model": "expediente_snapshot",
            "snapshot_version": (snapshot.get("metadata") or {}).get("snapshot_db_version") or (snapshot.get("metadata") or {}).get("snapshot_version"),
            "snapshot_hash": (snapshot.get("metadata") or {}).get("snapshot_db_hash") or (snapshot.get("metadata") or {}).get("source_hash"),
            "snapshot_created_at": (snapshot.get("metadata") or {}).get("snapshot_db_created_at") or (snapshot.get("metadata") or {}).get("generated_at"),
        },
        "presentacion": {
            "portal": "MERCURIO",
            "flujo": "BI_PRESENTAR_NUEVA_SOLICITUD",
            "provincia_codigo": expediente_json["provincia_codigo_mercurio"],
            "tipo_formulario_objetivo": tipo_formulario_objetivo,
            "mapper_codigo": mapper_codigo,
        },
        "datos_especificos": _snapshot_datos_especificos(snapshot),
        "expediente": expediente_json,
        "cliente": cliente,
        "familiar": build_datos_familiar_ex01(cliente, snapshot=snapshot) if is_ex01_familiar else {},
        "extranjero": extranjero,
        "domicilio_extranjero": {
            "extTipoVia": tipo_via_codigo,
            "extTipoVia_text": tipo_via_text,
            "extDomicilio": domicilio_limpio,
            "extNumero": numero_limpio,
            "extPiso": piso_limpio,
            "extCodigoProvincia": map_provincia(cliente["provincia"]),
            "extCodigoProvincia_text": cliente["provincia"],
            "extCodigoMunicipio_text": cliente["localidad"],
            "extCodigoLocalidad_text": cliente["localidad"],
            "extCodigoPostal": cliente["codigo_postal"],
            "extTelefono": cliente["telefono"],
            "extTelefonoMovil": cliente["telefono"],
            "extEmail": cliente["email"],
        },
        "notificacion": {
            "notNombreNotificacion": " ".join([
                cliente["nombre"],
                cliente["primer_apellido"],
                cliente["segundo_apellido"],
            ]).strip(),
            "notTipodocumentoNotificacion": "TU" if cliente["nie"] else ("PA" if cliente["pasaporte"] else ""),
            "notNieNotificacion": cliente["nie"] or cliente["pasaporte"] or cliente["dni"],
            "notTelefonoMovilNotificacion": cliente["telefono"],
            "notEmailNotificacion": cliente["email"],
            "notDomicilioNotificacion": domicilio_limpio,
            "notTipoViaNotificacion": tipo_via_codigo,
            "notTipoViaNotificacion_text": tipo_via_text,
            "notNumeroNotificacion": numero_limpio,
            "notPisoNotificacion": piso_limpio,
            "notCodigoProvinciaNotificacion": map_provincia(cliente["provincia"]),
            "notCodigoProvinciaNotificacion_text": cliente["provincia"],
            "notCodigoMunicipioNotificacion_text": cliente["localidad"],
            "notCodigoLocalidadNotificacion_text": cliente["localidad"],
            "notCodigoPostalNotificacion": cliente["codigo_postal"],
        },
        "representante": representante,
    }


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_and_export(expediente_or_id):
    expediente_id = expediente_or_id.get("id") if isinstance(expediente_or_id, dict) else expediente_or_id

    expediente = get_expediente_full(expediente_id)
    if not expediente:
        raise ValueError(f"No existe expediente id={expediente_id}")

    snapshot = load_snapshot_for_mercurio(expediente_id)

    folder = get_presentacion_folder(expediente)

    datos_cliente = build_datos_cliente(expediente, snapshot=snapshot)
    datos_expediente = build_datos_expediente(expediente, snapshot=snapshot)
    datos_mercurio = build_datos_mercurio(expediente, snapshot=snapshot)

    session = {
        "expediente_id": expediente.get("id"),
        "numero_expediente": datos_expediente.get("numero_expediente") or expediente.get("numero_expediente"),
        "numero_expediente_mercurio": datos_expediente.get("numero_expediente_mercurio") or "",
        "cliente_id": datos_cliente.get("id") or expediente.get("cliente_id_real") or expediente.get("cliente_id"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_model": "expediente_snapshot",
        "snapshot_version": (snapshot.get("metadata") or {}).get("snapshot_db_version") or (snapshot.get("metadata") or {}).get("snapshot_version"),
        "snapshot_hash": (snapshot.get("metadata") or {}).get("snapshot_db_hash") or (snapshot.get("metadata") or {}).get("source_hash"),
        "folder": str(folder),
        "datos_mercurio_json": str(folder / "datos_mercurio.json"),
    }

    write_json(folder / "session.json", session)
    write_json(folder / "datos_cliente.json", datos_cliente)
    write_json(folder / "datos_expediente.json", datos_expediente)
    write_json(folder / "datos_mercurio.json", datos_mercurio)

    return {
        "folder": folder,
        "session_path": folder / "session.json",
        "datos_cliente_path": folder / "datos_cliente.json",
        "datos_expediente_path": folder / "datos_expediente.json",
        "datos_mercurio_path": folder / "datos_mercurio.json",
        "datos_mercurio": datos_mercurio,
        "expediente": expediente,
    }

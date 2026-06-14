import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime

from backend.services import expedient_dynamic_form_service as dynamic_form_service
from backend.services import config_service
from backend.services import client_company_service
from backend.services import expedient_contract_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "expedient_snapshots_schema.sql"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def initialize_snapshot_schema():
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def _table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _fetch_expediente(expediente_id):
    with _connect() as conn:
        row = conn.execute(
            """
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
                c.tipo_via AS cliente_tipo_via,
                c.nombre_via AS cliente_nombre_via,
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
            """,
            (int(expediente_id),),
        ).fetchone()

    expediente = _dict(row)
    if not expediente:
        raise ValueError(f"No existe expediente id={expediente_id}")

    return expediente



def _clean_value(value):
    return str(value or "").strip()


def _join_parts(*parts):
    return " ".join(_clean_value(part) for part in parts if _clean_value(part))


def _with_domicilio_calculado(data):
    """Añade campos calculados de domicilio sin eliminar los campos originales.

    Convención de snapshot:
    - via_nombre: solo nombre de la vía. Ej.: REYES CATOLICOS
    - via_completa: tipo + nombre de vía. Ej.: CALLE REYES CATOLICOS
    - domicilio_estructurado: tipo + nombre + número + piso/puerta/escalera cuando existan.
    """
    item = dict(data or {})

    tipo_via = _clean_value(item.get("tipo_via"))
    nombre_via = _clean_value(item.get("nombre_via"))
    numero = _clean_value(item.get("numero"))
    piso = _clean_value(item.get("piso"))
    puerta = _clean_value(item.get("puerta"))
    escalera = _clean_value(item.get("escalera"))

    via_nombre = nombre_via
    via_completa = _join_parts(tipo_via, nombre_via)
    domicilio_estructurado = _join_parts(tipo_via, nombre_via, numero, piso, puerta, escalera)

    item["tipo_via"] = tipo_via
    item["nombre_via"] = nombre_via
    item["via_nombre"] = via_nombre
    item["via_completa"] = via_completa
    item["numero"] = numero
    item["piso"] = piso
    item["puerta"] = puerta
    item["escalera"] = escalera
    item["domicilio_estructurado"] = domicilio_estructurado
    item["domicilio_componentes"] = {
        "tipo_via": tipo_via,
        "nombre_via": nombre_via,
        "via_nombre": via_nombre,
        "via_completa": via_completa,
        "numero": numero,
        "piso": piso,
        "puerta": puerta,
        "escalera": escalera,
        "domicilio_estructurado": domicilio_estructurado,
    }

    return item


def _build_cliente(expediente):
    cliente = {
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
        "nombre_padre": expediente.get("cliente_nombre_padre") or "",
        "nombre_madre": expediente.get("cliente_nombre_madre") or "",
        "estado_civil": expediente.get("cliente_estado_civil") or "",
        "sexo": expediente.get("cliente_sexo") or "",
        "telefono": expediente.get("cliente_telefono") or "",
        "email": expediente.get("cliente_email") or "",
        "tipo_via": expediente.get("cliente_tipo_via") or "",
        "nombre_via": expediente.get("cliente_nombre_via") or "",
        "domicilio_espana": expediente.get("cliente_domicilio_espana") or "",
        "localidad": expediente.get("cliente_localidad") or "",
        "codigo_postal": expediente.get("cliente_codigo_postal") or "",
        "provincia": expediente.get("cliente_provincia") or "",
        "numero": expediente.get("cliente_numero") or "",
        "piso": expediente.get("cliente_piso") or "",
    }

    return _with_domicilio_calculado(cliente)


def _build_expediente(expediente):
    return {
        "id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente") or "",
        "numero_expediente_mercurio": expediente.get("numero_expediente_mercurio") or "",
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_expediente_codigo": expediente.get("tipo_expediente_codigo") or "",
        "tipo_expediente_nombre": expediente.get("tipo_expediente_nombre") or "",
        "subtipo_expediente_id": expediente.get("subtipo_expediente_id"),
        "subtipo_expediente_codigo": expediente.get("subtipo_expediente_codigo") or "",
        "subtipo_expediente_nombre": expediente.get("subtipo_expediente_nombre") or "",
        "subtipo_expediente": expediente.get("subtipo_expediente") or "",
        "estado_presentacion": expediente.get("estado_presentacion") or "",
        "fecha_apertura": expediente.get("fecha_apertura") or "",
        "fecha_presentacion": expediente.get("fecha_presentacion") or "",
        "fecha_resolucion": expediente.get("fecha_resolucion") or "",
        "numero_registro": expediente.get("numero_registro") or "",
        "organo_presentacion": expediente.get("organo_presentacion") or "",
        "provincia": expediente.get("provincia") or "",
        "responsable": expediente.get("responsable") or "",
        "box_folder_path": expediente.get("box_folder_path") or "",
    }


SNAPSHOT_LINKED_CONTACT_FIELDS = [
    "nombre", "primer_apellido", "segundo_apellido", "nie", "pasaporte", "dni",
    "nacionalidad", "fecha_nacimiento", "telefono", "email", "estado_cliente",
    "domicilio_espana", "tipo_via", "nombre_via", "numero", "piso",
    "localidad", "provincia", "codigo_postal",
    "localidad_nacimiento", "pais_nacimiento", "nombre_padre", "nombre_madre",
    "estado_civil", "sexo", "observaciones", "observaciones_internas",
]


def _apply_linked_client_snapshot_data(contacto):
    item = dict(contacto or {})
    if not item.get("cliente_referenciado_id"):
        return item

    for field in SNAPSHOT_LINKED_CONTACT_FIELDS:
        ref_value = item.get(f"ref_{field}")
        if ref_value not in (None, ""):
            item[field] = ref_value

    return item


def _fetch_contactos(cliente_id):
    if not cliente_id:
        return []

    with _connect() as conn:
        if not _table_exists(conn, "cliente_contactos"):
            return []

        rows = conn.execute(
            """
            SELECT
                cc.*,
                cr.nombre AS ref_nombre,
                cr.primer_apellido AS ref_primer_apellido,
                cr.segundo_apellido AS ref_segundo_apellido,
                cr.nie AS ref_nie,
                cr.pasaporte AS ref_pasaporte,
                cr.dni AS ref_dni,
                cr.nacionalidad AS ref_nacionalidad,
                cr.fecha_nacimiento AS ref_fecha_nacimiento,
                cr.telefono AS ref_telefono,
                cr.email AS ref_email,
                cr.estado_cliente AS ref_estado_cliente,
                cr.domicilio_espana AS ref_domicilio_espana,
                cr.tipo_via AS ref_tipo_via,
                cr.nombre_via AS ref_nombre_via,
                cr.numero AS ref_numero,
                cr.piso AS ref_piso,
                cr.localidad AS ref_localidad,
                cr.provincia AS ref_provincia,
                cr.codigo_postal AS ref_codigo_postal,
                cr.localidad_nacimiento AS ref_localidad_nacimiento,
                cr.pais_nacimiento AS ref_pais_nacimiento,
                cr.nombre_padre AS ref_nombre_padre,
                cr.nombre_madre AS ref_nombre_madre,
                cr.estado_civil AS ref_estado_civil,
                cr.sexo AS ref_sexo,
                cr.observaciones AS ref_observaciones,
                cr.observaciones_internas AS ref_observaciones_internas
            FROM cliente_contactos cc
            LEFT JOIN clientes cr ON cr.id = cc.cliente_referenciado_id
            WHERE cc.cliente_id = ?
              AND COALESCE(cc.activo, 1) = 1
            ORDER BY cc.tipo_contacto ASC, cc.parentesco ASC, COALESCE(cr.nombre, cc.nombre) ASC, cc.id ASC
            """,
            (int(cliente_id),),
        ).fetchall()

    contactos = [_apply_linked_client_snapshot_data(_dict(row)) for row in rows]
    return [_with_domicilio_calculado(contacto) for contacto in contactos]

def _split_contactos(contactos):
    empleador_tokens = ("EMPLEADOR", "EMPRESA", "TRABAJO")
    familiares = []
    empleadores = []

    for contacto in contactos:
        tipo = str(contacto.get("tipo_contacto") or "").upper()
        if any(token in tipo for token in empleador_tokens):
            empleadores.append(contacto)
        else:
            familiares.append(contacto)

    return familiares, empleadores



# --- Empresas como entidad propia -------------------------------------------------
# Compatibilidad: no sustituye todavía la clave legacy "empleadores" procedente de
# cliente_contactos. Añade claves nuevas para empresas, representantes y contratos.

def _safe_list_client_companies(cliente_id):
    if not cliente_id:
        return []
    try:
        return client_company_service.list_client_companies(cliente_id, active_only=False) or []
    except Exception:
        # El snapshot debe seguir funcionando aunque el schema de empresas aún no exista
        # en una base antigua o durante una migración parcial.
        return []


def _safe_list_expedient_contracts(expediente_id):
    if not expediente_id:
        return []
    try:
        return expedient_contract_service.list_expedient_contracts(expediente_id) or []
    except Exception:
        return []


def _first_or_none(items):
    return items[0] if items else None


def _build_empresa_from_relation(row):
    row = dict(row or {})
    if not row:
        return {}
    return {
        "client_company_id": row.get("id"),
        "company_id": row.get("company_id"),
        "entity_type": row.get("entity_type") or "",
        "nombre": row.get("company_name") or "",
        "nif_cif": row.get("company_tax_id") or "",
        "tax_id": row.get("company_tax_id") or "",
        "cnae": row.get("cnae_code") or "",
        "cnae_code": row.get("cnae_code") or "",
        "cnae_description": row.get("cnae_description") or "",
        "actividad": row.get("main_activity") or "",
        "main_activity": row.get("main_activity") or "",
        "relationship_type": row.get("relationship_type") or "",
        "is_active": row.get("is_active"),
        "start_date": row.get("start_date") or "",
        "end_date": row.get("end_date") or "",
        "notes": row.get("notes") or "",
    }


def _build_representante_empresa_from_relation(row):
    row = dict(row or {})
    if not row:
        return {}
    return {
        "representative_id": row.get("representative_id"),
        "nombre": row.get("representative_name") or "",
        "documento": row.get("representative_document") or "",
    }


def _build_empresa_from_contract(row):
    row = dict(row or {})
    if not row:
        return {}
    return {
        "contract_id": row.get("id"),
        "client_company_id": row.get("client_company_id"),
        "company_id": row.get("company_id"),
        "entity_type": row.get("entity_type") or "",
        "nombre": row.get("company_name") or "",
        "nif_cif": row.get("company_tax_id") or "",
        "tax_id": row.get("company_tax_id") or "",
        "cnae": row.get("cnae_code") or "",
        "cnae_code": row.get("cnae_code") or "",
        "cnae_description": row.get("cnae_description") or "",
        "actividad": row.get("main_activity") or "",
        "main_activity": row.get("main_activity") or "",
    }


def _build_representante_empresa_from_contract(row):
    row = dict(row or {})
    if not row:
        return {}
    return {
        "representative_id": row.get("representative_id"),
        "nombre": row.get("representative_name") or "",
        "documento": row.get("representative_document") or "",
        "cargo": row.get("representative_position") or "",
    }


def _build_contrato_snapshot(row):
    row = dict(row or {})
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "expedient_id": row.get("expedient_id"),
        "client_company_id": row.get("client_company_id"),
        "is_primary": row.get("is_primary"),
        "tipo_contrato": row.get("contract_type") or "",
        "contract_type": row.get("contract_type") or "",
        "puesto": row.get("contract_position") or "",
        "contract_position": row.get("contract_position") or "",
        "cno": row.get("contract_cno_code") or "",
        "contract_cno_code": row.get("contract_cno_code") or "",
        "contract_cno_description": row.get("contract_cno_description") or "",
        "fecha_inicio": row.get("contract_start_date") or "",
        "contract_start_date": row.get("contract_start_date") or "",
        "fecha_fin": row.get("contract_end_date") or "",
        "contract_end_date": row.get("contract_end_date") or "",
        "jornada": row.get("contract_hours") or "",
        "contract_hours": row.get("contract_hours") or "",
        "salario": row.get("salary_amount") or "",
        "salary_amount": row.get("salary_amount") or "",
        "salary_period": row.get("salary_period") or "",
        "box_contract_path": row.get("box_contract_path") or "",
        "notes": row.get("notes") or "",
    }


def _build_centro_trabajo_snapshot(row):
    row = dict(row or {})
    if not row:
        return {}
    centro = {
        "domicilio_espana": row.get("work_center_address") or "",
        "address": row.get("work_center_address") or "",
        "tipo_via": row.get("work_center_tipo_via") or "",
        "nombre_via": row.get("work_center_nombre_via") or "",
        "numero": row.get("work_center_numero") or "",
        "piso": row.get("work_center_piso") or "",
        "puerta": row.get("work_center_puerta") or "",
        "escalera": row.get("work_center_escalera") or "",
        "codigo_postal": row.get("work_center_postal_code") or "",
        "postal_code": row.get("work_center_postal_code") or "",
        "localidad": row.get("work_center_city") or "",
        "city": row.get("work_center_city") or "",
        "provincia": row.get("work_center_province") or "",
        "province": row.get("work_center_province") or "",
    }
    return _with_domicilio_calculado(centro)


def _build_empresas_snapshot(relaciones):
    return [_build_empresa_from_relation(row) for row in (relaciones or [])]


def _build_formulario(expediente):
    tipo_id = expediente.get("tipo_expediente_id")
    subtipo_id = expediente.get("subtipo_expediente_id")

    context = dynamic_form_service.get_formulario_for_context(tipo_id, subtipo_id)
    formulario = context.get("formulario")
    campos = context.get("campos") or []
    datos_especificos = dynamic_form_service.load_datos_especificos(expediente.get("id"))

    return {
        "formulario": formulario or {},
        "campos": campos,
        "datos_especificos": datos_especificos or {},
    }


def _stable_hash(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_snapshot(expediente_id):
    initialize_snapshot_schema()

    expediente_full = _fetch_expediente(expediente_id)
    cliente_id = expediente_full.get("cliente_id_real") or expediente_full.get("cliente_id")

    contactos = _fetch_contactos(cliente_id)
    familiares, empleadores = _split_contactos(contactos)

    empresas_relaciones = _safe_list_client_companies(cliente_id)
    contratos_expediente = _safe_list_expedient_contracts(expediente_full.get("id"))
    contrato_principal_raw = _first_or_none(contratos_expediente)
    empresa_principal = _build_empresa_from_contract(contrato_principal_raw) or _build_empresa_from_relation(_first_or_none(empresas_relaciones))
    representante_empresa = _build_representante_empresa_from_contract(contrato_principal_raw) or _build_representante_empresa_from_relation(_first_or_none(empresas_relaciones))

    formulario_data = _build_formulario(expediente_full)
    representante = config_service.get_representante_config()

    snapshot = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "Quesada Abogados ERP",
            "snapshot_version": 1,
        },
        "expediente": _build_expediente(expediente_full),
        "cliente": _build_cliente(expediente_full),
        "contactos": familiares,
        "empleadores": empleadores,
        "empresas": _build_empresas_snapshot(empresas_relaciones),
        "empresa_principal": empresa_principal,
        "representante_empresa": representante_empresa,
        "contratos": [_build_contrato_snapshot(row) for row in contratos_expediente],
        "contrato": _build_contrato_snapshot(contrato_principal_raw),
        "centro_trabajo": _build_centro_trabajo_snapshot(contrato_principal_raw),
        "representante": representante,
        "formulario": formulario_data.get("formulario") or {},
        "campos": formulario_data.get("campos") or [],
        "datos_especificos": formulario_data.get("datos_especificos") or {},
    }

    snapshot["metadata"]["source_hash"] = _stable_hash(snapshot)

    return snapshot


def validate_snapshot(snapshot):
    errors = []

    expediente = snapshot.get("expediente") or {}
    cliente = snapshot.get("cliente") or {}

    if not expediente.get("id"):
        errors.append("Falta expediente.id")

    if not cliente.get("id"):
        errors.append("Falta cliente.id")

    if not cliente.get("nombre"):
        errors.append("Falta nombre del cliente")

    if not expediente.get("tipo_expediente_id"):
        errors.append("Falta tipo de expediente")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def _next_version(expediente_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT MAX(version) AS max_version
            FROM expediente_snapshots
            WHERE expediente_id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

    return int((row["max_version"] if row else 0) or 0) + 1


def save_snapshot(expediente_id, created_by="ERP"):
    initialize_snapshot_schema()

    snapshot = build_snapshot(expediente_id)
    validation = validate_snapshot(snapshot)

    version = _next_version(expediente_id)
    source_hash = snapshot.get("metadata", {}).get("source_hash") or _stable_hash(snapshot)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO expediente_snapshots (
                expediente_id,
                version,
                snapshot_json,
                source_hash,
                validated,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                int(expediente_id),
                int(version),
                json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
                source_hash,
                1 if validation["valid"] else 0,
                created_by,
            ),
        )
        conn.commit()

    return {
        "id": cur.lastrowid,
        "expediente_id": int(expediente_id),
        "version": version,
        "validated": validation["valid"],
        "errors": validation["errors"],
        "source_hash": source_hash,
        "snapshot": snapshot,
    }


def load_latest_snapshot(expediente_id):
    initialize_snapshot_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM expediente_snapshots
            WHERE expediente_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (int(expediente_id),),
        ).fetchone()

    item = _dict(row)
    if not item:
        return None

    item["snapshot"] = json.loads(item.get("snapshot_json") or "{}")
    return item




def _snapshot_business_payload(snapshot):
    """
    Devuelve la parte funcional del snapshot para comparar vigencia.

    Excluye metadata porque contiene generated_at/versiones y cambiaría aunque
    los datos reales del expediente no hayan cambiado.
    """
    snapshot = dict(snapshot or {})
    snapshot.pop("metadata", None)
    return snapshot


def snapshot_business_hash(snapshot):
    return _stable_hash(_snapshot_business_payload(snapshot))


def snapshot_matches_current(expediente_id, snapshot):
    """Comprueba si un snapshot guardado coincide con la ficha viva actual."""
    if not snapshot:
        return False
    current_snapshot = build_snapshot(expediente_id)
    return snapshot_business_hash(snapshot) == snapshot_business_hash(current_snapshot)


def ensure_current_snapshot(expediente_id, created_by="ERP_AUTO_REFRESH"):
    """
    Garantiza que existe un snapshot validado y actualizado para el expediente.

    Si no hay snapshot, o el último ya no coincide con la ficha/datos dinámicos
    actuales, crea una nueva versión persistida. Esto permite que Mercurio use
    el mismo criterio que los formularios: siempre partir del snapshot vigente.
    """
    latest = load_latest_snapshot(expediente_id)

    if latest and int(latest.get("validated") or 0) == 1:
        try:
            if snapshot_matches_current(expediente_id, latest.get("snapshot") or {}):
                latest["generated_now"] = False
                return latest
        except Exception:
            pass

    result = save_snapshot(expediente_id, created_by=created_by)
    latest = load_latest_snapshot(expediente_id)
    if latest:
        latest["generated_now"] = True
        latest["generation_result"] = result
    return latest


def list_snapshots(expediente_id):
    initialize_snapshot_schema()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, expediente_id, version, source_hash, validated, created_by, created_at
            FROM expediente_snapshots
            WHERE expediente_id = ?
            ORDER BY version DESC
            """,
            (int(expediente_id),),
        ).fetchall()

    return [_dict(row) for row in rows]
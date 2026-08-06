import csv
import os
import subprocess
import sys
import sqlite3
import uuid
from pathlib import Path
from datetime import date, datetime

import flet as ft

from backend.services.master_data_service import (
    get_nacionalidades,
    get_paises_nombres,
    get_provincias_nombres,
    get_localidades_by_provincia,
)

from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_detail_section import detail_section
from frontend.components.app_badge import status_badge
from frontend.components.app_table import app_table
from frontend.components.app_empty_state import empty_state
from frontend.components.app_autocomplete import AppAutocomplete
from backend.services.client_administrative_status_service import (
    get_current_authorization,
    list_administrative_situations,
    list_client_authorizations,
)
from backend.services.expedient_traceability_service import (
    get_admin_document,
)
from backend.services import document_viewer_service

try:
    from frontend.views.company_detail_view import company_detail_view
except Exception:
    company_detail_view = None

try:
    from backend.services import company_service, client_company_service, employment_contract_service
except Exception:
    company_service = None
    client_company_service = None
    employment_contract_service = None

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
CATALOGOS_MERCURIO_CSV_DIR = Path(__file__).resolve().parents[2] / "database" / "catalogos_mercurio" / "csv"

CONTACT_TYPES = [
    "Familiar",
    "Empleador / Empresa",
]

CONTACT_RELATIONSHIPS = [
    "Cónyuge",
    "Pareja",
    "Padre",
    "Madre",
    "Hijo/a",
    "Hermano/a",
    "Abuelo/a",
    "Nieto/a",
    "Tutor/a",
    "Tutelado/a",
    "Representante legal",
    "Representado/a",
    "Ascendiente",
    "Descendiente",
    "Otro familiar",
]

RELATIONSHIP_INVERSES = {
    "Cónyuge": "Cónyuge",
    "Pareja": "Pareja",
    "Padre": "Hijo/a",
    "Madre": "Hijo/a",
    "Hijo/a": "Padre",
    "Hermano/a": "Hermano/a",
    "Abuelo/a": "Nieto/a",
    "Nieto/a": "Abuelo/a",
    "Tutor/a": "Tutelado/a",
    "Tutelado/a": "Tutor/a",
    "Representante legal": "Representado/a",
    "Representado/a": "Representante legal",
    "Ascendiente": "Descendiente",
    "Descendiente": "Ascendiente",
    "Otro familiar": "Otro familiar",
}

def _inverse_parentesco(parentesco):
    return RELATIONSHIP_INVERSES.get(str(parentesco or "").strip(), "")

VIA_TYPES = [
    "CALLE",
    "AVENIDA",
    "PLAZA",
    "PASEO",
    "CARRETERA",
    "CAMINO",
    "TRAVESÍA",
    "RONDA",
    "URBANIZACIÓN",
    "POLÍGONO",
    "OTRO",
]


FICHA_FIELDS = [
    "nombre",
    "primer_apellido",
    "segundo_apellido",
    "nie",
    "pasaporte",
    "dni",
    "nacionalidad",
    "fecha_nacimiento",
    "fecha_caducidad_residencia",
    "telefono",
    "email",
    "estado_cliente",
    "domicilio_espana",
    "localidad",
    "provincia",
    "codigo_postal",
    "localidad_nacimiento",
    "pais_nacimiento",
    "nombre_padre",
    "nombre_madre",
    "estado_civil",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in rows]
    except Exception:
        return []


def _ensure_column(conn, table_name, column_name, definition="TEXT"):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _load_catalog_options(filename, label_code="Código"):
    path = CATALOGOS_MERCURIO_CSV_DIR / filename
    if not path.exists():
        return []

    options = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                codigo = str(row.get("codigo") or "").strip()
                descripcion = str(row.get("descripcion") or "").strip()
                activo = str(row.get("activo") or "1").strip()
                if activo in {"0", "False", "false"}:
                    continue
                if not codigo and not descripcion:
                    continue
                if codigo and descripcion:
                    options.append(f"{descripcion} · {label_code} {codigo}")
                else:
                    options.append(descripcion or codigo)
    except Exception:
        return []

    return options


def _extract_catalog_code(value):
    raw = str(value or "").strip()
    if " · " not in raw:
        return raw
    tail = raw.rsplit(" · ", 1)[-1].strip()
    parts = tail.split()
    return parts[-1].strip() if parts else tail


def _extract_catalog_description(value):
    raw = str(value or "").strip()
    if " · " not in raw:
        return raw
    return raw.split(" · ", 1)[0].strip()


def _text_input_erp(label, width):
    return ft.TextField(
        label=label,
        width=width,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color="#18BFEA",
    )


def _via_type_dropdown(label="Tipo de vía", width=170):
    return ft.Dropdown(
        label=label,
        width=width,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color="#18BFEA",
        options=[ft.dropdown.Option(item) for item in VIA_TYPES],
    )


def _dialog_section(title, icon, controls):
    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=14,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(icon, size=18, color="#0057B8"),
                            bgcolor="#EAF3FF",
                            border_radius=18,
                            width=34,
                            height=34,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                *controls,
            ],
            spacing=12,
        ),
    )


def _themed_dialog_content(title, subtitle, sections, width=930, height=640):
    return ft.Container(
        width=width,
        height=height,
        bgcolor="#F8FAFC",
        border_radius=18,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=14,
                    padding=14,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.BUSINESS, size=24, color="#0057B8"),
                                bgcolor="#FFFFFF",
                                border_radius=22,
                                width=44,
                                height=44,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(subtitle, size=13, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                ft.Column(
                    controls=sections,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            spacing=12,
        ),
    )


def _ensure_client_contacts_schema():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cliente_contactos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                tipo_contacto TEXT NOT NULL,
                parentesco TEXT,
                cliente_referenciado_id INTEGER,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT,
                nie TEXT,
                pasaporte TEXT,
                dni TEXT,
                nacionalidad TEXT,
                fecha_nacimiento TEXT,
                telefono TEXT,
                email TEXT,
                estado_cliente TEXT,
                domicilio_espana TEXT,
                localidad TEXT,
                provincia TEXT,
                codigo_postal TEXT,
                localidad_nacimiento TEXT,
                pais_nacimiento TEXT,
                nombre_padre TEXT,
                nombre_madre TEXT,
                estado_civil TEXT,
                sexo TEXT,
                actividad TEXT,
                cnae TEXT,
                cno_sepe TEXT,
                observaciones TEXT,
                observaciones_internas TEXT,
                relacion_uuid TEXT,
                relacion_origen TEXT DEFAULT 'manual',
                sincronizar_bidireccional INTEGER DEFAULT 1,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
                FOREIGN KEY (cliente_referenciado_id) REFERENCES clientes(id)
            )
            """
        )
        for column in ["actividad", "cnae", "cno_sepe", "puerta", "escalera", "relacion_uuid", "relacion_origen"]:
            _ensure_column(conn, "cliente_contactos", column, "TEXT")
        _ensure_column(conn, "cliente_contactos", "sincronizar_bidireccional", "INTEGER DEFAULT 1")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente
            ON cliente_contactos(cliente_id, activo, tipo_contacto)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cliente_contactos_relacion_uuid
            ON cliente_contactos(relacion_uuid, activo)
            """
        )
        conn.commit()



def _safe_master_values(loader):
    try:
        values = loader()
        return values or []
    except Exception:
        return []


def _get_available_clients_for_reference(current_cliente_id):
    try:
        with _connect() as conn:
            if not _table_exists(conn, "clientes"):
                return []
            rows = conn.execute(
                """
                SELECT
                    id, nombre, primer_apellido, segundo_apellido, nie, pasaporte, dni,
                    nacionalidad, fecha_nacimiento, telefono, email, estado_cliente,
                    domicilio_espana, localidad, provincia, codigo_postal,
                    localidad_nacimiento, pais_nacimiento, nombre_padre, nombre_madre,
                    estado_civil, sexo, observaciones, observaciones_internas
                FROM clientes
                WHERE COALESCE(activo, 1) = 1
                  AND id != ?
                ORDER BY nombre ASC, primer_apellido ASC, segundo_apellido ASC
                """,
                (int(current_cliente_id or 0),),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _contact_reference_label(cliente):
    nombre = _nombre_completo(cliente)
    documento = cliente.get("nie") or cliente.get("pasaporte") or cliente.get("dni") or ""
    return f"{cliente.get('id')} - {nombre}" + (f" · {documento}" if documento else "")


def _id_from_reference_label(value):
    raw = str(value or "").strip()
    if " - " not in raw:
        return None
    try:
        return int(raw.split(" - ", 1)[0])
    except Exception:
        return None


def _copy_client_to_contact_data(cliente):
    return {
        "nombre": cliente.get("nombre") or "",
        "primer_apellido": cliente.get("primer_apellido") or "",
        "segundo_apellido": cliente.get("segundo_apellido") or "",
        "nie": cliente.get("nie") or "",
        "pasaporte": cliente.get("pasaporte") or "",
        "dni": cliente.get("dni") or "",
        "nacionalidad": cliente.get("nacionalidad") or "",
        "fecha_nacimiento": cliente.get("fecha_nacimiento") or "",
        "telefono": cliente.get("telefono") or "",
        "email": cliente.get("email") or "",
        "estado_cliente": cliente.get("estado_cliente") or "",
        "domicilio_espana": cliente.get("domicilio_espana") or "",
        "tipo_via": cliente.get("tipo_via") or "",
        "nombre_via": cliente.get("nombre_via") or "",
        "numero": cliente.get("numero") or "",
        "piso": cliente.get("piso") or "",
        "localidad": cliente.get("localidad") or "",
        "provincia": cliente.get("provincia") or "",
        "codigo_postal": cliente.get("codigo_postal") or "",
        "localidad_nacimiento": cliente.get("localidad_nacimiento") or "",
        "pais_nacimiento": cliente.get("pais_nacimiento") or "",
        "nombre_padre": cliente.get("nombre_padre") or "",
        "nombre_madre": cliente.get("nombre_madre") or "",
        "estado_civil": cliente.get("estado_civil") or "",
        "sexo": cliente.get("sexo") or "",
        "observaciones": cliente.get("observaciones") or "",
        "observaciones_internas": cliente.get("observaciones_internas") or "",
    }


LINKED_CLIENT_CONTACT_FIELDS = [
    "nombre", "primer_apellido", "segundo_apellido", "nie", "pasaporte", "dni",
    "nacionalidad", "fecha_nacimiento", "telefono", "email", "estado_cliente",
    "domicilio_espana", "tipo_via", "nombre_via", "numero", "piso",
    "localidad", "provincia", "codigo_postal",
    "localidad_nacimiento", "pais_nacimiento", "nombre_padre", "nombre_madre",
    "estado_civil", "sexo", "observaciones", "observaciones_internas",
]


def _apply_linked_client_live_data(contact):
    """
    Si un contacto referencia a otro cliente, la fuente viva de los datos
    personales es clientes, no la copia histórica guardada en cliente_contactos.

    Conserva los campos propios de la relación: id, cliente_id, parentesco,
    tipo_contacto, relacion_uuid, origen, activo, observaciones específicas si
    no existen en el cliente, etc.
    """
    item = dict(contact or {})
    if not item.get("cliente_referenciado_id"):
        return item

    for field in LINKED_CLIENT_CONTACT_FIELDS:
        ref_value = item.get(f"ref_{field}")
        if ref_value not in (None, ""):
            item[field] = ref_value

    return item


def _get_client_contacts(cliente_id):
    _ensure_client_contacts_schema()
    try:
        with _connect() as conn:
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
                ORDER BY cc.tipo_contacto ASC, cc.parentesco ASC, COALESCE(cr.nombre, cc.nombre) ASC, cc.id DESC
                """,
                (int(cliente_id),),
            ).fetchall()
            return [_apply_linked_client_live_data(dict(row)) for row in rows]
    except Exception:
        return []

CONTACT_FIELDS = [
    "cliente_id", "tipo_contacto", "parentesco", "cliente_referenciado_id",
    "nombre", "primer_apellido", "segundo_apellido", "nie", "pasaporte", "dni",
    "nacionalidad", "fecha_nacimiento", "telefono", "email", "estado_cliente",
    "domicilio_espana", "tipo_via", "nombre_via", "numero", "piso", "puerta", "escalera",
    "localidad", "provincia", "codigo_postal",
    "localidad_nacimiento", "pais_nacimiento", "nombre_padre", "nombre_madre",
    "estado_civil", "sexo", "actividad", "cnae", "cno_sepe",
    "observaciones", "observaciones_internas",
    "relacion_uuid", "relacion_origen", "sincronizar_bidireccional",
]


def _get_client_snapshot_for_contact(conn, client_id):
    if not client_id:
        return None
    row = conn.execute(
        """
        SELECT
            id, nombre, primer_apellido, segundo_apellido, nie, pasaporte, dni,
            nacionalidad, fecha_nacimiento, telefono, email, estado_cliente,
            domicilio_espana, tipo_via, nombre_via, numero, piso,
            localidad, provincia, codigo_postal,
            localidad_nacimiento, pais_nacimiento,
            nombre_padre, nombre_madre, estado_civil, sexo,
            observaciones, observaciones_internas
        FROM clientes
        WHERE id = ?
          AND COALESCE(activo, 1) = 1
        """,
        (int(client_id),),
    ).fetchone()
    return dict(row) if row else None


def _get_client_for_navigation(client_id):
    if not client_id:
        return None
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM clientes
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (int(client_id),),
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _contact_data_from_client(cliente):
    data = _copy_client_to_contact_data(cliente or {})
    data.setdefault("tipo_via", (cliente or {}).get("tipo_via") or "")
    data.setdefault("nombre_via", (cliente or {}).get("nombre_via") or "")
    data.setdefault("numero", (cliente or {}).get("numero") or "")
    data.setdefault("piso", (cliente or {}).get("piso") or "")
    data["puerta"] = ""
    data["escalera"] = ""
    data["actividad"] = ""
    data["cnae"] = ""
    data["cno_sepe"] = ""
    return data


def _get_contact_by_id(conn, contact_id):
    if not contact_id:
        return None
    row = conn.execute(
        "SELECT * FROM cliente_contactos WHERE id = ?",
        (int(contact_id),),
    ).fetchone()
    return dict(row) if row else None


def _find_inverse_contact(conn, relacion_uuid, exclude_id=None):
    if not relacion_uuid:
        return None

    params = [relacion_uuid]
    exclude_sql = ""
    if exclude_id:
        exclude_sql = "AND id != ?"
        params.append(int(exclude_id))

    row = conn.execute(
        f"""
        SELECT *
        FROM cliente_contactos
        WHERE relacion_uuid = ?
          {exclude_sql}
          AND COALESCE(activo, 1) = 1
        ORDER BY id ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict(row) if row else None


def _insert_contact_row(conn, data):
    payload = dict(data)
    payload.setdefault("sincronizar_bidireccional", 1)
    fields = [field for field in CONTACT_FIELDS if field in payload]
    cursor = conn.execute(
        f"""
        INSERT INTO cliente_contactos ({", ".join(fields)}, updated_at)
        VALUES ({", ".join("?" for _ in fields)}, CURRENT_TIMESTAMP)
        """,
        [payload.get(field) for field in fields],
    )
    return cursor.lastrowid


def _update_contact_row(conn, contact_id, data):
    payload = dict(data)
    fields = [field for field in CONTACT_FIELDS if field in payload and field != "cliente_id"]
    if not fields:
        return
    conn.execute(
        f"""
        UPDATE cliente_contactos
        SET {", ".join(f"{field} = ?" for field in fields)},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [payload.get(field) for field in fields] + [int(contact_id)],
    )


def _build_inverse_contact_data(conn, data, relacion_uuid):
    origen_id = data.get("cliente_id")
    destino_id = data.get("cliente_referenciado_id")
    origen_cliente = _get_client_snapshot_for_contact(conn, origen_id)
    if not origen_cliente or not destino_id:
        return None

    inverse = _contact_data_from_client(origen_cliente)
    inverse.update({
        "cliente_id": int(destino_id),
        "tipo_contacto": data.get("tipo_contacto") or "Familiar",
        "parentesco": _inverse_parentesco(data.get("parentesco")) or "",
        "cliente_referenciado_id": int(origen_id),
        "relacion_uuid": relacion_uuid,
        "relacion_origen": "inverse",
        "sincronizar_bidireccional": 1,
    })
    return inverse


def _sync_inverse_contact(conn, contact_id, data):
    if (data.get("tipo_contacto") or "") != "Familiar":
        return
    if not data.get("cliente_id") or not data.get("cliente_referenciado_id"):
        return
    if int(data.get("cliente_id")) == int(data.get("cliente_referenciado_id")):
        return
    if int(data.get("sincronizar_bidireccional", 1) or 0) != 1:
        return

    relacion_uuid = data.get("relacion_uuid") or uuid.uuid4().hex
    if not data.get("relacion_uuid"):
        conn.execute(
            """
            UPDATE cliente_contactos
            SET relacion_uuid = ?,
                relacion_origen = COALESCE(NULLIF(relacion_origen, ''), 'direct'),
                sincronizar_bidireccional = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (relacion_uuid, int(contact_id)),
        )

    inverse_data = _build_inverse_contact_data(conn, data, relacion_uuid)
    if not inverse_data:
        return

    inverse = _find_inverse_contact(conn, relacion_uuid, exclude_id=contact_id)
    if inverse:
        _update_contact_row(conn, inverse["id"], inverse_data)
        return

    _insert_contact_row(conn, inverse_data)


def _archive_inverse_contact(conn, contact):
    if not contact:
        return
    relacion_uuid = contact.get("relacion_uuid")
    if relacion_uuid:
        conn.execute(
            """
            UPDATE cliente_contactos
            SET activo = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE relacion_uuid = ?
              AND id != ?
            """,
            (relacion_uuid, int(contact.get("id"))),
        )


def _save_client_contact(data, contact_id=None):
    _ensure_client_contacts_schema()
    payload = dict(data)
    payload["sincronizar_bidireccional"] = int(payload.get("sincronizar_bidireccional", 1) or 0)

    with _connect() as conn:
        existing = _get_contact_by_id(conn, contact_id) if contact_id else None
        previous_ref = existing.get("cliente_referenciado_id") if existing else None
        previous_uuid = existing.get("relacion_uuid") if existing else None

        if payload.get("cliente_referenciado_id"):
            payload["relacion_uuid"] = previous_uuid or payload.get("relacion_uuid") or uuid.uuid4().hex
            payload.setdefault("relacion_origen", existing.get("relacion_origen") if existing else "direct")
        else:
            payload["relacion_uuid"] = previous_uuid or payload.get("relacion_uuid") or ""
            payload.setdefault("relacion_origen", existing.get("relacion_origen") if existing else "manual")

        if existing:
            _update_contact_row(conn, contact_id, payload)
            saved_id = int(contact_id)
        else:
            saved_id = _insert_contact_row(conn, payload)

        if payload.get("cliente_referenciado_id"):
            _sync_inverse_contact(conn, saved_id, payload)
        elif previous_ref:
            _archive_inverse_contact(conn, {**existing, "id": saved_id})

        conn.commit()


def _archive_client_contact(contact_id):
    _ensure_client_contacts_schema()
    with _connect() as conn:
        contact = _get_contact_by_id(conn, contact_id)
        if not contact:
            return
        conn.execute(
            """
            UPDATE cliente_contactos
            SET activo = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(contact_id),),
        )
        _archive_inverse_contact(conn, contact)
        conn.commit()


def _nombre_completo(client):
    return " ".join(
        [
            client.get("nombre") or "",
            client.get("primer_apellido") or "",
            client.get("segundo_apellido") or "",
        ]
    ).strip() or "Cliente sin nombre"


def _fecha_display(value):
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def _money(value):
    try:
        return f"{float(value or 0):.2f} €"
    except Exception:
        return "0.00 €"


def _residence_expiry_origin_label(value):
    origin = str(value or "").strip().upper()

    labels = {
        "MANUAL": "Introducción manual",
        "RESOLUCION_FAVORABLE":
            "Resolución favorable",
    }

    return labels.get(
        origin,
        str(value or "").strip(),
    )


def _get_residence_expiry_expedient_number(client):
    expediente_id = client.get(
        "fecha_caducidad_expediente_id"
    )

    if not expediente_id:
        return ""

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT numero_expediente
                FROM expedientes
                WHERE id = ?
                """,
                (int(expediente_id),),
            ).fetchone()

            if row:
                return (
                    row["numero_expediente"]
                    or f"Expediente #{expediente_id}"
                )

    except Exception:
        pass

    return f"Expediente #{expediente_id}"


def _calcular_edad(fecha_nacimiento):
    if not fecha_nacimiento:
        return ""
    try:
        nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        hoy = date.today()
        edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        return str(edad)
    except ValueError:
        return ""


def _porcentaje_ficha(client):
    total = len(FICHA_FIELDS)
    completados = sum(1 for field in FICHA_FIELDS if client.get(field))
    return int((completados / total) * 100)


def _progress_color(percent):
    if percent >= 80:
        return "#027A48"
    if percent >= 50:
        return "#B54708"
    return "#B42318"


def _header(client):
    percent = _porcentaje_ficha(client)

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Ficha del cliente", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Text(_nombre_completo(client), size=15, color=Q_MUTED),
                    ],
                    spacing=3,
                    expand=True,
                ),
                ft.Column(
                    controls=[
                        status_badge(client.get("estado_cliente") or "-"),
                        ft.Text(
                            f"Ficha completa: {percent}%",
                            size=12,
                            color=_progress_color(percent),
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                    spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
    )


def _administrative_location_label(value):
    labels = {
        "EN_ESPANA": "España",
        "EN_ORIGEN": "País de origen",
        "EN_OTRO_PAIS": "Otro país",
        "DESCONOCIDA": "Desconocida",
    }

    raw = str(value or "").strip().upper()

    return labels.get(
        raw,
        str(value or "").strip() or "No informada",
    )


def _administrative_situation_name(client):
    situation_id = client.get(
        "situacion_administrativa_id"
    )

    if not situation_id:
        return "No informada"

    try:
        situations = list_administrative_situations(
            active_only=False
        )
    except TypeError:
        try:
            situations = list_administrative_situations()
        except Exception:
            situations = []
    except Exception:
        situations = []

    for situation in situations:
        try:
            if int(
                situation.get("id")
                or 0
            ) == int(situation_id):
                return (
                    situation.get("nombre")
                    or "No informada"
                )
        except Exception:
            continue

    return "No informada"


def _years_months_days_from_date(value):
    if not value:
        return ""

    try:
        start = datetime.strptime(
            str(value)[:10],
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return ""

    today = date.today()

    if start > today:
        return "Fecha futura"

    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day

    if days < 0:
        months -= 1

        previous_month = (
            today.month - 1
            if today.month > 1
            else 12
        )

        previous_year = (
            today.year
            if today.month > 1
            else today.year - 1
        )

        if previous_month == 12:
            next_month = date(
                previous_year + 1,
                1,
                1,
            )
        else:
            next_month = date(
                previous_year,
                previous_month + 1,
                1,
            )

        current_month = date(
            previous_year,
            previous_month,
            1,
        )

        days += (
            next_month - current_month
        ).days

    if months < 0:
        years -= 1
        months += 12

    return (
        f"{years} años, "
        f"{months} meses y "
        f"{days} días"
    )


def _administrative_status_badge(
    text,
    foreground,
    background,
):
    return ft.Container(
        content=ft.Text(
            text,
            size=11,
            color=foreground,
            weight=ft.FontWeight.BOLD,
            no_wrap=True,
        ),
        bgcolor=background,
        border_radius=18,
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=6,
        ),
        height=30,
        alignment=ft.alignment.Alignment(
            0,
            0,
        ),
    )


def _administrative_info_block(
    label,
    value,
    *,
    secondary="",
    width=250,
    selectable=False,
):
    controls = [
        ft.Text(
            label,
            size=11,
            color=Q_MUTED,
        ),
        ft.Text(
            str(value or "No informado"),
            size=14,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
            selectable=selectable,
        ),
    ]

    if secondary:
        controls.append(
            ft.Text(
                str(secondary),
                size=12,
                color=Q_MUTED,
            )
        )

    return ft.Container(
        width=width,
        content=ft.Column(
            controls=controls,
            spacing=3,
            tight=True,
        ),
    )


def _authorization_status(
    authorization,
):
    if not authorization:
        return (
            "SIN AUTORIZACIÓN INFORMADA",
            "#475467",
            "#F2F4F7",
        )

    expiry_raw = authorization.get(
        "fecha_vigencia_hasta"
    )

    if not expiry_raw:
        return (
            "VIGENCIA NO INFORMADA",
            "#B54708",
            "#FFFAEB",
        )

    try:
        expiry = datetime.strptime(
            str(expiry_raw)[:10],
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return (
            "FECHA NO VÁLIDA",
            "#B42318",
            "#FEF3F2",
        )

    days = (
        expiry - date.today()
    ).days

    if days < 0:
        return (
            "AUTORIZACIÓN CADUCADA",
            "#B42318",
            "#FEF3F2",
        )

    if days <= 30:
        return (
            f"CADUCA EN {days} DÍAS",
            "#B54708",
            "#FFFAEB",
        )

    return (
        "AUTORIZACIÓN VIGENTE",
        "#027A48",
        "#ECFDF3",
    )


def _legal_residence_warning(client):
    continuity = str(
        client.get(
            "continuidad_residencia_legal"
        )
        or ""
    ).strip().upper()

    verification = str(
        client.get(
            "estado_verificacion_residencia_legal"
        )
        or ""
    ).strip().upper()

    if continuity == "INTERRUMPIDA":
        return (
            "Residencia legal interrumpida",
            "#B42318",
            "#FEF3F2",
        )

    if continuity == "POSIBLE INTERRUPCIÓN":
        return (
            "Posible interrupción pendiente de revisión",
            "#B54708",
            "#FFFAEB",
        )

    if continuity in {
        "",
        "NO DETERMINADA",
        "PENDIENTE DE VERIFICAR",
    }:
        return (
            "Continuidad pendiente de verificar",
            "#B54708",
            "#FFFAEB",
        )

    if verification == "DECLARADA POR EL CLIENTE":
        return (
            "Dato declarado por el cliente",
            "#175CD3",
            "#EFF8FF",
        )

    if verification in {
        "",
        "PENDIENTE DE DOCUMENTACIÓN",
        "REQUIERE REVISIÓN",
    }:
        return (
            "Residencia legal sin acreditar documentalmente",
            "#B54708",
            "#FFFAEB",
        )

    return None


def _administrative_summary_card(
    client,
    page=None,
    on_open_expediente=None,
):
    try:
        authorization = get_current_authorization(
            client.get("id")
        )
    except Exception:
        authorization = None

    status_text, status_fg, status_bg = (
        _authorization_status(
            authorization
        )
    )

    authorization_name = (
        authorization.get(
            "autorizacion_nombre"
        )
        if authorization
        else None
    )

    authorization_from = (
        authorization.get(
            "fecha_vigencia_desde"
        )
        if authorization
        else None
    )

    authorization_to = (
        authorization.get(
            "fecha_vigencia_hasta"
        )
        if authorization
        else None
    )

    start_residence = client.get(
        "fecha_inicio_residencia_legal"
    )

    seniority = (
        _years_months_days_from_date(
            start_residence
        )
    )

    legal_warning = (
        _legal_residence_warning(
            client
        )
    )

    warning_controls = []

    if legal_warning:
        text, foreground, background = (
            legal_warning
        )

        warning_controls.append(
            _administrative_status_badge(
                text,
                foreground,
                background,
            )
        )

    if (
        client.get(
            "fecha_inicio_residencia_legal_aproximada"
        )
    ):
        warning_controls.append(
            _administrative_status_badge(
                "FECHA INICIAL APROXIMADA",
                "#175CD3",
                "#EFF8FF",
            )
        )

    return _section_card(
        "Situación administrativa",
        ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        _administrative_status_badge(
                            status_text,
                            status_fg,
                            status_bg,
                        ),
                        *warning_controls,
                    ],
                    spacing=8,
                    wrap=True,
                    tight=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),

                ft.Row(
                    controls=[
                        _administrative_info_block(
                            "Localización actual",
                            _administrative_location_label(
                                client.get(
                                    "localizacion_actual"
                                )
                            ),
                            secondary=(
                                client.get(
                                    "pais_localizacion_actual"
                                )
                                or ""
                            ),
                            width=220,
                        ),
                        _administrative_info_block(
                            "Situación administrativa",
                            _administrative_situation_name(
                                client
                            ),
                            width=300,
                        ),
                        _administrative_info_block(
                            "Soporte NIE/TIE",
                            client.get(
                                "numero_soporte_nie"
                            )
                            or "No informado",
                            width=220,
                            selectable=True,
                        ),
                    ],
                    spacing=18,
                    wrap=True,
                    tight=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.START
                    ),
                ),

                ft.Divider(),

                ft.Text(
                    "Autorización vigente",
                    size=12,
                    color=Q_MUTED,
                ),

                ft.Text(
                    authorization_name
                    or (
                        "Situación administrativa "
                        "sin autorización actual asociada"
                    ),
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),

                ft.Text(
                    (
                        "Vigencia: "
                        f"{_fecha_display(authorization_from) or '-'}"
                        " — "
                        f"{_fecha_display(authorization_to) or '-'}"
                    ),
                    size=12,
                    color=Q_MUTED,
                ),

                _authorization_origin_actions(
                    authorization,
                    page=page,
                    on_open_expediente=(
                        on_open_expediente
                    ),
                ),

                ft.Divider(),

                ft.Text(
                    "Residencia legal computable para nacionalidad",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),

                ft.Row(
                    controls=[
                        _administrative_info_block(
                            "Inicio computable",
                            _fecha_display(
                                start_residence
                            )
                            or "No informado",
                            width=220,
                        ),
                        _administrative_info_block(
                            "Antigüedad",
                            seniority
                            or "No calculable",
                            width=260,
                        ),
                        _administrative_info_block(
                            "Continuidad",
                            client.get(
                                "continuidad_residencia_legal"
                            )
                            or "No determinada",
                            width=280,
                        ),
                    ],
                    spacing=18,
                    wrap=True,
                    tight=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.START
                    ),
                ),

                ft.Row(
                    controls=[
                        _administrative_info_block(
                            "Estado de verificación",
                            client.get(
                                "estado_verificacion_residencia_legal"
                            )
                            or "No informado",
                            width=300,
                        ),
                        _administrative_info_block(
                            "Fecha de verificación",
                            _fecha_display(
                                client.get(
                                    "fecha_verificacion_residencia_legal"
                                )
                            )
                            or "No informada",
                            width=220,
                        ),
                        _administrative_info_block(
                            "Origen del dato",
                            client.get(
                                "origen_residencia_legal"
                            )
                            or "No informado",
                            width=260,
                        ),
                    ],
                    spacing=18,
                    wrap=True,
                    tight=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.START
                    ),
                ),

                ft.Text(
                    client.get(
                        "observaciones_residencia_legal"
                    )
                    or "",
                    size=12,
                    color=Q_MUTED,
                    visible=bool(
                        client.get(
                            "observaciones_residencia_legal"
                        )
                    ),
                ),
            ],
            spacing=12,
            tight=True,
        ),
    )


def _show_authorization_origin_message(
    page,
    message,
):
    if page is None:
        return

    page.snack_bar = ft.SnackBar(
        content=ft.Text(
            str(message)
        )
    )
    page.snack_bar.open = True
    page.update()


def _open_authorization_resolution(
    authorization,
    page,
):
    document_id = authorization.get(
        "documento_origen_id"
    )

    expediente_id = authorization.get(
        "expediente_origen_id"
    )

    if not document_id:
        _show_authorization_origin_message(
            page,
            (
                "La autorización no tiene una "
                "resolución de origen vinculada."
            ),
        )
        return

    try:
        document = get_admin_document(
            int(document_id)
        )
    except Exception as exc:
        _show_authorization_origin_message(
            page,
            (
                "No se pudo recuperar la "
                f"resolución: {exc}"
            ),
        )
        return

    if not document:
        _show_authorization_origin_message(
            page,
            (
                "La resolución vinculada no "
                "existe o está archivada."
            ),
        )
        return

    file_path = str(
        document.get("archivo_ruta")
        or ""
    ).strip()

    if not file_path:
        _show_authorization_origin_message(
            page,
            (
                "La resolución vinculada no "
                "tiene una ruta de archivo "
                "informada."
            ),
        )
        return

    try:
        document_viewer_service.open_document(
            file_path,
            expediente_id=(
                int(expediente_id)
                if expediente_id
                else None
            ),
        )

    except FileNotFoundError:
        _show_authorization_origin_message(
            page,
            (
                "El archivo de la resolución "
                "ya no está disponible en la "
                "ruta registrada."
            ),
        )

    except Exception as exc:
        _show_authorization_origin_message(
            page,
            (
                "No se pudo abrir la "
                f"resolución: {exc}"
            ),
        )


def _open_authorization_expedient(
    authorization,
    page,
    on_open_expediente,
):
    expediente_id = authorization.get(
        "expediente_origen_id"
    )

    if not expediente_id:
        _show_authorization_origin_message(
            page,
            (
                "La autorización no tiene un "
                "expediente de origen vinculado."
            ),
        )
        return

    if not callable(
        on_open_expediente
    ):
        _show_authorization_origin_message(
            page,
            (
                "La navegación al expediente "
                "no está disponible desde esta "
                "vista."
            ),
        )
        return

    try:
        on_open_expediente(
            int(expediente_id)
        )

    except Exception as exc:
        _show_authorization_origin_message(
            page,
            (
                "No se pudo abrir el "
                f"expediente: {exc}"
            ),
        )


def _authorization_origin_actions(
    authorization,
    *,
    page=None,
    on_open_expediente=None,
):
    if not authorization:
        return ft.Row(
            controls=[],
            visible=False,
        )

    document_id = authorization.get(
        "documento_origen_id"
    )

    expediente_id = authorization.get(
        "expediente_origen_id"
    )

    controls = []

    if document_id:
        controls.append(
            secondary_button(
                "Ver resolución",
                lambda e, item=authorization: (
                    _open_authorization_resolution(
                        item,
                        page,
                    )
                ),
            )
        )

    if expediente_id:
        controls.append(
            secondary_button(
                "Ir al expediente",
                lambda e, item=authorization: (
                    _open_authorization_expedient(
                        item,
                        page,
                        on_open_expediente,
                    )
                ),
            )
        )

    return ft.Row(
        controls=controls,
        spacing=10,
        wrap=True,
        tight=True,
        visible=bool(controls),
    )


def _authorization_history_status(
    authorization,
):
    if int(
        authorization.get("es_actual")
        or 0
    ) == 1:
        return (
            "AUTORIZACIÓN ACTUAL",
            "#027A48",
            "#ECFDF3",
        )

    state = str(
        authorization.get(
            "estado_autorizacion"
        )
        or ""
    ).strip().upper()

    if state in {
        "CADUCADA",
        "EXTINGUIDA",
        "DENEGADA",
        "REVOCADA",
    }:
        return (
            state,
            "#B42318",
            "#FEF3F2",
        )

    return (
        "AUTORIZACIÓN ANTERIOR",
        "#475467",
        "#F2F4F7",
    )


def _authorization_history_origin(
    authorization,
):
    items = []

    expediente_id = authorization.get(
        "expediente_origen_id"
    )

    documento_id = authorization.get(
        "documento_origen_id"
    )

    administrative_number = authorization.get(
        "numero_expediente_administrativo"
    )

    if administrative_number:
        items.append(
            f"Expediente administrativo: "
            f"{administrative_number}"
        )

    if expediente_id:
        items.append(
            f"Expediente CRM #{expediente_id}"
        )

    if documento_id:
        items.append(
            f"Documento CRM #{documento_id}"
        )

    return " · ".join(items)


def _authorization_history_card(
    authorization,
    page=None,
    on_open_expediente=None,
):
    badge_text, badge_fg, badge_bg = (
        _authorization_history_status(
            authorization
        )
    )

    situation = (
        authorization.get(
            "situacion_nombre"
        )
        or "Situación no informada"
    )

    authorization_name = (
        authorization.get(
            "autorizacion_nombre"
        )
        or (
            "Situación administrativa "
            "sin autorización asociada"
        )
    )

    start = _fecha_display(
        authorization.get(
            "fecha_vigencia_desde"
        )
    )

    end = _fecha_display(
        authorization.get(
            "fecha_vigencia_hasta"
        )
    )

    state = (
        authorization.get(
            "estado_autorizacion"
        )
        or "No informado"
    )

    origin = _authorization_history_origin(
        authorization
    )

    secondary_controls = []

    if authorization.get("motivo_inicio"):
        secondary_controls.append(
            _administrative_info_block(
                "Motivo de inicio",
                authorization.get(
                    "motivo_inicio"
                ),
                width=360,
            )
        )

    if authorization.get("motivo_fin"):
        secondary_controls.append(
            _administrative_info_block(
                "Motivo de finalización",
                authorization.get(
                    "motivo_fin"
                ),
                width=360,
            )
        )

    if authorization.get("organismo_concedente"):
        secondary_controls.append(
            _administrative_info_block(
                "Organismo",
                authorization.get(
                    "organismo_concedente"
                ),
                secondary=(
                    authorization.get(
                        "provincia"
                    )
                    or ""
                ),
                width=300,
            )
        )

    if origin:
        secondary_controls.append(
            _administrative_info_block(
                "Origen",
                origin,
                width=420,
            )
        )

    return ft.Container(
        bgcolor=Q_WHITE,
        border=ft.border.all(
            1,
            "#B9D7FF"
            if int(
                authorization.get("es_actual")
                or 0
            ) == 1
            else Q_BORDER,
        ),
        border_radius=14,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        _administrative_status_badge(
                            badge_text,
                            badge_fg,
                            badge_bg,
                        ),
                        _administrative_status_badge(
                            str(state).upper(),
                            "#175CD3",
                            "#EFF8FF",
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                    tight=True,
                ),

                ft.Text(
                    situation,
                    size=13,
                    color=Q_MUTED,
                ),

                ft.Text(
                    authorization_name,
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),

                ft.Row(
                    controls=[
                        _administrative_info_block(
                            "Vigencia desde",
                            start or "No informada",
                            width=190,
                        ),
                        _administrative_info_block(
                            "Vigencia hasta",
                            end or "No informada",
                            width=190,
                        ),
                        _administrative_info_block(
                            "Fecha de concesión",
                            _fecha_display(
                                authorization.get(
                                    "fecha_concesion"
                                )
                            )
                            or "No informada",
                            width=200,
                        ),
                        _administrative_info_block(
                            "Fecha de notificación",
                            _fecha_display(
                                authorization.get(
                                    "fecha_notificacion"
                                )
                            )
                            or "No informada",
                            width=210,
                        ),
                    ],
                    spacing=14,
                    wrap=True,
                    tight=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.START
                    ),
                ),

                ft.Row(
                    controls=secondary_controls,
                    spacing=14,
                    wrap=True,
                    tight=True,
                    visible=bool(
                        secondary_controls
                    ),
                    vertical_alignment=(
                        ft.CrossAxisAlignment.START
                    ),
                ),

                _authorization_origin_actions(
                    authorization,
                    page=page,
                    on_open_expediente=(
                        on_open_expediente
                    ),
                ),

                ft.Text(
                    authorization.get(
                        "observaciones"
                    )
                    or "",
                    size=12,
                    color=Q_MUTED,
                    visible=bool(
                        authorization.get(
                            "observaciones"
                        )
                    ),
                ),
            ],
            spacing=10,
            tight=True,
        ),
    )


def _build_authorization_history_section(
    client_id,
    page=None,
    on_open_expediente=None,
):
    try:
        authorizations = (
            list_client_authorizations(
                client_id,
                active_only=False,
            )
        )
    except Exception:
        authorizations = []

    if not authorizations:
        return ft.Column(
            controls=[
                ft.Text(
                    "Trayectoria administrativa",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Historial de situaciones y autorizaciones "
                    "administrativas del cliente.",
                    size=13,
                    color=Q_MUTED,
                ),
                _section_card(
                    "Autorizaciones",
                    empty_state(
                        "Este cliente no tiene autorizaciones "
                        "administrativas registradas"
                    ),
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    current_count = sum(
        1
        for item in authorizations
        if int(
            item.get("es_actual")
            or 0
        ) == 1
    )

    previous_count = (
        len(authorizations)
        - current_count
    )

    cards = [
        _authorization_history_card(
            authorization,
            page=page,
            on_open_expediente=(
                on_open_expediente
            ),
        )
        for authorization in authorizations
    ]

    return ft.Column(
        controls=[
            ft.Text(
                "Trayectoria administrativa",
                size=20,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            ft.Text(
                "Evolución de las situaciones y autorizaciones "
                "administrativas registradas para este cliente.",
                size=13,
                color=Q_MUTED,
            ),
            ft.Row(
                controls=[
                    _administrative_status_badge(
                        f"REGISTROS: {len(authorizations)}",
                        "#175CD3",
                        "#EFF8FF",
                    ),
                    _administrative_status_badge(
                        f"ACTUAL: {current_count}",
                        "#027A48",
                        "#ECFDF3",
                    ),
                    _administrative_status_badge(
                        f"ANTERIORES: {previous_count}",
                        "#475467",
                        "#F2F4F7",
                    ),
                ],
                spacing=8,
                wrap=True,
                tight=True,
            ),
            *cards,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


def _section_card(title, content):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content,
            ],
            spacing=12,
        ),
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
    )




def _short_path(value, max_len=58):
    raw = str(value or "").strip()
    if not raw:
        return "-"
    normalized = raw.replace("\\", "/")
    if len(normalized) <= max_len:
        return normalized
    return "…" + normalized[-max_len:]


def _open_folder(path, page=None):
    target = Path(str(path or "").strip())
    if not target.exists() or not target.is_dir():
        if page:
            try:
                page.snack_bar = ft.SnackBar(ft.Text(f"No existe la carpeta Box: {target}"))
                page.snack_bar.open = True
                page.update()
            except Exception:
                pass
        return False

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception as exc:
        if page:
            try:
                page.snack_bar = ft.SnackBar(ft.Text(f"No se pudo abrir la carpeta: {exc}"))
                page.snack_bar.open = True
                page.update()
            except Exception:
                pass
        return False

def _placeholder_section(title, description):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(description, size=13, color=Q_MUTED),
                ft.Container(
                    content=ft.Text("Preparado para fase futura", size=12, color="#0057B8", weight=ft.FontWeight.W_600),
                    bgcolor="#EAF3FF",
                    border_radius=18,
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                ),
            ],
            spacing=8,
        ),
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
    )


def _get_expedientes_cliente(cliente_id):
    try:
        with _connect() as conn:
            if not _table_exists(conn, "expedientes"):
                return []

            rows = conn.execute(
                """
                SELECT
                    e.id,
                    e.numero_expediente,
                    e.fecha_apertura,
                    e.fecha_presentacion,
                    e.estado_presentacion,
                    e.responsable,
                    e.activo,
                    e.box_folder_path,
                    te.nombre AS tipo_expediente,
                    ed.nombre AS estado_documental,
                    ea.nombre AS estado_administrativo,
                    p.nombre AS prioridad
                FROM expedientes e
                LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
                LEFT JOIN config_estados_documentales ed ON ed.id = e.estado_documental_id
                LEFT JOIN config_estados_administrativos ea ON ea.id = e.estado_administrativo_id
                LEFT JOIN config_prioridades p ON p.id = e.prioridad_id
                WHERE e.cliente_id = ? AND COALESCE(e.activo, 1) = 1
                ORDER BY e.created_at DESC, e.id DESC
                """,
                (int(cliente_id),),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _get_cobros_cliente(cliente_id):
    try:
        with _connect() as conn:
            if not _table_exists(conn, "eco_cobros"):
                return []

            rows = conn.execute(
                """
                SELECT
                    cob.id,
                    cob.numero_cobro,
                    cob.fecha_cobro,
                    cob.importe,
                    cob.forma_pago,
                    cob.tipo_cobro,
                    cob.facturable,
                    cob.estado_conciliacion,
                    e.numero_expediente,
                    h.numero_hoja,
                    f.numero_factura
                FROM eco_cobros cob
                LEFT JOIN expedientes e ON e.id = cob.expediente_id
                LEFT JOIN eco_hojas_encargo h ON h.id = cob.hoja_encargo_id
                LEFT JOIN eco_facturas f ON f.id = cob.factura_id
                WHERE cob.cliente_id = ? AND COALESCE(cob.activo, 1) = 1
                ORDER BY cob.fecha_cobro DESC, cob.id DESC
                """,
                (int(cliente_id),),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _get_hojas_cliente(cliente_id):
    try:
        with _connect() as conn:
            if not _table_exists(conn, "eco_hojas_encargo"):
                return []

            rows = conn.execute(
                """
                SELECT
                    h.id,
                    h.numero_hoja,
                    h.fecha_firma,
                    h.procedimiento,
                    h.importe_bruto,
                    h.descuento_consultas_previas,
                    h.importe_neto,
                    h.estado,
                    e.numero_expediente
                FROM eco_hojas_encargo h
                LEFT JOIN expedientes e ON e.id = h.expediente_id
                WHERE h.cliente_id = ? AND COALESCE(h.activo, 1) = 1
                ORDER BY h.created_at DESC, h.id DESC
                """,
                (int(cliente_id),),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _build_expedientes_section(cliente_id, page=None):
    expedientes = _get_expedientes_cliente(cliente_id)
    if not expedientes:
        return _section_card("Expedientes asociados", empty_state("Este cliente no tiene expedientes asociados"))

    rows = []
    for exp in expedientes:
        rows.append(
            [
                exp.get("numero_expediente") or "-",
                exp.get("tipo_expediente") or "-",
                exp.get("estado_documental") or "-",
                exp.get("estado_administrativo") or exp.get("estado_presentacion") or "-",
                exp.get("prioridad") or "-",
                _fecha_display(exp.get("fecha_apertura")),
                _fecha_display(exp.get("fecha_presentacion")),
                exp.get("responsable") or "-",
                ft.Text(_short_path(exp.get("box_folder_path")), size=12, color=Q_MUTED, tooltip=exp.get("box_folder_path") or ""),
                secondary_button(
                    "Abrir Box",
                    lambda e, path=exp.get("box_folder_path"): _open_folder(path, page),
                ) if exp.get("box_folder_path") else "-",
            ]
        )

    return _section_card(
        "Expedientes asociados",
        app_table(
            ["Nº expediente", "Tipo", "Doc.", "Estado", "Prioridad", "Apertura", "Presentación", "Responsable", "Ruta Box", "Acción Box"],
            rows,
            height=300,
        ),
    )


def _build_hojas_section(cliente_id):
    hojas = _get_hojas_cliente(cliente_id)
    if not hojas:
        return _section_card("Hojas de encargo", empty_state("Este cliente no tiene hojas de encargo"))

    rows = []
    for hoja in hojas:
        rows.append(
            [
                hoja.get("numero_hoja") or "-",
                _fecha_display(hoja.get("fecha_firma")),
                hoja.get("numero_expediente") or "-",
                hoja.get("procedimiento") or "-",
                _money(hoja.get("importe_bruto")),
                _money(hoja.get("descuento_consultas_previas")),
                _money(hoja.get("importe_neto")),
                hoja.get("estado") or "-",
            ]
        )

    return _section_card(
        "Hojas de encargo",
        app_table(
            ["Nº hoja", "Firma", "Expediente", "Procedimiento", "Bruto", "Dto. consultas", "Neto", "Estado"],
            rows,
            height=240,
        ),
    )


def _build_cobros_section(cliente_id):
    cobros = _get_cobros_cliente(cliente_id)
    if not cobros:
        return _section_card("Cobros", empty_state("Este cliente no tiene cobros registrados"))

    total = sum(float(c.get("importe") or 0) for c in cobros)
    conciliados = sum(1 for c in cobros if (c.get("estado_conciliacion") or "").upper() == "CONCILIADO")

    rows = []
    for cobro in cobros:
        rows.append(
            [
                cobro.get("numero_cobro") or "-",
                _fecha_display(cobro.get("fecha_cobro")),
                _money(cobro.get("importe")),
                cobro.get("forma_pago") or "-",
                cobro.get("tipo_cobro") or "-",
                cobro.get("numero_expediente") or "-",
                cobro.get("numero_hoja") or "-",
                "Sí" if cobro.get("facturable") else "No",
                cobro.get("numero_factura") or "-",
                cobro.get("estado_conciliacion") or "-",
            ]
        )

    content = ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(f"Total cobrado: {_money(total)}", size=13, weight=ft.FontWeight.BOLD, color="#027A48"),
                        bgcolor="#ECFDF3",
                        border_radius=18,
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    ),
                    ft.Container(
                        content=ft.Text(f"Conciliados: {conciliados}/{len(cobros)}", size=13, weight=ft.FontWeight.BOLD, color="#0057B8"),
                        bgcolor="#EAF3FF",
                        border_radius=18,
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    ),
                ],
                spacing=8,
                wrap=True,
            ),
            app_table(
                ["Nº cobro", "Fecha", "Importe", "Forma", "Tipo", "Expediente", "Hoja", "Fact.", "Factura", "Conciliación"],
                rows,
                height=280,
            ),
        ],
        spacing=10,
    )

    return _section_card("Cobros", content)


def _client_initials(client):
    nombre = _nombre_completo(client)
    parts = [p for p in nombre.split() if p]
    if not parts:
        return "CL"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _photo_placeholder(client):
    return ft.Container(
        width=92,
        height=92,
        bgcolor="#EAF3FF",
        border=ft.border.all(1, "#B9D7FF"),
        border_radius=18,
        content=ft.Column(
            controls=[
                ft.Text(_client_initials(client), size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text("Foto", size=11, color=Q_MUTED),
            ],
            spacing=2,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def client_detail_view(
    page,
    client,
    on_back=None,
    on_edit=None,
    on_open_expediente=None,
):
    sidebar_actions = []

    if on_back:
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                tooltip="Volver clientes",
                icon_color=Q_PRIMARY_DARK,
                on_click=on_back,
            )
        )

    if client.get("_on_previous"):
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT,
                tooltip="Anterior",
                icon_color=Q_PRIMARY_DARK,
                on_click=lambda e: client["_on_previous"](),
            )
        )

    if client.get("_on_next"):
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT,
                tooltip="Siguiente",
                icon_color=Q_PRIMARY_DARK,
                on_click=lambda e: client["_on_next"](),
            )
        )

    if on_edit:
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.EDIT,
                tooltip="Editar cliente",
                icon_color="#0057B8",
                on_click=on_edit,
            )
        )

    cliente_id = client.get("id")
    state = {"section": "ficha"}

    content_container = ft.Container(expand=True)

    def build_ficha_section():
        return ft.Column(
            controls=[
                detail_section(
                    "Datos básicos",
                    [
                        ("Nombre completo", _nombre_completo(client)),
                        ("NIE", client.get("nie")),
                        ("Pasaporte", client.get("pasaporte")),
                        ("DNI", client.get("dni")),
                        ("Nacionalidad", client.get("nacionalidad")),
                        (
                            "Fecha nacimiento",
                            _fecha_display(
                                client.get(
                                    "fecha_nacimiento"
                                )
                            ),
                        ),
                        (
                            "Edad",
                            _calcular_edad(
                                client.get(
                                    "fecha_nacimiento"
                                )
                            ),
                        ),
                        (
                            "Caducidad NIE/TIE",
                            _fecha_display(
                                client.get(
                                    "fecha_caducidad_residencia"
                                )
                            ),
                        ),
                        (
                            "Origen caducidad",
                            _residence_expiry_origin_label(
                                client.get(
                                    "fecha_caducidad_origen"
                                )
                            ),
                        ),
                        (
                            "Expediente origen",
                            _get_residence_expiry_expedient_number(
                                client
                            ),
                        ),
                        (
                            "Caducidad actualizada",
                            _fecha_display(
                                str(
                                    client.get(
                                        "fecha_caducidad_actualizada_at"
                                    )
                                    or ""
                                )[:10]
                            ),
                        ),
                        ("Estado cliente", client.get("estado_cliente")),
                        ("Sexo", client.get("sexo")),
                        ("Ficha completada", f"{_porcentaje_ficha(client)}%"),
                    ],
                ),
                detail_section(
                    "Contacto",
                    [
                        ("Teléfono", client.get("telefono")),
                        ("Email", client.get("email")),
                    ],
                ),
                detail_section(
                    "Dirección en España",
                    [
                        ("Domicilio", client.get("domicilio_espana")),
                        ("Localidad", client.get("localidad")),
                        ("Provincia", client.get("provincia")),
                        ("Código postal", client.get("codigo_postal")),
                    ],
                ),
                detail_section(
                    "Datos personales",
                    [
                        ("Localidad nacimiento", client.get("localidad_nacimiento")),
                        ("País nacimiento", client.get("pais_nacimiento")),
                        ("Nombre padre", client.get("nombre_padre")),
                        ("Nombre madre", client.get("nombre_madre")),
                        ("Estado civil", client.get("estado_civil")),
                    ],
                ),
                _administrative_summary_card(
                    client,
                    page=page,
                    on_open_expediente=(
                        on_open_expediente
                    ),
                ),
                detail_section(
                    "Observaciones",
                    [
                        ("Observaciones", client.get("observaciones")),
                        ("Observaciones internas", client.get("observaciones_internas")),
                    ],
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_actividad_section():
        return ft.Column(
            controls=[
                ft.Text("Actividad operativa", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _build_expedientes_section(cliente_id, page),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_hojas_section():
        return ft.Column(
            controls=[
                ft.Text("Hojas de encargo", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _build_hojas_section(cliente_id),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_cobros_section():
        return ft.Column(
            controls=[
                ft.Text("Cobros", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _build_cobros_section(cliente_id),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_documentos_section():
        return ft.Column(
            controls=[
                ft.Text("Documentos Box", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _placeholder_section("Documentos Box", "Aquí se mostrarán carpetas y documentos observados en Box."),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _contact_rows(tipo_contacto):
        return [
            item for item in _get_client_contacts(cliente_id)
            if (item.get("tipo_contacto") or "") == tipo_contacto
        ]

    def _render_contact_table(items, empty_message, open_new_callback, open_edit_callback=None, delete_callback=None, open_ref_client_callback=None, is_employer=False):
        if not items:
            return ft.Column(
                controls=[
                    empty_state(empty_message),
                    primary_button("Nuevo empleador" if is_employer else "Nuevo contacto", open_new_callback),
                ],
                spacing=12,
            )

        def _contact_actions_menu(item):
            menu_items = []

            ref_id = item.get("cliente_referenciado_id")
            if ref_id and open_ref_client_callback:
                menu_items.append(
                    ft.PopupMenuItem(
                        content=ft.Text("Ver cliente"),
                        icon=ft.Icons.PERSON_SEARCH,
                        on_click=lambda e, rid=ref_id: open_ref_client_callback(rid),
                    )
                )

            # Si el contacto está vinculado a otro cliente, sus datos personales
            # se editan únicamente desde la ficha de ese cliente para evitar
            # divergencias entre clientes y cliente_contactos.
            if open_edit_callback and not ref_id:
                menu_items.append(
                    ft.PopupMenuItem(
                        content=ft.Text("Modificar"),
                        icon=ft.Icons.EDIT,
                        on_click=lambda e, contact=item: open_edit_callback(contact),
                    )
                )

            if delete_callback:
                menu_items.append(
                    ft.PopupMenuItem(
                        content=ft.Text("Eliminar"),
                        icon=ft.Icons.DELETE_OUTLINE,
                        on_click=lambda e, cid=item.get("id"): delete_callback(cid),
                    )
                )

            return ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT,
                tooltip="Acciones",
                items=menu_items,
            )

        rows = []
        for item in items:
            ref_nombre = " ".join(
                [
                    item.get("ref_nombre") or "",
                    item.get("ref_primer_apellido") or "",
                    item.get("ref_segundo_apellido") or "",
                ]
            ).strip()

            if is_employer:
                rows.append(
                    [
                        item.get("nombre") or "-",
                        item.get("dni") or item.get("nie") or item.get("pasaporte") or "-",
                        item.get("telefono") or "-",
                        item.get("email") or "-",
                        item.get("domicilio_espana") or "-",
                        item.get("localidad") or "-",
                    ]
                )
            else:
                rows.append(
                    [
                        _contact_actions_menu(item),
                        item.get("parentesco") or "-",
                        _nombre_completo(item),
                        item.get("nie") or item.get("pasaporte") or item.get("dni") or "-",
                        item.get("telefono") or "-",
                        item.get("email") or "-",
                        "Sí" if item.get("cliente_referenciado_id") else "No",
                        ref_nombre or "-",
                    ]
                )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        primary_button("Nuevo empleador" if is_employer else "Nuevo contacto", open_new_callback),
                        ft.Container(
                            content=ft.Text(
                                f"{'Empleadores' if is_employer else 'Contactos'}: {len(items)}",
                                size=12,
                                color="#0057B8",
                                weight=ft.FontWeight.BOLD,
                            ),
                            bgcolor="#EAF3FF",
                            border_radius=18,
                            padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                app_table(
                    ["Empresa", "CIF/NIF", "Teléfono", "Email", "Domicilio", "Localidad"] if is_employer else
                    ["", "Parentesco", "Nombre", "Documento", "Teléfono", "Email", "Es cliente", "Cliente referenciado"],
                    rows,
                    height=390,
                ),
            ],
            spacing=12,
        )

    def build_contactos_section():
        contactos = _contact_rows("Familiar")
        available_clients = _get_available_clients_for_reference(cliente_id)
        client_reference_options = [_contact_reference_label(item) for item in available_clients]

        nacionalidad_options = _safe_master_values(get_nacionalidades)
        pais_options = _safe_master_values(get_paises_nombres)
        provincia_options = _safe_master_values(get_provincias_nombres)

        parentesco = ft.Dropdown(
            label="Parentesco",
            width=220,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=[ft.dropdown.Option(item) for item in CONTACT_RELATIONSHIPS],
        )

        nombre = _text_input_erp("Nombre", 320)
        primer_apellido = _text_input_erp("Primer apellido", 320)
        segundo_apellido = _text_input_erp("Segundo apellido", 320)
        nie = _text_input_erp("NIE", 220)
        pasaporte = _text_input_erp("Pasaporte", 220)
        dni = _text_input_erp("DNI", 220)

        fecha_nacimiento = _text_input_erp("Fecha nacimiento DD/MM/AAAA", 260)
        telefono = _text_input_erp("Teléfono", 220)
        email = _text_input_erp("Email", 320)
        estado_cliente = _text_input_erp("Estado cliente", 320)
        sexo = ft.Dropdown(
            label="Sexo",
            width=180,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=[ft.dropdown.Option("HOMBRE"), ft.dropdown.Option("MUJER"), ft.dropdown.Option("X")],
        )

        domicilio_espana = _text_input_erp("Domicilio en España", 420)
        tipo_via = _via_type_dropdown("Tipo de vía", 170)
        nombre_via = _text_input_erp("Nombre de vía", 300)
        numero = _text_input_erp("Número", 110)
        piso = _text_input_erp("Piso", 110)
        puerta = _text_input_erp("Puerta", 110)
        escalera = _text_input_erp("Escalera", 110)
        codigo_postal = _text_input_erp("Código postal", 180)
        localidad_nacimiento = _text_input_erp("Localidad nacimiento", 260)
        nombre_padre = _text_input_erp("Nombre del padre", 320)
        nombre_madre = _text_input_erp("Nombre de la madre", 320)
        estado_civil = _text_input_erp("Estado civil", 220)
        observaciones = ft.TextField(label="Observaciones", width=640, multiline=True, min_lines=2, max_lines=4, border_radius=10, border_color=Q_BORDER, focused_border_color="#18BFEA")
        observaciones_internas = ft.TextField(label="Observaciones internas", width=640, multiline=True, min_lines=2, max_lines=4, border_radius=10, border_color=Q_BORDER, focused_border_color="#18BFEA")

        localidad_options = []

        def on_provincia_selected(value):
            nonlocal localidad_options
            provincia_value = (value or "").strip()
            if not provincia_value:
                localidad_options = []
                localidad_autocomplete.set_options([], clear_value=True)
                localidad_autocomplete.input.label = "Localidad"
                return
            try:
                localidad_options = get_localidades_by_provincia(provincia_value)
            except Exception:
                localidad_options = []
            localidad_autocomplete.set_options(localidad_options, clear_value=True)
            localidad_autocomplete.input.label = f"Localidad ({len(localidad_options)})" if localidad_options else "Localidad (sin datos)"

        nacionalidad_autocomplete = AppAutocomplete(
            page=page,
            label="Nacionalidad",
            options=nacionalidad_options,
            width=260,
            max_results=8,
        )
        pais_nacimiento_autocomplete = AppAutocomplete(
            page=page,
            label="País nacimiento",
            options=pais_options,
            width=260,
            max_results=8,
        )
        provincia_autocomplete = AppAutocomplete(
            page=page,
            label="Provincia",
            options=provincia_options,
            width=260,
            max_results=12,
            on_select=on_provincia_selected,
            allow_free_text=True,
        )
        localidad_autocomplete = AppAutocomplete(
            page=page,
            label="Localidad",
            options=[],
            width=260,
            max_results=12,
            allow_free_text=True,
        )

        controls = {
            "nombre": nombre,
            "primer_apellido": primer_apellido,
            "segundo_apellido": segundo_apellido,
            "nie": nie,
            "pasaporte": pasaporte,
            "dni": dni,
            "fecha_nacimiento": fecha_nacimiento,
            "telefono": telefono,
            "email": email,
            "estado_cliente": estado_cliente,
            "sexo": sexo,
            "domicilio_espana": domicilio_espana,
            "tipo_via": tipo_via,
            "nombre_via": nombre_via,
            "numero": numero,
            "piso": piso,
            "puerta": puerta,
            "escalera": escalera,
            "codigo_postal": codigo_postal,
            "localidad_nacimiento": localidad_nacimiento,
            "nombre_padre": nombre_padre,
            "nombre_madre": nombre_madre,
            "estado_civil": estado_civil,
            "observaciones": observaciones,
            "observaciones_internas": observaciones_internas,
        }

        referencia_cliente = None
        contact_form_state = {"editing_id": None}

        def fill_from_referenced_client(value=None):
            ref_id = _id_from_reference_label(value or referencia_cliente.get_value())
            ref = next((item for item in available_clients if item.get("id") == ref_id), None)
            if not ref:
                return
            data = _copy_client_to_contact_data(ref)
            for key, control in controls.items():
                control.value = data.get(key) or ""

            nacionalidad_autocomplete.set_value(data.get("nacionalidad") or "", update=False)
            pais_nacimiento_autocomplete.set_value(data.get("pais_nacimiento") or "", update=False)
            provincia_autocomplete.set_value(data.get("provincia") or "", update=False)

            provincia_value = data.get("provincia") or ""
            try:
                locs = get_localidades_by_provincia(provincia_value) if provincia_value else []
            except Exception:
                locs = []
            localidad_autocomplete.set_options(locs, clear_value=False)
            localidad_autocomplete.input.label = f"Localidad ({len(locs)})" if locs else "Localidad"
            localidad_autocomplete.set_value(data.get("localidad") or "", update=False)
            page.update()

        referencia_cliente = AppAutocomplete(
            page=page,
            label="Referenciar cliente existente",
            options=client_reference_options,
            width=520,
            max_results=10,
            on_select=fill_from_referenced_client,
            allow_free_text=True,
        )

        def _reference_label_for_id(ref_id):
            if not ref_id:
                return ""
            ref = next((item for item in available_clients if int(item.get("id") or 0) == int(ref_id)), None)
            return _contact_reference_label(ref) if ref else ""

        def close_contact_dialog(e=None):
            contacto_dialog.open = False
            page.update()

        def clear_contact_form():
            contact_form_state["editing_id"] = None
            parentesco.value = None
            referencia_cliente.set_value("", update=False)
            nacionalidad_autocomplete.set_value("", update=False)
            pais_nacimiento_autocomplete.set_value("", update=False)
            provincia_autocomplete.set_value("", update=False)
            localidad_autocomplete.set_options([], clear_value=True)
            localidad_autocomplete.input.label = "Localidad"
            for control in controls.values():
                control.value = ""

        def load_contact_form(contact):
            contact_form_state["editing_id"] = contact.get("id")
            parentesco.value = contact.get("parentesco") or None
            referencia_cliente.set_value(_reference_label_for_id(contact.get("cliente_referenciado_id")), update=False)

            for key, control in controls.items():
                control.value = contact.get(key) or ""

            nacionalidad_autocomplete.set_value(contact.get("nacionalidad") or "", update=False)
            pais_nacimiento_autocomplete.set_value(contact.get("pais_nacimiento") or "", update=False)
            provincia_autocomplete.set_value(contact.get("provincia") or "", update=False)

            provincia_value = contact.get("provincia") or ""
            try:
                locs = get_localidades_by_provincia(provincia_value) if provincia_value else []
            except Exception:
                locs = []
            localidad_autocomplete.set_options(locs, clear_value=False)
            localidad_autocomplete.input.label = f"Localidad ({len(locs)})" if locs else "Localidad"
            localidad_autocomplete.set_value(contact.get("localidad") or "", update=False)

        def save_contact(e=None):
            if not nombre.value and not referencia_cliente.get_value():
                page.snack_bar = ft.SnackBar(ft.Text("Indica un nombre o selecciona un cliente existente"))
                page.snack_bar.open = True
                page.update()
                return

            data = {
                "cliente_id": cliente_id,
                "tipo_contacto": "Familiar",
                "parentesco": parentesco.value or "",
                "cliente_referenciado_id": _id_from_reference_label(referencia_cliente.get_value()),
                "sincronizar_bidireccional": 1,
            }
            for key, control in controls.items():
                data[key] = control.value or ""

            data["nacionalidad"] = nacionalidad_autocomplete.get_value()
            data["pais_nacimiento"] = pais_nacimiento_autocomplete.get_value()
            data["provincia"] = provincia_autocomplete.get_value()
            data["localidad"] = localidad_autocomplete.get_value()
            data["actividad"] = ""
            data["cnae"] = ""
            data["cno_sepe"] = ""

            _save_client_contact(data, contact_id=contact_form_state.get("editing_id"))
            close_contact_dialog()
            content_container.content = build_contactos_section()
            page.update()

        def open_edit_contact(contact):
            load_contact_form(contact)
            contacto_dialog.title = ft.Text("Editar contacto")
            contacto_dialog.open = True
            page.update()

        def delete_contact(contact_id):
            _archive_client_contact(contact_id)
            content_container.content = build_contactos_section()
            page.snack_bar = ft.SnackBar(ft.Text("Contacto eliminado"))
            page.snack_bar.open = True
            page.update()

        def open_referenced_client(ref_id):
            referenced_client = _get_client_for_navigation(ref_id)
            if not referenced_client:
                page.snack_bar = ft.SnackBar(ft.Text("No se encontró el cliente referenciado"))
                page.snack_bar.open = True
                page.update()
                return

            content_container.content = client_detail_view(
                page,
                referenced_client,
                on_back=lambda e=None: set_section(
                    "contactos"
                ),
                on_open_expediente=(
                    on_open_expediente
                ),
            )
            page.update()

        contacto_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nuevo contacto"),
            content=_themed_dialog_content(
                "Nuevo contacto relacionado",
                "Alta rápida con la misma estructura de la ficha de cliente y búsquedas asistidas.",
                [
                    _dialog_section(
                        "Datos básicos",
                        ft.Icons.PERSON,
                        [
                            ft.Row([parentesco, referencia_cliente.control], wrap=True, spacing=10),
                            ft.Row([nombre, primer_apellido, segundo_apellido], wrap=True, spacing=10),
                            ft.Row([nie, pasaporte, dni], wrap=True, spacing=10),
                            ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),
                            ft.Row([email, estado_cliente], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Dirección en España",
                        ft.Icons.HOME,
                        [
                            domicilio_espana,
                            ft.Row([tipo_via, nombre_via, numero, piso, puerta, escalera], wrap=True, spacing=10),
                            ft.Row([provincia_autocomplete.control, localidad_autocomplete.control, codigo_postal], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Datos personales",
                        ft.Icons.BADGE,
                        [
                            ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True, spacing=10),
                            ft.Row([nombre_padre, nombre_madre, estado_civil, sexo], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Observaciones",
                        ft.Icons.NOTES,
                        [
                            observaciones,
                            observaciones_internas,
                        ],
                    ),
                ],
            ),
            actions=[
                secondary_button("Cancelar", close_contact_dialog),
                primary_button("Guardar contacto", save_contact),
            ],
        )

        if contacto_dialog not in page.overlay:
            page.overlay.append(contacto_dialog)

        def open_new_contact(e=None):
            clear_contact_form()
            contacto_dialog.title = ft.Text("Nuevo contacto")
            contacto_dialog.open = True
            page.update()

        return ft.Column(
            controls=[
                ft.Text("Contactos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(
                    "Familiares y personas relacionadas. Pueden referenciar a otro cliente existente.",
                    size=13,
                    color=Q_MUTED,
                ),
                _section_card(
                    "Contactos familiares",
                    _render_contact_table(
                        contactos,
                        "Este cliente no tiene contactos familiares relacionados",
                        open_new_contact,
                        open_edit_callback=open_edit_contact,
                        delete_callback=delete_contact,
                        open_ref_client_callback=open_referenced_client,
                        is_employer=False,
                    ),
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_empleadores_section():
        """Empresas vinculadas al cliente mediante el nuevo modelo client_companies.

        Nota de arquitectura:
        - Ya no se pinta el flujo legacy de empleadores en cliente_contactos.
        - Las acciones de cada fila siguen el patrón de la tabla de contactos:
          PopupMenuButton + PopupMenuItem.
        - Desvincular elimina la relación, no la empresa maestra.
        """
        try:
            empresas_vinculadas = (
                client_company_service.list_client_companies(cliente_id, active_only=False)
                if client_company_service else []
            )
        except Exception:
            empresas_vinculadas = []

        relationship_options = [
            ft.dropdown.Option("empleador", "Empleador"),
            ft.dropdown.Option("ofertante", "Ofertante"),
            ft.dropdown.Option("contratante", "Contratante"),
            ft.dropdown.Option("proveedor", "Proveedor"),
            ft.dropdown.Option("empresa relacionada", "Empresa relacionada"),
            ft.dropdown.Option("otro", "Otro"),
        ]

        active_options = [
            ft.dropdown.Option("1", "Activo"),
            ft.dropdown.Option("0", "Inactivo"),
        ]

        def _notify(message, error=False):
            page.snack_bar = ft.SnackBar(
                ft.Text(message),
                bgcolor="#B42318" if error else "#0F8A5F",
            )
            page.snack_bar.open = True
            page.update()

        def _relationship_label(value):
            lookup = {
                "empleador": "Empleador",
                "ofertante": "Ofertante",
                "contratante": "Contratante",
                "proveedor": "Proveedor",
                "empresa relacionada": "Empresa relacionada",
                "otro": "Otro",
            }
            return lookup.get(str(value or "").strip(), value or "-")

        def _company_label(company):
            name = company.get("name") or ""
            tax_id = company.get("tax_id") or ""
            activity = company.get("main_activity") or company.get("cnae_description") or ""
            parts = [name]
            details = " · ".join([p for p in [tax_id, activity] if p])
            if details:
                parts.append(details)
            return " — ".join(parts)

        def _company_id_from_label(label):
            label = str(label or "")
            if "#" not in label:
                return None
            try:
                return int(label.rsplit("#", 1)[1].strip())
            except Exception:
                return None

        def _refresh_section():
            content_container.content = build_empleadores_section()
            page.update()

        def _latest_client_company_link_id(company_id):
            try:
                with _connect() as conn:
                    row = conn.execute(
                        """
                        SELECT id
                        FROM client_companies
                        WHERE client_id = ? AND company_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (int(cliente_id), int(company_id)),
                    ).fetchone()
                    return int(row["id"]) if row else None
            except Exception:
                return None

        def _contract_payload(prefix):
            return {
                "contract_type": prefix["contract_type"].value or "",
                "contract_code": prefix["contract_code"].value or "",
                "collective_agreement": prefix["collective_agreement"].value or "",
                "collective_agreement_code": prefix["collective_agreement_code"].value or "",
                "contract_position": prefix["contract_position"].value or "",
                "contract_cno_code": _extract_catalog_code(prefix["contract_cno"].get_value()),
                "contract_cno_description": _extract_catalog_description(prefix["contract_cno"].get_value()),
                "contract_start_date": prefix["contract_start_date"].value or "",
                "contract_end_date": prefix["contract_end_date"].value or "",
                "contract_hours": prefix["contract_hours"].value or "",
                "salary_amount": prefix["salary_amount"].value or "",
                "salary_period": prefix["salary_period"].value or "",
                "work_center_address": prefix["work_center_address"].value or "",
                "box_contract_path": prefix["box_contract_path"].value or "",
                "notes": prefix["contract_notes"].value or "",
                "is_primary": 1,
            }

        def _create_contract_if_requested(flag, controls, company_id, created_link=None):
            if not flag.value:
                return
            if not employment_contract_service:
                _notify("Servicio de contratos no disponible", error=True)
                return
            link_id = None
            if isinstance(created_link, dict):
                link_id = created_link.get("id")
            link_id = link_id or _latest_client_company_link_id(company_id)
            if not link_id:
                _notify("No se pudo localizar la relación cliente-empresa para crear el contrato", error=True)
                return
            employment_contract_service.create_contract(link_id, _contract_payload(controls))

        def _contract_controls():
            cno_options = _load_catalog_options("cno_sepe_2011.csv", "CNO")
            cno_autocomplete = AppAutocomplete(
                page=page,
                label="CNO / SEPE",
                options=cno_options,
                width=720,
                max_results=12,
                allow_free_text=True,
            )
            return {
                "create_contract": ft.Checkbox(label="Crear contrato/oferta de trabajo ahora", value=False),
                "contract_type": _text_input_erp("Tipo de contrato", 260),
                "contract_code": _text_input_erp("Código contrato", 180),
                "collective_agreement": _text_input_erp("Convenio", 420),
                "collective_agreement_code": _text_input_erp("Código convenio", 180),
                "contract_position": _text_input_erp("Puesto", 320),
                "contract_cno": cno_autocomplete,
                "contract_start_date": _text_input_erp("Fecha inicio contrato", 190),
                "contract_end_date": _text_input_erp("Fecha fin contrato", 190),
                "contract_hours": _text_input_erp("Jornada / horas", 180),
                "salary_amount": _text_input_erp("Salario", 160),
                "salary_period": _text_input_erp("Periodo salario", 180),
                "work_center_address": _text_input_erp("Centro de trabajo", 720),
                "box_contract_path": _text_input_erp("Ruta Box contrato", 720),
                "contract_notes": ft.TextField(
                    label="Notas del contrato/oferta",
                    width=720,
                    multiline=True,
                    min_lines=2,
                    max_lines=4,
                    border_radius=10,
                    border_color=Q_BORDER,
                    focused_border_color="#18BFEA",
                ),
            }

        def _clear_contract_controls(controls):
            controls["create_contract"].value = False
            for key, control in controls.items():
                if key == "create_contract":
                    continue
                if key == "contract_cno":
                    control.set_value("", update=False)
                else:
                    control.value = ""

        def _contract_dialog_section(controls):
            return _dialog_section(
                "Contrato / oferta de trabajo",
                ft.Icons.DESCRIPTION,
                [
                    controls["create_contract"],
                    ft.Row([controls["contract_type"], controls["contract_code"]], wrap=True, spacing=10),
                    ft.Row([controls["collective_agreement"], controls["collective_agreement_code"]], wrap=True, spacing=10),
                    ft.Row([controls["contract_position"], controls["contract_start_date"], controls["contract_end_date"]], wrap=True, spacing=10),
                    controls["contract_cno"].control,
                    ft.Row([controls["contract_hours"], controls["salary_amount"], controls["salary_period"]], wrap=True, spacing=10),
                    controls["work_center_address"],
                    controls["box_contract_path"],
                    controls["contract_notes"],
                ],
            )

        # ------------------------------------------------------------------
        # Dialogo: vincular empresa existente
        # ------------------------------------------------------------------
        try:
            available_companies = company_service.list_companies(limit=1000) if company_service else []
        except Exception:
            available_companies = []

        company_options = [f"{_company_label(company)} #{company.get('id')}" for company in available_companies]

        existing_company_ac = AppAutocomplete(
            page=page,
            label="Buscar empresa existente",
            options=company_options,
            width=720,
            max_results=12,
            allow_free_text=False,
        )
        link_relationship = ft.Dropdown(
            label="Relación con el cliente",
            width=260,
            value="empleador",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=relationship_options,
        )
        link_active = ft.Dropdown(
            label="Estado",
            width=160,
            value="1",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=active_options,
        )
        link_start_date = _text_input_erp("Fecha inicio", 170)
        link_end_date = _text_input_erp("Fecha fin", 170)
        link_notes = ft.TextField(
            label="Notas de vinculación",
            width=720,
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
        )
        existing_contract_controls = _contract_controls()

        def close_link_existing_dialog(e=None):
            link_existing_dialog.open = False
            page.update()

        def clear_link_existing_form():
            existing_company_ac.set_value("", update=False)
            link_relationship.value = "empleador"
            link_active.value = "1"
            link_start_date.value = ""
            link_end_date.value = ""
            link_notes.value = ""
            _clear_contract_controls(existing_contract_controls)

        def save_existing_link(e=None):
            if not client_company_service:
                _notify("Servicio de vinculación no disponible", error=True)
                return
            company_id = _company_id_from_label(existing_company_ac.get_value())
            if not company_id:
                _notify("Selecciona una empresa existente", error=True)
                return
            try:
                created_link = client_company_service.link_company_to_client(
                    cliente_id,
                    company_id,
                    {
                        "relationship_type": link_relationship.value or "empleador",
                        "is_active": link_active.value or "1",
                        "start_date": link_start_date.value or "",
                        "end_date": link_end_date.value or "",
                        "notes": link_notes.value or "",
                    },
                )
                _create_contract_if_requested(existing_contract_controls["create_contract"], existing_contract_controls, company_id, created_link)
            except Exception as exc:
                _notify(f"No se pudo vincular la empresa: {exc}", error=True)
                return
            close_link_existing_dialog()
            _notify("Empresa vinculada al cliente")
            _refresh_section()

        link_existing_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Vincular empresa existente"),
            content=_themed_dialog_content(
                "Vincular empresa existente",
                "Selecciona una entidad ya creada en el módulo Empresas y define su relación con este cliente.",
                [
                    _dialog_section(
                        "Empresa",
                        ft.Icons.BUSINESS,
                        [existing_company_ac.control],
                    ),
                    _dialog_section(
                        "Relación",
                        ft.Icons.LINK,
                        [
                            ft.Row([link_relationship, link_active, link_start_date, link_end_date], wrap=True, spacing=10),
                            link_notes,
                        ],
                    ),
                    _contract_dialog_section(existing_contract_controls),
                ],
                width=940,
                height=680,
            ),
            actions=[
                secondary_button("Cancelar", close_link_existing_dialog),
                primary_button("Vincular empresa", save_existing_link),
            ],
        )
        if link_existing_dialog not in page.overlay:
            page.overlay.append(link_existing_dialog)

        def open_link_existing_dialog(e=None):
            clear_link_existing_form()
            link_existing_dialog.open = True
            page.update()

        # ------------------------------------------------------------------
        # Dialogo: nueva empresa y vincular
        # ------------------------------------------------------------------
        entity_type = ft.Dropdown(
            label="Tipo de entidad",
            width=240,
            value="juridica",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=[
                ft.dropdown.Option("juridica", "Sociedad / empresa"),
                ft.dropdown.Option("autonomo", "Autónomo"),
                ft.dropdown.Option("persona_fisica", "Persona física empleadora"),
            ],
        )
        company_name = _text_input_erp("Nombre / razón social", 390)
        company_tax_id = _text_input_erp("CIF / NIF / NIE", 220)
        company_kind = _text_input_erp("Tipo / forma", 220)
        company_phone = _text_input_erp("Teléfono", 220)
        company_email = _text_input_erp("Email", 320)
        company_activity = _text_input_erp("Actividad", 520)
        company_cnae = _text_input_erp("CNAE", 160)
        new_relationship = ft.Dropdown(
            label="Relación con el cliente",
            width=260,
            value="empleador",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=relationship_options,
        )
        new_active = ft.Dropdown(
            label="Estado",
            width=160,
            value="1",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=active_options,
        )
        new_start_date = _text_input_erp("Fecha inicio", 170)
        new_end_date = _text_input_erp("Fecha fin", 170)
        new_notes = ft.TextField(
            label="Notas de vinculación",
            width=720,
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
        )
        new_contract_controls = _contract_controls()

        def close_new_company_dialog(e=None):
            new_company_dialog.open = False
            page.update()

        def clear_new_company_form():
            for control in [company_name, company_tax_id, company_kind, company_phone, company_email, company_activity, company_cnae, new_start_date, new_end_date, new_notes]:
                control.value = ""
            entity_type.value = "juridica"
            new_relationship.value = "empleador"
            new_active.value = "1"
            _clear_contract_controls(new_contract_controls)

        def save_new_company_link(e=None):
            if not company_service or not client_company_service:
                _notify("Servicios de empresa no disponibles", error=True)
                return
            if not (company_name.value or "").strip():
                _notify("Indica el nombre o razón social de la empresa", error=True)
                return
            try:
                new_company = company_service.create_company({
                    "entity_type": entity_type.value or "juridica",
                    "name": company_name.value or "",
                    "document_type": "CIF/NIF",
                    "tax_id": company_tax_id.value or "",
                    "company_type": company_kind.value or "",
                    "phone": company_phone.value or "",
                    "email": company_email.value or "",
                    "main_activity": company_activity.value or "",
                    "cnae_code": company_cnae.value or "",
                })
                created_link = client_company_service.link_company_to_client(
                    cliente_id,
                    new_company["id"],
                    {
                        "relationship_type": new_relationship.value or "empleador",
                        "is_active": new_active.value or "1",
                        "start_date": new_start_date.value or "",
                        "end_date": new_end_date.value or "",
                        "notes": new_notes.value or "",
                    },
                )
                _create_contract_if_requested(new_contract_controls["create_contract"], new_contract_controls, new_company["id"], created_link)
            except Exception as exc:
                _notify(f"No se pudo crear/vincular la empresa: {exc}", error=True)
                return
            close_new_company_dialog()
            _notify("Empresa creada y vinculada")
            _refresh_section()

        new_company_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nueva empresa vinculada"),
            content=_themed_dialog_content(
                "Nueva empresa vinculada",
                "Alta mínima de entidad y relación con este cliente. Para datos completos usa el módulo Empresas.",
                [
                    _dialog_section(
                        "Datos de entidad",
                        ft.Icons.BUSINESS,
                        [
                            ft.Row([entity_type, company_name, company_tax_id], wrap=True, spacing=10),
                            ft.Row([company_kind, company_phone, company_email], wrap=True, spacing=10),
                            ft.Row([company_activity, company_cnae], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Relación con cliente",
                        ft.Icons.LINK,
                        [
                            ft.Row([new_relationship, new_active, new_start_date, new_end_date], wrap=True, spacing=10),
                            new_notes,
                        ],
                    ),
                    _contract_dialog_section(new_contract_controls),
                ],
                width=940,
                height=740,
            ),
            actions=[
                secondary_button("Cancelar", close_new_company_dialog),
                primary_button("Guardar empresa vinculada", save_new_company_link),
            ],
        )
        if new_company_dialog not in page.overlay:
            page.overlay.append(new_company_dialog)

        def open_new_company_dialog(e=None):
            clear_new_company_form()
            new_company_dialog.open = True
            page.update()

        # ------------------------------------------------------------------
        # Dialogo: modificar relación
        # ------------------------------------------------------------------
        edit_link_id = {"value": None}
        edit_relationship = ft.Dropdown(
            label="Relación con el cliente",
            width=260,
            value="empleador",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=relationship_options,
        )
        edit_active = ft.Dropdown(
            label="Estado",
            width=160,
            value="1",
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
            options=active_options,
        )
        edit_start_date = _text_input_erp("Fecha inicio", 170)
        edit_end_date = _text_input_erp("Fecha fin", 170)
        edit_notes = ft.TextField(
            label="Notas de vinculación",
            width=720,
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
        )

        def close_edit_link_dialog(e=None):
            edit_link_dialog.open = False
            page.update()

        def open_edit_link_dialog(link):
            edit_link_id["value"] = link.get("id")
            edit_relationship.value = link.get("relationship_type") or "empleador"
            edit_active.value = "1" if int(link.get("is_active") or 0) else "0"
            edit_start_date.value = link.get("start_date") or ""
            edit_end_date.value = link.get("end_date") or ""
            edit_notes.value = link.get("notes") or ""
            edit_link_dialog.title = ft.Text(f"Modificar relación: {link.get('company_name') or ''}")
            edit_link_dialog.open = True
            page.update()

        def save_edit_link(e=None):
            if not edit_link_id.get("value"):
                _notify("No hay vínculo seleccionado", error=True)
                return
            try:
                client_company_service.update_client_company(
                    edit_link_id["value"],
                    {
                        "relationship_type": edit_relationship.value or "empleador",
                        "is_active": edit_active.value or "1",
                        "start_date": edit_start_date.value or "",
                        "end_date": edit_end_date.value or "",
                        "notes": edit_notes.value or "",
                    },
                )
            except Exception as exc:
                _notify(f"No se pudo actualizar la relación: {exc}", error=True)
                return
            close_edit_link_dialog()
            _notify("Relación actualizada")
            _refresh_section()

        edit_link_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Modificar relación"),
            content=_themed_dialog_content(
                "Modificar relación",
                "Cambia el tipo de relación, vigencia y notas. La empresa maestra no se modifica desde aquí.",
                [
                    _dialog_section(
                        "Datos de relación",
                        ft.Icons.LINK,
                        [
                            ft.Row([edit_relationship, edit_active, edit_start_date, edit_end_date], wrap=True, spacing=10),
                            edit_notes,
                        ],
                    ),
                ],
                width=900,
                height=420,
            ),
            actions=[
                secondary_button("Cancelar", close_edit_link_dialog),
                primary_button("Guardar cambios", save_edit_link),
            ],
        )
        if edit_link_dialog not in page.overlay:
            page.overlay.append(edit_link_dialog)

        # ------------------------------------------------------------------
        # Dialogo: confirmar desvinculación
        # ------------------------------------------------------------------
        unlink_state = {"link": None}

        def close_unlink_dialog(e=None):
            unlink_dialog.open = False
            page.update()

        def open_unlink_dialog(link):
            unlink_state["link"] = link
            unlink_dialog.title = ft.Text("Desvincular empresa")
            unlink_dialog.content = ft.Container(
                width=520,
                content=ft.Text(
                    f"¿Quieres desvincular '{link.get('company_name') or 'esta empresa'}' de este cliente? La empresa no se eliminará del directorio.",
                    size=14,
                    color=Q_PRIMARY_DARK,
                ),
            )
            unlink_dialog.open = True
            page.update()

        def confirm_unlink(e=None):
            link = unlink_state.get("link")
            if not link:
                return
            try:
                client_company_service.unlink_company_from_client(link.get("id"))
            except Exception as exc:
                _notify(f"No se pudo desvincular la empresa: {exc}", error=True)
                return
            close_unlink_dialog()
            _notify("Empresa desvinculada")
            _refresh_section()

        unlink_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Desvincular empresa"),
            content=ft.Text(""),
            actions=[
                secondary_button("Cancelar", close_unlink_dialog),
                primary_button("Desvincular", confirm_unlink),
            ],
        )
        if unlink_dialog not in page.overlay:
            page.overlay.append(unlink_dialog)

        def open_company_detail_from_link(link):
            company_id = link.get("company_id")
            if not company_id:
                _notify("No se encontró el ID de empresa vinculada", error=True)
                return
            if company_detail_view is None:
                _notify("La ficha de empresa no está disponible", error=True)
                return

            content_container.content = company_detail_view(
                page,
                company_id,
                on_back=lambda e=None: set_section("empleadores"),
                on_edit=None,
            )
            page.update()

        def _company_actions_menu(link):
            return ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT,
                tooltip="Acciones",
                items=[
                    ft.PopupMenuItem(
                        content=ft.Text("Ver ficha empresa"),
                        icon=ft.Icons.BUSINESS,
                        on_click=lambda e, item=link: open_company_detail_from_link(item),
                    ),
                    ft.PopupMenuItem(
                        content=ft.Text("Modificar"),
                        icon=ft.Icons.EDIT,
                        on_click=lambda e, item=link: open_edit_link_dialog(item),
                    ),
                    ft.PopupMenuItem(
                        content=ft.Text("Desvincular"),
                        icon=ft.Icons.LINK_OFF,
                        on_click=lambda e, item=link: open_unlink_dialog(item),
                    ),
                ],
            )

        rows = []
        for link in empresas_vinculadas:
            rows.append([
                _company_actions_menu(link),
                link.get("company_name") or "-",
                link.get("company_tax_id") or "-",
                _relationship_label(link.get("relationship_type")),
                "Activo" if int(link.get("is_active") or 0) else "Inactivo",
                link.get("main_activity") or link.get("cnae_description") or "-",
                link.get("cnae_code") or "-",
                link.get("representative_name") or "-",
                link.get("notes") or "-",
            ])

        if not rows:
            table_content = ft.Column(
                controls=[
                    empty_state("Este cliente no tiene empresas vinculadas"),
                    ft.Row(
                        controls=[
                            primary_button("Vincular empresa existente", open_link_existing_dialog),
                            secondary_button("Nueva empresa y vincular", open_new_company_dialog),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=12,
            )
        else:
            table_content = ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            primary_button("Vincular empresa existente", open_link_existing_dialog),
                            secondary_button("Nueva empresa y vincular", open_new_company_dialog),
                            ft.Container(
                                content=ft.Text(
                                    f"Empresas vinculadas: {len(empresas_vinculadas)}",
                                    size=12,
                                    color="#0057B8",
                                    weight=ft.FontWeight.BOLD,
                                ),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    app_table(
                        ["", "Empresa", "CIF/NIF", "Relación", "Estado", "Actividad", "CNAE", "Representante", "Notas"],
                        rows,
                        height=430,
                    ),
                ],
                spacing=12,
            )

        return ft.Column(
            controls=[
                ft.Text("Empresas vinculadas", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(
                    "Entidades maestras vinculadas al cliente. La empresa se gestiona en Contactos > Empresas; aquí se gestiona la relación.",
                    size=13,
                    color=Q_MUTED,
                ),
                _section_card("Empresas / empleadores", table_content),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_administrative_history_section():
        return _build_authorization_history_section(
            cliente_id,
            page=page,
            on_open_expediente=(
                on_open_expediente
            ),
        )

    def build_historial_section():
        return ft.Column(
            controls=[
                ft.Text("Historial de actuaciones", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _placeholder_section("Historial de actuaciones", "Aquí se mostrará la actividad interna del cliente."),
                _placeholder_section("Referidos / recurrencia", "Aquí se mostrarán relaciones, referidos y recurrencia."),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_section_content():
        section = state.get("section") or "ficha"

        if section == "actividad":
            return build_actividad_section()
        if section == "hojas":
            return build_hojas_section()
        if section == "cobros":
            return build_cobros_section()
        if section == "documentos":
            return build_documentos_section()
        if section == "contactos":
            return build_contactos_section()
        if section == "empleadores":
            return build_empleadores_section()
        if section == "trayectoria_administrativa":
            return build_administrative_history_section()
        if section == "historial":
            return build_historial_section()

        return build_ficha_section()

    def set_section(section):
        state["section"] = section
        content_container.content = build_section_content()
        page.update()

    def nav_button(label, section):
        is_active = state.get("section") == section
        return ft.Container(
            content=ft.Text(
                label,
                size=13,
                weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500,
                color=Q_PRIMARY_DARK if is_active else Q_MUTED,
            ),
            bgcolor="#EAF3FF" if is_active else Q_WHITE,
            border=ft.border.all(1, "#B9D7FF" if is_active else Q_BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ink=True,
            on_click=lambda e, s=section: set_section(s),
        )

    menu_items = [
        ("Ficha cliente", "ficha"),
        ("Actividad operativa", "actividad"),
        ("Hojas de encargo", "hojas"),
        ("Cobros", "cobros"),
        ("Documentos Box", "documentos"),
        ("Contactos", "contactos"),
        ("Empleadores", "empleadores"),
        (
            "Trayectoria administrativa",
            "trayectoria_administrativa",
        ),
        ("Historial / relaciones", "historial"),
    ]

    content_container.content = build_section_content()

    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Container(
                        width=230,
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=14,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                _photo_placeholder(client),
                                ft.Text(_nombre_completo(client), size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                status_badge(client.get("estado_cliente") or "-"),
                                ft.Text(
                                    f"Ficha completa: {_porcentaje_ficha(client)}%",
                                    size=12,
                                    color=_progress_color(_porcentaje_ficha(client)),
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Divider(),
                                ft.Text("Menú cliente", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Navega por áreas sin una ficha única demasiado larga.", size=12, color=Q_MUTED),
                                ft.Divider(),
                                *[nav_button(label, section) for label, section in menu_items],
                                ft.Container(expand=True),
                                ft.Divider() if sidebar_actions else ft.Container(),
                                ft.Row(
                                    controls=sidebar_actions,
                                    spacing=6,
                                    alignment=ft.MainAxisAlignment.CENTER,
                                    visible=bool(sidebar_actions),
                                ),
                            ],
                            spacing=8,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=Q_WHITE,
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=14,
                        padding=16,
                        content=content_container,
                    ),
                ],
                spacing=14,
                expand=True,
            ),
        ],
        spacing=16,
        expand=True,
    )

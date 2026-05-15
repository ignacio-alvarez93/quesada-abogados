import csv
import os
import subprocess
import sys
import sqlite3
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
    "Otro familiar",
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
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
                FOREIGN KEY (cliente_referenciado_id) REFERENCES clientes(id)
            )
            """
        )
        for column in ["actividad", "cnae", "cno_sepe"]:
            _ensure_column(conn, "cliente_contactos", column, "TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente
            ON cliente_contactos(cliente_id, activo, tipo_contacto)
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
                    cr.segundo_apellido AS ref_segundo_apellido
                FROM cliente_contactos cc
                LEFT JOIN clientes cr ON cr.id = cc.cliente_referenciado_id
                WHERE cc.cliente_id = ?
                  AND COALESCE(cc.activo, 1) = 1
                ORDER BY cc.tipo_contacto ASC, cc.parentesco ASC, cc.nombre ASC, cc.id DESC
                """,
                (int(cliente_id),),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _save_client_contact(data):
    _ensure_client_contacts_schema()
    fields = [
        "cliente_id", "tipo_contacto", "parentesco", "cliente_referenciado_id",
        "nombre", "primer_apellido", "segundo_apellido", "nie", "pasaporte", "dni",
        "nacionalidad", "fecha_nacimiento", "telefono", "email", "estado_cliente",
        "domicilio_espana", "localidad", "provincia", "codigo_postal",
        "localidad_nacimiento", "pais_nacimiento", "nombre_padre", "nombre_madre",
        "estado_civil", "sexo", "actividad", "cnae", "cno_sepe",
        "observaciones", "observaciones_internas",
    ]
    with _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO cliente_contactos ({", ".join(fields)}, updated_at)
            VALUES ({", ".join("?" for _ in fields)}, CURRENT_TIMESTAMP)
            """,
            [data.get(field) for field in fields],
        )
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


def client_detail_view(page, client, on_back=None, on_edit=None):
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
                        ("Fecha nacimiento", _fecha_display(client.get("fecha_nacimiento"))),
                        ("Edad", _calcular_edad(client.get("fecha_nacimiento"))),
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

    def _render_contact_table(items, empty_message, open_new_callback, is_employer=False):
        if not items:
            return ft.Column(
                controls=[
                    empty_state(empty_message),
                    primary_button("Nuevo empleador" if is_employer else "Nuevo contacto", open_new_callback),
                ],
                spacing=12,
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
                    ["Parentesco", "Nombre", "Documento", "Teléfono", "Email", "Es cliente", "Cliente referenciado"],
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
            "codigo_postal": codigo_postal,
            "localidad_nacimiento": localidad_nacimiento,
            "nombre_padre": nombre_padre,
            "nombre_madre": nombre_madre,
            "estado_civil": estado_civil,
            "observaciones": observaciones,
            "observaciones_internas": observaciones_internas,
        }

        referencia_cliente = None

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

        def close_contact_dialog(e=None):
            contacto_dialog.open = False
            page.update()

        def clear_contact_form():
            parentesco.value = None
            referencia_cliente.set_value("", update=False)
            nacionalidad_autocomplete.set_value("", update=False)
            pais_nacimiento_autocomplete.set_value("", update=False)
            provincia_autocomplete.set_value("", update=False)
            localidad_autocomplete.set_options([], clear_value=True)
            localidad_autocomplete.input.label = "Localidad"
            for control in controls.values():
                control.value = ""

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

            _save_client_contact(data)
            close_contact_dialog()
            content_container.content = build_contactos_section()
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
                        is_employer=False,
                    ),
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_empleadores_section():
        empleadores = _contact_rows("Empleador / Empresa")

        actividades_options = _load_catalog_options("actividades_cnae.csv", "CNAE")
        cno_sepe_options = _load_catalog_options("cno_sepe_2011.csv", "CNO/SEPE")

        empresa = _text_input_erp("Empresa / empleador", 360)
        cif = _text_input_erp("CIF / NIF", 220)
        telefono = _text_input_erp("Teléfono", 220)
        email = _text_input_erp("Email", 320)
        domicilio = _text_input_erp("Domicilio", 520)
        localidad = _text_input_erp("Localidad", 220)
        provincia = _text_input_erp("Provincia", 220)
        codigo_postal = _text_input_erp("Código postal", 160)
        cnae = _text_input_erp("CNAE", 160)
        cnae.read_only = True
        cno_sepe_codigo = _text_input_erp("CNO/SEPE", 180)
        cno_sepe_codigo.read_only = True
        observaciones = ft.TextField(
            label="Observaciones",
            width=640,
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color="#18BFEA",
        )

        def on_actividad_selected(value=None):
            cnae.value = _extract_catalog_code(actividad_autocomplete.get_value())
            page.update()

        def on_cno_selected(value=None):
            cno_sepe_codigo.value = _extract_catalog_code(cno_sepe_autocomplete.get_value())
            page.update()

        actividad_autocomplete = AppAutocomplete(
            page=page,
            label="Actividad de la empresa",
            options=actividades_options,
            width=620,
            max_results=10,
            on_select=on_actividad_selected,
            allow_free_text=True,
        )

        cno_sepe_autocomplete = AppAutocomplete(
            page=page,
            label="Ocupación CNO/SEPE",
            options=cno_sepe_options,
            width=620,
            max_results=10,
            on_select=on_cno_selected,
            allow_free_text=True,
        )

        def close_employer_dialog(e=None):
            employer_dialog.open = False
            page.update()

        def clear_employer_form():
            for control in [empresa, cif, telefono, email, domicilio, localidad, provincia, codigo_postal, cnae, cno_sepe_codigo, observaciones]:
                control.value = ""
            actividad_autocomplete.set_value("", update=False)
            cno_sepe_autocomplete.set_value("", update=False)

        def save_employer(e=None):
            if not empresa.value:
                page.snack_bar = ft.SnackBar(ft.Text("Indica el nombre de la empresa o empleador"))
                page.snack_bar.open = True
                page.update()
                return

            actividad_value = actividad_autocomplete.get_value()
            cno_value = cno_sepe_autocomplete.get_value()

            _save_client_contact(
                {
                    "cliente_id": cliente_id,
                    "tipo_contacto": "Empleador / Empresa",
                    "parentesco": "",
                    "cliente_referenciado_id": None,
                    "nombre": empresa.value or "",
                    "primer_apellido": "",
                    "segundo_apellido": "",
                    "nie": "",
                    "pasaporte": "",
                    "dni": cif.value or "",
                    "nacionalidad": "",
                    "fecha_nacimiento": "",
                    "telefono": telefono.value or "",
                    "email": email.value or "",
                    "estado_cliente": "",
                    "domicilio_espana": domicilio.value or "",
                    "localidad": localidad.value or "",
                    "provincia": provincia.value or "",
                    "codigo_postal": codigo_postal.value or "",
                    "localidad_nacimiento": "",
                    "pais_nacimiento": "",
                    "nombre_padre": "",
                    "nombre_madre": "",
                    "estado_civil": "",
                    "sexo": "",
                    "actividad": _extract_catalog_description(actividad_value),
                    "cnae": cnae.value or _extract_catalog_code(actividad_value),
                    "cno_sepe": cno_sepe_codigo.value or _extract_catalog_code(cno_value),
                    "observaciones": observaciones.value or "",
                    "observaciones_internas": "",
                }
            )
            close_employer_dialog()
            content_container.content = build_empleadores_section()
            page.update()

        employer_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nuevo empleador / empresa"),
            content=_themed_dialog_content(
                "Nuevo empleador / empresa",
                "Datos de empresa alineados con Mercurio: actividad, CNAE y ocupación CNO/SEPE.",
                [
                    _dialog_section(
                        "Datos empresa / empleador",
                        ft.Icons.BUSINESS,
                        [
                            ft.Row([empresa, cif], wrap=True, spacing=10),
                            ft.Row([telefono, email], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Actividad y ocupación",
                        ft.Icons.WORK,
                        [
                            actividad_autocomplete.control,
                            ft.Row([cnae, cno_sepe_codigo], wrap=True, spacing=10),
                            cno_sepe_autocomplete.control,
                        ],
                    ),
                    _dialog_section(
                        "Dirección",
                        ft.Icons.HOME_WORK,
                        [
                            domicilio,
                            ft.Row([provincia, localidad, codigo_postal], wrap=True, spacing=10),
                        ],
                    ),
                    _dialog_section(
                        "Observaciones",
                        ft.Icons.NOTES,
                        [observaciones],
                    ),
                ],
                width=930,
                height=640,
            ),
            actions=[
                secondary_button("Cancelar", close_employer_dialog),
                primary_button("Guardar empleador", save_employer),
            ],
        )

        if employer_dialog not in page.overlay:
            page.overlay.append(employer_dialog)

        def open_new_employer(e=None):
            clear_employer_form()
            employer_dialog.open = True
            page.update()

        if not empleadores:
            content = ft.Column(
                controls=[
                    empty_state("Este cliente no tiene empleadores o empresas vinculadas"),
                    primary_button("Nuevo empleador", open_new_employer),
                ],
                spacing=12,
            )
        else:
            rows = []
            for item in empleadores:
                rows.append(
                    [
                        item.get("nombre") or "-",
                        item.get("dni") or item.get("nie") or item.get("pasaporte") or "-",
                        item.get("actividad") or "-",
                        item.get("cnae") or "-",
                        item.get("cno_sepe") or "-",
                        item.get("telefono") or "-",
                        item.get("email") or "-",
                        item.get("localidad") or "-",
                    ]
                )

            content = ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            primary_button("Nuevo empleador", open_new_employer),
                            ft.Container(
                                content=ft.Text(
                                    f"Empleadores: {len(empleadores)}",
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
                        ["Empresa", "CIF/NIF", "Actividad", "CNAE", "CNO/SEPE", "Teléfono", "Email", "Localidad"],
                        rows,
                        height=390,
                    ),
                ],
                spacing=12,
            )

        return ft.Column(
            controls=[
                ft.Text("Empleadores / Empresas", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(
                    "Empresas, empleadores y ocupaciones vinculadas al cliente para expedientes laborales.",
                    size=13,
                    color=Q_MUTED,
                ),
                _section_card("Empleadores", content),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
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

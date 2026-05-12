import os
import subprocess
import sys
import sqlite3
from pathlib import Path
from datetime import date, datetime

import flet as ft

from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_detail_section import detail_section
from frontend.components.app_badge import status_badge
from frontend.components.app_table import app_table
from frontend.components.app_empty_state import empty_state

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"

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

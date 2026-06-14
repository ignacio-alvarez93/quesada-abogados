import csv
import re
from pathlib import Path

import flet as ft

from backend.services import company_service, client_company_service, company_tax_service
from backend.services.master_data_service import (
    get_provincias_nombres,
    get_localidades_by_provincia,
    get_tipos_via,
)
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.views.company_detail_view import company_detail_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]

Q_PRIMARY = "#003B7A"
Q_PRIMARY_DARK = "#002B5C"
Q_ACCENT = "#18BFEA"
Q_BG = "#F4F7FB"
Q_CARD = "#FFFFFF"
Q_BORDER = "#D8E2F0"
Q_MUTED = "#5E6C84"
Q_SUCCESS = "#0F8A5F"
Q_DANGER = "#B42318"
Q_CHIP_BG = "#EAF3FF"
Q_ROW_SELECTED = "#EAF3FF"

ENTITY_TYPES = [
    ("juridica", "Sociedad / empresa"),
    ("autonomo", "Autónomo"),
    ("persona_fisica", "Persona física empleadora"),
]

DOCUMENT_TYPES = [
    ("CIF", "CIF"),
    ("NIF", "NIF"),
    ("DNI", "DNI"),
    ("NIE", "NIE"),
    ("PASAPORTE", "Pasaporte"),
]


def _safe_values(loader, fallback=None):
    try:
        values = loader() or []
        return [str(v).strip() for v in values if str(v or "").strip()]
    except Exception:
        return fallback or []


def _find_catalog_file(filename):
    candidates = [
        PROJECT_ROOT / "database" / "master_data" / filename,
        PROJECT_ROOT / "database" / "catalogs" / filename,
        PROJECT_ROOT / "data" / filename,
        PROJECT_ROOT / "assets" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    for candidate in (PROJECT_ROOT / "database").rglob(filename):
        if candidate.is_file():
            return candidate
    return None


def _load_catalog_options(filename, label_code="Código"):
    path = _find_catalog_file(filename)
    if not path:
        return []

    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    sample = raw[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
    except Exception:
        dialect = csv.excel
        dialect.delimiter = ";"

    rows = []
    for row in csv.reader(raw.splitlines(), dialect):
        clean = [str(col or "").strip() for col in row]
        clean = [col for col in clean if col]
        if not clean:
            continue

        first = clean[0].lower()
        if first in {"codigo", "código", "cnae", "code", label_code.lower()}:
            continue

        if len(clean) >= 2:
            code = clean[0]
            description = " - ".join(clean[1:])
            rows.append(f"{code} - {description}")
        else:
            rows.append(clean[0])

    return rows


def _extract_catalog_code(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if " - " in value:
        return value.split(" - ", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", value)
    return match.group(1).strip() if match else value


def _extract_catalog_description(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if " - " in value:
        return value.split(" - ", 1)[1].strip()
    return value


def _text_input(label, width=260, multiline=False, read_only=False):
    return ft.TextField(
        label=label,
        width=width,
        multiline=multiline,
        min_lines=2 if multiline else 1,
        max_lines=4 if multiline else 1,
        read_only=read_only,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color=Q_ACCENT,
        cursor_color=Q_PRIMARY,
        content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
    )


def _dropdown(label, options, width=260, value=None):
    return ft.Dropdown(
        label=label,
        width=width,
        value=value,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color=Q_ACCENT,
        options=[ft.dropdown.Option(key, text) for key, text in options],
    )


def _primary_button(text, on_click=None, icon=None):
    return ft.ElevatedButton(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=16, color="#FFFFFF") if icon else ft.Container(width=0),
                ft.Text(text, color="#FFFFFF"),
            ],
            spacing=8,
            tight=True,
        ),
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            bgcolor=Q_PRIMARY,
            color="#FFFFFF",
        ),
    )


def _secondary_button(text, on_click=None, icon=None):
    return ft.OutlinedButton(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=16, color=Q_PRIMARY) if icon else ft.Container(width=0),
                ft.Text(text, color=Q_PRIMARY),
            ],
            spacing=8,
            tight=True,
        ),
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            color=Q_PRIMARY,
            side=ft.BorderSide(1, Q_BORDER),
        ),
    )


def _section_card(title, content, subtitle=None, icon=None, expand=False):
    title_row = ft.Row(
        controls=[
            ft.Container(
                width=34,
                height=34,
                border_radius=10,
                bgcolor=Q_CHIP_BG,
                alignment=ft.Alignment(0, 0),
                content=ft.Text(icon or "•", size=16, color=Q_PRIMARY),
            ),
            ft.Column(
                controls=[
                    ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(subtitle, size=12, color=Q_MUTED) if subtitle else ft.Container(height=0),
                ],
                spacing=2,
                expand=True,
            ),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    return ft.Container(
        expand=expand,
        bgcolor=Q_CARD,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
        content=ft.Column(controls=[title_row, content], spacing=14, expand=expand),
    )


def _entity_type_label(value):
    lookup = dict(ENTITY_TYPES)
    return lookup.get(value or "", value or "")


def _snack(page, message, error=False):
    page.snack_bar = ft.SnackBar(
        ft.Text(message),
        bgcolor=Q_DANGER if error else Q_SUCCESS,
    )
    page.snack_bar.open = True
    page.update()


def _context_line(label, value, icon="•"):
    return ft.Row(
        controls=[
            ft.Text(icon or "•", size=14),
            ft.Column(
                controls=[
                    ft.Text(label, size=11, color=Q_MUTED),
                    ft.Text(str(value or "-"), size=13, color=Q_PRIMARY_DARK, weight=ft.FontWeight.W_500),
                ],
                spacing=1,
                expand=True,
            ),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _company_display_name(company):
    return (company or {}).get("trade_name") or (company or {}).get("name") or "Empresa sin nombre"


def _small_label(label, value, icon=None):
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=10, vertical=8),
        border_radius=12,
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        content=ft.Row(
            controls=[
                ft.Text(icon or "•", size=14),
                ft.Column(
                    controls=[
                        ft.Text(label, size=10, color=Q_MUTED),
                        ft.Text(value or "-", size=12, color=Q_PRIMARY_DARK, weight=ft.FontWeight.W_500),
                    ],
                    spacing=1,
                    expand=True,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def company_initials(company):
    name = _company_display_name(company)
    parts = [part for part in re.split(r"\s+", name or "") if part]
    initials = "".join(part[0] for part in parts[:2]).upper()
    return initials or "EM"


def company_completion_percent(company):
    fields = [
        "name", "tax_id", "codigo_cuenta_cotizacion", "entity_type", "main_activity", "cnae_code",
        "phone", "email", "address", "city", "province",
    ]
    completed = sum(1 for field in fields if (company or {}).get(field))
    return int((completed / len(fields)) * 100) if fields else 0


def company_status_badge(company):
    pct = company_completion_percent(company)
    if pct >= 80:
        color, bg, text = "#027A48", "#ECFDF3", f"Ficha {pct}%"
    elif pct >= 50:
        color, bg, text = "#B54708", "#FFFAEB", f"Ficha {pct}%"
    else:
        color, bg, text = "#B42318", "#FEF3F2", f"Ficha {pct}%"
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )


def context_card(title, controls):
    return ft.Container(
        width=360,
        content=ft.Column(
            controls=[
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY),
                *controls,
            ],
            spacing=8,
        ),
        bgcolor=Q_CARD,
        border=ft.border.all(1, "#E4E7EC"),
        border_radius=14,
        padding=12,
    )


def context_line(label, value):
    safe_value = str(value or "-").strip() or "-"
    return ft.Container(
        padding=ft.padding.only(top=2, bottom=2),
        content=ft.Column(
            controls=[
                ft.Text(label, size=12, color="#64748B"),
                ft.Text(
                    safe_value,
                    size=12,
                    color="#101828",
                    weight=ft.FontWeight.W_600,
                    no_wrap=False,
                ),
            ],
            spacing=2,
        ),
    )


def build_empty_company_context_panel():
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.BUSINESS, size=42, color=Q_PRIMARY),
                    bgcolor=Q_CHIP_BG,
                    border_radius=50,
                    width=82,
                    height=82,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Text(
                    "Sin empresa seleccionada",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    "Selecciona una empresa en la tabla para ver aquí su resumen operativo.",
                    size=13,
                    color="#64748B",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=360,
        bgcolor=Q_CARD,
        border=ft.border.all(1, "#E4E7EC"),
        border_radius=16,
        padding=18,
        margin=ft.margin.only(top=0),
    )


def company_context_header_card(company):
    return ft.Container(
        width=360,
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(
                        company_initials(company),
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color="#FFFFFF",
                    ),
                    width=52,
                    height=52,
                    border_radius=26,
                    bgcolor=Q_PRIMARY,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Column(
                    controls=[
                        ft.Text(_company_display_name(company), size=15, weight=ft.FontWeight.BOLD, color="#101828", no_wrap=False),
                        ft.Text(company.get("tax_id") or "Sin CIF/NIF", size=12, color="#64748B", no_wrap=False),
                        company_status_badge(company),
                    ],
                    spacing=5,
                    expand=True,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=Q_CARD,
        border=ft.border.all(1, "#E4E7EC"),
        border_radius=16,
        padding=14,
        margin=ft.margin.only(top=0),
    )


def build_company_context_alerts(company, stats):
    alerts = []
    if not company.get("tax_id"):
        alerts.append("Sin CIF/NIF")
    if not company.get("codigo_cuenta_cotizacion"):
        alerts.append("Sin CCC")
    if not company.get("cnae_code"):
        alerts.append("Sin CNAE")
    if not company.get("phone"):
        alerts.append("Sin teléfono")
    if not company.get("email"):
        alerts.append("Sin email")
    if not company.get("address") and not company.get("city"):
        alerts.append("Sin domicilio estructurado")
    if int(stats.get("clients") or 0) == 0:
        alerts.append("Sin clientes vinculados")
    if not alerts:
        alerts.append("Sin alertas críticas")
    return [
        ft.Text(
            alert,
            size=12,
            color="#B42318" if alert != "Sin alertas críticas" else "#027A48",
            weight=ft.FontWeight.W_600,
        )
        for alert in alerts[:6]
    ]


def companies_view(page: ft.Page):
    company_service.ensure_schema()
    try:
        company_tax_service.ensure_schema()
    except Exception:
        pass

    state = {
        "companies": [],
        "selected_id": None,
        "editing_id": None,
    }

    root_container = ft.Container(expand=True)
    table_container = ft.Container()
    context_container = ft.Container(
        width=360,
        padding=ft.padding.only(top=0),
        margin=ft.margin.only(top=0),
    )
    counter_text = ft.Text("", size=12, color=Q_MUTED)

    actividades_options = _load_catalog_options("actividades_cnae.csv", "CNAE")
    provincia_options = _safe_values(get_provincias_nombres)
    tipo_via_options = [(value, value) for value in _safe_values(get_tipos_via, ["CALLE", "AVENIDA", "PLAZA", "PASEO", "CARRETERA"])]

    search_input = _text_input("Buscar por nombre, CIF/NIF, CCC o actividad", width=420)
    entity_filter = _dropdown("Tipo", [("", "Todos")] + ENTITY_TYPES, width=240, value="")

    entity_type = _dropdown("Tipo de entidad", ENTITY_TYPES, width=280, value="juridica")
    name = _text_input("Razón social / nombre visible", 420)
    trade_name = _text_input("Nombre comercial", 320)
    document_type = _dropdown("Tipo documento", DOCUMENT_TYPES, width=180, value="CIF")
    tax_id = _text_input("CIF / NIF / DNI / NIE", 220)
    codigo_cuenta_cotizacion = _text_input("Código cuenta cotización", 260)
    first_name = _text_input("Nombre persona física/autónomo", 260)
    last_name_1 = _text_input("Primer apellido", 240)
    last_name_2 = _text_input("Segundo apellido", 240)
    company_type = _text_input("Forma / tipo", 260)
    main_activity = _text_input("Actividad principal", 520)
    cnae_code = _text_input("CNAE", 160, read_only=True)
    cnae_description = _text_input("Descripción CNAE", 420, read_only=True)
    phone = _text_input("Teléfono", 220)
    email = _text_input("Email", 300)
    website = _text_input("Web", 300)
    address = _text_input("Domicilio completo", 520)
    tipo_via = _dropdown("Tipo vía", tipo_via_options, width=170, value="CALLE" if tipo_via_options else None)
    nombre_via = _text_input("Nombre vía", 300)
    numero = _text_input("Número", 100)
    piso = _text_input("Piso", 100)
    puerta = _text_input("Puerta", 100)
    escalera = _text_input("Escalera", 100)
    postal_code = _text_input("Código postal", 150)
    country = _text_input("País", 220)
    country.value = "España"
    notes = _text_input("Notas", 640, multiline=True)

    def on_activity_selected(value=None):
        selected = actividad_autocomplete.get_value()
        cnae_code.value = _extract_catalog_code(selected)
        cnae_description.value = _extract_catalog_description(selected)
        if selected and not (main_activity.value or "").strip():
            main_activity.value = _extract_catalog_description(selected)
        page.update()

    actividad_autocomplete = AppAutocomplete(
        page=page,
        label="Actividad CNAE",
        options=actividades_options,
        width=640,
        max_results=10,
        on_select=on_activity_selected,
        allow_free_text=True,
    )

    def on_province_selected(value=None):
        provincia_value = provincia_autocomplete.get_value().strip()
        if not provincia_value:
            localidad_autocomplete.set_options([], clear_value=True)
            localidad_autocomplete.input.label = "Localidad"
            page.update()
            return
        localidades = _safe_values(lambda: get_localidades_by_provincia(provincia_value))
        localidad_autocomplete.set_options(localidades, clear_value=True)
        localidad_autocomplete.input.label = f"Localidad ({len(localidades)})" if localidades else "Localidad (sin datos)"
        page.update()

    provincia_autocomplete = AppAutocomplete(
        page=page,
        label="Provincia",
        options=provincia_options,
        width=260,
        max_results=12,
        on_select=on_province_selected,
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

    form_controls = [
        entity_type, name, trade_name, document_type, tax_id, codigo_cuenta_cotizacion,
        first_name, last_name_1, last_name_2, company_type,
        main_activity, cnae_code, cnae_description, phone, email, website,
        address, tipo_via, nombre_via, numero, piso, puerta, escalera,
        postal_code, country, notes,
    ]

    def selected_company():
        selected_id = state.get("selected_id")
        if not selected_id:
            return None
        for company in state.get("companies") or []:
            if company.get("id") == selected_id:
                return company
        return None

    def get_company_stats(company_id):
        stats = {"clients": 0, "representatives": 0, "fiscal_years": 0, "tax_documents": 0}
        try:
            stats["clients"] = len(client_company_service.list_company_clients(company_id, active_only=False))
        except Exception:
            pass
        try:
            stats["representatives"] = len(company_service.list_company_representatives(company_id))
        except Exception:
            pass
        try:
            stats["fiscal_years"] = len(company_tax_service.list_fiscal_years(company_id))
        except Exception:
            pass
        try:
            stats["tax_documents"] = len(company_tax_service.list_tax_documents(company_id))
        except Exception:
            pass
        return stats

    def clear_form():
        state["editing_id"] = None
        for control in form_controls:
            control.value = ""
        entity_type.value = "juridica"
        document_type.value = "CIF"
        if tipo_via_options:
            tipo_via.value = "CALLE" if any(v == "CALLE" for v, _ in tipo_via_options) else tipo_via_options[0][0]
        country.value = "España"
        actividad_autocomplete.set_value("", update=False)
        provincia_autocomplete.set_value("", update=False)
        localidad_autocomplete.set_options([], clear_value=True)
        localidad_autocomplete.input.label = "Localidad"

    def fill_form(company):
        state["editing_id"] = company.get("id")
        for field, control in [
            ("entity_type", entity_type),
            ("name", name),
            ("trade_name", trade_name),
            ("document_type", document_type),
            ("tax_id", tax_id),
            ("codigo_cuenta_cotizacion", codigo_cuenta_cotizacion),
            ("first_name", first_name),
            ("last_name_1", last_name_1),
            ("last_name_2", last_name_2),
            ("company_type", company_type),
            ("main_activity", main_activity),
            ("cnae_code", cnae_code),
            ("cnae_description", cnae_description),
            ("phone", phone),
            ("email", email),
            ("website", website),
            ("address", address),
            ("tipo_via", tipo_via),
            ("nombre_via", nombre_via),
            ("numero", numero),
            ("piso", piso),
            ("puerta", puerta),
            ("escalera", escalera),
            ("postal_code", postal_code),
            ("country", country),
            ("notes", notes),
        ]:
            control.value = company.get(field) or ""

        activity_label = ""
        if company.get("cnae_code") or company.get("cnae_description"):
            activity_label = f"{company.get('cnae_code') or ''} - {company.get('cnae_description') or company.get('main_activity') or ''}".strip(" -")
        actividad_autocomplete.set_value(activity_label, update=False)

        provincia_value = company.get("province") or ""
        ciudad_value = company.get("city") or ""
        provincia_autocomplete.set_value(provincia_value, update=False)
        localidades = _safe_values(lambda: get_localidades_by_provincia(provincia_value)) if provincia_value else []
        localidad_autocomplete.set_options(localidades, clear_value=False)
        localidad_autocomplete.input.label = f"Localidad ({len(localidades)})" if localidades else "Localidad"
        localidad_autocomplete.set_value(ciudad_value, update=False)

    def close_dialog(e=None):
        company_dialog.open = False
        page.update()

    def open_new_dialog(e=None):
        clear_form()
        company_dialog.title = ft.Text("Nueva empresa / entidad")
        company_dialog.open = True
        page.update()

    def open_edit_dialog(company=None):
        company = company or selected_company()
        if not company:
            _snack(page, "Selecciona una empresa", error=True)
            return
        fill_form(company)
        company_dialog.title = ft.Text("Editar empresa / entidad")
        company_dialog.open = True
        page.update()

    def save_company(e=None):
        activity_value = actividad_autocomplete.get_value()
        provincia_value = provincia_autocomplete.get_value()
        localidad_value = localidad_autocomplete.get_value()

        data = {
            "entity_type": entity_type.value or "juridica",
            "name": name.value or "",
            "trade_name": trade_name.value or "",
            "document_type": document_type.value or "",
            "tax_id": tax_id.value or "",
            "codigo_cuenta_cotizacion": codigo_cuenta_cotizacion.value or "",
            "first_name": first_name.value or "",
            "last_name_1": last_name_1.value or "",
            "last_name_2": last_name_2.value or "",
            "company_type": company_type.value or "",
            "main_activity": main_activity.value or _extract_catalog_description(activity_value),
            "cnae_code": cnae_code.value or _extract_catalog_code(activity_value),
            "cnae_description": cnae_description.value or _extract_catalog_description(activity_value),
            "phone": phone.value or "",
            "email": email.value or "",
            "website": website.value or "",
            "address": address.value or "",
            "tipo_via": tipo_via.value or "",
            "nombre_via": nombre_via.value or "",
            "numero": numero.value or "",
            "piso": piso.value or "",
            "puerta": puerta.value or "",
            "escalera": escalera.value or "",
            "postal_code": postal_code.value or "",
            "city": localidad_value or "",
            "province": provincia_value or "",
            "country": country.value or "España",
            "notes": notes.value or "",
        }
        try:
            if state.get("editing_id"):
                saved = company_service.update_company(state["editing_id"], data)
                msg = "Empresa actualizada"
            else:
                saved = company_service.create_company(data)
                msg = "Empresa creada"
            state["selected_id"] = saved.get("id")
            close_dialog()
            refresh()
            _snack(page, msg)
        except Exception as exc:
            _snack(page, f"No se pudo guardar la empresa: {exc}", error=True)

    def delete_company(company=None):
        company = company or selected_company()
        if not company:
            return
        try:
            company_service.delete_company(company["id"])
            state["selected_id"] = None
            refresh()
            _snack(page, "Empresa eliminada")
        except Exception as exc:
            _snack(page, f"No se pudo eliminar la empresa: {exc}", error=True)

    def select_company(company):
        company_id = company.get("id")
        state["selected_id"] = None if state.get("selected_id") == company_id else company_id
        render_table()
        render_context_panel()
        page.update()

    def show_master(e=None):
        render_master()
        page.update()

    def open_company_detail(company=None):
        company = company or selected_company()
        if not company:
            _snack(page, "Selecciona una empresa", error=True)
            return
        root_container.content = company_detail_view(
            page,
            company.get("id"),
            on_back=show_master,
            on_edit=lambda c=company: open_edit_dialog(company_service.get_company(c.get("id")) or c),
        )
        page.update()

    def render_table():
        rows = []
        for company in state.get("companies") or []:
            is_selected = company.get("id") == state.get("selected_id")
            rows.append(
                ft.DataRow(
                    color=Q_ROW_SELECTED if is_selected else None,
                    cells=[
                        ft.DataCell(
                            ft.Checkbox(
                                value=is_selected,
                                on_change=lambda e, c=company: select_company(c),
                            )
                        ),
                        ft.DataCell(
                            ft.Column(
                                controls=[
                                    ft.Text(company.get("name") or "", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(company.get("trade_name") or _entity_type_label(company.get("entity_type")), size=11, color=Q_MUTED),
                                ],
                                spacing=2,
                            )
                        ),
                        ft.DataCell(ft.Text(company.get("tax_id") or "-")),
                        ft.DataCell(ft.Text(_entity_type_label(company.get("entity_type")) or "-")),
                        ft.DataCell(ft.Text(company.get("main_activity") or company.get("cnae_description") or "-")),
                        ft.DataCell(ft.Text(company.get("cnae_code") or "-")),
                        ft.DataCell(ft.Text(company.get("city") or "-")),
                        ft.DataCell(
                            ft.TextButton(
                                content=ft.Text("Ficha"),
                                on_click=lambda e, c=company: open_company_detail(c),
                            )
                        ),
                    ],
                )
            )

        counter_text.value = f"{len(rows)} empresa(s) / entidad(es)"
        if not rows:
            table_container.content = ft.Container(
                padding=34,
                alignment=ft.Alignment(0, 0),
                bgcolor=Q_CARD,
                border_radius=14,
                border=ft.border.all(1, Q_BORDER),
                content=ft.Column(
                    controls=[
                        ft.Text("🏢", size=32),
                        ft.Text("No hay empresas que coincidan con el filtro", color=Q_MUTED),
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
            return

        table_container.content = ft.Row(
            controls=[
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Sel.")),
                        ft.DataColumn(ft.Text("Empresa")),
                        ft.DataColumn(ft.Text("CIF/NIF")),
                        ft.DataColumn(ft.Text("Tipo")),
                        ft.DataColumn(ft.Text("Actividad")),
                        ft.DataColumn(ft.Text("CNAE")),
                        ft.DataColumn(ft.Text("Localidad")),
                        ft.DataColumn(ft.Text("Ficha")),
                    ],
                    rows=rows,
                    column_spacing=16,
                    heading_row_color=ft.Colors.BLUE_50,
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def render_context_panel():
        company = selected_company()
        if not company:
            context_container.content = build_empty_company_context_panel()
            return

        stats = get_company_stats(company.get("id"))
        address_parts = [company.get("address"), company.get("postal_code"), company.get("city"), company.get("province")]
        address_text = " · ".join([p for p in address_parts if p])
        activity_text = company.get("main_activity") or company.get("cnae_description") or "-"
        contact_text = " · ".join([v for v in [company.get("phone"), company.get("email")] if v]) or "-"

        context_container.content = ft.Column(
            controls=[
                company_context_header_card(company),
                context_card(
                    "Resumen ficha",
                    [
                        context_line("Tipo", _entity_type_label(company.get("entity_type"))),
                        context_line("Documento", company.get("tax_id")),
                        context_line("CCC", company.get("codigo_cuenta_cotizacion")),
                        context_line("Teléfono", company.get("phone")),
                        context_line("Email", company.get("email")),
                        context_line("Web", company.get("website")),
                        context_line("Ficha", f"{company_completion_percent(company)}%"),
                        _primary_button("Ver ficha", lambda e, c=company: open_company_detail(c), icon=ft.Icons.OPEN_IN_NEW),
                    ],
                ),
                context_card(
                    "Actividad",
                    [
                        context_line("Actividad", activity_text),
                        context_line("CNAE", company.get("cnae_code")),
                        context_line("Descripción", company.get("cnae_description")),
                    ],
                ),
                context_card(
                    "Vinculaciones",
                    [
                        context_line("Clientes", stats.get("clients")),
                        context_line("Representantes", stats.get("representatives")),
                        context_line("Ejercicios fiscales", stats.get("fiscal_years")),
                        context_line("Documentos fiscales", stats.get("tax_documents")),
                    ],
                ),
                context_card(
                    "Domicilio",
                    [
                        context_line("Dirección", company.get("address")),
                        context_line("Código postal", company.get("postal_code")),
                        context_line("Localidad", company.get("city")),
                        context_line("Provincia", company.get("province")),
                        context_line("País", company.get("country")),
                    ],
                ),
                context_card(
                    "Alertas",
                    build_company_context_alerts(company, stats),
                ),
                ft.Row(
                    controls=[
                        _secondary_button("Editar", lambda e, c=company: open_edit_dialog(c), icon=ft.Icons.EDIT),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

    def refresh(e=None):
        try:
            state["companies"] = company_service.list_companies(
                search=(search_input.value or "").strip() or None,
                entity_type=(entity_filter.value or "").strip() or None,
                limit=500,
            )
            if state.get("selected_id") and not any(c.get("id") == state.get("selected_id") for c in state.get("companies") or []):
                state["selected_id"] = None
        except Exception as exc:
            state["companies"] = []
            state["selected_id"] = None
            _snack(page, f"No se pudieron cargar las empresas: {exc}", error=True)
        render_table()
        render_context_panel()
        page.update()

    company_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Nueva empresa / entidad"),
        content=ft.Container(
            width=1040,
            height=720,
            content=ft.Column(
                controls=[
                    _section_card(
                        "Datos de entidad",
                        ft.Column(
                            controls=[
                                ft.Row([entity_type, name, trade_name], wrap=True, spacing=10),
                                ft.Row([document_type, tax_id, codigo_cuenta_cotizacion, company_type], wrap=True, spacing=10),
                                ft.Row([first_name, last_name_1, last_name_2], wrap=True, spacing=10),
                            ],
                            spacing=10,
                        ),
                        subtitle="Datos maestros de sociedad, autónomo o persona física empleadora.",
                        icon="🏷️",
                    ),
                    _section_card(
                        "Actividad económica",
                        ft.Column(
                            controls=[
                                actividad_autocomplete.control,
                                ft.Row([main_activity, cnae_code, cnae_description], wrap=True, spacing=10),
                            ],
                            spacing=10,
                        ),
                        subtitle="Selecciona la actividad desde el catálogo CNAE; el código se autocompleta.",
                        icon="📊",
                    ),
                    _section_card(
                        "Contacto y domicilio",
                        ft.Column(
                            controls=[
                                ft.Row([phone, email, website], wrap=True, spacing=10),
                                ft.Row([address], wrap=True, spacing=10),
                                ft.Row([tipo_via, nombre_via, numero, piso, puerta, escalera], wrap=True, spacing=10),
                                ft.Row([provincia_autocomplete.control, localidad_autocomplete.control, postal_code, country], wrap=True, spacing=10),
                            ],
                            spacing=10,
                        ),
                        subtitle="Domicilio estructurado para futuras automatizaciones y documentos.",
                        icon="📍",
                    ),
                    _section_card(
                        "Observaciones",
                        notes,
                        subtitle="Notas internas no visibles fuera del ERP.",
                        icon="📝",
                    ),
                ],
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            _secondary_button("Cancelar", close_dialog),
            _primary_button("Guardar", save_company),
        ],
    )
    if company_dialog not in page.overlay:
        page.overlay.append(company_dialog)

    search_input.on_change = refresh
    entity_filter.on_change = refresh

    def render_master():
        filters = ft.Container(
            bgcolor=Q_CARD,
            border_radius=12,
            border=ft.border.all(1, Q_BORDER),
            padding=10,
            content=ft.Row(
                controls=[
                    search_input,
                    entity_filter,
                    _secondary_button("Actualizar", refresh, icon=ft.Icons.REFRESH),
                    counter_text,
                ],
                wrap=True,
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        root_container.content = ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=22,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text("Empresas", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text("Directorio maestro de sociedades, autónomos y personas físicas empleadoras", size=14, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            _primary_button("Nueva empresa", open_new_dialog, icon=ft.Icons.ADD),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    controls=[
                                        filters,
                                        table_container,
                                    ],
                                    spacing=6,
                                    expand=True,
                                ),
                            ),
                            context_container,
                        ],
                        spacing=14,
                        expand=True,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=14,
                expand=True,
            ),
        )
        render_table()
        render_context_panel()

    render_master()
    refresh()
    return root_container

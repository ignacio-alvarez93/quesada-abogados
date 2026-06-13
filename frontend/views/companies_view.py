import flet as ft

from backend.services import company_service

Q_PRIMARY = "#003B7A"
Q_PRIMARY_DARK = "#002B5C"
Q_ACCENT = "#18BFEA"
Q_BG = "#F4F7FB"
Q_CARD = "#FFFFFF"
Q_BORDER = "#D8E2F0"
Q_MUTED = "#5E6C84"
Q_SUCCESS = "#0F8A5F"
Q_DANGER = "#B42318"

ENTITY_TYPES = [
    ("juridica", "Sociedad / empresa"),
    ("autonomo", "Autónomo"),
    ("persona_fisica", "Persona física empleadora"),
]


def _text_input(label, width=260, multiline=False):
    return ft.TextField(
        label=label,
        width=width,
        multiline=multiline,
        min_lines=2 if multiline else 1,
        max_lines=4 if multiline else 1,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color=Q_ACCENT,
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
            bgcolor="#003B7A",
            color="#FFFFFF",
        ),
    )


def _secondary_button(text, on_click=None, icon=None):
    return ft.OutlinedButton(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=16) if icon else ft.Container(width=0),
                ft.Text(text),
            ],
            spacing=8,
            tight=True,
        ),
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            color="#003B7A",
            side=ft.BorderSide(1, "#D7E3F4"),
        ),
    )


def _section_card(title, content, subtitle=None):
    controls = [
        ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
    ]
    if subtitle:
        controls.append(ft.Text(subtitle, size=12, color=Q_MUTED))
    controls.append(content)
    return ft.Container(
        bgcolor=Q_CARD,
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
        content=ft.Column(controls=controls, spacing=12),
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


def companies_view(page: ft.Page):
    company_service.ensure_schema()

    state = {
        "companies": [],
        "editing_id": None,
    }

    search_input = _text_input("Buscar por nombre, CIF/NIF o actividad", width=420)
    entity_filter = _dropdown(
        "Tipo",
        [("", "Todos")] + ENTITY_TYPES,
        width=260,
        value="",
    )

    table_container = ft.Container(expand=True)
    counter_text = ft.Text("", size=12, color=Q_MUTED)

    entity_type = _dropdown("Tipo de entidad", ENTITY_TYPES, width=280, value="juridica")
    name = _text_input("Razón social / nombre visible", 420)
    trade_name = _text_input("Nombre comercial", 320)
    document_type = _dropdown("Tipo documento", [("CIF", "CIF"), ("NIF", "NIF"), ("DNI", "DNI"), ("NIE", "NIE"), ("PASAPORTE", "Pasaporte")], width=180, value="CIF")
    tax_id = _text_input("CIF / NIF / DNI / NIE", 220)
    first_name = _text_input("Nombre persona física/autónomo", 260)
    last_name_1 = _text_input("Primer apellido", 240)
    last_name_2 = _text_input("Segundo apellido", 240)
    company_type = _text_input("Forma / tipo", 260)
    main_activity = _text_input("Actividad principal", 520)
    cnae_code = _text_input("CNAE", 160)
    cnae_description = _text_input("Descripción CNAE", 420)
    phone = _text_input("Teléfono", 220)
    email = _text_input("Email", 300)
    website = _text_input("Web", 300)
    address = _text_input("Domicilio", 520)
    tipo_via = _text_input("Tipo vía", 160)
    nombre_via = _text_input("Nombre vía", 300)
    numero = _text_input("Número", 100)
    piso = _text_input("Piso", 100)
    puerta = _text_input("Puerta", 100)
    escalera = _text_input("Escalera", 100)
    postal_code = _text_input("Código postal", 150)
    city = _text_input("Localidad", 220)
    province = _text_input("Provincia", 220)
    country = _text_input("País", 220)
    country.value = "España"
    notes = _text_input("Notas", 640, multiline=True)

    form_controls = [
        entity_type, name, trade_name, document_type, tax_id,
        first_name, last_name_1, last_name_2, company_type,
        main_activity, cnae_code, cnae_description, phone, email, website,
        address, tipo_via, nombre_via, numero, piso, puerta, escalera,
        postal_code, city, province, country, notes,
    ]

    def refresh(e=None):
        try:
            state["companies"] = company_service.list_companies(
                search=(search_input.value or "").strip() or None,
                entity_type=(entity_filter.value or "").strip() or None,
                limit=500,
            )
        except Exception as exc:
            state["companies"] = []
            _snack(page, f"No se pudieron cargar las empresas: {exc}", error=True)
        render_table()
        page.update()

    def clear_form():
        state["editing_id"] = None
        for control in form_controls:
            control.value = ""
        entity_type.value = "juridica"
        document_type.value = "CIF"
        country.value = "España"

    def fill_form(company):
        state["editing_id"] = company.get("id")
        for field, control in [
            ("entity_type", entity_type),
            ("name", name),
            ("trade_name", trade_name),
            ("document_type", document_type),
            ("tax_id", tax_id),
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
            ("city", city),
            ("province", province),
            ("country", country),
            ("notes", notes),
        ]:
            control.value = company.get(field) or ""

    def close_dialog(e=None):
        company_dialog.open = False
        page.update()

    def open_new_dialog(e=None):
        clear_form()
        company_dialog.title = ft.Text("Nueva empresa / entidad")
        company_dialog.open = True
        page.update()

    def open_edit_dialog(company):
        fill_form(company)
        company_dialog.title = ft.Text("Editar empresa / entidad")
        company_dialog.open = True
        page.update()

    def save_company(e=None):
        data = {
            "entity_type": entity_type.value or "juridica",
            "name": name.value or "",
            "trade_name": trade_name.value or "",
            "document_type": document_type.value or "",
            "tax_id": tax_id.value or "",
            "first_name": first_name.value or "",
            "last_name_1": last_name_1.value or "",
            "last_name_2": last_name_2.value or "",
            "company_type": company_type.value or "",
            "main_activity": main_activity.value or "",
            "cnae_code": cnae_code.value or "",
            "cnae_description": cnae_description.value or "",
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
            "city": city.value or "",
            "province": province.value or "",
            "country": country.value or "España",
            "notes": notes.value or "",
        }
        try:
            if state.get("editing_id"):
                company_service.update_company(state["editing_id"], data)
                msg = "Empresa actualizada"
            else:
                company_service.create_company(data)
                msg = "Empresa creada"
            close_dialog()
            refresh()
            _snack(page, msg)
        except Exception as exc:
            _snack(page, f"No se pudo guardar la empresa: {exc}", error=True)

    def delete_company(company):
        try:
            company_service.delete_company(company["id"])
            refresh()
            _snack(page, "Empresa eliminada")
        except Exception as exc:
            _snack(page, f"No se pudo eliminar la empresa: {exc}", error=True)

    def render_table():
        rows = []
        for company in state.get("companies") or []:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(company.get("name") or "")),
                        ft.DataCell(ft.Text(_entity_type_label(company.get("entity_type")))),
                        ft.DataCell(ft.Text(company.get("tax_id") or "")),
                        ft.DataCell(ft.Text(company.get("main_activity") or company.get("cnae_description") or "")),
                        ft.DataCell(ft.Text(company.get("phone") or "")),
                        ft.DataCell(ft.Text(company.get("email") or "")),
                        ft.DataCell(ft.Text(company.get("city") or "")),
                        ft.DataCell(
                            ft.Row(
                                controls=[
                                    ft.TextButton("Editar", on_click=lambda e, c=company: open_edit_dialog(c)),
                                    ft.TextButton("Eliminar", on_click=lambda e, c=company: delete_company(c)),
                                ],
                                spacing=4,
                            )
                        ),
                    ]
                )
            )

        counter_text.value = f"{len(rows)} empresa(s) / entidad(es)"
        if not rows:
            table_container.content = ft.Container(
                padding=26,
                alignment=ft.alignment.center,
                content=ft.Text("No hay empresas que coincidan con el filtro", color=Q_MUTED),
            )
            return

        table_container.content = ft.Row(
            controls=[
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Nombre / razón social")),
                        ft.DataColumn(ft.Text("Tipo")),
                        ft.DataColumn(ft.Text("CIF/NIF")),
                        ft.DataColumn(ft.Text("Actividad")),
                        ft.DataColumn(ft.Text("Teléfono")),
                        ft.DataColumn(ft.Text("Email")),
                        ft.DataColumn(ft.Text("Localidad")),
                        ft.DataColumn(ft.Text("Acciones")),
                    ],
                    rows=rows,
                    column_spacing=22,
                    heading_row_color=ft.Colors.BLUE_50,
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=10,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    company_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Nueva empresa / entidad"),
        content=ft.Container(
            width=980,
            height=680,
            content=ft.Column(
                controls=[
                    ft.Text("Datos generales", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([entity_type, name, trade_name], wrap=True, spacing=10),
                    ft.Row([document_type, tax_id, company_type], wrap=True, spacing=10),
                    ft.Row([first_name, last_name_1, last_name_2], wrap=True, spacing=10),
                    ft.Row([main_activity, cnae_code, cnae_description], wrap=True, spacing=10),
                    ft.Divider(height=18),
                    ft.Text("Contacto y domicilio", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([phone, email, website], wrap=True, spacing=10),
                    ft.Row([address, tipo_via, nombre_via], wrap=True, spacing=10),
                    ft.Row([numero, piso, puerta, escalera, postal_code], wrap=True, spacing=10),
                    ft.Row([city, province, country], wrap=True, spacing=10),
                    notes,
                ],
                spacing=12,
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

    header = ft.Container(
        bgcolor=Q_CARD,
        border_radius=16,
        padding=22,
        border=ft.border.all(1, Q_BORDER),
        content=ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Empresas / Empleadores", size=26, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Text(
                            "Alta y mantenimiento de empresas, autónomos y personas físicas empleadoras. La vinculación con clientes se realiza desde la ficha del cliente.",
                            size=13,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=4,
                    expand=True,
                ),
                _primary_button("Nueva empresa", open_new_dialog),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
    )

    filters = ft.Row(
        controls=[search_input, entity_filter, _secondary_button("Actualizar", refresh), counter_text],
        wrap=True,
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    root = ft.Container(
        expand=True,
        bgcolor=Q_BG,
        padding=22,
        content=ft.Column(
            controls=[
                header,
                _section_card(
                    "Directorio de entidades",
                    ft.Column(controls=[filters, table_container], spacing=12),
                    subtitle="Vista maestra. No sustituye la ficha de cliente; sirve para dar de alta y mantener entidades.",
                ),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    refresh()
    return root

import flet as ft

from backend.services import company_service, client_company_service, company_tax_service

Q_PRIMARY = "#003B7A"
Q_PRIMARY_DARK = "#002B5C"
Q_ACCENT = "#18BFEA"
Q_BG = "#F4F7FB"
Q_CARD = "#FFFFFF"
Q_BORDER = "#D8E2F0"
Q_MUTED = "#5E6C84"
Q_CHIP_BG = "#EAF3FF"
Q_SUCCESS = "#0F8A5F"
Q_DANGER = "#B42318"

ENTITY_TYPE_LABELS = {
    "juridica": "Sociedad / empresa",
    "autonomo": "Autónomo",
    "persona_fisica": "Persona física empleadora",
}


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


def _section_card(title, content, subtitle=None, icon=None):
    return ft.Container(
        bgcolor=Q_CARD,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
        content=ft.Column(
            controls=[
                ft.Row(
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
                ),
                content,
            ],
            spacing=14,
        ),
    )


def _empty_state(message):
    return ft.Container(
        padding=24,
        alignment=ft.Alignment(0, 0),
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        content=ft.Text(message, color=Q_MUTED),
    )


def _info_tile(label, value, icon=None):
    return ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        border_radius=12,
        padding=12,
        content=ft.Row(
            controls=[
                ft.Text(icon or "•", size=16),
                ft.Column(
                    controls=[
                        ft.Text(label, size=11, color=Q_MUTED),
                        ft.Text(value or "-", size=13, color=Q_PRIMARY_DARK, weight=ft.FontWeight.W_500),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _entity_type_label(value):
    return ENTITY_TYPE_LABELS.get(value or "", value or "-")


def _company_name(company):
    return (company or {}).get("trade_name") or (company or {}).get("name") or "Empresa"


def _client_name(row):
    return " ".join(
        [
            row.get("client_nombre") or "",
            row.get("client_primer_apellido") or "",
            row.get("client_segundo_apellido") or "",
        ]
    ).strip() or "-"


def _document_from_client(row):
    return row.get("client_nie") or row.get("client_pasaporte") or row.get("client_dni") or "-"


def _data_table(columns, rows, empty_message):
    if not rows:
        return _empty_state(empty_message)
    return ft.Row(
        controls=[
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text(col)) for col in columns],
                rows=rows,
                column_spacing=22,
                heading_row_color=ft.Colors.BLUE_50,
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
            )
        ],
        scroll=ft.ScrollMode.AUTO,
    )




def _company_initials(company):
    name = _company_name(company)
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "EM"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _company_completion_percent(company):
    fields = [
        "name",
        "tax_id",
        "codigo_cuenta_cotizacion",
        "entity_type",
        "main_activity",
        "cnae_code",
        "phone",
        "email",
        "address",
        "city",
        "province",
    ]
    completed = sum(1 for field in fields if (company or {}).get(field))
    return int((completed / len(fields)) * 100) if fields else 0


def _progress_color(percent):
    if percent >= 80:
        return "#027A48"
    if percent >= 50:
        return "#B54708"
    return "#B42318"


def _company_status_chip(company):
    percent = _company_completion_percent(company)
    return ft.Container(
        content=ft.Text(
            f"Ficha completa: {percent}%",
            size=12,
            color=_progress_color(percent),
            weight=ft.FontWeight.BOLD,
        ),
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        border_radius=18,
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
    )


def _photo_placeholder(company):
    return ft.Container(
        width=92,
        height=92,
        bgcolor=Q_CHIP_BG,
        border=ft.border.all(1, "#B9D7FF"),
        border_radius=18,
        content=ft.Column(
            controls=[
                ft.Text(_company_initials(company), size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text("Empresa", size=11, color=Q_MUTED),
            ],
            spacing=2,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def company_detail_view(page: ft.Page, company_id, on_back=None, on_edit=None):
    try:
        company_tax_service.ensure_schema()
    except Exception:
        pass

    company = company_service.get_company(company_id)
    if not company:
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
                                    ft.Container(
                                        width=92,
                                        height=92,
                                        bgcolor=Q_CHIP_BG,
                                        border=ft.border.all(1, "#B9D7FF"),
                                        border_radius=18,
                                        content=ft.Icon(ft.Icons.BUSINESS, size=40, color=Q_PRIMARY_DARK),
                                        alignment=ft.Alignment(0, 0),
                                    ),
                                    ft.Text("Empresa", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Divider(),
                                    ft.Row(
                                        controls=[
                                            ft.IconButton(
                                                icon=ft.Icons.ARROW_BACK,
                                                tooltip="Volver empresas",
                                                icon_color=Q_PRIMARY_DARK,
                                                on_click=on_back,
                                            )
                                        ],
                                        alignment=ft.MainAxisAlignment.CENTER,
                                    ) if on_back else ft.Container(),
                                ],
                                spacing=8,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ),
                        ft.Container(
                            expand=True,
                            bgcolor=Q_CARD,
                            border=ft.border.all(1, Q_BORDER),
                            border_radius=14,
                            padding=16,
                            content=_empty_state("Empresa no encontrada"),
                        ),
                    ],
                    spacing=14,
                    expand=True,
                )
            ],
            spacing=16,
            expand=True,
        )

    try:
        linked_clients = client_company_service.list_company_clients(company_id, active_only=False)
    except Exception:
        linked_clients = []

    try:
        representatives = company_service.list_company_representatives(company_id)
    except Exception:
        representatives = []

    try:
        fiscal_years = company_tax_service.list_fiscal_years(company_id)
    except Exception:
        fiscal_years = []

    try:
        tax_documents = company_tax_service.list_tax_documents(company_id)
    except Exception:
        tax_documents = []

    try:
        financial_metrics = company_tax_service.list_financial_metrics(company_id)
    except Exception:
        financial_metrics = []

    address_parts = [
        company.get("address"),
        company.get("postal_code"),
        company.get("city"),
        company.get("province"),
        company.get("country"),
    ]
    address_text = " · ".join([p for p in address_parts if p])

    client_rows = []
    for row in linked_clients:
        client_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(_client_name(row), weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)),
                    ft.DataCell(ft.Text(_document_from_client(row))),
                    ft.DataCell(ft.Text(row.get("relationship_type") or "-")),
                    ft.DataCell(ft.Text("Activo" if int(row.get("is_active") or 0) else "Inactivo")),
                    ft.DataCell(ft.Text(row.get("client_telefono") or "-")),
                    ft.DataCell(ft.Text(row.get("client_email") or "-")),
                ]
            )
        )

    representative_rows = []
    for row in representatives:
        representative_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row.get("full_name") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)),
                    ft.DataCell(ft.Text(row.get("document_number") or "-")),
                    ft.DataCell(ft.Text(row.get("position") or "-")),
                    ft.DataCell(ft.Text(row.get("phone") or "-")),
                    ft.DataCell(ft.Text(row.get("email") or "-")),
                ]
            )
        )

    fiscal_rows = []
    for row in fiscal_years:
        fiscal_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("fiscal_year") or "-"), weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)),
                    ft.DataCell(ft.Text(row.get("net_revenue") or "-")),
                    ft.DataCell(ft.Text(row.get("profit_after_tax") or "-")),
                    ft.DataCell(ft.Text(row.get("equity") or "-")),
                    ft.DataCell(ft.Text(row.get("average_employees") or "-")),
                    ft.DataCell(ft.Text("Sí" if int(row.get("verified") or 0) else "No")),
                ]
            )
        )

    tax_rows = []
    for row in tax_documents:
        tax_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row.get("document_type") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)),
                    ft.DataCell(ft.Text(str(row.get("fiscal_year") or "-"))),
                    ft.DataCell(ft.Text(row.get("period") or "-")),
                    ft.DataCell(ft.Text(row.get("model_number") or "-")),
                    ft.DataCell(ft.Text(row.get("status") or "-")),
                    ft.DataCell(ft.Text(row.get("file_name") or "-")),
                ]
            )
        )

    metric_rows = []
    for row in financial_metrics[:80]:
        metric_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("fiscal_year") or "-"))),
                    ft.DataCell(ft.Text(row.get("metric_label") or row.get("metric_key") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)),
                    ft.DataCell(ft.Text(row.get("metric_value") or "-")),
                    ft.DataCell(ft.Text(row.get("metric_unit") or "-")),
                    ft.DataCell(ft.Text("Sí" if int(row.get("reviewed") or 0) else "No")),
                ]
            )
        )

    summary = ft.Row(
        controls=[
            _info_tile("Clientes vinculados", str(len(linked_clients)), "👥"),
            _info_tile("Representantes", str(len(representatives)), "👤"),
            _info_tile("Ejercicios fiscales", str(len(fiscal_years)), "📆"),
            _info_tile("Documentos fiscales", str(len(tax_documents)), "📄"),
        ],
        spacing=10,
        wrap=True,
    )

    datos_entidad = _section_card(
        "Datos de entidad",
        ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        _info_tile("Razón social", company.get("name") or "-", "🏢"),
                        _info_tile("Nombre comercial", company.get("trade_name") or "-", "🏷️"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _info_tile("Tipo", _entity_type_label(company.get("entity_type")), "🏷️"),
                        _info_tile("Documento", company.get("tax_id") or "-", "🪪"),
                        _info_tile("CCC", company.get("codigo_cuenta_cotizacion") or "-", "🏦"),
                        _info_tile("Forma / tipo", company.get("company_type") or "-", "#"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _info_tile("Actividad", company.get("main_activity") or company.get("cnae_description") or "-", "📊"),
                        _info_tile("CNAE", company.get("cnae_code") or "-", "#"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            spacing=10,
        ),
        subtitle="Datos maestros de sociedad, autónomo o persona física empleadora.",
        icon="🏷️",
    )

    contacto_domicilio = _section_card(
        "Contacto y domicilio",
        ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        _info_tile("Teléfono", company.get("phone") or "-", "☎️"),
                        _info_tile("Email", company.get("email") or "-", "✉️"),
                        _info_tile("Web", company.get("website") or "-", "🌐"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                _info_tile("Domicilio", address_text or "-", "📍"),
                ft.Row(
                    controls=[
                        _info_tile("Tipo vía", company.get("tipo_via") or "-", "↗️"),
                        _info_tile("Vía", company.get("nombre_via") or "-", "🛣️"),
                        _info_tile("Número", company.get("numero") or "-", "#"),
                        _info_tile("Piso/Puerta", " / ".join([v for v in [company.get("piso"), company.get("puerta")] if v]) or "-", "🏠"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _info_tile("Localidad", company.get("city") or "-", "📍"),
                        _info_tile("Provincia", company.get("province") or "-", "🗺️"),
                        _info_tile("Código postal", company.get("postal_code") or "-", "✉️"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            spacing=10,
        ),
        subtitle="Domicilio estructurado para futuras automatizaciones y documentos.",
        icon="📍",
    )

    clientes_section = _section_card(
        "Clientes vinculados",
        _data_table(
            ["Cliente", "Documento", "Relación", "Estado", "Teléfono", "Email"],
            client_rows,
            "No hay clientes vinculados a esta empresa.",
        ),
        subtitle="Lectura inversa del vínculo cliente ↔ empresa.",
        icon="👥",
    )

    representantes_section = _section_card(
        "Representantes",
        _data_table(
            ["Nombre", "Documento", "Cargo", "Teléfono", "Email"],
            representative_rows,
            "No hay representantes registrados.",
        ),
        subtitle="Representantes legales o contactos de la entidad.",
        icon="👤",
    )

    fiscal_section = _section_card(
        "Años fiscales",
        _data_table(
            ["Año", "Ingresos", "Resultado", "Fondos propios", "Empleados", "Verificado"],
            fiscal_rows,
            "No hay años fiscales registrados.",
        ),
        subtitle="Resumen anual preparado para futuras validaciones documentales.",
        icon="📆",
    )

    tax_section = _section_card(
        "Documentos fiscales",
        _data_table(
            ["Documento", "Año", "Periodo", "Modelo", "Estado", "Archivo"],
            tax_rows,
            "No hay documentos fiscales registrados.",
        ),
        subtitle="Modelos, certificados y documentos vinculados a la empresa.",
        icon="📄",
    )

    metrics_section = _section_card(
        "Métricas económicas",
        _data_table(
            ["Año", "Métrica", "Valor", "Unidad", "Revisado"],
            metric_rows,
            "No hay métricas económicas registradas.",
        ),
        subtitle="Datos extraídos o revisados desde documentos fiscales.",
        icon="📈",
    )

    notes_section = _section_card(
        "Observaciones",
        ft.Container(
            padding=14,
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            content=ft.Text(company.get("notes") or "Sin observaciones.", color=Q_PRIMARY_DARK),
        ),
        subtitle="Notas internas de la entidad.",
        icon="📝",
    )

    state = {"section": "ficha"}
    content_container = ft.Container(expand=True)

    def build_ficha_section():
        return ft.Column(
            controls=[
                datos_entidad,
                contacto_domicilio,
                notes_section,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_actividad_section():
        return ft.Column(
            controls=[
                ft.Text("Actividad económica", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _section_card(
                    "Actividad y CNAE",
                    ft.Column(
                        controls=[
                            _info_tile("Actividad principal", company.get("main_activity") or "-", "📊"),
                            _info_tile("CNAE", company.get("cnae_code") or "-", "#"),
                            _info_tile("Descripción CNAE", company.get("cnae_description") or "-", "📋"),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_clientes_section():
        return ft.Column(
            controls=[
                ft.Text("Clientes vinculados", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                clientes_section,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_representantes_section():
        return ft.Column(
            controls=[
                ft.Text("Representantes", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                representantes_section,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_fiscalidad_section():
        return ft.Column(
            controls=[
                ft.Text("Fiscalidad", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                summary,
                fiscal_section,
                tax_section,
                metrics_section,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_documentos_section():
        return ft.Column(
            controls=[
                ft.Text("Documentos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                tax_section,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_historial_section():
        return ft.Column(
            controls=[
                ft.Text("Historial / relaciones", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                _section_card(
                    "Relaciones operativas",
                    ft.Column(
                        controls=[
                            _info_tile("Clientes vinculados", str(len(linked_clients)), "👥"),
                            _info_tile("Representantes", str(len(representatives)), "👤"),
                            _info_tile("Ejercicios fiscales", str(len(fiscal_years)), "📆"),
                            _info_tile("Documentos fiscales", str(len(tax_documents)), "📄"),
                        ],
                        spacing=10,
                    ),
                    subtitle="Resumen de relaciones conectadas con esta empresa.",
                    icon="🔗",
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_section_content():
        section = state.get("section") or "ficha"
        if section == "actividad":
            return build_actividad_section()
        if section == "clientes":
            return build_clientes_section()
        if section == "representantes":
            return build_representantes_section()
        if section == "fiscalidad":
            return build_fiscalidad_section()
        if section == "documentos":
            return build_documentos_section()
        if section == "historial":
            return build_historial_section()
        return build_ficha_section()

    def set_section(section):
        state["section"] = section
        content_container.content = build_section_content()
        sidebar_menu.content = build_sidebar_menu()
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
            bgcolor=Q_CHIP_BG if is_active else Q_CARD,
            border=ft.border.all(1, "#B9D7FF" if is_active else Q_BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ink=True,
            on_click=lambda e, s=section: set_section(s),
        )

    menu_items = [
        ("Ficha empresa", "ficha"),
        ("Actividad económica", "actividad"),
        ("Clientes vinculados", "clientes"),
        ("Representantes", "representantes"),
        ("Fiscalidad", "fiscalidad"),
        ("Documentos", "documentos"),
        ("Historial / relaciones", "historial"),
    ]

    sidebar_actions = []
    if on_back:
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                tooltip="Volver empresas",
                icon_color=Q_PRIMARY_DARK,
                on_click=on_back,
            )
        )
    if on_edit:
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.EDIT,
                tooltip="Editar empresa",
                icon_color=Q_PRIMARY,
                on_click=lambda e: on_edit(company),
            )
        )

    def build_sidebar_menu():
        return ft.Column(
            controls=[
                _photo_placeholder(company),
                ft.Text(_company_name(company), size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK, text_align=ft.TextAlign.CENTER),
                ft.Text(company.get("tax_id") or "Sin CIF/NIF", size=12, color=Q_MUTED, text_align=ft.TextAlign.CENTER),
                _company_status_chip(company),
                ft.Divider(),
                ft.Text("Menú empresa", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text("Navega por áreas sin una ficha única demasiado larga.", size=12, color=Q_MUTED, text_align=ft.TextAlign.CENTER),
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
        )

    sidebar_menu = ft.Container(content=ft.Column(controls=[]))
    content_container.content = build_section_content()
    sidebar_menu.content = build_sidebar_menu()

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
                        content=sidebar_menu,
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=Q_CARD,
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

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


def company_detail_view(page: ft.Page, company_id, on_back=None, on_edit=None):
    try:
        company_tax_service.ensure_schema()
    except Exception:
        pass

    company = company_service.get_company(company_id)
    if not company:
        return ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=24,
            content=ft.Column(
                controls=[
                    _secondary_button("Volver", on_back, icon=ft.Icons.ARROW_BACK),
                    _empty_state("Empresa no encontrada"),
                ],
                spacing=14,
            ),
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

    address_parts = [company.get("address"), company.get("postal_code"), company.get("city"), company.get("province"), company.get("country")]
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

    header = ft.Container(
        bgcolor=Q_CARD,
        border=ft.border.all(1, Q_BORDER),
        border_radius=18,
        padding=22,
        content=ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("🏢", size=30),
                                ft.Text(_company_name(company), size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(company.get("name") or "", size=13, color=Q_MUTED),
                    ],
                    spacing=4,
                    expand=True,
                ),
                ft.Row(
                    controls=[
                        _secondary_button("Volver", on_back, icon=ft.Icons.ARROW_BACK),
                        _secondary_button("Editar", lambda e: on_edit(company) if on_edit else None, icon=ft.Icons.EDIT),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
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
                        _info_tile("Tipo", _entity_type_label(company.get("entity_type")), "🏷️"),
                        _info_tile("Documento", company.get("tax_id") or "-", "🪪"),
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

    return ft.Container(
        expand=True,
        bgcolor=Q_BG,
        padding=22,
        content=ft.Column(
            controls=[
                header,
                summary,
                datos_entidad,
                contacto_domicilio,
                clientes_section,
                representantes_section,
                fiscal_section,
                tax_section,
                metrics_section,
                notes_section,
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

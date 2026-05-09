import flet as ft

from backend.services.box_report_service import (
    get_document_type_counts,
    get_global_report,
    get_recent_scan_runs,
    get_routes_report,
)

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"


def _safe_value(value, default="—"):
    if value is None or value == "":
        return default
    return value


def _number(value):
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except Exception:
        return str(value or 0)


def _size_label(value):
    try:
        size = int(value or 0)
    except Exception:
        return "—"

    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size} B"


def _metric_card(title, value, subtitle=None):
    controls = [
        ft.Text(title, size=13, color=Q_MUTED, weight=ft.FontWeight.W_600),
        ft.Text(str(value), size=28, color=Q_PRIMARY_DARK, weight=ft.FontWeight.BOLD),
    ]
    if subtitle:
        controls.append(ft.Text(str(subtitle), size=11, color=Q_MUTED))

    return ft.Container(
        width=210,
        padding=16,
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        content=ft.Column(controls=controls, spacing=6),
    )


def _section(title, content, subtitle=None):
    header = [ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)]
    if subtitle:
        header.append(ft.Text(subtitle, size=12, color=Q_MUTED))

    return ft.Container(
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Column(header, spacing=3),
                content,
            ],
            spacing=12,
        ),
    )


def _table(headers, rows, height=260):
    total_width = sum(int(width or 0) for _, width in headers) + (len(headers) - 1) * 8 + 24
    body_height = max(120, int(height or 260) - 52)

    header_row = ft.Row(
        controls=[
            ft.Container(
                content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                width=width,
            )
            for label, width in headers
        ],
        spacing=8,
    )

    body_rows = []
    for row in rows:
        body_rows.append(
            ft.Container(
                padding=ft.padding.symmetric(vertical=8),
                border=ft.border.only(bottom=ft.BorderSide(1, "#EEF2F7")),
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=control if isinstance(control, ft.Control) else ft.Text(str(control), size=12, color="#101828"),
                            width=headers[index][1],
                        )
                        for index, control in enumerate(row)
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
        )

    table_inner = ft.Column(
        width=total_width,
        controls=[
            ft.Container(
                bgcolor="#F8FAFC",
                border_radius=10,
                padding=8,
                content=header_row,
            ),
            ft.Container(
                height=body_height,
                content=ft.Column(
                    controls=body_rows or [ft.Text("Sin datos disponibles.", size=13, color=Q_MUTED)],
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
        ],
        spacing=6,
    )

    return ft.Container(
        height=height,
        content=ft.Row(
            controls=[table_inner],
            scroll=ft.ScrollMode.AUTO,
        ),
    )


def _nav_button(label, active, on_click):
    return ft.Container(
        width=180,
        padding=ft.padding.symmetric(horizontal=12, vertical=11),
        border_radius=12,
        border=ft.border.all(1, "#B9D7FF" if active else Q_BORDER),
        bgcolor="#EAF3FF" if active else Q_WHITE,
        ink=True,
        on_click=on_click,
        content=ft.Text(
            label,
            size=13,
            color=Q_PRIMARY_DARK if active else Q_MUTED,
            weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500,
        ),
    )


def _horizontal_bar_chart(title, items, label_key, value_key, height=300, limit=8):
    data = list(items or [])[:limit]
    max_value = max([int(item.get(value_key) or 0) for item in data] or [1])

    rows = []
    for item in data:
        label = str(item.get(label_key) or "—")
        value = int(item.get(value_key) or 0)
        width = 210 if max_value <= 0 else max(12, int((value / max_value) * 210))

        rows.append(
            ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(label[:32], size=11, color="#101828", expand=True),
                            ft.Text(_number(value), size=11, color=Q_MUTED),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        height=9,
                        border_radius=8,
                        bgcolor="#EAF3FF",
                        content=ft.Container(
                            width=width,
                            height=9,
                            border_radius=8,
                            bgcolor=Q_PRIMARY,
                        ),
                    ),
                ],
                spacing=3,
            )
        )

    return _section(
        title,
        ft.Container(
            height=height,
            content=ft.Column(
                controls=rows or [ft.Text("Sin datos disponibles.", size=13, color=Q_MUTED)],
                spacing=9,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
    )


def _timeline_chart(title, runs, height=170):
    data = list(reversed(runs or []))[-12:]
    max_value = max([int(item.get("total_archivos") or 0) for item in data] or [1])

    bars = []
    for item in data:
        value = int(item.get("total_archivos") or 0)
        bar_height = 20 if max_value <= 0 else max(8, int((value / max_value) * 100))
        label = str(item.get("id") or "—")

        bars.append(
            ft.Column(
                controls=[
                    ft.Container(
                        width=28,
                        height=bar_height,
                        margin=ft.margin.only(top=6),
                        border_radius=6,
                        bgcolor=Q_PRIMARY,
                    ),
                    ft.Text(label, size=10, color=Q_MUTED),
                ],
                width=42,
                height=185,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            )
        )

    return _section(
        title,
        ft.Container(
            expand=True,
            height=height,
            content=ft.Row(
                controls=bars or [ft.Text("Sin datos disponibles.", size=13, color=Q_MUTED)],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.END,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        subtitle="Evolución por últimos escaneos registrados en Box Watch.",
    )


def reporting_view(page: ft.Page):
    try:
        global_report = get_global_report()
        routes_report = get_routes_report()
        document_types = get_document_type_counts(limit=30)
        recent_runs = get_recent_scan_runs(limit=10)
        error_message = None
    except Exception as exc:
        global_report = {}
        routes_report = []
        document_types = []
        recent_runs = []
        error_message = f"No se pudo cargar el reporting Box: {exc}"

    kpis = ft.Row(
        controls=[
            _metric_card("Carpetas", _number(global_report.get("total_carpetas")), "activas en inventario"),
            _metric_card("Archivos", _number(global_report.get("total_archivos")), "activos en inventario"),
            _metric_card("Pasaportes", _number(global_report.get("pasaportes")), "actuales/anteriores"),
            _metric_card("Justificantes", _number(global_report.get("justificantes_presentacion")), "presentación"),
            _metric_card("Tasas", _number(global_report.get("tasas") + global_report.get("justificantes_tasa")), "tasas y justificantes"),
            _metric_card("Sin clasificar", _number(global_report.get("sin_clasificar")), "pendientes de revisión"),
        ],
        spacing=12,
        wrap=True,
    )

    routes_rows = []
    for route in routes_report[:80]:
        routes_rows.append([
            ft.Text(_safe_value(route.get("tipo_expediente")), size=12, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
            route.get("ruta_box") or "—",
            _number(route.get("total_carpetas")),
            _number(route.get("total_archivos")),
            _number(route.get("pasaportes")),
            _number(route.get("justificantes_presentacion")),
            _number(route.get("sin_clasificar")),
            _safe_value(route.get("ultimo_escaneo")),
        ])

    document_rows = []
    for item in document_types:
        document_rows.append([
            ft.Text(item.get("tipo_documento") or "SIN CLASIFICAR", size=12, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
            _number(item.get("total")),
            _size_label(item.get("total_bytes")),
        ])

    run_rows = []
    for run in recent_runs:
        run_rows.append([
            run.get("id") or "—",
            _safe_value(run.get("estado")),
            _safe_value(run.get("fecha_fin") or run.get("fecha_inicio")),
            _number(run.get("total_carpetas")),
            _number(run.get("total_archivos")),
            _number(run.get("nuevos")),
            _number(run.get("modificados")),
            _number(run.get("alertas")),
        ])

    controls = [
        ft.Text("Reporting", size=30, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
        ft.Text("Box Reporting · métricas documentales desde inventario SQLite", size=14, color=Q_MUTED),
    ]

    if error_message:
        controls.append(
            ft.Container(
                bgcolor="#FEF3F2",
                border=ft.border.all(1, "#FDA29B"),
                border_radius=12,
                padding=12,
                content=ft.Text(error_message, color="#B42318", size=13),
            )
        )

    table_container = ft.Container(expand=True)
    active_section = {"value": "Rutas"}

    table_sections = {
        "Rutas": {
            "title": "Resumen por rutas Box",
            "subtitle": "Conteo por cada ruta configurada. Solo lectura.",
            "table": _table(
                headers=[
                    ("Tipo", 180),
                    ("Ruta", 260),
                    ("Carpetas", 80),
                    ("Archivos", 80),
                    ("Pasap.", 70),
                    ("Justif.", 70),
                    ("Sin clas.", 80),
                    ("Último escaneo", 180),
                ],
                rows=routes_rows,
                height=460,
            ),
        },
        "Tipos": {
            "title": "Tipos documentales detectados",
            "subtitle": "Distribución de documentos según clasificación actual.",
            "table": _table(
                headers=[
                    ("Tipo documental", 320),
                    ("Total", 90),
                    ("Tamaño", 130),
                ],
                rows=document_rows,
                height=460,
            ),
        },
        "Escaneos": {
            "title": "Últimos escaneos",
            "subtitle": "Histórico reciente de escaneos registrados por Box Watch.",
            "table": _table(
                headers=[
                    ("ID", 55),
                    ("Estado", 90),
                    ("Fecha", 170),
                    ("Carp.", 70),
                    ("Arch.", 70),
                    ("Nuevos", 80),
                    ("Mod.", 70),
                    ("Alertas", 75),
                ],
                rows=run_rows,
                height=460,
            ),
        },
        "Evolución": {
            "title": "Evolución temporal de archivos Box",
            "subtitle": "Evolución por últimos escaneos registrados en Box Watch.",
            "table": _timeline_chart(
                "Evolución temporal de archivos Box",
                recent_runs,
                height=460,
            ),
        },
    }

    def render_active_table():
        section = table_sections.get(active_section["value"], table_sections["Rutas"])
        table_container.content = _section(
            section["title"],
            section["table"],
            subtitle=section["subtitle"],
        )

    def set_active_table(name):
        active_section["value"] = name
        render_active_table()
        nav_container.content = build_nav()
        page.update()

    def build_nav():
        return ft.Container(
            width=210,
            bgcolor=Q_WHITE,
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Text("Tablas", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text("Selecciona el bloque de datos.", size=12, color=Q_MUTED),
                    ft.Divider(),
                    _nav_button("Resumen rutas Box", active_section["value"] == "Rutas", lambda e: set_active_table("Rutas")),
                    _nav_button("Tipos detectados", active_section["value"] == "Tipos", lambda e: set_active_table("Tipos")),
                    _nav_button("Últimos escaneos", active_section["value"] == "Escaneos", lambda e: set_active_table("Escaneos")),
                    _nav_button("Evolución temporal", active_section["value"] == "Evolución", lambda e: set_active_table("Evolución")),
                ],
                spacing=9,
            ),
        )

    nav_container = ft.Container()
    nav_container.content = build_nav()
    render_active_table()

    controls.extend([
        kpis,
        ft.Row(
            controls=[
                nav_container,
                ft.Container(
                    width=920,
                    content=table_container,
                ),
                ft.Container(
                    expand=True,
                    content=_horizontal_bar_chart(
                        "Distribución documental",
                        document_types,
                        "tipo_documento",
                        "total",
                        height=460,
                        limit=10,
                    ),
                ),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
    ])


    return ft.Container(
        expand=True,
        bgcolor=Q_BG,
        padding=20,
        content=ft.Column(
            controls=controls,
            spacing=16,
            expand=True,
        ),
    )

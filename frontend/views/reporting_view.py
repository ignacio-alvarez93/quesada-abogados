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

    return ft.Container(
        height=height,
        content=ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#F8FAFC",
                    border_radius=10,
                    padding=8,
                    content=header_row,
                ),
                ft.Column(
                    controls=body_rows or [ft.Text("Sin datos disponibles.", size=13, color=Q_MUTED)],
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=6,
        ),
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

    controls.extend([
        kpis,
        _section(
            "Resumen por rutas Box",
            _table(
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
                height=300,
            ),
            subtitle="Conteo por cada ruta configurada. Solo lectura.",
        ),
        ft.Row(
            controls=[
                ft.Container(
                    expand=True,
                    content=_section(
                        "Tipos documentales detectados",
                        _table(
                            headers=[
                                ("Tipo documental", 250),
                                ("Total", 80),
                                ("Tamaño", 100),
                            ],
                            rows=document_rows,
                            height=280,
                        ),
                    ),
                ),
                ft.Container(
                    expand=True,
                    content=_section(
                        "Últimos escaneos",
                        _table(
                            headers=[
                                ("ID", 55),
                                ("Estado", 90),
                                ("Fecha", 160),
                                ("Carp.", 65),
                                ("Arch.", 65),
                                ("Nuevos", 70),
                                ("Mod.", 60),
                                ("Alertas", 65),
                            ],
                            rows=run_rows,
                            height=280,
                        ),
                    ),
                ),
            ],
            spacing=14,
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
            scroll=ft.ScrollMode.AUTO,
        ),
    )

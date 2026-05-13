import flet as ft

from frontend.components.app_autocomplete import AppAutocomplete

from backend.services.box_report_service import (
    get_document_type_counts,
    get_global_report,
    get_missing_presentation_report,
    get_recent_scan_runs,
    get_routes_report,
)

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"

REPORTING_PAGE_SIZE_DEFAULT = 50
REPORTING_PAGE_SIZE_OPTIONS = [25, 50, 100, 150]


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


def _small_button(label, on_click=None, icon=None):
    controls = []
    if icon:
        controls.append(ft.Icon(icon, size=16))
    controls.append(ft.Text(label, size=12, weight=ft.FontWeight.W_600))

    return ft.ElevatedButton(
        content=ft.Row(
            controls=controls,
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=on_click,
        height=36,
    )


def _pagination_button(label, on_click=None, active=False, disabled=False):
    return ft.Container(
        width=36,
        height=32,
        alignment=ft.Alignment(0, 0),
        border_radius=8,
        border=ft.border.all(1, "#B9D7FF" if active else Q_BORDER),
        bgcolor="#EAF3FF" if active else Q_WHITE,
        ink=not disabled,
        on_click=None if disabled else on_click,
        content=ft.Text(
            str(label),
            size=12,
            color=Q_MUTED if disabled else Q_PRIMARY_DARK,
            weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500,
            text_align=ft.TextAlign.CENTER,
        ),
    )


def _page_numbers(current, total):
    if total <= 7:
        return list(range(1, total + 1))

    pages = {1, total, current - 1, current, current + 1}
    if current <= 4:
        pages.update(range(1, 6))
    elif current >= total - 3:
        pages.update(range(total - 4, total + 1))

    result = []
    last = None
    for number in sorted(p for p in pages if 1 <= p <= total):
        if last is not None and number - last > 1:
            result.append("...")
        result.append(number)
        last = number

    return result


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
            _number(route.get("carpetas_raiz") or route.get("total_carpetas")),
            _number(route.get("pasaportes")),
            _number(route.get("justificantes_presentacion")),
            _number(route.get("justificantes_tasa")),
            _number(route.get("requerimientos")),
            f"{float(route.get('porcentaje_presentados') or 0):.1f} %",
            f"{float(route.get('porcentaje_requerimientos') or 0):.1f} %",
            _size_label(route.get("total_bytes")),
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
    selected_missing_presentation = set()
    missing_presentation_rows_cache = {"rows": [], "loaded": False}
    missing_presentation_page = {"value": 1}
    missing_presentation_page_size = {"value": REPORTING_PAGE_SIZE_DEFAULT}
    missing_page_size_dd = ft.Dropdown(
        label="Filas/página",
        width=130,
        options=[ft.dropdown.Option(str(v)) for v in REPORTING_PAGE_SIZE_OPTIONS],
        value=str(REPORTING_PAGE_SIZE_DEFAULT),
    )
    route_filter_options = []
    for route in routes_report or []:
        label = " · ".join([
            str(route.get("tipo_expediente") or "").strip(),
            str(route.get("ruta_box") or "").strip(),
        ]).strip(" ·")
        if label and label not in route_filter_options:
            route_filter_options.append(label)
        ruta_box = str(route.get("ruta_box") or "").strip()
        if ruta_box and ruta_box not in route_filter_options:
            route_filter_options.append(ruta_box)

    missing_route_filter = AppAutocomplete(
        page=page,
        label="Filtrar por ruta Box",
        options=route_filter_options,
        width=390,
        max_results=8,
        allow_free_text=True,
    )

    def open_missing_folder_dialog(folder):
        ruta = folder.get("ruta") or ""
        status = ft.Text("Actualizando ruta concreta antes de abrir ficha...", size=12, color=Q_MUTED)
        content_box = ft.Container(
            height=420,
            content=ft.Column(
                controls=[status],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

        def close_dialog():
            page.dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(folder.get("nombre_carpeta") or "Ficha carpeta"),
            content=ft.Container(
                width=900,
                height=520,
                content=ft.Column(
                    controls=[
                        ft.Text(ruta, size=11, color=Q_MUTED),
                        content_box,
                    ],
                    spacing=12,
                ),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: close_dialog()),
            ],
        )

        page.dialog = dialog
        dialog.open = True
        page.update()

        try:
            from backend.services.box_watch_service import (
                get_box_folder_inspection,
                refresh_box_folder_before_inspection,
            )

            try:
                refresh_box_folder_before_inspection(ruta, calculate_hash=False)
                status.value = "Ruta actualizada. Revisando inventario..."
            except Exception as refresh_exc:
                status.value = f"No se pudo refrescar la ruta antes de inspeccionar: {refresh_exc}"

            inspection = get_box_folder_inspection(ruta)
            summary = inspection.get("summary") or {}
            subfolders = inspection.get("subfolders") or []
            files = inspection.get("files") or []

            controls = [
                status,
                ft.Divider(),
                ft.Text("Resumen", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(f"Subcarpetas directas: {summary.get('total_subcarpetas', 0)}", size=12),
                ft.Text(f"Archivos directos: {summary.get('total_archivos', 0)}", size=12),
                ft.Divider(),
                ft.Text("Subcarpetas", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ]

            for item in subfolders[:80]:
                controls.append(ft.Text(f"📁 {item.get('nombre_carpeta') or '—'} · {item.get('tipo_detectado') or 'OTROS'}", size=12))

            controls.append(ft.Divider())
            controls.append(ft.Text("Archivos", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK))

            for item in files[:120]:
                controls.append(ft.Text(f"📄 {item.get('nombre_archivo') or '—'} · {item.get('tipo_detectado') or 'SIN CLASIFICAR'}", size=12))

            content_box.content.controls = controls
            page.update()
        except Exception as exc:
            content_box.content.controls = [
                ft.Text(f"No se pudo abrir la ficha de carpeta: {exc}", size=13, color="#B42318")
            ]
            page.update()

    def build_missing_presentation_table():
        all_rows = missing_presentation_rows_cache["rows"] or []

        try:
            page_size = int(missing_presentation_page_size["value"] or REPORTING_PAGE_SIZE_DEFAULT)
        except Exception:
            page_size = REPORTING_PAGE_SIZE_DEFAULT
        if page_size not in REPORTING_PAGE_SIZE_OPTIONS:
            page_size = REPORTING_PAGE_SIZE_DEFAULT
        missing_presentation_page_size["value"] = page_size
        missing_page_size_dd.value = str(page_size)

        total_rows = len(all_rows)
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        current_page = max(1, min(int(missing_presentation_page["value"] or 1), total_pages))
        missing_presentation_page["value"] = current_page

        start_index = (current_page - 1) * page_size
        end_index = min(total_rows, start_index + page_size)
        visible_items = all_rows[start_index:end_index]
        rows = []

        def set_missing_page(page_number):
            try:
                page_number = int(page_number)
            except Exception:
                page_number = 1
            missing_presentation_page["value"] = max(1, min(page_number, total_pages))
            render_active_table()
            nav_container.content = build_nav()
            page.update()

        def go_first(e=None):
            set_missing_page(1)

        def go_prev(e=None):
            set_missing_page(current_page - 1)

        def go_next(e=None):
            set_missing_page(current_page + 1)

        def go_last(e=None):
            set_missing_page(total_pages)

        def on_page_size_change(e=None):
            try:
                missing_presentation_page_size["value"] = int(missing_page_size_dd.value or REPORTING_PAGE_SIZE_DEFAULT)
            except Exception:
                missing_presentation_page_size["value"] = REPORTING_PAGE_SIZE_DEFAULT
            missing_presentation_page["value"] = 1
            render_active_table()
            nav_container.content = build_nav()
            page.update()

        missing_page_size_dd.on_change = on_page_size_change

        def toggle_all(e):
            selected_missing_presentation.clear()
            if bool(e.control.value):
                for item in visible_items:
                    selected_missing_presentation.add(str(item.get("ruta") or ""))
            render_active_table()
            nav_container.content = build_nav()
            page.update()

        for item in visible_items:
            ruta = str(item.get("ruta") or "")

            def toggle_one(e, path=ruta):
                if e.control.value:
                    selected_missing_presentation.add(path)
                else:
                    selected_missing_presentation.discard(path)
                page.update()

            rows.append([
                ft.Checkbox(value=ruta in selected_missing_presentation, on_change=toggle_one),
                ft.Text(item.get("tipo_expediente") or "—", size=12, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                item.get("ruta_box") or "—",
                item.get("nombre_carpeta") or "—",
                _number(item.get("total_archivos")),
                _number(item.get("total_subcarpetas")),
                _safe_value(item.get("fecha_ultima_actividad")),
                _safe_value(item.get("ultimo_escaneo")),
                ft.TextButton("Abrir ficha", on_click=lambda e, folder=item: open_missing_folder_dialog(folder)),
            ])

        page_controls = [
            _pagination_button("«", on_click=go_first, disabled=current_page <= 1),
            _pagination_button("‹", on_click=go_prev, disabled=current_page <= 1),
        ]
        for item in _page_numbers(current_page, total_pages):
            if item == "...":
                page_controls.append(
                    ft.Container(
                        width=28,
                        height=32,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text("...", size=13, color=Q_MUTED),
                    )
                )
                continue

            page_controls.append(
                _pagination_button(
                    str(item),
                    on_click=lambda e, n=item: set_missing_page(n),
                    active=item == current_page,
                )
            )

        page_controls.extend([
            _pagination_button("›", on_click=go_next, disabled=current_page >= total_pages),
            _pagination_button("»", on_click=go_last, disabled=current_page >= total_pages),
        ])

        start_label = 0 if total_rows == 0 else start_index + 1
        pagination = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            content=ft.Row(
                controls=[
                    ft.Text(
                        f"Resultados: {total_rows} · Mostrando {start_label}-{end_index} · Seleccionados: {len(selected_missing_presentation)}",
                        size=12,
                        color=Q_MUTED,
                    ),
                    missing_page_size_dd,
                    ft.Row(controls=page_controls, spacing=4, wrap=True),
                ],
                spacing=12,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        missing_route_filter.control,
                        _small_button("Cargar / filtrar", on_click=lambda e: load_missing_presentation(), icon=ft.Icons.SEARCH),
                        ft.Checkbox(label="Seleccionar página", on_change=toggle_all),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                (
                    ft.Column(
                        controls=[
                            _table(
                                headers=[
                                    ("Sel.", 55),
                                    ("Tipo", 160),
                                    ("Ruta Box", 220),
                                    ("Carpeta raíz", 250),
                                    ("Arch.", 70),
                                    ("Sub.", 70),
                                    ("Última actividad", 150),
                                    ("Último escaneo", 160),
                                    ("Acción", 110),
                                ],
                                rows=rows,
                                height=315,
                            ),
                            pagination,
                        ],
                        spacing=8,
                    )
                    if rows
                    else ft.Container(
                        height=340,
                        content=ft.Text("No se encontraron carpetas sin justificante de presentación para ese filtro.", size=13, color=Q_MUTED),
                    )
                ) if missing_presentation_rows_cache["loaded"] else ft.Container(
                    height=405,
                    content=ft.Column(
                        controls=[
                            ft.Text("Pulsa “Cargar / filtrar” para consultar carpetas sin justificante de presentación.", size=13, color=Q_MUTED),
                            ft.Text("La consulta se carga bajo demanda para evitar bloquear Reporting.", size=12, color=Q_MUTED),
                        ],
                        spacing=8,
                    ),
                ),
            ],
            spacing=10,
        )


    def load_missing_presentation():
        try:
            missing_presentation_rows_cache["rows"] = get_missing_presentation_report(
                route_filter=missing_route_filter.get_value(),
                limit=300,
            )
            missing_presentation_rows_cache["loaded"] = True
            missing_presentation_page["value"] = 1
            selected_missing_presentation.clear()
        except Exception as exc:
            missing_presentation_rows_cache["rows"] = []
            missing_presentation_rows_cache["loaded"] = True
            table_container.content = _section(
                "Sin justificante presentación",
                ft.Text(f"No se pudo cargar la tabla: {exc}", color="#B42318", size=13),
                subtitle="Carpetas raíz sin justificante de presentación detectado.",
            )
            page.update()
            return

        render_active_table()
        nav_container.content = build_nav()
        page.update()

    table_sections = {
        "Rutas": {
            "title": "Resumen por rutas Box",
            "subtitle": "Conteo por cada ruta configurada. Solo lectura.",
            "table": _table(
                headers=[
                    ("Tipo", 170),
                    ("Ruta", 240),
                    ("Carpetas ruta", 90),
                    ("Pasap.", 70),
                    ("Justif. pres.", 90),
                    ("Justif. tasa", 90),
                    ("Req.", 70),
                    ("% Pres.", 80),
                    ("% Req.", 80),
                    ("Peso total", 100),
                    ("Último escaneo", 170),
                ],
                rows=routes_rows,
                height=460,
            ),
        },
        "SinPresentacion": {
            "title": "Sin justificante presentación",
            "subtitle": "Carpetas raíz/expedientes donde no se detecta justificante principal de presentación.",
            "table": build_missing_presentation_table(),
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
        if active_section["value"] == "SinPresentacion":
            section = {
                "title": "Sin justificante presentación",
                "subtitle": "Carpetas raíz/expedientes donde no se detecta justificante principal de presentación.",
                "table": build_missing_presentation_table(),
            }
        else:
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
                    _nav_button("Sin presentación", active_section["value"] == "SinPresentacion", lambda e: set_active_table("SinPresentacion")),
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

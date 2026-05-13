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


def _status_text(value):
    value = str(value or "—")
    color = Q_PRIMARY
    if value in ("CRITICA", "ERROR", "DUPLICADO", "RESUELTO_DENEGADO"):
        color = "#B42318"
    if value in ("ALTA", "SIN CLASIFICAR", "PENDIENTE REVISION", "REQUERIDO"):
        color = "#B54708"
    return ft.Text(value, size=13, weight=ft.FontWeight.W_600, color=color)


def _datetime_label(value):
    if not value:
        return "—"
    return str(value)


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


def _selectable_table(headers, rows, height=260):
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
    for index, row in enumerate(rows):
        meta = {}
        cells = row
        if row and isinstance(row[0], dict) and row[0].get("__row_meta__"):
            meta = row[0]
            cells = row[1:]

        selected = bool(meta.get("selected"))
        row_container = ft.Container(
            padding=ft.padding.symmetric(vertical=8),
            border=ft.border.only(bottom=ft.BorderSide(1, "#EEF2F7")),
            bgcolor="#EAF3FF" if selected else ("#FAFBFC" if index % 2 else "#FFFFFF"),
            border_radius=8,
            ink=bool(meta.get("on_click")),
            on_click=meta.get("on_click"),
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=control if isinstance(control, ft.Control) else ft.Text(str(control), size=12, color="#101828"),
                        width=headers[cell_index][1],
                    )
                    for cell_index, control in enumerate(cells)
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        if meta.get("row_ref") is not None:
            try:
                meta["row_ref"]["control"] = row_container
            except Exception:
                pass
        body_rows.append(row_container)

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


def _icon_action(label, icon, on_click=None, disabled=False):
    return ft.Container(
        height=38,
        border_radius=10,
        border=ft.border.all(1, Q_BORDER),
        bgcolor=Q_WHITE,
        ink=not disabled,
        opacity=0.40 if disabled else 1,
        on_click=None if disabled else on_click,
        padding=ft.padding.symmetric(horizontal=10, vertical=8),
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=16, color=Q_MUTED if disabled else Q_PRIMARY_DARK),
                ft.Text(label, size=12, color=Q_MUTED if disabled else Q_PRIMARY_DARK, weight=ft.FontWeight.W_600),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
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
    missing_selection_counter = ft.Text("Seleccionados: 0", size=12, color=Q_MUTED)
    missing_open_button_holder = ft.Container(opacity=0.45)
    missing_select_all_checkbox = ft.Checkbox(label="Seleccionar página")
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

    def open_missing_folder_dialog(folder, selected_folders=None, selected_index=0):
        selected_folders = list(selected_folders or [folder])
        if not selected_folders:
            return
        try:
            selected_index = max(0, min(int(selected_index or 0), len(selected_folders) - 1))
        except Exception:
            selected_index = 0
        folder = selected_folders[selected_index]
        ruta = folder.get("ruta") or ""
        if not ruta:
            return

        inspection_state = {
            "selected_folder_path": ruta,
            "inspection": None,
            "inspection_stack": [],
            "dialog_tab": "Documentación",
            "selected_folders": selected_folders,
            "selected_index": selected_index,
        }

        inspection_dialog_content = ft.Container(
            width=1080,
            height=720,
            bgcolor="#FFFFFF",
            border_radius=12,
            padding=0,
        )

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        def go_prev_selected_folder(e=None):
            selected = inspection_state.get("selected_folders") or []
            if not selected:
                return
            current = int(inspection_state.get("selected_index") or 0)
            next_index = max(0, current - 1)
            inspection_state["selected_index"] = next_index
            next_folder = selected[next_index]
            inspection_state["inspection_stack"] = []
            inspect_folder(next_folder.get("ruta"), push_history=False)

        def go_next_selected_folder(e=None):
            selected = inspection_state.get("selected_folders") or []
            if not selected:
                return
            current = int(inspection_state.get("selected_index") or 0)
            next_index = min(len(selected) - 1, current + 1)
            inspection_state["selected_index"] = next_index
            next_folder = selected[next_index]
            inspection_state["inspection_stack"] = []
            inspect_folder(next_folder.get("ruta"), push_history=False)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Inspección documental Box", color=Q_PRIMARY_DARK, weight=ft.FontWeight.BOLD),
            content=inspection_dialog_content,
            actions=[],
        )

        def open_selected_folder(e=None):
            try:
                from backend.services import box_watch_service
                box_watch_service.open_folder_in_explorer(inspection_state.get("selected_folder_path"))
            except Exception as exc:
                inspection_dialog_content.content = ft.Text(f"No se pudo abrir la carpeta: {exc}", color="#B42318")
                page.update()

        def export_selected_tree(e=None):
            try:
                from backend.services import box_watch_service
                output_path = box_watch_service.export_folder_tree_to_txt(inspection_state.get("selected_folder_path"))
                try:
                    box_watch_service.open_export_folder_for_file(output_path)
                except Exception:
                    pass
            except Exception as exc:
                inspection_dialog_content.content = ft.Text(f"No se pudo exportar el árbol: {exc}", color="#B42318")
                page.update()

        def set_dialog_tab(tab):
            inspection_state["dialog_tab"] = tab
            refresh_inspection_dialog_content()
            dialog.open = True
            page.update()

        def _inspection_nav_button(label, tab):
            is_active = inspection_state.get("dialog_tab") == tab
            return ft.Container(
                content=ft.Text(
                    label,
                    size=13,
                    weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500,
                    color=Q_PRIMARY_DARK if is_active else Q_MUTED,
                ),
                bgcolor="#EAF3FF" if is_active else "#FFFFFF",
                border=ft.border.all(1, "#B9D7FF" if is_active else "#E4E7EC"),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                ink=True,
                on_click=lambda e, t=tab: set_dialog_tab(t),
            )

        def inspect_folder(folder_path, push_history=False):
            try:
                from backend.services import box_watch_service

                current = inspection_state.get("selected_folder_path")
                if push_history and current:
                    stack = list(inspection_state.get("inspection_stack") or [])
                    stack.append(current)
                    inspection_state["inspection_stack"] = stack

                inspection_state["selected_folder_path"] = folder_path or ""

                # Refresco quirúrgico obligatorio antes de mostrar la ficha.
                # Escanea SOLO esta carpeta/ruta para no perder archivos nuevos, renombrados o modificados.
                box_watch_service.refresh_box_folder_before_inspection(folder_path, calculate_hash=False)

                inspection_state["inspection"] = box_watch_service.get_box_folder_inspection(folder_path)
                inspection_state["dialog_tab"] = "Documentación"
                refresh_inspection_dialog_content()
                dialog.open = True
                page.update()
            except Exception as exc:
                inspection_dialog_content.content = ft.Text(f"No se pudo inspeccionar la carpeta: {exc}", color="#B42318")
                dialog.open = True
                page.update()

        def go_back_inspection(e=None):
            stack = list(inspection_state.get("inspection_stack") or [])
            if not stack:
                return
            previous = stack.pop()
            inspection_state["inspection_stack"] = stack
            inspect_folder(previous, push_history=False)

        def build_dialog_summary():
            inspection = inspection_state.get("inspection") or {}
            folder_data = inspection.get("folder") or {}
            summary = inspection.get("summary") or {}
            fases = summary.get("fases") or {}
            documentos = summary.get("documentos") or {}

            fase_text = ", ".join([f"{k}: {v}" for k, v in list(fases.items())[:12]]) or "Sin fases detectadas"
            doc_text = ", ".join([f"{k}: {v}" for k, v in list(documentos.items())[:14]]) or "Sin documentos detectados"

            return ft.Column(
                controls=[
                    ft.Text(folder_data.get("nombre_carpeta") or inspection_state.get("selected_folder_path") or "Carpeta seleccionada", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(folder_data.get("ruta") or inspection_state.get("selected_folder_path") or "—", size=12, color=Q_MUTED),
                    ft.Row(
                        controls=[
                            _metric_card("Subcarpetas", summary.get("total_subcarpetas", 0)),
                            _metric_card("Archivos directos", summary.get("total_archivos", 0)),
                            _metric_card("Tipo carpeta", folder_data.get("tipo_detectado") or "—"),
                            _metric_card("Última actividad", _datetime_label(folder_data.get("fecha_ultima_actividad"))),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Text("Fases detectadas", size=13, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                    ft.Text(fase_text, size=12, color=Q_MUTED),
                    ft.Text("Tipos documentales detectados", size=13, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                    ft.Text(doc_text, size=12, color=Q_MUTED),
                ],
                spacing=10,
            )

        def build_dialog_documentacion():
            inspection = inspection_state.get("inspection") or {}
            folder_data = inspection.get("folder") or {}
            subfolders = inspection.get("subfolders") or []
            files = inspection.get("files") or []
            current_path = folder_data.get("ruta") or inspection_state.get("selected_folder_path") or "—"

            folder_controls = []
            for child in subfolders:
                is_para = str(child.get("nombre_carpeta") or "").strip().upper() == "PARA PRESENTAR"
                folder_controls.append(
                    ft.Container(
                        padding=10,
                        border_radius=10,
                        border=ft.border.all(1, "#B9D7FF" if is_para else "#E4E7EC"),
                        bgcolor="#EAF3FF" if is_para else "#F8FAFC",
                        ink=True,
                        on_click=lambda e, path=child.get("ruta"): inspect_folder(path, push_history=True),
                        content=ft.Row(
                            controls=[
                                ft.Text("📁", size=20),
                                ft.Column(
                                    controls=[
                                        ft.Text(child.get("nombre_carpeta") or "—", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(child.get("ruta") or "", size=11, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Text("PARA PRESENTAR", size=11, color=Q_PRIMARY, weight=ft.FontWeight.BOLD, visible=is_para),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            file_controls = []
            for item in files:
                file_controls.append(
                    ft.Container(
                        padding=10,
                        border_radius=10,
                        border=ft.border.all(1, "#E4E7EC"),
                        bgcolor="#FFFFFF",
                        content=ft.Row(
                            controls=[
                                ft.Text("📄", size=18),
                                ft.Column(
                                    controls=[
                                        ft.Text(item.get("nombre_archivo") or "—", weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                                        ft.Text(item.get("tipo_detectado") or "SIN CLASIFICAR", size=11, color=Q_MUTED),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Text(_size_label(item.get("tamano_bytes")), color=Q_MUTED, size=12),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            return ft.Column(
                width=760,
                spacing=10,
                controls=[
                    ft.Text("Documentación Box", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(
                        "Explorador readonly de la carpeta inspeccionada. No crea, mueve, borra ni renombra documentos.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, "#E4E7EC"),
                        border_radius=12,
                        padding=10,
                        content=ft.Column(
                            controls=[
                                ft.Text("Ruta actual", size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(current_path, selectable=True, size=12, color=Q_MUTED),
                            ],
                            spacing=4,
                        ),
                    ),
                    ft.Row(
                        controls=[
                            _small_button("Volver atrás", go_back_inspection),
                            _small_button("Abrir carpeta Windows", open_selected_folder),
                            _small_button("Exportar árbol TXT", export_selected_tree),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(f"Carpetas ({len(folder_controls)})", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    *(folder_controls or [ft.Text("No hay subcarpetas directas inventariadas.", color=Q_MUTED, size=13)]),
                    ft.Text(f"Archivos ({len(file_controls)})", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    *(file_controls or [ft.Text("No hay archivos directos inventariados en esta carpeta.", color=Q_MUTED, size=13)]),
                ],
            )

        def build_dialog_files():
            inspection = inspection_state.get("inspection") or {}
            files = inspection.get("files") or []

            if not files:
                return ft.Text("Esta carpeta no tiene archivos directos inventariados.", size=13, color=Q_MUTED)

            headers = [
                ("Archivo", 320),
                ("Tipo", 170),
                ("Estado", 140),
                ("Ext.", 70),
                ("Tamaño", 95),
                ("Fecha modificación", 155),
            ]

            rows = []
            for item in files:
                rows.append([
                    item.get("nombre_archivo") or "—",
                    item.get("tipo_detectado") or "—",
                    _status_text(item.get("estado") or "—"),
                    item.get("extension") or "—",
                    _size_label(item.get("tamano_bytes")),
                    _datetime_label(item.get("fecha_modificacion")),
                ])

            return _table(headers, rows, height=380)

        def build_dialog_acciones():
            action_controls = []
            if inspection_state.get("inspection_stack"):
                action_controls.append(_small_button("← Volver atrás", go_back_inspection))

            action_controls.extend([
                _small_button("Abrir carpeta Windows", open_selected_folder),
                _small_button("Exportar árbol TXT", export_selected_tree),
                _small_button("Cerrar", close_dialog),
            ])

            return ft.Column(
                controls=[
                    ft.Text("Acciones sobre la carpeta", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text("Acciones readonly. No crean, mueven, borran ni renombran documentos en Box.", size=12, color=Q_MUTED),
                    ft.Row(controls=action_controls, spacing=8, wrap=True),
                ],
                spacing=12,
            )

        def refresh_inspection_dialog_content():
            inspection = inspection_state.get("inspection") or {}
            folder_data = inspection.get("folder") or {}

            current_path = folder_data.get("ruta") or inspection_state.get("selected_folder_path") or "—"
            current_name = folder_data.get("nombre_carpeta") or inspection_state.get("selected_folder_path") or "Carpeta seleccionada"
            selected = inspection_state.get("selected_folders") or []
            current_selected_index = int(inspection_state.get("selected_index") or 0)
            selected_label = f"Ficha {current_selected_index + 1}/{len(selected)}" if len(selected) > 1 else ""

            tab = inspection_state.get("dialog_tab") or "Resumen"
            if tab == "Documentación":
                body = build_dialog_documentacion()
            elif tab == "Archivos":
                body = build_dialog_files()
            elif tab == "Acciones":
                body = build_dialog_acciones()
            else:
                body = build_dialog_summary()

            menu_items = [
                ("Resumen", "Resumen"),
                ("Documentación", "Documentación"),
                ("Archivos", "Archivos"),
                ("Acciones", "Acciones"),
            ]

            inspection_dialog_content.content = ft.Row(
                controls=[
                    ft.Container(
                        width=240,
                        height=700,
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, "#E4E7EC"),
                        border_radius=14,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Menú documentación", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Navega por cada zona sin deslizar todo el diálogo.", size=12, color=Q_MUTED),
                                ft.Divider(),
                                *[_inspection_nav_button(label, tab_name) for label, tab_name in menu_items],
                                ft.Divider(),
                                ft.Text(selected_label or "Ficha actual", size=12, color=Q_MUTED),
                                _icon_action("Anterior", ft.Icons.ARROW_BACK, go_prev_selected_folder, disabled=not (len(selected) > 1 and current_selected_index > 0)),
                                _icon_action("Siguiente", ft.Icons.ARROW_FORWARD, go_next_selected_folder, disabled=not (len(selected) > 1 and current_selected_index < len(selected) - 1)),
                                _icon_action("Atrás carpeta", ft.Icons.KEYBOARD_RETURN, go_back_inspection, disabled=not bool(inspection_state.get("inspection_stack"))),
                                ft.Divider(),
                                _icon_action("Abrir carpeta", ft.Icons.FOLDER_OPEN, open_selected_folder),
                                _icon_action("Cerrar", ft.Icons.CLOSE, close_dialog),
                            ],
                            spacing=8,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                    ),
                    ft.Container(
                        width=810,
                        height=700,
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, "#E4E7EC"),
                        border_radius=14,
                        padding=16,
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text("Documentación Box", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(current_name, size=13, color=Q_MUTED),
                                        ft.Text(selected_label, size=12, color=Q_MUTED, visible=bool(selected_label)),
                                    ],
                                    spacing=8,
                                    wrap=True,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(
                                    "Explorador readonly de la carpeta inspeccionada. No crea, mueve, borra ni renombra documentos.",
                                    size=12,
                                    color=Q_MUTED,
                                ),
                                ft.Container(
                                    bgcolor="#F8FAFC",
                                    border=ft.border.all(1, "#E4E7EC"),
                                    border_radius=12,
                                    padding=10,
                                    content=ft.Column(
                                        controls=[
                                            ft.Text("Ruta actual", size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                            ft.Text(current_path, selectable=True, size=12, color=Q_MUTED),
                                        ],
                                        spacing=4,
                                    ),
                                ),
                                ft.Container(
                                    height=510,
                                    bgcolor="#FFFFFF",
                                    content=ft.Column(
                                        controls=[body],
                                        spacing=10,
                                        scroll=ft.ScrollMode.AUTO,
                                    ),
                                ),
                            ],
                            spacing=12,
                        ),
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        try:
            if dialog not in page.overlay:
                page.overlay.append(dialog)
        except Exception:
            pass
        dialog.open = True
        inspection_dialog_content.content = ft.Container(
            width=1080,
            height=700,
            bgcolor="#FFFFFF",
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                controls=[
                    ft.ProgressRing(),
                    ft.Text("Escaneando solo esta ruta antes de abrir la ficha...", size=13, color=Q_MUTED),
                    ft.Text(ruta, size=11, color=Q_MUTED, selectable=True),
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        page.update()

        inspect_folder(ruta, push_history=False)


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

        selected_items = [
            item for item in all_rows
            if str(item.get("ruta") or "") in selected_missing_presentation
        ]

        def refresh_selection_controls():
            selected_count = len(selected_missing_presentation)
            missing_selection_counter.value = f"Seleccionados: {selected_count}"
            missing_open_button_holder.opacity = 1 if selected_count >= 1 else 0.45
            page.update()

        def update_row_visual(row_ref, checkbox, selected, index):
            try:
                if checkbox is not None:
                    checkbox.value = selected
                control = (row_ref or {}).get("control")
                if control is not None:
                    control.bgcolor = "#EAF3FF" if selected else ("#FAFBFC" if index % 2 else "#FFFFFF")
                    control.update()
                if checkbox is not None:
                    checkbox.update()
            except Exception:
                pass
            refresh_selection_controls()

        def open_single_missing_folder(folder_item):
            path = str((folder_item or {}).get("ruta") or "")
            if path and path not in selected_missing_presentation:
                selected_missing_presentation.add(path)
            current_selected = [
                item for item in (missing_presentation_rows_cache["rows"] or [])
                if str(item.get("ruta") or "") in selected_missing_presentation
            ]
            selected_index = 0
            for idx, item in enumerate(current_selected):
                if str(item.get("ruta") or "") == path:
                    selected_index = idx
                    break
            open_missing_folder_dialog(folder_item, selected_folders=current_selected or [folder_item], selected_index=selected_index)

        def open_selected_missing_folder(e=None):
            current_paths = set(selected_missing_presentation or set())
            current_selected = [
                item for item in (missing_presentation_rows_cache["rows"] or [])
                if str(item.get("ruta") or "") in current_paths
            ]
            if not current_selected:
                table_container.content = _section(
                    "Sin justificante presentación",
                    ft.Text("Marca al menos una carpeta para abrir la ficha.", color="#B42318", size=13),
                    subtitle="Carpetas raíz/expedientes donde no se detecta justificante principal de presentación.",
                )
                page.update()
                return
            open_missing_folder_dialog(current_selected[0], selected_folders=current_selected, selected_index=0)

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
            refresh_selection_controls()

        for row_index, item in enumerate(visible_items):
            ruta = str(item.get("ruta") or "")
            row_ref = {"control": None}
            selected = ruta in selected_missing_presentation
            checkbox = ft.Checkbox(value=selected)

            def set_selected(path, value, row_ref=row_ref, checkbox=checkbox, index=row_index):
                if value:
                    selected_missing_presentation.add(path)
                else:
                    selected_missing_presentation.discard(path)
                update_row_visual(row_ref, checkbox, value, index)

            def toggle_one(e, path=ruta, row_ref=row_ref, checkbox=checkbox, index=row_index):
                set_selected(path, bool(e.control.value), row_ref=row_ref, checkbox=checkbox, index=index)

            def toggle_row(e=None, path=ruta, row_ref=row_ref, checkbox=checkbox, index=row_index):
                new_value = path not in selected_missing_presentation
                set_selected(path, new_value, row_ref=row_ref, checkbox=checkbox, index=index)

            checkbox.on_change = toggle_one

            rows.append([
                {"__row_meta__": True, "selected": selected, "on_click": toggle_row, "row_ref": row_ref},
                checkbox,
                ft.Text(item.get("tipo_expediente") or "—", size=12, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                item.get("ruta_box") or "—",
                item.get("nombre_carpeta") or "—",
                _number(item.get("total_archivos")),
                _number(item.get("total_subcarpetas")),
                _safe_value(item.get("fecha_ultima_actividad")),
                _safe_value(item.get("ultimo_escaneo")),
                ft.TextButton("Abrir", on_click=lambda e, folder=item: open_single_missing_folder(folder)),
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

        missing_select_all_checkbox.on_change = toggle_all
        missing_select_all_checkbox.value = bool(visible_items) and all(
            str(item.get("ruta") or "") in selected_missing_presentation
            for item in visible_items
        )
        missing_selection_counter.value = f"Seleccionados: {len(selected_missing_presentation)}"
        missing_open_button_holder.content = _small_button("Abrir ficha", on_click=open_selected_missing_folder, icon=ft.Icons.FOLDER_OPEN)
        missing_open_button_holder.tooltip = "Marca una o varias carpetas. Si hay varias, podrás navegar entre sus fichas."
        missing_open_button_holder.opacity = 1 if len(selected_items) >= 1 else 0.45

        start_label = 0 if total_rows == 0 else start_index + 1
        pagination = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            content=ft.Row(
                controls=[
                    ft.Text(
                        f"Resultados: {total_rows} · Mostrando {start_label}-{end_index}",
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
                        missing_select_all_checkbox,
                        missing_selection_counter,
                        missing_open_button_holder,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                (
                    ft.Column(
                        controls=[
                            _selectable_table(
                                headers=[
                                    ("Sel.", 55),
                                    ("Tipo", 160),
                                    ("Ruta Box", 220),
                                    ("Carpeta raíz", 250),
                                    ("Arch.", 70),
                                    ("Sub.", 70),
                                    ("Última actividad", 150),
                                    ("Último escaneo", 160),
                                    ("Acción", 80),
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

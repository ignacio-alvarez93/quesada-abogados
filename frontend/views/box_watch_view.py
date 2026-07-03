import threading
import time
import unicodedata
from datetime import datetime

import flet as ft

from backend.services import box_watch_job_service, box_watch_service
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_file_card import document_file_card
from frontend.components.bulk_action_bar import bulk_action_bar
from frontend.components.listing import compact_pagination_bar
from frontend.components.app_card import metric_card, info_card
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import app_table
from frontend.components.app_text_field import text_input
from frontend.components.listing.card_item import card_item
from frontend.components.listing.status_chip import status_chip

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_MUTED = "#64748B"
Q_DANGER = "#B42318"
Q_WARNING = "#B54708"

BOX_WATCH_VIEW_CACHE = {
    "loaded": False,
    "selected_route": "TODAS",
    "root_filter": "",
    "root_limit": 999999999,
    "root_page": 1,
    "root_page_size": 100,
    "sort_by": "Última actividad",
    "sort_dir": "Descendente",
    "root_rows": [],
    "root_total_rows": 0,
    "all_root_rows": [],
    "selected_paths": set(),
    "last_scan_results": [],
    "last_scan_finished_at": "",
    "box_screen": "routes",
}



ROOT_PAGE_SIZE_DEFAULT = 100
ROOT_PAGE_SIZE_OPTIONS = [50, 100, 150, 200]

BOX_WATCH_PROGRESS_STATE = {
    "scanning": False,
    "loading_folders": False,
    "loading_label": "",
    "progress_percent": 0,
    "progress_processed": 0,
    "progress_folders": 0,
    "progress_total": 0,
    "progress_total_folders": 0,
    "progress_file": "",
    "progress_route": "",
}

def _filter_norm(value):
    raw = str(value or "").strip().lower()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    return raw


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _duration_label(started_at, finished_at=None):
    started = _parse_iso_datetime(started_at)
    if not started:
        return "—"

    finished = _parse_iso_datetime(finished_at) or datetime.now()
    seconds = max(0, int((finished - started).total_seconds()))

    if seconds < 60:
        return f"{seconds}s"

    minutes, rem_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem_seconds}s"

    hours, rem_minutes = divmod(minutes, 60)
    return f"{hours}h {rem_minutes}m"


def _short_datetime_label(value):
    parsed = _parse_iso_datetime(value)
    if not parsed:
        return "—"
    return parsed.strftime("%H:%M:%S")


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


def _datetime_label(value):
    if not value:
        return "—"
    raw = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    try:
        return datetime.fromisoformat(raw).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return raw


def _status_text(value):
    color = Q_PRIMARY
    if value in ("CRITICA", "ERROR", "DUPLICADO", "RESUELTO_DENEGADO"):
        color = Q_DANGER
    if value in ("ALTA", "SIN CLASIFICAR", "PENDIENTE REVISION", "REQUERIDO"):
        color = Q_WARNING
    return ft.Text(str(value or "—"), size=13, weight=ft.FontWeight.W_600, color=color)




def _document_route_label(folder):
    ruta_relativa = str(folder.get("ruta_relativa") or "").replace("\\", "/").strip("/")
    if ruta_relativa:
        parts = [p.strip() for p in ruta_relativa.split("/") if p.strip()]
        if parts and parts[0].upper() == "BOX":
            parts = parts[1:]
        return " > ".join(parts)

    config_relative = str(folder.get("config_route_relative") or "").replace("\\", "/").strip("/")
    if config_relative:
        parts = [p.strip() for p in config_relative.split("/") if p.strip()]
        if parts and parts[0].upper() == "BOX":
            parts = parts[1:]
        return " > ".join(parts)

    label = str(folder.get("config_route_label") or "").strip()
    if "·" in label:
        label = label.split("·", 1)[1].strip()
    if label:
        parts = [p.strip() for p in label.replace("\\", "/").split("/") if p.strip()]
        if parts and parts[0].upper() == "BOX":
            parts = parts[1:]
        return " > ".join(parts)

    return ""


def _client_root_folder(folder):
    nombre = str(folder.get("nombre_carpeta") or "").strip()
    if nombre:
        return nombre

    ruta = str(folder.get("ruta") or "").replace("\\", "/").strip("/")
    return ruta.split("/")[-1] if ruta else ""


def _document_year(folder):
    route_label = _document_route_label(folder)
    parts = [p.strip() for p in route_label.replace(">", "/").split("/") if p.strip()]

    for part in reversed(parts):
        if part.isdigit() and len(part) == 4:
            return part

    return "—"


def _document_case_label(folder):
    route_label = _document_route_label(folder)
    year = _document_year(folder)

    if year != "—":
        parts = [p.strip() for p in route_label.split(">") if p.strip()]
        parts = [p for p in parts if p != year]
        return " > ".join(parts) or route_label

    return route_label or "—"


def _box_link_label(folder):
    expediente_id = folder.get("expediente_id")
    display = str(folder.get("expediente_display") or "").strip()
    numero = str(folder.get("numero_expediente") or "").strip()

    if display:
        return display
    if numero:
        return numero
    if expediente_id:
        return f"EXPEDIENTE ID {expediente_id}"
    return "Sin vincular"


def _box_link_color(folder):
    return Q_PRIMARY if folder.get("expediente_id") else Q_MUTED


def _sort_key_for_folder(row, sort_by):
    client_folder = row.get("_client_folder") if isinstance(row, dict) else None
    year = row.get("_document_year") if isinstance(row, dict) else None
    case_label = row.get("_case_label") if isinstance(row, dict) else None

    if client_folder is None:
        client_folder = _client_root_folder(row)
    if year is None:
        year = _document_year(row)
    if case_label is None:
        case_label = _document_case_label(row)

    if sort_by == "Cliente":
        return (client_folder, year, case_label)
    if sort_by == "Año":
        return (year, case_label, client_folder)
    if sort_by == "Trámite":
        return (case_label, year, client_folder)
    if sort_by == "Última actividad":
        return (row.get("fecha_ultima_actividad") or "", client_folder)
    if sort_by == "Último escaneo":
        return (row.get("last_scan") or row.get("ultimo_escaneo") or "", client_folder)
    if sort_by == "Archivos":
        return (int(row.get("total_archivos_recursivos") or row.get("total_archivos") or 0), client_folder)
    if sort_by == "Subcarpetas":
        return (int(row.get("total_subcarpetas_recursivas") or row.get("total_subcarpetas") or 0), client_folder)

    return (client_folder, year, case_label)


def box_watch_view(page: ft.Page):
    state = {
        "message": None,
        "routes": [],
        "selected_route": BOX_WATCH_VIEW_CACHE.get("selected_route", "TODAS"),
        "root_loaded": bool(BOX_WATCH_VIEW_CACHE.get("loaded")),
        "root_filter": BOX_WATCH_VIEW_CACHE.get("root_filter", ""),
        "root_limit": BOX_WATCH_VIEW_CACHE.get("root_limit", 999999999),
        "root_page": int(BOX_WATCH_VIEW_CACHE.get("root_page", 1) or 1),
        "root_page_size": int(BOX_WATCH_VIEW_CACHE.get("root_page_size", ROOT_PAGE_SIZE_DEFAULT) or ROOT_PAGE_SIZE_DEFAULT),
        "root_rows": list(BOX_WATCH_VIEW_CACHE.get("root_rows") or []),
        "root_total_rows": int(BOX_WATCH_VIEW_CACHE.get("root_total_rows", len(BOX_WATCH_VIEW_CACHE.get("root_rows") or [])) or 0),
        "all_root_rows": list(BOX_WATCH_VIEW_CACHE.get("all_root_rows") or BOX_WATCH_VIEW_CACHE.get("root_rows") or []),
        "selected_paths": set(BOX_WATCH_VIEW_CACHE.get("selected_paths") or set()),
        "sort_by": BOX_WATCH_VIEW_CACHE.get("sort_by", "Última actividad"),
        "sort_dir": BOX_WATCH_VIEW_CACHE.get("sort_dir", "Descendente"),
        "selected_folder_path": "",
        "inspection": None,
        "inspection_stack": [],
        "dialog_tab": "Resumen",
        "box_screen": BOX_WATCH_VIEW_CACHE.get("box_screen", "routes"),
        "last_scan_results": list(BOX_WATCH_VIEW_CACHE.get("last_scan_results") or []),
        "last_scan_finished_at": BOX_WATCH_VIEW_CACHE.get("last_scan_finished_at", ""),
        "latest_scan_job": None,
        "route_page": int(BOX_WATCH_VIEW_CACHE.get("route_page") or 1),
        "route_page_size": 10,
        "selected_scan_route_ids": list(BOX_WATCH_VIEW_CACHE.get("selected_scan_route_ids") or []),
        "scanning": bool(BOX_WATCH_PROGRESS_STATE.get("scanning")),
        "loading_folders": bool(BOX_WATCH_PROGRESS_STATE.get("loading_folders")),
        "loading_label": BOX_WATCH_PROGRESS_STATE.get("loading_label", ""),
        "progress_percent": BOX_WATCH_PROGRESS_STATE.get("progress_percent", 0),
        "progress_processed": BOX_WATCH_PROGRESS_STATE.get("progress_processed", 0),
        "progress_folders": BOX_WATCH_PROGRESS_STATE.get("progress_folders", 0),
        "progress_total": BOX_WATCH_PROGRESS_STATE.get("progress_total", 0),
        "progress_total_folders": BOX_WATCH_PROGRESS_STATE.get("progress_total_folders", 0),
        "progress_file": BOX_WATCH_PROGRESS_STATE.get("progress_file", ""),
        "progress_route": BOX_WATCH_PROGRESS_STATE.get("progress_route", ""),
    }

    content_area = ft.Container(expand=True)
    root_table_container = ft.Container(expand=True)
    root_toolbar_container = ft.Container()
    filter_timer = {"timer": None}
    filter_job = {"seq": 0, "last_applied": None}
    root_filter_input = text_input("Buscar cliente / expediente", value=BOX_WATCH_VIEW_CACHE.get("root_filter", ""), width=300)
    route_dd = ft.Dropdown(label="Ruta Box configurada", width=420, options=[])
    sort_by_dd = ft.Dropdown(
        label="Ordenar por",
        width=190,
        options=[
            ft.dropdown.Option("Última actividad"),
            ft.dropdown.Option("Cliente"),
            ft.dropdown.Option("Año"),
            ft.dropdown.Option("Trámite"),
            ft.dropdown.Option("Último escaneo"),
            ft.dropdown.Option("Archivos"),
            ft.dropdown.Option("Subcarpetas"),
        ],
        value=BOX_WATCH_VIEW_CACHE.get("sort_by", "Última actividad"),
    )
    sort_dir_dd = ft.Dropdown(
        label="Dirección",
        width=145,
        options=[
            ft.dropdown.Option("Ascendente"),
            ft.dropdown.Option("Descendente"),
        ],
        value=BOX_WATCH_VIEW_CACHE.get("sort_dir", "Descendente"),
    )
    page_size_dd = ft.Dropdown(
        label="Filas/página",
        width=135,
        options=[ft.dropdown.Option(str(v)) for v in ROOT_PAGE_SIZE_OPTIONS],
        value=str(BOX_WATCH_VIEW_CACHE.get("root_page_size", ROOT_PAGE_SIZE_DEFAULT) or ROOT_PAGE_SIZE_DEFAULT),
    )

    inspection_dialog_content = ft.Container(width=1080, height=720)
    inspection_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Inspección documental Box", color=Q_PRIMARY_DARK, weight=ft.FontWeight.BOLD),
        content=inspection_dialog_content,
        actions=[],
    )
    page.overlay.append(inspection_dialog)

    link_expediente_dd = ft.Dropdown(
        label="Vincular a expediente",
        width=760,
        options=[],
    )

    try:
        box_watch_service.initialize_box_watch_schema()
        box_watch_service.ensure_box_watch_runtime_columns()
        try:
            box_watch_service.ensure_box_watch_indexes()
        except Exception:
            pass
    except Exception as exc:
        state["message"] = error_alert(f"No se pudo inicializar Vigilancia Box: {exc}")

    def safe_update():
        root_toolbar_container.content = build_root_toolbar()
        root_table_container.content = build_root_folders_table()
        content_area.content = build_layout()
        page.update()

    def notify_ok(text):
        state["message"] = success_alert(text)

    def notify_error(text):
        state["message"] = error_alert(text)

    def save_cache():
        BOX_WATCH_VIEW_CACHE["loaded"] = bool(state.get("root_loaded"))
        BOX_WATCH_VIEW_CACHE["selected_route"] = state.get("selected_route") or "TODAS"
        BOX_WATCH_VIEW_CACHE["root_filter"] = state.get("root_filter") or ""
        BOX_WATCH_VIEW_CACHE["root_limit"] = state.get("root_limit") or 999999999
        BOX_WATCH_VIEW_CACHE["root_page"] = int(state.get("root_page") or 1)
        BOX_WATCH_VIEW_CACHE["root_page_size"] = int(state.get("root_page_size") or ROOT_PAGE_SIZE_DEFAULT)
        BOX_WATCH_VIEW_CACHE["sort_by"] = state.get("sort_by") or "Última actividad"
        BOX_WATCH_VIEW_CACHE["sort_dir"] = state.get("sort_dir") or "Descendente"
        BOX_WATCH_VIEW_CACHE["root_rows"] = list(state.get("root_rows") or [])
        BOX_WATCH_VIEW_CACHE["root_total_rows"] = int(state.get("root_total_rows") or len(state.get("root_rows") or []))
        BOX_WATCH_VIEW_CACHE["all_root_rows"] = []
        BOX_WATCH_VIEW_CACHE["selected_paths"] = set(state.get("selected_paths") or set())
        BOX_WATCH_VIEW_CACHE["last_scan_results"] = list(state.get("last_scan_results") or [])
        BOX_WATCH_VIEW_CACHE["last_scan_finished_at"] = state.get("last_scan_finished_at", "")
        BOX_WATCH_VIEW_CACHE["box_screen"] = state.get("box_screen", "routes")

    def clear_cache():
        BOX_WATCH_VIEW_CACHE["loaded"] = False
        BOX_WATCH_VIEW_CACHE["root_rows"] = []
        BOX_WATCH_VIEW_CACHE["root_total_rows"] = 0
        BOX_WATCH_VIEW_CACHE["all_root_rows"] = []
        BOX_WATCH_VIEW_CACHE["root_page"] = 1
        BOX_WATCH_VIEW_CACHE["root_page_size"] = ROOT_PAGE_SIZE_DEFAULT
        BOX_WATCH_VIEW_CACHE["selected_paths"] = set()

    def save_progress_state():
        for key in [
            "scanning",
            "loading_folders",
            "loading_label",
            "progress_percent",
            "progress_processed",
            "progress_folders",
            "progress_total",
            "progress_total_folders",
            "progress_file",
            "progress_route",
        ]:
            BOX_WATCH_PROGRESS_STATE[key] = state.get(key)

    def sync_progress_from_global():
        for key, value in BOX_WATCH_PROGRESS_STATE.items():
            state[key] = value

    def refresh_routes(preserve_current=True):
        current_value = route_dd.value or state.get("selected_route") or "TODAS"

        try:
            routes = box_watch_service.get_configured_box_routes(active_only=True)
        except Exception:
            routes = []

        state["routes"] = routes
        options = [ft.dropdown.Option("TODAS", "Todas las rutas")]
        for route in routes:
            exists = "OK" if route.get("ruta_existe") else "NO ENCONTRADA"
            label = f"{route['id']} · {route['tipo_expediente_nombre']} · {route['ruta_box']} · {exists}"
            options.append(ft.dropdown.Option(str(route["id"]), label))

        route_dd.options = options
        valid = ["TODAS"] + [str(r["id"]) for r in routes]
        wanted = current_value if preserve_current else state.get("selected_route", "TODAS")
        if wanted not in valid:
            wanted = "TODAS"
        state["selected_route"] = wanted
        route_dd.value = wanted

    def on_route_change(e=None):
        state["selected_route"] = route_dd.value or "TODAS"
        state["root_loaded"] = False
        state["root_rows"] = []
        state["all_root_rows"] = []
        state["root_page"] = 1
        state["selected_paths"] = set()
        state["inspection"] = None
        state["inspection_stack"] = []
        clear_cache()
        safe_update()

    route_dd.on_change = on_route_change

    def _prepare_folder_for_memory(folder):
        """
        Precalcula campos caros una sola vez al cargar desde SQLite.
        El filtro y la ordenación trabajan después solo en memoria.
        """
        item = dict(folder or {})

        route_label = _document_route_label(item)
        client_folder = _client_root_folder(item)
        year = _document_year(item)
        case_label = _document_case_label(item)

        item["_route_label"] = route_label
        item["_client_folder"] = client_folder
        item["_document_year"] = year
        item["_case_label"] = case_label
        item["_search_key"] = _filter_norm(" ".join([
            str(client_folder or ""),
            str(year or ""),
            str(case_label or ""),
            str(route_label or ""),
            str(item.get("ruta_relativa") or ""),
            str(item.get("nombre_carpeta") or ""),
            str(item.get("ruta") or ""),
            str(item.get("expediente_display") or ""),
            str(item.get("numero_expediente") or ""),
            str(item.get("cliente_nombre") or ""),
            str(item.get("cliente_primer_apellido") or ""),
            str(item.get("cliente_segundo_apellido") or ""),
        ]))
        return item

    def _folder_matches_filter(folder, text):
        text = _filter_norm(text)
        if not text:
            return True
        return text in str(folder.get("_search_key") or "")

    def apply_memory_filter(force_text=None):
        """
        Filtro 100% en memoria.
        Caso importante: si el TextBox queda vacío, restaura TODA la tabla cargada
        desde all_root_rows, no desde la tabla previamente filtrada.
        """
        text = (root_filter_input.value if force_text is None else force_text) or ""
        text = str(text).strip()
        state["root_filter"] = text

        base_rows = state.get("all_root_rows") or []

        if not text:
            filtered = list(base_rows)
        else:
            normalized = _filter_norm(text)
            filtered = [row for row in base_rows if normalized in str(row.get("_search_key") or "")]

        state["root_rows"] = _sorted_root_rows(filtered)
        state["root_page"] = 1
        _clamp_root_page()

        selected_paths = set(state.get("selected_paths") or set())
        visible_paths = {row.get("ruta") for row in state["root_rows"]}
        state["selected_paths"] = {path for path in selected_paths if path in visible_paths}

        # Guardamos solo estado ligero. Guardar listas grandes en cada tecla mete lag.
        BOX_WATCH_VIEW_CACHE["loaded"] = bool(state.get("root_loaded"))
        BOX_WATCH_VIEW_CACHE["selected_route"] = state.get("selected_route") or "TODAS"
        BOX_WATCH_VIEW_CACHE["root_filter"] = state.get("root_filter") or ""
        BOX_WATCH_VIEW_CACHE["root_limit"] = state.get("root_limit") or 999999999
        BOX_WATCH_VIEW_CACHE["root_page"] = int(state.get("root_page") or 1)
        BOX_WATCH_VIEW_CACHE["root_page_size"] = int(state.get("root_page_size") or ROOT_PAGE_SIZE_DEFAULT)
        BOX_WATCH_VIEW_CACHE["sort_by"] = state.get("sort_by") or "Última actividad"
        BOX_WATCH_VIEW_CACHE["sort_dir"] = state.get("sort_dir") or "Descendente"
        BOX_WATCH_VIEW_CACHE["selected_paths"] = set(state.get("selected_paths") or set())

    def _sorted_root_rows(rows):
        sort_by = sort_by_dd.value or state.get("sort_by") or "Última actividad"
        sort_dir = sort_dir_dd.value or state.get("sort_dir") or "Descendente"
        state["sort_by"] = sort_by
        state["sort_dir"] = sort_dir
        reverse = sort_dir == "Descendente"
        try:
            return sorted(rows or [], key=lambda r: _sort_key_for_folder(r, sort_by), reverse=reverse)
        except Exception:
            return rows or []

    def _root_page_size():
        try:
            size = int(page_size_dd.value or state.get("root_page_size") or ROOT_PAGE_SIZE_DEFAULT)
        except Exception:
            size = ROOT_PAGE_SIZE_DEFAULT
        if size not in ROOT_PAGE_SIZE_OPTIONS:
            size = ROOT_PAGE_SIZE_DEFAULT
        state["root_page_size"] = size
        page_size_dd.value = str(size)
        return size

    def _root_total_pages():
        total = int(state.get("root_total_rows") or len(state.get("root_rows") or []))
        size = max(1, _root_page_size())
        return max(1, (total + size - 1) // size)

    def _clamp_root_page():
        total_pages = _root_total_pages()
        try:
            page_number = int(state.get("root_page") or 1)
        except Exception:
            page_number = 1
        state["root_page"] = max(1, min(page_number, total_pages))
        return state["root_page"]

    def _current_page_rows():
        # Paginación visual en memoria: root_rows contiene TODAS las carpetas cargadas.
        page_number = _clamp_root_page()
        page_size = _root_page_size()
        rows = state.get("root_rows") or []
        start = (page_number - 1) * page_size
        end = start + page_size
        return rows[start:end]

    def on_page_size_change(e=None):
        state["root_page_size"] = _root_page_size()
        state["root_page"] = 1
        BOX_WATCH_VIEW_CACHE["root_page_size"] = state["root_page_size"]
        BOX_WATCH_VIEW_CACHE["root_page"] = 1
        refresh_root_table()

    page_size_dd.on_change = on_page_size_change

    def on_sort_change(e=None):
        state["sort_by"] = sort_by_dd.value or "Última actividad"
        state["sort_dir"] = sort_dir_dd.value or "Descendente"
        state["root_page"] = 1
        if state.get("root_loaded"):
            state["root_rows"] = _sorted_root_rows(state.get("root_rows") or [])
            state["all_root_rows"] = list(state.get("root_rows") or [])
            save_cache()
            refresh_root_table()
        else:
            safe_update()

    sort_by_dd.on_change = on_sort_change
    sort_dir_dd.on_change = on_sort_change

    def refresh_root_table(e=None):
        # Repintado ligero: NO reconstruye toda la vista.
        root_toolbar_container.content = build_root_toolbar()
        root_table_container.content = build_root_folders_table()
        page.update()

    def _run_filter_after_debounce(seq, text):
        if not state.get("root_loaded"):
            return
        # Evita que timers antiguos repinten por detrás y provoquen saltos.
        if seq != filter_job.get("seq"):
            return
        if text == filter_job.get("last_applied"):
            return
        try:
            filter_job["last_applied"] = text
            state["root_filter"] = text
            state["root_page"] = 1
            load_root_folders(show_loading=False, refresh_routes_before=False)
        except Exception:
            pass

    def on_root_filter_change(e=None):
        if not state.get("root_loaded"):
            return

        text = (root_filter_input.value or "").strip()
        state["root_filter"] = text

        current_timer = filter_timer.get("timer")
        if current_timer:
            try:
                current_timer.cancel()
            except Exception:
                pass

        filter_job["seq"] = int(filter_job.get("seq") or 0) + 1
        seq = filter_job["seq"]

        # Caso crítico: si se limpia el TextBox, se restaura la lista completa INMEDIATAMENTE.
        # No esperamos al debounce porque Flet puede no disparar otro evento y la tabla queda filtrada.
        if not text:
            filter_job["last_applied"] = ""
            state["root_filter"] = ""
            state["root_page"] = 1
            load_root_folders(show_loading=False, refresh_routes_before=False)
            return

        # Con texto, sí aplicamos debounce para no reconstruir la tabla por cada pulsación.
        delay = 0.45
        timer = threading.Timer(delay, lambda: _run_filter_after_debounce(seq, text))
        filter_timer["timer"] = timer
        timer.daemon = True
        timer.start()

    root_filter_input.on_change = on_root_filter_change

    def selected_route_ids():
        value = route_dd.value or state.get("selected_route") or "TODAS"
        state["selected_route"] = value
        if value == "TODAS":
            return [int(r["id"]) for r in state.get("routes", [])]
        return [int(value)]

    def selected_route_label():
        value = route_dd.value or state.get("selected_route") or "TODAS"
        if value == "TODAS":
            return "Todas las rutas configuradas"
        route = next((r for r in state.get("routes", []) if str(r.get("id")) == str(value)), None)
        if not route:
            return "Ruta seleccionada"
        return f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"

    def on_progress(progress):
        processed = int(progress.get("processed", 0) or 0)
        folders = int(progress.get("processed_folders", 0) or 0)
        total = int(progress.get("total", 0) or 0)
        total_folders = int(progress.get("total_folders", 0) or 0)

        state["progress_processed"] = processed
        state["progress_folders"] = folders
        state["progress_total"] = total
        state["progress_total_folders"] = total_folders
        state["progress_percent"] = float(progress.get("percent", 0) or 0)
        state["progress_file"] = progress.get("current_file", "") or ""
        state["progress_route"] = progress.get("route_label", "") or state.get("progress_route", "")

        save_progress_state()
        # Escaneo silencioso: no repintamos la vista en cada avance.
        # Evita barras, bloqueos visuales y parpadeos mientras Box se escanea en segundo plano.


    def refresh_latest_scan_job():
        try:
            state["latest_scan_job"] = box_watch_job_service.get_latest_job()
        except Exception:
            state["latest_scan_job"] = None
        return state.get("latest_scan_job")

    def refresh_job_panel(e=None):
        refresh_latest_scan_job()
        content_area.content = build_layout()
        safe_update()

    def watch_external_job_until_finished(job_id, interval_seconds=5):
        """
        Vigila un job externo desde la UI sin ejecutar escaneo en Flet.

        Motivo:
        El runner externo escribe el estado en SQLite, pero la vista no recibe
        un evento automático al terminar. Este watcher consulta el job cada pocos
        segundos y actualiza el panel/aviso cuando finaliza.
        """
        def _watch():
            last_estado = None

            while True:
                time.sleep(interval_seconds)

                try:
                    job = box_watch_job_service.get_job(job_id)
                except Exception as exc:
                    print(f"[Box Watch] No se pudo consultar job #{job_id}: {exc}")
                    return

                if not job:
                    return

                estado = str(job.get("estado") or "").upper()
                state["latest_scan_job"] = job

                # Refresco ligero cuando cambia el estado.
                if estado != last_estado:
                    content_area.content = build_layout()
                    safe_update()
                    last_estado = estado

                if estado in ("DONE", "ERROR", "INTERRUPTED"):
                    total_routes = int(job.get("total_routes") or 0)
                    completed_routes = int(job.get("completed_routes") or 0)
                    total_archivos = int(job.get("total_archivos") or 0)
                    total_carpetas = int(job.get("total_carpetas") or 0)
                    total_errores = int(job.get("total_errores") or 0)

                    if estado == "DONE":
                        notify_ok(
                            f"Job Box Watch #{job_id} finalizado: "
                            f"{completed_routes}/{total_routes} ruta(s), "
                            f"{total_carpetas} carpeta(s), "
                            f"{total_archivos} archivo(s), "
                            f"{total_errores} error(es)."
                        )
                    else:
                        notify_error(
                            f"Job Box Watch #{job_id} terminó en estado {estado}: "
                            f"{job.get('error') or 'sin detalle'}"
                        )

                    content_area.content = build_layout()
                    safe_update()
                    return

        try:
            runner = getattr(page, "run_thread", None)
            if callable(runner):
                runner(_watch)
                return
        except Exception:
            pass

        threading.Thread(target=_watch, daemon=True).start()

    def launch_external_scan_job(route_ids, label):
        try:
            running_job_id = box_watch_job_service.has_running_job()
            if running_job_id:
                state["latest_scan_job"] = box_watch_job_service.get_job(running_job_id)
                notify_error(f"Ya hay un job Box Watch en curso: #{running_job_id}.")
                content_area.content = build_layout()
                safe_update()
                return

            job_id = box_watch_job_service.create_scan_job(route_ids=route_ids)
            box_watch_job_service.launch_scan_job(job_id)

            state["latest_scan_job"] = box_watch_job_service.get_job(job_id)
            state["scanning"] = False
            state["progress_file"] = f"Job externo lanzado: #{job_id}"
            state["progress_route"] = label or "Box Watch"
            save_progress_state()
            save_cache()

            notify_ok(
                f"Job Box Watch #{job_id} lanzado en CMD externo. "
                "Puedes seguir trabajando. La app avisará cuando termine."
            )
            watch_external_job_until_finished(job_id)
            content_area.content = build_layout()
            safe_update()
        except Exception as exc:
            state["scanning"] = False
            notify_error(f"No se pudo lanzar job externo Box Watch: {exc}")
            safe_update()

    def start_background_worker(target, *args):
        """
        Ejecuta trabajos en segundo plano usando el mecanismo de Flet cuando existe.
        Con threading.Thread puro, algunas versiones de Flet no empujan page.update()
        hasta que el usuario hace otra acción.
        """
        try:
            runner = getattr(page, "run_thread", None)
            if callable(runner):
                runner(target, *args)
                return
        except Exception:
            pass

        threading.Thread(target=target, args=args, daemon=True).start()

    def scan_worker(route_ids):
        """
        Guard defensivo:
        Los escaneos Box Watch pesados no deben ejecutarse dentro del hilo/UI Flet.
        La vía oficial es launch_external_scan_job(), que crea un job observable y
        delega el trabajo en scripts/runners/box_watch_scan_runner.py.
        """
        state["scanning"] = False
        notify_error(
            "Escaneo interno deshabilitado por seguridad. "
            "Usa el job externo de Box Watch para permitir seguir trabajando en el CRM."
        )
        content_area.content = build_layout()
        safe_update()
        return

    def scan_selected(e=None):
        refresh_routes()
        route_ids = selected_route_ids()
        if not route_ids:
            notify_error("No hay rutas activas configuradas.")
            safe_update()
            return

        launch_external_scan_job(route_ids, selected_route_label())

    def scan_all(e=None):
        refresh_routes()
        route_ids = [int(r["id"]) for r in state.get("routes", [])]
        if not route_ids:
            notify_error("No hay rutas activas configuradas.")
            safe_update()
            return

        route_dd.value = "TODAS"
        state["selected_route"] = "TODAS"
        launch_external_scan_job(route_ids, "Todas las rutas configuradas")

    def _load_root_rows():
        selected = state.get("selected_route") or "TODAS"
        text = (state.get("root_filter") or root_filter_input.value or "").strip()
        sort_by = state.get("sort_by") or sort_by_dd.value or "Última actividad"
        sort_dir = state.get("sort_dir") or sort_dir_dd.value or "Descendente"

        # Carga completa real por páginas internas.
        # El backend puede devolver 500 por página; aquí seguimos pidiendo páginas
        # hasta traer todo y luego la paginación visible queda solo en memoria.
        sql_page_size = 500

        def load_route_full(route_id):
            all_rows = []
            page_number = 1
            total = None

            while True:
                data = box_watch_service.list_root_folders_sql_page_for_route_id(
                    int(route_id),
                    ruta_contains=text or None,
                    page=page_number,
                    page_size=sql_page_size,
                    sort_by=sort_by,
                    sort_dir=sort_dir,
                )

                rows = data.get("rows") if isinstance(data, dict) else (data or [])
                if not rows:
                    break

                all_rows.extend(rows)

                if isinstance(data, dict):
                    total = int(data.get("total") or 0)
                    if total and len(all_rows) >= total:
                        break

                if len(rows) < sql_page_size:
                    break

                page_number += 1

            return all_rows

        if selected == "TODAS":
            rows = []
            for route in state.get("routes", []) or []:
                route_id = route.get("id")
                if not route_id:
                    continue
                try:
                    rows.extend(load_route_full(route_id))
                except Exception:
                    continue
            return {"rows": rows, "total": len(rows)}

        rows = load_route_full(selected)
        return {"rows": rows, "total": len(rows)}

    def load_root_folders(e=None, show_loading=True, refresh_routes_before=True):
        try:
            if show_loading:
                state["loading_folders"] = True
                state["loading_label"] = "Cargando carpetas desde SQLite..."
                save_progress_state()
                safe_update()

            selected_before_refresh = route_dd.value or state.get("selected_route") or "TODAS"
            state["selected_route"] = selected_before_refresh

            if refresh_routes_before:
                refresh_routes(preserve_current=True)

                if selected_before_refresh in (["TODAS"] + [str(r["id"]) for r in state.get("routes", [])]):
                    state["selected_route"] = selected_before_refresh
                    route_dd.value = selected_before_refresh

            state["root_filter"] = (root_filter_input.value or state.get("root_filter") or "").strip()
            data = _load_root_rows()
            rows = data.get("rows") if isinstance(data, dict) else (data or [])
            prepared_rows = [_prepare_folder_for_memory(row) for row in (rows or [])]
            state["root_rows"] = _sorted_root_rows(prepared_rows)
            state["all_root_rows"] = list(state["root_rows"])
            state["root_total_rows"] = len(state["root_rows"])
            state["root_loaded"] = True
            _clamp_root_page()
            state["inspection"] = None
            state["inspection_stack"] = []
            state["selected_paths"] = {
                p for p in state["selected_paths"]
                if any((r.get("ruta") == p) for r in state["root_rows"])
            }
            # No mostramos alerta verde de carga: ocupa espacio y no aporta en uso diario.
            state["message"] = None
            save_cache()
            state["loading_folders"] = False
            state["loading_label"] = ""
            save_progress_state()
        except Exception as exc:
            state["root_rows"] = []
            state["root_total_rows"] = 0
            state["root_loaded"] = True
            state["loading_folders"] = False
            state["loading_label"] = ""
            save_progress_state()
            notify_error(f"No se pudieron cargar carpetas raíz: {exc}")
        safe_update()

    def load_all_root_folders(e=None):
        state["selected_route"] = "TODAS"
        route_dd.value = "TODAS"
        load_root_folders()

    def load_more_root(e=None):
        state["root_limit"] += 500
        load_root_folders()

    def toggle_selected(path, selected=None, row_ref=None, checkbox_ref=None, index=0):
        selected_paths = set(state.get("selected_paths") or set())

        if selected is None:
            selected = path not in selected_paths

        if selected:
            selected_paths.add(path)
        else:
            selected_paths.discard(path)

        state["selected_paths"] = selected_paths
        is_selected = path in selected_paths

        if row_ref and row_ref.current:
            row_ref.current.bgcolor = "#EAF3FF" if is_selected else ("#FAFBFC" if index % 2 else "#FFFFFF")

        if checkbox_ref and checkbox_ref.current:
            checkbox_ref.current.value = is_selected

        save_cache()
        root_toolbar_container.content = build_root_toolbar()
        page.update()

    def select_all_visible(e=None):
        current = {r.get("ruta") for r in _current_page_rows() if r.get("ruta")}
        selected_paths = set(state.get("selected_paths") or set())
        selected_paths.update(current)
        state["selected_paths"] = selected_paths
        notify_ok(f"Seleccionadas en página: {len(current)}")
        save_cache()
        refresh_root_table()

    def clear_selection(e=None):
        state["selected_paths"] = set()
        notify_ok("Selección limpiada.")
        save_cache()
        refresh_root_table()

    def inspect_marked_folder(e=None):
        selected = list(state.get("selected_paths") or [])
        if not selected:
            notify_error("Marca una carpeta para inspeccionarla.")
            safe_update()
            return
        if len(selected) > 1:
            notify_error("Marca solo una carpeta para inspeccionarla.")
            safe_update()
            return
        inspect_folder(selected[0], push_history=False)

    def watchdog_placeholder(e=None):
        notify_ok("Vigilancia Watchdog preparada. Se desarrollará en un módulo independiente.")
        safe_update()

    def _option_id(value):
        if not value or " - " not in str(value):
            return None
        try:
            return int(str(value).split(" - ", 1)[0])
        except Exception:
            return None

    def load_link_expediente_options():
        try:
            expedientes = box_watch_service.get_expedientes_for_box_link()
        except Exception:
            expedientes = []

        link_expediente_dd.options = [
            ft.dropdown.Option(e["display"])
            for e in expedientes
        ]

        current = None
        inspection = state.get("inspection") or {}
        folder = inspection.get("folder") or {}
        expediente_id = folder.get("expediente_id")
        if expediente_id:
            current = next(
                (e["display"] for e in expedientes if int(e.get("id")) == int(expediente_id)),
                None,
            )

        link_expediente_dd.value = current

    def selected_folder_is_root_folder():
        path = state.get("selected_folder_path")
        if not path:
            return False
        return any((row.get("ruta") == path) for row in (state.get("root_rows") or []))

    def update_linked_folder_in_memory(path, link_result):
        """
        Refresca la vinculación en las filas ya cargadas de la vista Box.
        No consulta Box ni modifica archivos. Solo actualiza el estado visual local.
        """
        normalized = str(path or "").replace("\\", "/").rstrip("/")
        if not normalized:
            return

        expediente_id = link_result.get("expediente_id")
        cliente_id = link_result.get("cliente_id")
        display = link_result.get("display") or f"EXPEDIENTE ID {expediente_id}"

        for collection_name in ("root_rows", "all_root_rows"):
            updated = []
            for row in state.get(collection_name, []) or []:
                item = dict(row)
                row_path = str(item.get("ruta") or "").replace("\\", "/").rstrip("/")
                if row_path == normalized:
                    item["expediente_id"] = expediente_id
                    item["cliente_id"] = cliente_id
                    item["expediente_display"] = display
                updated.append(item)
            state[collection_name] = updated

        save_cache()

    def link_selected_folder_to_expediente(e=None):
        path = state.get("selected_folder_path")
        expediente_id = _option_id(link_expediente_dd.value)

        if not path:
            notify_error("No hay carpeta seleccionada.")
            safe_update()
            return

        if not selected_folder_is_root_folder():
            notify_error("Solo se pueden vincular carpetas principales, no subcarpetas.")
            safe_update()
            return

        if not expediente_id:
            notify_error("Selecciona un expediente para vincular.")
            safe_update()
            return

        try:
            result = box_watch_service.link_box_folder_to_expediente(path, expediente_id)
            update_linked_folder_in_memory(path, result)
            state["inspection"] = box_watch_service.get_box_folder_inspection(path)
            notify_ok(f"Carpeta vinculada: {result.get('display')}")
            refresh_inspection_dialog_content()
            root_toolbar_container.content = build_root_toolbar()
            root_table_container.content = build_root_folders_table()
            inspection_dialog.open = True
            page.update()
        except Exception as exc:
            notify_error(f"No se pudo vincular la carpeta: {exc}")
            safe_update()

    def inspect_folder(folder_path, push_history=False):
        try:
            current = state.get("selected_folder_path")
            if push_history and current:
                stack = list(state.get("inspection_stack") or [])
                stack.append(current)
                state["inspection_stack"] = stack

            state["selected_folder_path"] = folder_path or ""

            # Refresco quirúrgico: al inspeccionar, se reescanea solo esta carpeta.
            # Evita que archivos renombrados/modificados en Box queden obsoletos en SQLite.
            # No toca Box; solo actualiza inventario local y marca FALTANTE lo que ya no existe.
            box_watch_service.refresh_box_folder_before_inspection(folder_path, calculate_hash=False)

            state["inspection"] = box_watch_service.get_box_folder_inspection(folder_path)
            state["dialog_tab"] = "Documentación"
            open_inspection_dialog()
        except Exception as exc:
            notify_error(f"No se pudo inspeccionar la carpeta: {exc}")
            safe_update()

    def go_back_inspection(e=None):
        stack = list(state.get("inspection_stack") or [])
        if not stack:
            return
        previous = stack.pop()
        state["inspection_stack"] = stack
        try:
            state["selected_folder_path"] = previous

            # Refresco quirúrgico también al volver: se actualiza la ruta principal antes de mostrarla.
            box_watch_service.refresh_box_folder_before_inspection(previous, calculate_hash=False)

            state["inspection"] = box_watch_service.get_box_folder_inspection(previous)
            state["dialog_tab"] = "Documentación"
            refresh_inspection_dialog_content()
            inspection_dialog.open = True
            page.update()
        except Exception as exc:
            notify_error(f"No se pudo volver a la carpeta anterior: {exc}")
            safe_update()

    def close_dialog(e=None):
        inspection_dialog.open = False
        page.update()

    def set_dialog_tab(tab):
        state["dialog_tab"] = tab
        refresh_inspection_dialog_content()
        inspection_dialog.open = True
        page.update()

    def open_selected_folder(e=None):
        path = state.get("selected_folder_path")
        if not path:
            notify_error("No hay carpeta seleccionada para abrir.")
            safe_update()
            return
        try:
            box_watch_service.open_folder_in_explorer(path)
            notify_ok("Carpeta abierta en el explorador.")
        except Exception as exc:
            notify_error(f"No se pudo abrir la carpeta: {exc}")
        safe_update()

    def export_selected_tree(e=None):
        path = state.get("selected_folder_path")
        if not path:
            notify_error("No hay carpeta seleccionada para exportar.")
            safe_update()
            return
        try:
            output_path = box_watch_service.export_folder_tree_to_txt(path)
            try:
                box_watch_service.open_export_folder_for_file(output_path)
            except Exception:
                pass
            notify_ok(f"Árbol exportado a TXT: {output_path}")
        except Exception as exc:
            notify_error(f"No se pudo exportar el árbol: {exc}")
        safe_update()

    def export_checked_trees(e=None):
        paths = list(state.get("selected_paths") or [])
        if not paths:
            notify_error("Marca al menos una carpeta para exportar su árbol.")
            safe_update()
            return
        try:
            output_path = box_watch_service.export_multiple_folder_trees_to_txt(paths, "arbol_box_carpetas_marcadas.txt")
            try:
                box_watch_service.open_export_folder_for_file(output_path)
            except Exception:
                pass
            notify_ok(f"Árbol exportado: {output_path}")
        except Exception as exc:
            notify_error(f"No se pudo exportar el árbol: {exc}")
        safe_update()

    def export_visible_trees(e=None):
        paths = [r.get("ruta") for r in state.get("root_rows", []) if r.get("ruta")]
        if not paths:
            notify_error("No hay carpetas visibles para exportar.")
            safe_update()
            return
        try:
            output_path = box_watch_service.export_multiple_folder_trees_to_txt(paths, "arbol_box_tabla_visible.txt")
            try:
                box_watch_service.open_export_folder_for_file(output_path)
            except Exception:
                pass
            notify_ok(f"Árbol completo visible exportado: {output_path}")
        except Exception as exc:
            notify_error(f"No se pudo exportar el árbol completo: {exc}")
        safe_update()

    def header():
        controls = [
            ft.Text("Vigilancia Box", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text("Rutas configuradas → carpetas de cliente/expediente → inspección documental", size=14, color=Q_MUTED),
        ]
        if state["message"]:
            controls.append(state["message"])
        return ft.Column(controls=controls, spacing=8)

    def build_summary():
        if state["scanning"]:
            return info_card(
                "1. Resumen",
                ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                metric_card("Reescaneo", "En curso"),
                                metric_card("Ruta", state.get("progress_route") or "—"),
                                metric_card("Carpetas", state.get("progress_folders", 0)),
                                metric_card("Archivos", state.get("progress_processed", 0)),
                                metric_card("Progreso", f"{state.get('progress_percent', 0):.1f}%"),
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Text(
                            state.get("progress_file") or "Escaneo en segundo plano. La tabla sigue disponible.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=8,
                ),
            )

        try:
            summary = box_watch_service.get_box_dashboard_summary()
        except Exception as exc:
            return error_alert(f"No se pudo cargar el resumen: {exc}")

        last_results = list(state.get("last_scan_results") or [])
        last_finished = state.get("last_scan_finished_at") or ""

        last_total_routes = len(last_results)
        last_errors = sum(
            1 for r in last_results
            if str(r.get("estado") or "").upper() == "ERROR"
            or str(r.get("scan_mode") or "").upper() == "ERROR"
        )
        last_ok = max(0, last_total_routes - last_errors)
        last_files = sum(int(r.get("total_archivos", 0) or 0) for r in last_results)
        last_folders = sum(int(r.get("total_carpetas", 0) or 0) for r in last_results)
        last_minutes = sum(float(r.get("duration_minutes") or 0) for r in last_results)
        massive_count = sum(1 for r in last_results if str(r.get("scan_mode") or "").upper() == "BATCH_MASSIVE_ROOT")

        slowest = None
        if last_results:
            slowest = max(last_results, key=lambda r: float(r.get("duration_seconds") or 0))

        def _short_route_label(value, max_len=88):
            raw = str(value or "").replace("\\", "/").strip()
            if len(raw) <= max_len:
                return raw
            return "…" + raw[-max_len:]

        slowest_label = "—"
        if slowest:
            route_name = slowest.get("config_route_relative") or slowest.get("config_route_resolved") or "Ruta"
            slowest_label = f"{_short_route_label(route_name)} · {float(slowest.get('duration_minutes') or 0):.2f} min"

        dashboard_row = ft.Row(
            controls=[
                metric_card("Rutas activas", len(state.get("routes", []))),
                metric_card("Carpetas inventario", summary.get("total_carpetas", 0)),
                metric_card("Archivos inventario", summary.get("total_archivos", 0)),
                metric_card("Sin clasificar", summary.get("sin_clasificar", 0)),
                metric_card("Último escaneo BD", summary.get("ultimo_escaneo", "Sin escaneos")),
            ],
            spacing=12,
            wrap=True,
        )

        if not last_results:
            return info_card(
                "1. Resumen",
                ft.Column(
                    controls=[
                        dashboard_row,
                        ft.Text(
                            "Todavía no hay resumen visual del último escaneo en esta sesión. Ejecuta Reescanear o Reescanear todas para verlo aquí.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=10,
                ),
            )

        scan_row = ft.Row(
            controls=[
                metric_card("Último escaneo", _datetime_label(last_finished)),
                metric_card("Rutas escaneadas", last_total_routes),
                metric_card("OK", last_ok),
                metric_card("Errores", last_errors),
                metric_card("Masivas", massive_count),
                metric_card("Tiempo", f"{last_minutes:.2f} min"),
            ],
            spacing=12,
            wrap=True,
        )

        totals_row = ft.Row(
            controls=[
                metric_card("Archivos escaneados", last_files),
                metric_card("Carpetas escaneadas", last_folders),
            ],
            spacing=12,
            wrap=True,
        )

        slowest_text = ft.Text(
            f"Ruta más lenta: {slowest_label}",
            size=12,
            color=Q_MUTED,
            selectable=True,
        )

        error_lines = []
        for r in last_results:
            is_error = (
                str(r.get("estado") or "").upper() == "ERROR"
                or str(r.get("scan_mode") or "").upper() == "ERROR"
            )
            if not is_error:
                continue
            error_lines.append(
                ft.Text(
                    f"ERROR · {r.get('config_route_relative') or r.get('config_route_resolved') or 'Ruta'} · {r.get('error') or 'Sin detalle'}",
                    size=12,
                    color=Q_DANGER,
                )
            )

        controls = [
            dashboard_row,
            ft.Divider(height=10),
            scan_row,
            totals_row,
            slowest_text,
        ]

        if error_lines:
            controls.extend([
                ft.Divider(height=10),
                ft.Text("Rutas con incidencia", size=13, weight=ft.FontWeight.BOLD, color=Q_DANGER),
                *error_lines[:5],
            ])

        return info_card(
            "1. Resumen",
            ft.Column(
                controls=controls,
                spacing=10,
            ),
        )

    def build_route_controls():
        # No llamar a refresh_routes() en cada repaint: consulta backend y empeora el lag.
        # Las rutas se refrescan al entrar en la vista y antes de cargar/escanear.
        if not state.get("routes"):
            return info_card(
                "2. Rutas Box configuradas",
                ft.Column(
                    controls=[
                        empty_state("No hay rutas Box activas en Configuración."),
                        ft.Text("Ve a Configuración → Rutas Box y añade, por ejemplo: Box/NACIONALIDADES/2019", size=12, color=Q_MUTED),
                    ],
                    spacing=8,
                ),
            )

        valid_sort_values = {"Última actividad", "Cliente", "Año", "Trámite", "Último escaneo", "Archivos", "Subcarpetas"}
        if state.get("sort_by") not in valid_sort_values:
            state["sort_by"] = "Última actividad"
        if state.get("sort_dir") not in {"Ascendente", "Descendente"}:
            state["sort_dir"] = "Descendente"

        sort_by_dd.value = state.get("sort_by") or "Última actividad"
        sort_dir_dd.value = state.get("sort_dir") or "Descendente"

        left = ft.Column(
            controls=[
                ft.Row([route_dd, root_filter_input], spacing=8, wrap=True),
                ft.Row([sort_by_dd, sort_dir_dd, page_size_dd, secondary_button("Ordenar", on_sort_change)], spacing=8, wrap=True),
            ],
            spacing=8,
        )

        right = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        primary_button("Cargar", load_root_folders),
                        secondary_button("Todas", load_all_root_folders),
                        secondary_button("Recargar", load_root_folders),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        primary_button("Reescanear", scan_selected),
                        secondary_button("Reescanear todas", scan_all),
                    ],
                    spacing=8,
                    wrap=True,
                ),
            ],
            spacing=8,
        )

        controls = [
            ft.Row([left, right], spacing=14, wrap=True),
        ]

        if state.get("loading_folders"):
            controls.extend([
                ft.ProgressBar(value=None, width=760),
                ft.Text(state.get("loading_label") or "Cargando carpetas...", size=12, color=Q_MUTED),
            ])

        if state["scanning"]:
            controls.append(
                ft.Text(
                    f"Escaneo en segundo plano: {state.get('progress_route') or 'ruta seleccionada'}. La tabla sigue disponible.",
                    size=12,
                    color=Q_MUTED,
                )
            )

        return info_card("2. Rutas Box configuradas", ft.Column(controls=controls, spacing=10))

    def go_first_root_page(e=None):
        state["root_page"] = 1
        BOX_WATCH_VIEW_CACHE["root_page"] = 1
        load_root_folders(show_loading=False, refresh_routes_before=False)

    def go_prev_root_page(e=None):
        state["root_page"] = max(1, int(state.get("root_page") or 1) - 1)
        BOX_WATCH_VIEW_CACHE["root_page"] = state["root_page"]
        load_root_folders(show_loading=False, refresh_routes_before=False)

    def go_next_root_page(e=None):
        state["root_page"] = min(_root_total_pages(), int(state.get("root_page") or 1) + 1)
        BOX_WATCH_VIEW_CACHE["root_page"] = state["root_page"]
        load_root_folders(show_loading=False, refresh_routes_before=False)

    def go_last_root_page(e=None):
        state["root_page"] = _root_total_pages()
        BOX_WATCH_VIEW_CACHE["root_page"] = state["root_page"]
        load_root_folders(show_loading=False, refresh_routes_before=False)

    def go_to_root_page(page_number):
        try:
            page_number = int(page_number)
        except Exception:
            page_number = 1
        state["root_page"] = max(1, min(page_number, _root_total_pages()))
        BOX_WATCH_VIEW_CACHE["root_page"] = state["root_page"]
        load_root_folders(show_loading=False, refresh_routes_before=False)

    def _root_page_numbers(current, total):
        # Devuelve una paginación compacta: 1 2 3 4 5 ... última
        if total <= 7:
            return list(range(1, total + 1))

        pages = {1, total, current - 1, current, current + 1}
        if current <= 4:
            pages.update(range(1, 6))
        elif current >= total - 3:
            pages.update(range(total - 4, total + 1))

        result = []
        last = None
        for num in sorted(p for p in pages if 1 <= p <= total):
            if last is not None and num - last > 1:
                result.append("...")
            result.append(num)
            last = num
        return result

    def build_root_pagination():
        root_folders = state.get("root_rows") or []
        total_rows = int(state.get("root_total_rows") or len(root_folders))
        page_number = int(state.get("root_page") or 1)
        total_pages = _root_total_pages()
        page_size = _root_page_size()
        selection_count = len(state.get("selected_paths") or set())
        start_num = 0 if not total_rows else ((page_number - 1) * page_size) + 1
        end_num = min(total_rows, ((page_number - 1) * page_size) + len(root_folders))

        first_btn = secondary_button("«", go_first_root_page)
        prev_btn = secondary_button("‹", go_prev_root_page)
        next_btn = secondary_button("›", go_next_root_page)
        last_btn = secondary_button("»", go_last_root_page)
        first_btn.disabled = page_number <= 1
        prev_btn.disabled = page_number <= 1
        next_btn.disabled = page_number >= total_pages
        last_btn.disabled = page_number >= total_pages

        page_controls = [first_btn, prev_btn]
        for item in _root_page_numbers(page_number, total_pages):
            if item == "...":
                page_controls.append(ft.Text("...", size=13, color=Q_MUTED))
                continue
            btn = primary_button(str(item), lambda e, n=item: go_to_root_page(n)) if item == page_number else secondary_button(str(item), lambda e, n=item: go_to_root_page(n))
            btn.width = 42
            page_controls.append(btn)
        page_controls.extend([next_btn, last_btn])

        return ft.Row(
            controls=[
                ft.Text(
                    f"Resultados: {total_rows} · Mostrando {start_num}-{end_num} · Marcadas: {selection_count}",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(controls=page_controls, spacing=4, wrap=True),
            ],
            spacing=12,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def build_root_toolbar():
        selection_count = len(state.get("selected_paths") or set())

        inspect_btn = primary_button("Inspeccionar marcada", inspect_marked_folder)
        inspect_btn.disabled = selection_count != 1

        watchdog_btn = secondary_button("Vigilancia Watchdog", watchdog_placeholder)
        watchdog_btn.disabled = True
        watchdog_btn.tooltip = "Pendiente de desarrollo en módulo independiente"

        return ft.Row(
            controls=[
                secondary_button("Marcar página", select_all_visible),
                secondary_button("Limpiar marcas", clear_selection),
                inspect_btn,
                primary_button("Tree marcadas TXT", export_checked_trees),
                secondary_button("Tree página TXT", export_visible_trees),
                watchdog_btn,
            ],
            spacing=8,
            wrap=True,
        )

    def build_root_folders_table():
        if state.get("loading_folders"):
            return ft.Column(
                controls=[
                    ft.ProgressBar(value=None, width=760),
                    ft.Text(state.get("loading_label") or "Cargando carpetas...", size=13, color=Q_MUTED),
                ],
                spacing=10,
            )

        # Aunque haya escaneo en curso, la tabla permanece visible y usable.

        if not state["root_loaded"]:
            return empty_state("Pulsa “Cargar” para mostrar carpetas raíz.")

        root_folders = state.get("root_rows") or []
        if not root_folders:
            return empty_state("No hay carpetas raíz para esa ruta o filtro.")

        headers = [
            {"key": "Sel.", "width": 60},
            {"key": "Nombre cliente", "width": 360},
            {"key": "Año", "width": 90},
            {"key": "Trámite / ruta documental", "width": 430},
            {"key": "Vinculación", "width": 260},
            {"key": "Arch. dir.", "width": 90},
            {"key": "Sub. dir.", "width": 90},
            {"key": "Arch. total", "width": 105},
            {"key": "Sub. total", "width": 105},
            {"key": "Última actividad", "width": 160},
            {"key": "Último escaneo", "width": 160},
            {"key": "Ruta técnica", "width": 320},
        ]

        rows_to_paint = _current_page_rows()

        rows = []
        selected_paths = state.get("selected_paths") or set()

        for index, folder in enumerate(rows_to_paint):
            route_label = folder.get("_route_label") or _document_route_label(folder)
            client_folder = folder.get("_client_folder") or _client_root_folder(folder)
            year = folder.get("_document_year") or _document_year(folder)
            case_label = folder.get("_case_label") or _document_case_label(folder)
            ruta = folder.get("ruta")
            checked = ruta in selected_paths
            row_ref = ft.Ref()
            checkbox_ref = ft.Ref()
            checkbox = ft.Checkbox(
                ref=checkbox_ref,
                value=checked,
                on_change=lambda e, path=ruta, rr=row_ref, cr=checkbox_ref, idx=index: toggle_selected(path, bool(e.control.value), rr, cr, idx),
            )

            rows.append([
                {
                    "selected": checked,
                    "row_ref": row_ref,
                    "on_click": lambda e, path=ruta, rr=row_ref, cr=checkbox_ref, idx=index: toggle_selected(path, None, rr, cr, idx),
                },
                checkbox,
                ft.Text(client_folder, weight=ft.FontWeight.BOLD, size=13),
                ft.Text(year, weight=ft.FontWeight.BOLD, size=13),
                ft.Text(case_label, weight=ft.FontWeight.BOLD, size=13),
                ft.Text(_box_link_label(folder), size=12, color=_box_link_color(folder), weight=ft.FontWeight.W_600),
                folder.get("total_archivos_directos") if folder.get("total_archivos_directos") is not None else (folder.get("total_archivos") or 0),
                folder.get("total_subcarpetas_directas") if folder.get("total_subcarpetas_directas") is not None else (folder.get("total_subcarpetas") or 0),
                folder.get("total_archivos_recursivos") if folder.get("total_archivos_recursivos") is not None else (folder.get("total_archivos") or 0),
                folder.get("total_subcarpetas_recursivas") if folder.get("total_subcarpetas_recursivas") is not None else (folder.get("total_subcarpetas") or 0),
                ft.Text(_datetime_label(folder.get("fecha_ultima_actividad")), weight=ft.FontWeight.BOLD, size=13),
                _datetime_label(folder.get("last_scan") or folder.get("ultimo_escaneo")),
                folder.get("ruta_relativa") or folder.get("ruta") or "",
            ])

        return ft.Column(
            controls=[
                root_toolbar_container,
                app_table(headers=headers, rows=rows, height=560),
                build_root_pagination(),
            ],
            spacing=10,
        )

    def build_dialog_summary():
        inspection = state.get("inspection") or {}
        folder = inspection.get("folder") or {}
        summary = inspection.get("summary") or {}
        fases = summary.get("fases") or {}
        documentos = summary.get("documentos") or {}

        fase_text = ", ".join([f"{k}: {v}" for k, v in list(fases.items())[:12]]) or "Sin fases detectadas"
        doc_text = ", ".join([f"{k}: {v}" for k, v in list(documentos.items())[:14]]) or "Sin documentos detectados"

        return ft.Column(
            controls=[
                ft.Text(folder.get("nombre_carpeta") or state.get("selected_folder_path") or "Carpeta seleccionada", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(folder.get("ruta") or state.get("selected_folder_path") or "—", size=12, color=Q_MUTED),
                ft.Row(
                    controls=[
                        metric_card("Subcarpetas", summary.get("total_subcarpetas", 0)),
                        metric_card("Archivos directos", summary.get("total_archivos", 0)),
                        metric_card("Tipo carpeta", folder.get("tipo_detectado") or "—"),
                        metric_card("Última actividad", _datetime_label(folder.get("fecha_ultima_actividad"))),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Text(
                    "Vinculación con expediente" if selected_folder_is_root_folder() else "Vinculación con expediente no disponible",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Row(
                    controls=[
                        link_expediente_dd,
                        primary_button("Vincular expediente", link_selected_folder_to_expediente),
                    ],
                    spacing=10,
                    wrap=True,
                    visible=selected_folder_is_root_folder(),
                ),
                ft.Text(
                    "Esta acción solo actualiza SQLite. No modifica Box." if selected_folder_is_root_folder() else "Las subcarpetas heredan la vinculación de la carpeta principal.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Text("Fases detectadas", size=13, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                ft.Text(fase_text, size=12, color=Q_MUTED),
                ft.Text("Tipos documentales detectados", size=13, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                ft.Text(doc_text, size=12, color=Q_MUTED),
            ],
            spacing=10,
        )

    def build_dialog_subfolders():
        inspection = state.get("inspection") or {}
        subfolders = inspection.get("subfolders") or []

        if not subfolders:
            return empty_state("Esta carpeta no tiene subcarpetas directas inventariadas.")

        headers = [
            {"key": "Subcarpeta", "width": 250},
            {"key": "Fase", "width": 140},
            {"key": "Arch. dir.", "width": 90},
            {"key": "Sub. dir.", "width": 85},
            {"key": "Arch. total", "width": 100},
            {"key": "Sub. total", "width": 95},
            {"key": "Última actividad", "width": 150},
            {"key": "Acción", "width": 150},
        ]

        rows = []
        for folder in subfolders:
            rows.append([
                folder.get("nombre_carpeta") or "—",
                folder.get("tipo_detectado") or "—",
                folder.get("total_archivos_directos") if folder.get("total_archivos_directos") is not None else (folder.get("total_archivos") or 0),
                folder.get("total_subcarpetas_directas") if folder.get("total_subcarpetas_directas") is not None else (folder.get("total_subcarpetas") or 0),
                folder.get("total_archivos_recursivos") if folder.get("total_archivos_recursivos") is not None else (folder.get("total_archivos") or 0),
                folder.get("total_subcarpetas_recursivas") if folder.get("total_subcarpetas_recursivas") is not None else (folder.get("total_subcarpetas") or 0),
                _datetime_label(folder.get("fecha_ultima_actividad")),
                secondary_button("Abrir", lambda e, path=folder.get("ruta"): inspect_folder(path, push_history=True)),
            ])

        return app_table(headers=headers, rows=rows, height=380)

    def build_dialog_files():
        inspection = state.get("inspection") or {}
        files = inspection.get("files") or []

        if not files:
            return empty_state("Esta carpeta no tiene archivos directos inventariados.")

        headers = [
            {"key": "Archivo", "width": 320},
            {"key": "Tipo", "width": 170},
            {"key": "Estado", "width": 140},
            {"key": "Ext.", "width": 70},
            {"key": "Tamaño", "width": 95},
            {"key": "Fecha modificación", "width": 155},
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

        return app_table(headers=headers, rows=rows, height=380)


    def build_dialog_documentacion():
        inspection = state.get("inspection") or {}
        folder = inspection.get("folder") or {}
        subfolders = inspection.get("subfolders") or []
        files = inspection.get("files") or []

        current_path = folder.get("ruta") or state.get("selected_folder_path") or "—"

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
                                    ft.Text(item.get("ruta") or item.get("ruta_relativa") or "", size=11, color=Q_MUTED, selectable=True),
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
            width=920,
            height=620,
            scroll=ft.ScrollMode.AUTO,
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
                        secondary_button("Volver atrás", go_back_inspection),
                        primary_button("Abrir carpeta Windows", open_selected_folder),
                        secondary_button("Exportar árbol TXT", export_selected_tree),
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

    def _inspection_nav_button(label, tab):
        is_active = state.get("dialog_tab") == tab
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

    def build_dialog_vinculacion():
        controls = [
            ft.Text(
                "Vinculación con expediente" if selected_folder_is_root_folder() else "Vinculación con expediente no disponible",
                size=16,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            ft.Text(
                "Solo se pueden vincular carpetas principales. Las subcarpetas heredan la vinculación de la carpeta principal.",
                size=12,
                color=Q_MUTED,
            ),
            ft.Row(
                controls=[
                    link_expediente_dd,
                    primary_button("Vincular expediente", link_selected_folder_to_expediente),
                ],
                spacing=10,
                wrap=True,
                visible=selected_folder_is_root_folder(),
            ),
            ft.Text(
                "Esta acción solo actualiza SQLite. No modifica Box.",
                size=12,
                color=Q_MUTED,
                visible=selected_folder_is_root_folder(),
            ),
        ]
        return ft.Column(controls=controls, spacing=12)

    def build_dialog_acciones():
        action_controls = []
        if state.get("inspection_stack"):
            action_controls.append(secondary_button("← Volver atrás", go_back_inspection))

        action_controls.extend([
            secondary_button("Abrir carpeta Windows", open_selected_folder),
            primary_button("Exportar árbol TXT", export_selected_tree),
            secondary_button("Cerrar", close_dialog),
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
        load_link_expediente_options()

        inspection = state.get("inspection") or {}
        folder = inspection.get("folder") or {}
        summary = inspection.get("summary") or {}

        current_path = folder.get("ruta") or state.get("selected_folder_path") or "—"
        current_name = folder.get("nombre_carpeta") or state.get("selected_folder_path") or "Carpeta seleccionada"

        tab = state.get("dialog_tab") or "Resumen"
        if tab == "Documentación":
            body = build_dialog_documentacion()
        elif tab == "Vinculación":
            body = build_dialog_vinculacion()
        elif tab == "Acciones":
            body = build_dialog_acciones()
        else:
            body = build_dialog_summary()

        menu_items = [
            ("Resumen", "Resumen"),
            ("Documentación", "Documentación"),
            ("Vinculación", "Vinculación"),
            ("Acciones", "Acciones"),
        ]

        inspection_dialog_content.content = ft.Row(
            controls=[
                ft.Container(
                    width=240,
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
                            secondary_button("Abrir carpeta", open_selected_folder),
                            secondary_button("Cerrar", close_dialog),
                        ],
                        spacing=8,
                    ),
                ),
                ft.Container(
                    expand=True,
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
                                ],
                                spacing=12,
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
                                expand=True,
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
        )


    def open_inspection_dialog():
        if not state.get("inspection"):
            notify_error("No hay carpeta inspeccionada.")
            safe_update()
            return

        refresh_inspection_dialog_content()
        inspection_dialog.open = True
        page.update()

    def set_box_screen(screen_name):
        state["box_screen"] = screen_name or "routes"
        save_cache()
        content_area.content = build_layout()
        safe_update()

    def build_box_screen_selector():
        active = state.get("box_screen") or "routes"

        routes_btn = (
            primary_button("Panel de rutas", lambda e: set_box_screen("routes"))
            if active == "routes"
            else secondary_button("Panel de rutas", lambda e: set_box_screen("routes"))
        )

        summary_btn = (
            primary_button("Estado escaneos", lambda e: set_box_screen("summary"))
            if active == "summary"
            else secondary_button("Estado escaneos", lambda e: set_box_screen("summary"))
        )

        table_btn = (
            primary_button("Tabla técnica", lambda e: set_box_screen("table"))
            if active == "table"
            else secondary_button("Tabla técnica", lambda e: set_box_screen("table"))
        )

        return ft.Row(
            controls=[
                routes_btn,
                summary_btn,
                table_btn,
            ],
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _route_status_map():
        return {
            "active": ("Activa", "#ECFDF3", "#027A48"),
            "normal": ("Normal", "#EAF6FF", Q_PRIMARY),
            "massive": ("Masiva", "#FFF7E6", Q_WARNING),
            "inactive": ("Inactiva", "#F1F5F9", Q_MUTED),
        }


    def _short_box_path(value, max_len=110):
        raw = str(value or "").replace("\\", "/").strip()
        if len(raw) <= max_len:
            return raw
        return "…" + raw[-max_len:]


    def open_route_table(route_id):
        route_dd.value = str(route_id)
        state["selected_route"] = str(route_id)
        state["box_screen"] = "table"
        save_cache()
        load_root_folders(show_loading=True, refresh_routes_before=False)

    def selected_scan_route_ids():
        raw_ids = state.get("selected_scan_route_ids") or []
        return {str(x) for x in raw_ids if str(x or "").strip()}

    def persist_scan_route_selection(selected_ids):
        state["selected_scan_route_ids"] = sorted({str(x) for x in selected_ids if str(x or "").strip()})
        save_cache()

    def toggle_route_scan_selection(route_id):
        selected = selected_scan_route_ids()
        route_id_str = str(route_id or "")
        if not route_id_str:
            return

        if route_id_str in selected:
            selected.remove(route_id_str)
        else:
            selected.add(route_id_str)

        persist_scan_route_selection(selected)
        content_area.content = build_layout()
        safe_update()

    def clear_route_scan_selection(e=None):
        persist_scan_route_selection(set())
        content_area.content = build_layout()
        safe_update()

    def select_only_route(route_id):
        persist_scan_route_selection({str(route_id)})
        content_area.content = build_layout()
        safe_update()

    def select_visible_routes(visible_routes):
        selected = selected_scan_route_ids()
        for route in visible_routes or []:
            rid = route.get("id")
            if rid is not None:
                selected.add(str(rid))
        persist_scan_route_selection(selected)
        content_area.content = build_layout()
        safe_update()

    def scan_selected_route_cards(e=None):
        route_ids = []
        for rid in sorted(selected_scan_route_ids(), key=lambda x: int(x) if str(x).isdigit() else 999999):
            try:
                route_ids.append(int(rid))
            except Exception:
                pass

        if not route_ids:
            notify_error("Selecciona al menos una ruta para escanear.")
            safe_update()
            return

        launch_external_scan_job(route_ids, f"{len(route_ids)} ruta(s) seleccionada(s)")

    def set_route_cards_page(page_number):
        try:
            page_number = int(page_number or 1)
        except Exception:
            page_number = 1

        total = len(state.get("routes") or [])
        page_size = max(1, int(state.get("route_page_size") or 10))
        pages = max(1, (total + page_size - 1) // page_size)
        state["route_page"] = max(1, min(page_number, pages))
        save_cache()
        content_area.content = build_layout()
        safe_update()

    def paginated_route_cards(routes):
        page_size = max(1, int(state.get("route_page_size") or 10))
        total = len(routes or [])
        pages = max(1, (total + page_size - 1) // page_size)
        page_number = max(1, min(int(state.get("route_page") or 1), pages))
        state["route_page"] = page_number

        offset = (page_number - 1) * page_size
        return list(routes or [])[offset: offset + page_size], page_number, page_size, total

    def build_route_bulk_bar(visible_routes):
        selected_count = len(selected_scan_route_ids())

        return bulk_action_bar(
            title="Rutas seleccionadas",
            selected_count=selected_count,
            on_clear=clear_route_scan_selection,
            actions=[
                {
                    "icon": ft.Icons.REFRESH,
                    "tooltip": "Refrescar rutas",
                    "on_click": lambda e: refresh_routes(),
                },
                {
                    "icon": ft.Icons.SYNC,
                    "tooltip": "Reescanear todas",
                    "on_click": scan_all,
                },
                {
                    "icon": ft.Icons.PLAY_ARROW,
                    "tooltip": "Escanear seleccionadas",
                    "on_click": scan_selected_route_cards,
                },
                {
                    "icon": ft.Icons.SELECT_ALL,
                    "tooltip": "Seleccionar página",
                    "on_click": lambda e, items=visible_routes: select_visible_routes(items),
                },
                {
                    "icon": ft.Icons.CLEAR_ALL,
                    "tooltip": "Limpiar selección",
                    "on_click": clear_route_scan_selection,
                },
            ],
        )

    def scan_route_from_card(route_id):
        route = next((r for r in state.get("routes", []) if str(r.get("id")) == str(route_id)), None)
        route_label = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}" if route else f"Ruta {route_id}"

        launch_external_scan_job([int(route_id)], route_label)

    def build_route_card(route):
        route_id = route.get("id")
        route_box = route.get("ruta_box") or route.get("ruta_relativa") or ""
        route_resolved = route.get("ruta_resuelta") or route.get("resolved_path") or ""
        tipo = route.get("tipo_expediente_nombre") or route.get("tipo") or "Ruta Box"

        route_text = _short_box_path(route_box or route_resolved)
        resolved_text = _short_box_path(route_resolved, max_len=120)
        route_id_str = str(route_id or "")
        is_selected_for_scan = route_id_str in selected_scan_route_ids()

        extra_lines = [
            f"ID: {route_id} · Tipo: {tipo}",
        ]

        if resolved_text and resolved_text != route_text:
            extra_lines.append(f"Ruta local: {resolved_text}")

        if route_id_str == str(state.get("selected_route") or ""):
            extra_lines.append("Vista técnica seleccionada actualmente")

        return document_file_card(
            name=tipo,
            path=route_text or "Ruta sin definir",
            relative_path=resolved_text if resolved_text != route_text else "",
            folder="Ruta Box configurada",
            size_label="",
            modified_at="",
            file_type="BOX",
            selected=is_selected_for_scan,
            selectable=True,
            checkbox_value=is_selected_for_scan,
            on_select=lambda e, rid=route_id: toggle_route_scan_selection(rid),
            extra_lines=extra_lines,
            action_groups=[
                {
                    "items": [
                        {"label": "Ver carpetas", "on_click": lambda e, rid=route_id: open_route_table(rid)},
                        {"label": "Escanear esta ruta", "on_click": lambda e, rid=route_id: scan_route_from_card(rid)},
                        {"label": "Seleccionar solo esta ruta", "on_click": lambda e, rid=route_id: select_only_route(rid)},
                        {"label": "Limpiar selección", "on_click": clear_route_scan_selection},
                    ]
                }
            ],
            compact=False,
        )

    def build_latest_job_panel():
        job = refresh_latest_scan_job()
        if not job:
            return ft.Container()

        estado = str(job.get("estado") or "-").upper()
        total_routes = int(job.get("total_routes") or 0)
        completed_routes = int(job.get("completed_routes") or 0)
        total_archivos = int(job.get("total_archivos") or 0)
        total_carpetas = int(job.get("total_carpetas") or 0)
        total_errores = int(job.get("total_errores") or 0)
        progress = float(job.get("progress_percent") or 0)
        label = job.get("progress_label") or "-"
        started_at = job.get("started_at")
        finished_at = job.get("finished_at")
        duration = _duration_label(started_at, finished_at)

        status_key = "normal"
        operative_message = "Último escaneo registrado."
        if estado == "RUNNING":
            status_key = "active"
            operative_message = (
                "Escaneo externo activo. Puedes seguir trabajando en el CRM; "
                "este panel se actualizará al refrescar o al finalizar el job."
            )
        elif estado == "DONE":
            status_key = "active"
            operative_message = "Último escaneo finalizado correctamente."
        elif estado in ("ERROR", "INTERRUPTED"):
            status_key = "inactive"
            operative_message = job.get("error") or "El último escaneo terminó con incidencia."

        progress_label = f"{progress:.1f}%"
        if estado == "DONE" and total_routes and completed_routes >= total_routes:
            progress_label = "100.0%"

        return ft.Container(
            padding=12,
            border_radius=12,
            border=ft.border.all(1, "#D0D5DD"),
            bgcolor="#FFFFFF",
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"Último job Box Watch #{job.get('id')}",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            status_chip(
                                status_key,
                                label=estado,
                                status_map=_route_status_map(),
                                compact=True,
                                bordered=True,
                            ),
                            secondary_button("Refrescar job", refresh_job_panel),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(operative_message, size=12, color=Q_PRIMARY_DARK),
                    ft.Text(label, size=12, color=Q_MUTED),
                    ft.Row(
                        controls=[
                            metric_card("Progreso", progress_label),
                            metric_card("Rutas", f"{completed_routes}/{total_routes}"),
                            metric_card("Archivos", total_archivos),
                            metric_card("Carpetas", total_carpetas),
                            metric_card("Errores", total_errores),
                            metric_card("Duración", duration),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(f"Inicio: {_short_datetime_label(started_at)}", size=12, color=Q_MUTED),
                            ft.Text(f"Fin: {_short_datetime_label(finished_at)}", size=12, color=Q_MUTED),
                            ft.Text(f"Scope: {job.get('scope') or '-'}", size=12, color=Q_MUTED),
                        ],
                        spacing=14,
                        wrap=True,
                    ),
                ],
                spacing=8,
            ),
        )

    def build_runtime_diagnostic_panel():
        try:
            diag = box_watch_job_service.get_box_watch_runtime_diagnostic()
        except Exception as exc:
            return ft.Container(
                padding=10,
                border_radius=12,
                border=ft.border.all(1, "#FDA29B"),
                bgcolor="#FFFFFF",
                content=ft.Text(
                    f"No se pudo cargar diagnóstico Box Watch: {exc}",
                    size=12,
                    color=Q_DANGER,
                ),
            )

        ok = bool(diag.get("ok"))
        status_key = "active" if ok else "inactive"
        message = (
            "Runtime estable: SQLite WAL activo, timeout correcto y sin residuos críticos."
            if ok
            else "Revisar runtime: puede haber timeout bajo, WAL desactivado, jobs RUNNING o scan_runs residuales."
        )

        return ft.Container(
            padding=10,
            border_radius=12,
            border=ft.border.all(1, "#D0D5DD"),
            bgcolor="#FFFFFF",
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Diagnóstico runtime Box Watch",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            status_chip(
                                status_key,
                                label="OK" if ok else "REVISAR",
                                status_map=_route_status_map(),
                                compact=True,
                                bordered=True,
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(message, size=12, color=Q_MUTED),
                    ft.Row(
                        controls=[
                            metric_card("SQLite", str(diag.get("journal_mode") or "-").upper()),
                            metric_card("Timeout", f"{diag.get('busy_timeout') or 0} ms"),
                            metric_card("Jobs RUNNING", diag.get("running_jobs") or 0),
                            metric_card("Runs EN CURSO", diag.get("running_scan_runs") or 0),
                            metric_card("Último job", diag.get("latest_job_id") or "—"),
                            metric_card("Estado", diag.get("latest_job_estado") or "—"),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=8,
            ),
        )

    def build_scan_status_screen():
        return ft.Column(
            controls=[
                info_card(
                    "2. Estado de escaneos Box Watch",
                    ft.Column(
                        controls=[
                            build_latest_job_panel(),
                            build_runtime_diagnostic_panel(),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=14,
            expand=True,
        )

    def build_routes_dashboard():
        routes = list(state.get("routes") or [])

        if not routes:
            return info_card(
                "2. Panel de rutas Box",
                ft.Column(
                    controls=[
                        empty_state("No hay rutas Box activas configuradas."),
                        ft.Text("Configura rutas Box desde Configuración para empezar a trabajar por cards.", size=12, color=Q_MUTED),
                    ],
                    spacing=8,
                ),
            )

        visible_routes, page_number, page_size, total_routes = paginated_route_cards(routes)

        header_controls = [
            ft.Row(
                controls=[
                    ft.Text("Rutas configuradas", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(
                        f"{len(selected_scan_route_ids())} seleccionada(s) · {total_routes} ruta(s) activas · {page_size} por página",
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
                spacing=10,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            build_route_bulk_bar(visible_routes),
        ]

        if state.get("scanning"):
            header_controls.append(
                ft.Text(
                    f"Escaneo en curso: {state.get('progress_route') or 'ruta seleccionada'}",
                    size=12,
                    color=Q_MUTED,
                )
            )

        pagination = compact_pagination_bar(
            page=page_number,
            page_size=page_size,
            total_items=total_routes,
            on_page_change=set_route_cards_page,
            label_prefix="Rutas",
        )

        cards_scroll = ft.Container(
            expand=True,
            content=ft.ListView(
                controls=[build_route_card(route) for route in visible_routes],
                spacing=10,
                padding=ft.padding.only(bottom=48),
                auto_scroll=False,
                expand=True,
            ),
        )

        return ft.Column(
            controls=[
                ft.Container(
                    padding=10,
                    border_radius=12,
                    border=ft.border.all(1, "#D0D5DD"),
                    bgcolor="#FFFFFF",
                    content=ft.Column(
                        controls=header_controls,
                        spacing=8,
                    ),
                ),
                pagination,
                cards_scroll,
            ],
            spacing=10,
            expand=True,
        )

    def build_table_screen():
        return ft.Column(
            controls=[
                build_route_controls(),
                info_card("3. Carpetas raíz detectadas", root_table_container),
            ],
            spacing=14,
        )

    def build_layout():
        active = state.get("box_screen") or "routes"
        if active == "routes":
            screen_content = build_routes_dashboard()
        elif active == "summary":
            screen_content = build_scan_status_screen()
        else:
            screen_content = build_table_screen()

        layout_controls = [
            header(),
            build_box_screen_selector(),
        ]

        # En el panel de rutas evitamos el resumen grande para que las cards queden arriba.
        # El resumen completo se mantiene en la tabla técnica.
        if active == "table":
            layout_controls.append(build_summary())

        layout_controls.append(screen_content)

        return ft.Container(
            bgcolor=Q_BG,
            padding=18,
            expand=True,
            content=ft.Column(
                controls=layout_controls,
                spacing=14,
                expand=True,
            ),
        )

    sync_progress_from_global()
    refresh_routes()
    root_toolbar_container.content = build_root_toolbar()
    root_table_container.content = build_root_folders_table()
    content_area.content = build_layout()
    return content_area

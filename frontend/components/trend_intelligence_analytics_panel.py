"""Read-only Trend Intelligence analytics; all data comes from the injected service."""
import asyncio

import flet as ft

from frontend.components.app_badge import status_badge
from frontend.components.app_button import secondary_button
from frontend.components.app_card import Q_MUTED, info_card, metric_card
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import Q_TEXT, app_table

NO_DATA = "Sin datos"

# Mirrors app_table's fixed header/row heights so the table only reserves the
# rows it shows; longer lists scroll inside the body.
HEADER_HEIGHT = 46
ROW_HEIGHT = 58
SCROLLBAR_ALLOWANCE = 14
MAX_VISIBLE_ROWS = 5

SNAPSHOT_HEADERS = [
    {"key": "Tema", "width": 180},
    {"key": "Estado", "width": 130},
    {"key": "Puntuación", "width": 110},
    {"key": "Velocidad", "width": 100},
    {"key": "Observaciones", "width": 130},
    {"key": "Fuentes", "width": 90},
    {"key": "Línea base", "width": 150},
    {"key": "Ventana", "width": 190},
    {"key": "País / Idioma", "width": 130},
]

EXPLANATION_HEADERS = [
    {"key": "Tema", "width": 180},
    {"key": "Fuentes contribuyentes", "width": 260},
    {"key": "Procedencia", "width": 260},
    {"key": "Cobertura parcial", "width": 150},
    {"key": "Historial", "width": 260},
]

STATUS_LABELS = {
    "READY": "Datos disponibles",
    "EMPTY": "Sin snapshots",
    "NO_DOMAIN": "Sin dominio configurado",
    "NO_STORE": "Sin base de datos",
    "SCHEMA_INCOMPLETE": "Esquema incompleto",
    "ERROR": "Error",
    "LOADING": "Cargando",
}

STATE_MESSAGES = {
    "EMPTY": "No hay snapshots de tendencias persistidos para este dominio.",
    "NO_STORE": "No existe la base de Trend Intelligence. No se crea desde esta vista.",
    "SCHEMA_INCOMPLETE": "El esquema de Trend Intelligence no está completo. No se migra desde esta vista.",
}

REASON_MESSAGES = {
    "NOT_CONFIGURED": "No hay un dominio seleccionado en la configuración del Collector.",
    "NOT_REGISTERED": "El dominio configurado no está registrado en Trend Intelligence.",
    "INVALID_SETTINGS": "La configuración guardada no es válida; no se pudo leer el dominio.",
    "READ_FAILED": "No se pudo leer la analítica de tendencias.",
}

EXPLANATION_LABELS = {
    "NOT_REQUESTED": "No solicitada",
    "FAILED": "No disponible",
}


def _text(value):
    return NO_DATA if value is None or value == "" else str(value)


def _number(value, pattern):
    return NO_DATA if value is None else format(value, pattern)


def _date(value):
    return NO_DATA if not value else value.replace("T", " ")[:19]


def _window(snapshot):
    return f"{_date(snapshot.window_start)} → {_date(snapshot.window_end)}"


def _scope(snapshot):
    return f"{_text(snapshot.country)} / {_text(snapshot.language)}"


def _topic(row):
    return row.topic.name if row.topic is not None else NO_DATA


def _baseline(row):
    if row.baseline_mean is None:
        return NO_DATA
    samples = "" if row.baseline_samples is None else f" ({row.baseline_samples} muestras)"
    return f"{row.baseline_mean:.2f}{samples}"


def _sources(explanation):
    return ", ".join(
        f"{item.source_code} [{item.health_state}]" for item in explanation.contributing_sources
    ) or NO_DATA


def _provenance(explanation):
    return ", ".join(
        f"{item.collector_key} {item.collector_version} · {item.provider}"
        for item in explanation.provenance
    ) or NO_DATA


def _history(explanation):
    return ", ".join(
        f"{_date(item.window_end)}: {item.score:.1f} {item.status}" for item in explanation.recurrence
    ) or NO_DATA


def _table_height(count):
    return HEADER_HEIGHT + ROW_HEIGHT * max(1, min(count, MAX_VISIBLE_ROWS)) + SCROLLBAR_ALLOWANCE


def _cell(value):
    # Two lines plus a tooltip so long values are never silently cut off.
    return ft.Text(value, size=13, color=Q_TEXT, max_lines=2,
                   overflow=ft.TextOverflow.ELLIPSIS, tooltip=value)


def _table(headers, rows):
    table = app_table(headers, [[_cell(value) for value in row] for row in rows],
                      height=_table_height(len(rows)))
    # The table is wider than the content area at 1280/1360 px; keep the
    # horizontal scrollbar visible so the rightmost columns stay reachable.
    table.content.scroll = ft.ScrollMode.ALWAYS
    return table


def _state_view(state):
    if state.status == "READY":
        return _ready_view(state)
    if state.status == "SCHEMA_INCOMPLETE":
        missing = ", ".join(state.missing_tables) or NO_DATA
        return empty_state(f"{STATE_MESSAGES['SCHEMA_INCOMPLETE']} Tablas ausentes: {missing}.")
    message = STATE_MESSAGES.get(state.status) or REASON_MESSAGES.get(state.reason)
    return empty_state(message or REASON_MESSAGES["READ_FAILED"])


def _ready_view(state):
    rows = state.rows
    explained = [row for row in rows if row.explanation is not None]
    metrics = ft.Row(
        controls=[
            metric_card("Snapshots mostrados", len(rows), subtitle="Último por tema y ámbito"),
            metric_card("Fuentes con cobertura parcial",
                        len(state.partial_sources) if explained else NO_DATA,
                        subtitle=", ".join(state.partial_sources) or "Según explicabilidad"),
        ],
        spacing=12,
        wrap=True,
    )
    snapshot_rows = [[
        _topic(row),
        _text(row.snapshot.status),
        _number(row.snapshot.score, ".1f"),
        _number(row.snapshot.velocity, "+.2f"),
        _text(row.snapshot.observation_count),
        _text(row.snapshot.source_count),
        _baseline(row),
        _window(row.snapshot),
        _scope(row.snapshot),
    ] for row in rows]
    explanation_rows = [[
        _topic(row),
        _sources(row.explanation) if row.explanation else EXPLANATION_LABELS[row.explanation_status],
        _provenance(row.explanation) if row.explanation else NO_DATA,
        (", ".join(row.explanation.partial_sources) or "Ninguna") if row.explanation else NO_DATA,
        _history(row.explanation) if row.explanation else NO_DATA,
    ] for row in rows if row.explanation_status != "NOT_REQUESTED"]
    return ft.Column(
        controls=[
            metrics,
            _table(SNAPSHOT_HEADERS, snapshot_rows),
            ft.Text("Explicabilidad y procedencia", size=13, weight=ft.FontWeight.BOLD),
            _table(EXPLANATION_HEADERS, explanation_rows)
            if explanation_rows else empty_state("Sin explicabilidad disponible."),
        ],
        spacing=12,
    )


def trend_intelligence_analytics_panel(page, service):
    badge = ft.Container(content=status_badge(STATUS_LABELS["LOADING"]))
    domain = ft.Text(f"Dominio: {NO_DATA}", size=13, color=Q_MUTED)
    body = ft.Column(controls=[ft.Text("Cargando analítica…", size=13, color=Q_MUTED)])

    async def load_analytics(event=None):
        try:
            state = await asyncio.to_thread(service.state)
        except Exception:
            state = None
        if state is None:
            badge.content = status_badge(STATUS_LABELS["ERROR"])
            body.controls = [empty_state(REASON_MESSAGES["READ_FAILED"])]
        else:
            badge.content = status_badge(STATUS_LABELS.get(state.status, state.status))
            domain.value = (f"Dominio: {state.domain_name} ({state.domain_code})" if state.domain_name
                            else f"Dominio: {_text(state.domain_code)}")
            body.controls = [_state_view(state)]
        page.update()

    header = ft.Row(
        controls=[
            ft.Row([domain, badge], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            secondary_button("Actualizar analítica", load_analytics),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    card = info_card("Analítica de tendencias", ft.Column(controls=[header, body], spacing=12))
    # Opening only schedules a read-only projection; it never runs the Collector.
    page.run_task(load_analytics)
    return card

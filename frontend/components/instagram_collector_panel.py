"""CRM content only; all data and execution go through the application service."""
import asyncio
import re

import flet as ft

from frontend.components.app_badge import status_badge
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_card import Q_MUTED, Q_PRIMARY_DARK, info_card, metric_card
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import app_table

Q_BG = "#F5F9FF"

STATUS_LABELS = {
    "IDLE": "Listo",
    "RUNNING": "En ejecución",
    "SUCCESS": "Completada",
    "DISABLED": "Deshabilitado",
    "NOT_CONFIGURED": "Sin configurar",
    "ERROR": "Error",
    "BLOCKED": "Bloqueado por Instagram",
    "CLEANUP_REQUIRED": "Cierre pendiente",
    "CLOSED": "Cerrado",
}

ERROR_LABELS = {
    "COLLECTION_FAILED": "La recogida no se completó",
    "INVALID_CONFIGURATION": "Configuración no válida",
    "OWNERSHIP_RETAINED": "El navegador no se liberó; reintente el cierre",
}


def _status(value):
    return STATUS_LABELS.get(value, value or "—")


def _error(code):
    return f"{ERROR_LABELS.get(code, code)} ({code})" if code else "Sin error registrado"


def _date(value):
    return (value or "—").replace("T", " ")[:19]


def instagram_collector_panel(page, service):
    enabled = ft.Switch(label="Habilitar Collector", value=False)
    accounts = ft.TextField(label="Cuentas públicas objetivo", hint_text="Una por línea, sin @",
                            multiline=True, min_lines=3, max_lines=6)
    limit = ft.TextField(label="Límite de publicaciones por cuenta", value="1", width=260,
                         keyboard_type=ft.KeyboardType.NUMBER)
    message = ft.Text("", size=13, color=Q_MUTED, selectable=True)
    badge = ft.Container()
    metrics = ft.Row(spacing=12, wrap=True)
    operational = ft.Column(spacing=8)
    results = ft.Column()
    history = ft.Column()
    loaded = False

    async def refresh(event=None):
        nonlocal loaded
        try:
            state = await asyncio.to_thread(service.state)
        except Exception:
            message.value = "No se pudo leer el estado del Collector. Revise la configuración existente."
            run.disabled = True
            page.update()
            return
        settings = state["settings"]
        if not loaded:
            enabled.value = settings.get("enabled", False) is True
            targets = [t for t in settings.get("accounts") or [] if isinstance(t, dict)]
            accounts.value = "\n".join(str(t.get("account", "")) for t in targets)
            limit.value = str(targets[0].get("limit", 1)) if targets else "1"
            loaded = True
        if state.get("problem"):
            message.value = "La configuración guardada no es válida. Revise fuente, dominio, perfil y cuentas registradas."
        run.disabled = state["busy"] or state["retained"] or state["effective"] != "IDLE"
        save.disabled = state["busy"] or state["retained"]
        cleanup.visible = state["retained"] and not state["busy"]
        badge.content = status_badge(_status(state["status"]))

        latest, runs = state["latest"], state["history"]
        report = latest["result"] if latest else None
        failed = sum(1 for r in runs if r["error"])
        metrics.controls = [
            metric_card("Última ejecución", _date(latest["date"]) if latest else "—",
                        subtitle=_status(latest["status"]) if latest else "Sin ejecuciones en esta sesión"),
            metric_card("Publicaciones creadas", report.created if report else "—",
                        subtitle="Última ejecución"),
            metric_card("Duplicados", report.duplicates if report else "—",
                        subtitle="Última ejecución"),
            metric_card("Errores", failed if runs else "—", subtitle="Ejecuciones con error en esta sesión"),
        ]

        operational.controls = [
            ft.Text(f"Estado del Collector: {_status(state['status'])}", size=13),
            ft.Text("Navegador SeleniumBase: "
                    + ("pendiente de liberar" if state["retained"]
                       else "en uso por la ejecución" if state["busy"]
                       else "cerrado (solo se abre al ejecutar)"), size=13),
            ft.Text(f"Perfil gobernado: {settings.get('profile_key') or 'Sin configurar'}", size=13),
            ft.Text(f"Ejecución en curso: {'Sí' if state['busy'] else 'No'}", size=13),
            ft.Text(f"Última ejecución: {_date(latest['date']) if latest else 'Sin ejecuciones'}", size=13),
        ]

        rows = [[
            _date(row.published_at or row.observed_at),
            row.author or "—",
            row.title or row.external_id or str(row.id),
            row.observation_type,
            "Persistida",
            ft.Text(row.url, size=13, selectable=True) if row.url else "—",
        ] for row in state["rows"]]
        results.controls = [
            app_table(["Fecha", "Cuenta", "Publicación", "Tipo", "Estado de ingestión",
                       {"key": "URL original", "width": 360}], rows, height=320)
            if rows else empty_state("Sin resultados de la última ejecución de esta sesión."),
        ]

        history_rows = [[
            _date(r["date"]),
            _status(r["status"]),
            ft.Text(r["id"], size=12, selectable=True),
            _error(r["error"]),
        ] for r in reversed(runs)]
        history.controls = [
            app_table(["Fecha", "Estado", {"key": "Referencia", "width": 300}, "Errores"],
                      history_rows, height=260)
            if history_rows else empty_state("Sin ejecuciones en esta sesión."),
            ft.Text("Evidencia disponible: publicaciones persistidas en Resultados y referencia "
                    "trazable de cada ejecución en el log del CRM.", size=12, color=Q_MUTED),
        ]
        page.update()

    async def execute(event):
        run.disabled = True
        page.update()
        try:
            future = await asyncio.to_thread(service.execute)
            await refresh()
            if future is not None:
                await asyncio.wrap_future(future)
        except Exception:
            message.value = "No se pudo completar la ejecución. Consulte el historial."
        await refresh()

    async def save_config(event):
        try:
            value = int(limit.value)
            await asyncio.to_thread(service.save, enabled.value is True,
                                    re.split(r"[\s,;]+", accounts.value or ""), value)
            message.value = "Configuración guardada. El límite indicado se aplica a todas las cuentas."
        except Exception:
            message.value = ("No se pudo guardar. Compruebe cuentas, límite y el registro previo "
                             "de fuente, dominio y perfil.")
        await refresh()

    async def release(event):
        try:
            future = await asyncio.to_thread(service.retry_cleanup)
            if future is not None:
                await asyncio.wrap_future(future)
        except Exception:
            message.value = "No se pudo liberar el navegador. Vuelva a intentarlo."
        await refresh()

    run = primary_button("Ejecutar recogida", execute)
    run.disabled = True
    save = primary_button("Guardar configuración", save_config)
    cleanup = secondary_button("Reintentar cierre", release)
    cleanup.visible = False

    header = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text("IT / Tendencias", size=30, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([ft.Text("Instagram Collector", size=14, color=Q_MUTED), badge], spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ],
                spacing=4,
                expand=True,
            ),
            ft.Row([secondary_button("Actualizar estado", refresh), cleanup, run], spacing=10, wrap=True),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    configuration = info_card("Configuración", ft.Column(
        controls=[
            enabled, accounts, limit,
            ft.Text("Usa la fuente, dominio y perfil ya registrados. Guardar no inicia el navegador.",
                    size=12, color=Q_MUTED),
            ft.Row([save]),
        ],
        spacing=12,
    ))

    content = ft.Column(
        controls=[
            header,
            message,
            metrics,
            ft.ResponsiveRow(
                controls=[
                    ft.Container(content=configuration, col={"xs": 12, "lg": 7}),
                    ft.Container(content=info_card("Estado operativo", operational), col={"xs": 12, "lg": 5}),
                ],
                spacing=14,
                run_spacing=14,
            ),
            info_card("Resultados", results),
            info_card("Historial / Log", history),
        ],
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    # Opening the view only schedules a state read; it never executes.
    page.run_task(refresh)
    return ft.Container(content=content, padding=20, bgcolor=Q_BG, expand=True)

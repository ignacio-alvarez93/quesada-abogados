from __future__ import annotations

import flet as ft

from backend.services import worker_service
from frontend.components import (
    empty_state,
    metric_card,
    primary_button,
)
from frontend.components.app_autocomplete import (
    AppAutocomplete,
)
from frontend.components.listing import (
    compact_pagination_bar,
)
from frontend.components.worker_card import worker_card


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"


STATUS_OPTIONS = [
    {"id": "ACTIVE", "label": "Activos"},
    {"id": "ALL", "label": "Todos"},
    {"id": "INACTIVE", "label": "Inactivos"},
    {
        "id": "TEMPORARY_LEAVE",
        "label": "Baja temporal",
    },
    {
        "id": "SICK_LEAVE",
        "label": "Baja médica",
    },
    {
        "id": "MATERNITY_PATERNITY",
        "label": "Nacimiento y cuidado",
    },
    {
        "id": "LEAVE_OF_ABSENCE",
        "label": "Excedencia",
    },
    {
        "id": "TERMINATED",
        "label": "Finalizados",
    },
]


def workers_view(page: ft.Page):
    worker_service.ensure_schema()

    state = {
        "workers": [],
        "page": 1,
        "page_size": 12,
        "search": "",
        "status": "ACTIVE",
        "department": "ALL",
    }

    root = ft.Container(
        expand=True,
        bgcolor="#FFFFFF",
    )

    results_box = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, -1),
    )

    metrics_box = ft.Row(
        controls=[],
        spacing=10,
        wrap=True,
    )

    status_ac = AppAutocomplete(
        page,
        "Estado laboral",
        options=STATUS_OPTIONS,
        value="Activos",
        width=220,
        max_results=8,
        allow_free_text=False,
    )

    department_ac = AppAutocomplete(
        page,
        "Departamento",
        options=[
            {
                "id": "ALL",
                "label": "Todos los departamentos",
            }
        ],
        value="Todos los departamentos",
        width=260,
        max_results=8,
        allow_free_text=False,
    )

    search_input = ft.TextField(
        label="Buscar trabajador",
        hint_text=(
            "Nombre, DNI/NIE, teléfono, "
            "puesto o departamento..."
        ),
        width=460,
        dense=True,
        prefix_icon=ft.Icons.SEARCH,
        border_radius=10,
    )

    def selected_id(
        autocomplete,
        fallback=None,
    ):
        selected = autocomplete.get_selected()

        if isinstance(selected, dict):
            return selected.get("id")

        return fallback

    def update_metrics():
        metrics = worker_service.worker_metrics()

        metrics_box.controls = [
            metric_card(
                "Total",
                metrics.get("total", 0),
            ),
            metric_card(
                "Activos",
                metrics.get("active", 0),
            ),
            metric_card(
                "Inactivos",
                metrics.get("inactive", 0),
            ),
            metric_card(
                "Departamentos",
                metrics.get("departments", 0),
            ),
        ]

    def update_department_options():
        options = [
            {
                "id": "ALL",
                "label": "Todos los departamentos",
            }
        ]

        options.extend(
            {
                "id": department,
                "label": department,
            }
            for department
            in worker_service.worker_departments()
        )

        department_ac.set_options(
            options,
            clear_value=False,
        )

    def load_workers():
        state["workers"] = (
            worker_service.list_workers(
                search=state["search"],
                status=state["status"],
                department=state["department"],
            )
        )

        update_metrics()
        update_department_options()
        render_results()

    def set_page(page_number):
        state["page"] = max(
            1,
            int(page_number or 1),
        )
        render_results()

    def show_detail(worker):
        pass

    def open_edit(worker):
        pass

    def toggle_active(worker):
        try:
            worker_service.set_worker_active(
                worker["id"],
                not bool(worker.get("active")),
            )
            load_workers()
            page.update()
        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(str(exc)),
                open=True,
            )
            page.update()

    def render_results():
        workers = list(
            state.get("workers") or []
        )

        total_items = len(workers)
        page_size = int(
            state.get("page_size") or 12
        )

        total_pages = max(
            1,
            (
                total_items
                + page_size
                - 1
            )
            // page_size,
        )

        current_page = max(
            1,
            min(
                int(state.get("page") or 1),
                total_pages,
            ),
        )

        state["page"] = current_page

        start = (
            current_page - 1
        ) * page_size

        visible = workers[
            start:start + page_size
        ]

        if not visible:
            results_box.content = ft.Container(
                expand=True,
                alignment=ft.Alignment(0, 0),
                content=empty_state(
                    "No hay trabajadores para los filtros seleccionados"
                ),
            )
            return

        cards = [
            worker_card(
                worker,
                on_open=show_detail,
                on_edit=open_edit,
                on_toggle_active=toggle_active,
            )
            for worker in visible
        ]

        results_box.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"{total_items} "
                                "trabajador(es)"
                            ),
                            size=12,
                            color=Q_MUTED,
                            expand=True,
                        ),
                        compact_pagination_bar(
                            current_page=current_page,
                            total_pages=total_pages,
                            on_page_change=set_page,
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.ListView(
                    controls=cards,
                    spacing=10,
                    expand=True,
                    padding=ft.padding.only(
                        right=4,
                        bottom=12,
                    ),
                ),
            ],
            spacing=12,
            expand=True,
        )

    def on_search_change(e=None):
        state["search"] = (
            search_input.value or ""
        ).strip()
        state["page"] = 1

        state["workers"] = (
            worker_service.list_workers(
                search=state["search"],
                status=state["status"],
                department=state["department"],
            )
        )

        render_results()

        try:
            results_box.update()
        except Exception:
            page.update()

    def on_status_selected(value=None):
        state["status"] = (
            selected_id(
                status_ac,
                "ACTIVE",
            )
            or "ACTIVE"
        )
        state["page"] = 1
        load_workers()
        page.update()

    def on_department_selected(value=None):
        state["department"] = (
            selected_id(
                department_ac,
                "ALL",
            )
            or "ALL"
        )
        state["page"] = 1
        load_workers()
        page.update()

    search_input.on_change = on_search_change
    status_ac.on_select = on_status_selected
    department_ac.on_select = (
        on_department_selected
    )

    root.content = ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(
                                "Trabajadores",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Directorio laboral, "
                                    "contratos y futura "
                                    "gestión de nóminas"
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    primary_button(
                        "Nuevo trabajador",
                        lambda e: None,
                    ),
                ],
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
            metrics_box,
            ft.Row(
                controls=[
                    search_input,
                    status_ac.control,
                    department_ac.control,
                ],
                spacing=10,
                wrap=True,
            ),
            ft.Divider(
                height=1,
                color=Q_BORDER,
            ),
            results_box,
        ],
        spacing=14,
        expand=True,
    )

    load_workers()

    return root

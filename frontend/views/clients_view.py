import flet as ft

from frontend.components import (
    app_table,
    empty_state,
    filter_bar,
    metric_card,
    primary_button,
    select_input,
    text_input,
)

CLIENT_STATES = [
    "Todos",
    "Asesoramiento inicial",
    "Pendiente de documentación",
    "Documentación entregada",
    "Expediente abierto",
    "En tramitación",
    "Archivado",
]


def clients_view(clients=None, on_new_client=None, on_search=None, on_filter=None):
    clients = clients or []

    header = ft.Column(
        controls=[
            ft.Text("Clientes", size=28, weight=ft.FontWeight.BOLD, color="#003B7A"),
            ft.Text("Gestión operativa de clientes del despacho", size=14, color="#64748B"),
        ],
        spacing=2,
    )

    filters = filter_bar(
        dropdown=select_input("Estado", CLIENT_STATES, value="Todos", width=240, on_change=on_filter),
        search_input=text_input("Buscar cliente", width=320),
        actions=[primary_button("Nuevo cliente", on_new_client)],
    )

    content = empty_state("No hay clientes registrados") if not clients else app_table(
        headers=["Nombre", "NIE/Pasaporte", "Nacionalidad", "Edad", "Teléfono", "Estado"],
        rows=clients,
    )

    return ft.Column(
        controls=[
            header,
            ft.Row(
                controls=[
                    metric_card("Clientes activos", len(clients)),
                    metric_card("Pendientes documentación", sum(1 for c in clients if "Pendiente" in str(c))),
                ],
                spacing=12,
            ),
            filters,
            content,
        ],
        spacing=18,
        expand=True,
    )

import flet as ft

# COMPONENTES
from frontend.components.app_button import (
    primary_button,
    secondary_button,
    danger_button,
    small_button,
)

from frontend.components.app_text_field import (
    text_input,
    required_text_input,
    multiline_input,
)

from frontend.components.app_dropdown import select_input
from frontend.components.app_table import app_table
from frontend.components.app_card import info_card, metric_card
from frontend.components.app_badge import status_badge
from frontend.components.app_filter_bar import filter_bar
from frontend.components.app_detail_section import detail_section
from frontend.components.app_empty_state import empty_state
from frontend.components.app_alert import (
    success_alert,
    error_alert,
    warning_alert,
)
from frontend.components.app_action_row import action_row
from frontend.components.app_loader import app_loader, app_progress_bar


def main(page: ft.Page):
    page.title = "Test UI - Quesada Abogados"
    page.scroll = "auto"
    page.padding = 20

    # -------- BOTONES --------
    buttons = ft.Row(
        controls=[
            primary_button("Guardar", lambda e: print("Guardar")),
            secondary_button("Cancelar", lambda e: print("Cancelar")),
            danger_button("Eliminar", lambda e: print("Eliminar")),
            small_button("Detalle", lambda e: print("Detalle")),
        ],
        spacing=10,
    )

    # -------- INPUTS --------
    inputs = ft.Column(
        controls=[
            text_input("Nombre"),
            required_text_input("NIE"),
            multiline_input("Observaciones", height=80),
        ],
        spacing=10,
    )

    # -------- DROPDOWN --------
    dropdown = select_input(
        label="Estado",
        options=[
            "Asesoramiento inicial",
            "Pendiente de documentación",
            "Expediente abierto",
            "En tramitación",
            "Archivado",
        ],
    )

    # -------- BADGES --------
    badges = ft.Row(
        controls=[
            status_badge("Asesoramiento inicial"),
            status_badge("Pendiente de documentación"),
            status_badge("Expediente abierto"),
            status_badge("En tramitación"),
            status_badge("Archivado"),
        ]
    )

    # -------- TABLA (100 REGISTROS) --------
    def generate_fake_clients(n=100):
        estados = [
            "Asesoramiento inicial",
            "Pendiente de documentación",
            "Expediente abierto",
            "En tramitación",
            "Archivado",
        ]

        data = []

        for i in range(1, n + 1):
            estado = estados[i % len(estados)]

            data.append([
                f"Cliente {i}",
                f"X{i:07d}A",
                f"600{i:06d}",
                status_badge(estado),
                action_row([
                    small_button("Ver", lambda e, i=i: print(f"Ver {i}")),
                    danger_button("Eliminar", lambda e, i=i: print(f"Eliminar {i}")),
                ]),
            ])

        return data

    table = app_table(
        headers=["Nombre", "NIE", "Teléfono", "Estado", "Acciones"],
        rows=generate_fake_clients(100),
    )

    # -------- CARDS --------
    cards = ft.Row(
        controls=[
            metric_card("Clientes", "125"),
            metric_card("Expedientes", "78"),
            info_card("Info", "Sistema funcionando correctamente"),
        ],
        spacing=20,
    )

    # -------- FILTRO --------
    filters = filter_bar(
        dropdown=select_input(
            "Estado",
            [
                "Todos",
                "En tramitación",
                "Archivado",
            ],
        ),
        search_input=text_input("Buscar cliente..."),
        actions=primary_button("Nuevo cliente", lambda e: print("Nuevo")),
    )

    # -------- DETALLE --------
    detail = detail_section(
        "Datos del cliente",
        [
            ("Nombre", "Juan Pérez"),
            ("NIE", "X1234567A"),
            ("Teléfono", "600123123"),
        ],
    )

    # -------- ALERTAS --------
    alerts = ft.Column(
        controls=[
            success_alert("Cliente creado correctamente"),
            error_alert("Error al guardar"),
            warning_alert("Faltan datos obligatorios"),
        ]
    )

    # -------- LOADERS --------
    loaders = ft.Column(
        controls=[
            app_loader("Cargando clientes..."),
            app_progress_bar(0.25, "Importando CSV..."),
            app_progress_bar(0.60, "Procesando expedientes..."),
            app_progress_bar(1.0, "Completado"),
        ],
        spacing=12,
    )

    # -------- EMPTY --------
    empty = empty_state("No hay clientes registrados")

    # -------- RENDER --------
    page.add(
        ft.Column(
            controls=[
                ft.Text("BOTONES", size=18, weight="bold"),
                buttons,

                ft.Divider(),

                ft.Text("INPUTS", size=18, weight="bold"),
                inputs,
                dropdown,

                ft.Divider(),

                ft.Text("BADGES", size=18, weight="bold"),
                badges,

                ft.Divider(),

                ft.Text("CARDS", size=18, weight="bold"),
                cards,

                ft.Divider(),

                ft.Text("FILTROS", size=18, weight="bold"),
                filters,

                ft.Divider(),

                ft.Text("TABLA", size=18, weight="bold"),
                table,

                ft.Divider(),

                ft.Text("DETALLE", size=18, weight="bold"),
                detail,

                ft.Divider(),

                ft.Text("ALERTAS", size=18, weight="bold"),
                alerts,

                ft.Divider(),

                ft.Text("LOADERS", size=18, weight="bold"),
                loaders,

                ft.Divider(),

                ft.Text("EMPTY STATE", size=18, weight="bold"),
                empty,
            ],
            spacing=20,
        )
    )


ft.run(main)
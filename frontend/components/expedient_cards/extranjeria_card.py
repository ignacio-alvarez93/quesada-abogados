import flet as ft

from frontend.components.expedient_status_badge import (
    expedient_status_badge,
    priority_badge,
)
from frontend.components.listing.card_item import card_item


def _meta_text(
    label,
    value,
    *,
    color,
    muted,
    width=None,
    selectable=False,
    weight=ft.FontWeight.W_600,
):
    return ft.Container(
        width=width,
        content=ft.Column(
            controls=[
                ft.Text(
                    label,
                    size=10,
                    color=muted,
                ),
                ft.Text(
                    str(value or "-"),
                    size=11,
                    weight=weight,
                    color=color,
                    selectable=selectable,
                ),
            ],
            spacing=2,
        ),
    )


def build_extranjeria_card(
    *,
    client_name,
    cliente_documento,
    familia_label,
    tipo_label,
    subtipo_label,
    show_subtipo,
    numero_expediente_extranjeria,
    fecha_presentacion_card,
    estado_administrativo_nombre,
    estado_administrativo_color,
    fecha_estado_administrativo_card,
    estado_documental_nombre,
    estado_documental_color,
    prioridad_nombre,
    prioridad_color,
    fecha_apertura_card,
    fecha_admision_tramite_card,
    fecha_resolucion_card,
    crm_number,
    box_label,
    box_color,
    id_presentacion,
    responsable,
    leading,
    popup,
    selected,
    on_click,
    primary,
    primary_dark,
    muted,
):
    """
    Card visual específico de la familia EXTRANJERIA.

    Contrato visual congelado:
    - cabecera especializada;
    - cronología administrativa;
    - estado documental / prioridad;
    - CRM / Box;
    - ID presentación / responsable.

    No contiene acceso a servicios ni persistencia.
    """

    title_controls = [
        ft.Text(
            client_name,
            size=15,
            weight=ft.FontWeight.BOLD,
            color=primary_dark,
        ),
        ft.Text(
            cliente_documento,
            size=13,
            weight=ft.FontWeight.BOLD,
            color=primary_dark,
            selectable=True,
        ),
        expedient_status_badge(
            familia_label,
            "#0057B8",
        ),
        ft.Container(
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=5,
            ),
            border_radius=10,
            bgcolor="#EFF6FF",
            content=ft.Text(
                tipo_label,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=primary_dark,
            ),
        ),
        (
            ft.Container(
                padding=ft.padding.symmetric(
                    horizontal=10,
                    vertical=5,
                ),
                border_radius=10,
                bgcolor="#F5F3FF",
                content=ft.Text(
                    subtipo_label,
                    size=11,
                    weight=ft.FontWeight.W_600,
                    color="#6D28D9",
                ),
            )
            if show_subtipo
            else None
        ),
        ft.Text(
            numero_expediente_extranjeria
            or "SIN Nº EXPEDIENTE",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=(
                primary_dark
                if numero_expediente_extranjeria
                else "#B42318"
            ),
            selectable=True,
        ),
        ft.Text(
            fecha_presentacion_card or "-",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=primary_dark,
        ),
        expedient_status_badge(
            estado_administrativo_nombre,
            estado_administrativo_color,
        ),
        ft.Text(
            fecha_estado_administrativo_card,
            size=12,
            weight=ft.FontWeight.BOLD,
            color=primary_dark,
        ),
    ]

    left_details = [
        ft.Row(
            controls=[
                ft.Text(
                    "Estado documental:",
                    size=10,
                    color=muted,
                ),
                expedient_status_badge(
                    estado_documental_nombre,
                    estado_documental_color,
                ),
                ft.Text(
                    "Prioridad:",
                    size=10,
                    color=muted,
                ),
                priority_badge(
                    prioridad_nombre,
                    prioridad_color,
                ),
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
        ft.Row(
            controls=[
                _meta_text(
                    "Apertura",
                    fecha_apertura_card,
                    color=primary_dark,
                    muted=muted,
                    width=105,
                    weight=ft.FontWeight.BOLD,
                ),
                _meta_text(
                    "Presentación",
                    fecha_presentacion_card,
                    color=primary_dark,
                    muted=muted,
                    width=115,
                    weight=ft.FontWeight.BOLD,
                ),
                _meta_text(
                    "Admisión a trámite",
                    fecha_admision_tramite_card,
                    color=primary_dark,
                    muted=muted,
                    width=145,
                    weight=ft.FontWeight.BOLD,
                ),
                _meta_text(
                    "Resolución",
                    fecha_resolucion_card,
                    color=primary_dark,
                    muted=muted,
                    width=110,
                    weight=ft.FontWeight.BOLD,
                ),
            ],
            spacing=16,
            wrap=True,
            vertical_alignment=(
                ft.CrossAxisAlignment.START
            ),
        ),
        ft.Row(
            controls=[
                ft.Text(
                    "CRM:",
                    size=10,
                    color=muted,
                ),
                ft.Text(
                    crm_number or "-",
                    size=11,
                    weight=ft.FontWeight.W_600,
                    color=primary,
                    selectable=True,
                ),
                ft.Icon(
                    ft.Icons.FOLDER_OPEN,
                    size=14,
                    color=box_color,
                ),
                ft.Text(
                    box_label,
                    size=10,
                    color=box_color,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=5,
            wrap=True,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
    ]

    metadata_controls = [
        _meta_text(
            "ID presentación",
            id_presentacion or "SIN ID",
            color=(
                primary_dark
                if id_presentacion
                else "#B42318"
            ),
            muted=muted,
            width=145,
            selectable=True,
        ),
        _meta_text(
            "Responsable",
            responsable or "-",
            color=primary_dark,
            muted=muted,
            width=100,
        ),
    ]

    return card_item(
        title=client_name,
        subtitle=(
            "Expediente interno · CRM: "
            + str(crm_number or "-")
        ),
        leading=leading,
        selected=selected,
        on_click=on_click,
        title_controls=title_controls,
        trailing=popup,
        body=[
            ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Column(
                            controls=left_details,
                            spacing=5,
                        ),
                    ),
                    ft.Row(
                        controls=metadata_controls,
                        spacing=18,
                        wrap=True,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.START
                        ),
                    ),
                ],
                spacing=22,
                wrap=True,
                vertical_alignment=(
                    ft.CrossAxisAlignment.START
                ),
            ),
        ],
        padding=16,
    )

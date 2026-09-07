"""Automatizaciones → Twins."""

from __future__ import annotations

import flet as ft

from backend.services.twin_management_service import (
    TwinManagementService,
)

from frontend.components.app_card import (
    info_card,
    metric_card,
)

from frontend.components.listing.status_chip import (
    status_chip,
)


Q_PRIMARY = "#003B7A"
Q_TEXT = "#172B4D"
Q_MUTED = "#66788A"
Q_BORDER = "#D7E0EA"


TWIN_STATUS_MAP = {
    "MATERIALIZED":
        (
            "Materializado",
            "#ECFDF3",
            "#027A48",
        ),

    "EMPTY":
        (
            "Sin revisión",
            "#FFF7E6",
            "#B54708",
        ),

    "PLANNED":
        (
            "Pendiente",
            "#F1F5F9",
            "#475569",
        ),

    "ERROR":
        (
            "Error",
            "#FEF3F2",
            "#B42318",
        ),
}


def _value(
    value,
):
    text = str(
        value
        or ""
    ).strip()

    return (
        text
        if text
        else "—"
    )


def _detail_row(
    label,
    value,
):
    return ft.Row(
        controls=[
            ft.Text(
                label,
                width=150,
                size=12,
                color=Q_MUTED,
            ),
            ft.Text(
                _value(
                    value
                ),
                size=12,
                color=Q_TEXT,
                selectable=True,
                expand=True,
            ),
        ],
        spacing=12,
        vertical_alignment=(
            ft.CrossAxisAlignment.START
        ),
    )


def _twin_card(
    item,
    *,
    page,
    service,
):
    status = item[
        "status"
    ]

    controls = [
        ft.Row(
            controls=[
                ft.Text(
                    item[
                        "site_code"
                    ],
                    size=11,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                    color=Q_MUTED,
                ),

                status_chip(
                    status,
                    label=(
                        item[
                            "status_label"
                        ]
                    ),
                    status_map=(
                        TWIN_STATUS_MAP
                    ),
                    bordered=True,
                ),
            ],
            alignment=(
                ft.MainAxisAlignment.SPACE_BETWEEN
            ),
        ),
    ]

    if status in {
        "MATERIALIZED",
        "EMPTY",
    }:
        procedure = (
            item.get(
                "procedure_code"
            )
            or "—"
        )

        variant = (
            item.get(
                "flow_variant"
            )
            or "—"
        )

        discovery_status = ft.Text(
            _value(
                item.get(
                    "discovery_status"
                )
            ),
            size=12,
            color=Q_TEXT,
        )

        discovery_qcc = ft.Text(
            (
                "Registrado"
                if item.get(
                    "discovery_qcc_registered"
                )
                else "No registrado"
            ),
            size=12,
            color=Q_TEXT,
        )

        discovery_start_button = (
            ft.ElevatedButton(
                "Iniciar Discovery",
                icon=ft.Icons.TRAVEL_EXPLORE,
                disabled=(
                    item.get(
                        "discovery_status"
                    )
                    == "RUNNING"
                ),
            )
        )

        discovery_stop_button = (
            ft.TextButton(
                "Detener Discovery",
                icon=ft.Icons.STOP,
                disabled=(
                    item.get(
                        "discovery_status"
                    )
                    != "RUNNING"
                ),
            )
        )

        def apply_discovery_state(
            runtime,
        ):
            running = (
                runtime.get(
                    "status"
                )
                == "RUNNING"
            )

            discovery_status.value = (
                runtime.get(
                    "status"
                )
                or "STOPPED"
            )

            discovery_qcc.value = (
                "Registrado"
                if runtime.get(
                    "qcc_registered"
                )
                else "No registrado"
            )

            discovery_start_button.disabled = (
                running
            )

            discovery_stop_button.disabled = (
                not running
            )

            page.update()

        def handle_start_discovery(
            _event,
        ):
            try:
                runtime = (
                    service.start_discovery(
                        item[
                            "twin_key"
                        ]
                    )
                )

                apply_discovery_state(
                    runtime
                )

            except Exception as exc:
                discovery_status.value = (
                    "ERROR"
                )

                discovery_qcc.value = str(
                    exc
                )

                page.update()

        def handle_stop_discovery(
            _event,
        ):
            try:
                runtime = (
                    service.stop_discovery(
                        item[
                            "twin_key"
                        ]
                    )
                )

                apply_discovery_state(
                    runtime
                )

            except Exception as exc:
                discovery_status.value = (
                    "ERROR"
                )

                discovery_qcc.value = str(
                    exc
                )

                page.update()

        discovery_start_button.on_click = (
            handle_start_discovery
        )

        discovery_stop_button.on_click = (
            handle_stop_discovery
        )

        twin_browser_status = ft.Text(
            _value(
                item.get(
                    "twin_browser_status"
                )
            ),
            size=12,
            color=Q_TEXT,
        )

        twin_browser_profile = ft.Text(
            _value(
                item.get(
                    "twin_browser_profile_key"
                )
            ),
            size=11,
            color=Q_MUTED,
            selectable=True,
        )

        twin_browser_qcc = ft.Text(
            (
                "Registrado"
                if item.get(
                    "twin_browser_qcc_registered"
                )
                else "No registrado"
            ),
            size=12,
            color=Q_TEXT,
        )

        open_button = ft.ElevatedButton(
            "Abrir Twin SeleniumBase",
            icon=ft.Icons.OPEN_IN_NEW,
            disabled=(
                status != "MATERIALIZED"
                or item.get(
                    "twin_browser_status"
                )
                == "RUNNING"
            ),
        )

        stop_button = ft.TextButton(
            "Detener Twin",
            icon=ft.Icons.STOP,
            disabled=(
                item.get(
                    "twin_browser_status"
                )
                != "RUNNING"
            ),
        )

        def apply_twin_browser_state(
            runtime,
        ):
            running = (
                runtime.get(
                    "status"
                )
                == "RUNNING"
            )

            twin_browser_status.value = (
                runtime.get(
                    "status"
                )
                or "STOPPED"
            )

            twin_browser_profile.value = (
                runtime.get(
                    "profile_key"
                )
                or "—"
            )

            twin_browser_qcc.value = (
                "Registrado"
                if runtime.get(
                    "qcc_registered"
                )
                else "No registrado"
            )

            open_button.disabled = (
                running
            )

            stop_button.disabled = (
                not running
            )

            page.update()

        def handle_open_twin(
            _event,
        ):
            try:
                runtime = (
                    service.start_twin_browser(
                        item[
                            "twin_key"
                        ]
                    )
                )

                apply_twin_browser_state(
                    runtime
                )

            except Exception as exc:
                twin_browser_status.value = (
                    "ERROR"
                )

                twin_browser_profile.value = str(
                    exc
                )

                page.update()

        def handle_stop_twin(
            _event,
        ):
            try:
                runtime = (
                    service.stop_twin_browser(
                        item[
                            "twin_key"
                        ]
                    )
                )

                apply_twin_browser_state(
                    runtime
                )

            except Exception as exc:
                twin_browser_status.value = (
                    "ERROR"
                )

                twin_browser_profile.value = str(
                    exc
                )

                page.update()

        if status != "MATERIALIZED":
            open_button.disabled = True
            stop_button.disabled = True

        open_button.on_click = (
            handle_open_twin
        )

        stop_button.on_click = (
            handle_stop_twin
        )

        seed_label = (
            (
                "Sin seed · Discovery desde cero"
            )
            if status == "EMPTY"
            else (
                procedure
                + (
                    " · "
                    + variant
                    if variant != "—"
                    else ""
                )
            )
        )

        controls.extend([
            ft.Divider(
                color=Q_BORDER
            ),

            _detail_row(
                "Revisión",
                item.get(
                    "revision_id"
                ),
            ),

            _detail_row(
                "Ámbito",
                "Sede completa",
            ),

            _detail_row(
                "Seed inicial",
                seed_label,
            ),

            _detail_row(
                "Estados conocidos",
                item.get(
                    "state_count"
                ),
            ),

            ft.Divider(
                color=Q_BORDER
            ),

            ft.Text(
                "Discovery",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=Q_TEXT,
            ),

            _detail_row(
                "Perfil",
                (
                    item.get(
                        "discovery_profile_key"
                    )
                    or "—"
                ),
            ),

            _detail_row(
                "Modo",
                "PERSISTENT",
            ),

            _detail_row(
                "Extensión QCC",
                (
                    "Manual · persistente"
                    if (
                        item.get(
                            "discovery_extension_mode"
                        )
                        == "MANUAL_PERSISTENT"
                    )
                    else "—"
                ),
            ),

            _detail_row(
                "Perfil físico",
                item.get(
                    "discovery_profile_dir"
                ),
            ),

            ft.Text(
                (
                    "Discovery cartografía la sede completa. "
                    "No existe procedimiento objetivo: navega "
                    "libremente por la sede y QCC observará "
                    "los estados visitados."
                ),
                size=11,
                color=Q_MUTED,
            ),


            ft.Row(
                controls=[
                    ft.Text(
                        "Estado",
                        width=150,
                        size=12,
                        color=Q_MUTED,
                    ),
                    discovery_status,
                ],
                spacing=12,
            ),

            ft.Row(
                controls=[
                    ft.Text(
                        "Registro QCC",
                        width=150,
                        size=12,
                        color=Q_MUTED,
                    ),
                    discovery_qcc,
                ],
                spacing=12,
            ),

            ft.Row(
                controls=[
                    discovery_start_button,
                    discovery_stop_button,
                ],
                spacing=8,
                wrap=True,
            ),

            ft.Text(
                (
                    "Primer uso: carga QCC manualmente en "
                    "chrome://extensions dentro de este perfil "
                    "y recarga esta sede. En los siguientes "
                    "arranques permanecerá instalada."
                ),
                size=11,
                color=Q_MUTED,
            ),

            ft.Text(
                "Twin SeleniumBase",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=Q_TEXT,
            ),

            ft.Row(
                controls=[
                    ft.Text(
                        "Estado",
                        width=150,
                        size=12,
                        color=Q_MUTED,
                    ),
                    twin_browser_status,
                ],
                spacing=12,
            ),

            ft.Row(
                controls=[
                    ft.Text(
                        "Perfil",
                        width=150,
                        size=12,
                        color=Q_MUTED,
                    ),
                    twin_browser_profile,
                ],
                spacing=12,
            ),

            _detail_row(
                "Modo",
                (
                    item.get(
                        "twin_browser_session_mode"
                    )
                    or "PERSISTENT"
                ),
            ),

            ft.Row(
                controls=[
                    ft.Text(
                        "Registro QCC",
                        width=150,
                        size=12,
                        color=Q_MUTED,
                    ),
                    twin_browser_qcc,
                ],
                spacing=12,
            ),

            _detail_row(
                "Runtime",
                item.get(
                    "runtime_index"
                ),
            ),

            ft.Row(
                controls=[
                    open_button,
                    stop_button,
                ],
                spacing=8,
                wrap=True,
            ),

            ft.Text(
                (
                    "Discovery cartografiará la sede completa "
                    "y añadirá automáticamente nuevos estados "
                    "y ramas. Un Twin EMPTY comienza desde cero "
                    "con la primera evidencia capturada."
                ),
                size=11,
                color=Q_MUTED,
            ),

            ft.Text(
                (
                    "El Twin se ejecuta exclusivamente en un "
                    "navegador SeleniumBase persistente gobernado. "
                    "El servidor local queda encapsulado por el "
                    "runtime y la sede REAL no se modifica."
                ),
                size=11,
                color=Q_MUTED,
            ),
        ])

    elif status == "ERROR":
        controls.extend([
            ft.Divider(
                color=Q_BORDER
            ),

            ft.Text(
                _value(
                    item.get(
                        "error"
                    )
                ),
                size=12,
                color="#B42318",
                selectable=True,
            ),
        ])

    else:
        controls.extend([
            ft.Divider(
                color=Q_BORDER
            ),

            ft.Text(
                (
                    "Twin preparado en el catálogo operativo. "
                    "Se activará cuando iniciemos la "
                    "cartografía de esta sede."
                ),
                size=12,
                color=Q_MUTED,
            ),
        ])

    return info_card(
        item[
            "label"
        ],
        ft.Column(
            controls=controls,
            spacing=9,
        ),
    )


def twins_view(
    page: ft.Page,
    service=None,
):
    """Dashboard provider-neutral de AUTO TWIN."""

    service = (
        service
        or TwinManagementService()
    )

    snapshot = (
        service.get_dashboard_snapshot()
    )

    summary = snapshot[
        "summary"
    ]

    twins = snapshot[
        "twins"
    ]

    cards = [
        _twin_card(
            item,
            page=page,
            service=service,
        )
        for item
        in twins
    ]

    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(
                                "Twins",
                                size=28,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY,
                            ),

                            ft.Text(
                                (
                                    "Centro de control de gemelos "
                                    "digitales de sedes electrónicas."
                                ),
                                size=13,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=3,
                    ),
                ],
                alignment=(
                    ft.MainAxisAlignment.SPACE_BETWEEN
                ),
            ),

            ft.Row(
                controls=[
                    metric_card(
                        "Twins",
                        summary[
                            "total_twins"
                        ],
                    ),

                    metric_card(
                        "Materializados",
                        summary[
                            "materialized_twins"
                        ],
                    ),

                    metric_card(
                        "Estados conocidos",
                        summary[
                            "known_states"
                        ],
                    ),

                    metric_card(
                        "Discovery",
                        summary[
                            "discovery_profile_key"
                        ],
                    ),
                ],
                spacing=12,
                wrap=True,
            ),

            ft.Text(
                "Sedes",
                size=18,
                weight=(
                    ft.FontWeight.BOLD
                ),
                color=Q_TEXT,
            ),

            ft.Column(
                controls=cards,
                spacing=12,
            ),
        ],
        spacing=18,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

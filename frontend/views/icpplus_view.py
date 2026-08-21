"""
Vista CRM para consultas de disponibilidad ICP Plus.

La vista:
- no conoce SeleniumBase;
- no conoce Win32;
- no conoce Observer;
- no contiene SQL;
- no reserva citas;
- no interactúa con CAPTCHA.

Toda ejecución pasa por IcpPlusAvailabilityService.
"""

import threading
from datetime import datetime

import flet as ft

from frontend.components.app_autocomplete import (
    AppAutocomplete,
)
from frontend.components.listing import (
    compact_pagination_bar,
)

from backend.services import (
    icpplus_profile_service,
    icpplus_scheduler_service,
    icpplus_state_service,
    icpplus_test_reservation_service,
)


Q_PRIMARY = "#003B7A"
Q_PRIMARY_2 = "#0057B8"
Q_BORDER = "#D9E2EC"
Q_BG = "#F6F8FB"
Q_TEXT = "#172B4D"
Q_MUTED = "#66788A"
Q_SUCCESS = "#147D64"
Q_WARNING = "#B26A00"
Q_ERROR = "#B42318"


def _safe_page_update(page):
    try:
        page.update()
    except Exception:
        # La vista puede haber sido desmontada
        # mientras terminaba una consulta.
        pass


def _status_color(value):
    value = str(
        value
        or ""
    ).upper()

    if value in {
        "ONLINE",
        "AVAILABLE",
    }:
        return Q_SUCCESS

    if value == "PENDING":
        return Q_PRIMARY_2

    if value in {
        "UNAVAILABLE",
        "DEGRADED",
        "UNKNOWN",
    }:
        return Q_WARNING

    return Q_ERROR


def _portal_label(value):
    value = str(
        value
        or ""
    ).upper()

    return {
        "ONLINE":
            "Portal operativo",
        "BLOCKED":
            "Portal bloqueado",
        "DEGRADED":
            "Portal degradado",
        "DOWN":
            "Portal no disponible",
        "UNKNOWN":
            "Estado desconocido",
        "PENDING":
            "Pendiente",
    }.get(
        value,
        value or "Estado desconocido",
    )


def _availability_label(value):
    value = str(
        value
        or ""
    ).upper()

    return {
        "AVAILABLE":
            "Citas disponibles",
        "UNAVAILABLE":
            "Sin citas",
        "UNKNOWN":
            "Disponibilidad desconocida",
        "PENDING":
            "Sin comprobar",
    }.get(
        value,
        value or "Disponibilidad desconocida",
    )


def _status_background(value):
    value = str(
        value
        or ""
    ).upper()

    if value in {
        "ONLINE",
        "AVAILABLE",
    }:
        return "#E8F7F0"

    if value == "PENDING":
        return "#EAF3FF"

    if value in {
        "UNAVAILABLE",
        "DEGRADED",
        "UNKNOWN",
    }:
        return "#FFF4E5"

    return "#FDECEC"


def _status_chip(
    value,
    label,
):
    return ft.Container(
        padding=ft.padding.symmetric(
            horizontal=9,
            vertical=4,
        ),
        bgcolor=_status_background(
            value
        ),
        border_radius=20,
        content=ft.Text(
            label,
            size=11,
            weight=ft.FontWeight.BOLD,
            color=_status_color(
                value
            ),
        ),
    )


def _status_box(
    label,
    value_control,
):
    return ft.Container(
        expand=True,
        padding=14,
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=10,
        content=ft.Column(
            [
                ft.Text(
                    label,
                    size=12,
                    color=Q_MUTED,
                ),
                value_control,
            ],
            spacing=5,
        ),
    )


def icpplus_view(
    page: ft.Page,
    *,
    service,
):
    profile = (
        icpplus_profile_service
        .get_profile()
    )

    flows = (
        service
        .list_supported_flows()
    )

    # ========================================================
    # PERFIL
    # ========================================================

    nombre = ft.TextField(
        label="Nombre",
        value=(
            profile.get(
                "icpplus_nombre"
            )
            or ""
        ),
        expand=True,
    )

    nacionalidad = ft.TextField(
        label="Nacionalidad",
        value=(
            profile.get(
                "icpplus_nacionalidad"
            )
            or ""
        ),
        expand=True,
    )

    nie = ft.TextField(
        label="NIE",
        value=(
            profile.get(
                "icpplus_nie"
            )
            or ""
        ),
        width=220,
    )

    telefono = ft.TextField(
        label="Teléfono",
        value=(
            profile.get(
                "icpplus_telefono"
            )
            or ""
        ),
        width=230,
    )

    email = ft.TextField(
        label="Email",
        value=(
            profile.get(
                "icpplus_email"
            )
            or ""
        ),
        expand=True,
    )


    # ========================================================
    # FLUJO
    # ========================================================

    provinces = {}

    for flow in flows:
        key = str(
            flow.get(
                "province_key"
            )
            or ""
        )

        if key:
            provinces[key] = (
                flow.get(
                    "province_text"
                )
                or key
            )


    # ========================================================
    # SELECTORES DE CONSULTA DEL BOT
    # ========================================================

    province_label_to_key = {
        str(label):
            str(key)
        for key, label
        in provinces.items()
    }

    province_key_to_label = {
        str(key):
            str(label)
        for key, label
        in provinces.items()
    }

    first_province_key = (
        str(
            flows[0].get(
                "province_key"
            )
            or ""
        )
        if flows
        else ""
    )

    first_province_label = (
        province_key_to_label.get(
            first_province_key,
            "",
        )
    )


    province_dd = AppAutocomplete(
        page=page,
        label="Provincia",
        options=list(
            province_label_to_key.keys()
        ),
        value=first_province_label,
        width=300,
        max_results=12,
        allow_free_text=False,
        icon=ft.Icons.MAP_OUTLINED,
    )


    procedure_dd = AppAutocomplete(
        page=page,
        label="Trámite",
        options=[],
        width=520,
        max_results=12,
        allow_free_text=False,
        icon=ft.Icons.DESCRIPTION_OUTLINED,
    )


    office_dd = AppAutocomplete(
        page=page,
        label="Oficina",
        options=[],
        width=820,
        max_results=12,
        allow_free_text=False,
        icon=ft.Icons.ACCOUNT_BALANCE_OUTLINED,
    )


    procedure_label_to_key = {}
    procedure_key_to_label = {}

    office_label_to_key = {}
    office_key_to_label = {}


    def selected_province_key():
        label = str(
            province_dd.input.value
            or ""
        ).strip()

        return str(
            province_label_to_key.get(
                label
            )
            or ""
        )


    def selected_procedure_key():
        label = str(
            procedure_dd.input.value
            or ""
        ).strip()

        return str(
            procedure_label_to_key.get(
                label
            )
            or ""
        )


    def selected_office_key():
        label = str(
            office_dd.input.value
            or ""
        ).strip()

        return str(
            office_label_to_key.get(
                label
            )
            or ""
        )


    def selected_office_label():
        return str(
            office_dd.input.value
            or ""
        ).strip()


    def refresh_procedures():
        province_key = (
            selected_province_key()
        )

        available = [
            flow
            for flow in flows
            if str(
                flow.get(
                    "province_key"
                )
                or ""
            )
            == province_key
        ]


        procedure_label_to_key.clear()
        procedure_key_to_label.clear()


        for flow in available:
            key = str(
                flow.get(
                    "procedure_key"
                )
                or ""
            )

            label = str(
                flow.get(
                    "procedure_text"
                )
                or key
            )

            if (
                key
                and label
            ):
                procedure_label_to_key[
                    label
                ] = key

                procedure_key_to_label[
                    key
                ] = label


        labels = list(
            procedure_label_to_key.keys()
        )

        procedure_dd.set_options(
            labels,
            clear_value=True,
        )

        if labels:
            procedure_dd.input.value = (
                labels[0]
            )


    def refresh_offices():
        province_key = (
            selected_province_key()
        )

        procedure_key = (
            selected_procedure_key()
        )


        office_label_to_key.clear()
        office_key_to_label.clear()


        if (
            not province_key
            or not procedure_key
        ):
            office_dd.set_options(
                [],
                clear_value=True,
            )

            return


        try:
            offices = (
                service.list_offices(
                    province_key,
                    procedure_key,
                )
            )

        except Exception:
            offices = []


        for item in offices:
            key = str(
                item.get(
                    "key"
                )
                or ""
            )

            label = str(
                item.get(
                    "provider_text"
                )
                or item.get(
                    "text"
                )
                or key
            )

            if (
                key
                and label
            ):
                office_label_to_key[
                    label
                ] = key

                office_key_to_label[
                    key
                ] = label


        labels = list(
            office_label_to_key.keys()
        )

        office_dd.set_options(
            labels,
            clear_value=True,
        )

        if labels:
            office_dd.input.value = (
                labels[0]
            )


    def on_province_change(
        value=None,
    ):
        refresh_procedures()
        refresh_offices()

        _safe_page_update(
            page
        )


    def on_procedure_change(
        value=None,
    ):
        refresh_offices()

        _safe_page_update(
            page
        )


    province_dd.on_select = (
        on_province_change
    )

    procedure_dd.on_select = (
        on_procedure_change
    )

    # AppAutocomplete conserva el callback utilizado al crear
    # el componente.
    province_dd.on_select = (
        on_province_change
    )

    procedure_dd.on_select = (
        on_procedure_change
    )

    province_dd.dropdown.on_select = (
        lambda e:
            on_province_change(
                getattr(
                    e,
                    "data",
                    None,
                )
            )
    )

    procedure_dd.dropdown.on_select = (
        lambda e:
            on_procedure_change(
                getattr(
                    e,
                    "data",
                    None,
                )
            )
    )


    refresh_procedures()
    refresh_offices()


    # ========================================================
    # RESULTADO
    # ========================================================

    portal_value = ft.Text(
        "—",
        size=18,
        weight=ft.FontWeight.BOLD,
    )

    availability_value = ft.Text(
        "—",
        size=18,
        weight=ft.FontWeight.BOLD,
    )

    result_message = ft.Text(
        "Configura los datos y ejecuta una comprobación.",
        color=Q_MUTED,
    )

    appointments_column = ft.Column(
        spacing=8,
    )

    persistent_cards_column = ft.ResponsiveRow(
        columns=12,
        spacing=12,
        run_spacing=12,
    )

    # ========================================================
    # DASHBOARD
    # ========================================================

    dashboard_portal_value = ft.Text(
        "—",
        size=22,
        weight=ft.FontWeight.BOLD,
        color=Q_TEXT,
    )

    dashboard_portal_subtitle = ft.Text(
        "Sin comprobaciones",
        size=11,
        color=Q_MUTED,
    )

    dashboard_last_check_value = ft.Text(
        "—",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=Q_TEXT,
    )

    dashboard_last_check_subtitle = ft.Text(
        "Sin actividad",
        size=11,
        color=Q_MUTED,
    )

    dashboard_appointments_value = ft.Text(
        "0",
        size=22,
        weight=ft.FontWeight.BOLD,
        color=Q_TEXT,
    )

    dashboard_appointments_subtitle = ft.Text(
        "Citas conocidas",
        size=11,
        color=Q_MUTED,
    )

    dashboard_provinces_value = ft.Text(
        "0",
        size=22,
        weight=ft.FontWeight.BOLD,
        color=Q_TEXT,
    )

    dashboard_provinces_subtitle = ft.Text(
        "Monitorizadas",
        size=11,
        color=Q_MUTED,
    )

    dashboard_test_reservation_value = ft.Text(
        "0",
        size=22,
        weight=ft.FontWeight.BOLD,
        color=Q_TEXT,
    )

    dashboard_test_reservation_subtitle = ft.Text(
        "Sin reserva activa",
        size=11,
        color=Q_MUTED,
    )

    all_attempts_chip_text = ft.Text(
        "Todos los intentos · 0",
        size=11,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_2,
    )

    all_attempts_chip = ft.Container(
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=5,
        ),
        bgcolor="#EAF3FF",
        border=ft.border.all(
            1,
            "#B9D5F5",
        ),
        border_radius=20,
        ink=True,
        content=all_attempts_chip_text,
        tooltip=(
            "Mostrar el historial principal "
            "de intentos ICP Plus"
        ),
    )


    test_reservation_chip_text = ft.Text(
        "Cita reservada · 0",
        size=11,
        weight=ft.FontWeight.BOLD,
        color=Q_MUTED,
    )

    test_reservation_chip = ft.Container(
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=5,
        ),
        bgcolor="#F5F7FA",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=20,
        ink=True,
        content=test_reservation_chip_text,
        tooltip=(
            "Mostrar la cita reservada "
            "con el perfil técnico de prueba"
        ),
    )


    scheduler_chip_text = ft.Text(
        "Vigilancias activas · 0",
        size=11,
        weight=ft.FontWeight.BOLD,
        color=Q_MUTED,
    )

    scheduler_chip = ft.Container(
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=5,
        ),
        bgcolor="#F5F7FA",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=20,
        ink=True,
        content=scheduler_chip_text,
        tooltip=(
            "Mostrar las vigilancias "
            "programadas de ICP Plus"
        ),
    )


    test_reservation_detail = ft.Column(
        spacing=6,
    )

    test_reservation_panel = ft.Container(
        visible=False,
        padding=16,
        bgcolor="#FFFFFF",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        content=ft.Column(
            [
                ft.Text(
                    "Cita reservada con datos de prueba",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=Q_TEXT,
                ),

                ft.Text(
                    "Esta cita NO pertenece a ningún cliente.",
                    size=12,
                    color=Q_ERROR,
                    weight=ft.FontWeight.BOLD,
                ),

                test_reservation_detail,
            ],
            spacing=8,
        ),
    )


    # ========================================================
    # TRES PANELES PRINCIPALES
    # ========================================================

    province_monitor_column = ft.Column(
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    appointment_history_column = ft.Column(
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    check_history_column = ft.Column(
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    province_monitor_count = ft.Text(
        "0 provincias",
        size=11,
        color=Q_MUTED,
    )

    appointment_history_count = ft.Text(
        "0 citas",
        size=11,
        color=Q_MUTED,
    )

    check_history_count = ft.Text(
        "0 comprobaciones",
        size=11,
        color=Q_MUTED,
    )

    appointment_history_header = ft.Row(
        [
            appointment_history_count,
            all_attempts_chip,
            test_reservation_chip,
            scheduler_chip,
        ],
        spacing=8,
        vertical_alignment=(
            ft.CrossAxisAlignment.CENTER
        ),
    )

    appointment_panel_mode = {
        "value":
            "history",
    }


    # ========================================================
    # FILTROS CORPORATIVOS + PAGINACIÓN DE PASADAS
    # ========================================================

    APPOINTMENT_HISTORY_PAGE_SIZE = 10

    appointment_history_page = {
        "value":
            1,
    }

    appointment_pagination_host = ft.Container(
        visible=False,
    )


    province_filter_labels = {
        "Todas":
            "TODAS",
    }

    for key, label in provinces.items():
        province_filter_labels[
            str(label)
        ] = str(
            key
        )


    status_filter_labels = {
        "Todos":
            "TODOS",

        "Con citas":
            "AVAILABLE",

        "Sin citas":
            "UNAVAILABLE",

        "Bloqueado":
            "BLOCKED",

        "Desconocido":
            "UNKNOWN",

        "Pendiente":
            "PENDING",
    }


    def _dashboard_province_filter_key():
        label = str(
            dashboard_province_filter
            .input
            .value
            or "Todas"
        ).strip()

        return (
            province_filter_labels.get(
                label
            )
            or "TODAS"
        )


    def _dashboard_status_filter_key():
        label = str(
            dashboard_status_filter
            .input
            .value
            or "Todos"
        ).strip()

        return (
            status_filter_labels.get(
                label
            )
            or "TODOS"
        )


    def on_dashboard_filter_selected(
        value=None,
    ):
        # Cambiar filtros devuelve el histórico a página 1.
        appointment_history_page[
            "value"
        ] = 1

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    dashboard_province_filter = AppAutocomplete(
        page=page,
        label="Provincia",
        options=list(
            province_filter_labels.keys()
        ),
        value="Todas",
        width=220,
        max_results=12,
        allow_free_text=False,
        on_select=(
            on_dashboard_filter_selected
        ),
    )


    dashboard_status_filter = AppAutocomplete(
        page=page,
        label="Estado",
        options=list(
            status_filter_labels.keys()
        ),
        value="Todos",
        width=220,
        max_results=8,
        allow_free_text=False,
        on_select=(
            on_dashboard_filter_selected
        ),
    )


    dashboard_search = ft.TextField(
        label="Buscar provincia / oficina",
        expand=True,
    )

    diagnostic_page = ft.Text(
        "—",
        size=13,
        color=Q_MUTED,
    )

    diagnostic_result_class = ft.Text(
        "—",
        size=13,
        color=Q_MUTED,
    )

    diagnostic_support_id = ft.Text(
        "—",
        size=13,
        color=Q_MUTED,
        selectable=True,
    )

    diagnostic_navigation_error = ft.Text(
        "—",
        size=13,
        color=Q_MUTED,
        selectable=True,
    )

    diagnostic_checked_at = ft.Text(
        "—",
        size=13,
        color=Q_MUTED,
    )

    progress = ft.ProgressRing(
        visible=False,
        width=20,
        height=20,
        stroke_width=2,
    )

    check_button = ft.ElevatedButton(
        "Lanzar comprobación",
        bgcolor=Q_PRIMARY_2,
        color="#FFFFFF",
    )

    save_button = ft.OutlinedButton(
        "Guardar perfil",
    )


    def current_profile():
        return {
            "icpplus_nombre":
                nombre.value,

            "icpplus_nacionalidad":
                nacionalidad.value,

            "icpplus_nie":
                nie.value,

            "icpplus_telefono":
                telefono.value,

            "icpplus_email":
                email.value,
        }


    def show_error(message):
        result_message.value = str(
            message
            or "Error"
        )

        result_message.color = (
            Q_ERROR
        )

        _safe_page_update(
            page
        )


    def save_current_profile(
        *,
        show_feedback=True,
    ):
        saved = (
            icpplus_profile_service
            .save_profile(
                current_profile()
            )
        )

        nombre.value = (
            saved[
                "icpplus_nombre"
            ]
        )

        nacionalidad.value = (
            saved[
                "icpplus_nacionalidad"
            ]
        )

        nie.value = (
            saved[
                "icpplus_nie"
            ]
        )

        telefono.value = (
            saved[
                "icpplus_telefono"
            ]
        )

        email.value = (
            saved[
                "icpplus_email"
            ]
        )

        if show_feedback:
            result_message.value = (
                "Perfil ICP Plus guardado."
            )

            result_message.color = (
                Q_SUCCESS
            )

        return saved


    def on_save_profile(e):
        try:
            save_current_profile()

        except Exception as exc:
            show_error(
                exc
            )

        _safe_page_update(
            page
        )


    save_button.on_click = (
        on_save_profile
    )


    def _format_iso_datetime(value):
        value = str(
            value
            or ""
        ).strip()

        if not value:
            return "—"

        try:
            parsed = (
                datetime.fromisoformat(
                    value
                )
            )

            return parsed.strftime(
                "%d/%m/%Y %H:%M:%S"
            )

        except Exception:
            return value


    def _appointment_controls(
        appointments,
        *,
        historical=False,
    ):
        controls = []

        for item in (
            appointments
            or []
        ):
            if isinstance(
                item,
                dict,
            ):
                date = str(
                    item.get(
                        "date"
                    )
                    or ""
                )

                time_value = str(
                    item.get(
                        "time"
                    )
                    or ""
                )

                value = (
                    f"{date} · {time_value}"
                    .strip(" ·")
                )

            else:
                value = str(
                    item
                )

            if historical:
                value = (
                    value
                    + " · última conocida"
                )

            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(
                        horizontal=10,
                        vertical=6,
                    ),
                    bgcolor=(
                        "#F5F7FA"
                        if historical
                        else "#EEF5FF"
                    ),
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=20,
                    content=ft.Text(
                        value,
                        size=11,
                        color=(
                            Q_MUTED
                            if historical
                            else Q_PRIMARY
                        ),
                        weight=ft.FontWeight.W_500,
                    ),
                )
            )

        return controls


    def build_persistent_card(card):
        card = dict(
            card
            or {}
        )

        current = dict(
            card.get(
                "current"
            )
            or {}
        )

        last_valid = dict(
            card.get(
                "last_valid"
            )
            or {}
        )

        portal_status = str(
            current.get(
                "portal_status"
            )
            or "UNKNOWN"
        ).upper()

        availability_status = str(
            current.get(
                "availability_status"
            )
            or "UNKNOWN"
        ).upper()

        current_appointments = list(
            current.get(
                "appointments"
            )
            or []
        )

        historical_appointments = list(
            card.get(
                "last_known_appointments"
            )
            or []
        )

        # Si la observación actual tiene citas, son la fuente
        # visual principal. Si no, mantenemos las últimas
        # conocidas marcándolas explícitamente como históricas.
        shown_appointments = (
            current_appointments
            if current_appointments
            else historical_appointments
        )

        historical = bool(
            not current_appointments
            and historical_appointments
        )

        pending = bool(
            card.get(
                "pending"
            )
        )

        province_label = (
            str(
                card.get(
                    "province_key"
                )
                or ""
            )
            .replace(
                "_",
                " ",
            )
            .title()
        )

        office_label = str(
            card.get(
                "office_text"
            )
            or card.get(
                "office_key"
            )
            or "ICP Plus"
        )

        card_title = (
            (
                province_label
                + " / "
                + office_label
            )
            if province_label
            else office_label
        )

        procedure_label = str(
            card.get(
                "procedure_text"
            )
            or ""
        ).strip()

        if not procedure_label:
            procedure_label = (
                str(
                    card.get(
                        "procedure_key"
                    )
                    or ""
                )
                .replace(
                    "_",
                    " ",
                )
                .title()
            )


        details = [
            ft.Text(
                "Trámite: "
                + (
                    procedure_label
                    or "—"
                ),
                size=12,
                color=Q_MUTED,
            ),

            ft.Row(
                [
                    ft.Text(
                        "Portal",
                        size=12,
                        color=Q_MUTED,
                    ),
                    _status_chip(
                        portal_status,
                        _portal_label(
                            portal_status
                        ),
                    ),
                    ft.Text(
                        "Disponibilidad",
                        size=12,
                        color=Q_MUTED,
                    ),
                    _status_chip(
                        availability_status,
                        _availability_label(
                            availability_status
                        ),
                    ),
                ],
                spacing=12,
                wrap=True,
            ),

            ft.Text(
                "Última comprobación: "
                + _format_iso_datetime(
                    current.get(
                        "checked_at"
                    )
                ),
                size=12,
                color=Q_MUTED,
            ),
        ]

        if (
            portal_status != "ONLINE"
            and last_valid
        ):
            details.append(
                ft.Text(
                    "Último resultado válido: "
                    + str(
                        last_valid.get(
                            "availability_status"
                        )
                        or "UNKNOWN"
                    )
                    + " · "
                    + _format_iso_datetime(
                        last_valid.get(
                            "checked_at"
                        )
                    ),
                    size=12,
                    color=Q_MUTED,
                )
            )

        support_id = (
            current.get(
                "support_id"
            )
        )

        if support_id:
            details.append(
                ft.Text(
                    "Support ID: "
                    + str(
                        support_id
                    ),
                    size=12,
                    color=Q_MUTED,
                    selectable=True,
                )
            )

        if pending:
            details.append(
                ft.Container(
                    margin=ft.margin.only(
                        top=4,
                    ),
                    padding=10,
                    bgcolor="#F7FAFE",
                    border_radius=8,
                    content=ft.Text(
                        (
                            "Pendiente de primera comprobación. "
                            "Todavía no existe un resultado "
                            "guardado para esta oficina."
                        ),
                        size=11,
                        color=Q_MUTED,
                    ),
                )
            )

        if shown_appointments:
            details.append(
                ft.Divider()
            )

            details.append(
                ft.Text(
                    (
                        "Últimas citas conocidas"
                        if historical
                        else "Citas observadas"
                    ),
                    size=13,
                    weight=ft.FontWeight.BOLD,
                )
            )

            details.append(
                ft.Row(
                    controls=_appointment_controls(
                        shown_appointments,
                        historical=historical,
                    ),
                    spacing=8,
                    run_spacing=8,
                    wrap=True,
                )
            )

        return ft.Container(
            col={
                "sm": 12,
                "lg": 6,
            },
            padding=16,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text(
                        card_title,
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_TEXT,
                    ),

                    *details,
                ],
                spacing=8,
            ),
        )


    def refresh_test_reservation():
        active = (
            icpplus_test_reservation_service
            .get_active_reservation()
        )

        test_reservation_detail.controls.clear()

        if not active:
            dashboard_test_reservation_value.value = "0"

            dashboard_test_reservation_subtitle.value = (
                "Sin reserva activa"
            )

            test_reservation_chip_text.value = (
                "Cita reservada · 0"
            )

            test_reservation_chip_text.color = (
                Q_MUTED
            )

            test_reservation_chip.bgcolor = (
                "#F5F7FA"
            )

            dashboard_test_reservation_value.color = (
                Q_TEXT
            )

            test_reservation_panel.visible = False

            return

        dashboard_test_reservation_value.value = "1"

        dashboard_test_reservation_value.color = (
            Q_WARNING
        )

        test_reservation_chip_text.value = (
            "Cita reservada · 1"
        )

        test_reservation_chip_text.color = (
            Q_WARNING
        )

        test_reservation_chip.bgcolor = (
            "#FFF4E5"
        )

        location = str(
            active.get(
                "office_text"
            )
            or active.get(
                "office_key"
            )
            or ""
        )

        appointment = (
            str(
                active.get(
                    "appointment_date"
                )
                or ""
            )
            + " · "
            + str(
                active.get(
                    "appointment_time"
                )
                or ""
            )
        ).strip(" ·")

        dashboard_test_reservation_subtitle.value = (
            appointment
            or "Reserva activa"
        )

        test_reservation_detail.controls.extend(
            [
                ft.Text(
                    "Provincia: "
                    + str(
                        active.get(
                            "province_key"
                        )
                        or "—"
                    ),
                    size=12,
                    color=Q_MUTED,
                ),

                ft.Text(
                    "Oficina: "
                    + (
                        location
                        or "—"
                    ),
                    size=12,
                    color=Q_MUTED,
                ),

                ft.Text(
                    "Trámite: "
                    + str(
                        active.get(
                            "procedure_key"
                        )
                        or "—"
                    ),
                    size=12,
                    color=Q_MUTED,
                ),

                ft.Text(
                    "Fecha / hora: "
                    + (
                        appointment
                        or "—"
                    ),
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_TEXT,
                ),

                ft.Text(
                    "La futura cancelación deberá "
                    "realizarse en ICP Plus antes de "
                    "liberar este estado.",
                    size=11,
                    color=Q_MUTED,
                ),
            ]
        )

        test_reservation_panel.visible = True


    def refresh_dashboard_metrics(
        cards,
    ):
        cards = list(
            cards
            or []
        )

        latest_card = None
        latest_checked_at = ""

        provinces_seen = set()
        known_appointments = 0

        for card in cards:
            province_key = str(
                card.get(
                    "province_key"
                )
                or ""
            )

            if province_key:
                provinces_seen.add(
                    province_key
                )

            current = dict(
                card.get(
                    "current"
                )
                or {}
            )

            current_appointments = list(
                current.get(
                    "appointments"
                )
                or []
            )

            historical = list(
                card.get(
                    "last_known_appointments"
                )
                or []
            )

            known_appointments += len(
                current_appointments
                if current_appointments
                else historical
            )

            checked_at = str(
                current.get(
                    "checked_at"
                )
                or ""
            )

            if (
                checked_at
                and checked_at
                > latest_checked_at
            ):
                latest_checked_at = (
                    checked_at
                )

                latest_card = card

        dashboard_provinces_value.value = str(
            len(
                provinces_seen
            )
        )

        dashboard_appointments_value.value = str(
            known_appointments
        )

        if latest_card:
            current = dict(
                latest_card.get(
                    "current"
                )
                or {}
            )

            portal_status = str(
                current.get(
                    "portal_status"
                )
                or "UNKNOWN"
            ).upper()

            dashboard_portal_value.value = (
                _portal_label(
                    portal_status
                )
            )

            dashboard_portal_value.color = (
                _status_color(
                    portal_status
                )
            )

            dashboard_portal_subtitle.value = (
                "Último estado observado"
            )

            dashboard_last_check_value.value = (
                _format_iso_datetime(
                    current.get(
                        "checked_at"
                    )
                )
            )

            dashboard_last_check_subtitle.value = (
                str(
                    latest_card.get(
                        "office_text"
                    )
                    or latest_card.get(
                        "office_key"
                    )
                    or ""
                )
            )

        else:
            dashboard_portal_value.value = "—"
            dashboard_portal_value.color = Q_TEXT
            dashboard_portal_subtitle.value = (
                "Sin comprobaciones"
            )

            dashboard_last_check_value.value = "—"
            dashboard_last_check_subtitle.value = (
                "Sin actividad"
            )

        refresh_test_reservation()


    def build_dashboard_cards(
        persisted_cards,
    ):
        """
        El dashboard debe mostrar TODO el catálogo configurado,
        no únicamente las oficinas ya consultadas.

        Una oficina todavía no observada se representa como
        PENDING. No se inventa disponibilidad ni citas.
        """

        persisted_cards = list(
            persisted_cards
            or []
        )

        persisted_by_key = {}

        for card in persisted_cards:
            logical_key = (
                str(
                    card.get(
                        "province_key"
                    )
                    or ""
                ),
                str(
                    card.get(
                        "procedure_key"
                    )
                    or ""
                ),
                str(
                    card.get(
                        "office_key"
                    )
                    or ""
                ),
            )

            persisted_by_key[
                logical_key
            ] = card


        dashboard_cards = []
        seen = set()


        for flow in flows:
            province_key = str(
                flow.get(
                    "province_key"
                )
                or ""
            )

            procedure_key = str(
                flow.get(
                    "procedure_key"
                )
                or ""
            )

            province_text = str(
                flow.get(
                    "province_text"
                )
                or province_key
            )

            procedure_text = str(
                flow.get(
                    "procedure_text"
                )
                or procedure_key
            )

            if (
                not province_key
                or not procedure_key
            ):
                continue


            try:
                offices = (
                    service.list_offices(
                        province_key,
                        procedure_key,
                    )
                )

            except Exception:
                offices = []


            for office in offices:
                office_key = str(
                    office.get(
                        "key"
                    )
                    or ""
                )

                if not office_key:
                    continue

                logical_key = (
                    province_key,
                    procedure_key,
                    office_key,
                )

                seen.add(
                    logical_key
                )

                existing = (
                    persisted_by_key.get(
                        logical_key
                    )
                )

                if existing:
                    card = dict(
                        existing
                    )

                    card[
                        "pending"
                    ] = False

                    card.setdefault(
                        "province_text",
                        province_text,
                    )

                    card.setdefault(
                        "procedure_text",
                        procedure_text,
                    )

                    dashboard_cards.append(
                        card
                    )

                    continue


                office_text = str(
                    office.get(
                        "provider_text"
                    )
                    or office.get(
                        "text"
                    )
                    or office_key
                )


                dashboard_cards.append(
                    {
                        "key":
                            (
                                "ICP_PLUS|"
                                + province_key
                                + ":"
                                + procedure_key
                                + "|"
                                + office_key
                            ),

                        "provider":
                            "ICP_PLUS",

                        "province_key":
                            province_key,

                        "province_text":
                            province_text,

                        "procedure_key":
                            procedure_key,

                        "procedure_text":
                            procedure_text,

                        "office_key":
                            office_key,

                        "office_text":
                            office_text,

                        "pending":
                            True,

                        "current": {
                            "checked_at":
                                None,

                            "page":
                                None,

                            "portal_status":
                                "PENDING",

                            "availability_status":
                                "PENDING",

                            "result_class":
                                "PENDING",

                            "support_id":
                                None,

                            "navigation_error":
                                None,

                            "appointments":
                                [],

                            "appointment_count":
                                0,
                        },

                        "last_valid":
                            None,

                        "last_known_appointments":
                            [],
                    }
                )


        # Compatibilidad con resultados persistidos de una
        # configuración que ya no exista en el catálogo actual.
        for card in persisted_cards:
            logical_key = (
                str(
                    card.get(
                        "province_key"
                    )
                    or ""
                ),
                str(
                    card.get(
                        "procedure_key"
                    )
                    or ""
                ),
                str(
                    card.get(
                        "office_key"
                    )
                    or ""
                ),
            )

            if logical_key in seen:
                continue

            preserved = dict(
                card
            )

            preserved[
                "pending"
            ] = False

            dashboard_cards.append(
                preserved
            )


        return dashboard_cards


    def _province_display(
        card,
    ):
        key = str(
            card.get(
                "province_key"
            )
            or ""
        )

        return str(
            card.get(
                "province_text"
            )
            or provinces.get(
                key
            )
            or key
            or "Provincia"
        )


    def _appointment_datetime_key(
        item,
    ):
        date_value = str(
            item.get(
                "date"
            )
            or ""
        )

        time_value = str(
            item.get(
                "time"
            )
            or ""
        )

        try:
            return datetime.strptime(
                (
                    date_value
                    + " "
                    + time_value
                ).strip(),
                "%d/%m/%Y %H:%M",
            )

        except Exception:
            return datetime.max


    def refresh_province_monitor(
        cards,
    ):
        province_monitor_column.controls.clear()

        grouped = {}

        for card in (
            cards
            or []
        ):
            key = str(
                card.get(
                    "province_key"
                )
                or ""
            )

            if not key:
                continue

            grouped.setdefault(
                key,
                []
            ).append(
                card
            )


        province_monitor_count.value = (
            f"{len(grouped)} provincia(s)"
        )


        for province_key in sorted(
            grouped,
            key=lambda key: str(
                provinces.get(
                    key
                )
                or key
            ),
        ):
            province_cards = (
                grouped[
                    province_key
                ]
            )

            available_offices = 0
            blocked_offices = 0
            pending_offices = 0
            known_appointments = 0
            latest_checked = ""

            for card in province_cards:
                current = dict(
                    card.get(
                        "current"
                    )
                    or {}
                )

                portal_status = str(
                    current.get(
                        "portal_status"
                    )
                    or "UNKNOWN"
                ).upper()

                availability_status = str(
                    current.get(
                        "availability_status"
                    )
                    or "UNKNOWN"
                ).upper()

                if (
                    availability_status
                    == "AVAILABLE"
                ):
                    available_offices += 1

                if (
                    portal_status
                    == "BLOCKED"
                ):
                    blocked_offices += 1

                if card.get(
                    "pending"
                ):
                    pending_offices += 1

                current_appts = list(
                    current.get(
                        "appointments"
                    )
                    or []
                )

                known_appts = list(
                    card.get(
                        "last_known_appointments"
                    )
                    or []
                )

                known_appointments += len(
                    current_appts
                    if current_appts
                    else known_appts
                )

                checked = str(
                    current.get(
                        "checked_at"
                    )
                    or ""
                )

                if checked > latest_checked:
                    latest_checked = checked


            if available_offices:
                status_value = "AVAILABLE"
                status_text = (
                    "Citas disponibles"
                )

            elif blocked_offices:
                status_value = "BLOCKED"
                status_text = (
                    "Bloqueo detectado"
                )

            elif (
                pending_offices
                == len(
                    province_cards
                )
            ):
                status_value = "PENDING"
                status_text = "Pendiente"

            else:
                status_value = "UNAVAILABLE"
                status_text = "Sin citas"


            province_text = str(
                provinces.get(
                    province_key
                )
                or province_key
            )


            def select_province(
                e,
                key=province_key,
            ):
                dashboard_province_filter.input.value = (
                    str(
                        provinces.get(
                            key
                        )
                        or key
                    )
                )

                appointment_history_page[
                    "value"
                ] = 1

                refresh_persistent_cards()

                _safe_page_update(
                    page
                )


            province_monitor_column.controls.append(
                ft.Container(
                    padding=12,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=10,
                    ink=True,
                    on_click=select_province,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        province_text,
                                        size=13,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY,
                                        expand=True,
                                    ),

                                    _status_chip(
                                        status_value,
                                        status_text,
                                    ),
                                ],
                                spacing=6,
                            ),

                            ft.Text(
                                (
                                    f"Oficinas: "
                                    f"{len(province_cards)}"
                                    f" · Citas: "
                                    f"{known_appointments}"
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),

                            ft.Text(
                                (
                                    "Último válido: "
                                    + (
                                        _format_iso_datetime(
                                            latest_checked
                                        )
                                        if latest_checked
                                        else "Sin comprobar"
                                    )
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            )


    def _appointment_run_card(
        run,
        *,
        fallback=False,
    ):
        appointments = list(
            run.get(
                "appointments"
            )
            or []
        )

        province_key = str(
            run.get(
                "province_key"
            )
            or ""
        )

        province_text = str(
            provinces.get(
                province_key
            )
            or run.get(
                "province_text"
            )
            or province_key
            or "Provincia"
        )

        office_text = str(
            run.get(
                "office_text"
            )
            or run.get(
                "office_key"
            )
            or "ICP Plus"
        )

        checked_at = (
            _format_iso_datetime(
                run.get(
                    "checked_at"
                )
            )
        )

        appointment_chips = (
            _appointment_controls(
                appointments,
                historical=False,
            )
        )

        return ft.Container(
            padding=14,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=11,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        (
                                            province_text
                                            + " · "
                                            + office_text
                                        ),
                                        size=14,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY,
                                    ),

                                    ft.Text(
                                        (
                                            "Comprobación: "
                                            + checked_at
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),

                            _status_chip(
                                "AVAILABLE",
                                (
                                    f"{len(appointments)} "
                                    "cita(s)"
                                ),
                            ),
                        ],
                        spacing=8,
                    ),

                    ft.Divider(
                        height=1,
                    ),

                    ft.Text(
                        (
                            "Citas obtenidas en "
                            "esta pasada"
                            if not fallback
                            else
                            "Última pasada conocida"
                        ),
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color=Q_TEXT,
                    ),

                    ft.Row(
                        controls=appointment_chips,
                        spacing=7,
                        run_spacing=7,
                        wrap=True,
                    ),
                ],
                spacing=8,
            ),
        )


    def render_test_reservation_in_history():
        appointment_history_column.controls.clear()

        active = (
            icpplus_test_reservation_service
            .get_active_reservation()
        )

        if not active:
            appointment_history_column.controls.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.EVENT_BUSY,
                                size=30,
                                color=Q_MUTED,
                            ),

                            ft.Text(
                                "No existe una cita de prueba reservada.",
                                size=13,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=8,
                        horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                )
            )

            return


        appointment = (
            str(
                active.get(
                    "appointment_date"
                )
                or ""
            )
            + " · "
            + str(
                active.get(
                    "appointment_time"
                )
                or ""
            )
        ).strip(
            " ·"
        )


        appointment_history_column.controls.append(
            ft.Container(
                padding=18,
                bgcolor="#FFFDF7",
                border=ft.border.all(
                    1,
                    "#F0D9A8",
                ),
                border_radius=12,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    width=42,
                                    height=42,
                                    border_radius=10,
                                    bgcolor="#FFF4E5",
                                    alignment=ft.Alignment(
                                        0,
                                        0,
                                    ),
                                    content=ft.Icon(
                                        ft.Icons.LOCK_CLOCK,
                                        size=21,
                                        color=Q_WARNING,
                                    ),
                                ),

                                ft.Column(
                                    [
                                        ft.Text(
                                            "Cita reservada con perfil de prueba",
                                            size=15,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY,
                                        ),

                                        ft.Text(
                                            (
                                                "No pertenece a ningún "
                                                "cliente ni expediente."
                                            ),
                                            size=11,
                                            color=Q_ERROR,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),

                                ft.TextButton(
                                    "Volver al historial",
                                    on_click=(
                                        show_appointment_history
                                    ),
                                ),
                            ],
                            spacing=10,
                        ),

                        ft.Divider(),

                        ft.Text(
                            appointment,
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=Q_WARNING,
                        ),

                        ft.Text(
                            (
                                "Provincia: "
                                + str(
                                    active.get(
                                        "province_key"
                                    )
                                    or "—"
                                )
                            ),
                            size=12,
                            color=Q_TEXT,
                        ),

                        ft.Text(
                            (
                                "Oficina: "
                                + str(
                                    active.get(
                                        "office_text"
                                    )
                                    or active.get(
                                        "office_key"
                                    )
                                    or "—"
                                )
                            ),
                            size=12,
                            color=Q_TEXT,
                        ),

                        ft.Text(
                            (
                                "Trámite: "
                                + str(
                                    active.get(
                                        "procedure_key"
                                    )
                                    or "—"
                                )
                            ),
                            size=12,
                            color=Q_MUTED,
                        ),

                        ft.Text(
                            (
                                "Reserva técnica utilizada "
                                "exclusivamente para mantener "
                                "temporalmente este hueco."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=8,
                ),
            )
        )


    def show_test_reservation(
        e=None,
    ):
        appointment_panel_mode[
            "value"
        ] = "reservation"

        appointment_pagination_host.visible = (
            False
        )

        render_test_reservation_in_history()

        _safe_page_update(
            page
        )


    def show_appointment_history(
        e=None,
    ):
        appointment_panel_mode[
            "value"
        ] = "history"

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    test_reservation_chip.on_click = (
        show_test_reservation
    )


    def set_appointment_history_page(
        page_number,
    ):
        try:
            page_number = int(
                page_number
            )
        except Exception:
            page_number = 1

        appointment_history_page[
            "value"
        ] = max(
            1,
            page_number,
        )

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    def refresh_all_attempts_chip():
        try:
            attempts = (
                icpplus_state_service
                .list_history(
                    limit=250
                )
            )

            count = len(
                attempts
                or []
            )

        except Exception:
            count = 0

        all_attempts_chip_text.value = (
            f"Todos los intentos · {count}"
        )

        selected = (
            appointment_panel_mode[
                "value"
            ]
            == "history"
        )

        all_attempts_chip_text.color = (
            Q_PRIMARY_2
            if selected
            else Q_MUTED
        )

        all_attempts_chip.bgcolor = (
            "#EAF3FF"
            if selected
            else "#F5F7FA"
        )

        all_attempts_chip.border = (
            ft.border.all(
                1,
                "#B9D5F5",
            )
            if selected
            else ft.border.all(
                1,
                Q_BORDER,
            )
        )


    def refresh_scheduler_chip():
        count = (
            icpplus_scheduler_service
            .active_count()
        )

        scheduler_chip_text.value = (
            f"Vigilancias activas · {count}"
        )

        if count:
            scheduler_chip_text.color = (
                Q_PRIMARY_2
            )

            scheduler_chip.bgcolor = (
                "#EAF3FF"
            )

        else:
            scheduler_chip_text.color = (
                Q_MUTED
            )

            scheduler_chip.bgcolor = (
                "#F5F7FA"
            )


    def render_active_schedulers_in_history():
        appointment_history_column.controls.clear()

        appointment_pagination_host.visible = (
            False
        )

        schedules = (
            icpplus_scheduler_service
            .list_active()
        )

        refresh_scheduler_chip()

        if not schedules:
            appointment_history_count.value = (
                "0 vigilancias"
            )

            appointment_history_column.controls.append(
                ft.Container(
                    padding=16,
                    content=ft.Text(
                        "No hay vigilancias activas.",
                        size=12,
                        color=Q_MUTED,
                    ),
                )
            )

            return


        appointment_history_count.value = (
            f"{len(schedules)} vigilancias"
        )


        for schedule in schedules:
            status = str(
                schedule.get(
                    "status"
                )
                or "ACTIVE"
            ).upper()

            interval_minutes = int(
                schedule.get(
                    "interval_minutes"
                )
                or 0
            )

            attempt_count = int(
                schedule.get(
                    "attempt_count"
                )
                or 0
            )

            office_text = str(
                schedule.get(
                    "office_text"
                )
                or schedule.get(
                    "office_key"
                )
                or "ICP Plus"
            )

            province_text = str(
                schedule.get(
                    "province_key"
                )
                or ""
            ).replace(
                "_",
                " ",
            ).title()

            procedure_text = str(
                schedule.get(
                    "procedure_text"
                )
                or schedule.get(
                    "procedure_key"
                )
                or "Trámite ICP Plus"
            )

            appointment_history_column.controls.append(
                ft.Container(
                    padding=14,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=10,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        office_text,
                                        size=14,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY,
                                        expand=True,
                                    ),
                                    _status_chip(
                                        status,
                                        {
                                            "ACTIVE":
                                                "Activa",
                                            "RUNNING":
                                                "Ejecutando",
                                            "PAUSED":
                                                "Pausada",
                                        }.get(
                                            status,
                                            status,
                                        ),
                                    ),
                                ],
                                spacing=8,
                            ),

                            ft.Text(
                                province_text,
                                size=11,
                                color=Q_MUTED,
                            ),

                            ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.DESCRIPTION_OUTLINED,
                                        size=14,
                                        color=Q_PRIMARY_2,
                                    ),

                                    ft.Text(
                                        procedure_text,
                                        size=11,
                                        color=Q_TEXT,
                                        weight=ft.FontWeight.W_500,
                                        expand=True,
                                    ),
                                ],
                                spacing=5,
                            ),

                            ft.Text(
                                (
                                    f"Cada {interval_minutes} min"
                                    f" · Intentos: {attempt_count}"
                                ),
                                size=12,
                                color=Q_TEXT,
                            ),

                            ft.Text(
                                (
                                    "Próximo intento: "
                                    + _format_iso_datetime(
                                        schedule.get(
                                            "next_run_at"
                                        )
                                    )
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),

                            ft.Text(
                                (
                                    "Finaliza: "
                                    + _format_iso_datetime(
                                        schedule.get(
                                            "ends_at"
                                        )
                                    )
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            )


    def show_all_attempts(
        e=None,
    ):
        appointment_panel_mode[
            "value"
        ] = "history"

        appointment_history_page[
            "value"
        ] = 1

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    all_attempts_chip.on_click = (
        show_all_attempts
    )


    def show_active_schedulers(
        e=None,
    ):
        appointment_panel_mode[
            "value"
        ] = "schedulers"

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    scheduler_chip.on_click = (
        show_active_schedulers
    )


    def refresh_appointment_history(
        cards,
    ):
        refresh_all_attempts_chip()
        refresh_scheduler_chip()

        if (
            appointment_panel_mode[
                "value"
            ]
            == "reservation"
        ):
            render_test_reservation_in_history()
            return

        if (
            appointment_panel_mode[
                "value"
            ]
            == "schedulers"
        ):
            render_active_schedulers_in_history()
            return


        appointment_history_column.controls.clear()

        visible_offices = {
            str(
                card.get(
                    "office_key"
                )
                or ""
            )
            for card in (
                cards
                or []
            )
        }


        try:
            history = (
                icpplus_state_service
                .list_history(
                    limit=100
                )
            )

        except Exception:
            history = []


        runs = []


        # ----------------------------------------------------
        # HISTÓRICO REAL:
        # una card = una pasada completa.
        # ----------------------------------------------------

        for item in history:
            office_key = str(
                item.get(
                    "office_key"
                )
                or ""
            )

            if (
                visible_offices
                and office_key
                not in visible_offices
            ):
                continue

            appointments = list(
                item.get(
                    "appointments"
                )
                or []
            )

            if not appointments:
                continue

            run = dict(
                item
            )

            run[
                "appointments"
            ] = appointments

            runs.append(
                run
            )


        # ----------------------------------------------------
        # COMPATIBILIDAD CON COMPROBACIONES ANTERIORES
        # ----------------------------------------------------
        #
        # Las pasadas creadas antes de incorporar el snapshot
        # "appointments" al histórico pueden seguir teniendo
        # sus citas conservadas en la card de la oficina.
        #
        # Antes solo usábamos este fallback cuando `runs`
        # estaba completamente vacío. Eso provocaba que, tras
        # crear la primera pasada nueva, desaparecieran del
        # panel oficinas históricas como Luarca.
        #
        # Ahora fusionamos ambos orígenes:
        #
        #   1. histórico real nuevo;
        #   2. último snapshot conocido de oficinas antiguas
        #      que aún no estén representadas en `runs`.
        #
        # Nunca inventamos citas y nunca duplicamos una oficina
        # que ya tenga histórico nuevo con appointments.
        # ----------------------------------------------------

        history_office_keys = {
            str(
                run.get(
                    "office_key"
                )
                or ""
            )
            for run in runs
            if run.get(
                "office_key"
            )
        }


        for card in (
            cards
            or []
        ):
            office_key = str(
                card.get(
                    "office_key"
                )
                or ""
            )


            if (
                office_key
                and office_key
                in history_office_keys
            ):
                continue


            current = dict(
                card.get(
                    "current"
                )
                or {}
            )

            last_valid = dict(
                card.get(
                    "last_valid"
                )
                or {}
            )


            current_appointments = list(
                current.get(
                    "appointments"
                )
                or []
            )


            if current_appointments:
                appointments = (
                    current_appointments
                )

                checked_at = (
                    current.get(
                        "checked_at"
                    )
                )

            else:
                appointments = list(
                    card.get(
                        "last_known_appointments"
                    )
                    or []
                )

                # Para una cita histórica conservada usamos
                # preferentemente la fecha del último resultado
                # válido, no la de un BLOCKED posterior.
                checked_at = (
                    last_valid.get(
                        "checked_at"
                    )
                    or current.get(
                        "checked_at"
                    )
                )


            if not appointments:
                continue


            runs.append(
                {
                    "province_key":
                        card.get(
                            "province_key"
                        ),

                    "province_text":
                        card.get(
                            "province_text"
                        ),

                    "office_key":
                        office_key,

                    "office_text":
                        card.get(
                            "office_text"
                        ),

                    "checked_at":
                        checked_at,

                    "appointments":
                        appointments,

                    "_fallback":
                        True,
                }
            )


            if office_key:
                history_office_keys.add(
                    office_key
                )


        runs.sort(
            key=lambda item: str(
                item.get(
                    "checked_at"
                )
                or ""
            ),
            reverse=True,
        )


        total_appointments = sum(
            len(
                run.get(
                    "appointments"
                )
                or []
            )
            for run in runs
        )


        total_runs = len(
            runs
        )

        total_pages = max(
            1,
            (
                total_runs
                + APPOINTMENT_HISTORY_PAGE_SIZE
                - 1
            )
            // APPOINTMENT_HISTORY_PAGE_SIZE,
        )


        try:
            current_page = int(
                appointment_history_page[
                    "value"
                ]
            )

        except Exception:
            current_page = 1


        current_page = max(
            1,
            min(
                current_page,
                total_pages,
            ),
        )

        appointment_history_page[
            "value"
        ] = current_page


        start_index = (
            current_page
            - 1
        ) * APPOINTMENT_HISTORY_PAGE_SIZE

        end_index = (
            start_index
            + APPOINTMENT_HISTORY_PAGE_SIZE
        )

        page_runs = runs[
            start_index:
            end_index
        ]


        appointment_history_count.value = (
            f"{total_runs} pasada(s)"
            f" · {total_appointments} cita(s)"
        )


        appointment_pagination_host.visible = (
            total_runs
            > APPOINTMENT_HISTORY_PAGE_SIZE
        )

        appointment_pagination_host.content = (
            compact_pagination_bar(
                page=current_page,
                page_size=(
                    APPOINTMENT_HISTORY_PAGE_SIZE
                ),
                total_items=total_runs,
                on_page_change=(
                    set_appointment_history_page
                ),
                label_prefix="Pasadas",
            )
        )


        if not runs:
            appointment_pagination_host.visible = (
                False
            )

            appointment_history_column.controls.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Text(
                        (
                            "Todavía no hay pasadas "
                            "con citas detectadas."
                        ),
                        color=Q_MUTED,
                        size=12,
                    ),
                )
            )

            return


        # Máximo 10 PASADAS visibles.
        #
        # Cada pasada sigue mostrando dentro todas las citas
        # detectadas en esa ejecución.
        for run in page_runs:
            appointment_history_column.controls.append(
                _appointment_run_card(
                    run,
                    fallback=bool(
                        run.get(
                            "_fallback"
                        )
                    ),
                )
            )


    def refresh_check_history():
        check_history_column.controls.clear()

        try:
            history = (
                icpplus_state_service
                .list_history(
                    limit=100
                )
            )

        except Exception:
            history = []


        province_filter = str(
            _dashboard_province_filter_key()
            or "TODAS"
        )

        status_filter = str(
            _dashboard_status_filter_key()
            or "TODOS"
        ).upper()

        search = str(
            dashboard_search.value
            or ""
        ).strip().lower()


        visible = []


        for item in history:
            province_key = str(
                item.get(
                    "province_key"
                )
                or ""
            )

            portal_status = str(
                item.get(
                    "portal_status"
                )
                or "UNKNOWN"
            ).upper()

            availability_status = str(
                item.get(
                    "availability_status"
                )
                or "UNKNOWN"
            ).upper()


            if (
                province_filter
                != "TODAS"
                and province_key
                != province_filter
            ):
                continue


            if (
                status_filter
                != "TODOS"
            ):
                if (
                    status_filter
                    == "BLOCKED"
                    and portal_status
                    != "BLOCKED"
                ):
                    continue

                elif (
                    status_filter
                    not in {
                        "BLOCKED",
                        "PENDING",
                    }
                    and availability_status
                    != status_filter
                ):
                    continue


            if search:
                haystack = " ".join(
                    (
                        province_key,
                        str(
                            item.get(
                                "office_text"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "procedure_key"
                            )
                            or ""
                        ),
                    )
                ).lower()

                if search not in haystack:
                    continue


            visible.append(
                item
            )


        check_history_count.value = (
            f"{len(visible)} comprobación(es)"
        )


        if not visible:
            check_history_column.controls.append(
                ft.Container(
                    padding=20,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Text(
                        "Sin comprobaciones guardadas.",
                        size=12,
                        color=Q_MUTED,
                    ),
                )
            )

            return


        for item in visible:
            portal_status = str(
                item.get(
                    "portal_status"
                )
                or "UNKNOWN"
            ).upper()

            availability_status = str(
                item.get(
                    "availability_status"
                )
                or "UNKNOWN"
            ).upper()

            appointment_count = int(
                item.get(
                    "appointment_count"
                )
                or 0
            )

            check_history_column.controls.append(
                ft.Container(
                    padding=11,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=10,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        _format_iso_datetime(
                                            item.get(
                                                "checked_at"
                                            )
                                        ),
                                        size=11,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY,
                                        expand=True,
                                    ),

                                    _status_chip(
                                        (
                                            availability_status
                                            if portal_status
                                            == "ONLINE"
                                            else portal_status
                                        ),
                                        (
                                            _availability_label(
                                                availability_status
                                            )
                                            if portal_status
                                            == "ONLINE"
                                            else _portal_label(
                                                portal_status
                                            )
                                        ),
                                    ),
                                ],
                                spacing=6,
                            ),

                            ft.Text(
                                str(
                                    item.get(
                                        "office_text"
                                    )
                                    or item.get(
                                        "office_key"
                                    )
                                    or "ICP Plus"
                                ),
                                size=11,
                                color=Q_TEXT,
                            ),

                            ft.Text(
                                (
                                    f"Resultado: "
                                    f"{appointment_count} cita(s)"
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),

                            (
                                ft.Text(
                                    (
                                        "Support ID: "
                                        + str(
                                            item.get(
                                                "support_id"
                                            )
                                        )
                                    ),
                                    size=9,
                                    color=Q_ERROR,
                                    selectable=True,
                                )
                                if item.get(
                                    "support_id"
                                )
                                else ft.Container()
                            ),
                        ],
                        spacing=5,
                    ),
                )
            )


    def refresh_persistent_cards(
        e=None,
    ):
        persisted_cards = (
            icpplus_state_service
            .list_cards()
        )

        # Los KPI solo se calculan con observaciones reales.
        # Las cards PENDING no inflan métricas.
        refresh_dashboard_metrics(
            persisted_cards
        )

        cards = build_dashboard_cards(
            persisted_cards
        )

        # Panel izquierdo siempre muestra la cobertura completa.
        refresh_province_monitor(
            cards
        )


        province_filter = str(
            _dashboard_province_filter_key()
            or "TODAS"
        )

        status_filter = str(
            _dashboard_status_filter_key()
            or "TODOS"
        ).upper()

        search = str(
            dashboard_search.value
            or ""
        ).strip().lower()


        visible_cards = []


        for card in cards:
            if (
                province_filter
                != "TODAS"
                and str(
                    card.get(
                        "province_key"
                    )
                    or ""
                )
                != province_filter
            ):
                continue


            current = dict(
                card.get(
                    "current"
                )
                or {}
            )

            portal_status = str(
                current.get(
                    "portal_status"
                )
                or "UNKNOWN"
            ).upper()

            availability_status = str(
                current.get(
                    "availability_status"
                )
                or "UNKNOWN"
            ).upper()


            if (
                status_filter
                != "TODOS"
            ):
                if (
                    status_filter
                    == "BLOCKED"
                ):
                    if (
                        portal_status
                        != "BLOCKED"
                    ):
                        continue

                elif (
                    status_filter
                    == "PENDING"
                ):
                    if not card.get(
                        "pending"
                    ):
                        continue

                elif (
                    availability_status
                    != status_filter
                ):
                    continue


            if search:
                haystack = " ".join(
                    (
                        str(
                            card.get(
                                "province_text"
                            )
                            or card.get(
                                "province_key"
                            )
                            or ""
                        ),

                        str(
                            card.get(
                                "office_text"
                            )
                            or ""
                        ),

                        str(
                            card.get(
                                "office_key"
                            )
                            or ""
                        ),

                        str(
                            card.get(
                                "procedure_text"
                            )
                            or card.get(
                                "procedure_key"
                            )
                            or ""
                        ),
                    )
                ).lower()

                if search not in haystack:
                    continue


            visible_cards.append(
                card
            )


        refresh_appointment_history(
            visible_cards
        )

        refresh_check_history()


        # La cuadrícula antigua se conserva temporalmente como
        # implementación secundaria, pero ya no será la vista
        # principal del dashboard.
        persistent_cards_column.controls.clear()


        for card in visible_cards:
            persistent_cards_column.controls.append(
                build_persistent_card(
                    card
                )
            )


        if not visible_cards:
            persistent_cards_column.controls.append(
                ft.Container(
                    col=12,
                    padding=22,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Text(
                        (
                            "No hay oficinas "
                            "con los filtros actuales."
                        ),
                        color=Q_MUTED,
                        size=13,
                    ),
                )
            )


    def on_dashboard_search_change(
        e=None,
    ):
        appointment_history_page[
            "value"
        ] = 1

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    dashboard_search.on_change = (
        on_dashboard_search_change
    )

    refresh_persistent_cards()


    def render_result(result):
        portal_status = str(
            result.get(
                "portal_status"
            )
            or "UNKNOWN"
        ).upper()

        availability_status = str(
            result.get(
                "availability_status"
            )
            or "UNKNOWN"
        ).upper()

        portal_value.value = (
            portal_status
        )

        portal_value.color = (
            _status_color(
                portal_status
            )
        )

        availability_value.value = (
            availability_status
        )

        availability_value.color = (
            _status_color(
                availability_status
            )
        )

        appointments = list(
            result.get(
                "appointments"
            )
            or []
        )

        diagnostic_page.value = str(
            result.get(
                "page"
            )
            or "—"
        )

        diagnostic_result_class.value = str(
            result.get(
                "result_class"
            )
            or "—"
        )

        diagnostic_support_id.value = str(
            result.get(
                "support_id"
            )
            or "—"
        )

        diagnostic_navigation_error.value = str(
            result.get(
                "navigation_error"
            )
            or "—"
        )

        diagnostic_checked_at.value = (
            datetime.now()
            .astimezone()
            .strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        )

        appointments_column.controls.clear()

        for item in appointments:

            if isinstance(
                item,
                dict,
            ):
                date = str(
                    item.get(
                        "date"
                    )
                    or ""
                )

                time_value = str(
                    item.get(
                        "time"
                    )
                    or ""
                )

                text = (
                    f"{date} · {time_value}"
                    .strip(" ·")
                )

            else:
                text = str(
                    item
                )

            appointments_column.controls.append(
                ft.Container(
                    padding=12,
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=8,
                    content=ft.Text(
                        text,
                        size=15,
                        weight=(
                            ft.FontWeight.W_500
                        ),
                    ),
                )
            )


        if (
            availability_status
            == "AVAILABLE"
        ):
            result_message.value = (
                f"{len(appointments)} "
                "cita(s) observada(s)."
            )

            result_message.color = (
                Q_SUCCESS
            )

        elif (
            availability_status
            == "UNAVAILABLE"
        ):
            result_message.value = (
                "No hay citas disponibles "
                "según la respuesta observada."
            )

            result_message.color = (
                Q_WARNING
            )

        elif (
            portal_status
            == "BLOCKED"
        ):
            result_message.value = (
                "ICP Plus rechazó la solicitud. "
                "Estado BLOCKED confirmado. "
                "La ejecución se ha detenido "
                "sin reintento automático."
            )

            result_message.color = (
                Q_ERROR
            )

        elif (
            portal_status
            in {
                "DOWN",
                "DEGRADED",
            }
        ):
            result_message.value = (
                "El portal no está operativo "
                "con normalidad."
            )

            result_message.color = (
                Q_WARNING
            )

        else:
            result_message.value = (
                "No se pudo determinar "
                "la disponibilidad."
            )

            result_message.color = (
                Q_WARNING
            )


    def check_worker(
        profile_data,
        province_key,
        procedure_key,
        office_key,
    ):
        try:
            result_message.value = (
                "Abriendo ICP Plus y "
                "comprobando disponibilidad..."
            )

            result_message.color = (
                Q_PRIMARY_2
            )

            dialog_execution_status.value = (
                "Bot en ejecución"
            )

            dialog_execution_detail.value = (
                "Chrome se está ejecutando. "
                "No cierres esta ventana."
            )

            dialog_execution_status.color = (
                Q_PRIMARY_2
            )

            _safe_page_update(
                page
            )


            result = (
                service
                .check_availability(
                    province_key=(
                        province_key
                    ),
                    procedure_key=(
                        procedure_key
                    ),
                    office_scope="SINGLE",
                    office_key=(
                        office_key
                    ),
                    profile=(
                        profile_data
                    ),
                    contact=None,
                )
            )


            render_result(
                result
            )


            offices = (
                service.list_offices(
                    province_key,
                    procedure_key,
                )
            )


            office_meta = next(
                (
                    item
                    for item in offices
                    if str(
                        item.get(
                            "key"
                        )
                    )
                    == str(
                        office_key
                    )
                ),
                {},
            )


            office_text = str(
                office_meta.get(
                    "provider_text"
                )
                or office_meta.get(
                    "text"
                )
                or office_key
            )


            flow_key = (
                str(
                    province_key
                )
                + ":"
                + str(
                    procedure_key
                )
            )


            # ------------------------------------------------
            # UX PRIORITY:
            #
            # El resultado del bot ya está disponible.
            # Lo mostramos ANTES de reconstruir el dashboard,
            # porque refresh_persistent_cards() puede implicar
            # bastante trabajo visual.
            #
            # El usuario no debe permanecer viendo
            # "Bot en ejecución" mientras se refrescan cards,
            # históricos y paginación.
            # ------------------------------------------------

            render_dialog_result(
                result
            )

            dialog_last_result[
                "value"
            ] = result

            set_dialog_step(
                "result"
            )


            # ------------------------------------------------
            # Persistencia + actualización secundaria.
            #
            # Se realiza después de que Resultado ya sea
            # visible en el diálogo.
            # ------------------------------------------------

            try:
                icpplus_state_service.record_result(
                    provider="ICP_PLUS",
                    flow_key=flow_key,
                    province_key=province_key,
                    procedure_key=procedure_key,
                    office_key=office_key,
                    office_text=office_text,
                    result=result,
                )

                refresh_persistent_cards()

            except Exception as persist_exc:
                print(
                    "[ICPPLUS] error persistiendo card:",
                    repr(
                        persist_exc
                    ),
                    flush=True,
                )


        except Exception as exc:
            show_error(
                exc
            )

            render_dialog_error(
                exc
            )

            set_dialog_step(
                "result"
            )


        finally:
            try:
                service.close()
            except Exception:
                pass


            progress.visible = False

            check_button.disabled = (
                False
            )

            save_button.disabled = (
                False
            )

            dialog_execution_progress.visible = (
                False
            )

            _safe_page_update(
                page
            )


    def on_check(
        e=None,
    ):
        province_key = (
            selected_province_key()
        )

        procedure_key = (
            selected_procedure_key()
        )

        office_key = (
            selected_office_key()
        )


        if (
            not province_key
            or not procedure_key
            or not office_key
        ):
            dialog_execution_status.value = (
                "Configuración incompleta"
            )

            dialog_execution_status.color = (
                Q_ERROR
            )

            dialog_execution_detail.value = (
                "Provincia, trámite y oficina "
                "son obligatorios."
            )

            _safe_page_update(
                page
            )

            return


        try:
            profile_data = (
                save_current_profile(
                    show_feedback=False
                )
            )

        except Exception as exc:
            dialog_execution_status.value = (
                "Perfil no válido"
            )

            dialog_execution_status.color = (
                Q_ERROR
            )

            dialog_execution_detail.value = str(
                exc
            )

            _safe_page_update(
                page
            )

            return


        if (
            execution_mode.value
            == "SCHEDULED"
        ):
            try:
                interval_minutes = int(
                    scheduler_interval_input.value
                    or 0
                )

                duration_minutes = int(
                    scheduler_duration_input.value
                    or 0
                )

                schedule = (
                    icpplus_scheduler_service
                    .create_schedule(
                        province_key=(
                            province_key
                        ),
                        procedure_key=(
                            procedure_key
                        ),
                        procedure_text=(
                            procedure_key_to_label.get(
                                procedure_key,
                                procedure_key,
                            )
                        ),
                        office_key=(
                            office_key
                        ),
                        office_text=(
                            office_key_to_label.get(
                                office_key,
                                office_key,
                            )
                        ),
                        interval_minutes=(
                            interval_minutes
                        ),
                        duration_minutes=(
                            duration_minutes
                        ),
                    )
                )

                appointment_panel_mode[
                    "value"
                ] = "schedulers"

                result_message.value = (
                    "Vigilancia ICP Plus programada."
                )

                result_message.color = (
                    Q_SUCCESS
                )

                refresh_persistent_cards()

                check_dialog.open = False

                _safe_page_update(
                    page
                )

                print(
                    "[ICPPLUS-SCHEDULER] created =",
                    schedule.get(
                        "scheduler_id"
                    ),
                    flush=True,
                )

            except Exception as exc:
                dialog_execution_status.value = (
                    "No se pudo programar"
                )

                dialog_execution_status.color = (
                    Q_ERROR
                )

                dialog_execution_detail.value = str(
                    exc
                )

                _safe_page_update(
                    page
                )

            return


        check_button.disabled = True
        save_button.disabled = True

        progress.visible = True

        dialog_execution_progress.visible = (
            True
        )

        dialog_execution_status.value = (
            "Preparando comprobación..."
        )

        dialog_execution_status.color = (
            Q_PRIMARY_2
        )

        dialog_execution_detail.value = (
            "Inicializando el runtime ICP Plus."
        )


        result_message.value = (
            "Preparando comprobación..."
        )

        result_message.color = (
            Q_PRIMARY_2
        )


        appointments_column.controls.clear()

        portal_value.value = "—"
        availability_value.value = "—"


        set_dialog_step(
            "execution"
        )

        _safe_page_update(
            page
        )


        worker = threading.Thread(
            target=check_worker,
            kwargs={
                "profile_data":
                    profile_data,

                "province_key":
                    province_key,

                "procedure_key":
                    procedure_key,

                "office_key":
                    office_key,
            },
            name="icpplus-flet-check",
            daemon=True,
        )

        worker.start()


    check_button.on_click = (
        on_check
    )


    # ========================================================
    # DIALOG GOBERNADO DE LANZAMIENTO
    # ========================================================

    dialog_step_state = {
        "value":
            "profile",
    }

    dialog_last_result = {
        "value":
            None,
    }


    dialog_message = ft.Text(
        "",
        size=11,
        color=Q_MUTED,
        visible=False,
    )


    dialog_execution_status = ft.Text(
        "Listo para lanzar",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=Q_SUCCESS,
    )

    dialog_execution_detail = ft.Text(
        (
            "Revisa la configuración "
            "antes de iniciar Chrome."
        ),
        size=12,
        color=Q_MUTED,
    )

    dialog_execution_progress = ft.ProgressRing(
        visible=False,
        width=26,
        height=26,
        stroke_width=3,
    )


    execution_profile_value = ft.Text(
        "—",
        size=13,
        color=Q_TEXT,
    )

    execution_province_value = ft.Text(
        "—",
        size=13,
        color=Q_TEXT,
    )

    execution_procedure_value = ft.Text(
        "—",
        size=13,
        color=Q_TEXT,
    )

    execution_office_value = ft.Text(
        "—",
        size=13,
        color=Q_TEXT,
    )

    execution_mode_value = ft.Text(
        "Una comprobación",
        size=13,
        color=Q_TEXT,
    )

    execution_schedule_value = ft.Text(
        "No aplica",
        size=13,
        color=Q_TEXT,
    )


    dialog_result_body = ft.Column(
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


    def dialog_summary_row(
        label,
        control,
    ):
        return ft.Container(
            padding=12,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=9,
            bgcolor="#FFFFFF",
            content=ft.Row(
                [
                    ft.Text(
                        label,
                        width=140,
                        size=11,
                        color=Q_MUTED,
                        weight=ft.FontWeight.BOLD,
                    ),

                    control,
                ],
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )


    # --------------------------------------------------------
    # PERFIL
    # --------------------------------------------------------

    profile_step_content = ft.Column(
        [
            ft.Container(
                padding=14,
                bgcolor="#EAF3FF",
                border=ft.border.all(
                    1,
                    "#B9D5F5",
                ),
                border_radius=10,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.PERSON_OUTLINE,
                                    color=Q_PRIMARY_2,
                                    size=22,
                                ),

                                ft.Text(
                                    "Perfil técnico de prueba",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY,
                                ),
                            ],
                            spacing=8,
                        ),

                        ft.Text(
                            (
                                "Identidad utilizada únicamente "
                                "para las comprobaciones de ICP Plus. "
                                "No corresponde a ningún cliente."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=5,
                ),
            ),

            ft.Container(
                padding=18,
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=12,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                nombre,
                                nacionalidad,
                                nie,
                            ],
                            spacing=10,
                        ),

                        ft.Row(
                            [
                                telefono,
                                email,
                            ],
                            spacing=10,
                        ),

                        ft.Row(
                            [
                                save_button,
                            ]
                        ),
                    ],
                    spacing=12,
                ),
            ),
        ],
        spacing=12,
        expand=True,
    )


    # --------------------------------------------------------
    # CONSULTA
    # --------------------------------------------------------

    execution_mode = ft.RadioGroup(
        value="ONE_SHOT",
        content=ft.Row(
            [
                ft.Radio(
                    value="ONE_SHOT",
                    label="Una comprobación",
                ),
                ft.Radio(
                    value="SCHEDULED",
                    label="Vigilancia programada",
                ),
            ],
            spacing=28,
        ),
    )

    scheduler_interval_input = ft.TextField(
        label="Intervalo entre intentos (minutos)",
        value="15",
        width=260,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    scheduler_duration_input = ft.TextField(
        label="Duración total (minutos)",
        value="60",
        width=260,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    scheduler_settings = ft.Container(
        visible=False,
        padding=12,
        bgcolor="#F8FAFC",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=9,
        content=ft.Column(
            [
                ft.Text(
                    "Configuración de vigilancia",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY,
                ),
                ft.Row(
                    [
                        scheduler_interval_input,
                        scheduler_duration_input,
                    ],
                    spacing=10,
                ),
                ft.Text(
                    (
                        "Cada ejecución abre y cierra su propio "
                        "Chrome. Existe además un descanso global "
                        "mínimo de 15 minutos entre bots."
                    ),
                    size=11,
                    color=Q_MUTED,
                ),
                ft.Text(
                    (
                        "Un minuto antes de cada ejecución efectiva "
                        "se mostrará un aviso."
                    ),
                    size=11,
                    color=Q_MUTED,
                ),
            ],
            spacing=8,
        ),
    )


    def on_execution_mode_change(
        e=None,
    ):
        scheduled = (
            execution_mode.value
            == "SCHEDULED"
        )

        scheduler_settings.visible = (
            scheduled
        )

        check_button.text = (
            "Iniciar vigilancia"
            if scheduled
            else "Lanzar comprobación"
        )

        _safe_page_update(
            page
        )


    execution_mode.on_change = (
        on_execution_mode_change
    )


    query_step_content = ft.Column(
        [
            ft.Container(
                padding=14,
                bgcolor="#EAF3FF",
                border=ft.border.all(
                    1,
                    "#B9D5F5",
                ),
                border_radius=10,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.TRAVEL_EXPLORE,
                                    color=Q_PRIMARY_2,
                                    size=22,
                                ),

                                ft.Text(
                                    "Consulta ICP Plus",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY,
                                ),
                            ],
                            spacing=8,
                        ),

                        ft.Text(
                            (
                                "Selecciona provincia, trámite "
                                "y oficina que comprobará el bot."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=5,
                ),
            ),

            ft.Container(
                padding=18,
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=12,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                province_dd.control,
                                procedure_dd.control,
                            ],
                            spacing=10,
                        ),

                        office_dd.control,

                        ft.Divider(
                            height=1,
                        ),

                        ft.Text(
                            "Modo de ejecución",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY,
                        ),

                        execution_mode,

                        scheduler_settings,

                        ft.Container(
                            padding=12,
                            bgcolor="#F8FAFC",
                            border_radius=9,
                            content=ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.SECURITY_OUTLINED,
                                        color=Q_SUCCESS,
                                        size=18,
                                    ),

                                    ft.Text(
                                        (
                                            "La comprobación se detiene "
                                            "antes de CAPTCHA, selección "
                                            "de cita o reserva."
                                        ),
                                        size=11,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=8,
                            ),
                        ),
                    ],
                    spacing=14,
                ),
            ),
        ],
        spacing=12,
        expand=True,
    )


    # --------------------------------------------------------
    # EJECUCIÓN
    # --------------------------------------------------------

    execution_step_content = ft.Column(
        [
            ft.Container(
                padding=14,
                bgcolor="#EAF3FF",
                border=ft.border.all(
                    1,
                    "#B9D5F5",
                ),
                border_radius=10,
                content=ft.Row(
                    [
                        ft.Container(
                            width=46,
                            height=46,
                            border_radius=12,
                            bgcolor="#FFFFFF",
                            alignment=ft.Alignment(
                                0,
                                0,
                            ),
                            content=ft.Icon(
                                ft.Icons.ROCKET_LAUNCH_OUTLINED,
                                color=Q_PRIMARY_2,
                                size=24,
                            ),
                        ),

                        ft.Column(
                            [
                                ft.Text(
                                    "Ejecución del bot",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY,
                                ),

                                ft.Text(
                                    (
                                        "Confirma la configuración "
                                        "antes de abrir ICP Plus."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=3,
                        ),
                    ],
                    spacing=10,
                ),
            ),

            dialog_summary_row(
                "Perfil",
                execution_profile_value,
            ),

            dialog_summary_row(
                "Provincia",
                execution_province_value,
            ),

            dialog_summary_row(
                "Trámite",
                execution_procedure_value,
            ),

            dialog_summary_row(
                "Oficina",
                execution_office_value,
            ),

            dialog_summary_row(
                "Modo",
                execution_mode_value,
            ),

            dialog_summary_row(
                "Programación",
                execution_schedule_value,
            ),

            ft.Container(
                padding=16,
                bgcolor="#F8FAFC",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=12,
                content=ft.Row(
                    [
                        dialog_execution_progress,

                        ft.Column(
                            [
                                dialog_execution_status,
                                dialog_execution_detail,
                            ],
                            spacing=3,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
            ),
        ],
        spacing=10,
        expand=True,
    )


    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    result_step_content = ft.Column(
        [
            ft.Container(
                padding=14,
                bgcolor="#EAF3FF",
                border=ft.border.all(
                    1,
                    "#B9D5F5",
                ),
                border_radius=10,
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.FACT_CHECK_OUTLINED,
                            color=Q_PRIMARY_2,
                            size=22,
                        ),

                        ft.Column(
                            [
                                ft.Text(
                                    "Resultado de la comprobación",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY,
                                ),

                                ft.Text(
                                    (
                                        "El resultado queda persistido "
                                        "en el dashboard."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=3,
                        ),
                    ],
                    spacing=10,
                ),
            ),

            ft.Container(
                expand=True,
                padding=4,
                content=dialog_result_body,
            ),
        ],
        spacing=10,
        expand=True,
    )


    dialog_content_host = ft.Container(
        expand=True,
        content=profile_step_content,
    )


    def render_dialog_result(
        result,
    ):
        result = dict(
            result
            or {}
        )

        portal_status = str(
            result.get(
                "portal_status"
            )
            or "UNKNOWN"
        ).upper()

        availability_status = str(
            result.get(
                "availability_status"
            )
            or "UNKNOWN"
        ).upper()

        appointments = list(
            result.get(
                "appointments"
            )
            or []
        )


        dialog_result_body.controls.clear()


        dialog_result_body.controls.extend(
            [
                ft.Row(
                    [
                        _status_chip(
                            portal_status,
                            _portal_label(
                                portal_status
                            ),
                        ),

                        _status_chip(
                            availability_status,
                            _availability_label(
                                availability_status
                            ),
                        ),
                    ],
                    spacing=8,
                ),

                ft.Text(
                    (
                        f"{len(appointments)} "
                        "cita(s) detectada(s)"
                    ),
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY,
                ),
            ]
        )


        if appointments:
            dialog_result_body.controls.append(
                ft.Text(
                    "Citas observadas",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_TEXT,
                )
            )

            dialog_result_body.controls.append(
                ft.Row(
                    controls=_appointment_controls(
                        appointments,
                    ),
                    spacing=7,
                    run_spacing=7,
                    wrap=True,
                )
            )


        diagnostics = [
            (
                "Página",
                result.get(
                    "page"
                ),
            ),
            (
                "Clase de resultado",
                result.get(
                    "result_class"
                ),
            ),
            (
                "Support ID",
                result.get(
                    "support_id"
                ),
            ),
            (
                "Error de navegación",
                result.get(
                    "navigation_error"
                ),
            ),
        ]


        visible_diagnostics = [
            (
                label,
                value,
            )
            for label, value
            in diagnostics
            if value
        ]


        if visible_diagnostics:
            dialog_result_body.controls.append(
                ft.Divider()
            )

            dialog_result_body.controls.append(
                ft.Text(
                    "Diagnóstico",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_TEXT,
                )
            )


            for label, value in visible_diagnostics:
                dialog_result_body.controls.append(
                    dialog_summary_row(
                        label,
                        ft.Text(
                            str(
                                value
                            ),
                            size=11,
                            color=Q_MUTED,
                            selectable=True,
                        ),
                    )
                )


    def render_dialog_error(
        exc,
    ):
        dialog_result_body.controls.clear()

        dialog_result_body.controls.extend(
            [
                ft.Container(
                    padding=14,
                    bgcolor="#FDECEC",
                    border_radius=10,
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.ERROR_OUTLINE,
                                color=Q_ERROR,
                            ),

                            ft.Column(
                                [
                                    ft.Text(
                                        "La comprobación no pudo completarse",
                                        size=15,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_ERROR,
                                    ),

                                    ft.Text(
                                        str(
                                            exc
                                        ),
                                        size=11,
                                        color=Q_TEXT,
                                    ),
                                ],
                                spacing=3,
                            ),
                        ],
                        spacing=10,
                    ),
                )
            ]
        )


    # --------------------------------------------------------
    # SIDEBAR DEL DIALOG
    # --------------------------------------------------------

    def build_dialog_step_card(
        title,
        subtitle,
        icon,
    ):
        return ft.Container(
            padding=12,
            border_radius=9,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            content=ft.Row(
                [
                    ft.Icon(
                        icon,
                        size=20,
                        color=Q_MUTED,
                    ),

                    ft.Column(
                        [
                            ft.Text(
                                title,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY,
                            ),

                            ft.Text(
                                subtitle,
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=9,
            ),
        )


    modal_profile_step = (
        build_dialog_step_card(
            "Perfil",
            "Datos técnicos",
            ft.Icons.PERSON_OUTLINE,
        )
    )

    modal_query_step = (
        build_dialog_step_card(
            "Consulta",
            "Provincia y oficina",
            ft.Icons.TRAVEL_EXPLORE,
        )
    )

    modal_execution_step = (
        build_dialog_step_card(
            "Ejecución",
            "Lanzamiento del bot",
            ft.Icons.ROCKET_LAUNCH_OUTLINED,
        )
    )

    modal_result_step = (
        build_dialog_step_card(
            "Resultado",
            "Resultado persistido",
            ft.Icons.FACT_CHECK_OUTLINED,
        )
    )


    dialog_step_controls = {
        "profile":
            modal_profile_step,

        "query":
            modal_query_step,

        "execution":
            modal_execution_step,

        "result":
            modal_result_step,
    }


    dialog_step_contents = {
        "profile":
            profile_step_content,

        "query":
            query_step_content,

        "execution":
            execution_step_content,

        "result":
            result_step_content,
    }


    dialog_back_button = ft.OutlinedButton(
        "Atrás",
        visible=False,
    )

    dialog_cancel_button = ft.OutlinedButton(
        "Cancelar",
    )

    dialog_next_button = ft.ElevatedButton(
        "Siguiente",
        bgcolor=Q_PRIMARY_2,
        color="#FFFFFF",
    )

    dialog_close_button = ft.ElevatedButton(
        "Cerrar",
        visible=False,
        bgcolor=Q_PRIMARY_2,
        color="#FFFFFF",
    )


    def set_dialog_step(
        step,
    ):
        step = str(
            step
            or "profile"
        )

        if step not in dialog_step_contents:
            step = "profile"


        dialog_step_state[
            "value"
        ] = step

        dialog_content_host.content = (
            dialog_step_contents[
                step
            ]
        )


        for key, control in (
            dialog_step_controls.items()
        ):
            active = (
                key
                == step
            )

            control.bgcolor = (
                "#EAF3FF"
                if active
                else "#FFFFFF"
            )

            control.border = ft.border.all(
                1,
                (
                    "#9FC5F8"
                    if active
                    else Q_BORDER
                ),
            )


        dialog_back_button.visible = (
            step
            in {
                "query",
                "execution",
            }
        )

        dialog_next_button.visible = (
            step
            in {
                "profile",
                "query",
            }
        )

        check_button.visible = (
            step
            == "execution"
        )

        dialog_cancel_button.visible = (
            step
            != "result"
        )

        dialog_close_button.visible = (
            step
            == "result"
        )


        _safe_page_update(
            page
        )


    def prepare_execution_step():
        province_key = (
            selected_province_key()
        )

        procedure_key = (
            selected_procedure_key()
        )

        office_key = (
            selected_office_key()
        )


        if (
            not province_key
            or not procedure_key
            or not office_key
        ):
            raise ValueError(
                (
                    "Provincia, trámite y oficina "
                    "son obligatorios."
                )
            )


        profile_data = (
            save_current_profile(
                show_feedback=False
            )
        )


        execution_profile_value.value = (
            (
                profile_data.get(
                    "icpplus_nombre"
                )
                or "Perfil técnico"
            )
            + " · "
            + (
                profile_data.get(
                    "icpplus_nie"
                )
                or "—"
            )
        )


        execution_province_value.value = (
            province_key_to_label.get(
                province_key,
                province_key,
            )
        )

        execution_procedure_value.value = (
            procedure_key_to_label.get(
                procedure_key,
                procedure_key,
            )
        )

        execution_office_value.value = (
            office_key_to_label.get(
                office_key,
                office_key,
            )
        )


        if (
            execution_mode.value
            == "SCHEDULED"
        ):
            try:
                interval_minutes = int(
                    scheduler_interval_input.value
                    or 0
                )

                duration_minutes = int(
                    scheduler_duration_input.value
                    or 0
                )

            except (
                TypeError,
                ValueError,
            ):
                raise ValueError(
                    "Intervalo y duración deben "
                    "ser números enteros."
                )

            if (
                interval_minutes
                < icpplus_scheduler_service
                .MIN_INTERVAL_MINUTES
            ):
                raise ValueError(
                    "El intervalo mínimo de vigilancia "
                    "es de 15 minutos."
                )

            if (
                duration_minutes
                < interval_minutes
            ):
                raise ValueError(
                    "La duración debe ser igual o "
                    "superior al intervalo."
                )

            execution_mode_value.value = (
                "Vigilancia programada"
            )

            execution_schedule_value.value = (
                f"Cada {interval_minutes} min · "
                f"durante {duration_minutes} min"
            )

            check_button.text = (
                "Iniciar vigilancia"
            )

            dialog_execution_status.value = (
                "Vigilancia lista"
            )

            dialog_execution_detail.value = (
                (
                    "Al pulsar «Iniciar vigilancia» "
                    "se programará el primer intento. "
                    "Chrome NO se abrirá ahora."
                )
            )

        else:
            execution_mode_value.value = (
                "Una comprobación"
            )

            execution_schedule_value.value = (
                "No aplica"
            )

            check_button.text = (
                "Lanzar comprobación"
            )

            dialog_execution_status.value = (
                "Listo para lanzar"
            )

            dialog_execution_detail.value = (
                (
                    "Al pulsar «Lanzar comprobación» "
                    "se abrirá Chrome y comenzará "
                    "la consulta."
                )
            )


        dialog_execution_status.color = (
            Q_SUCCESS
        )


    def dialog_next(
        e=None,
    ):
        step = (
            dialog_step_state[
                "value"
            ]
        )


        dialog_message.visible = False


        try:
            if step == "profile":
                save_current_profile(
                    show_feedback=False
                )

                set_dialog_step(
                    "query"
                )

                return


            if step == "query":
                prepare_execution_step()

                set_dialog_step(
                    "execution"
                )

                return


        except Exception as exc:
            dialog_message.value = str(
                exc
            )

            dialog_message.color = (
                Q_ERROR
            )

            dialog_message.visible = (
                True
            )

            _safe_page_update(
                page
            )


    def dialog_back(
        e=None,
    ):
        step = (
            dialog_step_state[
                "value"
            ]
        )


        if step == "execution":
            set_dialog_step(
                "query"
            )

        elif step == "query":
            set_dialog_step(
                "profile"
            )


    def close_check_dialog(
        e=None,
    ):
        # Conservamos el control en overlay para poder
        # reutilizar exactamente la misma instancia.
        check_dialog.open = False

        _safe_page_update(
            page
        )


    dialog_back_button.on_click = (
        dialog_back
    )

    dialog_next_button.on_click = (
        dialog_next
    )

    dialog_cancel_button.on_click = (
        close_check_dialog
    )

    dialog_close_button.on_click = (
        close_check_dialog
    )


    check_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(
                    ft.Icons.ROCKET_LAUNCH_OUTLINED,
                    color=Q_PRIMARY_2,
                    size=24,
                ),

                ft.Text(
                    "Comprobar disponibilidad ICP Plus",
                    size=22,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY,
                ),
            ],
            spacing=9,
        ),

        content=ft.Container(
            width=1080,
            height=690,
            content=ft.Row(
                [
                    ft.Container(
                        width=220,
                        padding=12,
                        bgcolor="#FBFCFE",
                        border=ft.border.all(
                            1,
                            Q_BORDER,
                        ),
                        border_radius=12,
                        content=ft.Column(
                            [
                                ft.Text(
                                    "Comprobación",
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY,
                                ),

                                ft.Text(
                                    (
                                        "Flujo gobernado del bot "
                                        "ICP Plus."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),

                                ft.Divider(),

                                modal_profile_step,
                                modal_query_step,
                                modal_execution_step,
                                modal_result_step,
                            ],
                            spacing=9,
                        ),
                    ),

                    ft.Container(
                        expand=True,
                        padding=4,
                        content=ft.Column(
                            [
                                dialog_content_host,

                                dialog_message,
                            ],
                            spacing=8,
                            expand=True,
                        ),
                    ),
                ],
                spacing=14,
                vertical_alignment=(
                    ft.CrossAxisAlignment.STRETCH
                ),
            ),
        ),

        actions=[
            dialog_back_button,
            dialog_cancel_button,
            dialog_next_button,
            check_button,
            dialog_close_button,
        ],

        actions_alignment=(
            ft.MainAxisAlignment.END
        ),
    )


    def open_check_dialog(
        e=None,
    ):
        """
        Apertura explícita y estable del dialog.

        No dependemos de page.open() porque el ciclo del
        AlertDialog ha cambiado entre versiones de Flet.
        """

        dialog_message.visible = False

        dialog_last_result[
            "value"
        ] = None

        execution_mode.value = (
            "ONE_SHOT"
        )

        scheduler_settings.visible = (
            False
        )

        scheduler_interval_input.value = (
            "15"
        )

        scheduler_duration_input.value = (
            "60"
        )

        check_button.text = (
            "Lanzar comprobación"
        )

        # Primero registramos el diálogo en overlay.
        #
        # Así set_dialog_step() puede actualizar controles
        # que ya pertenecen al árbol visual de la página.
        if check_dialog not in page.overlay:
            page.overlay.append(
                check_dialog
            )

        check_dialog.open = True

        set_dialog_step(
            "profile"
        )

        _safe_page_update(
            page
        )


    open_check_button = ft.ElevatedButton(
        "Comprobar disponibilidad",
        bgcolor=Q_PRIMARY_2,
        color="#FFFFFF",
        on_click=open_check_dialog,
    )


    def dashboard_scroll_panel(
        *,
        title,
        subtitle_control,
        body,
        width=None,
        expand=False,
        footer=None,
    ):
        controls = [
            ft.Row(
                [
                    ft.Text(
                        title,
                        size=15,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY,
                        expand=True,
                    ),

                    subtitle_control,
                ],
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),

            ft.Divider(
                height=1,
            ),

            # Solo esta zona hace scroll.
            ft.Container(
                expand=True,
                content=body,
            ),
        ]

        if footer is not None:
            controls.append(
                footer
            )

        return ft.Container(
            width=width,
            expand=expand,
            padding=12,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            content=ft.Column(
                controls,
                spacing=8,
                expand=True,
            ),
        )


    dashboard_three_panel = ft.Row(
        [
            dashboard_scroll_panel(
                title="Monitorización por provincia",
                subtitle_control=(
                    province_monitor_count
                ),
                body=province_monitor_column,
                width=250,
            ),

            dashboard_scroll_panel(
                title="Historial de citas",
                subtitle_control=(
                    appointment_history_header
                ),
                body=appointment_history_column,
                expand=True,
                footer=(
                    appointment_pagination_host
                ),
            ),

            dashboard_scroll_panel(
                title="Historial de comprobaciones",
                subtitle_control=(
                    check_history_count
                ),
                body=check_history_column,
                width=320,
            ),
        ],
        spacing=12,
        expand=True,
        vertical_alignment=(
            ft.CrossAxisAlignment.STRETCH
        ),
    )


    persistent_state_card = ft.Container(
        padding=0,
        bgcolor=Q_BG,
        content=ft.Column(
            [
                ft.Text(
                    "Resultados guardados",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=Q_TEXT,
                ),

                ft.Text(
                    "Último estado y citas conocidas por oficina.",
                    color=Q_MUTED,
                    size=13,
                ),

                persistent_cards_column,
            ],
            spacing=12,
        ),
    )


    result_card = ft.Container(
        padding=18,
        bgcolor="#FFFFFF",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        content=ft.Column(
            [
                ft.Text(
                    "Resultado",
                    size=18,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                    color=Q_TEXT,
                ),

                ft.Row(
                    [
                        _status_box(
                            "Estado del portal",
                            portal_value,
                        ),

                        _status_box(
                            "Disponibilidad",
                            availability_value,
                        ),
                    ],
                    spacing=12,
                ),

                result_message,

                ft.Divider(),

                ft.Text(
                    "Diagnóstico técnico",
                    size=15,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                ),

                ft.Row(
                    [
                        ft.Text(
                            "Página:",
                            weight=ft.FontWeight.BOLD,
                        ),
                        diagnostic_page,
                    ]
                ),

                ft.Row(
                    [
                        ft.Text(
                            "Clase de resultado:",
                            weight=ft.FontWeight.BOLD,
                        ),
                        diagnostic_result_class,
                    ]
                ),

                ft.Row(
                    [
                        ft.Text(
                            "Support ID:",
                            weight=ft.FontWeight.BOLD,
                        ),
                        diagnostic_support_id,
                    ]
                ),

                ft.Row(
                    [
                        ft.Text(
                            "Error de navegación:",
                            weight=ft.FontWeight.BOLD,
                        ),
                        diagnostic_navigation_error,
                    ]
                ),

                ft.Row(
                    [
                        ft.Text(
                            "Comprobado:",
                            weight=ft.FontWeight.BOLD,
                        ),
                        diagnostic_checked_at,
                    ]
                ),

                ft.Divider(),

                ft.Text(
                    "Citas observadas",
                    size=15,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                ),

                appointments_column,
            ],
            spacing=12,
        ),
    )


    def dashboard_kpi(
        title,
        value_control,
        subtitle_control,
    ):
        return ft.Container(
            expand=True,
            height=112,
            padding=16,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            content=ft.Column(
                [
                    ft.Text(
                        title,
                        size=12,
                        color=Q_MUTED,
                        weight=ft.FontWeight.BOLD,
                    ),

                    value_control,

                    subtitle_control,
                ],
                spacing=6,
            ),
        )


    def clear_dashboard_filters(
        e=None,
    ):
        dashboard_province_filter.input.value = (
            "Todas"
        )

        dashboard_status_filter.input.value = (
            "Todos"
        )

        dashboard_search.value = ""

        appointment_history_page[
            "value"
        ] = 1

        refresh_persistent_cards()

        _safe_page_update(
            page
        )


    dashboard_filters = ft.Container(
        padding=12,
        bgcolor="#FFFFFF",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        content=ft.Row(
            [
                dashboard_province_filter.control,

                dashboard_status_filter.control,

                dashboard_search,

                ft.OutlinedButton(
                    "Limpiar",
                    on_click=(
                        clear_dashboard_filters
                    ),
                ),
            ],
            spacing=10,
        ),
    )



    return ft.Container(
        expand=True,
        bgcolor=Q_BG,
        padding=18,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    width=42,
                                    height=42,
                                    border_radius=12,
                                    bgcolor="#EAF3FF",
                                    alignment=ft.Alignment(
                                        0,
                                        0,
                                    ),
                                    content=ft.Icon(
                                        ft.Icons.CALENDAR_MONTH,
                                        color=Q_PRIMARY_2,
                                        size=22,
                                    ),
                                ),

                                ft.Column(
                                    [
                                        ft.Text(
                                            "Citas ICP Plus",
                                            size=28,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY,
                                        ),

                                        ft.Text(
                                            (
                                                "Consulta de disponibilidad "
                                                "y seguimiento persistente "
                                                "de citas."
                                            ),
                                            color=Q_MUTED,
                                            size=13,
                                        ),
                                    ],
                                    spacing=2,
                                ),
                            ],
                            spacing=10,
                            expand=True,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                        ),

                        open_check_button,
                    ],
                    alignment=(
                        ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                ),

                ft.Row(
                    [
                        dashboard_kpi(
                            "Estado del portal",
                            dashboard_portal_value,
                            dashboard_portal_subtitle,
                        ),

                        dashboard_kpi(
                            "Última comprobación",
                            dashboard_last_check_value,
                            dashboard_last_check_subtitle,
                        ),

                        dashboard_kpi(
                            "Citas detectadas",
                            dashboard_appointments_value,
                            dashboard_appointments_subtitle,
                        ),

                        dashboard_kpi(
                            "Provincias monitorizadas",
                            dashboard_provinces_value,
                            dashboard_provinces_subtitle,
                        ),
                    ],
                    spacing=10,
                ),

                dashboard_filters,


                dashboard_three_panel,
            ],
            spacing=14,
            expand=True,
        ),
    )

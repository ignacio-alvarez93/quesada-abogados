import flet as ft

from frontend.components import (
    app_table,
    empty_state,
    error_alert,
    filter_bar,
    metric_card,
    primary_button,
    secondary_button,
    select_input,
    text_input,
)
from frontend.components.listing.status_chip import (
    status_chip,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BG = "#F4F7FB"


CALL_STATUS_MAP = {
    "CREATED": (
        "Creada",
        "#F8FAFC",
        "#475569",
    ),
    "DIALING": (
        "Llamando",
        "#EFF8FF",
        "#175CD3",
    ),
    "RINGING": (
        "Entrando",
        "#EFF8FF",
        "#175CD3",
    ),
    "ANSWERED": (
        "Atendida",
        "#ECFDF3",
        "#027A48",
    ),
    "ENDED": (
        "Finalizada",
        "#ECFDF3",
        "#027A48",
    ),
    "MISSED": (
        "Perdida",
        "#FEF3F2",
        "#B42318",
    ),
    "REJECTED": (
        "Rechazada",
        "#FEF3F2",
        "#B42318",
    ),
    "BUSY": (
        "Ocupado",
        "#FFF7E6",
        "#B54708",
    ),
    "FAILED": (
        "Fallida",
        "#FEF3F2",
        "#B42318",
    ),
    "CANCELLED": (
        "Cancelada",
        "#F1F5F9",
        "#475569",
    ),
}


FOLLOW_UP_STATUS_MAP = {
    "PENDING": (
        "Pendiente de devolver",
        "#FFF7E6",
        "#B54708",
    ),
    "IN_PROGRESS": (
        "En devolución",
        "#EFF8FF",
        "#175CD3",
    ),
    "RESOLVED": (
        "Resuelto",
        "#ECFDF3",
        "#027A48",
    ),
}


CHANNEL_LABELS = {
    "WHATSAPP": "WhatsApp",
    "PHONE": "Teléfono",
}


DIRECTION_LABELS = {
    "INBOUND": "Entrante",
    "OUTBOUND": "Saliente",
}


def _format_duration(
    value,
):
    if value is None:
        return "—"

    try:
        seconds = max(
            0,
            int(value),
        )
    except Exception:
        return "—"

    hours = seconds // 3600

    minutes = (
        seconds % 3600
    ) // 60

    remaining = (
        seconds % 60
    )

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{remaining:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{remaining:02d}"
    )


def _format_timestamp(
    value,
):
    raw = str(
        value
        or ""
    ).strip()

    if not raw:
        return "—"

    try:
        date_part = raw[:10]

        time_part = (
            raw[11:16]
            if len(raw) >= 16
            else ""
        )

        year, month, day = (
            date_part.split(
                "-",
                2,
            )
        )

        return (
            f"{day}/{month}/{year}"
            + (
                f" {time_part}"
                if time_part
                else ""
            )
        )

    except Exception:
        return raw


def _direction_control(
    direction,
):
    normalized = str(
        direction
        or ""
    ).strip().upper()

    inbound = (
        normalized
        == "INBOUND"
    )

    return ft.Row(
        controls=[
            ft.Icon(
                (
                    ft.Icons.CALL_RECEIVED
                    if inbound
                    else ft.Icons.CALL_MADE
                ),
                size=16,
                color=(
                    "#B42318"
                    if inbound
                    else Q_PRIMARY
                ),
            ),
            ft.Text(
                DIRECTION_LABELS.get(
                    normalized,
                    normalized or "—",
                ),
                size=12,
                color=Q_PRIMARY_DARK,
            ),
        ],
        spacing=6,
        tight=True,
    )


def calls_view(
    page: ft.Page,
    *,
    call_service=None,
):
    """
    Registro omnicanal de llamadas.

    Reglas:
    - vista independiente de WhatsApp;
    - no contiene SQL;
    - no conoce repositories;
    - no conoce Selenium/CDP;
    - consume CommunicationCallService inyectado;
    - preparado para WhatsApp + telefonía futura.
    """

    state = {
        "items": [],
        "error": None,
    }

    search_input = text_input(
        "Buscar cliente, contacto o teléfono",
        width=440,
    )

    channel_filter = select_input(
        "Canal",
        [
            "Todos",
            "WhatsApp",
            "Teléfono",
        ],
        value="Todos",
        width=155,
    )

    direction_filter = select_input(
        "Dirección",
        [
            "Todas",
            "Entrantes",
            "Salientes",
        ],
        value="Todas",
        width=155,
    )

    status_filter = select_input(
        "Estado",
        [
            "Todos",
            "Llamando",
            "Entrando",
            "Atendida",
            "Finalizada",
            "Perdida",
            "Rechazada",
            "Ocupado",
            "Fallida",
            "Cancelada",
        ],
        value="Todos",
        width=165,
    )

    body = ft.Container(
        expand=True,
    )

    def selected_channel():
        return {
            "Todos": None,
            "WhatsApp": "WHATSAPP",
            "Teléfono": "PHONE",
        }.get(
            str(
                channel_filter.value
                or "Todos"
            )
        )

    def selected_direction():
        return {
            "Todas": None,
            "Entrantes": "INBOUND",
            "Salientes": "OUTBOUND",
        }.get(
            str(
                direction_filter.value
                or "Todas"
            )
        )

    def selected_status():
        return {
            "Todos": None,
            "Llamando": "DIALING",
            "Entrando": "RINGING",
            "Atendida": "ANSWERED",
            "Finalizada": "ENDED",
            "Perdida": "MISSED",
            "Rechazada": "REJECTED",
            "Ocupado": "BUSY",
            "Fallida": "FAILED",
            "Cancelada": "CANCELLED",
        }.get(
            str(
                status_filter.value
                or "Todos"
            )
        )

    def load_data():
        state["error"] = None

        if call_service is None:
            state["items"] = []
            state["error"] = (
                "El servicio de llamadas "
                "no está disponible."
            )
            return

        try:
            search = str(
                search_input.value
                or ""
            ).strip()

            state["items"] = list(
                call_service
                .list_call_overviews(
                    channel=(
                        selected_channel()
                    ),
                    direction=(
                        selected_direction()
                    ),
                    status=(
                        selected_status()
                    ),
                    search=(
                        search
                        or None
                    ),
                    limit=500,
                )
            )

        except Exception as exc:
            state["items"] = []
            state["error"] = str(
                exc
            )

    def status_control(
        item,
    ):
        normalized = str(
            item.status
            or ""
        ).strip().upper()

        return status_chip(
            normalized,
            status_map=(
                CALL_STATUS_MAP
            ),
            compact=True,
        )

    def follow_up_control(
        item,
    ):
        normalized = str(
            item.follow_up_status
            or ""
        ).strip().upper()

        if not normalized:
            return ft.Text(
                "—",
                size=12,
                color=Q_MUTED,
            )

        return status_chip(
            normalized,
            status_map=(
                FOLLOW_UP_STATUS_MAP
            ),
            compact=True,
        )

    def build_table():
        items = list(
            state.get(
                "items"
            )
            or []
        )

        if not items:
            return empty_state(
                "No hay llamadas "
                "para los filtros actuales"
            )

        headers = [
            {
                "key": "Contacto",
                "label": "Cliente / contacto",
                "width": 300,
            },
            {
                "key": "Telefono",
                "label": "Teléfono",
                "width": 150,
            },
            {
                "key": "Canal",
                "label": "Canal",
                "width": 110,
            },
            {
                "key": "Direccion",
                "label": "Dirección",
                "width": 125,
            },
            {
                "key": "Estado",
                "label": "Estado",
                "width": 135,
            },
            {
                "key": "Fecha",
                "label": "Fecha / hora",
                "width": 165,
            },
            {
                "key": "Duracion",
                "label": "Conversación",
                "width": 125,
            },
            {
                "key": "Seguimiento",
                "label": "Seguimiento",
                "width": 210,
            },
        ]

        rows = []

        for item in items:
            channel = str(
                item.channel
                or ""
            ).strip().upper()

            activity_at = (
                item.activity_at
                or item.started_at
                or item.created_at
            )

            name_control = ft.Column(
                controls=[
                    ft.Text(
                        (
                            item.display_name
                            or item.phone_number
                            or "Llamada"
                        ),
                        size=12,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                        overflow=(
                            ft.TextOverflow.ELLIPSIS
                        ),
                    ),
                    *(
                        [
                            ft.Text(
                                "Cliente CRM vinculado",
                                size=10,
                                color="#027A48",
                            )
                        ]
                        if item.client_id
                        is not None
                        else []
                    ),
                ],
                spacing=2,
            )

            rows.append(
                [
                    name_control,
                    item.phone_number
                    or "—",
                    CHANNEL_LABELS.get(
                        channel,
                        channel or "—",
                    ),
                    _direction_control(
                        item.direction
                    ),
                    status_control(
                        item
                    ),
                    _format_timestamp(
                        activity_at
                    ),
                    _format_duration(
                        item.talk_duration_seconds
                    ),
                    follow_up_control(
                        item
                    ),
                ]
            )

        return app_table(
            headers,
            rows,
            height=550,
        )

    def build_body():
        items = list(
            state.get(
                "items"
            )
            or []
        )

        error = state.get(
            "error"
        )

        missed = sum(
            1
            for item in items
            if str(
                item.status
                or ""
            ).upper()
            == "MISSED"
        )

        pending = sum(
            1
            for item in items
            if str(
                item.follow_up_status
                or ""
            ).upper()
            == "PENDING"
        )

        whatsapp = sum(
            1
            for item in items
            if str(
                item.channel
                or ""
            ).upper()
            == "WHATSAPP"
        )

        metrics = ft.Row(
            controls=[
                metric_card(
                    "Llamadas",
                    len(items),
                ),
                metric_card(
                    "WhatsApp",
                    whatsapp,
                ),
                metric_card(
                    "Perdidas",
                    missed,
                ),
                metric_card(
                    "Pendientes devolver",
                    pending,
                ),
            ],
            spacing=10,
            wrap=True,
        )

        filters = filter_bar(
            channel_filter,
            search_input,
            actions=[
                direction_filter,
                status_filter,
                secondary_button(
                    "Buscar",
                    refresh,
                ),
                secondary_button(
                    "Limpiar",
                    clear_filters,
                ),
            ],
        )

        content = (
            error_alert(
                error
            )
            if error
            else build_table()
        )

        return ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Llamadas",
                                        size=28,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            "Registro central de llamadas "
                                            "de WhatsApp y telefonía"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            primary_button(
                                "Actualizar",
                                refresh,
                            ),
                        ],
                        spacing=10,
                    ),
                    metrics,
                    filters,
                    ft.Container(
                        content=content,
                    ),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )

    def refresh(
        e=None,
    ):
        load_data()
        body.content = build_body()

        try:
            body.update()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    def clear_filters(
        e=None,
    ):
        search_input.value = ""
        channel_filter.value = "Todos"
        direction_filter.value = "Todas"
        status_filter.value = "Todos"

        refresh()

    search_input.on_submit = refresh
    channel_filter.on_change = refresh
    direction_filter.on_change = refresh
    status_filter.on_change = refresh

    load_data()
    body.content = build_body()

    return body

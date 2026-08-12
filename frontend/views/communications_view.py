import math

import flet as ft

from backend.services.communication_service import (
    CommunicationService,
)
from frontend.components.app_autocomplete import (
    AppAutocomplete,
)
from frontend.components.app_button import (
    primary_button,
    secondary_button,
)
from frontend.components.app_card import (
    metric_card,
)
from frontend.components.app_empty_state import (
    empty_state,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D8E2EE"
Q_MUTED = "#64748B"
Q_TEXT = "#0F172A"
Q_BG = "#F6F8FC"
Q_WHITE = "#FFFFFF"

LINKED_BG = "#ECFDF3"
LINKED_FG = "#027A48"

UNLINKED_BG = "#FFF7E6"
UNLINKED_FG = "#B54708"

SELECTED_BG = "#EAF3FF"


CHANNEL_FILTER_VALUES = {
    "WhatsApp": "WHATSAPP",
}

LINKAGE_FILTER_VALUES = {
    "Todas": "ALL",
    "Vinculadas": "LINKED",
    "Sin vincular": "UNLINKED",
}


def communications_view(
    page: ft.Page,
    *,
    service=None,
    initial_thread_id=None,
    on_open_cliente=None,
    on_open_expediente=None,
    on_create_expediente=None,
    on_create_task=None,
    on_create_alert=None,
):
    """
    Vista principal de Comunicaciones.

    Reglas arquitectónicas:
    - no contiene SQL;
    - no conoce SQLite;
    - no importa repositories concretos;
    - consume únicamente CommunicationService.

    `service` es inyectable para mantener la vista
    desacoplada del backend físico y facilitar
    PostgreSQL / Supabase en el futuro.
    """
    communication_service = (
        service
        or CommunicationService()
    )

    state = {
        "summary": {},
        "items": [],
        "selected_thread_id": (
            int(initial_thread_id)
            if initial_thread_id
            else None
        ),
        "context": None,
        "context_error": None,
        "messages": [],
        "messages_error": None,
        "search": "",
        "linkage": "ALL",
        "page": 1,
        "page_size": 20,
        "error": None,
    }

    content_area = ft.Container(
        expand=True,
    )

    search_input = ft.TextField(
        hint_text=(
            "Buscar conversación / teléfono / cliente"
        ),
        prefix_icon=ft.Icons.SEARCH,
        border_radius=10,
        border_color="#CBD5E1",
        focused_border_color=Q_PRIMARY,
        content_padding=ft.padding.symmetric(
            horizontal=14,
            vertical=10,
        ),
        expand=True,
    )

    channel_filter = AppAutocomplete(
        page=page,
        label="Canal",
        options=list(
            CHANNEL_FILTER_VALUES.keys()
        ),
        value="WhatsApp",
        width=175,
        max_results=4,
        allow_free_text=False,
        show_empty=False,
        icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
    )

    linkage_filter = AppAutocomplete(
        page=page,
        label="Vinculación",
        options=list(
            LINKAGE_FILTER_VALUES.keys()
        ),
        value="Todas",
        width=205,
        max_results=4,
        allow_free_text=False,
        show_empty=False,
        icon=ft.Icons.LINK,
    )

    def selected_channel():
        label = str(
            channel_filter.input.value
            or "WhatsApp"
        ).strip()

        return (
            CHANNEL_FILTER_VALUES.get(
                label,
                "WHATSAPP",
            )
        )

    def selected_linkage():
        label = str(
            linkage_filter.input.value
            or "Todas"
        ).strip()

        return (
            LINKAGE_FILTER_VALUES.get(
                label,
                "ALL",
            )
        )

    def _show_message(
        message,
        *,
        error=False,
    ):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(
                str(message),
            ),
            bgcolor=(
                "#FEE4E2"
                if error
                else "#ECFDF3"
            ),
        )

        page.snack_bar.open = True

        try:
            page.update()
        except Exception:
            pass

    def _safe_update():
        try:
            content_area.content = (
                build_content()
            )

            page.update()

        except Exception as exc:
            state["error"] = str(exc)

            content_area.content = (
                build_error_content(
                    str(exc)
                )
            )

            try:
                page.update()
            except Exception:
                pass

    def _display_name(item):
        return (
            item.client_name
            or item.external_display_name
            or item.external_address
            or "Conversación sin nombre"
        )

    def _secondary_name(item):
        if (
            item.client_name
            and item.external_display_name
            and (
                item.client_name
                != item.external_display_name
            )
        ):
            return (
                item.external_display_name
            )

        return ""

    def _is_linked(item):
        return (
            item.client_id
            is not None
        )

    def _status_badge(item):
        linked = _is_linked(
            item
        )

        return ft.Container(
            bgcolor=(
                LINKED_BG
                if linked
                else UNLINKED_BG
            ),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=4,
            ),
            content=ft.Text(
                (
                    "VINCULADO"
                    if linked
                    else "SIN VINCULAR"
                ),
                size=9,
                weight=ft.FontWeight.BOLD,
                color=(
                    LINKED_FG
                    if linked
                    else UNLINKED_FG
                ),
            ),
        )

    def _avatar(
        item,
        *,
        size=42,
    ):
        name = _display_name(
            item
        ).strip()

        initials = "".join(
            part[0]
            for part in name.split()[:2]
            if part
        ).upper()

        if not initials:
            initials = "?"

        size = max(
            30,
            int(size),
        )

        return ft.Container(
            width=size,
            height=size,
            border_radius=(
                size / 2
            ),
            bgcolor=(
                "#DCEBFF"
                if _is_linked(item)
                else "#EEF2F6"
            ),
            alignment=ft.Alignment(
                0,
                0,
            ),
            content=ft.Text(
                initials,
                size=13,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
        )

    def selected_item():
        selected_id = state.get(
            "selected_thread_id"
        )

        for item in (
            state.get("items")
            or []
        ):
            if (
                item.thread_id
                == selected_id
            ):
                return item

        items = (
            state.get("items")
            or []
        )

        return (
            items[0]
            if items
            else None
        )

    def load_thread_context():
        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            state["context"] = None
            state["context_error"] = None
            return

        try:
            state["context"] = (
                communication_service
                .get_thread_context(
                    int(thread_id)
                )
            )

            state["context_error"] = None

        except Exception as exc:
            state["context"] = None
            state["context_error"] = str(
                exc
            )

    def load_thread_messages():
        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            state["messages"] = []
            state["messages_error"] = None
            return

        try:
            state["messages"] = list(
                communication_service
                .list_thread_messages(
                    int(thread_id),
                    limit=500,
                )
                or []
            )

            state["messages_error"] = None

        except Exception as exc:
            state["messages"] = []
            state["messages_error"] = str(
                exc
            )

    def select_thread(
        thread_id,
    ):
        state[
            "selected_thread_id"
        ] = int(
            thread_id
        )

        load_thread_context()
        load_thread_messages()

        _safe_update()

    def load_data(
        *,
        preserve_selection=True,
    ):
        selected_before = (
            state.get(
                "selected_thread_id"
            )
            if preserve_selection
            else None
        )

        try:
            result = (
                communication_service
                .list_thread_overviews(
                    channel=(
                        selected_channel()
                    ),
                    linkage=(
                        selected_linkage()
                    ),
                    search=(
                        search_input.value
                        or ""
                    ),
                    include_archived=False,
                    limit=5000,
                )
            )

            state[
                "summary"
            ] = (
                result.get(
                    "summary"
                )
                or {}
            )

            state[
                "items"
            ] = list(
                result.get(
                    "items"
                )
                or []
            )

            state[
                "error"
            ] = None

            state[
                "search"
            ] = (
                search_input.value
                or ""
            )

            state[
                "linkage"
            ] = (
                selected_linkage()
            )

            valid_ids = {
                item.thread_id
                for item in state[
                    "items"
                ]
            }

            if (
                selected_before
                in valid_ids
            ):
                state[
                    "selected_thread_id"
                ] = (
                    selected_before
                )

            elif state["items"]:
                state[
                    "selected_thread_id"
                ] = (
                    state["items"][
                        0
                    ].thread_id
                )

            else:
                state[
                    "selected_thread_id"
                ] = None

            selected_id = state.get(
                "selected_thread_id"
            )

            if selected_id is not None:
                selected_index = next(
                    (
                        index
                        for index, item
                        in enumerate(
                            state["items"]
                        )
                        if item.thread_id
                        == selected_id
                    ),
                    None,
                )

                if selected_index is not None:
                    state["page"] = (
                        selected_index
                        // int(
                            state[
                                "page_size"
                            ]
                        )
                    ) + 1

            load_thread_context()
            load_thread_messages()

            total_pages = max(
                1,
                math.ceil(
                    len(
                        state["items"]
                    )
                    / state[
                        "page_size"
                    ]
                ),
            )

            state["page"] = max(
                1,
                min(
                    int(
                        state.get(
                            "page"
                        )
                        or 1
                    ),
                    total_pages,
                ),
            )

        except Exception as exc:
            state["summary"] = {}
            state["items"] = []
            state["context"] = None
            state["context_error"] = None
            state["error"] = str(
                exc
            )

    def refresh(
        e=None,
    ):
        state["page"] = 1

        load_data(
            preserve_selection=True,
        )

        _safe_update()

    def reconcile_links(
        e=None,
    ):
        try:
            result = (
                communication_service
                .backfill_whatsapp_thread_matches(
                    limit=5000,
                )
            )

            summary = (
                result.get(
                    "summary"
                )
                or {}
            )

            load_data(
                preserve_selection=True,
            )

            _safe_update()

            _show_message(
                (
                    "Reconciliación completada · "
                    f"{summary.get('updated', 0)} "
                    "vínculo(s) actualizado(s)"
                )
            )

        except Exception as exc:
            _show_message(
                (
                    "No se pudo reconciliar: "
                    f"{exc}"
                ),
                error=True,
            )

    def placeholder_sync(
        e=None,
    ):
        _show_message(
            (
                "La sincronización desde WhatsApp Web "
                "se integrará en la siguiente fase."
            )
        )

    def clear_filters(
        e=None,
    ):
        search_input.value = ""
        linkage_filter.input.value = (
            "Todas"
        )

        channel_filter.input.value = (
            "WhatsApp"
        )

        state["page"] = 1

        refresh()

    def previous_page(
        e=None,
    ):
        if state["page"] > 1:
            state["page"] -= 1
            _safe_update()

    def next_page(
        e=None,
    ):
        total = len(
            state.get(
                "items"
            )
            or []
        )

        pages = max(
            1,
            math.ceil(
                total
                / state[
                    "page_size"
                ]
            ),
        )

        if state["page"] < pages:
            state["page"] += 1
            _safe_update()

    def build_error_content(
        message,
    ):
        return ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Comunicaciones",
                        size=28,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Container(
                        padding=18,
                        bgcolor="#FEF3F2",
                        border_radius=12,
                        border=ft.border.all(
                            1,
                            "#FDA29B",
                        ),
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    (
                                        "No se pudo cargar "
                                        "Comunicaciones"
                                    ),
                                    size=16,
                                    weight=(
                                        ft.FontWeight.BOLD
                                    ),
                                    color="#B42318",
                                ),
                                ft.Text(
                                    str(
                                        message
                                    ),
                                    size=12,
                                    color=Q_TEXT,
                                    selectable=True,
                                ),
                            ],
                            spacing=8,
                        ),
                    ),
                ],
                spacing=14,
            ),
        )

    def set_linkage_filter(
        linkage,
    ):
        normalized = str(
            linkage
            or "ALL"
        ).strip().upper()

        label_by_value = {
            value: label
            for label, value
            in LINKAGE_FILTER_VALUES.items()
        }

        label = (
            label_by_value.get(
                normalized,
                "Todas",
            )
        )

        linkage_filter.input.value = (
            label
        )

        state[
            "linkage"
        ] = normalized

        state[
            "page"
        ] = 1

        load_data(
            preserve_selection=True,
        )

        _safe_update()

    def build_linkage_pill(
        label,
        value,
    ):
        selected = (
            state.get(
                "linkage",
                "ALL",
            )
            == value
        )

        if value == "LINKED":
            inactive_bg = "#ECFDF3"
            inactive_fg = "#027A48"
            inactive_border = "#ABEFC6"

        elif value == "UNLINKED":
            inactive_bg = "#FFF7E6"
            inactive_fg = "#B54708"
            inactive_border = "#FEDF89"

        else:
            inactive_bg = "#F8FAFC"
            inactive_fg = Q_PRIMARY_DARK
            inactive_border = Q_BORDER

        return ft.Container(
            bgcolor=(
                Q_PRIMARY
                if selected
                else inactive_bg
            ),
            border=ft.border.all(
                1,
                (
                    Q_PRIMARY
                    if selected
                    else inactive_border
                ),
            ),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=11,
                vertical=6,
            ),
            ink=True,
            on_click=(
                lambda e,
                linkage=value:
                    set_linkage_filter(
                        linkage
                    )
            ),
            content=ft.Text(
                label,
                size=10,
                weight=ft.FontWeight.W_600,
                color=(
                    Q_WHITE
                    if selected
                    else inactive_fg
                ),
            ),
        )

    def build_conversation_card(
        item,
    ):
        selected = (
            item.thread_id
            == state.get(
                "selected_thread_id"
            )
        )

        preview = (
            item.last_message_preview
            or (
                "Sin mensajes sincronizados"
                if not item.message_count
                else "Mensaje disponible"
            )
        )

        secondary = _secondary_name(
            item
        )

        return ft.Container(
            bgcolor=(
                SELECTED_BG
                if selected
                else Q_WHITE
            ),
            border=ft.border.all(
                (
                    1.5
                    if selected
                    else 1
                ),
                (
                    "#7EB5F5"
                    if selected
                    else Q_BORDER
                ),
            ),
            border_radius=10,
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=8,
            ),
            ink=True,
            on_click=(
                lambda e,
                thread_id=item.thread_id:
                    select_thread(
                        thread_id
                    )
            ),
            content=ft.Row(
                controls=[
                    _avatar(
                        item,
                        size=36,
                    ),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        _display_name(
                                            item
                                        ),
                                        size=12,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                        expand=True,
                                        overflow=(
                                            ft.TextOverflow.ELLIPSIS
                                        ),
                                    ),
                                    _status_badge(
                                        item
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                (
                                    item.external_address
                                    or "Sin teléfono"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            (
                                ft.Text(
                                    secondary,
                                    size=10,
                                    color=Q_MUTED,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                )
                                if secondary
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            ft.Text(
                                preview,
                                size=10,
                                color="#475467",
                                max_lines=1,
                                overflow=(
                                    ft.TextOverflow.ELLIPSIS
                                ),
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.START
                ),
            ),
        )

    def build_conversation_list():
        items = (
            state.get(
                "items"
            )
            or []
        )

        page_size = int(
            state[
                "page_size"
            ]
        )

        current_page = int(
            state[
                "page"
            ]
        )

        total_pages = max(
            1,
            math.ceil(
                len(items)
                / page_size
            ),
        )

        start = (
            current_page - 1
        ) * page_size

        end = start + page_size

        visible = items[
            start:end
        ]

        cards = [
            build_conversation_card(
                item
            )
            for item in visible
        ]

        if not cards:
            list_content = empty_state(
                (
                    "No hay conversaciones "
                    "para los filtros actuales"
                )
            )

        else:
            list_content = ft.Column(
                controls=cards,
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

        return ft.Container(
            width=385,
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Conversaciones",
                                size=15,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            ft.Text(
                                (
                                    f"{len(items)}"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            build_linkage_pill(
                                "Todas",
                                "ALL",
                            ),
                            build_linkage_pill(
                                "Vinculadas",
                                "LINKED",
                            ),
                            build_linkage_pill(
                                "Sin vincular",
                                "UNLINKED",
                            ),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                    list_content,
                    ft.Divider(
                        height=1,
                        color="#E4E7EC",
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                (
                                    f"Página "
                                    f"{current_page} "
                                    f"de {total_pages}"
                                ),
                                size=10,
                                color=Q_MUTED,
                                expand=True,
                            ),
                            ft.TextButton(
                                "<",
                                on_click=previous_page,
                                disabled=(
                                    current_page
                                    <= 1
                                ),
                            ),
                            ft.TextButton(
                                ">",
                                on_click=next_page,
                                disabled=(
                                    current_page
                                    >= total_pages
                                ),
                            ),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
        )

    def _message_type(message):
        metadata = (
            message.metadata
            or {}
        )

        return str(
            metadata.get(
                "message_type"
            )
            or "TEXT"
        ).strip().upper()


    def _message_body(message):
        body = str(
            message.body_text
            or ""
        ).strip()

        message_type = _message_type(
            message
        )

        if body:
            return body

        if message_type == "STICKER":
            return "🖼 Sticker"

        if message_type == "UNKNOWN_MEDIA":
            return "📎 Contenido multimedia"

        return "Mensaje sin contenido"


    def _message_time(message):
        value = str(
            message.provider_timestamp
            or ""
        ).strip()

        if not value:
            return ""

        if (
            len(value) >= 16
            and "T" in value
        ):
            return value[11:16]

        return value


    def _message_status_symbol(message):
        if str(
            message.direction
            or ""
        ).strip().upper() != "OUTBOUND":
            return ""

        status = str(
            message.status
            or ""
        ).strip().upper()

        if status == "READ":
            return "✓✓"

        if status == "DELIVERED":
            return "✓✓"

        if status in (
            "SENT",
            "SENDING",
            "QUEUED",
        ):
            return "✓"

        return ""


    def _build_message_bubble(
        message,
    ):
        outbound = (
            str(
                message.direction
                or ""
            ).strip().upper()
            == "OUTBOUND"
        )

        footer_controls = []

        timestamp = _message_time(
            message
        )

        if timestamp:
            footer_controls.append(
                ft.Text(
                    timestamp,
                    size=9,
                    color=Q_MUTED,
                )
            )

        status_symbol = (
            _message_status_symbol(
                message
            )
        )

        if status_symbol:
            footer_controls.append(
                ft.Text(
                    status_symbol,
                    size=10,
                    color=Q_PRIMARY,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                )
            )

        bubble = ft.Container(
            width=360,
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=9,
            ),
            bgcolor=(
                "#EAF3FF"
                if outbound
                else Q_WHITE
            ),
            border=ft.border.all(
                1,
                (
                    "#C7DCF8"
                    if outbound
                    else Q_BORDER
                ),
            ),
            border_radius=12,
            content=ft.Column(
                controls=[
                    ft.Text(
                        _message_body(
                            message
                        ),
                        size=12,
                        color=Q_TEXT,
                        selectable=True,
                    ),
                    ft.Row(
                        controls=(
                            footer_controls
                        ),
                        alignment=(
                            ft.MainAxisAlignment.END
                        ),
                        spacing=4,
                    ),
                ],
                spacing=5,
            ),
        )

        return ft.Row(
            controls=[
                bubble,
            ],
            alignment=(
                ft.MainAxisAlignment.END
                if outbound
                else ft.MainAxisAlignment.START
            ),
        )


    def _build_message_history():
        error = state.get(
            "messages_error"
        )

        if error:
            return ft.Container(
                expand=True,
                alignment=ft.Alignment(
                    0,
                    0,
                ),
                content=ft.Column(
                    controls=[
                        ft.Icon(
                            ft.Icons.ERROR_OUTLINE,
                            color="#B42318",
                            size=30,
                        ),
                        ft.Text(
                            "No se pudo cargar el historial",
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color="#B42318",
                        ),
                        ft.Text(
                            str(error),
                            size=10,
                            color=Q_MUTED,
                            text_align=(
                                ft.TextAlign.CENTER
                            ),
                        ),
                    ],
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                    spacing=7,
                ),
            )

        messages = list(
            state.get(
                "messages"
            )
            or []
        )

        if not messages:
            return ft.Container(
                expand=True,
                alignment=ft.Alignment(
                    0,
                    0,
                ),
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "💬",
                            size=40,
                        ),
                        ft.Text(
                            "No hay mensajes sincronizados todavía",
                            size=15,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "La conversación está registrada, "
                                "pero todavía no contiene historial."
                            ),
                            size=11,
                            color=Q_MUTED,
                            text_align=(
                                ft.TextAlign.CENTER
                            ),
                        ),
                    ],
                    spacing=7,
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                    alignment=(
                        ft.MainAxisAlignment.CENTER
                    ),
                ),
            )

        return ft.Column(
            controls=[
                _build_message_bubble(
                    message
                )
                for message in messages
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )


    def _disabled_send_button():
        button = primary_button(
            "Enviar",
            None,
        )

        button.disabled = True

        return button


    def build_chat_panel():
        item = selected_item()

        if not item:
            return ft.Container(
                expand=True,
                bgcolor=Q_WHITE,
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=20,
                content=empty_state(
                    "Selecciona una conversación"
                ),
            )

        linked = _is_linked(
            item
        )

        return ft.Container(
            expand=True,
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            content=ft.Column(
                controls=[
                    ft.Container(
                        padding=16,
                        border=ft.border.only(
                            bottom=ft.BorderSide(
                                1,
                                Q_BORDER,
                            )
                        ),
                        content=ft.Row(
                            controls=[
                                _avatar(
                                    item
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            _display_name(
                                                item
                                            ),
                                            size=16,
                                            weight=(
                                                ft.FontWeight.BOLD
                                            ),
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Row(
                                            controls=[
                                                ft.Text(
                                                    (
                                                        item.external_address
                                                        or "Sin teléfono"
                                                    ),
                                                    size=11,
                                                    color=Q_MUTED,
                                                ),
                                                ft.Text(
                                                    "•",
                                                    color=Q_MUTED,
                                                ),
                                                ft.Text(
                                                    (
                                                        item.channel
                                                        or "WHATSAPP"
                                                    ),
                                                    size=11,
                                                    color=Q_MUTED,
                                                ),
                                                _status_badge(
                                                    item
                                                ),
                                            ],
                                            spacing=7,
                                        ),
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        padding=20,
                        bgcolor="#FAFBFD",
                        content=(
                            _build_message_history()
                        ),
                    ),
                    ft.Container(
                        padding=14,
                        border=ft.border.only(
                            top=ft.BorderSide(
                                1,
                                Q_BORDER,
                            )
                        ),
                        content=ft.Row(
                            controls=[
                                ft.TextField(
                                    hint_text=(
                                        "Escribir mensaje..."
                                    ),
                                    disabled=True,
                                    border_radius=10,
                                    expand=True,
                                ),
                                _disabled_send_button(),
                            ],
                            spacing=10,
                        ),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
        )

    def current_return_context():
        return {
            "view": "WhatsApp",
            "thread_id": state.get(
                "selected_thread_id"
            ),
        }

    def build_context_panel():
        item = selected_item()

        if not item:
            return ft.Container(
                width=310,
            )

        context = state.get(
            "context"
        )

        context_error = state.get(
            "context_error"
        )

        linked = _is_linked(
            item
        )

        def context_row(
            label,
            value,
        ):
            return ft.Row(
                controls=[
                    ft.Text(
                        label,
                        size=10,
                        color=Q_MUTED,
                        width=78,
                    ),
                    ft.Text(
                        str(
                            value
                            or "-"
                        ),
                        size=10,
                        color=Q_TEXT,
                        weight=ft.FontWeight.W_600,
                        expand=True,
                        overflow=(
                            ft.TextOverflow.ELLIPSIS
                        ),
                    ),
                ],
                spacing=8,
                vertical_alignment=(
                    ft.CrossAxisAlignment.START
                ),
            )

        if context_error:
            contact_content = [
                ft.Text(
                    "Resumen contacto",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Container(
                    padding=10,
                    border_radius=10,
                    bgcolor="#FEF3F2",
                    content=ft.Text(
                        (
                            "No se pudo cargar el "
                            "contexto del cliente."
                        ),
                        size=10,
                        color="#B42318",
                    ),
                ),
            ]

        elif (
            context
            and context.client
        ):
            client = context.client

            contact_content = [
                ft.Row(
                    controls=[
                        ft.Text(
                            "Resumen contacto",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                            expand=True,
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.OPEN_IN_NEW,
                                    tooltip=(
                                        "Abrir ficha del cliente"
                                    ),
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_open_cliente(
                                                client_id,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_open_cliente
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=(
                                        ft.Icons
                                        .CREATE_NEW_FOLDER_OUTLINED
                                    ),
                                    tooltip="Crear expediente",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_expediente(
                                                client_id,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_expediente
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.TASK_ALT,
                                    tooltip="Crear tarea",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_task(
                                                client_id,
                                                None,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_task
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=(
                                        ft.Icons
                                        .NOTIFICATIONS_NONE
                                    ),
                                    tooltip="Crear aviso",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_alert(
                                                client_id,
                                                None,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_alert
                            else []
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            width=38,
                            height=38,
                            border_radius=19,
                            bgcolor="#EAF3FF",
                            alignment=ft.Alignment(
                                0,
                                0,
                            ),
                            content=ft.Text(
                                "".join(
                                    part[0]
                                    for part
                                    in (
                                        client.full_name
                                        or "CL"
                                    ).split()[:2]
                                    if part
                                ).upper()
                                or "CL",
                                size=12,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    client.full_name,
                                    size=12,
                                    weight=(
                                        ft.FontWeight.BOLD
                                    ),
                                    color=Q_PRIMARY_DARK,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                ),
                                ft.Text(
                                    (
                                        client.nationality
                                        or "Nacionalidad -"
                                    ),
                                    size=10,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=9,
                ),
                ft.Divider(
                    height=1,
                    color="#E4E7EC",
                ),
                context_row(
                    "Documento",
                    client.document,
                ),
                context_row(
                    "Teléfono",
                    client.phone,
                ),
                context_row(
                    "Email",
                    client.email,
                ),
                context_row(
                    "Estado",
                    client.status,
                ),
            ]

        else:
            contact_content = [
                ft.Text(
                    "Resumen contacto",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Row(
                    controls=[
                        _status_badge(
                            item
                        ),
                    ],
                ),
                ft.Text(
                    (
                        "No existe ningún cliente CRM "
                        "asociado a esta conversación."
                    ),
                    size=10,
                    color=Q_MUTED,
                ),
                context_row(
                    "WhatsApp",
                    (
                        item.external_address
                        or "-"
                    ),
                ),
                context_row(
                    "Nombre",
                    (
                        item.external_display_name
                        or "-"
                    ),
                ),
            ]

        contact_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=contact_content,
                spacing=8,
            ),
        )

        expedients = (
            list(
                context.expedients
            )
            if (
                context
                and context.client
            )
            else []
        )

        expedient_controls = []

        for expedient in expedients:
            title = (
                expedient.number
                or (
                    f"Expediente "
                    f"{expedient.expedient_id}"
                )
            )

            type_text = " · ".join(
                value
                for value in (
                    expedient.type_name,
                    expedient.subtype_name,
                )
                if value
            )

            status_controls = []

            if (
                expedient.documentary_status
            ):
                status_controls.append(
                    ft.Text(
                        expedient.documentary_status,
                        size=9,
                        color="#175CD3",
                        weight=ft.FontWeight.W_600,
                    )
                )

            if (
                expedient.administrative_status
            ):
                status_controls.append(
                    ft.Text(
                        expedient.administrative_status,
                        size=9,
                        color="#475467",
                        weight=ft.FontWeight.W_600,
                    )
                )

            expedient_controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    bgcolor="#F8FAFC",
                    border=ft.border.all(
                        1,
                        "#E4E7EC",
                    ),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        title,
                                        size=11,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                        expand=True,
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .OPEN_IN_NEW
                                                ),
                                                tooltip=(
                                                    "Abrir ficha "
                                                    "del expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_open_expediente(
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_open_expediente
                                        else []
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .TASK_ALT
                                                ),
                                                tooltip=(
                                                    "Crear tarea "
                                                    "para este expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    client_id=(
                                                        context
                                                        .client
                                                        .client_id
                                                    ),
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_create_task(
                                                            client_id,
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_create_task
                                        else []
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .NOTIFICATIONS_NONE
                                                ),
                                                tooltip=(
                                                    "Crear aviso "
                                                    "para este expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    client_id=(
                                                        context
                                                        .client
                                                        .client_id
                                                    ),
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_create_alert(
                                                            client_id,
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_create_alert
                                        else []
                                    ),
                                ],
                                spacing=2,
                            ),
                            (
                                ft.Text(
                                    expedient.family_name,
                                    size=9,
                                    color=Q_MUTED,
                                )
                                if expedient.family_name
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            (
                                ft.Text(
                                    type_text,
                                    size=10,
                                    color=Q_TEXT,
                                    max_lines=2,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                )
                                if type_text
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            *status_controls,
                        ],
                        spacing=3,
                    ),
                )
            )

        if not expedient_controls:
            expedient_controls.append(
                ft.Text(
                    (
                        "No hay expedientes activos "
                        "para este cliente."
                        if linked
                        else (
                            "Vincula primero la conversación "
                            "con un cliente."
                        )
                    ),
                    size=10,
                    color=Q_MUTED,
                )
            )

        expedients_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Expedientes activos",
                                size=13,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            ft.Text(
                                str(
                                    len(
                                        expedients
                                    )
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    *expedient_controls,
                ],
                spacing=8,
            ),
        )

        return ft.Container(
            width=310,
            content=ft.Column(
                controls=[
                    contact_card,
                    expedients_card,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

    def build_filters():
        search_input.on_submit = (
            refresh
        )

        channel_filter.on_select = (
            lambda value:
                refresh()
        )

        linkage_filter.on_select = (
            lambda value:
                set_linkage_filter(
                    selected_linkage()
                )
        )

        return ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=12,
            content=ft.Row(
                controls=[
                    search_input,
                    channel_filter.control,
                    linkage_filter.control,
                    secondary_button(
                        "Buscar",
                        refresh,
                    ),
                    secondary_button(
                        "Limpiar",
                        clear_filters,
                    ),
                ],
                spacing=10,
            ),
        )

    def build_content():
        if state.get(
            "error"
        ):
            return build_error_content(
                state[
                    "error"
                ]
            )

        summary = (
            state.get(
                "summary"
            )
            or {}
        )

        return ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=ft.padding.only(
                left=14,
                top=12,
                right=14,
                bottom=12,
            ),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Comunicaciones",
                                        size=28,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            "Gestión operativa de "
                                            "conversaciones, WhatsApp "
                                            "y seguimiento con clientes"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            secondary_button(
                                "Sincronizar WhatsApp",
                                placeholder_sync,
                            ),
                            secondary_button(
                                "Reconciliar vínculos",
                                reconcile_links,
                            ),
                            primary_button(
                                "Actualizar",
                                refresh,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        controls=[
                            metric_card(
                                "Conversaciones",
                                summary.get(
                                    "total",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "Vinculadas",
                                summary.get(
                                    "linked",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "Sin vincular",
                                summary.get(
                                    "unlinked",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "WhatsApp",
                                summary.get(
                                    "whatsapp",
                                    0,
                                ),
                                width=205,
                            ),
                        ],
                        spacing=12,
                    ),
                    build_filters(),
                    ft.Container(
                        expand=True,
                        content=ft.Row(
                            controls=[
                                build_conversation_list(),
                                build_chat_panel(),
                                build_context_panel(),
                            ],
                            spacing=12,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.START
                            ),
                        ),
                    ),
                ],
                spacing=12,
                expand=True,
            ),
        )

    load_data(
        preserve_selection=True,
    )

    content_area.content = (
        build_content()
    )

    return content_area

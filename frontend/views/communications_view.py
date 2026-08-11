import math

import flet as ft

from backend.services.communication_service import (
    CommunicationService,
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


def communications_view(
    page: ft.Page,
    *,
    service=None,
    on_open_cliente=None,
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
        "selected_thread_id": None,
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

    linkage_dropdown = ft.Dropdown(
        label="Vinculación",
        value="ALL",
        width=190,
        border_color="#CBD5E1",
        focused_border_color=Q_PRIMARY,
        options=[
            ft.dropdown.Option(
                key="ALL",
                text="Todas",
            ),
            ft.dropdown.Option(
                key="LINKED",
                text="Vinculadas",
            ),
            ft.dropdown.Option(
                key="UNLINKED",
                text="Sin vincular",
            ),
        ],
    )

    channel_dropdown = ft.Dropdown(
        label="Canal",
        value="WHATSAPP",
        width=170,
        border_color="#CBD5E1",
        focused_border_color=Q_PRIMARY,
        options=[
            ft.dropdown.Option(
                key="WHATSAPP",
                text="WhatsApp",
            ),
        ],
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

    def _avatar(item):
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

        return ft.Container(
            width=42,
            height=42,
            border_radius=21,
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

    def select_thread(
        thread_id,
    ):
        state[
            "selected_thread_id"
        ] = int(
            thread_id
        )

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
                        channel_dropdown.value
                        or "WHATSAPP"
                    ),
                    linkage=(
                        linkage_dropdown.value
                        or "ALL"
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
                linkage_dropdown.value
                or "ALL"
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
        linkage_dropdown.value = (
            "ALL"
        )
        channel_dropdown.value = (
            "WHATSAPP"
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
            border_radius=12,
            padding=12,
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
                        item
                    ),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        _display_name(
                                            item
                                        ),
                                        size=13,
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
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

        return ft.Container(
            width=390,
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
                        content=ft.Column(
                            controls=[
                                ft.Container(
                                    expand=True,
                                    alignment=(
                                        ft.Alignment(
                                            0,
                                            0,
                                        )
                                    ),
                                    content=ft.Column(
                                        controls=[
                                            ft.Text(
                                                "💬",
                                                size=40,
                                            ),
                                            ft.Text(
                                                (
                                                    "No hay mensajes "
                                                    "sincronizados todavía"
                                                ),
                                                size=15,
                                                weight=(
                                                    ft.FontWeight.BOLD
                                                ),
                                                color=Q_PRIMARY_DARK,
                                            ),
                                            ft.Text(
                                                (
                                                    "La conversación ya "
                                                    "está registrada y "
                                                    "preparada para la "
                                                    "sincronización del "
                                                    "historial."
                                                ),
                                                size=11,
                                                color=Q_MUTED,
                                                text_align=(
                                                    ft.TextAlign.CENTER
                                                ),
                                            ),
                                            ft.Text(
                                                (
                                                    f"Mensajes registrados: "
                                                    f"{item.message_count}"
                                                ),
                                                size=10,
                                                color=Q_MUTED,
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
                                ),
                            ],
                            expand=True,
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
                                primary_button(
                                    "Enviar",
                                    placeholder_sync,
                                ),
                            ],
                            spacing=10,
                        ),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
        )

    def build_context_panel():
        item = selected_item()

        if not item:
            return ft.Container(
                width=290,
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
                        expand=True,
                    ),
                    ft.Text(
                        str(
                            value
                            or "-"
                        ),
                        size=10,
                        color=Q_TEXT,
                        text_align=(
                            ft.TextAlign.RIGHT
                        ),
                    ),
                ],
                spacing=8,
            )

        contact_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Resumen contacto",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    context_row(
                        "Nombre",
                        _display_name(
                            item
                        ),
                    ),
                    context_row(
                        "Teléfono",
                        item.external_address,
                    ),
                    context_row(
                        "Canal",
                        item.channel,
                    ),
                    context_row(
                        "Cliente ID",
                        (
                            item.client_id
                            if linked
                            else "-"
                        ),
                    ),
                    context_row(
                        "Estado",
                        (
                            "Vinculado"
                            if linked
                            else "Sin vincular"
                        ),
                    ),
                ],
                spacing=8,
            ),
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
                    ft.Text(
                        "Expedientes vinculados",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        (
                            "La integración de expedientes "
                            "se añadirá en la siguiente "
                            "iteración de la vista."
                        ),
                        size=10,
                        color=Q_MUTED,
                    ),
                ],
                spacing=8,
            ),
        )

        actions = []

        if (
            linked
            and on_open_cliente
        ):
            actions.append(
                secondary_button(
                    "Ver ficha del cliente",
                    (
                        lambda e,
                        client_id=item.client_id:
                            on_open_cliente(
                                client_id
                            )
                    ),
                )
            )

        if not actions:
            actions.append(
                ft.Text(
                    (
                        "No hay acciones contextuales "
                        "disponibles todavía."
                    ),
                    size=10,
                    color=Q_MUTED,
                )
            )

        actions_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Acciones",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    *actions,
                ],
                spacing=8,
            ),
        )

        return ft.Container(
            width=290,
            content=ft.Column(
                controls=[
                    contact_card,
                    expedients_card,
                    actions_card,
                ],
                spacing=10,
            ),
        )

    def build_filters():
        search_input.on_submit = (
            refresh
        )

        linkage_dropdown.on_change = (
            refresh
        )

        channel_dropdown.on_change = (
            refresh
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
                    channel_dropdown,
                    linkage_dropdown,
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
                        height=575,
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
        preserve_selection=False,
    )

    content_area.content = (
        build_content()
    )

    return content_area

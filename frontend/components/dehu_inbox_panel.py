"""
Panel visual mínimo para la bandeja interna DEHú.

La bandeja es multiorigen:
- EMAIL_ONLY
- PORTAL_ONLY
- EMAIL_AND_PORTAL
- UNKNOWN

No realiza todavía aceptación, rechazo, descarga ni acceso
automatizado al portal.
"""

from datetime import datetime

import flet as ft

from backend.services.email_platform import (
    dehu_inbox_service,
)
from frontend.components.app_card import metric_card
from frontend.components.app_empty_state import empty_state
from frontend.components.listing import (
    compact_pagination_bar,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D8E2EE"
Q_TEXT = "#0F172A"


ITEM_TYPE_LABELS = {
    "NOTIFICATION": "Notificación",
    "COMMUNICATION": "Comunicación",
    "UNKNOWN": "Tipo no determinado",
}

ORIGIN_LABELS = {
    "EMAIL_ONLY": "Solo email",
    "PORTAL_ONLY": "Solo portal DEHú",
    "EMAIL_AND_PORTAL": "Email + portal DEHú",
    "UNKNOWN": "Origen sin determinar",
}

ORIGIN_COLORS = {
    "EMAIL_ONLY": (
        "#EEF4FF",
        "#3538CD",
    ),
    "PORTAL_ONLY": (
        "#ECFDF3",
        "#027A48",
    ),
    "EMAIL_AND_PORTAL": (
        "#F0F9FF",
        "#026AA2",
    ),
    "UNKNOWN": (
        "#F2F4F7",
        "#475467",
    ),
}

VERIFICATION_LABELS = {
    "MATCHED_PROVISIONAL":
        "Vinculada provisionalmente",
    "EXPEDIENT_NOT_FOUND":
        "Expediente no encontrado",
    "MULTIPLE_EXPEDIENTS":
        "Varias coincidencias",
    "REFERENCE_DETECTED_FAMILY_NOT_AVAILABLE":
        "Familia todavía no disponible",
    "EMAIL_ONLY":
        "Pendiente de revisión",
}

VERIFICATION_COLORS = {
    "MATCHED_PROVISIONAL": (
        "#ECFDF3",
        "#027A48",
    ),
    "EXPEDIENT_NOT_FOUND": (
        "#FFF7E6",
        "#B54708",
    ),
    "MULTIPLE_EXPEDIENTS": (
        "#FEF3F2",
        "#B42318",
    ),
    "REFERENCE_DETECTED_FAMILY_NOT_AVAILABLE": (
        "#F4F3FF",
        "#5925DC",
    ),
    "EMAIL_ONLY": (
        "#F2F4F7",
        "#475467",
    ),
}

PORTAL_LABELS = {
    "UNKNOWN": "Pendiente de comprobar",
    "PENDING_VERIFICATION":
        "Pendiente de comprobar",
    "VERIFIED": "Confirmada en DEHú",
    "ACCEPTED": "Aceptada",
    "REJECTED": "Rechazada",
}


def _text(value):
    return str(value or "").strip()


def _full_client_name(item):
    return " ".join(
        [
            _text(item.get("cliente_nombre")),
            _text(
                item.get(
                    "cliente_primer_apellido"
                )
            ),
            _text(
                item.get(
                    "cliente_segundo_apellido"
                )
            ),
        ]
    ).strip()


def _format_datetime(value):
    value = _text(value)

    if not value:
        return "-"

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        return parsed.strftime(
            "%d/%m/%Y %H:%M"
        )
    except Exception:
        return value


def _badge(
    label,
    background,
    foreground,
):
    return ft.Container(
        bgcolor=background,
        border_radius=999,
        padding=ft.padding.symmetric(
            horizontal=9,
            vertical=4,
        ),
        content=ft.Text(
            _text(label).upper(),
            size=10,
            weight=ft.FontWeight.BOLD,
            color=foreground,
        ),
    )


def _field_block(
    title,
    value,
    *,
    width=220,
    selectable=False,
    value_color=Q_TEXT,
):
    return ft.Container(
        width=width,
        content=ft.Column(
            spacing=2,
            controls=[
                ft.Text(
                    title,
                    size=11,
                    color=Q_MUTED,
                ),
                ft.Text(
                    _text(value) or "-",
                    size=12,
                    color=value_color,
                    weight=ft.FontWeight.W_600,
                    selectable=selectable,
                ),
            ],
        ),
    )


def build_dehu_inbox_panel(
    page: ft.Page,
    *,
    on_open_expediente=None,
    on_message=None,
):
    state = {
        "summary": {},
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "search": "",
        "item_type": "",
        "family_hint": "",
        "verification_status": "",
        "portal_status": "",
        "deadline_filter": "",
        "loading": False,
    }

    host = ft.Container(
        expand=True,
    )

    search_field = ft.TextField(
        hint_text=(
            "Buscar referencia, destinatario, "
            "organismo, cliente o expediente"
        ),
        prefix_icon=ft.Icons.SEARCH,
        height=42,
        dense=True,
        expand=True,
    )

    type_dropdown = ft.Dropdown(
        label="Tipo",
        value="",
        width=190,
        dense=True,
        options=[
            ft.dropdown.Option(
                key="",
                text="Todos",
            ),
            ft.dropdown.Option(
                key="NOTIFICATION",
                text="Notificaciones",
            ),
            ft.dropdown.Option(
                key="COMMUNICATION",
                text="Comunicaciones",
            ),
        ],
    )

    family_dropdown = ft.Dropdown(
        label="Familia",
        value="",
        width=190,
        dense=True,
        options=[
            ft.dropdown.Option(
                key="",
                text="Todas",
            ),
            ft.dropdown.Option(
                key="EXTRANJERIA",
                text="Extranjería",
            ),
            ft.dropdown.Option(
                key="NACIONALIDAD",
                text="Nacionalidad",
            ),
            ft.dropdown.Option(
                key="UNKNOWN",
                text="Sin determinar",
            ),
        ],
    )

    status_dropdown = ft.Dropdown(
        label="Vinculación",
        value="",
        width=245,
        dense=True,
        options=[
            ft.dropdown.Option(
                key="",
                text="Todos los estados",
            ),
            ft.dropdown.Option(
                key="MATCHED_PROVISIONAL",
                text="Vinculadas",
            ),
            ft.dropdown.Option(
                key="EXPEDIENT_NOT_FOUND",
                text="Expediente no encontrado",
            ),
            ft.dropdown.Option(
                key=(
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
                text="Familia no disponible",
            ),
            ft.dropdown.Option(
                key="MULTIPLE_EXPEDIENTS",
                text="Varias coincidencias",
            ),
        ],
    )

    portal_status_dropdown = ft.Dropdown(
        label="Estado DEHú",
        value="",
        width=205,
        dense=True,
        options=[
            ft.dropdown.Option(
                key="",
                text="Todos",
            ),
            ft.dropdown.Option(
                key="PENDING",
                text="Pendientes",
            ),
            ft.dropdown.Option(
                key="ACCEPTED",
                text="Aceptadas",
            ),
            ft.dropdown.Option(
                key="REJECTED",
                text="Rechazadas",
            ),
            ft.dropdown.Option(
                key="VERIFIED",
                text="Confirmadas",
            ),
        ],
    )

    deadline_dropdown = ft.Dropdown(
        label="Plazo",
        value="",
        width=205,
        dense=True,
        options=[
            ft.dropdown.Option(
                key="",
                text="Todos los plazos",
            ),
            ft.dropdown.Option(
                key="UPCOMING_7_DAYS",
                text="Próximos 7 días",
            ),
            ft.dropdown.Option(
                key="EXPIRED",
                text="Expiradas",
            ),
            ft.dropdown.Option(
                key="NO_DEADLINE",
                text="Sin plazo",
            ),
        ],
    )

    def notify(control):
        if callable(on_message):
            on_message(control)

    def safe_page_update():
        try:
            page.update()
        except Exception:
            pass

    def load_data():
        state["loading"] = True

        try:
            state["summary"] = (
                dehu_inbox_service.get_summary()
            )

            result = (
                dehu_inbox_service.list_items(
                    search=state["search"],
                    item_type=state["item_type"],
                    family_hint=(
                        state["family_hint"]
                    ),
                    verification_status=(
                        state[
                            "verification_status"
                        ]
                    ),
                    portal_status=(
                        state["portal_status"]
                    ),
                    deadline_filter=(
                        state["deadline_filter"]
                    ),
                    page=state["page"],
                    page_size=state["page_size"],
                )
            )

            state["items"] = (
                result.get("items")
                or []
            )
            state["total"] = int(
                result.get("total")
                or 0
            )
            state["page"] = int(
                result.get("page")
                or 1
            )

        except Exception as exc:
            state["items"] = []
            state["total"] = 0

            notify(
                ft.Container(
                    padding=12,
                    bgcolor="#FEF3F2",
                    border=ft.border.all(
                        1,
                        "#FDA29B",
                    ),
                    border_radius=10,
                    content=ft.Text(
                        "No se pudo cargar la "
                        f"bandeja DEHú: {exc}",
                        color="#B42318",
                        size=12,
                    ),
                )
            )

        finally:
            state["loading"] = False

    def rebuild():
        host.content = build_content()
        safe_page_update()

    def refresh(e=None):
        load_data()
        rebuild()

    def apply_filters(e=None):
        state["search"] = _text(
            search_field.value
        )
        state["item_type"] = _text(
            type_dropdown.value
        )
        state["family_hint"] = _text(
            family_dropdown.value
        )
        state["verification_status"] = (
            _text(status_dropdown.value)
        )
        state["portal_status"] = _text(
            portal_status_dropdown.value
        )
        state["deadline_filter"] = _text(
            deadline_dropdown.value
        )
        state["page"] = 1

        load_data()
        rebuild()

    def clear_filters(e=None):
        search_field.value = ""
        type_dropdown.value = ""
        family_dropdown.value = ""
        status_dropdown.value = ""
        portal_status_dropdown.value = ""
        deadline_dropdown.value = ""

        state["search"] = ""
        state["item_type"] = ""
        state["family_hint"] = ""
        state["verification_status"] = ""
        state["portal_status"] = ""
        state["deadline_filter"] = ""
        state["page"] = 1

        load_data()
        rebuild()

    def set_page(page_number):
        state["page"] = max(
            1,
            int(page_number or 1),
        )
        load_data()
        rebuild()

    def open_portal(item):
        url = _text(
            item.get("direct_access_url")
        )

        if not url:
            notify(
                ft.Container(
                    padding=12,
                    bgcolor="#FFF7E6",
                    border=ft.border.all(
                        1,
                        "#FEC84B",
                    ),
                    border_radius=10,
                    content=ft.Text(
                        "Este elemento no tiene "
                        "un enlace directo a DEHú.",
                        color="#B54708",
                        size=12,
                    ),
                )
            )
            safe_page_update()
            return

        try:
            page.launch_url(url)
        except Exception as exc:
            notify(
                ft.Container(
                    padding=12,
                    bgcolor="#FEF3F2",
                    border=ft.border.all(
                        1,
                        "#FDA29B",
                    ),
                    border_radius=10,
                    content=ft.Text(
                        "No se pudo abrir DEHú: "
                        f"{exc}",
                        color="#B42318",
                        size=12,
                    ),
                )
            )
            safe_page_update()

    def open_expedient(item):
        expediente_id = item.get(
            "expediente_id"
        )

        if not expediente_id:
            notify(
                ft.Container(
                    padding=12,
                    bgcolor="#FFF7E6",
                    border=ft.border.all(
                        1,
                        "#FEC84B",
                    ),
                    border_radius=10,
                    content=ft.Text(
                        "La notificación todavía "
                        "no está vinculada a un "
                        "expediente.",
                        color="#B54708",
                        size=12,
                    ),
                )
            )
            safe_page_update()
            return

        if callable(on_open_expediente):
            on_open_expediente(
                int(expediente_id)
            )

    def close_dialog(dialog):
        dialog.open = False
        safe_page_update()

    def show_detail(item):
        try:
            detail = (
                dehu_inbox_service
                .get_item_detail(
                    item["id"]
                )
                or item
            )
        except Exception:
            detail = item

        sources = detail.get(
            "sources"
        ) or []

        source_controls = []

        for source in sources:
            source_controls.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(
                        1,
                        "#EAECF0",
                    ),
                    border_radius=8,
                    content=ft.Column(
                        spacing=3,
                        controls=[
                            ft.Text(
                                (
                                    _text(
                                        source.get(
                                            "provider"
                                        )
                                    )
                                    or "Proveedor"
                                ),
                                size=12,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                "Cuenta: "
                                + (
                                    _text(
                                        source.get(
                                            "account_email"
                                        )
                                    )
                                    or "-"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                "Carpeta: "
                                + (
                                    _text(
                                        source.get(
                                            "source_folder"
                                        )
                                    )
                                    or "-"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                "Recibido: "
                                + _format_datetime(
                                    source.get(
                                        "received_at"
                                    )
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                _text(
                                    source.get(
                                        "subject"
                                    )
                                )
                                or "Sin asunto",
                                size=11,
                                selectable=True,
                                color=Q_TEXT,
                            ),
                        ],
                    ),
                )
            )

        if not source_controls:
            source_controls.append(
                ft.Text(
                    "No existen correos asociados.",
                    size=12,
                    color=Q_MUTED,
                )
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Detalle DEHú · "
                + (
                    _text(
                        detail.get(
                            "reference_value"
                        )
                    )
                    or _text(
                        detail.get(
                            "dehu_identifier"
                        )
                    )
                    or f"#{detail.get('id')}"
                ),
                color=Q_PRIMARY_DARK,
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Container(
                width=850,
                height=560,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        ft.Row(
                            wrap=True,
                            spacing=12,
                            controls=[
                                _field_block(
                                    "Tipo",
                                    ITEM_TYPE_LABELS.get(
                                        _text(
                                            detail.get(
                                                "item_type"
                                            )
                                        ),
                                        detail.get(
                                            "item_type"
                                        ),
                                    ),
                                ),
                                _field_block(
                                    "Familia",
                                    detail.get(
                                        "family_hint"
                                    ),
                                ),
                                _field_block(
                                    "Referencia",
                                    detail.get(
                                        "reference_value"
                                    ),
                                    selectable=True,
                                ),
                                _field_block(
                                    "Identificador",
                                    detail.get(
                                        "dehu_identifier"
                                    ),
                                    width=310,
                                    selectable=True,
                                ),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=12,
                            controls=[
                                _field_block(
                                    "Organismo",
                                    detail.get(
                                        "issuer_name"
                                    ),
                                    width=350,
                                ),
                                _field_block(
                                    "Destinatario",
                                    detail.get(
                                        "recipient_name"
                                    ),
                                    width=300,
                                ),
                                _field_block(
                                    "Documento",
                                    detail.get(
                                        "recipient_document_masked"
                                    ),
                                ),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=12,
                            controls=[
                                _field_block(
                                    "Vencimiento",
                                    _format_datetime(
                                        detail.get(
                                            "deadline_at"
                                        )
                                    ),
                                ),
                                _field_block(
                                    "Vinculación",
                                    VERIFICATION_LABELS.get(
                                        _text(
                                            detail.get(
                                                "verification_status"
                                            )
                                        ),
                                        detail.get(
                                            "verification_status"
                                        ),
                                    ),
                                    width=300,
                                ),
                                _field_block(
                                    "Estado portal",
                                    PORTAL_LABELS.get(
                                        _text(
                                            detail.get(
                                                "portal_status"
                                            )
                                        ),
                                        detail.get(
                                            "portal_status"
                                        ),
                                    ),
                                ),
                            ],
                        ),
                        ft.Divider(),
                        ft.Text(
                            "Concepto",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            _text(
                                detail.get(
                                    "concept"
                                )
                            )
                            or "-",
                            size=12,
                            selectable=True,
                            color=Q_TEXT,
                        ),
                        ft.Text(
                            "Fuentes de correo",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Column(
                            controls=source_controls,
                            spacing=8,
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Abrir DEHú",
                    on_click=lambda e: (
                        open_portal(detail)
                    ),
                ),
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda e: (
                        close_dialog(dialog)
                    ),
                ),
            ],
        )

        page.overlay.append(dialog)
        dialog.open = True
        safe_page_update()

    def card(item):
        item_type = _text(
            item.get("item_type")
        )
        origin = _text(
            item.get("detection_origin")
        )
        verification = _text(
            item.get("verification_status")
        )
        portal_status = _text(
            item.get("portal_status")
        ) or "UNKNOWN"

        origin_bg, origin_fg = (
            ORIGIN_COLORS.get(
                origin,
                ORIGIN_COLORS["UNKNOWN"],
            )
        )

        verification_bg, verification_fg = (
            VERIFICATION_COLORS.get(
                verification,
                (
                    "#F2F4F7",
                    "#475467",
                ),
            )
        )

        reference = (
            _text(
                item.get(
                    "reference_value"
                )
            )
            or f"Elemento #{item.get('id')}"
        )

        dehu_identifier = (
            _text(
                item.get(
                    "dehu_identifier"
                )
            )
            or "-"
        )

        expediente = (
            _text(
                item.get(
                    "numero_expediente"
                )
            )
            or _text(
                item.get(
                    "numero_expediente_extranjeria"
                )
            )
            or "Sin expediente vinculado"
        )

        cliente = (
            _full_client_name(item)
            or _text(
                item.get(
                    "recipient_name"
                )
            )
            or "Destinatario no indicado"
        )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=ft.padding.symmetric(
                horizontal=16,
                vertical=14,
            ),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        spacing=8,
                        wrap=True,
                        controls=[
                            _badge(
                                ITEM_TYPE_LABELS.get(
                                    item_type,
                                    item_type,
                                ),
                                "#EEF4FF",
                                "#3538CD",
                            ),
                            _badge(
                                item.get(
                                    "family_hint"
                                )
                                or "Sin familia",
                                "#F8FAFC",
                                "#475467",
                            ),
                            _badge(
                                ORIGIN_LABELS.get(
                                    origin,
                                    origin,
                                ),
                                origin_bg,
                                origin_fg,
                            ),
                            _badge(
                                VERIFICATION_LABELS.get(
                                    verification,
                                    verification,
                                ),
                                verification_bg,
                                verification_fg,
                            ),
                        ],
                    ),
                    ft.Row(
                        vertical_alignment=(
                            ft.CrossAxisAlignment.START
                        ),
                        controls=[
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    spacing=3,
                                    controls=[
                                        ft.Text(
                                            reference,
                                            size=16,
                                            weight=(
                                                ft.FontWeight.BOLD
                                            ),
                                            color=Q_PRIMARY_DARK,
                                            selectable=True,
                                        ),
                                        ft.Text(
                                            "Identificador: "
                                            + dehu_identifier,
                                            size=11,
                                            color=Q_MUTED,
                                            selectable=True,
                                        ),
                                        ft.Text(
                                            _text(
                                                item.get(
                                                    "issuer_name"
                                                )
                                            )
                                            or (
                                                "Organismo "
                                                "no indicado"
                                            ),
                                            size=13,
                                            weight=(
                                                ft.FontWeight.W_600
                                            ),
                                            color=Q_TEXT,
                                        ),
                                        ft.Text(
                                            cliente,
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            _text(
                                                item.get(
                                                    "concept"
                                                )
                                            )
                                            or "-",
                                            size=11,
                                            color=Q_MUTED,
                                            max_lines=2,
                                            overflow=(
                                                ft.TextOverflow.ELLIPSIS
                                            ),
                                        ),
                                    ],
                                ),
                            ),
                            ft.Row(
                                spacing=2,
                                controls=[
                                    ft.IconButton(
                                        icon=(
                                            ft.Icons.DESCRIPTION
                                        ),
                                        tooltip="Ver detalle",
                                        on_click=(
                                            lambda e, current=item:
                                            show_detail(
                                                current
                                            )
                                        ),
                                    ),
                                    ft.IconButton(
                                        icon=(
                                            ft.Icons.FOLDER_OPEN
                                        ),
                                        tooltip=(
                                            "Abrir expediente"
                                        ),
                                        disabled=not bool(
                                            item.get(
                                                "expediente_id"
                                            )
                                        ),
                                        on_click=(
                                            lambda e, current=item:
                                            open_expedient(
                                                current
                                            )
                                        ),
                                    ),
                                    ft.IconButton(
                                        icon=(
                                            ft.Icons.OPEN_IN_NEW
                                        ),
                                        tooltip="Abrir DEHú",
                                        disabled=not bool(
                                            _text(
                                                item.get(
                                                    "direct_access_url"
                                                )
                                            )
                                        ),
                                        on_click=(
                                            lambda e, current=item:
                                            open_portal(
                                                current
                                            )
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                    ft.Divider(
                        height=1,
                        color="#EAECF0",
                    ),
                    ft.Row(
                        spacing=14,
                        wrap=True,
                        controls=[
                            _field_block(
                                "Expediente",
                                expediente,
                                width=260,
                                selectable=True,
                            ),
                            _field_block(
                                "Vencimiento",
                                _format_datetime(
                                    item.get(
                                        "deadline_at"
                                    )
                                ),
                                width=180,
                            ),
                            _field_block(
                                "Estado en DEHú",
                                PORTAL_LABELS.get(
                                    portal_status,
                                    portal_status,
                                ),
                                width=210,
                            ),
                            _field_block(
                                "Última detección",
                                _format_datetime(
                                    item.get(
                                        "last_seen_at"
                                    )
                                ),
                                width=180,
                            ),
                            _field_block(
                                "Fuentes",
                                item.get(
                                    "source_count"
                                )
                                or 0,
                                width=90,
                            ),
                        ],
                    ),
                ],
            ),
        )

    def build_content():
        summary = state.get(
            "summary"
        ) or {}
        items = state.get("items") or []

        controls = [
            ft.Row(
                alignment=(
                    ft.MainAxisAlignment.SPACE_BETWEEN
                ),
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(
                                "Bandeja DEHú",
                                size=21,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Inventario unificado de "
                                    "avisos detectados por "
                                    "correo y por el portal"
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    ft.OutlinedButton(
                        "Actualizar",
                        icon=ft.Icons.REFRESH,
                        on_click=refresh,
                    ),
                ],
            ),
            ft.Row(
                spacing=10,
                wrap=True,
                controls=[
                    metric_card(
                        "Total",
                        summary.get(
                            "total",
                            0,
                        ),
                    ),
                    metric_card(
                        "Notificaciones",
                        summary.get(
                            "notifications",
                            0,
                        ),
                    ),
                    metric_card(
                        "Comunicaciones",
                        summary.get(
                            "communications",
                            0,
                        ),
                    ),
                    metric_card(
                        "Vinculadas",
                        summary.get(
                            "linked",
                            0,
                        ),
                    ),
                    metric_card(
                        "Próximos 7 días",
                        summary.get(
                            "upcoming_7_days",
                            0,
                        ),
                    ),
                    metric_card(
                        "Detectadas en portal",
                        summary.get(
                            "portal_detected",
                            0,
                        ),
                    ),
                ],
            ),
            ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=12,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            spacing=8,
                            controls=[
                                search_field,
                                ft.ElevatedButton(
                                    "Buscar",
                                    icon=ft.Icons.SEARCH,
                                    on_click=apply_filters,
                                ),
                                ft.OutlinedButton(
                                    "Limpiar",
                                    icon=ft.Icons.CLEAR,
                                    on_click=clear_filters,
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=8,
                            wrap=True,
                            controls=[
                                type_dropdown,
                                family_dropdown,
                                status_dropdown,
                                portal_status_dropdown,
                                deadline_dropdown,
                            ],
                        ),
                    ],
                ),
            ),
        ]

        if state["total"]:
            controls.append(
                compact_pagination_bar(
                    page=state["page"],
                    page_size=state["page_size"],
                    total_items=state["total"],
                    on_page_change=set_page,
                    label_prefix="DEHú",
                )
            )

        if items:
            cards = [
                card(item)
                for item in items
            ]
        else:
            cards = [
                empty_state(
                    "No hay elementos DEHú "
                    "para los filtros seleccionados."
                )
            ]

        controls.append(
            ft.Container(
                expand=True,
                content=ft.Column(
                    controls=cards,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            )
        )

        return ft.Column(
            controls=controls,
            spacing=12,
            expand=True,
        )

    search_field.on_submit = apply_filters
    type_dropdown.on_change = apply_filters
    family_dropdown.on_change = apply_filters
    status_dropdown.on_change = apply_filters
    portal_status_dropdown.on_change = apply_filters
    deadline_dropdown.on_change = apply_filters

    load_data()
    host.content = build_content()

    return host

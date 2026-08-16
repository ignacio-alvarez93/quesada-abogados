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
from frontend.components.app_empty_state import empty_state
from frontend.components.listing import (
    compact_pagination_bar,
    counter_chips,
)
from frontend.components.period_filter import (
    PERIOD_ALL,
    build_period_filter,
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
    "CONFIRMED_BY_TRACEABILITY":
        "Confirmada desde Trazabilidad",
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
    "CONFIRMED_BY_TRACEABILITY": (
        "#ECFDF3",
        "#027A48",
    ),
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

QUICK_FILTER_STATUS_MAP = {
    "PENDING_REVIEW": (
        "Pendientes de localizar",
        "#FFF7E6",
        "#B54708",
    ),
    "PENDING_CLASSIFICATION": (
        "Pendientes de clasificar",
        "#F4F3FF",
        "#5925DC",
    ),
    "CONFIRMED_BY_TRACEABILITY": (
        "Confirmadas",
        "#ECFDF3",
        "#027A48",
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
    on_open_portal=None,
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
        "period_value": PERIOD_ALL,
        "detected_from": "",
        "detected_to": "",
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
                key="PENDING_REVIEW",
                text="Pendientes de localizar",
            ),
            ft.dropdown.Option(
                key="PENDING_CLASSIFICATION",
                text="Pendientes de clasificar",
            ),
            ft.dropdown.Option(
                key="CONFIRMED_BY_TRACEABILITY",
                text="Confirmadas por Trazabilidad",
            ),
            ft.dropdown.Option(
                key="MATCHED_PROVISIONAL",
                text="Vinculadas provisionalmente",
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

    def handle_period_change(result):
        state["period_value"] = (
            result.get("value")
            or PERIOD_ALL
        )
        state["detected_from"] = (
            result.get("date_from")
            or ""
        )
        state["detected_to"] = (
            result.get("date_to")
            or ""
        )
        state["page"] = 1

        load_data()
        rebuild()

    period_dropdown = build_period_filter(
        page,
        initial_value=PERIOD_ALL,
        on_change=handle_period_change,
        width=215,
        label="Fecha de detección",
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
                    detected_from=(
                        state["detected_from"]
                    ),
                    detected_to=(
                        state["detected_to"]
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
            state["summary"] = {}
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

    def set_quick_filter(value):
        selected = _text(value)

        if (
            state["verification_status"]
            == selected
        ):
            selected = ""

        state["verification_status"] = selected
        status_dropdown.value = selected
        state["page"] = 1

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
        period_dropdown.set_period_value(
            PERIOD_ALL,
            update=False,
        )

        state["search"] = ""
        state["item_type"] = ""
        state["family_hint"] = ""
        state["verification_status"] = ""
        state["portal_status"] = ""
        state["deadline_filter"] = ""
        state["period_value"] = PERIOD_ALL
        state["detected_from"] = ""
        state["detected_to"] = ""
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

    def request_portal_open(
        url,
    ):
        """
        Delega la navegación DEHú en la capa superior.

        ``None`` representa expresamente la raíz oficial
        del portal. La URL física continúa siendo
        responsabilidad del connector/backend.
        """

        if not callable(
            on_open_portal
        ):
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
                        "La apertura gobernada de "
                        "DEHú no está disponible.",
                        color="#B42318",
                        size=12,
                    ),
                )
            )
            safe_page_update()
            return False

        try:
            on_open_portal(
                url
            )

            return True

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
                        "No se pudo solicitar "
                        "la apertura de DEHú: "
                        f"{exc}",
                        color="#B42318",
                        size=12,
                    ),
                )
            )
            safe_page_update()

            return False

    def open_portal_root(
        e=None,
    ):
        return request_portal_open(
            None
        )

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
            return False

        return request_portal_open(
            url
        )

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
                                    "Clasificación procesal",
                                    (
                                        detail.get(
                                            "procedural_event_label"
                                        )
                                        or "Sin clasificar"
                                    ),
                                    width=270,
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
                *(
                    [
                        ft.TextButton(
                            "Abrir expediente",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda e: (
                                open_expedient(detail)
                            ),
                        ),
                    ]
                    if detail.get(
                        "expediente_id"
                    )
                    else []
                ),
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

        procedural_label = _text(
            item.get(
                "procedural_event_label"
            )
        )

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
                                (
                                    procedural_label
                                    or ITEM_TYPE_LABELS.get(
                                        item_type,
                                        item_type,
                                    )
                                ),
                                (
                                    "#ECFDF3"
                                    if procedural_label
                                    else "#EEF4FF"
                                ),
                                (
                                    "#027A48"
                                    if procedural_label
                                    else "#3538CD"
                                ),
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
                                            (
                                                procedural_label
                                                or reference
                                            ),
                                            size=16,
                                            weight=(
                                                ft.FontWeight.BOLD
                                            ),
                                            color=Q_PRIMARY_DARK,
                                            selectable=True,
                                        ),
                                        (
                                            ft.Text(
                                                "Referencia: "
                                                + reference,
                                                size=11,
                                                color=Q_MUTED,
                                                selectable=True,
                                            )
                                            if procedural_label
                                            else ft.Container(
                                                visible=False
                                            )
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
        items = state.get("items") or []
        summary = state.get("summary") or {}

        quick_counts = {
            "": int(
                summary.get(
                    "total",
                    0,
                )
                or 0
            ),
            "PENDING_REVIEW": int(
                summary.get(
                    "pending_review",
                    0,
                )
                or 0
            ),
            "PENDING_CLASSIFICATION": int(
                summary.get(
                    "pending_classification",
                    0,
                )
                or 0
            ),
            "CONFIRMED_BY_TRACEABILITY": int(
                summary.get(
                    "confirmed_by_traceability",
                    0,
                )
                or 0
            ),
        }

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
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.OutlinedButton(
                                "Abrir portal DEHú",
                                icon=(
                                    ft.Icons.OPEN_IN_NEW
                                ),
                                on_click=(
                                    open_portal_root
                                ),
                            ),
                            ft.OutlinedButton(
                                "Actualizar",
                                icon=ft.Icons.REFRESH,
                                on_click=refresh,
                            ),
                        ],
                    ),
                ],
            ),
            counter_chips(
                options=[
                    (
                        "PENDING_REVIEW",
                        "Pendientes de localizar",
                    ),
                    (
                        "PENDING_CLASSIFICATION",
                        "Pendientes de clasificar",
                    ),
                    (
                        "CONFIRMED_BY_TRACEABILITY",
                        "Confirmadas",
                    ),
                ],
                counts=quick_counts,
                active_value=(
                    state["verification_status"]
                ),
                on_select=set_quick_filter,
                include_all=True,
                all_label="Todos",
                all_value="",
                status_map=(
                    QUICK_FILTER_STATUS_MAP
                ),
                bordered_status=True,
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
                                period_dropdown.control,
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

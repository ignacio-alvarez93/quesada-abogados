from __future__ import annotations

import flet as ft

from frontend.components.listing.card_item import card_item
from frontend.components.listing.status_chip import status_chip


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_DANGER = "#B42318"


INVOICE_STATUS_MAP = {
    "BORRADOR": ("Borrador", "#F1F5F9", "#475569", "#CBD5E1"),
    "EMITIDA": ("Emitida", "#ECFDF3", "#027A48", "#6CE9A6"),
    "EXPORTADA": ("Exportada", "#EAF3FF", "#0057B8", "#84CAFF"),
    "ANULADA": ("Anulada", "#FEF3F2", "#B42318", "#FDA29B"),
}


FISCAL_TYPE_MAP = {
    "PROVISION": (
        "Provisión",
        "#EAF3FF",
        "#0057B8",
        "#84CAFF",
    ),
    "SUPLIDO": (
        "Suplido",
        "#FDF2FA",
        "#9D174D",
        "#F9A8D4",
    ),
}


HOLDED_STATUS_MAP = {
    "HOLDED_PENDING": (
        "Pendiente Holded",
        "#FFFAEB",
        "#B54708",
        "#FEC84B",
    ),
    "HOLDED_EXPORTED": (
        "Exportada a Holded",
        "#ECFDF3",
        "#027A48",
        "#6CE9A6",
    ),
}


def _money(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0

    return (
        f"{amount:,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _client_name(factura: dict) -> str:
    value = " ".join(
        part.strip()
        for part in [
            str(factura.get("nombre") or ""),
            str(factura.get("primer_apellido") or ""),
            str(factura.get("segundo_apellido") or ""),
        ]
        if part and str(part).strip()
    )
    return value or f"Cliente #{factura.get('cliente_id') or '-'}"


def _date_badge(value) -> ft.Container:
    resolved = str(value or "-").strip() or "-"

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.CALENDAR_TODAY,
                    size=14,
                    color=Q_PRIMARY,
                ),
                ft.Text(
                    resolved,
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY,
                    selectable=True,
                ),
            ],
            spacing=5,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#EAF3FF",
        border=ft.border.all(1, "#84CAFF"),
        border_radius=8,
        padding=ft.padding.symmetric(horizontal=9, vertical=5),
    )


def _amount_indicator(
    label: str,
    value,
    *,
    bgcolor="#F8FAFC",
    border_color="#D0D5DD",
    text_color=Q_PRIMARY_DARK,
) -> ft.Container:
    return ft.Container(
        bgcolor=bgcolor,
        border=ft.border.all(1, border_color),
        border_radius=9,
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=6,
        ),
        content=ft.Column(
            controls=[
                ft.Text(
                    label.upper(),
                    size=9,
                    weight=ft.FontWeight.BOLD,
                    color=Q_MUTED,
                ),
                ft.Text(
                    _money(value),
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=text_color,
                    selectable=True,
                ),
            ],
            spacing=1,
            tight=True,
        ),
    )


def _invoice_display_amounts(
    factura: dict,
) -> dict:
    """
    Convierte los importes fiscales internos a signos contables.

    Fórmula interna:
        total = base + IVA - IRPF + suplidos

    Presentación:
    - Factura normal:
        base positiva
        IVA positivo
        IRPF negativo
    - Rectificativa:
        base negativa
        IVA negativo
        IRPF positivo

    Los valores persistidos no se modifican.
    """
    base = float(
        factura.get("base_imponible") or 0
    )
    iva = float(
        factura.get("iva") or 0
    )
    irpf = float(
        factura.get("irpf") or 0
    )
    suplidos = float(
        factura.get("suplidos") or 0
    )

    is_rectifying = (
        str(
            factura.get("tipo_factura")
            or "NORMAL"
        ).strip().upper()
        == "RECTIFICATIVA"
        or factura.get("factura_rectificada_id")
        is not None
    )

    if is_rectifying:
        display_base = -abs(base)
        display_iva = -abs(iva)
        display_irpf = abs(irpf)
        display_suplidos = -abs(suplidos)
    else:
        display_base = abs(base)
        display_iva = abs(iva)
        display_irpf = -abs(irpf)
        display_suplidos = abs(suplidos)

    return {
        "base_imponible": round(display_base, 2),
        "iva": round(display_iva, 2),
        "irpf": round(display_irpf, 2),
        "suplidos": round(display_suplidos, 2),
    }


def _metadata_text(label: str, value) -> ft.Text:
    resolved = str(value or "-").strip() or "-"

    return ft.Text(
        f"{label}: {resolved}",
        size=11,
        color=Q_MUTED,
        selectable=True,
    )


def _action_menu(
    factura: dict,
    on_edit=None,
    on_delete=None,
    on_export_holded=None,
    on_rectify=None,
):
    is_rectified_original = (
        str(
            factura.get("estado")
            or ""
        ).strip().upper()
        == "RECTIFICADA"
        and str(
            factura.get("tipo_factura")
            or "NORMAL"
        ).strip().upper()
        != "RECTIFICATIVA"
    )

    if is_rectified_original:
        # Factura original ya rectificada:
        # permanece visible, pero sin acciones.
        return ft.Container(
            width=0,
            height=0,
            visible=False,
        )

    exported = bool(factura.get("exportada_holded"))
    period_closed = bool(factura.get("_period_closed"))
    is_rectifying = (
        str(
            factura.get("tipo_factura")
            or "NORMAL"
        ).upper()
        == "RECTIFICATIVA"
    )

    items = []

    if exported:
        if (
            on_rectify is not None
            and not is_rectifying
        ):
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.REPLAY_CIRCLE_FILLED_OUTLINED,
                                size=18,
                                color="#B54708",
                            ),
                            ft.Text(
                                "Generar rectificativa",
                                size=13,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e: on_rectify(factura),
                )
            )

    elif not period_closed:
        if on_edit is not None:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.EDIT_OUTLINED,
                                size=18,
                            ),
                            ft.Text(
                                "Modificar factura y cobro",
                                size=13,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e: on_edit(factura),
                )
            )

        if on_export_holded is not None:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.UPLOAD_FILE_OUTLINED,
                                size=18,
                            ),
                            ft.Text(
                                "Marcar exportada a Holded",
                                size=13,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e: on_export_holded(factura),
                )
            )

        if on_delete is not None:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.DELETE_OUTLINE,
                                size=18,
                                color="#B42318",
                            ),
                            ft.Text(
                                "Eliminar factura",
                                size=13,
                                color="#B42318",
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e: on_delete(factura),
                )
            )

    if not items:
        return None

    return ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT,
        tooltip="Acciones de la factura",
        items=items,
    )

def economic_invoice_card(
    factura: dict,
    *,
    date_display=None,
    on_edit=None,
    on_delete=None,
    on_export_holded=None,
    on_rectify=None,
):
    """
    Card reutilizable de factura.

    No consulta servicios ni modifica datos. Recibe el registro y
    los callbacks proporcionados por la vista.
    """
    factura = dict(factura or {})

    numero = (
        factura.get("numero_factura")
        or f"Factura #{factura.get('id') or '-'}"
    )
    cliente = _client_name(factura).upper()

    fecha = (
        date_display(factura.get("fecha_factura"))
        if date_display
        else str(factura.get("fecha_factura") or "-")
    )

    estado = (
        str(factura.get("estado") or "BORRADOR")
        .strip()
        .upper()
        .replace(" ", "_")
    )

    holded_status = (
        "HOLDED_EXPORTED"
        if bool(factura.get("exportada_holded"))
        else "HOLDED_PENDING"
    )

    fiscal_type = (
        "SUPLIDO"
        if str(factura.get("tipo_fiscal") or "").upper() == "SUPLIDO"
        else "PROVISION"
    )

    actions = [
        control
        for control in [
            _action_menu(
                factura,
                on_edit=on_edit,
                on_delete=on_delete,
                on_export_holded=on_export_holded,
                on_rectify=on_rectify,
            )
        ]
        if control is not None
    ]

    badges = [
        status_chip(
            estado,
            status_map=INVOICE_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
        status_chip(
            holded_status,
            status_map=HOLDED_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
        status_chip(
            fiscal_type,
            status_map=FISCAL_TYPE_MAP,
            compact=True,
            bordered=True,
        ),
    ]

    try:
        total_value = float(factura.get("total") or 0)
        display_amounts = _invoice_display_amounts(
            factura
        )
    except (TypeError, ValueError):
        total_value = 0.0

    body = [
        ft.Row(
            controls=[
                ft.Text(
                    _money(total_value),
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=Q_SUCCESS if total_value >= 0 else Q_DANGER,
                ),
                _amount_indicator(
                    "Base imponible",
                    display_amounts["base_imponible"],
                    bgcolor="#F8FAFC",
                    border_color="#CBD5E1",
                    text_color=Q_PRIMARY_DARK,
                ),
                _amount_indicator(
                    "IVA",
                    display_amounts["iva"],
                    bgcolor="#EAF3FF",
                    border_color="#84CAFF",
                    text_color=Q_PRIMARY,
                ),
                _amount_indicator(
                    "IRPF",
                    display_amounts["irpf"],
                    bgcolor="#FFF4E5",
                    border_color="#FEC84B",
                    text_color="#B54708",
                ),
                _amount_indicator(
                    "Suplidos",
                    display_amounts["suplidos"],
                    bgcolor="#FDF2FA",
                    border_color="#F9A8D4",
                    text_color="#9D174D",
                ),
            ],
            spacing=14,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Row(
            controls=[
                _metadata_text(
                    "Expediente",
                    factura.get("numero_expediente") or "Sin expediente",
                ),
                _metadata_text(
                    "Hoja",
                    factura.get("numero_hoja") or "Sin hoja",
                ),
            ],
            spacing=14,
            wrap=True,
        ),
    ]

    if bool(factura.get("_period_closed")):
        body.append(
            ft.Container(
                bgcolor="#FFF4E5",
                border=ft.border.all(1, "#FEC84B"),
                border_radius=8,
                padding=ft.padding.symmetric(
                    horizontal=10,
                    vertical=7,
                ),
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.EVENT_BUSY_OUTLINED,
                            size=15,
                            color="#B54708",
                        ),
                        ft.Text(
                            (
                                "Periodo cerrado: esta factura y su "
                                "cobro vinculado no pueden modificarse."
                            ),
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color="#B54708",
                        ),
                    ],
                    spacing=7,
                    tight=True,
                ),
            )
        )

    if bool(factura.get("exportada_holded")):
        body.append(
            ft.Container(
                bgcolor="#F1F5F9",
                border=ft.border.all(1, "#CBD5E1"),
                border_radius=8,
                padding=ft.padding.symmetric(
                    horizontal=10,
                    vertical=7,
                ),
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.LOCK_OUTLINE,
                            size=15,
                            color="#475569",
                        ),
                        ft.Text(
                            (
                                "Factura congelada: ya fue exportada "
                                "a Holded."
                            ),
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color="#475569",
                        ),
                    ],
                    spacing=7,
                    tight=True,
                ),
            )
        )

    concepto = str(factura.get("concepto") or "").strip()

    if concepto:
        body.append(
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            size=15,
                            color=Q_PRIMARY,
                        ),
                        ft.Text(
                            concepto,
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                            selectable=True,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=7,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor="#F8FAFC",
                border_radius=8,
                padding=ft.padding.symmetric(
                    horizontal=10,
                    vertical=7,
                ),
            )
        )

    observaciones = str(factura.get("observaciones") or "").strip()

    if observaciones:
        body.append(
            ft.Text(
                observaciones,
                size=12,
                color=Q_PRIMARY_DARK,
                selectable=True,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
        )

    return card_item(
        title=f"{numero}  ·  {fecha}  ·  {cliente}",
        subtitle=None,
        badges=badges,
        actions=actions,
        body=body,
        padding=11,
    )

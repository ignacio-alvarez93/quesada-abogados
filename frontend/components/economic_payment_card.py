from __future__ import annotations

import flet as ft

from frontend.components.listing.card_item import card_item
from frontend.components.listing.status_chip import status_chip


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_DANGER = "#B42318"


RECONCILIATION_STATUS_MAP = {
    "PENDIENTE": ("Pendiente", "#FFFAEB", "#B54708", "#F79009"),
    "PARCIAL": ("Conciliado parcial", "#EAF3FF", "#0057B8", "#84CAFF"),
    "CONCILIACION_PARCIAL": (
        "Conciliado parcial",
        "#EAF3FF",
        "#0057B8",
        "#84CAFF",
    ),
    "CONCILIADO_PARCIAL": (
        "Conciliado parcial",
        "#EAF3FF",
        "#0057B8",
        "#84CAFF",
    ),
    "CONCILIADO": ("Conciliado", "#ECFDF3", "#027A48", "#6CE9A6"),
    "REVIEW_REQUIRED": ("Revisar", "#FEF3F2", "#B42318", "#FDA29B"),
    "SOBRANTE_REVISION": ("Revisar sobrante", "#FEF3F2", "#B42318", "#FDA29B"),
}


FISCAL_STATUS_MAP = {
    "PROVISION": (
        "Provisión",
        "#EAF3FF",
        "#0057B8",
        "#84CAFF",
    ),
    "SUPLIDO": (
        "Suplido",
        "#FFF4E5",
        "#B54708",
        "#FEC84B",
    ),
    "MIXTO": (
        "Mixto (provisión + suplido)",
        "#F4F3FF",
        "#5925DC",
        "#BDB4FE",
    ),
}


TIPO_ECONOMICO_LABELS = {
    "PROVISION": "Provisión",
    "TASA": "Tasa",
    "HONORARIOS": "Honorarios",
    "OTRO": "Otro",
}

TIPO_FISCAL_LABELS = {
    "PROVISION": "Provisión",
    "SUPLIDO": "Suplido",
}


FACTURATION_STATUS_MAP = {
    "NO_FACTURABLE": ("No facturable", "#F1F5F9", "#475569", "#CBD5E1"),
    "FACTURABLE": ("Facturable", "#FFFAEB", "#B54708", "#FEC84B"),
    "FACTURADO": ("Facturado", "#ECFDF3", "#027A48", "#6CE9A6"),
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


def _client_name(cobro: dict) -> str:
    value = " ".join(
        part.strip()
        for part in [
            str(cobro.get("nombre") or ""),
            str(cobro.get("primer_apellido") or ""),
            str(cobro.get("segundo_apellido") or ""),
        ]
        if part and str(part).strip()
    )
    return value or f"Cliente #{cobro.get('cliente_id') or '-'}"


def _reconciliation_status(cobro: dict) -> str:
    value = str(cobro.get("estado_conciliacion") or "PENDIENTE")
    return value.strip().upper().replace(" ", "_") or "PENDIENTE"


def _facturation_status(cobro: dict) -> str:
    if cobro.get("numero_factura") or cobro.get("factura_id"):
        return "FACTURADO"
    if bool(cobro.get("facturable")):
        return "FACTURABLE"
    return "NO_FACTURABLE"


def _fiscal_status(cobro: dict) -> str:
    # resumen_fiscal viene del desglose (economic_service); tipo_fiscal
    # de cabecera solo como respaldo para registros sin enriquecer.
    value = str(
        cobro.get("resumen_fiscal") or cobro.get("tipo_fiscal") or ""
    ).strip().upper()
    if value in FISCAL_STATUS_MAP:
        return value
    return "PROVISION"


def _line_money(linea: dict) -> str:
    try:
        return _money(int(linea.get("importe_centimos") or 0) / 100)
    except (TypeError, ValueError):
        return _money(linea.get("importe"))


def _lines_breakdown(lineas: list) -> ft.Container:
    rows = []
    for linea in lineas:
        tipo_economico = str(linea.get("tipo_economico") or "").upper()
        tipo_fiscal = str(linea.get("tipo_fiscal") or "").upper()
        rows.append(
            ft.Row(
                controls=[
                    ft.Text(
                        f"{linea.get('posicion') or '-'}.",
                        size=11,
                        color=Q_MUTED,
                        width=18,
                    ),
                    ft.Text(
                        str(linea.get("concepto") or "-"),
                        size=11,
                        color=Q_PRIMARY_DARK,
                        expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        selectable=True,
                    ),
                    ft.Text(
                        " · ".join(
                            [
                                TIPO_ECONOMICO_LABELS.get(tipo_economico, tipo_economico or "-"),
                                TIPO_FISCAL_LABELS.get(tipo_fiscal, tipo_fiscal or "-"),
                            ]
                        ),
                        size=11,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        _line_money(linea),
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    return ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, "#E4E7EC"),
        border_radius=8,
        padding=ft.padding.symmetric(horizontal=9, vertical=6),
        content=ft.Column(controls=rows, spacing=3),
    )


def _date_badge(value) -> ft.Container:
    resolved = str(value or "-").strip() or "-"

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.CALENDAR_TODAY,
                    size=14,
                    color="#0057B8",
                ),
                ft.Text(
                    resolved,
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color="#0057B8",
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


def _metadata_text(label: str, value) -> ft.Text:
    resolved = str(value or "-").strip() or "-"
    return ft.Text(
        f"{label}: {resolved}",
        size=11,
        color=Q_MUTED,
        selectable=True,
    )


def _action_menu(cobro: dict, on_edit=None):
    items = []

    if on_edit is not None:
        items.append(
            ft.PopupMenuItem(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.EDIT_OUTLINED, size=16, color=Q_PRIMARY),
                        ft.Text("Editar cobro"),
                    ],
                    spacing=8,
                ),
                on_click=lambda e: on_edit(cobro),
            )
        )

    if not items:
        return None

    return ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT,
        tooltip="Acciones del cobro",
        items=items,
    )


def economic_payment_card(
    cobro: dict,
    *,
    date_display=None,
    on_edit=None,
):
    """
    Card reutilizable para un cobro del módulo económico.

    El componente no consulta servicios ni accede a base de datos.
    Recibe el registro ya cargado y callbacks proporcionados por la vista.
    """
    cobro = dict(cobro or {})

    numero_cobro = cobro.get("numero_cobro") or f"Cobro #{cobro.get('id') or '-'}"
    cliente = _client_name(cobro).upper()
    fecha = date_display(cobro.get("fecha_cobro")) if date_display else str(
        cobro.get("fecha_cobro") or "-"
    )

    reconciliation_status = _reconciliation_status(cobro)
    facturation_status = _facturation_status(cobro)
    fiscal_status = _fiscal_status(cobro)
    lineas = list(cobro.get("lineas") or [])

    actions = [
        control
        for control in [_action_menu(cobro, on_edit=on_edit)]
        if control is not None
    ]

    try:
        importe_value = float(cobro.get("importe") or 0)
    except (TypeError, ValueError):
        importe_value = 0.0

    badges = [
        status_chip(
            reconciliation_status,
            status_map=RECONCILIATION_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
        status_chip(
            facturation_status,
            status_map=FACTURATION_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
        status_chip(
            fiscal_status,
            status_map=FISCAL_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
    ]

    body = [
        ft.Row(
            controls=[
                ft.Text(
                    _money(importe_value),
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=Q_SUCCESS if importe_value >= 0 else Q_DANGER,
                ),
                _date_badge(fecha),
                _metadata_text("Forma", cobro.get("forma_pago")),
                _metadata_text("Tipo", cobro.get("tipo_cobro")),
                *(
                    [
                        ft.Text(
                            cobro.get("resumen_lineas")
                            or f"{len(lineas)} conceptos",
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY,
                        )
                    ]
                    if len(lineas) > 1
                    else []
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
                    cobro.get("numero_expediente") or "Sin expediente",
                ),
                _metadata_text(
                    "Hoja",
                    cobro.get("numero_hoja") or "Sin hoja",
                ),
                _metadata_text(
                    "Factura",
                    cobro.get("numero_factura") or "Sin factura",
                ),
            ],
            spacing=14,
            wrap=True,
        ),
    ]

    concepto = str(cobro.get("concepto") or "").strip()
    if len(lineas) > 1:
        # Una sola tarjeta por cobro: el desglose va dentro, no como
        # cobros adicionales.
        body.append(_lines_breakdown(lineas))
    elif concepto:
        body.append(
            ft.Text(
                concepto,
                size=12,
                color=Q_PRIMARY_DARK,
                selectable=True,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
        )

    return card_item(
        title=cliente,
        subtitle=numero_cobro,
        badges=badges,
        actions=actions,
        body=body,
        padding=11,
    )

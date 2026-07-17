from __future__ import annotations

from typing import Any, Callable

import flet as ft

from frontend.components.listing.card_item import card_item
from frontend.components.listing.status_chip import status_chip


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_WARNING = "#B54708"
Q_DANGER = "#B42318"
Q_BORDER = "#D0D5DD"


ENGAGEMENT_STATUS_MAP = {
    "PENDIENTE FIRMA": (
        "Pendiente de firma",
        "#FFFAEB",
        "#B54708",
        "#FEC84B",
    ),
    "FIRMADA": (
        "Firmada",
        "#ECFDF3",
        "#027A48",
        "#6CE9A6",
    ),
    "CANCELADA": (
        "Cancelada",
        "#FEF3F2",
        "#B42318",
        "#FDA29B",
    ),
    "ARCHIVADA": (
        "Archivada",
        "#F2F4F7",
        "#475467",
        "#D0D5DD",
    ),
}


def _money(value: Any) -> str:
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


def _text(value: Any, fallback="-") -> str:
    return str(value or "").strip() or fallback


def _amount(label, value, color=Q_PRIMARY_DARK):
    return ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        border_radius=9,
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
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
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    selectable=True,
                ),
            ],
            spacing=1,
            tight=True,
        ),
    )


def _metadata(label, value):
    return ft.Text(
        f"{label}: {_text(value)}",
        size=11,
        color=Q_MUTED,
        selectable=True,
    )


def economic_engagement_letter_card(
    engagement: dict[str, Any],
    *,
    date_display: Callable[[Any], str] | None = None,
    on_view_document: Callable[[dict[str, Any]], None] | None = None,
) -> ft.Control:
    engagement = dict(engagement or {})

    client_name = _text(
        engagement.get("cliente_nombre_completo"),
        f"Cliente no disponible (ID {engagement.get('cliente_id') or '-'})",
    ).upper()

    number = _text(
        engagement.get("numero_hoja"),
        f"Hoja #{engagement.get('id') or '-'}",
    )

    status = _text(
        engagement.get("estado"),
        "PENDIENTE FIRMA",
    ).upper()

    formatter = date_display or (
        lambda value: _text(value)
    )

    pending = float(
        engagement.get("importe_pendiente") or 0
    )

    discounts = (
        float(engagement.get("descuento_manual") or 0)
        + float(
            engagement.get(
                "descuento_consultas_previas"
            ) or 0
        )
    )

    actions = []
    document_path = _text(
        engagement.get("documento_ruta"),
        "",
    )

    if document_path and on_view_document is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.DESCRIPTION_OUTLINED,
                tooltip="Abrir documento",
                on_click=lambda e: on_view_document(
                    engagement
                ),
            )
        )

    badges = [
        status_chip(
            status,
            status_map=ENGAGEMENT_STATUS_MAP,
            compact=True,
            bordered=True,
        ),
        status_chip(
            "cobros",
            label=f"Cobros: {int(engagement.get('cobros_count') or 0)}",
            compact=True,
            bordered=True,
        ),
        status_chip(
            "facturas",
            label=f"Facturas: {int(engagement.get('facturas_count') or 0)}",
            compact=True,
            bordered=True,
        ),
    ]

    body = [
        ft.Row(
            controls=[
                _amount(
                    "Bruto",
                    engagement.get("importe_bruto"),
                ),
                _amount(
                    "Descuentos",
                    discounts,
                    Q_WARNING,
                ),
                _amount(
                    "Neto",
                    engagement.get("importe_neto"),
                    Q_PRIMARY,
                ),
                _amount(
                    "Cobrado",
                    engagement.get("total_cobrado"),
                    Q_SUCCESS,
                ),
                _amount(
                    "Pendiente",
                    pending,
                    Q_DANGER if pending > 0 else Q_SUCCESS,
                ),
            ],
            spacing=8,
            wrap=True,
        ),
        ft.Row(
            controls=[
                _metadata(
                    "Expediente",
                    engagement.get("numero_expediente")
                    or "Sin expediente",
                ),
                _metadata(
                    "Procedimiento",
                    engagement.get("procedimiento")
                    or "Sin procedimiento",
                ),
                _metadata(
                    "Firma",
                    formatter(
                        engagement.get("fecha_firma")
                    ),
                ),
                _metadata(
                    "Pago máximo",
                    formatter(
                        engagement.get(
                            "fecha_maxima_pago"
                        )
                    ),
                ),
            ],
            spacing=14,
            wrap=True,
        ),
        ft.Row(
            controls=[
                _metadata(
                    "Forma pactada",
                    engagement.get(
                        "forma_pago_pactada"
                    )
                    or "No indicada",
                ),
                _metadata(
                    "Plazos",
                    engagement.get("numero_plazos")
                    or 1,
                ),
            ],
            spacing=14,
            wrap=True,
        ),
    ]

    observations = _text(
        engagement.get("observaciones"),
        "",
    )

    if observations:
        body.append(
            ft.Text(
                observations,
                size=11,
                color=Q_PRIMARY_DARK,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
                selectable=True,
            )
        )

    return card_item(
        title=client_name,
        subtitle=number,
        badges=badges,
        actions=actions,
        body=body,
        padding=12,
    )

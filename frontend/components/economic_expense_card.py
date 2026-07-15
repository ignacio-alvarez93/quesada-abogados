from __future__ import annotations

from typing import Any, Callable

import flet as ft


Q_PRIMARY_DARK = "#17324D"
Q_MUTED = "#667085"
Q_BORDER = "#E4E7EC"
Q_BG = "#F8FAFC"


def _money_centimos(value: Any) -> str:
    try:
        amount = int(value or 0) / 100
    except (TypeError, ValueError):
        amount = 0

    return (
        f"{amount:,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _badge(
    label: str,
    *,
    background: str = "#F2F4F7",
    foreground: str = "#344054",
) -> ft.Container:
    return ft.Container(
        bgcolor=background,
        border_radius=999,
        padding=ft.Padding.symmetric(
            horizontal=10,
            vertical=5,
        ),
        content=ft.Text(
            label,
            size=11,
            weight=ft.FontWeight.W_600,
            color=foreground,
        ),
    )


def _document_badge(value: str) -> ft.Container:
    value = str(value or "SIN_JUSTIFICANTE").upper()

    labels = {
        "SIN_JUSTIFICANTE": "Sin justificante",
        "JUSTIFICANTE_ADJUNTO": "Justificante adjunto",
        "FACTURA_RECIBIDA": "Factura recibida",
        "DOCUMENTO_REVISADO": "Documento revisado",
    }

    if value == "SIN_JUSTIFICANTE":
        return _badge(
            labels[value],
            background="#FEF3F2",
            foreground="#B42318",
        )

    return _badge(
        labels.get(value, value.replace("_", " ").title()),
        background="#ECFDF3",
        foreground="#027A48",
    )


def _fiscal_badge(expense: dict[str, Any]) -> ft.Container:
    deductible = bool(
        expense.get("deducible_irpf")
        if expense.get("deducible_irpf") is not None
        else expense.get("deducible")
    )

    if deductible:
        return _badge(
            "Deducible",
            background="#ECFDF3",
            foreground="#027A48",
        )

    return _badge(
        "No deducible",
        background="#F2F4F7",
        foreground="#475467",
    )


def _reconciliation_badge(value: str) -> ft.Container:
    value = str(value or "PENDIENTE").upper()

    if value == "CONCILIADO":
        return _badge(
            "Conciliado",
            background="#ECFDF3",
            foreground="#027A48",
        )

    if value == "PARCIAL":
        return _badge(
            "Conciliado parcial",
            background="#FFFAEB",
            foreground="#B54708",
        )

    if value == "NO_REQUIERE_CONCILIACION":
        return _badge(
            "No requiere conciliación",
            background="#EFF8FF",
            foreground="#175CD3",
        )

    return _badge(
        "Pendiente de conciliar",
        background="#FFF4ED",
        foreground="#C4320A",
    )


def economic_expense_card(
    expense: dict[str, Any],
    *,
    on_view: Callable[[dict[str, Any]], None] | None = None,
    on_edit: Callable[[dict[str, Any]], None] | None = None,
    on_toggle_active: Callable[[dict[str, Any]], None] | None = None,
) -> ft.Control:
    supplier = (
        expense.get("supplier_display_name")
        or expense.get("proveedor")
        or "Sin proveedor"
    )

    concept = expense.get("concepto") or "Sin concepto"
    invoice = expense.get("numero_factura")
    category = expense.get("categoria") or "Sin categoría"
    date_value = expense.get("fecha_gasto") or "-"
    payment_method = expense.get("forma_pago") or "No indicada"

    subtitle_parts = [category]

    if invoice:
        subtitle_parts.append(f"Factura {invoice}")
    else:
        subtitle_parts.append("Sin número de factura")

    menu_items: list[ft.PopupMenuItem] = []

    if on_view is not None:
        menu_items.append(
            ft.PopupMenuItem(
                content=ft.Text("Ver ficha"),
                on_click=lambda e: on_view(expense),
            )
        )

    if on_edit is not None:
        menu_items.append(
            ft.PopupMenuItem(
                content=ft.Text("Editar"),
                on_click=lambda e: on_edit(expense),
            )
        )

    if on_toggle_active is not None:
        active = bool(expense.get("activo", 1))

        menu_items.append(
            ft.PopupMenuItem(
                content=ft.Text(
                    "Archivar" if active else "Restaurar"
                ),
                on_click=lambda e: on_toggle_active(expense),
            )
        )

    actions: list[ft.Control] = []

    if menu_items:
        actions.append(
            ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT,
                tooltip="Acciones",
                items=menu_items,
            )
        )

    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.Border.all(1, Q_BORDER),
        border_radius=14,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    str(supplier).upper(),
                                    size=15,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    concept,
                                    size=13,
                                    color="#344054",
                                ),
                                ft.Text(
                                    " · ".join(subtitle_parts),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Row(
                            controls=actions,
                            spacing=0,
                            tight=True,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Divider(
                    height=1,
                    color=Q_BORDER,
                ),
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "FECHA",
                                    size=10,
                                    color=Q_MUTED,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    str(date_value),
                                    size=13,
                                    color="#344054",
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "FORMA DE PAGO",
                                    size=10,
                                    color=Q_MUTED,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    str(payment_method),
                                    size=13,
                                    color="#344054",
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "TOTAL",
                                    size=10,
                                    color=Q_MUTED,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    _money_centimos(
                                        expense.get(
                                            "effective_total_centimos"
                                        )
                                    ),
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                            ],
                            spacing=2,
                            horizontal_alignment=(
                                ft.CrossAxisAlignment.END
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    (
                        "Base: "
                        f"{_money_centimos(expense.get('base_imponible_centimos'))}"
                        " · IVA: "
                        f"{_money_centimos(expense.get('iva_centimos'))}"
                        " · IRPF: "
                        f"{_money_centimos(expense.get('irpf_centimos'))}"
                    ),
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(
                    controls=[
                        _document_badge(
                            expense.get("estado_documental")
                        ),
                        _fiscal_badge(expense),
                        _reconciliation_badge(
                            expense.get("estado_conciliacion")
                        ),
                    ],
                    spacing=7,
                    wrap=True,
                ),
            ],
            spacing=11,
        ),
    )

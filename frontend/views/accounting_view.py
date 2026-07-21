from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import profit_and_loss_service


Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"


def _money(value_centimos) -> str:
    try:
        amount = int(value_centimos or 0) / 100
    except (TypeError, ValueError):
        amount = 0

    return (
        f"{amount:,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _metric_card(
    title: str,
    value_centimos: int,
    subtitle: str,
    *,
    foreground: str,
    background: str,
    border: str,
) -> ft.Container:
    return ft.Container(
        expand=True,
        bgcolor=background,
        border=ft.border.all(1, border),
        border_radius=14,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Text(
                    title,
                    size=12,
                    color=Q_MUTED,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    _money(value_centimos),
                    size=24,
                    color=foreground,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    subtitle,
                    size=11,
                    color=Q_MUTED,
                ),
            ],
            spacing=5,
        ),
    )


def accounting_view(page: ft.Page):
    state = {
        "section": "profit_and_loss",
        "year": None,
        "display_mode": "summary",
    }

    content_box = ft.Container()

    def refresh(e=None):
        content_box.content = build_content()
        page.update()

    def set_year(year: int):
        state["year"] = int(year)
        refresh()

    def year_button(year: int, selected_year: int):
        selected = int(year) == int(selected_year)

        return ft.Container(
            content=ft.Text(
                str(year),
                size=13,
                weight=ft.FontWeight.BOLD,
                color=Q_WHITE if selected else Q_PRIMARY_DARK,
            ),
            bgcolor=Q_PRIMARY_DARK if selected else "#EAF3FF",
            border=ft.border.all(
                1,
                Q_PRIMARY_DARK if selected else "#B2DDFF",
            ),
            border_radius=20,
            padding=ft.padding.symmetric(
                horizontal=14,
                vertical=7,
            ),
            ink=True,
            on_click=lambda e, y=year: set_year(y),
        )

    def set_display_mode(mode: str):
        state["display_mode"] = str(mode)
        refresh()


    def display_mode_chip(
        key: str,
        label: str,
        icon,
    ):
        selected = state.get(
            "display_mode"
        ) == key

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        icon,
                        size=16,
                        color=(
                            Q_WHITE
                            if selected
                            else Q_PRIMARY
                        ),
                    ),
                    ft.Text(
                        label,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=(
                            Q_WHITE
                            if selected
                            else Q_PRIMARY_DARK
                        ),
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=(
                Q_PRIMARY
                if selected
                else "#EAF3FF"
            ),
            border=ft.border.all(
                1,
                (
                    Q_PRIMARY
                    if selected
                    else "#B2DDFF"
                ),
            ),
            border_radius=20,
            padding=ft.padding.symmetric(
                horizontal=14,
                vertical=8,
            ),
            ink=True,
            on_click=lambda e, value=key: (
                set_display_mode(value)
            ),
        )


    def build_content():
        try:
            years = (
                profit_and_loss_service
                .available_profit_and_loss_years()
            )

            if not years:
                years = [datetime.today().year]

            selected_year = state.get("year")

            if selected_year not in years:
                selected_year = years[0]
                state["year"] = selected_year

            summary = (
                profit_and_loss_service
                .profit_and_loss_summary(
                    date_from=f"{selected_year}-01-01",
                    date_to=f"{selected_year}-12-31",
                )
            )

            monthly = (
                profit_and_loss_service
                .monthly_profit_and_loss(
                    year=selected_year,
                )
            )

        except Exception as exc:
            return ft.Container(
                bgcolor="#FEF3F2",
                border=ft.border.all(1, "#FDA29B"),
                border_radius=12,
                padding=14,
                content=ft.Text(
                    (
                        "No se pudo calcular la cuenta de "
                        f"pérdidas y ganancias: {exc}"
                    ),
                    color="#B42318",
                ),
            )

        income = summary["income"]
        expenses = summary["expenses"]
        result_centimos = int(
            summary["result_centimos"] or 0
        )
        positive = result_centimos >= 0

        active_months = [
            row
            for row in monthly
            if (
                int(row["income_centimos"] or 0)
                or int(
                    row["total_expenses_centimos"]
                    or 0
                )
            )
        ]

        monthly_controls = []

        for row in active_months:
            row_result = int(
                row["result_centimos"] or 0
            )

            monthly_controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(
                        vertical=9,
                        horizontal=8,
                    ),
                    border=ft.border.only(
                        bottom=ft.BorderSide(
                            1,
                            "#EEF2F7",
                        )
                    ),
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                width=90,
                                content=ft.Text(
                                    row["period_label"],
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                            ),
                            ft.Container(
                                expand=True,
                                content=ft.Text(
                                    _money(
                                        row[
                                            "income_centimos"
                                        ]
                                    ),
                                    size=12,
                                    color="#027A48",
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ),
                            ft.Container(
                                expand=True,
                                content=ft.Text(
                                    _money(
                                        row[
                                            "total_expenses_centimos"
                                        ]
                                    ),
                                    size=12,
                                    color="#B42318",
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ),
                            ft.Container(
                                expand=True,
                                content=ft.Text(
                                    _money(row_result),
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=(
                                        "#027A48"
                                        if row_result >= 0
                                        else "#B42318"
                                    ),
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ),
                            ft.Container(
                                width=90,
                                content=ft.Text(
                                    (
                                        f"{float(row['margin_percentage']):.2f}%"
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ),
                        ],
                        spacing=12,
                    ),
                )
            )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Pérdidas y ganancias",
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Resultado interno del "
                                        "despacho por ejercicio."
                                    ),
                                    size=13,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                        ft.Row(
                            controls=[
                                year_button(
                                    year,
                                    selected_year,
                                )
                                for year in years
                            ],
                            spacing=6,
                            wrap=True,
                        ),
                    ],
                    spacing=12,
                ),
                ft.Row(
                    controls=[
                        display_mode_chip(
                            "summary",
                            "Resumen",
                            ft.Icons.DASHBOARD_OUTLINED,
                        ),
                        display_mode_chip(
                            "monthly",
                            "Evolución mensual",
                            ft.Icons.CALENDAR_MONTH_OUTLINED,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(
                    visible=(
                        state.get("display_mode")
                        == "summary"
                    ),
                    bgcolor="#FFFAEB",
                    border=ft.border.all(1, "#FEC84B"),
                    border_radius=12,
                    padding=12,
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE,
                                color="#B54708",
                            ),
                            ft.Text(
                                (
                                    "Criterio interno de caja: "
                                    "el ingreso nace del cobro. "
                                    "Los suplidos no computan y "
                                    "la conciliación bancaria no "
                                    "crea ingresos ni gastos."
                                ),
                                size=12,
                                color="#7A2E0E",
                                expand=True,
                            ),
                        ],
                        spacing=10,
                    ),
                ),
                ft.Row(
                    visible=(
                        state.get("display_mode")
                        == "summary"
                    ),
                    controls=[
                        _metric_card(
                            "Ingresos computables",
                            income["computable_centimos"],
                            "Cobros activos sin suplidos",
                            foreground="#027A48",
                            background="#ECFDF3",
                            border="#6CE9A6",
                        ),
                        _metric_card(
                            "Gastos económicos",
                            expenses["total_centimos"],
                            "Sin IVA deducible",
                            foreground="#B42318",
                            background="#FEF3F2",
                            border="#FDA29B",
                        ),
                        _metric_card(
                            "Resultado",
                            result_centimos,
                            (
                                "Margen "
                                f"{summary['margin_percentage']:.2f}%"
                            ),
                            foreground=(
                                "#027A48"
                                if positive
                                else "#B42318"
                            ),
                            background=(
                                "#ECFDF3"
                                if positive
                                else "#FEF3F2"
                            ),
                            border=(
                                "#6CE9A6"
                                if positive
                                else "#FDA29B"
                            ),
                        ),
                    ],
                    spacing=12,
                ),
                ft.Container(
                    visible=(
                        state.get("display_mode")
                        == "summary"
                    ),
                    bgcolor=Q_WHITE,
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Composición de los ingresos",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Diferencia entre tesorería "
                                    "cobrada e ingreso reconocido."
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                            ft.Row(
                                controls=[
                                    _metric_card(
                                        "Cobros brutos",
                                        income[
                                            "collected_total_centimos"
                                        ],
                                        (
                                            f"{income['collection_count']} "
                                            "cobros activos"
                                        ),
                                        foreground=Q_PRIMARY_DARK,
                                        background="#F8FAFC",
                                        border=Q_BORDER,
                                    ),
                                    _metric_card(
                                        "Cobros sin suplidos",
                                        (
                                            income[
                                                "collected_total_centimos"
                                            ]
                                            - income[
                                                "suplidos_centimos"
                                            ]
                                        ),
                                        (
                                            "Total cobrado antes de "
                                            "descontar IVA e IRPF"
                                        ),
                                        foreground="#175CD3",
                                        background="#EFF8FF",
                                        border="#84CAFF",
                                    ),
                                    _metric_card(
                                        "IVA repercutido",
                                        income[
                                            "output_vat_centimos"
                                        ],
                                        "Excluido del ingreso",
                                        foreground="#B54708",
                                        background="#FFFAEB",
                                        border="#FEC84B",
                                    ),
                                    _metric_card(
                                        "Ingresos provisionales",
                                        income[
                                            "provisional_centimos"
                                        ],
                                        "Cobros todavía sin factura",
                                        foreground="#175CD3",
                                        background="#EFF8FF",
                                        border="#84CAFF",
                                    ),
                                    _metric_card(
                                        "Ingresos facturados",
                                        income[
                                            "invoiced_centimos"
                                        ],
                                        "Base definitiva facturada",
                                        foreground="#027A48",
                                        background="#ECFDF3",
                                        border="#6CE9A6",
                                    ),
                                ],
                                spacing=10,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        (
                                            "Suplidos excluidos: "
                                            f"{_money(income['suplidos_centimos'])}"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        (
                                            "IRPF retenido: "
                                            f"{_money(income['withholding_centimos'])}"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=20,
                            ),
                        ],
                        spacing=10,
                    ),
                ),
                ft.Row(
                    visible=(
                        state.get("display_mode")
                        == "summary"
                    ),
                    controls=[
                        _metric_card(
                            "Gastos operativos",
                            expenses["operating_centimos"],
                            "Proveedores y estructura",
                            foreground=Q_PRIMARY_DARK,
                            background="#EFF8FF",
                            border="#84CAFF",
                        ),
                        _metric_card(
                            "Nóminas",
                            expenses["payroll_centimos"],
                            "Salarios brutos",
                            foreground="#5925DC",
                            background="#F4F3FF",
                            border="#BDB4FE",
                        ),
                        _metric_card(
                            "Seguridad Social empresa",
                            expenses[
                                "employer_social_security_centimos"
                            ],
                            "Aportación empresarial",
                            foreground="#175CD3",
                            background="#EFF8FF",
                            border="#84CAFF",
                        ),
                    ],
                    spacing=12,
                ),
                ft.Container(
                    visible=(
                        state.get("display_mode")
                        == "monthly"
                    ),
                    bgcolor=Q_WHITE,
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Evolución mensual",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Ingresos, gastos y resultado "
                                    "por mes con actividad."
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border_radius=10,
                                padding=8,
                                content=ft.Row(
                                    controls=[
                                        ft.Container(
                                            width=90,
                                            content=ft.Text(
                                                "Periodo",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                            ),
                                        ),
                                        ft.Container(
                                            expand=True,
                                            content=ft.Text(
                                                "Ingresos",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                                text_align=ft.TextAlign.RIGHT,
                                            ),
                                        ),
                                        ft.Container(
                                            expand=True,
                                            content=ft.Text(
                                                "Gastos",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                                text_align=ft.TextAlign.RIGHT,
                                            ),
                                        ),
                                        ft.Container(
                                            expand=True,
                                            content=ft.Text(
                                                "Resultado",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                                text_align=ft.TextAlign.RIGHT,
                                            ),
                                        ),
                                        ft.Container(
                                            width=90,
                                            content=ft.Text(
                                                "Margen",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                                text_align=ft.TextAlign.RIGHT,
                                            ),
                                        ),
                                    ],
                                    spacing=12,
                                ),
                            ),
                            *(
                                monthly_controls
                                if monthly_controls
                                else [
                                    ft.Text(
                                        (
                                            "No existen ingresos ni "
                                            "gastos en este ejercicio."
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                        italic=True,
                                    )
                                ]
                            ),
                        ],
                        spacing=6,
                    ),
                ),
            ],
            spacing=14,
        )

    content_box.content = build_content()

    return ft.Column(
        controls=[
            ft.Text(
                "Contabilidad",
                size=28,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            ft.Text(
                (
                    "Análisis contable, resultados e "
                    "informes internos del despacho."
                ),
                size=14,
                color=Q_MUTED,
            ),
            ft.Container(
                content=ft.Text(
                    "Pérdidas y ganancias",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_WHITE,
                ),
                bgcolor=Q_PRIMARY,
                border_radius=20,
                padding=ft.padding.symmetric(
                    horizontal=14,
                    vertical=8,
                ),
                alignment=ft.alignment.Alignment(-1, 0),
            ),
            content_box,
        ],
        spacing=18,
        expand=True,
    )

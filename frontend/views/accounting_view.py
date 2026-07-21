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
                ft.Container(
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
                ft.Row(
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

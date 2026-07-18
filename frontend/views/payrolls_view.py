from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import worker_payroll_service
from frontend.components import empty_state


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"
Q_SUCCESS = "#15803D"
Q_WARNING = "#B45309"


MONTH_LABELS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def _money(value) -> str:
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


def _worker_name(payroll: dict) -> str:
    return " ".join(
        part
        for part in (
            str(payroll.get("first_name") or "").strip(),
            str(payroll.get("last_name_1") or "").strip(),
            str(payroll.get("last_name_2") or "").strip(),
        )
        if part
    ) or f"Trabajador #{payroll.get('worker_id')}"


def _summary_card(
    label: str,
    value: str,
    *,
    subtitle: str = "",
) -> ft.Control:
    controls = [
        ft.Text(
            label,
            size=12,
            color=Q_MUTED,
        ),
        ft.Text(
            value,
            size=21,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
    ]

    if subtitle:
        controls.append(
            ft.Text(
                subtitle,
                size=11,
                color=Q_MUTED,
            )
        )

    return ft.Container(
        expand=True,
        padding=14,
        bgcolor="#F8FAFC",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        content=ft.Column(
            controls=controls,
            spacing=3,
        ),
    )


def _amount_column(
    label: str,
    value,
    *,
    highlight: bool = False,
) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text(
                label,
                size=11,
                color=Q_MUTED,
            ),
            ft.Text(
                _money(value),
                size=14,
                weight=ft.FontWeight.BOLD,
                color=(
                    Q_PRIMARY
                    if highlight
                    else Q_PRIMARY_DARK
                ),
            ),
        ],
        spacing=2,
        expand=True,
    )


def _payroll_card(
    payroll: dict,
) -> ft.Control:
    year = int(
        payroll.get("period_year")
        or 0
    )
    month = int(
        payroll.get("period_month")
        or 0
    )

    expense_created = bool(
        payroll.get("salary_expense_id")
    )

    return ft.Container(
        padding=14,
        bgcolor=Q_WHITE,
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    _worker_name(payroll),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        f"{MONTH_LABELS.get(month, month)} "
                                        f"{year}"
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(
                                horizontal=10,
                                vertical=5,
                            ),
                            border_radius=20,
                            bgcolor=(
                                "#DCFCE7"
                                if expense_created
                                else "#FEF3C7"
                            ),
                            content=ft.Text(
                                (
                                    "Gasto generado"
                                    if expense_created
                                    else "Pendiente de gasto"
                                ),
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=(
                                    Q_SUCCESS
                                    if expense_created
                                    else Q_WARNING
                                ),
                            ),
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Divider(height=10),
                ft.Row(
                    controls=[
                        _amount_column(
                            "Bruto",
                            payroll.get(
                                "gross_salary_centimos"
                            ),
                        ),
                        _amount_column(
                            "Deducciones",
                            payroll.get(
                                "total_deductions_centimos"
                            ),
                        ),
                        _amount_column(
                            "Líquido",
                            payroll.get(
                                "net_salary_centimos"
                            ),
                            highlight=True,
                        ),
                        _amount_column(
                            "SS empresa",
                            payroll.get(
                                "employer_social_security_centimos"
                            ),
                        ),
                        _amount_column(
                            "Coste empresa",
                            payroll.get(
                                "total_employer_cost_centimos"
                            ),
                        ),
                    ],
                    spacing=12,
                ),
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                "Código: "
                                f"{payroll.get('worker_code') or '-'}"
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                        ft.Text(
                            (
                                "Puesto: "
                                f"{payroll.get('position') or '-'}"
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                        ft.Text(
                            (
                                "IRPF: "
                                f"{_money(payroll.get('irpf_centimos'))}"
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                        ft.Text(
                            (
                                "SS trabajador: "
                                f"{_money(payroll.get('employee_social_security_centimos'))}"
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=18,
                    wrap=True,
                ),
            ],
            spacing=8,
        ),
    )


def payrolls_view(
    page: ft.Page,
) -> ft.Control:
    now = datetime.now()

    year_filter = ft.Dropdown(
        label="Ejercicio",
        width=150,
        value=str(now.year),
        options=[
            ft.dropdown.Option(str(year))
            for year in range(
                now.year - 3,
                now.year + 2,
            )
        ],
    )

    month_filter = ft.Dropdown(
        label="Mes",
        width=180,
        value=str(now.month),
        options=[
            ft.dropdown.Option(
                key="",
                text="Todos",
            ),
            *[
                ft.dropdown.Option(
                    key=str(month),
                    text=label,
                )
                for month, label
                in MONTH_LABELS.items()
            ],
        ],
    )

    summary_row = ft.Row(
        controls=[],
        spacing=10,
    )

    payroll_list = ft.Column(
        controls=[],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def load_payrolls(_=None):
        selected_year = int(
            year_filter.value
            or now.year
        )
        selected_month = (
            int(month_filter.value)
            if month_filter.value
            else None
        )

        payrolls = (
            worker_payroll_service
            .list_payrolls(
                year=selected_year,
                month=selected_month,
            )
        )

        gross_total = sum(
            int(
                item.get(
                    "gross_salary_centimos"
                )
                or 0
            )
            for item in payrolls
        )

        net_total = sum(
            int(
                item.get(
                    "net_salary_centimos"
                )
                or 0
            )
            for item in payrolls
        )

        employer_ss_total = sum(
            int(
                item.get(
                    "employer_social_security_centimos"
                )
                or 0
            )
            for item in payrolls
        )

        employer_cost_total = sum(
            int(
                item.get(
                    "total_employer_cost_centimos"
                )
                or 0
            )
            for item in payrolls
        )

        summary_row.controls = [
            _summary_card(
                "Nóminas",
                str(len(payrolls)),
                subtitle="Registros del periodo",
            ),
            _summary_card(
                "Bruto",
                _money(gross_total),
            ),
            _summary_card(
                "Líquido",
                _money(net_total),
            ),
            _summary_card(
                "SS empresa",
                _money(employer_ss_total),
            ),
            _summary_card(
                "Coste total",
                _money(employer_cost_total),
            ),
        ]

        if payrolls:
            payroll_list.controls = [
                _payroll_card(payroll)
                for payroll in payrolls
            ]
        else:
            payroll_list.controls = [
                empty_state(
                    "No existen nóminas para "
                    "el periodo seleccionado"
                )
            ]

        try:
            summary_row.update()
            payroll_list.update()
        except Exception:
            pass

    year_filter.on_change = load_payrolls
    month_filter.on_change = load_payrolls

    load_payrolls()

    return ft.Container(
        expand=True,
        padding=ft.padding.only(
            left=8,
            top=4,
            right=12,
            bottom=4,
        ),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Nóminas",
                                    size=30,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Gestión de nóminas, "
                                        "costes laborales y "
                                        "pagos a trabajadores."
                                    ),
                                    size=13,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                        year_filter,
                        month_filter,
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="Actualizar",
                            on_click=load_payrolls,
                        ),
                        ft.FilledButton(
                            content=ft.Text(
                                "Nueva nómina"
                            ),
                            icon=ft.Icons.ADD,
                            disabled=True,
                            tooltip=(
                                "El alta se conectará "
                                "desde la ficha del trabajador"
                            ),
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                summary_row,
                ft.Container(
                    expand=True,
                    padding=14,
                    bgcolor=Q_WHITE,
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    content=payroll_list,
                ),
            ],
            spacing=14,
            expand=True,
        ),
    )

from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import fiscal_period_service
from frontend.components.app_alert import error_alert, warning_alert
from frontend.components.app_button import primary_button
from frontend.components.app_dropdown import select_input
from frontend.components.listing.status_chip import status_chip


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D8E2EE"
Q_SUCCESS = "#027A48"
Q_WARNING = "#B54708"
Q_DANGER = "#B42318"


PERIOD_STATUS_MAP = {
    "OPEN": ("Abierto", "#EFF8FF", "#175CD3", "#84CAFF"),
    "REVIEWED": ("Revisado", "#FFFAEB", "#B54708", "#FEC84B"),
    "CLOSED": ("Cerrado", "#ECFDF3", "#027A48", "#6CE9A6"),
}


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _money_centimos(value):
    amount = _int(value) / 100
    return (
        f"{amount:,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _result_label(result_type):
    labels = {
        "A_PAGAR": "A pagar",
        "A_COMPENSAR": "A compensar",
        "A_DEVOLVER": "A devolver",
        "CERO": "Resultado cero",
    }
    key = str(result_type or "").upper()
    return labels.get(key, key.replace("_", " ").title() or "-")


def _result_color(result_type):
    key = str(result_type or "").upper()

    if key == "A_PAGAR":
        return Q_DANGER

    if key in {"A_COMPENSAR", "A_DEVOLVER"}:
        return Q_SUCCESS

    return Q_PRIMARY_DARK


def _period_status(settings):
    if not settings:
        return "OPEN"

    return str(settings.get("status") or "OPEN").upper()


def _metric_block(
    label,
    value,
    *,
    color=Q_PRIMARY_DARK,
    background="#F8FAFC",
    border_color=Q_BORDER,
    width=210,
):
    return ft.Container(
        width=width,
        bgcolor=background,
        border=ft.border.all(1, border_color),
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=14, vertical=12),
        content=ft.Column(
            controls=[
                ft.Text(
                    label.upper(),
                    size=10,
                    weight=ft.FontWeight.BOLD,
                    color=Q_MUTED,
                ),
                ft.Text(
                    str(value),
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    selectable=True,
                ),
            ],
            spacing=3,
            tight=True,
        ),
    )


def _model_card(
    *,
    model_number,
    title,
    subtitle,
    model,
    settings,
):
    confirmed = model.get("confirmed") or {}
    provisional = model.get("provisional") or {}
    counts = model.get("counts") or {}

    if model_number == "303":
        detail_controls = [
            _metric_block(
                "IVA repercutido",
                _money_centimos(confirmed.get("output_vat_centimos")),
            ),
            _metric_block(
                "IVA soportado deducible",
                _money_centimos(
                    confirmed.get("deductible_input_vat_centimos")
                ),
            ),
            _metric_block(
                "Compensación anterior",
                _money_centimos(
                    confirmed.get("compensation_previous_centimos")
                ),
            ),
        ]

        count_text = (
            f"{counts.get('invoices_confirmed', 0)} facturas confirmadas · "
            f"{counts.get('expenses_confirmed', 0)} gastos confirmados · "
            f"{counts.get('expenses_pending_review', 0)} pendientes"
        )
    else:
        detail_controls = [
            _metric_block(
                "Ingresos acumulados",
                _money_centimos(confirmed.get("income_base_centimos")),
            ),
            _metric_block(
                "Gastos deducibles",
                _money_centimos(
                    confirmed.get(
                        "registered_deductible_expenses_centimos",
                        confirmed.get("deductible_expenses_centimos"),
                    )
                ),
            ),
            _metric_block(
                "Difícil justificación",
                _money_centimos(
                    confirmed.get("difficult_to_justify_expenses_centimos")
                ),
            ),
        ]

        count_text = (
            f"{counts.get('invoices_confirmed', 0)} facturas confirmadas · "
            f"{counts.get('expenses_confirmed', 0)} gastos confirmados"
        )

    confirmed_type = confirmed.get("result_type")
    provisional_type = provisional.get("result_type")

    return ft.Container(
        width=650,
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    f"Modelo {model_number}",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    title,
                                    size=13,
                                    weight=ft.FontWeight.W_600,
                                    color=Q_PRIMARY,
                                ),
                                ft.Text(
                                    subtitle,
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        status_chip(
                            _period_status(settings),
                            status_map=PERIOD_STATUS_MAP,
                            bordered=True,
                            compact=False,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Divider(height=1, color=Q_BORDER),
                ft.Row(
                    controls=[
                        _metric_block(
                            (
                                "Confirmado · "
                                f"{_result_label(confirmed_type)}"
                            ),
                            _money_centimos(
                                confirmed.get("result_centimos")
                            ),
                            color=_result_color(confirmed_type),
                        ),
                        _metric_block(
                            (
                                "Provisional · "
                                f"{_result_label(provisional_type)}"
                            ),
                            _money_centimos(
                                provisional.get("result_centimos")
                            ),
                            color=_result_color(provisional_type),
                            background="#FFFDF5",
                            border_color="#FEC84B",
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=detail_controls,
                    spacing=10,
                    wrap=True,
                ),
                ft.Text(count_text, size=11, color=Q_MUTED),
            ],
            spacing=13,
        ),
    )


def _warning_controls(summary):
    controls = []
    seen = set()

    for model_key in ("model_303", "model_130"):
        model = summary.get(model_key) or {}

        for warning in model.get("warnings") or []:
            message = str(warning.get("message") or "").strip()
            code = str(warning.get("code") or "")
            key = (code, message)

            if not message or key in seen:
                continue

            seen.add(key)
            controls.append(warning_alert(message))

    return controls


def fiscal_view(page: ft.Page):
    now = datetime.now()
    current_year = now.year
    current_quarter = ((now.month - 1) // 3) + 1

    state = {"summary": None}

    year_dropdown = select_input(
        "Ejercicio",
        [
            str(year)
            for year in range(current_year - 3, current_year + 2)
        ],
        value=str(current_year),
        width=150,
    )

    quarter_dropdown = select_input(
        "Trimestre",
        ["1", "2", "3", "4"],
        value=str(current_quarter),
        width=150,
    )

    message_box = ft.Column(spacing=8)
    content_box = ft.Container()

    def selected_period():
        year = _int(year_dropdown.value, current_year)
        quarter = _int(quarter_dropdown.value, current_quarter)

        if quarter not in {1, 2, 3, 4}:
            raise ValueError("Selecciona un trimestre válido")

        return year, quarter

    def load_summary():
        year, quarter = selected_period()

        state["summary"] = (
            fiscal_period_service.estimate_configured_period(
                year,
                quarter,
            )
        )

    def render_dashboard():
        summary = state.get("summary")

        if not summary:
            return ft.Text(
                "No hay cálculo fiscal disponible.",
                color=Q_MUTED,
            )

        model_303 = summary.get("model_303") or {}
        model_130 = summary.get("model_130") or {}
        combined = summary.get("combined") or {}
        settings = summary.get("settings") or {}

        warnings = _warning_controls(summary)

        return ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=16,
                    padding=18,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                width=430,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            (
                                                f"Previsión fiscal "
                                                f"{summary.get('quarter')}T "
                                                f"{summary.get('year')}"
                                            ),
                                            size=17,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            (
                                                "Estimación basada en "
                                                "facturas y gastos registrados."
                                            ),
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                ),
                            ),
                            _metric_block(
                                "Confirmado a pagar",
                                _money_centimos(
                                    combined.get(
                                        "confirmed_to_pay_centimos"
                                    )
                                ),
                                color=Q_DANGER,
                                background="#FEF3F2",
                                border_color="#FDA29B",
                            ),
                            _metric_block(
                                "Provisional a pagar",
                                _money_centimos(
                                    combined.get(
                                        "provisional_to_pay_centimos"
                                    )
                                ),
                                color=Q_WARNING,
                                background="#FFFAEB",
                                border_color="#FEC84B",
                            ),
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                ),
                ft.Row(
                    controls=[
                        _model_card(
                            model_number="303",
                            title="IVA trimestral",
                            subtitle=(
                                "IVA repercutido menos IVA "
                                "soportado deducible."
                            ),
                            model=model_303,
                            settings=settings.get("303"),
                        ),
                        _model_card(
                            model_number="130",
                            title="Pago fraccionado IRPF",
                            subtitle=(
                                "Cálculo acumulado desde "
                                "el 1 de enero."
                            ),
                            model=model_130,
                            settings=settings.get("130"),
                        ),
                    ],
                    spacing=14,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Column(
                    controls=warnings,
                    spacing=8,
                    visible=bool(warnings),
                ),
                ft.Container(
                    bgcolor="#EFF8FF",
                    border=ft.border.all(1, "#84CAFF"),
                    border_radius=12,
                    padding=14,
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE,
                                color=Q_PRIMARY,
                                size=20,
                            ),
                            ft.Text(
                                (
                                    "Los registros actuales son de prueba. "
                                    "Esta estimación no sustituye el "
                                    "cálculo de la asesoría."
                                ),
                                size=12,
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=14,
        )

    def refresh_view(event=None):
        try:
            load_summary()
            message_box.controls = []
            content_box.content = render_dashboard()
        except Exception as exc:
            message_box.controls = [
                error_alert(
                    f"No se pudo calcular el periodo fiscal: {exc}"
                )
            ]

        try:
            page.update()
        except Exception:
            pass

    year_dropdown.on_change = refresh_view
    quarter_dropdown.on_change = refresh_view

    refresh_button = primary_button(
        "Actualizar cálculo",
        refresh_view,
    )

    load_summary()
    content_box.content = render_dashboard()

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
                        ft.Container(
                            width=520,
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        "Fiscal",
                                        size=30,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            "Estimación continua de "
                                            "los modelos 303 y 130."
                                        ),
                                        size=14,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                            ),
                        ),
                        year_dropdown,
                        quarter_dropdown,
                        refresh_button,
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                message_box,
                content_box,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )

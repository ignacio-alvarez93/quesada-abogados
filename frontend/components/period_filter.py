"""
Selector temporal reutilizable.

Modos:
- ALL
- TODAY
- LAST_7_DAYS
- LAST_30_DAYS
- CUSTOM

Devuelve fechas normalizadas:
- desde: YYYY-MM-DD 00:00:00
- hasta: YYYY-MM-DD 23:59:59
"""

from datetime import datetime, timedelta

import flet as ft

from frontend.components.app_autocomplete import (
    AppAutocomplete,
)


PERIOD_ALL = "ALL"
PERIOD_TODAY = "TODAY"
PERIOD_LAST_7_DAYS = "LAST_7_DAYS"
PERIOD_LAST_30_DAYS = "LAST_30_DAYS"
PERIOD_CUSTOM = "CUSTOM"


PERIOD_LABELS = {
    PERIOD_ALL: "Todas",
    PERIOD_TODAY: "Hoy",
    PERIOD_LAST_7_DAYS: "Últimos 7 días",
    PERIOD_LAST_30_DAYS: "Últimos 30 días",
    PERIOD_CUSTOM: "Elegir fechas",
}


def _text(value):
    return str(value or "").strip()


def _parse_date(value):
    value = _text(value)

    if not value:
        return None

    for pattern in (
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                value,
                pattern,
            )
        except ValueError:
            continue

    raise ValueError(
        "La fecha debe tener formato "
        "dd/mm/aaaa."
    )


def resolve_period(
    value,
    *,
    custom_from="",
    custom_to="",
    now=None,
):
    normalized = _text(
        value
    ).upper() or PERIOD_ALL

    current = now or datetime.now()

    if normalized == PERIOD_ALL:
        return {
            "value": PERIOD_ALL,
            "label": PERIOD_LABELS[
                PERIOD_ALL
            ],
            "date_from": "",
            "date_to": "",
            "custom_from": "",
            "custom_to": "",
        }

    if normalized == PERIOD_TODAY:
        start = current.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = current.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )

    elif normalized == PERIOD_LAST_7_DAYS:
        start = (
            current
            - timedelta(days=6)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = current.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )

    elif normalized == PERIOD_LAST_30_DAYS:
        start = (
            current
            - timedelta(days=29)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = current.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )

    elif normalized == PERIOD_CUSTOM:
        parsed_from = _parse_date(
            custom_from
        )
        parsed_to = _parse_date(
            custom_to
        )

        if (
            parsed_from
            and parsed_to
            and parsed_from.date()
            > parsed_to.date()
        ):
            raise ValueError(
                "La fecha desde no puede ser "
                "posterior a la fecha hasta."
            )

        start = (
            parsed_from.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            if parsed_from
            else None
        )

        end = (
            parsed_to.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=0,
            )
            if parsed_to
            else None
        )

    else:
        return resolve_period(
            PERIOD_ALL,
            now=current,
        )

    return {
        "value": normalized,
        "label": PERIOD_LABELS.get(
            normalized,
            normalized,
        ),
        "date_from": (
            start.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if start
            else ""
        ),
        "date_to": (
            end.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if end
            else ""
        ),
        "custom_from": _text(
            custom_from
        ),
        "custom_to": _text(
            custom_to
        ),
    }



def build_period_filter(
    page,
    *,
    initial_value=PERIOD_ALL,
    initial_custom_from="",
    initial_custom_to="",
    on_change=None,
    width=215,
    label="Periodo",
):
    """
    Construye un filtro temporal basado en AppAutocomplete.

    El objeto devuelto expone:
    - control: control visual para insertar en la vista.
    - set_value(): restaura o cambia el periodo.
    - get_value(): devuelve el código interno.
    - period_state: estado temporal resuelto.
    """

    option_codes = {
        label_text: code
        for code, label_text
        in PERIOD_LABELS.items()
    }

    options = [
        {
            "id": PERIOD_ALL,
            "label": PERIOD_LABELS[
                PERIOD_ALL
            ],
        },
        {
            "id": PERIOD_TODAY,
            "label": PERIOD_LABELS[
                PERIOD_TODAY
            ],
        },
        {
            "id": PERIOD_LAST_7_DAYS,
            "label": PERIOD_LABELS[
                PERIOD_LAST_7_DAYS
            ],
        },
        {
            "id": PERIOD_LAST_30_DAYS,
            "label": PERIOD_LABELS[
                PERIOD_LAST_30_DAYS
            ],
        },
        {
            "id": PERIOD_CUSTOM,
            "label": PERIOD_LABELS[
                PERIOD_CUSTOM
            ],
        },
    ]

    state = resolve_period(
        initial_value,
        custom_from=initial_custom_from,
        custom_to=initial_custom_to,
    )

    autocomplete = None

    def safe_update():
        try:
            page.update()
        except Exception:
            pass

    def emit(result):
        state.clear()
        state.update(result)

        if autocomplete is not None:
            autocomplete.set_value(
                result["label"],
                update=False,
            )

        if callable(on_change):
            on_change(dict(result))

        safe_update()

    def close_dialog(dialog):
        dialog.open = False
        safe_update()

    def open_custom_dialog():
        from_field = ft.TextField(
            label="Desde",
            hint_text="dd/mm/aaaa",
            value=state.get(
                "custom_from"
            )
            or "",
            width=200,
            dense=True,
        )

        to_field = ft.TextField(
            label="Hasta",
            hint_text="dd/mm/aaaa",
            value=state.get(
                "custom_to"
            )
            or "",
            width=200,
            dense=True,
        )

        error_text = ft.Text(
            "",
            size=11,
            color="#B42318",
        )

        previous_label = state.get(
            "label"
        ) or PERIOD_LABELS[
            PERIOD_ALL
        ]

        def apply_custom(e=None):
            try:
                result = resolve_period(
                    PERIOD_CUSTOM,
                    custom_from=(
                        from_field.value
                    ),
                    custom_to=(
                        to_field.value
                    ),
                )
            except ValueError as exc:
                error_text.value = str(exc)
                safe_update()
                return

            close_dialog(dialog)
            emit(result)

        def cancel(e=None):
            autocomplete.set_value(
                previous_label,
                update=False,
            )
            close_dialog(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Elegir fechas",
                weight=ft.FontWeight.BOLD,
                color="#003B7A",
            ),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Text(
                        (
                            "Puedes indicar ambas "
                            "fechas o dejar uno de "
                            "los límites vacío."
                        ),
                        size=12,
                        color="#64748B",
                    ),
                    ft.Row(
                        controls=[
                            from_field,
                            to_field,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    error_text,
                ],
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=cancel,
                ),
                ft.TextButton(
                    "Aplicar",
                    on_click=apply_custom,
                ),
            ],
        )

        page.overlay.append(dialog)
        dialog.open = True
        safe_update()

    def handle_select(selected_label):
        selected_label = str(
            selected_label or ""
        ).strip()

        selected_code = option_codes.get(
            selected_label
        )

        if selected_code is None:
            # No se admite texto libre:
            # restauramos el último periodo válido.
            autocomplete.set_value(
                state.get("label")
                or PERIOD_LABELS[
                    PERIOD_ALL
                ],
                update=False,
            )
            safe_update()
            return

        if selected_code == PERIOD_CUSTOM:
            open_custom_dialog()
            return

        emit(
            resolve_period(
                selected_code
            )
        )

    autocomplete = AppAutocomplete(
        page,
        label,
        options=options,
        value=state["label"],
        width=width,
        max_results=5,
        on_select=handle_select,
        allow_free_text=False,
        hint_text="Seleccionar periodo",
        empty_text="Periodo no válido",
        show_empty=False,
    )

    # API compatible con el uso anterior.
    autocomplete.period_state = state

    def set_period_value(
        value,
        update=True,
    ):
        code = str(
            value or PERIOD_ALL
        ).strip().upper()

        if code not in PERIOD_LABELS:
            code = PERIOD_ALL

        result = resolve_period(code)

        state.clear()
        state.update(result)

        autocomplete.set_value(
            result["label"],
            update=update,
        )

    def get_period_value():
        return state.get(
            "value"
        ) or PERIOD_ALL

    autocomplete.set_period_value = (
        set_period_value
    )
    autocomplete.get_period_value = (
        get_period_value
    )

    return autocomplete


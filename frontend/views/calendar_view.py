from datetime import datetime, timedelta
import time

import flet as ft

from backend.services import calendar_service
from backend.services import calendar_agenda_summary_service
from backend.services import calendar_alert_service
from backend.services import expedient_service
from backend.services import task_service
from backend.services import (
    calendar_task_application_service
    as calendar_task_app,
)

from backend.services import (
    scheduled_notification_service,
)

from backend.services import (
    calendar_alert_application_service
    as calendar_alert_app,
)

from backend.services import (
    calendar_alert_recurrence_service
    as calendar_alert_recurrence,
)

from backend.services import (
    calendar_alert_recurrence_application_service
    as calendar_alert_recurrence_app,
)



from frontend.components.app_button import (
    primary_button,
    secondary_button,
    danger_button,
)

from frontend.components.app_card import (
    metric_card,
)

from frontend.components.app_dropdown import (
    select_input,
)

from frontend.components.app_text_field import (
    text_input,
    required_text_input,
    multiline_input,
)

from frontend.components.app_dialog import (
    form_dialog,
)

from frontend.components.app_autocomplete import (
    AppAutocomplete,
)

from frontend.components.listing.status_chip import (
    status_chip,
)

from frontend.components.calendar import (
    calendar_week_grid,
    calendar_summary_panel,
)

from frontend.components.calendar.calendar_month_grid import (
    calendar_month_grid,
)

from frontend.components.calendar.calendar_today_view import (
    calendar_today_primary,
    calendar_today_summary,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_BG = "#F5F8FC"


PRIORITY_STATUS_MAP = {
    "BAJA": (
        "Baja",
        "#ECFDF3",
        "#027A48",
    ),
    "NORMAL": (
        "Normal",
        "#F1F5F9",
        "#475569",
    ),
    "ALTA": (
        "Alta",
        "#EEF4FF",
        "#0057B8",
    ),
    "URGENTE": (
        "Urgente",
        "#FEF3F2",
        "#B42318",
    ),
}


def _monday(value):
    current = (
        value
        if isinstance(value, datetime)
        else datetime.now()
    )

    return (
        current
        - timedelta(
            days=current.weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _date_display(value):
    raw = str(value or "")

    try:
        parsed = datetime.fromisoformat(
            raw.replace(
                "T",
                " ",
            )
        )

        return parsed.strftime(
            "%d/%m/%Y %H:%M"
        )

    except Exception:
        return raw



def _option_id(value):
    raw = str(value or "").strip()

    if not raw or " - " not in raw:
        return None

    try:
        return int(
            raw.split(" - ", 1)[0]
        )
    except Exception:
        return None


def _task_form_datetime(
    date_value,
    time_value,
):
    date_raw = str(
        date_value or ""
    ).strip()

    time_raw = str(
        time_value or ""
    ).strip()

    if not date_raw:
        raise ValueError(
            "La fecha de vencimiento es obligatoria."
        )

    if not time_raw:
        time_raw = "09:00"

    for fmt in (
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(
                f"{date_raw} {time_raw}",
                fmt,
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass

    raise ValueError(
        "Fecha u hora no válida. "
        "Usa DD/MM/AAAA y HH:MM."
    )


def _task_projection(task):
    return {
        "item_type": "TASK",
        "source_id": task.get("id"),
        "title": task.get("titulo") or "",
        "description":
            task.get("descripcion") or "",
        "date":
            task.get("fecha_vencimiento") or "",
        "warning_date": None,
        "priority":
            task.get("prioridad") or "NORMAL",
        "status":
            task.get("estado") or "PENDIENTE",
        "responsible":
            task.get("responsable") or "",
        "cliente_id":
            task.get("cliente_id"),
        "client_name": " ".join(
            value
            for value in (
                task.get("cliente_nombre"),
                task.get(
                    "cliente_primer_apellido"
                ),
                task.get(
                    "cliente_segundo_apellido"
                ),
            )
            if value
        ),
        "expediente_id":
            task.get("expediente_id"),
        "expedient_number":
            task.get("numero_expediente")
            or "",
        "origin_type":
            task.get("origen_tipo")
            or "MANUAL",
        "origin_id":
            task.get("origen_id"),
        "source_key":
            task.get("source_key")
            or "",
    }


def _alert_projection(
    alert,
    *,
    previous=None,
):
    previous = previous or {}

    return {
        "item_type": "ALERT",
        "source_id": alert.get("id"),
        "title": alert.get("titulo") or "",
        "description":
            alert.get("descripcion") or "",
        "date":
            alert.get("fecha_evento") or "",
        "warning_date":
            alert.get("fecha_inicio_aviso") or "",
        "priority":
            alert.get("prioridad") or "NORMAL",
        "status":
            alert.get("estado") or "ACTIVO",
        "responsible": "",
        "cliente_id":
            alert.get("cliente_id"),
        "client_name": (
            " ".join(
                value
                for value in (
                    alert.get(
                        "cliente_nombre"
                    ),
                    alert.get(
                        "cliente_primer_apellido"
                    ),
                    alert.get(
                        "cliente_segundo_apellido"
                    ),
                )
                if value
            )
            or previous.get(
                "client_name"
            )
            or ""
        ),
        "expediente_id":
            alert.get("expediente_id"),
        "expedient_number": (
            alert.get(
                "numero_expediente"
            )
            or previous.get(
                "expedient_number"
            )
            or ""
        ),
        "origin_type":
            alert.get("origen_tipo")
            or "MANUAL",
        "origin_id":
            alert.get("origen_id"),
        "source_key":
            alert.get("source_key")
            or "",
    }


def calendar_view(
    page: ft.Page,
    on_open_expediente=None,
    on_open_cliente=None,
    initial_action=None,
    initial_client_id=None,
    initial_expedient_id=None,
    on_context_back=None,
):
    state = {
        "view_mode": "TODAY",
        "week_start": _monday(
            datetime.now()
        ),
        "month_anchor": (
            datetime.now()
            .replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        ),
        "items": [],
        "summary": {},
        "selected_item": None,
        "last_upcoming_click_key": None,
        "last_upcoming_click_at": 0.0,
    }

    content = ft.Container(
        expand=True,
    )

    # ==============================================================
    # FORMULARIO NUEVA TAREA
    # ==============================================================

    client_rows = (
        expedient_service
        .get_clientes_for_select()
    )

    client_options = [
        row["display"]
        for row in client_rows
    ]

    task_title = required_text_input(
        "Título",
        width=720,
    )

    task_description = multiline_input(
        "Descripción",
        width=720,
        height=100,
    )

    task_client = AppAutocomplete(
        page=page,
        label="Cliente",
        options=client_options,
        width=270,
        max_results=8,
        allow_free_text=False,
        helper_text=(
            "Opcional. Al seleccionar cliente "
            "se filtran sus expedientes."
        ),
    )

    task_expedient = AppAutocomplete(
        page=page,
        label="Expediente",
        options=[],
        width=720,
        max_results=8,
        allow_free_text=False,
        helper_text=(
            "Opcional. Solo expedientes activos "
            "del cliente seleccionado."
        ),
    )

    task_priority = select_input(
        "Prioridad",
        [
            "BAJA",
            "NORMAL",
            "ALTA",
            "URGENTE",
        ],
        value="NORMAL",
        width=220,
    )

    task_responsible = text_input(
        "Responsable",
        width=300,
    )

    task_due_date = required_text_input(
        "Fecha vencimiento DD/MM/AAAA",
        width=300,
    )

    task_due_time = required_text_input(
        "Hora HH:MM",
        value="09:00",
        width=180,
    )

    task_dialog = None
    editing_task_id = None

    # ==============================================================
    # FORMULARIO NUEVO AVISO
    # ==============================================================

    alert_title = required_text_input(
        "Título",
        width=550,
    )

    alert_description = multiline_input(
        "Descripción",
        width=550,
        height=100,
    )

    alert_client = AppAutocomplete(
        page=page,
        label="Cliente",
        options=client_options,
        width=235,
        max_results=8,
        allow_free_text=False,
        helper_text=(
            "Opcional. Al seleccionar cliente "
            "se filtran sus expedientes."
        ),
    )

    alert_expedient = AppAutocomplete(
        page=page,
        label="Expediente",
        options=[],
        width=235,
        max_results=8,
        allow_free_text=False,
        helper_text=(
            "Opcional. Solo expedientes "
            "del cliente seleccionado."
        ),
    )

    alert_priority = select_input(
        "Prioridad",
        [
            "BAJA",
            "NORMAL",
            "ALTA",
            "URGENTE",
        ],
        value="NORMAL",
        width=220,
    )

    alert_event_date = required_text_input(
        "Fecha del evento DD/MM/AAAA",
        width=300,
    )

    alert_event_time = required_text_input(
        "Hora HH:MM",
        value="09:00",
        width=180,
    )

    alert_warning_date = text_input(
        "Avisarme desde DD/MM/AAAA",
        width=300,
    )

    alert_warning_time = text_input(
        "Hora aviso HH:MM",
        value="",
        width=180,
    )

    # --------------------------------------------------------------
    # RECURRENCIA DE AVISOS
    # --------------------------------------------------------------

    alert_recurrence_enabled = ft.Switch(
        value=True,
        active_color=Q_PRIMARY,
    )

    alert_recurrence_interval = required_text_input(
        "Cada",
        value="1",
        width=90,
    )

    alert_recurrence_frequency = select_input(
        "Frecuencia",
        [
            "Días",
            "Semanas",
            "Meses",
            "Años",
        ],
        value="Meses",
        width=170,
    )

    alert_recurrence_end_type = ft.RadioGroup(
        value="NEVER",
        content=ft.Row(
            controls=[
                ft.Radio(
                    value="NEVER",
                    label="Nunca",
                ),
                ft.Radio(
                    value="DATE",
                    label="En una fecha",
                ),
                ft.Radio(
                    value="COUNT",
                    label="Después de X avisos",
                ),
            ],
            spacing=18,
            wrap=True,
        ),
    )

    alert_recurrence_end_date = text_input(
        "Fecha final DD/MM/AAAA",
        width=190,
    )

    alert_recurrence_count = text_input(
        "Número total de avisos",
        value="10",
        width=190,
    )

    alert_recurrence_preview_title = ft.Text(
        "PRÓXIMOS RECORDATORIOS",
        size=10,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_DARK,
    )

    alert_recurrence_preview = ft.Column(
        controls=[],
        spacing=6,
        tight=True,
    )

    alert_recurrence_end_date.visible = False
    alert_recurrence_count.visible = False

    alert_recurrence_panel = ft.Container(
        visible=False,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        alert_recurrence_interval,
                        alert_recurrence_frequency,
                    ],
                    spacing=8,
                ),

                ft.Text(
                    "Finalizar",
                    size=10,
                    weight=ft.FontWeight.W_600,
                    color=Q_PRIMARY_DARK,
                ),

                alert_recurrence_end_type,

                alert_recurrence_end_date,
                alert_recurrence_count,

                ft.Divider(
                    height=6,
                    color=Q_BORDER,
                ),

                ft.Container(
                    bgcolor="#EFF6FF",
                    border_radius=9,
                    padding=10,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons
                                        .CALENDAR_MONTH_OUTLINED,
                                        size=15,
                                        color=Q_PRIMARY,
                                    ),
                                    alert_recurrence_preview_title,
                                ],
                                spacing=6,
                            ),
                            alert_recurrence_preview,
                        ],
                        spacing=5,
                        tight=True,
                    ),
                ),
            ],
            spacing=7,
            tight=True,
        ),
    )


    alert_dialog = None
    editing_alert_id = None

    search_input = text_input(
        "Buscar tarea / aviso / expediente / cliente",
        width=360,
    )

    responsible_filter = (
        select_input(
            "Responsable",
            ["Todos"],
            value="Todos",
            width=190,
        )
    )

    priority_filter = select_input(
        "Prioridad",
        [
            "Todos",
            "BAJA",
            "NORMAL",
            "ALTA",
            "URGENTE",
        ],
        value="Todos",
        width=170,
    )

    status_filter = select_input(
        "Estado",
        [
            "Todos",
            "PENDIENTE",
            "EN_CURSO",
            "COMPLETADA",
            "CANCELADA",
            "ACTIVO",
            "RESUELTO",
            "CANCELADO",
        ],
        value="Todos",
        width=180,
    )

    type_filter = select_input(
        "Tipo",
        [
            "Todos",
            "TASK",
            "ALERT",
        ],
        value="Todos",
        width=160,
    )


    # ==============================================================
    # AGENDA COMPLETA
    # ==============================================================

    agenda_search = text_input(
        "Buscar cliente, expediente o actuación",
        width=320,
    )

    agenda_type_filter = select_input(
        "Tipo",
        [
            "Todos",
            "TASK",
            "ALERT",
        ],
        value="Todos",
        width=150,
    )

    agenda_status_filter = select_input(
        "Estado",
        [
            "Todos",
            "PENDIENTE",
            "EN_CURSO",
            "COMPLETADA",
            "CANCELADA",
            "ACTIVO",
            "RESUELTO",
            "CANCELADO",
        ],
        value="Todos",
        width=180,
    )

    agenda_priority_filter = select_input(
        "Prioridad",
        [
            "Todos",
            "BAJA",
            "NORMAL",
            "ALTA",
            "URGENTE",
        ],
        value="Todos",
        width=160,
    )

    agenda_date_from = text_input(
        "Desde DD/MM/AAAA",
        width=170,
    )

    agenda_date_to = text_input(
        "Hasta DD/MM/AAAA",
        width=170,
    )

    agenda_include_archived = ft.Checkbox(
        label="Incluir archivados",
        value=False,
    )

    agenda_dialog = None

    # Igual que table_container en Clientes:
    # este contenedor permanece montado mientras
    # se reconstruye únicamente su contenido.
    agenda_table_container = ft.Container()

    agenda_count_text = ft.Text(
        "",
        size=10,
        color=Q_MUTED,
        expand=True,
    )

    def _agenda_parse_date(
        value,
        *,
        end_of_day=False,
    ):
        raw = str(
            value or ""
        ).strip()

        if not raw:
            return None

        for fmt in (
            "%d/%m/%Y",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(
                    raw,
                    fmt,
                )

                if end_of_day:
                    parsed = parsed.replace(
                        hour=23,
                        minute=59,
                        second=59,
                    )

                return parsed

            except ValueError:
                pass

        raise ValueError(
            "Fecha no válida. Usa DD/MM/AAAA."
        )


    def _agenda_task_item(task):
        return _task_projection(
            task
        )


    def _agenda_alert_item(alert):
        return _alert_projection(
            alert
        )


    def safe_update():
        try:
            content.update()
        except Exception:
            pass

    def _show_message(
        message,
        *,
        error=False,
    ):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(
                str(message),
                color=(
                    "#FFFFFF"
                    if error
                    else "#0F172A"
                ),
            ),
            bgcolor=(
                "#B42318"
                if error
                else "#ECFDF3"
            ),
        )

        page.snack_bar.open = True
        page.update()


    def _expedient_label(expedient):
        number = (
            expedient.get(
                "numero_expediente"
            )
            or f"EXP {expedient.get('id')}"
        )

        tipo = (
            expedient.get(
                "tipo_expediente_nombre"
            )
            or ""
        )

        subtipo = (
            expedient.get(
                "subtipo_expediente_nombre"
            )
            or ""
        )

        suffix = " · ".join(
            value
            for value in (
                tipo,
                subtipo,
            )
            if value
        )

        return (
            f"{expedient['id']} - {number}"
            + (
                f" · {suffix}"
                if suffix
                else ""
            )
        )


    def _refresh_task_expedients():
        client_id = _option_id(
            task_client.input.value
        )

        if not client_id:
            task_expedient.set_options(
                [],
                clear_value=True,
            )

            try:
                task_expedient.control.update()
            except Exception:
                pass

            return

        expedients = (
            expedient_service
            .get_expedientes(
                cliente_id=client_id,
                active_only=True,
            )
        )

        task_expedient.set_options(
            [
                _expedient_label(item)
                for item in expedients
            ],
            clear_value=True,
        )

        try:
            task_expedient.control.update()
        except Exception:
            pass


    def _on_task_client_select(*args):
        _refresh_task_expedients()


    task_client.on_select = (
        _on_task_client_select
    )


    def _client_label_by_id(client_id):
        if not client_id:
            return ""

        prefix = f"{int(client_id)} - "

        for row in client_rows:
            display = str(
                row.get("display")
                or ""
            )

            if display.startswith(prefix):
                return display

        return ""


    def _load_task_form_for_edit(task):
        task_title.value = str(
            task.get("titulo")
            or ""
        )

        task_description.value = str(
            task.get("descripcion")
            or ""
        )

        client_id = task.get(
            "cliente_id"
        )

        client_label = (
            _client_label_by_id(
                client_id
            )
        )

        task_client.set_value(
            client_label,
            update=False,
        )

        task_expedient.set_options(
            [],
            clear_value=True,
        )

        if client_id:
            expedients = (
                expedient_service
                .get_expedientes(
                    cliente_id=int(
                        client_id
                    ),
                    active_only=False,
                )
            )

            labels = [
                _expedient_label(item)
                for item in expedients
            ]

            task_expedient.set_options(
                labels,
                clear_value=False,
            )

            current_expedient_id = (
                task.get(
                    "expediente_id"
                )
            )

            if current_expedient_id:
                prefix = (
                    f"{int(current_expedient_id)} - "
                )

                current_label = next(
                    (
                        label
                        for label in labels
                        if str(label).startswith(
                            prefix
                        )
                    ),
                    "",
                )

                if not current_label:
                    expedient = (
                        expedient_service
                        .get_expediente(
                            int(
                                current_expedient_id
                            )
                        )
                    )

                    if expedient:
                        current_label = (
                            _expedient_label(
                                expedient
                            )
                        )

                        task_expedient.set_options(
                            [
                                current_label,
                                *task_expedient.options,
                            ],
                            clear_value=False,
                        )

                task_expedient.set_value(
                    current_label,
                    update=False,
                )

        task_priority.value = (
            task.get("prioridad")
            or "NORMAL"
        )

        task_responsible.value = str(
            task.get("responsable")
            or ""
        )

        due_raw = str(
            task.get(
                "fecha_vencimiento"
            )
            or ""
        )

        try:
            due_dt = datetime.fromisoformat(
                due_raw.replace(
                    "T",
                    " ",
                )
            )

            task_due_date.value = (
                due_dt.strftime(
                    "%d/%m/%Y"
                )
            )

            task_due_time.value = (
                due_dt.strftime(
                    "%H:%M"
                )
            )

        except Exception:
            task_due_date.value = ""
            task_due_time.value = "09:00"


    def _refresh_alert_expedients():
        client_id = _option_id(
            alert_client.input.value
        )

        if not client_id:
            alert_expedient.set_options(
                [],
                clear_value=True,
            )

            try:
                alert_expedient.control.update()
            except Exception:
                pass

            return

        expedients = (
            expedient_service
            .get_expedientes(
                cliente_id=client_id,
                active_only=True,
            )
        )

        alert_expedient.set_options(
            [
                _expedient_label(item)
                for item in expedients
            ],
            clear_value=True,
        )

        try:
            alert_expedient.control.update()
        except Exception:
            pass


    def _on_alert_client_select(*args):
        _refresh_alert_expedients()


    alert_client.on_select = (
        _on_alert_client_select
    )


    def _load_alert_form_for_edit(
        alert,
    ):
        alert_title.value = str(
            alert.get("titulo")
            or ""
        )

        alert_description.value = str(
            alert.get("descripcion")
            or ""
        )

        client_id = alert.get(
            "cliente_id"
        )

        client_label = (
            _client_label_by_id(
                client_id
            )
        )

        alert_client.set_value(
            client_label,
            update=False,
        )

        alert_expedient.set_options(
            [],
            clear_value=True,
        )

        if client_id:
            expedients = (
                expedient_service
                .get_expedientes(
                    cliente_id=int(
                        client_id
                    ),
                    active_only=False,
                )
            )

            labels = [
                _expedient_label(item)
                for item in expedients
            ]

            alert_expedient.set_options(
                labels,
                clear_value=False,
            )

            current_expedient_id = (
                alert.get(
                    "expediente_id"
                )
            )

            if current_expedient_id:
                prefix = (
                    f"{int(current_expedient_id)} - "
                )

                current_label = next(
                    (
                        label
                        for label in labels
                        if str(label).startswith(
                            prefix
                        )
                    ),
                    "",
                )

                if not current_label:
                    expedient = (
                        expedient_service
                        .get_expediente(
                            int(
                                current_expedient_id
                            )
                        )
                    )

                    if expedient:
                        current_label = (
                            _expedient_label(
                                expedient
                            )
                        )

                        alert_expedient.set_options(
                            [
                                current_label,
                                *labels,
                            ],
                            clear_value=False,
                        )

                alert_expedient.set_value(
                    current_label,
                    update=False,
                )

        alert_priority.value = (
            alert.get("prioridad")
            or "NORMAL"
        )

        event_raw = str(
            alert.get("fecha_evento")
            or ""
        ).strip()

        if event_raw:
            event_dt = datetime.fromisoformat(
                event_raw.replace(
                    "T",
                    " ",
                )
            )

            alert_event_date.value = (
                event_dt.strftime(
                    "%d/%m/%Y"
                )
            )

            alert_event_time.value = (
                event_dt.strftime(
                    "%H:%M"
                )
            )

        warning_raw = str(
            alert.get(
                "fecha_inicio_aviso"
            )
            or ""
        ).strip()

        if warning_raw:
            warning_dt = datetime.fromisoformat(
                warning_raw.replace(
                    "T",
                    " ",
                )
            )

            alert_warning_date.value = (
                warning_dt.strftime(
                    "%d/%m/%Y"
                )
            )

            alert_warning_time.value = (
                warning_dt.strftime(
                    "%H:%M"
                )
            )
        else:
            alert_warning_date.value = ""
            alert_warning_time.value = ""


    def _reset_alert_form():
        alert_title.value = ""
        alert_description.value = ""

        alert_event_date.disabled = False
        alert_event_time.disabled = False
        alert_warning_date.disabled = False
        alert_warning_time.disabled = False

        alert_client.set_value(
            "",
            update=False,
        )

        alert_expedient.set_options(
            [],
            clear_value=True,
        )

        alert_priority.value = "NORMAL"

        now = datetime.now()

        alert_event_date.value = (
            now.strftime(
                "%d/%m/%Y"
            )
        )

        alert_event_time.value = "09:00"

        alert_warning_date.value = ""
        alert_warning_time.value = ""

        alert_recurrence_enabled.value = True
        alert_recurrence_interval.value = "1"
        alert_recurrence_frequency.value = "Meses"
        alert_recurrence_end_type.value = "NEVER"
        alert_recurrence_end_date.value = ""
        alert_recurrence_count.value = "10"

        alert_recurrence_panel.visible = True
        alert_recurrence_end_date.visible = False
        alert_recurrence_count.visible = False

        alert_recurrence_preview.controls = []


    def _optional_alert_datetime(
        date_value,
        time_value,
    ):
        clean_date = str(
            date_value or ""
        ).strip()

        clean_time = str(
            time_value or ""
        ).strip()

        if not clean_date and not clean_time:
            return None

        if not clean_date:
            raise ValueError(
                "Indica la fecha de aviso."
            )

        if not clean_time:
            raise ValueError(
                "Indica la hora de aviso."
            )

        return _task_form_datetime(
            clean_date,
            clean_time,
        )


    def _alert_recurrence_frequency_code():
        mapping = {
            "Días": "DAY",
            "Semanas": "WEEK",
            "Meses": "MONTH",
            "Años": "YEAR",
        }

        value = str(
            alert_recurrence_frequency.value
            or "Meses"
        ).strip()

        return mapping.get(
            value,
            "MONTH",
        )


    def _alert_recurrence_end_datetime(
        event_at,
    ):
        if (
            alert_recurrence_end_type.value
            != "DATE"
        ):
            return None

        raw = str(
            alert_recurrence_end_date.value
            or ""
        ).strip()

        if not raw:
            raise ValueError(
                "Indica la fecha final "
                "de la recurrencia."
            )

        # El campo representa solamente una fecha.
        # Si por cualquier motivo visual contiene también
        # la hora ("13/08/2026 · 09:00"), conservamos
        # exclusivamente la parte DD/MM/AAAA.
        clean_date = (
            raw.split(
                "·",
                1,
            )[0]
            .strip()
        )

        try:
            end_day = datetime.strptime(
                clean_date,
                "%d/%m/%Y",
            )

        except ValueError as exc:
            raise ValueError(
                "Fecha final no válida. "
                "Usa DD/MM/AAAA."
            ) from exc

        event_datetime = (
            event_at
            if isinstance(
                event_at,
                datetime,
            )
            else datetime.fromisoformat(
                str(event_at).replace(
                    "T",
                    " ",
                )
            )
        )

        result = end_day.replace(
            hour=event_datetime.hour,
            minute=event_datetime.minute,
            second=event_datetime.second,
            microsecond=0,
        )

        # Mantenemos visualmente el campo como fecha,
        # nunca como fecha + hora.
        alert_recurrence_end_date.value = (
            end_day.strftime(
                "%d/%m/%Y"
            )
        )

        return result


    def _alert_recurrence_values():
        try:
            interval_value = int(
                str(
                    alert_recurrence_interval.value
                    or ""
                ).strip()
            )

        except ValueError as exc:
            raise ValueError(
                "El intervalo de recurrencia "
                "debe ser un número entero."
            ) from exc

        if interval_value < 1:
            raise ValueError(
                "El intervalo de recurrencia "
                "debe ser igual o superior a 1."
            )

        end_type = str(
            alert_recurrence_end_type.value
            or "NEVER"
        ).upper()

        event_raw = _task_form_datetime(
            alert_event_date.value,
            alert_event_time.value,
        )

        warning_raw = (
            _optional_alert_datetime(
                alert_warning_date.value,
                alert_warning_time.value,
            )
        )

        event_at = datetime.fromisoformat(
            str(event_raw).replace(
                "T",
                " ",
            )
        )

        warning_at = (
            datetime.fromisoformat(
                str(warning_raw).replace(
                    "T",
                    " ",
                )
            )
            if warning_raw
            else None
        )

        # La periodicidad pertenece a los
        # recordatorios, no al evento.
        #
        # Si no existe fecha específica de aviso,
        # la propia fecha del evento actúa como
        # primer y único punto natural de partida.
        anchor_at = (
            warning_at
            or event_at
        )

        if anchor_at > event_at:
            raise ValueError(
                "La fecha de inicio del aviso "
                "no puede ser posterior a la "
                "fecha del evento."
            )

        end_date = (
            _alert_recurrence_end_datetime(
                event_at
            )
        )

        max_occurrences = None

        if end_type == "COUNT":
            try:
                max_occurrences = int(
                    str(
                        alert_recurrence_count.value
                        or ""
                    ).strip()
                )

            except ValueError as exc:
                raise ValueError(
                    "El número de avisos "
                    "debe ser un entero."
                ) from exc

            if max_occurrences < 1:
                raise ValueError(
                    "El número de avisos "
                    "debe ser superior a 0."
                )

        return {
            "event_at": event_at,
            "anchor_at": anchor_at,
            "frequency_unit": (
                _alert_recurrence_frequency_code()
            ),
            "interval_value": interval_value,
            "end_type": end_type,
            "end_date": end_date,
            "max_occurrences": max_occurrences,
        }


    def _refresh_alert_recurrence_preview(
        e=None,
    ):
        enabled = bool(
            alert_recurrence_enabled.value
        )

        alert_recurrence_panel.visible = (
            enabled
        )

        end_type = str(
            alert_recurrence_end_type.value
            or "NEVER"
        ).upper()

        alert_recurrence_end_date.visible = (
            enabled
            and end_type == "DATE"
        )

        alert_recurrence_count.visible = (
            enabled
            and end_type == "COUNT"
        )

        alert_recurrence_preview.controls = []

        if not enabled:
            page.update()
            return

        try:
            values = (
                _alert_recurrence_values()
            )

            occurrences = (
                calendar_alert_recurrence
                .preview_occurrences(
                    values["anchor_at"],
                    frequency_unit=(
                        values[
                            "frequency_unit"
                        ]
                    ),
                    interval_value=(
                        values[
                            "interval_value"
                        ]
                    ),
                    end_type=(
                        values[
                            "end_type"
                        ]
                    ),
                    end_date=(
                        values[
                            "end_date"
                        ]
                    ),
                    max_occurrences=(
                        values[
                            "max_occurrences"
                        ]
                    ),
                    limit=4,
                )
            )

            # El preview representa recordatorios,
            # no nuevas fechas de evento.
            #
            # El servicio puede devolver datetime
            # o texto ISO. Normalizamos antes de
            # comparar con la fecha real del evento.
            future_items = []

            for item in occurrences:
                item_datetime = (
                    item
                    if isinstance(
                        item,
                        datetime,
                    )
                    else datetime.fromisoformat(
                        str(item).replace(
                            "T",
                            " ",
                        )
                    )
                )

                if (
                    item_datetime
                    <= values["event_at"]
                ):
                    future_items.append(
                        item_datetime
                    )

            if not future_items:
                alert_recurrence_preview.controls = [
                    ft.Text(
                        (
                            "La configuración no genera "
                            "repeticiones posteriores."
                        ),
                        size=11,
                        color=Q_MUTED,
                    )
                ]

            else:
                preview_rows = []

                for item in future_items:
                    item_datetime = (
                        item
                        if isinstance(
                            item,
                            datetime,
                        )
                        else datetime.fromisoformat(
                            str(item).replace(
                                "T",
                                " ",
                            )
                        )
                    )

                    preview_rows.append(
                        ft.Text(
                            (
                                "• "
                                + item_datetime.strftime(
                                    "%d/%m/%Y %H:%M"
                                )
                            ),
                            size=10,
                            weight=ft.FontWeight.W_500,
                            color=Q_PRIMARY_DARK,
                        )
                    )

                alert_recurrence_preview.controls = [
                    ft.Column(
                        controls=preview_rows,
                        spacing=4,
                        tight=True,
                    )
                ]

        except Exception as exc:
            alert_recurrence_preview.controls = [
                ft.Text(
                    str(exc),
                    size=11,
                    color="#B42318",
                )
            ]

        page.update()


    alert_recurrence_enabled.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_recurrence_interval.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_recurrence_frequency.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_recurrence_end_type.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_recurrence_end_date.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_recurrence_count.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_event_date.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_event_time.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_warning_date.on_change = (
        _refresh_alert_recurrence_preview
    )

    alert_warning_time.on_change = (
        _refresh_alert_recurrence_preview
    )


    def _set_contextual_client_and_expedient(
        *,
        client_id=None,
        expedient_id=None,
        target="TASK",
    ):
        if not client_id:
            return

        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            return

        client_label = _client_label_by_id(
            client_id
        )

        if not client_label:
            return

        if target == "ALERT":
            client_control = alert_client
            expedient_control = alert_expedient
            refresh_expedients = (
                _refresh_alert_expedients
            )
        else:
            client_control = task_client
            expedient_control = task_expedient
            refresh_expedients = (
                _refresh_task_expedients
            )

        client_control.set_value(
            client_label,
            update=False,
        )

        refresh_expedients()

        if not expedient_id:
            return

        try:
            expedient_id = int(
                expedient_id
            )
        except (TypeError, ValueError):
            return

        prefix = f"{expedient_id} - "

        selected_label = next(
            (
                option
                for option
                in expedient_control.options
                if str(option).startswith(
                    prefix
                )
            ),
            "",
        )

        if not selected_label:
            expedient = (
                expedient_service
                .get_expediente(
                    expedient_id
                )
            )

            if expedient:
                selected_label = (
                    _expedient_label(
                        expedient
                    )
                )

                expedient_control.set_options(
                    [
                        selected_label,
                        *expedient_control.options,
                    ],
                    clear_value=False,
                )

        if selected_label:
            expedient_control.set_value(
                selected_label,
                update=False,
            )


    def _reset_task_form():
        task_title.value = ""
        task_description.value = ""

        task_client.input.value = ""
        task_client.selected_option = None

        task_expedient.set_options(
            [],
            clear_value=True,
        )

        task_priority.value = "NORMAL"
        task_responsible.value = ""

        now = datetime.now()

        task_due_date.value = (
            now.strftime("%d/%m/%Y")
        )

        task_due_time.value = "09:00"


    def _close_task_dialog(
        e=None,
        *,
        return_to_context=True,
    ):
        nonlocal task_dialog

        if task_dialog is None:
            return

        page.pop_dialog()
        page.update()

        task_dialog = None

        if (
            return_to_context
            and on_context_back
            and str(
                initial_action
                or ""
            ).upper()
            == "TASK"
        ):
            on_context_back()


    def _close_alert_dialog(
        e=None,
        *,
        return_to_context=True,
    ):
        nonlocal alert_dialog

        if alert_dialog is None:
            return

        page.pop_dialog()
        page.update()

        alert_dialog = None

        if (
            return_to_context
            and on_context_back
            and str(
                initial_action
                or ""
            ).upper()
            == "ALERT"
        ):
            on_context_back()


    def _save_alert_edit(e=None):
        nonlocal alert_dialog
        nonlocal editing_alert_id

        if not editing_alert_id:
            return

        alert_id = int(
            editing_alert_id
        )

        try:
            title = str(
                alert_title.value
                or ""
            ).strip()

            if not title:
                raise ValueError(
                    "El título es obligatorio."
                )

            event_at = _task_form_datetime(
                alert_event_date.value,
                alert_event_time.value,
            )

            warning_at = (
                _optional_alert_datetime(
                    alert_warning_date.value,
                    alert_warning_time.value,
                )
            )

            warning_update = (
                ""
                if warning_at is None
                else warning_at
            )

            client_id = _option_id(
                alert_client.input.value
            )

            expedient_id = _option_id(
                alert_expedient.input.value
            )

            if expedient_id:
                expedient = (
                    expedient_service
                    .get_expediente(
                        expedient_id
                    )
                )

                if not expedient:
                    raise ValueError(
                        "El expediente seleccionado "
                        "no existe."
                    )

                expedient_client_id = (
                    expedient.get(
                        "cliente_id"
                    )
                )

                if (
                    client_id
                    and expedient_client_id
                    and int(client_id)
                    != int(
                        expedient_client_id
                    )
                ):
                    raise ValueError(
                        "El expediente no pertenece "
                        "al cliente seleccionado."
                    )

                if not client_id:
                    client_id = (
                        expedient_client_id
                    )

            (
                calendar_alert_app
                .update_calendar_alert(
                    alert_id,
                    titulo=title,
                    descripcion=str(
                        alert_description.value
                        or ""
                    ).strip(),
                    cliente_id=client_id,
                    expediente_id=(
                        expedient_id
                    ),
                    prioridad=(
                        alert_priority.value
                        or "NORMAL"
                    ),
                    fecha_evento=event_at,
                    fecha_inicio_aviso=(
                        warning_update
                    ),
                )
            )

            _close_alert_dialog()

            editing_alert_id = None

            refresh()

            _reload_selected_alert(
                alert_id
            )

            render()
            safe_update()
            _refresh_detail_dialog()

            _show_message(
                "Aviso actualizado correctamente."
            )

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _save_alert(e=None):
        nonlocal alert_dialog

        try:
            title = str(
                alert_title.value
                or ""
            ).strip()

            if not title:
                raise ValueError(
                    "El título es obligatorio."
                )

            event_at = _task_form_datetime(
                alert_event_date.value,
                alert_event_time.value,
            )

            warning_at = (
                _optional_alert_datetime(
                    alert_warning_date.value,
                    alert_warning_time.value,
                )
            )

            client_id = _option_id(
                alert_client.input.value
            )

            expedient_id = _option_id(
                alert_expedient.input.value
            )

            # Misma protección relacional que TASK.
            if expedient_id:
                expedient = (
                    expedient_service
                    .get_expediente(
                        expedient_id
                    )
                )

                if not expedient:
                    raise ValueError(
                        "El expediente seleccionado "
                        "no existe."
                    )

                expedient_client_id = (
                    expedient.get(
                        "cliente_id"
                    )
                )

                if (
                    client_id
                    and expedient_client_id
                    and int(client_id)
                    != int(
                        expedient_client_id
                    )
                ):
                    raise ValueError(
                        "El expediente no pertenece "
                        "al cliente seleccionado."
                    )

                if not client_id:
                    client_id = (
                        expedient_client_id
                    )

            description = str(
                alert_description.value
                or ""
            ).strip()

            if alert_recurrence_enabled.value:
                recurrence_values = (
                    _alert_recurrence_values()
                )

                result = (
                    calendar_alert_recurrence_app
                    .create_recurring_alert(
                        titulo=title,
                        descripcion=description,
                        cliente_id=client_id,
                        expediente_id=(
                            expedient_id
                        ),
                        tipo="GENERAL",
                        prioridad=(
                            alert_priority.value
                            or "NORMAL"
                        ),
                        fecha_evento=event_at,
                        fecha_inicio_aviso=(
                            warning_at
                        ),
                        frequency_unit=(
                            recurrence_values[
                                "frequency_unit"
                            ]
                        ),
                        interval_value=(
                            recurrence_values[
                                "interval_value"
                            ]
                        ),
                        end_type=(
                            recurrence_values[
                                "end_type"
                            ]
                        ),
                        end_date=(
                            recurrence_values[
                                "end_date"
                            ]
                        ),
                        max_occurrences=(
                            recurrence_values[
                                "max_occurrences"
                            ]
                        ),
                        origen_tipo="MANUAL",
                        created_by="ERP",
                    )
                )

                alert = result["alert"]

                materialized = (
                    calendar_alert_recurrence_app
                    .materialize_until_limit(
                        result[
                            "recurrence"
                        ]["id"],
                    )
                )

            else:
                result = (
                    calendar_alert_app
                    .create_calendar_alert(
                        titulo=title,
                        descripcion=description,
                        cliente_id=client_id,
                        expediente_id=(
                            expedient_id
                        ),
                        tipo="GENERAL",
                        prioridad=(
                            alert_priority.value
                            or "NORMAL"
                        ),
                        fecha_evento=event_at,
                        fecha_inicio_aviso=(
                            warning_at
                        ),
                        origen_tipo="MANUAL",
                        created_by="ERP",
                    )
                )

                alert = result["alert"]
                materialized = []

            # Llevar automáticamente Calendar
            # a la semana donde ocurre el evento.
            event_dt = datetime.fromisoformat(
                str(
                    alert[
                        "fecha_evento"
                    ]
                ).replace(
                    "T",
                    " ",
                )
            )

            state["week_start"] = (
                _monday(
                    event_dt
                )
            )

            _clear_calendar_filters()

            _close_alert_dialog(
                return_to_context=False,
            )

            refresh()
            render()
            safe_update()

            if alert_recurrence_enabled.value:
                _show_message(
                    (
                        "Serie de avisos creada correctamente. "
                        f"{1 + len(materialized)} avisos "
                        "disponibles y Telegram programado."
                    )
                )
            else:
                _show_message(
                    (
                        "Aviso creado correctamente. "
                        "Telegram programado."
                    )
                )

            if (
                on_context_back
                and str(
                    initial_action
                    or ""
                ).upper()
                == "ALERT"
            ):
                on_context_back()

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _clear_calendar_filters(
        *,
        update=False,
    ):
        search_input.value = ""
        responsible_filter.value = "Todos"
        priority_filter.value = "Todos"
        status_filter.value = "Todos"
        type_filter.value = "Todos"

        if update:
            render()
            safe_update()


    def _save_task_edit(e=None):
        nonlocal task_dialog
        nonlocal editing_task_id

        if not editing_task_id:
            return

        task_id = int(
            editing_task_id
        )

        try:
            title = str(
                task_title.value
                or ""
            ).strip()

            if not title:
                raise ValueError(
                    "El título es obligatorio."
                )

            due_at = _task_form_datetime(
                task_due_date.value,
                task_due_time.value,
            )

            client_id = _option_id(
                task_client.input.value
            )

            expedient_id = _option_id(
                task_expedient.input.value
            )

            # Mantener la misma seguridad relacional
            # que ya usamos al crear una tarea.
            if expedient_id:
                expedient = (
                    expedient_service
                    .get_expediente(
                        expedient_id
                    )
                )

                if not expedient:
                    raise ValueError(
                        "El expediente seleccionado "
                        "no existe."
                    )

                expedient_client_id = (
                    expedient.get(
                        "cliente_id"
                    )
                )

                if (
                    client_id
                    and expedient_client_id
                    and int(client_id)
                    != int(
                        expedient_client_id
                    )
                ):
                    raise ValueError(
                        "El expediente no pertenece "
                        "al cliente seleccionado."
                    )

                if not client_id:
                    client_id = (
                        expedient_client_id
                    )

            calendar_task_app.update_calendar_task(
                task_id,
                titulo=title,
                descripcion=str(
                    task_description.value
                    or ""
                ).strip(),
                cliente_id=client_id,
                expediente_id=(
                    expedient_id
                ),
                prioridad=(
                    task_priority.value
                    or "NORMAL"
                ),
                responsable=str(
                    task_responsible.value
                    or ""
                ).strip(),
                fecha_vencimiento=due_at,
            )

            # Cerramos únicamente el diálogo de edición.
            _close_task_dialog()

            editing_task_id = None

            refresh()

            _reload_selected_task(
                task_id
            )

            render()
            safe_update()

            # El detalle permanece debajo del formulario
            # de edición y se reconstruye con la tarea
            # recién actualizada.
            _refresh_detail_dialog()

            _show_message(
                "Tarea actualizada correctamente."
            )

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _save_task(e=None):
        nonlocal task_dialog

        try:
            title = str(
                task_title.value or ""
            ).strip()

            if not title:
                raise ValueError(
                    "El título es obligatorio."
                )

            due_at = _task_form_datetime(
                task_due_date.value,
                task_due_time.value,
            )

            client_id = _option_id(
                task_client.input.value
            )

            expedient_id = _option_id(
                task_expedient.input.value
            )

            # Seguridad relacional:
            # un expediente seleccionado debe pertenecer
            # al cliente seleccionado.
            if expedient_id:
                expedient = (
                    expedient_service
                    .get_expediente(
                        expedient_id
                    )
                )

                if not expedient:
                    raise ValueError(
                        "El expediente seleccionado "
                        "no existe."
                    )

                expedient_client_id = (
                    expedient.get(
                        "cliente_id"
                    )
                )

                if (
                    client_id
                    and expedient_client_id
                    and int(client_id)
                    != int(expedient_client_id)
                ):
                    raise ValueError(
                        "El expediente no pertenece "
                        "al cliente seleccionado."
                    )

                if not client_id:
                    client_id = (
                        expedient_client_id
                    )

            result = (
                calendar_task_app
                .create_calendar_task(
                    titulo=title,
                    descripcion=str(
                        task_description.value
                        or ""
                    ).strip(),
                    cliente_id=client_id,
                    expediente_id=(
                        expedient_id
                    ),
                    prioridad=(
                        task_priority.value
                        or "NORMAL"
                    ),
                    responsable=str(
                        task_responsible.value
                        or ""
                    ).strip(),
                    fecha_vencimiento=due_at,
                )
            )

            created_task = result["task"]

            _close_task_dialog(
                return_to_context=False,
            )

            # Si la fecha cae fuera de la semana visible,
            # saltamos automáticamente a su semana.
            due_dt = datetime.fromisoformat(
                created_task[
                    "fecha_vencimiento"
                ].replace("T", " ")
            )

            state["week_start"] = _monday(
                due_dt
            )

            state["selected_item"] = (
                _task_projection(
                    created_task
                )
            )

            # Una tarea recién creada no debe quedar
            # aparentemente oculta por filtros antiguos.
            _clear_calendar_filters(
                update=False,
            )

            refresh()

            # refresh conserva una selección canónica
            # si el elemento está en la semana cargada.
            for item in state["items"]:
                if (
                    item.get("item_type")
                    == "TASK"
                    and int(
                        item.get("source_id")
                        or 0
                    )
                    == int(
                        created_task["id"]
                    )
                ):
                    state[
                        "selected_item"
                    ] = item
                    break

            render()
            safe_update()

            _show_message(
                "Tarea creada y "
                "notificaciones Telegram programadas."
            )

            if (
                on_context_back
                and str(
                    initial_action
                    or ""
                ).upper()
                == "TASK"
            ):
                on_context_back()

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _open_edit_task_dialog(e=None):
        nonlocal task_dialog
        nonlocal editing_task_id

        item = state.get(
            "selected_item"
        ) or {}

        if (
            item.get("item_type")
            != "TASK"
        ):
            return

        task_id = int(
            item.get("source_id")
            or 0
        )

        if not task_id:
            return

        task = task_service.get_task(
            task_id
        )

        if not task:
            _show_message(
                "No se ha podido cargar la tarea.",
                error=True,
            )
            return

        editing_task_id = task_id

        _load_task_form_for_edit(
            task
        )

        task_dialog = form_dialog(
            "Editar tarea",
            ft.Container(
                width=760,
                content=ft.Column(
                    controls=[
                        task_title,
                        task_description,
                        task_client.control,
                        task_expedient.control,
                        ft.Row(
                            controls=[
                                task_priority,
                                task_responsible,
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Row(
                            controls=[
                                task_due_date,
                                task_due_time,
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Container(
                            bgcolor="#F8FAFC",
                            border=ft.border.all(
                                1,
                                Q_BORDER,
                            ),
                            border_radius=10,
                            padding=12,
                            content=ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons
                                        .SYNC_ROUNDED,
                                        size=18,
                                        color=Q_PRIMARY,
                                    ),
                                    ft.Text(
                                        (
                                            "Si cambias el vencimiento "
                                            "o la prioridad, las "
                                            "notificaciones Telegram "
                                            "se recalcularán "
                                            "automáticamente."
                                        ),
                                        size=11,
                                        color=Q_MUTED,
                                        expand=True,
                                    ),
                                ],
                                spacing=8,
                            ),
                        ),
                    ],
                    spacing=12,
                    tight=True,
                ),
            ),
            actions=[
                secondary_button(
                    "Cancelar",
                    _close_task_dialog,
                ),
                primary_button(
                    "Guardar cambios",
                    _save_task_edit,
                ),
            ],
        )

        page.show_dialog(
            task_dialog
        )

        page.update()


    def _open_edit_alert_dialog(e=None):
        nonlocal alert_dialog
        nonlocal editing_alert_id

        item = state.get(
            "selected_item"
        ) or {}

        if (
            item.get("item_type")
            != "ALERT"
        ):
            return

        alert_id = int(
            item.get("source_id")
            or 0
        )

        if not alert_id:
            return

        alert = (
            calendar_alert_service
            .get_alert(
                alert_id
            )
        )

        if not alert:
            _show_message(
                "No se ha podido cargar el aviso.",
                error=True,
            )
            return

        editing_alert_id = alert_id

        _load_alert_form_for_edit(
            alert
        )

        recurrence = (
            calendar_alert_recurrence
            .get_recurrence_for_alert(
                alert_id
            )
        )

        recurrence_is_operational = (
            recurrence
            and recurrence.get("estado")
            in {
                "ACTIVA",
                "PAUSADA",
            }
        )

        alert_event_date.disabled = (
            recurrence_is_operational
        )
        alert_event_time.disabled = (
            recurrence_is_operational
        )
        alert_warning_date.disabled = (
            recurrence_is_operational
        )
        alert_warning_time.disabled = (
            recurrence_is_operational
        )

        alert_dialog = form_dialog(
            "Editar aviso",
            ft.Container(
                width=760,
                content=ft.Column(
                    controls=[
                        alert_title,
                        alert_description,
                        alert_client.control,
                        alert_expedient.control,
                        ft.Row(
                            controls=[
                                alert_priority,
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Text(
                            "Fecha del evento",
                            size=11,
                            weight=(
                                ft.FontWeight.W_600
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Row(
                            controls=[
                                alert_event_date,
                                alert_event_time,
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Text(
                            "Notificación",
                            size=11,
                            weight=(
                                ft.FontWeight.W_600
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Row(
                            controls=[
                                alert_warning_date,
                                alert_warning_time,
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        ft.Container(
                            bgcolor="#F8FAFC",
                            border=ft.border.all(
                                1,
                                Q_BORDER,
                            ),
                            border_radius=10,
                            padding=12,
                            content=ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons
                                        .SYNC_ROUNDED,
                                        size=18,
                                        color=Q_PRIMARY,
                                    ),
                                    ft.Text(
                                        (
                                            (
                                                "Este aviso pertenece "
                                                "a una serie recurrente. "
                                                "Puedes modificar sus "
                                                "datos generales, pero "
                                                "no sus fechas mientras "
                                                "la serie esté activa "
                                                "o pausada. Para cambiar "
                                                "la planificación, "
                                                "cancela la serie y "
                                                "crea una nueva."
                                            )
                                            if recurrence_is_operational
                                            else (
                                                "Si cambias la fecha del "
                                                "evento o la fecha de "
                                                "aviso, Telegram "
                                                "cancelará la "
                                                "planificación anterior "
                                                "y creará una nueva "
                                                "revisión."
                                            )
                                        ),
                                        size=11,
                                        color=Q_MUTED,
                                        expand=True,
                                    ),
                                ],
                                spacing=8,
                            ),
                        ),
                    ],
                    spacing=12,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                secondary_button(
                    "Cancelar",
                    _close_alert_dialog,
                ),
                primary_button(
                    "Guardar cambios",
                    _save_alert_edit,
                ),
            ],
        )

        page.show_dialog(
            alert_dialog
        )

        page.update()


    def _open_new_alert_dialog(e=None):
        nonlocal alert_dialog
        nonlocal editing_alert_id

        editing_alert_id = None
        _reset_alert_form()

        if (
            str(
                initial_action
                or ""
            ).upper()
            == "ALERT"
        ):
            _set_contextual_client_and_expedient(
                client_id=initial_client_id,
                expedient_id=initial_expedient_id,
                target="ALERT",
            )

        def label(
            text,
        ):
            return ft.Text(
                text,
                size=10,
                weight=ft.FontWeight.W_600,
                color=Q_PRIMARY_DARK,
            )

        # ==========================================================
        # COLUMNA IZQUIERDA
        # ==========================================================

        def small_label(
            text,
        ):
            return ft.Text(
                text,
                size=10,
                weight=ft.FontWeight.W_600,
                color=Q_PRIMARY_DARK,
            )

        main_column = ft.Column(
            controls=[
                # --------------------------------------------------
                # DATOS PRINCIPALES
                # --------------------------------------------------
                alert_title,

                alert_description,

                ft.Row(
                    controls=[
                        ft.Container(
                            expand=True,
                            content=ft.Row(
                                controls=[
                                    ft.Container(
                                        width=32,
                                        height=32,
                                        border_radius=8,
                                        bgcolor="#EEF4FF",
                                        alignment=(
                                            ft.Alignment.CENTER
                                        ),
                                        content=ft.Icon(
                                            ft.Icons
                                            .PERSON_OUTLINE_ROUNDED,
                                            size=16,
                                            color=Q_PRIMARY,
                                        ),
                                    ),
                                    ft.Container(
                                        content=(
                                            alert_client.control
                                        ),
                                        expand=True,
                                    ),
                                ],
                                spacing=7,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                        ),
                        ft.Container(
                            expand=True,
                            content=ft.Row(
                                controls=[
                                    ft.Container(
                                        width=32,
                                        height=32,
                                        border_radius=8,
                                        bgcolor="#EEF4FF",
                                        alignment=(
                                            ft.Alignment.CENTER
                                        ),
                                        content=ft.Icon(
                                            ft.Icons
                                            .FOLDER_OUTLINED,
                                            size=16,
                                            color=Q_PRIMARY,
                                        ),
                                    ),
                                    ft.Container(
                                        content=(
                                            alert_expedient.control
                                        ),
                                        expand=True,
                                    ),
                                ],
                                spacing=7,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                        ),
                    ],
                    spacing=12,
                ),

                ft.Row(
                    controls=[
                        ft.Container(
                            content=alert_priority,
                            expand=True,
                        ),
                        ft.Container(
                            expand=True,
                            height=48,
                            border=ft.border.all(
                                1,
                                Q_BORDER,
                            ),
                            border_radius=8,
                            padding=ft.padding.symmetric(
                                horizontal=12,
                            ),
                            alignment=(
                                ft.Alignment.CENTER_LEFT
                            ),
                            content=ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons
                                        .EVENT_NOTE_OUTLINED,
                                        size=16,
                                        color=Q_PRIMARY,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(
                                                "Tipo de aviso",
                                                size=9,
                                                color=Q_MUTED,
                                            ),
                                            ft.Text(
                                                "Aviso general",
                                                size=11,
                                                weight=(
                                                    ft.FontWeight.W_500
                                                ),
                                                color="#344054",
                                            ),
                                        ],
                                        spacing=0,
                                        tight=True,
                                    ),
                                ],
                                spacing=8,
                            ),
                        ),
                    ],
                    spacing=12,
                ),

                ft.Divider(
                    height=16,
                    color=Q_BORDER,
                ),

                # --------------------------------------------------
                # EVENTO
                # --------------------------------------------------
                small_label(
                    "Fecha y hora del evento"
                ),

                ft.Row(
                    controls=[
                        ft.Container(
                            content=alert_event_date,
                            expand=True,
                        ),
                        ft.Container(
                            content=alert_event_time,
                            width=180,
                        ),
                    ],
                    spacing=12,
                ),

                ft.Divider(
                    height=12,
                    color=Q_BORDER,
                ),

                # --------------------------------------------------
                # TELEGRAM
                # --------------------------------------------------
                small_label(
                    "Notificación"
                ),

                ft.Row(
                    controls=[
                        ft.Container(
                            content=alert_warning_date,
                            expand=True,
                        ),
                        ft.Container(
                            content=alert_warning_time,
                            width=180,
                        ),
                    ],
                    spacing=12,
                ),

                ft.Container(
                    bgcolor="#F8FAFC",
                    border_radius=8,
                    padding=ft.padding.symmetric(
                        horizontal=10,
                        vertical=8,
                    ),
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons
                                .NOTIFICATIONS_ACTIVE_OUTLINED,
                                size=15,
                                color=Q_PRIMARY,
                            ),
                            ft.Text(
                                (
                                    "Si no indicas fecha de aviso, "
                                    "Telegram utilizará la propia "
                                    "fecha del evento."
                                ),
                                size=9,
                                color=Q_MUTED,
                                expand=True,
                            ),
                        ],
                        spacing=7,
                    ),
                ),
            ],
            spacing=10,
            tight=True,
        )

        # ==========================================================
        # COLUMNA DERECHA — RECURRENCIA
        # ==========================================================

        recurrence_card = ft.Container(
            bgcolor="#FCFDFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                (
                                    "Repetición "
                                    "(aviso recurrente)"
                                ),
                                size=11,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            alert_recurrence_enabled,
                        ],
                        spacing=6,
                    ),

                    alert_recurrence_panel,
                ],
                spacing=10,
                tight=True,
            ),
        )

        recurrence_info_card = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=30,
                                height=30,
                                border_radius=8,
                                bgcolor="#EEF4FF",
                                alignment=(
                                    ft.Alignment.CENTER
                                ),
                                content=ft.Icon(
                                    ft.Icons
                                    .INFO_OUTLINE_ROUNDED,
                                    size=16,
                                    color=Q_PRIMARY,
                                ),
                            ),
                            ft.Text(
                                "Comportamiento",
                                size=11,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                        ],
                        spacing=8,
                    ),

                    ft.Text(
                        (
                            "Cada repetición se mostrará "
                            "como un aviso independiente "
                            "en Calendar y Agenda."
                        ),
                        size=10,
                        color="#475467",
                        height=32,
                    ),

                    ft.Divider(
                        height=4,
                        color=Q_BORDER,
                    ),

                    ft.Text(
                        (
                            "El recordatorio de Telegram "
                            "mantendrá la misma antelación "
                            "respecto de cada fecha."
                        ),
                        size=10,
                        color=Q_MUTED,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
        )

        side_column = ft.Column(
            controls=[
                recurrence_card,
                recurrence_info_card,
            ],
            spacing=10,
            tight=True,
        )

        # ==========================================================
        # CABECERA
        # ==========================================================

        header = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#EAECF0",
            ),
            border_radius=12,
            padding=ft.Padding.symmetric(
                horizontal=18,
                vertical=18,
            ),
            shadow=ft.BoxShadow(
                blur_radius=4,
                spread_radius=0,
                color="#12000000",
                offset=ft.Offset(
                    0,
                    1,
                ),
            ),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=44,
                        height=44,
                        bgcolor="#EEF4FF",
                        border_radius=12,
                        alignment=(
                            ft.Alignment.CENTER
                        ),
                        content=ft.Icon(
                            ft.Icons
                            .NOTIFICATIONS_NONE_ROUNDED,
                            size=23,
                            color=Q_PRIMARY,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                (
                                    "Crea un aviso para "
                                    "no olvidar lo importante"
                                ),
                                size=11,
                                color="#475467",
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                (
                                    "Planifica fecha, recordatorio "
                                    "y repetición."
                                ),
                                size=9,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=11,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        # ==========================================================
        # FOOTER INFORMATIVO
        # ==========================================================

        footer_info = ft.Container(
            bgcolor="#FFFAEB",
            border=ft.border.all(
                1,
                "#FDE68A",
            ),
            border_radius=9,
            padding=ft.padding.symmetric(
                horizontal=11,
                vertical=8,
            ),
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.LIGHTBULB_OUTLINE,
                        size=17,
                        color="#DC6803",
                    ),
                    ft.Text(
                        (
                            "El aviso se mostrará en Calendar "
                            "en la fecha del evento. Telegram "
                            "se enviará en la fecha de aviso."
                        ),
                        size=9,
                        weight=ft.FontWeight.W_500,
                        color="#7A2E0E",
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
        )

        alert_dialog = form_dialog(
            "Nuevo aviso",
            ft.Container(
                width=950,
                height=690,
                content=ft.Column(
                    controls=[
                        header,

                        ft.Divider(
                            height=7,
                            color=Q_BORDER,
                        ),

                        ft.Row(
                            controls=[
                                ft.Container(
                                    width=560,
                                    bgcolor="#FFFFFF",
                                    border=ft.border.all(
                                        1,
                                        "#EAECF0",
                                    ),
                                    border_radius=12,
                                    padding=14,
                                    shadow=ft.BoxShadow(
                                        blur_radius=4,
                                        spread_radius=0,
                                        color="#12000000",
                                        offset=ft.Offset(
                                            0,
                                            1,
                                        ),
                                    ),
                                    content=main_column,
                                ),

                                ft.VerticalDivider(
                                    width=1,
                                    color=Q_BORDER,
                                ),

                                ft.Container(
                                    width=300,
                                    content=side_column,
                                ),
                            ],
                            spacing=14,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.START
                            ),
                            expand=True,
                        ),

                        ft.Container(
                            padding=ft.padding.only(
                                top=12,
                            ),
                            content=ft.Row(
                                controls=[
                                    ft.Container(
                                        content=footer_info,
                                        expand=True,
                                    ),
                                    secondary_button(
                                        "Cancelar",
                                        _close_alert_dialog,
                                    ),
                                    primary_button(
                                        "Crear aviso",
                                        _save_alert,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                        ),
                    ],
                    spacing=9,
                    tight=True,
                ),
            ),
            actions=[],
        )

        page.show_dialog(
            alert_dialog
        )

        page.update()


    def _open_new_task_dialog(e=None):
        nonlocal task_dialog
        nonlocal editing_task_id

        editing_task_id = None
        _reset_task_form()

        if (
            str(
                initial_action
                or ""
            ).upper()
            == "TASK"
        ):
            _set_contextual_client_and_expedient(
                client_id=initial_client_id,
                expedient_id=initial_expedient_id,
                target="TASK",
            )

        # ==========================================================
        # COMPOSICIÓN VISUAL · NUEVA TAREA
        # ==========================================================

        task_header = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#EAECF0",
            ),
            border_radius=12,
            padding=ft.Padding.symmetric(
                horizontal=18,
                vertical=18,
            ),
            shadow=ft.BoxShadow(
                blur_radius=4,
                spread_radius=0,
                color="#12000000",
                offset=ft.Offset(
                    0,
                    1,
                ),
            ),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=44,
                        height=44,
                        bgcolor="#EEF4FF",
                        border_radius=12,
                        alignment=(
                            ft.Alignment.CENTER
                        ),
                        content=ft.Icon(
                            ft.Icons
                            .TASK_ALT_ROUNDED,
                            size=23,
                            color=Q_PRIMARY,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                (
                                    "Organiza una nueva "
                                    "tarea de trabajo"
                                ),
                                size=11,
                                color="#475467",
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                            ),
                            ft.Text(
                                (
                                    "Vincula cliente, expediente, "
                                    "prioridad y vencimiento."
                                ),
                                size=9,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=11,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        task_form_card = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#EAECF0",
            ),
            border_radius=12,
            padding=16,
            shadow=ft.BoxShadow(
                blur_radius=4,
                spread_radius=0,
                color="#12000000",
                offset=ft.Offset(
                    0,
                    1,
                ),
            ),
            content=ft.Column(
                controls=[
                    task_title,
                    task_description,

                    ft.Divider(
                        height=6,
                        color=Q_BORDER,
                    ),

                    task_client.control,
                    task_expedient.control,

                    ft.Row(
                        controls=[
                            task_priority,
                            task_responsible,
                        ],
                        spacing=12,
                        wrap=True,
                    ),

                    ft.Row(
                        controls=[
                            task_due_date,
                            task_due_time,
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                ],
                spacing=12,
                tight=True,
            ),
        )

        task_telegram_info = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=10,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=32,
                        height=32,
                        bgcolor="#EEF4FF",
                        border_radius=8,
                        alignment=(
                            ft.Alignment.CENTER
                        ),
                        content=ft.Icon(
                            ft.Icons
                            .SEND_ROUNDED,
                            size=17,
                            color=Q_PRIMARY,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                "Recordatorio automático",
                                size=10,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Al guardar, Telegram "
                                    "se programa automáticamente "
                                    "según la prioridad."
                                ),
                                size=9,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=9,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        task_footer = ft.Container(
            padding=ft.Padding.only(
                top=8,
            ),
            content=ft.Row(
                controls=[
                    ft.Container(
                        expand=True,
                    ),
                    secondary_button(
                        "Cancelar",
                        _close_task_dialog,
                    ),
                    primary_button(
                        "Guardar tarea",
                        _save_task,
                    ),
                ],
                spacing=8,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        task_dialog = form_dialog(
            "Nueva tarea",
            ft.Container(
                width=820,
                content=ft.Column(
                    controls=[
                        task_header,
                        task_form_card,
                        task_telegram_info,
                        task_footer,
                    ],
                    spacing=12,
                    tight=True,
                ),
            ),
            actions=[],
        )

        page.show_dialog(
            task_dialog
        )
        page.update()


    def _reload_selected_task(task_id):
        task = task_service.get_task(
            task_id
        )

        if task:
            state[
                "selected_item"
            ] = _task_projection(
                task
            )


    def _reload_selected_alert(
        alert_id,
    ):
        previous = (
            state.get(
                "selected_item"
            )
            or {}
        )

        alert = (
            calendar_alert_service
            .get_alert(
                alert_id
            )
        )

        if alert:
            state[
                "selected_item"
            ] = _alert_projection(
                alert,
                previous=previous,
            )


    def _run_alert_action(
        action,
        success_message,
    ):
        item = state.get(
            "selected_item"
        ) or {}

        if (
            item.get("item_type")
            != "ALERT"
        ):
            return

        alert_id = int(
            item.get("source_id")
            or 0
        )

        if not alert_id:
            return

        try:
            action(
                alert_id
            )

            refresh()

            _reload_selected_alert(
                alert_id
            )

            render()
            safe_update()
            _refresh_detail_dialog()

            _show_message(
                success_message
            )

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _refresh_detail_dialog():
        nonlocal detail_dialog

        if detail_dialog is None:
            return

        detail_dialog.content = ft.Container(
            width=820,
            content=detail_panel(),
        )

        page.update()


    def _run_task_action(
        action,
        success_message,
    ):
        item = state.get(
            "selected_item"
        ) or {}

        if (
            item.get("item_type")
            != "TASK"
        ):
            return

        task_id = int(
            item["source_id"]
        )

        try:
            action(task_id)

            refresh()

            _reload_selected_task(
                task_id
            )

            render()
            safe_update()

            # Si la acción procede del modal,
            # reconstruimos el detalle con el estado
            # recién persistido.
            _refresh_detail_dialog()

            _show_message(
                success_message
            )

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _agenda_status_chip(
        item,
    ):
        status = str(
            item.get("status")
            or ""
        ).upper()

        if status in {
            "COMPLETADA",
            "RESUELTO",
        }:
            label = (
                "Completada"
                if item.get("item_type") == "TASK"
                else "Resuelto"
            )
            bg = "#ECFDF3"
            fg = "#027A48"

        elif status in {
            "CANCELADA",
            "CANCELADO",
        }:
            label = "Cancelada"
            bg = "#F2F4F7"
            fg = "#475467"

        elif status in {
            "PENDIENTE",
            "EN_CURSO",
        }:
            label = status.replace(
                "_",
                " ",
            ).title()
            bg = "#EEF4FF"
            fg = Q_PRIMARY

        elif status == "ACTIVO":
            label = "Activo"
            bg = "#ECFDF3"
            fg = "#027A48"

        else:
            label = (
                status.replace(
                    "_",
                    " ",
                ).title()
                or "-"
            )
            bg = "#F8FAFC"
            fg = "#475569"

        return ft.Container(
            bgcolor=bg,
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=4,
            ),
            content=ft.Text(
                label,
                size=10,
                weight=ft.FontWeight.W_600,
                color=fg,
            ),
        )


    def _agenda_type_cell(
        item,
    ):
        is_alert = (
            item.get("item_type")
            == "ALERT"
        )

        return ft.Row(
            controls=[
                ft.Icon(
                    (
                        ft.Icons.NOTIFICATIONS_OUTLINED
                        if is_alert
                        else ft.Icons.CHECKLIST_RTL_OUTLINED
                    ),
                    size=15,
                    color=(
                        "#F79009"
                        if is_alert
                        else Q_PRIMARY
                    ),
                ),
                ft.Text(
                    (
                        "Aviso"
                        if is_alert
                        else "Tarea"
                    ),
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=(
                        "#B54708"
                        if is_alert
                        else Q_PRIMARY
                    ),
                ),
            ],
            spacing=5,
        )


    def _agenda_responsible_cell(
        item,
    ):
        responsible = str(
            item.get("responsible")
            or "Ignacio Alvarez"
        ).strip()

        if not responsible:
            responsible = "Ignacio Alvarez"

        words = [
            word
            for word in responsible.split()
            if word
        ]

        initials = "".join(
            word[0].upper()
            for word in words[:2]
        ) or "IA"

        return ft.Row(
            controls=[
                ft.Container(
                    width=30,
                    height=30,
                    border_radius=999,
                    bgcolor="#EEF4FF",
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(
                        initials,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY,
                    ),
                ),
                ft.Text(
                    responsible,
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color="#344054",
                    width=115,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=7,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        )


    def _agenda_row_style(
        item,
    ):
        status = str(
            item.get("status")
            or ""
        ).strip().upper()

        styles = {
            "PENDIENTE": {
                "bg": "#F5F9FF",
                "accent": "#1570EF",
                "border": "#D6E4FF",
            },
            "EN_CURSO": {
                "bg": "#FFFAEB",
                "accent": "#DC6803",
                "border": "#FEDF89",
            },
            "COMPLETADA": {
                "bg": "#F6FEF9",
                "accent": "#039855",
                "border": "#ABEFC6",
            },
            "RESUELTO": {
                "bg": "#F6FEF9",
                "accent": "#039855",
                "border": "#ABEFC6",
            },
            "ACTIVO": {
                "bg": "#FFF8F0",
                "accent": "#F79009",
                "border": "#FED7AA",
            },
            "CANCELADA": {
                "bg": "#F8FAFC",
                "accent": "#667085",
                "border": "#E2E8F0",
            },
            "CANCELADO": {
                "bg": "#F8FAFC",
                "accent": "#667085",
                "border": "#E2E8F0",
            },
        }

        return styles.get(
            status,
            {
                "bg": "#FFFFFF",
                "accent": "#98A2B3",
                "border": "#E2E8F0",
            },
        )


    def _agenda_table(
        items,
    ):
        header = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=10,
            padding=ft.padding.symmetric(
                horizontal=14,
                vertical=11,
            ),
            content=ft.Row(
                controls=[
                    ft.Text(
                        "FECHA",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=120,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "TIPO",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=85,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "TÍTULO",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=180,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "CLIENTE / EXPEDIENTE",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=255,
                        color=Q_PRIMARY_DARK,
                    ),

                    # Separación específica entre
                    # cliente y prioridad.
                    ft.Container(
                        width=24,
                    ),

                    ft.Text(
                        "PRIORIDAD",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=100,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "ESTADO",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=110,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "RESPONSABLE",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        width=175,
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        rows = []

        for index, item in enumerate(
            items
        ):
            client_name = str(
                item.get("client_name")
                or ""
            ).strip()

            expedient_number = str(
                item.get("expedient_number")
                or ""
            ).strip()

            client_controls = [
                ft.Text(
                    client_name or "-",
                    size=12,
                    weight=(
                        ft.FontWeight.BOLD
                        if client_name
                        else ft.FontWeight.NORMAL
                    ),
                    color=(
                        Q_PRIMARY_DARK
                        if client_name
                        else Q_MUTED
                    ),
                    width=255,
                    max_lines=1,
                    overflow=(
                        ft.TextOverflow.ELLIPSIS
                    ),
                )
            ]

            if expedient_number:
                client_controls.append(
                    ft.Text(
                        expedient_number,
                        size=10,
                        weight=ft.FontWeight.W_500,
                        color=Q_MUTED,
                        width=255,
                        max_lines=1,
                        overflow=(
                            ft.TextOverflow.ELLIPSIS
                        ),
                    )
                )

            row_style = (
                _agenda_row_style(
                    item
                )
            )

            row = ft.Container(
                ink=True,
                on_click=(
                    lambda e,
                    current=item:
                        _open_agenda_item(
                            current
                        )
                ),
                bgcolor=row_style["bg"],
                border=ft.border.all(
                    1,
                    row_style["border"],
                ),
                border_radius=9,
                margin=ft.margin.only(
                    top=3,
                    bottom=3,
                ),
                padding=ft.padding.symmetric(
                    horizontal=14,
                    vertical=13,
                ),
                content=ft.Row(
                    controls=[
                        ft.Container(
                            width=4,
                            height=42,
                            border_radius=999,
                            bgcolor=(
                                row_style[
                                    "accent"
                                ]
                            ),
                        ),

                        ft.Text(
                            _date_display(
                                item.get(
                                    "date"
                                )
                            ),
                            size=12,
                            width=120,
                            color="#334155",
                            weight=ft.FontWeight.W_500,
                        ),

                        ft.Container(
                            width=85,
                            content=_agenda_type_cell(
                                item
                            ),
                        ),

                        ft.Text(
                            item.get(
                                "title"
                            )
                            or "-",
                            size=12,
                            width=180,
                            color=Q_PRIMARY,
                            weight=ft.FontWeight.BOLD,
                            max_lines=2,
                            overflow=(
                                ft.TextOverflow.ELLIPSIS
                            ),
                        ),

                        ft.Container(
                            width=255,
                            content=ft.Column(
                                controls=client_controls,
                                spacing=3,
                            ),
                        ),

                        # Separación visual explícita.
                        ft.Container(
                            width=24,
                        ),

                        ft.Container(
                            width=100,
                            content=status_chip(
                                item.get(
                                    "priority"
                                ),
                                status_map=(
                                    PRIORITY_STATUS_MAP
                                ),
                            ),
                        ),

                        ft.Container(
                            width=110,
                            content=_agenda_status_chip(
                                item
                            ),
                        ),

                        ft.Container(
                            width=175,
                            content=_agenda_responsible_cell(
                                item
                            ),
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
            )

            rows.append(
                row
            )

        if not rows:
            rows = [
                ft.Container(
                    padding=32,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        controls=[
                            ft.Icon(
                                ft.Icons.EVENT_BUSY_OUTLINED,
                                size=30,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                (
                                    "No hay elementos que "
                                    "coincidan con los filtros."
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=8,
                        horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                )
            ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    header,
                    ft.Column(
                        controls=rows,
                        spacing=0,
                        scroll=ft.ScrollMode.AUTO,
                        height=285,
                    ),
                ],
                spacing=5,
            ),
        )


    def _load_agenda_items():
        include_archived = bool(
            agenda_include_archived.value
        )

        tasks = (
            task_service
            .list_tasks(
                include_archived=(
                    include_archived
                )
            )
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=(
                    include_archived
                )
            )
        )

        items = [
            _agenda_task_item(task)
            for task in tasks
        ]

        items.extend(
            _agenda_alert_item(alert)
            for alert in alerts
        )

        search = str(
            agenda_search.value
            or ""
        ).strip().upper()

        item_type = str(
            agenda_type_filter.value
            or "Todos"
        )

        status = str(
            agenda_status_filter.value
            or "Todos"
        )

        priority = str(
            agenda_priority_filter.value
            or "Todos"
        )

        date_from = _agenda_parse_date(
            agenda_date_from.value,
        )

        date_to = _agenda_parse_date(
            agenda_date_to.value,
            end_of_day=True,
        )

        filtered = []

        for item in items:
            if (
                item_type != "Todos"
                and item.get(
                    "item_type"
                )
                != item_type
            ):
                continue

            if (
                status != "Todos"
                and item.get(
                    "status"
                )
                != status
            ):
                continue

            if (
                priority != "Todos"
                and item.get(
                    "priority"
                )
                != priority
            ):
                continue

            item_date = None

            raw_date = str(
                item.get("date")
                or ""
            ).strip()

            if raw_date:
                try:
                    item_date = (
                        datetime.fromisoformat(
                            raw_date.replace(
                                "T",
                                " ",
                            )
                        )
                    )
                except ValueError:
                    item_date = None

            if (
                date_from
                and (
                    not item_date
                    or item_date < date_from
                )
            ):
                continue

            if (
                date_to
                and (
                    not item_date
                    or item_date > date_to
                )
            ):
                continue

            if search:
                haystack = " ".join(
                    (
                        str(
                            item.get("title")
                            or ""
                        ),
                        str(
                            item.get(
                                "description"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "client_name"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "expedient_number"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "status"
                            )
                            or ""
                        ),
                    )
                ).upper()

                if search not in haystack:
                    continue

            filtered.append(
                item
            )

        filtered.sort(
            key=lambda item: (
                str(
                    item.get("date")
                    or ""
                ),
                str(
                    item.get(
                        "item_type"
                    )
                    or ""
                ),
                int(
                    item.get(
                        "source_id"
                    )
                    or 0
                ),
            )
        )

        return filtered


    def _close_agenda_dialog(
        e=None,
    ):
        nonlocal agenda_dialog

        if agenda_dialog is None:
            return

        page.pop_dialog()
        page.update()

        agenda_dialog = None


    def _open_agenda_item(
        item,
    ):
        nonlocal agenda_dialog

        if not item:
            return

        # Cerramos Agenda para evitar diálogos
        # superpuestos y reutilizamos el detalle
        # operativo ya existente.
        if agenda_dialog is not None:
            page.pop_dialog()
            agenda_dialog = None

        state[
            "selected_item"
        ] = item

        _open_detail_dialog(
            item
        )


    def _refresh_agenda_results(
        e=None,
    ):
        """
        Reconstruye únicamente la tabla de Agenda.

        Replica el patrón de Clients:
        table_container.content = build_table()

        Los controles de filtros permanecen montados,
        por lo que el buscador conserva foco y cursor.
        """
        if agenda_dialog is None:
            return

        try:
            items = _load_agenda_items()

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )
            return

        agenda_table_container.content = (
            _agenda_table(
                items
            )
        )

        agenda_count_text.value = (
            f"Mostrando {len(items)} elementos"
        )

        page.update()


    def _refresh_agenda_dialog(
        e=None,
    ):
        nonlocal agenda_dialog

        if agenda_dialog is None:
            return

        try:
            items = _load_agenda_items()
        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )
            return

        agenda_dialog.content = (
            _agenda_dialog_content(
                items
            )
        )

        page.update()


    # El buscador de Agenda es reactivo:
    # cada cambio reconstruye inmediatamente
    # la tabla aplicando el texto introducido.
    # Mismo patrón que Clients:
    # al escribir solo se reconstruye la tabla.
    agenda_search.on_change = (
        _refresh_agenda_results
    )


    def _clear_agenda_filters(
        e=None,
    ):
        agenda_search.value = ""
        agenda_type_filter.value = (
            "Todos"
        )
        agenda_status_filter.value = (
            "Todos"
        )
        agenda_priority_filter.value = (
            "Todos"
        )
        agenda_date_from.value = ""
        agenda_date_to.value = ""
        agenda_include_archived.value = (
            False
        )

        _refresh_agenda_results()


    def _agenda_metric_card(
        title,
        value,
        subtitle,
        icon,
        *,
        accent=Q_PRIMARY,
        background="#F8FAFC",
    ):
        return ft.Container(
            expand=True,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=38,
                        height=38,
                        border_radius=10,
                        bgcolor=background,
                        alignment=(
                            ft.Alignment.CENTER
                        ),
                        content=ft.Icon(
                            icon,
                            color=accent,
                            size=20,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                title,
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                str(value),
                                size=23,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                subtitle,
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )


    def _agenda_metrics(
        items,
    ):
        now = datetime.now()

        pending = 0
        today = 0
        completed = 0
        cancelled = 0

        for item in items:
            status = str(
                item.get("status")
                or ""
            ).upper()

            if (
                item.get("item_type")
                == "TASK"
                and status in {
                    "PENDIENTE",
                    "EN_CURSO",
                }
            ):
                pending += 1

            if status in {
                "COMPLETADA",
                "RESUELTO",
            }:
                completed += 1

            if status in {
                "CANCELADA",
                "CANCELADO",
            }:
                cancelled += 1

            raw_date = str(
                item.get("date")
                or ""
            ).strip()

            if raw_date:
                try:
                    parsed = (
                        datetime.fromisoformat(
                            raw_date.replace(
                                "T",
                                " ",
                            )
                        )
                    )

                    if (
                        parsed.date()
                        == now.date()
                    ):
                        today += 1

                except ValueError:
                    pass

        return {
            "pending": pending,
            "today": today,
            "completed": completed,
            "cancelled": cancelled,
        }


    def _send_agenda_to_telegram(
        e=None,
    ):
        try:
            result = (
                calendar_agenda_summary_service
                .send_agenda_summary()
            )

        except Exception as exc:
            _show_message(
                (
                    "No se pudo enviar el resumen "
                    "a Telegram: "
                    f"{exc}"
                ),
                error=True,
            )
            return

        snapshot = (
            result.get("snapshot")
            or {}
        )

        counts = (
            snapshot.get("counts")
            or {}
        )

        open_tasks = int(
            counts.get("open_tasks")
            or 0
        )

        message_count = int(
            result.get("message_count")
            or 0
        )

        message_label = (
            "1 mensaje"
            if message_count == 1
            else f"{message_count} mensajes"
        )

        _show_message(
            (
                "Resumen enviado a Telegram. "
                f"{open_tasks} tareas abiertas · "
                f"{message_label}."
            )
        )


    def _agenda_dialog_content(
        items,
    ):
        metrics = _agenda_metrics(
            items
        )

        return ft.Container(
            width=1260,
            height=665,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=42,
                                height=42,
                                bgcolor="#EEF4FF",
                                border_radius=11,
                                alignment=(
                                    ft.Alignment.CENTER
                                ),
                                content=ft.Icon(
                                    ft.Icons.CALENDAR_MONTH_OUTLINED,
                                    color=Q_PRIMARY,
                                    size=22,
                                ),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Agenda completa",
                                        size=23,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=(
                                            Q_PRIMARY_DARK
                                        ),
                                    ),
                                    ft.Text(
                                        (
                                            "Tareas, avisos y "
                                            "seguimiento operativo "
                                            "del despacho"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            primary_button(
                                "✈ Enviar resumen a Telegram",
                                _send_agenda_to_telegram,
                            ),
                            ft.Container(
                                bgcolor="#EEF4FF",
                                border_radius=999,
                                padding=(
                                    ft.padding.symmetric(
                                        horizontal=12,
                                        vertical=5,
                                    )
                                ),
                                content=ft.Text(
                                    (
                                        f"{len(items)} "
                                        "elementos"
                                    ),
                                    size=11,
                                    weight=(
                                        ft.FontWeight.W_600
                                    ),
                                    color=Q_PRIMARY,
                                ),
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            _agenda_metric_card(
                                "Pendientes",
                                metrics[
                                    "pending"
                                ],
                                "Tareas por completar",
                                ft.Icons.PENDING_ACTIONS_OUTLINED,
                                accent=Q_PRIMARY,
                                background="#EEF4FF",
                            ),
                            _agenda_metric_card(
                                "Hoy",
                                metrics[
                                    "today"
                                ],
                                "Tareas y avisos hoy",
                                ft.Icons.TODAY_OUTLINED,
                                accent="#027A48",
                                background="#ECFDF3",
                            ),
                            _agenda_metric_card(
                                "Completadas",
                                metrics[
                                    "completed"
                                ],
                                "Actuaciones finalizadas",
                                ft.Icons.CHECK_CIRCLE_OUTLINE,
                                accent="#7F56D9",
                                background="#F4F3FF",
                            ),
                            _agenda_metric_card(
                                "Canceladas",
                                metrics[
                                    "cancelled"
                                ],
                                "Actuaciones canceladas",
                                ft.Icons.BLOCK_OUTLINED,
                                accent="#475467",
                                background="#F2F4F7",
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(
                            1,
                            Q_BORDER,
                        ),
                        border_radius=12,
                        padding=10,
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        agenda_search,
                                        agenda_type_filter,
                                        agenda_status_filter,
                                        agenda_priority_filter,
                                    ],
                                    spacing=8,
                                    wrap=False,
                                ),
                                ft.Row(
                                    controls=[
                                        agenda_date_from,
                                        agenda_date_to,
                                        agenda_include_archived,
                                        primary_button(
                                            "Aplicar filtros",
                                            _refresh_agenda_results,
                                        ),
                                        secondary_button(
                                            "Limpiar filtros",
                                            _clear_agenda_filters,
                                        ),
                                    ],
                                    spacing=8,
                                    wrap=False,
                                ),
                            ],
                            spacing=6,
                        ),
                    ),

                    agenda_table_container,

                    ft.Row(
                        controls=[
                            agenda_count_text,
                            ft.Text(
                                (
                                    "Haz clic en una fila "
                                    "para abrir su detalle."
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),
                            secondary_button(
                                "Cerrar",
                                _close_agenda_dialog,
                            ),
                        ],
                        spacing=14,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                ],
                spacing=12,
            ),
        )


    def _open_full_agenda(
        e=None,
    ):
        nonlocal agenda_dialog

        try:
            items = _load_agenda_items()
        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )
            return

        agenda_table_container.content = (
            _agenda_table(
                items
            )
        )

        agenda_count_text.value = (
            f"Mostrando {len(items)} elementos"
        )

        agenda_dialog = ft.AlertDialog(
            modal=True,
            inset_padding=ft.padding.symmetric(
                horizontal=18,
                vertical=14,
            ),
            content_padding=ft.padding.all(
                12
            ),
            content=_agenda_dialog_content(
                items
            ),
        )

        page.show_dialog(
            agenda_dialog
        )

        page.update()


    def show_placeholder(
        message,
    ):
        page.snack_bar = ft.SnackBar(
            ft.Text(message)
        )
        page.snack_bar.open = True
        page.update()

    def _shift_month(
        value,
        delta,
    ):
        month_index = (
            value.year * 12
            + value.month
            - 1
            + int(delta)
        )

        year = (
            month_index // 12
        )

        month = (
            month_index % 12
            + 1
        )

        return value.replace(
            year=year,
            month=month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )


    def _show_today(
        e=None,
    ):
        state[
            "view_mode"
        ] = "TODAY"

        now = datetime.now()

        state[
            "week_start"
        ] = _monday(
            now
        )

        state[
            "month_anchor"
        ] = now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        refresh()


    def _show_week(
        e=None,
    ):
        state[
            "view_mode"
        ] = "WEEK"

        refresh()


    def _show_month(
        e=None,
    ):
        state[
            "view_mode"
        ] = "MONTH"

        selected_week = state[
            "week_start"
        ]

        state[
            "month_anchor"
        ] = selected_week.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        refresh()


    def _open_day_as_week(
        day,
    ):
        state[
            "view_mode"
        ] = "WEEK"

        state[
            "week_start"
        ] = _monday(
            day
        )

        refresh()


    def previous_week(e=None):
        if (
            state.get(
                "view_mode"
            )
            == "MONTH"
        ):
            state[
                "month_anchor"
            ] = _shift_month(
                state[
                    "month_anchor"
                ],
                -1,
            )
        else:
            state["week_start"] -= (
                timedelta(days=7)
            )

        refresh()


    def next_week(e=None):
        if (
            state.get(
                "view_mode"
            )
            == "MONTH"
        ):
            state[
                "month_anchor"
            ] = _shift_month(
                state[
                    "month_anchor"
                ],
                1,
            )
        else:
            state["week_start"] += (
                timedelta(days=7)
            )

        refresh()


    def current_week(e=None):
        now = datetime.now()

        if (
            state.get(
                "view_mode"
            )
            == "MONTH"
        ):
            state[
                "month_anchor"
            ] = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            state[
                "week_start"
            ] = _monday(
                now
            )

        refresh()

    def select_item(item):
        if not item:
            return

        state["selected_item"] = item

        # detail_panel() se construye dentro de render().
        # Un simple update() no basta: hay que regenerar
        # el árbol visual para mostrar el nuevo elemento.
        render()
        safe_update()


    def open_selected_expedient(
        e=None,
    ):
        item = state.get(
            "selected_item"
        ) or {}

        expedient_id = item.get(
            "expediente_id"
        )

        if (
            expedient_id
            and on_open_expediente
        ):
            on_open_expediente(
                expedient_id
            )

    def _calendar_filters_active():
        search = (
            search_input.value
            or ""
        ).strip()

        return bool(
            search
            or (
                priority_filter.value
                or "Todos"
            )
            != "Todos"
            or (
                status_filter.value
                or "Todos"
            )
            != "Todos"
            or (
                type_filter.value
                or "Todos"
            )
            != "Todos"
            or (
                responsible_filter.value
                or "Todos"
            )
            != "Todos"
        )


    def filtered_items(
        source_items=None,
    ):
        search = (
            search_input.value
            or ""
        ).strip().upper()

        priority = (
            priority_filter.value
            or "Todos"
        )

        status = (
            status_filter.value
            or "Todos"
        )

        item_type = (
            type_filter.value
            or "Todos"
        )

        responsible = (
            responsible_filter.value
            or "Todos"
        )

        result = []

        source = (
            state["items"]
            if source_items is None
            else source_items
        )

        for item in source:
            if (
                priority != "Todos"
                and item.get("priority")
                != priority
            ):
                continue

            if (
                status != "Todos"
                and item.get("status")
                != status
            ):
                continue

            if (
                item_type != "Todos"
                and item.get(
                    "item_type"
                )
                != item_type
            ):
                continue

            if (
                responsible != "Todos"
                and item.get(
                    "responsible"
                )
                != responsible
            ):
                continue

            if search:
                haystack = " ".join(
                    [
                        str(
                            item.get("title")
                            or ""
                        ),
                        str(
                            item.get(
                                "description"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "client_name"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "expedient_number"
                            )
                            or ""
                        ),
                    ]
                ).upper()

                if search not in haystack:
                    continue

            result.append(item)

        return result

    detail_dialog = None


    def _close_detail_dialog(e=None):
        nonlocal detail_dialog

        if detail_dialog is None:
            return

        page.pop_dialog()
        page.update()

        detail_dialog = None


    def _open_detail_dialog(item):
        nonlocal detail_dialog

        if not item:
            return

        state["selected_item"] = item

        detail_dialog = ft.AlertDialog(
            modal=True,
            content=ft.Container(
                width=820,
                content=detail_panel(),
            ),
            actions=[
                secondary_button(
                    "Cerrar",
                    _close_detail_dialog,
                ),
            ],
            actions_alignment=(
                ft.MainAxisAlignment.END
            ),
        )

        page.show_dialog(
            detail_dialog
        )

        page.update()


    def _handle_upcoming_click(item):
        if not item:
            return

        item_key = (
            str(
                item.get("item_type")
                or ""
            ),
            int(
                item.get("source_id")
                or 0
            ),
        )

        now = time.monotonic()

        previous_key = state.get(
            "last_upcoming_click_key"
        )

        previous_at = float(
            state.get(
                "last_upcoming_click_at"
            )
            or 0.0
        )

        is_double_click = (
            previous_key == item_key
            and (
                now - previous_at
            ) <= 0.45
        )

        state[
            "last_upcoming_click_key"
        ] = item_key

        state[
            "last_upcoming_click_at"
        ] = now

        if is_double_click:
            state[
                "last_upcoming_click_key"
            ] = None

            state[
                "last_upcoming_click_at"
            ] = 0.0

            _open_detail_dialog(
                item
            )


    def _period_action_items(
        items,
        *,
        view_mode,
        week_start,
        month_anchor,
    ):
        result = []

        for item in items or []:
            raw_date = str(
                item.get("date")
                or ""
            ).strip()

            if not raw_date:
                continue

            try:
                item_date = (
                    datetime.fromisoformat(
                        raw_date.replace(
                            "T",
                            " ",
                        )
                    )
                )
            except ValueError:
                continue

            if view_mode == "MONTH":
                if (
                    item_date.year
                    != month_anchor.year
                    or item_date.month
                    != month_anchor.month
                ):
                    # El grid mensual carga también
                    # días adyacentes para completar
                    # las seis semanas visuales.
                    continue

            elif view_mode == "WEEK":
                week_end = (
                    week_start
                    + timedelta(
                        days=6,
                        hours=23,
                        minutes=59,
                        seconds=59,
                    )
                )

                if not (
                    week_start
                    <= item_date
                    <= week_end
                ):
                    continue

            result.append(
                item
            )

        result.sort(
            key=lambda item: str(
                item.get("date")
                or ""
            )
        )

        return result


    def upcoming_table(
        items,
        *,
        limit=8,
    ):
        rows = []

        visible_items = (
            list(items or [])
            if limit is None
            else list(items or [])[
                :int(limit)
            ]
        )

        for item in visible_items:
            item_type = item.get(
                "item_type"
            )

            rows.append(
                ft.Container(
                    padding=ft.padding.symmetric(
                        horizontal=10,
                        vertical=8,
                    ),
                    border=ft.border.only(
                        bottom=ft.BorderSide(
                            1,
                            Q_BORDER,
                        )
                    ),
                    ink=True,
                    on_click=(
                        lambda e,
                        current=item:
                            _handle_upcoming_click(
                                current
                            )
                    ),
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                "●",
                                size=10,
                                color=(
                                    "#B54708"
                                    if item_type
                                    == "ALERT"
                                    else Q_PRIMARY
                                ),
                            ),
                            ft.Container(
                                width=250,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            item.get(
                                                "title"
                                            )
                                            or "-",
                                            size=11,
                                            weight=(
                                                ft.FontWeight
                                                .W_600
                                            ),
                                            color=(
                                                Q_PRIMARY_DARK
                                            ),
                                        ),
                                        ft.Text(
                                            (
                                                "Aviso"
                                                if item_type
                                                == "ALERT"
                                                else "Tarea"
                                            ),
                                            size=9,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=1,
                                ),
                            ),
                            ft.Container(
                                width=260,
                                content=ft.Text(
                                    (
                                        item.get(
                                            "client_name"
                                        )
                                        or item.get(
                                            "expedient_number"
                                        )
                                        or "-"
                                    ),
                                    size=10,
                                    color="#334155",
                                    overflow=(
                                        ft.TextOverflow
                                        .ELLIPSIS
                                    ),
                                ),
                            ),
                            ft.Container(
                                width=150,
                                content=ft.Text(
                                    _date_display(
                                        item.get(
                                            "date"
                                        )
                                    ),
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                            ft.Container(
                                width=100,
                                content=status_chip(
                                    item.get(
                                        "priority"
                                    ),
                                    status_map=(
                                        PRIORITY_STATUS_MAP
                                    ),
                                ),
                            ),
                            ft.Container(
                                width=130,
                                content=ft.Text(
                                    item.get(
                                        "status"
                                    )
                                    or "-",
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                            ft.Container(
                                width=130,
                                content=ft.Text(
                                    item.get(
                                        "responsible"
                                    )
                                    or "-",
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=(
                            ft.CrossAxisAlignment
                            .CENTER
                        ),
                    ),
                )
            )

        if not rows:
            rows.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Column(
                        controls=[
                            ft.Icon(
                                ft.Icons
                                .EVENT_AVAILABLE,
                                size=34,
                                color="#94A3B8",
                            ),
                            ft.Text(
                                "Sin actuaciones programadas",
                                size=13,
                                weight=(
                                    ft.FontWeight
                                    .W_600
                                ),
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                (
                                    "Las nuevas tareas y avisos "
                                    "aparecerán aquí."
                                ),
                                size=11,
                                color="#94A3B8",
                            ),
                        ],
                        spacing=5,
                        horizontal_alignment=(
                            ft.CrossAxisAlignment
                            .CENTER
                        ),
                    ),
                )
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=ft.padding.only(
                left=14,
                right=14,
                top=12,
                bottom=10,
            ),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Próximas actuaciones",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            ft.Text(
                                "Doble clic para abrir detalle",
                                size=10,
                                color=Q_MUTED,
                                italic=True,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Tarea / Aviso",
                                size=10,
                                color=Q_MUTED,
                                width=270,
                            ),
                            ft.Text(
                                "Cliente / Expediente",
                                size=10,
                                color=Q_MUTED,
                                width=260,
                            ),
                            ft.Text(
                                "Vencimiento",
                                size=10,
                                color=Q_MUTED,
                                width=150,
                            ),
                            ft.Text(
                                "Prioridad",
                                size=10,
                                color=Q_MUTED,
                                width=100,
                            ),
                            ft.Text(
                                "Estado",
                                size=10,
                                color=Q_MUTED,
                                width=130,
                            ),
                            ft.Text(
                                "Responsable",
                                size=10,
                                color=Q_MUTED,
                                width=130,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        height=230,
                        content=ft.Column(
                            controls=rows,
                            spacing=0,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                    ),
                ],
                spacing=8,
            ),
        )

    def _notification_status_style(
        status,
    ):
        value = str(
            status or ""
        ).upper()

        styles = {
            "PENDIENTE": (
                "#FFF7E6",
                "#B54708",
            ),
            "PROCESANDO": (
                "#EEF4FF",
                "#0057B8",
            ),
            "ENVIADA": (
                "#ECFDF3",
                "#027A48",
            ),
            "CANCELADA": (
                "#F2F4F7",
                "#667085",
            ),
            "ERROR": (
                "#FEF3F2",
                "#B42318",
            ),
        }

        return styles.get(
            value,
            (
                "#F2F4F7",
                "#475467",
            ),
        )


    def _notification_badge(status):
        bg, fg = (
            _notification_status_style(
                status
            )
        )

        label = (
            str(status or "-")
            .replace("_", " ")
            .title()
        )

        return ft.Container(
            bgcolor=bg,
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=3,
            ),
            content=ft.Text(
                label,
                size=9,
                weight=ft.FontWeight.W_600,
                color=fg,
            ),
        )


    def _notification_row(
        notification,
        *,
        historical=False,
    ):
        notification_type = (
            str(
                notification.get(
                    "notification_type"
                )
                or "-"
            )
            .replace("_", " ")
            .title()
        )

        scheduled_at = _date_display(
            notification.get(
                "scheduled_at"
            )
        )

        status = notification.get(
            "estado"
        )

        attempt_count = int(
            notification.get(
                "attempt_count"
            )
            or 0
        )

        sent_at = notification.get(
            "sent_at"
        )

        last_error = str(
            notification.get(
                "last_error"
            )
            or ""
        ).strip()

        details = []

        if sent_at:
            details.append(
                "Enviada: "
                + _date_display(
                    sent_at
                )
            )

        if attempt_count:
            details.append(
                (
                    "Intentos: "
                    f"{attempt_count}"
                )
            )

        if last_error:
            details.append(
                (
                    "Último error: "
                    + last_error
                )
            )

        return ft.Container(
            bgcolor=(
                "#FAFAFA"
                if historical
                else "#FFFFFF"
            ),
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=10,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(
                                (
                                    ft.Icons
                                    .HISTORY_ROUNDED
                                    if historical
                                    else ft.Icons
                                    .SEND_ROUNDED
                                ),
                                size=16,
                                color=(
                                    Q_MUTED
                                    if historical
                                    else Q_PRIMARY
                                ),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        notification_type,
                                        size=11,
                                        weight=(
                                            ft.FontWeight
                                            .W_600
                                        ),
                                        color="#0F172A",
                                    ),
                                    ft.Text(
                                        scheduled_at
                                        or "-",
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            _notification_badge(
                                status
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=(
                            ft.CrossAxisAlignment
                            .CENTER
                        ),
                    ),
                    (
                        ft.Text(
                            " · ".join(
                                details
                            ),
                            size=9,
                            color=(
                                "#B42318"
                                if last_error
                                else Q_MUTED
                            ),
                        )
                        if details
                        else ft.Container()
                    ),
                ],
                spacing=5,
            ),
        )


    def _notification_section(
        source_type,
        source_id,
    ):
        try:
            notifications = (
                scheduled_notification_service
                .list_for_source(
                    str(source_type).upper(),
                    int(source_id),
                    include_inactive=True,
                )
            )
        except Exception as exc:
            return ft.Container(
                bgcolor="#FEF3F2",
                border=ft.border.all(
                    1,
                    "#FDA29B",
                ),
                border_radius=10,
                padding=10,
                content=ft.Text(
                    (
                        "No se pudieron cargar "
                        "las notificaciones Telegram: "
                        + str(exc)
                    ),
                    size=10,
                    color="#B42318",
                ),
            )

        notifications = list(
            notifications or []
        )

        notifications.sort(
            key=lambda item: int(
                item.get("id")
                or 0
            ),
            reverse=True,
        )

        active = [
            item
            for item in notifications
            if int(
                item.get("activo")
                or 0
            )
            == 1
        ]

        history = [
            item
            for item in notifications
            if int(
                item.get("activo")
                or 0
            )
            != 1
        ]

        controls = [
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons
                        .TELEGRAM,
                        size=18,
                        color=Q_PRIMARY,
                    ),
                    ft.Text(
                        "Notificaciones Telegram",
                        size=12,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=7,
            ),
        ]

        controls.append(
            ft.Text(
                (
                    "Planificación vigente"
                    f" ({len(active)})"
                ),
                size=10,
                weight=ft.FontWeight.W_600,
                color="#475467",
            )
        )

        if active:
            controls.extend(
                [
                    _notification_row(
                        item
                    )
                    for item in active
                ]
            )
        else:
            controls.append(
                ft.Text(
                    (
                        "No hay notificaciones "
                        "activas programadas."
                    ),
                    size=10,
                    color=Q_MUTED,
                    italic=True,
                )
            )

        if history:
            controls.extend(
                [
                    ft.Container(
                        height=4,
                    ),
                    ft.Text(
                        (
                            "Histórico"
                            f" ({len(history)})"
                        ),
                        size=10,
                        weight=(
                            ft.FontWeight.W_600
                        ),
                        color="#475467",
                    ),
                ]
            )

            controls.extend(
                [
                    _notification_row(
                        item,
                        historical=True,
                    )
                    for item in history
                ]
            )

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=controls,
                spacing=8,
            ),
        )


    def _task_notification_section(
        task_id,
    ):
        return _notification_section(
            "TASK",
            task_id,
        )


    def _alert_notification_section(
        alert_id,
    ):
        return _notification_section(
            "ALERT",
            alert_id,
        )


    def _run_recurrence_action(
        action,
        success_message,
    ):
        item = state.get(
            "selected_item"
        ) or {}

        if (
            item.get("item_type")
            != "ALERT"
        ):
            return

        alert_id = int(
            item.get("source_id")
            or 0
        )

        if not alert_id:
            return

        try:
            recurrence = (
                calendar_alert_recurrence
                .get_recurrence_for_alert(
                    alert_id
                )
            )

            if not recurrence:
                raise ValueError(
                    "Este aviso no tiene "
                    "una serie recurrente."
                )

            action(
                recurrence["id"]
            )

            refresh()

            _reload_selected_alert(
                alert_id
            )

            render()
            safe_update()
            _refresh_detail_dialog()

            _show_message(
                success_message
            )

        except Exception as exc:
            _show_message(
                str(exc),
                error=True,
            )


    def _recurrence_frequency_label(
        recurrence,
    ):
        unit = str(
            recurrence.get(
                "frequency_unit"
            )
            or ""
        ).upper()

        interval = int(
            recurrence.get(
                "interval_value"
            )
            or 1
        )

        labels = {
            "DAY": (
                "día"
                if interval == 1
                else "días"
            ),
            "WEEK": (
                "semana"
                if interval == 1
                else "semanas"
            ),
            "MONTH": (
                "mes"
                if interval == 1
                else "meses"
            ),
            "YEAR": (
                "año"
                if interval == 1
                else "años"
            ),
        }

        label = labels.get(
            unit,
            unit.lower() or "-"
        )

        return (
            f"Cada {interval} {label}"
        )


    def _alert_recurrence_section(
        alert_id,
    ):
        recurrence = (
            calendar_alert_recurrence
            .get_recurrence_for_alert(
                alert_id
            )
        )

        if not recurrence:
            return ft.Container()

        state_value = str(
            recurrence.get("estado")
            or ""
        ).upper()

        mappings = (
            calendar_alert_recurrence
            .list_notification_occurrences(
                recurrence["id"]
            )
        )

        controls = [
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons
                        .AUTORENEW_ROUNDED,
                        size=18,
                        color=Q_PRIMARY,
                    ),
                    ft.Text(
                        "Recordatorios periódicos",
                        size=11,
                        weight=(
                            ft.FontWeight.W_600
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=7,
            ),
            ft.Text(
                (
                    "Estado: "
                    + (
                        state_value.title()
                        if state_value
                        else "-"
                    )
                ),
                size=10,
                color="#334155",
            ),
            ft.Text(
                (
                    "Frecuencia: "
                    + _recurrence_frequency_label(
                        recurrence
                    )
                ),
                size=10,
                color=Q_MUTED,
            ),
            ft.Text(
                (
                    "Recordatorios programados: "
                    + str(
                        len(mappings)
                    )
                ),
                size=10,
                color=Q_MUTED,
            ),
        ]

        if state_value == "ACTIVA":
            controls.append(
                ft.Row(
                    controls=[
                        secondary_button(
                            "Pausar serie",
                            lambda e:
                                _run_recurrence_action(
                                    calendar_alert_recurrence_app
                                    .pause_recurring_alert,
                                    (
                                        "Serie pausada. "
                                        "Los recordatorios "
                                        "quedan suspendidos."
                                    ),
                                ),
                        ),
                        danger_button(
                            "Cancelar serie",
                            lambda e:
                                _run_recurrence_action(
                                    calendar_alert_recurrence_app
                                    .cancel_recurring_alert,
                                    (
                                        "Serie cancelada. "
                                        "El aviso principal "
                                        "permanece activo."
                                    ),
                                ),
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                )
            )

        elif state_value == "PAUSADA":
            controls.append(
                ft.Row(
                    controls=[
                        primary_button(
                            "Reanudar serie",
                            lambda e:
                                _run_recurrence_action(
                                    calendar_alert_recurrence_app
                                    .resume_recurring_alert,
                                    (
                                        "Serie reanudada. "
                                        "Los recordatorios "
                                        "vencidos no se enviarán."
                                    ),
                                ),
                        ),
                        danger_button(
                            "Cancelar serie",
                            lambda e:
                                _run_recurrence_action(
                                    calendar_alert_recurrence_app
                                    .cancel_recurring_alert,
                                    (
                                        "Serie cancelada. "
                                        "El aviso principal "
                                        "permanece activo."
                                    ),
                                ),
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                )
            )

        elif state_value == "CANCELADA":
            controls.append(
                ft.Text(
                    (
                        "Los recordatorios periódicos "
                        "de esta serie han sido "
                        "cancelados."
                    ),
                    size=10,
                    color=Q_MUTED,
                )
            )

        elif state_value == "FINALIZADA":
            controls.append(
                ft.Text(
                    (
                        "La serie de recordatorios "
                        "ha finalizado."
                    ),
                    size=10,
                    color=Q_MUTED,
                )
            )

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=controls,
                spacing=7,
            ),
        )


    def detail_panel():
        item = state.get(
            "selected_item"
        )

        if not item:
            return ft.Container(
                height=400,
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=18,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Detalle del elemento",
                            size=14,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "Selecciona una tarea o "
                                "aviso para ver su detalle."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=8,
                ),
            )

        return ft.Container(
            height=400,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=18,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Detalle del elemento",
                        size=14,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        item.get("title")
                        or "-",
                        size=13,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            status_chip(
                                item.get(
                                    "priority"
                                ),
                                status_map=(
                                    PRIORITY_STATUS_MAP
                                ),
                            ),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(
                                    1,
                                    Q_BORDER,
                                ),
                                border_radius=999,
                                padding=ft.padding.symmetric(
                                    horizontal=10,
                                    vertical=4,
                                ),
                                content=ft.Text(
                                    (
                                        item.get("status")
                                        or "-"
                                    ).replace(
                                        "_",
                                        " ",
                                    ).title(),
                                    size=10,
                                    weight=ft.FontWeight.W_600,
                                    color=Q_PRIMARY_DARK,
                                ),
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Divider(
                        color=Q_BORDER,
                    ),
                    ft.Text(
                        (
                            "Cliente: "
                            + (
                                item.get(
                                    "client_name"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Expediente: "
                            + (
                                item.get(
                                    "expedient_number"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Fecha: "
                            + _date_display(
                                item.get("date")
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Estado: "
                            + (
                                item.get(
                                    "status"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    (
                        ft.Container(
                            bgcolor="#F8FAFC",
                            border=ft.border.all(
                                1,
                                Q_BORDER,
                            ),
                            border_radius=10,
                            padding=10,
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        "Aviso",
                                        size=10,
                                        weight=(
                                            ft.FontWeight.W_600
                                        ),
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            "Fecha del evento: "
                                            + _date_display(
                                                item.get(
                                                    "date"
                                                )
                                            )
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        (
                                            "Avisar desde: "
                                            + (
                                                _date_display(
                                                    item.get(
                                                        "warning_date"
                                                    )
                                                )
                                                if item.get(
                                                    "warning_date"
                                                )
                                                else (
                                                    "misma fecha "
                                                    "del evento"
                                                )
                                            )
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        (
                                            "Origen: "
                                            + str(
                                                item.get(
                                                    "origin_type"
                                                )
                                                or "MANUAL"
                                            ).replace(
                                                "_",
                                                " ",
                                            ).title()
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=4,
                            ),
                        )
                        if item.get(
                            "item_type"
                        )
                        == "ALERT"
                        else ft.Container()
                    ),
                    (
                        _alert_recurrence_section(
                            item.get(
                                "source_id"
                            )
                        )
                        if (
                            item.get(
                                "item_type"
                            )
                            == "ALERT"
                            and item.get(
                                "source_id"
                            )
                        )
                        else ft.Container()
                    ),
                    (
                        _alert_notification_section(
                            item.get(
                                "source_id"
                            )
                        )
                        if (
                            item.get(
                                "item_type"
                            )
                            == "ALERT"
                            and item.get(
                                "source_id"
                            )
                        )
                        else ft.Container()
                    ),
                    (
                        _task_notification_section(
                            item.get(
                                "source_id"
                            )
                        )
                        if (
                            item.get(
                                "item_type"
                            )
                            == "TASK"
                            and item.get(
                                "source_id"
                            )
                        )
                        else ft.Container()
                    ),
                    (
                        ft.Row(
                            controls=[
                                (
                                    secondary_button(
                                        "Editar",
                                        _open_edit_task_dialog,
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    in {
                                        "PENDIENTE",
                                        "EN_CURSO",
                                    }
                                    else ft.Container()
                                ),
                                (
                                    primary_button(
                                        "Iniciar",
                                        lambda e:
                                            _run_task_action(
                                                calendar_task_app
                                                .start_calendar_task,
                                                "Tarea iniciada.",
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    == "PENDIENTE"
                                    else ft.Container()
                                ),
                                (
                                    primary_button(
                                        "Completar",
                                        lambda e:
                                            _run_task_action(
                                                calendar_task_app
                                                .complete_calendar_task,
                                                (
                                                    "Tarea completada. "
                                                    "Avisos pendientes cancelados."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    in {
                                        "PENDIENTE",
                                        "EN_CURSO",
                                    }
                                    else ft.Container()
                                ),
                                (
                                    secondary_button(
                                        "Reabrir",
                                        lambda e:
                                            _run_task_action(
                                                calendar_task_app
                                                .reopen_calendar_task,
                                                (
                                                    "Tarea reabierta y "
                                                    "Telegram reprogramado."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    in {
                                        "COMPLETADA",
                                        "CANCELADA",
                                    }
                                    else ft.Container()
                                ),
                                (
                                    danger_button(
                                        "Cancelar tarea",
                                        lambda e:
                                            _run_task_action(
                                                calendar_task_app
                                                .cancel_calendar_task,
                                                (
                                                    "Tarea cancelada. "
                                                    "Avisos pendientes cancelados."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    in {
                                        "PENDIENTE",
                                        "EN_CURSO",
                                    }
                                    else ft.Container()
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        )
                        if item.get(
                            "item_type"
                        )
                        == "TASK"
                        else ft.Container()
                    ),
                    (
                        ft.Row(
                            controls=[
                                (
                                    secondary_button(
                                        "Editar",
                                        _open_edit_alert_dialog,
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    == "ACTIVO"
                                    else ft.Container()
                                ),
                                (
                                    primary_button(
                                        "Resolver",
                                        lambda e:
                                            _run_alert_action(
                                                calendar_alert_app
                                                .resolve_calendar_alert,
                                                (
                                                    "Aviso resuelto. "
                                                    "Telegram pendiente "
                                                    "cancelado."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    == "ACTIVO"
                                    else ft.Container()
                                ),
                                (
                                    secondary_button(
                                        "Reabrir",
                                        lambda e:
                                            _run_alert_action(
                                                calendar_alert_app
                                                .reopen_calendar_alert,
                                                (
                                                    "Aviso reabierto y "
                                                    "Telegram reprogramado."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    in {
                                        "RESUELTO",
                                        "CANCELADO",
                                    }
                                    else ft.Container()
                                ),
                                (
                                    danger_button(
                                        "Cancelar aviso",
                                        lambda e:
                                            _run_alert_action(
                                                calendar_alert_app
                                                .cancel_calendar_alert,
                                                (
                                                    "Aviso cancelado. "
                                                    "Telegram pendiente "
                                                    "cancelado."
                                                ),
                                            ),
                                    )
                                    if item.get(
                                        "status"
                                    )
                                    == "ACTIVO"
                                    else ft.Container()
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        )
                        if item.get(
                            "item_type"
                        )
                        == "ALERT"
                        else ft.Container()
                    ),
                    (
                        secondary_button(
                            "Abrir expediente",
                            open_selected_expedient,
                        )
                        if item.get(
                            "expediente_id"
                        )
                        else ft.Container()
                    ),
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

    # Contenedores persistentes.
    #
    # Igual que Clientes conserva su barra de filtros
    # y reconstruye únicamente la tabla de resultados,
    # Calendar mantiene montado el buscador y actualiza
    # solamente estas dos zonas.
    calendar_workspace_slot = ft.Container()
    period_actions_slot = ft.Container()


    def render():
        week_start = state[
            "week_start"
        ]

        week_end = (
            week_start
            + timedelta(days=6)
        )

        calendar_items = list(
            state["items"]
        )

        filtered_period_items = (
            filtered_items(
                calendar_items
            )
        )

        highlighted_keys = set()

        if _calendar_filters_active():
            highlighted_keys = {
                (
                    str(
                        item.get(
                            "item_type"
                        )
                        or ""
                    ).upper(),
                    item.get(
                        "source_id"
                    ),
                )
                for item
                in filtered_period_items
            }

        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "Calendario",
                            size=28,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "Gestión operativa de tareas, "
                                "avisos y vencimientos del despacho"
                            ),
                            size=13,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
                secondary_button(
                    "Ver agenda completa",
                    _open_full_agenda,
                ),
                secondary_button(
                    "Nuevo aviso",
                    _open_new_alert_dialog,
                ),
                primary_button(
                    "Nueva tarea",
                    _open_new_task_dialog,
                ),
            ],
            vertical_alignment=(
                ft.CrossAxisAlignment.START
            ),
        )

        controls_bar = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=10,
            content=ft.Row(
                controls=[
                    (
                        primary_button(
                            "Hoy",
                            _show_today,
                        )
                        if state.get(
                            "view_mode"
                        )
                        == "TODAY"
                        else secondary_button(
                            "Hoy",
                            _show_today,
                        )
                    ),
                    (
                        primary_button(
                            "Semana",
                            _show_week,
                        )
                        if state.get(
                            "view_mode"
                        )
                        == "WEEK"
                        else secondary_button(
                            "Semana",
                            _show_week,
                        )
                    ),
                    (
                        primary_button(
                            "Mes",
                            _show_month,
                        )
                        if state.get(
                            "view_mode"
                        )
                        == "MONTH"
                        else secondary_button(
                            "Mes",
                            _show_month,
                        )
                    ),
                    search_input,
                    responsible_filter,
                    priority_filter,
                    status_filter,
                    type_filter,
                    secondary_button(
                        "Limpiar",
                        lambda e: (
                            _clear_calendar_filters(
                                update=True,
                            )
                        ),
                    ),
                ],
                spacing=10,
                wrap=True,
            ),
        )

        view_mode = (
            state.get(
                "view_mode"
            )
            or "WEEK"
        )

        month_anchor = state[
            "month_anchor"
        ]

        if view_mode == "TODAY":
            today = datetime.now()

            period_label = ""

            calendar_body = (
                calendar_today_primary(
                    calendar_items,
                    today,
                    on_item_click=(
                        _open_detail_dialog
                    ),
                )
            )

        elif view_mode == "MONTH":
            period_label = (
                month_anchor.strftime(
                    "%B %Y"
                ).capitalize()
            )

            calendar_body = (
                calendar_month_grid(
                    calendar_items,
                    month_anchor,
                    on_day_click=(
                        _open_day_as_week
                    ),
                )
            )

        else:
            period_label = (
                f"{week_start.strftime('%d/%m')}"
                " – "
                f"{week_end.strftime('%d/%m/%Y')}"
            )

            calendar_body = (
                calendar_week_grid(
                    calendar_items,
                    week_start,
                    on_item_click=(
                        select_item
                    ),
                    highlighted_keys=(
                        highlighted_keys
                    ),
                )
            )

        calendar_header = ft.Row(
            controls=[
                secondary_button(
                    "‹",
                    previous_week,
                ),
                secondary_button(
                    "›",
                    next_week,
                ),
                ft.Text(
                    period_label,
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
        )

        if view_mode == "TODAY":
            calendar_workspace = (
                calendar_body
            )
        else:
            calendar_workspace = (
                ft.Container(
                    height=460,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            calendar_header,
                            calendar_body,
                        ],
                        spacing=10,
                    ),
                )
            )

        period_actions = (
            _period_action_items(
                filtered_period_items,
                view_mode=view_mode,
                week_start=week_start,
                month_anchor=month_anchor,
            )
        )

        calendar_workspace_slot.content = (
            calendar_workspace
        )

        period_actions_slot.content = (
            calendar_today_summary(
                calendar_items,
                datetime.now(),
                on_item_click=(
                    _open_detail_dialog
                ),
            )
            if view_mode
            == "TODAY"
            else upcoming_table(
                period_actions,
                limit=(
                    None
                    if view_mode
                    == "MONTH"
                    else 20
                ),
            )
        )

        left = ft.Column(
            controls=[
                calendar_workspace_slot,
                period_actions_slot,
            ],
            spacing=12,
            expand=True,
        )

        right = ft.Container(
            width=330,
            height=460,
            content=ft.Column(
                controls=[
                    calendar_summary_panel(
                        state["summary"],
                        calendar_service
                        .get_upcoming_items(
                            days=7,
                            limit=20,
                        ),
                        on_select_item=(
                            select_item
                        ),
                    ),
                ],
                spacing=12,
                expand=True,
            ),
        )

        content.content = ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=18,
            content=ft.Column(
                controls=[
                    header,
                    controls_bar,
                    ft.Row(
                        controls=[
                            left,
                            right,
                        ],
                        spacing=14,
                        vertical_alignment=(
                            ft.CrossAxisAlignment
                            .START
                        ),
                        expand=True,
                    ),
                ],
                spacing=14,
            ),
        )

    def refresh_filtered_results(
        e=None,
    ):
        """
        Refresco parcial de filtros.

        No reconstruye:
        - cabecera;
        - buscador;
        - dropdowns;
        - botones Hoy/Semana/Mes;
        - panel derecho.

        Solo reconstruye:
        - calendario para aplicar resaltado;
        - próximas actuaciones filtradas.

        Es el mismo principio utilizado por
        Clientes al refrescar únicamente su
        bloque de resultados.
        """

        week_start = state[
            "week_start"
        ]

        week_end = (
            week_start
            + timedelta(
                days=6
            )
        )

        calendar_items = list(
            state["items"]
        )

        filtered_period_items = (
            filtered_items(
                calendar_items
            )
        )

        highlighted_keys = set()

        if _calendar_filters_active():
            highlighted_keys = {
                (
                    str(
                        item.get(
                            "item_type"
                        )
                        or ""
                    ).upper(),
                    item.get(
                        "source_id"
                    ),
                )
                for item
                in filtered_period_items
            }

        view_mode = (
            state.get(
                "view_mode"
            )
            or "WEEK"
        )

        month_anchor = state[
            "month_anchor"
        ]

        if view_mode == "TODAY":
            today = datetime.now()

            calendar_body = (
                calendar_today_primary(
                    calendar_items,
                    today,
                    on_item_click=(
                        _open_detail_dialog
                    ),
                )
            )

            calendar_workspace = (
                calendar_body
            )

        elif view_mode == "MONTH":
            period_label = (
                month_anchor.strftime(
                    "%B %Y"
                ).capitalize()
            )

            calendar_body = (
                calendar_month_grid(
                    calendar_items,
                    month_anchor,
                    on_day_click=(
                        _open_day_as_week
                    ),
                )
            )

            calendar_header = ft.Row(
                controls=[
                    secondary_button(
                        "‹",
                        previous_week,
                    ),
                    secondary_button(
                        "›",
                        next_week,
                    ),
                    ft.Text(
                        period_label,
                        size=14,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=8,
            )

            calendar_workspace = (
                ft.Container(
                    height=460,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            calendar_header,
                            calendar_body,
                        ],
                        spacing=10,
                    ),
                )
            )

        else:
            period_label = (
                f"{week_start.strftime('%d/%m')}"
                " – "
                f"{week_end.strftime('%d/%m/%Y')}"
            )

            calendar_body = (
                calendar_week_grid(
                    calendar_items,
                    week_start,
                    on_item_click=(
                        select_item
                    ),
                    highlighted_keys=(
                        highlighted_keys
                    ),
                )
            )

            calendar_header = ft.Row(
                controls=[
                    secondary_button(
                        "‹",
                        previous_week,
                    ),
                    secondary_button(
                        "›",
                        next_week,
                    ),
                    ft.Text(
                        period_label,
                        size=14,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=8,
            )

            calendar_workspace = (
                ft.Container(
                    height=460,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            calendar_header,
                            calendar_body,
                        ],
                        spacing=10,
                    ),
                )
            )

        period_actions = (
            _period_action_items(
                filtered_period_items,
                view_mode=view_mode,
                week_start=week_start,
                month_anchor=month_anchor,
            )
        )

        calendar_workspace_slot.content = (
            calendar_workspace
        )

        period_actions_slot.content = (
            calendar_today_summary(
                calendar_items,
                datetime.now(),
                on_item_click=(
                    _open_detail_dialog
                ),
            )
            if view_mode
            == "TODAY"
            else upcoming_table(
                period_actions,
                limit=(
                    None
                    if view_mode
                    == "MONTH"
                    else 20
                ),
            )
        )

        # Importante:
        # NO llamamos render().
        # Así search_input no pierde foco.
        safe_update()


    def refresh(e=None):
        week_start = state[
            "week_start"
        ]

        if (
            state.get(
                "view_mode"
            )
            == "TODAY"
        ):
            now = datetime.now()

            range_start = now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            range_end = now.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999,
            )

        elif (
            state.get(
                "view_mode"
            )
            == "MONTH"
        ):
            month_anchor = state[
                "month_anchor"
            ]

            first_day = (
                month_anchor.replace(
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            )

            range_start = (
                first_day
                - timedelta(
                    days=(
                        first_day.weekday()
                    )
                )
            )

            range_end = (
                range_start
                + timedelta(
                    days=41,
                    hours=23,
                    minutes=59,
                    seconds=59,
                )
            )

        else:
            range_start = week_start

            range_end = (
                week_start
                + timedelta(
                    days=6,
                    hours=23,
                    minutes=59,
                    seconds=59,
                )
            )

        state["items"] = (
            calendar_service
            .list_calendar_items(
                start_at=(
                    range_start.isoformat(
                        sep=" "
                    )
                ),
                end_at=(
                    range_end.isoformat(
                        sep=" "
                    )
                ),
            )
        )

        state["summary"] = (
            calendar_service
            .get_calendar_summary()
        )

        responsibles = sorted(
            {
                item.get(
                    "responsible"
                )
                for item
                in state["items"]
                if item.get(
                    "responsible"
                )
            }
        )

        current = (
            responsible_filter.value
            or "Todos"
        )

        responsible_filter.options = [
            ft.dropdown.Option(
                "Todos"
            ),
            *[
                ft.dropdown.Option(
                    value
                )
                for value
                in responsibles
            ],
        ]

        responsible_filter.value = (
            current
            if current
            in (
                ["Todos"]
                + responsibles
            )
            else "Todos"
        )

        render()
        safe_update()

    def filters_changed(e=None):
        # Igual que en Clientes:
        # el control de búsqueda permanece montado
        # y solo se reconstruyen los resultados.
        refresh_filtered_results(
            e
        )

    search_input.on_change = (
        filters_changed
    )

    responsible_filter.on_change = (
        filters_changed
    )

    priority_filter.on_change = (
        filters_changed
    )

    status_filter.on_change = (
        filters_changed
    )

    type_filter.on_change = (
        filters_changed
    )

    refresh()

    initial_action_normalized = str(
        initial_action
        or ""
    ).strip().upper()

    if initial_action_normalized == "TASK":
        _open_new_task_dialog()

    elif initial_action_normalized == "ALERT":
        _open_new_alert_dialog()

    return content

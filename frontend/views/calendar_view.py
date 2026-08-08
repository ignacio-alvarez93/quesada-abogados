from datetime import datetime, timedelta
import time

import flet as ft

from backend.services import calendar_service
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


def calendar_view(
    page: ft.Page,
    on_open_expediente=None,
    on_open_cliente=None,
):
    state = {
        "week_start": _monday(
            datetime.now()
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
        width=720,
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
        width=720,
    )

    alert_description = multiline_input(
        "Descripción",
        width=720,
        height=100,
    )

    alert_client = AppAutocomplete(
        page=page,
        label="Cliente",
        options=client_options,
        width=720,
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
        width=720,
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

    alert_dialog = None

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
            "ACTIVO",
            "RESUELTO",
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
            task_expedient.options = []
            task_expedient.input.value = ""
            task_expedient.selected_option = None

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

        task_expedient.options = [
            _expedient_label(item)
            for item in expedients
        ]

        task_expedient.input.value = ""
        task_expedient.selected_option = None

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

                        task_expedient.options = [
                            current_label,
                            *task_expedient.options,
                        ]

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


    def _reset_alert_form():
        alert_title.value = ""
        alert_description.value = ""

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


    def _reset_task_form():
        task_title.value = ""
        task_description.value = ""

        task_client.input.value = ""
        task_client.selected_option = None

        task_expedient.options = []
        task_expedient.input.value = ""
        task_expedient.selected_option = None

        task_priority.value = "NORMAL"
        task_responsible.value = ""

        now = datetime.now()

        task_due_date.value = (
            now.strftime("%d/%m/%Y")
        )

        task_due_time.value = "09:00"


    def _close_task_dialog(e=None):
        nonlocal task_dialog

        if task_dialog is None:
            return

        page.pop_dialog()
        page.update()

        task_dialog = None


    def _close_alert_dialog(e=None):
        nonlocal alert_dialog

        if alert_dialog is None:
            return

        page.pop_dialog()
        page.update()

        alert_dialog = None


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

            result = (
                calendar_alert_app
                .create_calendar_alert(
                    titulo=title,
                    descripcion=str(
                        alert_description.value
                        or ""
                    ).strip(),
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

            _close_alert_dialog()

            refresh()
            render()
            safe_update()

            _show_message(
                (
                    "Aviso creado correctamente. "
                    "Telegram programado."
                )
            )

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

            _close_task_dialog()

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


    def _open_new_alert_dialog(e=None):
        nonlocal alert_dialog

        _reset_alert_form()

        alert_dialog = form_dialog(
            "Nuevo aviso",
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
                                        .NOTIFICATIONS_ACTIVE_ROUNDED,
                                        size=18,
                                        color=Q_PRIMARY,
                                    ),
                                    ft.Text(
                                        (
                                            "El aviso aparecerá en "
                                            "Calendar en la fecha del "
                                            "evento. Telegram se enviará "
                                            "en la fecha de aviso. Si "
                                            "la dejas vacía, se utilizará "
                                            "la propia fecha del evento."
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
                    "Crear aviso",
                    _save_alert,
                ),
            ],
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

        task_dialog = form_dialog(
            "Nueva tarea",
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
                                        .SEND_ROUNDED,
                                        size=18,
                                        color=Q_PRIMARY,
                                    ),
                                    ft.Text(
                                        (
                                            "Al guardar, Telegram "
                                            "se programa automáticamente "
                                            "según la prioridad."
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
                    "Guardar tarea",
                    _save_task,
                ),
            ],
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


    def show_placeholder(
        message,
    ):
        page.snack_bar = ft.SnackBar(
            ft.Text(message)
        )
        page.snack_bar.open = True
        page.update()

    def previous_week(e=None):
        state["week_start"] -= (
            timedelta(days=7)
        )

        refresh()

    def next_week(e=None):
        state["week_start"] += (
            timedelta(days=7)
        )

        refresh()

    def current_week(e=None):
        state["week_start"] = (
            _monday(
                datetime.now()
            )
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

    def filtered_items():
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

        for item in state["items"]:
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


    def upcoming_table(items):
        rows = []

        for item in items[:8]:
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


    def _task_notification_section(
        task_id,
    ):
        try:
            notifications = (
                scheduled_notification_service
                .list_for_source(
                    "TASK",
                    int(task_id),
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

    def render():
        week_start = state[
            "week_start"
        ]

        week_end = (
            week_start
            + timedelta(days=6)
        )

        items = filtered_items()

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
                    lambda e:
                        show_placeholder(
                            "Agenda completa: siguiente fase."
                        ),
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
                    secondary_button(
                        "Hoy",
                        current_week,
                    ),
                    primary_button(
                        "Semana",
                        lambda e: None,
                    ),
                    secondary_button(
                        "Mes",
                        lambda e:
                            show_placeholder(
                                "Vista mensual: siguiente iteración visual."
                            ),
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
                    (
                        f"{week_start.strftime('%d/%m')}"
                        " – "
                        f"{week_end.strftime('%d/%m/%Y')}"
                    ),
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
        )

        calendar_workspace = ft.Container(
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
                    calendar_week_grid(
                        items,
                        week_start,
                        on_item_click=(
                            select_item
                        ),
                    ),
                ],
                spacing=10,
            ),
        )

        left = ft.Column(
            controls=[
                calendar_workspace,
                upcoming_table(
                    calendar_service
                    .get_upcoming_items(
                        days=7,
                        limit=20,
                    )
                ),
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

    def refresh(e=None):
        week_start = state[
            "week_start"
        ]

        week_end = (
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
                    week_start.isoformat(
                        sep=" "
                    )
                ),
                end_at=(
                    week_end.isoformat(
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
        render()
        safe_update()

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

    return content

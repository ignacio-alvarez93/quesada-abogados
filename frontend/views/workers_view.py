from __future__ import annotations

import flet as ft

from backend.services import worker_service
from frontend.components import (
    empty_state,
    metric_card,
    primary_button,
)
from frontend.components.app_autocomplete import (
    AppAutocomplete,
)
from frontend.components.listing import (
    compact_pagination_bar,
)
from frontend.components.worker_card import worker_card
from frontend.views.worker_detail_view import (
    worker_detail_view,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"


STATUS_OPTIONS = [
    {"id": "ACTIVE", "label": "Activos"},
    {"id": "ALL", "label": "Todos"},
    {"id": "INACTIVE", "label": "Inactivos"},
    {
        "id": "TEMPORARY_LEAVE",
        "label": "Baja temporal",
    },
    {
        "id": "SICK_LEAVE",
        "label": "Baja médica",
    },
    {
        "id": "MATERNITY_PATERNITY",
        "label": "Nacimiento y cuidado",
    },
    {
        "id": "LEAVE_OF_ABSENCE",
        "label": "Excedencia",
    },
    {
        "id": "TERMINATED",
        "label": "Finalizados",
    },
]


def _text_field(
    label,
    *,
    width=250,
    multiline=False,
):
    return ft.TextField(
        label=label,
        width=width,
        multiline=multiline,
        min_lines=3 if multiline else 1,
        max_lines=5 if multiline else 1,
        dense=True,
        border_radius=10,
    )


def _dropdown(
    label,
    options,
    *,
    width=240,
    value=None,
):
    return ft.Dropdown(
        label=label,
        width=width,
        value=value,
        dense=True,
        border_radius=10,
        options=[
            ft.dropdown.Option(
                key,
                text,
            )
            for key, text in options
        ],
    )


def _display_date(value):
    raw = str(value or "").strip()

    if not raw:
        return ""

    parts = raw.split("-")

    if len(parts) == 3:
        year, month, day = parts
        if (
            len(year) == 4
            and len(month) == 2
            and len(day) == 2
        ):
            return f"{day}/{month}/{year}"

    return raw


def _snack(
    page,
    message,
    *,
    error=False,
):
    page.snack_bar = ft.SnackBar(
        content=ft.Text(message),
        bgcolor=(
            "#FEF3F2"
            if error
            else "#ECFDF3"
        ),
        open=True,
    )
    page.update()


def workers_view(page: ft.Page):
    worker_service.ensure_schema()

    state = {
        "workers": [],
        "page": 1,
        "page_size": 12,
        "search": "",
        "status": "ACTIVE",
        "department": "ALL",
        "editing_id": None,
        "detail_worker_id": None,
    }

    root = ft.Container(
        expand=True,
        bgcolor="#FFFFFF",
    )

    results_box = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, -1),
    )

    metrics_box = ft.Row(
        controls=[],
        spacing=10,
        wrap=True,
    )

    status_ac = AppAutocomplete(
        page,
        "Estado laboral",
        options=STATUS_OPTIONS,
        value="Activos",
        width=220,
        max_results=8,
        allow_free_text=False,
    )

    department_ac = AppAutocomplete(
        page,
        "Departamento",
        options=[
            {
                "id": "ALL",
                "label": "Todos los departamentos",
            }
        ],
        value="Todos los departamentos",
        width=260,
        max_results=8,
        allow_free_text=False,
    )

    search_input = ft.TextField(
        label="Buscar trabajador",
        hint_text=(
            "Nombre, DNI/NIE, teléfono, "
            "puesto o departamento..."
        ),
        width=460,
        dense=True,
        prefix_icon=ft.Icons.SEARCH,
        border_radius=10,
    )

    first_name = _text_field(
        "Nombre *",
        width=240,
    )
    last_name_1 = _text_field(
        "Primer apellido",
        width=240,
    )
    last_name_2 = _text_field(
        "Segundo apellido",
        width=240,
    )

    document_type = _dropdown(
        "Tipo de documento",
        [
            ("", "Sin indicar"),
            ("DNI", "DNI"),
            ("NIE", "NIE"),
            ("PASSPORT", "Pasaporte"),
            ("OTHER", "Otro"),
        ],
        width=210,
        value="",
    )
    tax_id = _text_field(
        "DNI / NIE / documento",
        width=250,
    )
    birth_date = _text_field(
        "Fecha de nacimiento (DD/MM/YYYY)",
        width=230,
    )
    birth_date.hint_text = "DD/MM/YYYY"
    social_security_number = _text_field(
        "Número de Seguridad Social",
        width=270,
    )

    phone = _text_field(
        "Teléfono",
        width=220,
    )
    secondary_phone = _text_field(
        "Teléfono secundario",
        width=220,
    )
    email = _text_field(
        "Correo electrónico",
        width=300,
    )

    address = _text_field(
        "Domicilio",
        width=730,
    )
    postal_code = _text_field(
        "Código postal",
        width=180,
    )
    city = _text_field(
        "Localidad",
        width=230,
    )
    province = _text_field(
        "Provincia",
        width=230,
    )
    country = _text_field(
        "País",
        width=220,
    )

    iban = _text_field(
        "IBAN para nómina",
        width=360,
    )

    position = _text_field(
        "Puesto",
        width=260,
    )
    department = _text_field(
        "Departamento",
        width=250,
    )
    workplace = _text_field(
        "Centro de trabajo",
        width=260,
    )

    professional_category = _text_field(
        "Categoría profesional",
        width=270,
    )
    collective_agreement = _text_field(
        "Convenio colectivo",
        width=330,
    )

    hire_date = _text_field(
        "Fecha de alta (DD/MM/YYYY)",
        width=230,
    )
    hire_date.hint_text = "DD/MM/YYYY"
    termination_date = _text_field(
        "Fecha de baja (DD/MM/YYYY)",
        width=230,
    )
    termination_date.hint_text = "DD/MM/YYYY"

    employment_status = _dropdown(
        "Estado laboral",
        [
            ("ACTIVE", "Activo"),
            (
                "TEMPORARY_LEAVE",
                "Baja temporal",
            ),
            (
                "SICK_LEAVE",
                "Baja médica",
            ),
            (
                "MATERNITY_PATERNITY",
                "Nacimiento y cuidado",
            ),
            (
                "LEAVE_OF_ABSENCE",
                "Excedencia",
            ),
            ("TERMINATED", "Finalizado"),
        ],
        width=260,
        value="ACTIVE",
    )

    notes = _text_field(
        "Observaciones internas",
        width=730,
        multiline=True,
    )

    def all_form_controls():
        return [
            first_name,
            last_name_1,
            last_name_2,
            document_type,
            tax_id,
            birth_date,
            social_security_number,
            phone,
            secondary_phone,
            email,
            address,
            postal_code,
            city,
            province,
            country,
            iban,
            position,
            department,
            workplace,
            professional_category,
            collective_agreement,
            hire_date,
            termination_date,
            employment_status,
            notes,
        ]

    def reset_form():
        state["editing_id"] = None

        for control in all_form_controls():
            try:
                control.value = ""
            except Exception:
                pass

        document_type.value = ""
        country.value = "España"
        employment_status.value = "ACTIVE"

    def form_data():
        return {
            "first_name": first_name.value,
            "last_name_1": last_name_1.value,
            "last_name_2": last_name_2.value,
            "document_type": document_type.value,
            "tax_id": tax_id.value,
            "birth_date": birth_date.value,
            "social_security_number":
                social_security_number.value,
            "phone": phone.value,
            "secondary_phone":
                secondary_phone.value,
            "email": email.value,
            "address": address.value,
            "postal_code": postal_code.value,
            "city": city.value,
            "province": province.value,
            "country": country.value,
            "iban": iban.value,
            "position": position.value,
            "department": department.value,
            "workplace": workplace.value,
            "professional_category":
                professional_category.value,
            "collective_agreement":
                collective_agreement.value,
            "hire_date": hire_date.value,
            "termination_date":
                termination_date.value,
            "employment_status":
                employment_status.value,
            "active": (
                employment_status.value
                != "TERMINATED"
            ),
            "notes": notes.value,
        }

    def fill_form(worker):
        state["editing_id"] = int(worker["id"])

        mapping = {
            first_name: "first_name",
            last_name_1: "last_name_1",
            last_name_2: "last_name_2",
            document_type: "document_type",
            tax_id: "tax_id",
            birth_date: "birth_date",
            social_security_number:
                "social_security_number",
            phone: "phone",
            secondary_phone: "secondary_phone",
            email: "email",
            address: "address",
            postal_code: "postal_code",
            city: "city",
            province: "province",
            country: "country",
            iban: "iban",
            position: "position",
            department: "department",
            workplace: "workplace",
            professional_category:
                "professional_category",
            collective_agreement:
                "collective_agreement",
            hire_date: "hire_date",
            termination_date:
                "termination_date",
            employment_status:
                "employment_status",
            notes: "notes",
        }

        date_keys = {
            "birth_date",
            "hire_date",
            "termination_date",
        }

        for control, key in mapping.items():
            value = worker.get(key)

            if key in date_keys:
                control.value = _display_date(value)
            else:
                control.value = (
                    ""
                    if value is None
                    else str(value)
                )

    def close_worker_dialog(e=None):
        worker_dialog.open = False
        page.update()

    def save_worker(e=None):
        try:
            data = form_data()

            if state.get("editing_id"):
                worker_service.update_worker(
                    state["editing_id"],
                    data,
                )
                message = "Trabajador actualizado"
            else:
                worker_service.create_worker(data)
                message = "Trabajador creado"

            detail_worker_id = state.get(
                "detail_worker_id"
            )

            close_worker_dialog()
            state["page"] = 1

            if detail_worker_id:
                updated_worker = (
                    worker_service.get_worker(
                        detail_worker_id
                    )
                )

                if updated_worker:
                    show_detail(updated_worker)
                else:
                    show_list()
            else:
                load_workers()

            _snack(page, message)

        except Exception as exc:
            _snack(
                page,
                f"No se pudo guardar: {exc}",
                error=True,
            )

    worker_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Nuevo trabajador",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Container(
            width=1040,
            height=700,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Identificación personal",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            first_name,
                            last_name_1,
                            last_name_2,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            document_type,
                            tax_id,
                            birth_date,
                            social_security_number,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Contacto y domicilio",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            phone,
                            secondary_phone,
                            email,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    address,
                    ft.Row(
                        controls=[
                            postal_code,
                            city,
                            province,
                            country,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Datos laborales",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            position,
                            department,
                            workplace,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            professional_category,
                            collective_agreement,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            hire_date,
                            termination_date,
                            employment_status,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Datos económicos",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    iban,
                    ft.Divider(),
                    ft.Text(
                        "Observaciones",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    notes,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton(
                "Cancelar",
                on_click=close_worker_dialog,
            ),
            primary_button(
                "Guardar",
                save_worker,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(
            radius=16,
        ),
    )

    page.overlay.append(worker_dialog)

    def open_new_dialog(e=None):
        reset_form()
        worker_dialog.title = ft.Text(
            "Nuevo trabajador",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )
        worker_dialog.open = True
        page.update()

    def open_edit_dialog(worker):
        fill_form(worker)
        worker_dialog.title = ft.Text(
            "Editar trabajador",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )
        worker_dialog.open = True
        page.update()

    def selected_id(
        autocomplete,
        fallback=None,
    ):
        selected = autocomplete.get_selected()

        if isinstance(selected, dict):
            return selected.get("id")

        return fallback

    def update_metrics():
        metrics = worker_service.worker_metrics()

        metrics_box.controls = [
            metric_card(
                "Total",
                metrics.get("total", 0),
            ),
            metric_card(
                "Activos",
                metrics.get("active", 0),
            ),
            metric_card(
                "Inactivos",
                metrics.get("inactive", 0),
            ),
            metric_card(
                "Departamentos",
                metrics.get("departments", 0),
            ),
        ]

    def update_department_options():
        options = [
            {
                "id": "ALL",
                "label": "Todos los departamentos",
            }
        ]

        options.extend(
            {
                "id": department,
                "label": department,
            }
            for department
            in worker_service.worker_departments()
        )

        department_ac.set_options(
            options,
            clear_value=False,
        )

    def load_workers():
        state["workers"] = (
            worker_service.list_workers(
                search=state["search"],
                status=state["status"],
                department=state["department"],
            )
        )

        update_metrics()
        update_department_options()
        render_results()

    def set_page(page_number):
        state["page"] = max(
            1,
            int(page_number or 1),
        )
        render_results()

    def show_detail(worker):
        worker_id = int(worker["id"])
        state["detail_worker_id"] = worker_id

        root.content = worker_detail_view(
            page,
            worker_id,
            on_back=show_list,
            on_edit=open_edit_dialog,
        )
        page.update()

    def open_edit(worker):
        open_edit_dialog(worker)

    def toggle_active(worker):
        try:
            worker_service.set_worker_active(
                worker["id"],
                not bool(worker.get("active")),
            )
            load_workers()
            page.update()
        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(str(exc)),
                open=True,
            )
            page.update()

    def render_results():
        workers = list(
            state.get("workers") or []
        )

        total_items = len(workers)
        page_size = int(
            state.get("page_size") or 12
        )

        total_pages = max(
            1,
            (
                total_items
                + page_size
                - 1
            )
            // page_size,
        )

        current_page = max(
            1,
            min(
                int(state.get("page") or 1),
                total_pages,
            ),
        )

        state["page"] = current_page

        start = (
            current_page - 1
        ) * page_size

        visible = workers[
            start:start + page_size
        ]

        if not visible:
            results_box.content = ft.Container(
                expand=True,
                alignment=ft.Alignment(0, 0),
                content=empty_state(
                    "No hay trabajadores para los filtros seleccionados"
                ),
            )
            return

        cards = [
            worker_card(
                worker,
                on_open=show_detail,
                on_edit=open_edit,
                on_toggle_active=toggle_active,
            )
            for worker in visible
        ]

        results_box.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"{total_items} "
                                "trabajador(es)"
                            ),
                            size=12,
                            color=Q_MUTED,
                            expand=True,
                        ),
                        compact_pagination_bar(
                            page=current_page,
                            page_size=page_size,
                            total_items=total_items,
                            on_page_change=set_page,
                            label_prefix="Trabajadores",
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.ListView(
                    controls=cards,
                    spacing=10,
                    expand=True,
                    padding=ft.padding.only(
                        right=4,
                        bottom=12,
                    ),
                ),
            ],
            spacing=12,
            expand=True,
        )

    def on_search_change(e=None):
        state["search"] = (
            search_input.value or ""
        ).strip()
        state["page"] = 1

        state["workers"] = (
            worker_service.list_workers(
                search=state["search"],
                status=state["status"],
                department=state["department"],
            )
        )

        render_results()

        try:
            results_box.update()
        except Exception:
            page.update()

    def on_status_selected(value=None):
        state["status"] = (
            selected_id(
                status_ac,
                "ACTIVE",
            )
            or "ACTIVE"
        )
        state["page"] = 1
        load_workers()
        page.update()

    def on_department_selected(value=None):
        state["department"] = (
            selected_id(
                department_ac,
                "ALL",
            )
            or "ALL"
        )
        state["page"] = 1
        load_workers()
        page.update()

    search_input.on_change = on_search_change
    status_ac.on_select = on_status_selected
    department_ac.on_select = (
        on_department_selected
    )

    def show_list(e=None):
        state["detail_worker_id"] = None
        load_workers()

        root.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Trabajadores",
                                    size=28,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Directorio laboral, "
                                        "contratos y futura "
                                        "gestión de nóminas"
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        primary_button(
                            "Nuevo trabajador",
                            open_new_dialog,
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                metrics_box,
                ft.Row(
                    controls=[
                        search_input,
                        status_ac.control,
                        department_ac.control,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Divider(
                    height=1,
                    color=Q_BORDER,
                ),
                results_box,
            ],
            spacing=14,
            expand=True,
        )


        page.update()

    show_list()

    return root

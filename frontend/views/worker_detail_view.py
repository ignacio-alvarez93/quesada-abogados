from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import (
    worker_contract_service,
    worker_service,
)
from frontend.components import (
    detail_section,
    empty_state,
    multiline_input,
    primary_button,
    secondary_button,
    select_input,
    status_badge,
    text_input,
)
from frontend.components.app_autocomplete import (
    AppAutocomplete,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"


STATUS_LABELS = {
    "ACTIVE": "Activo",
    "TEMPORARY_LEAVE": "Baja temporal",
    "SICK_LEAVE": "Baja médica",
    "MATERNITY_PATERNITY": "Nacimiento y cuidado",
    "LEAVE_OF_ABSENCE": "Excedencia",
    "TERMINATED": "Finalizado",
}


def _text(value, fallback="-"):
    value = str(value or "").strip()
    return value or fallback


def _full_name(worker):
    return " ".join(
        part
        for part in [
            str(worker.get("first_name") or "").strip(),
            str(worker.get("last_name_1") or "").strip(),
            str(worker.get("last_name_2") or "").strip(),
        ]
        if part
    ) or f"Trabajador #{worker.get('id')}"


def _display_date(value):
    raw = str(value or "").strip()

    if not raw:
        return "-"

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%d/%m/%Y")
        except ValueError:
            pass

    return raw


def _initials(worker):
    parts = [
        str(worker.get("first_name") or "").strip(),
        str(worker.get("last_name_1") or "").strip(),
    ]

    return "".join(
        part[0].upper()
        for part in parts
        if part
    )[:2] or "TR"


def _photo_placeholder(worker):
    return ft.Container(
        width=78,
        height=78,
        border_radius=39,
        bgcolor="#EAF3FF",
        alignment=ft.Alignment(0, 0),
        content=ft.Text(
            _initials(worker),
            size=26,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY,
        ),
    )



def _money_from_centimos(value):
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


def _centimos_from_input(value):
    raw = str(value or "").strip()

    if not raw:
        return 0

    raw = (
        raw.replace("€", "")
        .replace(" ", "")
    )

    if "," in raw:
        raw = (
            raw.replace(".", "")
            .replace(",", ".")
        )

    try:
        return int(
            round(float(raw) * 100)
        )
    except ValueError:
        raise ValueError(
            "El salario debe ser "
            "un importe válido"
        )


CONTRACT_TYPE_LABELS = {
    "INDEFINITE": "Indefinido",
    "TEMPORARY": "Temporal",
    "TRAINING": "Formativo",
    "INTERNSHIP": "Prácticas",
    "OTHER": "Otro",
}


WORKDAY_LABELS = {
    "FULL_TIME": "Jornada completa",
    "PART_TIME": "Jornada parcial",
}


SALARY_PERIOD_LABELS = {
    "ANNUAL": "Anual",
    "MONTHLY": "Mensual",
}


def worker_detail_view(
    page: ft.Page,
    worker_id: int,
    *,
    on_back=None,
    on_edit=None,
):
    worker = worker_service.get_worker(worker_id)

    if not worker:
        return empty_state(
            "No se ha encontrado el trabajador"
        )

    state = {
        "section": "ficha",
    }

    content_container = ft.Container(
        expand=True,
    )

    contract_state = {
        "editing_id": None,
    }

    cno_options = (
        worker_contract_service
        .load_cno_autocomplete_options()
    )

    contract_code = text_input(
        "Código de contrato",
        width=210,
    )

    contract_type = select_input(
        "Tipo de contrato",
        list(CONTRACT_TYPE_LABELS.values()),
        value="Indefinido",
        width=240,
    )

    contract_start_date = text_input(
        "Fecha inicio DD/MM/AAAA",
        width=220,
    )

    contract_end_date = text_input(
        "Fecha fin DD/MM/AAAA",
        width=220,
    )

    trial_period_end_date = text_input(
        "Fin periodo de prueba",
        width=220,
    )

    contract_position = text_input(
        "Puesto",
        width=330,
    )

    contract_cno = AppAutocomplete(
        page=page,
        label="Ocupación CNO / SEPE",
        options=cno_options,
        width=720,
        max_results=10,
        allow_free_text=False,
    )

    workday_type = select_input(
        "Jornada",
        list(WORKDAY_LABELS.values()),
        value="Jornada completa",
        width=240,
    )

    weekly_hours = text_input(
        "Horas semanales",
        width=180,
    )

    gross_salary = text_input(
        "Salario bruto",
        width=190,
    )

    salary_periodicity = select_input(
        "Periodicidad",
        list(SALARY_PERIOD_LABELS.values()),
        value="Anual",
        width=190,
    )

    payments_per_year = text_input(
        "Número de pagas",
        width=170,
    )

    professional_category = text_input(
        "Categoría profesional",
        width=310,
    )

    contribution_group = text_input(
        "Grupo de cotización",
        width=230,
    )

    collective_agreement = text_input(
        "Convenio colectivo",
        width=420,
    )

    document_path = text_input(
        "Ruta del documento",
        width=720,
    )

    contract_notes = multiline_input(
        "Observaciones",
        width=720,
    )

    contract_message = ft.Column(
        controls=[],
        visible=False,
    )

    def _value_key(labels, value, default):
        selected = str(value or "").strip()

        for key, label in labels.items():
            if selected == label:
                return key

        return default


    def _cno_option_for_contract(contract):
        catalog_id = str(
            contract.get(
                "contract_cno_catalog_id"
            )
            or ""
        ).strip()

        code = str(
            contract.get("contract_cno_code")
            or ""
        ).strip()

        description = str(
            contract.get(
                "contract_cno_description"
            )
            or ""
        ).strip()

        for option in cno_options:
            resolved = (
                worker_contract_service
                .resolve_cno_value(option)
            )

            if (
                catalog_id
                and resolved.get("catalog_id")
                == catalog_id
            ):
                return option

            if (
                code
                and resolved.get("code") == code
                and (
                    not description
                    or resolved.get("description")
                    == description
                )
            ):
                return option

        return None


    def clear_contract_form():
        contract_state["editing_id"] = None

        contract_code.value = ""
        contract_type.value = "Indefinido"
        contract_start_date.value = ""
        contract_end_date.value = ""
        trial_period_end_date.value = ""
        contract_position.value = ""
        contract_cno.set_value(
            "",
            update=False,
        )
        workday_type.value = "Jornada completa"
        weekly_hours.value = "40"
        gross_salary.value = ""
        salary_periodicity.value = "Anual"
        payments_per_year.value = "14"
        professional_category.value = ""
        contribution_group.value = ""
        collective_agreement.value = ""
        document_path.value = ""
        contract_notes.value = ""

        contract_message.controls.clear()
        contract_message.visible = False


    def load_contract_form(contract):
        contract_state["editing_id"] = int(
            contract["id"]
        )

        contract_code.value = (
            contract.get("contract_code") or ""
        )

        contract_type.value = (
            CONTRACT_TYPE_LABELS.get(
                contract.get("contract_type"),
                "Otro",
            )
        )

        contract_start_date.value = _display_date(
            contract.get("start_date")
        )
        contract_end_date.value = _display_date(
            contract.get("end_date")
        )
        trial_period_end_date.value = _display_date(
            contract.get(
                "trial_period_end_date"
            )
        )

        contract_position.value = (
            contract.get("contract_position") or ""
        )

        selected_cno = _cno_option_for_contract(
            contract
        )

        if selected_cno:
            contract_cno.set_value(
                selected_cno,
                update=False,
            )
        else:
            cno_code = str(
                contract.get("contract_cno_code")
                or ""
            ).strip()
            cno_description = str(
                contract.get(
                    "contract_cno_description"
                )
                or ""
            ).strip()

            cno_label = " · ".join(
                part
                for part in [
                    cno_code,
                    cno_description,
                ]
                if part
            )

            contract_cno.set_value(
                cno_label,
                update=False,
            )

        workday_type.value = (
            WORKDAY_LABELS.get(
                contract.get("workday_type"),
                "Jornada completa",
            )
        )

        weekly_hours.value = str(
            contract.get("weekly_hours") or ""
        )

        gross_salary.value = (
            f"{int(contract.get('gross_salary_centimos') or 0) / 100:.2f}"
            .replace(".", ",")
        )

        salary_periodicity.value = (
            SALARY_PERIOD_LABELS.get(
                contract.get(
                    "salary_periodicity"
                ),
                "Anual",
            )
        )

        payments_per_year.value = str(
            contract.get("payments_per_year")
            or ""
        )

        professional_category.value = (
            contract.get(
                "professional_category"
            )
            or ""
        )
        contribution_group.value = (
            contract.get("contribution_group")
            or ""
        )
        collective_agreement.value = (
            contract.get(
                "collective_agreement"
            )
            or ""
        )
        document_path.value = (
            contract.get("document_path") or ""
        )
        contract_notes.value = (
            contract.get("notes") or ""
        )

        contract_message.controls.clear()
        contract_message.visible = False


    def close_contract_dialog(e=None):
        contract_dialog.open = False
        page.update()


    def _contract_payload():
        selected_cno = contract_cno.get_value()

        if not selected_cno:
            raise ValueError(
                "Debe seleccionar una ocupación "
                "del catálogo CNO / SEPE"
            )

        cno_data = (
            worker_contract_service
            .resolve_cno_value(selected_cno)
        )

        if not cno_data.get("catalog_id"):
            raise ValueError(
                "Debe seleccionar una ocupación "
                "válida del catálogo CNO / SEPE"
            )

        return {
            "contract_code": contract_code.value or "",
            "contract_type": _value_key(
                CONTRACT_TYPE_LABELS,
                contract_type.value,
                "INDEFINITE",
            ),
            "start_date": (
                contract_start_date.value or ""
            ),
            "end_date": (
                contract_end_date.value or ""
            ),
            "trial_period_end_date": (
                trial_period_end_date.value or ""
            ),
            "workday_type": _value_key(
                WORKDAY_LABELS,
                workday_type.value,
                "FULL_TIME",
            ),
            "weekly_hours": (
                weekly_hours.value or "40"
            ),
            "gross_salary_centimos": (
                _centimos_from_input(
                    gross_salary.value
                )
            ),
            "salary_periodicity": _value_key(
                SALARY_PERIOD_LABELS,
                salary_periodicity.value,
                "ANNUAL",
            ),
            "payments_per_year": (
                payments_per_year.value or "14"
            ),
            "contribution_group": (
                contribution_group.value or ""
            ),
            "professional_category": (
                professional_category.value or ""
            ),
            "collective_agreement": (
                collective_agreement.value or ""
            ),
            "contract_position": (
                contract_position.value or ""
            ),
            "contract_cno_code": (
                cno_data.get("code") or ""
            ),
            "contract_cno_description": (
                cno_data.get("description") or ""
            ),
            "contract_cno_catalog_id": (
                cno_data.get("catalog_id") or ""
            ),
            "document_path": (
                document_path.value or ""
            ),
            "active": 1,
            "notes": contract_notes.value or "",
        }


    def refresh_contracts_section():
        if state.get("section") == "contracts":
            content_container.content = (
                build_contracts_section()
            )
            page.update()


    def save_contract(e=None):
        try:
            payload = _contract_payload()
            editing_id = contract_state.get(
                "editing_id"
            )

            if editing_id:
                worker_contract_service.update_contract(
                    editing_id,
                    payload,
                )
            else:
                worker_contract_service.create_contract(
                    worker_id,
                    payload,
                )

            contract_dialog.open = False
            refresh_contracts_section()

        except Exception as exc:
            contract_message.controls = [
                ft.Text(
                    str(exc),
                    color="#B42318",
                    size=12,
                )
            ]
            contract_message.visible = True
            page.update()


    def open_new_contract_dialog(e=None):
        clear_contract_form()

        contract_dialog.title = ft.Text(
            "Nuevo contrato",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )

        contract_dialog.open = True
        page.update()


    def open_edit_contract_dialog(contract):
        load_contract_form(contract)

        contract_dialog.title = ft.Text(
            "Editar contrato",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )

        contract_dialog.open = True
        page.update()


    contract_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Nuevo contrato",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Container(
            width=900,
            height=680,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Datos contractuales",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            contract_type,
                            contract_code,
                            contract_start_date,
                            contract_end_date,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            trial_period_end_date,
                            contract_position,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    contract_cno.control,
                    ft.Divider(),
                    ft.Text(
                        "Jornada y salario",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            workday_type,
                            weekly_hours,
                            gross_salary,
                            salary_periodicity,
                            payments_per_year,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Clasificación laboral",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            professional_category,
                            contribution_group,
                            collective_agreement,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    document_path,
                    contract_notes,
                    contract_message,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton(
                "Cancelar",
                on_click=close_contract_dialog,
            ),
            primary_button(
                "Guardar",
                save_contract,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(
            radius=16,
        ),
    )

    page.overlay.append(contract_dialog)

    sidebar_actions = []

    if on_back:
        sidebar_actions.append(
            secondary_button(
                "Volver",
                on_back,
            )
        )

    if on_edit:
        sidebar_actions.append(
            ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                tooltip="Editar trabajador",
                on_click=lambda e: on_edit(worker),
            )
        )

    def build_ficha_section():
        return ft.Column(
            controls=[
                ft.Text(
                    "Ficha del trabajador",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                detail_section(
                    "Identificación",
                    [
                        (
                            "Código CRM",
                            worker.get("worker_code"),
                        ),
                        (
                            "Nombre completo",
                            _full_name(worker),
                        ),
                        (
                            "Documento",
                            " ".join(
                                part
                                for part in [
                                    worker.get(
                                        "document_type"
                                    ),
                                    worker.get("tax_id"),
                                ]
                                if part
                            ),
                        ),
                        (
                            "Fecha de nacimiento",
                            _display_date(
                                worker.get("birth_date")
                            ),
                        ),
                        (
                            "Número Seguridad Social",
                            worker.get(
                                "social_security_number"
                            ),
                        ),
                    ],
                ),
                detail_section(
                    "Contacto",
                    [
                        (
                            "Teléfono",
                            worker.get("phone"),
                        ),
                        (
                            "Teléfono secundario",
                            worker.get(
                                "secondary_phone"
                            ),
                        ),
                        (
                            "Correo electrónico",
                            worker.get("email"),
                        ),
                    ],
                ),
                detail_section(
                    "Domicilio",
                    [
                        (
                            "Dirección",
                            worker.get("address"),
                        ),
                        (
                            "Código postal",
                            worker.get("postal_code"),
                        ),
                        (
                            "Localidad",
                            worker.get("city"),
                        ),
                        (
                            "Provincia",
                            worker.get("province"),
                        ),
                        (
                            "País",
                            worker.get("country"),
                        ),
                    ],
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_labor_section():
        return ft.Column(
            controls=[
                ft.Text(
                    "Situación laboral",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                detail_section(
                    "Relación laboral",
                    [
                        (
                            "Estado",
                            STATUS_LABELS.get(
                                worker.get(
                                    "employment_status"
                                ),
                                worker.get(
                                    "employment_status"
                                ),
                            ),
                        ),
                        (
                            "Puesto",
                            worker.get("position"),
                        ),
                        (
                            "Departamento",
                            worker.get("department"),
                        ),
                        (
                            "Centro de trabajo",
                            worker.get("workplace"),
                        ),
                        (
                            "Categoría profesional",
                            worker.get(
                                "professional_category"
                            ),
                        ),
                        (
                            "Convenio colectivo",
                            worker.get(
                                "collective_agreement"
                            ),
                        ),
                        (
                            "Fecha de alta",
                            _display_date(
                                worker.get("hire_date")
                            ),
                        ),
                        (
                            "Fecha de baja",
                            _display_date(
                                worker.get(
                                    "termination_date"
                                )
                            ),
                        ),
                    ],
                ),
                detail_section(
                    "Datos económicos",
                    [
                        (
                            "IBAN para nómina",
                            worker.get("iban"),
                        ),
                    ],
                ),
                detail_section(
                    "Observaciones",
                    [
                        (
                            "Observaciones internas",
                            worker.get("notes"),
                        ),
                    ],
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def placeholder_section(
        title,
        section_title,
        description,
    ):
        return ft.Column(
            controls=[
                ft.Text(
                    title,
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Container(
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
                                section_title,
                                size=17,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            empty_state(description),
                        ],
                        spacing=12,
                    ),
                ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_contracts_section():
        contracts = (
            worker_contract_service
            .list_worker_contracts(worker_id)
        )

        cards = []

        for contract in contracts:
            active = bool(
                contract.get("active")
            )

            contract_type_label = (
                CONTRACT_TYPE_LABELS.get(
                    contract.get("contract_type"),
                    contract.get("contract_type")
                    or "Contrato laboral",
                )
            )

            title = (
                contract.get("contract_position")
                or contract_type_label
            )

            cno_text = " · ".join(
                part
                for part in [
                    contract.get(
                        "contract_cno_code"
                    ),
                    contract.get(
                        "contract_cno_description"
                    ),
                ]
                if part
            )

            cards.append(
                ft.Container(
                    bgcolor=Q_WHITE,
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
                                    ft.Column(
                                        controls=[
                                            ft.Text(
                                                title,
                                                size=16,
                                                weight=(
                                                    ft.FontWeight.BOLD
                                                ),
                                                color=(
                                                    Q_PRIMARY_DARK
                                                ),
                                            ),
                                            ft.Text(
                                                (
                                                    "Activo"
                                                    if active
                                                    else "Finalizado"
                                                ),
                                                size=12,
                                                color=(
                                                    "#067647"
                                                    if active
                                                    else Q_MUTED
                                                ),
                                            ),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.IconButton(
                                        icon=(
                                            ft.Icons
                                            .EDIT_OUTLINED
                                        ),
                                        tooltip=(
                                            "Editar contrato"
                                        ),
                                        on_click=(
                                            lambda e,
                                            item=contract:
                                            open_edit_contract_dialog(
                                                item
                                            )
                                        ),
                                    ),
                                ],
                            ),
                            ft.Divider(height=1),
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        (
                                            "Inicio: "
                                            f"{_display_date(contract.get('start_date'))}"
                                        ),
                                        size=12,
                                    ),
                                    ft.Text(
                                        (
                                            "Fin: "
                                            f"{_display_date(contract.get('end_date'))}"
                                        ),
                                        size=12,
                                    ),
                                    ft.Text(
                                        (
                                            WORKDAY_LABELS.get(
                                                contract.get(
                                                    "workday_type"
                                                ),
                                                contract.get(
                                                    "workday_type"
                                                )
                                                or "-",
                                            )
                                        ),
                                        size=12,
                                    ),
                                    ft.Text(
                                        (
                                            f"{contract.get('weekly_hours') or 0} h/semana"
                                        ),
                                        size=12,
                                    ),
                                ],
                                spacing=18,
                                wrap=True,
                            ),
                            ft.Text(
                                cno_text or "Sin ocupación CNO",
                                size=12,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                (
                                    f"Salario bruto: "
                                    f"{_money_from_centimos(contract.get('gross_salary_centimos'))} "
                                    f"· "
                                    f"{SALARY_PERIOD_LABELS.get(contract.get('salary_periodicity'), contract.get('salary_periodicity') or '-')}"
                                ),
                                size=12,
                                color=Q_PRIMARY_DARK,
                            ),
                        ],
                        spacing=8,
                    ),
                )
            )

        body = (
            ft.Column(
                controls=cards,
                spacing=10,
            )
            if cards
            else empty_state(
                "No hay contratos registrados"
            )
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            "Contratos",
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Container(expand=True),
                        primary_button(
                            "Nuevo contrato",
                            open_new_contract_dialog,
                        ),
                    ],
                ),
                body,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_payrolls_section():
        return placeholder_section(
            "Nóminas",
            "Nóminas del trabajador",
            (
                "Aquí se mostrarán las nóminas, "
                "gastos salariales y pagos conciliados."
            ),
        )

    def build_social_security_section():
        return placeholder_section(
            "Seguridad Social",
            "Cotizaciones",
            (
                "Aquí se mostrarán las cuotas "
                "y liquidaciones del trabajador."
            ),
        )

    def build_documents_section():
        return placeholder_section(
            "Documentos",
            "Documentación laboral",
            (
                "Aquí se mostrarán contratos, "
                "nóminas y documentos asociados."
            ),
        )

    def build_economic_section():
        return placeholder_section(
            "Económico",
            "Coste del trabajador",
            (
                "Aquí se calcularán salario bruto, "
                "Seguridad Social y coste total."
            ),
        )

    def build_traceability_section():
        return placeholder_section(
            "Trazabilidad",
            "Historial de actuaciones",
            (
                "Aquí se mostrará la actividad "
                "relacionada con el trabajador."
            ),
        )

    def build_section_content():
        section = state.get("section") or "ficha"

        if section == "labor":
            return build_labor_section()

        if section == "contracts":
            return build_contracts_section()

        if section == "payrolls":
            return build_payrolls_section()

        if section == "social_security":
            return build_social_security_section()

        if section == "documents":
            return build_documents_section()

        if section == "economic":
            return build_economic_section()

        if section == "traceability":
            return build_traceability_section()

        return build_ficha_section()

    def set_section(section):
        state["section"] = section
        content_container.content = (
            build_section_content()
        )
        page.update()

    def nav_button(label, section):
        active = (
            state.get("section") == section
        )

        return ft.Container(
            content=ft.Text(
                label,
                size=13,
                weight=(
                    ft.FontWeight.BOLD
                    if active
                    else ft.FontWeight.W_500
                ),
                color=(
                    Q_PRIMARY_DARK
                    if active
                    else Q_MUTED
                ),
            ),
            bgcolor=(
                "#EAF3FF"
                if active
                else Q_WHITE
            ),
            border=ft.border.all(
                1,
                (
                    "#B9D7FF"
                    if active
                    else Q_BORDER
                ),
            ),
            border_radius=10,
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=10,
            ),
            ink=True,
            on_click=lambda e, value=section: (
                set_section(value)
            ),
        )

    menu_items = [
        ("Ficha trabajador", "ficha"),
        ("Situación laboral", "labor"),
        ("Contratos", "contracts"),
        ("Nóminas", "payrolls"),
        (
            "Seguridad Social",
            "social_security",
        ),
        ("Documentos", "documents"),
        ("Económico", "economic"),
        ("Trazabilidad", "traceability"),
    ]

    content_container.content = (
        build_section_content()
    )

    status = STATUS_LABELS.get(
        worker.get("employment_status"),
        worker.get("employment_status") or "-",
    )

    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Container(
                        width=230,
                        bgcolor="#F8FAFC",
                        border=ft.border.all(
                            1,
                            Q_BORDER,
                        ),
                        border_radius=14,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                _photo_placeholder(worker),
                                ft.Text(
                                    _full_name(worker),
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                status_badge(status),
                                ft.Text(
                                    _text(
                                        worker.get("worker_code")
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                                ft.Divider(),
                                ft.Text(
                                    "Menú trabajador",
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Navega por las áreas "
                                        "laborales y económicas."
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Divider(),
                                *[
                                    nav_button(
                                        label,
                                        section,
                                    )
                                    for label, section
                                    in menu_items
                                ],
                                ft.Container(expand=True),
                                (
                                    ft.Divider()
                                    if sidebar_actions
                                    else ft.Container()
                                ),
                                ft.Row(
                                    controls=sidebar_actions,
                                    spacing=6,
                                    alignment=(
                                        ft.MainAxisAlignment.CENTER
                                    ),
                                    visible=bool(sidebar_actions),
                                ),
                            ],
                            spacing=8,
                            horizontal_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=Q_WHITE,
                        border=ft.border.all(
                            1,
                            Q_BORDER,
                        ),
                        border_radius=14,
                        padding=16,
                        content=content_container,
                    ),
                ],
                spacing=14,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ],
        spacing=16,
        expand=True,
    )

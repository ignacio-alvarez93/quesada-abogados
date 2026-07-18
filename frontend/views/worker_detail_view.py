from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import (
    worker_contract_service,
    worker_payroll_service,
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


def _basis_points_from_input(value):
    raw = str(value or "").strip()

    if not raw:
        return 0

    raw = (
        raw.replace("%", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    try:
        return int(round(float(raw) * 100))
    except ValueError:
        raise ValueError(
            "El tipo de IRPF debe ser "
            "un porcentaje válido"
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

    payroll_state = {
        "editing_id": None,
    }

    payroll_year = text_input(
        "Ejercicio",
        width=150,
    )
    payroll_month = select_input(
        "Mes",
        [
            "01 - Enero",
            "02 - Febrero",
            "03 - Marzo",
            "04 - Abril",
            "05 - Mayo",
            "06 - Junio",
            "07 - Julio",
            "08 - Agosto",
            "09 - Septiembre",
            "10 - Octubre",
            "11 - Noviembre",
            "12 - Diciembre",
        ],
        width=190,
    )
    payroll_accrual_date = text_input(
        "Fecha de devengo",
        width=200,
    )
    payroll_payment_due_date = text_input(
        "Fecha prevista de pago",
        width=210,
    )
    payroll_liquidation_start = text_input(
        "Inicio liquidación",
        width=200,
    )
    payroll_liquidation_end = text_input(
        "Fin liquidación",
        width=200,
    )
    payroll_liquidation_days = text_input(
        "Días liquidados",
        width=170,
    )

    payroll_gross = text_input(
        "Total devengado",
        width=190,
    )
    payroll_employee_ss = text_input(
        "SS trabajador",
        width=190,
    )
    payroll_irpf = text_input(
        "IRPF retenido",
        width=190,
    )
    payroll_other_deductions = text_input(
        "Otras deducciones",
        width=190,
    )
    payroll_total_deductions = text_input(
        "Total deducciones",
        width=190,
    )
    payroll_net = text_input(
        "Líquido",
        width=190,
    )

    payroll_employer_ss = text_input(
        "SS empresa",
        width=190,
    )
    payroll_total_cost = text_input(
        "Coste total empresa",
        width=210,
    )

    payroll_common_base = text_input(
        "Base contingencias comunes",
        width=240,
    )
    payroll_accident_base = text_input(
        "Base accidentes",
        width=210,
    )
    payroll_irpf_base = text_input(
        "Base IRPF",
        width=190,
    )
    payroll_irpf_rate = text_input(
        "Tipo IRPF %",
        width=160,
    )

    payroll_contract_code = text_input(
        "Código contrato",
        width=200,
    )
    payroll_contribution_group = text_input(
        "Grupo cotización",
        width=220,
    )
    payroll_professional_group = text_input(
        "Grupo profesional",
        width=260,
    )

    payroll_document_path = text_input(
        "Ruta del documento",
        width=720,
    )
    payroll_notes = multiline_input(
        "Observaciones",
        width=720,
    )

    payroll_message = ft.Column(
        controls=[],
        visible=False,
    )

    payroll_total_deductions.read_only = True
    payroll_net.read_only = True
    payroll_total_cost.read_only = True

    def _payroll_input_centimos(control):
        try:
            return _centimos_from_input(
                control.value
            )
        except Exception:
            return 0

    def _payroll_centimos_to_input(value):
        return (
            f"{int(value or 0) / 100:.2f}"
            .replace(".", ",")
        )

    def recalculate_payroll_totals(e=None):
        gross = _payroll_input_centimos(
            payroll_gross
        )
        employee_ss = _payroll_input_centimos(
            payroll_employee_ss
        )
        irpf = _payroll_input_centimos(
            payroll_irpf
        )
        other_deductions = (
            _payroll_input_centimos(
                payroll_other_deductions
            )
        )
        employer_ss = _payroll_input_centimos(
            payroll_employer_ss
        )

        deductions = (
            employee_ss
            + irpf
            + other_deductions
        )
        net = gross - deductions
        employer_cost = gross + employer_ss

        payroll_total_deductions.value = (
            _payroll_centimos_to_input(
                deductions
            )
        )
        payroll_net.value = (
            _payroll_centimos_to_input(
                max(0, net)
            )
        )
        payroll_total_cost.value = (
            _payroll_centimos_to_input(
                employer_cost
            )
        )

        if e is not None:
            try:
                payroll_total_deductions.update()
                payroll_net.update()
                payroll_total_cost.update()
            except Exception:
                pass

    payroll_gross.on_change = (
        recalculate_payroll_totals
    )
    payroll_employee_ss.on_change = (
        recalculate_payroll_totals
    )
    payroll_irpf.on_change = (
        recalculate_payroll_totals
    )
    payroll_other_deductions.on_change = (
        recalculate_payroll_totals
    )
    payroll_employer_ss.on_change = (
        recalculate_payroll_totals
    )

    def clear_payroll_form():
        payroll_state["editing_id"] = None

        now = datetime.now()
        month_label = next(
            (
                value
                for value in payroll_month.options
                if str(value.key or "").startswith(
                    f"{now.month:02d}"
                )
            ),
            None,
        )

        payroll_year.value = str(now.year)
        payroll_month.value = (
            month_label.key
            if month_label
            else f"{now.month:02d} -"
        )

        payroll_accrual_date.value = ""
        payroll_payment_due_date.value = ""
        payroll_liquidation_start.value = ""
        payroll_liquidation_end.value = ""
        payroll_liquidation_days.value = ""

        payroll_gross.value = ""
        payroll_employee_ss.value = ""
        payroll_irpf.value = ""
        payroll_other_deductions.value = ""
        payroll_total_deductions.value = ""
        payroll_net.value = ""

        payroll_employer_ss.value = ""
        payroll_total_cost.value = ""

        payroll_common_base.value = ""
        payroll_accident_base.value = ""
        payroll_irpf_base.value = ""
        payroll_irpf_rate.value = ""

        payroll_contract_code.value = ""
        payroll_contribution_group.value = ""
        payroll_professional_group.value = ""

        payroll_document_path.value = ""
        payroll_notes.value = ""

        payroll_message.controls.clear()
        payroll_message.visible = False

        recalculate_payroll_totals()

    def load_payroll_form(payroll):
        payroll_state["editing_id"] = int(
            payroll["id"]
        )

        payroll_year.value = str(
            payroll.get("period_year") or ""
        )

        month = int(
            payroll.get("period_month") or 0
        )
        payroll_month.value = next(
            (
                option.key
                for option in payroll_month.options
                if str(option.key or "").startswith(
                    f"{month:02d}"
                )
            ),
            "",
        )

        payroll_accrual_date.value = (
            _display_date(
                payroll.get("accrual_date")
            )
        )
        payroll_payment_due_date.value = (
            _display_date(
                payroll.get("payment_due_date")
            )
        )
        payroll_liquidation_start.value = (
            _display_date(
                payroll.get(
                    "liquidation_start_date"
                )
            )
        )
        payroll_liquidation_end.value = (
            _display_date(
                payroll.get(
                    "liquidation_end_date"
                )
            )
        )
        payroll_liquidation_days.value = str(
            payroll.get("liquidation_days") or ""
        )

        money_fields = [
            (
                payroll_gross,
                "gross_salary_centimos",
            ),
            (
                payroll_employee_ss,
                "employee_social_security_centimos",
            ),
            (
                payroll_irpf,
                "irpf_centimos",
            ),
            (
                payroll_other_deductions,
                "other_deductions_centimos",
            ),
            (
                payroll_total_deductions,
                "total_deductions_centimos",
            ),
            (
                payroll_net,
                "net_salary_centimos",
            ),
            (
                payroll_employer_ss,
                "employer_social_security_centimos",
            ),
            (
                payroll_total_cost,
                "total_employer_cost_centimos",
            ),
            (
                payroll_common_base,
                "contribution_common_base_centimos",
            ),
            (
                payroll_accident_base,
                "contribution_accident_base_centimos",
            ),
            (
                payroll_irpf_base,
                "irpf_base_centimos",
            ),
        ]

        for control, field in money_fields:
            control.value = (
                _payroll_centimos_to_input(
                    payroll.get(field)
                )
            )

        payroll_irpf_rate.value = (
            f"{int(payroll.get('irpf_rate_basis_points') or 0) / 100:.2f}"
            .replace(".", ",")
        )

        payroll_contract_code.value = (
            payroll.get(
                "contract_code_snapshot"
            )
            or ""
        )
        payroll_contribution_group.value = (
            payroll.get(
                "contribution_group_snapshot"
            )
            or ""
        )
        payroll_professional_group.value = (
            payroll.get(
                "professional_group_snapshot"
            )
            or ""
        )

        payroll_document_path.value = (
            payroll.get("document_path") or ""
        )
        payroll_notes.value = (
            payroll.get("notes") or ""
        )

        payroll_message.controls.clear()
        payroll_message.visible = False

        recalculate_payroll_totals()

    def _payroll_payload():
        month_raw = str(
            payroll_month.value or ""
        ).strip()

        if not month_raw:
            raise ValueError(
                "Debe seleccionar el mes"
            )

        month_number = int(
            month_raw.split(
                " ",
                1,
            )[0]
        )

        return {
            "period_year": int(
                payroll_year.value or 0
            ),
            "period_month": month_number,
            "accrual_date": (
                payroll_accrual_date.value or ""
            ),
            "payment_due_date": (
                payroll_payment_due_date.value or ""
            ),
            "liquidation_start_date": (
                payroll_liquidation_start.value or ""
            ),
            "liquidation_end_date": (
                payroll_liquidation_end.value or ""
            ),
            "liquidation_days": int(
                payroll_liquidation_days.value or 0
            ),
            "gross_salary_centimos": (
                _centimos_from_input(
                    payroll_gross.value
                )
            ),
            "employee_social_security_centimos": (
                _centimos_from_input(
                    payroll_employee_ss.value
                )
            ),
            "irpf_centimos": (
                _centimos_from_input(
                    payroll_irpf.value
                )
            ),
            "other_deductions_centimos": (
                _centimos_from_input(
                    payroll_other_deductions.value
                )
            ),
            "total_deductions_centimos": (
                _centimos_from_input(
                    payroll_total_deductions.value
                )
            ),
            "net_salary_centimos": (
                _centimos_from_input(
                    payroll_net.value
                )
            ),
            "employer_social_security_centimos": (
                _centimos_from_input(
                    payroll_employer_ss.value
                )
            ),
            "total_employer_cost_centimos": (
                _centimos_from_input(
                    payroll_total_cost.value
                )
            ),
            "contribution_common_base_centimos": (
                _centimos_from_input(
                    payroll_common_base.value
                )
            ),
            "contribution_accident_base_centimos": (
                _centimos_from_input(
                    payroll_accident_base.value
                )
            ),
            "irpf_base_centimos": (
                _centimos_from_input(
                    payroll_irpf_base.value
                )
            ),
            "irpf_rate_basis_points": (
                _basis_points_from_input(
                    payroll_irpf_rate.value
                )
            ),
            "contract_code_snapshot": (
                payroll_contract_code.value or ""
            ),
            "contribution_group_snapshot": (
                payroll_contribution_group.value or ""
            ),
            "professional_group_snapshot": (
                payroll_professional_group.value or ""
            ),
            "document_path": (
                payroll_document_path.value or ""
            ),
            "status": "PENDING",
            "notes": payroll_notes.value or "",
            "active": 1,
        }

    def close_payroll_dialog(e=None):
        payroll_dialog.open = False
        page.update()

    def refresh_payrolls_section():
        if state.get("section") == "payrolls":
            content_container.content = (
                build_payrolls_section()
            )
            page.update()

    def save_payroll(e=None):
        try:
            payload = _payroll_payload()
            editing_id = payroll_state.get(
                "editing_id"
            )

            if editing_id:
                worker_payroll_service.update_payroll(
                    editing_id,
                    payload,
                )
                payroll_id = int(editing_id)
            else:
                payroll_id = (
                    worker_payroll_service
                    .create_payroll(
                        worker_id,
                        payload,
                    )
                )

            worker_payroll_service.sync_salary_expense(
                payroll_id
            )

            payroll_dialog.open = False
            refresh_payrolls_section()

        except Exception as exc:
            payroll_message.controls = [
                ft.Text(
                    str(exc),
                    color="#B42318",
                    size=12,
                )
            ]
            payroll_message.visible = True
            page.update()

    def open_new_payroll_dialog(e=None):
        clear_payroll_form()

        payroll_dialog.title = ft.Text(
            "Nueva nómina",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )

        payroll_dialog.open = True
        page.update()

    def open_edit_payroll_dialog(payroll):
        load_payroll_form(payroll)

        payroll_dialog.title = ft.Text(
            "Editar nómina",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )

        payroll_dialog.open = True
        page.update()

    payroll_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Nueva nómina",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Container(
            width=920,
            height=690,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Periodo y liquidación",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            payroll_year,
                            payroll_month,
                            payroll_accrual_date,
                            payroll_payment_due_date,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            payroll_liquidation_start,
                            payroll_liquidation_end,
                            payroll_liquidation_days,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Devengos y deducciones",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            payroll_gross,
                            payroll_employee_ss,
                            payroll_irpf,
                            payroll_other_deductions,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            payroll_total_deductions,
                            payroll_net,
                            payroll_employer_ss,
                            payroll_total_cost,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Bases y clasificación",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            payroll_common_base,
                            payroll_accident_base,
                            payroll_irpf_base,
                            payroll_irpf_rate,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            payroll_contract_code,
                            payroll_contribution_group,
                            payroll_professional_group,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(),
                    payroll_document_path,
                    payroll_notes,
                    payroll_message,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton(
                "Cancelar",
                on_click=close_payroll_dialog,
            ),
            primary_button(
                "Guardar nómina",
                save_payroll,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(
            radius=16,
        ),
    )

    page.overlay.append(payroll_dialog)

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
        payrolls = (
            worker_payroll_service
            .list_worker_payrolls(
                worker_id
            )
        )

        gross_total = sum(
            int(
                payroll.get(
                    "gross_salary_centimos"
                )
                or 0
            )
            for payroll in payrolls
        )
        net_total = sum(
            int(
                payroll.get(
                    "net_salary_centimos"
                )
                or 0
            )
            for payroll in payrolls
        )
        employer_ss_total = sum(
            int(
                payroll.get(
                    "employer_social_security_centimos"
                )
                or 0
            )
            for payroll in payrolls
        )
        employer_cost_total = sum(
            int(
                payroll.get(
                    "total_employer_cost_centimos"
                )
                or 0
            )
            for payroll in payrolls
        )

        def summary_item(label, value):
            return ft.Container(
                expand=True,
                padding=12,
                bgcolor="#F8FAFC",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=12,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            label,
                            size=11,
                            color=Q_MUTED,
                        ),
                        ft.Text(
                            value,
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                    ],
                    spacing=2,
                ),
            )

        def amount_item(
            label,
            value,
            *,
            highlight=False,
        ):
            return ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=11,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        _money_from_centimos(
                            value
                        ),
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

        def payroll_card(payroll):
            month = int(
                payroll.get("period_month")
                or 0
            )
            year = int(
                payroll.get("period_year")
                or 0
            )

            month_names = {
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

            expense_created = bool(
                payroll.get(
                    "salary_expense_id"
                )
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
                                            (
                                                f"{month_names.get(month, month)} "
                                                f"{year}"
                                            ),
                                            size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            (
                                                "Devengo: "
                                                f"{_display_date(payroll.get('accrual_date'))}"
                                            ),
                                            size=11,
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
                                            "#15803D"
                                            if expense_created
                                            else "#B45309"
                                        ),
                                    ),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.EDIT_OUTLINED,
                                    tooltip="Editar nómina",
                                    on_click=lambda e: (
                                        open_edit_payroll_dialog(
                                            payroll
                                        )
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
                                amount_item(
                                    "Bruto",
                                    payroll.get(
                                        "gross_salary_centimos"
                                    ),
                                ),
                                amount_item(
                                    "Deducciones",
                                    payroll.get(
                                        "total_deductions_centimos"
                                    ),
                                ),
                                amount_item(
                                    "Líquido",
                                    payroll.get(
                                        "net_salary_centimos"
                                    ),
                                    highlight=True,
                                ),
                                amount_item(
                                    "SS empresa",
                                    payroll.get(
                                        "employer_social_security_centimos"
                                    ),
                                ),
                                amount_item(
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
                                        "IRPF: "
                                        f"{_money_from_centimos(payroll.get('irpf_centimos'))}"
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    (
                                        "SS trabajador: "
                                        f"{_money_from_centimos(payroll.get('employee_social_security_centimos'))}"
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    (
                                        "Días liquidados: "
                                        f"{payroll.get('liquidation_days') or '-'}"
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

        if payrolls:
            body = ft.Column(
                controls=[
                    payroll_card(payroll)
                    for payroll in payrolls
                ],
                spacing=10,
            )
        else:
            body = empty_state(
                "Este trabajador todavía "
                "no tiene nóminas registradas"
            )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Nóminas",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Histórico salarial, "
                                        "deducciones y costes."
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        primary_button(
                            "Nueva nómina",
                            open_new_payroll_dialog,
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Row(
                    controls=[
                        summary_item(
                            "Nóminas",
                            str(len(payrolls)),
                        ),
                        summary_item(
                            "Bruto acumulado",
                            _money_from_centimos(
                                gross_total
                            ),
                        ),
                        summary_item(
                            "Líquido acumulado",
                            _money_from_centimos(
                                net_total
                            ),
                        ),
                        summary_item(
                            "SS empresa",
                            _money_from_centimos(
                                employer_ss_total
                            ),
                        ),
                        summary_item(
                            "Coste total",
                            _money_from_centimos(
                                employer_cost_total
                            ),
                        ),
                    ],
                    spacing=10,
                ),
                body,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
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

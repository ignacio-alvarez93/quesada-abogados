from __future__ import annotations

from datetime import datetime

import flet as ft

from backend.services import worker_service
from frontend.components import (
    detail_section,
    empty_state,
    secondary_button,
    status_badge,
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
        return placeholder_section(
            "Contratos",
            "Histórico contractual",
            (
                "Aquí se registrarán contratos, "
                "jornada, salario y modificaciones."
            ),
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

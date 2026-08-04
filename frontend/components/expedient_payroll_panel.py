"""
Panel visual de nóminas aportadas a un expediente.

Primera fase visual:
- selecciona un PDF;
- ejecuta la extracción multipágina;
- persiste documento y propuestas;
- lista documentos y propuestas existentes.

No permite todavía:
- corregir propuestas;
- confirmarlas o descartarlas;
- aplicar el consolidado al EX02.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from backend.services import (
    expedient_payroll_proposal_service
    as payroll_proposal_service,
)
from backend.services import (
    payroll_file_extraction_service
    as payroll_extraction_service,
)


Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"

STATUS_COLORS = {
    "PENDIENTE_REVISION": {
        "text": "#B54708",
        "background": "#FFFAEB",
        "border": "#FEC84B",
    },
    "CONFIRMADA": {
        "text": "#027A48",
        "background": "#ECFDF3",
        "border": "#6CE9A6",
    },
    "DESCARTADA": {
        "text": "#B42318",
        "background": "#FEF3F2",
        "border": "#FDA29B",
    },
    "APLICADA": {
        "text": "#175CD3",
        "background": "#EFF8FF",
        "border": "#84CAFF",
    },
}


def _money_centimos(value) -> str:
    if value in (None, ""):
        return "No detectado"

    try:
        amount = int(value) / 100
    except (TypeError, ValueError):
        return "No detectado"

    return (
        f"{amount:,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _percentage(value) -> str:
    try:
        return f"{float(value or 0) * 100:.0f} %"
    except (TypeError, ValueError):
        return "0 %"


def _period_label(proposal: dict) -> str:
    year = proposal.get("period_year")
    month = proposal.get("period_month")

    if not year or not month:
        return "Periodo no detectado"

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

    return (
        f"{month_names.get(int(month), str(month))} "
        f"{int(year)}"
    )


def _status_chip(status: str) -> ft.Container:
    normalized = (
        str(status or "PENDIENTE_REVISION")
        .strip()
        .upper()
    )

    style = STATUS_COLORS.get(
        normalized,
        STATUS_COLORS["PENDIENTE_REVISION"],
    )

    label = normalized.replace("_", " ")

    return ft.Container(
        content=ft.Text(
            label,
            size=10,
            weight=ft.FontWeight.BOLD,
            color=style["text"],
        ),
        bgcolor=style["background"],
        border=ft.Border.all(
            1,
            style["border"],
        ),
        border_radius=999,
        padding=ft.Padding.symmetric(
            horizontal=9,
            vertical=4,
        ),
    )


def _info_value(
    label: str,
    value,
    *,
    width: int = 180,
) -> ft.Container:
    return ft.Container(
        width=width,
        content=ft.Column(
            controls=[
                ft.Text(
                    label,
                    size=10,
                    color=Q_MUTED,
                ),
                ft.Text(
                    str(value or "-"),
                    size=12,
                    color=Q_PRIMARY_DARK,
                    weight=ft.FontWeight.W_600,
                    selectable=True,
                ),
            ],
            spacing=2,
            tight=True,
        ),
    )


def _proposal_card(
    proposal: dict,
) -> ft.Container:
    warnings = list(
        proposal.get("warnings")
        or []
    )

    pages = (
        proposal.get("source_pages")
        or []
    )
    pages_label = (
        ", ".join(str(page) for page in pages)
        if pages
        else "-"
    )

    controls = [
        ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            _period_label(proposal),
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                f"Propuesta "
                                f"#{proposal.get('sequence') or '-'}"
                            ),
                            size=10,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=1,
                    tight=True,
                    expand=True,
                ),
                _status_chip(
                    proposal.get("review_status")
                ),
            ],
            spacing=10,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
        ft.Row(
            controls=[
                _info_value(
                    "Trabajador",
                    proposal.get("employee_name")
                    or "No detectado",
                    width=230,
                ),
                _info_value(
                    "Empresa",
                    proposal.get("company_name")
                    or "No detectada",
                    width=230,
                ),
                _info_value(
                    "Líquido",
                    _money_centimos(
                        proposal.get(
                            "net_pay_centimos"
                        )
                    ),
                    width=140,
                ),
                _info_value(
                    "Confianza",
                    _percentage(
                        proposal.get("confidence")
                    ),
                    width=105,
                ),
                _info_value(
                    "Páginas",
                    pages_label,
                    width=90,
                ),
            ],
            spacing=10,
            wrap=True,
        ),
    ]

    if warnings:
        controls.append(
            ft.Container(
                bgcolor="#FFFAEB",
                border=ft.Border.all(
                    1,
                    "#FEC84B",
                ),
                border_radius=8,
                padding=8,
                content=ft.Text(
                    " · ".join(
                        str(item)
                        for item in warnings
                    ),
                    size=10,
                    color="#92400E",
                    selectable=True,
                ),
            )
        )

    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.Border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        padding=12,
        content=ft.Column(
            controls=controls,
            spacing=9,
        ),
    )


def _document_card(
    document: dict,
) -> ft.Container:
    proposals = list(
        document.get("proposals")
        or []
    )

    warning_count = len(
        document.get("warnings")
        or []
    )

    document_status = (
        document.get("extraction_status")
        or "PENDIENTE_REVISION"
    )

    return ft.Container(
        bgcolor="#F8FAFC",
        border=ft.Border.all(
            1,
            Q_BORDER,
        ),
        border_radius=14,
        padding=12,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.PICTURE_AS_PDF,
                            color="#B42318",
                            size=22,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    (
                                        document.get(
                                            "source_name"
                                        )
                                        or "PDF de nóminas"
                                    ),
                                    size=14,
                                    weight=(
                                        ft.FontWeight.BOLD
                                    ),
                                    color=Q_PRIMARY_DARK,
                                    selectable=True,
                                ),
                                ft.Text(
                                    (
                                        f"{document.get('page_count') or 0} "
                                        "página(s) · "
                                        f"{len(proposals)} "
                                        "nómina(s) detectada(s)"
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        _status_chip(document_status),
                    ],
                    spacing=10,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                (
                    ft.Container(
                        bgcolor="#FFFAEB",
                        border=ft.Border.all(
                            1,
                            "#FEC84B",
                        ),
                        border_radius=8,
                        padding=8,
                        content=ft.Text(
                            (
                                f"{warning_count} advertencia(s) "
                                "en la extracción"
                            ),
                            size=10,
                            color="#92400E",
                        ),
                    )
                    if warning_count
                    else ft.Container(
                        visible=False
                    )
                ),
                (
                    ft.Column(
                        controls=[
                            _proposal_card(proposal)
                            for proposal in proposals
                        ],
                        spacing=8,
                    )
                    if proposals
                    else ft.Container(
                        padding=12,
                        content=ft.Text(
                            (
                                "No se detectaron nóminas "
                                "clasificables en este PDF."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    )
                ),
            ],
            spacing=10,
        ),
    )


def _load_documents(
    expediente_id: int,
    *,
    db_path: str | Path | None = None,
) -> list[dict]:
    list_kwargs = {}

    if db_path is not None:
        list_kwargs["db_path"] = db_path

    documents = (
        payroll_proposal_service
        .list_expedient_documents(
            int(expediente_id),
            **list_kwargs,
        )
    )

    result = []

    for item in documents:
        document = dict(item)

        document["proposals"] = (
            payroll_proposal_service
            .list_document_proposals(
                int(document["id"]),
                **list_kwargs,
            )
        )

        result.append(document)

    return result


def build_expedient_payroll_panel(
    page: ft.Page,
    expediente_id: int,
    *,
    on_refresh: Callable[[], None] | None = None,
    db_path: str | Path | None = None,
) -> ft.Control:
    """
    Construye el panel de carga y listado de nóminas.
    """

    expediente_id = int(expediente_id)

    try:
        documents = _load_documents(
            expediente_id,
            db_path=db_path,
        )
        load_error = ""
    except Exception as exc:
        documents = []
        load_error = str(exc)

    async def select_payroll_pdf(e=None):
        try:
            files = await ft.FilePicker().pick_files(
                dialog_title=(
                    "Seleccionar PDF de nóminas"
                ),
                allow_multiple=False,
                file_type=(
                    ft.FilePickerFileType.CUSTOM
                ),
                allowed_extensions=["pdf"],
            )

            if not files:
                return

            selected = files[0]

            file_path = (
                getattr(selected, "path", None)
                or ""
            )

            if not file_path:
                raise ValueError(
                    "El PDF seleccionado no dispone "
                    "de una ruta local"
                )

            bundle = (
                payroll_extraction_service
                .extract_payroll_bundle(
                    Path(file_path)
                )
            )

            persist_kwargs = {}

            if db_path is not None:
                persist_kwargs["db_path"] = db_path

            persisted = (
                payroll_proposal_service
                .persist_payroll_bundle(
                    expediente_id,
                    bundle,
                    **persist_kwargs,
                )
            )

            payroll_count = len(
                persisted.get("proposals")
                or []
            )

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    (
                        "PDF procesado: "
                        f"{payroll_count} nómina(s) "
                        "registrada(s)"
                    )
                ),
                open=True,
            )

            if on_refresh:
                on_refresh()
            else:
                page.update()

        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"No se pudo procesar el PDF: {exc}"
                ),
                open=True,
            )
            page.update()

    header = ft.Row(
        controls=[
            ft.Container(
                width=42,
                height=42,
                border_radius=21,
                bgcolor="#EAF3FF",
                alignment=ft.alignment.Alignment(
                    0,
                    0,
                ),
                content=ft.Icon(
                    ft.Icons.RECEIPT_LONG,
                    color=Q_PRIMARY,
                    size=22,
                ),
            ),
            ft.Column(
                controls=[
                    ft.Text(
                        "Nóminas aportadas",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        (
                            "Extrae y registra varias "
                            "mensualidades desde un único PDF."
                        ),
                        size=11,
                        color=Q_MUTED,
                    ),
                ],
                spacing=2,
                expand=True,
            ),
            ft.FilledButton(
                content=ft.Text(
                    "Seleccionar PDF"
                ),
                icon=ft.Icons.UPLOAD_FILE,
                on_click=select_payroll_pdf,
            ),
        ],
        spacing=10,
        wrap=True,
        vertical_alignment=(
            ft.CrossAxisAlignment.CENTER
        ),
    )

    body_controls = [header]

    if load_error:
        body_controls.append(
            ft.Container(
                bgcolor="#FEF3F2",
                border=ft.Border.all(
                    1,
                    "#FDA29B",
                ),
                border_radius=10,
                padding=10,
                content=ft.Text(
                    (
                        "No se pudieron cargar las "
                        f"nóminas: {load_error}"
                    ),
                    size=11,
                    color="#B42318",
                ),
            )
        )
    elif not documents:
        body_controls.append(
            ft.Container(
                bgcolor="#FFFFFF",
                border=ft.Border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=12,
                padding=18,
                alignment=ft.alignment.Alignment(
                    0,
                    0,
                ),
                content=ft.Column(
                    controls=[
                        ft.Icon(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            color=Q_MUTED,
                            size=30,
                        ),
                        ft.Text(
                            (
                                "Todavía no hay PDFs de "
                                "nóminas registrados"
                            ),
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                    spacing=6,
                ),
            )
        )
    else:
        body_controls.append(
            ft.Column(
                controls=[
                    _document_card(document)
                    for document in documents
                ],
                spacing=10,
            )
        )

    return ft.Container(
        bgcolor="#F8FAFC",
        border=ft.Border.all(
            1,
            Q_BORDER,
        ),
        border_radius=14,
        padding=14,
        content=ft.Column(
            controls=body_controls,
            spacing=12,
        ),
    )

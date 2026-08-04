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
from backend.services import (
    expedient_payroll_review_service
    as payroll_review_service,
)
from backend.services import (
    expedient_payroll_application_service
    as payroll_application_service,
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
    *,
    on_confirm=None,
    on_discard=None,
    on_reopen=None,
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

    status = str(
        proposal.get("review_status")
        or "PENDIENTE_REVISION"
    ).strip().upper()

    proposal_id = int(
        proposal.get("id")
        or 0
    )

    actions = []

    if (
        status == "PENDIENTE_REVISION"
        and proposal_id
    ):
        actions.extend(
            [
                ft.OutlinedButton(
                    content=ft.Text(
                        "Confirmar"
                    ),
                    icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                    on_click=(
                        lambda e, value=proposal_id:
                        on_confirm(value)
                    ),
                ),
                ft.TextButton(
                    content=ft.Text(
                        "Descartar"
                    ),
                    icon=ft.Icons.BLOCK,
                    on_click=(
                        lambda e, value=proposal_id:
                        on_discard(value)
                    ),
                ),
            ]
        )

    elif (
        status
        in {
            "CONFIRMADA",
            "DESCARTADA",
        }
        and proposal_id
    ):
        actions.append(
            ft.TextButton(
                content=ft.Text(
                    "Reabrir"
                ),
                icon=ft.Icons.REPLAY,
                on_click=(
                    lambda e, value=proposal_id:
                    on_reopen(value)
                ),
            )
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
                _status_chip(status),
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

    if actions:
        controls.append(
            ft.Row(
                controls=actions,
                spacing=8,
                wrap=True,
                alignment=(
                    ft.MainAxisAlignment.END
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
    *,
    on_delete=None,
    on_confirm=None,
    on_discard=None,
    on_reopen=None,
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

    document_id = int(
        document.get("id")
        or 0
    )

    header_actions = []

    if document_id and on_delete:
        header_actions.append(
            ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                tooltip="Eliminar registro de nóminas",
                icon_color="#B42318",
                on_click=(
                    lambda e, value=document_id:
                    on_delete(value)
                ),
            )
        )

    header_controls = [
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
                    weight=ft.FontWeight.BOLD,
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
    ]

    header_controls.extend(
        header_actions
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
                    controls=header_controls,
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
                            _proposal_card(
                                proposal,
                                on_confirm=on_confirm,
                                on_discard=on_discard,
                                on_reopen=on_reopen,
                            )
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

    proposals = (
        payroll_review_service
        .list_expedient_proposals(
            int(expediente_id),
            **list_kwargs,
        )
    )

    proposals_by_document = {}

    for proposal in proposals:
        document_id = int(
            proposal.get("document_id")
            or 0
        )

        proposals_by_document.setdefault(
            document_id,
            [],
        ).append(proposal)

    result = []

    for item in documents:
        document = dict(item)

        document_id = int(
            document.get("id")
            or 0
        )

        document["proposals"] = (
            proposals_by_document.get(
                document_id,
                [],
            )
        )

        result.append(document)

    return result


def build_expedient_payroll_panel(
    page: ft.Page,
    expediente_id: int,
    *,
    formulario_id: int | None = None,
    on_refresh: Callable[[], None] | None = None,
    on_average_applied: (
        Callable[[int], None] | None
    ) = None,
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

    consolidation_kwargs = {}

    if db_path is not None:
        consolidation_kwargs["db_path"] = (
            db_path
        )

    try:
        consolidation = (
            payroll_review_service
            .consolidate_expedient_payrolls(
                expediente_id,
                **consolidation_kwargs,
            )
        )
        consolidation_error = ""
    except Exception as exc:
        consolidation = {}
        consolidation_error = str(exc)

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

    def show_message(message, *, error=False):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(
                str(message or "")
            ),
            open=True,
        )
        page.update()

    def refresh_panel():
        if on_refresh:
            on_refresh()
        else:
            page.update()

    def confirm_proposal(proposal_id):
        try:
            kwargs = {}
            if db_path is not None:
                kwargs["db_path"] = db_path

            payroll_review_service.confirm_proposal(
                int(proposal_id),
                **kwargs,
            )

            show_message(
                "Nómina confirmada"
            )
            refresh_panel()

        except Exception as exc:
            show_message(
                f"No se pudo confirmar: {exc}",
                error=True,
            )

    def discard_proposal(proposal_id):
        try:
            kwargs = {}
            if db_path is not None:
                kwargs["db_path"] = db_path

            payroll_review_service.discard_proposal(
                int(proposal_id),
                **kwargs,
            )

            show_message(
                "Nómina descartada"
            )
            refresh_panel()

        except Exception as exc:
            show_message(
                f"No se pudo descartar: {exc}",
                error=True,
            )

    def reopen_proposal(proposal_id):
        try:
            kwargs = {}
            if db_path is not None:
                kwargs["db_path"] = db_path

            payroll_review_service.reopen_proposal(
                int(proposal_id),
                **kwargs,
            )

            show_message(
                "Nómina reabierta para revisión"
            )
            refresh_panel()

        except Exception as exc:
            show_message(
                f"No se pudo reabrir: {exc}",
                error=True,
            )

    def apply_payroll_average(e=None):
        try:
            if not formulario_id:
                raise ValueError(
                    "No se ha identificado el "
                    "formulario EX02"
                )

            suggested = consolidation.get(
                "suggested_monthly_"
                "income_centimos"
            )

            if suggested is None:
                reasons = consolidation.get(
                    "blocking_reasons"
                ) or []

                raise ValueError(
                    "El consolidado no está listo: "
                    + (
                        " ".join(
                            str(item)
                            for item in reasons
                        )
                        or
                        "revisa las nóminas"
                    )
                )

            kwargs = {}

            if db_path is not None:
                kwargs["db_path"] = db_path

            result = (
                payroll_application_service
                .apply_payroll_consolidation_to_expedient(
                    expediente_id,
                    int(formulario_id),
                    expected_amount_centimos=(
                        int(suggested)
                    ),
                    **kwargs,
                )
            )

            diagnosis = (
                result.get("consolidation")
                or {}
            ).get("diagnosis") or {}

            show_message(
                (
                    "Promedio aplicado al EX02: "
                    f"{_money_centimos(suggested)}. "
                    "Diagnóstico: "
                    f"{diagnosis.get('estado') or '-'}"
                )
            )

            if on_average_applied:
                on_average_applied(
                    int(suggested)
                )
            else:
                refresh_panel()

        except Exception as exc:
            show_message(
                (
                    "No se pudo aplicar el promedio: "
                    f"{exc}"
                ),
                error=True,
            )

    def request_delete_document(document_id):
        document = next(
            (
                item
                for item in documents
                if int(item.get("id") or 0)
                == int(document_id)
            ),
            {},
        )

        source_name = (
            document.get("source_name")
            or "PDF de nóminas"
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Eliminar registro de nóminas"
            ),
            content=ft.Text(
                (
                    f"Se eliminará {source_name} "
                    "del expediente y también sus "
                    "propuestas extraídas. "
                    "El archivo físico no se borrará."
                )
            ),
        )

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        def confirm_delete(e=None):
            try:
                kwargs = {}
                if db_path is not None:
                    kwargs["db_path"] = db_path

                result = (
                    payroll_proposal_service
                    .delete_payroll_document(
                        int(document_id),
                        **kwargs,
                    )
                )

                dialog.open = False
                page.update()

                show_message(
                    (
                        "PDF eliminado del CRM: "
                        f"{result.get('deleted_proposal_count') or 0} "
                        "propuesta(s) eliminada(s)"
                    )
                )

                refresh_panel()

            except Exception as exc:
                dialog.open = False
                page.update()

                show_message(
                    f"No se pudo eliminar el PDF: {exc}",
                    error=True,
                )

        dialog.actions = [
            ft.TextButton(
                content=ft.Text(
                    "Cancelar"
                ),
                on_click=close_dialog,
            ),
            ft.TextButton(
                content=ft.Text(
                    "Eliminar registro"
                ),
                on_click=confirm_delete,
            ),
        ]

        if dialog not in page.overlay:
            page.overlay.append(dialog)

        dialog.open = True
        page.update()

    header_text = ft.Column(
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
        tight=True,
    )

    select_button = ft.FilledButton(
        content=ft.Text(
            "Seleccionar PDF"
        ),
        icon=ft.Icons.UPLOAD_FILE,
        on_click=select_payroll_pdf,
    )

    header = ft.Column(
        controls=[
            ft.Row(
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
                    ft.Container(
                        content=header_text,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
            ft.Row(
                controls=[
                    select_button,
                ],
                alignment=ft.MainAxisAlignment.END,
            ),
        ],
        spacing=10,
    )

    confirmed_count = int(
        consolidation.get(
            "confirmed_payroll_count"
        )
        or 0
    )

    pending_count = int(
        consolidation.get(
            "pending_review_count"
        )
        or 0
    )

    average_centimos = consolidation.get(
        "average_net_centimos"
    )

    ready_for_application = bool(
        consolidation.get(
            "ready_for_application"
        )
    )

    active_application = None

    if formulario_id:
        try:
            application_kwargs = {}

            if db_path is not None:
                application_kwargs["db_path"] = (
                    db_path
                )

            active_application = (
                payroll_application_service
                .get_active_application(
                    expediente_id,
                    int(formulario_id),
                    **application_kwargs,
                )
            )
        except Exception:
            active_application = None

    consolidation_controls = [
        ft.Row(
            controls=[
                _info_value(
                    "Confirmadas",
                    confirmed_count,
                    width=120,
                ),
                _info_value(
                    "Pendientes",
                    pending_count,
                    width=120,
                ),
                _info_value(
                    "Promedio mensual",
                    _money_centimos(
                        average_centimos
                    ),
                    width=180,
                ),
            ],
            spacing=12,
            wrap=True,
        )
    ]

    if consolidation_error:
        consolidation_controls.append(
            ft.Text(
                (
                    "No se pudo calcular el "
                    f"consolidado: {consolidation_error}"
                ),
                size=11,
                color="#B42318",
            )
        )

    elif active_application:
        consolidation_controls.append(
            ft.Container(
                bgcolor="#ECFDF3",
                border=ft.Border.all(
                    1,
                    "#6CE9A6",
                ),
                border_radius=8,
                padding=10,
                content=ft.Text(
                    (
                        "Promedio aplicado al EX02: "
                        + _money_centimos(
                            active_application.get(
                                "applied_value_centimos"
                            )
                        )
                    ),
                    size=11,
                    color="#027A48",
                    weight=ft.FontWeight.BOLD,
                ),
            )
        )

    else:
        blocking_reasons = (
            consolidation.get(
                "blocking_reasons"
            )
            or []
        )

        if blocking_reasons:
            consolidation_controls.append(
                ft.Text(
                    " ".join(
                        str(item)
                        for item
                        in blocking_reasons
                    ),
                    size=11,
                    color="#92400E",
                )
            )

        consolidation_controls.append(
            ft.FilledButton(
                content=ft.Text(
                    "Aplicar promedio al diagnóstico"
                ),
                icon=ft.Icons.CALCULATE_OUTLINED,
                on_click=apply_payroll_average,
                disabled=(
                    not ready_for_application
                    or not formulario_id
                ),
            )
        )

    consolidation_panel = ft.Container(
        bgcolor="#FFFFFF",
        border=ft.Border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        padding=12,
        content=ft.Column(
            controls=consolidation_controls,
            spacing=10,
        ),
    )

    body_controls = [
        header,
        consolidation_panel,
    ]

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
                    _document_card(
                        document,
                        on_delete=(
                            request_delete_document
                        ),
                        on_confirm=(
                            confirm_proposal
                        ),
                        on_discard=(
                            discard_proposal
                        ),
                        on_reopen=(
                            reopen_proposal
                        ),
                    )
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

from __future__ import annotations

import flet as ft

from backend.services import supplier_service
from frontend.components import (
    detail_section,
    empty_state,
    secondary_button,
    status_badge,
)


Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"


SUPPLIER_TYPE_LABELS = {
    "COMPANY": "Empresa",
    "SELF_EMPLOYED": "Autónomo",
    "INDIVIDUAL": "Persona física",
    "PUBLIC_BODY": "Organismo público",
    "PROFESSIONAL_ASSOCIATION": "Colegio profesional",
    "MUTUALITY": "Mutualidad",
    "FINANCIAL_ENTITY": "Entidad financiera",
    "LANDLORD": "Arrendador",
    "SOFTWARE_PROVIDER": "Software / SaaS",
    "TELECOMMUNICATIONS": "Telecomunicaciones",
    "OTHER": "Otro",
}


DOCUMENT_TYPE_LABELS = {
    "INVOICE": "Factura",
    "RECEIPT": "Recibo",
    "SUBSCRIPTION_RECEIPT": "Recibo de suscripción",
    "PROFESSIONAL_FEE": "Cuota profesional",
    "INSURANCE_RECEIPT": "Recibo de seguro",
    "RENT_INVOICE": "Factura de alquiler",
    "BANK_STATEMENT": "Extracto bancario",
    "OTHER_SUPPORTING_DOCUMENT": "Otro justificante",
}


def _yes_no(value):
    return "Sí" if bool(value) else "No"


def _percentage(value):
    try:
        return f"{float(value or 0):.2f} %"
    except Exception:
        return "0,00 %"


def supplier_detail_view(
    page: ft.Page,
    supplier_id: int,
    *,
    on_back=None,
    on_edit=None,
):
    supplier = supplier_service.get_supplier(
        supplier_id
    )

    if not supplier:
        return empty_state(
            "No se ha encontrado el proveedor"
        )

    title = (
        supplier.get("legal_name")
        or f"Proveedor #{supplier_id}"
    )

    trade_name = str(
        supplier.get("trade_name") or ""
    ).strip()

    badges = [
        status_badge(
            "Activo"
            if supplier.get("active")
            else "Inactivo"
        )
    ]

    if supplier.get("preferred"):
        badges.append(
            status_badge("Preferente")
        )

    if supplier.get("recurring"):
        badges.append(
            status_badge("Recurrente")
        )

    header = ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=16,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    title,
                                    size=25,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        trade_name
                                        or supplier.get(
                                            "supplier_code"
                                        )
                                        or ""
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Row(
                            controls=badges,
                            spacing=8,
                            wrap=True,
                            tight=True,
                        ),
                    ],
                    spacing=12,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Text(
                    supplier.get(
                        "services_description"
                    )
                    or "Sin descripción de servicios",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            spacing=8,
        ),
    )

    actions = []

    if on_back:
        actions.append(
            secondary_button(
                "Volver",
                on_back,
            )
        )

    if on_edit:
        actions.append(
            ft.ElevatedButton(
                "Editar proveedor",
                icon=ft.Icons.EDIT_OUTLINED,
                on_click=lambda e: on_edit(
                    supplier
                ),
            )
        )

    return ft.Container(
        expand=True,
        bgcolor="#FFFFFF",
        padding=20,
        alignment=ft.Alignment(0, -1),
        content=ft.Column(
            controls=[
            ft.Row(
                controls=actions,
                spacing=8,
                alignment=ft.MainAxisAlignment.END,
            ),
            header,
            detail_section(
                "Identificación",
                [
                    (
                        "Código CRM",
                        supplier.get(
                            "supplier_code"
                        ),
                    ),
                    (
                        "Tipo",
                        SUPPLIER_TYPE_LABELS.get(
                            supplier.get(
                                "supplier_type"
                            ),
                            supplier.get(
                                "supplier_type"
                            ),
                        ),
                    ),
                    (
                        "Tipo de entidad",
                        supplier.get(
                            "entity_type"
                        ),
                    ),
                    (
                        "Razón social / nombre",
                        supplier.get(
                            "legal_name"
                        ),
                    ),
                    (
                        "Nombre comercial",
                        supplier.get(
                            "trade_name"
                        ),
                    ),
                    (
                        "Documento",
                        " ".join(
                            part
                            for part in [
                                supplier.get(
                                    "document_type"
                                ),
                                supplier.get(
                                    "tax_id"
                                ),
                            ]
                            if part
                        ),
                    ),
                    (
                        "Categoría",
                        supplier.get(
                            "category"
                        ),
                    ),
                    (
                        "Subcategoría",
                        supplier.get(
                            "subcategory"
                        ),
                    ),
                ],
            ),
            detail_section(
                "Contacto",
                [
                    (
                        "Teléfono",
                        supplier.get("phone"),
                    ),
                    (
                        "Teléfono secundario",
                        supplier.get(
                            "secondary_phone"
                        ),
                    ),
                    (
                        "Email",
                        supplier.get("email"),
                    ),
                    (
                        "Web",
                        supplier.get("website"),
                    ),
                    (
                        "Persona de contacto",
                        supplier.get(
                            "contact_person"
                        ),
                    ),
                    (
                        "Cargo",
                        supplier.get(
                            "contact_position"
                        ),
                    ),
                ],
            ),
            detail_section(
                "Domicilio",
                [
                    (
                        "Dirección",
                        supplier.get("address"),
                    ),
                    (
                        "Código postal",
                        supplier.get(
                            "postal_code"
                        ),
                    ),
                    (
                        "Localidad",
                        supplier.get("city"),
                    ),
                    (
                        "Provincia",
                        supplier.get(
                            "province"
                        ),
                    ),
                    (
                        "País",
                        supplier.get("country"),
                    ),
                ],
            ),
            detail_section(
                "Condiciones habituales",
                [
                    (
                        "Forma de pago",
                        supplier.get(
                            "usual_payment_method"
                        ),
                    ),
                    (
                        "Vencimiento",
                        (
                            f"{supplier.get('payment_terms_days')} días"
                            if supplier.get(
                                "payment_terms_days"
                            )
                            else "Sin plazo definido"
                        ),
                    ),
                    (
                        "IBAN",
                        supplier.get("iban"),
                    ),
                    (
                        "IVA habitual",
                        _percentage(
                            supplier.get(
                                "usual_vat_rate"
                            )
                        ),
                    ),
                    (
                        "IRPF habitual",
                        _percentage(
                            supplier.get(
                                "usual_irpf_rate"
                            )
                        ),
                    ),
                    (
                        "Emite factura",
                        _yes_no(
                            supplier.get(
                                "issues_invoice"
                            )
                        ),
                    ),
                    (
                        "Justificante habitual",
                        DOCUMENT_TYPE_LABELS.get(
                            supplier.get(
                                "usual_document_type"
                            ),
                            supplier.get(
                                "usual_document_type"
                            ),
                        ),
                    ),
                ],
            ),
            detail_section(
                "Contratos y referencias",
                [
                    (
                        "Código cliente",
                        supplier.get(
                            "customer_reference"
                        ),
                    ),
                    (
                        "Contrato",
                        supplier.get(
                            "contract_reference"
                        ),
                    ),
                    (
                        "Referencia externa",
                        supplier.get(
                            "external_reference"
                        ),
                    ),
                    (
                        "Proveedor recurrente",
                        _yes_no(
                            supplier.get(
                                "recurring"
                            )
                        ),
                    ),
                    (
                        "Proveedor preferente",
                        _yes_no(
                            supplier.get(
                                "preferred"
                            )
                        ),
                    ),
                ],
            ),
            detail_section(
                "Observaciones",
                [
                    (
                        "Servicios",
                        supplier.get(
                            "services_description"
                        ),
                    ),
                    (
                        "Notas internas",
                        supplier.get("notes"),
                    ),
                ],
            ),
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

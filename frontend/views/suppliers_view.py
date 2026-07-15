from __future__ import annotations

import flet as ft

from backend.services import supplier_service
from frontend.components import (
    empty_state,
    metric_card,
    primary_button,
    secondary_button,
    status_badge,
)
from frontend.components.listing import (
    card_item,
    compact_pagination_bar,
)
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.views.supplier_detail_view import (
    supplier_detail_view,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"
Q_BG = "#F4F7FB"
Q_SUCCESS = "#027A48"
Q_DANGER = "#B42318"


SUPPLIER_TYPES = [
    ("ALL", "Todos los tipos"),
    ("COMPANY", "Empresa"),
    ("SELF_EMPLOYED", "Autónomo"),
    ("INDIVIDUAL", "Persona física"),
    ("PUBLIC_BODY", "Organismo público"),
    (
        "PROFESSIONAL_ASSOCIATION",
        "Colegio profesional",
    ),
    ("MUTUALITY", "Mutualidad"),
    ("FINANCIAL_ENTITY", "Entidad financiera"),
    ("LANDLORD", "Arrendador"),
    ("SOFTWARE_PROVIDER", "Software / SaaS"),
    (
        "TELECOMMUNICATIONS",
        "Telecomunicaciones",
    ),
    ("OTHER", "Otro"),
]


ENTITY_TYPES = [
    ("COMPANY", "Empresa / sociedad"),
    ("SELF_EMPLOYED", "Autónomo"),
    ("INDIVIDUAL", "Persona física"),
    ("PUBLIC_BODY", "Organismo / entidad"),
    ("OTHER", "Otro"),
]


DOCUMENT_TYPES = [
    ("", "Sin indicar"),
    ("CIF", "CIF"),
    ("NIF", "NIF"),
    ("DNI", "DNI"),
    ("NIE", "NIE"),
    ("VAT", "VAT intracomunitario"),
    ("OTHER", "Otro"),
]


DOCUMENT_KINDS = [
    ("INVOICE", "Factura"),
    ("RECEIPT", "Recibo"),
    (
        "SUBSCRIPTION_RECEIPT",
        "Recibo de suscripción",
    ),
    (
        "PROFESSIONAL_FEE",
        "Cuota profesional",
    ),
    (
        "INSURANCE_RECEIPT",
        "Recibo de seguro",
    ),
    ("RENT_INVOICE", "Factura de alquiler"),
    ("BANK_STATEMENT", "Extracto bancario"),
    (
        "OTHER_SUPPORTING_DOCUMENT",
        "Otro justificante",
    ),
]


CATEGORIES = [
    "Arrendamientos",
    "Asesoría y servicios profesionales",
    "Comisiones bancarias y TPV",
    "Cuotas colegiales",
    "Mantenimiento de equipos",
    "Material de oficina e imprenta",
    "Mutualidad y previsión",
    "Notaría y registros",
    "Publicidad y marketing",
    "Seguros",
    "Software y suscripciones",
    "Suministros",
    "Telefonía fija e internet",
    "Telefonía móvil",
    "Traducciones",
    "Otros servicios",
]


TYPE_LABELS = dict(SUPPLIER_TYPES)

STATUS_FILTER_LABEL_TO_KEY = {
    "Todos": "ALL",
    "Activos": "ACTIVE",
    "Inactivos": "INACTIVE",
}

STATUS_FILTER_KEY_TO_LABEL = {
    value: key
    for key, value in STATUS_FILTER_LABEL_TO_KEY.items()
}

TYPE_FILTER_LABEL_TO_KEY = {
    label: key
    for key, label in SUPPLIER_TYPES
}

TYPE_FILTER_KEY_TO_LABEL = {
    value: key
    for key, value in TYPE_FILTER_LABEL_TO_KEY.items()
}

CATEGORY_FILTER_LABEL_TO_KEY = {
    "Todas": "ALL",
    **{
        category: category
        for category in CATEGORIES
    },
}

CATEGORY_FILTER_KEY_TO_LABEL = {
    value: key
    for key, value in CATEGORY_FILTER_LABEL_TO_KEY.items()
}


def _text_field(
    label,
    *,
    width=260,
    multiline=False,
):
    return ft.TextField(
        label=label,
        width=width,
        multiline=multiline,
        min_lines=3 if multiline else 1,
        max_lines=5 if multiline else 1,
        border_radius=10,
        dense=True,
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


def suppliers_view(page: ft.Page):
    supplier_service.ensure_schema()

    state = {
        "suppliers": [],
        "page": 1,
        "page_size": 12,
        "search": "",
        "status": "ACTIVE",
        "type": "ALL",
        "category": "ALL",
        "preferred_only": False,
        "editing_id": None,
    }

    root = ft.Container(
        expand=True,
        padding=0,
        bgcolor="#FFFFFF",
    )

    results_box = ft.Container(
        alignment=ft.Alignment(0, -1),
    )

    search_input = ft.TextField(
        label="Buscar proveedor",
        hint_text=(
            "Nombre, NIF, servicio, categoría, "
            "teléfono, contrato..."
        ),
        width=460,
        dense=True,
        prefix_icon=ft.Icons.SEARCH,
        border_radius=10,
    )

    def on_status_filter_selected(value):
        selected = STATUS_FILTER_LABEL_TO_KEY.get(
            str(value or "").strip()
        )
        if selected is None:
            return

        state["status"] = selected
        state["page"] = 1
        load_suppliers()

    def on_type_filter_selected(value):
        selected = TYPE_FILTER_LABEL_TO_KEY.get(
            str(value or "").strip()
        )
        if selected is None:
            return

        state["type"] = selected
        state["page"] = 1
        load_suppliers()

    def on_category_filter_selected(value):
        selected = CATEGORY_FILTER_LABEL_TO_KEY.get(
            str(value or "").strip()
        )
        if selected is None:
            return

        state["category"] = selected
        state["page"] = 1
        load_suppliers()

    status_filter = AppAutocomplete(
        page=page,
        label="Estado",
        options=list(STATUS_FILTER_LABEL_TO_KEY.keys()),
        value="Activos",
        width=165,
        max_results=5,
        on_select=on_status_filter_selected,
        allow_free_text=False,
        show_empty=False,
    )

    type_filter = AppAutocomplete(
        page=page,
        label="Tipo",
        options=list(TYPE_FILTER_LABEL_TO_KEY.keys()),
        value="Todos los tipos",
        width=225,
        max_results=8,
        on_select=on_type_filter_selected,
        allow_free_text=False,
        show_empty=False,
    )

    category_filter = AppAutocomplete(
        page=page,
        label="Categoría",
        options=list(CATEGORY_FILTER_LABEL_TO_KEY.keys()),
        value="Todas",
        width=285,
        max_results=8,
        on_select=on_category_filter_selected,
        allow_free_text=False,
        show_empty=False,
    )

    preferred_checkbox = ft.Checkbox(
        label="Solo preferentes",
        value=False,
    )

    legal_name = _text_field(
        "Razón social / nombre *",
        width=390,
    )
    trade_name = _text_field(
        "Nombre comercial",
        width=310,
    )
    entity_type = _dropdown(
        "Tipo de entidad",
        ENTITY_TYPES,
        width=220,
        value="COMPANY",
    )
    supplier_type = _dropdown(
        "Tipo de proveedor",
        SUPPLIER_TYPES[1:],
        width=265,
        value="OTHER",
    )
    document_type = _dropdown(
        "Tipo documento",
        DOCUMENT_TYPES,
        width=180,
        value="",
    )
    tax_id = _text_field(
        "NIF / CIF / VAT",
        width=230,
    )

    first_name = _text_field(
        "Nombre",
        width=220,
    )
    last_name_1 = _text_field(
        "Primer apellido",
        width=220,
    )
    last_name_2 = _text_field(
        "Segundo apellido",
        width=220,
    )

    category = _dropdown(
        "Categoría",
        [
            ("", "Sin categoría"),
            *[
                (value, value)
                for value in CATEGORIES
            ],
        ],
        width=310,
        value="",
    )
    subcategory = _text_field(
        "Subcategoría",
        width=280,
    )
    services_description = _text_field(
        "Servicios prestados",
        width=730,
        multiline=True,
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
        "Email",
        width=300,
    )
    website = _text_field(
        "Página web",
        width=300,
    )
    contact_person = _text_field(
        "Persona de contacto",
        width=270,
    )
    contact_position = _text_field(
        "Cargo",
        width=240,
    )

    address = _text_field(
        "Dirección",
        width=600,
    )
    postal_code = _text_field(
        "Código postal",
        width=150,
    )
    city = _text_field(
        "Localidad",
        width=250,
    )
    province = _text_field(
        "Provincia",
        width=250,
    )
    country = _text_field(
        "País",
        width=220,
    )
    country.value = "España"

    payment_method = _dropdown(
        "Forma de pago habitual",
        [
            ("", "Sin indicar"),
            ("DIRECT_DEBIT", "Domiciliación"),
            ("BANK_TRANSFER", "Transferencia"),
            ("CARD", "Tarjeta"),
            ("CASH", "Efectivo"),
            ("OTHER", "Otra"),
        ],
        width=260,
        value="",
    )
    payment_terms_days = _text_field(
        "Vencimiento en días",
        width=175,
    )
    payment_terms_days.value = "0"
    iban = _text_field(
        "IBAN",
        width=390,
    )
    vat_rate = _text_field(
        "IVA habitual %",
        width=160,
    )
    vat_rate.value = "21"
    irpf_rate = _text_field(
        "IRPF habitual %",
        width=160,
    )
    irpf_rate.value = "0"

    usual_document_type = _dropdown(
        "Justificante habitual",
        DOCUMENT_KINDS,
        width=310,
        value="INVOICE",
    )

    issues_invoice = ft.Checkbox(
        label="Emite factura",
        value=True,
    )
    recurring = ft.Checkbox(
        label="Proveedor recurrente",
        value=False,
    )
    preferred = ft.Checkbox(
        label="Proveedor preferente",
        value=False,
    )

    customer_reference = _text_field(
        "Código de cliente",
        width=240,
    )
    contract_reference = _text_field(
        "Número de contrato",
        width=240,
    )
    external_reference = _text_field(
        "Referencia externa",
        width=260,
    )
    notes = _text_field(
        "Observaciones internas",
        width=730,
        multiline=True,
    )

    def all_form_controls():
        return [
            legal_name,
            trade_name,
            entity_type,
            supplier_type,
            document_type,
            tax_id,
            first_name,
            last_name_1,
            last_name_2,
            category,
            subcategory,
            services_description,
            phone,
            secondary_phone,
            email,
            website,
            contact_person,
            contact_position,
            address,
            postal_code,
            city,
            province,
            country,
            payment_method,
            payment_terms_days,
            iban,
            vat_rate,
            irpf_rate,
            usual_document_type,
            customer_reference,
            contract_reference,
            external_reference,
            notes,
        ]

    def reset_form():
        state["editing_id"] = None

        for control in all_form_controls():
            try:
                control.value = ""
            except Exception:
                pass

        entity_type.value = "COMPANY"
        supplier_type.value = "OTHER"
        document_type.value = ""
        category.value = ""
        country.value = "España"
        payment_method.value = ""
        payment_terms_days.value = "0"
        vat_rate.value = "21"
        irpf_rate.value = "0"
        usual_document_type.value = "INVOICE"

        issues_invoice.value = True
        recurring.value = False
        preferred.value = False

    def form_data():
        return {
            "entity_type":
                entity_type.value,
            "supplier_type":
                supplier_type.value,
            "legal_name":
                legal_name.value,
            "trade_name":
                trade_name.value,
            "document_type":
                document_type.value,
            "tax_id":
                tax_id.value,
            "first_name":
                first_name.value,
            "last_name_1":
                last_name_1.value,
            "last_name_2":
                last_name_2.value,
            "category":
                category.value,
            "subcategory":
                subcategory.value,
            "services_description":
                services_description.value,
            "phone":
                phone.value,
            "secondary_phone":
                secondary_phone.value,
            "email":
                email.value,
            "website":
                website.value,
            "contact_person":
                contact_person.value,
            "contact_position":
                contact_position.value,
            "address":
                address.value,
            "postal_code":
                postal_code.value,
            "city":
                city.value,
            "province":
                province.value,
            "country":
                country.value,
            "usual_payment_method":
                payment_method.value,
            "payment_terms_days":
                payment_terms_days.value,
            "iban":
                iban.value,
            "usual_vat_rate":
                vat_rate.value,
            "usual_irpf_rate":
                irpf_rate.value,
            "issues_invoice":
                issues_invoice.value,
            "usual_document_type":
                usual_document_type.value,
            "recurring":
                recurring.value,
            "preferred":
                preferred.value,
            "customer_reference":
                customer_reference.value,
            "contract_reference":
                contract_reference.value,
            "external_reference":
                external_reference.value,
            "active": True,
            "notes":
                notes.value,
        }

    def fill_form(supplier):
        state["editing_id"] = int(
            supplier["id"]
        )

        mapping = {
            legal_name: "legal_name",
            trade_name: "trade_name",
            entity_type: "entity_type",
            supplier_type: "supplier_type",
            document_type: "document_type",
            tax_id: "tax_id",
            first_name: "first_name",
            last_name_1: "last_name_1",
            last_name_2: "last_name_2",
            category: "category",
            subcategory: "subcategory",
            services_description:
                "services_description",
            phone: "phone",
            secondary_phone: "secondary_phone",
            email: "email",
            website: "website",
            contact_person: "contact_person",
            contact_position: "contact_position",
            address: "address",
            postal_code: "postal_code",
            city: "city",
            province: "province",
            country: "country",
            payment_method:
                "usual_payment_method",
            payment_terms_days:
                "payment_terms_days",
            iban: "iban",
            vat_rate: "usual_vat_rate",
            irpf_rate: "usual_irpf_rate",
            usual_document_type:
                "usual_document_type",
            customer_reference:
                "customer_reference",
            contract_reference:
                "contract_reference",
            external_reference:
                "external_reference",
            notes: "notes",
        }

        for control, key in mapping.items():
            value = supplier.get(key)

            if value is None:
                value = ""

            control.value = str(value)

        issues_invoice.value = bool(
            supplier.get("issues_invoice")
        )
        recurring.value = bool(
            supplier.get("recurring")
        )
        preferred.value = bool(
            supplier.get("preferred")
        )

    def close_dialog(e=None):
        supplier_dialog.open = False
        page.update()

    def save_supplier(e=None):
        try:
            data = form_data()

            if state.get("editing_id"):
                supplier_service.update_supplier(
                    state["editing_id"],
                    data,
                )
                message = "Proveedor actualizado"
            else:
                supplier_service.create_supplier(
                    data
                )
                message = "Proveedor creado"

            close_dialog()
            load_suppliers()
            _snack(page, message)

        except Exception as exc:
            _snack(
                page,
                f"No se pudo guardar: {exc}",
                error=True,
            )

    supplier_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Nuevo proveedor",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Container(
            width=1040,
            height=700,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Identificación",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        [
                            legal_name,
                            trade_name,
                            supplier_type,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            entity_type,
                            document_type,
                            tax_id,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            first_name,
                            last_name_1,
                            last_name_2,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Actividad",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        [
                            category,
                            subcategory,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    services_description,
                    ft.Divider(),
                    ft.Text(
                        "Contacto y domicilio",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        [
                            phone,
                            secondary_phone,
                            email,
                            website,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            contact_person,
                            contact_position,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    address,
                    ft.Row(
                        [
                            postal_code,
                            city,
                            province,
                            country,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Condiciones habituales",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        [
                            payment_method,
                            payment_terms_days,
                            iban,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            vat_rate,
                            irpf_rate,
                            usual_document_type,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            issues_invoice,
                            recurring,
                            preferred,
                        ],
                        wrap=True,
                        spacing=14,
                    ),
                    ft.Divider(),
                    ft.Text(
                        "Contratos y referencias",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        [
                            customer_reference,
                            contract_reference,
                            external_reference,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    notes,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            secondary_button(
                "Cancelar",
                close_dialog,
            ),
            primary_button(
                "Guardar",
                save_supplier,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(
            radius=16
        ),
    )

    page.overlay.append(supplier_dialog)

    def open_new_dialog(e=None):
        reset_form()
        supplier_dialog.title = ft.Text(
            "Nuevo proveedor",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )
        supplier_dialog.open = True
        page.update()

    def open_edit_dialog(supplier):
        fill_form(supplier)
        supplier_dialog.title = ft.Text(
            "Editar proveedor",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )
        supplier_dialog.open = True
        page.update()

    def active_filter_value():
        selected = str(
            state.get("status") or "ACTIVE"
        )

        if selected == "ACTIVE":
            return True

        if selected == "INACTIVE":
            return False

        return None

    def load_suppliers(e=None):
        state["search"] = str(
            search_input.value or ""
        ).strip()
        status_label = str(
            status_filter.get_value() or "Activos"
        ).strip()
        type_label = str(
            type_filter.get_value() or "Todos los tipos"
        ).strip()
        category_label = str(
            category_filter.get_value() or "Todas"
        ).strip()

        state["status"] = STATUS_FILTER_LABEL_TO_KEY.get(
            status_label,
            state.get("status") or "ACTIVE",
        )
        state["type"] = TYPE_FILTER_LABEL_TO_KEY.get(
            type_label,
            state.get("type") or "ALL",
        )
        state["category"] = CATEGORY_FILTER_LABEL_TO_KEY.get(
            category_label,
            state.get("category") or "ALL",
        )
        state["preferred_only"] = bool(
            preferred_checkbox.value
        )

        state["suppliers"] = (
            supplier_service.list_suppliers(
                search=state["search"],
                active=active_filter_value(),
                category=(
                    None
                    if state["category"] == "ALL"
                    else state["category"]
                ),
                supplier_type=(
                    None
                    if state["type"] == "ALL"
                    else state["type"]
                ),
                preferred=(
                    True
                    if state[
                        "preferred_only"
                    ]
                    else None
                ),
            )
        )

        render_results()
        page.update()

    def set_page(page_number):
        state["page"] = max(
            1,
            int(page_number),
        )
        render_results()
        page.update()

    def clear_filters(e=None):
        search_input.value = ""

        status_filter.set_value(
            "Activos",
            update=False,
        )
        type_filter.set_value(
            "Todos los tipos",
            update=False,
        )
        category_filter.set_value(
            "Todas",
            update=False,
        )

        preferred_checkbox.value = False

        state["status"] = "ACTIVE"
        state["type"] = "ALL"
        state["category"] = "ALL"
        state["preferred_only"] = False
        state["page"] = 1

        load_suppliers()

    def show_list(e=None):
        load_suppliers()
        render_master()

    def show_detail(supplier):
        root.content = supplier_detail_view(
            page,
            int(supplier["id"]),
            on_back=show_list,
            on_edit=open_edit_dialog,
        )
        page.update()

    def toggle_active(supplier):
        try:
            new_active = not bool(
                supplier.get("active")
            )

            supplier_service.set_supplier_active(
                supplier["id"],
                new_active,
            )

            load_suppliers()

            _snack(
                page,
                (
                    "Proveedor restaurado"
                    if new_active
                    else "Proveedor archivado"
                ),
            )

        except Exception as exc:
            _snack(
                page,
                f"No se pudo actualizar: {exc}",
                error=True,
            )

    def action_menu(supplier):
        items = [
            ft.PopupMenuItem(
                content=ft.Text(
                    "Ver ficha"
                ),
                on_click=lambda e, s=supplier: (
                    show_detail(s)
                ),
            ),
            ft.PopupMenuItem(
                content=ft.Text(
                    "Editar"
                ),
                on_click=lambda e, s=supplier: (
                    open_edit_dialog(s)
                ),
            ),
        ]

        items.append(
            ft.PopupMenuItem(
                content=ft.Text(
                    (
                        "Restaurar"
                        if not supplier.get(
                            "active"
                        )
                        else "Archivar"
                    ),
                    color=(
                        Q_SUCCESS
                        if not supplier.get(
                            "active"
                        )
                        else Q_DANGER
                    ),
                ),
                on_click=lambda e, s=supplier: (
                    toggle_active(s)
                ),
            )
        )

        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Acciones",
            items=items,
        )

    def supplier_card(supplier):
        badges = [
            status_badge(
                "Activo"
                if supplier.get("active")
                else "Inactivo"
            ),
        ]

        if supplier.get("category"):
            badges.append(
                status_badge(
                    supplier.get("category")
                )
            )

        if supplier.get("recurring"):
            badges.append(
                status_badge("Recurrente")
            )

        if supplier.get("preferred"):
            badges.append(
                status_badge("Preferente")
            )

        contact = " · ".join(
            value
            for value in [
                str(
                    supplier.get("phone")
                    or ""
                ).strip(),
                str(
                    supplier.get("email")
                    or ""
                ).strip(),
            ]
            if value
        ) or "Sin datos de contacto"

        location = " · ".join(
            value
            for value in [
                str(
                    supplier.get("city")
                    or ""
                ).strip(),
                str(
                    supplier.get("province")
                    or ""
                ).strip(),
            ]
            if value
        ) or "Sin ubicación"

        references = " · ".join(
            value
            for value in [
                (
                    "Cliente "
                    + str(
                        supplier.get(
                            "customer_reference"
                        )
                    )
                    if supplier.get(
                        "customer_reference"
                    )
                    else ""
                ),
                (
                    "Contrato "
                    + str(
                        supplier.get(
                            "contract_reference"
                        )
                    )
                    if supplier.get(
                        "contract_reference"
                    )
                    else ""
                ),
            ]
            if value
        )

        body = [
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.CONTACT_PHONE_OUTLINED,
                        size=15,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        contact,
                        size=11,
                        color=Q_MUTED,
                        selectable=True,
                    ),
                ],
                spacing=6,
                wrap=True,
            ),
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.LOCATION_ON_OUTLINED,
                        size=15,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        location,
                        size=11,
                        color=Q_MUTED,
                        selectable=True,
                    ),
                ],
                spacing=6,
                wrap=True,
            ),
        ]

        if references:
            body.append(
                ft.Text(
                    references,
                    size=11,
                    color=Q_MUTED,
                    selectable=True,
                )
            )

        return card_item(
            title=(
                supplier.get("legal_name")
                or f"Proveedor #{supplier.get('id')}"
            ),
            subtitle=" · ".join(
                value
                for value in [
                    TYPE_LABELS.get(
                        supplier.get(
                            "supplier_type"
                        ),
                        supplier.get(
                            "supplier_type"
                        ),
                    ),
                    supplier.get("tax_id"),
                    supplier.get(
                        "supplier_code"
                    ),
                ]
                if value
            ),
            badges=badges,
            actions=[
                action_menu(supplier)
            ],
            body=body,
            highlight=not bool(
                supplier.get("active")
            ),
            highlight_color="#F8FAFC",
            border_color=(
                "#D0D5DD"
                if supplier.get("active")
                else "#98A2B3"
            ),
            on_click=lambda e, s=supplier: (
                show_detail(s)
            ),
            padding=11,
        )

    def render_results():
        suppliers = list(
            state.get("suppliers") or []
        )

        total_items = len(suppliers)
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
        visible = suppliers[
            start:start + page_size
        ]

        if not visible:
            results_box.content = ft.Container(
                width=720,
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=24,
                margin=ft.margin.only(top=4),
                content=ft.Row(
                    controls=[
                        ft.Container(
                            width=46,
                            height=46,
                            border_radius=12,
                            bgcolor="#EAF3FF",
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(
                                ft.Icons.LOCAL_SHIPPING_OUTLINED,
                                color=Q_PRIMARY,
                                size=24,
                            ),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "No hay proveedores",
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Crea el primer proveedor o "
                                        "modifica los filtros actuales."
                                    ),
                                    size=12,
                                    color=Q_MUTED,
                                ),
                                ft.TextButton(
                                    "Crear primer proveedor",
                                    icon=ft.Icons.ADD,
                                    on_click=open_new_dialog,
                                ),
                            ],
                            spacing=4,
                            tight=True,
                        ),
                    ],
                    spacing=14,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
            )
            return

        results_box.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"{total_items} "
                                "proveedores encontrados"
                            ),
                            size=12,
                            color=Q_MUTED,
                        ),
                        compact_pagination_bar(
                            page=current_page,
                            page_size=page_size,
                            total_items=total_items,
                            on_page_change=set_page,
                            label_prefix="Proveedores",
                        ),
                    ],
                    alignment=(
                        ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Container(
                    height=500,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    padding=8,
                    content=ft.Column(
                        controls=[
                            supplier_card(supplier)
                            for supplier in visible
                        ],
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=8,
        )

    def render_master():
        metrics = supplier_service.supplier_metrics()

        root.content = ft.Container(
            expand=True,
            bgcolor="#FFFFFF",
            padding=20,
            content=ft.Column(
                controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Proveedores",
                                    size=28,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    (
                                        "Directorio maestro de "
                                        "proveedores, contratos "
                                        "y condiciones habituales"
                                    ),
                                    size=14,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.ElevatedButton(
                            "Nuevo proveedor",
                            icon=ft.Icons.ADD,
                            on_click=open_new_dialog,
                        ),
                    ],
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Row(
                    controls=[
                        metric_card(
                            "Proveedores activos",
                            metrics["active"],
                        ),
                        metric_card(
                            "Recurrentes",
                            metrics["recurring"],
                        ),
                        metric_card(
                            "Preferentes",
                            metrics["preferred"],
                        ),
                        metric_card(
                            "Archivados",
                            metrics["inactive"],
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    search_input,
                                    status_filter.control,
                                    type_filter.control,
                                    category_filter.control,
                                ],
                                spacing=8,
                                wrap=True,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                            ft.Row(
                                controls=[
                                    preferred_checkbox,
                                    ft.Row(
                                        controls=[
                                            secondary_button(
                                                "Limpiar filtros",
                                                clear_filters,
                                            ),
                                            secondary_button(
                                                "Actualizar",
                                                load_suppliers,
                                            ),
                                        ],
                                        spacing=8,
                                        tight=True,
                                    ),
                                ],
                                spacing=8,
                                alignment=(
                                    ft.MainAxisAlignment.SPACE_BETWEEN
                                ),
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                        ],
                        spacing=8,
                    ),
                ),
                    results_box,
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

        render_results()

    def filters_changed(e=None):
        state["page"] = 1
        load_suppliers()

    search_input.on_change = filters_changed
    preferred_checkbox.on_change = filters_changed

    load_suppliers()
    render_master()

    return root

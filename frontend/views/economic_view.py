from pathlib import Path
import flet as ft
from datetime import datetime

from backend.services import economic_service
import backend.services.invoicing_obligations_service as invoicing_obligations_service
from backend.services.cash_deposit_invoice_service import (
    add_invoice_allocation,
    get_cash_deposit_snapshot,
    list_candidate_invoices,
    remove_invoice_allocation,
)
from backend.services.invoicing_obligations_service import (
    available_obligation_months,
    daily_invoicing_obligations,
    invoicing_obligations_summary,
)
from backend.services import advisory_invoice_export_service
from backend.services import economic_movements_export_service
from backend.services import expense_export_service
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_text_field import text_input, required_text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_dialog import form_dialog
from frontend.components.app_table import app_table
from frontend.components.app_empty_state import empty_state
from frontend.components.app_alert import success_alert, error_alert
from frontend.components.economic_badge import economic_badge
from frontend.components.economic_payment_card import economic_payment_card
from frontend.components.economic_expense_card import economic_expense_card
from frontend.components.economic_engagement_letter_card import (
    economic_engagement_letter_card,
)
from backend.services import expense_service
from backend.services import expense_reconciliation_service
from backend.services import expense_classification_service
from backend.services import supplier_service
from frontend.components.economic_invoice_card import economic_invoice_card
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.listing import (
    card_item,
    compact_pagination_bar,
)
from frontend.components.listing.counter_chips import counter_chips
from backend.services.economic_reconciliation import (
    list_bank_movements,
    list_cashmatic_movements,
)
from backend.services.economic_reconciliation import (
    cents_to_eur,
    create_reconciliation_group,
    add_cobro_to_group,
    get_reconciliation_group_detail,
    list_reconciliation_groups,
)

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"


def _date_to_sql(value):
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _date_to_display(value):
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def _today_display():
    return datetime.today().strftime("%d/%m/%Y")


def _id(value):
    if not value or " - " not in value:
        return None
    return int(value.split(" - ", 1)[0])


def _leading_id(value):
    value = str(value or "").strip()
    if not value:
        return None

    # Soporta:
    # "13 - texto"
    # "13 | texto"
    # "13"
    for sep in (" - ", " | "):
        if sep in value:
            value = value.split(sep, 1)[0].strip()
            break

    try:
        return int(value)
    except Exception:
        return None


def _option_by_id(options, value_id, empty_label):
    if not value_id:
        return empty_label
    prefix = f"{int(value_id)} - "
    for option in options:
        if str(option).startswith(prefix):
            return option
    return empty_label


def _get_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _date_time_to_display(value):
    value = str(value or "").strip()
    if not value:
        return ""

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            if "H" in fmt:
                return dt.strftime("%d/%m/%Y %H:%M")
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass

    # Si viene con fecha ISO y cola rara, intentamos al menos YYYY-MM-DD.
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass

    return value


def _money_centimos(value):
    try:
        return f"{(int(value or 0) / 100):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00 €"


def _money(value):
    try:
        return f"{float(value or 0):.2f} €"
    except Exception:
        return "0.00 €"


def reconciliation_badge(status):
    raw = str(status or "").strip()
    key = raw.upper().replace(" ", "_")

    palette = {
        "CONCILIADO": {
            "label": "✓ CONCILIADO",
            "bg": "#DCFCE7",
            "fg": "#166534",
            "border": "#22C55E",
        },
        "PENDIENTE": {
            "label": "● PENDIENTE",
            "bg": "#FEF3C7",
            "fg": "#92400E",
            "border": "#F59E0B",
        },
        "PARCIAL": {
            "label": "◐ PARCIAL",
            "bg": "#DBEAFE",
            "fg": "#1D4ED8",
            "border": "#3B82F6",
        },
        "CONCILIACION_PARCIAL": {
            "label": "◐ PARCIAL",
            "bg": "#DBEAFE",
            "fg": "#1D4ED8",
            "border": "#3B82F6",
        },
        "SOBRANTE_REVISION": {
            "label": "⚠ SOBRANTE",
            "bg": "#FFE4E6",
            "fg": "#BE123C",
            "border": "#FB7185",
        },
        "REVIEW_REQUIRED": {
            "label": "⚠ REVISAR",
            "bg": "#FFE4E6",
            "fg": "#BE123C",
            "border": "#FB7185",
        },
        "PAYMENT_REVIEW_REQUIRED": {
            "label": "⚠ REVISAR",
            "bg": "#FFE4E6",
            "fg": "#BE123C",
            "border": "#FB7185",
        },
        "MANUALLY_LINKED": {
            "label": "🔗 MANUAL",
            "bg": "#F3E8FF",
            "fg": "#7E22CE",
            "border": "#A855F7",
        },
        "IGNORADO": {
            "label": "IGNORADO",
            "bg": "#F3F4F6",
            "fg": "#374151",
            "border": "#9CA3AF",
        },
        "IGNORED": {
            "label": "IGNORADO",
            "bg": "#F3F4F6",
            "fg": "#374151",
            "border": "#9CA3AF",
        },
        "ERROR": {
            "label": "✕ ERROR",
            "bg": "#FEE2E2",
            "fg": "#991B1B",
            "border": "#EF4444",
        },
        "QUARANTINE": {
            "label": "⛔ CUARENTENA",
            "bg": "#FEE2E2",
            "fg": "#991B1B",
            "border": "#EF4444",
        },
    }

    cfg = palette.get(key)
    if not cfg:
        cfg = {
            "label": raw or "-",
            "bg": "#EEF2FF",
            "fg": "#3730A3",
            "border": "#818CF8",
        }

    return ft.Container(
        content=ft.Text(
            cfg["label"],
            size=11,
            weight=ft.FontWeight.BOLD,
            color=cfg["fg"],
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        border_radius=999,
        bgcolor=cfg["bg"],
        border=ft.border.all(1.4, cfg["border"]),
    )


def economic_view(page: ft.Page):
    economic_service.initialize_economic_schema()

    state = {
        "section": "cobros",
        "message": None,
        "reconciliation_selected_group_id": None,
        "obligations_month": "",
        "obligations_source": "ALL",
        "obligations_search": "",
        "obligations_page": 1,
        "obligations_page_size": 8,
        "movements_source": "cashmatic",
        "cobros_page": 1,
        "cobros_page_size": 10,
        "cobros_search": "",
        "cobros_status_filter": "all",
        "cobros_date_from": "",
        "cobros_date_to": "",
        "facturas_page": 1,
        "facturas_page_size": 10,
        "facturas_search": "",
        "facturas_status_filter": "all",
        "facturas_holded_filter": "all",
        "facturas_date_from": "",
        "facturas_date_to": "",
        "hojas_page": 1,
        "hojas_page_size": 10,
        "hojas_search": "",
        "hojas_status_filter": "all",
    }

    content_area = ft.Container(expand=True)
    table_container = ft.Container(expand=True)

    clientes = economic_service.get_clientes_for_select()
    cliente_options = [c["display"] for c in clientes]
    expediente_options = [e["display"] for e in economic_service.get_expedientes_for_select()]
    hoja_options = [h["display"] for h in economic_service.get_hojas_for_select()]
    def _get_cobro_options_for_reconciliation():
        options = []
        try:
            for c in economic_service.list_cobros():
                label = " | ".join(
                    x for x in [
                        f'{c.get("id")}',
                        c.get("numero_cobro") or "",
                        _date_to_display(c.get("fecha_cobro")),
                        f'{c.get("importe") or 0} €',
                        c.get("forma_pago") or "",
                        c.get("numero_expediente") or "",
                    ]
                    if str(x or "").strip()
                )
                options.append(label)
        except Exception:
            pass
        return options



    def show_message(control):
        state["message"] = control

    def set_section(section):
        state["section"] = section
        state["message"] = None
        refresh()

    def section_button(key, label):
        selected = state["section"] == key
        return ft.Container(
            content=ft.Text(
                label,
                color="#FFFFFF" if selected else "#0057B8",
                weight=ft.FontWeight.BOLD,
                size=13,
            ),
            bgcolor="#0057B8" if selected else "#EAF3FF",
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            ink=True,
            on_click=lambda e, k=key: set_section(k),
        )

    def build_nav():
        return ft.Row(
            controls=[
                section_button("hojas", "Hojas de encargo"),
                section_button("cobros", "Cobros"),
                section_button("facturas", "Facturas"),
                section_button("gastos", "Gastos"),
                section_button("movimientos", "Movimientos"),
                section_button(
                    "conciliacion_manual",
                    "Obligaciones de facturación",
                ),
            ],
            spacing=8,
            wrap=True,
        )

    def refresh(e=None):
        table_container.content = build_table()
        content_area.content = build_view()
        page.update()

    def _cobro_search_blob(cobro):
        cliente = " ".join(
            part
            for part in [
                str(cobro.get("nombre") or "").strip(),
                str(cobro.get("primer_apellido") or "").strip(),
                str(cobro.get("segundo_apellido") or "").strip(),
            ]
            if part
        )

        facturacion_label = (
            "facturado"
            if cobro.get("numero_factura") or cobro.get("factura_id")
            else "facturable"
            if cobro.get("facturable")
            else "no facturable"
        )

        values = [
            cobro.get("id"),
            cobro.get("numero_cobro"),
            cobro.get("fecha_cobro"),
            _date_to_display(cobro.get("fecha_cobro")),
            cliente,
            cobro.get("cliente_id"),
            cobro.get("numero_expediente"),
            cobro.get("expediente_id"),
            cobro.get("numero_hoja"),
            cobro.get("hoja_encargo_id"),
            cobro.get("importe"),
            _money(cobro.get("importe")),
            cobro.get("forma_pago"),
            cobro.get("tipo_cobro"),
            cobro.get("tipo_fiscal"),
            cobro.get("concepto"),
            cobro.get("numero_factura"),
            cobro.get("factura_id"),
            cobro.get("estado_conciliacion"),
            facturacion_label,
        ]

        blob = []

        for value in values:
            blob.append(str(value or ""))

            try:
                blob.extend(_date_search_tokens(value))
            except Exception:
                pass

        return " ".join(blob).lower()


    def cobro_matches_search(cobro):
        query = str(state.get("cobros_search") or "").strip().lower()

        if not query:
            return True

        # Permite buscar varias palabras sin necesidad de que estén juntas.
        tokens = [token for token in query.split() if token]
        blob = _cobro_search_blob(cobro)

        return all(token in blob for token in tokens)


    def _normalized_cobro_date(value):
        raw = str(value or "").strip()
        if not raw:
            return ""

        normalized = _date_to_sql(raw)
        if normalized:
            return normalized

        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            return raw[:10]

        return ""


    def _cobro_status_keys(cobro):
        keys = set()

        reconciliation = str(
            cobro.get("estado_conciliacion") or "PENDIENTE"
        ).strip().upper().replace(" ", "_")

        if reconciliation in ("", "PENDIENTE"):
            keys.add("pending_reconciliation")
        elif reconciliation in (
            "PARCIAL",
            "CONCILIACION_PARCIAL",
            "CONCILIADO_PARCIAL",
        ):
            keys.add("partial_reconciliation")
        elif reconciliation == "CONCILIADO":
            keys.add("reconciled")
        else:
            keys.add("review")

        if cobro.get("numero_factura") or cobro.get("factura_id"):
            keys.add("invoiced")
        else:
            keys.add("not_invoiced")

        return keys


    def cobro_matches_period(cobro):
        cobro_date = _normalized_cobro_date(cobro.get("fecha_cobro"))
        date_from = str(state.get("cobros_date_from") or "").strip()
        date_to = str(state.get("cobros_date_to") or "").strip()

        if date_from and (not cobro_date or cobro_date < date_from):
            return False

        if date_to and (not cobro_date or cobro_date > date_to):
            return False

        return True


    def cobro_matches_status(cobro):
        active_status = str(
            state.get("cobros_status_filter") or "all"
        ).strip()

        if active_status in ("", "all"):
            return True

        return active_status in _cobro_status_keys(cobro)


    def filtered_cobros(include_status=True):
        results = [
            cobro
            for cobro in economic_service.list_cobros()
            if cobro_matches_search(cobro)
            and cobro_matches_period(cobro)
        ]

        if include_status:
            results = [
                cobro
                for cobro in results
                if cobro_matches_status(cobro)
            ]

        return results


    def cobros_status_counts():
        base_cobros = filtered_cobros(include_status=False)

        counts = {
            "all": len(base_cobros),
            "invoiced": 0,
            "not_invoiced": 0,
            "pending_reconciliation": 0,
            "partial_reconciliation": 0,
            "reconciled": 0,
            "review": 0,
        }

        for cobro in base_cobros:
            for key in _cobro_status_keys(cobro):
                counts[key] = counts.get(key, 0) + 1

        return counts


    def build_cobros_status_filters():
        status_map = {
            "all": ("Todos", "#F8FAFC", "#475569", "#CBD5E1"),
            "invoiced": ("Facturados", "#ECFDF3", "#027A48", "#6CE9A6"),
            "not_invoiced": (
                "No facturados",
                "#F1F5F9",
                "#475569",
                "#CBD5E1",
            ),
            "pending_reconciliation": (
                "Pendientes",
                "#FFFAEB",
                "#B54708",
                "#FEC84B",
            ),
            "partial_reconciliation": (
                "Parciales",
                "#EAF3FF",
                "#0057B8",
                "#84CAFF",
            ),
            "reconciled": (
                "Conciliados",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "review": (
                "Revisar",
                "#FEF3F2",
                "#B42318",
                "#FDA29B",
            ),
        }

        return counter_chips(
            options=[
                ("invoiced", "Facturados"),
                ("not_invoiced", "No facturados"),
                ("pending_reconciliation", "Pendientes"),
                ("partial_reconciliation", "Parciales"),
                ("reconciled", "Conciliados"),
                ("review", "Revisar"),
            ],
            counts=cobros_status_counts(),
            active_value=state.get("cobros_status_filter") or "all",
            on_select=on_cobros_status_select,
            include_all=True,
            all_label="Todos",
            all_value="all",
            status_map=status_map,
            bordered_status=True,
        )


    def build_cobros_period_summary():
        date_from = str(state.get("cobros_date_from") or "").strip()
        date_to = str(state.get("cobros_date_to") or "").strip()

        if not date_from and not date_to:
            return ft.Text(
                "Sin filtro temporal",
                size=11,
                color=Q_MUTED,
            )

        from_label = _date_to_display(date_from) if date_from else "Inicio"
        to_label = _date_to_display(date_to) if date_to else "Hoy"

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.DATE_RANGE,
                        size=14,
                        color="#0057B8",
                    ),
                    ft.Text(
                        f"{from_label} → {to_label}",
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color="#0057B8",
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor="#EAF3FF",
            border=ft.border.all(1, "#84CAFF"),
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
        )


    def refresh_cobros_results_only():
        cobros_results_box.content = build_cobros_results()
        cobros_status_box.content = build_cobros_status_filters()
        cobros_period_summary_box.content = build_cobros_period_summary()

        has_search = bool(
            str(state.get("cobros_search") or "").strip()
        )
        has_period = bool(
            state.get("cobros_date_from")
            or state.get("cobros_date_to")
        )
        has_status_filter = (
            str(state.get("cobros_status_filter") or "all").strip()
            not in ("", "all")
        )
        has_any_filter = (
            has_search
            or has_period
            or has_status_filter
        )

        # La X debe estar disponible siempre que exista cualquier filtro:
        # texto, periodo o estado.
        cobros_clear_button.disabled = not has_any_filter
        cobros_clear_button.icon_color = (
            Q_PRIMARY_DARK if has_any_filter else "#98A2B3"
        )
        cobros_clear_button.tooltip = (
            "Reiniciar todos los filtros"
            if has_any_filter
            else "No hay filtros activos"
        )

        cobros_period_button.icon_color = (
            "#0057B8" if has_period else Q_PRIMARY_DARK
        )

        try:
            cobros_results_box.update()
            cobros_status_box.update()
            cobros_period_summary_box.update()
            cobros_clear_button.update()
            cobros_period_button.update()
        except Exception:
            page.update()


    def on_cobros_search_change(e=None):
        state["cobros_search"] = str(cobros_filter.value or "")
        state["cobros_page"] = 1
        refresh_cobros_results_only()


    def clear_cobros_search(e=None):
        """
        Reinicia todos los filtros de la vista Cobros:
        búsqueda, periodo, estado y paginación.
        """
        state.update(
            {
                "cobros_search": "",
                "cobros_date_from": "",
                "cobros_date_to": "",
                "cobros_status_filter": "all",
                "cobros_page": 1,
            }
        )

        cobros_filter.value = ""
        cobros_date_from_input.value = ""
        cobros_date_to_input.value = ""
        cobros_period_error.value = ""

        # Actualiza resultados, chips, resumen temporal e iconos.
        refresh_cobros_results_only()

        try:
            cobros_filter.update()
            cobros_date_from_input.update()
            cobros_date_to_input.update()
            cobros_period_error.update()
        except Exception:
            page.update()


    def on_cobros_status_select(status_value):
        state["cobros_status_filter"] = str(status_value or "all")
        state["cobros_page"] = 1
        refresh_cobros_results_only()


    def open_cobros_period_dialog(e=None):
        cobros_date_from_input.value = (
            _date_to_display(state.get("cobros_date_from"))
            if state.get("cobros_date_from")
            else ""
        )
        cobros_date_to_input.value = (
            _date_to_display(state.get("cobros_date_to"))
            if state.get("cobros_date_to")
            else ""
        )

        cobros_period_error.value = ""
        cobros_period_dialog.open = True
        page.update()


    def close_cobros_period_dialog(e=None):
        cobros_period_dialog.open = False
        page.update()


    def apply_cobros_period_filter(e=None):
        raw_from = str(cobros_date_from_input.value or "").strip()
        raw_to = str(cobros_date_to_input.value or "").strip()

        date_from = _date_to_sql(raw_from) if raw_from else ""
        date_to = _date_to_sql(raw_to) if raw_to else ""

        if raw_from and not date_from:
            cobros_period_error.value = (
                "La fecha inicial no es válida. Usa DD/MM/AAAA."
            )
            cobros_period_error.update()
            return

        if raw_to and not date_to:
            cobros_period_error.value = (
                "La fecha final no es válida. Usa DD/MM/AAAA."
            )
            cobros_period_error.update()
            return

        if date_from and date_to and date_from > date_to:
            cobros_period_error.value = (
                "La fecha inicial no puede ser posterior a la fecha final."
            )
            cobros_period_error.update()
            return

        state["cobros_date_from"] = date_from
        state["cobros_date_to"] = date_to
        state["cobros_page"] = 1

        cobros_period_dialog.open = False
        refresh_cobros_results_only()
        page.update()


    def clear_cobros_period_filter(e=None):
        cobros_date_from_input.value = ""
        cobros_date_to_input.value = ""
        cobros_period_error.value = ""

        state["cobros_date_from"] = ""
        state["cobros_date_to"] = ""
        state["cobros_page"] = 1

        cobros_period_dialog.open = False
        refresh_cobros_results_only()
        page.update()


    def go_cobros_page(page_number):
        try:
            requested_page = int(page_number)
        except (TypeError, ValueError):
            requested_page = 1

        cobros = filtered_cobros()
        page_size = max(1, int(state.get("cobros_page_size") or 10))
        total_pages = max(1, (len(cobros) + page_size - 1) // page_size)

        state["cobros_page"] = max(1, min(requested_page, total_pages))
        refresh_cobros_results_only()

    def build_view():
        resumen = economic_service.resumen_economico()
        controls = [
            ft.Text("Módulo económico", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text("Hojas de encargo, ingresos, cobros, facturas, gastos y conciliación.", size=14, color=Q_MUTED),
        ]

        if state["message"]:
            controls.append(state["message"])

        controls.append(build_nav())

        action_control = build_actions()
        if action_control is not None:
            controls.append(action_control)

        controls.append(table_container)

        return ft.Column(controls=controls, spacing=18, expand=True)

    def build_actions():
        # En Cobros, el alta está integrada como icono
        # junto a la barra de búsqueda.
        if state["section"] == "cobros":
            return None

        if state["section"] in ("facturas", "hojas"):
            # Estas secciones integran sus acciones y filtros
            # dentro de su propia cabecera.
            return None

        mapping = {
            "gastos": ("Nuevo gasto", open_gasto_dialog),
        }

        action = mapping.get(state["section"])

        if not action:
            return None

        label, handler = action

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Row(
                controls=[primary_button(label, handler)],
                alignment=ft.MainAxisAlignment.END,
            ),
        )

    def _reconciliation_status_badge(status):
        status = (status or "DRAFT").upper()
        color_map = {
            "BALANCED": "#047857",
            "UNBALANCED": "#B42318",
            "REVIEWED": "#0057B8",
            "IGNORED": "#667085",
            "DRAFT": "#B54708",
        }
        bg_map = {
            "BALANCED": "#ECFDF3",
            "UNBALANCED": "#FEF3F2",
            "REVIEWED": "#EAF3FF",
            "IGNORED": "#F2F4F7",
            "DRAFT": "#FFFAEB",
        }
        return ft.Container(
            content=ft.Text(status, size=11, weight=ft.FontWeight.BOLD, color=color_map.get(status, "#344054")),
            bgcolor=bg_map.get(status, "#F2F4F7"),
            border_radius=999,
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
        )


    def _money_centimos(value):
        try:
            return f"{cents_to_eur(int(value or 0)):.2f} €"
        except Exception:
            return "0.00 €"


    reconciliation_group_type = select_input(
        "Tipo de grupo",
        ["CASH_RECEIPT", "CARD_SETTLEMENT", "BANK_TRANSFER", "STRIPE_SETTLEMENT", "MIXED_REVIEW"],
        value="BANK_TRANSFER",
        width=260,
    )
    reconciliation_group_date = text_input("Fecha YYYY-MM-DD", width=180)
    reconciliation_group_title = required_text_input("Título", width=520)
    reconciliation_group_description = multiline_input("Descripción / notas", width=620)


    def open_reconciliation_group_dialog(e=None):
        reconciliation_group_type.value = "BANK_TRANSFER"
        reconciliation_group_date.value = datetime.today().strftime("%Y-%m-%d")
        reconciliation_group_title.value = ""
        reconciliation_group_description.value = ""
        reconciliation_group_dialog.open = True
        page.update()


    def save_reconciliation_group(e=None):
        try:
            title = (reconciliation_group_title.value or "").strip()
            if not title:
                raise ValueError("Indica un título para la conciliación")

            group_id = create_reconciliation_group(
                group_type=reconciliation_group_type.value,
                title=title,
                description=reconciliation_group_description.value,
                group_date=reconciliation_group_date.value,
                notes="",
            )
            state["reconciliation_selected_group_id"] = group_id
            reconciliation_group_dialog.open = False
            show_message(success_alert("Conciliación creada"))
            refresh()
        except Exception as exc:
            show_message(error_alert(str(exc)))
            refresh()


    reconciliation_group_dialog = form_dialog(
        "Nueva conciliación de conciliación",
        ft.Column(
            controls=[
                ft.Text(
                    "Crea un contenedor manual para cuadrar cobros/recibos contra movimientos reales.",
                    size=13,
                    color=Q_MUTED,
                ),
                ft.Row([reconciliation_group_type, reconciliation_group_date], wrap=True, spacing=10),
                reconciliation_group_title,
                reconciliation_group_description,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(reconciliation_group_dialog)), primary_button("Crear conciliación", save_reconciliation_group)],
    )
    page.overlay.append(reconciliation_group_dialog)


    reconciliation_cobro_dd = select_input(
        "Cobro",
        ["Selecciona cobro"] + _get_cobro_options_for_reconciliation(),
        value="Selecciona cobro",
        width=620,
    )


    def open_add_cobro_to_group_dialog(e=None):
        if not state.get("reconciliation_selected_group_id"):
            show_message(error_alert("Selecciona una conciliación de conciliación"))
            refresh()
            return

        _set_dropdown_options(
            reconciliation_cobro_dd,
            _get_cobro_options_for_reconciliation(),
            "Selecciona cobro",
        )
        reconciliation_cobro_dd.value = "Selecciona cobro"
        add_cobro_to_group_dialog.open = True
        page.update()


    def save_add_cobro_to_group(e=None):
        try:
            group_id = state.get("reconciliation_selected_group_id")
            if not group_id:
                raise ValueError("Selecciona una conciliación de conciliación")

            cobro_id = _leading_id(reconciliation_cobro_dd.value)
            if not cobro_id:
                raise ValueError("Selecciona un cobro")

            add_cobro_to_group(
                group_id=int(group_id),
                cobro_id=int(cobro_id),
                role="EXPECTED",
            )
            add_cobro_to_group_dialog.open = False
            show_message(success_alert("Recibo/cobro añadido a la conciliación"))
            refresh()
        except Exception as exc:
            show_message(error_alert(str(exc)))
            refresh()


    add_cobro_to_group_dialog = form_dialog(
        "Añadir recibo/cobro al grupo",
        ft.Column(
            controls=[
                ft.Text(
                    "El recibo/cobro se añadirá como elemento esperado. No se crea factura ni se vincula automáticamente ningún movimiento.",
                    size=13,
                    color=Q_MUTED,
                ),
                reconciliation_cobro_dd,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(add_cobro_to_group_dialog)), primary_button("Añadir recibo/cobro", save_add_cobro_to_group)],
    )
    page.overlay.append(add_cobro_to_group_dialog)


    def _obligation_month_label(month_value):
        raw = str(month_value or "").strip()

        if len(raw) != 7 or raw[4] != "-":
            return "Todos los meses"

        month_names = {
            "01": "Enero",
            "02": "Febrero",
            "03": "Marzo",
            "04": "Abril",
            "05": "Mayo",
            "06": "Junio",
            "07": "Julio",
            "08": "Agosto",
            "09": "Septiembre",
            "10": "Octubre",
            "11": "Noviembre",
            "12": "Diciembre",
        }

        year, month = raw.split("-", 1)

        return f"{month_names.get(month, month)} de {year}"


    def _obligation_source_style(source_type):
        styles = {
            "CAJA_RURAL": (
                "Caja Rural",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "SANTANDER": (
                "Santander",
                "#FEF3F2",
                "#B42318",
                "#FDA29B",
            ),
            "ING": (
                "ING",
                "#FFF7ED",
                "#C2410C",
                "#FDBA74",
            ),
        }

        return styles.get(
            str(source_type or "").upper(),
            (
                str(source_type or "Otro"),
                "#F2F4F7",
                "#475467",
                "#D0D5DD",
            ),
        )


    def _obligation_source_badge(source_type):
        label, background, foreground, border_color = (
            _obligation_source_style(source_type)
        )

        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=foreground,
            ),
            bgcolor=background,
            border=ft.border.all(1, border_color),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=4,
            ),
        )


    def _obligation_metric_card(title, value, subtitle):
        return ft.Container(
            width=230,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text(
                        title,
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        value,
                        size=21,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        subtitle,
                        size=11,
                        color=Q_MUTED,
                    ),
                ],
                spacing=4,
            ),
        )


    def _obligation_source_filter_button(source_type, label):
        selected = (
            str(state.get("obligations_source") or "ALL")
            == source_type
        )

        if source_type == "ALL":
            color = "#0057B8"
        else:
            _, _, color, _ = _obligation_source_style(source_type)

        def select_source(e=None):
            state["obligations_source"] = source_type
            state["obligations_page"] = 1
            refresh()

        return ft.Container(
            content=ft.Text(
                label,
                size=12,
                weight=ft.FontWeight.BOLD,
                color="#FFFFFF" if selected else color,
            ),
            bgcolor=color if selected else "#FFFFFF",
            border=ft.border.all(1.3, color),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=7,
            ),
            ink=True,
            on_click=select_source,
        )


    def _obligation_status_config(
        pending_centimos,
        invoiced_centimos,
    ):
        pending_centimos = int(
            pending_centimos or 0
        )
        invoiced_centimos = int(
            invoiced_centimos or 0
        )

        if pending_centimos <= 0 and invoiced_centimos > 0:
            return {
                "status": "FACTURADO",
                "foreground": "#027A48",
                "background": "#ECFDF3",
                "border": "#6CE9A6",
                "icon": ft.Icons.CHECK_CIRCLE_OUTLINE,
            }

        if invoiced_centimos > 0:
            return {
                "status": "PARCIAL",
                "foreground": "#B54708",
                "background": "#FFFAEB",
                "border": "#FEC84B",
                "icon": ft.Icons.PIE_CHART_OUTLINE,
            }

        return {
            "status": "PENDIENTE",
            "foreground": "#B54708",
            "background": "#FFFAEB",
            "border": "#FEC84B",
            "icon": ft.Icons.SCHEDULE,
        }


    def _obligation_status_badge(
        pending_centimos,
        invoiced_centimos,
    ):
        config = _obligation_status_config(
            pending_centimos,
            invoiced_centimos,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        config["icon"],
                        size=13,
                        color=config["foreground"],
                    ),
                    ft.Text(
                        config["status"],
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=config["foreground"],
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=config["background"],
            border=ft.border.all(
                1,
                config["border"],
            ),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=4,
            ),
        )


    def _obligation_day_amounts(day):
        movements = list(
            day.get("movements") or []
        )

        original_centimos = sum(
            int(
                getattr(
                    movement,
                    "original_amount_centimos",
                    movement.amount_centimos,
                )
                or 0
            )
            for movement in movements
        )

        invoiced_centimos = sum(
            int(
                getattr(
                    movement,
                    "invoiced_centimos",
                    0,
                )
                or 0
            )
            for movement in movements
        )

        pending_centimos = sum(
            int(
                getattr(
                    movement,
                    "amount_centimos",
                    0,
                )
                or 0
            )
            for movement in movements
        )

        return {
            "original_centimos": original_centimos,
            "invoiced_centimos": invoiced_centimos,
            "pending_centimos": pending_centimos,
        }


    def _obligation_metric(
        label,
        value,
        *,
        color=Q_PRIMARY_DARK,
        width=180,
    ):
        return ft.Container(
            width=width,
            bgcolor="#F8FAFC",
            border=ft.border.all(1, "#E2E8F0"),
            border_radius=10,
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=9,
            ),
            content=ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=10,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        value,
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=color,
                    ),
                ],
                spacing=2,
            ),
        )


    def _is_cash_deposit_obligation_movement(
        movement,
    ):
        return (
            str(
                getattr(
                    movement,
                    "source_type",
                    "",
                )
                or ""
            ).strip().upper()
            == "CAJA_RURAL"
            and str(
                getattr(
                    movement,
                    "concept",
                    "",
                )
                or ""
            ).strip().upper()
            == "INGRESO EN EFECTIVO"
            and int(
                getattr(
                    movement,
                    "original_amount_centimos",
                    getattr(
                        movement,
                        "amount_centimos",
                        0,
                    ),
                )
                or 0
            )
            > 0
        )


    def _cash_deposit_allocation_card(
        allocation,
        *,
        movement_id,
    ):
        allocation_id = int(
            allocation.get("id") or 0
        )

        def remove_allocation(e=None):
            try:
                remove_invoice_allocation(
                    allocation_id
                )

                for control in list(page.overlay):
                    if isinstance(
                        control,
                        ft.AlertDialog,
                    ):
                        control.open = False

                refresh()

                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Factura retirada del ingreso en efectivo."
                    )
                )
                page.snack_bar.open = True
                page.update()

            except Exception as exc:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        f"No se pudo retirar la factura: {exc}"
                    )
                )
                page.snack_bar.open = True
                page.update()

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#D0D5DD",
            ),
            border_radius=10,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.RECEIPT_LONG_OUTLINED,
                                size=17,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        str(
                                            allocation.get(
                                                "numero_factura"
                                            )
                                            or (
                                                "Factura #"
                                                + str(
                                                    allocation.get(
                                                        "invoice_id"
                                                    )
                                                    or "-"
                                                )
                                            )
                                        ),
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            str(
                                                allocation.get(
                                                    "cliente"
                                                )
                                                or "Cliente sin identificar"
                                            )
                                            + " · "
                                            + _date_to_display(
                                                allocation.get(
                                                    "fecha_factura"
                                                )
                                            )
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                tooltip="Retirar factura del ingreso",
                                icon_color="#B42318",
                                on_click=remove_allocation,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Aplicado: "
                                + _money_centimos(
                                    allocation.get(
                                        "amount_centimos"
                                    )
                                ),
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color="#027A48",
                            ),
                            ft.Text(
                                "Cobrado en efectivo: "
                                + (
                                    _date_to_display(
                                        allocation.get(
                                            "cash_collection_date"
                                        )
                                    )
                                    if allocation.get(
                                        "cash_collection_date"
                                    )
                                    else "Sin fecha indicada"
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=14,
                        wrap=True,
                    ),
                    (
                        ft.Text(
                            str(
                                allocation.get("notes")
                                or ""
                            ),
                            size=10,
                            color=Q_MUTED,
                            selectable=True,
                        )
                        if str(
                            allocation.get("notes")
                            or ""
                        ).strip()
                        else ft.Container(
                            visible=False,
                            width=0,
                            height=0,
                        )
                    ),
                ],
                spacing=6,
            ),
        )


    def open_cash_deposit_invoice_dialog(
        movement,
    ):
        movement_id = int(
            getattr(
                movement,
                "source_id",
                0,
            )
            or 0
        )

        try:
            snapshot = get_cash_deposit_snapshot(
                movement_id
            )
            candidates = list_candidate_invoices(
                movement_id
            )
        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"No se pudo cargar el ingreso en efectivo: {exc}"
                )
            )
            page.snack_bar.open = True
            page.update()
            return

        candidate_by_label = {}

        for candidate in candidates:
            label = (
                str(
                    candidate.get("numero_factura")
                    or f"Factura #{candidate.get('id')}"
                )
                + " · "
                + str(
                    candidate.get("cliente")
                    or "Cliente sin identificar"
                )
                + " · "
                + _date_to_display(
                    candidate.get("fecha_factura")
                )
                + " · Disponible "
                + _money_centimos(
                    candidate.get(
                        "available_centimos"
                    )
                )
            )

            candidate_by_label[label] = candidate

        invoice_selector = ft.Dropdown(
            label="Factura previa",
            width=650,
            options=[
                ft.dropdown.Option(label)
                for label in candidate_by_label
            ],
            disabled=not bool(candidate_by_label),
        )

        amount_input = ft.TextField(
            label="Importe aplicado",
            width=185,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        amount_input_control = ft.Row(
            controls=[
                amount_input,
                ft.Container(
                    width=28,
                    height=40,
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                "€",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                        spacing=0,
                    ),
                ),
            ],
            spacing=3,
            tight=True,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        )

        cash_date_input = ft.TextField(
            label="Fecha real del cobro en efectivo",
            hint_text="AAAA-MM-DD",
            width=260,
        )

        notes_input = ft.TextField(
            label="Notas",
            multiline=True,
            min_lines=2,
            max_lines=3,
            width=650,
        )

        confirmation = ft.Checkbox(
            label=(
                "Confirmo que esta factura corresponde a "
                "dinero cobrado en efectivo antes de su "
                "ingreso en la cuenta bancaria."
            ),
            value=False,
        )

        available_text = ft.Text(
            "",
            size=11,
            color=Q_MUTED,
        )

        def selected_candidate():
            return candidate_by_label.get(
                str(invoice_selector.value or "")
            )

        def update_selected_invoice(e=None):
            candidate = selected_candidate()

            if not candidate:
                available_text.value = ""
                amount_input.value = ""
                page.update()
                return

            available = int(
                candidate.get(
                    "available_centimos"
                )
                or 0
            )

            movement_available = int(
                snapshot.get(
                    "pending_centimos"
                )
                or 0
            )

            suggested = min(
                available,
                movement_available,
            )

            amount_input.value = (
                f"{suggested / 100:.2f}"
                .replace(".", ",")
            )

            available_text.value = (
                "Disponible en factura: "
                + _money_centimos(available)
                + " · Pendiente en ingreso: "
                + _money_centimos(
                    movement_available
                )
            )

            if not cash_date_input.value:
                cash_date_input.value = str(
                    candidate.get(
                        "fecha_factura"
                    )
                    or ""
                )

            page.update()

        invoice_selector.on_change = (
            update_selected_invoice
        )

        def parse_amount_centimos(value):
            raw = str(value or "").strip()

            if not raw:
                return 0

            raw = (
                raw.replace("€", "")
                .replace(" ", "")
            )

            if "," in raw and "." in raw:
                raw = raw.replace(".", "")
                raw = raw.replace(",", ".")
            elif "," in raw:
                raw = raw.replace(",", ".")

            try:
                return int(
                    round(float(raw) * 100)
                )
            except Exception:
                raise ValueError(
                    "El importe aplicado no es válido."
                )

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        def save_allocation(e=None):
            candidate = selected_candidate()

            if not candidate:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Selecciona una factura previa."
                    )
                )
                page.snack_bar.open = True
                page.update()
                return

            if not bool(confirmation.value):
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Debes confirmar que la factura fue "
                        "cobrada en efectivo."
                    )
                )
                page.snack_bar.open = True
                page.update()
                return

            try:
                amount_centimos = (
                    parse_amount_centimos(
                        amount_input.value
                    )
                )

                add_invoice_allocation(
                    movement_id=movement_id,
                    invoice_id=int(
                        candidate["id"]
                    ),
                    amount_centimos=amount_centimos,
                    cash_collection_date=str(
                        cash_date_input.value
                        or ""
                    ).strip(),
                    notes=str(
                        notes_input.value
                        or ""
                    ).strip(),
                )

                for control in list(page.overlay):
                    if isinstance(
                        control,
                        ft.AlertDialog,
                    ):
                        control.open = False

                refresh()

                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Factura aplicada al ingreso en efectivo."
                    )
                )
                page.snack_bar.open = True
                page.update()

            except Exception as exc:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        f"No se pudo aplicar la factura: {exc}"
                    )
                )
                page.snack_bar.open = True
                page.update()

        allocation_cards = [
            _cash_deposit_allocation_card(
                allocation,
                movement_id=movement_id,
            )
            for allocation in (
                snapshot.get("allocations")
                or []
            )
        ]

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.POINT_OF_SALE_OUTLINED,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                "Ingreso en efectivo",
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    f"Movimiento #{movement_id} · "
                                    + _date_to_display(
                                        getattr(
                                            movement,
                                            "obligation_date",
                                            "",
                                        )
                                    )
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=9,
            ),
            content=ft.Container(
                width=760,
                height=620,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                _obligation_metric(
                                    "Importe ingresado",
                                    _money_centimos(
                                        snapshot.get(
                                            "original_centimos"
                                        )
                                    ),
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Mediante cobros",
                                    _money_centimos(
                                        snapshot.get(
                                            "payment_invoiced_centimos"
                                        )
                                    ),
                                    color="#027A48",
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Facturas previas",
                                    _money_centimos(
                                        snapshot.get(
                                            "direct_invoice_centimos"
                                        )
                                    ),
                                    color="#027A48",
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Pendiente",
                                    _money_centimos(
                                        snapshot.get(
                                            "pending_centimos"
                                        )
                                    ),
                                    color=(
                                        "#027A48"
                                        if int(
                                            snapshot.get(
                                                "pending_centimos"
                                            )
                                            or 0
                                        )
                                        <= 0
                                        else "#B54708"
                                    ),
                                    width=170,
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        ft.Divider(height=16),
                        ft.Text(
                            "Facturas ya aplicadas",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        (
                            ft.Column(
                                controls=allocation_cards,
                                spacing=7,
                            )
                            if allocation_cards
                            else ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(
                                    1,
                                    "#E2E8F0",
                                ),
                                border_radius=10,
                                padding=12,
                                content=ft.Text(
                                    "Todavía no hay facturas previas "
                                    "aplicadas a este ingreso.",
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            )
                        ),
                        ft.Divider(height=16),
                        ft.Text(
                            "Vincular factura previa",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        (
                            ft.Column(
                                controls=[
                                    invoice_selector,
                                    available_text,
                                    ft.Row(
                                        controls=[
                                            amount_input_control,
                                            cash_date_input,
                                        ],
                                        spacing=10,
                                        wrap=True,
                                        vertical_alignment=(
                                            ft.CrossAxisAlignment.CENTER
                                        ),
                                    ),
                                    notes_input,
                                    confirmation,
                                ],
                                spacing=9,
                            )
                            if candidate_by_label
                            else ft.Container(
                                bgcolor="#FFFAEB",
                                border=ft.border.all(
                                    1,
                                    "#FEC84B",
                                ),
                                border_radius=10,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            "No existen facturas previas "
                                            "compatibles.",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color="#B54708",
                                        ),
                                        ft.Text(
                                            "Solo se muestran facturas activas, "
                                            "emitidas o aprobadas, con fecha igual "
                                            "o anterior al ingreso bancario y con "
                                            "importe todavía disponible.",
                                            size=10,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            )
                        ),
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=close_dialog,
                ),
                ft.ElevatedButton(
                    "Aplicar factura",
                    icon=ft.Icons.ADD_LINK,
                    disabled=not bool(candidate_by_label),
                    on_click=save_allocation,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(
                radius=16
            ),
            inset_padding=ft.padding.symmetric(
                horizontal=24,
                vertical=18,
            ),
        )

        try:
            if dialog not in page.overlay:
                page.overlay.append(dialog)
        except Exception:
            pass

        dialog.open = True
        page.update()


    def _obligation_dialog_movement_card(movement):
        original_centimos = int(
            getattr(
                movement,
                "original_amount_centimos",
                movement.amount_centimos,
            )
            or 0
        )
        invoiced_centimos = int(
            getattr(
                movement,
                "invoiced_centimos",
                0,
            )
            or 0
        )
        pending_centimos = int(
            getattr(
                movement,
                "amount_centimos",
                0,
            )
            or 0
        )

        status = str(
            getattr(
                movement,
                "invoicing_status",
                "PENDIENTE",
            )
            or "PENDIENTE"
        ).strip().upper()

        is_cash_deposit = (
            _is_cash_deposit_obligation_movement(
                movement
            )
        )

        cash_snapshot = None

        if is_cash_deposit:
            try:
                cash_snapshot = (
                    get_cash_deposit_snapshot(
                        int(movement.source_id)
                    )
                )
            except Exception:
                cash_snapshot = None

        controls = [
            ft.Row(
                controls=[
                    _obligation_source_badge(
                        movement.source_type
                    ),
                    (
                        ft.Container(
                            content=ft.Text(
                                "INGRESO EN EFECTIVO",
                                size=9,
                                weight=ft.FontWeight.BOLD,
                                color="#175CD3",
                            ),
                            bgcolor="#EFF8FF",
                            border=ft.border.all(
                                1,
                                "#84CAFF",
                            ),
                            border_radius=999,
                            padding=ft.padding.symmetric(
                                horizontal=8,
                                vertical=3,
                            ),
                        )
                        if is_cash_deposit
                        else ft.Container(
                            visible=False,
                            width=0,
                            height=0,
                        )
                    ),
                    ft.Text(
                        (
                            f"Movimiento "
                            f"#{movement.source_id}"
                        ),
                        size=11,
                        color=Q_MUTED,
                        expand=True,
                    ),
                    _obligation_status_badge(
                        pending_centimos,
                        invoiced_centimos,
                    ),
                ],
                spacing=8,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
            ft.Text(
                movement.concept or "-",
                size=12,
                weight=ft.FontWeight.W_500,
                color="#344054",
                selectable=True,
            ),
            ft.Row(
                controls=[
                    ft.Text(
                        "Original: "
                        + _money_centimos(
                            original_centimos
                        ),
                        size=11,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        "Facturado: "
                        + _money_centimos(
                            invoiced_centimos
                        ),
                        size=11,
                        color="#027A48",
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "Pendiente: "
                        + _money_centimos(
                            pending_centimos
                        ),
                        size=11,
                        color=(
                            "#027A48"
                            if pending_centimos <= 0
                            else "#B54708"
                        ),
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        f"Estado: {status}",
                        size=10,
                        color=Q_MUTED,
                    ),
                ],
                spacing=14,
                wrap=True,
            ),
        ]

        if is_cash_deposit:
            direct_invoice_centimos = int(
                (
                    cash_snapshot
                    or {}
                ).get(
                    "direct_invoice_centimos",
                    0,
                )
                or 0
            )

            payment_invoice_centimos = int(
                (
                    cash_snapshot
                    or {}
                ).get(
                    "payment_invoiced_centimos",
                    0,
                )
                or 0
            )

            allocation_count = len(
                (
                    cash_snapshot
                    or {}
                ).get("allocations")
                or []
            )

            controls.extend(
                [
                    ft.Divider(height=10),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(
                            1,
                            "#E2E8F0",
                        ),
                        border_radius=10,
                        padding=10,
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            "Justificación del efectivo",
                                            size=11,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            (
                                                f"{allocation_count} "
                                                + (
                                                    "factura previa aplicada"
                                                    if allocation_count == 1
                                                    else "facturas previas aplicadas"
                                                )
                                                + " · Cobros conciliados: "
                                                + _money_centimos(
                                                    payment_invoice_centimos
                                                )
                                                + " · Facturas previas: "
                                                + _money_centimos(
                                                    direct_invoice_centimos
                                                )
                                            ),
                                            size=10,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.OutlinedButton(
                                    "Gestionar facturas",
                                    icon=ft.Icons.RECEIPT_LONG_OUTLINED,
                                    on_click=lambda e, item=movement: (
                                        open_cash_deposit_invoice_dialog(
                                            item
                                        )
                                    ),
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                        ),
                    ),
                ]
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                (
                    "#84CAFF"
                    if is_cash_deposit
                    else Q_BORDER
                ),
            ),
            border_radius=10,
            padding=10,
            content=ft.Column(
                controls=controls,
                spacing=7,
            ),
        )


    def open_obligation_day_dialog(day):
        obligation_date = str(
            day.get("obligation_date") or ""
        )
        amounts = _obligation_day_amounts(day)

        original_centimos = amounts[
            "original_centimos"
        ]
        invoiced_centimos = amounts[
            "invoiced_centimos"
        ]
        pending_centimos = amounts[
            "pending_centimos"
        ]

        source_groups = {}

        for movement in day.get("movements") or []:
            source = source_groups.setdefault(
                movement.source_type,
                {
                    "source_type": movement.source_type,
                    "source_label": movement.source_label,
                    "movements": 0,
                    "original_centimos": 0,
                    "invoiced_centimos": 0,
                    "pending_centimos": 0,
                },
            )

            source["movements"] += 1
            source["original_centimos"] += int(
                getattr(
                    movement,
                    "original_amount_centimos",
                    movement.amount_centimos,
                )
                or 0
            )
            source["invoiced_centimos"] += int(
                getattr(
                    movement,
                    "invoiced_centimos",
                    0,
                )
                or 0
            )
            source["pending_centimos"] += int(
                getattr(
                    movement,
                    "amount_centimos",
                    0,
                )
                or 0
            )

        source_cards = []

        for source in sorted(
            source_groups.values(),
            key=lambda item: str(
                item.get("source_label") or ""
            ),
        ):
            movement_label = (
                "movimiento"
                if int(source["movements"]) == 1
                else "movimientos"
            )

            source_cards.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(
                        1,
                        "#E2E8F0",
                    ),
                    border_radius=10,
                    padding=10,
                    content=ft.Row(
                        controls=[
                            _obligation_source_badge(
                                source["source_type"]
                            ),
                            ft.Text(
                                (
                                    f"{source['movements']} "
                                    f"{movement_label}"
                                ),
                                size=11,
                                color=Q_MUTED,
                                expand=True,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Facturado: "
                                        + _money_centimos(
                                            source[
                                                "invoiced_centimos"
                                            ]
                                        ),
                                        size=10,
                                        color="#027A48",
                                    ),
                                    ft.Text(
                                        "Pendiente: "
                                        + _money_centimos(
                                            source[
                                                "pending_centimos"
                                            ]
                                        ),
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=(
                                            "#027A48"
                                            if int(
                                                source[
                                                    "pending_centimos"
                                                ]
                                            )
                                            <= 0
                                            else "#B54708"
                                        ),
                                    ),
                                ],
                                spacing=2,
                                horizontal_alignment=(
                                    ft.CrossAxisAlignment.END
                                ),
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                )
            )

        movement_cards = [
            _obligation_dialog_movement_card(
                movement
            )
            for movement in day.get("movements") or []
        ]

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.RECEIPT_LONG_OUTLINED,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                "Obligación de facturación",
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                _date_to_display(
                                    obligation_date
                                ),
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=820,
                height=620,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                _obligation_metric(
                                    "Total detectado",
                                    _money_centimos(
                                        original_centimos
                                    ),
                                ),
                                _obligation_metric(
                                    "Facturado",
                                    _money_centimos(
                                        invoiced_centimos
                                    ),
                                    color="#027A48",
                                ),
                                _obligation_metric(
                                    "Pendiente",
                                    _money_centimos(
                                        pending_centimos
                                    ),
                                    color=(
                                        "#027A48"
                                        if pending_centimos <= 0
                                        else "#B54708"
                                    ),
                                ),
                                _obligation_status_badge(
                                    pending_centimos,
                                    invoiced_centimos,
                                ),
                            ],
                            spacing=10,
                            wrap=True,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                        ),
                        ft.Divider(height=16),
                        ft.Text(
                            "Desglose por banco",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Column(
                            controls=source_cards,
                            spacing=7,
                        ),
                        ft.Divider(height=16),
                        ft.Text(
                            "Movimientos",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Column(
                            controls=movement_cards,
                            spacing=7,
                        ),
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda e: close_dialog(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(
                radius=16
            ),
            inset_padding=ft.padding.symmetric(
                horizontal=24,
                vertical=18,
            ),
        )

        try:
            if dialog not in page.overlay:
                page.overlay.append(dialog)
        except Exception:
            pass

        dialog.open = True
        page.update()


    def _obligation_day_action_menu(day):
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Acciones",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.VISIBILITY_OUTLINED,
                                size=17,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                "Ver detalle",
                                color=Q_PRIMARY_DARK,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ],
                        spacing=8,
                    ),
                    on_click=lambda e, item=day: (
                        open_obligation_day_dialog(item)
                    ),
                ),
            ],
        )


    def _obligation_day_card(day):
        obligation_date = str(
            day.get("obligation_date") or ""
        )
        amounts = _obligation_day_amounts(day)

        original_centimos = amounts[
            "original_centimos"
        ]
        invoiced_centimos = amounts[
            "invoiced_centimos"
        ]
        pending_centimos = amounts[
            "pending_centimos"
        ]

        movement_count = int(
            day.get("movement_count") or 0
        )

        source_labels = [
            str(source.get("source_label") or "").strip()
            for source in day.get("source_totals") or []
            if str(
                source.get("source_label") or ""
            ).strip()
        ]

        sources_text = (
            " · ".join(source_labels)
            if source_labels
            else "Sin banco identificado"
        )

        movement_text = (
            "1 movimiento"
            if movement_count == 1
            else f"{movement_count} movimientos"
        )

        body = [
            ft.Row(
                controls=[
                    _obligation_metric(
                        "Total detectado",
                        _money_centimos(
                            original_centimos
                        ),
                        width=190,
                    ),
                    _obligation_metric(
                        "Facturado",
                        _money_centimos(
                            invoiced_centimos
                        ),
                        color="#027A48",
                        width=190,
                    ),
                    _obligation_metric(
                        "Pendiente",
                        _money_centimos(
                            pending_centimos
                        ),
                        color=(
                            "#027A48"
                            if pending_centimos <= 0
                            else "#B54708"
                        ),
                        width=190,
                    ),
                ],
                spacing=10,
                wrap=True,
            ),
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.ACCOUNT_BALANCE_OUTLINED,
                        size=14,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        sources_text,
                        size=11,
                        color=Q_MUTED,
                        selectable=True,
                    ),
                ],
                spacing=5,
                wrap=True,
            ),
        ]

        return card_item(
            title=_date_to_display(
                obligation_date
            ),
            subtitle=(
                f"{movement_text} · "
                f"Obligación diaria"
            ),
            badges=[
                _obligation_status_badge(
                    pending_centimos,
                    invoiced_centimos,
                ),
            ],
            actions=[
                _obligation_day_action_menu(day),
            ],
            body=body,
            highlight=pending_centimos > 0,
            highlight_color="#FFFCF5",
            border_color=(
                "#FEC84B"
                if pending_centimos > 0
                else "#6CE9A6"
            ),
            border_width=1,
            on_click=lambda e, item=day: (
                open_obligation_day_dialog(item)
            ),
            padding=10,
        )


    def _obligation_pagination(total_items):
        page_size = max(
            1,
            int(state.get("obligations_page_size") or 8),
        )
        total_pages = max(
            1,
            (int(total_items or 0) + page_size - 1)
            // page_size,
        )
        current_page = max(
            1,
            min(
                int(state.get("obligations_page") or 1),
                total_pages,
            ),
        )
        state["obligations_page"] = current_page

        def change_page(target):
            state["obligations_page"] = max(
                1,
                min(int(target), total_pages),
            )
            refresh()

        return ft.Row(
            controls=[
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    tooltip="Página anterior",
                    disabled=current_page <= 1,
                    on_click=lambda e: change_page(
                        current_page - 1
                    ),
                ),
                ft.Text(
                    f"Página {current_page} de {total_pages}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    tooltip="Página siguiente",
                    disabled=current_page >= total_pages,
                    on_click=lambda e: change_page(
                        current_page + 1
                    ),
                ),
            ],
            spacing=4,
            tight=True,
        )


    def open_obligations_month_summary_dialog(
        e=None,
    ):
        selected_month = str(
            state.get("obligations_month") or ""
        ).strip()

        selected_source = str(
            state.get("obligations_source") or "ALL"
        ).strip().upper()

        if selected_source == "CASHMATIC":
            selected_source = "ALL"

        search = str(
            state.get("obligations_search") or ""
        ).strip()

        days = daily_invoicing_obligations(
            month=selected_month,
            source_type=selected_source,
            search=search,
        )

        movements = [
            movement
            for day in days
            for movement in (
                day.get("movements") or []
            )
        ]

        original_centimos = sum(
            int(
                getattr(
                    movement,
                    "original_amount_centimos",
                    movement.amount_centimos,
                )
                or 0
            )
            for movement in movements
        )

        invoiced_centimos = sum(
            int(
                getattr(
                    movement,
                    "invoiced_centimos",
                    0,
                )
                or 0
            )
            for movement in movements
        )

        pending_centimos = sum(
            int(
                getattr(
                    movement,
                    "amount_centimos",
                    0,
                )
                or 0
            )
            for movement in movements
        )

        fully_invoiced_count = 0
        partial_count = 0
        pending_count = 0

        by_source = {}

        for movement in movements:
            movement_original = int(
                getattr(
                    movement,
                    "original_amount_centimos",
                    movement.amount_centimos,
                )
                or 0
            )

            movement_invoiced = int(
                getattr(
                    movement,
                    "invoiced_centimos",
                    0,
                )
                or 0
            )

            movement_pending = int(
                getattr(
                    movement,
                    "amount_centimos",
                    0,
                )
                or 0
            )

            if (
                movement_pending <= 0
                and movement_invoiced > 0
            ):
                fully_invoiced_count += 1
            elif movement_invoiced > 0:
                partial_count += 1
            else:
                pending_count += 1

            source = by_source.setdefault(
                str(
                    movement.source_type or ""
                ),
                {
                    "source_type": str(
                        movement.source_type or ""
                    ),
                    "source_label": str(
                        movement.source_label
                        or movement.source_type
                        or "Sin banco"
                    ),
                    "movements": 0,
                    "original_centimos": 0,
                    "invoiced_centimos": 0,
                    "pending_centimos": 0,
                },
            )

            source["movements"] += 1
            source["original_centimos"] += (
                movement_original
            )
            source["invoiced_centimos"] += (
                movement_invoiced
            )
            source["pending_centimos"] += (
                movement_pending
            )

        source_cards = []

        for source in sorted(
            by_source.values(),
            key=lambda item: str(
                item.get("source_label") or ""
            ),
        ):
            source_cards.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(
                        1,
                        "#E2E8F0",
                    ),
                    border_radius=10,
                    padding=10,
                    content=ft.Row(
                        controls=[
                            _obligation_source_badge(
                                source["source_type"]
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        str(
                                            source[
                                                "source_label"
                                            ]
                                        ),
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            f"{source['movements']} "
                                            + (
                                                "movimiento"
                                                if int(
                                                    source[
                                                        "movements"
                                                    ]
                                                )
                                                == 1
                                                else "movimientos"
                                            )
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Total: "
                                        + _money_centimos(
                                            source[
                                                "original_centimos"
                                            ]
                                        ),
                                        size=10,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        "Facturado: "
                                        + _money_centimos(
                                            source[
                                                "invoiced_centimos"
                                            ]
                                        ),
                                        size=10,
                                        color="#027A48",
                                    ),
                                    ft.Text(
                                        "Pendiente: "
                                        + _money_centimos(
                                            source[
                                                "pending_centimos"
                                            ]
                                        ),
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=(
                                            "#027A48"
                                            if int(
                                                source[
                                                    "pending_centimos"
                                                ]
                                            )
                                            <= 0
                                            else "#B54708"
                                        ),
                                    ),
                                ],
                                spacing=1,
                                horizontal_alignment=(
                                    ft.CrossAxisAlignment.END
                                ),
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                )
            )

        month_label = (
            _obligation_month_label(
                selected_month
            )
            if selected_month
            else "Todos los meses"
        )

        filters_description = []

        if selected_source not in {
            "",
            "ALL",
            "TODOS",
        }:
            filters_description.append(
                f"Banco: {selected_source}"
            )

        if search:
            filters_description.append(
                f'Búsqueda: "{search}"'
            )

        filters_text = (
            " · ".join(filters_description)
            if filters_description
            else "Sin filtros adicionales"
        )

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.CALENDAR_MONTH_OUTLINED,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                f"Resumen de {month_label}",
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                filters_text,
                                size=11,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=820,
                height=570,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                _obligation_metric(
                                    "Total detectado",
                                    _money_centimos(
                                        original_centimos
                                    ),
                                    width=235,
                                ),
                                _obligation_metric(
                                    "Facturado",
                                    _money_centimos(
                                        invoiced_centimos
                                    ),
                                    color="#027A48",
                                    width=235,
                                ),
                                _obligation_metric(
                                    "Pendiente",
                                    _money_centimos(
                                        pending_centimos
                                    ),
                                    color=(
                                        "#027A48"
                                        if pending_centimos <= 0
                                        else "#B54708"
                                    ),
                                    width=235,
                                ),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        ft.Row(
                            controls=[
                                _obligation_metric(
                                    "Días",
                                    str(len(days)),
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Movimientos",
                                    str(len(movements)),
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Facturados",
                                    str(
                                        fully_invoiced_count
                                    ),
                                    color="#027A48",
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Parciales",
                                    str(partial_count),
                                    color="#B54708",
                                    width=170,
                                ),
                                _obligation_metric(
                                    "Pendientes",
                                    str(pending_count),
                                    color="#B42318",
                                    width=170,
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        ft.Divider(height=16),
                        ft.Text(
                            "Desglose por banco",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        (
                            ft.Column(
                                controls=source_cards,
                                spacing=7,
                            )
                            if source_cards
                            else ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(
                                    1,
                                    "#E2E8F0",
                                ),
                                border_radius=10,
                                padding=14,
                                content=ft.Text(
                                    (
                                        "No hay movimientos para "
                                        "los filtros seleccionados."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            )
                        ),
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=close_dialog,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(
                radius=16
            ),
            inset_padding=ft.padding.symmetric(
                horizontal=24,
                vertical=18,
            ),
        )

        try:
            if dialog not in page.overlay:
                page.overlay.append(dialog)
        except Exception:
            pass

        dialog.open = True
        page.update()


    def build_manual_reconciliation_section():
        months = available_obligation_months()

        if (
            not state.get("obligations_month")
            and months
        ):
            state["obligations_month"] = months[0]

        selected_month = str(
            state.get("obligations_month") or ""
        )
        selected_source = str(
            state.get("obligations_source") or "ALL"
        )

        if selected_source == "CASHMATIC":
            selected_source = "ALL"
            state["obligations_source"] = "ALL"
        search = str(
            state.get("obligations_search") or ""
        )

        days = daily_invoicing_obligations(
            month=selected_month,
            source_type=selected_source,
            search=search,
        )
        month_options = [
            _obligation_month_label(month)
            for month in months
        ]

        obligations_month_autocomplete.set_options(
            month_options,
            clear_value=False,
        )

        if selected_month:
            obligations_month_autocomplete.set_value(
                _obligation_month_label(selected_month),
                update=False,
            )

        obligations_search_input.value = search

        page_size = max(
            1,
            int(state.get("obligations_page_size") or 8),
        )
        total_pages = max(
            1,
            (len(days) + page_size - 1) // page_size,
        )
        current_page = max(
            1,
            min(
                int(state.get("obligations_page") or 1),
                total_pages,
            ),
        )
        state["obligations_page"] = current_page

        start = (current_page - 1) * page_size
        visible_days = days[start:start + page_size]

        cards = [
            _obligation_day_card(day)
            for day in visible_days
        ]

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            "Obligaciones de facturación",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                            expand=True,
                        ),
                        ft.OutlinedButton(
                            "Ver mes",
                            icon=ft.Icons.CALENDAR_MONTH_OUTLINED,
                            tooltip=(
                                "Ver el resumen del mes "
                                "con los filtros actuales"
                            ),
                            on_click=(
                                open_obligations_month_summary_dialog
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="Actualizar obligaciones",
                            on_click=refresh,
                        ),
                    ],
                ),
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    obligations_month_autocomplete.control,
                                    obligations_search_input,
                                    ft.IconButton(
                                        icon=ft.Icons.CLOSE,
                                        tooltip="Limpiar filtros",
                                        on_click=(
                                            clear_obligations_filters
                                        ),
                                    ),
                                ],
                                spacing=8,
                                wrap=True,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                            ft.Row(
                                controls=[
                                    _obligation_source_filter_button(
                                        "ALL",
                                        "Todos",
                                    ),
                                    _obligation_source_filter_button(
                                        "CAJA_RURAL",
                                        "Caja Rural",
                                    ),
                                    _obligation_source_filter_button(
                                        "SANTANDER",
                                        "Santander",
                                    ),
                                    _obligation_source_filter_button(
                                        "ING",
                                        "ING",
                                    ),
                                ],
                                spacing=7,
                                wrap=True,
                            ),
                        ],
                        spacing=10,
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"{len(days)} días encontrados"
                            ),
                            size=12,
                            color=Q_MUTED,
                            expand=True,
                        ),
                        _obligation_pagination(len(days)),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                (
                    ft.ListView(
                        controls=cards,
                        spacing=10,
                        expand=True,
                        padding=ft.padding.only(
                            right=4,
                            bottom=12,
                        ),
                    )
                    if cards
                    else ft.Container(
                        expand=True,
                        alignment=ft.alignment.center,
                        content=empty_state(
                            "No hay obligaciones para los filtros seleccionados"
                        ),
                    )
                ),
            ],
            spacing=14,
            expand=True,
        )


    def set_movements_source(source):
        state["movements_source"] = source
        state["movements_page"] = 1
        state["movements_search"] = ""
        movements_filter.value = ""
        refresh()


    def movements_source_button(source_key, label):
        selected = (state.get("movements_source") or "cashmatic") == source_key

        source_colors = {
            "cashmatic": "#2563EB",    # azul
            "caja_rural": "#16A34A",   # verde
            "ing": "#F97316",          # naranja
            "santander": "#DC2626",    # rojo
        }

        color = source_colors.get(source_key, "#64748B")

        def select_source(e=None):
            state["movements_source"] = source_key
            state["movements_page"] = 1
            refresh()

        return ft.Container(
            content=ft.Text(
                label,
                size=12,
                weight=ft.FontWeight.BOLD if selected else ft.FontWeight.W_500,
                color="#FFFFFF" if selected else color,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            border_radius=999,
            bgcolor=color if selected else "#FFFFFF",
            border=ft.border.all(1.4, color),
            on_click=select_source,
            ink=True,
        )


    def movements_cache_key(source=None):
        return source or state.get("movements_source") or "cashmatic"


    def clear_movements_cache(source=None):
        cache = state.setdefault("movements_cache", {})
        if source:
            cache.pop(source, None)
        else:
            cache.clear()


    def _cashmatic_dedupe_score(item):
        """
        Cuando el mismo movimiento viene en exports distintos, Cashmatic puede
        traer un export con segundos reales y otro redondeado al minuto.
        Para mostrar un histórico limpio, conservamos la versión más precisa.
        """
        start_time = str(_get_value(item, "start_time") or "")
        seconds = ""
        try:
            seconds = start_time.split(" ")[1].split(":")[2]
        except Exception:
            seconds = ""

        score = 0

        if seconds and seconds != "00":
            score += 10

        if _get_value(item, "reason_raw"):
            score += 3

        if _get_value(item, "reference_raw"):
            score += 2

        try:
            score += int(_get_value(item, "id") or 0) / 100000000
        except Exception:
            pass

        return score


    def unique_cashmatic_movements(items):
        """
        El histórico visible debe representar movimientos lógicos, no filas
        repetidas de distintos exports Cashmatic.

        Clave principal: cashmatic_id.
        Si no hubiera cashmatic_id, se conserva la fila como única.
        """
        unique = {}
        passthrough = []

        for item in items:
            cashmatic_id = str(_get_value(item, "cashmatic_id") or "").strip()

            if not cashmatic_id:
                passthrough.append(item)
                continue

            previous = unique.get(cashmatic_id)
            if previous is None:
                unique[cashmatic_id] = item
                continue

            if _cashmatic_dedupe_score(item) > _cashmatic_dedupe_score(previous):
                unique[cashmatic_id] = item

        ordered = list(unique.values()) + passthrough

        def sort_key(item):
            return (
                str(_get_value(item, "start_time") or ""),
                int(_get_value(item, "id") or 0),
            )

        return sorted(ordered, key=sort_key, reverse=True)


    def load_movements_for_source(source):
        source = movements_cache_key(source)
        cache = state.setdefault("movements_cache", {})
        if source in cache:
            return cache[source]

        if source == "cashmatic":
            page_data = list_cashmatic_movements(
                page=1,
                page_size=1000000,
                include_ignored=False,
            )
            items = unique_cashmatic_movements(list(getattr(page_data, "items", None) or []))
        else:
            bank_map = {
                "caja_rural": "CAJA_RURAL",
                "ing": "ING",
                "santander": "SANTANDER",
            }
            page_data = list_bank_movements(
                page=1,
                page_size=5000,
                bank_name=bank_map.get(source, "ING"),
                include_ignored=False,
            )
            items = list(getattr(page_data, "items", None) or [])

            # La tabla bancaria debe representar el extracto:
            # 1) días más recientes primero;
            # 2) dentro del mismo día, respetar el orden original del XLS.
            #
            # ING, Santander y Caja Rural guardan row_number del archivo origen.
            # Usar id DESC altera el orden visual dentro del mismo día y confunde
            # al comparar contra el Excel.
            def bank_sort_key(item):
                operation_date = str(_get_value(item, "operation_date") or "")
                try:
                    row_number = int(_get_value(item, "row_number") or 999999)
                except Exception:
                    row_number = 999999

                return (
                    operation_date,
                    -row_number,
                )

            items = sorted(items, key=bank_sort_key, reverse=True)

        cache[source] = items
        return items


    def _date_search_tokens(value):
        raw = str(value or "").strip()
        if not raw:
            return []

        tokens = [raw.lower()]

        # Esperado: YYYY-MM-DD HH:MM:SS
        date_part = raw.split(" ")[0]
        pieces = date_part.split("-")

        if len(pieces) == 3:
            yyyy, mm, dd = pieces
            tokens.extend([
                f"{dd}/{mm}/{yyyy}",
                f"{dd}-{mm}-{yyyy}",
                f"{mm}/{yyyy}",
                f"{yyyy}-{mm}",
                f"{dd}/{mm}",
                f"{dd}-{mm}",
            ])

            month_names = {
                "01": "enero",
                "02": "febrero",
                "03": "marzo",
                "04": "abril",
                "05": "mayo",
                "06": "junio",
                "07": "julio",
                "08": "agosto",
                "09": "septiembre",
                "10": "octubre",
                "11": "noviembre",
                "12": "diciembre",
            }

            month_name = month_names.get(mm)
            if month_name:
                tokens.extend([
                    month_name,
                    f"{month_name} {yyyy}",
                    f"{dd} {month_name}",
                    f"{dd} {month_name} {yyyy}",
                ])

        return tokens


    def _movement_search_blob(values):
        blob = []
        for value in values:
            blob.append(str(value or ""))
            blob.extend(_date_search_tokens(value))
        return " ".join(blob).lower()


    def movement_matches_filter(item, source):
        texto = (state.get("movements_search") or "").lower().strip()
        if not texto:
            return True

        if source == "cashmatic":
            values = [
                _get_value(item, "id"),
                _get_value(item, "batch_id"),
                _get_value(item, "cashmatic_id"),
                _get_value(item, "reason_raw"),
                _get_value(item, "reference_raw"),
                _get_value(item, "operation"),
                _get_value(item, "movement_status"),
                _get_value(item, "start_time"),
                _get_value(item, "end_time"),
                _money_centimos(_get_value(item, "inserted_centimos")),
                _money_centimos(_get_value(item, "net_amount_centimos")),
            ]
        else:
            values = [
                _get_value(item, "id"),
                _get_value(item, "batch_id"),
                _get_value(item, "concept"),
                _get_value(item, "movement_type"),
                _get_value(item, "movement_status"),
                _get_value(item, "operation_date"),
                _get_value(item, "value_date"),
                _get_value(item, "bank_name"),
                _money_centimos(_get_value(item, "amount_centimos")),
            ]

        return texto in _movement_search_blob(values)


    def filtered_movements_for_source(source):
        source = movements_cache_key(source)
        return [
            item for item in load_movements_for_source(source)
            if movement_matches_filter(item, source)
        ]


    def paginate_movements(items):
        page_size = max(1, int(state.get("movements_page_size") or 50))
        total_items = len(items)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page_number = max(1, min(int(state.get("movements_page") or 1), total_pages))
        state["movements_page"] = page_number

        start_index = (page_number - 1) * page_size
        end_index = start_index + page_size
        return items[start_index:end_index], total_items, page_number, page_size


    def movements_pagination(total_items, page_number, page_size):
        return compact_pagination_bar(
            page=page_number,
            page_size=page_size,
            total_items=total_items,
            on_page_change=go_movements_page,
            label_prefix="Movimientos",
        )


    def go_movements_page(page_number):
        try:
            page_number = int(page_number)
        except Exception:
            page_number = 1

        source = state.get("movements_source") or "cashmatic"
        total_items = len(filtered_movements_for_source(source))
        page_size = max(1, int(state.get("movements_page_size") or 50))
        total_pages = max(1, (total_items + page_size - 1) // page_size)

        state["movements_page"] = max(1, min(page_number, total_pages))
        refresh_movements_results()






    def movement_money_text(value):
        try:
            amount = int(value or 0)
        except Exception:
            amount = 0

        color = Q_MUTED
        if amount > 0:
            color = "#16A34A"
        elif amount < 0:
            color = "#DC2626"

        return ft.Text(
            _money_centimos(value),
            size=12,
            weight=ft.FontWeight.BOLD if amount != 0 else ft.FontWeight.NORMAL,
            color=color,
            selectable=True,
        )

    def is_cashmatic_candidate_payment(item):
        """
        Cashmatic:
        - payment: conciliable, aunque esté en REVISAR.
        - movimiento interno: no conciliable.
        """
        status = str(_get_value(item, "movement_status") or "").strip().upper()
        operation = str(_get_value(item, "operation") or "").strip().lower()
        candidate_payment = str(_get_value(item, "candidate_payment") or "").strip().lower()

        if status in {
            "INTERNAL_CASHMATIC_MOVEMENT",
            "IGNORED",
            "IGNORADO",
        }:
            return False

        if operation == "payment":
            return True

        if status in {
            "CANDIDATE_PAYMENT_MANUAL_LINK_REQUIRED",
            "PAYMENT_REVIEW_REQUIRED",
            "CONCILIADO",
            "PARCIAL",
            "CONCILIACION_PARCIAL",
            "MANUALLY_LINKED",
        }:
            return True

        if candidate_payment in {"1", "true", "yes", "sí", "si"}:
            return True

        return False



    def is_movement_reconcilable(source, item):
        if source != "cashmatic":
            return True
        return is_cashmatic_candidate_payment(item)


    def movement_reconciliation_status(item):
        """
        Estado visual simplificado para movimientos importados.

        Estados visibles:
        - MOVIMIENTO INTERNO
        - REVISAR
        - CONCILIADO PARCIAL
        - CONCILIADO
        """
        movement_status = str(_get_value(item, "movement_status") or "").strip().upper()
        operation = str(_get_value(item, "operation") or "").strip().lower()

        if movement_status == "INTERNAL_CASHMATIC_MOVEMENT":
            return "MOVIMIENTO INTERNO", "#6B7280"

        raw_status = str(
            _get_value(item, "reconciliation_status")
            or _get_value(item, "conciliation_status")
            or _get_value(item, "manual_reconciliation_status")
            or ""
        ).strip().upper()

        if raw_status in {
            "PARTIAL",
            "PARTIAL_RECONCILED",
            "CONCILIACION_PARCIAL",
            "CONCILIACIÓN_PARCIAL",
        }:
            return "CONCILIADO PARCIAL", "#7E22CE"

        if raw_status in {
            "RECONCILED",
            "CONCILIADO",
            "LINKED",
            "MANUALLY_LINKED",
        }:
            return "CONCILIADO", "#16A34A"

        linked_markers = [
            "linked_client_id",
            "linked_expedient_id",
            "linked_payment_id",
            "linked_at",
            "manual_link_id",
            "reconciliation_group_id",
        ]

        movement_amount = (
            _get_value(item, "requested_centimos")
            or _get_value(item, "amount_centimos")
            or _get_value(item, "net_amount_centimos")
            or _get_value(item, "inserted_centimos")
            or 0
        )

        linked_amount = (
            _get_value(item, "linked_amount_centimos")
            or _get_value(item, "matched_amount_centimos")
            or _get_value(item, "reconciled_amount_centimos")
            or 0
        )

        try:
            movement_abs = abs(int(movement_amount or 0))
        except Exception:
            movement_abs = 0

        try:
            linked_abs = abs(int(linked_amount or 0))
        except Exception:
            linked_abs = 0

        if linked_abs > 0:
            if movement_abs > 0 and linked_abs < movement_abs:
                return "CONCILIADO PARCIAL", "#7E22CE"
            return "CONCILIADO", "#16A34A"

        if any(_get_value(item, key) for key in linked_markers):
            return "CONCILIADO", "#16A34A"

        # Payment Cashmatic no vinculado o payment con revisión: se puede conciliar/revisar.
        # Bancos sin vínculo: también deben quedar en REVISAR.
        if operation == "payment" or movement_status in {
            "CANDIDATE_PAYMENT_MANUAL_LINK_REQUIRED",
            "PAYMENT_REVIEW_REQUIRED",
            "QUARANTINE",
        }:
            return "REVISAR", "#7E22CE"

        return "REVISAR", "#7E22CE"



    def movement_reconciliation_badge(item):
        label, color = movement_reconciliation_status(item)

        palette = {
            "MOVIMIENTO INTERNO": {
                "bg": "#F3F4F6",
                "fg": "#374151",
                "border": "#9CA3AF",
            },
            "CONCILIADO": {
                "bg": "#DCFCE7",
                "fg": "#166534",
                "border": "#22C55E",
            },
            "CONCILIADO PARCIAL": {
                "bg": "#F3E8FF",
                "fg": "#7E22CE",
                "border": "#A855F7",
            },
            "REVISAR": {
                "bg": "#F3E8FF",
                "fg": "#7E22CE",
                "border": "#A855F7",
            },
        }

        cfg = palette.get(label, {
            "bg": "#EEF2FF",
            "fg": color or "#3730A3",
            "border": color or "#818CF8",
        })

        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=cfg["fg"],
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
            border_radius=999,
            bgcolor=cfg["bg"],
            border=ft.border.all(1.4, cfg["border"]),
        )



    def movement_applied_pending_summary(source, item):
        """
        Columna 'Conciliación' de movimientos importados.

        No es un estado.
        Debe mostrar resumen económico:
        - Pendiente
        - Aplicado
        - Completo

        Y en tooltip:
        - Movimiento
        - Aplicado
        - Pendiente
        """
        if source == "cashmatic" and not is_movement_reconcilable(source, item):
            return ft.Text("-", size=12, color=Q_MUTED)

        movement_amount = movement_amount_centimos_for_reconciliation(source, item)

        linked_amount = (
            _get_value(item, "linked_amount_centimos")
            or _get_value(item, "matched_amount_centimos")
            or _get_value(item, "reconciled_amount_centimos")
            or 0
        )

        try:
            movement_abs = abs(int(movement_amount or 0))
        except Exception:
            movement_abs = 0

        try:
            linked_abs = abs(int(linked_amount or 0))
        except Exception:
            linked_abs = 0

        pending_abs = max(movement_abs - linked_abs, 0)

        if movement_abs <= 0:
            label = "-"
            fg = Q_MUTED
            bg = "#F9FAFB"
            border = "#E5E7EB"
        elif linked_abs <= 0:
            label = f"Pendiente: {_money_centimos(pending_abs)}"
            fg = "#7E22CE"
            bg = "#F3E8FF"
            border = "#A855F7"
        elif pending_abs > 0:
            label = f"Aplicado: {_money_centimos(linked_abs)}"
            fg = "#92400E"
            bg = "#FEF3C7"
            border = "#F59E0B"
        else:
            label = "Completo"
            fg = "#166534"
            bg = "#DCFCE7"
            border = "#22C55E"

        tooltip = (
            "Conciliación del movimiento\n"
            f"Movimiento: {_money_centimos(movement_abs)}\n"
            f"Aplicado: {_money_centimos(linked_abs)}\n"
            f"Pendiente: {_money_centimos(pending_abs)}"
        )

        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=fg,
                no_wrap=True,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
            border_radius=999,
            bgcolor=bg,
            border=ft.border.all(1.2, border),
            tooltip=tooltip,
        )



    def movement_amount_centimos_for_reconciliation(source, item):
        source = (source or "").lower().strip()

        if source == "cashmatic":
            # En conciliación económica Cashmatic debe mandar el importe requerido:
            # es el importe que se pretendía cobrar al cliente.
            # El neto/insertado puede variar por devoluciones, incidencias o caja.
            return int(
                _get_value(item, "requested_centimos")
                or _get_value(item, "inserted_centimos")
                or _get_value(item, "net_amount_centimos")
                or 0
            )

        return int(_get_value(item, "amount_centimos") or 0)


    def movement_date_for_reconciliation(source, item):
        source = (source or "").lower().strip()
        if source == "cashmatic":
            return str(_get_value(item, "start_time") or "")[:10]
        return str(_get_value(item, "operation_date") or _get_value(item, "value_date") or "")[:10]


    def movement_concept_for_reconciliation(source, item):
        source = (source or "").lower().strip()
        if source == "cashmatic":
            return (
                _get_value(item, "reason_raw")
                or _get_value(item, "reference_raw")
                or _get_value(item, "operation")
                or "Movimiento Cashmatic"
            )
        return _get_value(item, "concept") or "Movimiento bancario"


    def option_id_from_label(value):
        raw = str(value or "").strip()
        if not raw:
            return None

        # Formatos habituales:
        # "13 - Cliente"
        # "#13 · Cliente"
        # "13 | Cliente"
        first = raw.split(" - ", 1)[0].split(" · ", 1)[0].split(" | ", 1)[0]
        first = first.replace("#", "").strip()

        try:
            parsed = int(first)
        except Exception:
            return None

        return parsed if parsed > 0 else None


    def app_autocomplete_control(ac):
        """
        AppAutocomplete es un wrapper Python.
        En layouts Flet hay que insertar su control interno, no el wrapper.
        """
        for attr in ["control", "container", "view", "widget", "root"]:
            value = getattr(ac, attr, None)
            if value is not None:
                return value

        for method_name in ["build", "render", "get_control"]:
            method = getattr(ac, method_name, None)
            if callable(method):
                try:
                    value = method()
                    if value is not None:
                        return value
                except Exception:
                    pass

        # Fallback mínimo para no romper serialización.
        inner = getattr(ac, "field", None) or getattr(ac, "text_field", None) or getattr(ac, "input", None)
        if inner is not None:
            return inner

        return ft.Text("No se pudo renderizar el selector de cliente.", size=12, color="#B91C1C")


    def selected_autocomplete_id(ac):
        for attr in ["selected_id", "value_id", "current_id"]:
            value = getattr(ac, attr, None)
            if value:
                try:
                    return int(value)
                except Exception:
                    pass

        for method_name in ["get_selected_id", "selected_value", "get_value"]:
            method = getattr(ac, method_name, None)
            if callable(method):
                try:
                    parsed = option_id_from_label(method())
                    if parsed:
                        return parsed
                except Exception:
                    pass

        for attr in ["value", "selected_value", "text"]:
            parsed = option_id_from_label(getattr(ac, attr, None))
            if parsed:
                return parsed

        # AppAutocomplete suele envolver un TextField interno.
        for attr in ["field", "text_field", "input", "control"]:
            inner = getattr(ac, attr, None)
            if inner is not None:
                parsed = option_id_from_label(getattr(inner, "value", None))
                if parsed:
                    return parsed

        return None


    def get_client_cobros_for_reconciliation(client_id):
        """
        Devuelve solo cobros del cliente con pendiente real.

        No basta con estado_conciliacion = PENDIENTE, porque el estado puede estar
        desactualizado o venir de legacy. Se calcula pendiente económico real:
        importe cobro - applications - vínculos legacy no migrados.
        """
        import sqlite3

        try:
            client_id = int(client_id or 0)
        except Exception:
            return []

        if client_id <= 0:
            return []

        conn = sqlite3.connect("database/quesada.db")
        conn.row_factory = sqlite3.Row

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_movement_id INTEGER NOT NULL,
                    payment_id INTEGER NOT NULL,
                    client_id INTEGER,
                    expedient_id INTEGER,
                    amount_centimos INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_type, source_movement_id, payment_id)
                )
                """
            )

            rows = conn.execute(
                """
                SELECT
                    c.*,
                    cl.nombre,
                    cl.primer_apellido,
                    cl.segundo_apellido,
                    e.numero_expediente,
                    h.numero_hoja
                FROM eco_cobros c
                LEFT JOIN clientes cl ON cl.id = c.cliente_id
                LEFT JOIN expedientes e ON e.id = c.expediente_id
                LEFT JOIN eco_hojas_encargo h ON h.id = c.hoja_encargo_id
                WHERE c.cliente_id = ?
                  AND COALESCE(c.activo, 1) = 1
                ORDER BY c.fecha_cobro DESC, c.id DESC
                """,
                (client_id,),
            ).fetchall()

            result = []

            for row in rows:
                cobro = dict(row)
                cobro_id = int(cobro.get("id") or 0)
                total = int(round(float(cobro.get("importe") or 0) * 100))

                if cobro_id <= 0 or total <= 0:
                    continue

                applications = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(amount_centimos), 0) AS total
                    FROM economic_reconciliation_applications
                    WHERE payment_id = ?
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                bank_legacy = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(b.linked_amount_centimos, 0), b.amount_centimos, 0)
                    ), 0) AS total
                    FROM bank_movements b
                    WHERE b.linked_payment_id = ?
                      AND b.ignored_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM economic_reconciliation_applications a
                          WHERE a.source_type = 'bank'
                            AND a.source_movement_id = b.id
                            AND a.payment_id = b.linked_payment_id
                      )
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                cashmatic_legacy = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(cm.linked_amount_centimos, 0), cm.requested_centimos, cm.net_amount_centimos, 0)
                    ), 0) AS total
                    FROM cashmatic_movements cm
                    WHERE cm.linked_payment_id = ?
                      AND cm.ignored_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM economic_reconciliation_applications a
                          WHERE a.source_type = 'cashmatic'
                            AND a.source_movement_id = cm.id
                            AND a.payment_id = cm.linked_payment_id
                      )
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                linked = applications + bank_legacy + cashmatic_legacy
                pending = max(0, total - linked)

                if pending <= 0:
                    continue

                cobro["importe_total_centimos"] = total
                cobro["importe_vinculado_centimos"] = linked
                cobro["importe_pendiente_centimos"] = pending
                result.append(cobro)

            return result
        finally:
            conn.close()




    def cobro_option_label(cobro):
        cobro_id = cobro.get("id")
        numero = cobro.get("numero_cobro") or f"COB-{cobro_id}"
        fecha = cobro.get("fecha_cobro") or "-"
        importe = cobro.get("importe") or 0
        concepto = cobro.get("concepto") or ""

        try:
            importe_txt = f"{float(importe):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            importe_txt = f"{importe} €"

        pendiente = cobro.get("importe_pendiente_centimos")
        vinculado = cobro.get("importe_vinculado_centimos")

        extra = ""
        if pendiente not in (None, ""):
            extra = f" · Pendiente: {_money_centimos(pendiente)}"
            if vinculado not in (None, "", 0):
                extra += f" · Vinculado: {_money_centimos(vinculado)}"

        if concepto:
            return f"{cobro_id} - {numero} · {fecha} · {importe_txt}{extra} · {concepto}"
        return f"{cobro_id} - {numero} · {fecha} · {importe_txt}{extra}"


    def update_cobro_as_reconciled(cobro_id, source=None, movement_id=None):
        """
        Recalcula estado_conciliacion del cobro.

        Fuente principal actual:
        - economic_reconciliation_applications

        Compatibilidad:
        - bank_movements.linked_payment_id
        - cashmatic_movements.linked_payment_id

        Importante:
        Desde que un movimiento puede aplicarse a varios cobros, linked_payment_id
        ya no puede ser la fuente principal, porque solo representa un resumen legacy.
        """
        import sqlite3

        try:
            cobro_id = int(cobro_id or 0)
        except Exception:
            return

        if cobro_id <= 0:
            return

        conn = sqlite3.connect("database/quesada.db")
        conn.row_factory = sqlite3.Row

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_movement_id INTEGER NOT NULL,
                    payment_id INTEGER NOT NULL,
                    client_id INTEGER,
                    expedient_id INTEGER,
                    amount_centimos INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_type, source_movement_id, payment_id)
                )
                """
            )

            cobro = conn.execute(
                """
                SELECT id, importe
                FROM eco_cobros
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (cobro_id,),
            ).fetchone()

            if not cobro:
                return

            cobro_amount_centimos = int(round(float(cobro["importe"] or 0) * 100))

            applications_total_centimos = int(conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_reconciliation_applications
                WHERE payment_id = ?
                """,
                (cobro_id,),
            ).fetchone()["total"] or 0)

            # Compatibilidad legacy: solo sumar vínculos antiguos que NO estén ya
            # migrados a applications, para evitar doble cómputo.
            bank_legacy_centimos = int(conn.execute(
                """
                SELECT COALESCE(SUM(
                    COALESCE(NULLIF(b.linked_amount_centimos, 0), b.amount_centimos, 0)
                ), 0) AS total
                FROM bank_movements b
                WHERE b.linked_payment_id = ?
                  AND b.ignored_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM economic_reconciliation_applications a
                      WHERE a.source_type = 'bank'
                        AND a.source_movement_id = b.id
                        AND a.payment_id = b.linked_payment_id
                  )
                """,
                (cobro_id,),
            ).fetchone()["total"] or 0)

            cashmatic_legacy_centimos = int(conn.execute(
                """
                SELECT COALESCE(SUM(
                    COALESCE(NULLIF(c.linked_amount_centimos, 0), c.requested_centimos, c.net_amount_centimos, 0)
                ), 0) AS total
                FROM cashmatic_movements c
                WHERE c.linked_payment_id = ?
                  AND c.ignored_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM economic_reconciliation_applications a
                      WHERE a.source_type = 'cashmatic'
                        AND a.source_movement_id = c.id
                        AND a.payment_id = c.linked_payment_id
                  )
                """,
                (cobro_id,),
            ).fetchone()["total"] or 0)

            linked_total_centimos = (
                applications_total_centimos
                + bank_legacy_centimos
                + cashmatic_legacy_centimos
            )

            if linked_total_centimos <= 0:
                status = "PENDIENTE"
            elif linked_total_centimos < cobro_amount_centimos:
                status = "PARCIAL"
            elif linked_total_centimos == cobro_amount_centimos:
                status = "CONCILIADO"
            else:
                status = "SOBRANTE_REVISION"

            conn.execute(
                """
                UPDATE eco_cobros
                SET estado_conciliacion = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, cobro_id),
            )

            conn.commit()
        finally:
            conn.close()



    def show_reconciliation_dialog(dialog):
        """
        La vista económica abre sus dialogs como variables persistentes:
        cobro_dialog.open = True; page.update().
        Por tanto copiamos ese patrón en lugar de usar page.dialog/page.open/overlay.
        """
        reconciliation_dialog.title = dialog.title
        reconciliation_dialog.content = dialog.content
        reconciliation_dialog.actions = dialog.actions
        reconciliation_dialog.actions_alignment = dialog.actions_alignment
        reconciliation_dialog.modal = True

        try:
            if reconciliation_dialog not in page.overlay:
                page.overlay.append(reconciliation_dialog)
        except Exception:
            pass

        reconciliation_dialog.open = True
        page.update()




    reconciliation_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Conciliar movimiento"),
        content=ft.Container(width=760, content=ft.Text("")),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.END,
    )


    def _expense_reconciliation_label(expense):
        supplier = str(
            expense.get("supplier_display_name")
            or "Sin proveedor"
        ).strip()
        concept = str(
            expense.get("concepto")
            or "Sin concepto"
        ).strip()
        date_value = _date_to_display(
            expense.get("fecha_gasto")
        )
        pending = _money_centimos(
            expense.get("pending_centimos")
            or 0
        )

        return (
            f"{expense.get('id')} - "
            f"{supplier} · {date_value} · "
            f"{concept} · Pendiente {pending}"
        )


    def open_negative_movement_reconciliation(
        source,
        item,
    ):
        source = str(source or "").lower().strip()

        if source == "cashmatic":
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    "Los gastos se concilian contra "
                    "movimientos bancarios negativos."
                ),
                open=True,
            )
            page.update()
            return

        movement_id = int(
            _get_value(item, "id") or 0
        )

        if movement_id <= 0:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    "No se pudo identificar el movimiento."
                ),
                open=True,
            )
            page.update()
            return

        try:
            summary = (
                expense_reconciliation_service
                .get_movement_summary(
                    movement_id
                )
            )
        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(str(exc)),
                open=True,
            )
            page.update()
            return

        movement = summary["movement"]
        movement_total = int(
            summary["total_centimos"] or 0
        )
        movement_applied = int(
            summary["applied_centimos"] or 0
        )
        movement_pending = int(
            summary["pending_centimos"] or 0
        )

        expenses = (
            expense_reconciliation_service
            .list_reconcilable_expenses(
                limit=2000,
            )
        )

        option_map = {}
        options = []

        for expense in expenses:
            label = _expense_reconciliation_label(
                expense
            )
            option_map[label] = expense

            options.append(
                {
                    "id": expense.get("id"),
                    "label": label,
                    "subtitle": (
                        expense.get("numero_factura")
                        or expense.get("categoria")
                        or ""
                    ),
                }
            )

        selected_expense = {
            "row": None,
        }

        amount_input = text_input(
            "Importe a aplicar",
            width=190,
        )
        amount_input.value = (
            f"{movement_pending / 100:.2f}"
            .replace(".", ",")
        )

        notes_input = multiline_input(
            "Notas de conciliación",
            width=690,
            height=90,
        )

        selection_summary = ft.Container()
        applications_box = ft.Container()
        message_box = ft.Container()

        def set_message(message, error=False):
            message_box.content = ft.Container(
                bgcolor=(
                    "#FEF3F2"
                    if error
                    else "#F8FAFC"
                ),
                border=ft.border.all(
                    1,
                    (
                        "#FDA29B"
                        if error
                        else Q_BORDER
                    ),
                ),
                border_radius=10,
                padding=10,
                content=ft.Text(
                    str(message or ""),
                    size=12,
                    color=(
                        "#B42318"
                        if error
                        else Q_MUTED
                    ),
                ),
            )

            try:
                message_box.update()
            except Exception:
                pass

        def expense_selected(value):
            label = str(value or "").strip()
            expense = option_map.get(label)
            selected_expense["row"] = expense

            if not expense:
                selection_summary.content = None
                return

            expense_pending = int(
                expense.get("pending_centimos")
                or 0
            )
            applicable = min(
                movement_pending,
                expense_pending,
            )

            amount_input.value = (
                f"{applicable / 100:.2f}"
                .replace(".", ",")
            )

            selection_summary.content = ft.Container(
                bgcolor="#EFF8FF",
                border=ft.border.all(
                    1,
                    "#84CAFF",
                ),
                border_radius=10,
                padding=12,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            str(
                                expense.get(
                                    "supplier_display_name"
                                )
                                or "Sin proveedor"
                            ).upper(),
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            expense.get("concepto")
                            or "Sin concepto",
                            size=12,
                            color="#344054",
                        ),
                        ft.Row(
                            controls=[
                                ft.Text(
                                    "Total: "
                                    + _money_centimos(
                                        expense.get(
                                            "effective_total_centimos"
                                        )
                                        or 0
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    "Aplicado: "
                                    + _money_centimos(
                                        expense.get(
                                            "applied_centimos"
                                        )
                                        or 0
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    "Pendiente: "
                                    + _money_centimos(
                                        expense_pending
                                    ),
                                    size=11,
                                    weight=ft.FontWeight.BOLD,
                                    color="#B54708",
                                ),
                            ],
                            spacing=14,
                            wrap=True,
                        ),
                    ],
                    spacing=5,
                ),
            )

            try:
                amount_input.update()
                selection_summary.update()
            except Exception:
                pass

        expense_ac = AppAutocomplete(
            page=page,
            label="Gasto pendiente",
            options=options,
            width=690,
            max_results=10,
            on_select=expense_selected,
            allow_free_text=False,
            hint_text=(
                "Busca por proveedor, concepto, "
                "factura o ID"
            ),
            empty_text=(
                "No hay gastos pendientes "
                "que coincidan"
            ),
        )

        def parse_amount_centimos():
            raw = str(
                amount_input.value or ""
            ).strip()

            if not raw:
                raise ValueError(
                    "Indica el importe a aplicar."
                )

            normalized = raw.replace(" ", "")

            if (
                "," in normalized
                and "." in normalized
            ):
                if (
                    normalized.rfind(",")
                    > normalized.rfind(".")
                ):
                    normalized = (
                        normalized
                        .replace(".", "")
                        .replace(",", ".")
                    )
                else:
                    normalized = (
                        normalized.replace(",", "")
                    )
            else:
                normalized = normalized.replace(
                    ",",
                    ".",
                )

            amount = int(
                round(float(normalized) * 100)
            )

            if amount <= 0:
                raise ValueError(
                    "El importe debe ser mayor que cero."
                )

            return amount

        def reopen_dialog():
            current_item = dict(item)

            try:
                state.setdefault(
                    "movements_cache",
                    {},
                ).pop(source, None)
            except Exception:
                state["movements_cache"] = {}

            open_negative_movement_reconciliation(
                source,
                current_item,
            )

        def remove_application(
            application_id,
        ):
            def handler(e=None):
                try:
                    (
                        expense_reconciliation_service
                        .remove_expense_reconciliation(
                            int(application_id),
                            reason=(
                                "Retirada manual desde "
                                "Económico > Movimientos"
                            ),
                        )
                    )

                    show_message(
                        success_alert(
                            "Aplicación retirada"
                        )
                    )

                    reopen_dialog()

                except Exception as exc:
                    set_message(
                        str(exc),
                        error=True,
                    )

            return handler

        application_controls = []

        for application in summary["applications"]:
            supplier = (
                application.get(
                    "supplier_name_snapshot"
                )
                or application.get("proveedor")
                or "Sin proveedor"
            )

            application_controls.append(
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(
                        1,
                        Q_BORDER,
                    ),
                    border_radius=10,
                    padding=10,
                    content=ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        str(supplier),
                                        size=12,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        application.get(
                                            "concepto"
                                        )
                                        or "Sin concepto",
                                        size=11,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        "Aplicado: "
                                        + _money_centimos(
                                            application.get(
                                                "amount_centimos"
                                            )
                                            or 0
                                        ),
                                        size=11,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color="#027A48",
                                    ),
                                ],
                                spacing=2,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color="#B42318",
                                tooltip=(
                                    "Retirar esta aplicación"
                                ),
                                on_click=remove_application(
                                    application.get("id")
                                ),
                            ),
                        ],
                        alignment=(
                            ft.MainAxisAlignment
                            .SPACE_BETWEEN
                        ),
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                )
            )

        if application_controls:
            applications_box.content = ft.Column(
                controls=[
                    ft.Text(
                        "Aplicaciones registradas",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    *application_controls,
                ],
                spacing=8,
            )
        else:
            applications_box.content = ft.Text(
                "El movimiento todavía no tiene "
                "gastos aplicados.",
                size=12,
                color=Q_MUTED,
                italic=True,
            )

        def apply_to_existing_expense(e=None):
            expense = selected_expense.get(
                "row"
            )

            if not expense:
                set_message(
                    "Selecciona un gasto pendiente.",
                    error=True,
                )
                return

            try:
                amount_centimos = (
                    parse_amount_centimos()
                )

                (
                    expense_reconciliation_service
                    .apply_expense_reconciliation(
                        movement_id=movement_id,
                        expense_id=int(
                            expense.get("id")
                        ),
                        amount_centimos=(
                            amount_centimos
                        ),
                        notes=notes_input.value,
                    )
                )

                show_message(
                    success_alert(
                        "Gasto conciliado con "
                        "el movimiento"
                    )
                )

                reopen_dialog()

            except Exception as exc:
                set_message(
                    str(exc),
                    error=True,
                )

        def create_expense_from_movement(e=None):
            if movement_pending <= 0:
                set_message(
                    "El movimiento ya está "
                    "completamente aplicado.",
                    error=True,
                )
                return

            movement_bank_name = (
                movement.get("bank_name")
                or ""
            )
            movement_concept = (
                movement.get("concept")
                or ""
            )

            try:
                classification_suggestion = (
                    expense_classification_service
                    .suggest_for_movement(
                        bank_name=movement_bank_name,
                        concept=movement_concept,
                    )
                )
            except Exception:
                classification_suggestion = None

            state[
                "pending_expense_from_movement"
            ] = {
                "source": source,
                "movement_id": movement_id,
                "date": (
                    movement.get(
                        "operation_date"
                    )
                    or ""
                ),
                "concept": movement_concept,
                "amount_centimos": (
                    movement_pending
                ),
                "bank_name": movement_bank_name,
                "classification_suggestion": (
                    classification_suggestion
                ),
            }

            reconciliation_dialog.open = False
            open_gasto_dialog()

        summary_box = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Text(
                        (
                            str(
                                movement.get(
                                    "bank_name"
                                )
                                or "Banco"
                            )
                            + " · "
                            + _date_to_display(
                                movement.get(
                                    "operation_date"
                                )
                            )
                        ),
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        movement.get("concept")
                        or "Sin concepto",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Movimiento: "
                                + _money_centimos(
                                    movement_total
                                ),
                                size=12,
                                color="#B42318",
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                "Aplicado: "
                                + _money_centimos(
                                    movement_applied
                                ),
                                size=12,
                                color="#027A48",
                            ),
                            ft.Text(
                                "Pendiente: "
                                + _money_centimos(
                                    movement_pending
                                ),
                                size=12,
                                color="#B54708",
                                weight=ft.FontWeight.BOLD,
                            ),
                        ],
                        spacing=18,
                        wrap=True,
                    ),
                ],
                spacing=6,
            ),
        )

        content = ft.Column(
            controls=[
                summary_box,
                applications_box,
                ft.Divider(height=1),
                ft.Text(
                    "Aplicar a un gasto existente",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                expense_ac.control,
                selection_summary,
                ft.Row(
                    controls=[
                        amount_input,
                        ft.Container(
                            content=ft.Text(
                                (
                                    "El importe no puede superar "
                                    "el pendiente del movimiento "
                                    "ni el pendiente del gasto."
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            width=470,
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                notes_input,
                message_box,
            ],
            width=730,
            height=580,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.RECEIPT_LONG_OUTLINED,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "Conciliar salida bancaria",
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                ],
                spacing=8,
            ),
            content=content,
            actions=[
                secondary_button(
                    "Cerrar",
                    lambda e: close(
                        reconciliation_dialog
                    ),
                ),
                secondary_button(
                    "Crear gasto desde movimiento",
                    create_expense_from_movement,
                ),
                primary_button(
                    "Aplicar al gasto",
                    apply_to_existing_expense,
                ),
            ],
            actions_alignment=(
                ft.MainAxisAlignment.END
            ),
        )

        show_reconciliation_dialog(dialog)


    def open_movement_reconciliation_action(source, item):
        if not is_movement_reconcilable(source, item):
            page.snack_bar = ft.SnackBar(
                ft.Text(
                    "Cashmatic: solo los movimientos payment candidatos son conciliables. "
                    "Este movimiento es interno, revisión o cuarentena."
                )
            )
            page.snack_bar.open = True
            page.update()
            return

        source = (source or "").lower().strip()
        movement_id = int(_get_value(item, "id") or 0)
        amount_centimos = movement_amount_centimos_for_reconciliation(source, item)

        if int(amount_centimos or 0) < 0:
            open_negative_movement_reconciliation(
                source,
                item,
            )
            return

        if int(amount_centimos or 0) == 0:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    "No se puede conciliar un "
                    "movimiento de importe cero."
                ),
                open=True,
            )
            page.update()
            return
        movement_date = movement_date_for_reconciliation(source, item)
        movement_concept = movement_concept_for_reconciliation(source, item)

        state["movement_to_reconcile"] = {
            "source": source,
            "id": movement_id,
            "amount_centimos": amount_centimos,
            "date": movement_date,
            "concept": movement_concept,
        }

        if movement_id <= 0:
            page.snack_bar = ft.SnackBar(ft.Text("No se pudo identificar el movimiento."))
            page.snack_bar.open = True
            page.update()
            return

        if amount_centimos == 0:
            page.snack_bar = ft.SnackBar(ft.Text("No se puede conciliar un movimiento con importe cero."))
            page.snack_bar.open = True
            page.update()
            return

        def get_client_ids_with_pending_cobros_for_reconciliation():
            """
            Devuelve clientes que tienen al menos un cobro con pendiente real.

            Usa:
            - eco_cobros.importe como total del cobro;
            - economic_reconciliation_applications como fuente principal;
            - legacy bank/cashmatic linked_payment_id solo si no está migrado a applications.
            """
            import sqlite3

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_type TEXT NOT NULL,
                        source_movement_id INTEGER NOT NULL,
                        payment_id INTEGER NOT NULL,
                        client_id INTEGER,
                        expedient_id INTEGER,
                        amount_centimos INTEGER NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_type, source_movement_id, payment_id)
                    )
                    """
                )

                rows = conn.execute(
                    """
                    SELECT
                        c.id AS cobro_id,
                        c.cliente_id,
                        c.importe
                    FROM eco_cobros c
                    WHERE COALESCE(c.activo, 1) = 1
                    """
                ).fetchall()

                client_ids = set()

                for row in rows:
                    cobro_id = int(row["cobro_id"] or 0)
                    client_id = int(row["cliente_id"] or 0)
                    total = int(round(float(row["importe"] or 0) * 100))

                    if cobro_id <= 0 or client_id <= 0 or total <= 0:
                        continue

                    applications = int(conn.execute(
                        """
                        SELECT COALESCE(SUM(amount_centimos), 0) AS total
                        FROM economic_reconciliation_applications
                        WHERE payment_id = ?
                        """,
                        (cobro_id,),
                    ).fetchone()["total"] or 0)

                    bank_legacy = int(conn.execute(
                        """
                        SELECT COALESCE(SUM(
                            COALESCE(NULLIF(b.linked_amount_centimos, 0), b.amount_centimos, 0)
                        ), 0) AS total
                        FROM bank_movements b
                        WHERE b.linked_payment_id = ?
                          AND b.ignored_at IS NULL
                          AND NOT EXISTS (
                              SELECT 1
                              FROM economic_reconciliation_applications a
                              WHERE a.source_type = 'bank'
                                AND a.source_movement_id = b.id
                                AND a.payment_id = b.linked_payment_id
                          )
                        """,
                        (cobro_id,),
                    ).fetchone()["total"] or 0)

                    cashmatic_legacy = int(conn.execute(
                        """
                        SELECT COALESCE(SUM(
                            COALESCE(NULLIF(cm.linked_amount_centimos, 0), cm.requested_centimos, cm.net_amount_centimos, 0)
                        ), 0) AS total
                        FROM cashmatic_movements cm
                        WHERE cm.linked_payment_id = ?
                          AND cm.ignored_at IS NULL
                          AND NOT EXISTS (
                              SELECT 1
                              FROM economic_reconciliation_applications a
                              WHERE a.source_type = 'cashmatic'
                                AND a.source_movement_id = cm.id
                                AND a.payment_id = cm.linked_payment_id
                          )
                        """,
                        (cobro_id,),
                    ).fetchone()["total"] or 0)

                    linked = applications + bank_legacy + cashmatic_legacy
                    pending = total - linked

                    if pending > 0:
                        client_ids.add(client_id)

                return client_ids
            finally:
                conn.close()


        def client_option_id_for_reconciliation(option):
            """
            Extrae id de cliente desde las opciones usadas por AppAutocomplete.
            Soporta dicts y labels tipo '12 - Nombre'.
            """
            if isinstance(option, dict):
                for key in ["id", "cliente_id", "value"]:
                    value = option.get(key)
                    if value not in (None, ""):
                        try:
                            return int(value)
                        except Exception:
                            pass

            try:
                parsed = option_id_from_label(option)
                if parsed not in (None, ""):
                    return int(parsed)
            except Exception:
                pass

            raw = str(option or "").strip()
            if " - " in raw:
                raw = raw.split(" - ", 1)[0].strip()

            try:
                return int(raw)
            except Exception:
                return None


        pending_client_ids = get_client_ids_with_pending_cobros_for_reconciliation()
        reconciliation_cliente_options = [
            option
            for option in cliente_options
            if client_option_id_for_reconciliation(option) in pending_client_ids
        ]

        client_ac = AppAutocomplete(
            page,
            "Cliente con cobros pendientes",
            reconciliation_cliente_options,
            width=520,
            max_results=12,
        )
        cobro_dropdown = ft.Dropdown(
            label="Cobro existente",
            width=720,
            options=[],
            disabled=True,
        )

        message_box = ft.Container()
        movement_summary_box = ft.Container()
        selected_client_id_box = {"value": None}

        def set_message(text_value, is_error=False):
            message_box.content = ft.Container(
                content=ft.Text(
                    text_value,
                    size=12,
                    color="#B91C1C" if is_error else Q_MUTED,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=8),
                border_radius=10,
                bgcolor="#FEF2F2" if is_error else "#F8FAFC",
                border=ft.border.all(1, "#FCA5A5" if is_error else Q_BORDER),
            )
            try:
                message_box.update()
            except Exception:
                pass

        def get_cobro_reconciliation_amounts(cobro_id):
            """
            Devuelve total, ya aplicado y pendiente del cobro para mostrarlo en UI.
            """
            import sqlite3

            try:
                cobro_id = int(cobro_id or 0)
            except Exception:
                return {"total": 0, "linked": 0, "pending": 0}

            if cobro_id <= 0:
                return {"total": 0, "linked": 0, "pending": 0}

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                cobro = conn.execute(
                    """
                    SELECT id, importe
                    FROM eco_cobros
                    WHERE id = ?
                      AND COALESCE(activo, 1) = 1
                    """,
                    (cobro_id,),
                ).fetchone()

                if not cobro:
                    return {"total": 0, "linked": 0, "pending": 0}

                total = int(round(float(cobro["importe"] or 0) * 100))

                bank = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(linked_amount_centimos, 0), amount_centimos, 0)
                    ), 0) AS total
                    FROM bank_movements
                    WHERE linked_payment_id = ?
                      AND ignored_at IS NULL
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                cashmatic = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(linked_amount_centimos, 0), requested_centimos, net_amount_centimos, 0)
                    ), 0) AS total
                    FROM cashmatic_movements
                    WHERE linked_payment_id = ?
                      AND ignored_at IS NULL
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                linked = bank + cashmatic
                pending = max(0, total - linked)

                return {"total": total, "linked": linked, "pending": pending}
            finally:
                conn.close()


        def cobro_option_label_with_pending(cobro):
            cobro_id = cobro.get("id") if isinstance(cobro, dict) else None
            return cobro_option_label(cobro)



        def ensure_reconciliation_applications_table():
            """
            Tabla puente para permitir que un mismo movimiento importado
            se aplique a varios cobros.

            Los campos linked_* de bank_movements/cashmatic_movements quedan
            como resumen legacy, pero ya no bloquean la aplicación parcial.
            """
            import sqlite3

            conn = sqlite3.connect("database/quesada.db")
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_type TEXT NOT NULL,
                        source_movement_id INTEGER NOT NULL,
                        payment_id INTEGER NOT NULL,
                        client_id INTEGER,
                        expedient_id INTEGER,
                        amount_centimos INTEGER NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_type, source_movement_id, payment_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_era_source
                    ON economic_reconciliation_applications(source_type, source_movement_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_era_payment
                    ON economic_reconciliation_applications(payment_id)
                    """
                )
                conn.commit()
            finally:
                conn.close()


        def seed_current_movement_legacy_link_to_applications():
            """
            Si el movimiento ya tenía linked_payment_id antes de existir
            applications, crea la aplicación equivalente una sola vez.
            """
            import sqlite3

            ensure_reconciliation_applications_table()

            source_type = "cashmatic" if source == "cashmatic" else "bank"
            table = "cashmatic_movements" if source == "cashmatic" else "bank_movements"

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                row = conn.execute(
                    f"""
                    SELECT
                        id,
                        linked_payment_id,
                        linked_client_id,
                        linked_expedient_id,
                        linked_amount_centimos,
                        link_notes
                    FROM {table}
                    WHERE id = ?
                    """,
                    (movement_id,),
                ).fetchone()

                if not row:
                    return

                payment_id = row["linked_payment_id"]
                amount = int(row["linked_amount_centimos"] or 0)

                if not payment_id or amount <= 0:
                    return

                exists = conn.execute(
                    """
                    SELECT id
                    FROM economic_reconciliation_applications
                    WHERE source_type = ?
                      AND source_movement_id = ?
                      AND payment_id = ?
                    """,
                    (source_type, movement_id, payment_id),
                ).fetchone()

                if exists:
                    return

                conn.execute(
                    """
                    INSERT INTO economic_reconciliation_applications (
                        source_type,
                        source_movement_id,
                        payment_id,
                        client_id,
                        expedient_id,
                        amount_centimos,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_type,
                        movement_id,
                        payment_id,
                        row["linked_client_id"],
                        row["linked_expedient_id"],
                        amount,
                        row["link_notes"] or "Migrado desde vínculo legacy linked_payment_id",
                    ),
                )

                conn.commit()
            finally:
                conn.close()


        def sync_current_movement_legacy_summary_from_applications():
            """
            Recalcula los campos linked_* del movimiento como resumen:
            - linked_amount_centimos = total aplicado;
            - linked_payment_id = primer cobro vinculado, solo como referencia legacy.
            """
            import sqlite3

            ensure_reconciliation_applications_table()

            source_type = "cashmatic" if source == "cashmatic" else "bank"
            table = "cashmatic_movements" if source == "cashmatic" else "bank_movements"

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                summary = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(amount_centimos), 0) AS total,
                        MIN(payment_id) AS first_payment_id,
                        MIN(client_id) AS first_client_id,
                        MIN(expedient_id) AS first_expedient_id
                    FROM economic_reconciliation_applications
                    WHERE source_type = ?
                      AND source_movement_id = ?
                    """,
                    (source_type, movement_id),
                ).fetchone()

                total = int(summary["total"] or 0)
                first_payment_id = summary["first_payment_id"]
                first_client_id = summary["first_client_id"]
                first_expedient_id = summary["first_expedient_id"]

                conn.execute(
                    f"""
                    UPDATE {table}
                    SET
                        linked_payment_id = ?,
                        linked_client_id = ?,
                        linked_expedient_id = ?,
                        linked_amount_centimos = ?,
                        linked_target_type = CASE WHEN ? > 0 THEN 'payment' ELSE linked_target_type END,
                        linked_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE linked_at END
                    WHERE id = ?
                    """,
                    (
                        first_payment_id,
                        first_client_id,
                        first_expedient_id,
                        total,
                        total,
                        total,
                        movement_id,
                    ),
                )

                conn.commit()
            finally:
                conn.close()


        def apply_reconciliation_application(cobro_id, client_id, applied_amount_centimos, notes):
            """
            Inserta una aplicación parcial/total del movimiento contra un cobro.

            Permite varios cobros por movimiento.
            """
            import sqlite3

            ensure_reconciliation_applications_table()
            seed_current_movement_legacy_link_to_applications()

            source_type = "cashmatic" if source == "cashmatic" else "bank"

            cobro_id = int(cobro_id or 0)
            client_id = int(client_id or 0) if client_id else None
            applied_amount_centimos = int(applied_amount_centimos or 0)

            if cobro_id <= 0:
                raise ValueError("Selecciona un cobro válido.")

            if applied_amount_centimos <= 0:
                raise ValueError("No hay importe pendiente para aplicar.")

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                existing = conn.execute(
                    """
                    SELECT id, amount_centimos
                    FROM economic_reconciliation_applications
                    WHERE source_type = ?
                      AND source_movement_id = ?
                      AND payment_id = ?
                    """,
                    (source_type, movement_id, cobro_id),
                ).fetchone()

                if existing:
                    new_amount = int(existing["amount_centimos"] or 0) + applied_amount_centimos
                    conn.execute(
                        """
                        UPDATE economic_reconciliation_applications
                        SET amount_centimos = ?,
                            client_id = COALESCE(client_id, ?),
                            notes = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (new_amount, client_id, notes, existing["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO economic_reconciliation_applications (
                            source_type,
                            source_movement_id,
                            payment_id,
                            client_id,
                            amount_centimos,
                            notes
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_type,
                            movement_id,
                            cobro_id,
                            client_id,
                            applied_amount_centimos,
                            notes,
                        ),
                    )

                conn.commit()
            finally:
                conn.close()

            sync_current_movement_legacy_summary_from_applications()


        def get_current_movement_reconciliation_summary():
            """
            Lee el estado real del movimiento seleccionado usando applications.
            """
            import sqlite3

            ensure_reconciliation_applications_table()
            seed_current_movement_legacy_link_to_applications()

            movement_abs = abs(int(amount_centimos or 0))
            source_type = "cashmatic" if source == "cashmatic" else "bank"
            table = "cashmatic_movements" if source == "cashmatic" else "bank_movements"
            amount_field = "requested_centimos" if source == "cashmatic" else "amount_centimos"

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                movement_row = conn.execute(
                    f"""
                    SELECT id, {amount_field} AS movement_amount_centimos
                    FROM {table}
                    WHERE id = ?
                    """,
                    (movement_id,),
                ).fetchone()

                if movement_row:
                    movement_abs = abs(int(movement_row["movement_amount_centimos"] or movement_abs or 0))

                rows = conn.execute(
                    """
                    SELECT
                        a.id,
                        a.payment_id,
                        a.amount_centimos,
                        a.created_at,
                        c.numero_cobro,
                        c.estado_conciliacion,
                        cl.nombre,
                        cl.primer_apellido,
                        cl.segundo_apellido
                    FROM economic_reconciliation_applications a
                    LEFT JOIN eco_cobros c ON c.id = a.payment_id
                    LEFT JOIN clientes cl ON cl.id = c.cliente_id
                    WHERE a.source_type = ?
                      AND a.source_movement_id = ?
                    ORDER BY a.created_at ASC, a.id ASC
                    """,
                    (source_type, movement_id),
                ).fetchall()

                linked_rows = []
                linked_total = 0

                for row in rows:
                    amount = abs(int(row["amount_centimos"] or 0))
                    linked_total += amount

                    cliente = " ".join(
                        str(row[x] or "").strip()
                        for x in ["nombre", "primer_apellido", "segundo_apellido"]
                    ).strip()

                    linked_rows.append(
                        {
                            "payment_id": row["payment_id"],
                            "numero_cobro": row["numero_cobro"] or f"Cobro #{row['payment_id']}",
                            "cliente": cliente,
                            "amount": amount,
                            "estado": row["estado_conciliacion"] or "",
                            "linked_at": row["created_at"] or "",
                        }
                    )

                pending = max(0, movement_abs - linked_total)

                return {
                    "movement_amount": movement_abs,
                    "linked_total": linked_total,
                    "pending": pending,
                    "linked_rows": linked_rows,
                }
            finally:
                conn.close()


        def render_movement_summary_card(cobro_id=None):
            """
            Card principal del movimiento dentro del diálogo.

            Debe mostrar por defecto:
            - movimiento;
            - cobros ya vinculados;
            - total aplicado;
            - pendiente/sobrante por vincular.
            """
            summary = get_current_movement_reconciliation_summary()

            movement_abs = int(summary["movement_amount"] or 0)
            already_applied = int(summary["linked_total"] or 0)
            movement_pending = int(summary["pending"] or 0)
            linked_rows = summary.get("linked_rows") or []

            controls = [
                ft.Text("Movimiento seleccionado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(f"Origen: {source}", size=12, color=Q_MUTED),
                ft.Text(f"Movimiento: {movement_id}", size=12, color=Q_MUTED),
                ft.Text(f"Fecha: {movement_date}", size=12, color=Q_MUTED),
                ft.Text(f"Concepto: {movement_concept}", size=12, color=Q_MUTED, selectable=True),
                ft.Divider(height=8),
                ft.Text(
                    f"Importe movimiento: {_money_centimos(movement_abs)}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    f"Total ya vinculado: {_money_centimos(already_applied)}",
                    size=12,
                    color="#16A34A" if already_applied else Q_MUTED,
                ),
                ft.Text(
                    f"Pendiente por vincular: {_money_centimos(movement_pending)}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color="#F59E0B" if movement_pending else "#16A34A",
                ),
            ]

            controls.append(ft.Divider(height=8))
            controls.append(
                ft.Text(
                    "Cobros vinculados",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                )
            )

            if linked_rows:
                for linked in linked_rows:
                    linked_label = linked.get("numero_cobro") or f"Cobro #{linked.get('payment_id')}"
                    cliente = linked.get("cliente") or "-"
                    estado = linked.get("estado") or "-"
                    controls.append(
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        f"{linked_label} · {_money_centimos(linked.get('amount') or 0)}",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(f"Cliente: {cliente}", size=11, color=Q_MUTED),
                                    ft.Text(f"Estado cobro: {estado}", size=11, color=Q_MUTED),
                                ],
                                spacing=2,
                                tight=True,
                            ),
                            padding=ft.padding.symmetric(horizontal=10, vertical=7),
                            border_radius=10,
                            bgcolor="#FFFFFF",
                            border=ft.border.all(1, Q_BORDER),
                        )
                    )
            else:
                controls.append(
                    ft.Text("Todavía no hay cobros vinculados a este movimiento.", size=12, color=Q_MUTED)
                )

            try:
                selected_cobro_id = int(cobro_id or 0)
            except Exception:
                selected_cobro_id = 0

            if selected_cobro_id > 0:
                amounts = get_cobro_reconciliation_amounts(selected_cobro_id)
                cobro_pending = int(amounts["pending"] or 0)
                applied_preview = min(movement_pending, cobro_pending)
                remaining_preview = max(0, movement_pending - applied_preview)

                controls.extend(
                    [
                        ft.Divider(height=8),
                        ft.Text("Nuevo cobro seleccionado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Text(f"Cobro total: {_money_centimos(amounts['total'])}", size=12, color=Q_MUTED),
                        ft.Text(f"Ya aplicado al cobro: {_money_centimos(amounts['linked'])}", size=12, color=Q_MUTED),
                        ft.Text(
                            f"Pendiente del cobro: {_money_centimos(cobro_pending)}",
                            size=12,
                            color="#F59E0B" if cobro_pending else "#16A34A",
                        ),
                        ft.Text(
                            f"Se aplicará ahora: {_money_centimos(applied_preview)}",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            f"Pendiente que quedará en el movimiento: {_money_centimos(remaining_preview)}",
                            size=12,
                            color="#F59E0B" if remaining_preview else "#16A34A",
                        ),
                    ]
                )

            movement_summary_box.content = ft.Container(
                content=ft.Column(controls=controls, spacing=4, tight=True),
                padding=ft.padding.all(12),
                border_radius=12,
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
            )

            try:
                movement_summary_box.update()
            except Exception:
                pass


        def refresh_selected_cobro_pending_message(e=None):
            cobro_id = option_id_from_label(cobro_dropdown.value) or cobro_dropdown.value

            try:
                cobro_id = int(cobro_id or 0)
            except Exception:
                cobro_id = 0

            render_movement_summary_card(cobro_id)

            if cobro_id <= 0:
                set_message("Selecciona un cobro para continuar.")
                return

            amounts = get_cobro_reconciliation_amounts(cobro_id)
            if int(amounts["pending"] or 0) <= 0:
                set_message("Este cobro ya no tiene importe pendiente.", is_error=True)
            else:
                set_message("Revisa el resumen del movimiento y pulsa Guardar vinculación.")

        cobro_dropdown.on_change = refresh_selected_cobro_pending_message

        def refresh_cobros(e=None):
            client_id = selected_autocomplete_id(client_ac)
            selected_client_id_box["value"] = client_id

            if not client_id:
                cobro_dropdown.options = []
                cobro_dropdown.value = None
                cobro_dropdown.disabled = True
                set_message("Selecciona primero un cliente para cargar sus cobros pendientes.")
                try:
                    cobro_dropdown.update()
                except Exception:
                    pass
                return

            cobros = get_client_cobros_for_reconciliation(client_id)
            cobro_dropdown.options = [
                ft.dropdown.Option(str(c.get("id")), cobro_option_label(c))
                for c in cobros
            ]
            cobro_dropdown.value = None
            cobro_dropdown.disabled = False if cobros else True

            if cobros:
                set_message(f"Cobros pendientes encontrados para el cliente: {len(cobros)}")
            else:
                set_message("Este cliente no tiene cobros pendientes para vincular.", is_error=True)

            try:
                cobro_dropdown.update()
            except Exception:
                pass

        def close_dialog(e=None):
            reconciliation_dialog.open = False
            page.update()

        def get_cobro_pending_centimos(cobro_id):
            """
            Devuelve cuánto queda pendiente de aplicar al cobro.

            eco_cobros.importe está en euros.
            Los movimientos importados guardan importes en céntimos.
            """
            import sqlite3

            try:
                cobro_id = int(cobro_id or 0)
            except Exception:
                return 0

            if cobro_id <= 0:
                return 0

            conn = sqlite3.connect("database/quesada.db")
            conn.row_factory = sqlite3.Row

            try:
                cobro = conn.execute(
                    """
                    SELECT id, importe
                    FROM eco_cobros
                    WHERE id = ?
                      AND COALESCE(activo, 1) = 1
                    """,
                    (cobro_id,),
                ).fetchone()

                if not cobro:
                    return 0

                total_centimos = int(round(float(cobro["importe"] or 0) * 100))

                bank_linked_centimos = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(linked_amount_centimos, 0), amount_centimos, 0)
                    ), 0) AS total
                    FROM bank_movements
                    WHERE linked_payment_id = ?
                      AND ignored_at IS NULL
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                cashmatic_linked_centimos = int(conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE(NULLIF(linked_amount_centimos, 0), requested_centimos, net_amount_centimos, 0)
                    ), 0) AS total
                    FROM cashmatic_movements
                    WHERE linked_payment_id = ?
                      AND ignored_at IS NULL
                    """,
                    (cobro_id,),
                ).fetchone()["total"] or 0)

                pending = total_centimos - bank_linked_centimos - cashmatic_linked_centimos
                return max(0, int(pending))
            finally:
                conn.close()

        def generate_linked_cobro_from_movement(e=None):
            """
            Inicia flujo:
            conciliación -> pestaña Cobros -> nuevo cobro precargado -> vuelta a conciliación.
            """
            summary = get_current_movement_reconciliation_summary()
            pending = int(summary.get("pending") or 0)

            if pending <= 0:
                set_message("Este movimiento no tiene importe pendiente para generar un cobro.", is_error=True)
                return

            selected_client_id = selected_autocomplete_id(client_ac)
            if not selected_client_id:
                selected_client_id = selected_client_id_box.get("value")

            try:
                movement_item_snapshot = dict(item)
            except Exception:
                movement_item_snapshot = {}

            state["pending_linked_cobro_from_reconciliation"] = {
                "source": source,
                "movement_id": movement_id,
                "movement_item": movement_item_snapshot,
                "movement_amount_centimos": amount_centimos,
                "amount_centimos": pending,
                "amount_eur": pending / 100,
                "date": movement_date,
                "concept": movement_concept,
                "client_id": selected_client_id,
                "return_section": "movimientos",
                "auto_reopen_reconciliation": True,
                "auto_link_after_create": True,
            }

            state["movement_to_reconcile"] = {
                "source": source,
                "id": movement_id,
                "item": movement_item_snapshot,
                "amount_centimos": amount_centimos,
                "date": movement_date,
                "concept": movement_concept,
            }

            try:
                reconciliation_dialog.open = False
            except Exception:
                pass

            state["section"] = "cobros"
            try:
                refresh()
            except Exception:
                pass

            try:
                open_cobro_dialog()
            except Exception as exc:
                set_message(f"No se pudo abrir el alta de cobro: {exc}", is_error=True)
                try:
                    page.update()
                except Exception:
                    pass


        def save_link(e=None):
            client_id = selected_client_id_box.get("value") or selected_autocomplete_id(client_ac)
            cobro_id = option_id_from_label(cobro_dropdown.value) or cobro_dropdown.value

            try:
                client_id = int(client_id or 0)
            except Exception:
                client_id = 0

            try:
                cobro_id = int(cobro_id or 0)
            except Exception:
                cobro_id = 0

            if client_id <= 0:
                set_message("Selecciona un cliente válido.", is_error=True)
                return

            if cobro_id <= 0:
                set_message("Selecciona un cobro existente.", is_error=True)
                return

            pending_centimos = get_cobro_pending_centimos(cobro_id)

            if pending_centimos <= 0:
                set_message(
                    "Este cobro ya no tiene importe pendiente de conciliación.",
                    is_error=True,
                )
                return

            movement_summary = get_current_movement_reconciliation_summary()
            movement_pending_centimos = int(movement_summary.get("pending") or 0)

            if movement_pending_centimos <= 0:
                set_message("Este movimiento ya no tiene importe pendiente por vincular.", is_error=True)
                return

            applied_amount_centimos = min(int(movement_pending_centimos or 0), int(pending_centimos or 0))
            remaining_movement_centimos = int(movement_pending_centimos or 0) - int(applied_amount_centimos or 0)

            application_type = "TOTAL"
            if remaining_movement_centimos > 0:
                application_type = "PARCIAL_SOBRANTE"
            elif applied_amount_centimos < amount_centimos:
                application_type = "PARCIAL"

            notes = "\n".join(
                [
                    "Conciliación manual desde Económico > Movimientos",
                    f"Origen: {source}",
                    f"Movimiento: {movement_id}",
                    f"Fecha movimiento: {movement_date}",
                    f"Concepto: {movement_concept}",
                    f"Importe movimiento: {amount_centimos / 100:.2f} EUR",
                    f"Pendiente previo del cobro: {pending_centimos / 100:.2f} EUR",
                    f"Importe aplicado al cobro: {applied_amount_centimos / 100:.2f} EUR",
                    f"Sobrante no aplicado del movimiento: {remaining_movement_centimos / 100:.2f} EUR",
                    f"Tipo aplicación: {application_type}",
                ]
            )

            try:
                apply_reconciliation_application(
                    cobro_id=cobro_id,
                    client_id=client_id,
                    applied_amount_centimos=applied_amount_centimos,
                    notes=notes,
                )

                update_cobro_as_reconciled(cobro_id, source, movement_id)

                # Limpiar caché del origen para que la tabla lea de BD el nuevo estado.
                state.setdefault("movements_cache", {}).pop(source, None)

                # Mantener el diálogo abierto para poder aplicar el sobrante
                # del mismo movimiento contra otros cobros.
                cobro_dropdown.value = None

                # Refrescar lista de cobros por si el cobro seleccionado ya quedó conciliado
                # y debe desaparecer de pendientes.
                try:
                    refresh_cobros()
                except Exception:
                    pass

                # Refrescar tabla de movimientos sin cerrar el diálogo.
                try:
                    refresh_movements_results()
                except Exception:
                    try:
                        refresh()
                    except Exception:
                        pass

                # Refrescar el card del diálogo con el estado real posterior al vínculo.
                render_movement_summary_card()
                summary_after_link = get_current_movement_reconciliation_summary()
                pending_after_link = int(summary_after_link.get("pending") or 0)

                try:
                    cobro_dropdown.update()
                except Exception:
                    pass

                if pending_after_link <= 0:
                    set_message("Movimiento totalmente conciliado. No queda importe pendiente por vincular.")
                else:
                    set_message(
                        "Cobro vinculado. "
                        f"Pendiente del movimiento por vincular: {_money_centimos(pending_after_link)}."
                    )

                page.snack_bar = ft.SnackBar(ft.Text("Cobro vinculado al movimiento."))
                page.snack_bar.open = True
                page.update()
            except Exception as exc:
                set_message(f"No se pudo conciliar: {exc}", is_error=True)

        render_movement_summary_card()
        set_message("Selecciona un cliente y pulsa “Cargar cobros”.")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Conciliar movimiento con cobro existente"),
            content=ft.Container(
                width=780,
                content=ft.Column(
                    controls=[
                        movement_summary_box,
                        app_autocomplete_control(client_ac),
                        ft.Row(
                            controls=[
                                secondary_button("Cargar cobros del cliente", refresh_cobros),
                            ],
                            spacing=10,
                        ),
                        cobro_dropdown,
                        message_box,
                    ],
                    spacing=12,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.OutlinedButton("Generar cobro vinculado", on_click=generate_linked_cobro_from_movement),
                ft.ElevatedButton("Vincular cobro", on_click=save_link),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        show_reconciliation_dialog(dialog)



    def movement_invoiceability_status(item):
        raw = str(
            _get_value(item, "invoiceability_status")
            or "PENDING"
        ).strip().upper()

        if raw == "NON_INVOICEABLE":
            return "NO FACTURABLE"

        if raw == "FACTURABLE":
            return "FACTURABLE"

        return "PENDIENTE"


    def movement_invoicing_status_snapshot(items):
        movement_ids = [
            int(_get_value(item, "id"))
            for item in items or []
            if _get_value(item, "id") is not None
        ]

        try:
            return (
                invoicing_obligations_service
                .bank_movement_invoicing_snapshot(
                    movement_ids
                )
            )
        except Exception:
            return {}


    def movement_invoicing_badge(item, snapshot=None):
        movement_id = _get_value(item, "id")

        try:
            movement_id = int(movement_id)
        except (TypeError, ValueError):
            movement_id = None

        data = (
            (snapshot or {}).get(movement_id)
            if movement_id is not None
            else None
        ) or {}

        status = str(
            data.get("status") or "PENDIENTE"
        ).strip().upper()

        labels = {
            "FACTURADO": "FACTURADO",
            "PARCIAL": "FACTURADO PARCIAL",
            "PENDIENTE": "PENDIENTE",
            "NO_FACTURABLE": "NO FACTURABLE",
        }

        colors = {
            "FACTURADO": (
                "#027A48",
                "#ECFDF3",
                "#6CE9A6",
            ),
            "PARCIAL": (
                "#B54708",
                "#FFFAEB",
                "#FEC84B",
            ),
            "PENDIENTE": (
                "#475467",
                "#F2F4F7",
                "#D0D5DD",
            ),
            "NO_FACTURABLE": (
                "#B42318",
                "#FEF3F2",
                "#FDA29B",
            ),
        }

        foreground, background, border = colors.get(
            status,
            colors["PENDIENTE"],
        )

        original = int(
            data.get("original_centimos") or 0
        )
        invoiced = int(
            data.get("invoiced_centimos") or 0
        )
        pending = int(
            data.get("pending_centimos") or 0
        )

        tooltip = (
            "Movimiento: "
            + _money_centimos(original)
            + "\nFacturado: "
            + _money_centimos(invoiced)
            + "\nPendiente: "
            + _money_centimos(pending)
        )

        return ft.Container(
            content=ft.Text(
                labels.get(status, status),
                size=10,
                weight=ft.FontWeight.BOLD,
                color=foreground,
            ),
            bgcolor=background,
            border=ft.border.all(1, border),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=4,
            ),
            tooltip=tooltip,
        )


    def movement_invoiceability_badge(item):
        status = movement_invoiceability_status(item)

        palette = {
            "PENDIENTE": {
                "bg": "#FFFAEB",
                "fg": "#B54708",
                "border": "#FEC84B",
            },
            "FACTURABLE": {
                "bg": "#ECFDF3",
                "fg": "#027A48",
                "border": "#6CE9A6",
            },
            "NO FACTURABLE": {
                "bg": "#F2F4F7",
                "fg": "#475467",
                "border": "#98A2B3",
            },
        }

        cfg = palette[status]
        reason = str(
            _get_value(item, "invoiceability_reason") or ""
        ).strip()

        tooltip = status

        if reason:
            tooltip += f"\nMotivo: {reason}"

        return ft.Container(
            content=ft.Text(
                status,
                size=11,
                weight=ft.FontWeight.BOLD,
                color=cfg["fg"],
                no_wrap=True,
            ),
            bgcolor=cfg["bg"],
            border=ft.border.all(1.2, cfg["border"]),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=5,
            ),
            tooltip=tooltip,
        )


    def refresh_after_invoiceability_change(source):
        state.setdefault(
            "movements_cache",
            {},
        ).pop(source, None)

        state["obligations_page"] = 1

        refresh_movements_results()


    def restore_movement_invoiceability_action(
        source,
        item,
    ):
        movement_id = int(
            _get_value(item, "id") or 0
        )

        try:
            from backend.services.economic_reconciliation.bank_query_service import (
                restore_bank_movement_invoiceability,
            )

            if not restore_bank_movement_invoiceability(
                movement_id
            ):
                raise ValueError(
                    "No se encontró el movimiento."
                )

            refresh_after_invoiceability_change(source)

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    "Movimiento restaurado como pendiente "
                    "de facturación."
                ),
                open=True,
            )
            page.update()

        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"No se pudo restaurar: {exc}"
                ),
                open=True,
            )
            page.update()


    def open_non_invoiceable_movement_dialog(
        source,
        item,
    ):
        movement_id = int(
            _get_value(item, "id") or 0
        )
        amount_centimos = int(
            _get_value(item, "amount_centimos") or 0
        )
        concept = str(
            _get_value(item, "concept") or "-"
        ).strip()

        reason_input = ft.TextField(
            label="Motivo",
            hint_text=(
                "Ej.: traspaso interno, aportación de socio, "
                "devolución o ingreso duplicado"
            ),
            width=620,
            multiline=True,
            min_lines=2,
            max_lines=4,
        )

        message = ft.Text(
            "",
            size=12,
            color="#B42318",
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Marcar como no facturable"
            ),
        )

        def close_dialog(e=None):
            dialog.open = False
            page.update()

        def save_action(e=None):
            reason = str(
                reason_input.value or ""
            ).strip()

            if not reason:
                message.value = "Debes indicar el motivo."
                try:
                    message.update()
                except Exception:
                    page.update()
                return

            try:
                from backend.services.economic_reconciliation.bank_query_service import (
                    mark_bank_movement_non_invoiceable,
                )

                if not mark_bank_movement_non_invoiceable(
                    movement_id,
                    reason,
                ):
                    raise ValueError(
                        "No se encontró el movimiento."
                    )

                dialog.open = False
                refresh_after_invoiceability_change(source)

                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Movimiento marcado como no facturable."
                    ),
                    open=True,
                )
                page.update()

            except Exception as exc:
                message.value = str(exc)
                try:
                    message.update()
                except Exception:
                    page.update()

        dialog.content = ft.Container(
            width=660,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"Movimiento #{movement_id}",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        _money_centimos(amount_centimos),
                        size=19,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        concept,
                        size=12,
                        selectable=True,
                    ),
                    ft.Divider(height=14),
                    ft.Text(
                        (
                            "El movimiento seguirá visible y podrá "
                            "conciliarse, pero dejará de aparecer en "
                            "Obligaciones de facturación."
                        ),
                        size=12,
                        color=Q_MUTED,
                    ),
                    reason_input,
                    message,
                ],
                spacing=10,
                tight=True,
            ),
        )

        dialog.actions = [
            ft.TextButton(
                "Cancelar",
                on_click=close_dialog,
            ),
            ft.ElevatedButton(
                "Marcar como no facturable",
                on_click=save_action,
            ),
        ]
        dialog.actions_alignment = (
            ft.MainAxisAlignment.END
        )

        try:
            if dialog not in page.overlay:
                page.overlay.append(dialog)
        except Exception:
            pass

        dialog.open = True
        page.update()


    def movement_actions_button(source, item):
        items = []

        if is_movement_reconcilable(source, item):
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.LINK,
                                size=16,
                            ),
                            ft.Text(
                                "Conciliar",
                                size=13,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e, s=source, m=item: (
                        open_movement_reconciliation_action(
                            s,
                            m,
                        )
                    ),
                )
            )

        is_bank = source in {
            "caja_rural",
            "ing",
            "santander",
        }
        amount_centimos = int(
            _get_value(item, "amount_centimos") or 0
        )

        if is_bank and amount_centimos > 0:
            if (
                movement_invoiceability_status(item)
                == "NO FACTURABLE"
            ):
                items.append(
                    ft.PopupMenuItem(
                        content=ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.RESTORE,
                                    size=16,
                                ),
                                ft.Text(
                                    (
                                        "Restaurar como pendiente "
                                        "de facturación"
                                    ),
                                    size=13,
                                ),
                            ],
                            spacing=8,
                            tight=True,
                        ),
                        on_click=lambda e, s=source, m=item: (
                            restore_movement_invoiceability_action(
                                s,
                                m,
                            )
                        ),
                    )
                )
            else:
                items.append(
                    ft.PopupMenuItem(
                        content=ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.BLOCK,
                                    size=16,
                                    color="#B42318",
                                ),
                                ft.Text(
                                    "Marcar como no facturable",
                                    size=13,
                                    color="#B42318",
                                ),
                            ],
                            spacing=8,
                            tight=True,
                        ),
                        on_click=lambda e, s=source, m=item: (
                            open_non_invoiceable_movement_dialog(
                                s,
                                m,
                            )
                        ),
                    )
                )

        if not items:
            return ft.Container(
                width=1,
                height=1,
            )

        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Acciones",
            items=items,
        )


    def build_cashmatic_movements_table():
        source = "cashmatic"
        filtered = filtered_movements_for_source(source)
        items, total_items, page_number, page_size = paginate_movements(filtered)

        rows = []
        for m in items:
            reason = _get_value(m, "reason_raw") or "-"
            rows.append([
                movement_actions_button("cashmatic", m),
                _get_value(m, "cashmatic_id") or _get_value(m, "id") or "-",
                _date_time_to_display(_get_value(m, "start_time")),
                movement_money_text(_get_value(m, "requested_centimos")),
                movement_money_text(_get_value(m, "inserted_centimos")),
                _get_value(m, "operation") or "-",
                movement_reconciliation_badge(m),
                movement_applied_pending_summary("cashmatic", m),
                ft.Text(
                    reason,
                    size=12,
                    tooltip=reason,
                    selectable=True,
                    no_wrap=False,
                ),
            ])

        headers = [
            {"label": "", "key": "Acciones", "width": 60},
            {"label": "ID", "key": "ID", "width": 80},
            {"label": "Fecha", "key": "Fecha", "width": 150},
            {"label": "Solicitado", "key": "Solicitado", "width": 130},
            {"label": "Introducido", "key": "Introducido", "width": 130},
            {"label": "Operación", "key": "Operación", "width": 120},
            {"label": "Estado", "key": "Estado", "width": 240},
            {"label": "Conciliación", "key": "Conciliación", "width": 170},
            {"label": "Motivo", "key": "Motivo", "width": 620},
        ]

        table = app_table(headers, rows, height=430) if rows else empty_state("No hay movimientos Cashmatic importados")
        return ft.Column(
            controls=[
                movements_pagination(total_items, page_number, page_size),
                table,
            ],
            spacing=10,
        )


    def build_bank_movements_table(bank_name):
        bank_to_source = {
            "CAJA_RURAL": "caja_rural",
            "ING": "ing",
            "SANTANDER": "santander",
        }
        source = bank_to_source.get(str(bank_name or "").upper(), "ing")

        filtered = filtered_movements_for_source(source)
        items, total_items, page_number, page_size = paginate_movements(filtered)

        invoicing_snapshot = (
            movement_invoicing_status_snapshot(items)
        )

        rows = []
        for m in items:
            concept = (
                _get_value(m, "concept")
                or _get_value(m, "description")
                or _get_value(m, "motivo")
                or _get_value(m, "reason_raw")
                or "-"
            )

            operation_date = (
                _get_value(m, "operation_date")
                or _get_value(m, "date")
                or _get_value(m, "fecha")
                or _get_value(m, "start_time")
            )

            rows.append([
                movement_actions_button(source, m),
                _get_value(m, "id") or "-",
                _date_time_to_display(operation_date),
                movement_money_text(_get_value(m, "amount_centimos")),
                movement_reconciliation_badge(m),
                movement_applied_pending_summary(source, m),
                movement_invoicing_badge(
                    m,
                    invoicing_snapshot,
                ),
                ft.Text(
                    str(concept or "").upper(),
                    size=12,
                    tooltip=str(concept or "").upper(),
                    selectable=True,
                    no_wrap=False,
                ),
            ])

        headers = [
            {"label": "", "key": "Acciones", "width": 60},
            {"label": "ID", "key": "ID", "width": 80},
            {"label": "Fecha", "key": "Fecha", "width": 150},
            {"label": "Importe", "key": "Importe", "width": 130},
            {"label": "Estado", "key": "Estado", "width": 190},
            {"label": "Conciliación", "key": "Conciliación", "width": 190},
            {"label": "Facturación", "key": "Facturación", "width": 160},
            {"label": "Concepto", "key": "Concepto", "width": 650},
        ]

        table = app_table(headers, rows, height=430) if rows else empty_state(f"No hay movimientos {bank_name} importados")
        return ft.Column(
            controls=[
                movements_pagination(total_items, page_number, page_size),
                table,
            ],
            spacing=10,
        )



    def movement_source_color(source: str):
        source = (source or "").lower().strip()

        if source == "cashmatic":
            return ft.Colors.BLUE_600
        if source == "caja_rural":
            return ft.Colors.GREEN_600
        if source == "ing":
            return ft.Colors.ORANGE_600
        if source == "santander":
            return ft.Colors.RED_600

        return ft.Colors.BLUE_GREY_500

    def current_imported_movements_content():
        source = state.get("movements_source") or "cashmatic"

        source_map = {
            "cashmatic": ("Cashmatic", build_cashmatic_movements_table),
            "caja_rural": ("Caja Rural", lambda: build_bank_movements_table("CAJA_RURAL")),
            "ing": ("ING", lambda: build_bank_movements_table("ING")),
            "santander": ("Santander", lambda: build_bank_movements_table("SANTANDER")),
        }

        title, builder = source_map.get(source, source_map["cashmatic"])

        return ft.Column(
            controls=[
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                builder(),
            ],
            spacing=10,
        )


    def refresh_movements_results():
        movements_results_box.content = current_imported_movements_content()
        try:
            movements_results_box.update()
        except Exception:
            pass


    def on_movements_filter_change(e=None):
        state["movements_search"] = (movements_filter.value or "").strip()
        state["movements_page"] = 1
        refresh_movements_results()


    def import_movements_backend(source, file_path):
        source = (source or "").strip().lower()
        file_path = str(file_path or "").strip()

        if not file_path:
            raise ValueError("No se ha seleccionado ningún archivo.")

        if source == "cashmatic":
            from backend.services.economic_reconciliation.cashmatic_import_service import import_cashmatic_file
            return import_cashmatic_file(file_path)

        if source == "santander":
            from backend.services.economic_reconciliation.bank_import_service import import_santander_bank_file
            return import_santander_bank_file(file_path)

        if source == "caja_rural":
            from backend.services.economic_reconciliation.bank_import_service import import_caja_rural_bank_file
            return import_caja_rural_bank_file(file_path)

        if source == "ing":
            from backend.services.economic_reconciliation.bank_import_service import import_ing_bank_file
            return import_ing_bank_file(file_path)

        raise ValueError(f"Origen no soportado: {source}")


    def summarize_movements_import_result(result):
        if result is None:
            return "Importación completada."

        def value(*names):
            for name in names:
                if isinstance(result, dict) and name in result:
                    return result.get(name)

                if hasattr(result, name):
                    return getattr(result, name)

            return None

        inserted = value(
            "inserted_rows",
            "rows_inserted",
            "inserted",
            "imported_rows",
        )
        duplicates = value(
            "duplicate_rows",
            "duplicates",
        )
        total = value(
            "total_rows",
            "valid_rows",
        )
        quarantine = value(
            "quarantine_rows",
            "quarantine",
        )
        income = value(
            "income_rows",
        )
        expense = value(
            "expense_rows",
        )
        batch_id = value(
            "batch_id",
        )

        def integer(raw):
            try:
                return int(raw or 0)
            except Exception:
                return 0

        inserted_int = integer(inserted)
        duplicates_int = integer(duplicates)
        total_int = integer(total)
        quarantine_int = integer(quarantine)
        income_int = integer(income)
        expense_int = integer(expense)

        if inserted_int > 0:
            title = (
                f"Nuevos movimientos importados: "
                f"{inserted_int}"
            )
        elif duplicates_int > 0:
            title = (
                "Archivo revisado: no hay movimientos nuevos"
            )
        else:
            title = (
                "Importación completada sin movimientos nuevos"
            )

        details = [
            f"Duplicados omitidos: {duplicates_int}",
            f"Ingresos leídos: {income_int}",
            f"Cargos leídos: {expense_int}",
            f"Cuarentena: {quarantine_int}",
            f"Filas analizadas: {total_int}",
        ]

        if batch_id is not None:
            details.append(f"Lote: {batch_id}")

        return title + " · " + " · ".join(details)


    def show_movements_import_result_dialog(result):
        def value(*names):
            for name in names:
                if isinstance(result, dict) and name in result:
                    return result.get(name)

                if hasattr(result, name):
                    return getattr(result, name)

            return None

        def integer(raw):
            try:
                return int(raw or 0)
            except Exception:
                return 0

        inserted = integer(
            value(
                "inserted_rows",
                "rows_inserted",
                "inserted",
                "imported_rows",
            )
        )
        duplicates = integer(
            value(
                "duplicate_rows",
                "duplicates",
            )
        )
        total = integer(
            value(
                "total_rows",
                "valid_rows",
            )
        )
        quarantine = integer(
            value(
                "quarantine_rows",
                "quarantine",
            )
        )
        income = integer(
            value("income_rows")
        )
        expense = integer(
            value("expense_rows")
        )

        batch_id = value("batch_id")
        source_file = value("source_file")

        if inserted > 0:
            title = "Nuevos movimientos importados"
            icon = ft.Icons.CHECK_CIRCLE_OUTLINE
            title_color = ft.Colors.GREEN_700

        elif duplicates > 0:
            title = "No hay movimientos nuevos"
            icon = ft.Icons.INFO_OUTLINE
            title_color = ft.Colors.BLUE_700

        else:
            title = "Importación completada"
            icon = ft.Icons.WARNING_AMBER_OUTLINED
            title_color = ft.Colors.ORANGE_700

        details = [
            ("Nuevos movimientos", inserted),
            ("Duplicados omitidos", duplicates),
            ("Ingresos leídos", income),
            ("Cargos leídos", expense),
            ("Filas en cuarentena", quarantine),
            ("Filas analizadas", total),
        ]

        if batch_id is not None:
            details.append(("Lote", batch_id))

        detail_controls = []

        for label, amount in details:
            detail_controls.append(
                ft.Row(
                    controls=[
                        ft.Text(
                            label,
                            size=13,
                            color=Q_MUTED,
                            expand=True,
                        ),
                        ft.Text(
                            str(amount),
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                    ],
                    spacing=16,
                )
            )

        if source_file:
            detail_controls.extend(
                [
                    ft.Divider(height=18),
                    ft.Text(
                        "Archivo importado",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        str(source_file),
                        size=12,
                        selectable=True,
                    ),
                ]
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(
                        icon,
                        color=title_color,
                    ),
                    ft.Text(
                        title,
                        color=title_color,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    controls=detail_controls,
                    spacing=8,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda e: page.close(dialog),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.open(dialog)


    def export_filtered_movements_to_excel(
        e=None,
    ):
        try:
            source = movements_cache_key(
                state.get(
                    "movements_source"
                )
                or "cashmatic"
            )

            movements = (
                filtered_movements_for_source(
                    source
                )
            )

            if not movements:
                raise ValueError(
                    "No hay movimientos para exportar "
                    "con los filtros actuales"
                )

            result = (
                economic_movements_export_service
                .export_movements_to_excel(
                    source,
                    movements,
                    search=str(
                        state.get(
                            "movements_search"
                        )
                        or ""
                    ).strip(),
                )
            )

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    (
                        f"Exportados {result['count']} "
                        f"movimientos de "
                        f"{result['source_label']}."
                    )
                ),
                open=True,
            )

            try:
                page.run_task(
                    page.launch_url,
                    Path(
                        result["path"]
                    ).as_uri(),
                )
            except Exception:
                pass

            page.update()

        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"No se pudo exportar: {exc}"
                ),
                open=True,
            )
            page.update()


    async def seleccionar_movimientos_csv_xls(e=None):
        source = state.get("movements_source") or "cashmatic"

        extension_map = {
            "cashmatic": ["csv"],
            "santander": ["xls", "xlsx"],
            "caja_rural": ["xls", "xlsx"],
            "ing": ["xls", "xlsx"],
        }

        files = await ft.FilePicker().pick_files(
            allow_multiple=False,
            allowed_extensions=extension_map.get(source, ["csv", "xls", "xlsx"]),
        )

        if not files:
            return

        file_path = files[0].path

        try:
            result = import_movements_backend(source, file_path)

            # Forzar recarga real desde backend tras importar.
            # Los bancos comparten bank_movements filtrado por bank_name.
            # Limpiamos toda la cache para evitar datos antiguos entre Santander/ING/Caja Rural.
            try:
                state["movements_cache"] = {}
            except Exception:
                pass

            state["movements_source"] = source
            state["movements_page"] = 1
            state["movements_search"] = ""

            try:
                movements_filter.value = ""
            except Exception:
                pass

            try:
                movements_results_box.content = current_imported_movements_content()
                movements_results_box.update()
            except Exception:
                pass

            show_movements_import_result_dialog(result)

        except Exception as exc:
            try:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(f"Error importando movimientos: {exc}"),
                    open=True,
                )
                page.update()
            except Exception:
                raise


    def build_imported_movements_section():
        movements_filter.value = state.get("movements_search") or ""
        movements_filter.on_change = on_movements_filter_change
        movements_results_box.content = current_imported_movements_content()

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Movimientos importados", size=22, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Container(expand=True),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Row(
                    controls=[
                        movements_source_button("cashmatic", "Cashmatic"),
                        movements_source_button("caja_rural", "Caja Rural"),
                        movements_source_button("ing", "ING"),
                        movements_source_button("santander", "Santander"),
                        ft.IconButton(
                            icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                            icon_color="#027A48",
                            tooltip=(
                                "Exportar a Excel todos los "
                                "movimientos resultantes de "
                                "los filtros actuales"
                            ),
                            on_click=(
                                export_filtered_movements_to_excel
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.UPLOAD_FILE,
                            tooltip="Importar CSV/XLS",
                            on_click=seleccionar_movimientos_csv_xls,
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        movements_filter,
                        ft.Text("Ej.: marzo, 03/2026, 16/03/2026, 2026-03, ID Cashmatic o nombre", size=12, color=Q_MUTED),
                    ],
                    spacing=8,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=8,
                    content=movements_results_box,
                ),
            ],
            spacing=8,
            expand=True,
        )


    def _factura_client_name(factura):
        return " ".join(
            part
            for part in [
                str(factura.get("nombre") or "").strip(),
                str(factura.get("primer_apellido") or "").strip(),
                str(factura.get("segundo_apellido") or "").strip(),
            ]
            if part
        )


    def _factura_search_blob(factura):
        values = [
            factura.get("id"),
            factura.get("numero_factura"),
            factura.get("fecha_factura"),
            _date_to_display(factura.get("fecha_factura")),
            _factura_client_name(factura),
            factura.get("cliente_id"),
            factura.get("numero_expediente"),
            factura.get("expediente_id"),
            factura.get("numero_hoja"),
            factura.get("hoja_encargo_id"),
            factura.get("base_imponible"),
            _money(factura.get("base_imponible")),
            factura.get("iva"),
            _money(factura.get("iva")),
            factura.get("irpf"),
            _money(factura.get("irpf")),
            factura.get("suplidos"),
            _money(factura.get("suplidos")),
            factura.get("total"),
            _money(factura.get("total")),
            factura.get("estado"),
            factura.get("tipo_fiscal"),
            factura.get("concepto"),
            (
                "exportada holded"
                if factura.get("exportada_holded")
                else "pendiente holded"
            ),
            factura.get("observaciones"),
        ]

        blob = []

        for value in values:
            blob.append(str(value or ""))

            try:
                blob.extend(_date_search_tokens(value))
            except Exception:
                pass

        return " ".join(blob).lower()


    def factura_matches_search(factura):
        query = str(
            state.get("facturas_search") or ""
        ).strip().lower()

        if not query:
            return True

        return query in _factura_search_blob(factura)


    def factura_matches_period(factura):
        date_value = str(factura.get("fecha_factura") or "").strip()
        date_from = str(
            state.get("facturas_date_from") or ""
        ).strip()
        date_to = str(
            state.get("facturas_date_to") or ""
        ).strip()

        if date_from and date_value < date_from:
            return False

        if date_to and date_value > date_to:
            return False

        return True


    def factura_matches_status(factura):
        selected = str(
            state.get("facturas_status_filter") or "all"
        ).strip().lower()

        if selected in ("", "all"):
            return True

        estado = str(
            factura.get("estado") or "BORRADOR"
        ).strip().lower()

        return estado == selected


    def factura_matches_holded(factura):
        selected = str(
            state.get("facturas_holded_filter") or "all"
        ).strip().lower()

        if selected in ("", "all"):
            return True

        exported = bool(factura.get("exportada_holded"))

        if selected == "exported":
            return exported

        if selected == "pending":
            return not exported

        return True


    def filtered_facturas(
        *,
        include_status=True,
        include_holded=True,
    ):
        result = []

        for factura in economic_service.list_facturas():
            factura = dict(factura)

            if not factura_matches_search(factura):
                continue

            if not factura_matches_period(factura):
                continue

            if include_status and not factura_matches_status(factura):
                continue

            if include_holded and not factura_matches_holded(factura):
                continue

            result.append(factura)

        return result


    def facturas_status_counts():
        counts = {
            "all": 0,
            "borrador": 0,
            "emitida": 0,
            "exportada": 0,
            "anulada": 0,
        }

        for factura in filtered_facturas(
            include_status=False,
            include_holded=True,
        ):
            counts["all"] += 1

            estado = str(
                factura.get("estado") or "BORRADOR"
            ).strip().lower()

            if estado in counts:
                counts[estado] += 1

        return counts


    def facturas_holded_counts():
        counts = {
            "all": 0,
            "pending": 0,
            "exported": 0,
        }

        for factura in filtered_facturas(
            include_status=True,
            include_holded=False,
        ):
            counts["all"] += 1

            if factura.get("exportada_holded"):
                counts["exported"] += 1
            else:
                counts["pending"] += 1

        return counts


    def build_facturas_status_filters():
        status_map = {
            "borrador": (
                "Borrador",
                "#F1F5F9",
                "#475569",
                "#CBD5E1",
            ),
            "emitida": (
                "Emitida",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "exportada": (
                "Aprobada",
                "#EAF3FF",
                "#0057B8",
                "#84CAFF",
            ),
            "anulada": (
                "Anulada",
                "#FEF3F2",
                "#B42318",
                "#FDA29B",
            ),
        }

        return counter_chips(
            options=[
                ("borrador", "Borradores"),
                ("emitida", "Emitidas"),
                ("exportada", "Aprobadas"),
                ("anulada", "Anuladas"),
            ],
            counts=facturas_status_counts(),
            active_value=state.get("facturas_status_filter") or "all",
            on_select=on_facturas_status_select,
            include_all=True,
            all_label="Todas",
            all_value="all",
            status_map=status_map,
            bordered_status=True,
        )


    def build_facturas_holded_filters():
        status_map = {
            "pending": (
                "Pendiente de aprobación",
                "#FFFAEB",
                "#B54708",
                "#FEC84B",
            ),
            "exported": (
                "Aprobada",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
        }

        return counter_chips(
            options=[
                ("pending", "Pendientes de aprobación"),
                ("exported", "Aprobadas"),
            ],
            counts=facturas_holded_counts(),
            active_value=state.get("facturas_holded_filter") or "all",
            on_select=on_facturas_holded_select,
            include_all=True,
            all_label="Todas por aprobación",
            all_value="all",
            status_map=status_map,
            bordered_status=True,
        )


    def build_facturas_period_summary():
        date_from = str(
            state.get("facturas_date_from") or ""
        ).strip()
        date_to = str(
            state.get("facturas_date_to") or ""
        ).strip()

        if not date_from and not date_to:
            return ft.Text(
                "Sin filtro temporal",
                size=11,
                color=Q_MUTED,
            )

        from_label = (
            _date_to_display(date_from)
            if date_from
            else "Inicio"
        )
        to_label = (
            _date_to_display(date_to)
            if date_to
            else "Hoy"
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.DATE_RANGE,
                        size=14,
                        color="#0057B8",
                    ),
                    ft.Text(
                        f"{from_label} → {to_label}",
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color="#0057B8",
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor="#EAF3FF",
            border=ft.border.all(1, "#84CAFF"),
            border_radius=20,
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=5,
            ),
        )


    def go_facturas_page(page_number):
        state["facturas_page"] = max(1, int(page_number or 1))
        refresh_facturas_results_only()


    factura_delete_state = {
        "id": None,
        "numero": "",
    }


    def open_edit_factura_linked_cobro(factura):
        if bool(factura.get("_period_closed")):
            show_message(
                error_alert(
                    "La factura pertenece a un periodo cerrado"
                )
            )
            refresh()
            return

        if bool(factura.get("exportada_holded")):
            show_message(
                error_alert(
                    "La factura está aprobada y congelada "
                    "y permanece bloqueada"
                )
            )
            refresh()
            return

        cobro_id = factura.get("cobro_id")

        if not cobro_id:
            show_message(
                error_alert(
                    "La factura no tiene un cobro vinculado modificable"
                )
            )
            refresh()
            return

        cobro = economic_service.get_cobro(cobro_id)

        if not cobro:
            show_message(
                error_alert("No se encontró el cobro vinculado")
            )
            refresh()
            return

        open_edit_cobro_dialog(cobro)


    rectification_state = {
        "factura": None,
    }


    def _rectification_float(control):
        raw = str(control.value or "").strip()
        raw = raw.replace(",", ".")

        if raw in ("", "-", "+"):
            return 0.0

        return round(float(raw), 2)


    def update_rectification_total(e=None):
        try:
            base = _rectification_float(
                rectification_base_input
            )
            iva = _rectification_float(
                rectification_iva_input
            )
            irpf = _rectification_float(
                rectification_irpf_input
            )
            suplidos = _rectification_float(
                rectification_suplidos_input
            )

            total = round(
                base + iva - irpf + suplidos,
                2,
            )

            rectification_total_text.value = (
                f"Total rectificativa: {total:.2f} €"
            )
            rectification_error_text.value = ""

        except Exception:
            rectification_total_text.value = (
                "Total rectificativa: —"
            )
            rectification_error_text.value = (
                "Revisa los importes introducidos"
            )

        try:
            rectification_total_text.update()
            rectification_error_text.update()
        except Exception:
            pass


    def apply_rectification_mode(e=None):
        factura = (
            rectification_state.get("factura")
            or {}
        )

        total_mode = (
            rectification_mode.value
            == "ANULACION_TOTAL"
        )

        controls = [
            rectification_base_input,
            rectification_iva_input,
            rectification_irpf_input,
            rectification_suplidos_input,
        ]

        if total_mode:
            rectification_base_input.value = (
                f"{-float(factura.get('base_imponible') or 0):.2f}"
            )
            rectification_iva_input.value = (
                f"{-float(factura.get('iva') or 0):.2f}"
            )
            rectification_irpf_input.value = (
                f"{-float(factura.get('irpf') or 0):.2f}"
            )
            rectification_suplidos_input.value = (
                f"{-float(factura.get('suplidos') or 0):.2f}"
            )

        for control in controls:
            control.disabled = total_mode

        update_rectification_total()

        try:
            for control in controls:
                control.update()
        except Exception:
            page.update()


    def open_rectification_dialog(factura):
        if not bool(
            factura.get("exportada_holded")
        ):
            show_message(
                error_alert(
                    "La factura no está exportada. "
                    "Puedes modificarla directamente."
                )
            )
            return

        if (
            str(
                factura.get("tipo_factura")
                or "NORMAL"
            ).upper()
            == "RECTIFICATIVA"
        ):
            show_message(
                error_alert(
                    "Esta acción no está disponible para "
                    "una rectificativa."
                )
            )
            return

        rectification_state["factura"] = dict(factura)

        rectification_original_text.value = (
            f"Factura original: "
            f"{factura.get('numero_factura') or '-'} · "
            f"{float(factura.get('total') or 0):.2f} €"
        )

        rectification_date_input.value = (
            datetime.today().strftime("%Y-%m-%d")
        )
        rectification_mode.value = "ANULACION_TOTAL"
        rectification_cause_code.value = (
            "ANULACION_OPERACION"
        )
        rectification_cause_input.value = ""
        rectification_observations_input.value = ""

        apply_rectification_mode()

        rectification_dialog.open = True
        page.update()


    def close_rectification_dialog(e=None):
        rectification_dialog.open = False
        rectification_state["factura"] = None
        page.update()


    def confirm_rectification(e=None):
        factura = (
            rectification_state.get("factura")
            or {}
        )

        factura_id = factura.get("id")

        if not factura_id:
            show_message(
                error_alert(
                    "No se ha identificado la factura original"
                )
            )
            return

        try:
            rectificativa_id = (
                economic_service
                .create_factura_rectificativa(
                    factura_id,
                    {
                        "fecha_factura":
                            rectification_date_input.value,
                        "codigo_causa_rectificacion":
                            rectification_cause_code.value,
                        "causa_rectificacion":
                            rectification_cause_input.value,
                        "base_imponible":
                            _rectification_float(
                                rectification_base_input
                            ),
                        "iva":
                            _rectification_float(
                                rectification_iva_input
                            ),
                        "irpf":
                            _rectification_float(
                                rectification_irpf_input
                            ),
                        "suplidos":
                            _rectification_float(
                                rectification_suplidos_input
                            ),
                        "observaciones":
                            rectification_observations_input.value,
                    },
                )
            )

            rectification_dialog.open = False
            rectification_state["factura"] = None

            show_message(
                success_alert(
                    "Factura rectificativa creada "
                    f"correctamente (ID {rectificativa_id})"
                )
            )

            refresh()

        except Exception as exc:
            rectification_error_text.value = str(exc)

            try:
                rectification_error_text.update()
            except Exception:
                page.update()


    def open_delete_factura_dialog(factura):
        if bool(factura.get("_period_closed")):
            show_message(
                error_alert(
                    "La factura pertenece a un periodo cerrado"
                )
            )
            refresh()
            return

        if bool(factura.get("exportada_holded")):
            show_message(
                error_alert(
                    "La factura está aprobada y congelada "
                    "y no puede eliminarse"
                )
            )
            refresh()
            return

        factura_delete_state["id"] = factura.get("id")
        factura_delete_state["numero"] = (
            factura.get("numero_factura")
            or f"Factura #{factura.get('id') or '-'}"
        )

        factura_delete_message.value = (
            f"Se eliminará {factura_delete_state['numero']}. "
            "El cobro vinculado se conservará y volverá a quedar "
            "disponible como facturable."
        )

        factura_delete_dialog.open = True
        page.update()


    def close_delete_factura_dialog(e=None):
        factura_delete_dialog.open = False
        page.update()


    def confirm_delete_factura(e=None):
        try:
            factura_id = factura_delete_state.get("id")

            if not factura_id:
                raise ValueError("Factura no identificada")

            economic_service.delete_factura(factura_id)

            factura_delete_dialog.open = False
            factura_delete_state["id"] = None
            factura_delete_state["numero"] = ""

            show_message(
                success_alert(
                    "Factura eliminada; el cobro se ha conservado"
                )
            )
        except Exception as exc:
            factura_delete_dialog.open = False
            show_message(error_alert(str(exc)))

        refresh()


    def approve_factura(factura):
        try:
            factura_id = factura.get("id")

            if not factura_id:
                raise ValueError("Factura no identificada")

            if bool(factura.get("exportada_holded")):
                raise ValueError(
                    "La factura ya está aprobada y congelada"
                )

            economic_service.approve_factura(
                factura_id
            )

            show_message(
                success_alert(
                    "Factura aprobada y congelada correctamente"
                )
            )
        except Exception as exc:
            show_message(error_alert(str(exc)))

        refresh()


    def export_filtered_invoices_to_advisory(e=None):
        try:
            facturas = filtered_facturas()

            invoice_ids = [
                int(factura["id"])
                for factura in facturas
                if factura.get("id") is not None
            ]

            if not invoice_ids:
                raise ValueError(
                    "No hay facturas para exportar "
                    "con los filtros actuales"
                )

            result = (
                advisory_invoice_export_service
                .export_invoices_to_advisory(
                    invoice_ids
                )
            )

            show_message(
                success_alert(
                    (
                        f"Exportadas {result['count']} "
                        "facturas para la asesoría"
                    )
                )
            )

            try:
                page.run_task(
                    page.launch_url,
                    Path(result["path"]).as_uri(),
                )
            except Exception:
                pass

        except Exception as exc:
            show_message(
                error_alert(str(exc))
            )

        refresh()


    facturas_export_advisory_button = ft.IconButton(
        icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
        icon_color="#027A48",
        tooltip=(
            "Exportar a Excel las facturas "
            "resultantes de los filtros actuales"
        ),
        on_click=export_filtered_invoices_to_advisory,
    )


    def build_facturas_results():
        facturas = filtered_facturas()

        if not facturas:
            state["facturas_page"] = 1

            if str(state.get("facturas_search") or "").strip():
                empty_result = empty_state(
                    "No hay facturas que coincidan con la búsqueda"
                )
            else:
                empty_result = empty_state("No hay facturas")

            return ft.Column(
                controls=[
                        empty_result,
                ],
                spacing=12,
            )

        page_size = max(
            1,
            int(state.get("facturas_page_size") or 10),
        )
        total_items = len(facturas)
        total_pages = max(
            1,
            (total_items + page_size - 1) // page_size,
        )

        current_page = max(
            1,
            min(
                int(state.get("facturas_page") or 1),
                total_pages,
            ),
        )
        state["facturas_page"] = current_page

        start_index = (current_page - 1) * page_size
        end_index = start_index + page_size
        visible_facturas = facturas[start_index:end_index]

        closure_date = (
            economic_service.get_invoice_closure_date()
        )

        cards = []

        for factura in visible_facturas:
            factura_data = dict(factura)

            factura_date = str(
                factura_data.get("fecha_factura") or ""
            )

            # La fecha de la última factura aprobada permanece
            # abierta durante todo ese día. Solo las fechas
            # estrictamente anteriores se consideran cerradas.
            factura_data["_period_closed"] = bool(
                closure_date
                and factura_date
                and factura_date < closure_date
            )

            cards.append(
                economic_invoice_card(
                    factura_data,
                    date_display=_date_to_display,
                    on_edit=open_edit_factura_linked_cobro,
                    on_delete=open_delete_factura_dialog,
                    on_export_holded=approve_factura,
                    on_rectify=open_rectification_dialog,
                )
            )

        closure_date = (
            economic_service.get_invoice_closure_date()
        )

        holded_closure_chip = (
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.LOCK_OUTLINE,
                            size=14,
                            color="#027A48",
                        ),
                        ft.Text(
                            (
                                "Facturas congeladas hasta "
                                f"{_date_to_display(closure_date)}"
                            ),
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color="#027A48",
                        ),
                    ],
                    spacing=5,
                    tight=True,
                ),
                bgcolor="#ECFDF3",
                border=ft.border.all(1, "#6CE9A6"),
                border_radius=20,
                padding=ft.padding.symmetric(
                    horizontal=10,
                    vertical=5,
                ),
            )
            if closure_date
            else ft.Container()
        )

        toolbar = ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"Resultados: {total_items}"
                                if str(
                                    state.get(
                                        "facturas_search"
                                    ) or ""
                                ).strip()
                                else (
                                    f"Facturas registradas: "
                                    f"{total_items}"
                                )
                            ),
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        holded_closure_chip,
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                compact_pagination_bar(
                    page=current_page,
                    page_size=page_size,
                    total_items=total_items,
                    on_page_change=go_facturas_page,
                    label_prefix="Facturas",
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

        return ft.Column(
            controls=[
                toolbar,
                ft.Container(
                    height=620,
                    content=ft.Column(
                        controls=cards,
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=8,
        )


    def refresh_facturas_results_only():
        facturas_results_box.content = build_facturas_results()
        facturas_status_box.content = build_facturas_status_filters()
        facturas_holded_box.content = build_facturas_holded_filters()
        facturas_period_summary_box.content = (
            build_facturas_period_summary()
        )

        has_search = bool(
            str(state.get("facturas_search") or "").strip()
        )
        has_period = bool(
            state.get("facturas_date_from")
            or state.get("facturas_date_to")
        )
        has_status = (
            str(
                state.get("facturas_status_filter") or "all"
            ).strip()
            not in ("", "all")
        )
        has_holded = (
            str(
                state.get("facturas_holded_filter") or "all"
            ).strip()
            not in ("", "all")
        )

        has_any_filter = (
            has_search
            or has_period
            or has_status
            or has_holded
        )

        facturas_clear_button.disabled = not has_any_filter
        facturas_clear_button.icon_color = (
            Q_PRIMARY_DARK
            if has_any_filter
            else "#98A2B3"
        )
        facturas_clear_button.tooltip = (
            "Reiniciar todos los filtros"
            if has_any_filter
            else "No hay filtros activos"
        )

        facturas_period_button.icon_color = (
            "#0057B8"
            if has_period
            else Q_PRIMARY_DARK
        )

        try:
            facturas_results_box.update()
            facturas_status_box.update()
            facturas_holded_box.update()
            facturas_period_summary_box.update()
            facturas_clear_button.update()
            facturas_period_button.update()
        except Exception:
            page.update()


    def on_facturas_search_change(e=None):
        state["facturas_search"] = str(
            facturas_filter.value or ""
        )
        state["facturas_page"] = 1
        refresh_facturas_results_only()


    def clear_facturas_filters(e=None):
        state.update(
            {
                "facturas_search": "",
                "facturas_status_filter": "all",
                "facturas_holded_filter": "all",
                "facturas_date_from": "",
                "facturas_date_to": "",
                "facturas_page": 1,
            }
        )

        facturas_filter.value = ""
        facturas_date_from_input.value = ""
        facturas_date_to_input.value = ""
        facturas_period_error.value = ""

        refresh_facturas_results_only()

        try:
            facturas_filter.update()
            facturas_date_from_input.update()
            facturas_date_to_input.update()
            facturas_period_error.update()
        except Exception:
            page.update()


    def on_facturas_status_select(status_value):
        state["facturas_status_filter"] = str(
            status_value or "all"
        )
        state["facturas_page"] = 1
        refresh_facturas_results_only()


    def on_facturas_holded_select(status_value):
        state["facturas_holded_filter"] = str(
            status_value or "all"
        )
        state["facturas_page"] = 1
        refresh_facturas_results_only()


    def open_facturas_period_dialog(e=None):
        facturas_date_from_input.value = (
            _date_to_display(state.get("facturas_date_from"))
            if state.get("facturas_date_from")
            else ""
        )
        facturas_date_to_input.value = (
            _date_to_display(state.get("facturas_date_to"))
            if state.get("facturas_date_to")
            else ""
        )

        facturas_period_error.value = ""
        facturas_period_dialog.open = True
        page.update()


    def close_facturas_period_dialog(e=None):
        facturas_period_dialog.open = False
        page.update()


    def apply_facturas_period_filter(e=None):
        raw_from = str(
            facturas_date_from_input.value or ""
        ).strip()
        raw_to = str(
            facturas_date_to_input.value or ""
        ).strip()

        date_from = _date_to_sql(raw_from) if raw_from else ""
        date_to = _date_to_sql(raw_to) if raw_to else ""

        if raw_from and not date_from:
            facturas_period_error.value = (
                "La fecha inicial no es válida. Usa DD/MM/AAAA."
            )
            facturas_period_error.update()
            return

        if raw_to and not date_to:
            facturas_period_error.value = (
                "La fecha final no es válida. Usa DD/MM/AAAA."
            )
            facturas_period_error.update()
            return

        if date_from and date_to and date_from > date_to:
            facturas_period_error.value = (
                "La fecha inicial no puede ser posterior "
                "a la fecha final."
            )
            facturas_period_error.update()
            return

        state["facturas_date_from"] = date_from
        state["facturas_date_to"] = date_to
        state["facturas_page"] = 1

        facturas_period_dialog.open = False
        refresh_facturas_results_only()
        page.update()


    def clear_facturas_period_filter(e=None):
        facturas_date_from_input.value = ""
        facturas_date_to_input.value = ""
        facturas_period_error.value = ""

        state["facturas_date_from"] = ""
        state["facturas_date_to"] = ""
        state["facturas_page"] = 1

        facturas_period_dialog.open = False
        refresh_facturas_results_only()
        page.update()


    def build_facturas_section():
        facturas_filter.value = (
            state.get("facturas_search") or ""
        )
        facturas_results_box.content = build_facturas_results()
        facturas_status_box.content = build_facturas_status_filters()
        facturas_holded_box.content = build_facturas_holded_filters()
        facturas_period_summary_box.content = (
            build_facturas_period_summary()
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        facturas_filter,
                        facturas_period_button,
                        facturas_clear_button,
                        facturas_export_advisory_button,
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        facturas_period_summary_box,
                        ft.Container(expand=True),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        facturas_status_box,
                        facturas_holded_box,
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                facturas_results_box,
            ],
            spacing=8,
        )


    def build_cobros_results():
        cobros = filtered_cobros()

        if not cobros:
            state["cobros_page"] = 1

            if str(state.get("cobros_search") or "").strip():
                return empty_state(
                    "No hay cobros que coincidan con la búsqueda"
                )

            return empty_state("No hay cobros")

        page_size = max(1, int(state.get("cobros_page_size") or 10))
        total_items = len(cobros)
        total_pages = max(1, (total_items + page_size - 1) // page_size)

        current_page = max(
            1,
            min(int(state.get("cobros_page") or 1), total_pages),
        )
        state["cobros_page"] = current_page

        start_index = (current_page - 1) * page_size
        end_index = start_index + page_size
        visible_cobros = cobros[start_index:end_index]

        cards = [
            economic_payment_card(
                dict(cobro),
                date_display=_date_to_display,
                on_edit=lambda item: open_edit_cobro_dialog(dict(item)),
            )
            for cobro in visible_cobros
        ]

        toolbar = ft.Row(
            controls=[
                ft.Text(
                    (
                        f"Resultados: {total_items}"
                        if str(state.get("cobros_search") or "").strip()
                        else f"Cobros registrados: {total_items}"
                    ),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                compact_pagination_bar(
                    page=current_page,
                    page_size=page_size,
                    total_items=total_items,
                    on_page_change=go_cobros_page,
                    label_prefix="Cobros",
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

        return ft.Column(
            controls=[
                toolbar,
                ft.Container(
                    height=620,
                    content=ft.Column(
                        controls=cards,
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=8,
        )


    def build_cobros_section():
        cobros_results_box.content = build_cobros_results()
        cobros_status_box.content = build_cobros_status_filters()
        cobros_period_summary_box.content = build_cobros_period_summary()

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        cobros_filter,
                        ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            icon_color=Q_PRIMARY_DARK,
                            tooltip="Nuevo cobro",
                            on_click=open_cobro_dialog,
                        ),
                        cobros_period_button,
                        cobros_clear_button,
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        cobros_period_summary_box,
                        ft.Container(expand=True),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                cobros_status_box,
                cobros_results_box,
            ],
            spacing=8,
        )


    def _obligation_month_value_from_label(value):
        normalized = str(value or "").strip().lower()

        if not normalized:
            return ""

        months = available_obligation_months()

        for month in months:
            label = _obligation_month_label(month)

            if normalized in {
                str(month).strip().lower(),
                str(label).strip().lower(),
            }:
                return month

        return ""


    def on_obligations_month_selected(value=None):
        selected_month = _obligation_month_value_from_label(
            value
        )

        if not selected_month:
            return

        state["obligations_month"] = selected_month
        state["obligations_page"] = 1

        obligations_month_autocomplete.set_value(
            _obligation_month_label(selected_month),
            update=False,
        )

        refresh()


    def on_obligations_search_change(e=None):
        state["obligations_search"] = str(
            obligations_search_input.value or ""
        )
        state["obligations_page"] = 1
        refresh()


    def clear_obligations_filters(e=None):
        months = available_obligation_months()

        state["obligations_month"] = (
            months[0] if months else ""
        )
        state["obligations_source"] = "ALL"
        state["obligations_search"] = ""
        state["obligations_page"] = 1

        obligations_search_input.value = ""

        selected_month = state["obligations_month"]

        obligations_month_autocomplete.set_value(
            (
                _obligation_month_label(selected_month)
                if selected_month
                else ""
            ),
            update=False,
        )

        refresh()


    obligations_month_autocomplete = AppAutocomplete(
        page=page,
        label="Mes",
        options=[
            _obligation_month_label(month)
            for month in available_obligation_months()
        ],
        value="",
        width=230,
        max_results=8,
        on_select=on_obligations_month_selected,
        allow_free_text=False,
        hint_text="Escribe o selecciona un mes",
        empty_text="No hay meses disponibles",
    )


    obligations_search_input = ft.TextField(
        label="Buscar movimiento",
        hint_text="Concepto, banco, fecha o ID",
        width=340,
        dense=True,
        prefix_icon=ft.Icons.SEARCH,
    )
    obligations_search_input.on_submit = (
        on_obligations_search_change
    )


    # ========================================================
    # HOJAS DE ENCARGO: BÚSQUEDA, ESTADOS Y PAGINACIÓN
    # ========================================================

    hojas_filter = text_input(
        "Buscar cliente, hoja, expediente o procedimiento...",
        width=620,
    )
    hojas_filter.value = ""

    hojas_results_box = ft.Container(expand=True)
    hojas_status_box = ft.Container()

    hojas_clear_button = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="#98A2B3",
        tooltip="No hay filtros activos",
        disabled=True,
    )


    def _hoja_search_blob(hoja):
        values = [
            hoja.get("id"),
            hoja.get("numero_hoja"),
            hoja.get("cliente_nombre_completo"),
            hoja.get("cliente_id"),
            hoja.get("numero_expediente"),
            hoja.get("expediente_id"),
            hoja.get("procedimiento"),
            hoja.get("estado"),
            hoja.get("fecha_firma"),
            hoja.get("fecha_maxima_pago"),
            hoja.get("forma_pago_pactada"),
            hoja.get("importe_bruto"),
            hoja.get("importe_neto"),
            hoja.get("total_cobrado"),
            hoja.get("importe_pendiente"),
            hoja.get("observaciones"),
        ]

        return " ".join(
            str(value or "")
            for value in values
        ).lower()


    def hoja_matches_search(hoja):
        query = str(
            state.get("hojas_search") or ""
        ).strip().lower()

        if not query:
            return True

        tokens = [
            token
            for token in query.split()
            if token
        ]

        blob = _hoja_search_blob(hoja)

        return all(
            token in blob
            for token in tokens
        )


    def hoja_matches_status(hoja):
        active = str(
            state.get("hojas_status_filter") or "all"
        ).strip().upper()

        if active in ("", "ALL"):
            return True

        status = str(
            hoja.get("estado") or "PENDIENTE FIRMA"
        ).strip().upper()

        return status == active


    def filtered_hojas(include_status=True):
        rows = [
            hoja
            for hoja in economic_service.list_hojas_encargo()
            if hoja_matches_search(hoja)
        ]

        if include_status:
            rows = [
                hoja
                for hoja in rows
                if hoja_matches_status(hoja)
            ]

        return rows


    def hojas_status_counts():
        rows = filtered_hojas(include_status=False)

        counts = {
            "all": len(rows),
            "PENDIENTE FIRMA": 0,
            "FIRMADA": 0,
            "CANCELADA": 0,
            "ARCHIVADA": 0,
        }

        for hoja in rows:
            status = str(
                hoja.get("estado")
                or "PENDIENTE FIRMA"
            ).strip().upper()

            counts[status] = counts.get(status, 0) + 1

        return counts


    def refresh_hojas_results_only():
        hojas_results_box.content = build_hojas_results()
        hojas_status_box.content = build_hojas_status_filters()

        has_filters = bool(
            str(state.get("hojas_search") or "").strip()
            or str(
                state.get("hojas_status_filter") or "all"
            ).strip() not in ("", "all")
        )

        hojas_clear_button.disabled = not has_filters
        hojas_clear_button.icon_color = (
            Q_PRIMARY_DARK if has_filters else "#98A2B3"
        )
        hojas_clear_button.tooltip = (
            "Reiniciar filtros"
            if has_filters
            else "No hay filtros activos"
        )

        try:
            hojas_results_box.update()
            hojas_status_box.update()
            hojas_clear_button.update()
        except Exception:
            page.update()


    def on_hojas_search_change(e=None):
        state["hojas_search"] = str(
            hojas_filter.value or ""
        )
        state["hojas_page"] = 1
        refresh_hojas_results_only()


    def on_hojas_status_select(value):
        state["hojas_status_filter"] = str(
            value or "all"
        )
        state["hojas_page"] = 1
        refresh_hojas_results_only()


    def clear_hojas_filters(e=None):
        hojas_filter.value = ""
        state["hojas_search"] = ""
        state["hojas_status_filter"] = "all"
        state["hojas_page"] = 1
        refresh_hojas_results_only()

        try:
            hojas_filter.update()
        except Exception:
            page.update()


    def go_hojas_page(page_number):
        try:
            requested = int(page_number)
        except (TypeError, ValueError):
            requested = 1

        rows = filtered_hojas()
        page_size = max(
            1,
            int(state.get("hojas_page_size") or 10),
        )
        total_pages = max(
            1,
            (len(rows) + page_size - 1) // page_size,
        )

        state["hojas_page"] = max(
            1,
            min(requested, total_pages),
        )
        refresh_hojas_results_only()


    hojas_filter.on_change = on_hojas_search_change
    hojas_filter.on_submit = on_hojas_search_change


    def build_hojas_status_filters():
        status_map = {
            "all": (
                "Todas",
                "#F8FAFC",
                "#475569",
                "#CBD5E1",
            ),
            "PENDIENTE FIRMA": (
                "Pendientes",
                "#FFFAEB",
                "#B54708",
                "#FEC84B",
            ),
            "FIRMADA": (
                "Firmadas",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "CANCELADA": (
                "Canceladas",
                "#FEF3F2",
                "#B42318",
                "#FDA29B",
            ),
            "ARCHIVADA": (
                "Archivadas",
                "#F2F4F7",
                "#475467",
                "#D0D5DD",
            ),
        }

        return counter_chips(
            options=[
                ("PENDIENTE FIRMA", "Pendientes"),
                ("FIRMADA", "Firmadas"),
                ("CANCELADA", "Canceladas"),
                ("ARCHIVADA", "Archivadas"),
            ],
            counts=hojas_status_counts(),
            active_value=(
                state.get("hojas_status_filter")
                or "all"
            ),
            on_select=on_hojas_status_select,
            include_all=True,
            all_label="Todas",
            all_value="all",
            status_map=status_map,
            bordered_status=True,
        )


    def build_hojas_results():
        hojas = filtered_hojas()

        if not hojas:
            state["hojas_page"] = 1

            if str(
                state.get("hojas_search") or ""
            ).strip():
                return empty_state(
                    "No hay hojas que coincidan con la búsqueda"
                )

            return empty_state(
                "No hay hojas de encargo para este estado"
            )

        page_size = max(
            1,
            int(state.get("hojas_page_size") or 10),
        )
        total_items = len(hojas)
        total_pages = max(
            1,
            (total_items + page_size - 1) // page_size,
        )

        current_page = max(
            1,
            min(
                int(state.get("hojas_page") or 1),
                total_pages,
            ),
        )
        state["hojas_page"] = current_page

        start_index = (current_page - 1) * page_size
        visible_rows = hojas[
            start_index:start_index + page_size
        ]

        cards = [
            economic_engagement_letter_card(
                dict(hoja),
                date_display=_date_to_display,
                on_edit=lambda item: (
                    open_edit_hoja_dialog(
                        dict(item)
                    )
                ),
            )
            for hoja in visible_rows
        ]

        toolbar = ft.Row(
            controls=[
                ft.Text(
                    f"Hojas registradas: {total_items}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                compact_pagination_bar(
                    page=current_page,
                    page_size=page_size,
                    total_items=total_items,
                    on_page_change=go_hojas_page,
                    label_prefix="Hojas",
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

        return ft.Column(
            controls=[
                toolbar,
                ft.Container(
                    height=620,
                    content=ft.Column(
                        controls=cards,
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=8,
        )


    def build_hojas_section():
        hojas_results_box.content = build_hojas_results()
        hojas_status_box.content = build_hojas_status_filters()

        has_filters = bool(
            str(state.get("hojas_search") or "").strip()
            or str(
                state.get("hojas_status_filter") or "all"
            ).strip() not in ("", "all")
        )

        hojas_clear_button.disabled = not has_filters
        hojas_clear_button.icon_color = (
            Q_PRIMARY_DARK if has_filters else "#98A2B3"
        )
        hojas_clear_button.tooltip = (
            "Reiniciar filtros"
            if has_filters
            else "No hay filtros activos"
        )
        hojas_clear_button.on_click = clear_hojas_filters

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        hojas_filter,
                        ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            icon_color=Q_PRIMARY_DARK,
                            tooltip="Nueva hoja de encargo",
                            on_click=open_hoja_dialog,
                        ),
                        hojas_clear_button,
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                hojas_status_box,
                hojas_results_box,
            ],
            spacing=8,
        )


    def build_table():
        if state["section"] == "conciliacion_manual":
            return build_manual_reconciliation_section()

        if state["section"] == "hojas":
            return build_hojas_section()

        if state["section"] == "cobros":
            return build_cobros_section()

        if state["section"] == "facturas":
            return build_facturas_section()

        if state["section"] == "gastos":
            return build_gastos_section()

        if state["section"] == "movimientos":
            return build_imported_movements_section()

        return empty_state("Selecciona una sección")

    # ========================================================
    # GASTOS: CARDS, BÚSQUEDA, FILTROS Y PAGINACIÓN
    # ========================================================

    state.setdefault("gastos_search", "")
    state.setdefault("gastos_quick_filter", "ALL")
    state.setdefault("gastos_date_from", None)
    state.setdefault("gastos_date_to", None)
    state.setdefault("gastos_page", 1)
    state.setdefault("gastos_page_size", 10)

    gastos_results_box = ft.Container(
        expand=True,
    )
    gastos_metrics_box = ft.Container()
    gastos_filters_box = ft.Container()
    gastos_period_summary_box = ft.Container()

    gastos_filter = text_input(
        "Buscar proveedor, concepto, factura, categoría o ID...",
        width=620,
    )
    gastos_filter.value = ""

    gasto_date_from_input = text_input(
        "Desde DD/MM/AAAA",
        width=210,
    )
    gasto_date_to_input = text_input(
        "Hasta DD/MM/AAAA",
        width=210,
    )
    gasto_period_error = ft.Text(
        "",
        size=12,
        color="#B42318",
    )

    def _gastos_money_centimos(value):
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

    def _gastos_sql_date(value):
        value = str(value or "").strip()

        if not value:
            return None

        return _date_to_sql(value)

    def set_gastos_quick_filter(filter_key):
        state["gastos_quick_filter"] = filter_key
        state["gastos_page"] = 1
        render_gastos_results()
        page.update()

    def clear_gastos_filters(e=None):
        gastos_filter.value = ""
        gasto_date_from_input.value = ""
        gasto_date_to_input.value = ""

        state["gastos_search"] = ""
        state["gastos_quick_filter"] = "ALL"
        state["gastos_date_from"] = None
        state["gastos_date_to"] = None
        state["gastos_page"] = 1

        render_gastos_results()
        page.update()

    def on_gastos_search_change(e=None):
        state["gastos_search"] = str(
            gastos_filter.value or ""
        ).strip()
        state["gastos_page"] = 1
        render_gastos_results()
        page.update()

    gastos_filter.on_change = on_gastos_search_change

    def apply_gastos_period(e=None):
        try:
            date_from = _gastos_sql_date(
                gasto_date_from_input.value
            )
            date_to = _gastos_sql_date(
                gasto_date_to_input.value
            )

            if date_from and date_to and date_from > date_to:
                raise ValueError(
                    "La fecha desde no puede ser posterior a hasta."
                )

            state["gastos_date_from"] = date_from
            state["gastos_date_to"] = date_to
            state["gastos_page"] = 1
            gasto_period_error.value = ""
            gastos_period_dialog.open = False

            render_gastos_results()
            page.update()

        except Exception as exc:
            gasto_period_error.value = str(exc)
            page.update()

    def clear_gastos_period(e=None):
        gasto_date_from_input.value = ""
        gasto_date_to_input.value = ""
        state["gastos_date_from"] = None
        state["gastos_date_to"] = None
        state["gastos_page"] = 1
        gasto_period_error.value = ""
        gastos_period_dialog.open = False

        render_gastos_results()
        page.update()

    def open_gastos_period_dialog(e=None):
        gasto_date_from_input.value = (
            _date_to_display(state["gastos_date_from"])
            if state.get("gastos_date_from")
            else ""
        )
        gasto_date_to_input.value = (
            _date_to_display(state["gastos_date_to"])
            if state.get("gastos_date_to")
            else ""
        )
        gasto_period_error.value = ""
        gastos_period_dialog.open = True
        page.update()

    gastos_period_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Filtrar gastos por periodo",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Column(
            controls=[
                ft.Text(
                    "Introduce una o ambas fechas. "
                    "Los límites están incluidos.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(
                    controls=[
                        gasto_date_from_input,
                        gasto_date_to_input,
                    ],
                    spacing=10,
                ),
                gasto_period_error,
            ],
            width=450,
            height=150,
            spacing=12,
        ),
        actions=[
            secondary_button(
                "Limpiar",
                clear_gastos_period,
            ),
            secondary_button(
                "Cancelar",
                lambda e: close(gastos_period_dialog),
            ),
            primary_button(
                "Aplicar",
                apply_gastos_period,
            ),
        ],
    )
    page.overlay.append(gastos_period_dialog)

    def set_gastos_page(page_number):
        state["gastos_page"] = max(
            1,
            int(page_number),
        )
        render_gastos_results()
        page.update()

    def toggle_gasto_active(expense):
        try:
            new_active = not bool(
                expense.get("activo", 1)
            )
            expense_service.set_expense_active(
                int(expense["id"]),
                new_active,
            )
            show_message(
                success_alert(
                    "Gasto restaurado"
                    if new_active
                    else "Gasto archivado"
                )
            )
            render_gastos_results()
            page.update()
        except Exception as exc:
            show_message(error_alert(str(exc)))

    def _gastos_metric_card(
        title,
        value,
        icon,
    ):
        return ft.Container(
            width=230,
            bgcolor="#FFFFFF",
            border=ft.Border.all(
                1,
                "#E4E7EC",
            ),
            border_radius=12,
            padding=14,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=38,
                        height=38,
                        bgcolor="#EFF8FF",
                        border_radius=10,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            icon,
                            size=20,
                            color=Q_PRIMARY_DARK,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                title,
                                size=11,
                                color=Q_MUTED,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                value,
                                size=17,
                                color=Q_PRIMARY_DARK,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

    def render_gastos_metrics(metrics):
        gastos_metrics_box.content = ft.Row(
            controls=[
                _gastos_metric_card(
                    "Gastos",
                    _gastos_money_centimos(
                        metrics.get("total_centimos")
                    ),
                    ft.Icons.PAYMENTS_OUTLINED,
                ),
                _gastos_metric_card(
                    "Base imponible",
                    _gastos_money_centimos(
                        metrics.get("base_centimos")
                    ),
                    ft.Icons.RECEIPT_LONG_OUTLINED,
                ),
                _gastos_metric_card(
                    "IVA soportado",
                    _gastos_money_centimos(
                        metrics.get("iva_centimos")
                    ),
                    ft.Icons.PERCENT,
                ),
                _gastos_metric_card(
                    "Pendiente conciliar",
                    _gastos_money_centimos(
                        metrics.get("pending_centimos")
                    ),
                    ft.Icons.SYNC_PROBLEM,
                ),
            ],
            spacing=10,
            wrap=True,
        )

    def gastos_filter_counts():
        common = {
            "search": state.get("gastos_search") or "",
            "active": True,
            "date_from": state.get("gastos_date_from"),
            "date_to": state.get("gastos_date_to"),
        }

        return {
            "ALL": expense_service.count_expenses(
                quick_filter="ALL",
                **common,
            ),
            "PENDING": expense_service.count_expenses(
                quick_filter="PENDING",
                **common,
            ),
            "WITHOUT_DOCUMENT": expense_service.count_expenses(
                quick_filter="WITHOUT_DOCUMENT",
                **common,
            ),
            "WITH_INVOICE": expense_service.count_expenses(
                quick_filter="WITH_INVOICE",
                **common,
            ),
            "RECONCILED": expense_service.count_expenses(
                quick_filter="RECONCILED",
                **common,
            ),
            "DEDUCTIBLE": expense_service.count_expenses(
                quick_filter="DEDUCTIBLE",
                **common,
            ),
            "NON_DEDUCTIBLE": expense_service.count_expenses(
                quick_filter="NON_DEDUCTIBLE",
                **common,
            ),
        }

    def render_gastos_filters():
        status_map = {
            "ALL": (
                "Todos",
                "#F2F4F7",
                "#344054",
                "#D0D5DD",
            ),
            "PENDING": (
                "Pendiente",
                "#FFF4ED",
                "#C4320A",
                "#FDB022",
            ),
            "WITHOUT_DOCUMENT": (
                "Sin justificante",
                "#FEF3F2",
                "#B42318",
                "#FDA29B",
            ),
            "WITH_INVOICE": (
                "Con factura",
                "#EFF8FF",
                "#175CD3",
                "#84CAFF",
            ),
            "RECONCILED": (
                "Conciliado",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "DEDUCTIBLE": (
                "Deducible",
                "#ECFDF3",
                "#027A48",
                "#6CE9A6",
            ),
            "NON_DEDUCTIBLE": (
                "No deducible",
                "#F2F4F7",
                "#475467",
                "#D0D5DD",
            ),
        }

        gastos_filters_box.content = counter_chips(
            options=[
                ("PENDING", "Pendientes"),
                (
                    "WITHOUT_DOCUMENT",
                    "Sin justificante",
                ),
                ("WITH_INVOICE", "Con factura"),
                ("RECONCILED", "Conciliados"),
                ("DEDUCTIBLE", "Deducibles"),
                (
                    "NON_DEDUCTIBLE",
                    "No deducibles",
                ),
            ],
            counts=gastos_filter_counts(),
            active_value=(
                state.get("gastos_quick_filter")
                or "ALL"
            ),
            on_select=set_gastos_quick_filter,
            include_all=True,
            all_label="Todos",
            all_value="ALL",
            status_map=status_map,
            bordered_status=True,
        )

    def render_gastos_period_summary():
        date_from = state.get("gastos_date_from")
        date_to = state.get("gastos_date_to")

        if not date_from and not date_to:
            gastos_period_summary_box.content = None
            return

        if date_from and date_to:
            label = (
                f"Periodo: {_date_to_display(date_from)}"
                f" – {_date_to_display(date_to)}"
            )
        elif date_from:
            label = (
                f"Desde {_date_to_display(date_from)}"
            )
        else:
            label = (
                f"Hasta {_date_to_display(date_to)}"
            )

        gastos_period_summary_box.content = ft.Container(
            bgcolor="#EFF8FF",
            border_radius=8,
            padding=ft.Padding.symmetric(
                horizontal=10,
                vertical=6,
            ),
            content=ft.Text(
                label,
                size=12,
                color="#175CD3",
            ),
        )

    def render_gastos_results():
        search = state.get("gastos_search") or ""
        quick_filter = state.get(
            "gastos_quick_filter",
            "ALL",
        )
        date_from = state.get("gastos_date_from")
        date_to = state.get("gastos_date_to")
        page_number = max(
            1,
            int(state.get("gastos_page") or 1),
        )
        page_size = max(
            1,
            int(state.get("gastos_page_size") or 10),
        )

        total_items = expense_service.count_expenses(
            search=search,
            active=True,
            quick_filter=quick_filter,
            date_from=date_from,
            date_to=date_to,
        )

        max_page = max(
            1,
            (total_items + page_size - 1) // page_size,
        )

        if page_number > max_page:
            page_number = max_page
            state["gastos_page"] = page_number

        expenses = expense_service.list_expenses(
            search=search,
            active=True,
            quick_filter=quick_filter,
            date_from=date_from,
            date_to=date_to,
            limit=page_size,
            offset=(page_number - 1) * page_size,
        )

        metrics = expense_service.expense_metrics(
            search=search,
            active=True,
            quick_filter=quick_filter,
            date_from=date_from,
            date_to=date_to,
        )

        render_gastos_metrics(metrics)
        render_gastos_filters()
        render_gastos_period_summary()

        if not expenses:
            gastos_results_box.content = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.Border.all(
                    1,
                    "#E4E7EC",
                ),
                border_radius=12,
                padding=24,
                content=ft.Column(
                    controls=[
                        ft.Icon(
                            ft.Icons.RECEIPT_LONG_OUTLINED,
                            size=32,
                            color="#98A2B3",
                        ),
                        ft.Text(
                            "No hay gastos",
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            "Crea el primer gasto o modifica "
                            "los filtros aplicados.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=7,
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
            )
            return

        cards = [
            economic_expense_card(
                expense,
                on_edit=open_edit_gasto_dialog,
                on_toggle_active=toggle_gasto_active,
            )
            for expense in expenses
        ]

        gastos_results_box.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            (
                                f"{total_items} gastos encontrados"
                            ),
                            size=12,
                            color=Q_MUTED,
                        ),
                        compact_pagination_bar(
                            page=page_number,
                            page_size=page_size,
                            total_items=total_items,
                            on_page_change=set_gastos_page,
                            label_prefix="Gastos",
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.ListView(
                    controls=cards,
                    expand=True,
                    spacing=10,
                    padding=ft.Padding.only(
                        right=6,
                        bottom=8,
                    ),
                ),
            ],
            spacing=10,
            expand=True,
        )

    def export_filtered_expenses_to_excel(
        e=None,
    ):
        try:
            expenses = expense_service.list_expenses(
                search=(
                    state.get("gastos_search")
                    or ""
                ),
                active=True,
                quick_filter=(
                    state.get(
                        "gastos_quick_filter"
                    )
                    or "ALL"
                ),
                date_from=state.get(
                    "gastos_date_from"
                ),
                date_to=state.get(
                    "gastos_date_to"
                ),
                limit=1_000_000,
                offset=0,
            )

            result = (
                expense_export_service
                .export_expenses_to_excel(
                    expenses,
                    search=str(
                        state.get(
                            "gastos_search"
                        )
                        or ""
                    ).strip(),
                    quick_filter=str(
                        state.get(
                            "gastos_quick_filter"
                        )
                        or "ALL"
                    ),
                    date_from=state.get(
                        "gastos_date_from"
                    ),
                    date_to=state.get(
                        "gastos_date_to"
                    ),
                )
            )

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    (
                        f"Exportados "
                        f"{result['count']} gastos "
                        "a Excel."
                    )
                ),
                open=True,
            )

            try:
                page.run_task(
                    page.launch_url,
                    Path(
                        result["path"]
                    ).as_uri(),
                )
            except Exception:
                pass

            page.update()

        except Exception as exc:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"No se pudo exportar: {exc}"
                ),
                open=True,
            )
            page.update()

    def build_gastos_section():
        render_gastos_results()

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        gastos_filter,
                        ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            icon_color=Q_PRIMARY_DARK,
                            tooltip="Nuevo gasto",
                            on_click=open_gasto_dialog,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                            icon_color="#027A48",
                            tooltip=(
                                "Exportar a Excel todos los "
                                "gastos resultantes de los "
                                "filtros actuales"
                            ),
                            on_click=(
                                export_filtered_expenses_to_excel
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CALENDAR_MONTH,
                            icon_color=Q_PRIMARY_DARK,
                            tooltip="Filtrar por periodo",
                            on_click=open_gastos_period_dialog,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color="#98A2B3",
                            tooltip="Limpiar filtros",
                            on_click=clear_gastos_filters,
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                gastos_period_summary_box,
                gastos_filters_box,
                gastos_metrics_box,
                gastos_results_box,
            ],
            spacing=12,
            expand=True,
        )

    cobros_filter = text_input(
        "Buscar cobro, cliente, fecha, importe, expediente...",
        width=620,
    )
    cobros_filter.value = ""
    cobros_filter.on_change = on_cobros_search_change

    cobros_clear_button = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="#98A2B3",
        tooltip="No hay filtros activos",
        disabled=True,
        on_click=clear_cobros_search,
    )

    cobros_period_button = ft.IconButton(
        icon=ft.Icons.CALENDAR_MONTH,
        icon_color=Q_PRIMARY_DARK,
        tooltip="Filtrar cobros por periodo",
        on_click=open_cobros_period_dialog,
    )

    cobros_results_box = ft.Container()
    cobros_status_box = ft.Container()
    cobros_period_summary_box = ft.Container()

    cobros_date_from_input = text_input(
        "Desde DD/MM/AAAA",
        width=210,
    )
    cobros_date_to_input = text_input(
        "Hasta DD/MM/AAAA",
        width=210,
    )
    cobros_period_error = ft.Text(
        "",
        size=12,
        color="#B42318",
    )

    cobros_period_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Filtrar cobros por periodo",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Column(
            controls=[
                ft.Text(
                    "Introduce una o ambas fechas. Los límites están incluidos.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(
                    controls=[
                        cobros_date_from_input,
                        cobros_date_to_input,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                cobros_period_error,
            ],
            spacing=12,
            tight=True,
        ),
        actions=[
            ft.TextButton(
                "Quitar periodo",
                on_click=clear_cobros_period_filter,
            ),
            ft.TextButton(
                "Cancelar",
                on_click=close_cobros_period_dialog,
            ),
            ft.TextButton(
                "Aplicar",
                on_click=apply_cobros_period_filter,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(cobros_period_dialog)

    facturas_filter = text_input(
        "Buscar factura, cliente, fecha, importe, expediente...",
        width=620,
    )
    facturas_filter.value = ""
    facturas_filter.on_change = on_facturas_search_change

    facturas_clear_button = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="#98A2B3",
        tooltip="No hay filtros activos",
        disabled=True,
        on_click=clear_facturas_filters,
    )

    facturas_period_button = ft.IconButton(
        icon=ft.Icons.CALENDAR_MONTH,
        icon_color=Q_PRIMARY_DARK,
        tooltip="Filtrar facturas por periodo",
        on_click=open_facturas_period_dialog,
    )

    facturas_results_box = ft.Container()
    facturas_status_box = ft.Container()
    facturas_holded_box = ft.Container()
    facturas_period_summary_box = ft.Container()

    facturas_date_from_input = text_input(
        "Desde DD/MM/AAAA",
        width=210,
    )
    facturas_date_to_input = text_input(
        "Hasta DD/MM/AAAA",
        width=210,
    )
    facturas_period_error = ft.Text(
        "",
        size=12,
        color="#B42318",
    )

    facturas_period_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Filtrar facturas por periodo",
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
        content=ft.Column(
            controls=[
                ft.Text(
                    (
                        "Introduce una o ambas fechas. "
                        "Los límites están incluidos."
                    ),
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(
                    controls=[
                        facturas_date_from_input,
                        facturas_date_to_input,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                facturas_period_error,
            ],
            spacing=12,
            tight=True,
        ),
        actions=[
            ft.TextButton(
                "Quitar periodo",
                on_click=clear_facturas_period_filter,
            ),
            ft.TextButton(
                "Cancelar",
                on_click=close_facturas_period_dialog,
            ),
            ft.TextButton(
                "Aplicar",
                on_click=apply_facturas_period_filter,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(facturas_period_dialog)


    factura_delete_message = ft.Text(
        "",
        size=13,
        color=Q_PRIMARY_DARK,
    )

    rectification_original_text = ft.Text(
        "",
        size=13,
        weight=ft.FontWeight.BOLD,
    )

    rectification_date_input = ft.TextField(
        label="Fecha de la rectificativa",
        hint_text="AAAA-MM-DD",
        width=220,
        dense=True,
    )

    rectification_mode = ft.Dropdown(
        label="Tipo de rectificación",
        width=260,
        value="ANULACION_TOTAL",
        options=[
            ft.dropdown.Option(
                "ANULACION_TOTAL",
                "Anulación total",
            ),
            ft.dropdown.Option(
                "AJUSTE_MANUAL",
                "Ajuste manual",
            ),
        ],
    )
    rectification_mode.on_change = apply_rectification_mode

    rectification_cause_code = ft.Dropdown(
        label="Causa",
        width=280,
        value="ANULACION_OPERACION",
        options=[
            ft.dropdown.Option(
                "ERROR_IMPORTE",
                "Error en el importe",
            ),
            ft.dropdown.Option(
                "ERROR_DATOS",
                "Error en los datos",
            ),
            ft.dropdown.Option(
                "DEVOLUCION",
                "Devolución",
            ),
            ft.dropdown.Option(
                "DESCUENTO_POSTERIOR",
                "Descuento posterior",
            ),
            ft.dropdown.Option(
                "ANULACION_OPERACION",
                "Anulación de la operación",
            ),
            ft.dropdown.Option(
                "OTRA",
                "Otra causa",
            ),
        ],
    )

    rectification_cause_input = ft.TextField(
        label="Motivo detallado",
        multiline=True,
        min_lines=2,
        max_lines=4,
    )

    rectification_base_input = ft.TextField(
        label="Base rectificada",
        width=180,
        value="0.00",
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=update_rectification_total,
    )

    rectification_iva_input = ft.TextField(
        label="IVA rectificado",
        width=180,
        value="0.00",
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=update_rectification_total,
    )

    rectification_irpf_input = ft.TextField(
        label="IRPF rectificado",
        width=180,
        value="0.00",
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=update_rectification_total,
    )

    rectification_suplidos_input = ft.TextField(
        label="Suplidos rectificados",
        width=180,
        value="0.00",
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=update_rectification_total,
    )

    rectification_total_text = ft.Text(
        "Total rectificativa: 0.00 €",
        size=15,
        weight=ft.FontWeight.BOLD,
    )

    rectification_observations_input = ft.TextField(
        label="Observaciones internas",
        multiline=True,
        min_lines=2,
        max_lines=3,
    )

    rectification_error_text = ft.Text(
        "",
        color="#B42318",
        size=12,
    )

    rectification_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Generar factura rectificativa"),
        content=ft.Container(
            width=760,
            content=ft.Column(
                controls=[
                    rectification_original_text,
                    ft.Row(
                        controls=[
                            rectification_date_input,
                            rectification_mode,
                        ],
                        wrap=True,
                    ),
                    rectification_cause_code,
                    rectification_cause_input,
                    ft.Text(
                        "Importes de la rectificación",
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Row(
                        controls=[
                            rectification_base_input,
                            rectification_iva_input,
                            rectification_irpf_input,
                            rectification_suplidos_input,
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    rectification_total_text,
                    rectification_observations_input,
                    rectification_error_text,
                ],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton(
                "Cancelar",
                on_click=close_rectification_dialog,
            ),
            ft.FilledButton(
                "Crear rectificativa",
                on_click=confirm_rectification,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(rectification_dialog)


    factura_delete_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.DELETE_OUTLINE,
                    color="#B42318",
                ),
                ft.Text(
                    "Eliminar factura",
                    weight=ft.FontWeight.BOLD,
                    color="#B42318",
                ),
            ],
            spacing=8,
        ),
        content=ft.Column(
            controls=[
                factura_delete_message,
                ft.Container(
                    bgcolor="#FFFAEB",
                    border=ft.border.all(1, "#FEC84B"),
                    border_radius=10,
                    padding=10,
                    content=ft.Text(
                        (
                            "La factura desaparecerá del listado, "
                            "pero el cobro no será eliminado."
                        ),
                        size=11,
                        color="#B54708",
                    ),
                ),
            ],
            spacing=12,
            tight=True,
            width=480,
        ),
        actions=[
            secondary_button(
                "Cancelar",
                close_delete_factura_dialog,
            ),
            ft.TextButton(
                "Eliminar factura",
                on_click=confirm_delete_factura,
                style=ft.ButtonStyle(
                    color="#B42318",
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    page.overlay.append(factura_delete_dialog)


    movements_filter = text_input("Filtrar por concepto / motivo / fecha / ID", width=560)
    movements_filter.value = ""
    movements_results_box = ft.Container()


    # Controles independientes por formulario
    hoja_cliente_ac = AppAutocomplete(page, "Cliente", cliente_options, width=520, max_results=12)
    cobro_cliente_ac = AppAutocomplete(page, "Cliente", cliente_options, width=520, max_results=12)
    factura_cliente_ac = AppAutocomplete(page, "Cliente", cliente_options, width=520, max_results=12)

    hoja_expediente_dd = select_input("Expediente", ["Sin expediente"] + expediente_options, value="Sin expediente", width=420)
    cobro_expediente_dd = select_input("Expediente", ["Sin expediente"] + expediente_options, value="Sin expediente", width=420)
    factura_expediente_dd = select_input("Expediente", ["Sin expediente"] + expediente_options, value="Sin expediente", width=420)

    cobro_hoja_dd = select_input("Hoja de encargo", ["Sin hoja"] + hoja_options, value="Sin hoja", width=420)
    factura_hoja_dd = select_input("Hoja de encargo", ["Sin hoja"] + hoja_options, value="Sin hoja", width=420)

    def _set_dropdown_options(dropdown, values, empty_label):
        dropdown.options = [ft.dropdown.Option(empty_label)] + [ft.dropdown.Option(v) for v in values]
        dropdown.value = empty_label

    def refresh_runtime_options():
        nonlocal clientes, cliente_options, expediente_options, hoja_options

        clientes = economic_service.get_clientes_for_select()
        cliente_options = [c["display"] for c in clientes]
        expediente_options = [e["display"] for e in economic_service.get_expedientes_for_select()]
        hoja_options = [h["display"] for h in economic_service.get_hojas_for_select()]

        hoja_cliente_ac.set_options(cliente_options, clear_value=True)
        cobro_cliente_ac.set_options(cliente_options, clear_value=True)
        factura_cliente_ac.set_options(cliente_options, clear_value=True)

        _set_dropdown_options(hoja_expediente_dd, expediente_options, "Sin expediente")
        _set_dropdown_options(cobro_expediente_dd, expediente_options, "Sin expediente")
        _set_dropdown_options(factura_expediente_dd, expediente_options, "Sin expediente")
        _set_dropdown_options(cobro_hoja_dd, hoja_options, "Sin hoja")
        _set_dropdown_options(factura_hoja_dd, hoja_options, "Sin hoja")

    def refresh_hoja_expedientes_for_cliente(value=None):
        cliente_id = _id(
            hoja_cliente_ac.get_value()
        )

        options = [
            e["display"]
            for e in economic_service
            .get_expedientes_for_select(
                cliente_id=cliente_id
            )
        ] if cliente_id else expediente_options

        _set_dropdown_options(
            hoja_expediente_dd,
            options,
            "Sin expediente",
        )

        refresh_hoja_consultas_for_cliente(
            cliente_id,
            update=False,
        )

        page.update()

    def refresh_cobro_dependencies(value=None):
        cliente_id = _id(cobro_cliente_ac.get_value())

        exp_options = [
            e["display"]
            for e in economic_service.get_expedientes_for_select(cliente_id=cliente_id)
        ] if cliente_id else []

        _set_dropdown_options(cobro_expediente_dd, exp_options, "Sin expediente")

        # IMPORTANTE:
        # No vaciar hojas al seleccionar cliente. Primero cargamos todas las hojas
        # visibles para ese cliente/pagador. Después, si se selecciona expediente,
        # se filtran por expediente.
        hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id) if cliente_id else []
        _set_dropdown_options(cobro_hoja_dd, [h["display"] for h in hojas], "Sin hoja")

        page.update()

    def refresh_cobro_hojas_for_expediente(e=None):
        cliente_id = _id(cobro_cliente_ac.get_value())
        expediente_id = None if cobro_expediente_dd.value == "Sin expediente" else _id(cobro_expediente_dd.value)

        hojas = []

        if expediente_id:
            hojas = economic_service.get_hojas_for_select(
                cliente_id=cliente_id,
                expediente_id=expediente_id,
            )

            # Fallback fundamental para expedientes multicliente:
            # si cliente+expediente no devuelve hojas, buscar solo por expediente.
            if not hojas:
                hojas = economic_service.get_hojas_for_select(
                    cliente_id=None,
                    expediente_id=expediente_id,
                )

        elif cliente_id:
            # Si todavía no se ha elegido expediente, mostrar hojas del cliente.
            hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id)

        _set_dropdown_options(cobro_hoja_dd, [h["display"] for h in hojas], "Sin hoja")
        page.update()

    def refresh_factura_dependencies(value=None):
        cliente_id = _id(factura_cliente_ac.get_value())
        options = [e["display"] for e in economic_service.get_expedientes_for_select(cliente_id=cliente_id)] if cliente_id else []
        _set_dropdown_options(factura_expediente_dd, options, "Sin expediente")
        _set_dropdown_options(factura_hoja_dd, [], "Sin hoja")
        page.update()

    def refresh_factura_hojas_for_expediente(e=None):
        cliente_id = _id(factura_cliente_ac.get_value())
        expediente_id = None if factura_expediente_dd.value == "Sin expediente" else _id(factura_expediente_dd.value)
        options = [
            h["display"]
            for h in economic_service.get_hojas_for_select(cliente_id=cliente_id, expediente_id=expediente_id)
        ] if cliente_id else []
        _set_dropdown_options(factura_hoja_dd, options, "Sin hoja")
        page.update()

    hoja_cliente_ac.on_select = refresh_hoja_expedientes_for_cliente
    cobro_cliente_ac.on_select = refresh_cobro_dependencies
    factura_cliente_ac.on_select = refresh_factura_dependencies
    cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente
    factura_expediente_dd.on_change = refresh_factura_hojas_for_expediente

    # Hoja dialog
    hoja_numero = text_input("Nº hoja automático", width=180)
    hoja_fecha = text_input("Fecha firma DD/MM/AAAA", width=220)
    hoja_proc = text_input("Procedimiento", width=360)
    hoja_bruto = required_text_input("Importe bruto", width=180)
    hoja_desc_manual = text_input("Descuento manual", "0", width=180)
    hoja_consulta_state = {
        "cobro_id": None,
    }

    hoja_consulta_ac = AppAutocomplete(
        page,
        "Aplicar consulta previa",
        options=[],
        width=560,
        max_results=6,
        allow_free_text=False,
        hint_text="Selecciona un cobro de consulta disponible",
        empty_text="No hay consultas disponibles",
    )

    hoja_forma = text_input("Forma pago pactada", width=260)
    hoja_plazos = text_input("Nº plazos", "1", width=120)
    hoja_fecha_max = text_input("Fecha máxima pago DD/MM/AAAA", width=240)
    hoja_ruta = text_input("Ruta documento", width=620)
    hoja_estado = select_input("Estado", ["PENDIENTE FIRMA", "FIRMADA", "CANCELADA", "ARCHIVADA"], value="PENDIENTE FIRMA", width=220)
    hoja_obs = multiline_input("Observaciones", width=620)

    hoja_neto_text = ft.Text(
        "0,00 €",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_DARK,
    )

    hoja_economic_summary = ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, Q_BORDER),
        border_radius=10,
        padding=12,
        content=ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "IMPORTE NETO",
                            size=10,
                            weight=ft.FontWeight.BOLD,
                            color=Q_MUTED,
                        ),
                        hoja_neto_text,
                    ],
                    spacing=2,
                    tight=True,
                ),
                ft.Container(expand=True),
                ft.Text(
                    "Bruto - descuentos",
                    size=11,
                    color=Q_MUTED,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    def _hoja_float(value):
        raw = str(value or "").strip()
        raw = raw.replace("€", "").replace(" ", "")

        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")

        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    def refresh_hoja_neto(e=None):
        neto = max(
            0.0,
            _hoja_float(hoja_bruto.value)
            - _hoja_float(hoja_desc_manual.value),
        )

        hoja_neto_text.value = (
            f"{neto:,.2f} €"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        try:
            hoja_neto_text.update()
        except Exception:
            pass

    def _hoja_consulta_options(cliente_id):
        options = []

        cobros = (
            economic_service
            .list_consulta_cobros_disponibles()
        )

        for cobro in cobros:
            importe = float(
                cobro.get("importe") or 0
            )

            numero = str(
                cobro.get("numero_cobro")
                or f"Consulta #{cobro.get('id')}"
            )

            cliente_nombre = " ".join(
                part
                for part in [
                    str(cobro.get("nombre") or "").strip(),
                    str(cobro.get("primer_apellido") or "").strip(),
                    str(cobro.get("segundo_apellido") or "").strip(),
                ]
                if part
            ) or f"Cliente #{cobro.get('cliente_id') or '-'}"

            fecha = _date_to_display(
                cobro.get("fecha_cobro")
            )

            importe_text = (
                f"{importe:,.2f} €"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

            options.append({
                "id": int(cobro["id"]),
                "label": cliente_nombre,
                "subtitle": (
                    f"{numero} · {fecha} · "
                    f"{importe_text}"
                ),
                "importe": importe,
                "expediente_id": (
                    cobro.get("expediente_id")
                ),
            })

        return options


    def refresh_hoja_consultas_for_cliente(
        cliente_id=None,
        update=False,
    ):
        if cliente_id is None:
            cliente_id = _id(
                hoja_cliente_ac.get_value()
            )

        options = _hoja_consulta_options(
            cliente_id
        )

        hoja_consulta_ac.set_options(
            options,
            clear_value=True,
        )

        refresh_hoja_neto()

        if update:
            page.update()


    def on_hoja_consulta_selected(value=None):
        selected = hoja_consulta_ac.get_selected()

        if isinstance(selected, dict):
            hoja_consulta_state["cobro_id"] = int(
                selected.get("id") or 0
            ) or None
        else:
            hoja_consulta_state["cobro_id"] = None

        refresh_hoja_neto()
        page.update()


    hoja_consulta_ac.on_select = (
        on_hoja_consulta_selected
    )


    hoja_bruto.on_change = refresh_hoja_neto
    hoja_desc_manual.on_change = refresh_hoja_neto

    hoja_form_state = {
        "id": None,
    }

    hoja_save_button = primary_button(
        "Crear hoja",
        lambda e: save_hoja(e),
    )

    def open_hoja_dialog(e=None):
        hoja_form_state["id"] = None
        hoja_consulta_state["cobro_id"] = None
        refresh_runtime_options()

        hoja_dialog.title.value = "Nueva hoja de encargo"
        hoja_save_button.content.value = "Crear hoja"

        hoja_cliente_ac.set_value("", update=False)
        hoja_consulta_ac.set_disabled(
            False,
            update=False,
        )
        hoja_consulta_ac.set_options(
            _hoja_consulta_options(None),
            clear_value=True,
        )
        hoja_expediente_dd.value = "Sin expediente"
        for field in [hoja_numero, hoja_fecha, hoja_proc, hoja_bruto, hoja_ruta, hoja_obs]:
            field.value = ""
        hoja_desc_manual.value = "0"
        hoja_forma.value = ""
        hoja_plazos.value = "1"
        hoja_fecha_max.value = ""
        hoja_estado.value = "PENDIENTE FIRMA"
        refresh_hoja_neto()
        hoja_dialog.open = True
        page.update()

    def open_edit_hoja_dialog(hoja):
        hoja = dict(hoja or {})
        hoja_id = int(hoja.get("id") or 0)

        if hoja_id <= 0:
            show_message(
                error_alert("No se pudo identificar la hoja")
            )
            refresh()
            return

        loaded = economic_service.get_hoja_encargo(
            hoja_id
        )

        if not loaded:
            show_message(
                error_alert("Hoja de encargo no encontrada")
            )
            refresh()
            return

        hoja_form_state["id"] = hoja_id
        hoja_consulta_state["cobro_id"] = None
        refresh_runtime_options()

        hoja_dialog.title.value = (
            "Editar hoja de encargo"
        )
        hoja_save_button.content.value = (
            "Guardar cambios"
        )

        client_value = _option_by_id(
            cliente_options,
            loaded.get("cliente_id"),
            "",
        )

        hoja_cliente_ac.set_value(
            client_value,
            update=False,
        )

        cliente_id = loaded.get("cliente_id")

        expedientes_cliente = (
            economic_service
            .get_expedientes_for_select(
                cliente_id=cliente_id
            )
            if cliente_id
            else []
        )

        expediente_values = [
            item["display"]
            for item in expedientes_cliente
        ]

        _set_dropdown_options(
            hoja_expediente_dd,
            expediente_values,
            "Sin expediente",
        )

        hoja_expediente_dd.value = _option_by_id(
            expediente_values,
            loaded.get("expediente_id"),
            "Sin expediente",
        )

        hoja_numero.value = str(
            loaded.get("numero_hoja") or ""
        )
        hoja_fecha.value = _date_to_display(
            loaded.get("fecha_firma")
        )
        hoja_proc.value = str(
            loaded.get("procedimiento") or ""
        )
        hoja_bruto.value = str(
            loaded.get("importe_bruto") or 0
        )
        hoja_desc_manual.value = str(
            loaded.get("descuento_manual") or 0
        )
        hoja_consulta_ac.set_disabled(
            False,
            update=False,
        )
        hoja_consulta_ac.set_options(
            _hoja_consulta_options(None),
            clear_value=True,
        )

        hoja_forma.value = str(
            loaded.get("forma_pago_pactada") or ""
        )
        hoja_plazos.value = str(
            loaded.get("numero_plazos") or 1
        )
        hoja_fecha_max.value = _date_to_display(
            loaded.get("fecha_maxima_pago")
        )
        hoja_ruta.value = str(
            loaded.get("documento_ruta") or ""
        )
        hoja_estado.value = str(
            loaded.get("estado")
            or "PENDIENTE FIRMA"
        )
        hoja_obs.value = str(
            loaded.get("observaciones") or ""
        )

        refresh_hoja_neto()

        hoja_dialog.open = True
        page.update()


    def save_hoja(e=None):
        try:
            cliente_id = _id(
                hoja_cliente_ac.get_value()
            )

            if not cliente_id:
                raise ValueError(
                    "Selecciona un cliente válido"
                )

            expediente_id = (
                None
                if hoja_expediente_dd.value
                == "Sin expediente"
                else _id(
                    hoja_expediente_dd.value
                )
            )

            hoja_id = hoja_form_state.get("id")
            consulta_selected = (
                hoja_consulta_ac.get_selected()
            )

            consulta_cobro_id = (
                hoja_consulta_state.get("cobro_id")
            )

            if (
                not consulta_cobro_id
                and isinstance(consulta_selected, dict)
            ):
                consulta_cobro_id = int(
                    consulta_selected.get("id") or 0
                ) or None

            data = {
                "cliente_id": cliente_id,
                "expediente_id": expediente_id,
                "numero_hoja": hoja_numero.value,
                "fecha_firma": _date_to_sql(
                    hoja_fecha.value
                ),
                "procedimiento": hoja_proc.value,
                "importe_bruto": hoja_bruto.value,
                "descuento_manual": (
                    hoja_desc_manual.value
                ),
                "descuento_consultas_previas": "0",
                "forma_pago_pactada": hoja_forma.value,
                "numero_plazos": hoja_plazos.value,
                "fecha_maxima_pago": _date_to_sql(
                    hoja_fecha_max.value
                ),
                "documento_ruta": hoja_ruta.value,
                "estado": hoja_estado.value,
                "observaciones": hoja_obs.value,
            }

            is_edit = bool(hoja_id)

            if is_edit:
                economic_service.update_hoja_encargo(
                    hoja_id,
                    data,
                )
                message = (
                    "Hoja de encargo actualizada"
                )
            else:
                hoja_id = (
                    economic_service
                    .create_hoja_encargo(data)
                )
                message = (
                    "Hoja de encargo creada"
                )

            if consulta_cobro_id:
                economic_service.aplicar_cobro_consulta_a_hoja(
                    cobro_id=int(consulta_cobro_id),
                    expediente_id=expediente_id,
                    hoja_encargo_id=hoja_id,
                    importe_aplicado=None,
                    observaciones=(
                        "Aplicada al editar la hoja"
                        if is_edit
                        else "Aplicada al crear la hoja"
                    ),
                )

                message += (
                    " y consulta previa aplicada"
                )

            hoja_dialog.open = False
            hoja_form_state["id"] = None
            hoja_consulta_state["cobro_id"] = None

            refresh_runtime_options()
            show_message(
                success_alert(message)
            )

        except Exception as exc:
            show_message(
                error_alert(str(exc))
            )

        refresh()


    def _hoja_form_section(title, subtitle, controls):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text(
                        title,
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        subtitle,
                        size=11,
                        color=Q_MUTED,
                    ),
                    ft.Divider(height=10, color="#EAECF0"),
                    *controls,
                ],
                spacing=10,
            ),
        )


    hoja_dialog = form_dialog(
        "Nueva hoja de encargo",
        ft.Column(
            controls=[
                _hoja_form_section(
                    "Cliente y expediente",
                    "Selecciona el titular y, cuando proceda, el expediente relacionado.",
                    [
                        hoja_cliente_ac.control,
                        hoja_expediente_dd,
                    ],
                ),
                _hoja_form_section(
                    "Datos del encargo",
                    "Identificación, fecha, procedimiento y estado de la hoja.",
                    [
                        ft.Row(
                            controls=[
                                hoja_numero,
                                hoja_fecha,
                                hoja_estado,
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        hoja_proc,
                    ],
                ),
                _hoja_form_section(
                    "Condiciones económicas",
                    "Importe pactado y descuentos que reducen el importe neto.",
                    [
                        ft.Row(
                            controls=[
                                hoja_bruto,
                                hoja_desc_manual,
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        hoja_consulta_ac.control,
                        hoja_economic_summary,
                    ],
                ),
                _hoja_form_section(
                    "Forma y plazo de pago",
                    "Define la modalidad, número de plazos y fecha máxima.",
                    [
                        ft.Row(
                            controls=[
                                hoja_forma,
                                hoja_plazos,
                                hoja_fecha_max,
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                    ],
                ),
                _hoja_form_section(
                    "Documento y observaciones",
                    "Ruta del documento contractual e información interna adicional.",
                    [
                        hoja_ruta,
                        hoja_obs,
                    ],
                ),
            ],
            width=820,
            height=650,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [
            secondary_button(
                "Cancelar",
                lambda e: close(hoja_dialog),
            ),
            hoja_save_button,
        ],
    )
    page.overlay.append(hoja_dialog)

    # Cobro dialog
    cobro_fecha = required_text_input("Fecha cobro DD/MM/AAAA", width=220)
    cobro_numero = text_input("Nº cobro automático", width=220)
    cobro_importe = required_text_input("Importe", width=160)
    cobro_forma = select_input("Forma pago", ["EFECTIVO", "TRANSFERENCIA", "TARJETA", "BIZUM", "OTRO"], value="EFECTIVO", width=180)
    cobro_tipo = select_input("Tipo", ["CONSULTA", "PAGO_EXPEDIENTE", "PAGO_PARCIAL", "RESERVA", "DEVOLUCION", "AJUSTE"], value="PAGO_EXPEDIENTE", width=220)
    cobro_facturable = select_input(
        "Facturable",
        ["No", "Sí"],
        value="No",
        width=120,
    )
    cobro_tipo_fiscal = select_input(
        "Naturaleza fiscal",
        ["PROVISIÓN", "SUPLIDO"],
        value="PROVISIÓN",
        width=180,
    )
    cobro_iva_porcentaje = select_input(
        "IVA",
        ["0", "4", "10", "21"],
        value="0",
        width=140,
    )
    cobro_irpf_porcentaje = select_input(
        "IRPF",
        ["0", "7", "15"],
        value="0",
        width=140,
    )
    cobro_concepto = text_input("Concepto", width=420)
    cobro_recibo = text_input("Ruta recibo/documento", width=620)
    cobro_obs = multiline_input("Observaciones", width=620)

    def _find_cliente_option_by_id_for_cobro(cliente_id):
        try:
            cliente_id = int(cliente_id or 0)
        except Exception:
            return ""

        if cliente_id <= 0:
            return ""

        for option in cliente_options:
            try:
                if int(_id(option) or 0) == cliente_id:
                    return option
            except Exception:
                continue

        return ""


    def _sql_or_display_date_to_display(value):
        raw = str(value or "").strip()
        if not raw:
            return _today_display()

        if "/" in raw:
            return raw

        try:
            return _date_to_display(raw)
        except Exception:
            return raw


    def _money_centimos_to_input_value(centimos):
        try:
            return f"{int(centimos or 0) / 100:.2f}"
        except Exception:
            return ""


    def _find_created_cobro_id(cliente_id, fecha_sql, importe_value, concepto):
        import sqlite3

        conn = sqlite3.connect("database/quesada.db")
        conn.row_factory = sqlite3.Row

        try:
            row = conn.execute(
                """
                SELECT id
                FROM eco_cobros
                WHERE cliente_id = ?
                  AND fecha_cobro = ?
                  AND CAST(importe AS REAL) = CAST(? AS REAL)
                  AND COALESCE(concepto, '') = COALESCE(?, '')
                  AND COALESCE(activo, 1) = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (cliente_id, fecha_sql, importe_value, concepto),
            ).fetchone()

            if row:
                return int(row["id"] or 0)

            row = conn.execute(
                """
                SELECT id
                FROM eco_cobros
                WHERE cliente_id = ?
                  AND COALESCE(activo, 1) = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (cliente_id,),
            ).fetchone()

            return int(row["id"] or 0) if row else 0
        finally:
            conn.close()


    def _ensure_reconciliation_applications_table_global():
        import sqlite3

        conn = sqlite3.connect("database/quesada.db")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_movement_id INTEGER NOT NULL,
                    payment_id INTEGER NOT NULL,
                    client_id INTEGER,
                    expedient_id INTEGER,
                    amount_centimos INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_type, source_movement_id, payment_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_era_source
                ON economic_reconciliation_applications(source_type, source_movement_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_era_payment
                ON economic_reconciliation_applications(payment_id)
                """
            )
            conn.commit()
        finally:
            conn.close()


    def _sync_movement_legacy_summary_from_applications_global(source, movement_id):
        import sqlite3

        _ensure_reconciliation_applications_table_global()

        source_type = "cashmatic" if source == "cashmatic" else "bank"
        table = "cashmatic_movements" if source == "cashmatic" else "bank_movements"

        conn = sqlite3.connect("database/quesada.db")
        conn.row_factory = sqlite3.Row

        try:
            summary = conn.execute(
                """
                SELECT
                    COALESCE(SUM(amount_centimos), 0) AS total,
                    MIN(payment_id) AS first_payment_id,
                    MIN(client_id) AS first_client_id,
                    MIN(expedient_id) AS first_expedient_id
                FROM economic_reconciliation_applications
                WHERE source_type = ?
                  AND source_movement_id = ?
                """,
                (source_type, movement_id),
            ).fetchone()

            total = int(summary["total"] or 0)

            conn.execute(
                f"""
                UPDATE {table}
                SET
                    linked_payment_id = ?,
                    linked_client_id = ?,
                    linked_expedient_id = ?,
                    linked_amount_centimos = ?,
                    linked_target_type = CASE WHEN ? > 0 THEN 'payment' ELSE linked_target_type END,
                    linked_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE linked_at END
                WHERE id = ?
                """,
                (
                    summary["first_payment_id"],
                    summary["first_client_id"],
                    summary["first_expedient_id"],
                    total,
                    total,
                    total,
                    movement_id,
                ),
            )

            conn.commit()
        finally:
            conn.close()


    def _auto_link_created_cobro_to_pending_movement(cobro_id, cliente_id):
        import sqlite3

        ctx = state.get("pending_linked_cobro_from_reconciliation") or {}
        if not ctx or not ctx.get("auto_link_after_create"):
            return False

        source = ctx.get("source")
        movement_id = int(ctx.get("movement_id") or 0)
        suggested_amount_centimos = int(ctx.get("amount_centimos") or 0)

        if not source or movement_id <= 0 or cobro_id <= 0 or suggested_amount_centimos <= 0:
            return False

        source_type = "cashmatic" if source == "cashmatic" else "bank"

        _ensure_reconciliation_applications_table_global()

        # ------------------------------------------------------------
        # El importe a aplicar NO es necesariamente el pendiente completo
        # del movimiento. Si el usuario edita el cobro y lo crea por menos,
        # solo debe aplicarse el importe real del cobro creado.
        # ------------------------------------------------------------
        import sqlite3

        conn_amount = sqlite3.connect("database/quesada.db")
        conn_amount.row_factory = sqlite3.Row

        try:
            cobro_row = conn_amount.execute(
                """
                SELECT id, importe
                FROM eco_cobros
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (cobro_id,),
            ).fetchone()

            if not cobro_row:
                return False

            cobro_amount_centimos = int(round(float(cobro_row["importe"] or 0) * 100))

            already_applied_to_movement = int(conn_amount.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_reconciliation_applications
                WHERE source_type = ?
                  AND source_movement_id = ?
                """,
                (source_type, movement_id),
            ).fetchone()["total"] or 0)

            table = "cashmatic_movements" if source == "cashmatic" else "bank_movements"
            amount_field = "requested_centimos" if source == "cashmatic" else "amount_centimos"

            movement_row = conn_amount.execute(
                f"""
                SELECT {amount_field} AS movement_amount_centimos
                FROM {table}
                WHERE id = ?
                """,
                (movement_id,),
            ).fetchone()

            movement_amount_centimos = abs(int(
                (movement_row["movement_amount_centimos"] if movement_row else suggested_amount_centimos) or 0
            ))

            movement_pending_centimos = max(0, movement_amount_centimos - already_applied_to_movement)
            amount_centimos = min(cobro_amount_centimos, movement_pending_centimos)

            if amount_centimos <= 0:
                return False
        finally:
            conn_amount.close()

        notes = "\n".join(
            [
                "Cobro generado y vinculado automáticamente desde Económico > Movimientos",
                f"Origen: {source}",
                f"Movimiento: {movement_id}",
                f"Fecha movimiento: {ctx.get('date') or ''}",
                f"Concepto movimiento: {ctx.get('concept') or ''}",
                f"Importe sugerido inicialmente: {_money_centimos(suggested_amount_centimos)}",
                f"Importe real del cobro creado: {_money_centimos(cobro_amount_centimos)}",
                f"Importe aplicado finalmente: {_money_centimos(amount_centimos)}",
            ]
        )

        conn = sqlite3.connect("database/quesada.db")
        try:
            existing = conn.execute(
                """
                SELECT id
                FROM economic_reconciliation_applications
                WHERE source_type = ?
                  AND source_movement_id = ?
                  AND payment_id = ?
                """,
                (source_type, movement_id, cobro_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE economic_reconciliation_applications
                    SET amount_centimos = ?,
                        client_id = COALESCE(client_id, ?),
                        notes = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (amount_centimos, cliente_id, notes, existing[0]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO economic_reconciliation_applications (
                        source_type,
                        source_movement_id,
                        payment_id,
                        client_id,
                        amount_centimos,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_type,
                        movement_id,
                        cobro_id,
                        cliente_id,
                        amount_centimos,
                        notes,
                    ),
                )

            conn.commit()
        finally:
            conn.close()

        _sync_movement_legacy_summary_from_applications_global(source, movement_id)
        update_cobro_as_reconciled(cobro_id, source, movement_id)

        try:
            state.setdefault("movements_cache", {}).pop(source, None)
        except Exception:
            state["movements_cache"] = {}

        return True


    def _reopen_reconciliation_after_generated_cobro():
        ctx = state.get("pending_linked_cobro_from_reconciliation") or {}
        if not ctx or not ctx.get("auto_reopen_reconciliation"):
            return

        source = ctx.get("source")
        movement_id = int(ctx.get("movement_id") or 0)
        item = ctx.get("movement_item") or {}

        if not item:
            item = {
                "id": movement_id,
                "requested_centimos": ctx.get("movement_amount_centimos"),
                "amount_centimos": ctx.get("movement_amount_centimos"),
                "start_time": ctx.get("date"),
                "operation_date": ctx.get("date"),
                "concept": ctx.get("concept"),
                "description": ctx.get("concept"),
                "motivo": ctx.get("concept"),
            }

        if not source or movement_id <= 0:
            return

        try:
            open_movement_reconciliation_action(source, item)
        except Exception:
            pass






    def open_cobro_dialog(e=None):
        refresh_runtime_options()

        linked_ctx = state.get("pending_linked_cobro_from_reconciliation") or {}

        cobro_cliente_ac.set_value("", update=False)
        cobro_expediente_dd.value = "Sin expediente"
        cobro_hoja_dd.value = "Sin hoja"
        cobro_fecha.value = _today_display()
        cobro_numero.value = ""
        cobro_importe.value = ""
        cobro_forma.value = "EFECTIVO"
        cobro_tipo.value = "PAGO_EXPEDIENTE"
        cobro_facturable.value = "No"
        cobro_tipo_fiscal.value = "PROVISIÓN"
        cobro_iva_porcentaje.value = "0"
        cobro_irpf_porcentaje.value = "0"
        cobro_concepto.value = ""
        cobro_recibo.value = ""
        cobro_obs.value = ""

        if linked_ctx:
            # En cobros generados desde conciliación nunca arrastramos numeración.
            # La numeración debe asignarla economic_service.create_cobro().
            cobro_numero.value = ""

            cliente_option = _find_cliente_option_by_id_for_cobro(linked_ctx.get("client_id"))
            if cliente_option:
                cobro_cliente_ac.set_value(cliente_option, update=False)

            cobro_fecha.value = _sql_or_display_date_to_display(linked_ctx.get("date"))
            cobro_importe.value = _money_centimos_to_input_value(linked_ctx.get("amount_centimos"))
            cobro_forma.value = "EFECTIVO"

            # Para permitir crear el cobro sin hoja desde conciliación.
            cobro_tipo.value = "CONSULTA"

            concept = str(linked_ctx.get("concept") or "").strip()
            cobro_concepto.value = f"Cobro generado desde movimiento: {concept}"[:400]
            cobro_obs.value = (
                "Cobro generado desde conciliación de movimientos.\n"
                f"Origen: {linked_ctx.get('source')}\n"
                f"Movimiento: {linked_ctx.get('movement_id')}\n"
                f"Importe a vincular: {_money_centimos(linked_ctx.get('amount_centimos') or 0)}"
            )

        cobro_dialog.open = True
        page.update()


    def save_cobro(e=None):
        try:
            cliente_id = _id(cobro_cliente_ac.get_value())
            if not cliente_id:
                raise ValueError("Selecciona un cliente pagador válido")

            # Las consultas previas pueden registrarse sin expediente y sin hoja.
            # Los pagos de expediente sí deben vincularse a una hoja de encargo.
            if cobro_tipo.value != "CONSULTA" and cobro_hoja_dd.value == "Sin hoja":
                raise ValueError("Selecciona una hoja de encargo para el cobro")

            fecha_sql = _date_to_sql(cobro_fecha.value)
            importe_value = cobro_importe.value
            concepto_value = cobro_concepto.value

            cobro_payload = {
                "cliente_id": cliente_id,
                "expediente_id": None if cobro_expediente_dd.value == "Sin expediente" else _id(cobro_expediente_dd.value),
                "hoja_encargo_id": None if cobro_hoja_dd.value == "Sin hoja" else _id(cobro_hoja_dd.value),
                "fecha_cobro": fecha_sql,
                "importe": importe_value,
                "forma_pago": cobro_forma.value,
                "tipo_cobro": cobro_tipo.value,
                "facturable": 1 if cobro_facturable.value == "Sí" else 0,
                "tipo_fiscal": cobro_tipo_fiscal.value,
                "iva_porcentaje": (
                    "0"
                    if cobro_tipo_fiscal.value == "SUPLIDO"
                    else cobro_iva_porcentaje.value
                ),
                "irpf_porcentaje": cobro_irpf_porcentaje.value,
                "concepto": concepto_value,
                "recibo_ruta": cobro_recibo.value,
                "observaciones": cobro_obs.value,
            }

            # No forzar numeración si el campo está vacío.
            # Dejamos que economic_service.create_cobro use su secuencia normal.
            if str(cobro_numero.value or "").strip():
                cobro_payload["numero_cobro"] = cobro_numero.value

            create_result = economic_service.create_cobro(cobro_payload)

            created_cobro_id = 0
            if isinstance(create_result, dict):
                created_cobro_id = int(create_result.get("id") or create_result.get("cobro_id") or 0)
            elif isinstance(create_result, int):
                created_cobro_id = int(create_result or 0)

            if created_cobro_id <= 0:
                created_cobro_id = _find_created_cobro_id(
                    cliente_id=cliente_id,
                    fecha_sql=fecha_sql,
                    importe_value=importe_value,
                    concepto=concepto_value,
                )

            linked_from_reconciliation = False
            if state.get("pending_linked_cobro_from_reconciliation"):
                linked_from_reconciliation = _auto_link_created_cobro_to_pending_movement(
                    created_cobro_id,
                    cliente_id,
                )

            cobro_dialog.open = False

            if linked_from_reconciliation:
                state["section"] = "movimientos"
                show_message(success_alert("Cobro creado y vinculado al movimiento"))

                try:
                    refresh()
                except Exception:
                    pass

                _reopen_reconciliation_after_generated_cobro()
                state.pop("pending_linked_cobro_from_reconciliation", None)
            else:
                show_message(success_alert("Cobro creado"))
                refresh()

        except Exception as exc:
            show_message(error_alert(str(exc)))
            refresh()


    def _cobro_form_section(
        title,
        icon,
        controls,
        *,
        subtitle=None,
        accent="#0057B8",
    ):
        section_header = [
            ft.Container(
                width=34,
                height=34,
                border_radius=10,
                bgcolor="#EAF3FF",
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(
                    icon,
                    size=18,
                    color=accent,
                ),
            ),
            ft.Column(
                controls=[
                    ft.Text(
                        title,
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    *(
                        [
                            ft.Text(
                                subtitle,
                                size=11,
                                color=Q_MUTED,
                            )
                        ]
                        if subtitle
                        else []
                    ),
                ],
                spacing=1,
            ),
        ]

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#D8E2EE"),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=section_header,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color="#E4E7EC"),
                    *controls,
                ],
                spacing=12,
            ),
        )


    cobro_dialog_header = ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, "#D8E2EE"),
        border_radius=14,
        padding=14,
        content=ft.Row(
            controls=[
                ft.Container(
                    width=44,
                    height=44,
                    border_radius=12,
                    bgcolor="#EAF3FF",
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.PAYMENTS_OUTLINED,
                        size=24,
                        color="#0057B8",
                    ),
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            "Registrar nuevo cobro",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            "Añade el pago, vincúlalo al expediente y configura su facturación.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


    cobro_dialog_content = ft.Column(
        controls=[
            cobro_dialog_header,

            _cobro_form_section(
                "Cliente pagador",
                ft.Icons.PERSON_OUTLINE,
                controls=[
                    cobro_cliente_ac.control,
                ],
                subtitle="Selecciona la persona que realiza o asume el pago.",
            ),

            _cobro_form_section(
                "Datos principales",
                ft.Icons.RECEIPT_LONG_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            cobro_fecha,
                            cobro_importe,
                            cobro_forma,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            cobro_tipo,
                            cobro_numero,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                subtitle="Fecha, importe, modalidad y naturaleza del cobro.",
            ),

            _cobro_form_section(
                "Vinculación",
                ft.Icons.LINK_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            cobro_expediente_dd,
                            cobro_hoja_dd,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border_radius=10,
                        padding=10,
                        content=ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.INFO_OUTLINE,
                                    size=16,
                                    color="#0057B8",
                                ),
                                ft.Text(
                                    (
                                        "Los pagos de expediente deben vincularse a una hoja "
                                        "de encargo. Las consultas pueden registrarse sin hoja."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                    ),
                ],
                subtitle="Relaciona el cobro con su expediente y hoja de encargo.",
            ),

            _cobro_form_section(
                "Facturación",
                ft.Icons.DESCRIPTION_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            cobro_facturable,
                            cobro_tipo_fiscal,
                            cobro_iva_porcentaje,
                            cobro_irpf_porcentaje,
                            ft.Container(
                                width=310,
                                bgcolor="#FFFAEB",
                                border=ft.border.all(1, "#FEC84B"),
                                border_radius=10,
                                padding=10,
                                content=ft.Text(
                                    (
                                        "Al marcarlo como facturable, el sistema generará "
                                        "automáticamente una factura si todavía no existe."
                                    ),
                                    size=11,
                                    color="#B54708",
                                ),
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                subtitle="Define si el ingreso debe generar factura.",
                accent="#B54708",
            ),

            _cobro_form_section(
                "Información adicional",
                ft.Icons.NOTES_OUTLINED,
                controls=[
                    cobro_concepto,
                    cobro_recibo,
                    cobro_obs,
                ],
                subtitle="Concepto, justificante y observaciones internas.",
            ),
        ],
        width=820,
        height=650,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )


    cobro_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.ADD_CARD,
                    size=22,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Nuevo cobro",
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=cobro_dialog_content,
        actions=[
            secondary_button(
                "Cancelar",
                lambda e: close(cobro_dialog),
            ),
            primary_button(
                "Guardar cobro",
                save_cobro,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=16),
        inset_padding=ft.padding.symmetric(
            horizontal=24,
            vertical=18,
        ),
    )
    page.overlay.append(cobro_dialog)


    # Editar cobro dialog
    edit_cobro_state = {"id": None, "cliente_id": None}

    edit_cobro_fecha = required_text_input("Fecha cobro DD/MM/AAAA", width=220)
    edit_cobro_importe = required_text_input("Importe", width=160)
    edit_cobro_forma = select_input("Forma pago", ["EFECTIVO", "TRANSFERENCIA", "TARJETA", "BIZUM", "OTRO"], value="EFECTIVO", width=180)
    edit_cobro_tipo = select_input("Tipo", ["CONSULTA", "PAGO_EXPEDIENTE", "PAGO_PARCIAL", "RESERVA", "DEVOLUCION", "AJUSTE"], value="PAGO_EXPEDIENTE", width=220)
    edit_cobro_facturable = select_input(
        "Facturable",
        ["No", "Sí"],
        value="No",
        width=120,
    )
    edit_cobro_tipo_fiscal = select_input(
        "Naturaleza fiscal",
        ["PROVISIÓN", "SUPLIDO"],
        value="PROVISIÓN",
        width=180,
    )
    edit_cobro_iva_porcentaje = select_input(
        "IVA",
        ["0", "4", "10", "21"],
        value="0",
        width=140,
    )
    edit_cobro_irpf_porcentaje = select_input(
        "IRPF",
        ["0", "7", "15"],
        value="0",
        width=140,
    )
    edit_cobro_expediente_dd = select_input("Expediente", ["Sin expediente"] + expediente_options, value="Sin expediente", width=420)
    edit_cobro_hoja_dd = select_input("Hoja de encargo", ["Sin hoja"], value="Sin hoja", width=420)
    edit_cobro_concepto = text_input("Concepto", width=420)
    edit_cobro_recibo = text_input("Ruta recibo/documento", width=620)
    edit_cobro_obs = multiline_input("Observaciones", width=620)

    def refresh_edit_cobro_hojas(e=None):
        cliente_id = edit_cobro_state.get("cliente_id")
        expediente_id = None if edit_cobro_expediente_dd.value == "Sin expediente" else _id(edit_cobro_expediente_dd.value)

        hojas = []
        if expediente_id:
            hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id, expediente_id=expediente_id)
            if not hojas:
                hojas = economic_service.get_hojas_for_select(cliente_id=None, expediente_id=expediente_id)
        elif cliente_id:
            hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id)

        _set_dropdown_options(edit_cobro_hoja_dd, [h["display"] for h in hojas], "Sin hoja")
        page.update()

    edit_cobro_expediente_dd.on_change = refresh_edit_cobro_hojas

    def open_edit_cobro_dialog(cobro):
        refresh_runtime_options()

        edit_cobro_state["id"] = cobro.get("id")
        edit_cobro_state["cliente_id"] = cobro.get("cliente_id")

        cliente_id = cobro.get("cliente_id")
        exp_options = [
            e["display"]
            for e in economic_service.get_expedientes_for_select(cliente_id=cliente_id)
        ] if cliente_id else expediente_options

        _set_dropdown_options(edit_cobro_expediente_dd, exp_options, "Sin expediente")
        edit_cobro_expediente_dd.value = _option_by_id(exp_options, cobro.get("expediente_id"), "Sin expediente")

        hojas = []
        if cobro.get("expediente_id"):
            hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id, expediente_id=cobro.get("expediente_id"))
            if not hojas:
                hojas = economic_service.get_hojas_for_select(cliente_id=None, expediente_id=cobro.get("expediente_id"))
        elif cliente_id:
            hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id)

        hoja_opts = [h["display"] for h in hojas]
        _set_dropdown_options(edit_cobro_hoja_dd, hoja_opts, "Sin hoja")
        edit_cobro_hoja_dd.value = _option_by_id(hoja_opts, cobro.get("hoja_encargo_id"), "Sin hoja")

        edit_cobro_fecha.value = _date_to_display(cobro.get("fecha_cobro"))
        edit_cobro_importe.value = str(cobro.get("importe") or "")
        edit_cobro_forma.value = cobro.get("forma_pago") or "EFECTIVO"
        edit_cobro_tipo.value = cobro.get("tipo_cobro") or "PAGO_EXPEDIENTE"
        edit_cobro_facturable.value = "Sí" if cobro.get("facturable") else "No"
        edit_cobro_tipo_fiscal.value = (
            "SUPLIDO"
            if str(cobro.get("tipo_fiscal") or "").upper() == "SUPLIDO"
            else "PROVISIÓN"
        )
        edit_cobro_iva_porcentaje.value = str(
            int(float(cobro.get("iva_porcentaje") or 0))
        )
        edit_cobro_irpf_porcentaje.value = str(
            int(float(cobro.get("irpf_porcentaje") or 0))
        )
        edit_cobro_concepto.value = cobro.get("concepto") or ""
        edit_cobro_recibo.value = cobro.get("recibo_ruta") or ""
        edit_cobro_obs.value = cobro.get("observaciones") or ""

        edit_cobro_dialog.open = True
        page.update()

    def save_edit_cobro(e=None):
        try:
            cobro_id = edit_cobro_state.get("id")
            if not cobro_id:
                raise ValueError("Cobro no identificado")

            if edit_cobro_tipo.value != "CONSULTA" and edit_cobro_hoja_dd.value == "Sin hoja":
                raise ValueError("Selecciona una hoja de encargo para el cobro")

            economic_service.update_cobro(cobro_id, {
                "fecha_cobro": _date_to_sql(edit_cobro_fecha.value),
                "expediente_id": None if edit_cobro_expediente_dd.value == "Sin expediente" else _id(edit_cobro_expediente_dd.value),
                "hoja_encargo_id": None if edit_cobro_hoja_dd.value == "Sin hoja" else _id(edit_cobro_hoja_dd.value),
                "importe": edit_cobro_importe.value,
                "forma_pago": edit_cobro_forma.value,
                "tipo_cobro": edit_cobro_tipo.value,
                "facturable": 1 if edit_cobro_facturable.value == "Sí" else 0,
                "tipo_fiscal": edit_cobro_tipo_fiscal.value,
                "iva_porcentaje": (
                    "0"
                    if edit_cobro_tipo_fiscal.value == "SUPLIDO"
                    else edit_cobro_iva_porcentaje.value
                ),
                "irpf_porcentaje": edit_cobro_irpf_porcentaje.value,
                "concepto": edit_cobro_concepto.value,
                "recibo_ruta": edit_cobro_recibo.value,
                "observaciones": edit_cobro_obs.value,
            })

            edit_cobro_dialog.open = False
            show_message(success_alert("Cobro modificado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    edit_cobro_dialog_header = ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, "#D8E2EE"),
        border_radius=14,
        padding=14,
        content=ft.Row(
            controls=[
                ft.Container(
                    width=44,
                    height=44,
                    border_radius=12,
                    bgcolor="#EAF3FF",
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.EDIT_NOTE,
                        size=24,
                        color="#0057B8",
                    ),
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            "Modificar cobro",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            "Actualiza los datos económicos, la vinculación y la facturación.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


    edit_cobro_dialog_content = ft.Column(
        controls=[
            edit_cobro_dialog_header,

            _cobro_form_section(
                "Datos principales",
                ft.Icons.RECEIPT_LONG_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            edit_cobro_fecha,
                            edit_cobro_importe,
                            edit_cobro_forma,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            edit_cobro_tipo,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                subtitle="Fecha, importe, forma de pago y naturaleza del cobro.",
            ),

            _cobro_form_section(
                "Vinculación",
                ft.Icons.LINK_OUTLINED,
                controls=[
                    edit_cobro_expediente_dd,
                    ft.Row(
                        controls=[
                            edit_cobro_hoja_dd,
                            secondary_button(
                                "Buscar hojas",
                                refresh_edit_cobro_hojas,
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border_radius=10,
                        padding=10,
                        content=ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.INFO_OUTLINE,
                                    size=16,
                                    color="#0057B8",
                                ),
                                ft.Text(
                                    (
                                        "Los pagos de expediente deben permanecer vinculados "
                                        "a una hoja de encargo. Las consultas pueden quedar sin hoja."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                    ),
                ],
                subtitle="Modifica el expediente y la hoja asociados al cobro.",
            ),

            _cobro_form_section(
                "Facturación",
                ft.Icons.DESCRIPTION_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            edit_cobro_facturable,
                            edit_cobro_tipo_fiscal,
                            edit_cobro_iva_porcentaje,
                            edit_cobro_irpf_porcentaje,
                            ft.Container(
                                width=310,
                                bgcolor="#FFFAEB",
                                border=ft.border.all(1, "#FEC84B"),
                                border_radius=10,
                                padding=10,
                                content=ft.Text(
                                    (
                                        "Si marcas el cobro como facturable, el sistema generará "
                                        "automáticamente una factura si todavía no existe."
                                    ),
                                    size=11,
                                    color="#B54708",
                                ),
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                subtitle="Controla si el cobro debe generar factura.",
                accent="#B54708",
            ),

            _cobro_form_section(
                "Información adicional",
                ft.Icons.NOTES_OUTLINED,
                controls=[
                    edit_cobro_concepto,
                    edit_cobro_recibo,
                    edit_cobro_obs,
                ],
                subtitle="Concepto, justificante y observaciones internas.",
            ),
        ],
        width=820,
        height=650,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )


    edit_cobro_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.EDIT_OUTLINED,
                    size=22,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Editar cobro",
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=edit_cobro_dialog_content,
        actions=[
            secondary_button(
                "Cancelar",
                lambda e: close(edit_cobro_dialog),
            ),
            primary_button(
                "Guardar cambios",
                save_edit_cobro,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=16),
        inset_padding=ft.padding.symmetric(
            horizontal=24,
            vertical=18,
        ),
    )
    page.overlay.append(edit_cobro_dialog)

    # Factura dialog
    fra_fecha = required_text_input("Fecha factura DD/MM/AAAA", width=220)
    fra_numero = text_input("Nº factura automático", width=220)
    fra_base = required_text_input("Base imponible", width=180)
    fra_iva = text_input("IVA", "0", width=140)
    fra_irpf = text_input("IRPF", "0", width=140)
    fra_total = text_input("Total opcional", width=160)
    fra_estado = select_input("Estado", ["BORRADOR", "EMITIDA", "APROBADA", "ANULADA"], value="BORRADOR", width=180)
    fra_ruta = text_input("Ruta factura", width=620)
    fra_obs = multiline_input("Observaciones", width=620)

    def open_factura_dialog(e=None):
        refresh_runtime_options()
        factura_cliente_ac.set_value("", update=False)
        factura_expediente_dd.value = "Sin expediente"
        factura_hoja_dd.value = "Sin hoja"
        fra_fecha.value = _today_display()
        fra_numero.value = ""
        fra_base.value = ""
        fra_iva.value = "0"
        fra_irpf.value = "0"
        fra_total.value = ""
        fra_estado.value = "BORRADOR"
        fra_ruta.value = ""
        fra_obs.value = ""
        factura_dialog.open = True
        page.update()

    def save_factura(e=None):
        try:
            cliente_id = _id(factura_cliente_ac.get_value())
            if not cliente_id:
                raise ValueError("Selecciona un cliente válido")

            economic_service.create_factura({
                "cliente_id": cliente_id,
                "expediente_id": None if factura_expediente_dd.value == "Sin expediente" else _id(factura_expediente_dd.value),
                "hoja_encargo_id": None if factura_hoja_dd.value == "Sin hoja" else _id(factura_hoja_dd.value),
                "numero_factura": fra_numero.value,
                "fecha_factura": _date_to_sql(fra_fecha.value),
                "base_imponible": fra_base.value,
                "iva": fra_iva.value,
                "irpf": fra_irpf.value,
                "total": fra_total.value,
                "estado": fra_estado.value,
                "documento_ruta": fra_ruta.value,
                "observaciones": fra_obs.value,
            })
            factura_dialog.open = False
            show_message(success_alert("Factura creada"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    factura_dialog = form_dialog(
        "Factura",
        ft.Column(
            [
                factura_cliente_ac.control,
                factura_expediente_dd,
                factura_hoja_dd,
                ft.Row([fra_fecha, fra_numero, fra_estado], wrap=True, spacing=10),
                ft.Row([fra_base, fra_iva, fra_irpf, fra_total], wrap=True, spacing=10),
                fra_ruta,
                fra_obs,
            ],
            width=760,
            height=560,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(factura_dialog)), primary_button("Guardar", save_factura)],
    )
    page.overlay.append(factura_dialog)

    # ========================================================
    # GASTOS: DIÁLOGO MODERNO DE ALTA Y EDICIÓN
    # ========================================================

    gasto_form_state = {
        "editing_id": None,
        "supplier_id": None,
        "calculating": False,
        "classification_suggestion": None,
        "counterparty_id": None,
        "expense_category_id": None,
        "expense_subcategory_id": None,
        "classification_rule_id": None,
        "classification_confidence": 0.0,
        "tax_model": "",
    }

    supplier_rows = supplier_service.list_suppliers(
        active=True,
        limit=2000,
    )

    gasto_supplier_by_label = {}
    gasto_supplier_options = []

    for supplier in supplier_rows:
        label_parts = [
            str(supplier.get("legal_name") or "").strip(),
            str(supplier.get("tax_id") or "").strip(),
        ]

        label = " · ".join(
            part
            for part in label_parts
            if part
        )

        option = {
            "id": supplier.get("id"),
            "label": label,
            "subtitle": (
                supplier.get("category")
                or supplier.get("services_description")
                or ""
            ),
        }

        gasto_supplier_options.append(option)
        gasto_supplier_by_label[label] = supplier

    gasto_fecha = required_text_input(
        "Fecha gasto DD/MM/AAAA",
        width=210,
    )
    gasto_fecha_factura = text_input(
        "Fecha factura DD/MM/AAAA",
        width=210,
    )
    gasto_numero_factura = text_input(
        "Número de factura",
        width=230,
    )
    gasto_concepto = required_text_input(
        "Concepto",
        width=660,
    )
    gasto_categoria = text_input(
        "Categoría",
        width=310,
    )
    gasto_forma = select_input(
        "Forma de pago",
        [
            "DIRECT_DEBIT",
            "BANK_TRANSFER",
            "CARD",
            "CASH",
            "BIZUM",
            "OTHER",
        ],
        value="DIRECT_DEBIT",
        width=230,
    )
    gasto_tipo_justificante = select_input(
        "Tipo de justificante",
        [
            "INVOICE",
            "RECEIPT",
            "BANK_STATEMENT",
            "TICKET",
            "OTHER",
        ],
        value="INVOICE",
        width=250,
    )

    gasto_base = required_text_input(
        "Base imponible",
        width=180,
    )
    gasto_iva_porcentaje = select_input(
        "IVA %",
        ["0", "4", "10", "21"],
        value="21",
        width=120,
    )
    gasto_iva_importe = text_input(
        "IVA",
        width=160,
    )
    gasto_irpf_porcentaje = select_input(
        "IRPF %",
        ["0", "1", "2", "7", "15", "19"],
        value="0",
        width=120,
    )
    gasto_irpf_importe = text_input(
        "IRPF",
        width=160,
    )
    gasto_otros = text_input(
        "Otros impuestos/ajustes",
        width=210,
    )
    gasto_total = required_text_input(
        "Total",
        width=180,
    )

    gasto_deducible_irpf = select_input(
        "Deducible IRPF",
        ["Sí", "No"],
        value="Sí",
        width=160,
    )
    gasto_iva_deducible = select_input(
        "IVA deducible",
        ["Sí", "No"],
        value="Sí",
        width=160,
    )
    gasto_porcentaje_deducible = text_input(
        "% deducible",
        value="100",
        width=150,
    )
    gasto_estado_fiscal = select_input(
        "Estado fiscal",
        [
            "PENDIENTE_REVISION",
            "DEDUCIBLE",
            "NO_DEDUCIBLE",
            "DEDUCIBLE_PARCIAL",
        ],
        value="PENDIENTE_REVISION",
        width=240,
    )
    gasto_estado_documental = select_input(
        "Estado documental",
        [
            "SIN_JUSTIFICANTE",
            "JUSTIFICANTE_ADJUNTO",
            "FACTURA_RECIBIDA",
            "DOCUMENTO_REVISADO",
        ],
        value="SIN_JUSTIFICANTE",
        width=250,
    )
    gasto_estado_conciliacion = select_input(
        "Conciliación",
        [
            "PENDIENTE",
            "PARCIAL",
            "CONCILIADO",
            "NO_REQUIERE_CONCILIACION",
        ],
        value="PENDIENTE",
        width=260,
    )

    gasto_ruta = text_input(
        "Ruta del justificante",
        width=660,
    )
    gasto_periodo_desde = text_input(
        "Periodo desde DD/MM/AAAA",
        width=220,
    )
    gasto_periodo_hasta = text_input(
        "Periodo hasta DD/MM/AAAA",
        width=220,
    )
    gasto_vencimiento = text_input(
        "Vencimiento DD/MM/AAAA",
        width=220,
    )
    gasto_obs = multiline_input(
        "Observaciones",
        width=660,
        height=100,
    )

    gasto_total_summary = ft.Text(
        "Total calculado: 0,00 €",
        size=14,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_DARK,
    )
    gasto_calculation_error = ft.Text(
        "",
        size=11,
        color="#B42318",
    )

    gasto_apply_suggestion = select_input(
        "Aplicar sugerencia",
        ["Sí", "No"],
        value="No",
        width=190,
    )

    gasto_classification_title = ft.Text(
        "Sin sugerencia automática",
        size=13,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_DARK,
    )

    gasto_classification_detail = ft.Text(
        (
            "El gasto se guardará con clasificación "
            "manual o pendiente de revisión."
        ),
        size=11,
        color=Q_MUTED,
    )

    gasto_classification_badge = ft.Container(
        bgcolor="#F2F4F7",
        border_radius=999,
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=5,
        ),
        content=ft.Text(
            "MANUAL",
            size=10,
            weight=ft.FontWeight.W_600,
            color="#475467",
        ),
    )

    def _expense_decimal(value, default=0.0):
        raw = str(value or "").strip()

        if not raw:
            return float(default)

        normalized = raw.replace(" ", "")

        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = (
                    normalized
                    .replace(".", "")
                    .replace(",", ".")
                )
            else:
                normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")

        return round(float(normalized), 4)

    def _expense_centimos(value):
        return int(
            round(
                _expense_decimal(value) * 100
            )
        )

    def _expense_input_from_centimos(value):
        try:
            amount = int(value or 0) / 100
        except Exception:
            amount = 0

        return f"{amount:.2f}".replace(".", ",")

    def _expense_format_rate(value):
        try:
            number = float(value or 0)
        except Exception:
            number = 0

        if number.is_integer():
            return str(int(number))

        return (
            f"{number:.2f}"
            .rstrip("0")
            .rstrip(".")
        )

    def _expense_form_section(
        title,
        icon,
        controls,
        *,
        subtitle=None,
        accent="#0057B8",
    ):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#D8E2EE"),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=34,
                                height=34,
                                border_radius=10,
                                bgcolor="#EAF3FF",
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(
                                    icon,
                                    size=18,
                                    color=accent,
                                ),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        title,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    *(
                                        [
                                            ft.Text(
                                                subtitle,
                                                size=11,
                                                color=Q_MUTED,
                                            )
                                        ]
                                        if subtitle
                                        else []
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
                    ft.Divider(
                        height=1,
                        color="#E4E7EC",
                    ),
                    *controls,
                ],
                spacing=12,
            ),
        )

    def set_gasto_classification_suggestion(
        suggestion,
        *,
        update=False,
    ):
        suggestion = suggestion or None

        gasto_form_state[
            "classification_suggestion"
        ] = suggestion

        if suggestion:
            gasto_form_state["counterparty_id"] = (
                suggestion.get("counterparty_id")
            )
            gasto_form_state["expense_category_id"] = (
                suggestion.get("category_id")
            )
            gasto_form_state[
                "expense_subcategory_id"
            ] = suggestion.get("subcategory_id")
            gasto_form_state[
                "classification_rule_id"
            ] = suggestion.get("id")
            gasto_form_state[
                "classification_confidence"
            ] = float(
                suggestion.get("confidence") or 0
            )
            gasto_form_state["tax_model"] = (
                suggestion.get("tax_model") or ""
            )

            gasto_apply_suggestion.value = "Sí"

            category = (
                suggestion.get("category_name")
                or "Sin categoría"
            )
            subcategory = (
                suggestion.get("subcategory_name")
                or "Sin subcategoría"
            )
            counterparty = (
                suggestion.get("counterparty_name")
                or "Sin contraparte"
            )
            confidence = int(
                round(
                    float(
                        suggestion.get("confidence")
                        or 0
                    )
                    * 100
                )
            )

            gasto_classification_title.value = (
                f"{category} · {subcategory}"
            )
            gasto_classification_detail.value = (
                f"Contraparte: {counterparty} · "
                f"Confianza: {confidence}% · "
                "Pendiente de confirmación"
            )
            gasto_classification_badge.bgcolor = (
                "#EFF8FF"
            )
            gasto_classification_badge.content = ft.Text(
                "SUGERENCIA",
                size=10,
                weight=ft.FontWeight.W_600,
                color="#175CD3",
            )
        else:
            gasto_form_state["counterparty_id"] = None
            gasto_form_state["expense_category_id"] = None
            gasto_form_state[
                "expense_subcategory_id"
            ] = None
            gasto_form_state[
                "classification_rule_id"
            ] = None
            gasto_form_state[
                "classification_confidence"
            ] = 0.0
            gasto_form_state["tax_model"] = ""

            gasto_apply_suggestion.value = "No"
            gasto_classification_title.value = (
                "Sin sugerencia automática"
            )
            gasto_classification_detail.value = (
                "El gasto se guardará con clasificación "
                "manual o pendiente de revisión."
            )
            gasto_classification_badge.bgcolor = (
                "#F2F4F7"
            )
            gasto_classification_badge.content = ft.Text(
                "MANUAL",
                size=10,
                weight=ft.FontWeight.W_600,
                color="#475467",
            )

        if update:
            for control in [
                gasto_apply_suggestion,
                gasto_classification_title,
                gasto_classification_detail,
                gasto_classification_badge,
            ]:
                try:
                    control.update()
                except Exception:
                    pass

    def update_gasto_calculation(e=None):
        if gasto_form_state["calculating"]:
            return

        gasto_form_state["calculating"] = True

        try:
            base = _expense_decimal(
                gasto_base.value
            )
            iva_rate = _expense_decimal(
                gasto_iva_porcentaje.value
            )
            irpf_rate = _expense_decimal(
                gasto_irpf_porcentaje.value
            )
            otros = _expense_decimal(
                gasto_otros.value
            )

            iva = round(
                base * iva_rate / 100,
                2,
            )
            irpf = round(
                base * irpf_rate / 100,
                2,
            )
            total = round(
                base + iva - irpf + otros,
                2,
            )

            gasto_iva_importe.value = (
                f"{iva:.2f}".replace(".", ",")
            )
            gasto_irpf_importe.value = (
                f"{irpf:.2f}".replace(".", ",")
            )
            gasto_total.value = (
                f"{total:.2f}".replace(".", ",")
            )
            gasto_total_summary.value = (
                "Total calculado: "
                f"{total:.2f} €".replace(".", ",")
            )
            gasto_calculation_error.value = ""

        except Exception:
            gasto_total_summary.value = (
                "Total calculado: —"
            )
            gasto_calculation_error.value = (
                "Revisa la base y los porcentajes."
            )

        finally:
            gasto_form_state["calculating"] = False

        try:
            gasto_iva_importe.update()
            gasto_irpf_importe.update()
            gasto_total.update()
            gasto_total_summary.update()
            gasto_calculation_error.update()
        except Exception:
            pass

    gasto_base.on_change = update_gasto_calculation
    gasto_iva_porcentaje.on_change = (
        update_gasto_calculation
    )
    gasto_irpf_porcentaje.on_change = (
        update_gasto_calculation
    )
    gasto_otros.on_change = update_gasto_calculation

    def on_gasto_supplier_selected(value):
        label = str(value or "").strip()
        supplier = gasto_supplier_by_label.get(label)

        if supplier is None:
            gasto_form_state["supplier_id"] = None
            return

        gasto_form_state["supplier_id"] = (
            supplier.get("id")
        )

        gasto_categoria.value = (
            supplier.get("category") or ""
        )
        gasto_forma.value = (
            supplier.get("usual_payment_method")
            or "DIRECT_DEBIT"
        )
        gasto_iva_porcentaje.value = (
            _expense_format_rate(
                supplier.get("usual_vat_rate")
            )
        )
        gasto_irpf_porcentaje.value = (
            _expense_format_rate(
                supplier.get("usual_irpf_rate")
            )
        )
        gasto_tipo_justificante.value = (
            supplier.get("usual_document_type")
            or "INVOICE"
        )

        if bool(supplier.get("issues_invoice")):
            gasto_estado_documental.value = (
                "FACTURA_RECIBIDA"
            )
        else:
            gasto_estado_documental.value = (
                "SIN_JUSTIFICANTE"
            )

        update_gasto_calculation()
        page.update()

    gasto_supplier_ac = AppAutocomplete(
        page=page,
        label="Proveedor opcional",
        options=gasto_supplier_options,
        value="",
        width=660,
        max_results=7,
        on_select=on_gasto_supplier_selected,
        allow_free_text=False,
        hint_text="Escribe el nombre, NIF o código",
        empty_text="No se encontró el proveedor",
    )

    def clear_gasto_form():
        gasto_form_state["editing_id"] = None
        gasto_form_state["supplier_id"] = None

        set_gasto_classification_suggestion(
            None,
            update=False,
        )

        gasto_supplier_ac.set_value(
            "",
            update=False,
        )

        gasto_fecha.value = _today_display()
        gasto_fecha_factura.value = _today_display()
        gasto_numero_factura.value = ""
        gasto_concepto.value = ""
        gasto_categoria.value = ""
        gasto_forma.value = "DIRECT_DEBIT"
        gasto_tipo_justificante.value = "INVOICE"

        gasto_base.value = ""
        gasto_iva_porcentaje.value = "21"
        gasto_iva_importe.value = "0,00"
        gasto_irpf_porcentaje.value = "0"
        gasto_irpf_importe.value = "0,00"
        gasto_otros.value = "0,00"
        gasto_total.value = ""

        gasto_deducible_irpf.value = "Sí"
        gasto_iva_deducible.value = "Sí"
        gasto_porcentaje_deducible.value = "100"
        gasto_estado_fiscal.value = (
            "PENDIENTE_REVISION"
        )
        gasto_estado_documental.value = (
            "SIN_JUSTIFICANTE"
        )
        gasto_estado_conciliacion.value = (
            "PENDIENTE"
        )

        gasto_ruta.value = ""
        gasto_periodo_desde.value = ""
        gasto_periodo_hasta.value = ""
        gasto_vencimiento.value = ""
        gasto_obs.value = ""

        gasto_total_summary.value = (
            "Total calculado: 0,00 €"
        )
        gasto_calculation_error.value = ""

    def open_gasto_dialog(e=None):
        clear_gasto_form()

        linked_movement = (
            state.get(
                "pending_expense_from_movement"
            )
            or {}
        )

        if linked_movement:
            suggestion = linked_movement.get(
                "classification_suggestion"
            )

            set_gasto_classification_suggestion(
                suggestion,
                update=False,
            )

            gasto_fecha.value = _date_to_display(
                linked_movement.get("date")
            )
            gasto_fecha_factura.value = (
                gasto_fecha.value
            )
            gasto_concepto.value = str(
                linked_movement.get("concept")
                or "Gasto generado desde movimiento bancario"
            )[:600]
            if suggestion:
                category_name = str(
                    suggestion.get("category_name")
                    or ""
                ).strip()
                subcategory_name = str(
                    suggestion.get("subcategory_name")
                    or ""
                ).strip()

                gasto_categoria.value = " · ".join(
                    value
                    for value in [
                        category_name,
                        subcategory_name,
                    ]
                    if value
                )
            else:
                gasto_categoria.value = (
                    "Gasto bancario pendiente "
                    "de clasificación"
                )

            amount_centimos = int(
                linked_movement.get(
                    "amount_centimos"
                )
                or 0
            )

            amount_value = (
                f"{amount_centimos / 100:.2f}"
                .replace(".", ",")
            )

            gasto_base.value = amount_value
            gasto_iva_porcentaje.value = "0"
            gasto_iva_importe.value = "0,00"
            gasto_irpf_porcentaje.value = "0"
            gasto_irpf_importe.value = "0,00"
            gasto_otros.value = "0,00"
            gasto_total.value = amount_value
            gasto_forma.value = "BANK_TRANSFER"
            gasto_tipo_justificante.value = (
                "BANK_STATEMENT"
            )
            gasto_estado_documental.value = (
                "SIN_JUSTIFICANTE"
            )
            gasto_estado_conciliacion.value = (
                "PENDIENTE"
            )
            gasto_total_summary.value = (
                "Total procedente del movimiento: "
                + _money_centimos(
                    amount_centimos
                )
            )
            gasto_obs.value = (
                "Gasto generado desde conciliación bancaria.\n"
                f"Banco: {linked_movement.get('bank_name') or ''}\n"
                f"Movimiento ID: {linked_movement.get('movement_id') or ''}\n"
                f"Concepto: {linked_movement.get('concept') or ''}"
            )

        gasto_dialog.title = ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.ADD_CARD,
                    size=22,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Nuevo gasto",
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        )

        gasto_dialog_header_title.value = (
            "Registrar nuevo gasto"
        )
        gasto_dialog_header_subtitle.value = (
            "Añade el justificante, los importes "
            "fiscales y el proveedor."
        )
        gasto_save_button.text = "Guardar gasto"

        gasto_dialog.open = True
        page.update()

    def open_edit_gasto_dialog(expense):
        expense_id = int(expense.get("id") or 0)

        current = expense_service.get_expense(
            expense_id
        )

        if not current:
            show_message(
                error_alert(
                    "No se encontró el gasto."
                )
            )
            refresh()
            return

        clear_gasto_form()

        gasto_form_state["editing_id"] = expense_id
        gasto_form_state["supplier_id"] = (
            current.get("supplier_id")
        )

        if current.get("expense_category_id"):
            existing_classification = {
                "id": current.get(
                    "classification_rule_id"
                ),
                "counterparty_id": current.get(
                    "counterparty_id"
                ),
                "counterparty_name": (
                    current.get(
                        "counterparty_legal_name"
                    )
                    or current.get(
                        "counterparty_name_snapshot"
                    )
                    or ""
                ),
                "category_id": current.get(
                    "expense_category_id"
                ),
                "category_name": (
                    current.get(
                        "expense_category_name"
                    )
                    or ""
                ),
                "subcategory_id": current.get(
                    "expense_subcategory_id"
                ),
                "subcategory_name": (
                    current.get(
                        "expense_subcategory_name"
                    )
                    or ""
                ),
                "confidence": current.get(
                    "classification_confidence"
                ),
                "tax_model": current.get(
                    "tax_model"
                ),
            }

            set_gasto_classification_suggestion(
                existing_classification,
                update=False,
            )
            gasto_apply_suggestion.value = "Sí"
        else:
            set_gasto_classification_suggestion(
                None,
                update=False,
            )

        supplier_label = ""

        supplier_id = current.get("supplier_id")

        if supplier_id:
            for label, supplier in (
                gasto_supplier_by_label.items()
            ):
                if int(supplier.get("id") or 0) == int(
                    supplier_id
                ):
                    supplier_label = label
                    break

        gasto_supplier_ac.set_value(
            supplier_label,
            update=False,
        )

        gasto_fecha.value = _date_to_display(
            current.get("fecha_gasto")
        )
        gasto_fecha_factura.value = _date_to_display(
            current.get("fecha_factura")
            or current.get("fecha_gasto")
        )
        gasto_numero_factura.value = (
            current.get("numero_factura") or ""
        )
        gasto_concepto.value = (
            current.get("concepto") or ""
        )
        gasto_categoria.value = (
            current.get("categoria") or ""
        )
        gasto_forma.value = (
            current.get("forma_pago")
            or "DIRECT_DEBIT"
        )
        gasto_tipo_justificante.value = (
            current.get("tipo_justificante")
            or "INVOICE"
        )

        gasto_base.value = (
            _expense_input_from_centimos(
                current.get(
                    "base_imponible_centimos"
                )
            )
        )
        gasto_iva_porcentaje.value = (
            _expense_format_rate(
                current.get("iva_porcentaje")
            )
        )
        gasto_iva_importe.value = (
            _expense_input_from_centimos(
                current.get("iva_centimos")
            )
        )
        gasto_irpf_porcentaje.value = (
            _expense_format_rate(
                current.get("irpf_porcentaje")
            )
        )
        gasto_irpf_importe.value = (
            _expense_input_from_centimos(
                current.get("irpf_centimos")
            )
        )
        gasto_otros.value = (
            _expense_input_from_centimos(
                current.get(
                    "otros_impuestos_centimos"
                )
            )
        )
        gasto_total.value = (
            _expense_input_from_centimos(
                current.get("total_centimos")
            )
        )

        gasto_deducible_irpf.value = (
            "Sí"
            if bool(
                current.get("deducible_irpf")
            )
            else "No"
        )
        gasto_iva_deducible.value = (
            "Sí"
            if bool(
                current.get("iva_deducible")
            )
            else "No"
        )
        gasto_porcentaje_deducible.value = (
            _expense_format_rate(
                current.get(
                    "porcentaje_deducible"
                )
            )
        )
        gasto_estado_fiscal.value = (
            current.get("estado_fiscal")
            or "PENDIENTE_REVISION"
        )
        gasto_estado_documental.value = (
            current.get("estado_documental")
            or "SIN_JUSTIFICANTE"
        )
        gasto_estado_conciliacion.value = (
            current.get("estado_conciliacion")
            or "PENDIENTE"
        )

        gasto_ruta.value = (
            current.get("documento_ruta")
            or current.get(
                "factura_recibida_ruta"
            )
            or ""
        )
        gasto_periodo_desde.value = _date_to_display(
            current.get("periodo_desde")
        )
        gasto_periodo_hasta.value = _date_to_display(
            current.get("periodo_hasta")
        )
        gasto_vencimiento.value = _date_to_display(
            current.get("fecha_vencimiento")
        )
        gasto_obs.value = (
            current.get("observaciones") or ""
        )

        total = (
            int(current.get("total_centimos") or 0)
            / 100
        )
        gasto_total_summary.value = (
            f"Total registrado: {total:.2f} €"
            .replace(".", ",")
        )

        gasto_dialog.title = ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.EDIT_NOTE,
                    size=22,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Editar gasto",
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        )

        gasto_dialog_header_title.value = (
            "Editar gasto registrado"
        )
        gasto_dialog_header_subtitle.value = (
            "Actualiza el justificante, los importes "
            "o su clasificación fiscal."
        )
        gasto_save_button.text = "Guardar cambios"

        gasto_dialog.open = True
        page.update()

    def _optional_expense_date(control, label):
        raw = str(control.value or "").strip()

        if not raw:
            return None

        value = _date_to_sql(raw)

        if not value:
            raise ValueError(
                f"{label} no es válida. Usa DD/MM/AAAA."
            )

        return value

    def save_gasto(e=None):
        try:
            fecha_gasto = _date_to_sql(
                gasto_fecha.value
            )

            if not fecha_gasto:
                raise ValueError(
                    "La fecha del gasto no es válida."
                )

            fecha_factura = _optional_expense_date(
                gasto_fecha_factura,
                "La fecha de factura",
            )

            base_centimos = _expense_centimos(
                gasto_base.value
            )
            iva_centimos = _expense_centimos(
                gasto_iva_importe.value
            )
            irpf_centimos = _expense_centimos(
                gasto_irpf_importe.value
            )
            otros_centimos = _expense_centimos(
                gasto_otros.value
            )
            total_centimos = _expense_centimos(
                gasto_total.value
            )

            apply_classification = (
                gasto_apply_suggestion.value == "Sí"
                and bool(
                    gasto_form_state.get(
                        "expense_category_id"
                    )
                )
            )

            payload = {
                "fecha_gasto": fecha_gasto,
                "fecha_factura": (
                    fecha_factura or fecha_gasto
                ),
                "supplier_id": (
                    gasto_form_state.get(
                        "supplier_id"
                    )
                ),
                "concepto": gasto_concepto.value,
                "categoria": gasto_categoria.value,
                "counterparty_id": (
                    gasto_form_state.get(
                        "counterparty_id"
                    )
                    if apply_classification
                    else None
                ),
                "expense_category_id": (
                    gasto_form_state.get(
                        "expense_category_id"
                    )
                    if apply_classification
                    else None
                ),
                "expense_subcategory_id": (
                    gasto_form_state.get(
                        "expense_subcategory_id"
                    )
                    if apply_classification
                    else None
                ),
                "classification_source": (
                    "RULE"
                    if (
                        apply_classification
                        and gasto_form_state.get(
                            "classification_rule_id"
                        )
                    )
                    else "MANUAL"
                ),
                "classification_rule_id": (
                    gasto_form_state.get(
                        "classification_rule_id"
                    )
                    if apply_classification
                    else None
                ),
                "classification_confidence": (
                    gasto_form_state.get(
                        "classification_confidence"
                    )
                    if apply_classification
                    else 0
                ),
                "tax_model": (
                    gasto_form_state.get(
                        "tax_model"
                    )
                    if apply_classification
                    else ""
                ),
                "numero_factura": (
                    gasto_numero_factura.value
                ),
                "tipo_justificante": (
                    gasto_tipo_justificante.value
                ),
                "forma_pago": gasto_forma.value,
                "base_imponible_centimos": (
                    base_centimos
                ),
                "iva_centimos": iva_centimos,
                "irpf_centimos": irpf_centimos,
                "otros_impuestos_centimos": (
                    otros_centimos
                ),
                "total_centimos": total_centimos,
                "iva_porcentaje": (
                    gasto_iva_porcentaje.value
                ),
                "irpf_porcentaje": (
                    gasto_irpf_porcentaje.value
                ),
                "deducible_irpf": (
                    gasto_deducible_irpf.value
                    == "Sí"
                ),
                "iva_deducible": (
                    gasto_iva_deducible.value
                    == "Sí"
                ),
                "porcentaje_deducible": (
                    gasto_porcentaje_deducible.value
                ),
                "estado_fiscal": (
                    gasto_estado_fiscal.value
                ),
                "estado_documental": (
                    gasto_estado_documental.value
                ),
                "estado_conciliacion": (
                    gasto_estado_conciliacion.value
                ),
                "documento_ruta": gasto_ruta.value,
                "periodo_desde": (
                    _optional_expense_date(
                        gasto_periodo_desde,
                        "El inicio del periodo",
                    )
                ),
                "periodo_hasta": (
                    _optional_expense_date(
                        gasto_periodo_hasta,
                        "El final del periodo",
                    )
                ),
                "fecha_vencimiento": (
                    _optional_expense_date(
                        gasto_vencimiento,
                        "La fecha de vencimiento",
                    )
                ),
                "observaciones": gasto_obs.value,
            }

            editing_id = gasto_form_state.get(
                "editing_id"
            )

            created_expense = None

            if editing_id:
                created_expense = (
                    expense_service.update_expense(
                        int(editing_id),
                        payload,
                    )
                )
                message = "Gasto actualizado"
            else:
                created_expense = (
                    expense_service.create_expense(
                        payload
                    )
                )
                message = "Gasto creado"

            linked_movement = (
                state.get(
                    "pending_expense_from_movement"
                )
                or {}
            )

            if (
                not editing_id
                and linked_movement
                and created_expense
            ):
                expense_id = int(
                    created_expense.get("id")
                    or 0
                )
                movement_id = int(
                    linked_movement.get(
                        "movement_id"
                    )
                    or 0
                )
                amount_to_apply = min(
                    int(
                        linked_movement.get(
                            "amount_centimos"
                        )
                        or 0
                    ),
                    int(
                        created_expense.get(
                            "total_centimos"
                        )
                        or 0
                    ),
                )

                if (
                    expense_id > 0
                    and movement_id > 0
                    and amount_to_apply > 0
                ):
                    (
                        expense_reconciliation_service
                        .apply_expense_reconciliation(
                            movement_id=movement_id,
                            expense_id=expense_id,
                            amount_centimos=(
                                amount_to_apply
                            ),
                            notes=(
                                "Gasto creado y conciliado "
                                "desde Económico > Movimientos"
                            ),
                        )
                    )

                    message = (
                        "Gasto creado y conciliado "
                        "con el movimiento"
                    )

                    try:
                        state.setdefault(
                            "movements_cache",
                            {},
                        ).pop(
                            linked_movement.get(
                                "source"
                            ),
                            None,
                        )
                    except Exception:
                        state["movements_cache"] = {}

                state.pop(
                    "pending_expense_from_movement",
                    None,
                )

            gasto_dialog.open = False
            clear_gasto_form()

            show_message(
                success_alert(message)
            )

            state["gastos_page"] = 1
            refresh()

        except Exception as exc:
            show_message(
                error_alert(str(exc))
            )
            refresh()

    gasto_dialog_header_title = ft.Text(
        "Registrar nuevo gasto",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=Q_PRIMARY_DARK,
    )
    gasto_dialog_header_subtitle = ft.Text(
        "Añade el justificante, los importes "
        "fiscales y el proveedor.",
        size=12,
        color=Q_MUTED,
    )

    gasto_dialog_header = ft.Container(
        bgcolor="#F8FAFC",
        border=ft.border.all(1, "#D8E2EE"),
        border_radius=14,
        padding=14,
        content=ft.Row(
            controls=[
                ft.Container(
                    width=44,
                    height=44,
                    border_radius=12,
                    bgcolor="#EAF3FF",
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.RECEIPT_LONG_OUTLINED,
                        size=24,
                        color="#0057B8",
                    ),
                ),
                ft.Column(
                    controls=[
                        gasto_dialog_header_title,
                        gasto_dialog_header_subtitle,
                    ],
                    spacing=2,
                ),
            ],
            spacing=12,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
    )

    gasto_dialog_content = ft.Column(
        controls=[
            gasto_dialog_header,

            _expense_form_section(
                "Clasificación económica",
                ft.Icons.ACCOUNT_TREE_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    gasto_classification_title,
                                    gasto_classification_detail,
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            gasto_classification_badge,
                        ],
                        alignment=(
                            ft.MainAxisAlignment
                            .SPACE_BETWEEN
                        ),
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                    ft.Row(
                        controls=[
                            gasto_apply_suggestion,
                            ft.Container(
                                width=430,
                                content=ft.Text(
                                    (
                                        "La sugerencia solo se "
                                        "guardará cuando esté "
                                        "confirmada. No crea ni "
                                        "concilia gastos de forma "
                                        "automática."
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ),
                        ],
                        spacing=12,
                        wrap=True,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                ],
                subtitle=(
                    "Contraparte, categoría y "
                    "subcategoría propuestas desde "
                    "el concepto bancario."
                ),
                accent="#175CD3",
            ),

            _expense_form_section(
                "Proveedor",
                ft.Icons.BUSINESS_OUTLINED,
                controls=[
                    gasto_supplier_ac.control,
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border_radius=10,
                        padding=10,
                        content=ft.Text(
                            (
                                "El proveedor es opcional. "
                                "Las comisiones bancarias y otros "
                                "gastos pueden registrarse sin proveedor."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ),
                ],
                subtitle=(
                    "Al seleccionarlo se cargan sus "
                    "condiciones habituales."
                ),
            ),

            _expense_form_section(
                "Datos principales",
                ft.Icons.DESCRIPTION_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            gasto_fecha,
                            gasto_fecha_factura,
                            gasto_numero_factura,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    gasto_concepto,
                    ft.Row(
                        controls=[
                            gasto_categoria,
                            gasto_forma,
                            gasto_tipo_justificante,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                subtitle=(
                    "Fecha, factura, concepto y "
                    "clasificación del gasto."
                ),
            ),

            _expense_form_section(
                "Importes",
                ft.Icons.CALCULATE_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            gasto_base,
                            gasto_iva_porcentaje,
                            gasto_iva_importe,
                            gasto_irpf_porcentaje,
                            gasto_irpf_importe,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            gasto_otros,
                            gasto_total,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Container(
                        bgcolor="#EFF8FF",
                        border=ft.border.all(
                            1,
                            "#84CAFF",
                        ),
                        border_radius=10,
                        padding=10,
                        content=ft.Column(
                            controls=[
                                gasto_total_summary,
                                gasto_calculation_error,
                                ft.Text(
                                    (
                                        "Total = Base + IVA "
                                        "− IRPF + otros ajustes"
                                    ),
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=3,
                        ),
                    ),
                ],
                subtitle=(
                    "Los importes fiscales se calculan "
                    "a partir de la base."
                ),
            ),

            _expense_form_section(
                "Fiscalidad y estados",
                ft.Icons.ACCOUNT_BALANCE_OUTLINED,
                controls=[
                    ft.Row(
                        controls=[
                            gasto_deducible_irpf,
                            gasto_iva_deducible,
                            gasto_porcentaje_deducible,
                            gasto_estado_fiscal,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            gasto_estado_documental,
                            gasto_estado_conciliacion,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                subtitle=(
                    "Configura la deducibilidad y el "
                    "estado del justificante."
                ),
            ),

            _expense_form_section(
                "Documentación y periodo",
                ft.Icons.FOLDER_OUTLINED,
                controls=[
                    gasto_ruta,
                    ft.Row(
                        controls=[
                            gasto_periodo_desde,
                            gasto_periodo_hasta,
                            gasto_vencimiento,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    gasto_obs,
                ],
                subtitle=(
                    "Documento recibido, periodo facturado "
                    "y observaciones internas."
                ),
            ),
        ],
        width=840,
        height=650,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    gasto_save_button = primary_button(
        "Guardar gasto",
        save_gasto,
    )

    gasto_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.ADD_CARD,
                    size=22,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    "Nuevo gasto",
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
        content=gasto_dialog_content,
        actions=[
            secondary_button(
                "Cancelar",
                lambda e: close(gasto_dialog),
            ),
            gasto_save_button,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(
            radius=16
        ),
        inset_padding=ft.padding.symmetric(
            horizontal=24,
            vertical=18,
        ),
    )
    page.overlay.append(gasto_dialog)

    # Movimiento dialog
    mov_origen = select_input("Origen", ["BANCO", "CASHMATIC", "STRIPE", "MANUAL"], value="BANCO", width=180)
    mov_fecha = required_text_input("Fecha operación DD/MM/AAAA", width=240)
    mov_concepto = text_input("Concepto", width=520)
    mov_importe = required_text_input("Importe", width=160)
    mov_ref = text_input("Referencia", width=260)
    mov_cuenta = text_input("Cuenta", width=220)
    mov_obs = multiline_input("Observaciones", width=620)

    def open_movimiento_dialog(e=None):
        mov_origen.value = "BANCO"
        mov_fecha.value = _today_display()
        for field in [mov_concepto, mov_importe, mov_ref, mov_cuenta, mov_obs]:
            field.value = ""
        movimiento_dialog.open = True
        page.update()

    def save_movimiento(e=None):
        try:
            economic_service.create_movimiento_importado({
                "origen": mov_origen.value,
                "fecha_operacion": _date_to_sql(mov_fecha.value),
                "concepto": mov_concepto.value,
                "importe": mov_importe.value,
                "referencia": mov_ref.value,
                "cuenta": mov_cuenta.value,
                "observaciones": mov_obs.value,
            })
            movimiento_dialog.open = False
            show_message(success_alert("Movimiento creado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    movimiento_dialog = form_dialog(
        "Movimiento importado / conciliación",
        ft.Column(
            [
                ft.Row([mov_origen, mov_fecha, mov_importe], wrap=True, spacing=10),
                mov_concepto,
                ft.Row([mov_ref, mov_cuenta], wrap=True, spacing=10),
                mov_obs,
            ],
            width=760,
            height=420,
            spacing=12,
        ),
        [secondary_button("Cancelar", lambda e: close(movimiento_dialog)), primary_button("Guardar", save_movimiento)],
    )
    page.overlay.append(movimiento_dialog)

    def close(dialog):
        dialog.open = False
        page.update()

    table_container.content = build_table()
    content_area.content = build_view()
    return content_area

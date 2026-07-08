import flet as ft
from datetime import datetime

from backend.services import economic_service
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_text_field import text_input, required_text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_dialog import form_dialog
from frontend.components.app_table import app_table
from frontend.components.app_empty_state import empty_state
from frontend.components.app_alert import success_alert, error_alert
from frontend.components.economic_badge import economic_badge
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.listing import compact_pagination_bar
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


def economic_view(page: ft.Page):
    economic_service.initialize_economic_schema()

    state = {
        "section": "cobros",
        "message": None,
        "reconciliation_selected_group_id": None,
        "movements_source": "cashmatic",
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
                section_button("conciliacion_manual", "Conciliación manual"),
            ],
            spacing=8,
            wrap=True,
        )

    def refresh(e=None):
        table_container.content = build_table()
        content_area.content = build_view()
        page.update()

    def build_view():
        resumen = economic_service.resumen_economico()
        controls = [
            ft.Text("Módulo económico", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text("Hojas de encargo, ingresos, cobros, facturas, gastos y conciliación.", size=14, color=Q_MUTED),
        ]

        if state["message"]:
            controls.append(state["message"])

        controls.extend(
            [
                ft.Row(
                    controls=[
                    ],
                    spacing=12,
                    wrap=True,
                ),
                build_nav(),
                build_actions(),
                table_container,
            ]
        )
        return ft.Column(controls=controls, spacing=18, expand=True)

    def build_actions():
        mapping = {
            "hojas": ("Nueva hoja de encargo", open_hoja_dialog),
            "cobros": ("Nuevo cobro", open_cobro_dialog),
            "facturas": ("Nueva factura", open_factura_dialog),
            "gastos": ("Nuevo gasto", open_gasto_dialog),
        }
        if state["section"] == "facturas":
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Las facturas se generan automáticamente al guardar un cobro marcado como facturable.",
                    color=Q_MUTED,
                    size=13,
                ),
            )

        action = mapping.get(state["section"])
        if not action:
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Row(controls=[], alignment=ft.MainAxisAlignment.END),
            )

        label, handler = action
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Row(controls=[primary_button(label, handler)], alignment=ft.MainAxisAlignment.END),
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


    def build_manual_reconciliation_section():
        try:
            groups = list_reconciliation_groups(limit=50)
        except Exception as exc:
            return error_alert(f"No se pudieron cargar grupos de conciliación: {exc}")

        if not groups:
            return ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Conciliación manual", size=22, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Container(expand=True),
                            primary_button("Nueva conciliación", open_reconciliation_group_dialog),
                            secondary_button("Refrescar", refresh),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        "Vincula recibos/cobros físicos o del CRM contra movimientos reales ya importados desde Cashmatic, banco o Stripe. La conciliación siempre es manual.",
                        size=13,
                        color=Q_MUTED,
                    ),
                    empty_state("No hay conciliaciones manuales todavía"),
                ],
                spacing=14,
                expand=True,
            )

        selected_id = state.get("reconciliation_selected_group_id")
        if not selected_id and groups:
            selected_id = groups[0].id
            state["reconciliation_selected_group_id"] = selected_id

        try:
            detail = get_reconciliation_group_detail(int(selected_id)) if selected_id else None
        except Exception:
            detail = None

        def select_group(group_id):
            state["reconciliation_selected_group_id"] = group_id
            refresh()

        group_cards = []
        for group in groups:
            selected = int(group.id) == int(selected_id or 0)
            group_cards.append(
                ft.Container(
                    bgcolor="#FFFFFF" if not selected else "#EAF3FF",
                    border=ft.border.all(1, "#0057B8" if selected else Q_BORDER),
                    border_radius=14,
                    padding=12,
                    ink=True,
                    on_click=lambda e, gid=group.id: select_group(gid),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(group.title or f"Grupo #{group.id}", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK, expand=True),
                                    _reconciliation_status_badge(group.status),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(f"{group.group_type} · {group.group_date or '-'}", size=12, color=Q_MUTED),
                            ft.Row(
                                controls=[
                                    ft.Text(f"Esperado: {_money_centimos(group.expected_amount_centimos)}", size=12),
                                    ft.Text(f"Real: {_money_centimos(group.actual_amount_centimos)}", size=12),
                                    ft.Text(f"Dif: {_money_centimos(group.difference_centimos)}", size=12, weight=ft.FontWeight.BOLD),
                                ],
                                wrap=True,
                                spacing=10,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            )

        expected_items = []
        actual_items = []

        if detail:
            for item in detail.items:
                row = ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(item.source_type, size=11, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(_money_centimos(item.amount_centimos), size=12, weight=ft.FontWeight.BOLD),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(item.label or "-", size=12, color="#344054"),
                        ],
                        spacing=4,
                    ),
                )
                if item.role == "EXPECTED":
                    expected_items.append(row)
                else:
                    actual_items.append(row)

        detail_panel = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Detalle de conciliación", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            _reconciliation_status_badge(detail.group.status if detail else "DRAFT"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(detail.group.title if detail else "Selecciona una conciliación", size=13, color=Q_MUTED),
                    ft.Divider(),
                    ft.Text("Recibos / cobros esperados", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Column(expected_items or [ft.Text("Sin recibos/cobros esperados", size=12, color=Q_MUTED)], spacing=8),
                    ft.Divider(),
                    ft.Text("Movimientos reales importados", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Column(actual_items or [ft.Text("Sin movimientos reales vinculados", size=12, color=Q_MUTED)], spacing=8),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Conciliación manual", size=22, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Container(expand=True),
                        primary_button("Nueva conciliación", open_reconciliation_group_dialog),
                        secondary_button("Añadir recibo/cobro", open_add_cobro_to_group_dialog),
                        secondary_button("Refrescar", refresh),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(
                    "Vincula recibos/cobros físicos o del CRM contra movimientos reales ya importados desde Cashmatic, banco o Stripe. La conciliación siempre es manual.",
                    size=13,
                    color=Q_MUTED,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            width=430,
                            content=ft.Column(
                                controls=[
                                    ft.Text("Conciliaciones", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Column(group_cards, spacing=10, scroll=ft.ScrollMode.AUTO),
                                ],
                                spacing=10,
                            ),
                        ),
                        detail_panel,
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    expand=True,
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

    def movement_reconciliation_status(item):
        """
        Estado visual preparado para conciliación manual.
        No crea vínculos ni conciliaciones automáticas.
        """
        raw_status = str(
            _get_value(item, "reconciliation_status")
            or _get_value(item, "conciliation_status")
            or _get_value(item, "manual_reconciliation_status")
            or ""
        ).strip().upper()

        if raw_status in {"PARTIAL", "PARTIAL_RECONCILED", "CONCILIACION_PARCIAL", "CONCILIACIÓN_PARCIAL"}:
            return "Conciliación parcial", "#F59E0B"

        if raw_status in {"RECONCILED", "CONCILIADO", "LINKED", "MANUALLY_LINKED"}:
            return "Conciliado", "#16A34A"

        linked_markers = [
            "linked_client_id",
            "linked_expedient_id",
            "linked_payment_id",
            "linked_at",
            "manual_link_id",
            "reconciliation_group_id",
        ]

        if any(_get_value(item, key) not in (None, "", 0) for key in linked_markers):
            return "Conciliado", "#16A34A"

        partial_markers = [
            "partial_reconciliation_id",
            "partial_link_id",
            "matched_amount_centimos",
            "reconciled_amount_centimos",
        ]

        matched = _get_value(item, "matched_amount_centimos") or _get_value(item, "reconciled_amount_centimos")
        amount = (
            _get_value(item, "net_amount_centimos")
            or _get_value(item, "amount_centimos")
            or _get_value(item, "inserted_centimos")
            or _get_value(item, "requested_centimos")
        )

        try:
            if matched not in (None, "", 0) and amount not in (None, "", 0) and abs(int(matched)) != abs(int(amount)):
                return "Conciliación parcial", "#F59E0B"
        except Exception:
            pass

        if any(_get_value(item, key) not in (None, "", 0) for key in partial_markers):
            return "Conciliación parcial", "#F59E0B"

        return "No conciliado", "#64748B"


    def movement_reconciliation_badge(item):
        label, color = movement_reconciliation_status(item)
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=color),
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
            border_radius=999,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, color),
        )


    def open_movement_reconciliation_action(source, item):
        state["movement_to_reconcile"] = {
            "source": source,
            "id": _get_value(item, "id"),
            "external_id": _get_value(item, "cashmatic_id") or _get_value(item, "bank_movement_id"),
            "amount_centimos": (
                _get_value(item, "net_amount_centimos")
                or _get_value(item, "amount_centimos")
                or _get_value(item, "inserted_centimos")
                or _get_value(item, "requested_centimos")
            ),
            "date": _get_value(item, "start_time") or _get_value(item, "operation_date"),
            "reason": _get_value(item, "reason_raw") or _get_value(item, "concept") or _get_value(item, "description"),
        }

        try:
            page.snack_bar = ft.SnackBar(
                ft.Text("Movimiento seleccionado para conciliación manual. Abre o crea una conciliación desde la sección de conciliación."),
                open=True,
            )
            page.update()
        except Exception:
            pass


    def movement_actions_button(source, item):
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Acciones",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.LINK, size=16),
                            ft.Text("Conciliar", size=13),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    on_click=lambda e, s=source, m=item: open_movement_reconciliation_action(s, m),
                ),
            ],
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
                economic_badge(_get_value(m, "movement_status")),
                movement_reconciliation_badge(m),
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

        rows = []
        for m in items:
            concept = (
                _get_value(m, "concept")
                or _get_value(m, "description")
                or _get_value(m, "reason_raw")
                or "-"
            )

            date_value = (
                _get_value(m, "operation_date")
                or _get_value(m, "value_date")
                or _get_value(m, "start_time")
            )

            amount_value = (
                _get_value(m, "amount_centimos")
                or _get_value(m, "net_amount_centimos")
                or _get_value(m, "inserted_centimos")
            )

            rows.append([
                movement_actions_button(source, m),
                _get_value(m, "id") or "-",
                _date_time_to_display(date_value),
                movement_money_text(amount_value),
                movement_reconciliation_badge(m),
                ft.Text(
                    concept,
                    size=12,
                    tooltip=str(concept),
                    selectable=True,
                    no_wrap=False,
                ),
            ])

        headers = [
            {"label": "", "key": "Acciones", "width": 60},
            {"label": "ID", "key": "ID", "width": 80},
            {"label": "Fecha", "key": "Fecha", "width": 150},
            {"label": "Importe", "key": "Importe", "width": 130},
            {"label": "Conciliación", "key": "Conciliación", "width": 170},
            {"label": "Concepto", "key": "Concepto", "width": 900},
        ]

        table = app_table(headers, rows, height=430) if rows else empty_state(f"No hay movimientos importados de {bank_name}")
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

        parts = []
        for key in [
            "batch_id",
            "inserted_rows",
            "rows_inserted",
            "inserted",
            "duplicates",
            "duplicate_rows",
            "quarantine_rows",
            "quarantine",
            "valid_rows",
            "total_rows",
        ]:
            if isinstance(result, dict) and key in result:
                parts.append(f"{key}={result.get(key)}")
            elif hasattr(result, key):
                parts.append(f"{key}={getattr(result, key)}")

        return "Importación completada" + (": " + " · ".join(parts) if parts else f": {result}")


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
            try:
                state.setdefault("movements_cache", {}).pop(source, None)
            except Exception:
                pass

            state["movements_source"] = source
            state["movements_page"] = 1
            state["movements_search"] = ""

            try:
                movements_filter.value = ""
            except Exception:
                pass

            # Reconstruye la vista y vuelve a leer los datos ya importados.
            refresh()

            try:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text(summarize_movements_import_result(result)),
                    open=True,
                )
                page.update()
            except Exception:
                pass

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


    def build_table():
        if state["section"] == "conciliacion_manual":
            return build_manual_reconciliation_section()

        if state["section"] == "hojas":
            rows = []
            for h in economic_service.list_hojas_encargo():
                cliente = f"{h.get('nombre') or ''} {h.get('primer_apellido') or ''} {h.get('segundo_apellido') or ''}".strip()
                rows.append([
                    h.get("numero_hoja") or "-",
                    _date_to_display(h.get("fecha_firma")),
                    cliente,
                    h.get("numero_expediente") or "-",
                    h.get("procedimiento") or "-",
                    _money(h.get("importe_bruto")),
                    _money(h.get("importe_neto")),
                    economic_badge(h.get("estado")),
                ])
            return app_table(
                rows,
                height=430,
            ) if rows else empty_state("No hay hojas de encargo")

        if state["section"] == "cobros":
            rows = []
            for c in economic_service.list_cobros():
                cliente = f"{c.get('nombre') or ''} {c.get('primer_apellido') or ''} {c.get('segundo_apellido') or ''}".strip()
                rows.append([
                    ft.Text(c.get("numero_cobro") or "-", weight=ft.FontWeight.BOLD, size=13, color=Q_PRIMARY_DARK),
                    _date_to_display(c.get("fecha_cobro")),
                    cliente,
                    c.get("numero_expediente") or "-",
                    c.get("numero_hoja") or "-",
                    _money(c.get("importe")),
                    c.get("forma_pago") or "-",
                    "Sí" if c.get("facturable") else "No",
                    c.get("numero_factura") or "-",
                    economic_badge(c.get("estado_conciliacion")),
                    secondary_button("Editar", lambda e, cobro=dict(c): open_edit_cobro_dialog(cobro)),
                ])
            return app_table(
                ["Nº cobro", "Fecha", "Cliente", "Expediente", "Hoja", "Importe", "Forma", "Facturable", "Factura", "Conciliación", "Editar"],
                rows,
                height=430,
            ) if rows else empty_state("No hay cobros")

        if state["section"] == "facturas":
            rows = []
            for f in economic_service.list_facturas():
                cliente = f"{f.get('nombre') or ''} {f.get('primer_apellido') or ''} {f.get('segundo_apellido') or ''}".strip()
                rows.append([
                    f.get("numero_factura") or "-",
                    _date_to_display(f.get("fecha_factura")),
                    cliente,
                    f.get("numero_expediente") or "-",
                    _money(f.get("base_imponible")),
                    _money(f.get("iva")),
                    _money(f.get("total")),
                    economic_badge(f.get("estado")),
                    "Sí" if f.get("exportada_holded") else "No",
                ])
            return app_table(
                ["Nº factura", "Fecha", "Cliente", "Expediente", "Base", "IVA", "Total", "Estado", "Holded"],
                rows,
                height=430,
            ) if rows else empty_state("No hay facturas")

        if state["section"] == "gastos":
            rows = []
            for g in economic_service.list_gastos():
                rows.append([
                    _date_to_display(g.get("fecha_gasto")),
                    g.get("proveedor") or "-",
                    g.get("concepto") or "-",
                    g.get("categoria") or "-",
                    _money(g.get("importe")),
                    g.get("forma_pago") or "-",
                    "Sí" if g.get("deducible") else "No",
                    economic_badge(g.get("estado_conciliacion")),
                ])
            return app_table(
                ["Fecha", "Proveedor", "Concepto", "Categoría", "Importe", "Forma", "Deducible", "Conciliación"],
                rows,
                height=430,
            ) if rows else empty_state("No hay gastos")

        if state["section"] == "movimientos":
            return build_imported_movements_section()

        return empty_state("Selecciona una sección")

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
        cliente_id = _id(hoja_cliente_ac.get_value())
        options = [e["display"] for e in economic_service.get_expedientes_for_select(cliente_id=cliente_id)] if cliente_id else expediente_options
        _set_dropdown_options(hoja_expediente_dd, options, "Sin expediente")
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
    hoja_desc_consulta = text_input("Descuento consultas", "0", width=180)
    hoja_forma = text_input("Forma pago pactada", width=260)
    hoja_plazos = text_input("Nº plazos", "1", width=120)
    hoja_fecha_max = text_input("Fecha máxima pago DD/MM/AAAA", width=240)
    hoja_ruta = text_input("Ruta documento", width=620)
    hoja_estado = select_input("Estado", ["PENDIENTE FIRMA", "FIRMADA", "CANCELADA", "ARCHIVADA"], value="PENDIENTE FIRMA", width=220)
    hoja_obs = multiline_input("Observaciones", width=620)

    def open_hoja_dialog(e=None):
        refresh_runtime_options()
        hoja_cliente_ac.set_value("", update=False)
        hoja_expediente_dd.value = "Sin expediente"
        for field in [hoja_numero, hoja_fecha, hoja_proc, hoja_bruto, hoja_ruta, hoja_obs]:
            field.value = ""
        hoja_desc_manual.value = "0"
        hoja_desc_consulta.value = "0"
        hoja_forma.value = ""
        hoja_plazos.value = "1"
        hoja_fecha_max.value = ""
        hoja_estado.value = "PENDIENTE FIRMA"
        hoja_dialog.open = True
        page.update()

    def save_hoja(e=None):
        try:
            cliente_id = _id(hoja_cliente_ac.get_value())
            if not cliente_id:
                raise ValueError("Selecciona un cliente válido")

            economic_service.create_hoja_encargo({
                "cliente_id": cliente_id,
                "expediente_id": None if hoja_expediente_dd.value == "Sin expediente" else _id(hoja_expediente_dd.value),
                "numero_hoja": hoja_numero.value,
                "fecha_firma": _date_to_sql(hoja_fecha.value),
                "procedimiento": hoja_proc.value,
                "importe_bruto": hoja_bruto.value,
                "descuento_manual": hoja_desc_manual.value,
                "descuento_consultas_previas": hoja_desc_consulta.value,
                "forma_pago_pactada": hoja_forma.value,
                "numero_plazos": hoja_plazos.value,
                "fecha_maxima_pago": _date_to_sql(hoja_fecha_max.value),
                "documento_ruta": hoja_ruta.value,
                "estado": hoja_estado.value,
                "observaciones": hoja_obs.value,
            })
            hoja_dialog.open = False
            refresh_runtime_options()
            show_message(success_alert("Hoja de encargo creada"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    hoja_dialog = form_dialog(
        "Hoja de encargo",
        ft.Column(
            [
                hoja_cliente_ac.control,
                hoja_expediente_dd,
                ft.Row([hoja_numero, hoja_fecha, hoja_estado], wrap=True, spacing=10),
                hoja_proc,
                ft.Row([hoja_bruto, hoja_desc_manual, hoja_desc_consulta], wrap=True, spacing=10),
                ft.Row([hoja_forma, hoja_plazos, hoja_fecha_max], wrap=True, spacing=10),
                hoja_ruta,
                hoja_obs,
            ],
            width=760,
            height=600,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(hoja_dialog)), primary_button("Guardar", save_hoja)],
    )
    page.overlay.append(hoja_dialog)

    # Cobro dialog
    cobro_fecha = required_text_input("Fecha cobro DD/MM/AAAA", width=220)
    cobro_numero = text_input("Nº cobro automático", width=220)
    cobro_importe = required_text_input("Importe", width=160)
    cobro_forma = select_input("Forma pago", ["EFECTIVO", "TRANSFERENCIA", "TARJETA", "BIZUM", "OTRO"], value="EFECTIVO", width=180)
    cobro_tipo = select_input("Tipo", ["CONSULTA", "PAGO_EXPEDIENTE", "PAGO_PARCIAL", "RESERVA", "DEVOLUCION", "AJUSTE"], value="PAGO_EXPEDIENTE", width=220)
    cobro_facturable = select_input("Facturable", ["No", "Sí"], value="No", width=120)
    cobro_concepto = text_input("Concepto", width=420)
    cobro_recibo = text_input("Ruta recibo/documento", width=620)
    cobro_obs = multiline_input("Observaciones", width=620)

    def open_cobro_dialog(e=None):
        refresh_runtime_options()
        cobro_cliente_ac.set_value("", update=False)
        cobro_expediente_dd.value = "Sin expediente"
        cobro_hoja_dd.value = "Sin hoja"
        cobro_fecha.value = _today_display()
        cobro_numero.value = ""
        cobro_importe.value = ""
        cobro_forma.value = "EFECTIVO"
        cobro_tipo.value = "PAGO_EXPEDIENTE"
        cobro_facturable.value = "No"
        cobro_concepto.value = ""
        cobro_recibo.value = ""
        cobro_obs.value = ""
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

            economic_service.create_cobro({
                "cliente_id": cliente_id,
                "expediente_id": None if cobro_expediente_dd.value == "Sin expediente" else _id(cobro_expediente_dd.value),
                "hoja_encargo_id": None if cobro_hoja_dd.value == "Sin hoja" else _id(cobro_hoja_dd.value),
                "numero_cobro": cobro_numero.value,
                "fecha_cobro": _date_to_sql(cobro_fecha.value),
                "importe": cobro_importe.value,
                "forma_pago": cobro_forma.value,
                "tipo_cobro": cobro_tipo.value,
                "facturable": 1 if cobro_facturable.value == "Sí" else 0,
                "concepto": cobro_concepto.value,
                "recibo_ruta": cobro_recibo.value,
                "observaciones": cobro_obs.value,
            })
            cobro_dialog.open = False
            show_message(success_alert("Cobro creado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    cobro_dialog = form_dialog(
        "Cobro",
        ft.Column(
            [
                cobro_cliente_ac.control,
                cobro_expediente_dd,
                ft.Row(
                    [
                        cobro_hoja_dd,
                        secondary_button("Buscar hojas", refresh_cobro_hojas_for_expediente),
                    ],
                    wrap=True,
                    spacing=10,
                ),
                ft.Row([cobro_fecha, cobro_numero, cobro_importe], wrap=True, spacing=10),
                ft.Row([cobro_forma, cobro_tipo, cobro_facturable], wrap=True, spacing=10),
                cobro_concepto,
                cobro_recibo,
                cobro_obs,
            ],
            width=760,
            height=620,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(cobro_dialog)), primary_button("Guardar", save_cobro)],
    )
    page.overlay.append(cobro_dialog)


    # Editar cobro dialog
    edit_cobro_state = {"id": None, "cliente_id": None}

    edit_cobro_fecha = required_text_input("Fecha cobro DD/MM/AAAA", width=220)
    edit_cobro_importe = required_text_input("Importe", width=160)
    edit_cobro_forma = select_input("Forma pago", ["EFECTIVO", "TRANSFERENCIA", "TARJETA", "BIZUM", "OTRO"], value="EFECTIVO", width=180)
    edit_cobro_tipo = select_input("Tipo", ["CONSULTA", "PAGO_EXPEDIENTE", "PAGO_PARCIAL", "RESERVA", "DEVOLUCION", "AJUSTE"], value="PAGO_EXPEDIENTE", width=220)
    edit_cobro_facturable = select_input("Facturable", ["No", "Sí"], value="No", width=120)
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
                "concepto": edit_cobro_concepto.value,
                "recibo_ruta": edit_cobro_recibo.value,
                "observaciones": edit_cobro_obs.value,
            })

            edit_cobro_dialog.open = False
            show_message(success_alert("Cobro modificado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    edit_cobro_dialog = form_dialog(
        "Editar cobro",
        ft.Column(
            [
                edit_cobro_expediente_dd,
                ft.Row(
                    [
                        edit_cobro_hoja_dd,
                        secondary_button("Buscar hojas", refresh_edit_cobro_hojas),
                    ],
                    wrap=True,
                    spacing=10,
                ),
                ft.Row([edit_cobro_fecha, edit_cobro_importe], wrap=True, spacing=10),
                ft.Row([edit_cobro_forma, edit_cobro_tipo, edit_cobro_facturable], wrap=True, spacing=10),
                edit_cobro_concepto,
                edit_cobro_recibo,
                edit_cobro_obs,
                ft.Text(
                    "Si marcas el cobro como facturable, se generará factura automáticamente si aún no existe.",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            width=760,
            height=620,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(edit_cobro_dialog)), primary_button("Guardar cambios", save_edit_cobro)],
    )
    page.overlay.append(edit_cobro_dialog)

    # Factura dialog
    fra_fecha = required_text_input("Fecha factura DD/MM/AAAA", width=220)
    fra_numero = text_input("Nº factura automático", width=220)
    fra_base = required_text_input("Base imponible", width=180)
    fra_iva = text_input("IVA", "0", width=140)
    fra_irpf = text_input("IRPF", "0", width=140)
    fra_total = text_input("Total opcional", width=160)
    fra_estado = select_input("Estado", ["BORRADOR", "EMITIDA", "EXPORTADA", "ANULADA"], value="BORRADOR", width=180)
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

    # Gasto dialog
    gasto_fecha = required_text_input("Fecha gasto DD/MM/AAAA", width=220)
    gasto_proveedor = text_input("Proveedor", width=260)
    gasto_concepto = required_text_input("Concepto", width=420)
    gasto_categoria = text_input("Categoría", width=220)
    gasto_importe = required_text_input("Importe", width=160)
    gasto_forma = text_input("Forma pago", width=180)
    gasto_deducible = select_input("Deducible", ["Sí", "No"], value="Sí", width=120)
    gasto_ruta = text_input("Ruta factura recibida", width=620)
    gasto_obs = multiline_input("Observaciones", width=620)

    def open_gasto_dialog(e=None):
        for field in [gasto_proveedor, gasto_concepto, gasto_categoria, gasto_importe, gasto_forma, gasto_ruta, gasto_obs]:
            field.value = ""
        gasto_fecha.value = _today_display()
        gasto_deducible.value = "Sí"
        gasto_dialog.open = True
        page.update()

    def save_gasto(e=None):
        try:
            economic_service.create_gasto({
                "fecha_gasto": _date_to_sql(gasto_fecha.value),
                "proveedor": gasto_proveedor.value,
                "concepto": gasto_concepto.value,
                "categoria": gasto_categoria.value,
                "importe": gasto_importe.value,
                "forma_pago": gasto_forma.value,
                "deducible": 1 if gasto_deducible.value == "Sí" else 0,
                "factura_recibida_ruta": gasto_ruta.value,
                "observaciones": gasto_obs.value,
            })
            gasto_dialog.open = False
            show_message(success_alert("Gasto creado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    gasto_dialog = form_dialog(
        "Gasto",
        ft.Column(
            [
                ft.Row([gasto_fecha, gasto_proveedor, gasto_importe], wrap=True, spacing=10),
                gasto_concepto,
                ft.Row([gasto_categoria, gasto_forma, gasto_deducible], wrap=True, spacing=10),
                gasto_ruta,
                gasto_obs,
            ],
            width=760,
            height=500,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        [secondary_button("Cancelar", lambda e: close(gasto_dialog)), primary_button("Guardar", save_gasto)],
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

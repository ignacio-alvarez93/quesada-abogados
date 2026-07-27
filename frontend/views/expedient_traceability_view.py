import flet as ft
from datetime import datetime

from backend.services import expedient_service
from backend.services import expedient_traceability_service as trace_service
from backend.services import economic_service
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.app_text_field import text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_dialog import form_dialog
from frontend.components.app_alert import success_alert, error_alert
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import app_table
from frontend.components.traceability_badge import traceability_badge
from frontend.components.economic_badge import economic_badge
from frontend.components.app_autocomplete import AppAutocomplete

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"


def _id_from_option(value):
    if not value or " - " not in value:
        return None
    return int(value.split(" - ", 1)[0])


def _money(value):
    try:
        return f"{float(value or 0):.2f} €"
    except Exception:
        return "0.00 €"


def _date(value):
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    return value


def _date_to_sql(value):
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def expedient_traceability_view(page: ft.Page):
    trace_service.initialize_traceability_schema()
    expedient_service.initialize_expedients_schema()
    economic_service.initialize_economic_schema()

    state = {"selected_expediente_id": None, "message": None}

    content_area = ft.Container(expand=True)
    detail_container = ft.Container(expand=True)

    expedientes = expedient_service.get_expedientes(active_only=True)
    expediente_options = [
        f"{e['id']} - {e['numero_expediente']} · {e.get('cliente_nombre') or ''} {e.get('cliente_primer_apellido') or ''}".strip()
        for e in expedientes
    ]

    expediente_select = select_input("Expediente", expediente_options, width=620)

    def selected_expediente_id():
        return _id_from_option(expediente_select.value)

    def show_message(control):
        state["message"] = control

    def refresh(e=None):
        state["selected_expediente_id"] = selected_expediente_id()
        detail_container.content = build_detail()
        content_area.content = build_view()
        page.update()

    expediente_select.on_change = refresh

    def section(title, content):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    content,
                ],
                spacing=12,
            ),
        )

    def build_view():
        controls = [
            ft.Text("Trazabilidad de expedientes", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text("Justificantes, historial y trazabilidad económica desde cobros reales.", size=14, color=Q_MUTED),
        ]

        if state["message"]:
            controls.append(state["message"])

        controls.extend(
            [
                ft.Container(
                    content=ft.Row(
                        controls=[expediente_select, primary_button("Actualizar", refresh)],
                        spacing=10,
                        wrap=True,
                    ),
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                ),
                detail_container,
            ]
        )

        return ft.Column(controls=controls, spacing=18, expand=True)

    def economic_resume_expediente(expediente_id):
        hojas = [h for h in economic_service.list_hojas_encargo() if h.get("expediente_id") == expediente_id]
        cobros = [c for c in economic_service.list_cobros() if c.get("expediente_id") == expediente_id]
        facturas = [f for f in economic_service.list_facturas() if f.get("expediente_id") == expediente_id]

        total_hojas = sum(float(h.get("importe_neto") or 0) for h in hojas)
        total_cobros = sum(float(c.get("importe") or 0) for c in cobros if c.get("tipo_cobro") != "CONSULTA")
        total_facturas = sum(float(f.get("total") or 0) for f in facturas)

        return {
            "hojas": hojas,
            "cobros": cobros,
            "facturas": facturas,
            "total_hojas": total_hojas,
            "total_cobros": total_cobros,
            "total_facturas": total_facturas,
            "pendiente": max(0, total_hojas - total_cobros),
        }

    def build_detail():
        expediente_id = state["selected_expediente_id"]

        if not expediente_id:
            return empty_state("Selecciona un expediente para ver su trazabilidad")

        resumen = trace_service.get_resumen_trazabilidad(expediente_id)
        eco = economic_resume_expediente(expediente_id)

        return ft.Column(
            controls=[
                build_actions(expediente_id),
                build_justificantes(resumen["justificantes"]),
                build_hojas(eco["hojas"]),
                build_cobros(eco["cobros"]),
                build_facturas(eco["facturas"]),
                build_resumen_economico(eco),
                build_eventos(resumen["eventos"]),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    def build_actions(expediente_id):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            primary_button("Cargar justificante", lambda e: open_justificante_dialog(expediente_id)),
                            secondary_button("Aplicar consulta pagada", lambda e: open_aplicar_consulta_dialog(expediente_id)),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Text(
                        "La consulta previa debe existir como cobro tipo CONSULTA. Aquí solo se aplica a una hoja de encargo.",
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
                spacing=8,
            ),
        )

    def build_justificantes(items):
        if not items:
            return section("Justificantes", empty_state("No hay justificantes cargados"))

        rows = []
        for j in items:
            rows.append([
                j.get("archivo_nombre") or "-",
                j.get("archivo_ruta") or "-",
                _date(j.get("fecha_presentacion")),
                j.get("numero_registro") or "-",
                secondary_button("Conciliar", lambda e, jid=j["id"]: conciliar_justificante(jid)),
            ])

        return section("Justificantes", app_table(["Archivo", "Ruta", "Fecha presentación", "Registro", "Estado", "Acción"], rows, height=260))

    def build_hojas(items):
        if not items:
            return section("Hoja económica asociada", empty_state("No hay hoja de encargo asociada"))

        rows = []
        for h in items:
            rows.append([
                h.get("numero_hoja") or "-",
                _date(h.get("fecha_firma")),
                h.get("procedimiento") or "-",
                _money(h.get("importe_bruto")),
                _money(h.get("descuento_consultas_previas")),
                _money(h.get("importe_neto")),
                economic_badge(h.get("estado")),
            ])

        return section("Hoja económica asociada", app_table(["Nº hoja", "Firma", "Procedimiento", "Bruto", "Dto. consultas", "Neto", "Estado"], rows, height=260))

    def build_cobros(items):
        if not items:
            return section("Cobros asociados", empty_state("No hay cobros asociados"))

        rows = []
        for c in items:
            rows.append([
                c.get("numero_cobro") or "-",
                _date(c.get("fecha_cobro")),
                _money(c.get("importe")),
                c.get("forma_pago") or "-",
                c.get("tipo_cobro") or "-",
                c.get("numero_hoja") or "-",
                economic_badge(c.get("estado_conciliacion")),
            ])

        return section("Cobros asociados", app_table(["Nº cobro", "Fecha", "Importe", "Forma", "Tipo", "Hoja", "Conciliación"], rows, height=260))

    def build_facturas(items):
        if not items:
            return section("Facturas asociadas", empty_state("No hay facturas asociadas"))

        rows = []
        for f in items:
            rows.append([
                f.get("numero_factura") or "-",
                _date(f.get("fecha_factura")),
                _money(f.get("base_imponible")),
                _money(f.get("iva")),
                _money(f.get("total")),
                economic_badge(f.get("estado")),
            ])

        return section("Facturas asociadas", app_table(["Nº factura", "Fecha", "Base", "IVA", "Total", "Estado"], rows, height=240))

    def build_resumen_economico(eco):
        rows = [
            ["Importe neto hojas", _money(eco["total_hojas"])],
            ["Cobros expediente", _money(eco["total_cobros"])],
            ["Facturas emitidas", _money(eco["total_facturas"])],
            ["Pendiente estimado", _money(eco["pendiente"])],
        ]
        return section("Resumen económico", app_table(["Concepto", "Importe"], rows, height=220))

    def build_eventos(items):
        if not items:
            return section("Historial", empty_state("No hay eventos registrados"))

        rows = []
        for ev in items:
            rows.append([
                _date(ev.get("fecha_evento")),
                ev.get("tipo_evento") or "-",
                ev.get("titulo") or "-",
                ev.get("descripcion") or "-",
            ])

        return section("Historial", app_table(["Fecha", "Tipo", "Título", "Descripción"], rows, height=300))

    def conciliar_justificante(justificante_id):
        try:
            trace_service.conciliar_justificante(justificante_id)
            show_message(success_alert("Justificante conciliado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    archivo_nombre = text_input("Nombre archivo", width=320)
    archivo_ruta = text_input("Ruta archivo", width=620)
    fecha_presentacion = text_input("Fecha presentación DD/MM/AAAA", width=260)
    numero_registro = text_input("Número registro", width=280)
    organo_presentacion = text_input("Órgano presentación", width=360)
    procedimiento_detectado = text_input("Procedimiento detectado", width=360)
    estado_conciliacion = select_input("Estado conciliación", ["PENDIENTE", "CONCILIADO", "DUDOSO", "NO IDENTIFICADO", "ERROR"], value="PENDIENTE", width=240)
    justificante_obs = multiline_input("Observaciones", width=620)

    def open_justificante_dialog(expediente_id):
        archivo_nombre.value = ""
        archivo_ruta.value = ""
        fecha_presentacion.value = ""
        numero_registro.value = ""
        organo_presentacion.value = ""
        procedimiento_detectado.value = ""
        estado_conciliacion.value = "PENDIENTE"
        justificante_obs.value = ""
        justificante_dialog.data = expediente_id
        justificante_dialog.open = True
        page.update()

    def save_justificante(e=None):
        try:
            trace_service.create_justificante({
                "expediente_id": justificante_dialog.data,
                "archivo_nombre": archivo_nombre.value,
                "archivo_ruta": archivo_ruta.value,
                "fecha_presentacion": _date_to_sql(fecha_presentacion.value),
                "numero_registro": numero_registro.value,
                "organo_presentacion": organo_presentacion.value,
                "procedimiento_detectado": procedimiento_detectado.value,
                "estado_conciliacion": estado_conciliacion.value,
                "observaciones": justificante_obs.value,
            })
            justificante_dialog.open = False
            show_message(success_alert("Justificante cargado"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    justificante_dialog = form_dialog(
        "Cargar justificante",
        ft.Column(
            controls=[
                ft.Row([archivo_nombre, estado_conciliacion], wrap=True, spacing=10),
                archivo_ruta,
                ft.Row([fecha_presentacion, numero_registro, organo_presentacion], wrap=True, spacing=10),
                procedimiento_detectado,
                justificante_obs,
            ],
            width=760,
            height=420,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        actions=[secondary_button("Cancelar", lambda e: close_dialog(justificante_dialog)), primary_button("Guardar", save_justificante)],
    )
    page.overlay.append(justificante_dialog)

    aplicar_cliente_ac = AppAutocomplete(page, "Cliente pagador", [], width=620, max_results=12)
    consulta_cobro_dd = select_input("Cobro tipo CONSULTA disponible", [], width=620)
    hoja_aplicar_dd = select_input("Hoja de encargo", [], width=620)
    importe_aplicar = text_input("Importe a aplicar", width=180)
    aplicar_obs = multiline_input("Observaciones", width=620)

    def load_consultas_y_hojas(e=None):
        cliente_id = _id_from_option(aplicar_cliente_ac.get_value())
        expediente_id = aplicar_dialog.data

        consultas = economic_service.list_consulta_cobros_disponibles(cliente_id) if cliente_id else []
        hojas = economic_service.get_hojas_for_select(cliente_id=cliente_id, expediente_id=expediente_id) if cliente_id else []

        consulta_cobro_dd.options = [
            ft.dropdown.Option(f"{c['id']} - {c.get('numero_cobro') or 'COBRO'} · {_date(c.get('fecha_cobro'))} · {_money(c.get('importe'))}")
            for c in consultas
        ]
        consulta_cobro_dd.value = consulta_cobro_dd.options[0].key if consulta_cobro_dd.options else None

        hoja_aplicar_dd.options = [ft.dropdown.Option(h["display"]) for h in hojas]
        hoja_aplicar_dd.value = hoja_aplicar_dd.options[0].key if hoja_aplicar_dd.options else None

        page.update()

    aplicar_cliente_ac.on_select = load_consultas_y_hojas

    def open_aplicar_consulta_dialog(expediente_id):
        clientes = economic_service.get_clientes_expediente_for_select(expediente_id)
        aplicar_cliente_ac.set_options([c["display"] for c in clientes], clear_value=True)
        consulta_cobro_dd.options = []
        consulta_cobro_dd.value = None
        hoja_aplicar_dd.options = []
        hoja_aplicar_dd.value = None
        importe_aplicar.value = ""
        aplicar_obs.value = ""
        aplicar_dialog.data = expediente_id
        aplicar_dialog.open = True
        page.update()

    def save_aplicar_consulta(e=None):
        try:
            cliente_id = _id_from_option(aplicar_cliente_ac.get_value())
            cobro_id = _id_from_option(consulta_cobro_dd.value)
            hoja_id = _id_from_option(hoja_aplicar_dd.value)
            expediente_id = aplicar_dialog.data

            if not cliente_id:
                raise ValueError("Selecciona un cliente pagador")
            if not cobro_id:
                raise ValueError("Selecciona un cobro tipo CONSULTA disponible")
            if not hoja_id:
                raise ValueError("Selecciona una hoja de encargo")

            economic_service.aplicar_cobro_consulta_a_hoja(
                cobro_id=cobro_id,
                expediente_id=expediente_id,
                hoja_encargo_id=hoja_id,
                importe_aplicado=importe_aplicar.value or None,
                observaciones=aplicar_obs.value,
            )

            aplicar_dialog.open = False
            show_message(success_alert("Consulta pagada aplicada a hoja de encargo"))
        except Exception as exc:
            show_message(error_alert(str(exc)))
        refresh()

    aplicar_dialog = form_dialog(
        "Aplicar consulta pagada",
        ft.Column(
            controls=[
                aplicar_cliente_ac.control,
                secondary_button("Buscar recibos/consultas pagadas", load_consultas_y_hojas),
                consulta_cobro_dd,
                hoja_aplicar_dd,
                importe_aplicar,
                aplicar_obs,
                ft.Text("Primero registra la consulta como Cobro tipo CONSULTA. Después se aplica aquí a la hoja.", size=12, color=Q_MUTED),
            ],
            width=760,
            height=470,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        actions=[secondary_button("Cancelar", lambda e: close_dialog(aplicar_dialog)), primary_button("Aplicar", save_aplicar_consulta)],
    )
    page.overlay.append(aplicar_dialog)

    def close_dialog(dialog):
        dialog.open = False
        page.update()

    if expediente_options:
        expediente_select.value = expediente_options[0]
        state["selected_expediente_id"] = selected_expediente_id()

    detail_container.content = build_detail()
    content_area.content = build_view()
    return content_area

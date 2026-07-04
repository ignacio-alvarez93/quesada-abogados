import threading
import json
import csv
import sqlite3
from pathlib import Path

import flet as ft
from datetime import datetime

from backend.services import expedient_service
from backend.services import box_watch_service
from backend.services import document_viewer_service
from backend.services import document_inbox_service
from backend.services import expedient_document_state_service as document_state_service
from backend.services import expedient_traceability_service as trace_service
from backend.services import presentation_assistant_service
from backend.services import presentation_queue_service
from backend.services import presentation_config_service
from backend.services import config_service
from backend.services import expedient_dynamic_form_service as dynamic_form_service
from backend.services import expedient_snapshot_service as snapshot_service
from backend.services import document_template_service
from backend.services import document_docx_service
from backend.services import mapper_preview_service
from backend.services import pdf_fill_service
from backend.services import form_mapper_admin_service
from backend.services.list_expediente_box_directory import list_expediente_box_directory, list_para_presentar_documents
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.document_file_card import document_file_card
from frontend.components.bulk_action_bar import bulk_action_bar
from frontend.components.app_text_field import text_input, required_text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_dialog import form_dialog
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_empty_state import empty_state
from frontend.components.app_filter_bar import filter_bar
from frontend.components.app_card import metric_card
from frontend.components.app_action_row import action_row
from frontend.components.expedient_status_badge import expedient_status_badge, priority_badge
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.listing.card_item import card_item

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"


def _option_id(value):
    if not value or " - " not in value:
        return None
    try:
        return int(value.split(" - ", 1)[0])
    except Exception:
        return None


def _norm(value):
    return str(value or "").strip().upper()


def _option_id_from_autocomplete_value(value, options):
    value = str(value or "").strip()
    direct = _option_id(value)
    if direct:
        return direct

    normalized_value = _norm(value)
    if not normalized_value or normalized_value == "SIN SUBTIPO":
        return None

    for option in options or []:
        if _norm(option) == normalized_value:
            return _option_id(option)

    for option in options or []:
        parts = str(option).split(" - ", 2)
        label = parts[-1] if parts else option
        if _norm(label) == normalized_value or normalized_value in _norm(label):
            return _option_id(option)

    return None


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
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def _format_date_typing(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())[:8]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return f"{digits[:2]}/{digits[2:]}"
    return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"


def _cliente_nombre(expediente):
    return " ".join(
        [
            expediente.get("cliente_nombre") or "",
            expediente.get("cliente_primer_apellido") or "",
            expediente.get("cliente_segundo_apellido") or "",
        ]
    ).strip()


def _cliente_documento(expediente):
    return expediente.get("cliente_nie") or expediente.get("cliente_pasaporte") or expediente.get("cliente_dni") or ""


def _box_path_label(expediente):
    path = str(expediente.get("box_folder_path") or "").strip()
    if not path:
        return "Sin vincular"
    normalized = path.replace("\\", "/").rstrip("/")
    parts = [p for p in normalized.split("/") if p]
    if len(parts) >= 3:
        return " > ".join(parts[-3:])
    return normalized


def _box_path_color(expediente):
    return Q_PRIMARY if str(expediente.get("box_folder_path") or "").strip() else Q_MUTED


def _mercurio_file_sort_key(item):
    import re
    name = str((item or {}).get("name") or "").strip()
    match = re.match(r"^\s*(\d+)(?:[\s._-]+|$)", name)
    if match:
        return (0, int(match.group(1)), name.lower())
    return (1, 999999, name.lower())


def _mercurio_file_order_label(item):
    import re
    explicit = str((item or {}).get("order_label") or "").strip()
    if explicit and explicit != "-":
        return explicit
    name = str((item or {}).get("name") or "").strip()
    match = re.match(r"^\s*(\d+)(?:[\s._-]+|$)", name)
    if match:
        return str(int(match.group(1))).zfill(2)
    return "-"


def expedients_view(page: ft.Page, on_return_to_queue=None):
    expedient_service.initialize_expedients_schema()
    trace_service.initialize_traceability_schema()
    dynamic_form_service.initialize_dynamic_forms_schema()
    snapshot_service.initialize_snapshot_schema()

    state = {
        "expedientes": [],
        "editing_id": None,
        "message": None,
        "selected_ids": set(),
        "dialog_section": "ficha",
        "dialog_expediente_id": None,
        "presentation_start": None,
        "presentation_context": None,
        "presentation_url": None,
        "mercurio_box_status": {},
        "box_scan_running": set(),
        "document_browser_path": {},
        "para_presentar_documents": {},
        "para_presentar_documents_error": {},
        "specific_field_controls": {},
        "specific_live_values": {},
        "specific_formulario_id": None,
        "specific_view_mode": None,
        "specific_data_step": 0,
        "specific_generation_result": {},
        "specific_refresh_counter": 0,
        "snapshot_status": {},
        "expedient_docx_result": {},
        "expedient_docx_error": {},
        "payload_preview_destination": "MERCURIO",
        "payload_preview_result": {},
        "payload_preview_error": {},
    }

    content_area = ft.Container(expand=True)
    table_container = ft.Container(expand=True)

    clientes = expedient_service.get_clientes_for_select()
    tipos = expedient_service.get_tipos_expediente()
    subtipos = expedient_service.get_subtipos_expediente()
    estados_doc = expedient_service.get_estados_documentales()
    estados_admin = expedient_service.get_estados_administrativos()
    prioridades = expedient_service.get_prioridades()

    cliente_options = [c["display"] for c in clientes]
    tipo_options = [f"{t['id']} - {t['nombre']}" for t in tipos]
    subtipo_options = ["Sin subtipo"] + [f"{s['id']} - {s['tipo_expediente_nombre']} - {s['nombre']}" for s in subtipos]
    estado_doc_options = [f"{e['id']} - {e['nombre']}" for e in estados_doc]
    estado_admin_options = [f"{e['id']} - {e['nombre']}" for e in estados_admin]
    prioridad_options = [f"{p['id']} - {p['nombre']}" for p in prioridades]

    search_input = text_input("Buscar expediente / cliente / registro", width=360)
    filtro_cliente = AppAutocomplete(
        page=page,
        label="Filtrar cliente",
        options=cliente_options,
        width=360,
        max_results=10,
        allow_free_text=True,
    )
    filtro_tipo = select_input("Tipo", ["Todos"] + tipo_options, value="Todos", width=260)
    filtro_estado = select_input("Estado admin.", ["Todos"] + estado_admin_options, value="Todos", width=260)
    filtro_prioridad = select_input("Prioridad", ["Todos"] + prioridad_options, value="Todos", width=220)

    numero_expediente = text_input("Nº expediente", width=220)
    numero_expediente_mercurio = text_input("Nº expediente Mercurio", width=260)
    cliente = AppAutocomplete(
        page=page,
        label="Cliente",
        options=cliente_options,
        width=520,
        max_results=12,
        allow_free_text=True,
    )
    tipo_expediente = AppAutocomplete(
        page=page,
        label="Tipo expediente",
        options=tipo_options,
        width=320,
        max_results=10,
        allow_free_text=False,
    )
    subtipo_expediente = AppAutocomplete(
        page=page,
        label="Subtipo expediente",
        options=subtipo_options,
        value="Sin subtipo",
        width=360,
        max_results=10,
        allow_free_text=False,
    )
    subtipo_expediente_manual = text_input("Subtipo manual / variante", width=320)
    estado_documental = select_input("Estado documental", estado_doc_options, width=320)
    estado_administrativo = select_input("Estado administrativo", estado_admin_options, width=320)
    estado_presentacion = select_input(
        "Estado presentación",
        ["NO PRESENTADO", "EN PREPARACIÓN", "PRESENTADO", "SUBSANACIÓN", "FINALIZADO"],
        value="NO PRESENTADO",
        width=240,
    )
    prioridad = select_input("Prioridad", prioridad_options, width=220)
    responsable = text_input("Responsable", width=260)
    fecha_apertura = text_input("Fecha apertura DD/MM/AAAA", width=240)
    fecha_presentacion = text_input("Fecha presentación DD/MM/AAAA", width=260)
    fecha_resolucion = text_input("Fecha resolución DD/MM/AAAA", width=240)
    numero_registro = text_input("Número registro", width=280)
    organo_presentacion = text_input("Órgano presentación", width=360)
    provincia = text_input("Provincia", width=240)
    observaciones = multiline_input("Observaciones", width=720)
    observaciones_internas = multiline_input("Observaciones internas", width=720)
    box_folder_path = text_input("Ruta Box futura / observada", width=720)

    admin_document_event_options = [
        "JUSTIFICANTE_PRESENTACION - Justificante de presentación",
        "ADMISION_TRAMITE - Admisión a trámite",
        "INADMISION_TRAMITE - Inadmisión a trámite",
        "ADMISION_TRAMITE_TASA - Admisión a trámite y tasa",
        "JUSTIFICANTE_TASA - Justificante de tasa",
        "REQUERIMIENTO - Requerimiento",
        "JUSTIFICANTE_APORTACION_DOCUMENTACION - Justificante aportación documentación",
        "JUSTIFICANTE_AMPLIACION_PLAZO - Justificante ampliación de plazo",
        "RESOLUCION_FAVORABLE - Resolución favorable",
        "RESOLUCION_DESFAVORABLE - Resolución desfavorable",
        "OTRO - Otro documento administrativo",
    ]

    admin_document_event_type = select_input(
        "Tipo de documento / evento",
        admin_document_event_options,
        value=admin_document_event_options[0],
        width=620,
    )
    admin_document_selected_file = text_input("Documento seleccionado", width=720)
    admin_document_selected_file.read_only = True
    admin_document_observaciones = multiline_input("Observaciones", width=720, height=90)

    def refresh_subtipo_options_for_tipo(selected_subtipo_id=None, tipo_value=None, reset_value=False):
        """
        Refresca los subtipos según el tipo seleccionado.

        Versión robusta:
        - Relee siempre SQLite, no usa solo la lista cargada al abrir la vista.
        - Si el filtro por tipo falla, intenta filtrar por nombre del tipo.
        - Si solo hay un subtipo disponible, lo selecciona automáticamente.
        - Si hay varios, muestra la lista para elegir.
        """
        current_tipo_value = tipo_value or tipo_expediente.get_value()
        tipo_id = _option_id(current_tipo_value)
        tipo_label = ""
        if current_tipo_value and " - " in str(current_tipo_value):
            tipo_label = str(current_tipo_value).split(" - ", 1)[1]

        try:
            all_subtipos = expedient_service.get_subtipos_expediente(active_only=True)
        except Exception:
            try:
                all_subtipos = expedient_service.get_subtipos_expediente()
            except Exception:
                all_subtipos = list(subtipos or [])

        available = []
        if tipo_id:
            available = [
                s for s in (all_subtipos or [])
                if int(s.get("tipo_expediente_id") or 0) == int(tipo_id)
            ]

        # Fallback por nombre por si el ID no llega sincronizado desde Flet.
        if not available and tipo_label:
            available = [
                s for s in (all_subtipos or [])
                if _norm(s.get("tipo_expediente_nombre")) == _norm(tipo_label)
                or _norm(tipo_label) in _norm(s.get("tipo_expediente_nombre"))
            ]

        options = ["Sin subtipo"] + [
            f"{s['id']} - {s.get('tipo_expediente_nombre') or ''} - {s['nombre']}"
            for s in (available or [])
        ]

        subtipo_expediente.set_options(options, clear_value=False)

        selected_value = "Sin subtipo"
        current_value = subtipo_expediente.get_value()

        if selected_subtipo_id:
            selected_value = next((x for x in options if x.startswith(str(selected_subtipo_id) + " - ")), "Sin subtipo")
        elif not reset_value and current_value in options:
            selected_value = current_value
        elif reset_value and len(options) == 2:
            # Caso habitual actual: Nacionalidad solo tiene un subtipo creado.
            selected_value = options[1]

        subtipo_expediente.set_value(selected_value, update=False)
        if selected_value != "Sin subtipo":
            subtipo_expediente_manual.value = ""

    def on_tipo_expediente_change(selected_value=None):
        selected_tipo_value = selected_value or tipo_expediente.get_value()
        tipo_expediente.set_value(selected_tipo_value, update=False)

        refresh_subtipo_options_for_tipo(tipo_value=selected_tipo_value, reset_value=True)
        if state.get("dialog_section") == "datos_especificos":
            expediente_dialog.content = build_expediente_dialog_content(state.get("dialog_expediente_id"))
        page.update()

    tipo_expediente.on_select = on_tipo_expediente_change

    for date_field in [fecha_apertura, fecha_presentacion, fecha_resolucion]:
        def on_date_change(e, field=date_field):
            formatted = _format_date_typing(field.value)
            if field.value != formatted:
                field.value = formatted
                page.update()
        date_field.on_change = on_date_change

    form_message = ft.Column(controls=[], visible=False)

    def show_form_error(message):
        form_message.controls.clear()
        form_message.controls.append(error_alert(message))
        form_message.visible = True
        page.update()

    def show_form_success(message):
        form_message.controls.clear()
        form_message.controls.append(success_alert(message))
        form_message.visible = True
        page.update()

    def clear_form_message():
        form_message.controls.clear()
        form_message.visible = False

    def set_message(control):
        state["message"] = control

    def clear_message():
        state["message"] = None

    def load_data():
        filters = {
            "text": search_input.value,
            "active_only": True,
        }

        filtro_cliente_value = filtro_cliente.get_value()
        if filtro_cliente_value and filtro_cliente_value != "Todos":
            filters["cliente_id"] = _option_id(filtro_cliente_value)
        if filtro_tipo.value != "Todos":
            filters["tipo_expediente_id"] = _option_id(filtro_tipo.value)
        if filtro_estado.value != "Todos":
            filters["estado_administrativo_id"] = _option_id(filtro_estado.value)
        if filtro_prioridad.value != "Todos":
            filters["prioridad_id"] = _option_id(filtro_prioridad.value)

        state["expedientes"] = expedient_service.search_expedientes(filters)

    def clear_form():
        state["editing_id"] = None
        numero_expediente.value = ""
        numero_expediente_mercurio.value = ""
        cliente.set_value("", update=False)
        tipo_expediente.set_value(tipo_options[0] if tipo_options else "", update=False)
        refresh_subtipo_options_for_tipo(tipo_value=tipo_expediente.get_value(), reset_value=True)
        subtipo_expediente_manual.value = ""
        estado_documental.value = estado_doc_options[0] if estado_doc_options else None
        estado_administrativo.value = estado_admin_options[0] if estado_admin_options else None
        estado_presentacion.value = "NO PRESENTADO"
        prioridad.value = prioridad_options[0] if prioridad_options else None
        responsable.value = ""
        fecha_apertura.value = datetime.today().strftime("%d/%m/%Y")
        fecha_presentacion.value = ""
        fecha_resolucion.value = ""
        numero_registro.value = ""
        organo_presentacion.value = ""
        provincia.value = ""
        observaciones.value = ""
        observaciones_internas.value = ""
        box_folder_path.value = ""
        clear_form_message()

    def load_form(expediente):
        state["editing_id"] = expediente["id"]
        numero_expediente.value = expediente.get("numero_expediente") or ""
        numero_expediente_mercurio.value = expediente.get("numero_expediente_mercurio") or ""

        cliente.set_value(
            next(
                (x for x in cliente_options if x.startswith(str(expediente.get("cliente_id")) + " - ")),
                "",
            ),
            update=False,
        )
        tipo_expediente.set_value(
            next(
                (x for x in tipo_options if x.startswith(str(expediente.get("tipo_expediente_id")) + " - ")),
                "",
            ),
            update=False,
        )
        estado_documental.value = next(
            (x for x in estado_doc_options if x.startswith(str(expediente.get("estado_documental_id")) + " - ")),
            None,
        )
        estado_administrativo.value = next(
            (x for x in estado_admin_options if x.startswith(str(expediente.get("estado_administrativo_id")) + " - ")),
            None,
        )
        prioridad.value = next(
            (x for x in prioridad_options if x.startswith(str(expediente.get("prioridad_id")) + " - ")),
            None,
        )

        refresh_subtipo_options_for_tipo(expediente.get("subtipo_expediente_id"), tipo_value=tipo_expediente.get_value())
        if subtipo_expediente.get_value() == "Sin subtipo":
            subtipo_expediente_manual.value = expediente.get("subtipo_expediente") or ""
        else:
            subtipo_expediente_manual.value = ""
        estado_presentacion.value = expediente.get("estado_presentacion") or "NO PRESENTADO"
        responsable.value = expediente.get("responsable") or ""
        fecha_apertura.value = _date_to_display(expediente.get("fecha_apertura"))
        fecha_presentacion.value = _date_to_display(expediente.get("fecha_presentacion"))
        fecha_resolucion.value = _date_to_display(expediente.get("fecha_resolucion"))
        numero_registro.value = expediente.get("numero_registro") or ""
        organo_presentacion.value = expediente.get("organo_presentacion") or ""
        provincia.value = expediente.get("provincia") or ""
        observaciones.value = expediente.get("observaciones") or ""
        observaciones_internas.value = expediente.get("observaciones_internas") or ""
        box_folder_path.value = expediente.get("box_folder_path") or ""
        clear_form_message()

    def form_data():
        return {
            "cliente_id": _option_id(cliente.get_value()),
            "numero_expediente": numero_expediente.value,
            "numero_expediente_mercurio": numero_expediente_mercurio.value,
            "tipo_expediente_id": _option_id(tipo_expediente.get_value()),
            "subtipo_expediente_id": _option_id_from_autocomplete_value(subtipo_expediente.get_value(), subtipo_expediente.options),
            "subtipo_expediente": subtipo_expediente_manual.value or (
                subtipo_expediente.get_value().split(" - ", 2)[-1] if subtipo_expediente.get_value() and subtipo_expediente.get_value() != "Sin subtipo" else ""
            ),
            "estado_documental_id": _option_id(estado_documental.value),
            "estado_administrativo_id": _option_id(estado_administrativo.value),
            "estado_presentacion": estado_presentacion.value,
            "prioridad_id": _option_id(prioridad.value),
            "responsable": responsable.value,
            "fecha_apertura": _date_to_sql(fecha_apertura.value),
            "fecha_presentacion": _date_to_sql(fecha_presentacion.value),
            "fecha_resolucion": _date_to_sql(fecha_resolucion.value),
            "numero_registro": numero_registro.value,
            "organo_presentacion": organo_presentacion.value,
            "provincia": provincia.value,
            "observaciones": observaciones.value,
            "observaciones_internas": observaciones_internas.value,
            "box_folder_path": box_folder_path.value,
            "activo": 1,
        }

    def validate_form(data):
        errors = []
        if not data["cliente_id"]:
            errors.append("Selecciona un cliente")
        if not data["tipo_expediente_id"]:
            errors.append("Selecciona un tipo de expediente")
        if not data["estado_documental_id"]:
            errors.append("Selecciona un estado documental")
        if not data["estado_administrativo_id"]:
            errors.append("Selecciona un estado administrativo")
        if fecha_apertura.value and not data["fecha_apertura"]:
            errors.append("Fecha apertura inválida")
        if fecha_presentacion.value and not data["fecha_presentacion"]:
            errors.append("Fecha presentación inválida")
        if fecha_resolucion.value and not data["fecha_resolucion"]:
            errors.append("Fecha resolución inválida")
        return errors

    def close_dialog(e=None):
        expediente_dialog.open = False

        should_return_to_queue = bool(getattr(page, "return_to_queue_after_expediente", False))
        if should_return_to_queue and state.get("dialog_expediente_id"):
            page.return_to_queue_after_expediente = False
            page.open_expediente_id = None
            page.update()
            if on_return_to_queue:
                on_return_to_queue()
            return
        page.update()

    def save_expediente(e=None):
        data = form_data()
        errors = validate_form(data)
        if errors:
            show_form_error("\n".join(errors))
            return

        try:
            if state["editing_id"]:
                expedient_service.update_expediente(state["editing_id"], data)
                set_message(success_alert("Expediente actualizado"))
                close_dialog()
                refresh_table()
            else:
                new_expediente_id = expedient_service.create_expediente(data)
                set_message(success_alert("Expediente creado"))
                refresh_table()

                expediente = expedient_service.get_expediente(new_expediente_id)
                if expediente:
                    open_edit(expediente)
                else:
                    close_dialog()
        except Exception as exc:
            show_form_error(str(exc))


    def cerrar_box_folder_options_dialog(e=None):
        box_folder_options_dialog.open = False
        page.update()

    def vincular_box_folder_option(ruta):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda el expediente antes de vincular Box.")
            return

        ruta = str(ruta or "").strip()
        if not ruta:
            show_form_error("La carpeta seleccionada no tiene ruta.")
            return

        try:
            box_watch_service.link_box_folder_to_expediente(ruta, expediente_id)
            box_folder_path.value = ruta
            _get_mercurio_box_status(expediente_id, force=True)
            _load_para_presentar_documents(expediente_id, force=True)
            box_folder_options_dialog.open = False
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            set_message(success_alert("Carpeta Box vinculada al expediente"))
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def cargar_box_folder_options(force_scan=False):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda el expediente antes de buscar carpetas Box.")
            return

        try:
            result = box_watch_service.list_box_folder_options_for_expediente(
                expediente_id,
                force_scan=force_scan,
            )
        except Exception as exc:
            show_form_error(str(exc))
            return

        options = result.get("options") or []
        routes = result.get("routes") or []
        scan_error = result.get("scan_error") or ""

        route_controls = []
        for route in routes:
            route_controls.append(
                ft.Text(
                    f"{route.get('id')} · {route.get('candidate_route_strategy') or ''} · {route.get('ruta_resuelta') or route.get('ruta_box')}",
                    size=11,
                    color=Q_MUTED,
                )
            )

        option_controls = []
        for option in options[:200]:
            ruta = option.get("ruta") or ""
            score = option.get("score") or 0
            reasons = ", ".join(option.get("match_reasons") or [])
            linked = option.get("expediente_id")

            option_controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    border=ft.border.all(1, Q_BORDER),
                    bgcolor="#F8FAFC" if int(score or 0) <= 0 else "#ECFDF3",
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(option.get("nombre_carpeta") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK, expand=True),
                                    ft.Text(f"score {score}", size=12, color=Q_MUTED),
                                    primary_button("Vincular esta", lambda e, p=ruta: vincular_box_folder_option(p)),
                                ],
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(ruta, size=11, color=Q_MUTED),
                            ft.Text(f"Motivos: {reasons or '-'}", size=11, color=Q_MUTED),
                            ft.Text(f"Ya vinculado a expediente: {linked}", size=11, color="#B42318", visible=bool(linked)),
                        ],
                        spacing=5,
                    ),
                )
            )

        if not option_controls:
            option_controls = [
                ft.Container(
                    padding=12,
                    border_radius=10,
                    bgcolor="#FFF7ED",
                    border=ft.border.all(1, "#FED7AA"),
                    content=ft.Text("No hay carpetas cargadas para las rutas seleccionadas.", color="#9A3412"),
                )
            ]

        box_folder_options_dialog.title = ft.Text("Carpetas Box candidatas")
        box_folder_options_dialog.content = ft.Container(
            width=900,
            height=620,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"Cliente: {result.get('cliente_nombre') or '-'} · Tipo: {result.get('tipo_expediente_nombre') or '-'}",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        "Selecciona manualmente la carpeta correcta. El score solo ordena posibles coincidencias.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    error_alert(scan_error) if scan_error else ft.Container(),
                    ft.Container(
                        padding=10,
                        border_radius=10,
                        border=ft.border.all(1, Q_BORDER),
                        bgcolor="#FFFFFF",
                        content=ft.Column(
                            controls=[
                                ft.Text("Rutas consultadas", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                *(route_controls or [ft.Text("Sin rutas", color=Q_MUTED, size=12)]),
                            ],
                            spacing=4,
                        ),
                    ),
                    ft.Text(f"Opciones encontradas: {result.get('total_options') or 0}", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Column(
                        controls=option_controls,
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                ],
                spacing=10,
            ),
        )
        box_folder_options_dialog.actions = [
            secondary_button("Cerrar", cerrar_box_folder_options_dialog),
        ]
        box_folder_options_dialog.open = True
        page.update()

    def vincular_box_folder_desde_ficha(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de vincular Box.")
            return

        ruta = (box_folder_path.value or "").strip()
        if not ruta:
            show_form_error("Indica una ruta Box antes de vincular.")
            return

        try:
            box_watch_service.link_box_folder_to_expediente(ruta, expediente_id)
            state.setdefault("mercurio_box_status", {}).pop(int(expediente_id), None)
            _get_mercurio_box_status(expediente_id, force=True)
            set_message(success_alert("Carpeta Box vinculada al expediente."))
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()
        except Exception as exc:
            show_form_error(str(exc))


    def _section_box(title, controls, width=900):
        return ft.Container(
            width=width,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=14,
            content=ft.Column(
                controls=[ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)] + controls,
                spacing=10,
            ),
        )

    def _get_mercurio_box_status(expediente_id, force=False):
        if not expediente_id:
            return None
        cached = state.get("mercurio_box_status", {}).get(int(expediente_id))
        if cached and not force:
            return cached
        try:
            status = expedient_service.get_expediente_mercurio_box_status(expediente_id, persist=True)
        except Exception as exc:
            status = {
                "expediente_id": int(expediente_id),
                "tiene_carpeta_para_presentar": False,
                "estado": "ERROR",
                "mensaje": str(exc),
                "box_para_presentar_folder_path": "",
            }
        state.setdefault("mercurio_box_status", {})[int(expediente_id)] = status
        return status

    def open_para_presentar_folder(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        status = _get_mercurio_box_status(expediente_id, force=True) if expediente_id else None
        path = (status or {}).get("box_para_presentar_folder_path") or ""
        if not path:
            show_form_error('No existe carpeta "PARA PRESENTAR" para abrir.')
            return
        try:
            expedient_service.open_box_folder_path(path)
        except Exception as exc:
            show_form_error(str(exc))

    def _refresh_open_expediente_dialog(expediente_id):
        if not expediente_id:
            return
        if state.get("dialog_expediente_id") != expediente_id:
            return
        try:
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()
        except Exception:
            pass

    def scan_expediente_box_in_background(expediente_id):
        if not expediente_id:
            return
        expediente_id = int(expediente_id)
        running = state.setdefault("box_scan_running", set())
        if expediente_id in running:
            return
        running.add(expediente_id)
        _get_mercurio_box_status(expediente_id, force=True)
        _refresh_open_expediente_dialog(expediente_id)

        def worker():
            try:
                result = expedient_service.scan_expediente_box_folder(expediente_id, calculate_hash=False)
                status = (result or {}).get("status") or expedient_service.get_expediente_mercurio_box_status(expediente_id, persist=True)
                state.setdefault("mercurio_box_status", {})[expediente_id] = status
            except Exception as exc:
                state.setdefault("mercurio_box_status", {})[expediente_id] = {
                    "expediente_id": expediente_id,
                    "tiene_carpeta_para_presentar": False,
                    "estado": "ERROR_ESCANEO",
                    "mensaje": f"No se pudo escanear la carpeta del expediente: {exc}",
                    "box_para_presentar_folder_path": "",
                }
            finally:
                state.setdefault("box_scan_running", set()).discard(expediente_id)
                _refresh_open_expediente_dialog(expediente_id)

        try:
            if hasattr(page, "run_thread"):
                page.run_thread(worker)
            else:
                threading.Thread(target=worker, daemon=True).start()
        except Exception:
            threading.Thread(target=worker, daemon=True).start()

    def _format_datetime(value):
        value = str(value or "").strip()
        if not value:
            return "-"
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%d/%m/%Y %H:%M") if "H" in fmt else parsed.strftime("%d/%m/%Y")
            except Exception:
                pass
        return value

    def _load_para_presentar_documents(expediente_id, force=False):
        if not expediente_id:
            return []
        expediente_id = int(expediente_id)
        cached = state.setdefault("para_presentar_documents", {}).get(expediente_id)
        if cached is not None and not force:
            return cached

        status = _get_mercurio_box_status(expediente_id, force=force)
        folder_path = (status or {}).get("box_para_presentar_folder_path") or ""
        root_path = (status or {}).get("box_root_folder_path") or ""

        if not folder_path:
            state.setdefault("para_presentar_documents", {})[expediente_id] = []
            return []

        try:
            docs = list_para_presentar_documents(folder_path, relative_base=root_path or folder_path)
            docs = sorted(docs or [], key=_mercurio_file_sort_key)
            state.setdefault("para_presentar_documents_error", {}).pop(expediente_id, None)
        except Exception as exc:
            docs = []
            state.setdefault("para_presentar_documents_error", {})[expediente_id] = str(exc)

        state.setdefault("para_presentar_documents", {})[expediente_id] = docs
        return docs

    def refresh_para_presentar_documents(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            return
        _get_mercurio_box_status(expediente_id, force=True)
        _load_para_presentar_documents(expediente_id, force=True)
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()

    def build_mercurio_box_status_content(expediente_id):
        if not expediente_id:
            return _section_box(
                "DOCUMENTACIÓN MERCURIO",
                [ft.Text("Guarda el expediente para validar la carpeta PARA PRESENTAR.", size=13, color=Q_MUTED)],
            )

        status = _get_mercurio_box_status(expediente_id)
        scanning = int(expediente_id) in state.get("box_scan_running", set())
        ok = bool((status or {}).get("tiene_carpeta_para_presentar"))
        message = (status or {}).get("mensaje") or ("Carpeta PARA PRESENTAR encontrada" if ok else "Falta carpeta PARA PRESENTAR")
        folder_path = (status or {}).get("box_para_presentar_folder_path") or ""
        docs = _load_para_presentar_documents(expediente_id) if ok else []
        error = state.setdefault("para_presentar_documents_error", {}).get(int(expediente_id))

        status_color = "#027A48" if ok else "#B42318"
        icon = "✓" if ok else "✗"

        controls = [
            ft.Row(
                controls=[
                    ft.Text(icon, size=22, weight=ft.FontWeight.BOLD, color=status_color),
                    ft.Text(message, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                    ft.Text("Escaneando carpeta del expediente...", size=12, color=Q_MUTED, visible=scanning),
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                "Lectura readonly de documentos preparados para Mercurio. No inicia subida automática.",
                size=12,
                color=Q_MUTED,
            ),
        ]

        if folder_path:
            controls.append(ft.Text(folder_path, size=12, color=Q_MUTED))

        controls.append(
            ft.Row(
                controls=[
                    secondary_button("Refrescar documentos", refresh_para_presentar_documents),
                    primary_button("Abrir carpeta", open_para_presentar_folder),
                    secondary_button("Ver en explorador", open_para_presentar_in_browser),
                ],
                spacing=10,
                wrap=True,
            )
        )

        if not ok:
            controls.append(ft.Text('No se puede leer documentación: falta carpeta "PARA PRESENTAR".', size=12, color="#B42318"))
            controls.append(ft.Text('La Presentación Asistida Mercurio queda bloqueada hasta que exista "PARA PRESENTAR".', size=12, color="#B42318"))
            return _section_box("DOCUMENTACIÓN MERCURIO", controls)

        if error:
            controls.append(error_alert(error))
            return _section_box("DOCUMENTACIÓN MERCURIO", controls)

        if not docs:
            controls.append(ft.Text("No hay documentos en la carpeta PARA PRESENTAR.", size=13, color=Q_MUTED))
            return _section_box("DOCUMENTACIÓN MERCURIO", controls)

        controls.append(ft.Text("Documentación detectada correctamente.", size=13, weight=ft.FontWeight.BOLD, color="#027A48"))

        rows = []
        for doc in sorted(docs, key=_mercurio_file_sort_key):
            rows.append([
                _mercurio_file_order_label(doc),
                doc.get("name") or "-",
                doc.get("extension") or "-",
                _format_file_size(doc.get("size")),
                _format_datetime(doc.get("modified_at") or doc.get("fecha_modificacion")),
                doc.get("box_file_id") or "-",
                doc.get("relative_path") or "-",
                doc.get("box_url") or doc.get("path") or "-",
            ])

        controls.append(
            app_table(
                ["Orden", "Nombre", "Ext.", "Tamaño", "Fecha modificación", "box_file_id", "Ruta relativa", "URL Box"],
                rows,
                height=280,
            )
        )
        return _section_box("DOCUMENTACIÓN MERCURIO", controls)

    def _selected_tipo_id():
        return _option_id(tipo_expediente.get_value())

    def _selected_subtipo_id():
        return _option_id_from_autocomplete_value(subtipo_expediente.get_value(), subtipo_expediente.options)

    def _selected_option_label(value):
        value = str(value or "").strip()
        if " - " in value:
            return value.split(" - ", 1)[1].strip()
        return value or "-"

    def _selected_subtipo_label():
        value = str(subtipo_expediente.get_value() or "").strip()
        if not value or value == "Sin subtipo":
            manual = str(subtipo_expediente_manual.value or "").strip()
            return manual or "Sin subtipo"
        parts = value.split(" - ", 2)
        return parts[-1].strip() if parts else value

    def _dynamic_value(control):
        """Lee controles normales y AppAutocomplete de forma uniforme."""
        if hasattr(control, "get_value"):
            return control.get_value()
        return getattr(control, "value", "")

    def _database_path():
        return Path(__file__).resolve().parents[2] / "database" / "quesada.db"

    def _fetch_cliente_contact_options(cliente_id, only_employers=False):
        if not cliente_id:
            return []
        db_path = _database_path()
        if not db_path.exists():
            return []

        employer_tokens = ("EMPLEADOR", "EMPRESA", "TRABAJO")
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, tipo_contacto, parentesco, nombre, primer_apellido, segundo_apellido,
                           nie, dni, pasaporte, email, telefono
                    FROM cliente_contactos
                    WHERE cliente_id = ?
                      AND COALESCE(activo, 1) = 1
                    ORDER BY tipo_contacto ASC, parentesco ASC, nombre ASC, id DESC
                    """,
                    (int(cliente_id),),
                ).fetchall()
        except Exception:
            return []

        options = []
        for row in rows:
            tipo_contacto = str(row["tipo_contacto"] or "").upper()
            is_employer = any(token in tipo_contacto for token in employer_tokens)
            if only_employers and not is_employer:
                continue
            if not only_employers and is_employer:
                continue

            nombre = " ".join(
                part for part in [row["nombre"], row["primer_apellido"], row["segundo_apellido"]] if part
            ).strip() or "Sin nombre"
            documento = row["nie"] or row["dni"] or row["pasaporte"] or ""
            detalle = documento or row["email"] or row["telefono"] or row["parentesco"] or tipo_contacto
            options.append(f"{row['id']} - {nombre}" + (f" · {detalle}" if detalle else ""))

        return options

    def _row_document(row):
        if not row:
            return ""
        for key in ("nie", "dni", "pasaporte", "documento"):
            try:
                value = row[key]
            except Exception:
                value = None
            if value:
                return value
        return ""

    def _row_nombre_completo(row):
        if not row:
            return ""
        parts = []
        for key in ("nombre", "primer_apellido", "segundo_apellido"):
            try:
                value = row[key]
            except Exception:
                value = None
            if value:
                parts.append(str(value).strip())
        return " ".join(part for part in parts if part).strip()

    def _row_to_autofill_details(row, extra=None):
        if not row:
            return {}
        details = {key: (row[key] if row[key] is not None else "") for key in row.keys()}
        details["nombre_completo"] = _row_nombre_completo(row)
        details["documento"] = _row_document(row)
        if extra:
            details.update(extra)
        return details

    def _fetch_cliente_details(cliente_id):
        if not cliente_id:
            return {}
        db_path = _database_path()
        if not db_path.exists():
            return {}

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT *
                    FROM clientes
                    WHERE id = ?
                      AND COALESCE(activo, 1) = 1
                    LIMIT 1
                    """,
                    (int(cliente_id),),
                ).fetchone()
        except Exception:
            return {}

        return _row_to_autofill_details(row)

    def _fetch_cliente_contact_details(contacto_id):
        if not contacto_id:
            return {}
        db_path = _database_path()
        if not db_path.exists():
            return {}

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT *
                    FROM cliente_contactos
                    WHERE id = ?
                      AND COALESCE(activo, 1) = 1
                    LIMIT 1
                    """,
                    (int(contacto_id),),
                ).fetchone()
        except Exception:
            return {}

        titulo = ""
        if row:
            titulo = row["parentesco"] if "parentesco" in row.keys() and row["parentesco"] else ""
            if not titulo and "tipo_contacto" in row.keys():
                titulo = row["tipo_contacto"] or ""

        return _row_to_autofill_details(row, {"titulo": titulo})


    def _autocomplete_source_options(source):
        source = (source or "contactos_cliente").lower()
        cliente_id = _option_id(cliente.get_value())

        if source in ("cliente", "cliente_expediente", "clientes", "datos_cliente"):
            return cliente_options, _fetch_cliente_details

        if source in ("empleadores_cliente", "empleador", "empleadores"):
            return _fetch_cliente_contact_options(cliente_id, only_employers=True), _fetch_cliente_contact_details

        if source in ("catalogo_cnae", "actividad_cnae"):
            return _load_catalog_options("actividades_cnae.csv"), lambda selected_id: {}

        if source in ("catalogo_cno", "cno_sepe"):
            return _load_catalog_options("cno_sepe_2011.csv"), lambda selected_id: {}

        return _fetch_cliente_contact_options(cliente_id, only_employers=False), _fetch_cliente_contact_details


    def _detail_value(details, source_key):
        if not details:
            return ""
        key = str(source_key or "").strip()
        if not key:
            return ""

        # Alias útiles para evitar que el mapper dependa de nombres exactos.
        aliases = {
            "nombre_apellidos": "nombre_completo",
            "nombre_y_apellidos": "nombre_completo",
            "documento_identidad": "documento",
            "num_documento": "documento",
            "numero_documento": "documento",
            "telefono_movil": "telefono",
            "movil": "telefono",
            "mail": "email",
            "correo": "email",
        }

        candidates = [key, key.lower(), aliases.get(key.lower())]
        for candidate in candidates:
            if candidate and details.get(candidate) not in (None, ""):
                return details.get(candidate) or ""
        return ""


    def _build_mapped_autocomplete_field(campo, saved_values, required_suffix, config, default_help=""):
        codigo = campo.get("codigo")
        label = campo.get("etiqueta") or codigo
        ayuda = campo.get("ayuda") or default_help or "Selecciona un valor. Los campos derivados configurados se completarán automáticamente."
        source = (config or {}).get("source") or "contactos_cliente"
        mappings = (config or {}).get("campos") or {}

        selected_value = saved_values.get(codigo, campo.get("valor_defecto") or "")
        selected_id = saved_values.get(f"{codigo}_id", "")
        id_control = text_input("ID seleccionado", selected_id, width=160)
        id_control.visible = False
        state.setdefault("specific_field_controls", {})[f"{codigo}_id"] = id_control

        derived_controls = []
        for target_key, source_key in mappings.items():
            full_code = f"{codigo}_{target_key}"
            label_text = target_key.replace("_", " ").capitalize()
            control = text_input(label_text, saved_values.get(full_code, ""), width=260)
            state.setdefault("specific_field_controls", {})[full_code] = control
            derived_controls.append((control, source_key))

        options, detail_loader = _autocomplete_source_options(source)

        def apply_selected(selected):
            selected_id_value = _option_id(selected)
            id_control.value = str(selected_id_value or "")
            details = detail_loader(selected_id_value) if selected_id_value else {}
            for control, source_key in derived_controls:
                control.value = _detail_value(details, source_key)
            page.update()

        autocomplete = AppAutocomplete(
            page=page,
            label=label + required_suffix,
            options=options,
            value=selected_value or "",
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_selected if derived_controls else None,
        )
        state.setdefault("specific_field_controls", {})[codigo] = autocomplete

        controls = [autocomplete.control]
        if derived_controls:
            controls.append(ft.Row([item[0] for item in derived_controls] + [id_control], wrap=True, spacing=10))
        else:
            controls.append(id_control)
        controls.append(ft.Text(ayuda, size=11, color=Q_MUTED))

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(controls=controls, spacing=8),
        )



    def _is_dynamic_autocomplete_type(tipo):
        tipo = str(tipo or "").strip().lower()
        return tipo in (
            "dato_cliente",
            "autocomplete_cliente",
            "contacto_cliente",
            "autocomplete_familiar",
            "representante_legal",
            "autocomplete_representante_legal",
            "empleador_empresa",
            "autocomplete_empleador",
        )

    def _autocomplete_has_derived_fields(config):
        if not isinstance(config, dict):
            return False
        fields = config.get("derived_fields")
        return isinstance(fields, list) and bool(fields)

    def _autocomplete_is_employer(tipo, config):
        tipo = str(tipo or "").strip().lower()
        profile = str((config or {}).get("profile") or "").strip().upper()
        contact_filter = str((config or {}).get("contact_filter") or "").strip().upper()
        source = str((config or {}).get("source") or "").strip().lower()

        if tipo in ("empleador_empresa", "autocomplete_empleador"):
            return True
        if "EMPLEADOR" in profile or "EMPRESA" in profile:
            return True
        if any(token in contact_filter for token in ("EMPLEADOR", "EMPRESA", "TRABAJO")):
            return True
        if source in ("empleadores_cliente", "empleador", "empleadores"):
            return True
        return False

    def _autocomplete_options_and_loader_for_config(campo, config):
        tipo = str((campo or {}).get("tipo_campo") or "").strip().lower()
        source = str((config or {}).get("source") or "").strip().lower()
        cliente_id = _option_id(cliente.get_value())

        if source in ("cliente", "cliente_expediente", "clientes", "datos_cliente") or tipo in ("dato_cliente", "autocomplete_cliente"):
            return cliente_options, _fetch_cliente_details

        if source in ("catalogo_cnae", "actividad_cnae") or tipo == "actividad_cnae":
            return _load_catalog_options("actividades_cnae.csv"), lambda selected_id: {}

        if source in ("catalogo_cno", "cno_sepe") or tipo == "cno_sepe":
            return _load_catalog_options("cno_sepe_2011.csv"), lambda selected_id: {}

        return (
            _fetch_cliente_contact_options(
                cliente_id,
                only_employers=_autocomplete_is_employer(tipo, config),
            ),
            _fetch_cliente_contact_details,
        )

    def _source_key_for_derived_field(field_name):
        field_name = str(field_name or "").strip()
        lowered = field_name.lower()

        if lowered in ("id", "contacto_id", "cliente_id", "empleador_id", "empresa_id", "record_id"):
            return "id"

        aliases = {
            "nombre_completo": "nombre_completo",
            "documento": "documento",
            "documento_identidad": "documento",
            "num_documento": "documento",
            "numero_documento": "documento",
            "telefono_movil": "telefono",
            "movil": "telefono",
            "mail": "email",
            "correo": "email",
            "titulo": "titulo",
        }
        return aliases.get(lowered, field_name)

    def _remember_specific_value(codigo, value):
        if not codigo:
            return
        state.setdefault("specific_live_values", {})[str(codigo)] = str(value or "")

    def _set_specific_control_value(codigo, value):
        value = str(value or "")
        _remember_specific_value(codigo, value)
        control = state.setdefault("specific_field_controls", {}).get(codigo)
        if control is None:
            return
        try:
            if hasattr(control, "set_value"):
                control.set_value(value, update=False)
            else:
                control.value = value
        except Exception:
            try:
                control.value = value
            except Exception:
                pass

    def _current_specific_values():
        """Lee los controles visibles y mezcla los valores volcados en vivo.

        No puede llamarse a sí misma: esta función es la fuente única de
        valores que se guardan en expediente_datos_especificos.
        """
        values = {
            codigo: _dynamic_value(control)
            for codigo, control in state.get("specific_field_controls", {}).items()
        }
        values.update(state.get("specific_live_values") or {})
        return values

    def _autosave_specific_values_silent():
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id or not formulario_id:
            return
        try:
            if state.get("specific_view_mode") in ("EX01_FAMILIAR", "EX01_TITULAR", "EX02") and hasattr(dynamic_form_service, "save_datos_especificos_patch"):
                dynamic_form_service.save_datos_especificos_patch(
                    expediente_id,
                    formulario_id,
                    _current_specific_values(),
                )
            else:
                dynamic_form_service.save_datos_especificos(
                    expediente_id,
                    formulario_id,
                    _current_specific_values(),
                )
        except Exception:
            # No bloquea la selección. El botón Guardar mostrará el error si persiste.
            pass

    def _apply_autocomplete_derived_fields(codigo, config, selected, detail_loader):
        """
        Vuelca en pantalla los derived_fields materializados.

        Ejemplo:
        campo principal: representante_legal
        derived_fields: ["nombre", "nie"]
        controles destino:
        - representante_legal_nombre
        - representante_legal_nie
        """
        selected_id_value = _option_id(selected)
        details = detail_loader(selected_id_value) if selected_id_value else {}

        fields = (config or {}).get("derived_fields") or []
        controls = state.setdefault("specific_field_controls", {})

        # Compatibilidad: si existe un campo técnico prefix_id, también se rellena.
        _set_specific_control_value(f"{codigo}_id", str(selected_id_value or ""))

        for field_name in fields:
            field_name = str(field_name or "").strip()
            if not field_name:
                continue

            target_code = f"{codigo}_{field_name}"
            source_key = _source_key_for_derived_field(field_name)
            if source_key == "id":
                value = str(selected_id_value or "")
            else:
                value = _detail_value(details, source_key)

            _set_specific_control_value(target_code, value)

    def _build_autocomplete_derivatives_field(campo, saved_values, required_suffix, config, default_help=""):
        codigo = campo.get("codigo")
        label = campo.get("etiqueta") or codigo
        value = saved_values.get(codigo, campo.get("valor_defecto") or "")
        ayuda = campo.get("ayuda") or default_help or "Selecciona y se rellenan los derivados."

        options, detail_loader = _autocomplete_options_and_loader_for_config(campo, config)

        def apply_selected(selected):
            _remember_specific_value(codigo, selected)
            _apply_autocomplete_derived_fields(codigo, config, selected, detail_loader)
            _autosave_specific_values_silent()
            page.update()

        autocomplete = AppAutocomplete(
            page=page,
            label=label + required_suffix,
            options=options or [],
            value=value or "",
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_selected,
        )
        state.setdefault("specific_field_controls", {})[codigo] = autocomplete

        return ft.Column(
            controls=[
                autocomplete.control,
                ft.Text(ayuda, size=11, color=Q_MUTED),
            ],
            spacing=3,
        )


    def _build_representante_legal_field(campo, saved_values, required_suffix):
        codigo = campo.get("codigo")
        label = campo.get("etiqueta") or codigo or "Representante legal"
        ayuda = campo.get("ayuda") or "Selecciona un contacto del cliente. El nombre, documento y título se copiarán a datos específicos y al snapshot."

        selected_value = saved_values.get(codigo, campo.get("valor_defecto") or "")
        selected_id = saved_values.get(f"{codigo}_id", "")
        nombre_value = saved_values.get(f"{codigo}_nombre", "")
        documento_value = saved_values.get(f"{codigo}_documento", "")
        titulo_value = saved_values.get(f"{codigo}_titulo", "")

        nombre_control = text_input("Nombre representante legal", nombre_value, width=360)
        documento_control = text_input("Documento representante legal", documento_value, width=240)
        titulo_control = text_input("Título / parentesco", titulo_value, width=240)
        id_control = text_input("ID contacto representante legal", selected_id, width=160)
        id_control.visible = False

        state.setdefault("specific_field_controls", {})[f"{codigo}_id"] = id_control
        state.setdefault("specific_field_controls", {})[f"{codigo}_nombre"] = nombre_control
        state.setdefault("specific_field_controls", {})[f"{codigo}_documento"] = documento_control
        state.setdefault("specific_field_controls", {})[f"{codigo}_titulo"] = titulo_control

        def apply_contact(selected):
            contacto_id = _option_id(selected)
            id_control.value = str(contacto_id or "")
            if not contacto_id:
                return
            details = _fetch_cliente_contact_details(contacto_id)
            if not details:
                return
            nombre_control.value = details.get("nombre_completo") or details.get("nombre") or ""
            documento_control.value = details.get("documento") or ""
            titulo_control.value = details.get("titulo") or ""
            page.update()

        options = _fetch_cliente_contact_options(_option_id(cliente.get_value()), only_employers=False)
        autocomplete = AppAutocomplete(
            page=page,
            label=label + required_suffix,
            options=options,
            value=selected_value or "",
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_contact,
        )
        state.setdefault("specific_field_controls", {})[codigo] = autocomplete

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=[
                    autocomplete.control,
                    ft.Row([nombre_control, documento_control, titulo_control, id_control], wrap=True, spacing=10),
                    ft.Text(ayuda, size=11, color=Q_MUTED),
                ],
                spacing=8,
            ),
        )

    def _load_catalog_options(filename, limit=2500):
        path = Path(__file__).resolve().parents[2] / "database" / "catalogos_mercurio" / "csv" / filename
        if not path.exists():
            return []

        options = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for index, row in enumerate(reader):
                    if index >= limit:
                        break
                    values = [str(v or "").strip() for v in row.values() if str(v or "").strip()]
                    if values:
                        options.append(" · ".join(values[:3]))
        except Exception:
            return []
        return options

    def _autocomplete_field(codigo, label, value, options, required_suffix, ayuda="", width=520, allow_free_text=True):
        autocomplete = AppAutocomplete(
            page=page,
            label=label + required_suffix,
            options=options or [],
            value=value or "",
            width=width,
            max_results=10,
            allow_free_text=allow_free_text,
        )
        state.setdefault("specific_field_controls", {})[codigo] = autocomplete
        controls = [autocomplete.control]
        if ayuda:
            controls.append(ft.Text(ayuda, size=11, color=Q_MUTED))
        return ft.Column(controls=controls, spacing=3)

    def _build_dynamic_field_control(campo, saved_values):
        codigo = campo.get("codigo")
        label = campo.get("etiqueta") or codigo
        value = saved_values.get(codigo, campo.get("valor_defecto") or "")
        tipo = (campo.get("tipo_campo") or "texto").lower()
        placeholder = campo.get("placeholder") or ""
        ayuda = campo.get("ayuda") or ""
        required_suffix = " *" if int(campo.get("obligatorio") or 0) else ""
        autocomplete_config = dynamic_form_service.parse_autocomplete_fill_config(campo.get("opciones_json"))

        if tipo.startswith("autocomplete_") and autocomplete_config.get("campos"):
            return _build_mapped_autocomplete_field(campo, saved_values, required_suffix, autocomplete_config, ayuda)

        if _is_dynamic_autocomplete_type(tipo) and _autocomplete_has_derived_fields(autocomplete_config):
            return _build_autocomplete_derivatives_field(campo, saved_values, required_suffix, autocomplete_config, ayuda)

        if tipo in ("dato_cliente", "autocomplete_cliente"):
            return _autocomplete_field(
                codigo,
                label,
                value,
                cliente_options,
                required_suffix,
                ayuda or "Selecciona un cliente del CRM. Se guarda el valor confirmado en datos específicos.",
                width=560,
                allow_free_text=True,
            )

        if tipo in ("representante_legal", "autocomplete_representante_legal"):
            return _build_representante_legal_field(campo, saved_values, required_suffix)

        if tipo in ("contacto_cliente", "autocomplete_familiar"):
            options = _fetch_cliente_contact_options(_option_id(cliente.get_value()), only_employers=False)
            return _autocomplete_field(
                codigo,
                label,
                value,
                options,
                required_suffix,
                ayuda or "Selecciona un contacto/familiar vinculado al cliente del expediente.",
                width=560,
                allow_free_text=True,
            )

        if tipo in ("empleador_empresa", "autocomplete_empleador"):
            options = _fetch_cliente_contact_options(_option_id(cliente.get_value()), only_employers=True)
            return _autocomplete_field(
                codigo,
                label,
                value,
                options,
                required_suffix,
                ayuda or "Selecciona un empleador/empresa vinculado al cliente del expediente.",
                width=560,
                allow_free_text=True,
            )

        if tipo == "actividad_cnae":
            options = _load_catalog_options("actividades_cnae.csv")
            return _autocomplete_field(
                codigo,
                label,
                value,
                options,
                required_suffix,
                ayuda or "Catálogo Mercurio de actividades/CNAE.",
                width=720,
                allow_free_text=True,
            )

        if tipo == "cno_sepe":
            options = _load_catalog_options("cno_sepe_2011.csv")
            return _autocomplete_field(
                codigo,
                label,
                value,
                options,
                required_suffix,
                ayuda or "Catálogo Mercurio CNO/SEPE.",
                width=720,
                allow_free_text=True,
            )

        if tipo == "textarea":
            control = multiline_input(label + required_suffix, value, width=760, height=90)
        elif tipo == "select":
            options = dynamic_form_service.parse_field_options(campo.get("opciones_json"))
            control = select_input(label + required_suffix, options or [""], value=value if value in options else (options[0] if options else ""), width=360)
        elif tipo == "boolean":
            control = select_input(label + required_suffix, ["Sí", "No"], value=value if value in ["Sí", "No"] else "No", width=180)
        else:
            width = 220 if tipo in ("numero", "fecha") else 360
            control = text_input(label + required_suffix, value, width=width)
            if placeholder:
                control.hint_text = placeholder

        state.setdefault("specific_field_controls", {})[codigo] = control

        if ayuda:
            return ft.Column(
                controls=[control, ft.Text(ayuda, size=11, color=Q_MUTED)],
                spacing=3,
            )

        return control

    def save_specific_data(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de guardar datos específicos")
            return
        if not formulario_id:
            show_form_error("No hay formulario específico configurado para este expediente")
            return

        values = _current_specific_values()

        try:
            if state.get("specific_view_mode") in ("EX01_FAMILIAR", "EX01_TITULAR", "EX02") and hasattr(dynamic_form_service, "save_datos_especificos_patch"):
                dynamic_form_service.save_datos_especificos_patch(expediente_id, formulario_id, values)
            else:
                dynamic_form_service.save_datos_especificos(expediente_id, formulario_id, values)
            clear_form_message()
            set_message(success_alert("Datos específicos guardados"))
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def generate_snapshot(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de generar snapshot")
            return

        try:
            # Antes de congelar el snapshot, persistimos los datos específicos visibles
            # y los campos técnicos ocultos materializados en la ficha EX.
            if state.get("specific_formulario_id"):
                _save_specific_values_or_raise()

            result = snapshot_service.save_snapshot(expediente_id, created_by="ERP")
            state.setdefault("snapshot_status", {})[int(expediente_id)] = result

            if result.get("validated"):
                message = f"Snapshot generado correctamente · versión {result.get('version')}"
                _set_specific_generation_success(expediente_id, message)
                set_message(success_alert(message))
                show_form_success(message)
            else:
                errors = result.get("errors") or []
                message = "Snapshot generado con advertencias:\n- " + "\n- ".join(errors)
                set_message(error_alert(message))
                show_form_error(message)

            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        except Exception as exc:
            show_form_error(str(exc))


    def build_snapshot_status_content(expediente_id):
        if not expediente_id:
            return ft.Text(
                "Guarda el expediente para poder generar snapshot.",
                size=12,
                color=Q_MUTED,
            )

        try:
            latest = snapshot_service.load_latest_snapshot(expediente_id)
        except Exception as exc:
            return error_alert(f"No se pudo leer snapshot: {exc}")

        if not latest:
            return ft.Container(
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("Snapshot no generado", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Text(
                            "Todavía no existe una versión congelada de datos para Mercurio / EX.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                ),
            )

        valid_text = "VALIDADO" if int(latest.get("validated") or 0) else "CON ADVERTENCIAS"
        valid_color = "#027A48" if int(latest.get("validated") or 0) else "#B42318"

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"Snapshot v{latest.get('version')}",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(valid_text, size=12, weight=ft.FontWeight.BOLD, color=valid_color),
                        ],
                        spacing=10,
                    ),
                    ft.Text(f"Creado: {latest.get('created_at') or '-'}", size=12, color=Q_MUTED),
                    ft.Text(f"Hash: {latest.get('source_hash') or '-'}", size=11, color=Q_MUTED),
                    ft.Text(
                        "Este snapshot será el origen estable para Mercurio, EX y automatización.",
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
            ),
        )



    def _save_payload_preview_file(expediente_id, destination, preview):
        base_dir = Path(__file__).resolve().parents[2] / "exports" / "mapper_previews"
        base_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"expediente_{expediente_id}_{destination}_{timestamp}.json"
        path = base_dir / filename

        path.write_text(
            json.dumps(preview or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def generate_payload_preview_for_destination(destination, e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de generar preview")
            return

        destination = destination or "MERCURIO"
        state["payload_preview_destination"] = destination

        try:
            preview = mapper_preview_service.preview_destination_for_expedient(
                expediente_id,
                destination,
                auto_build_snapshot=True,
            )
            preview_path = _save_payload_preview_file(expediente_id, destination, preview)

            state.setdefault("payload_preview_result", {})[int(expediente_id)] = preview
            state.setdefault("payload_preview_file", {})[int(expediente_id)] = preview_path
            state.setdefault("payload_preview_error", {}).pop(int(expediente_id), None)
            clear_form_message()
        except Exception as exc:
            state.setdefault("payload_preview_result", {}).pop(int(expediente_id), None)
            state.setdefault("payload_preview_file", {}).pop(int(expediente_id), None)
            state.setdefault("payload_preview_error", {})[int(expediente_id)] = str(exc)

        # No abrimos segundos diálogos ni pantallas internas.
        # Se reconstruye solo la sección compacta de Automatización.
        state["dialog_section"] = "automatizacion"
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()


    def open_payload_preview_fullscreen(preview, e=None):
        if not preview:
            return

        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            return

        state["payload_preview_fullscreen"] = preview
        state["dialog_section"] = "payload_preview_fullscreen"
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()

    def back_to_payload_preview(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        state["dialog_section"] = "automatizacion"
        if expediente_id:
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()

    def build_payload_preview_fullscreen_content(expediente_id):
        preview = state.get("payload_preview_fullscreen") or {}
        if not preview:
            return ft.Column(
                width=920,
                height=620,
                spacing=12,
                controls=[
                    secondary_button("Volver a Automatización", back_to_payload_preview),
                    empty_state("No hay preview generado para mostrar"),
                ],
            )

        payload = preview.get("payload") or {}
        errors = ((preview.get("validation") or {}).get("errors")) or []
        empty_fields = preview.get("empty_fields") or []
        summary = preview.get("summary") or {}
        template = preview.get("template") or {}
        snapshot_info = preview.get("snapshot") or {}

        valid = bool(summary.get("valid"))
        status_color = "#027A48" if valid else "#B42318"
        status_text = "PREVIEW VÁLIDO" if valid else "PREVIEW CON ERRORES"
        snapshot_text = (
            "Snapshot generado en memoria"
            if snapshot_info.get("generated_in_memory")
            else f"Snapshot v{snapshot_info.get('version') or '-'}"
        )

        return ft.Column(
            width=920,
            height=620,
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
            controls=[
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=16,
                    padding=14,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.CODE, size=24, color=Q_PRIMARY),
                                bgcolor="#FFFFFF",
                                border_radius=24,
                                width=48,
                                height=48,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        f"Payload completo · {preview.get('destination') or '-'}",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        "Vista de solo lectura del payload generado desde el snapshot.",
                                        size=13,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            secondary_button("Volver", back_to_payload_preview),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                                    ft.Text(snapshot_text, size=12, color=Q_MUTED),
                                    ft.Text(f"Match: {preview.get('match_level') or '-'}", size=12, color=Q_MUTED),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Text(
                                f"Mapper: {template.get('codigo') or '-'} · {template.get('nombre') or '-'}",
                                size=12,
                                color=Q_PRIMARY_DARK,
                                selectable=True,
                            ),
                            ft.Text(
                                f"Campos payload: {summary.get('payload_fields', 0)} · "
                                f"Campos vacíos: {summary.get('empty_fields', 0)} · "
                                f"Errores required: {summary.get('required_errors', 0)}",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                ),
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text("Validación", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(
                                "Errores:\n- " + "\n- ".join(errors) if errors else "Sin errores de validación.",
                                size=12,
                                color="#B42318" if errors else "#027A48",
                                selectable=True,
                            ),
                            ft.Text(
                                "Campos vacíos:\n- " + "\n- ".join(empty_fields) if empty_fields else "Sin campos vacíos.",
                                size=12,
                                color="#B42318" if empty_fields else "#027A48",
                                selectable=True,
                            ),
                        ],
                    ),
                ),
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text("Payload JSON completo", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=12,
                                content=ft.Text(
                                    json.dumps(payload, ensure_ascii=False, indent=2),
                                    size=12,
                                    color="#101828",
                                    selectable=True,
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        )


    def _payload_preview_destination_button(destination):
        selected = (state.get("payload_preview_destination") or "MERCURIO") == destination

        return ft.Container(
            bgcolor=Q_PRIMARY if selected else "#FFFFFF",
            border=ft.border.all(1, Q_PRIMARY if selected else Q_BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            ink=True,
            on_click=lambda e, d=destination: generate_payload_preview_for_destination(d, e),
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.PLAY_ARROW,
                        size=16,
                        color="#FFFFFF" if selected else Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        destination,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color="#FFFFFF" if selected else Q_PRIMARY_DARK,
                    ),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _payload_preview_summary(preview):
        summary = preview.get("summary") or {}
        snapshot_info = preview.get("snapshot") or {}
        template = preview.get("template") or {}

        valid = bool(summary.get("valid"))
        status_text = "PREVIEW VÁLIDO" if valid else "PREVIEW CON ERRORES"
        status_color = "#027A48" if valid else "#B42318"
        snapshot_text = (
            "Snapshot generado en memoria"
            if snapshot_info.get("generated_in_memory")
            else f"Snapshot v{snapshot_info.get('version') or '-'}"
        )

        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                            ft.Text(snapshot_text, size=12, color=Q_MUTED),
                            ft.Text(f"Match: {preview.get('match_level') or '-'}", size=12, color=Q_MUTED),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Text(
                        f"Mapper: {template.get('codigo') or '-'} · {template.get('nombre') or '-'}",
                        size=12,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        f"Destino: {preview.get('destination') or '-'} · "
                        f"Campos payload: {summary.get('payload_fields', 0)} · "
                        f"Campos vacíos: {summary.get('empty_fields', 0)} · "
                        f"Errores required: {summary.get('required_errors', 0)}",
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
            ),
        )

    def _payload_preview_validation(preview):
        errors = ((preview.get("validation") or {}).get("errors")) or []
        empty_fields = preview.get("empty_fields") or []

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text("Validación", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(
                        "Errores:\n- " + "\n- ".join(errors) if errors else "Sin errores de validación.",
                        size=12,
                        color="#B42318" if errors else "#027A48",
                    ),
                    ft.Text(
                        "Campos vacíos:\n- " + "\n- ".join(empty_fields) if empty_fields else "Sin campos vacíos.",
                        size=12,
                        color="#B42318" if empty_fields else "#027A48",
                    ),
                ],
            ),
        )

    def _payload_preview_actions(preview):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        preview_path = state.setdefault("payload_preview_file", {}).get(int(expediente_id)) if expediente_id else ""

        controls = [
            ft.Text(
                "Preview generado correctamente. El payload completo se ha guardado como JSON para evitar bloqueos visuales en Flet.",
                size=12,
                color=Q_MUTED,
                expand=True,
            ),
        ]

        if preview_path:
            controls.append(
                ft.Text(
                    f"Archivo: {preview_path}",
                    size=11,
                    color=Q_PRIMARY_DARK,
                )
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                spacing=8,
                controls=controls,
            ),
        )


    def _payload_preview_payload(preview):
        payload = preview.get("payload") or {}
        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text("Payload generado", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.TextField(
                        value=json.dumps(payload, ensure_ascii=False, indent=2),
                        multiline=True,
                        read_only=True,
                        min_lines=10,
                        max_lines=16,
                        border_color=Q_BORDER,
                        text_size=12,
                    ),
                ],
            ),
        )

    def build_payload_preview_content(expediente_id):
        if not expediente_id:
            return empty_state("Guarda el expediente para poder previsualizar payloads")

        expediente_id = int(expediente_id)
        preview = state.setdefault("payload_preview_result", {}).get(expediente_id)
        error = state.setdefault("payload_preview_error", {}).get(expediente_id)

        controls = [
            ft.Container(
                bgcolor="#EAF3FF",
                border=ft.border.all(1, "#B9D7FF"),
                border_radius=16,
                padding=14,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.ROCKET_LAUNCH, size=24, color=Q_PRIMARY),
                            bgcolor="#FFFFFF",
                            border_radius=24,
                            width=48,
                            height=48,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("Automatización", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(
                                    "Preview del payload generado desde el snapshot. No ejecuta Mercurio ni presenta.",
                                    size=13,
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
            ),
            build_snapshot_status_content(expediente_id),
            ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=14,
                padding=12,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("Generar preview por destino", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Row(
                            controls=[
                                _payload_preview_destination_button("MERCURIO"),
                                _payload_preview_destination_button("EX"),
                                _payload_preview_destination_button("PDF"),
                                _payload_preview_destination_button("WORD"),
                                _payload_preview_destination_button("OCR"),
                                _payload_preview_destination_button("OTRO"),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        ft.Text(
                            "Busca mapper específico del expediente; si no existe, usa mapper general del destino.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                ),
            ),
        ]

        if error:
            controls.append(error_alert(error))

        if preview:
            controls.extend([
                _payload_preview_summary(preview),
                _payload_preview_validation(preview),
                _payload_preview_actions(preview),
            ])
        else:
            controls.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=14,
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text("Sin preview generado", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text("Pulsa uno de los destinos para generar el payload.", size=12, color=Q_MUTED),
                        ],
                    ),
                )
            )

        return ft.Container(
            width=920,
            height=620,
            bgcolor="#FFFFFF",
            content=ft.Column(
                controls=controls,
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            ),
        )


    def volcar_datos_formulario(e=None):
        """Acción puente para el futuro volcado a EX/Mercurio.

        En esta fase deja claro que el origen será el snapshot de datos específicos
        del expediente. La integración real con formularios oficiales/Mercurio se
        conectará después al mapper.
        """
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de volcar datos")
            return
        if not formulario_id:
            show_form_error("No hay formulario específico configurado para este expediente")
            return

        try:
            values = dynamic_form_service.load_datos_especificos(expediente_id) or {}
            if not values:
                show_form_error("Guarda primero los datos específicos antes de volcarlos al formulario")
                return
            clear_form_message()
            set_message(success_alert("Datos específicos listos para volcado. Siguiente fase: mapper EX/Mercurio"))
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def _resolve_ex_template_code(tipo_id, subtipo_id, tipo_label="", subtipo_label=""):
        """Resuelve la plantilla EX preferente para la pantalla específica.

        Para EX01 familiar no basta con EX01: en Settings puede existir una
        plantilla separada como EX01_FAMILIAR. Por eso devolvemos el código
        funcional más específico y luego buscamos fallbacks.
        """
        try:
            reglas = presentation_config_service.get_presentacion_reglas(tipo_id, subtipo_id=subtipo_id) if tipo_id else {}
        except Exception:
            reglas = {}

        mapper = str((reglas or {}).get("mapper_codigo") or "").strip().upper()
        joined = _norm(f"{tipo_label} {subtipo_label} {mapper}")

        if mapper == "MERCURIO_EX01_FAMILIAR" or ("EX01" in joined and "FAMILIAR" in joined) or ("NO LUCRATIVA" in joined and "FAMILIAR" in joined):
            return "EX01_FAMILIAR"

        tipo_formulario = str((reglas or {}).get("tipo_formulario_objetivo") or "").strip().upper()
        if tipo_formulario:
            return tipo_formulario

        if "EX01" in joined or "NO LUCRATIVA" in joined:
            return "EX01"
        if "EX02" in joined or "REAGRUPACION" in joined or "REAGRUPACIÓN" in joined:
            return "EX02"
        return "EX"

    def _safe_export_name(value):
        raw = _norm(value).replace(" ", "_")
        safe = []
        for ch in raw:
            if ch.isalnum() or ch in ("_", "-"):
                safe.append(ch)
            else:
                safe.append("_")
        return "".join(safe).strip("_") or "EXPEDIENTE"

    def _normalize_template_lookup(value):
        return _safe_export_name(value).upper()

    def _ex_template_candidates(ex_code):
        code = _normalize_template_lookup(ex_code)
        candidates = [code]
        if code == "EX01_FAMILIAR":
            candidates.extend(["MERCURIO_EX01_FAMILIAR", "EX01", "MERCURIO_EX01"])
        elif code == "EX01":
            candidates.extend(["MERCURIO_EX01"])
        elif code == "EX02":
            candidates.extend(["MERCURIO_EX02"])
        return list(dict.fromkeys(candidates))

    def _find_ex_document_template(ex_code):
        """Busca la plantilla EX igual que Settings, pero por código funcional.

        No nos limitamos a mapper_destino=EX01 porque las plantillas pueden
        haberse registrado como EX01_FAMILIAR, MERCURIO_EX01_FAMILIAR o EX01.
        """
        candidates = set(_ex_template_candidates(ex_code))

        try:
            templates = document_template_service.list_document_templates(active_only=True)
        except Exception:
            templates = []

        scored = []
        for template in templates or []:
            values = {
                _normalize_template_lookup(template.get("codigo")),
                _normalize_template_lookup(template.get("mapper_destino")),
                _normalize_template_lookup(template.get("nombre")),
                _normalize_template_lookup(template.get("nombre_oficial")),
            }
            categoria = _normalize_template_lookup(template.get("categoria"))
            template_type = str(template.get("template_type") or "").strip().lower()
            if template_type and template_type not in ("pdf", "fillable_pdf", "ex"):
                continue

            score = -1
            for index, candidate in enumerate(_ex_template_candidates(ex_code)):
                if candidate in values:
                    score = 100 - index
                    break
                if any(candidate in value for value in values if value):
                    score = max(score, 70 - index)

            if categoria == "EX" and score >= 0:
                score += 10

            if score >= 0:
                scored.append((score, template))

        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return scored[0][1]

        # Fallbacks directos por servicios existentes.
        for candidate in _ex_template_candidates(ex_code):
            try:
                template = document_template_service.get_document_template_by_mapper_destino(candidate, active_only=True)
                if template:
                    return template
            except Exception:
                pass
            try:
                template = document_template_service.get_document_template_by_code(candidate, active_only=True)
                if template:
                    return template
            except Exception:
                pass

        return None

    def _compatible_mapper_codes_for_current_expedient():
        """Códigos de mapper compatibles con el tipo/subtipo actual.

        document_templates no guarda tipo_expediente_id ni subtipo_expediente_id.
        La asignación por trámite vive en form_mapper_templates, y la plantilla
        documental se conecta por mapper_destino/codigo. Por eso el menú de tres
        puntos debe cruzar ambas tablas.
        """
        tipo_id = _selected_tipo_id()
        subtipo_id = _selected_subtipo_id()
        codes = []

        try:
            mapper_templates = form_mapper_admin_service.list_mapper_templates(active_only=True)
        except Exception:
            mapper_templates = []

        for mapper in mapper_templates or []:
            code = _normalize_template_lookup(mapper.get("codigo"))
            if not code:
                continue

            mapper_tipo_id = mapper.get("tipo_expediente_id")
            mapper_subtipo_id = mapper.get("subtipo_expediente_id")

            try:
                mapper_tipo_id = int(mapper_tipo_id) if mapper_tipo_id not in (None, "", "None") else None
            except Exception:
                mapper_tipo_id = None
            try:
                mapper_subtipo_id = int(mapper_subtipo_id) if mapper_subtipo_id not in (None, "", "None") else None
            except Exception:
                mapper_subtipo_id = None

            # 1) Mapper específico del subtipo actual.
            if tipo_id and subtipo_id and mapper_tipo_id == int(tipo_id) and mapper_subtipo_id == int(subtipo_id):
                codes.append(code)
                continue

            # 2) Mapper específico del tipo, sin subtipo.
            if tipo_id and mapper_tipo_id == int(tipo_id) and mapper_subtipo_id is None:
                codes.append(code)
                continue

            # 3) Mapper general sin tipo/subtipo: aquí entran plantillas como
            # DESIGNACIÓN DE REPRESENTANTE si se han configurado como generales.
            if mapper_tipo_id is None and mapper_subtipo_id is None:
                codes.append(code)
                continue

        # Refuerzo para EX01 familiar cuando la presentación tiene reglas Mercurio.
        ex_code = _resolve_ex_template_code(
            tipo_id,
            subtipo_id,
            _selected_option_label(tipo_expediente.get_value()),
            _selected_subtipo_label(),
        )
        codes.extend(_ex_template_candidates(ex_code))

        return list(dict.fromkeys(code for code in codes if code))

    def _list_ex_document_templates_for_menu():
        """Devuelve plantillas PDF compatibles para el menú contextual.

        Criterio:
        - plantilla cuyo mapper_destino/codigo coincida con mapper específico del subtipo;
        - plantilla cuyo mapper sea del tipo sin subtipo;
        - plantilla general sin tipo/subtipo, como Designación de representante.
        """
        try:
            templates = document_template_service.list_document_templates(active_only=True)
        except Exception:
            templates = []

        compatible_codes = set(_compatible_mapper_codes_for_current_expedient())
        result = []

        for template in templates or []:
            categoria = _normalize_template_lookup(template.get("categoria"))
            template_type = str(template.get("template_type") or "").strip().lower()
            codigo = _normalize_template_lookup(template.get("codigo"))
            mapper = _normalize_template_lookup(template.get("mapper_destino"))
            nombre = _normalize_template_lookup(template.get("nombre"))
            nombre_oficial = _normalize_template_lookup(template.get("nombre_oficial"))

            is_pdf = template_type in ("pdf", "fillable_pdf", "ex", "")
            if not is_pdf:
                continue

            values = {codigo, mapper, nombre, nombre_oficial}
            values = {v for v in values if v}

            # EX asignado al subtipo/tipo o formulario general compatible.
            if compatible_codes and values.intersection(compatible_codes):
                result.append(template)
                continue

            # Fallback explícito para designación/representante general si no hay
            # mapper enlazado pero sí se nombró claramente la plantilla.
            joined = " ".join(values)
            if "DESIGNACION" in joined or "DESIGNACIÓN" in joined or "REPRESENTANTE" in joined:
                result.append(template)
                continue

            # Fallback conservador para EX/PDF con categoria EX cuando coincide por candidato.
            if categoria == "EX" and any(candidate in joined for candidate in compatible_codes):
                result.append(template)

        def sort_key(item):
            code = _normalize_template_lookup(item.get("codigo") or item.get("mapper_destino") or item.get("nombre"))
            if "EX01_FAMILIAR" in code:
                return (0, code)
            if "EX01" in code:
                return (1, code)
            if "DESIGN" in code or "REPRESENTANTE" in code:
                return (2, code)
            return (3, code)

        # Deduplicamos por id por si entra por varios criterios.
        deduped = []
        seen = set()
        for item in sorted(result, key=sort_key):
            item_id = item.get("id")
            if item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(item)
        return deduped

    def _set_specific_generation_success(expediente_id, title, path="", extra=""):
        if not expediente_id:
            return
        state.setdefault("specific_generation_result", {})[int(expediente_id)] = {
            "status": "ok",
            "title": title,
            "path": path or "",
            "extra": extra or "",
            "at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }

    def _specific_generation_status_card(expediente_id):
        result = state.setdefault("specific_generation_result", {}).get(int(expediente_id)) if expediente_id else None
        if not result:
            return ft.Container(visible=False)

        return ft.Container(
            bgcolor="#ECFDF3",
            border=ft.border.all(1, "#ABEFC6"),
            border_radius=12,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color="#027A48", size=20),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(result.get("title") or "Formulario generado", size=13, weight=ft.FontWeight.BOLD, color="#027A48"),
                            ft.Text(result.get("path") or result.get("extra") or "", size=11, color=Q_PRIMARY_DARK, selectable=True),
                            ft.Text(f"Realizado: {result.get('at') or '-'}", size=10, color=Q_MUTED),
                        ],
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _generate_ex_from_template(template, expediente_id):
        if not template:
            raise ValueError("No se ha seleccionado una plantilla EX")

        generated = pdf_fill_service.fill_pdf_from_template(
            template.get("id"),
            expediente_id=int(expediente_id),
            auto_build_snapshot=True,
            flatten=False,
        )
        output = generated.get("output") or {}
        pdf_info = generated.get("pdf") or {}
        pdf_path = output.get("pdf_path") or pdf_info.get("pdf_path") or ""
        json_path = output.get("json_path") or output.get("payload_path") or ""
        return generated, pdf_path, json_path

    def generate_specific_ex_template(template, e=None, return_section=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de generar formularios")
            return
        try:
            if formulario_id:
                values = _current_specific_values()
                if state.get("specific_view_mode") in ("EX01_FAMILIAR", "EX01_TITULAR", "EX02") and hasattr(dynamic_form_service, "save_datos_especificos_patch"):
                    dynamic_form_service.save_datos_especificos_patch(expediente_id, formulario_id, values)
                else:
                    dynamic_form_service.save_datos_especificos(expediente_id, formulario_id, values)

            generated, pdf_path, json_path = _generate_ex_from_template(template, expediente_id)
            label = template.get("nombre") or template.get("codigo") or "Formulario"
            title = f"{label} realizado"
            _set_specific_generation_success(expediente_id, title, pdf_path or json_path)
            clear_form_message()
            set_message(success_alert(title + (f"\nArchivo: {pdf_path or json_path}" if (pdf_path or json_path) else "")))
            state["dialog_section"] = return_section or state.get("dialog_section") or "datos_especificos"
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def _forms_popup_menu():
        templates = _list_ex_document_templates_for_menu()
        items = []
        for template in templates[:12]:
            label = template.get("nombre") or template.get("codigo") or template.get("mapper_destino") or "Formulario"
            items.append(
                ft.PopupMenuItem(
                    content=ft.Text(label),
                    on_click=lambda e, t=template: generate_specific_ex_template(t, e),
                )
            )

        if not items:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Text("No hay plantillas EX activas"),
                    disabled=True,
                )
            )

        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Generar otros formularios",
            items=items,
        )

    def _write_ex_payload_fallback(expediente_id, ex_code):
        """
        Export mínimo siempre disponible para que el botón Genere EX deje rastro
        en exports/ex_forms aunque todavía no exista plantilla PDF activa.
        """
        try:
            preview = mapper_preview_service.preview_destination_for_expedient(
                expediente_id,
                "EX",
                auto_build_snapshot=True,
            )
        except Exception as exc:
            snapshot_result = snapshot_service.save_snapshot(expediente_id, created_by="EX_FALLBACK_EXPORT")
            preview = {
                "mode": "snapshot_fallback",
                "warning": str(exc),
                "expediente_id": int(expediente_id),
                "ex_code": ex_code,
                "snapshot": snapshot_result.get("snapshot") or {},
            }

        expediente_info = preview.get("expediente") or (preview.get("snapshot") or {}).get("expediente") or {}
        numero = expediente_info.get("numero_expediente") or f"EXPEDIENTE_{expediente_id}"
        export_dir = Path(__file__).resolve().parents[2] / "exports" / "ex_forms" / _safe_export_name(numero)
        export_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_dir / f"{_safe_export_name(ex_code)}_{timestamp}_payload.json"
        path.write_text(json.dumps(preview, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {
            "mode": preview.get("mode") or "payload_json",
            "path": str(path),
            "preview": preview,
        }

    def generate_referenced_ex_form(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de generar el EX")
            return

        tipo_id = _selected_tipo_id()
        subtipo_id = _selected_subtipo_id()
        tipo_label = _selected_option_label(tipo_expediente.get_value())
        subtipo_label = _selected_subtipo_label()
        ex_code = _resolve_ex_template_code(tipo_id, subtipo_id, tipo_label, subtipo_label)

        try:
            if formulario_id:
                values = _current_specific_values()
                if state.get("specific_view_mode") in ("EX01_FAMILIAR", "EX01_TITULAR", "EX02") and hasattr(dynamic_form_service, "save_datos_especificos_patch"):
                    dynamic_form_service.save_datos_especificos_patch(expediente_id, formulario_id, values)
                else:
                    dynamic_form_service.save_datos_especificos(expediente_id, formulario_id, values)

            # Primero intentamos generar el PDF oficial si existe una plantilla EX activa.
            template = _find_ex_document_template(ex_code)

            if template:
                generated, pdf_path, json_path = _generate_ex_from_template(template, expediente_id)
                label = template.get("nombre") or template.get("codigo") or ex_code
                title = f"{label} realizado"
                _set_specific_generation_success(expediente_id, title, pdf_path or json_path)
                clear_form_message()
                set_message(success_alert(
                    title
                    + (f"\nPDF: {pdf_path}" if pdf_path else "")
                    + (f"\nPayload: {json_path}" if json_path else "")
                ))
            else:
                # Fallback útil: exporta payload EX a exports/ex_forms para que haya artefacto revisable.
                fallback = _write_ex_payload_fallback(int(expediente_id), ex_code)
                title = f"{ex_code} payload realizado"
                _set_specific_generation_success(expediente_id, title, fallback.get("path"))
                clear_form_message()
                set_message(success_alert(
                    f"No hay plantilla PDF activa para {ex_code}. Se ha exportado el payload EX para revisión."
                    f"\nArchivo: {fallback.get('path')}"
                ))

            state["dialog_section"] = return_section or state.get("dialog_section") or "datos_especificos"
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def _specific_mapper_codigo(tipo_id, subtipo_id, tipo_label="", subtipo_label=""):
        try:
            reglas = presentation_config_service.get_presentacion_reglas(tipo_id, subtipo_id=subtipo_id) if tipo_id else {}
        except Exception:
            reglas = {}

        mapper = str((reglas or {}).get("mapper_codigo") or "").strip().upper()
        if mapper:
            return mapper

        joined = _norm(f"{tipo_label} {subtipo_label}")
        if "NO LUCRATIVA" in joined and "FAMILIAR" in joined:
            return "MERCURIO_EX01_FAMILIAR"
        if "EX01" in joined and "FAMILIAR" in joined:
            return "MERCURIO_EX01_FAMILIAR"
        if "NO LUCRATIVA" in joined or "EX01" in joined:
            return "MERCURIO_EX01"
        if "EX02" in joined or "REAGRUPACION" in joined or "REAGRUPACIÓN" in joined:
            return "MERCURIO_EX02"
        return ""

    def _specific_data_stepper(steps, current_step):
        controls = []
        for index, (title, _subtitle) in enumerate(steps):
            active = index == current_step
            completed = index < current_step
            controls.append(
                ft.Container(
                    bgcolor=Q_PRIMARY if active else ("#EAF3FF" if completed else "#FFFFFF"),
                    border=ft.border.all(1, Q_PRIMARY if active else "#B9D7FF" if completed else Q_BORDER),
                    border_radius=12,
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    content=ft.Row(
                        tight=True,
                        spacing=6,
                        controls=[
                            ft.Container(
                                width=22,
                                height=22,
                                border_radius=11,
                                bgcolor="#FFFFFF" if active else ("#D1FADF" if completed else "#F8FAFC"),
                                alignment=ft.alignment.Alignment(0, 0),
                                content=ft.Text(
                                    "✓" if completed else str(index + 1),
                                    size=11,
                                    weight=ft.FontWeight.BOLD,
                                    color="#027A48" if completed else Q_PRIMARY_DARK,
                                ),
                            ),
                            ft.Text(
                                title,
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color="#FFFFFF" if active else Q_PRIMARY_DARK,
                            ),
                        ],
                    ),
                    ink=True,
                    on_click=lambda e, i=index: _set_specific_data_step(i),
                )
            )

        return ft.Row(controls=controls, spacing=8, wrap=True)

    def _set_specific_data_step(step):
        steps_count = 5
        try:
            step = max(0, min(int(step), steps_count - 1))
        except Exception:
            step = 0
        state["specific_data_step"] = step
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if expediente_id:
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

    def _save_specific_values_or_raise():
        """Guarda los datos específicos visibles sin cambiar de pantalla.

        A diferencia de _autosave_specific_values_silent(), esta función deja
        subir el error para impedir avanzar de paso si el guardado falla.
        """
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        formulario_id = state.get("specific_formulario_id")
        if not expediente_id:
            raise ValueError("Guarda primero el expediente antes de guardar datos específicos")
        if not formulario_id:
            raise ValueError("No hay formulario específico configurado para este expediente")

        values = _current_specific_values()

        if state.get("specific_view_mode") in ("EX01_FAMILIAR", "EX01_TITULAR", "EX02") and hasattr(dynamic_form_service, "save_datos_especificos_patch"):
            dynamic_form_service.save_datos_especificos_patch(
                expediente_id,
                formulario_id,
                values,
            )
        else:
            dynamic_form_service.save_datos_especificos(
                expediente_id,
                formulario_id,
                values,
            )

    def _save_specific_and_go_step(next_step):
        try:
            _save_specific_values_or_raise()
            clear_form_message()
            _set_specific_data_step(next_step)
        except Exception as exc:
            show_form_error(str(exc))

    def _specific_field_value(saved_values, codigo, default=""):
        value = saved_values.get(codigo)
        if value in (None, ""):
            return default
        return value

    def _register_hidden_specific_control(codigo, value=""):
        control = text_input(codigo, str(value or ""), width=10)
        control.visible = False
        state.setdefault("specific_field_controls", {})[codigo] = control
        return control

    def _specific_info_row(label, value):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            padding=10,
            content=ft.Column(
                spacing=2,
                controls=[
                    ft.Text(label, size=11, color=Q_MUTED),
                    ft.Text(str(value or "-"), size=13, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                ],
            ),
        )

    def _specific_card(title, subtitle, controls, icon=ft.Icons.ARTICLE):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=14,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                content=ft.Icon(icon, size=20, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=20,
                                width=40,
                                height=40,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                spacing=2,
                                expand=True,
                                controls=[
                                    ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(subtitle, size=12, color=Q_MUTED),
                                ],
                            ),
                        ],
                    ),
                    *controls,
                ],
            ),
        )

    def _specific_value_text(codigo, label, saved_values, width=320, multiline=False):
        value = _specific_field_value(saved_values, codigo, "")
        if multiline:
            control = multiline_input(label, value, width=width, height=90)
        else:
            control = text_input(label, value, width=width)
        state.setdefault("specific_field_controls", {})[codigo] = control
        return control

    def _specific_value_select(codigo, label, options, saved_values, width=260, default=None):
        value = _specific_field_value(saved_values, codigo, default if default is not None else (options[0] if options else ""))
        control = select_input(label, options, value=value if value in options else (default if default is not None else (options[0] if options else "")), width=width)
        state.setdefault("specific_field_controls", {})[codigo] = control
        return control

    def refresh_specific_data_screen(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if expediente_id:
            # Relee la ficha base del expediente y limpia controles cacheados.
            # Así, si se actualiza la ficha del cliente/expediente desde otra
            # pantalla, Datos específicos muestra los datos vivos al refrescar.
            try:
                latest = expedient_service.get_expediente(expediente_id)
                if latest:
                    load_form(latest)
            except Exception:
                pass
            state["specific_refresh_counter"] = int(state.get("specific_refresh_counter") or 0) + 1
            state["specific_field_controls"] = {}
            state["specific_live_values"] = {}
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

    def _remember_contact_specific_values(prefix, selected_value, details):
        selected_id_value = _option_id(selected_value)
        _set_specific_control_value(prefix, selected_value)
        _set_specific_control_value(f"{prefix}_contacto_id", str(selected_id_value or ""))
        _set_specific_control_value(f"{prefix}_id", str(selected_id_value or ""))

        detail_map = {
            "tipo_contacto": "tipo_contacto",
            "parentesco": "parentesco",
            "nombre": "nombre",
            "primer_apellido": "primer_apellido",
            "segundo_apellido": "segundo_apellido",
            "nombre_completo": "nombre_completo",
            "documento": "documento",
            "nie": "nie",
            "dni": "dni",
            "pasaporte": "pasaporte",
            "nacionalidad": "nacionalidad",
            "fecha_nacimiento": "fecha_nacimiento",
            "sexo": "sexo",
            "telefono": "telefono",
            "email": "email",
            "estado_cliente": "estado_cliente",
            "domicilio_espana": "domicilio_espana",
            "tipo_via": "tipo_via",
            "nombre_via": "nombre_via",
            "numero": "numero",
            "piso": "piso",
            "puerta": "puerta",
            "escalera": "escalera",
            "localidad": "localidad",
            "provincia": "provincia",
            "codigo_postal": "codigo_postal",
            "localidad_nacimiento": "localidad_nacimiento",
            "pais_nacimiento": "pais_nacimiento",
            "nombre_padre": "nombre_padre",
            "nombre_madre": "nombre_madre",
            "estado_civil": "estado_civil",
            "sexo": "sexo",
            "cliente_referenciado_id": "cliente_referenciado_id",
        }

        for target, source in detail_map.items():
            _set_specific_control_value(f"{prefix}_{target}", _detail_value(details, source) if source not in details else details.get(source))

        via_completa = " ".join(
            str(details.get(key) or "").strip()
            for key in ("tipo_via", "nombre_via")
            if str(details.get(key) or "").strip()
        ).strip() or str(details.get("domicilio_espana") or "").strip()
        _set_specific_control_value(f"{prefix}_via_completa", via_completa)

    def _refresh_saved_values_from_live_contact(saved_values, prefix="representante_legal"):
        """Mezcla datos vivos del contacto seleccionado en datos específicos.

        Evita que la pantalla EX01 familiar enseñe datos antiguos hasta cambiar
        de pestaña o volver a seleccionar el autocomplete.
        """
        values = dict(saved_values or {})
        contacto_id = (
            values.get(f"{prefix}_contacto_id")
            or values.get(f"{prefix}_id")
            or _option_id(values.get(prefix))
        )
        if not contacto_id:
            return values

        details = _fetch_cliente_contact_details(contacto_id) or {}
        if not details:
            return values

        values[prefix] = values.get(prefix) or f"{contacto_id} - {details.get('nombre_completo') or details.get('nombre') or ''}".strip()

        detail_map = {
            "contacto_id": "id",
            "id": "id",
            "tipo_contacto": "tipo_contacto",
            "parentesco": "parentesco",
            "nombre": "nombre",
            "primer_apellido": "primer_apellido",
            "segundo_apellido": "segundo_apellido",
            "nombre_completo": "nombre_completo",
            "documento": "documento",
            "nie": "nie",
            "dni": "dni",
            "pasaporte": "pasaporte",
            "nacionalidad": "nacionalidad",
            "fecha_nacimiento": "fecha_nacimiento",
            "sexo": "sexo",
            "telefono": "telefono",
            "email": "email",
            "estado_cliente": "estado_cliente",
            "domicilio_espana": "domicilio_espana",
            "tipo_via": "tipo_via",
            "nombre_via": "nombre_via",
            "numero": "numero",
            "piso": "piso",
            "puerta": "puerta",
            "escalera": "escalera",
            "localidad": "localidad",
            "provincia": "provincia",
            "codigo_postal": "codigo_postal",
            "localidad_nacimiento": "localidad_nacimiento",
            "pais_nacimiento": "pais_nacimiento",
            "nombre_padre": "nombre_padre",
            "nombre_madre": "nombre_madre",
            "estado_civil": "estado_civil",
            "sexo": "sexo",
            "cliente_referenciado_id": "cliente_referenciado_id",
        }

        for target, source in detail_map.items():
            key = f"{prefix}_{target}"
            if source == "id":
                values[key] = str(contacto_id or "")
            else:
                values[key] = str(details.get(source) or "")

        via_completa = " ".join(
            str(details.get(key) or "").strip()
            for key in ("tipo_via", "nombre_via")
            if str(details.get(key) or "").strip()
        ).strip() or str(details.get("domicilio_espana") or "").strip()
        values[f"{prefix}_via_completa"] = via_completa

        return values

    def _build_ex01_familiar_specific_content(expediente_id, formulario, saved_values, tipo_label, subtipo_label):
        state["specific_view_mode"] = "EX01_FAMILIAR"
        state["specific_formulario_id"] = formulario.get("id") if formulario else None
        saved_values = _refresh_saved_values_from_live_contact(saved_values, "representante_legal")
        saved_values = _refresh_saved_values_from_live_contact(saved_values, "solicitante_representante_legal")

        steps = [
            ("Solicitante", "Cliente del expediente"),
            ("Familiar titular", "Medios económicos"),
            ("Representación", "Presentador profesional"),
            ("Checks", "Datos del trámite"),
            ("Revisión", "Snapshot y EX"),
        ]
        current_step = max(0, min(int(state.get("specific_data_step") or 0), len(steps) - 1))

        cliente_id = _option_id(cliente.get_value())
        cliente_details = _fetch_cliente_details(cliente_id) if cliente_id else {}
        presentador = {}
        try:
            presentador = config_service.get_representante_config() or {}
        except Exception:
            presentador = {}

        # El bloque familiar/titular usa las claves actuales para no romper snapshot ni Mercurio.
        familiar_value = _specific_field_value(saved_values, "representante_legal", "")
        familiar_options = _fetch_cliente_contact_options(cliente_id, only_employers=False)

        hidden_codes = [
            "representante_legal_contacto_id", "representante_legal_id",
            "representante_legal_tipo_contacto", "representante_legal_parentesco",
            "representante_legal_nombre", "representante_legal_primer_apellido",
            "representante_legal_segundo_apellido", "representante_legal_nombre_completo",
            "representante_legal_documento", "representante_legal_nie",
            "representante_legal_dni", "representante_legal_pasaporte",
            "representante_legal_nacionalidad", "representante_legal_fecha_nacimiento",
            "representante_legal_telefono", "representante_legal_email",
            "representante_legal_estado_cliente", "representante_legal_domicilio_espana",
            "representante_legal_tipo_via", "representante_legal_nombre_via",
            "representante_legal_numero", "representante_legal_piso",
            "representante_legal_puerta", "representante_legal_escalera",
            "representante_legal_localidad", "representante_legal_provincia",
            "representante_legal_codigo_postal", "representante_legal_localidad_nacimiento",
            "representante_legal_pais_nacimiento", "representante_legal_nombre_padre",
            "representante_legal_nombre_madre", "representante_legal_estado_civil",
            "representante_legal_sexo", "representante_legal_cliente_referenciado_id",

            # Representante legal real del solicitante.
            # Se selecciona entre los contactos del cliente del expediente,
            # no desde todos los contactos globales del CRM.
            "solicitante_representante_legal_contacto_id", "solicitante_representante_legal_id",
            "solicitante_representante_legal_tipo_contacto", "solicitante_representante_legal_parentesco",
            "solicitante_representante_legal_nombre", "solicitante_representante_legal_primer_apellido",
            "solicitante_representante_legal_segundo_apellido", "solicitante_representante_legal_nombre_completo",
            "solicitante_representante_legal_documento", "solicitante_representante_legal_nie",
            "solicitante_representante_legal_dni", "solicitante_representante_legal_pasaporte",
            "solicitante_representante_legal_nacionalidad", "solicitante_representante_legal_fecha_nacimiento",
            "solicitante_representante_legal_telefono", "solicitante_representante_legal_email",
            "solicitante_representante_legal_estado_cliente", "solicitante_representante_legal_domicilio_espana",
            "solicitante_representante_legal_tipo_via", "solicitante_representante_legal_nombre_via",
            "solicitante_representante_legal_numero", "solicitante_representante_legal_piso",
            "solicitante_representante_legal_puerta", "solicitante_representante_legal_escalera",
            "solicitante_representante_legal_localidad", "solicitante_representante_legal_provincia",
            "solicitante_representante_legal_codigo_postal", "solicitante_representante_legal_localidad_nacimiento",
            "solicitante_representante_legal_pais_nacimiento", "solicitante_representante_legal_nombre_padre",
            "solicitante_representante_legal_nombre_madre", "solicitante_representante_legal_estado_civil",
            "solicitante_representante_legal_sexo", "solicitante_representante_legal_cliente_referenciado_id",
        ]
        hidden_controls = [_register_hidden_specific_control(code, saved_values.get(code, "")) for code in hidden_codes]

        def apply_familiar_contact(selected):
            selected_id_value = _option_id(selected)
            details = _fetch_cliente_contact_details(selected_id_value) if selected_id_value else {}
            _remember_contact_specific_values("representante_legal", selected or "", details or {})
            _autosave_specific_values_silent()
            # Reconstruye la sección para que las tarjetas resumen reflejen el
            # contacto vivo inmediatamente, sin cambiar de pestaña.
            if expediente_id:
                expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        familiar_autocomplete = AppAutocomplete(
            page=page,
            label="Familiar / titular de medios económicos",
            options=familiar_options,
            value=familiar_value,
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_familiar_contact,
        )
        state.setdefault("specific_field_controls", {})["representante_legal"] = familiar_autocomplete

        solicitante_rep_value = _specific_field_value(saved_values, "solicitante_representante_legal", "")
        solicitante_rep_options = _fetch_cliente_contact_options(cliente_id, only_employers=False)

        def apply_solicitante_representante_contact(selected):
            selected_id_value = _option_id(selected)
            details = _fetch_cliente_contact_details(selected_id_value) if selected_id_value else {}
            _remember_contact_specific_values("solicitante_representante_legal", selected or "", details or {})
            _autosave_specific_values_silent()
            # Reconstruye la sección para que las tarjetas resumen reflejen
            # el representante legal inmediatamente, sin cambiar de pestaña.
            if expediente_id:
                expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        solicitante_rep_autocomplete = AppAutocomplete(
            page=page,
            label="Representante legal del solicitante",
            options=solicitante_rep_options,
            value=solicitante_rep_value,
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_solicitante_representante_contact,
        )
        state.setdefault("specific_field_controls", {})["solicitante_representante_legal"] = solicitante_rep_autocomplete

        propietario = _specific_value_select(
            "propietario_medios_economicos",
            "Origen de medios económicos",
            ["CLIENTE", "FAMILIAR", "OTRO"],
            saved_values,
            width=300,
            default="FAMILIAR",
        )
        hijos_menores = _specific_value_select(
            "hijos_menores_edad_escolarizacion",
            "Hijos menores en edad escolar",
            ["Sí", "No"],
            saved_values,
            width=300,
            default="No",
        )
        parentesco_manual = _specific_value_text(
            "parentesco_mercurio_manual",
            "Parentesco jurídico manual, si procede",
            saved_values,
            width=380,
        )
        observaciones_especificas = _specific_value_text(
            "observaciones_ex01_familiar",
            "Observaciones EX01 familiar",
            saved_values,
            width=720,
            multiline=True,
        )

        hidden_bucket = ft.Column(controls=hidden_controls, visible=False)

        def _name_from_details(details):
            return details.get("nombre_completo") or " ".join(
                str(details.get(k) or "").strip()
                for k in ("nombre", "primer_apellido", "segundo_apellido")
                if str(details.get(k) or "").strip()
            ).strip()

        def _presentador_nombre(rep):
            return rep.get("representante_nombre_razon_social") or " ".join(
                str(rep.get(k) or "").strip()
                for k in ("representante_nombre", "representante_apellido1", "representante_apellido2")
                if str(rep.get(k) or "").strip()
            ).strip()

        def _solicitante_rows():
            return [
                _specific_info_row("Nombre", _name_from_details(cliente_details)),
                _specific_info_row("Documento", _row_document(cliente_details)),
                _specific_info_row("Nacionalidad", cliente_details.get("nacionalidad")),
                _specific_info_row("Nacimiento", cliente_details.get("fecha_nacimiento")),
                _specific_info_row("Estado civil", cliente_details.get("estado_civil")),
                _specific_info_row("Domicilio", cliente_details.get("domicilio_espana")),
                _specific_info_row("Provincia", cliente_details.get("provincia")),
                _specific_info_row("Localidad", cliente_details.get("localidad")),
                _specific_info_row("Teléfono", cliente_details.get("telefono")),
                _specific_info_row("Email", cliente_details.get("email")),
            ]

        def current_step_controls():
            values = _current_specific_values()
            familiar_nombre = values.get("representante_legal_nombre_completo") or saved_values.get("representante_legal_nombre_completo") or "-"
            familiar_doc = values.get("representante_legal_documento") or saved_values.get("representante_legal_documento") or "-"
            familiar_parentesco = values.get("representante_legal_parentesco") or saved_values.get("representante_legal_parentesco") or "-"
            familiar_domicilio = values.get("representante_legal_domicilio_espana") or saved_values.get("representante_legal_domicilio_espana") or "-"
            familiar_localidad = values.get("representante_legal_localidad") or saved_values.get("representante_legal_localidad") or "-"
            familiar_provincia = values.get("representante_legal_provincia") or saved_values.get("representante_legal_provincia") or "-"
            solicitante_rep_nombre = values.get("solicitante_representante_legal_nombre_completo") or saved_values.get("solicitante_representante_legal_nombre_completo") or "-"
            solicitante_rep_doc = values.get("solicitante_representante_legal_documento") or saved_values.get("solicitante_representante_legal_documento") or "-"
            solicitante_rep_parentesco = values.get("solicitante_representante_legal_parentesco") or saved_values.get("solicitante_representante_legal_parentesco") or "-"
            solicitante_rep_telefono = values.get("solicitante_representante_legal_telefono") or saved_values.get("solicitante_representante_legal_telefono") or "-"
            solicitante_rep_email = values.get("solicitante_representante_legal_email") or saved_values.get("solicitante_representante_legal_email") or "-"

            if current_step == 0:
                return [
                    _specific_card(
                        "Solicitante · cliente del expediente",
                        "Datos del cliente que se volcarán en Mercurio y quedarán congelados en el snapshot.",
                        [
                            ft.Row(controls=_solicitante_rows(), spacing=10, wrap=True),
                            ft.Container(
                                bgcolor="#FFFFFF",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=12,
                                padding=12,
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        ft.Text("Representante legal del solicitante", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            "Opcional. Selecciona uno de los contactos vinculados a este cliente.",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        solicitante_rep_autocomplete.control,
                                        ft.Row(
                                            controls=[
                                                _specific_info_row("Nombre", solicitante_rep_nombre),
                                                _specific_info_row("Documento", solicitante_rep_doc),
                                                _specific_info_row("Vínculo / título", solicitante_rep_parentesco),
                                                _specific_info_row("Teléfono", solicitante_rep_telefono),
                                                _specific_info_row("Email", solicitante_rep_email),
                                            ],
                                            spacing=10,
                                            wrap=True,
                                        ),
                                    ],
                                ),
                            ),
                            ft.Text(
                                "Los datos del solicitante vienen de la ficha del cliente. El representante legal se guarda aparte y se vuelca en Mercurio como representante del extranjero/solicitante.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        ft.Icons.PERSON,
                    )
                ]

            if current_step == 1:
                return [
                    _specific_card(
                        "Familiar / titular de medios económicos",
                        "Selecciona el familiar o contacto que alimentará el bloque familiar/titular en Mercurio.",
                        [
                            familiar_autocomplete.control,
                            ft.Row(
                                controls=[
                                    _specific_info_row("Nombre", familiar_nombre),
                                    _specific_info_row("Documento", familiar_doc),
                                    _specific_info_row("Parentesco CRM", familiar_parentesco),
                                    _specific_info_row("Domicilio", familiar_domicilio),
                                    _specific_info_row("Provincia", familiar_provincia),
                                    _specific_info_row("Localidad", familiar_localidad),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Row([propietario, parentesco_manual], wrap=True, spacing=10),
                            ft.Text(
                                "El parentesco jurídico de Mercurio puede decidirlo el abogado si el supuesto no coincide con el parentesco CRM.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        ft.Icons.ACCOUNT_BALANCE,
                    )
                ]

            if current_step == 2:
                return [
                    _specific_card(
                        "Representación / presentador profesional",
                        "Datos del presentador configurado en Settings. En este caso debe ser Ana Belén, no el familiar del solicitante.",
                        [
                            ft.Row(
                                controls=[
                                    _specific_info_row("Presentador", _presentador_nombre(presentador)),
                                    _specific_info_row("Documento", presentador.get("representante_documento")),
                                    _specific_info_row("Tipo documento", presentador.get("representante_tipo_documento")),
                                    _specific_info_row("Provincia", presentador.get("representante_provincia")),
                                    _specific_info_row("Municipio", presentador.get("representante_municipio")),
                                    _specific_info_row("Email", presentador.get("representante_email")),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Text(
                                "Este bloque es informativo: se toma de Configuración y el mapper lo envía a Datos del presentador.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        ft.Icons.GAVEL,
                    )
                ]

            if current_step == 3:
                return [
                    _specific_card(
                        "Checks del trámite",
                        "Campos operativos del expediente. Se guardan en datos específicos y entran en el snapshot.",
                        [
                            ft.Row([hijos_menores], wrap=True, spacing=10),
                            observaciones_especificas,
                        ],
                        ft.Icons.CHECKLIST,
                    )
                ]

            return [
                _specific_card(
                    "Revisión y generación",
                    "Guarda los datos, genera snapshot y después genera el EX/formulario referenciado para revisión.",
                    [
                        ft.Row(
                            controls=[
                                _specific_info_row("Solicitante", _name_from_details(cliente_details)),
                                _specific_info_row("Familiar/titular", familiar_nombre),
                                _specific_info_row("Parentesco CRM", familiar_parentesco),
                                _specific_info_row("Medios", values.get("propietario_medios_economicos") or propietario.value),
                                _specific_info_row("Medios", values.get("propietario_medios_economicos") or "TITULAR"),
                                _specific_info_row("Escolarización", values.get("hijos_menores_edad_escolarizacion") or hijos_menores.value),
                                _specific_info_row("Representante legal", solicitante_rep_nombre),
                                _specific_info_row("Presentador", _presentador_nombre(presentador)),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        _specific_generation_status_card(expediente_id),
                        build_snapshot_status_content(expediente_id),
                        ft.Text(
                            "Usa la barra inferior para guardar, generar snapshot, generar EX01 familiar o elegir otros formularios desde el menú de tres puntos.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    ft.Icons.FACT_CHECK,
                )
            ]

        nav_controls = []
        if current_step > 0:
            nav_controls.append(secondary_button("Anterior", lambda e: _set_specific_data_step(current_step - 1)))
        nav_controls.append(primary_button("Guardar", save_specific_data))
        if current_step < len(steps) - 1:
            nav_controls.append(secondary_button("Siguiente", lambda e: _save_specific_and_go_step(current_step + 1)))
        else:
            nav_controls.extend([
                secondary_button("Generar snapshot", generate_snapshot),
                secondary_button("Generar EX01 familiar", generate_referenced_ex_form),
                _forms_popup_menu(),
            ])

        controls = [
            ft.Container(
                bgcolor="#EAF3FF",
                border=ft.border.all(1, "#B9D7FF"),
                border_radius=16,
                padding=14,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.VIEW_WEEK, size=24, color=Q_PRIMARY),
                            bgcolor="#FFFFFF",
                            border_radius=24,
                            width=48,
                            height=48,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("EX01 familiar · Datos específicos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(f"Tipo/Subtipo: {tipo_label} / {subtipo_label}", size=13, color=Q_MUTED),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        secondary_button("Refrescar datos", refresh_specific_data_screen),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            _specific_data_stepper(steps, current_step),
            hidden_bucket,
            *current_step_controls(),
            ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=14,
                padding=10,
                content=ft.Row(
                    controls=nav_controls + [
                        ft.Text(
                            "Pantalla específica. Guarda en datos específicos y respeta snapshot.",
                            size=12,
                            color=Q_MUTED,
                            expand=True,
                        )
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ]

        return ft.Container(
            width=860,
            height=660,
            bgcolor="#FFFFFF",
            border_radius=0,
            padding=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=controls,
                spacing=10,
                scroll=None,
            ),
        )


    def _build_ex01_titular_specific_content(expediente_id, formulario, saved_values, tipo_label, subtipo_label):
        """Pantalla específica para EX01 renovación titular.

        Reutiliza el mismo contrato de datos específicos que EX01 familiar:
        - guardado patch para campos técnicos;
        - representante legal del solicitante con prefijo solicitante_representante_legal_*;
        - checks del trámite;
        - revisión/snapshot/generación EX.
        """
        state["specific_view_mode"] = "EX01_TITULAR"
        state["specific_formulario_id"] = formulario.get("id") if formulario else None
        saved_values = _refresh_saved_values_from_live_contact(saved_values, "solicitante_representante_legal")

        steps = [
            ("Solicitante", "Cliente del expediente"),
            ("Representación", "Presentador profesional"),
            ("Checks", "Datos del trámite"),
            ("Revisión", "Snapshot y EX"),
        ]
        current_step = max(0, min(int(state.get("specific_data_step") or 0), len(steps) - 1))

        cliente_id = _option_id(cliente.get_value())
        cliente_details = _fetch_cliente_details(cliente_id) if cliente_id else {}
        presentador = {}
        try:
            presentador = config_service.get_representante_config() or {}
        except Exception:
            presentador = {}

        # EX01 renovación titular: el propio solicitante es el titular de los
        # medios económicos. El mapper PDF usa este valor para marcar la
        # casilla correspondiente.
        saved_values["propietario_medios_economicos"] = "TITULAR"

        hidden_codes = [
            "propietario_medios_economicos",

            # Representante legal real del solicitante.
            "solicitante_representante_legal_contacto_id", "solicitante_representante_legal_id",
            "solicitante_representante_legal_tipo_contacto", "solicitante_representante_legal_parentesco",
            "solicitante_representante_legal_nombre", "solicitante_representante_legal_primer_apellido",
            "solicitante_representante_legal_segundo_apellido", "solicitante_representante_legal_nombre_completo",
            "solicitante_representante_legal_documento", "solicitante_representante_legal_nie",
            "solicitante_representante_legal_dni", "solicitante_representante_legal_pasaporte",
            "solicitante_representante_legal_nacionalidad", "solicitante_representante_legal_fecha_nacimiento",
            "solicitante_representante_legal_telefono", "solicitante_representante_legal_email",
            "solicitante_representante_legal_estado_cliente", "solicitante_representante_legal_domicilio_espana",
            "solicitante_representante_legal_tipo_via", "solicitante_representante_legal_nombre_via",
            "solicitante_representante_legal_numero", "solicitante_representante_legal_piso",
            "solicitante_representante_legal_puerta", "solicitante_representante_legal_escalera",
            "solicitante_representante_legal_localidad", "solicitante_representante_legal_provincia",
            "solicitante_representante_legal_codigo_postal", "solicitante_representante_legal_localidad_nacimiento",
            "solicitante_representante_legal_pais_nacimiento", "solicitante_representante_legal_nombre_padre",
            "solicitante_representante_legal_nombre_madre", "solicitante_representante_legal_estado_civil",
            "solicitante_representante_legal_sexo", "solicitante_representante_legal_cliente_referenciado_id",
        ]
        hidden_controls = [_register_hidden_specific_control(code, saved_values.get(code, "")) for code in hidden_codes]

        solicitante_rep_value = _specific_field_value(saved_values, "solicitante_representante_legal", "")
        solicitante_rep_options = _fetch_cliente_contact_options(cliente_id, only_employers=False)

        def apply_solicitante_representante_contact(selected):
            selected_id_value = _option_id(selected)
            details = _fetch_cliente_contact_details(selected_id_value) if selected_id_value else {}
            _remember_contact_specific_values("solicitante_representante_legal", selected or "", details or {})
            _autosave_specific_values_silent()
            if expediente_id:
                expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        solicitante_rep_autocomplete = AppAutocomplete(
            page=page,
            label="Representante legal del solicitante",
            options=solicitante_rep_options,
            value=solicitante_rep_value,
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_solicitante_representante_contact,
        )
        state.setdefault("specific_field_controls", {})["solicitante_representante_legal"] = solicitante_rep_autocomplete

        hijos_menores = _specific_value_select(
            "hijos_menores_edad_escolarizacion",
            "Hijos menores en edad escolar",
            ["Sí", "No"],
            saved_values,
            width=300,
            default="No",
        )
        observaciones_especificas = _specific_value_text(
            "observaciones_ex01_titular",
            "Observaciones EX01 titular",
            saved_values,
            width=720,
            multiline=True,
        )

        hidden_bucket = ft.Column(controls=hidden_controls, visible=False)

        def _name_from_details(details):
            return details.get("nombre_completo") or " ".join(
                str(details.get(k) or "").strip()
                for k in ("nombre", "primer_apellido", "segundo_apellido")
                if str(details.get(k) or "").strip()
            ).strip()

        def _presentador_nombre(rep):
            return rep.get("representante_nombre_razon_social") or " ".join(
                str(rep.get(k) or "").strip()
                for k in ("representante_nombre", "representante_apellido1", "representante_apellido2")
                if str(rep.get(k) or "").strip()
            ).strip()

        def _solicitante_rows():
            return [
                _specific_info_row("Nombre", _name_from_details(cliente_details)),
                _specific_info_row("Documento", _row_document(cliente_details)),
                _specific_info_row("Nacionalidad", cliente_details.get("nacionalidad")),
                _specific_info_row("Nacimiento", cliente_details.get("fecha_nacimiento")),
                _specific_info_row("Estado civil", cliente_details.get("estado_civil")),
                _specific_info_row("Domicilio", cliente_details.get("domicilio_espana")),
                _specific_info_row("Provincia", cliente_details.get("provincia")),
                _specific_info_row("Localidad", cliente_details.get("localidad")),
                _specific_info_row("Teléfono", cliente_details.get("telefono")),
                _specific_info_row("Email", cliente_details.get("email")),
            ]

        def current_step_controls():
            values = _current_specific_values()
            solicitante_rep_nombre = values.get("solicitante_representante_legal_nombre_completo") or saved_values.get("solicitante_representante_legal_nombre_completo") or "-"
            solicitante_rep_doc = values.get("solicitante_representante_legal_documento") or saved_values.get("solicitante_representante_legal_documento") or "-"
            solicitante_rep_parentesco = values.get("solicitante_representante_legal_parentesco") or saved_values.get("solicitante_representante_legal_parentesco") or "-"
            solicitante_rep_telefono = values.get("solicitante_representante_legal_telefono") or saved_values.get("solicitante_representante_legal_telefono") or "-"
            solicitante_rep_email = values.get("solicitante_representante_legal_email") or saved_values.get("solicitante_representante_legal_email") or "-"

            if current_step == 0:
                return [
                    _specific_card(
                        "Solicitante · titular de la renovación",
                        "Datos del cliente que se volcarán en Mercurio y quedarán congelados en el snapshot.",
                        [
                            ft.Row(controls=_solicitante_rows(), spacing=10, wrap=True),
                            ft.Container(
                                bgcolor="#FFFFFF",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=12,
                                padding=12,
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        ft.Text("Representante legal del solicitante", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            "Opcional. Selecciona uno de los contactos vinculados a este cliente.",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        solicitante_rep_autocomplete.control,
                                        ft.Row(
                                            controls=[
                                                _specific_info_row("Nombre", solicitante_rep_nombre),
                                                _specific_info_row("Documento", solicitante_rep_doc),
                                                _specific_info_row("Vínculo / título", solicitante_rep_parentesco),
                                                _specific_info_row("Teléfono", solicitante_rep_telefono),
                                                _specific_info_row("Email", solicitante_rep_email),
                                            ],
                                            spacing=10,
                                            wrap=True,
                                        ),
                                    ],
                                ),
                            ),
                            ft.Text(
                                "No hay bloque de familiar/titular de medios en EX01 titular. Si existe representante legal, se vuelca en Datos del extranjero/a.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        ft.Icons.PERSON,
                    )
                ]

            if current_step == 1:
                return [
                    _specific_card(
                        "Representación / presentador profesional",
                        "Datos del presentador configurado en Settings.",
                        [
                            ft.Row(
                                controls=[
                                    _specific_info_row("Presentador", _presentador_nombre(presentador)),
                                    _specific_info_row("Documento", presentador.get("representante_documento")),
                                    _specific_info_row("Tipo documento", presentador.get("representante_tipo_documento")),
                                    _specific_info_row("Provincia", presentador.get("representante_provincia")),
                                    _specific_info_row("Municipio", presentador.get("representante_municipio")),
                                    _specific_info_row("Email", presentador.get("representante_email")),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Text(
                                "Este bloque es informativo: se toma de Configuración y el mapper lo envía a Datos del presentador.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        ft.Icons.GAVEL,
                    )
                ]

            if current_step == 2:
                return [
                    _specific_card(
                        "Checks del trámite",
                        "Campos operativos del expediente. Se guardan en datos específicos y entran en el snapshot.",
                        [
                            ft.Row([hijos_menores], wrap=True, spacing=10),
                            observaciones_especificas,
                        ],
                        ft.Icons.CHECKLIST,
                    )
                ]

            return [
                _specific_card(
                    "Revisión y generación",
                    "Guarda los datos, genera snapshot y después genera el EX01 para revisión.",
                    [
                        ft.Row(
                            controls=[
                                _specific_info_row("Solicitante", _name_from_details(cliente_details)),
                                _specific_info_row("Escolarización", values.get("hijos_menores_edad_escolarizacion") or hijos_menores.value),
                                _specific_info_row("Representante legal", solicitante_rep_nombre),
                                _specific_info_row("Presentador", _presentador_nombre(presentador)),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        _specific_generation_status_card(expediente_id),
                        build_snapshot_status_content(expediente_id),
                        ft.Text(
                            "Usa la barra inferior para guardar, generar snapshot, generar EX01 titular o elegir otros formularios desde el menú de tres puntos.",
                            size=12,
                            color=Q_MUTED,
                        ),
                    ],
                    ft.Icons.FACT_CHECK,
                )
            ]

        nav_controls = []
        if current_step > 0:
            nav_controls.append(secondary_button("Anterior", lambda e: _set_specific_data_step(current_step - 1)))
        nav_controls.append(primary_button("Guardar", save_specific_data))
        if current_step < len(steps) - 1:
            nav_controls.append(secondary_button("Siguiente", lambda e: _save_specific_and_go_step(current_step + 1)))
        else:
            nav_controls.extend([
                secondary_button("Generar snapshot", generate_snapshot),
                secondary_button("Generar EX01 titular", generate_referenced_ex_form),
                _forms_popup_menu(),
            ])

        controls = [
            ft.Container(
                bgcolor="#EAF3FF",
                border=ft.border.all(1, "#B9D7FF"),
                border_radius=16,
                padding=14,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.VIEW_WEEK, size=24, color=Q_PRIMARY),
                            bgcolor="#FFFFFF",
                            border_radius=24,
                            width=48,
                            height=48,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("EX01 titular · Datos específicos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(f"Tipo/Subtipo: {tipo_label} / {subtipo_label}", size=13, color=Q_MUTED),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        secondary_button("Refrescar datos", refresh_specific_data_screen),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            _specific_data_stepper(steps, current_step),
            hidden_bucket,
            *current_step_controls(),
            ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=14,
                padding=10,
                content=ft.Row(
                    controls=nav_controls + [
                        ft.Text(
                            "Pantalla específica. Guarda en datos específicos y respeta snapshot.",
                            size=12,
                            color=Q_MUTED,
                            expand=True,
                        )
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ]

        return ft.Container(
            width=860,
            height=660,
            bgcolor="#FFFFFF",
            border_radius=0,
            padding=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=controls,
                spacing=10,
                scroll=None,
            ),
        )


    def build_dynamic_specific_data_content(expediente_id, formulario, campos, saved_values, tipo_label, subtipo_label):
        state["specific_view_mode"] = "DYNAMIC"
        controls = [
            ft.Container(
                bgcolor="#EAF3FF",
                border=ft.border.all(1, "#B9D7FF"),
                border_radius=16,
                padding=14,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.DYNAMIC_FORM, size=24, color=Q_PRIMARY),
                            bgcolor="#FFFFFF",
                            border_radius=24,
                            width=48,
                            height=48,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("Datos específicos del expediente", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(f"Tipo/Subtipo: {tipo_label} / {subtipo_label}", size=13, color=Q_MUTED),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        secondary_button("Generar snapshot", generate_snapshot),
                        secondary_button("Volcar datos en formulario", volcar_datos_formulario),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ]

        controls.append(build_snapshot_status_content(expediente_id))

        if not formulario:
            controls.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=14,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text("Sin formulario específico configurado", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text("Crea un formulario dinámico en Configuración para este tipo/subtipo.", size=13, color=Q_MUTED),
                            ft.Text(f"Clave funcional: {tipo_label} / {subtipo_label}", size=13, color=Q_PRIMARY),
                        ],
                    ),
                )
            )
        else:
            controls.append(
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(formulario.get("nombre") or "Formulario específico", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(formulario.get("descripcion") or "Campos dinámicos configurados para este trámite.", size=12, color=Q_MUTED),
                        ],
                    ),
                )
            )

            if campos:
                field_controls = [_build_dynamic_field_control(campo, saved_values) for campo in campos]
                controls.append(
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=14,
                        content=ft.Column(
                            controls=field_controls,
                            spacing=12,
                        ),
                    )
                )
                controls.append(
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=14,
                        padding=12,
                        content=ft.Row(
                            controls=[
                                primary_button("Guardar datos específicos", save_specific_data),
                                secondary_button("Generar snapshot", generate_snapshot),
                                secondary_button("Volcar datos en formulario", volcar_datos_formulario),
                                ft.Text(
                                    "El volcado usará el snapshot confirmado del expediente, no la ficha maestra.",
                                    size=12,
                                    color=Q_MUTED,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                            wrap=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )
            else:
                controls.append(empty_state("El formulario existe, pero todavía no tiene campos configurados"))

        return ft.Container(
            width=920,
            height=620,
            bgcolor="#FFFFFF",
            content=ft.Column(
                controls=controls,
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            ),
        )


    def _build_ex02_specific_content(expediente_id, formulario, saved_values, tipo_label, subtipo_label):
        """
        Pantalla específica EX02 - Reagrupación familiar.

        Contrato corregido de datos:
        - datos_especificos.reagrupado_*   -> cliente del expediente / solicitante en Mercurio.
        - datos_especificos.reagrupante_*  -> familiar residente que reagrupa, seleccionado desde contactos.
        - datos_especificos.representante_* -> presentador profesional congelado para revisión.

        No usa contactos.0.* para evitar dependencia del orden de contactos.
        """
        state["specific_view_mode"] = "EX02"
        state["specific_formulario_id"] = formulario.get("id") if formulario else None
        saved_values = _refresh_saved_values_from_live_contact(saved_values, "reagrupante")
        saved_values = _refresh_saved_values_from_live_contact(saved_values, "solicitante_representante_legal")

        steps = [
            ("Reagrupado", "Cliente solicitante"),
            ("Reagrupante", "Familiar residente"),
            ("Representante", "Presentador profesional"),
            ("Solicitud", "Checks EX02"),
            ("Revisión", "Snapshot y EX"),
        ]
        current_step = max(0, min(int(state.get("specific_data_step") or 0), len(steps) - 1))

        cliente_id = _option_id(cliente.get_value())
        cliente_details = _fetch_cliente_details(cliente_id) if cliente_id else {}
        reagrupante_options = _fetch_cliente_contact_options(cliente_id, only_employers=False)

        try:
            presentador = config_service.get_representante_config() or {}
        except Exception:
            presentador = {}

        person_fields = [
            "contacto_id", "id", "tipo_contacto", "parentesco",
            "nombre", "primer_apellido", "segundo_apellido", "nombre_completo",
            "documento", "nie", "dni", "pasaporte", "nacionalidad",
            "fecha_nacimiento", "sexo", "telefono", "email",
            "estado_cliente", "domicilio_espana", "tipo_via", "nombre_via",
            "numero", "piso", "puerta", "escalera", "localidad", "provincia",
            "codigo_postal", "localidad_nacimiento", "pais_nacimiento",
            "nombre_padre", "nombre_madre", "estado_civil", "cliente_referenciado_id",
            "via_completa",
        ]

        def full_name_from_details(details):
            if not details:
                return ""
            return (
                details.get("nombre_completo")
                or " ".join(
                    str(details.get(k) or "").strip()
                    for k in ("nombre", "primer_apellido", "segundo_apellido")
                    if str(details.get(k) or "").strip()
                )
            ).strip()

        def via_completa_from_details(details):
            if not details:
                return ""
            existing = str(details.get("via_completa") or "").strip()
            if existing:
                return existing
            tipo = str(details.get("tipo_via") or "").strip()
            nombre = str(details.get("nombre_via") or "").strip()
            joined = " ".join(part for part in (tipo, nombre) if part).strip()
            return joined or str(details.get("domicilio_espana") or "").strip()

        def document_from_details(details):
            return (
                str(details.get("documento") or "").strip()
                or str(details.get("nie") or "").strip()
                or str(details.get("dni") or "").strip()
                or str(details.get("pasaporte") or "").strip()
            )

        def person_values_from_details(details=None):
            details = details or {}
            values = {}
            for field in person_fields:
                values[field] = str(details.get(field) or "")
            values["nombre_completo"] = full_name_from_details(details)
            values["documento"] = document_from_details(details)
            values["via_completa"] = via_completa_from_details(details)
            return values

        def register_person(prefix, details=None, force_live=False):
            defaults = person_values_from_details(details)
            for field in person_fields:
                code = f"{prefix}_{field}"
                value = defaults.get(field, "") if force_live else _specific_field_value(saved_values, code, defaults.get(field, ""))
                _register_hidden_specific_control(code, value)
                if force_live:
                    _remember_specific_value(code, value)

        def register_presentador():
            mapping = {
                "representante_nombre_razon_social": presentador.get("representante_nombre_razon_social") or " ".join(
                    str(presentador.get(k) or "").strip()
                    for k in ("representante_nombre", "representante_apellido1", "representante_apellido2")
                    if str(presentador.get(k) or "").strip()
                ),
                "representante_documento": presentador.get("representante_documento") or "",
                "representante_tipo_via": presentador.get("representante_tipo_via") or "",
                "representante_domicilio": presentador.get("representante_domicilio") or "",
                "representante_numero": presentador.get("representante_numero") or "",
                "representante_piso": presentador.get("representante_piso") or "",
                "representante_localidad": presentador.get("representante_localidad") or "",
                "representante_codigo_postal": presentador.get("representante_codigo_postal") or "",
                "representante_provincia": presentador.get("representante_provincia") or "",
                "representante_telefono_movil": presentador.get("representante_telefono_movil") or presentador.get("representante_telefono") or "",
                "representante_email": presentador.get("representante_email") or "",
            }
            for code, default in mapping.items():
                _register_hidden_specific_control(code, _specific_field_value(saved_values, code, default))

        # EX02: el expediente y la solicitud Mercurio quedan a nombre del cliente reagrupado.
        # Se fuerza desde ficha viva del cliente para que el mapper pueda usar datos_especificos.reagrupado_*.
        register_person("reagrupado", cliente_details, force_live=True)
        # Representante legal real del reagrupado/solicitante, seleccionado desde contactos.
        register_person("solicitante_representante_legal", {})
        # El reagrupante es el familiar/contacto residente que da derecho.
        register_person("reagrupante", {})
        register_presentador()

        # Campos visibles de solicitud EX02.
        vinculo_reagrupado_reagrupante = _specific_value_select(
            "vinculo_reagrupado_reagrupante",
            "Vínculo de la persona reagrupada respecto a la persona que reagrupa",
            [
                "CÓNYUGE",
                "PAREJA REGISTRADA",
                "PAREJA NO REGISTRADA",
                "ASCENDIENTE MAYOR DE 65 AÑOS",
                "ASCENDIENTE MENOR DE 65 AÑOS",
                "HIJO/A MENOR 18 AÑOS",
                "HIJO/A MAYOR DE 18 AÑOS CON DISCAPACIDAD",
                "MENOR DE 18 AÑOS REPRESENTADA LEGALMENTE POR EL REAGRUPANTE",
                "MAYOR DE 18 AÑOS DISCAPACITADA REPRESENTADA LEGALMENTE POR EL REAGRUPANTE",
                "HIJO/A MAYOR 18 AÑOS, CUIDADOR",
                "HIJO/A MAYOR 18 AÑOS - RENOVACIÓN",
            ],
            saved_values,
            width=720,
            default="CÓNYUGE",
        )
        hijos = _specific_value_select(
            "hijasos_a_cargo_en_edad_de_escolarización_en_españa",
            "Hijos/as a cargo en edad de escolarización en España",
            ["Si", "No"],
            saved_values,
            width=260,
            default="No",
        )
        autorizacion = _specific_value_text(
            "autorización_de_la_que_es_titular",
            "Autorización de la que es titular el reagrupante",
            saved_values,
            width=520,
        )
        tipo_solicitud = _specific_value_select(
            "tipo_de_solicitud",
            "Tipo de solicitud",
            [
                "REAGRUPACIÓN FAMILIAR INICIAL",
                "REAGRUPACIÓN FAMILIAR INICIAL COMO FAMILIAR DE RESIDENTE DE LARGA DURACIÓN-UE EN OTRO ESTADO\rMIEMBRO DE LA UNIÓN EUROPEA",
                "REAGRUPACIÓN FAMILIAR RENOVACIÓN",
            ],
            saved_values,
            width=620,
            default="REAGRUPACIÓN FAMILIAR INICIAL",
        )
        simultaneas = _specific_value_select(
            "presentan_simultáneamente_otras_solicitudes_por_reagrupación_familiar",
            "Presentan simultáneamente otras solicitudes por reagrupación familiar",
            ["Si", "No"],
            saved_values,
            width=360,
            default="No",
        )
        familiar_reagrupado = _specific_value_text(
            "familiar_reagrupado",
            "Familiar reagrupado / observación interna",
            saved_values,
            width=620,
        )

        def apply_reagrupante(selected):
            contacto_id = _option_id(selected)
            details = _fetch_cliente_contact_details(contacto_id) if contacto_id else {}
            _remember_contact_specific_values("reagrupante", selected, details)
            # El reagrupado es el cliente: se mantiene como referencia visible del trámite.
            _set_specific_control_value("familiar_reagrupado", full_name_from_details(cliente_details))
            _autosave_specific_values_silent()
            # Reconstruye la sección para que las tarjetas resumen reflejen el contacto
            # vivo inmediatamente, sin tener que avanzar y volver.
            if expediente_id:
                expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        reagrupante_autocomplete = AppAutocomplete(
            page=page,
            label="Familiar reagrupante",
            options=reagrupante_options,
            value=_specific_field_value(saved_values, "reagrupante", ""),
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_reagrupante,
        )
        state.setdefault("specific_field_controls", {})["reagrupante"] = reagrupante_autocomplete

        solicitante_rep_value = _specific_field_value(saved_values, "solicitante_representante_legal", "")

        def apply_solicitante_representante_contact(selected):
            contacto_id = _option_id(selected)
            details = _fetch_cliente_contact_details(contacto_id) if contacto_id else {}
            _remember_contact_specific_values("solicitante_representante_legal", selected or "", details or {})
            _autosave_specific_values_silent()
            # Mismo patrón que EX01 familiar: actualizar la tarjeta inmediatamente.
            if expediente_id:
                expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            page.update()

        solicitante_rep_autocomplete = AppAutocomplete(
            page=page,
            label="Representante legal del reagrupado / solicitante",
            options=reagrupante_options,
            value=solicitante_rep_value,
            width=620,
            max_results=10,
            allow_free_text=True,
            on_select=apply_solicitante_representante_contact,
        )
        state.setdefault("specific_field_controls", {})["solicitante_representante_legal"] = solicitante_rep_autocomplete

        header = ft.Container(
            bgcolor="#EAF3FF",
            border=ft.border.all(1, "#B9D7FF"),
            border_radius=16,
            padding=14,
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.FAMILY_RESTROOM, size=24, color=Q_PRIMARY),
                        bgcolor="#FFFFFF",
                        border_radius=24,
                        width=48,
                        height=48,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        spacing=2,
                        expand=True,
                        controls=[
                            ft.Text("EX02 · Datos específicos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text("Contrato explícito: reagrupado=cliente solicitante, reagrupante=familiar/contacto. No depende de contactos.0.", size=13, color=Q_MUTED),
                        ],
                    ),
                    secondary_button("Refrescar", refresh_specific_data_screen),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        reagrupado_card = _specific_card(
            "Reagrupado / solicitante",
            "Se toma del cliente principal del expediente. Es la persona a cuyo nombre se tramita la solicitud en Mercurio.",
            [
                ft.Row(
                    controls=[
                        _specific_info_row("Nombre", full_name_from_details(cliente_details)),
                        _specific_info_row("Documento", document_from_details(cliente_details)),
                        _specific_info_row("NIE", cliente_details.get("nie") or "-"),
                        _specific_info_row("Pasaporte", cliente_details.get("pasaporte") or "-"),
                        _specific_info_row("Nacimiento", cliente_details.get("fecha_nacimiento") or "-"),
                        _specific_info_row("Estado civil", cliente_details.get("estado_civil") or "-"),
                        _specific_info_row("Sexo", cliente_details.get("sexo") or "-"),
                        _specific_info_row("Nacionalidad", cliente_details.get("nacionalidad") or "-"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _specific_info_row("Domicilio", via_completa_from_details(cliente_details)),
                        _specific_info_row("Número", cliente_details.get("numero") or "-"),
                        _specific_info_row("Piso", cliente_details.get("piso") or "-"),
                        _specific_info_row("Localidad", cliente_details.get("localidad") or "-"),
                        _specific_info_row("Provincia", cliente_details.get("provincia") or "-"),
                        _specific_info_row("C.P.", cliente_details.get("codigo_postal") or "-"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            solicitante_rep_autocomplete.control,
                            ft.Text("Opcional. Se copia como solicitante_representante_legal_* igual que en EX01 familiar.", size=11, color=Q_MUTED),
                            ft.Row(
                                controls=[
                                    _specific_info_row("Representante legal", _specific_field_value(saved_values, "solicitante_representante_legal_nombre_completo", "-")),
                                    _specific_info_row("Documento", _specific_field_value(saved_values, "solicitante_representante_legal_documento", "-")),
                                    _specific_info_row("Parentesco/título", _specific_field_value(saved_values, "solicitante_representante_legal_parentesco", "-")),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                        ],
                    ),
                ),
                ft.Text("Estos datos se guardan como campos técnicos reagrupado_* al avanzar o guardar.", size=11, color=Q_MUTED),
            ],
            icon=ft.Icons.PERSON,
        )

        reagrupante_card = _specific_card(
            "Reagrupante",
            "Selecciona el familiar/contacto residente que reagrupa. Sus datos vivos se materializan como reagrupante_*.",
            [
                reagrupante_autocomplete.control,
                ft.Text("Al seleccionar, se copian NIE/pasaporte, filiación, domicilio, parentesco y contacto.", size=11, color=Q_MUTED),
                ft.Row(
                    controls=[
                        _specific_info_row("Seleccionado", _specific_field_value(saved_values, "reagrupante_nombre_completo", "-")),
                        _specific_info_row("Documento", _specific_field_value(saved_values, "reagrupante_documento", "-")),
                        _specific_info_row("NIE", _specific_field_value(saved_values, "reagrupante_nie", "-")),
                        _specific_info_row("Pasaporte", _specific_field_value(saved_values, "reagrupante_pasaporte", "-")),
                        _specific_info_row("Nacimiento", _specific_field_value(saved_values, "reagrupante_fecha_nacimiento", "-")),
                        _specific_info_row("Estado civil", _specific_field_value(saved_values, "reagrupante_estado_civil", "-")),
                        _specific_info_row("Sexo", _specific_field_value(saved_values, "reagrupante_sexo", "-")),
                        _specific_info_row("Parentesco", _specific_field_value(saved_values, "reagrupante_parentesco", "-")),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _specific_info_row("Domicilio", _specific_field_value(saved_values, "reagrupante_via_completa", "-")),
                        _specific_info_row("Número", _specific_field_value(saved_values, "reagrupante_numero", "-")),
                        _specific_info_row("Piso", _specific_field_value(saved_values, "reagrupante_piso", "-")),
                        _specific_info_row("Localidad", _specific_field_value(saved_values, "reagrupante_localidad", "-")),
                        _specific_info_row("Provincia", _specific_field_value(saved_values, "reagrupante_provincia", "-")),
                        _specific_info_row("C.P.", _specific_field_value(saved_values, "reagrupante_codigo_postal", "-")),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            icon=ft.Icons.GROUP,
        )

        representante_card = _specific_card(
            "Representante / presentador",
            "Se muestra desde Settings y se congela como representante_* para revisión del EX02.",
            [
                ft.Row(
                    controls=[
                        _specific_info_row("Nombre", presentador.get("representante_nombre_razon_social") or "-"),
                        _specific_info_row("Documento", presentador.get("representante_documento") or "-"),
                        _specific_info_row("Email", presentador.get("representante_email") or "-"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        _specific_info_row("Domicilio", " ".join(part for part in [presentador.get("representante_tipo_via"), presentador.get("representante_domicilio")] if part)),
                        _specific_info_row("Número", presentador.get("representante_numero") or "-"),
                        _specific_info_row("Piso", presentador.get("representante_piso") or "-"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            icon=ft.Icons.BADGE,
        )

        solicitud_card = _specific_card(
            "Datos de solicitud EX02",
            "Campos que alimentan checks y textos específicos del EX02.",
            [
                ft.Row([tipo_solicitud], wrap=True, spacing=10),
                ft.Row([vinculo_reagrupado_reagrupante], wrap=True, spacing=10),
                ft.Row([autorizacion, hijos], wrap=True, spacing=10),
                ft.Row([simultaneas, familiar_reagrupado], wrap=True, spacing=10),
            ],
            icon=ft.Icons.FACT_CHECK,
        )

        review_card = _specific_card(
            "Revisión y generación",
            "Guarda, genera snapshot y prepara el EX02 desde datos específicos.",
            [
                _specific_generation_status_card(expediente_id),
                ft.Row(
                    controls=[
                        _specific_info_row("Mapper", "MERCURIO_EX02"),
                        _specific_info_row("Reagrupado", full_name_from_details(cliente_details)),
                        _specific_info_row("Reagrupante", _specific_field_value(saved_values, "reagrupante_nombre_completo", "-")),
                        _specific_info_row("Vínculo", _specific_field_value(saved_values, "vinculo_reagrupado_reagrupante", "-")),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                build_snapshot_status_content(expediente_id),
                ft.Text(
                    "Los botones de guardado, snapshot y generación están agrupados abajo para mantener el flujo único de volcado.",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            icon=ft.Icons.CHECK_CIRCLE,
        )

        step_controls = [reagrupado_card, reagrupante_card, representante_card, solicitud_card, review_card]

        nav_controls = []
        if current_step > 0:
            nav_controls.append(secondary_button("Anterior", lambda e: _save_specific_and_go_step(current_step - 1)))
        if current_step < len(steps) - 1:
            nav_controls.append(primary_button("Siguiente", lambda e: _save_specific_and_go_step(current_step + 1)))
        else:
            nav_controls.extend([
                secondary_button("Guardar datos", save_specific_data),
                secondary_button("Generar snapshot", generate_snapshot),
                primary_button("Generar EX02", generate_referenced_ex_form),
                _forms_popup_menu(),
            ])

        nav = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=10,
            content=ft.Row(
                controls=nav_controls,
                spacing=10,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        return ft.Container(
            width=920,
            height=620,
            bgcolor="#FFFFFF",
            content=ft.Column(
                controls=[
                    header,
                    _specific_data_stepper(steps, current_step),
                    form_message,
                    step_controls[current_step],
                    nav,
                ],
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            ),
        )


    def build_specific_data_content(expediente_id):
        tipo_id = _selected_tipo_id()
        subtipo_id = _selected_subtipo_id()
        tipo_label = _selected_option_label(tipo_expediente.get_value())
        subtipo_label = _selected_subtipo_label()

        context = dynamic_form_service.get_formulario_for_context(tipo_id, subtipo_id)
        formulario = context.get("formulario")
        campos = context.get("campos") or []
        saved_values = dynamic_form_service.load_datos_especificos(expediente_id) if expediente_id else {}

        state["specific_field_controls"] = {}
        state["specific_live_values"] = {}
        state["specific_formulario_id"] = formulario.get("id") if formulario else None

        mapper_codigo = _specific_mapper_codigo(tipo_id, subtipo_id, tipo_label, subtipo_label)

        if formulario and mapper_codigo == "MERCURIO_EX01_FAMILIAR":
            return _build_ex01_familiar_specific_content(
                expediente_id,
                formulario,
                saved_values,
                tipo_label,
                subtipo_label,
            )

        if formulario and mapper_codigo == "MERCURIO_EX01":
            return _build_ex01_titular_specific_content(
                expediente_id,
                formulario,
                saved_values,
                tipo_label,
                subtipo_label,
            )

        if formulario and mapper_codigo == "MERCURIO_EX02":
            return _build_ex02_specific_content(
                expediente_id,
                formulario,
                saved_values,
                tipo_label,
                subtipo_label,
            )

        return build_dynamic_specific_data_content(
            expediente_id,
            formulario,
            campos,
            saved_values,
            tipo_label,
            subtipo_label,
        )

    def _form_card(title, subtitle, controls, icon=ft.Icons.EDIT_DOCUMENT):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(icon, size=18, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                width=36,
                                height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(subtitle, size=12, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    *controls,
                ],
                spacing=12,
            ),
        )

    def build_edit_content():
        return ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=16,
                    padding=14,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.FOLDER_SPECIAL, size=24, color=Q_PRIMARY),
                                bgcolor="#FFFFFF",
                                border_radius=24,
                                width=48,
                                height=48,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("Ficha principal del expediente", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text("Datos base, estados, presentación y vinculación documental.", size=13, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                _form_card(
                    "Datos principales",
                    "Cliente, tipo, subtipo y estado operativo del asunto.",
                    [
                        ft.Row([numero_expediente, numero_expediente_mercurio, cliente.control], wrap=True, spacing=10),
                        ft.Row([tipo_expediente.control, subtipo_expediente.control, subtipo_expediente_manual, prioridad], wrap=True, spacing=10),
                        ft.Row([estado_documental, estado_administrativo, estado_presentacion], wrap=True, spacing=10),
                        ft.Row([responsable, provincia], wrap=True, spacing=10),
                    ],
                    ft.Icons.ACCOUNT_TREE,
                ),
                _form_card(
                    "Fechas y presentación",
                    "Control temporal y datos administrativos de presentación.",
                    [
                        ft.Row([fecha_apertura, fecha_presentacion, fecha_resolucion], wrap=True, spacing=10),
                        ft.Row([numero_registro, organo_presentacion], wrap=True, spacing=10),
                    ],
                    ft.Icons.EVENT_NOTE,
                ),
                _form_card(
                    "Box y observaciones",
                    "Ruta de referencia y notas internas del expediente.",
                    [
                        box_folder_path,
                        ft.Row(
                            controls=[
                                secondary_button("Buscar carpetas Box", lambda e: cargar_box_folder_options(False)),
                                primary_button("Escanear ruta y buscar", lambda e: cargar_box_folder_options(True)),
                                secondary_button("Vincular ruta escrita", vincular_box_folder_desde_ficha),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        ft.Text("Selector readonly: el ERP observa Box y solo vincula la ruta en SQLite. No mueve, borra ni renombra archivos.", size=12, color=Q_MUTED),
                        ft.Text("Solo se guarda una ruta de referencia. El ERP no manipula Box en esta fase.", size=12, color=Q_MUTED),
                        ft.Row(
                            controls=[
                                primary_button("Vincular ruta Box al expediente", vincular_box_folder_desde_ficha),
                                secondary_button("Refrescar estado Box", refresh_para_presentar_documents),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        observaciones,
                        observaciones_internas,
                    ],
                    ft.Icons.FOLDER_OPEN,
                ),
                form_message,
            ],
            width=920,
            height=620,
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
        )

    def build_diagnostic_content(expediente_id):
        if not expediente_id:
            return ft.Container(
                width=920,
                height=620,
                content=empty_state("Guarda el expediente para poder generar diagnóstico documental"),
            )

        try:
            result = document_state_service.diagnose_expediente_document_state(expediente_id)
            resumen = result.get("resumen") or {}

            diagnostic_doc_path_by_name = {}
            try:
                viewer_docs = document_viewer_service.list_expediente_documents(expediente_id).get("documents") or []
                for viewer_doc in viewer_docs:
                    viewer_name = str(viewer_doc.get("name") or "").strip()
                    viewer_path = str(viewer_doc.get("path") or "").strip()
                    if viewer_name and viewer_path:
                        diagnostic_doc_path_by_name[viewer_name.casefold()] = viewer_path
            except Exception:
                diagnostic_doc_path_by_name = {}

            faltantes_controls = [
                ft.Text(f"• {f.get('nombre') or f.get('codigo')}", color="#B42318", size=13)
                for f in result.get("faltantes", [])
            ] or [ft.Text("No hay faltantes", color="#027A48", size=13)]

            selected_diagnostic_docs = state.setdefault("diagnostic_viewer_selected_docs", {})

            def _diagnostic_doc_path(item):
                direct_path = (
                    item.get("path")
                    or item.get("archivo_ruta")
                    or item.get("ruta")
                    or item.get("file_path")
                    or item.get("box_path")
                    or item.get("document_path")
                    or ""
                )
                if direct_path:
                    return direct_path

                archivo = (
                    item.get("archivo")
                    or item.get("archivo_nombre")
                    or item.get("file_name")
                    or item.get("document_name")
                    or item.get("nombre_archivo")
                    or ""
                )
                archivo_key = str(archivo or "").strip().casefold()
                if archivo_key:
                    return diagnostic_doc_path_by_name.get(archivo_key, "")

                return ""

            def _diagnostic_doc_name(item):
                raw_path = _diagnostic_doc_path(item)
                return (
                    item.get("archivo_nombre")
                    or item.get("archivo")
                    or item.get("file_name")
                    or item.get("document_name")
                    or item.get("nombre_archivo")
                    or item.get("nombre")
                    or item.get("codigo")
                    or Path(str(raw_path)).name
                    or "-"
                )

            def toggle_diagnostic_doc_selection(e, file_path, file_name):
                if not file_path:
                    e.control.value = False
                    show_form_error("Esta detección no tiene archivo asociado para abrir en el visor.")
                    page.update()
                    return

                if e.control.value:
                    selected_diagnostic_docs[file_path] = {"path": file_path, "name": file_name}
                else:
                    selected_diagnostic_docs.pop(file_path, None)

                page.update()

            def open_selected_diagnostic_documents(e=None):
                selected = list(selected_diagnostic_docs.values())
                if not selected:
                    show_form_error("Selecciona uno o varios documentos detectados para abrir el visor.")
                    return

                first = selected[0]
                show_document_preview(
                    first.get("path"),
                    first.get("name"),
                    expediente_id,
                    1,
                    1.6,
                    selected,
                    0,
                )

            encontrados_controls = []
            for f in result.get("encontrados", []):
                doc_path = _diagnostic_doc_path(f)
                doc_name = _diagnostic_doc_name(f)
                label = f.get("nombre") or f.get("codigo") or doc_name
                codigo = f.get("codigo") or ""
                has_path = bool(doc_path)

                encontrados_controls.append(
                    ft.Container(
                        padding=10,
                        border_radius=10,
                        border=ft.border.all(1, "#ABEFC6" if has_path else Q_BORDER),
                        bgcolor="#F6FEF9" if has_path else "#F8FAFC",
                        content=ft.Row(
                            controls=[
                                ft.Checkbox(
                                    value=doc_path in selected_diagnostic_docs,
                                    disabled=not has_path,
                                    tooltip="Seleccionar para visor" if has_path else "Detección sin archivo asociado",
                                    on_change=lambda e, p=doc_path, n=doc_name: toggle_diagnostic_doc_selection(e, p, n),
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(f"• {label}", color="#027A48" if has_path else Q_MUTED, size=13, weight=ft.FontWeight.BOLD),
                                        ft.Text(f"Código: {codigo}" if codigo else "Detección documental", size=11, color=Q_MUTED),
                                        ft.Text(doc_path if has_path else "Sin ruta de archivo vinculada en el diagnóstico", size=11, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                secondary_button("Abrir", lambda e, p=doc_path: open_document_with_system(p),) if has_path else ft.Text("Sin visor", size=11, color=Q_MUTED),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            if encontrados_controls:
                encontrados_controls.insert(
                    0,
                    ft.Row(
                        controls=[
                            primary_button("Ver seleccionados", open_selected_diagnostic_documents),
                            ft.Text("Selecciona detecciones con archivo asociado para revisarlas en el visor v7.", size=12, color=Q_MUTED),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                )
            else:
                encontrados_controls = [ft.Text("No hay documentos encontrados por regla", color=Q_MUTED, size=13)]

            signals_controls = [
                ft.Text(f"• {signal}", size=13)
                for signal in result.get("senales", [])
            ] or [ft.Text("Sin señales específicas", size=13, color=Q_MUTED)]

            return ft.Column(
                width=920,
                height=620,
                scroll=ft.ScrollMode.AUTO,
                spacing=14,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"Estado sugerido: {result.get('estado_sugerido')}",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY,
                            ),
                            ft.Text(f"Confianza: {result.get('confianza')}", size=14, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=18,
                    ),
                    _section_box(
                        "Resumen documental",
                        [
                            ft.Text(
                                (
                                    f"Archivos: {resumen.get('total_archivos', 0)} · "
                                    f"Carpetas: {resumen.get('total_carpetas', 0)} · "
                                    f"Obligatorios: {resumen.get('total_obligatorios', 0)} · "
                                    f"Encontrados: {resumen.get('total_encontrados', 0)} · "
                                    f"Faltantes: {resumen.get('total_faltantes', 0)}"
                                ),
                                selectable=True,
                                size=13,
                            )
                        ],
                    ),
                    _section_box("Documentos encontrados", encontrados_controls),
                    _section_box("Documentos faltantes", faltantes_controls),
                    _section_box("Señales detectadas", signals_controls),
                ],
            )
        except Exception as exc:
            return ft.Container(width=920, height=620, content=error_alert(str(exc)))

    def _admin_event_code_from_option(value):
        value = str(value or "").strip()
        return value.split(" - ", 1)[0].strip() if " - " in value else value

    async def open_admin_document_picker(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de anexar documentos")
            return

        state["admin_document_expediente_id"] = int(expediente_id)
        state["admin_document_file"] = None

        try:
            files = await ft.FilePicker().pick_files(allow_multiple=False)
        except Exception as exc:
            show_form_error(str(exc))
            return

        if not files:
            return

        selected = files[0]
        file_path = getattr(selected, "path", "") or getattr(selected, "name", "")
        file_name = getattr(selected, "name", "") or Path(str(file_path)).name

        if not file_path:
            show_form_error("No se pudo obtener la ruta del archivo seleccionado")
            return

        state["admin_document_file"] = {
            "path": str(file_path),
            "name": str(file_name),
        }

        admin_document_selected_file.value = str(file_path)
        admin_document_event_type.value = admin_document_event_options[0] if admin_document_event_options else None
        admin_document_observaciones.value = ""
        admin_document_dialog.open = True
        page.update()

    def close_admin_document_dialog(e=None):
        admin_document_dialog.open = False
        state["admin_document_file"] = None
        admin_document_selected_file.value = ""
        admin_document_observaciones.value = ""
        page.update()

    def save_admin_document_event(e=None):
        expediente_id = state.get("admin_document_expediente_id") or state.get("dialog_expediente_id") or state.get("editing_id")
        selected = state.get("admin_document_file") or {}
        if not expediente_id:
            show_form_error("No hay expediente activo")
            return
        if not selected.get("path") and not selected.get("name"):
            show_form_error("Selecciona un documento")
            return

        try:
            result = trace_service.create_admin_document_event({
                "expediente_id": expediente_id,
                "archivo_nombre": selected.get("name") or Path(selected.get("path") or "").name,
                "archivo_ruta": selected.get("path") or selected.get("name"),
                "event_code": _admin_event_code_from_option(admin_document_event_type.value),
                "observaciones": admin_document_observaciones.value,
                "usuario": "ERP",
            })

            # Sincroniza los controles principales del formulario abierto.
            # Sin esto, al guardar el expediente se pisa la transición automática
            # con el valor antiguo que tenía el dropdown en memoria.
            estado_nuevo_id = result.get("estado_nuevo_id")
            estado_nuevo = (result.get("estado_nuevo") or "").strip().upper()

            if estado_nuevo_id:
                estado_administrativo.value = next(
                    (
                        option
                        for option in estado_admin_options
                        if option.startswith(str(estado_nuevo_id) + " - ")
                    ),
                    estado_administrativo.value,
                )

            if estado_nuevo == "PRESENTADO":
                estado_presentacion.value = "PRESENTADO"

            admin_document_dialog.open = False

            queue_completion = result.get("queue_completion") or {}
            if queue_completion.get("changed"):
                set_message(success_alert(
                    f"Documento anexado: {result.get('event_label') or 'evento administrativo'}\n"
                    "Cola de presentación marcada como presentada."
                ))
            else:
                set_message(success_alert(f"Documento anexado: {result.get('event_label') or 'evento administrativo'}"))

            state["dialog_section"] = "trazabilidad"
            expediente_dialog.content = build_expediente_dialog_content(expediente_id)
            refresh_table()
            page.update()
        except Exception as exc:
            show_form_error(str(exc))

    def build_traceability_content(expediente_id):
        if not expediente_id:
            return ft.Container(
                width=920,
                height=620,
                content=empty_state("Guarda el expediente para poder ver su trazabilidad"),
            )

        try:
            resumen = trace_service.get_resumen_trazabilidad(expediente_id)
            justificantes = resumen.get("justificantes", [])
            hojas = resumen.get("hojas_encargo", [])
            consultas = resumen.get("consultas_aplicadas", [])
            eventos = resumen.get("eventos", [])

            def rows_or_empty(headers, rows, empty_text, height=220):
                if not rows:
                    return empty_state(empty_text)
                return app_table(headers, rows, height=height)

            justificante_rows = [
                [
                    j.get("archivo_nombre") or "-",
                    j.get("archivo_ruta") or "-",
                    _date_to_display(j.get("fecha_presentacion")),
                    j.get("numero_registro") or "-",
                    j.get("estado_conciliacion") or "-",
                ]
                for j in justificantes
            ]
            hoja_rows = [
                [
                    h.get("numero_hoja") or "-",
                    _date_to_display(h.get("fecha_firma")),
                    h.get("procedimiento") or "-",
                    f"{float(h.get('importe_neto') or 0):.2f} €",
                    h.get("estado_firma") or h.get("estado") or "-",
                ]
                for h in hojas
            ]
            consulta_rows = [
                [
                    _date_to_display(c.get("fecha_consulta")),
                    f"{float(c.get('importe_aplicado') or 0):.2f} €",
                    f"{float(c.get('importe_original') or 0):.2f} €",
                    c.get("observaciones") or "-",
                ]
                for c in consultas
            ]
            evento_rows = [
                [
                    _date_to_display(ev.get("fecha_evento")),
                    ev.get("tipo_evento") or "-",
                    ev.get("titulo") or "-",
                    ev.get("descripcion") or "-",
                ]
                for ev in eventos
            ]

            return ft.Column(
                width=920,
                height=620,
                scroll=ft.ScrollMode.AUTO,
                spacing=14,
                controls=[
                    ft.Container(
                        bgcolor="#EAF3FF",
                        border=ft.border.all(1, "#B9D7FF"),
                        border_radius=16,
                        padding=14,
                        content=ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Icon(ft.Icons.ATTACH_FILE, size=24, color=Q_PRIMARY),
                                    bgcolor="#FFFFFF",
                                    border_radius=24,
                                    width=48,
                                    height=48,
                                    alignment=ft.alignment.Alignment(0, 0),
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Trazabilidad administrativa", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text("Anexa documentos desde la carpeta del cliente y deja rastro en el historial del expediente.", size=13, color=Q_MUTED),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                primary_button("Anexar documento", open_admin_document_picker),
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ),
                    _section_box(
                        "Justificantes",
                        [rows_or_empty(["Archivo", "Ruta", "Fecha presentación", "Registro", "Estado"], justificante_rows, "No hay justificantes cargados", 240)],
                    ),
                    _section_box(
                        "Hojas de encargo",
                        [rows_or_empty(["Nº hoja", "Firma", "Procedimiento", "Importe neto", "Estado"], hoja_rows, "No hay hojas de encargo asociadas", 220)],
                    ),
                    _section_box(
                        "Consultas aplicadas",
                        [rows_or_empty(["Fecha consulta", "Aplicado", "Importe original", "Observaciones"], consulta_rows, "No hay consultas aplicadas", 200)],
                    ),
                    _section_box(
                        "Historial del expediente",
                        [rows_or_empty(["Fecha", "Tipo", "Título", "Descripción"], evento_rows, "No hay eventos registrados", 300)],
                    ),
                ],
            )
        except Exception as exc:
            return ft.Container(width=920, height=620, content=error_alert(str(exc)))

    def _format_file_size(size):
        try:
            size = int(size or 0)
        except Exception:
            size = 0
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    def _document_browser_current_path(expediente_id, root_path):
        by_exp = state.setdefault("document_browser_path", {})
        current = by_exp.get(int(expediente_id)) if expediente_id else None
        return current or root_path

    def open_document_folder(path):
        expediente_id = state.get("dialog_expediente_id")
        if expediente_id:
            state.setdefault("document_browser_path", {})[int(expediente_id)] = path
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()

    def open_document_parent_folder(current_path, root_path):
        from pathlib import Path

        current = Path(str(current_path or ""))
        root = Path(str(root_path or ""))

        try:
            if current.resolve() == root.resolve():
                return
        except Exception:
            if str(current).rstrip("\\/") == str(root).rstrip("\\/"):
                return

        parent = str(current.parent)
        open_document_folder(parent)

    def open_current_document_folder(path):
        try:
            expedient_service.open_box_folder_path(path)
        except Exception as exc:
            show_form_error(str(exc))

    def open_para_presentar_in_browser(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        status = _get_mercurio_box_status(expediente_id, force=True) if expediente_id else None
        path = (status or {}).get("box_para_presentar_folder_path") or ""
        if not path:
            show_form_error('No existe carpeta "PARA PRESENTAR" para navegar.')
            return
        open_document_folder(path)

    def build_documentacion_content(expediente_id):
        if not expediente_id:
            return ft.Container(
                width=920,
                height=620,
                content=empty_state("Guarda el expediente para explorar su documentación Box"),
            )

        expediente = expedient_service.get_expediente(expediente_id)
        root_path = str((expediente or {}).get("box_folder_path") or "").strip()

        if not root_path:
            return ft.Container(
                width=920,
                height=620,
                content=empty_state("Este expediente no tiene ruta Box vinculada"),
            )

        current_path = _document_browser_current_path(expediente_id, root_path)
        scanning = int(expediente_id) in state.get("box_scan_running", set())
        status = _get_mercurio_box_status(expediente_id)
        para_presentar_path = (status or {}).get("box_para_presentar_folder_path") or ""

        try:
            data = list_expediente_box_directory(current_path)
        except Exception as exc:
            return ft.Container(
                width=920,
                height=620,
                content=ft.Column(
                    controls=[
                        error_alert(str(exc)),
                        secondary_button("Volver a carpeta raíz", lambda e: open_document_folder(root_path)),
                    ],
                    spacing=12,
                ),
            )

        folder_controls = []
        for folder in data.get("folders", []):
            is_para = _norm(folder.get("name")) == "PARA PRESENTAR"
            folder_controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    border=ft.border.all(1, "#B9D7FF" if is_para else Q_BORDER),
                    bgcolor="#EAF3FF" if is_para else "#F8FAFC",
                    ink=True,
                    on_click=lambda e, p=folder.get("path"): open_document_folder(p),
                    content=ft.Row(
                        controls=[
                            ft.Text("📁", size=20),
                            ft.Column(
                                controls=[
                                    ft.Text(folder.get("name") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(folder.get("path") or "", size=11, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Text("PARA PRESENTAR", size=11, color=Q_PRIMARY, visible=is_para),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        selected_docs = state.setdefault("document_viewer_selected_docs", {})

        box_to_inbox_selected_paths = set()
        box_to_inbox_files = []
        box_to_inbox_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        box_to_inbox_message = ft.Container()

        def close_box_to_inbox_dialog(e=None):
            box_to_inbox_dialog.open = False
            try:
                page.update()
            except Exception:
                pass

        def render_box_to_inbox_files():
            rows = []

            if not box_to_inbox_files:
                rows.append(empty_state("No hay documentos Box copiables en este expediente"))
            else:
                for file_info in box_to_inbox_files:
                    file_path = str(file_info.get("path") or "")
                    relative_path = str(file_info.get("relative_path") or file_info.get("name") or file_path)
                    size_bytes = file_info.get("size_bytes") or file_info.get("size") or 0
                    already_imported = bool(file_info.get("already_imported"))
                    inbox_item_id = file_info.get("inbox_item_id")
                    dedupe_reason = str(file_info.get("dedupe_reason") or "")
                    selected = file_path in box_to_inbox_selected_paths

                    if already_imported and file_path in box_to_inbox_selected_paths:
                        box_to_inbox_selected_paths.discard(file_path)
                        selected = False

                    try:
                        size_label = f"{int(size_bytes) / 1024:.1f} KB" if size_bytes else "—"
                    except Exception:
                        size_label = "—"

                    status_label = ""
                    if already_imported:
                        status_label = f"Ya en Bandeja #{inbox_item_id or '-'}"
                        if dedupe_reason:
                            status_label += f" · {dedupe_reason}"

                    rows.append(
                        ft.Container(
                            bgcolor="#EFF6FF" if selected else "#FFFFFF",
                            border=ft.border.all(1, Q_PRIMARY if selected else Q_BORDER),
                            border_radius=10,
                            padding=8,
                            content=ft.Row(
                                controls=[
                                    ft.Checkbox(
                                        value=selected,
                                        disabled=already_imported,
                                        on_change=lambda e, p=file_path: toggle_box_to_inbox_selection(p),
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(relative_path, size=12, weight=ft.FontWeight.W_600, color=Q_PRIMARY_DARK),
                                            ft.Text(file_path, size=10, color=Q_MUTED, selectable=True),
                                            ft.Text(status_label, size=11, color="#027A48", visible=already_imported),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.Text(size_label, size=11, color=Q_MUTED),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        )
                    )

            box_to_inbox_list.controls = rows

        def toggle_box_to_inbox_selection(file_path):
            file_path = str(file_path or "")
            if not file_path:
                return

            file_info = next((f for f in box_to_inbox_files if str(f.get("path") or "") == file_path), None)
            if file_info and file_info.get("already_imported"):
                box_to_inbox_selected_paths.discard(file_path)
                return

            if file_path in box_to_inbox_selected_paths:
                box_to_inbox_selected_paths.remove(file_path)
            else:
                box_to_inbox_selected_paths.add(file_path)

            render_box_to_inbox_files()
            try:
                box_to_inbox_list.update()
            except Exception:
                pass

        def load_box_to_inbox_files():
            box_to_inbox_selected_paths.clear()
            box_to_inbox_files.clear()

            try:
                files = document_inbox_service.list_expedient_box_files_for_inbox(
                    int(expediente_id),
                    max_files=500,
                )
                box_to_inbox_files.extend(files or [])
                already_count = sum(1 for item in box_to_inbox_files if item.get("already_imported"))
                pending_count = len(box_to_inbox_files) - already_count
                box_to_inbox_message.content = ft.Text(
                    f"{len(box_to_inbox_files)} documento(s) encontrados en Box · "
                    f"{pending_count} pendiente(s) · {already_count} ya en Bandeja.",
                    size=12,
                    color=Q_MUTED,
                )
            except Exception as exc:
                box_to_inbox_message.content = error_alert(f"No se pudieron cargar documentos Box: {exc}")

            render_box_to_inbox_files()

        def copy_selected_box_files_to_inbox(e=None):
            if not box_to_inbox_selected_paths:
                box_to_inbox_message.content = error_alert("Selecciona al menos un documento Box.")
                try:
                    box_to_inbox_message.update()
                except Exception:
                    pass
                return

            copied = 0
            already = 0
            errors = []

            for file_path in list(box_to_inbox_selected_paths):
                try:
                    item = document_inbox_service.import_box_file_to_inbox(
                        file_path,
                        expedient_id=int(expediente_id),
                        source_label="Box expediente",
                    )
                    if item.get("already_imported"):
                        already += 1
                    else:
                        copied += 1
                except Exception as exc:
                    errors.append(f"{Path(file_path).name}: {exc}")

            if errors:
                box_to_inbox_message.content = error_alert(
                    f"Copiados {copied}. Errores: " + " | ".join(errors[:3])
                )
            else:
                box_to_inbox_selected_paths.clear()
                box_to_inbox_message.content = success_alert(
                    f"{copied} nuevo(s) copiado(s) a Bandeja Documental · "
                    f"{already} ya estaba(n) importado(s)."
                )
                load_box_to_inbox_files()

            render_box_to_inbox_files()

            try:
                box_to_inbox_message.update()
                box_to_inbox_list.update()
            except Exception:
                pass

        def open_box_to_inbox_dialog(e=None):
            load_box_to_inbox_files()

            if box_to_inbox_dialog not in page.overlay:
                page.overlay.append(box_to_inbox_dialog)

            box_to_inbox_dialog.open = True
            page.update()

        box_to_inbox_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Copiar documentos Box a Bandeja", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            content=ft.Container(
                width=980,
                height=720,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Selecciona documentos de la carpeta Box del expediente. Se copiarán a Bandeja; el original de Box no se modifica.",
                            size=12,
                            color=Q_MUTED,
                        ),
                        box_to_inbox_message,
                        ft.Container(
                            expand=True,
                            border=ft.border.all(1, Q_BORDER),
                            border_radius=12,
                            padding=8,
                            content=box_to_inbox_list,
                        ),
                    ],
                    spacing=10,
                    expand=True,
                ),
            ),
            actions=[
                secondary_button("Cerrar", close_box_to_inbox_dialog),
                primary_button("Copiar seleccionados a bandeja", copy_selected_box_files_to_inbox),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        selected_docs_count_label = ft.Text(
            f"Seleccionados: {len(selected_docs)}",
            size=11,
            color=Q_MUTED,
        )

        selected_docs_view_button = ft.IconButton(
            icon=ft.Icons.VISIBILITY,
            icon_color=Q_PRIMARY_DARK if selected_docs else "#98A2B3",
            tooltip="Ver seleccionados",
            disabled=not bool(selected_docs),
            on_click=lambda e: open_selected_documents(e),
        )

        selected_docs_clear_button = ft.IconButton(
            icon=ft.Icons.CLEAR_ALL,
            icon_color=Q_PRIMARY_DARK if selected_docs else "#98A2B3",
            tooltip="Limpiar selección",
            disabled=not bool(selected_docs),
            on_click=lambda e: clear_selected_documents(e),
        )

        def refresh_selected_docs_bulk_controls():
            has_selected = bool(selected_docs)
            selected_docs_count_label.value = f"Seleccionados: {len(selected_docs)}"
            selected_docs_view_button.disabled = not has_selected
            selected_docs_view_button.icon_color = Q_PRIMARY_DARK if has_selected else "#98A2B3"
            selected_docs_clear_button.disabled = not has_selected
            selected_docs_clear_button.icon_color = Q_PRIMARY_DARK if has_selected else "#98A2B3"

        def clear_selected_documents(e=None):
            selected_docs.clear()

            try:
                open_document_folder(data.get("current_path") or current_path)
            except Exception:
                page.update()

        def toggle_document_selection(e, file_path, file_name):
            if e.control.value:
                selected_docs[file_path] = {"path": file_path, "name": file_name}
            else:
                selected_docs.pop(file_path, None)

            try:
                open_document_folder(data.get("current_path") or current_path)
            except Exception:
                page.update()

        def open_selected_documents(e=None):
            selected = list(selected_docs.values())
            if not selected:
                show_form_error("Selecciona uno o varios documentos para abrir el visor.")
                return

            first = selected[0]
            show_document_preview(
                first.get("path"),
                first.get("name"),
                expediente_id,
                1,
                1.6,
                selected,
                0,
            )

        file_controls = []
        for file in sorted(data.get("files", []), key=_mercurio_file_sort_key):
            file_path = file.get("path") or ""
            file_name = file.get("name") or "-"
            file_controls.append(
                document_file_card(
                    name=file_name,
                    path=file_path,
                    size_label=_format_file_size(file.get("size")),
                    modified_at=f"Orden: {_mercurio_file_order_label(file)}",
                    file_type=file.get("type"),
                    selected=False,
                    selectable=True,
                    checkbox_value=file_path in selected_docs,
                    on_select=lambda e, p=file_path, n=file_name: toggle_document_selection(e, p, n),
                    action_groups=[
                        {
                            "label": "Documento",
                            "items": [
                                {"label": "Previsualizar", "on_click": lambda e, p=file_path, n=file_name: show_document_preview(p, n, expediente_id)},
                                {"label": "Abrir externo", "on_click": lambda e, p=file_path: open_document_with_system(p, expediente_id)},
                            ],
                        },
                    ],
                    compact=True,
                )
            )

        controls = [
            ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Documentación Box", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Container(expand=True),
                            primary_button("Copiar Box a bandeja", open_box_to_inbox_dialog),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("Escaneando expediente...", size=12, color=Q_MUTED, visible=scanning),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                "Explorador readonly del expediente. No crea, mueve, borra ni renombra documentos.",
                size=12,
                color=Q_MUTED,
            ),
            ft.Container(
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=10,
                content=ft.Column(
                    controls=[
                        ft.Text("Ruta actual", size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Text(data.get("current_path") or current_path, size=12, color=Q_MUTED),
                    ],
                    spacing=4,
                ),
            ),
            ft.Row(
                controls=[
                    secondary_button("Volver a raíz", lambda e: open_document_folder(root_path)),
                    secondary_button("Subir nivel", lambda e: open_document_parent_folder(data.get("current_path"), root_path)),
                    primary_button("Abrir carpeta Windows", lambda e: open_current_document_folder(data.get("current_path") or current_path)),
                    secondary_button("Ir a PARA PRESENTAR", open_para_presentar_in_browser),
                    secondary_button("Volcar datos en formulario", volcar_datos_formulario),
                ],
                spacing=10,
                wrap=True,
            ),
            bulk_action_bar(
                title="Documentos",
                selected_count=len(selected_docs),
                on_clear=clear_selected_documents,
                clear_tooltip="Limpiar selección",
                actions=[
                    {
                        "icon": ft.Icons.VISIBILITY,
                        "tooltip": "Ver seleccionados",
                        "on_click": open_selected_documents,
                    },
                ],
                compact=True,
            ),
            ft.Divider(),
            ft.Text(f"Carpetas ({len(folder_controls)})", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            *(folder_controls or [ft.Text("No hay subcarpetas directas", color=Q_MUTED, size=13)]),
            ft.Text(f"Archivos ({len(file_controls)}) · orden Mercurio: 01, 02, 10 primero; después alfabético", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            *(file_controls or [ft.Text("No hay archivos directos en esta carpeta", color=Q_MUTED, size=13)]),
            ft.Divider(),
            build_mercurio_box_status_content(expediente_id),
        ]

        return ft.Column(
            width=920,
            height=620,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=controls,
        )

    def set_dialog_section(section):
        state["dialog_section"] = section
        expediente_id = state.get("dialog_expediente_id")
        if section == "datos_especificos":
            return ft.Container(
                width=920,
                height=620,
                content=ft.Column(
                    controls=[
                        build_specific_data_content(expediente_id),
                        build_expediente_documents_inline(expediente_id),
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
            )

        if section == "trazabilidad":
            return build_traceability_content(expediente_id)

        if section == "automatizacion":
            return build_payload_preview_content(expediente_id)

        if section == "plantillas":
            return build_expedient_templates_content(expediente_id)

        return build_edit_content()


    def close_document_viewer_dialog(e=None):
        document_viewer_dialog.open = False
        page.update()

    def open_document_with_system(path, expediente_id=None):
        expediente_id = expediente_id or state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda o abre un expediente antes de abrir documentos.")
            return

        try:
            document_viewer_service.open_document(path, expediente_id=expediente_id)
        except Exception as exc:
            show_form_error(str(exc))

    def show_document_preview(path, title=None, expediente_id=None, page_number=1, zoom=1.6, queue=None, queue_index=0):
        expediente_id = expediente_id or state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda o abre un expediente antes de previsualizar documentos.")
            return

        try:
            preview = document_viewer_service.create_document_preview(path, expediente_id=expediente_id, page_number=page_number, zoom=zoom)
        except Exception as exc:
            show_form_error(str(exc))
            return

        controls = [
            ft.Text(str(title or path), weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text(str(path), size=11, color=Q_MUTED),
        ]

        preview_path = preview.get("preview_path") or ""
        current_page = int(preview.get("page_number") or page_number or 1)
        total_pages = int(preview.get("total_pages") or 1)
        current_zoom = float(preview.get("zoom") or zoom or 1.6)

        def _zoomed_preview_image(image_path, page_idx):
            zoomed_width = int(700 * float(current_zoom or 1.6))
            viewport_width = 920
            canvas_width = max(viewport_width, zoomed_width)

            return ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Container(
                        width=canvas_width,
                        alignment=ft.alignment.Alignment(0, 0),
                        content=ft.Image(
                            src=image_path,
                            width=zoomed_width,
                        ),
                    )
                ],
            )


        viewer_queue = queue or []
        try:
            current_queue_index = int(queue_index or 0)
        except Exception:
            current_queue_index = 0

        if viewer_queue:
            current_queue_index = max(0, min(current_queue_index, len(viewer_queue) - 1))

        viewer_scroll_state = state.setdefault("document_viewer_scroll_state", {})
        viewer_scroll_key = f"{expediente_id}|{path}|{current_zoom:.1f}"

        loaded_until_page = current_page
        if total_pages > 1 and preview.get("preview_type") == "pdf":
            try:
                loaded_until_page = int(viewer_scroll_state.get(viewer_scroll_key) or 0)
            except Exception:
                loaded_until_page = 0

            loaded_until_page = max(loaded_until_page, current_page + 3)
            loaded_until_page = min(total_pages, max(1, loaded_until_page))
            viewer_scroll_state[viewer_scroll_key] = loaded_until_page

        viewer_scroll_controls = state.setdefault("document_viewer_scroll_controls", {})
        viewer_scroll_loading = state.setdefault("document_viewer_scroll_loading", {})

        def _viewer_page_controls(page_idx, page_preview_path):
            return [
                ft.Container(
                    padding=ft.padding.only(top=8, bottom=2),
                    content=ft.Text(
                        f"Página {page_idx} de {total_pages}",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                ),
                _zoomed_preview_image(page_preview_path, page_idx),
                ft.Divider(),
            ]

        def load_more_viewer_pages(e=None):
            if not (total_pages > 1 and preview.get("preview_type") == "pdf"):
                return

            if viewer_scroll_loading.get(viewer_scroll_key):
                return

            current_loaded = int(viewer_scroll_state.get(viewer_scroll_key) or loaded_until_page or current_page)
            if current_loaded >= total_pages:
                return

            viewer_list = viewer_scroll_controls.get(viewer_scroll_key)
            if not viewer_list:
                return

            viewer_scroll_loading[viewer_scroll_key] = True
            try:
                new_loaded = min(total_pages, current_loaded + 3)

                for page_idx in range(current_loaded + 1, new_loaded + 1):
                    try:
                        page_preview = document_viewer_service.create_document_preview(
                            path,
                            expediente_id=expediente_id,
                            page_number=page_idx,
                            zoom=current_zoom,
                        )
                        page_preview_path = page_preview.get("preview_path") or ""
                    except Exception:
                        page_preview_path = ""

                    if page_preview_path:
                        viewer_list.controls.extend(_viewer_page_controls(page_idx, page_preview_path))

                viewer_scroll_state[viewer_scroll_key] = new_loaded

                if new_loaded >= total_pages:
                    viewer_list.controls.append(
                        ft.Text("Documento completo cargado.", size=11, color=Q_MUTED)
                    )

                page.update()
            finally:
                viewer_scroll_loading[viewer_scroll_key] = False

        def on_viewer_scroll(e):
            try:
                pixels = float(getattr(e, "pixels", 0) or 0)
                max_scroll = float(getattr(e, "max_scroll_extent", 0) or 0)
            except Exception:
                return

            if max_scroll > 0 and pixels >= max_scroll - 250:
                load_more_viewer_pages()

        if total_pages > 1:
            controls.append(
                ft.Text(
                    f"Página {current_page} de {total_pages}",
                    size=12,
                    color=Q_MUTED,
                )
            )

        if preview.get("ok") and preview_path:
            preview_controls = [
                ft.Text(f"Zoom: {current_zoom:.1f}x", size=11, color=Q_MUTED),
            ]

            if total_pages > 1 and preview.get("preview_type") == "pdf":
                # Carga progresiva: al abrir solo unas páginas; al final del scroll se amplía.
                visible_start_page = 1

                preview_controls.append(
                    ft.Text(
                        f"Vista rápida: páginas {visible_start_page}-{loaded_until_page} de {total_pages}. "
                        + ("Desplázate al final para cargar más." if loaded_until_page < total_pages else "Documento completo cargado."),
                        size=11,
                        color=Q_MUTED,
                    )
                )

                for page_idx in range(visible_start_page, loaded_until_page + 1):
                    try:
                        if page_idx == current_page:
                            page_preview_path = preview_path
                        else:
                            page_preview = document_viewer_service.create_document_preview(
                                path,
                                expediente_id=expediente_id,
                                page_number=page_idx,
                                zoom=current_zoom,
                            )
                            page_preview_path = page_preview.get("preview_path") or ""
                    except Exception:
                        page_preview_path = ""

                    if page_preview_path:
                        preview_controls.extend(_viewer_page_controls(page_idx, page_preview_path))
            else:
                preview_controls.append(
                    _zoomed_preview_image(preview_path, current_page)
                )

            controls.append(
                ft.Container(
                    expand=True,
                    bgcolor="#F8FAFC",
                    border_radius=12,
                    border=ft.border.all(1, Q_BORDER),
                    padding=8,
                    content=(
                        lambda viewer_list: (
                            viewer_scroll_controls.__setitem__(viewer_scroll_key, viewer_list) or viewer_list
                        )
                    )(
                        ft.ListView(
                            controls=preview_controls,
                            spacing=6,
                            expand=True,
                            auto_scroll=False,
                            on_scroll=on_viewer_scroll,
                        )
                    ),
                )
            )
        else:
            controls.append(
                ft.Container(
                    padding=16,
                    bgcolor="#FFF7ED",
                    border_radius=12,
                    border=ft.border.all(1, "#FED7AA"),
                    content=ft.Text(
                        preview.get("message") or "No hay preview disponible para este documento.",
                        color="#9A3412",
                    ),
                )
            )

        document_viewer_dialog.title = ft.Text("Visor documental", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
        document_viewer_dialog.content = ft.Container(
            width=980,
            height=680,
            content=ft.Column(
                controls=controls,
                spacing=10,
                expand=True,
            ),
        )
        actions = []

        if viewer_queue and len(viewer_queue) > 1:
            if current_queue_index > 0:
                prev_doc = viewer_queue[current_queue_index - 1]
                actions.append(
                    secondary_button(
                        "Doc anterior",
                        lambda e, d=prev_doc, q=viewer_queue, idx=current_queue_index - 1: show_document_preview(
                            d.get("path"), d.get("name"), expediente_id, 1, current_zoom, q, idx
                        ),
                    )
                )

            if current_queue_index < len(viewer_queue) - 1:
                next_doc = viewer_queue[current_queue_index + 1]
                actions.append(
                    primary_button(
                        "Doc siguiente",
                        lambda e, d=next_doc, q=viewer_queue, idx=current_queue_index + 1: show_document_preview(
                            d.get("path"), d.get("name"), expediente_id, 1, current_zoom, q, idx
                        ),
                    )
                )

        if total_pages > 1:
            if current_page > 1:
                actions.append(
                    secondary_button(
                        "Anterior",
                        lambda e, p=path, t=title, exp_id=expediente_id, pg=current_page - 1, z=current_zoom, q=viewer_queue, idx=current_queue_index: show_document_preview(p, t, exp_id, pg, z, q, idx),
                    )
                )

            if current_page < total_pages:
                actions.append(
                    primary_button(
                        "Siguiente",
                        lambda e, p=path, t=title, exp_id=expediente_id, pg=current_page + 1, z=current_zoom, q=viewer_queue, idx=current_queue_index: show_document_preview(p, t, exp_id, pg, z, q, idx),
                    )
                )

        if preview.get("ok") and preview_path:
            actions.append(
                secondary_button(
                    "Zoom -",
                    lambda e, p=path, t=title, exp_id=expediente_id, pg=current_page, z=max(0.8, current_zoom - 0.4), q=viewer_queue, idx=current_queue_index: show_document_preview(p, t, exp_id, pg, z, q, idx),
                )
            )
            actions.append(
                primary_button(
                    "Zoom +",
                    lambda e, p=path, t=title, exp_id=expediente_id, pg=current_page, z=min(3.5, current_zoom + 0.4), q=viewer_queue, idx=current_queue_index: show_document_preview(p, t, exp_id, pg, z, q, idx),
                )
            )

        actions.extend([
            secondary_button("Abrir con visor del sistema", lambda e, p=path, exp_id=expediente_id: open_document_with_system(p, exp_id)),
            secondary_button("Cerrar", close_document_viewer_dialog),
        ])

        document_viewer_dialog.actions = actions
        document_viewer_dialog.open = True
        page.update()

    def show_expediente_documents_dialog(e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda el expediente antes de cargar documentos.")
            return

        try:
            result = document_viewer_service.list_expediente_documents(expediente_id)
        except Exception as exc:
            show_form_error(str(exc))
            return

        docs = result.get("documents") or []
        root_path = result.get("root_path") or ""
        message = result.get("message") or ""

        document_cards = []
        for doc in docs[:500]:
            path = doc.get("path") or ""
            name = doc.get("name") or "-"
            rel = doc.get("relative_path") or ""
            folder = doc.get("folder_relative") or "Raíz"
            size_label = doc.get("size_label") or "-"
            modified_at = doc.get("modified_at") or "-"
            doc_type = doc.get("type") or "document"
            previewable = bool(doc.get("previewable"))

            document_cards.append(
                document_file_card(
                    name=name,
                    path=path,
                    relative_path=rel,
                    folder=folder,
                    size_label=size_label,
                    modified_at=f"Modificado: {modified_at}",
                    file_type=doc_type,
                    on_preview=lambda e, p=path, n=name: show_document_preview(p, n),
                    on_open=lambda e, p=path: open_document_with_system(p),
                )
            )

        if not document_cards:
            document_cards = [
                ft.Container(
                    padding=14,
                    border_radius=10,
                    bgcolor="#FFF7ED",
                    border=ft.border.all(1, "#FED7AA"),
                    content=ft.Text(message or "No se han encontrado documentos en la carpeta vinculada.", color="#9A3412"),
                )
            ]

        document_viewer_dialog.title = ft.Text("Documentos del expediente", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
        document_viewer_dialog.content = ft.Container(
            width=980,
            height=680,
            content=ft.Column(
                controls=[
                    ft.Text(f"Raíz documental: {root_path or '-'}", size=11, color=Q_MUTED),
                    ft.Text(f"Documentos encontrados: {result.get('total_documents') or 0}", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Column(
                        controls=document_cards,
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
        )
        document_viewer_dialog.actions = [
            secondary_button("Cerrar", close_document_viewer_dialog),
        ]
        document_viewer_dialog.open = True
        page.update()

    def build_expedient_templates_content(expediente_id):
        """
        Sección segura del diálogo de expediente para plantillas y formularios.

        Reutiliza el catálogo de plantillas EX ya disponible en la vista.
        Evita el NameError al entrar en la pestaña "Plantillas y formularios".
        """
        templates = _list_ex_document_templates_for_menu()

        template_controls = []

        for template in templates[:20]:
            label = (
                template.get("nombre")
                or template.get("codigo")
                or template.get("mapper_destino")
                or "Formulario"
            )
            subtitle = " · ".join(
                part
                for part in [
                    template.get("codigo"),
                    template.get("mapper_destino"),
                    template.get("template_type"),
                ]
                if part
            )

            template_controls.append(
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=Q_PRIMARY),
                            ft.Column(
                                controls=[
                                    ft.Text(label, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(subtitle or "Plantilla documental", size=11, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            secondary_button(
                                "Generar",
                                lambda e, t=template: generate_specific_ex_template(
                                    t,
                                    e,
                                    return_section="plantillas",
                                ),
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        if not template_controls:
            template_controls.append(
                ft.Container(
                    bgcolor="#FFFBEB",
                    border=ft.border.all(1, "#FDE68A"),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "No hay plantillas EX activas",
                                weight=ft.FontWeight.BOLD,
                                color="#92400E",
                            ),
                            ft.Text(
                                "Revisa el catálogo de plantillas documentales en Settings.",
                                size=12,
                                color="#92400E",
                            ),
                        ],
                        spacing=4,
                    ),
                )
            )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Plantillas y formularios",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    "Generación de formularios EX y modelos vinculados al expediente.",
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(height=1, color=Q_BORDER),
                ft.Column(
                    controls=template_controls,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            spacing=12,
            expand=True,
        )


    def build_dialog_section_content(expediente_id):
        section = state.get("dialog_section") or "ficha"

        if section == "documentacion":
            return build_documentacion_content(expediente_id)

        if section == "diagnostico":
            return build_diagnostic_content(expediente_id)

        if section == "datos_especificos":
            return build_specific_data_content(expediente_id)

        if section == "trazabilidad":
            return build_traceability_content(expediente_id)

        if section == "automatizacion":
            return build_payload_preview_content(expediente_id)

        if section == "plantillas":
            return build_expedient_templates_content(expediente_id)

        return build_edit_content()


    def build_expediente_dialog_content(expediente_id=None):
        """
        Ficha de expediente con menú interno.

        Evita un diálogo largo con scroll vertical general.
        El usuario navega por zonas: Ficha, Documentación, Diagnóstico,
        Datos específicos y Trazabilidad.
        """
        state["dialog_expediente_id"] = expediente_id

        if not state.get("dialog_section"):
            state["dialog_section"] = "ficha"

        menu_items = [
            ("Ficha", "ficha", ft.Icons.ARTICLE, "Datos base"),
            ("Datos específicos", "datos_especificos", ft.Icons.DYNAMIC_FORM, "Formulario"),
            ("Documentación", "documentacion", ft.Icons.FOLDER_OPEN, "Box / PARA PRESENTAR"),
            ("Plantillas y formularios", "plantillas", ft.Icons.DESCRIPTION, "EX / DOCX"),
            ("Diagnóstico", "diagnostico", ft.Icons.FACT_CHECK, "Estado documental"),
            ("Automatización", "automatizacion", ft.Icons.ROCKET_LAUNCH, "Payload mapper"),
            ("Trazabilidad", "trazabilidad", ft.Icons.TIMELINE, "Historial"),
        ]

        def _nav_button(label, section, icon, subtitle):
            selected = (state.get("dialog_section") or "ficha") == section

            def _go(e, target_section=section):
                state["dialog_section"] = target_section
                expediente_dialog.content = build_expediente_dialog_content(state.get("dialog_expediente_id"))
                page.update()

            return ft.Container(
                padding=10,
                border_radius=12,
                bgcolor="#EAF2FF" if selected else "#FFFFFF",
                border=ft.border.all(1, Q_PRIMARY if selected else Q_BORDER),
                on_click=_go,
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, color=Q_PRIMARY if selected else Q_MUTED),
                        ft.Column(
                            controls=[
                                ft.Text(label, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(subtitle, size=11, color=Q_MUTED),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )

        return ft.Container(
            width=1160,
            height=740,
            bgcolor="#FFFFFF",
            padding=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=260,
                        height=710,
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=18,
                        padding=14,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        content=ft.Column(
                            controls=[
                                ft.Container(
                                    bgcolor="#EAF3FF",
                                    border=ft.border.all(1, "#B9D7FF"),
                                    border_radius=16,
                                    padding=12,
                                    content=ft.Column(
                                        controls=[
                                            ft.Text("Menú expediente", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                            ft.Text("Ficha completa organizada por zonas.", size=11, color=Q_MUTED),
                                        ],
                                        spacing=2,
                                    ),
                                ),
                    *[_nav_button(label, section, icon, subtitle) for label, section, icon, subtitle in menu_items],
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        height=710,
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=18,
                        padding=16,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        content=ft.Container(
                            width=860,
                            height=678,
                            bgcolor="#FFFFFF",
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                            content=build_dialog_section_content(expediente_id),
                        ),
                    ),
                ],
                spacing=14,
            ),
        )


    admin_document_dialog = form_dialog(
        "Anexar documento administrativo",
        ft.Column(
            controls=[
                admin_document_selected_file,
                admin_document_event_type,
                admin_document_observaciones,
                ft.Text(
                    "Fase 1: se guarda la referencia del archivo y se registra el evento en trazabilidad. El cambio automático de estado administrativo se conectará en la siguiente fase.",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            width=760,
            height=300,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        actions=[
            secondary_button("Cancelar", close_admin_document_dialog),
            primary_button("Guardar evento", save_admin_document_event),
        ],
    )

    expediente_dialog = form_dialog(
        "Expediente",
        build_expediente_dialog_content(),
        actions=[
            secondary_button("Cancelar", close_dialog),
            primary_button("Guardar", save_expediente),
        ],
    )
    try:
        expediente_dialog.bgcolor = "#FFFFFF"
        expediente_dialog.surface_tint_color = "#FFFFFF"
    except Exception:
        pass
    page.overlay.append(expediente_dialog)
    def build_expediente_documents_inline(expediente_id=None):
        if not expediente_id:
            return ft.Container(
                padding=12,
                border_radius=12,
                bgcolor="#FFF7ED",
                border=ft.border.all(1, "#FED7AA"),
                content=ft.Text("Guarda el expediente para poder ver documentos.", color="#9A3412"),
            )

        try:
            result = document_viewer_service.list_expediente_documents(expediente_id)
        except Exception as exc:
            return ft.Container(
                padding=12,
                border_radius=12,
                bgcolor="#FEF2F2",
                border=ft.border.all(1, "#FECACA"),
                content=ft.Text(str(exc), color="#B42318"),
            )

        docs = result.get("documents") or []
        root_path = result.get("root_path") or ""
        message = result.get("message") or ""

        controls = [
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.FOLDER_OPEN, color=Q_PRIMARY),
                    ft.Column(
                        controls=[
                            ft.Text("Documentos del expediente", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(root_path or message or "Carpeta Box vinculada", size=11, color=Q_MUTED, selectable=True),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Text(f"{len(docs)} docs", size=12, color=Q_MUTED),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        ]

        if not docs:
            controls.append(ft.Text(message or "No hay documentos detectados.", size=13, color=Q_MUTED))
            return ft.Container(
                padding=12,
                border_radius=12,
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
                content=ft.Column(controls=controls, spacing=10),
            )

        document_rows = []
        current_folder = None

        for doc in docs[:500]:
            doc_path = doc.get("path") or ""
            name = doc.get("name") or "-"
            rel = doc.get("relative_path") or ""
            folder = doc.get("folder_relative") or "Raíz"
            size_label = doc.get("size_label") or "-"
            modified_at = doc.get("modified_at") or "-"
            doc_type = doc.get("type") or "document"

            if folder != current_folder:
                current_folder = folder
                document_rows.append(
                    ft.Container(
                        padding=ft.padding.only(top=10, bottom=2),
                        content=ft.Text(str(folder), weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    )
                )

            icon = ft.Icons.PICTURE_AS_PDF if doc_type == "pdf" else ft.Icons.IMAGE if doc_type == "image" else ft.Icons.DESCRIPTION

            document_rows.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    border=ft.border.all(1, Q_BORDER),
                    bgcolor="#FFFFFF",
                    content=ft.Row(
                        controls=[
                            ft.Icon(icon, color=Q_PRIMARY),
                            ft.Checkbox(
                                label="Ver",
                                value=False,
                                on_change=lambda e, p=doc_path, n=name: (
                                    show_document_preview(p, n),
                                    setattr(e.control, "value", False),
                                    page.update(),
                                ) if e.control.value else None,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(name, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(f"{size_label} · {modified_at}", size=11, color=Q_MUTED),
                                    ft.Text(rel, size=10, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            secondary_button("Abrir", lambda e, p=doc_path: open_document_with_system(p)),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        controls.append(
            ft.Container(
                height=470,
                padding=8,
                border_radius=12,
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
                content=ft.Column(
                    controls=document_rows,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
            )
        )

        if len(docs) > 500:
            controls.append(ft.Text("Se muestran los primeros 500 documentos.", size=11, color=Q_MUTED))

        return ft.Container(
            padding=12,
            border_radius=12,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            content=ft.Column(controls=controls, spacing=10),
        )

    document_viewer_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Visor documental"),
        content=ft.Container(width=980, height=680, content=ft.Text("Sin documento")),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(document_viewer_dialog)
    box_folder_options_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Carpetas Box candidatas"),
        content=ft.Container(width=900, height=620, content=ft.Text("Sin datos")),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(box_folder_options_dialog)
    page.overlay.append(admin_document_dialog)

    def open_new(e=None, cliente_id=None):
        if not cliente_options:
            set_message(error_alert("No hay clientes activos para crear expedientes"))
            refresh()
            return
        clear_form()

        if cliente_id:
            selected_cliente = next(
                (option for option in cliente_options if option.startswith(str(cliente_id) + " - ")),
                "",
            )
            if selected_cliente:
                cliente.set_value(selected_cliente, update=False)

        refresh_subtipo_options_for_tipo(tipo_value=tipo_expediente.get_value(), reset_value=True)
        state["dialog_section"] = "ficha"
        state["dialog_expediente_id"] = None
        state.pop("payload_preview_fullscreen", None)
        expediente_dialog.title = ft.Text("Nuevo expediente", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
        expediente_dialog.content = build_expediente_dialog_content()
        expediente_dialog.open = True
        page.update()

    def open_edit(expediente):
        load_form(expediente)
        expediente_id = expediente.get("id")
        state["dialog_section"] = "ficha"
        state["dialog_expediente_id"] = expediente_id
        state["specific_field_controls"] = {}
        state["specific_live_values"] = {}
        state.pop("payload_preview_fullscreen", None)
        state.setdefault("document_browser_path", {}).pop(int(expediente_id), None)
        _get_mercurio_box_status(expediente_id, force=True)
        expediente_dialog.title = ft.Text("Ficha completa del expediente", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        expediente_dialog.open = True
        page.update()
        scan_expediente_box_in_background(expediente_id)

    def open_new_expediente_from_client_navigation():
        pending_client_id = getattr(page, "new_expediente_client_id", None)
        page.new_expediente_client_id = None

        if not pending_client_id:
            return

        try:
            pending_client_id = int(pending_client_id)
        except (TypeError, ValueError):
            return

        open_new(cliente_id=pending_client_id)

    def open_pending_expediente_from_navigation():
        pending_id = getattr(page, "open_expediente_id", None)
        page.open_expediente_id = None

        if not pending_id:
            return

        try:
            pending_id = int(pending_id)
        except (TypeError, ValueError):
            return

        expediente = next(
            (item for item in state.get("expedientes", []) if int(item.get("id") or 0) == pending_id),
            None,
        )

        if expediente:
            open_edit(expediente)
        else:
            set_message(error_alert(f"No se encontró el expediente #{pending_id} para abrir la ficha"))
            refresh()


    def get_single_selected_expediente():
        if len(state["selected_ids"]) != 1:
            return None

        selected_id = next(iter(state["selected_ids"]))
        return next(
            (expediente for expediente in state["expedientes"] if expediente.get("id") == selected_id),
            None,
        )

    def open_selected_expediente(e=None):
        expediente = get_single_selected_expediente()
        if not expediente:
            set_message(error_alert("Selecciona un único expediente para abrir la ficha"))
            refresh()
            return
        open_edit(expediente)

    def enqueue_selected_presentation(e=None):
        expediente = get_single_selected_expediente()
        if not expediente:
            set_message(error_alert("Selecciona un único expediente para enviar a cola de presentación"))
            refresh()
            return

        try:
            expedient_service.validate_expediente_para_presentar_ready(expediente.get("id"))
            result = presentation_queue_service.enqueue_expediente(expediente.get("id"))
            set_message(success_alert(result.get("message") or "Expediente enviado a cola de presentación"))

            try:
                trace_service.registrar_evento(
                    expediente_id=expediente["id"],
                    cliente_id=expediente["cliente_id"],
                    tipo_evento="COLA_PRESENTACION",
                    titulo="EXPEDIENTE ENVIADO A COLA DE PRESENTACION",
                    descripcion="El expediente se incorpora a la cola de presentación asistida.",
                    entidad_relacionada="expedientes",
                    entidad_relacionada_id=expediente["id"],
                    usuario="ERP",
                )
            except Exception:
                pass

        except Exception as exc:
            set_message(error_alert(str(exc)))

        refresh()


    def open_presentacion_asistida(e=None):
        expediente = get_single_selected_expediente()
        if not expediente:
            set_message(error_alert("Selecciona un único expediente para iniciar la presentación asistida"))
            refresh()
            return

        try:
            expedient_service.validate_expediente_para_presentar_ready(expediente.get("id"))
            context = presentation_assistant_service.start_presentation_for_expediente(expediente)
            state["presentation_context"] = context
            state["presentation_start"] = context.get("started_at")
            state["presentation_url"] = (context.get("config") or {}).get("url_presentacion")

            try:
                trace_service.registrar_evento(
                    expediente_id=expediente["id"],
                    cliente_id=expediente["cliente_id"],
                    tipo_evento="PRESENTACION_ASISTIDA",
                    titulo="PRESENTACION ASISTIDA INICIADA",
                    descripcion=f"Se inicia presentación asistida en: {state['presentation_url']}",
                    entidad_relacionada="expedientes",
                    entidad_relacionada_id=expediente["id"],
                    usuario="ERP",
                )
            except Exception:
                # No bloquea la presentación si falla el registro del evento.
                pass

            set_message(
                success_alert(
                    "Presentación asistida iniciada. Chrome se ha abierto con la URL configurada."
                )
            )

            load_form(expediente)
            state["dialog_section"] = "diagnostico"
            state["dialog_expediente_id"] = expediente.get("id")

            expediente_dialog.title = ft.Text(
                "Presentación asistida del expediente",
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            )
            expediente_dialog.content = ft.Container(
                width=980,
                height=720,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=14,
                    controls=[
                        ft.Text(
                            "Presentación asistida iniciada",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                        ),
                        success_alert("Navegador abierto correctamente"),
                        ft.Text(
                            f"URL: {state.get('presentation_url') or '-'}",
                            size=13,
                            color=Q_MUTED,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Inicio: {state['presentation_start'].strftime('%d/%m/%Y %H:%M:%S') if state.get('presentation_start') else '-'}",
                            size=13,
                            color=Q_MUTED,
                        ),
                        ft.Divider(),
                        ft.Text("1. Datos de presentación", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Row([estado_presentacion, fecha_presentacion, numero_registro], wrap=True, spacing=10),
                        ft.Row([organo_presentacion, provincia, responsable], wrap=True, spacing=10),
                        ft.Text("2. Diagnóstico documental", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        build_diagnostic_content(expediente.get("id")),
                        ft.Text("3. Trazabilidad", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        build_traceability_content(expediente.get("id")),
                        ft.Text(
                            "Siguiente paso: cuando estés en la pantalla correcta, obtén el page source y lo analizamos.",
                            size=12,
                            color=Q_MUTED,
                        ),
                        form_message,
                    ],
                ),
            )
            expediente_dialog.open = True
            page.update()

        except Exception as exc:
            set_message(error_alert(str(exc)))
            refresh()

    def archive_selected(e=None):
        for expediente_id in list(state["selected_ids"]):
            expedient_service.archive_expediente(expediente_id)
        state["selected_ids"].clear()
        set_message(success_alert("Expedientes archivados"))
        refresh_table()

    def toggle_selection(expediente_id, row_ref=None, checkbox_ref=None, index=0):
        if expediente_id in state["selected_ids"]:
            state["selected_ids"].remove(expediente_id)
        else:
            state["selected_ids"].add(expediente_id)

        is_selected = expediente_id in state["selected_ids"]

        if row_ref and row_ref.current:
            row_ref.current.bgcolor = "#EAF3FF" if is_selected else ("#FAFBFC" if index % 2 else "#FFFFFF")
        if checkbox_ref and checkbox_ref.current:
            checkbox_ref.current.value = is_selected

        content_area.content = build_view()
        page.update()

    def build_table():
        expedientes = state["expedientes"]
        if not expedientes:
            return empty_state("No hay expedientes que coincidan con la búsqueda")

        cards = []

        for index, e in enumerate(expedientes):
            expediente_id = e["id"]
            is_selected = expediente_id in state["selected_ids"]

            checkbox = ft.Checkbox(
                value=is_selected,
                on_change=lambda ev, eid=expediente_id, idx=index: toggle_selection(eid, index=idx),
            )

            tipo_label = e.get("tipo_expediente_nombre") or "-"
            subtipo_label = e.get("subtipo_expediente_nombre") or e.get("subtipo_expediente") or "-"
            external_number = (
                e.get("numero_expediente_mercurio")
                or e.get("numero_registro")
                or e.get("numero_expediente_externo")
                or e.get("numero_mercurio")
                or e.get("expediente_mercurio")
                or ""
            )
            box_label = _box_path_label(e)
            box_color = _box_path_color(e)

            cards.append(
                card_item(
                    title=(_cliente_nombre(e) or "-").upper(),
                    subtitle=f"Expediente interno CRM: {e.get('numero_expediente') or '-'}",
                    leading=checkbox,
                    selected=is_selected,
                    on_click=lambda ev, eid=expediente_id, idx=index: toggle_selection(eid, index=idx),
                    badges=[
                        expedient_status_badge("Extranjería", "#0057B8"),
                        expedient_status_badge(e.get("estado_documental_nombre"), e.get("estado_documental_color")),
                        expedient_status_badge(e.get("estado_administrativo_nombre"), e.get("estado_administrativo_color")),
                        priority_badge(e.get("prioridad_nombre"), e.get("prioridad_color")),
                    ],
                    body=[
                        ft.Row(
                            controls=[
                                ft.Text("Tipo:", size=11, color=Q_MUTED),
                                ft.Text(tipo_label, size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Subtipo:", size=11, color=Q_MUTED),
                                ft.Text(subtipo_label, size=12, color=Q_PRIMARY_DARK),
                            ],
                            spacing=6,
                            wrap=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.CONFIRMATION_NUMBER_OUTLINED,
                                    size=16,
                                    color=Q_PRIMARY if external_number else "#B42318",
                                ),
                                ft.Text(
                                    "Nº expediente:",
                                    size=12,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    external_number or "SIN NÚMERO DE EXPEDIENTE",
                                    size=14,
                                    color=Q_PRIMARY_DARK if external_number else "#B42318",
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=6,
                            wrap=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.FOLDER_OPEN, size=15, color=box_color),
                                ft.Text(box_label, size=12, color=box_color, weight=ft.FontWeight.W_600),
                            ],
                            spacing=6,
                            wrap=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    footer=[
                        ft.Row(
                            controls=[
                                ft.Text(
                                    f"Apertura: {_date_to_display(e.get('fecha_apertura'))}",
                                    size=11,
                                    color=Q_MUTED,
                                ),
                                ft.Text(
                                    f"Responsable: {e.get('responsable') or '-'}",
                                    size=11,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=14,
                            wrap=True,
                        )
                    ],
                    padding=12,
                )
            )

        return ft.Container(
            height=430,
            content=ft.Column(
                controls=cards,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )

    def archive_one(expediente_id):
        expedient_service.archive_expediente(expediente_id)
        state["selected_ids"].discard(expediente_id)
        set_message(success_alert("Expediente archivado"))
        refresh_table()

    def refresh_table(e=None):
        clear_message()
        load_data()
        table_container.content = build_table()
        content_area.content = build_view()
        page.update()

    def refresh(e=None):
        load_data()
        table_container.content = build_table()
        content_area.content = build_view()
        page.update()

    def metrics():
        expedientes = state["expedientes"]
        return {
            "total": len(expedientes),
            "presentados": sum(1 for e in expedientes if (e.get("estado_administrativo_nombre") or "").upper() == "PRESENTADO"),
            "requeridos": sum(1 for e in expedientes if (e.get("estado_administrativo_nombre") or "").upper() == "REQUERIDO"),
            "incompletos": sum(1 for e in expedientes if "INCOMPLETA" in (e.get("estado_documental_nombre") or "").upper()),
        }

    def build_selected_action_bar():
        selected_count = len(state["selected_ids"])
        if selected_count == 0:
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Selecciona un expediente para ver acciones rápidas.",
                    size=13,
                    color=Q_MUTED,
                ),
            )

        single_selected = selected_count == 1
        return ft.Container(
            bgcolor="#EAF3FF",
            border=ft.border.all(1, "#B9D7FF"),
            border_radius=12,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Text(
                        f"{selected_count} expediente(s) seleccionado(s)",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        f"Presentación iniciada: {state['presentation_start'].strftime('%H:%M:%S')}" if state.get("presentation_start") else "",
                        size=12,
                        color=Q_MUTED,
                        visible=state.get("presentation_start") is not None,
                    ),
                    primary_button("Abrir ficha", open_selected_expediente),
                    secondary_button("Enviar a cola", enqueue_selected_presentation),
                    secondary_button("Presentación asistida", open_presentacion_asistida),
                    danger_button("Archivar selección", archive_selected),
                    ft.Text(
                        "Para abrir ficha o presentación asistida selecciona solo uno.",
                        size=12,
                        color=Q_MUTED,
                        visible=not single_selected,
                    ),
                ],
                spacing=10,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def build_view():
        m = metrics()
        message = state["message"]

        controls = [
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("Expedientes", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text("Control operativo de asuntos jurídicos y administrativos", size=14, color=Q_MUTED),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    primary_button("Nuevo expediente", open_new),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]

        if message:
            controls.append(message)

        controls.extend(
            [
                ft.Row(
                    controls=[
                        metric_card("Expedientes activos", m["total"]),
                        metric_card("Presentados", m["presentados"]),
                        metric_card("Requeridos", m["requeridos"]),
                        metric_card("Doc. incompleta", m["incompletos"]),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                build_selected_action_bar(),
                filter_bar(
                    dropdown=filtro_estado,
                    search_input=search_input,
                    actions=[
                        filtro_cliente.control,
                        filtro_tipo,
                        filtro_prioridad,
                    ],
                ),
                table_container,
            ]
        )

        return ft.Column(
            controls=controls,
            spacing=18,
            expand=True,
        )

    original_filtro_select = filtro_cliente.select

    def filtro_select_and_refresh(selected):
        original_filtro_select(selected)
        refresh()

    filtro_cliente.select = filtro_select_and_refresh

    search_input.on_change = refresh
    original_filtro_cliente_change = filtro_cliente.input.on_change

    def on_filtro_cliente_change(e=None):
        if original_filtro_cliente_change:
            original_filtro_cliente_change(e)
        refresh()

    filtro_cliente.input.on_change = on_filtro_cliente_change
    filtro_tipo.on_change = refresh
    filtro_estado.on_change = refresh
    filtro_prioridad.on_change = refresh

    load_data()
    table_container.content = build_table()
    content_area.content = build_view()
    open_new_expediente_from_client_navigation()
    open_pending_expediente_from_navigation()
    return content_area

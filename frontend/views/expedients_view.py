import threading
import json
import csv
import sqlite3
from pathlib import Path

import flet as ft
from datetime import datetime

from backend.services import expedient_service
from backend.services import expedient_document_state_service as document_state_service
from backend.services import expedient_traceability_service as trace_service
from backend.services import presentation_assistant_service
from backend.services import expedient_dynamic_form_service as dynamic_form_service
from backend.services import expedient_snapshot_service as snapshot_service
from backend.services import document_template_service
from backend.services import document_docx_service
from backend.services import mapper_preview_service
from backend.services.list_expediente_box_directory import list_expediente_box_directory, list_para_presentar_documents
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.app_text_field import text_input, required_text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_dialog import form_dialog
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import app_table
from frontend.components.app_filter_bar import filter_bar
from frontend.components.app_card import metric_card
from frontend.components.app_action_row import action_row
from frontend.components.expedient_status_badge import expedient_status_badge, priority_badge
from frontend.components.app_autocomplete import AppAutocomplete

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


def expedients_view(page: ft.Page):
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
        "specific_formulario_id": None,
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
            else:
                expedient_service.create_expediente(data)
                set_message(success_alert("Expediente creado"))
            close_dialog()
            refresh_table()
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

        values = {
            codigo: _dynamic_value(control)
            for codigo, control in state.get("specific_field_controls", {}).items()
        }

        try:
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
            result = snapshot_service.save_snapshot(expediente_id, created_by="ERP")
            state.setdefault("snapshot_status", {})[int(expediente_id)] = result
            clear_form_message()

            if result.get("validated"):
                set_message(success_alert(f"Snapshot generado correctamente · versión {result.get('version')}"))
            else:
                errors = result.get("errors") or []
                set_message(error_alert("Snapshot generado con advertencias:\n- " + "\n- ".join(errors)))

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
        state["specific_formulario_id"] = formulario.get("id") if formulario else None

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
            controls.extend(
                [
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
                    ),
                ]
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
                        ft.Text("Solo se guarda una ruta de referencia. El ERP no manipula Box en esta fase.", size=12, color=Q_MUTED),
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

            faltantes_controls = [
                ft.Text(f"• {f.get('nombre') or f.get('codigo')}", color="#B42318", size=13)
                for f in result.get("faltantes", [])
            ] or [ft.Text("No hay faltantes", color="#027A48", size=13)]

            encontrados_controls = [
                ft.Text(f"• {f.get('nombre') or f.get('codigo')}", color="#027A48", size=13)
                for f in result.get("encontrados", [])
            ] or [ft.Text("No hay documentos encontrados por regla", color=Q_MUTED, size=13)]

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

        file_controls = []
        for file in sorted(data.get("files", []), key=_mercurio_file_sort_key):
            file_controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    border=ft.border.all(1, Q_BORDER),
                    bgcolor="#FFFFFF",
                    content=ft.Row(
                        controls=[
                            ft.Text("📄", size=18),
                            ft.Container(
                                width=34,
                                content=ft.Text(_mercurio_file_order_label(file), size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(file.get("name") or "-", weight=ft.FontWeight.W_500),
                                    ft.Text(file.get("path") or "", size=11, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Text(_format_file_size(file.get("size")), color=Q_MUTED, size=12),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        controls = [
            ft.Row(
                controls=[
                    ft.Text("Documentación Box", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
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
        expediente_dialog.content = build_expediente_dialog_content(state.get("dialog_expediente_id"))
        page.update()

    def _nav_button(label, section, icon, subtitle=""):
        is_active = state.get("dialog_section") == section
        return ft.Container(
            bgcolor="#EAF3FF" if is_active else "#FFFFFF",
            border=ft.border.all(1, "#B9D7FF" if is_active else Q_BORDER),
            border_radius=14,
            padding=10,
            ink=True,
            on_click=lambda e, s=section: set_dialog_section(s),
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, size=18, color=Q_PRIMARY if is_active else Q_MUTED),
                        bgcolor="#FFFFFF" if is_active else "#F8FAFC",
                        border_radius=18,
                        width=36,
                        height=36,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(label, size=13, weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_600, color=Q_PRIMARY_DARK if is_active else "#101828"),
                            ft.Text(subtitle, size=10, color=Q_MUTED),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                ],
                spacing=9,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )



    def _load_docx_templates_for_expediente():
        """Carga únicamente plantillas DOCX/Word activas sin tocar lógica de snapshot ni automatización."""
        try:
            templates = document_template_service.list_document_templates(active_only=True)
        except Exception:
            return []

        return [
            template for template in (templates or [])
            if str(template.get("template_type") or "").strip().lower() in ("docx", "word")
        ]

    def generate_docx_from_expedient(template_id, e=None):
        expediente_id = state.get("dialog_expediente_id") or state.get("editing_id")
        if not expediente_id:
            show_form_error("Guarda primero el expediente antes de generar documentos")
            return

        try:
            result = document_docx_service.generate_docx_from_template(
                template_id,
                expediente_id=expediente_id,
                auto_build_snapshot=True,
            )
            state.setdefault("expedient_docx_result", {})[int(expediente_id)] = result
            state.setdefault("expedient_docx_error", {}).pop(int(expediente_id), None)
            clear_form_message()
            set_message(success_alert("Documento generado correctamente"))
        except Exception as exc:
            state.setdefault("expedient_docx_result", {}).pop(int(expediente_id), None)
            state.setdefault("expedient_docx_error", {})[int(expediente_id)] = str(exc)

        state["dialog_section"] = "plantillas"
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        page.update()

    def _docx_template_card(template):
        template_id = template.get("id")
        nombre = template.get("nombre") or template.get("codigo") or "Plantilla"
        codigo = template.get("codigo") or "-"
        categoria = template.get("categoria") or "-"
        mapper = template.get("mapper_destino") or "-"
        alcance = "Expediente" if int(template.get("requiere_expediente") or 0) else "General"

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.DESCRIPTION, size=20, color=Q_PRIMARY),
                        bgcolor="#EAF3FF",
                        border_radius=20,
                        width=40,
                        height=40,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(nombre, size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(f"{codigo} · {categoria} · {alcance}", size=11, color=Q_MUTED),
                            ft.Text(f"Mapper destino: {mapper}", size=11, color=Q_MUTED, selectable=True),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    primary_button("Generar DOCX", lambda ev, tid=template_id: generate_docx_from_expedient(tid, ev)),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def build_expedient_templates_content(expediente_id):
        if not expediente_id:
            return ft.Container(
                width=920,
                height=620,
                content=empty_state("Guarda el expediente para poder generar documentos"),
            )

        expediente_id = int(expediente_id)
        templates = _load_docx_templates_for_expediente()
        result = state.setdefault("expedient_docx_result", {}).get(expediente_id)
        error = state.setdefault("expedient_docx_error", {}).get(expediente_id)

        controls = [
            ft.Container(
                bgcolor="#EAF3FF",
                border=ft.border.all(1, "#B9D7FF"),
                border_radius=16,
                padding=14,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.DESCRIPTION, size=24, color=Q_PRIMARY),
                            bgcolor="#FFFFFF",
                            border_radius=24,
                            width=48,
                            height=48,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("Plantillas documentales", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Genera DOCX desde plantillas registradas usando el payload del mapper.", size=13, color=Q_MUTED),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ]

        if error:
            controls.append(error_alert(error))

        if result:
            output = result.get("output") or {}
            docx = result.get("docx") or {}
            unresolved = docx.get("unresolved_placeholders") or []
            controls.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        spacing=5,
                        controls=[
                            ft.Text("Último DOCX generado", size=14, weight=ft.FontWeight.BOLD, color="#027A48"),
                            ft.Text(output.get("docx_path") or docx.get("docx_path") or "-", size=12, color=Q_PRIMARY_DARK, selectable=True),
                            ft.Text(
                                f"Placeholders pendientes: {len(unresolved)}" + (" · " + ", ".join(unresolved[:6]) if unresolved else ""),
                                size=12,
                                color="#B42318" if unresolved else Q_MUTED,
                                selectable=True,
                            ),
                        ],
                    ),
                )
            )

        if not templates:
            controls.append(empty_state("No hay plantillas DOCX activas configuradas"))
        else:
            controls.extend(_docx_template_card(template) for template in templates)

        return ft.Column(
            width=920,
            height=620,
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
            controls=controls,
        )

    def build_justificantes_content(expediente_id):
        if not expediente_id:
            return empty_state("Guarda el expediente para poder ver justificantes")

        try:
            resumen = trace_service.get_resumen_trazabilidad(expediente_id)
            justificantes = resumen.get("justificantes", [])

            rows = [
                [
                    j.get("archivo_nombre") or "-",
                    j.get("archivo_ruta") or "-",
                    _date_to_display(j.get("fecha_presentacion")),
                    j.get("numero_registro") or "-",
                    j.get("estado_conciliacion") or "-",
                ]
                for j in justificantes
            ]

            if not rows:
                return empty_state("No hay justificantes cargados")

            return app_table(
                ["Archivo", "Ruta", "Fecha presentación", "Registro", "Estado"],
                rows,
                height=520,
            )
        except Exception as exc:
            return error_alert(str(exc))

    def build_hojas_content(expediente_id):
        if not expediente_id:
            return empty_state("Guarda el expediente para poder ver hojas de encargo")

        try:
            resumen = trace_service.get_resumen_trazabilidad(expediente_id)
            hojas = resumen.get("hojas_encargo", [])

            rows = [
                [
                    h.get("numero_hoja") or "-",
                    _date_to_display(h.get("fecha_firma")),
                    h.get("procedimiento") or "-",
                    f"{float(h.get('importe_neto') or 0):.2f} €",
                    h.get("estado_firma") or h.get("estado") or "-",
                ]
                for h in hojas
            ]

            if not rows:
                return empty_state("No hay hojas de encargo asociadas")

            return app_table(
                ["Nº hoja", "Firma", "Procedimiento", "Importe neto", "Estado"],
                rows,
                height=520,
            )
        except Exception as exc:
            return error_alert(str(exc))

    def build_consultas_content(expediente_id):
        if not expediente_id:
            return empty_state("Guarda el expediente para poder ver consultas aplicadas")

        try:
            resumen = trace_service.get_resumen_trazabilidad(expediente_id)
            consultas = resumen.get("consultas_aplicadas", [])

            rows = [
                [
                    _date_to_display(c.get("fecha_consulta")),
                    f"{float(c.get('importe_aplicado') or 0):.2f} €",
                    f"{float(c.get('importe_original') or 0):.2f} €",
                    c.get("observaciones") or "-",
                ]
                for c in consultas
            ]

            if not rows:
                return empty_state("No hay consultas aplicadas")

            return app_table(
                ["Fecha consulta", "Aplicado", "Importe original", "Observaciones"],
                rows,
                height=520,
            )
        except Exception as exc:
            return error_alert(str(exc))

    def build_historial_content(expediente_id):
        if not expediente_id:
            return empty_state("Guarda el expediente para poder ver historial")

        try:
            resumen = trace_service.get_resumen_trazabilidad(expediente_id)
            eventos = resumen.get("eventos", [])

            rows = [
                [
                    _date_to_display(ev.get("fecha_evento")),
                    ev.get("tipo_evento") or "-",
                    ev.get("titulo") or "-",
                    ev.get("descripcion") or "-",
                ]
                for ev in eventos
            ]

            if not rows:
                return empty_state("No hay eventos registrados")

            return app_table(
                ["Fecha", "Tipo", "Título", "Descripción"],
                rows,
                height=520,
            )
        except Exception as exc:
            return error_alert(str(exc))

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
            ("Plantillas", "plantillas", ft.Icons.DESCRIPTION, "Generar DOCX"),
            ("Diagnóstico", "diagnostico", ft.Icons.FACT_CHECK, "Estado documental"),
            ("Automatización", "automatizacion", ft.Icons.ROCKET_LAUNCH, "Payload mapper"),
            ("Trazabilidad", "trazabilidad", ft.Icons.TIMELINE, "Historial"),
        ]

        return ft.Container(
            width=1160,
            height=740,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=260,
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=18,
                        padding=14,
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
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=18,
                        padding=16,
                        content=ft.Column(
                            controls=[
                                build_dialog_section_content(expediente_id),
                            ],
                            spacing=12,
                        ),
                    ),
                ],
                spacing=14,
            ),
        )

    expediente_dialog = form_dialog(
        "Expediente",
        build_expediente_dialog_content(),
        actions=[
            secondary_button("Cancelar", close_dialog),
            primary_button("Guardar", save_expediente),
        ],
    )
    page.overlay.append(expediente_dialog)

    def open_new(e=None):
        if not cliente_options:
            set_message(error_alert("No hay clientes activos para crear expedientes"))
            refresh()
            return
        clear_form()
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
        state.pop("payload_preview_fullscreen", None)
        state.setdefault("document_browser_path", {}).pop(int(expediente_id), None)
        _get_mercurio_box_status(expediente_id, force=True)
        expediente_dialog.title = ft.Text("Ficha completa del expediente", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
        expediente_dialog.content = build_expediente_dialog_content(expediente_id)
        expediente_dialog.open = True
        page.update()
        scan_expediente_box_in_background(expediente_id)

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

        rows = []
        for index, e in enumerate(expedientes):
            row_ref = ft.Ref()
            checkbox_ref = ft.Ref()
            is_selected = e["id"] in state["selected_ids"]

            checkbox = ft.Checkbox(
                ref=checkbox_ref,
                value=is_selected,
                on_change=lambda ev, eid=e["id"], rr=row_ref, cr=checkbox_ref, idx=index: toggle_selection(eid, rr, cr, idx),
            )

            rows.append(
                [
                    {
                        "selected": is_selected,
                        "row_ref": row_ref,
                        "on_click": lambda ev, eid=e["id"], rr=row_ref, cr=checkbox_ref, idx=index: toggle_selection(eid, rr, cr, idx),
                    },
                    checkbox,
                    ft.Text(e.get("numero_expediente") or "-", weight=ft.FontWeight.BOLD, size=13),
                    _cliente_nombre(e),
                    e.get("tipo_expediente_nombre") or "-",
                    e.get("subtipo_expediente_nombre") or e.get("subtipo_expediente") or "-",
                    ft.Text(_box_path_label(e), size=12, color=_box_path_color(e), weight=ft.FontWeight.W_600),
                    expedient_status_badge(e.get("estado_documental_nombre"), e.get("estado_documental_color")),
                    expedient_status_badge(e.get("estado_administrativo_nombre"), e.get("estado_administrativo_color")),
                    priority_badge(e.get("prioridad_nombre"), e.get("prioridad_color")),
                    _date_to_display(e.get("fecha_apertura")),
                    e.get("responsable") or "-",
                ]
            )

        return app_table(
            headers=[
                {"key": "Sel", "label": "Sel", "width": 70},
                {"key": "Nº", "label": "Nº expediente", "width": 150},
                {"key": "Cliente", "label": "Cliente", "width": 260},
                {"key": "Tipo", "label": "Tipo", "width": 200},
                {"key": "Subtipo", "label": "Subtipo", "width": 240},
                {"key": "Box", "label": "Vinculación Box", "width": 260},
                {"key": "Documental", "label": "Documental", "width": 210},
                {"key": "Administrativo", "label": "Administrativo", "width": 210},
                {"key": "Prioridad", "label": "Prioridad", "width": 130},
                {"key": "Apertura", "label": "Apertura", "width": 120},
                {"key": "Responsable", "label": "Responsable", "width": 160},
            ],
            rows=rows,
            height=430,
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
    return content_area

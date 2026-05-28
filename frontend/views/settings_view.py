import json

import flet as ft

from backend.services import config_service
from backend.services import expedient_dynamic_form_service as dynamic_form_service
from backend.services import expedient_service
from backend.services import expedient_snapshot_service as snapshot_service
from backend.services import form_mapper_service
from backend.services import form_mapper_admin_service as mapper_admin_service
from backend.services import mapper_preview_service
from backend.services import presentation_config_service
from backend.services import document_template_service
from backend.services import document_generation_service
from backend.services import document_docx_service
from backend.services import pdf_fill_service
from backend.services import pdf_template_service
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.app_text_field import text_input, required_text_input, multiline_input
from frontend.components.app_dropdown import select_input
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_empty_state import empty_state
from frontend.components.app_table import app_table
from frontend.components.settings_sidebar import settings_sidebar
from frontend.components.config_section_card import config_section_card

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_BORDER = "#E4E7EC"
Q_MUTED = "#64748B"



def _mapper_actions_menu(on_test=None, on_export=None, on_generate_docx=None, on_generate_pdf=None, on_export_pdf_fields=None, on_export_pdf_overlay=None, on_edit=None, on_delete=None):
    """
    Menú compacto para la columna Acciones de Mappers / Mapper Blocks.

    Compatibilidad Flet:
    PopupMenuItem no acepta text= ni icon= en esta versión.
    Usamos content=ft.Text(...).
    """
    items = []

    if on_test:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Probar"),
                on_click=on_test,
            )
        )

    if on_export:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Exportar payload"),
                on_click=on_export,
            )
        )

    if on_generate_docx:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Generar DOCX"),
                on_click=on_generate_docx,
            )
        )

    if on_generate_pdf:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Generar PDF"),
                on_click=on_generate_pdf,
            )
        )

    if on_export_pdf_fields:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Generar fields.json"),
                on_click=on_export_pdf_fields,
            )
        )

    if on_export_pdf_overlay:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Generar overlay campos"),
                on_click=on_export_pdf_overlay,
            )
        )

    if on_edit:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Editar"),
                on_click=on_edit,
            )
        )

    if on_delete:
        items.append(
            ft.PopupMenuItem(
                content=ft.Text("Eliminar"),
                on_click=on_delete,
            )
        )

    return ft.PopupMenuButton(
        tooltip="Acciones",
        icon=ft.Icons.MORE_VERT,
        items=items,
    )


def _bool_options():
    return ["Sí", "No"]


def _active_value(record):
    return "Sí" if int(record.get("activo", 1)) == 1 else "No"


def _bool_to_int(value):
    return 1 if value == "Sí" else 0


def _table(headers, rows, height=300):
    """
    Tabla administrativa con scroll interno, igual que la tabla de Clientes.

    La vista no debe hacer scroll general para ver filas:
    el scroll vertical queda dentro de la tabla.
    """
    if not rows:
        return empty_state("No hay registros configurados todavía")

    return app_table(
        headers=headers,
        rows=rows,
        height=height,
    )

def settings_view(page: ft.Page):
    state = {
        "section": "tipos",
        "expediente_tab": "tipos",
        "editing_id": None,
        "editing_subtipo_id": None,
        "editing_formulario_id": None,
        "editing_campo_id": None,
        "selected_formulario_id": None,
        "editing_mapper_id": None,
        "editing_mapper_block_id": None,
        "editing_presentacion_config_id": None,
        "editing_document_template_id": None,
        "documentos_tab": "requeridos",
        "message": None,
    }

    content_area = ft.Container(expand=True)

    try:
        config_service.initialize_config_schema()
        dynamic_form_service.initialize_dynamic_forms_schema()
        mapper_admin_service.initialize_mapper_admin_schema()
        document_template_service.initialize_document_templates_schema()
    except Exception as exc:
        content_area.content = error_alert(f"No se pudo inicializar configuración: {exc}")

    def notify(message):
        state["message"] = success_alert(message)

    def fail(message):
        state["message"] = error_alert(message)

    def refresh():
        content_area.content = build_layout()
        page.update()

    def set_section(section):
        state["section"] = section
        state["editing_id"] = None
        state["editing_subtipo_id"] = None
        state["editing_formulario_id"] = None
        state["editing_campo_id"] = None
        state["selected_formulario_id"] = None
        state["editing_mapper_id"] = None
        state["editing_mapper_block_id"] = None
        state["editing_presentacion_config_id"] = None
        state["editing_document_template_id"] = None
        state["message"] = None
        refresh()

    def _mini_metric(label, value, icon, accent="#0057B8"):
        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, size=18, color=accent),
                        bgcolor="#EAF3FF",
                        border_radius=18,
                        width=36,
                        height=36,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(str(value), size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(label, size=12, color=Q_MUTED),
                        ],
                        spacing=0,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _expediente_tab_button(label, key, icon, subtitle):
        selected = state.get("expediente_tab") == key
        return ft.Container(
            bgcolor="#EAF3FF" if selected else "#FFFFFF",
            border=ft.border.all(1, "#B9D7FF" if selected else Q_BORDER),
            border_radius=14,
            padding=12,
            ink=True,
            on_click=lambda e, k=key: open_representante_dialog() if k == "representante" else set_expediente_tab(k),
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, size=20, color=Q_PRIMARY if selected else Q_MUTED),
                        bgcolor="#FFFFFF" if selected else "#F8FAFC",
                        border_radius=20,
                        width=40,
                        height=40,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(label, size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK if selected else "#101828"),
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

    def set_expediente_tab(tab):
        state["expediente_tab"] = tab
        state["editing_id"] = None
        state["editing_subtipo_id"] = None
        state["editing_formulario_id"] = None
        state["editing_campo_id"] = None
        state["editing_mapper_id"] = None
        state["editing_mapper_block_id"] = None
        state["editing_presentacion_config_id"] = None
        state["editing_document_template_id"] = None
        state["message"] = None
        refresh()

    def _expediente_workspace(title, subtitle, body, metrics=None):
        metrics = metrics or []
        return ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=18,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=16,
                        padding=16,
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(title, size=22, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(subtitle, size=13, color=Q_MUTED),
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                                ft.Row(metrics, spacing=10, wrap=True),
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ),
                    body,
                ],
                spacing=14,
                expand=True,
            ),
        )

    def header():
        msg = state["message"]
        controls = [
            ft.Text("Configuración operativa", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text(
                "Núcleo de parametrización para expedientes, documentación, cobros y automatizaciones futuras.",
                size=14,
                color=Q_MUTED,
            ),
        ]
        if msg:
            controls.append(msg)
        return ft.Column(controls=controls, spacing=8)

    def build_layout():
        return ft.Row(
            controls=[
                settings_sidebar(state["section"], set_section),
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[header(), build_section()],
                        spacing=18,
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=18,
            expand=True,
        )

    def run_save(fn, ok_message):
        try:
            fn()
            state["editing_id"] = None
            notify(ok_message)
        except Exception as exc:
            fail(str(exc))
        refresh()

    def edit_button(record_id):
        return secondary_button("Editar", lambda e, rid=record_id: start_edit(rid))

    def delete_button(table, record_id):
        return danger_button(
            "Eliminar",
            lambda e, t=table, rid=record_id: run_save(
                lambda: config_service.delete_record(t, rid),
                "Registro eliminado",
            ),
        )

    def start_edit(record_id):
        state["editing_id"] = record_id
        state["message"] = None
        refresh()

    def cancel_edit(e=None):
        state["editing_id"] = None
        state["editing_subtipo_id"] = None
        state["editing_formulario_id"] = None
        state["editing_campo_id"] = None
        state["editing_mapper_id"] = None
        state["editing_mapper_block_id"] = None
        state["editing_presentacion_config_id"] = None
        state["editing_document_template_id"] = None
        state["message"] = None
        refresh()

    def build_section():
        section = state["section"]
        if section == "tipos":
            return build_tipos()
        if section == "documentos":
            return build_documentos()
        if section == "estados":
            return build_estados()
        if section == "prioridades":
            return build_prioridades()
        if section == "box":
            return build_box()
        if section == "nomenclaturas":
            return build_nomenclaturas()
        return build_tablas()


    def build_representante():
        data = config_service.get_representante_config()

        def value(key):
            return data.get(key, "")

        def tf(label, key, width=240, required=False):
            factory = required_text_input if required else text_input
            return factory(label, value(key), width=width)

        def dd(label, key, options, width=220, required=False):
            return select_input(label, options, value=value(key), width=width)

        tipo_documento_options = ["DNI", "NIE", "Pasaporte", "CIF"]
        tipo_via_options = [
            "CALLE",
            "AVENIDA",
            "PLAZA",
            "PASEO",
            "CAMINO",
            "CARRETERA",
            "RONDA",
            "TRAVESÍA",
            "URBANIZACIÓN",
            "OTROS",
        ]
        opcion_notarial_options = ["", "CSV", "NOTARIO", "APODERA"]

        nombre = tf("Nombre", "representante_nombre", width=240)
        apellido1 = tf("Primer apellido", "representante_apellido1", width=240)
        apellido2 = tf("Segundo apellido", "representante_apellido2", width=240)
        nombre_razon_social = tf(
            "Nombre/Razón social Mercurio",
            "representante_nombre_razon_social",
            width=420,
            required=True,
        )

        tipo_documento = dd(
            "Tipo documento",
            "representante_tipo_documento",
            tipo_documento_options,
            width=180,
            required=True,
        )
        documento = tf("Documento", "representante_documento", width=220, required=True)

        colegio = tf("Colegio", "representante_colegio", width=320)
        numero_colegiado = tf("Número colegiado", "representante_numero_colegiado", width=220)

        tipo_via = dd("Tipo de vía", "representante_tipo_via", tipo_via_options, width=180, required=True)
        domicilio = tf("Domicilio", "representante_domicilio", width=420, required=True)
        numero = tf("Número", "representante_numero", width=120, required=True)
        piso = tf("Piso", "representante_piso", width=120)
        letra = tf("Letra", "representante_letra", width=120)
        escalera = tf("Escalera", "representante_escalera", width=140)
        bloque = tf("Bloque", "representante_bloque", width=140)
        kilometro = tf("Km", "representante_kilometro", width=120)
        hectometro = tf("Hectómetro", "representante_hectometro", width=140)

        provincia = tf("Provincia", "representante_provincia", width=240, required=True)
        municipio = tf("Municipio", "representante_municipio", width=260, required=True)
        localidad = tf("Localidad", "representante_localidad", width=260, required=True)
        codigo_postal = tf("Código postal", "representante_codigo_postal", width=160, required=True)

        telefono = tf("Teléfono", "representante_telefono", width=180)
        telefono_movil = tf("Teléfono móvil", "representante_telefono_movil", width=180)
        email = tf("Email", "representante_email", width=320)

        ruta_box_dni = tf(
            "Ruta relativa Box DNI",
            "representante_ruta_box_dni",
            width=620,
            required=True,
        )

        legal_nombre = tf("Representante legal", "representante_legal_nombre", width=360)
        legal_tipo_documento = dd(
            "Tipo documento rep. legal",
            "representante_legal_tipo_documento",
            tipo_documento_options,
            width=220,
        )
        legal_documento = tf("Documento rep. legal", "representante_legal_documento", width=220)
        legal_titulo = tf("Título rep. legal", "representante_legal_titulo", width=320)
        legal_telefono_movil = tf(
            "Teléfono móvil rep. legal",
            "representante_legal_telefono_movil",
            width=220,
        )
        legal_email = tf("Email rep. legal", "representante_legal_email", width=320)

        opcion_notarial = dd(
            "Tipo consulta notarial",
            "representante_opcion_notarial",
            opcion_notarial_options,
            width=220,
        )
        csv = tf("Código seguro de verificación (CSV)", "representante_csv", width=360)
        codigo_notario = tf("Código notario", "representante_codigo_notario", width=220)
        codigo_notaria = tf("Código notaría", "representante_codigo_notaria", width=220)
        fecha_escritura = tf("Fecha autorización escritura", "representante_fecha_escritura", width=240)
        num_protocolo = tf("Número protocolo escritura", "representante_num_protocolo", width=240)
        num_bis = tf("Número bis protocolo", "representante_num_bis", width=220)

        ayuda_ruta = ft.Column(
            controls=[
                ft.Text(
                    "Ruta válida: REPRESENTANTES/ANA_BELEN_QUESADA/DNI.pdf",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Text(
                    "No uses rutas absolutas tipo C:\\Users\\... ni /Users/...",
                    size=12,
                    color="#B42318",
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text("Recomendado: usa / como separador.", size=12, color=Q_MUTED),
            ],
            spacing=3,
        )

        def save():
            config_service.save_representante_config(
                {
                    "representante_nombre": nombre.value,
                    "representante_apellido1": apellido1.value,
                    "representante_apellido2": apellido2.value,
                    "representante_nombre_razon_social": nombre_razon_social.value,
                    "representante_tipo_documento": tipo_documento.value,
                    "representante_documento": documento.value,
                    "representante_colegio": colegio.value,
                    "representante_numero_colegiado": numero_colegiado.value,
                    "representante_tipo_via": tipo_via.value,
                    "representante_domicilio": domicilio.value,
                    "representante_numero": numero.value,
                    "representante_piso": piso.value,
                    "representante_letra": letra.value,
                    "representante_escalera": escalera.value,
                    "representante_bloque": bloque.value,
                    "representante_kilometro": kilometro.value,
                    "representante_hectometro": hectometro.value,
                    "representante_provincia": provincia.value,
                    "representante_municipio": municipio.value,
                    "representante_localidad": localidad.value,
                    "representante_codigo_postal": codigo_postal.value,
                    "representante_telefono": telefono.value,
                    "representante_telefono_movil": telefono_movil.value,
                    "representante_email": email.value,
                    "representante_ruta_box_dni": ruta_box_dni.value,
                    "representante_legal_nombre": legal_nombre.value,
                    "representante_legal_tipo_documento": legal_tipo_documento.value,
                    "representante_legal_documento": legal_documento.value,
                    "representante_legal_titulo": legal_titulo.value,
                    "representante_legal_telefono_movil": legal_telefono_movil.value,
                    "representante_legal_email": legal_email.value,
                    "representante_opcion_notarial": opcion_notarial.value,
                    "representante_csv": csv.value,
                    "representante_codigo_notario": codigo_notario.value,
                    "representante_codigo_notaria": codigo_notaria.value,
                    "representante_fecha_escritura": fecha_escritura.value,
                    "representante_num_protocolo": num_protocolo.value,
                    "representante_num_bis": num_bis.value,
                }
            )

        return config_section_card(
            "Representante",
            "Datos globales del representante/presentador para reutilizarlos después en Mercurio.",
            ft.Column(
                [
                    ft.Text("Identidad", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([nombre, apellido1, apellido2], wrap=True, spacing=10),
                    ft.Row([nombre_razon_social, tipo_documento, documento], wrap=True, spacing=10),
                    ft.Row([colegio, numero_colegiado], wrap=True, spacing=10),

                    ft.Text("Domicilio Mercurio", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([tipo_via, domicilio, numero, piso, letra], wrap=True, spacing=10),
                    ft.Row([escalera, bloque, kilometro, hectometro], wrap=True, spacing=10),
                    ft.Row([provincia, municipio, localidad, codigo_postal], wrap=True, spacing=10),

                    ft.Text("Contacto", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([telefono, telefono_movil, email], wrap=True, spacing=10),

                    ft.Text("Documento en Box", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ruta_box_dni,
                    ayuda_ruta,

                    ft.Text("Representante legal del presentador/a, si procede", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([legal_nombre, legal_tipo_documento, legal_documento], wrap=True, spacing=10),
                    ft.Row([legal_titulo, legal_telefono_movil, legal_email], wrap=True, spacing=10),

                    ft.Text("Datos notariales / CSV, si procede", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row([opcion_notarial, csv], wrap=True, spacing=10),
                    ft.Row([codigo_notario, codigo_notaria, fecha_escritura], wrap=True, spacing=10),
                    ft.Row([num_protocolo, num_bis], wrap=True, spacing=10),

                    ft.Row(
                        [
                            primary_button(
                                "Guardar representante",
                                lambda e: run_save(save, "Configuración del representante guardada"),
                            ),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=14,
            ),
        )


    def open_representante_dialog(e=None):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Representante / presentador"),
            content=ft.Container(
                width=1050,
                height=680,
                bgcolor="#F8FAFC",
                border_radius=18,
                padding=12,
                content=build_representante(),
            ),
            actions=[secondary_button("Cerrar", lambda ev: close_representante_dialog(dialog))],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def close_representante_dialog(dialog):
        dialog.open = False
        page.update()



    def tipo_options():
        tipos = config_service.get_tipos_expediente(active_only=True)
        return [f"{t['id']} - {t['nombre']}" for t in tipos]

    def selected_id(value):
        if not value or " - " not in value:
            return None
        return int(value.split(" - ", 1)[0])


    def build_presentaciones_asistidas():
        tipos = config_service.get_tipos_expediente(active_only=True)
        configs = presentation_config_service.list_presentacion_configs()
        editing_id = state.get("editing_presentacion_config_id")
        editing = presentation_config_service.get_presentacion_config_by_id(editing_id) if editing_id else None

        def numeric_id(value):
            raw = str(value or "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        if editing:
            selected_tipo_id = editing.get("tipo_expediente_id")
            selected_subtipo_id = editing.get("subtipo_expediente_id")
        else:
            selected_tipo_id = numeric_id(state.get("presentacion_selected_tipo_id"))
            selected_subtipo_id = numeric_id(state.get("presentacion_selected_subtipo_id"))

        if not selected_tipo_id and tipos:
            selected_tipo_id = tipos[0].get("id")

        subtipos = config_service.get_subtipos_expediente(selected_tipo_id, active_only=True) if selected_tipo_id else []

        nombre = text_input("Nombre configuración", (editing or {}).get("nombre_configuracion") or "", width=420)

        tipo_id_field = ft.TextField(
            label="Tipo expediente ID",
            value=str(selected_tipo_id or ""),
            width=170,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color=Q_PRIMARY,
            content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
        )
        subtipo_id_field = ft.TextField(
            label="Subtipo ID (opcional)",
            value=str(selected_subtipo_id or ""),
            width=170,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color=Q_PRIMARY,
            content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
        )

        def reload_tipo(e=None):
            state["presentacion_selected_tipo_id"] = tipo_id_field.value
            state["presentacion_selected_subtipo_id"] = ""
            state["editing_presentacion_config_id"] = None
            state["message"] = None
            refresh()

        def catalog_card(title, items, width=360):
            controls = [ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)]
            if not items:
                controls.append(ft.Text("Sin registros", size=12, color=Q_MUTED))
            else:
                for item in items[:10]:
                    controls.append(ft.Text(item, size=12, color=Q_MUTED, selectable=True))
                if len(items) > 10:
                    controls.append(ft.Text(f"... y {len(items) - 10} más", size=12, color=Q_MUTED))
            return ft.Container(
                bgcolor="#F8FAFC",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=10,
                width=width,
                content=ft.Column(controls=controls, spacing=4),
            )

        tipos_help = catalog_card(
            "Tipos activos disponibles",
            [f"{t['id']} - {t['nombre']}" for t in tipos],
            width=420,
        )
        subtipos_help = catalog_card(
            "Subtipos activos del tipo seleccionado",
            [f"{s['id']} - {s['nombre']}" for s in subtipos],
            width=420,
        )

        portal = text_input("Portal", (editing or {}).get("portal") or "MERCURIO", width=180)
        flujo = text_input("Flujo", (editing or {}).get("flujo") or "BI_PRESENTAR_NUEVA_SOLICITUD", width=280)
        url_presentacion = text_input("URL presentación", (editing or {}).get("url_presentacion") or "", width=620)
        tipo_formulario = text_input("Formulario Mercurio objetivo", (editing or {}).get("tipo_formulario_objetivo") or "", width=240)
        mapper_codigo = text_input("Mapper código", (editing or {}).get("mapper_codigo") or "", width=240)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        def save(e=None):
            tipo_id = numeric_id(tipo_id_field.value)
            subtipo_id = numeric_id(subtipo_id_field.value)
            if not tipo_id:
                fail("Introduce un tipo de expediente ID válido")
                refresh()
                return
            payload = {
                "tipo_expediente_id": tipo_id,
                "subtipo_expediente_id": subtipo_id,
                "nombre_configuracion": nombre.value,
                "url_presentacion": url_presentacion.value,
                "portal": portal.value or "MERCURIO",
                "flujo": flujo.value,
                "tipo_formulario_objetivo": tipo_formulario.value,
                "mapper_codigo": mapper_codigo.value,
                "activo": _bool_to_int(activo.value),
            }
            if editing_id:
                run_save(
                    lambda: presentation_config_service.update_presentacion_config(editing_id, payload),
                    "Configuración de presentación actualizada",
                )
            else:
                run_save(
                    lambda: presentation_config_service.create_presentacion_config(payload),
                    "Configuración de presentación creada",
                )
            state["editing_presentacion_config_id"] = None

        def edit_config(config_id):
            state["editing_presentacion_config_id"] = config_id
            state["message"] = None
            refresh()

        rows = []
        for config in configs:
            subtipo_label = config.get("subtipo_expediente_nombre") or "General"
            formulario_label = config.get("tipo_formulario_objetivo") or "—"
            mapper_label = config.get("mapper_codigo") or "—"
            estado_label = "Activo" if int(config.get("activo") or 0) else "Inactivo"
            rows.append(
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=12,
                    content=ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(config.get("nombre_configuracion") or "Sin nombre", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text(f"{config.get('tipo_expediente_nombre') or 'Tipo'} · {subtipo_label}", size=12, color=Q_MUTED),
                                    ft.Text(f"Formulario: {formulario_label} · Mapper: {mapper_label} · {estado_label}", size=12, color=Q_MUTED),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Row(
                                controls=[
                                    secondary_button("Editar", on_click=lambda e, rid=config["id"]: edit_config(rid)),
                                    danger_button(
                                        "Eliminar",
                                        on_click=lambda e, rid=config["id"]: run_save(
                                            lambda: presentation_config_service.delete_presentacion_config(rid),
                                            "Configuración de presentación eliminada",
                                        ),
                                    ),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=18,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Text("Configurar Presentación Asistida Mercurio", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text("Define qué EX, mapper y flujo usará cada tipo/subtipo sin tocar SeleniumBase.", size=12, color=Q_MUTED),
                    ft.Row([nombre, tipo_id_field, subtipo_id_field, secondary_button("Cargar subtipos", on_click=reload_tipo)], spacing=10, wrap=True),
                    ft.Row([tipos_help, subtipos_help], spacing=10, wrap=True),
                    ft.Row([portal, flujo, activo], spacing=10, wrap=True),
                    ft.Row([tipo_formulario, mapper_codigo], spacing=10, wrap=True),
                    url_presentacion,
                    ft.Row(
                        controls=[
                            primary_button("Guardar", on_click=save),
                            secondary_button("Cancelar", on_click=cancel_edit) if editing_id else ft.Container(),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=10,
            ),
        )

        if not rows:
            rows = [
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=14,
                    content=ft.Text("No hay configuraciones de presentación asistida.", color=Q_MUTED),
                )
            ]

        return ft.Column(
            controls=[
                form,
                ft.Text("Configuraciones existentes", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                *rows,
            ],
            spacing=12,
        )


    def build_tipos():
        """
        Hub navegable de configuración de expedientes.

        Evita una única pantalla vertical gigante mezclando:
        - tipos de expediente
        - subtipos
        - formularios dinámicos
        """
        def build_tipos_tab():
            editing = config_service.get_record("config_tipos_expediente", state["editing_id"]) if state["editing_id"] else {}

            codigo = text_input("Código", editing.get("codigo", ""), width=220)
            nombre = required_text_input("Nombre", editing.get("nombre", ""), width=320)
            descripcion = multiline_input("Descripción", editing.get("descripcion", ""), width=560, height=90)
            url_presentacion = text_input("URL presentación", editing.get("url_presentacion", ""), width=560)
            activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

            ayuda_codigo = ft.Text(
                "Código opcional: si lo dejas vacío, se genera automáticamente desde el nombre. "
                "Siempre se guarda en MAYÚSCULAS y con espacios convertidos en guiones bajos.",
                size=12,
                color=Q_MUTED,
            )

            def save():
                data = {
                    "codigo": codigo.value,
                    "nombre": nombre.value,
                    "descripcion": descripcion.value,
                    "url_presentacion": url_presentacion.value,
                    "activo": _bool_to_int(activo.value),
                }
                if not data["nombre"]:
                    raise ValueError("El nombre es obligatorio")
                if state["editing_id"]:
                    config_service.update_tipo_expediente(state["editing_id"], data)
                else:
                    config_service.create_tipo_expediente(data)

            form = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=16,
                padding=16,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Icon(ft.Icons.FOLDER_SPECIAL, size=18, color=Q_PRIMARY),
                                    bgcolor="#EAF3FF",
                                    border_radius=18,
                                    width=36,
                                    height=36,
                                    alignment=ft.alignment.Alignment(0, 0),
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Alta / edición de tipo", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text("Define el trámite principal y su URL de presentación asistida.", size=12, color=Q_MUTED),
                                    ],
                                    spacing=2,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Row([codigo, nombre, activo], wrap=True, spacing=10),
                        ayuda_codigo,
                        url_presentacion,
                        ft.Text(
                            "URL donde se iniciará la presentación asistida para este tipo de expediente.",
                            size=12,
                            color=Q_MUTED,
                        ),
                        descripcion,
                        ft.Row(
                            [
                                primary_button("Guardar tipo", lambda e: run_save(save, "Tipo de expediente guardado")),
                                secondary_button("Cancelar", lambda e: cancel_edit()),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=12,
                ),
            )

            rows = []
            for r in config_service.get_tipos_expediente():
                rows.append(
                    [
                        r["codigo"],
                        r["nombre"],
                        r.get("descripcion"),
                        r.get("url_presentacion") or "-",
                        "Sí" if r["activo"] else "No",
                        ft.Row(
                            [
                                edit_button(r["id"]),
                                delete_button("config_tipos_expediente", r["id"]),
                            ],
                            spacing=8,
                        ),
                    ]
                )

            return _expediente_workspace(
                "Tipos de expediente",
                "Catálogo principal de trámites: arraigo, nacionalidad, renovaciones, recursos y futuras automatizaciones.",
                ft.Column(
                    controls=[
                        form,
                        _table(["Código", "Nombre", "Descripción", "URL presentación", "Activo", "Acciones"], rows, height=360),
                    ],
                    spacing=14,
                ),
                metrics=[_mini_metric("Tipos", len(rows), ft.Icons.FOLDER_SPECIAL)],
            )

        def build_subtipos_tab():
            subtipo_editing = (
                config_service.get_record("config_subtipos_expediente", state.get("editing_subtipo_id"))
                if state.get("editing_subtipo_id") else {}
            )
            subtipo_tipos_opts = tipo_options()
            subtipo_selected_tipo = ""
            if subtipo_editing:
                subtipo_selected_tipo = next(
                    (x for x in subtipo_tipos_opts if x.startswith(str(subtipo_editing.get("tipo_expediente_id")) + " - ")),
                    "",
                )

            subtipo_tipo = select_input("Tipo padre", subtipo_tipos_opts, value=subtipo_selected_tipo, width=300)
            subtipo_codigo = text_input("Código subtipo", subtipo_editing.get("codigo", ""), width=220)
            subtipo_nombre = required_text_input("Nombre subtipo", subtipo_editing.get("nombre", ""), width=320)
            subtipo_orden = text_input("Orden", str(subtipo_editing.get("orden", 0)), width=100)
            subtipo_activo = select_input("Activo", _bool_options(), value=_active_value(subtipo_editing) if subtipo_editing else "Sí", width=120)
            subtipo_descripcion = multiline_input("Descripción subtipo", subtipo_editing.get("descripcion", ""), width=620, height=80)

            def save_subtipo():
                tid = selected_id(subtipo_tipo.value)
                if not tid:
                    raise ValueError("Selecciona el tipo padre")
                data = {
                    "tipo_expediente_id": tid,
                    "codigo": subtipo_codigo.value,
                    "nombre": subtipo_nombre.value,
                    "descripcion": subtipo_descripcion.value,
                    "orden": int(subtipo_orden.value or 0),
                    "activo": _bool_to_int(subtipo_activo.value),
                }
                if state.get("editing_subtipo_id"):
                    config_service.update_subtipo_expediente(state["editing_subtipo_id"], data)
                else:
                    config_service.create_subtipo_expediente(data)
                state["editing_subtipo_id"] = None

            def start_edit_subtipo(record_id):
                state["editing_subtipo_id"] = record_id
                state["message"] = None
                refresh()

            def delete_subtipo(record_id):
                config_service.delete_record("config_subtipos_expediente", record_id)
                state["editing_subtipo_id"] = None

            subtype_rows = []
            try:
                subtipos_records = config_service.get_subtipos_expediente()
            except Exception:
                subtipos_records = []

            for s in subtipos_records:
                subtype_rows.append(
                    [
                        s.get("tipo_expediente_nombre") or "-",
                        s.get("codigo") or "-",
                        s.get("nombre") or "-",
                        s.get("descripcion") or "",
                        s.get("orden") or 0,
                        "Sí" if s.get("activo") else "No",
                        ft.Row(
                            [
                                secondary_button("Editar", lambda e, sid=s["id"]: start_edit_subtipo(sid)),
                                danger_button(
                                    "Eliminar",
                                    lambda e, sid=s["id"]: run_save(lambda: delete_subtipo(sid), "Subtipo eliminado"),
                                ),
                            ],
                            spacing=8,
                        ),
                    ]
                )

            subtipo_form = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=16,
                padding=16,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Icon(ft.Icons.ACCOUNT_TREE, size=18, color=Q_PRIMARY),
                                    bgcolor="#EAF3FF",
                                    border_radius=18,
                                    width=36,
                                    height=36,
                                    alignment=ft.alignment.Alignment(0, 0),
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Alta / edición de subtipo", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text("Variantes del trámite para reglas documentales y formularios específicos.", size=12, color=Q_MUTED),
                                    ],
                                    spacing=2,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Row([subtipo_tipo, subtipo_codigo, subtipo_nombre], wrap=True, spacing=10),
                        ft.Row([subtipo_orden, subtipo_activo], wrap=True, spacing=10),
                        subtipo_descripcion,
                        ft.Row(
                            [
                                primary_button("Guardar subtipo", lambda e: run_save(save_subtipo, "Subtipo de expediente guardado")),
                                secondary_button("Cancelar", lambda e: cancel_edit()),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=12,
                ),
            )

            return _expediente_workspace(
                "Subtipos de expediente",
                "Divide cada trámite en variantes: residencia caso general, familiar, laboral, estudios o cualquier subtipo futuro.",
                ft.Column(
                    controls=[
                        subtipo_form,
                        _table(["Tipo padre", "Código", "Subtipo", "Descripción", "Orden", "Activo", "Acciones"], subtype_rows, height=360),
                    ],
                    spacing=14,
                ),
                metrics=[_mini_metric("Subtipos", len(subtype_rows), ft.Icons.ACCOUNT_TREE)],
            )

        tipos_count = len(config_service.get_tipos_expediente())
        try:
            subtipos_count = len(config_service.get_subtipos_expediente())
        except Exception:
            subtipos_count = 0
        try:
            formularios_count = len(dynamic_form_service.list_formularios())
        except Exception:
            formularios_count = 0
        try:
            mappers_count = len(mapper_admin_service.list_mapper_templates())
        except Exception:
            mappers_count = 0
        try:
            mapper_blocks_count = len(mapper_admin_service.list_mapper_blocks())
        except Exception:
            mapper_blocks_count = 0
        try:
            presentaciones_count = len(presentation_config_service.list_presentacion_configs())
        except Exception:
            presentaciones_count = 0

        tab = state.get("expediente_tab") or "tipos"
        if tab == "subtipos":
            body = build_subtipos_tab()
        elif tab == "formularios":
            body = build_formularios_expediente()
        elif tab == "mappers":
            body = build_mappers_expediente()
        elif tab == "mapper_blocks":
            body = build_mapper_blocks_expediente()
        elif tab == "presentaciones":
            body = build_presentaciones_asistidas()
        else:
            body = build_tipos_tab()

        return ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=18,
                    padding=16,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.TUNE, size=26, color=Q_PRIMARY),
                                bgcolor="#FFFFFF",
                                border_radius=24,
                                width=48,
                                height=48,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("Expedientes", size=24, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text("Configura la arquitectura del expediente sin una pantalla vertical interminable.", size=13, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Row(
                                controls=[
                                    _mini_metric("Tipos", tipos_count, ft.Icons.FOLDER_SPECIAL),
                                    _mini_metric("Subtipos", subtipos_count, ft.Icons.ACCOUNT_TREE),
                                    _mini_metric("Formularios", formularios_count, ft.Icons.DYNAMIC_FORM),
                                    _mini_metric("Mappers", mappers_count, ft.Icons.HUB),
                                    _mini_metric("Blocks", mapper_blocks_count, ft.Icons.VIEW_MODULE),
                                    _mini_metric("Presentaciones", presentaciones_count, ft.Icons.PLAY_CIRCLE),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                ft.Row(
                    controls=[
                        _expediente_tab_button("Tipos", "tipos", ft.Icons.FOLDER_SPECIAL, "Trámites principales"),
                        _expediente_tab_button("Subtipos", "subtipos", ft.Icons.ACCOUNT_TREE, "Variantes por trámite"),
                        _expediente_tab_button("Formularios", "formularios", ft.Icons.DYNAMIC_FORM, "Campos específicos"),
                        _expediente_tab_button("Representante", "representante", ft.Icons.VERIFIED_USER, "Datos Mercurio"),
                        _expediente_tab_button("Presentaciones", "presentaciones", ft.Icons.PLAY_CIRCLE, "Mercurio por EX"),
                        _expediente_tab_button("Mappers", "mappers", ft.Icons.HUB, "Snapshot → destino"),
                        _expediente_tab_button("Mapper Blocks", "mapper_blocks", ft.Icons.VIEW_MODULE, "Bloques reutilizables"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                body,
            ],
            spacing=14,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )


    def _documentos_tab_button(label, key, icon, subtitle):
        selected = state.get("documentos_tab", "requeridos") == key
        return ft.Container(
            bgcolor="#EAF3FF" if selected else "#FFFFFF",
            border=ft.border.all(1, "#B9D7FF" if selected else Q_BORDER),
            border_radius=14,
            padding=12,
            ink=True,
            on_click=lambda e, k=key: set_documentos_tab(k),
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, size=20, color=Q_PRIMARY if selected else Q_MUTED),
                        bgcolor="#FFFFFF" if selected else "#F8FAFC",
                        border_radius=20,
                        width=40,
                        height=40,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(label, size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK if selected else "#101828"),
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

    def set_documentos_tab(tab):
        state["documentos_tab"] = tab
        state["editing_id"] = None
        state["editing_document_template_id"] = None
        state["message"] = None
        refresh()


    def build_documentos_requeridos():
        editing = config_service.get_record("config_documentos_requeridos", state["editing_id"]) if state["editing_id"] else {}
        tipos_opts = tipo_options()
        subtipos = []
        subtipo_opts = ["Sin subtipo"] + [
            f"{s['id']} - {s['tipo_expediente_nombre']} - {s['nombre']}"
            for s in subtipos
        ]
        selected_tipo = ""
        selected_subtipo = "Sin subtipo"
        if editing:
            selected_tipo = next((x for x in tipos_opts if x.startswith(str(editing["tipo_expediente_id"]) + " - ")), "")
            selected_subtipo = next(
                (x for x in subtipo_opts if x.startswith(str(editing.get("subtipo_expediente_id")) + " - ")),
                "Sin subtipo",
            )

        tipo = select_input("Tipo expediente", tipos_opts, value=selected_tipo, width=300)
        subtipo = select_input("Subtipo", subtipo_opts, value=selected_subtipo, width=360)
        codigo = text_input("Código documento", editing.get("codigo_documento", ""), width=220)
        nombre = required_text_input("Nombre documento", editing.get("nombre_documento", ""), width=320)
        obligatorio = select_input("Obligatorio", _bool_options(), value="Sí" if int(editing.get("obligatorio", 1)) else "No", width=140)
        orden = text_input("Orden", str(editing.get("orden", 0)), width=100)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        def save():
            tid = selected_id(tipo.value)
            if not tid:
                raise ValueError("Selecciona un tipo de expediente")
            data = {
                "tipo_expediente_id": tid,
                "subtipo_expediente_id": selected_id(subtipo.value),
                "codigo_documento": codigo.value,
                "nombre_documento": nombre.value,
                "obligatorio": _bool_to_int(obligatorio.value),
                "orden": int(orden.value or 0),
                "activo": _bool_to_int(activo.value),
            }
            if not data["nombre_documento"]:
                raise ValueError("El nombre del documento es obligatorio")
            if state["editing_id"]:
                config_service.update_documento_requerido(state["editing_id"], data)
            else:
                config_service.create_documento_requerido(data)

        form = ft.Column(
            controls=[
                ft.Row([tipo, subtipo, codigo, nombre], wrap=True, spacing=10),
                ft.Text(
                    "Código opcional: se genera desde el nombre si lo dejas vacío.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row([obligatorio, orden, activo], wrap=True, spacing=10),
                ft.Row(
                    [
                        primary_button("Guardar", lambda e: run_save(save, "Documento requerido guardado")),
                        secondary_button("Cancelar", lambda e: cancel_edit()),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )

        rows = []
        for r in config_service.get_documentos_requeridos():
            rows.append(
                [
                    r["tipo_expediente_nombre"],
                    r.get("subtipo_expediente_nombre") or "General",
                    r["codigo_documento"],
                    r["nombre_documento"],
                    "Sí" if r["obligatorio"] else "No",
                    r["orden"],
                    "Sí" if r["activo"] else "No",
                    ft.Row([edit_button(r["id"]), delete_button("config_documentos_requeridos", r["id"])], spacing=8),
                ]
            )

        return config_section_card(
            "Documentos requeridos",
            "Documentación esperada por tipo de expediente.",
            ft.Column(
                [
                    form,
                    _table(["Tipo", "Subtipo", "Código", "Documento", "Obligatorio", "Orden", "Activo", "Acciones"], rows),
                ],
                spacing=16,
            ),
        )


    def build_plantillas_documentales():
        try:
            templates = document_template_service.list_document_templates(active_only=False)
        except Exception as exc:
            return config_section_card(
                "Plantillas documentales",
                "Catálogo general de plantillas EX, documentos internos y modelos generales.",
                error_alert(f"No se pudieron cargar las plantillas documentales: {exc}"),
            )

        editing = (
            document_template_service.get_document_template(state.get("editing_document_template_id"))
            if state.get("editing_document_template_id")
            else {}
        )

        codigo = required_text_input("Código", editing.get("codigo", ""), width=260)
        nombre = required_text_input("Nombre", editing.get("nombre", ""), width=320)
        nombre_oficial = text_input("Nombre oficial", editing.get("nombre_oficial", ""), width=520)
        descripcion = multiline_input("Descripción", editing.get("descripcion", ""), width=760, height=80)

        categoria = select_input(
            "Categoría",
            ["EX", "REPRESENTACION", "AUTORIZACION", "HOJA_ENCARGO", "ESCRITO", "CONTRATO", "GENERAL"],
            value=editing.get("categoria", "GENERAL") if editing else "GENERAL",
            width=220,
        )
        tipo_destino = select_input(
            "Tipo destino",
            ["EX", "DOCUMENTO", "PDF", "WORD", "OTRO"],
            value=editing.get("tipo_destino", "DOCUMENTO") if editing else "DOCUMENTO",
            width=180,
        )
        template_type = select_input(
            "Tipo plantilla",
            ["docx", "pdf", "pdf_acroform", "pdf_overlay", "html", "json"],
            value=editing.get("template_type", "docx") if editing else "docx",
            width=180,
        )
        requiere_expediente = select_input(
            "Requiere expediente",
            _bool_options(),
            value="Sí" if int(editing.get("requiere_expediente", 1)) else "No",
            width=180,
        )
        activo = select_input(
            "Activo",
            _bool_options(),
            value=_active_value(editing) if editing else "Sí",
            width=120,
        )
        orden = text_input("Orden", str(editing.get("orden", 0)), width=100)
        mapper_destino = text_input(
            "Mapper destino",
            editing.get("mapper_destino", ""),
            width=320,
        )
        template_path = text_input("Ruta plantilla", editing.get("template_path", ""), width=760)
        fields_json_path = text_input("Ruta fields.json", editing.get("fields_json_path", ""), width=760)
        metadata_json_path = text_input("Ruta metadata.json", editing.get("metadata_json_path", ""), width=760)

        def apply_default_paths(e=None):
            paths = document_template_service.build_default_template_paths(
                codigo.value,
                categoria.value,
                template_type.value,
            )
            template_path.value = paths.get("template_path", "")
            fields_json_path.value = paths.get("fields_json_path", "")
            metadata_json_path.value = paths.get("metadata_json_path", "")
            if not mapper_destino.value:
                mapper_destino.value = (codigo.value or "").strip().upper().replace(" ", "_")
            page.update()

        def save_template():
            data = {
                "codigo": codigo.value,
                "nombre": nombre.value,
                "nombre_oficial": nombre_oficial.value,
                "descripcion": descripcion.value,
                "categoria": categoria.value,
                "tipo_destino": tipo_destino.value,
                "template_type": template_type.value,
                "template_path": template_path.value,
                "fields_json_path": fields_json_path.value,
                "metadata_json_path": metadata_json_path.value,
                "mapper_destino": mapper_destino.value or codigo.value,
                "requiere_expediente": _bool_to_int(requiere_expediente.value),
                "activo": _bool_to_int(activo.value),
                "orden": int(orden.value or 0),
            }

            template_id = state.get("editing_document_template_id")
            if template_id:
                document_template_service.update_document_template(template_id, data)
            else:
                document_template_service.create_document_template(data)

            state["editing_document_template_id"] = None

        def start_edit_template(template_id):
            state["documentos_tab"] = "plantillas"
            state["editing_id"] = None
            state["editing_document_template_id"] = int(template_id)
            state["message"] = None
            refresh()

        def delete_template(template_id):
            document_template_service.hard_delete_document_template(template_id)
            if state.get("editing_document_template_id") == template_id:
                state["editing_document_template_id"] = None

        def open_test_document_template_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            try:
                expedientes = expedient_service.get_expedientes(active_only=True)
            except Exception as exc:
                fail(f"No se pudieron cargar expedientes: {exc}")
                refresh()
                return

            expediente_options = []
            for expediente in expedientes:
                cliente_nombre = " ".join(
                    part for part in [
                        expediente.get("cliente_nombre"),
                        expediente.get("cliente_primer_apellido"),
                        expediente.get("cliente_segundo_apellido"),
                    ] if part
                ).strip()
                expediente_options.append(
                    f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NÚMERO'} · {cliente_nombre or 'SIN CLIENTE'}"
                )

            expediente_selector = select_input(
                "Expediente de prueba",
                expediente_options,
                value=expediente_options[0] if expediente_options else "",
                width=680,
            )

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Selecciona un expediente y pulsa Probar payload. No se genera ningún documento.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def run_test(ev=None):
                expediente_id = selected_id(expediente_selector.value)
                if not expediente_id:
                    result_box.content = error_alert("Selecciona un expediente de prueba")
                    page.update()
                    return

                try:
                    preview = mapper_preview_service.preview_document_template_for_expedient(
                        template_id,
                        expediente_id,
                        auto_build_snapshot=True,
                    )

                    payload = preview.get("payload") or {}
                    validation = preview.get("validation") or {}
                    errors = validation.get("errors") or []
                    empty_fields = preview.get("empty_fields") or []
                    summary = preview.get("summary") or {}
                    snapshot_info = preview.get("snapshot") or {}
                    mapper_match = preview.get("mapper_match") or {}

                    is_valid = bool(summary.get("valid"))
                    status_color = "#027A48" if is_valid else "#B42318"
                    status_text = "PAYLOAD CORRECTO" if is_valid else "PAYLOAD CON ERRORES"
                    snapshot_text = (
                        "Snapshot generado en memoria"
                        if snapshot_info.get("generated_in_memory")
                        else f"Snapshot v{snapshot_info.get('version') or '-'}"
                    )

                    result_box.content = ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                                    ft.Text(snapshot_text, size=12, color=Q_MUTED),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Resumen", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Mapper: {mapper_match.get('mapper_codigo') or '-'} · "
                                            f"Campos payload: {summary.get('payload_fields', len(payload))} · "
                                            f"Vacíos: {summary.get('empty_fields', len(empty_fields))} · "
                                            f"Errores required: {summary.get('required_errors', len(errors))}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
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
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Payload generado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            json.dumps(payload, ensure_ascii=False, indent=2),
                                            size=12,
                                            color="#101828",
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ),
                        ],
                        spacing=10,
                    )
                    page.update()

                except Exception as exc:
                    result_box.content = error_alert(str(exc))
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Probar payload de plantilla", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content=ft.Container(
                    width=940,
                    height=650,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Código: {template.get('codigo') or '-'} · Mapper destino: {template.get('mapper_destino') or '-'}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            "La prueba usa el mapper asociado por código y el último snapshot del expediente. No crea DOCX/PDF.",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            expediente_selector,
                            ft.Row(
                                controls=[
                                    primary_button("Probar payload", run_test),
                                    secondary_button("Cerrar", lambda ev: close_test_document_template_dialog(dialog)),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def close_test_document_template_dialog(dialog):
            dialog.open = False
            page.update()

        def open_export_document_template_payload_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            try:
                expedientes = expedient_service.get_expedientes(active_only=True)
            except Exception as exc:
                fail(f"No se pudieron cargar expedientes: {exc}")
                refresh()
                return

            requires_expediente = int(template.get("requiere_expediente") or 0) == 1
            is_ex_template = str(template.get("categoria") or "").strip().upper() == "EX"

            expediente_options = []
            if not requires_expediente and not is_ex_template:
                expediente_options.append("Sin expediente")

            for expediente in expedientes:
                cliente_nombre = " ".join(
                    part for part in [
                        expediente.get("cliente_nombre"),
                        expediente.get("cliente_primer_apellido"),
                        expediente.get("cliente_segundo_apellido"),
                    ] if part
                ).strip()
                expediente_options.append(
                    f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NÚMERO'} · {cliente_nombre or 'SIN CLIENTE'}"
                )

            expediente_selector = select_input(
                "Expediente",
                expediente_options,
                value=expediente_options[0] if expediente_options else "",
                width=680,
            )

            help_text = (
                "Esta plantilla requiere expediente para exportar el payload."
                if requires_expediente or is_ex_template
                else "Puedes exportar como general o asociarlo a un expediente concreto."
            )

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Pulsa Exportar payload. Se generará únicamente un JSON; no se crea DOCX/PDF.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def run_export(ev=None):
                selected_value = expediente_selector.value or ""
                expediente_id = None if selected_value == "Sin expediente" else selected_id(selected_value)

                if (requires_expediente or is_ex_template) and not expediente_id:
                    result_box.content = error_alert("Selecciona un expediente para esta plantilla")
                    page.update()
                    return

                try:
                    exported = document_generation_service.export_document_payload(
                        template_id,
                        expediente_id=expediente_id,
                        auto_build_snapshot=True,
                    )

                    validation = exported.get("validation") or {}
                    summary = exported.get("summary") or {}
                    output = exported.get("output") or {}
                    empty_fields = exported.get("empty_fields") or []
                    errors = validation.get("errors") or []
                    payload = exported.get("payload") or {}

                    is_valid = bool(summary.get("valid", validation.get("valid")))
                    status_color = "#027A48" if is_valid else "#B42318"
                    status_text = "EXPORTACIÓN CORRECTA" if is_valid else "EXPORTACIÓN CON AVISOS"

                    result_box.content = ft.Column(
                        controls=[
                            ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Archivo generado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(output.get("json_path") or "-", size=12, color="#101828", selectable=True),
                                        ft.Text(f"Directorio: {output.get('directory') or '-'}", size=12, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Text(
                                f"Campos payload: {summary.get('payload_fields', len(payload))} · "
                                f"Vacíos: {summary.get('empty_fields', len(empty_fields))} · "
                                f"Errores required: {summary.get('required_errors', len(errors))}",
                                size=12,
                                color=Q_MUTED,
                            ),
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
                        spacing=10,
                    )
                    page.update()

                except Exception as exc:
                    result_box.content = error_alert(str(exc))
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Exportar payload documental", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content=ft.Container(
                    width=940,
                    height=620,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Código: {template.get('codigo') or '-'} · Mapper destino: {template.get('mapper_destino') or '-'}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(help_text, size=12, color=Q_MUTED),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            expediente_selector,
                            ft.Row(
                                controls=[
                                    primary_button("Exportar payload", run_export),
                                    secondary_button("Cerrar", lambda ev: close_export_document_template_payload_dialog(dialog)),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def close_export_document_template_payload_dialog(dialog):
            dialog.open = False
            page.update()

        def open_generate_document_template_docx_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            if str(template.get("template_type") or "").strip().lower() != "docx":
                fail("Solo las plantillas de tipo docx permiten generar DOCX")
                refresh()
                return

            try:
                expedientes = expedient_service.get_expedientes(active_only=True)
            except Exception as exc:
                fail(f"No se pudieron cargar expedientes: {exc}")
                refresh()
                return

            requires_expediente = int(template.get("requiere_expediente") or 0) == 1
            is_ex_template = str(template.get("categoria") or "").strip().upper() == "EX"

            expediente_options = []
            if not requires_expediente and not is_ex_template:
                expediente_options.append("Sin expediente")

            for expediente in expedientes:
                cliente_nombre = " ".join(
                    part for part in [
                        expediente.get("cliente_nombre"),
                        expediente.get("cliente_primer_apellido"),
                        expediente.get("cliente_segundo_apellido"),
                    ] if part
                ).strip()
                expediente_options.append(
                    f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NÚMERO'} · {cliente_nombre or 'SIN CLIENTE'}"
                )

            expediente_selector = select_input(
                "Expediente",
                expediente_options,
                value=expediente_options[0] if expediente_options else "",
                width=680,
            )

            help_text = (
                "Esta plantilla requiere expediente para generar el DOCX."
                if requires_expediente or is_ex_template
                else "Puedes generar un documento general o asociarlo a un expediente concreto."
            )

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Pulsa Generar DOCX. Se creará el JSON payload y el documento final desde la plantilla configurada.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def run_generate(ev=None):
                selected_value = expediente_selector.value or ""
                expediente_id = None if selected_value == "Sin expediente" else selected_id(selected_value)

                if (requires_expediente or is_ex_template) and not expediente_id:
                    result_box.content = error_alert("Selecciona un expediente para esta plantilla")
                    page.update()
                    return

                try:
                    generated = document_docx_service.generate_docx_from_template(
                        template_id,
                        expediente_id=expediente_id,
                        auto_build_snapshot=True,
                    )

                    validation = generated.get("validation") or {}
                    summary = generated.get("summary") or {}
                    output = generated.get("output") or {}
                    docx_info = generated.get("docx") or {}
                    empty_fields = generated.get("empty_fields") or []
                    errors = validation.get("errors") or []
                    unresolved = docx_info.get("unresolved_placeholders") or []
                    payload = generated.get("payload") or {}

                    is_valid = bool(summary.get("valid", validation.get("valid"))) and not unresolved
                    status_color = "#027A48" if is_valid else "#B42318"
                    status_text = "DOCX GENERADO CORRECTAMENTE" if is_valid else "DOCX GENERADO CON AVISOS"

                    result_box.content = ft.Column(
                        controls=[
                            ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Archivos generados", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(f"DOCX: {output.get('docx_path') or docx_info.get('docx_path') or '-'}", size=12, color="#101828", selectable=True),
                                        ft.Text(f"Payload JSON: {output.get('json_path') or '-'}", size=12, color="#101828", selectable=True),
                                        ft.Text(f"Directorio: {output.get('directory') or '-'}", size=12, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Text(
                                f"Campos payload: {summary.get('payload_fields', len(payload))} · "
                                f"Vacíos: {summary.get('empty_fields', len(empty_fields))} · "
                                f"Errores required: {summary.get('required_errors', len(errors))} · "
                                f"Placeholders sin resolver: {docx_info.get('unresolved_count', len(unresolved))}",
                                size=12,
                                color=Q_MUTED,
                            ),
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
                            ft.Text(
                                "Placeholders sin resolver:\n- " + "\n- ".join(unresolved) if unresolved else "Sin placeholders pendientes.",
                                size=12,
                                color="#B42318" if unresolved else "#027A48",
                                selectable=True,
                            ),
                        ],
                        spacing=10,
                    )
                    page.update()

                except Exception as exc:
                    result_box.content = error_alert(str(exc))
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Generar DOCX documental", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content=ft.Container(
                    width=940,
                    height=620,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Código: {template.get('codigo') or '-'} · Plantilla: {template.get('template_path') or '-'}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(help_text, size=12, color=Q_MUTED),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            expediente_selector,
                            ft.Row(
                                controls=[
                                    primary_button("Generar DOCX", run_generate),
                                    secondary_button("Cerrar", lambda ev: close_generate_document_template_docx_dialog(dialog)),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def close_generate_document_template_docx_dialog(dialog):
            dialog.open = False
            page.update()

        def open_export_pdf_fields_json_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            if str(template.get("template_type") or "").strip().lower() not in ("pdf", "pdf_acroform"):
                fail("Solo las plantillas de tipo pdf/pdf_acroform permiten generar fields.json")
                refresh()
                return

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Pulsa Generar fields.json para inspeccionar el PDF autorrellenable y guardar el catálogo de campos junto a la plantilla.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def close_dialog(ev=None):
                dialog.open = False
                page.update()

            def run_export(ev=None):
                try:
                    result_box.content = ft.Text("Generando fields.json...", size=12, color=Q_MUTED)
                    page.update()

                    result = pdf_template_service.export_document_template_pdf_fields(
                        template_id,
                        update_template=True,
                    )

                    result_box.content = ft.Column(
                        controls=[
                            success_alert("fields.json generado correctamente"),
                            ft.Text(f"PDF: {result.get('pdf_path') or '-'}", size=12, color=Q_MUTED),
                            ft.Text(f"fields.json: {result.get('fields_json_path') or template.get('fields_json_path') or '-'}", size=12, color=Q_MUTED),
                            ft.Text(f"Páginas: {result.get('page_count') or 0} · Campos detectados: {result.get('field_count') or 0}", size=12, color=Q_MUTED),
                            ft.Text(
                                "Puedes usar estos nombres de campo en el mapper PDF. Ejemplo: Texto1, Texto2 o Casilla de verificación7.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=6,
                    )
                    page.update()
                except Exception as exc:
                    result_box.content = error_alert(f"No se pudo generar fields.json: {exc}")
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Generar fields.json"),
                content=ft.Container(
                    width=780,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla PDF", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(f"Código: {template.get('codigo') or '-'}", size=12, color=Q_MUTED),
                                        ft.Text(f"PDF: {template.get('template_path') or '-'}", size=12, color=Q_MUTED),
                                        ft.Text(f"fields_json_path actual: {template.get('fields_json_path') or 'Se generará automáticamente'}", size=12, color=Q_MUTED),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Row(
                                controls=[
                                    primary_button("Generar fields.json", run_export),
                                    secondary_button("Cerrar", close_dialog),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def open_export_pdf_fields_overlay_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            if str(template.get("template_type") or "").strip().lower() not in ("pdf", "pdf_acroform"):
                fail("Solo las plantillas de tipo pdf/pdf_acroform permiten generar el overlay de campos")
                refresh()
                return

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Pulsa Generar overlay para crear un HTML visual con los nombres de campos encima del PDF. Sirve para mapear PDFs con campos tipo Texto1 o Casilla de verificación7.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def close_dialog(ev=None):
                dialog.open = False
                page.update()

            def run_export(ev=None):
                try:
                    result_box.content = ft.Text("Generando overlay visual de campos...", size=12, color=Q_MUTED)
                    page.update()

                    result = pdf_template_service.export_document_template_fields_overlay_html(
                        template_id,
                    )

                    result_box.content = ft.Column(
                        controls=[
                            success_alert("Overlay de campos generado correctamente"),
                            ft.Text(f"PDF: {result.get('pdf_path') or '-'}", size=12, color=Q_MUTED, selectable=True),
                            ft.Text(f"fields.json: {result.get('fields_json_path') or template.get('fields_json_path') or '-'}", size=12, color=Q_MUTED, selectable=True),
                            ft.Text(f"HTML overlay: {result.get('overlay_html_path') or '-'}", size=12, color="#101828", selectable=True),
                            ft.Text(f"Páginas: {result.get('page_count') or 0} · Campos: {result.get('field_count') or 0}", size=12, color=Q_MUTED),
                            ft.Text(
                                "Abre el HTML generado en el navegador para identificar cada campo antes de crear el mapper.",
                                size=12,
                                color=Q_MUTED,
                            ),
                        ],
                        spacing=6,
                    )
                    page.update()
                except Exception as exc:
                    result_box.content = error_alert(f"No se pudo generar el overlay de campos: {exc}")
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Generar overlay visual de campos"),
                content=ft.Container(
                    width=820,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla PDF", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(f"Código: {template.get('codigo') or '-'}", size=12, color=Q_MUTED),
                                        ft.Text(f"PDF: {template.get('template_path') or '-'}", size=12, color=Q_MUTED, selectable=True),
                                        ft.Text(f"fields.json: {template.get('fields_json_path') or 'Se usará/generará junto a la plantilla'}", size=12, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Row(
                                controls=[
                                    primary_button("Generar overlay", run_export),
                                    secondary_button("Cerrar", close_dialog),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def open_generate_document_template_pdf_dialog(template_id):
            template = document_template_service.get_document_template(template_id)
            if not template:
                fail("Plantilla documental no encontrada")
                refresh()
                return

            if str(template.get("template_type") or "").strip().lower() not in ("pdf", "pdf_acroform"):
                fail("Solo las plantillas de tipo pdf/pdf_acroform permiten generar PDF")
                refresh()
                return

            try:
                expedientes = expedient_service.get_expedientes(active_only=True)
            except Exception as exc:
                fail(f"No se pudieron cargar expedientes: {exc}")
                refresh()
                return

            requires_expediente = int(template.get("requiere_expediente") or 0) == 1
            is_ex_template = str(template.get("categoria") or "").strip().upper() == "EX"

            expediente_options = []
            if not requires_expediente and not is_ex_template:
                expediente_options.append("Sin expediente")

            for expediente in expedientes:
                cliente_nombre = " ".join(
                    part for part in [
                        expediente.get("cliente_nombre"),
                        expediente.get("cliente_primer_apellido"),
                        expediente.get("cliente_segundo_apellido"),
                    ] if part
                ).strip()
                expediente_options.append(
                    f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NÚMERO'} · {cliente_nombre or 'SIN CLIENTE'}"
                )

            expediente_selector = select_input(
                "Expediente",
                expediente_options,
                value=expediente_options[0] if expediente_options else "",
                width=680,
            )
            flatten = select_input("Aplanar PDF", _bool_options(), value="No", width=150)

            help_text = (
                "Esta plantilla requiere expediente para generar el PDF."
                if requires_expediente or is_ex_template
                else "Puedes generar un PDF general o asociarlo a un expediente concreto."
            )

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Pulsa Generar PDF. Se creará el payload y el PDF rellenable desde la plantilla configurada.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def selected_expediente_id_for_generation():
                value = expediente_selector.value or ""
                if value == "Sin expediente":
                    return None
                expediente_id = selected_id(value)
                if not expediente_id and (requires_expediente or is_ex_template):
                    raise ValueError("Selecciona un expediente")
                return expediente_id

            def run_generate(ev=None):
                try:
                    result_box.content = ft.Text("Generando PDF...", size=12, color=Q_MUTED)
                    page.update()

                    generated = pdf_fill_service.fill_pdf_from_template(
                        template_id,
                        expediente_id=selected_expediente_id_for_generation(),
                        auto_build_snapshot=True,
                        flatten=_bool_to_int(flatten.value) == 1,
                    )

                    output = generated.get("output") or {}
                    pdf_info = generated.get("pdf") or {}
                    validation = generated.get("validation") or {}
                    summary = generated.get("summary") or {}
                    empty_fields = generated.get("empty_fields") or []
                    errors = validation.get("errors") or []
                    skipped = pdf_info.get("skipped_payload_fields") or []
                    page_errors = pdf_info.get("page_update_errors") or []
                    payload = generated.get("payload") or {}

                    is_valid = bool(summary.get("valid", validation.get("valid"))) and not page_errors
                    status_color = "#027A48" if is_valid else "#B42318"
                    status_text = "PDF GENERADO CORRECTAMENTE" if is_valid else "PDF GENERADO CON AVISOS"

                    result_box.content = ft.Column(
                        controls=[
                            ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Archivos generados", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(f"PDF: {output.get('pdf_path') or pdf_info.get('pdf_path') or '-'}", size=12, color="#101828", selectable=True),
                                        ft.Text(f"Payload JSON: {output.get('json_path') or '-'}", size=12, color="#101828", selectable=True),
                                        ft.Text(f"Directorio: {output.get('directory') or '-'}", size=12, color=Q_MUTED, selectable=True),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Text(
                                f"Campos payload: {summary.get('payload_fields', len(payload))} · "
                                f"Campos PDF rellenados: {pdf_info.get('filled_count', 0)} · "
                                f"Saltados: {pdf_info.get('skipped_payload_count', len(skipped))} · "
                                f"Vacíos: {summary.get('empty_fields', len(empty_fields))}",
                                size=12,
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                "Errores:\n- " + "\n- ".join(errors) if errors else "Sin errores de validación.",
                                size=12,
                                color="#B42318" if errors else "#027A48",
                                selectable=True,
                            ),
                            ft.Text(
                                "Campos payload no presentes en PDF:\n- " + "\n- ".join(skipped) if skipped else "Sin campos payload saltados.",
                                size=12,
                                color="#B42318" if skipped else "#027A48",
                                selectable=True,
                            ),
                            ft.Text(
                                "Avisos por página:\n- " + "\n- ".join(page_errors) if page_errors else "Sin errores de escritura por página.",
                                size=12,
                                color="#B42318" if page_errors else "#027A48",
                                selectable=True,
                            ),
                        ],
                        spacing=10,
                    )
                    page.update()

                except Exception as exc:
                    result_box.content = error_alert(str(exc))
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Generar PDF rellenable", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content=ft.Container(
                    width=940,
                    height=620,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Plantilla", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Código: {template.get('codigo') or '-'} · PDF: {template.get('template_path') or '-'}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(help_text, size=12, color=Q_MUTED),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            ft.Row([expediente_selector, flatten], wrap=True, spacing=10),
                            ft.Row(
                                controls=[
                                    primary_button("Generar PDF", run_generate),
                                    secondary_button("Cerrar", lambda ev: close_generate_document_template_pdf_dialog(dialog)),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def close_generate_document_template_pdf_dialog(dialog):
            dialog.open = False
            page.update()

        form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.ARTICLE, size=18, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                width=36,
                                height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Editar plantilla documental" if state.get("editing_document_template_id") else "Alta de plantilla documental",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        "Registra EX oficiales, designaciones, autorizaciones y modelos generales sin hardcodear documentos.",
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([codigo, nombre, categoria, tipo_destino], wrap=True, spacing=10),
                    nombre_oficial,
                    descripcion,
                    ft.Row([template_type, requiere_expediente, activo, orden], wrap=True, spacing=10),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Rutas y mapper", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(
                                    "Usa rutas relativas. Ejemplo EX: templates/ex_forms/EX10/template.pdf. Ejemplo documento: templates/documents/DESIGNACION_REPRESENTANTE/template.docx.",
                                    size=12,
                                    color=Q_MUTED,
                                ),
                                mapper_destino,
                                template_path,
                                fields_json_path,
                                metadata_json_path,
                                ft.Row(
                                    controls=[
                                        secondary_button("Proponer rutas", apply_default_paths),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Row(
                        [
                            primary_button("Guardar plantilla", lambda e: run_save(save_template, "Plantilla documental guardada")),
                            secondary_button("Cancelar", lambda e: cancel_edit()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            ),
        )

        rows = []
        for template in templates:
            active_color = "#027A48" if int(template.get("activo") or 0) else "#B42318"
            requiere_color = "#027A48" if int(template.get("requiere_expediente") or 0) else Q_MUTED
            rows.append(
                [
                    _mapper_actions_menu(
                        on_test=lambda e, tid=template["id"]: open_test_document_template_dialog(tid),
                        on_export=lambda e, tid=template["id"]: open_export_document_template_payload_dialog(tid),
                        on_generate_docx=(
                            (lambda e, tid=template["id"]: open_generate_document_template_docx_dialog(tid))
                            if str(template.get("template_type") or "").strip().lower() == "docx"
                            else None
                        ),
                        on_generate_pdf=(
                            (lambda e, tid=template["id"]: open_generate_document_template_pdf_dialog(tid))
                            if str(template.get("template_type") or "").strip().lower() in ("pdf", "pdf_acroform")
                            else None
                        ),
                        on_export_pdf_fields=(
                            (lambda e, tid=template["id"]: open_export_pdf_fields_json_dialog(tid))
                            if str(template.get("template_type") or "").strip().lower() in ("pdf", "pdf_acroform")
                            else None
                        ),
                        on_export_pdf_overlay=(
                            (lambda e, tid=template["id"]: open_export_pdf_fields_overlay_dialog(tid))
                            if str(template.get("template_type") or "").strip().lower() in ("pdf", "pdf_acroform")
                            else None
                        ),
                        on_edit=lambda e, tid=template["id"]: start_edit_template(tid),
                        on_delete=lambda e, tid=template["id"]: run_save(lambda tid=tid: delete_template(tid), "Plantilla eliminada"),
                    ),
                    template.get("codigo") or "-",
                    template.get("nombre") or "-",
                    ft.Text(template.get("categoria") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    template.get("tipo_destino") or "-",
                    template.get("template_type") or "-",
                    ft.Text("Sí" if template.get("requiere_expediente") else "No", color=requiere_color, weight=ft.FontWeight.W_600),
                    ft.Text("Sí" if template.get("activo") else "No", color=active_color, weight=ft.FontWeight.W_600),
                ]
            )

        metrics = [
            _mini_metric("Plantillas", len(templates), ft.Icons.ARTICLE),
            _mini_metric("EX", len([t for t in templates if t.get("categoria") == "EX"]), ft.Icons.DESCRIPTION),
            _mini_metric("Generales", len([t for t in templates if not int(t.get("requiere_expediente") or 0)]), ft.Icons.PUBLIC),
        ]

        return _expediente_workspace(
            "Plantillas documentales",
            "Catálogo general para EX oficiales, designaciones, autorizaciones, hojas de encargo, escritos y modelos internos.",
            ft.Column(
                controls=[
                    form,
                    _table(["Acciones", "Código", "Nombre", "Categoría", "Destino", "Tipo plantilla", "Requiere exp.", "Activo"], rows, height=340),
                ],
                spacing=14,
            ),
            metrics=metrics,
        )


    def build_documentos():
        try:
            required_count = len(config_service.get_documentos_requeridos())
        except Exception:
            required_count = 0

        try:
            template_count = len(document_template_service.list_document_templates(active_only=False))
        except Exception:
            template_count = 0

        tab = state.get("documentos_tab", "requeridos")
        body = build_plantillas_documentales() if tab == "plantillas" else build_documentos_requeridos()

        return ft.Column(
            controls=[
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#B9D7FF"),
                    border_radius=18,
                    padding=16,
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.DESCRIPTION, size=26, color=Q_PRIMARY),
                                bgcolor="#FFFFFF",
                                border_radius=24,
                                width=48,
                                height=48,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("Documentación", size=24, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text("Configura documentos requeridos y plantillas documentales reutilizables.", size=13, color=Q_MUTED),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Row(
                                controls=[
                                    _mini_metric("Requeridos", required_count, ft.Icons.CHECKLIST),
                                    _mini_metric("Plantillas", template_count, ft.Icons.ARTICLE),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                ft.Row(
                    controls=[
                        _documentos_tab_button("Documentos requeridos", "requeridos", ft.Icons.CHECKLIST, "Reglas por expediente"),
                        _documentos_tab_button("Plantillas documentales", "plantillas", ft.Icons.ARTICLE, "EX y modelos internos"),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                body,
            ],
            spacing=14,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )


    def build_catalog(title, subtitle, table, getter, create_fn, update_fn):
        editing = config_service.get_record(table, state["editing_id"]) if state["editing_id"] else {}
        codigo = text_input("Código", editing.get("codigo", ""), width=220)
        nombre = required_text_input("Nombre", editing.get("nombre", ""), width=300)
        color = text_input("Color HEX", editing.get("color", "#0057B8"), width=150)
        orden = text_input("Orden", str(editing.get("orden", 0)), width=100)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        def save():
            data = {
                "codigo": codigo.value,
                "nombre": nombre.value,
                "color": color.value,
                "orden": int(orden.value or 0),
                "activo": _bool_to_int(activo.value),
            }
            if not data["nombre"]:
                raise ValueError("El nombre es obligatorio")
            if state["editing_id"]:
                update_fn(state["editing_id"], data)
            else:
                create_fn(data)

        form = ft.Column(
            controls=[
                ft.Row([codigo, nombre, color, orden, activo], wrap=True, spacing=10),
                ft.Text(
                    "Código opcional: se guarda en MAYÚSCULAS. El color debe indicarse en formato HEX, por ejemplo #0057B8.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row(
                    [
                        primary_button("Guardar", lambda e: run_save(save, f"{title} guardado")),
                        secondary_button("Cancelar", lambda e: cancel_edit()),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )

        rows = []
        for r in getter():
            color_chip = ft.Container(
                width=22,
                height=22,
                bgcolor=r.get("color") or "#0057B8",
                border_radius=20,
            )
            rows.append(
                [
                    r["codigo"],
                    r["nombre"],
                    color_chip,
                    r["orden"],
                    "Sí" if r["activo"] else "No",
                    ft.Row([edit_button(r["id"]), delete_button(table, r["id"])], spacing=8),
                ]
            )

        return config_section_card(
            title,
            subtitle,
            ft.Column(
                [
                    form,
                    _table(["Código", "Nombre", "Color", "Orden", "Activo", "Acciones"], rows),
                ],
                spacing=16,
            ),
        )

    def build_estados():
        return build_catalog(
            "Estados expediente",
            "Estados parametrizables para expedientes futuros.",
            "config_estados_expediente",
            config_service.get_estados_expediente,
            config_service.create_estado_expediente,
            config_service.update_estado_expediente,
        )

    def build_prioridades():
        return build_catalog(
            "Prioridades",
            "Prioridades operativas reutilizables en expedientes y escaneado.",
            "config_prioridades",
            config_service.get_prioridades,
            config_service.create_prioridad,
            config_service.update_prioridad,
        )

    def build_box():
        editing = config_service.get_record("config_box_rutas", state["editing_id"]) if state["editing_id"] else {}
        tipos_opts = tipo_options()
        selected_tipo = ""
        if editing:
            selected_tipo = next((x for x in tipos_opts if x.startswith(str(editing["tipo_expediente_id"]) + " - ")), "")

        tipo = select_input("Tipo expediente", tipos_opts, value=selected_tipo, width=320)
        ruta = required_text_input("Ruta relativa desde Escritorio", editing.get("ruta_box", ""), width=560)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        ayuda = ft.Column(
            controls=[
                ft.Text(
                    "No guardes rutas absolutas tipo C:/Users/Nacho/...",
                    size=12,
                    color="#B42318",
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Guarda rutas relativas al Escritorio. Ejemplo: Box/NACIONALIDADES/2023",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Text(
                    "El módulo Box resolverá automáticamente la ruta en cada ordenador.",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            spacing=3,
        )

        def save():
            tid = selected_id(tipo.value)
            if not tid:
                raise ValueError("Selecciona un tipo de expediente")
            data = {
                "tipo_expediente_id": tid,
                "ruta_box": ruta.value,
                "activo": _bool_to_int(activo.value),
            }
            if not data["ruta_box"]:
                raise ValueError("La ruta Box es obligatoria")
            if state["editing_id"]:
                config_service.update_box_ruta(state["editing_id"], data)
            else:
                config_service.create_box_ruta(data)

        form = ft.Column(
            controls=[
                ft.Row([tipo, ruta, activo], wrap=True, spacing=10),
                ayuda,
                ft.Row(
                    [
                        primary_button("Guardar", lambda e: run_save(save, "Ruta Box guardada")),
                        secondary_button("Cancelar", lambda e: cancel_edit()),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )

        rows = []
        for r in config_service.get_box_rutas(include_resolved=True):
            estado_ruta = "Existe" if r.get("ruta_existe") else "No encontrada"
            estado_color = "#027A48" if r.get("ruta_existe") else "#B42318"
            rows.append(
                [
                    r["tipo_expediente_nombre"],
                    r["ruta_box"],
                    ft.Text(estado_ruta, color=estado_color, weight=ft.FontWeight.W_600),
                    r.get("ruta_resuelta") or "—",
                    "Sí" if r["activo"] else "No",
                    ft.Row([edit_button(r["id"]), delete_button("config_box_rutas", r["id"])], spacing=8),
                ]
            )

        return config_section_card(
            "Rutas Box",
            "Rutas relativas para vigilancia documental. Se resuelven automáticamente según el ordenador.",
            ft.Column(
                [
                    form,
                    _table(["Tipo", "Ruta relativa", "Estado", "Ruta resuelta", "Activo", "Acciones"], rows),
                ],
                spacing=16,
            ),
        )

    def build_nomenclaturas():
        editing = config_service.get_record("config_nomenclaturas_documentales", state["editing_id"]) if state["editing_id"] else {}
        tipos_opts = tipo_options()
        docs = config_service.get_documentos_requeridos(active_only=True)
        doc_opts = [f"{d['id']} - {d['tipo_expediente_nombre']} - {d['nombre_documento']}" for d in docs]

        selected_tipo = ""
        selected_doc = ""
        if editing:
            selected_tipo = next((x for x in tipos_opts if x.startswith(str(editing["tipo_expediente_id"]) + " - ")), "")
            selected_doc = next((x for x in doc_opts if x.startswith(str(editing["documento_id"]) + " - ")), "")

        tipo = select_input("Tipo expediente", tipos_opts, value=selected_tipo, width=280)
        documento = select_input("Documento", doc_opts, value=selected_doc, width=420)
        patron = required_text_input("Patrón nombre", editing.get("patron_nombre", ""), width=260)
        extensiones = text_input("Extensiones", editing.get("extension_permitida", "pdf,jpg,jpeg,png"), width=200)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        def save():
            tid = selected_id(tipo.value)
            did = selected_id(documento.value)
            if not tid or not did:
                raise ValueError("Selecciona tipo y documento")
            data = {
                "tipo_expediente_id": tid,
                "documento_id": did,
                "patron_nombre": patron.value,
                "extension_permitida": extensiones.value,
                "activo": _bool_to_int(activo.value),
            }
            if not data["patron_nombre"]:
                raise ValueError("El patrón es obligatorio")
            if state["editing_id"]:
                config_service.update_nomenclatura(state["editing_id"], data)
            else:
                config_service.create_nomenclatura(data)

        form = ft.Column(
            controls=[
                ft.Row([tipo, documento], wrap=True, spacing=10),
                ft.Row([patron, extensiones, activo], wrap=True, spacing=10),
                ft.Row(
                    [
                        primary_button("Guardar", lambda e: run_save(save, "Nomenclatura guardada")),
                        secondary_button("Cancelar", lambda e: cancel_edit()),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )

        rows = []
        for r in config_service.get_nomenclaturas():
            rows.append(
                [
                    r["tipo_expediente_nombre"],
                    r["nombre_documento"],
                    r["patron_nombre"],
                    r["extension_permitida"],
                    "Sí" if r["activo"] else "No",
                    ft.Row([edit_button(r["id"]), delete_button("config_nomenclaturas_documentales", r["id"])], spacing=8),
                ]
            )

        return config_section_card(
            "Nomenclaturas documentales",
            "Patrones para detección documental futura.",
            ft.Column(
                [
                    form,
                    _table(["Tipo", "Documento", "Patrón", "Extensiones", "Activo", "Acciones"], rows),
                ],
                spacing=16,
            ),
        )


    def build_formularios_expediente():
        """
        Constructor de formularios dinámicos por tipo/subtipo.

        Se mantiene separado de Tipos y Subtipos para evitar una pantalla larga.
        """
        try:
            formularios = dynamic_form_service.list_formularios()
        except Exception as exc:
            return _expediente_workspace(
                "Formularios específicos",
                "Constructor de campos específicos por tipo y subtipo de expediente.",
                error_alert(f"No se pudieron cargar formularios dinámicos: {exc}"),
            )

        tipos_opts = tipo_options()
        subtipos_records = config_service.get_subtipos_expediente(active_only=True)
        subtipo_opts = ["Sin subtipo"] + [
            f"{s['id']} - {s['tipo_expediente_nombre']} - {s['nombre']}"
            for s in subtipos_records
        ]

        selected_formulario_id = state.get("selected_formulario_id")
        if not selected_formulario_id and formularios:
            selected_formulario_id = formularios[0]["id"]
            state["selected_formulario_id"] = selected_formulario_id

        formulario_editing = (
            dynamic_form_service.get_formulario(state.get("editing_formulario_id"))
            if state.get("editing_formulario_id") else {}
        )

        selected_tipo = ""
        selected_subtipo = "Sin subtipo"
        if formulario_editing:
            selected_tipo = next(
                (x for x in tipos_opts if x.startswith(str(formulario_editing.get("tipo_expediente_id")) + " - ")),
                "",
            )
            selected_subtipo = next(
                (x for x in subtipo_opts if x.startswith(str(formulario_editing.get("subtipo_expediente_id")) + " - ")),
                "Sin subtipo",
            )

        formulario_tipo = select_input("Tipo expediente", tipos_opts, value=selected_tipo, width=300)
        formulario_subtipo = select_input("Subtipo", subtipo_opts, value=selected_subtipo, width=360)
        formulario_codigo = text_input("Código formulario", formulario_editing.get("codigo", ""), width=220)
        formulario_nombre = required_text_input("Nombre formulario", formulario_editing.get("nombre", ""), width=320)
        formulario_orden = text_input("Orden", str(formulario_editing.get("orden", 0)), width=100)
        formulario_activo = select_input("Activo", _bool_options(), value=_active_value(formulario_editing) if formulario_editing else "Sí", width=120)
        formulario_descripcion = multiline_input("Descripción formulario", formulario_editing.get("descripcion", ""), width=620, height=80)

        def save_formulario():
            tid = selected_id(formulario_tipo.value)
            if not tid:
                raise ValueError("Selecciona un tipo de expediente")
            data = {
                "tipo_expediente_id": tid,
                "subtipo_expediente_id": selected_id(formulario_subtipo.value),
                "codigo": formulario_codigo.value,
                "nombre": formulario_nombre.value,
                "descripcion": formulario_descripcion.value,
                "orden": int(formulario_orden.value or 0),
                "activo": _bool_to_int(formulario_activo.value),
            }
            if not data["nombre"]:
                raise ValueError("El nombre del formulario es obligatorio")
            if state.get("editing_formulario_id"):
                dynamic_form_service.update_formulario(state["editing_formulario_id"], data)
                state["selected_formulario_id"] = state["editing_formulario_id"]
            else:
                state["selected_formulario_id"] = dynamic_form_service.create_formulario(data)
            state["editing_formulario_id"] = None

        def select_formulario(formulario_id):
            state["selected_formulario_id"] = formulario_id
            state["editing_campo_id"] = None
            state["message"] = None
            refresh()

        def start_edit_formulario(record_id):
            state["editing_formulario_id"] = record_id
            state["selected_formulario_id"] = record_id
            state["message"] = None
            refresh()

        def delete_formulario(record_id):
            dynamic_form_service.delete_formulario(record_id)
            if state.get("selected_formulario_id") == record_id:
                state["selected_formulario_id"] = None
            state["editing_formulario_id"] = None
            state["editing_campo_id"] = None

        formulario_rows = []
        for f in formularios:
            formulario_rows.append(
                [
                    f.get("tipo_expediente_nombre") or "-",
                    f.get("subtipo_expediente_nombre") or "General",
                    f.get("codigo") or "-",
                    f.get("nombre") or "-",
                    f.get("orden") or 0,
                    "Sí" if f.get("activo") else "No",
                    ft.Row(
                        [
                            secondary_button("Seleccionar", lambda e, fid=f["id"]: select_formulario(fid)),
                            secondary_button("Editar", lambda e, fid=f["id"]: start_edit_formulario(fid)),
                            danger_button("Eliminar", lambda e, fid=f["id"]: run_save(lambda: delete_formulario(fid), "Formulario eliminado")),
                        ],
                        spacing=8,
                    ),
                ]
            )

        selected_formulario = dynamic_form_service.get_formulario(state.get("selected_formulario_id")) if state.get("selected_formulario_id") else None
        campo_editing = dynamic_form_service.get_campo_formulario(state.get("editing_campo_id")) if state.get("editing_campo_id") else {}

        campo_codigo = text_input("Código técnico", campo_editing.get("codigo", ""), width=220)
        campo_etiqueta = required_text_input("Etiqueta", campo_editing.get("etiqueta", ""), width=320)
        campo_tipo = select_input(
            "Tipo campo",
            [
                "texto", "numero", "fecha", "textarea", "select", "boolean",
                "autocomplete_cliente", "autocomplete_familiar", "autocomplete_empleador",
                "actividad_cnae", "cno_sepe", "contrato_trabajo", "representante",
            ],
            value=campo_editing.get("tipo_campo", "texto") if campo_editing else "texto",
            width=220,
        )
        campo_obligatorio = select_input("Obligatorio", _bool_options(), value="Sí" if int(campo_editing.get("obligatorio", 0)) else "No", width=140)
        campo_opciones = text_input("Opciones select separadas por |", campo_editing.get("opciones_json", ""), width=520)
        campo_placeholder = text_input("Placeholder", campo_editing.get("placeholder", ""), width=320)
        campo_ayuda = text_input("Ayuda", campo_editing.get("ayuda", ""), width=420)
        campo_valor_defecto = text_input("Valor defecto", campo_editing.get("valor_defecto", ""), width=240)
        campo_orden = text_input("Orden", str(campo_editing.get("orden", 0)), width=100)
        campo_activo = select_input("Activo", _bool_options(), value=_active_value(campo_editing) if campo_editing else "Sí", width=120)

        def save_campo():
            if not state.get("selected_formulario_id"):
                raise ValueError("Selecciona primero un formulario")
            data = {
                "formulario_id": state["selected_formulario_id"],
                "codigo": campo_codigo.value,
                "etiqueta": campo_etiqueta.value,
                "tipo_campo": campo_tipo.value,
                "obligatorio": _bool_to_int(campo_obligatorio.value),
                "opciones": campo_opciones.value,
                "placeholder": campo_placeholder.value,
                "ayuda": campo_ayuda.value,
                "valor_defecto": campo_valor_defecto.value,
                "orden": int(campo_orden.value or 0),
                "activo": _bool_to_int(campo_activo.value),
            }
            if not data["etiqueta"]:
                raise ValueError("La etiqueta del campo es obligatoria")
            if state.get("editing_campo_id"):
                dynamic_form_service.update_campo_formulario(state["editing_campo_id"], data)
            else:
                dynamic_form_service.create_campo_formulario(state["selected_formulario_id"], data)
            state["editing_campo_id"] = None

        def start_edit_campo(record_id):
            state["editing_campo_id"] = record_id
            state["message"] = None
            refresh()

        def delete_campo(record_id):
            dynamic_form_service.delete_campo_formulario(record_id)
            state["editing_campo_id"] = None

        campo_rows = []
        if state.get("selected_formulario_id"):
            for c in dynamic_form_service.list_campos_formulario(state["selected_formulario_id"]):
                campo_rows.append(
                    [
                        c.get("codigo") or "-",
                        c.get("etiqueta") or "-",
                        c.get("tipo_campo") or "-",
                        "Sí" if c.get("obligatorio") else "No",
                        c.get("orden") or 0,
                        "Sí" if c.get("activo") else "No",
                        ft.Row(
                            [
                                secondary_button("Editar", lambda e, cid=c["id"]: start_edit_campo(cid)),
                                danger_button("Eliminar", lambda e, cid=c["id"]: run_save(lambda: delete_campo(cid), "Campo eliminado")),
                            ],
                            spacing=8,
                        ),
                    ]
                )

        formulario_form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.DYNAMIC_FORM, size=18, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                width=36,
                                height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("Alta / edición de formulario", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Text("Define un formulario por tipo/subtipo. Si no eliges subtipo, actúa como general.", size=12, color=Q_MUTED),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row([formulario_tipo, formulario_subtipo, formulario_codigo, formulario_nombre], wrap=True, spacing=10),
                    ft.Row([formulario_orden, formulario_activo], wrap=True, spacing=10),
                    formulario_descripcion,
                    ft.Row(
                        [
                            primary_button("Guardar formulario", lambda e: run_save(save_formulario, "Formulario guardado")),
                            secondary_button("Cancelar", lambda e: cancel_edit()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            ),
        )

        campo_form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"Campos del formulario: {(selected_formulario or {}).get('nombre') or 'sin seleccionar'}",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text("Los códigos técnicos se usarán después para mapear Mercurio/PDF.", size=12, color=Q_MUTED),
                    ft.Row([campo_codigo, campo_etiqueta, campo_tipo, campo_obligatorio], wrap=True, spacing=10),
                    campo_opciones,
                    ft.Row([campo_placeholder, campo_ayuda, campo_valor_defecto], wrap=True, spacing=10),
                    ft.Row([campo_orden, campo_activo], wrap=True, spacing=10),
                    ft.Row(
                        [
                            primary_button("Guardar campo", lambda e: run_save(save_campo, "Campo guardado")),
                            secondary_button("Cancelar campo", lambda e: cancel_edit()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            ),
        )

        body_controls = [
            formulario_form,
            _table(["Tipo", "Subtipo", "Código", "Formulario", "Orden", "Activo", "Acciones"], formulario_rows, height=260),
        ]

        if selected_formulario:
            body_controls.extend([
                campo_form,
                _table(["Código", "Etiqueta", "Tipo", "Obligatorio", "Orden", "Activo", "Acciones"], campo_rows, height=280),
            ])
        else:
            body_controls.append(empty_state("Selecciona o crea un formulario para configurar sus campos"))

        return _expediente_workspace(
            "Formularios específicos",
            "Constructor de fichas específicas por tipo y subtipo de expediente.",
            ft.Column(body_controls, spacing=14),
            metrics=[_mini_metric("Formularios", len(formulario_rows), ft.Icons.DYNAMIC_FORM)],
        )




    def open_snapshot_fields_dialog():
        try:
            expedientes = expedient_service.get_expedientes(active_only=True)
        except Exception as exc:
            fail(str(exc))
            refresh()
            return

        expediente_options = []
        for expediente in expedientes:
            expediente_options.append(
                f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NUMERO'}"
            )

        selector = select_input(
            "Expediente",
            expediente_options,
            value=expediente_options[0] if expediente_options else "",
            width=520,
        )

        results_column = ft.Column(
            controls=[
                ft.Text(
                    "Selecciona un expediente y carga las rutas disponibles del snapshot.",
                    size=12,
                    color=Q_MUTED,
                )
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        def load_fields(e=None):
            expediente_id = selected_id(selector.value)

            if not expediente_id:
                results_column.controls = [error_alert("Selecciona un expediente")]
                page.update()
                return

            try:
                latest = snapshot_service.load_latest_snapshot(expediente_id)

                if not latest:
                    results_column.controls = [
                        error_alert("El expediente no tiene snapshots")
                    ]
                    page.update()
                    return

                snapshot = latest.get("snapshot") or {}

                paths = form_mapper_service.get_snapshot_field_paths(snapshot)

                controls = [
                    ft.Container(
                        bgcolor="#EAF3FF",
                        border=ft.border.all(1, "#B9D7FF"),
                        border_radius=12,
                        padding=10,
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    f"Snapshot v{latest.get('version')}",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    f"{len(paths)} rutas disponibles",
                                    size=12,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                        ),
                    )
                ]

                for path in paths:
                    controls.append(
                        ft.Container(
                            bgcolor="#FFFFFF",
                            border=ft.border.all(1, Q_BORDER),
                            border_radius=10,
                            padding=10,
                            content=ft.Text(
                                path,
                                selectable=True,
                                size=12,
                                color="#101828",
                            ),
                        )
                    )

                results_column.controls = controls
                page.update()

            except Exception as exc:
                results_column.controls = [error_alert(str(exc))]
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Explorador de campos snapshot",
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            content=ft.Container(
                width=920,
                height=720,
                bgcolor="#F8FAFC",
                border_radius=18,
                padding=14,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Visualiza todas las rutas disponibles del snapshot para construir mappings sin memorizar campos.",
                            size=12,
                            color=Q_MUTED,
                        ),
                        selector,
                        ft.Row(
                            controls=[
                                primary_button("Cargar campos", load_fields),
                            ],
                            spacing=8,
                        ),
                        ft.Container(
                            expand=True,
                            content=results_column,
                        ),
                    ],
                    spacing=12,
                    expand=True,
                ),
            ),
            actions=[
                secondary_button("Cerrar", lambda e: close_snapshot_fields_dialog(dialog))
            ],
        )

        page.overlay.append(dialog)
        dialog.open = True
        page.update()


    def close_snapshot_fields_dialog(dialog):
        dialog.open = False
        page.update()


    def build_mappers_expediente():
        """
        Administración profesional de mappers dinámicos.

        Permite configurar la transformación:
        Snapshot expediente → payload destino (Mercurio / EX / PDF / futuros adaptadores)

        Esta vista solo administra templates. El motor de mapeo sigue separado en
        backend/services/form_mapper_service.py.
        """
        try:
            mapper_templates = mapper_admin_service.list_mapper_templates()
        except Exception as exc:
            return _expediente_workspace(
                "Mappers",
                "Plantillas de transformación desde snapshot hacia Mercurio, EX y otros destinos.",
                error_alert(f"No se pudieron cargar los mappers: {exc}"),
            )

        general_tipo_option = "General / Sin tipo"
        tipos_opts = [general_tipo_option] + tipo_options()
        subtipos_records = config_service.get_subtipos_expediente(active_only=True)
        subtipo_opts = ["Sin subtipo"] + [
            f"{s['id']} - {s['tipo_expediente_nombre']} - {s['nombre']}"
            for s in subtipos_records
        ]

        editing = mapper_admin_service.get_mapper_template(state.get("editing_mapper_id")) if state.get("editing_mapper_id") else {}

        selected_tipo = general_tipo_option
        selected_subtipo = "Sin subtipo"
        if editing:
            if editing.get("tipo_expediente_id"):
                selected_tipo = next(
                    (x for x in tipos_opts if x.startswith(str(editing.get("tipo_expediente_id")) + " - ")),
                    general_tipo_option,
                )
            else:
                selected_tipo = general_tipo_option

            selected_subtipo = next(
                (x for x in subtipo_opts if x.startswith(str(editing.get("subtipo_expediente_id")) + " - ")),
                "Sin subtipo",
            )

        codigo = text_input("Código mapper", editing.get("codigo", ""), width=240)
        nombre = required_text_input("Nombre", editing.get("nombre", ""), width=320)
        tipo_destino = select_input(
            "Destino",
            ["MERCURIO", "EX", "PDF", "WORD", "OCR", "OTRO"],
            value=editing.get("tipo_destino", "MERCURIO") if editing else "MERCURIO",
            width=180,
        )
        tipo = select_input("Tipo expediente", tipos_opts, value=selected_tipo, width=300)
        subtipo = select_input("Subtipo", subtipo_opts, value=selected_subtipo, width=360)
        version = text_input("Versión", str(editing.get("version", 1)), width=100)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        default_mapper = '{\n  "nombre": "cliente.nombre",\n  "apellido1": "cliente.primer_apellido",\n  "nie": "cliente.nie"\n}'
        default_required = '[\n  "nombre",\n  "apellido1"\n]'

        try:
            available_blocks = mapper_admin_service.list_mapper_blocks()
        except Exception:
            available_blocks = []

        selected_block_codes = editing.get("block_codes") or []

        block_checkboxes = []

        def _safe_json_object(raw):
            try:
                data = json.loads(raw or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        def _safe_json_list(raw):
            try:
                data = json.loads(raw or "[]")
                return data if isinstance(data, list) else []
            except Exception:
                return []

        def apply_mapper_block(block, checked):
            block_mapper = _safe_json_object(block.get("mapper_json"))
            block_required = _safe_json_list(block.get("required_fields_json"))

            current_mapper = _safe_json_object(mapper_json.value)
            current_required = _safe_json_list(required_fields_json.value)

            if checked:
                current_mapper.update(block_mapper)

                for field in block_required:
                    if field not in current_required:
                        current_required.append(field)
            else:
                for key, value in block_mapper.items():
                    if current_mapper.get(key) == value:
                        current_mapper.pop(key, None)

                for field in block_required:
                    if field in current_required:
                        current_required.remove(field)

            mapper_json.value = json.dumps(current_mapper, ensure_ascii=False, indent=2)
            required_fields_json.value = json.dumps(current_required, ensure_ascii=False, indent=2)
            state["message"] = None
            page.update()

        for block in available_blocks:
            checkbox = ft.Checkbox(
                label=f"{block.get('codigo')} · {block.get('nombre')}",
                value=block.get("codigo") in selected_block_codes,
                on_change=lambda e, b=block: apply_mapper_block(b, bool(e.control.value)),
            )
            checkbox.block_code = block.get("codigo")
            block_checkboxes.append(checkbox)

        mapper_json = multiline_input(
            "Mapper JSON",
            editing.get("mapper_json") or default_mapper,
            width=760,
            height=180,
        )
        required_fields_json = multiline_input(
            "Campos obligatorios JSON",
            editing.get("required_fields_json") or default_required,
            width=760,
            height=110,
        )

        insert_key = text_input("Key destino", "", width=220)
        insert_value = text_input("Ruta origen snapshot", "", width=420)
        insert_static_value = text_input("Valor estático", "", width=420)
        insert_equals_source = text_input("Ruta a comparar", "", width=300)
        insert_equals_expected = text_input("Valor esperado", "", width=260)
        insert_slice_source = text_input("Ruta a cortar", "", width=300)
        insert_slice_start = text_input("Inicio", "", width=90)
        insert_slice_end = text_input("Fin", "", width=90)
        insert_join_sources = multiline_input("Rutas a unir (una por línea)", "", width=420, height=82)
        insert_join_separator = text_input("Separador", " ", width=120)
        insert_today_format = text_input("Formato fecha", "%d/%m/%Y", width=180)

        def insert_mapping_pair(e=None):
            key = (insert_key.value or "").strip()
            value = (insert_value.value or "").strip()

            if not key:
                fail("Indica la key destino del mapper")
                page.update()
                return

            if not value:
                fail("Indica la ruta origen del snapshot")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = value
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_value.value = ""
            state["message"] = None
            page.update()

        def insert_static_pair(e=None):
            key = (insert_key.value or "").strip()
            value = (insert_static_value.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if value == "":
                fail("Indica el valor estático")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__static__:{value}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_static_value.value = ""
            state["message"] = None
            page.update()

        def insert_equals_pair(e=None):
            key = (insert_key.value or "").strip()
            source = (insert_equals_source.value or "").strip()
            expected = (insert_equals_expected.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not source:
                fail("Indica la ruta origen que quieres comparar")
                page.update()
                return

            if expected == "":
                fail("Indica el valor esperado")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__equals__:{source}:{expected}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_equals_source.value = ""
            insert_equals_expected.value = ""
            state["message"] = None
            page.update()

        def insert_slice_pair(e=None):
            key = (insert_key.value or "").strip()
            source = (insert_slice_source.value or "").strip()
            start = (insert_slice_start.value or "").strip()
            end = (insert_slice_end.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not source:
                fail("Indica la ruta origen que quieres cortar")
                page.update()
                return

            if start == "" and end == "":
                fail("Indica al menos inicio o fin para el corte")
                page.update()
                return

            for label, raw in (("inicio", start), ("fin", end)):
                if raw and not raw.lstrip("-").isdigit():
                    fail(f"El valor de {label} debe ser numérico")
                    page.update()
                    return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__slice__:{source}:{start}:{end}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_slice_source.value = ""
            insert_slice_start.value = ""
            insert_slice_end.value = ""
            state["message"] = None
            page.update()

        def insert_join_pair(e=None):
            key = (insert_key.value or "").strip()
            raw_sources = (insert_join_sources.value or "").replace(",", "\n")
            sources = [item.strip() for item in raw_sources.splitlines() if item.strip()]
            separator = insert_join_separator.value
            if separator is None or separator == "":
                separator = " "

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not sources:
                fail("Indica al menos una ruta para unir")
                page.update()
                return

            if ":" in separator:
                fail("El separador de join no puede contener ':'")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__join__:{separator}:{':'.join(sources)}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_join_sources.value = ""
            insert_join_separator.value = " "
            state["message"] = None
            page.update()

        def insert_today_pair(e=None):
            key = (insert_key.value or "").strip()
            fmt = (insert_today_format.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__today__:{fmt}" if fmt else "__today__"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_today_format.value = "%d/%m/%Y"
            state["message"] = None
            page.update()

        mapping_insert_card = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Text("Insertar regla de mapping", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text("Crea el diccionario paso a paso: key destino → ruta origen del snapshot.", size=12, color=Q_MUTED),
                    ft.Row(
                        controls=[
                            insert_key,
                            insert_value,
                            primary_button("Insertar ruta", insert_mapping_pair),
                            secondary_button("Ver campos snapshot", lambda e: open_snapshot_fields_dialog()),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_static_value,
                            primary_button("Insertar estático", insert_static_pair),
                            ft.Text("Se guardará como __static__:valor", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_equals_source,
                            insert_equals_expected,
                            primary_button("Insertar equals", insert_equals_pair),
                            ft.Text("Se guardará como __equals__:ruta:valor", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_slice_source,
                            insert_slice_start,
                            insert_slice_end,
                            primary_button("Insertar slice", insert_slice_pair),
                            ft.Text("Se guardará como __slice__:ruta:inicio:fin", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_join_sources,
                            insert_join_separator,
                            primary_button("Insertar join", insert_join_pair),
                            ft.Text("Se guardará como __join__:separador:ruta1:ruta2", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_today_format,
                            primary_button("Insertar hoy", insert_today_pair),
                            ft.Text("Se guardará como __today__:formato", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=8,
            ),
        )

        def save_mapper():
            is_general_mapper = tipo.value == general_tipo_option
            tid = None if is_general_mapper else selected_id(tipo.value)
            subtipo_id = None if is_general_mapper else selected_id(subtipo.value)

            if not is_general_mapper and not tid:
                raise ValueError("Selecciona un tipo de expediente o usa General / Sin tipo")

            data = {
                "codigo": codigo.value,
                "nombre": nombre.value,
                "tipo_destino": tipo_destino.value,
                "tipo_expediente_id": tid,
                "subtipo_expediente_id": subtipo_id,
                "version": int(version.value or 1),
                "activo": _bool_to_int(activo.value),
                "mapper_json": mapper_json.value,
                "required_fields_json": required_fields_json.value,
                "block_codes_json": json.dumps(
                    [
                        cb.block_code
                        for cb in block_checkboxes
                        if cb.value
                    ],
                    ensure_ascii=False,
                ),
            }

            if state.get("editing_mapper_id"):
                mapper_admin_service.update_mapper_template(state["editing_mapper_id"], data)
            else:
                mapper_admin_service.create_mapper_template(data)

            state["editing_mapper_id"] = None

        def start_edit_mapper(record_id):
            state["editing_mapper_id"] = record_id
            state["message"] = None
            refresh()

        def delete_mapper(record_id):
            mapper_admin_service.delete_mapper_template(record_id)
            state["editing_mapper_id"] = None

        def open_test_mapper_dialog(template_id):
            template = mapper_admin_service.get_mapper_template(template_id)
            if not template:
                fail("Mapper no encontrado")
                refresh()
                return

            try:
                expedientes = expedient_service.get_expedientes(active_only=True)
            except Exception as exc:
                fail(f"No se pudieron cargar expedientes: {exc}")
                refresh()
                return

            expediente_options = []
            for expediente in expedientes:
                cliente_nombre = " ".join(
                    part for part in [
                        expediente.get("cliente_nombre"),
                        expediente.get("cliente_primer_apellido"),
                        expediente.get("cliente_segundo_apellido"),
                    ] if part
                ).strip()
                expediente_options.append(
                    f"{expediente['id']} - {expediente.get('numero_expediente') or 'SIN NÚMERO'} · {cliente_nombre or 'SIN CLIENTE'}"
                )

            expediente_selector = select_input(
                "Expediente con snapshot",
                expediente_options,
                value=expediente_options[0] if expediente_options else "",
                width=640,
            )

            result_box = ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=12,
                padding=12,
                content=ft.Text(
                    "Selecciona un expediente y pulsa Probar mapper.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

            def run_test(ev=None):
                expediente_id = selected_id(expediente_selector.value)
                if not expediente_id:
                    result_box.content = error_alert("Selecciona un expediente")
                    page.update()
                    return

                try:
                    preview = mapper_preview_service.preview_mapper_for_expedient(
                        expediente_id,
                        template_id,
                        auto_build_snapshot=True,
                    )

                    payload = preview.get("payload") or {}
                    validation = preview.get("validation") or {}
                    errors = validation.get("errors") or []
                    empty_fields = preview.get("empty_fields") or []
                    summary = preview.get("summary") or {}
                    snapshot_info = preview.get("snapshot") or {}

                    is_valid = bool(summary.get("valid"))
                    status_color = "#027A48" if is_valid else "#B42318"
                    status_text = "PREVIEW CORRECTO" if is_valid else "PREVIEW CON ERRORES"

                    if snapshot_info.get("generated_in_memory"):
                        snapshot_text = "Snapshot generado en memoria"
                    else:
                        snapshot_text = f"Snapshot v{snapshot_info.get('version') or '-'}"

                    result_box.content = ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(status_text, size=14, weight=ft.FontWeight.BOLD, color=status_color),
                                    ft.Text(snapshot_text, size=12, color=Q_MUTED),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Resumen", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Campos payload: {summary.get('payload_fields', len(payload))} · "
                                            f"Campos vacíos: {summary.get('empty_fields', len(empty_fields))} · "
                                            f"Errores required: {summary.get('required_errors', len(errors))}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
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
                            ft.Container(
                                bgcolor="#F8FAFC",
                                border=ft.border.all(1, Q_BORDER),
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    controls=[
                                        ft.Text("Payload generado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            json.dumps(payload, ensure_ascii=False, indent=2),
                                            size=12,
                                            color="#101828",
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ),
                        ],
                        spacing=10,
                    )
                    page.update()

                except Exception as exc:
                    result_box.content = error_alert(str(exc))
                    page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Probar mapper", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content=ft.Container(
                    width=900,
                    height=650,
                    bgcolor="#F8FAFC",
                    border_radius=18,
                    padding=14,
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                bgcolor="#EAF3FF",
                                border=ft.border.all(1, "#B9D7FF"),
                                border_radius=14,
                                padding=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(template.get("nombre") or template.get("codigo") or "Mapper", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                        ft.Text(
                                            f"Destino: {template.get('tipo_destino') or '-'} · Versión: {template.get('version') or 1}",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            "La prueba usa el último snapshot guardado del expediente. No abre Mercurio ni ejecuta Selenium.",
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ),
                            expediente_selector,
                            ft.Row(
                                controls=[
                                    primary_button("Probar mapper", run_test),
                                    secondary_button("Cerrar", lambda ev: close_test_mapper_dialog(dialog)),
                                ],
                                spacing=8,
                            ),
                            result_box,
                        ],
                        spacing=12,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
                actions=[],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def close_test_mapper_dialog(dialog):
            dialog.open = False
            page.update()

        form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.HUB, size=18, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                width=36,
                                height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Editar mapper seleccionado" if state.get("editing_mapper_id") else "Alta de mapper",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        "Transforma el snapshot validado del expediente en payloads para Mercurio, EX, PDF u otros destinos.",
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([codigo, nombre, tipo_destino, version, activo], wrap=True, spacing=10),
                    ft.Row([tipo, subtipo], wrap=True, spacing=10),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Bloques reutilizables asociados", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Estos checks pertenecen al formulario, no a la tabla; no generan el cuadro gris.", size=12, color=Q_MUTED),
                                ft.Row(block_checkboxes, wrap=True, spacing=8),
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Regla de mapping", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Formato: campo_destino → ruta_origen_snapshot. Ejemplo: nombre → cliente.nombre", size=12, color=Q_MUTED),
                                mapping_insert_card,
                                mapper_json,
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Validación mínima", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Lista JSON de campos destino que no pueden quedar vacíos.", size=12, color=Q_MUTED),
                                required_fields_json,
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Row(
                        [
                            primary_button("Guardar mapper", lambda e: run_save(save_mapper, "Mapper guardado")),
                            secondary_button("Ver campos snapshot", lambda e: open_snapshot_fields_dialog()),
                            secondary_button("Cancelar", lambda e: cancel_edit()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            ),
        )

        rows = []
        for m in mapper_templates:
            active_color = "#027A48" if int(m.get("activo") or 0) else "#B42318"
            rows.append(
                [
                    _mapper_actions_menu(
                        on_test=lambda e, mid=m["id"]: open_test_mapper_dialog(mid),
                        on_edit=lambda e, mid=m["id"]: start_edit_mapper(mid),
                        on_delete=lambda e, mid=m["id"]: run_save(lambda: delete_mapper(mid), "Mapper eliminado"),
                    ),
                    m.get("codigo") or "-",
                    m.get("nombre") or "-",
                    ft.Text(m.get("tipo_destino") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    m.get("tipo_expediente_nombre") or "General",
                    m.get("subtipo_expediente_nombre") or "General",
                    m.get("version") or 1,
                    ft.Text("Sí" if m.get("activo") else "No", color=active_color, weight=ft.FontWeight.W_600),
                ]
            )

        resumen_destinos = {}
        for m in mapper_templates:
            destino = m.get("tipo_destino") or "SIN_DESTINO"
            resumen_destinos[destino] = resumen_destinos.get(destino, 0) + 1

        metrics = [
            _mini_metric("Mappers", len(mapper_templates), ft.Icons.HUB),
            _mini_metric("Mercurio", resumen_destinos.get("MERCURIO", 0), ft.Icons.ROCKET_LAUNCH),
            _mini_metric("EX/PDF", resumen_destinos.get("EX", 0) + resumen_destinos.get("PDF", 0), ft.Icons.DESCRIPTION),
        ]

        return _expediente_workspace(
            "Mappers",
            "Plantillas configurables para convertir snapshots en datos listos para Mercurio, formularios EX, PDFs y futuras automatizaciones.",
            ft.Column(
                controls=[
                    form,
                    _table(["Acciones", "Código", "Nombre", "Destino", "Tipo", "Subtipo", "Versión", "Activo"], rows, height=340),
                ],
                spacing=14,
            ),
            metrics=metrics,
        )


    def build_mapper_blocks_expediente():
        """
        Administración profesional de bloques reutilizables de mapper.

        Cambio acotado:
        - Solo gestiona form_mapper_blocks.
        - No toca Mercurio, Selenium, snapshots ni templates existentes.
        """
        try:
            blocks = mapper_admin_service.list_mapper_blocks()
        except Exception as exc:
            return _expediente_workspace(
                "Mapper Blocks",
                "Bloques reutilizables para componer mappers sin duplicar campos.",
                error_alert(f"No se pudieron cargar los bloques de mapper: {exc}"),
            )

        editing = (
            mapper_admin_service.get_mapper_block(state.get("editing_mapper_block_id"))
            if state.get("editing_mapper_block_id")
            else {}
        )

        codigo = text_input("Código bloque", editing.get("codigo", ""), width=240)
        nombre = required_text_input("Nombre", editing.get("nombre", ""), width=320)
        descripcion = multiline_input("Descripción", editing.get("descripcion", ""), width=760, height=72)
        version = text_input("Versión", str(editing.get("version", 1)), width=100)
        activo = select_input("Activo", _bool_options(), value=_active_value(editing) if editing else "Sí", width=120)

        default_mapper = '{\n  "nombre": "cliente.nombre",\n  "apellido1": "cliente.primer_apellido",\n  "apellido2": "cliente.segundo_apellido",\n  "nie": "cliente.nie"\n}'
        default_required = '[\n  "nombre",\n  "apellido1"\n]'

        mapper_json = multiline_input(
            "Mapper JSON",
            editing.get("mapper_json") or default_mapper,
            width=760,
            height=190,
        )
        required_fields_json = multiline_input(
            "Campos obligatorios JSON",
            editing.get("required_fields_json") or default_required,
            width=760,
            height=110,
        )

        insert_key = text_input("Key destino", "", width=220)
        insert_value = text_input("Ruta origen snapshot", "", width=420)
        insert_static_value = text_input("Valor estático", "", width=420)
        insert_equals_source = text_input("Ruta a comparar", "", width=300)
        insert_equals_expected = text_input("Valor esperado", "", width=260)
        insert_slice_source = text_input("Ruta a cortar", "", width=300)
        insert_slice_start = text_input("Inicio", "", width=90)
        insert_slice_end = text_input("Fin", "", width=90)
        insert_join_sources = multiline_input("Rutas a unir (una por línea)", "", width=420, height=82)
        insert_join_separator = text_input("Separador", " ", width=120)
        insert_today_format = text_input("Formato fecha", "%d/%m/%Y", width=180)

        def insert_mapping_pair(e=None):
            key = (insert_key.value or "").strip()
            value = (insert_value.value or "").strip()

            if not key:
                fail("Indica la key destino del bloque")
                page.update()
                return

            if not value:
                fail("Indica la ruta origen del snapshot")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = value
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_value.value = ""
            state["message"] = None
            page.update()

        def insert_static_pair(e=None):
            key = (insert_key.value or "").strip()
            value = (insert_static_value.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if value == "":
                fail("Indica el valor estático")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__static__:{value}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_static_value.value = ""
            state["message"] = None
            page.update()

        def insert_equals_pair(e=None):
            key = (insert_key.value or "").strip()
            source = (insert_equals_source.value or "").strip()
            expected = (insert_equals_expected.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not source:
                fail("Indica la ruta origen que quieres comparar")
                page.update()
                return

            if expected == "":
                fail("Indica el valor esperado")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__equals__:{source}:{expected}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_equals_source.value = ""
            insert_equals_expected.value = ""
            state["message"] = None
            page.update()

        def insert_slice_pair(e=None):
            key = (insert_key.value or "").strip()
            source = (insert_slice_source.value or "").strip()
            start = (insert_slice_start.value or "").strip()
            end = (insert_slice_end.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not source:
                fail("Indica la ruta origen que quieres cortar")
                page.update()
                return

            if start == "" and end == "":
                fail("Indica al menos inicio o fin para el corte")
                page.update()
                return

            for label, raw in (("inicio", start), ("fin", end)):
                if raw and not raw.lstrip("-").isdigit():
                    fail(f"El valor de {label} debe ser numérico")
                    page.update()
                    return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__slice__:{source}:{start}:{end}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_slice_source.value = ""
            insert_slice_start.value = ""
            insert_slice_end.value = ""
            state["message"] = None
            page.update()

        def insert_join_pair(e=None):
            key = (insert_key.value or "").strip()
            raw_sources = (insert_join_sources.value or "").replace(",", "\n")
            sources = [item.strip() for item in raw_sources.splitlines() if item.strip()]
            separator = insert_join_separator.value
            if separator is None or separator == "":
                separator = " "

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            if not sources:
                fail("Indica al menos una ruta para unir")
                page.update()
                return

            if ":" in separator:
                fail("El separador de join no puede contener ':'")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__join__:{separator}:{':'.join(sources)}"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_join_sources.value = ""
            insert_join_separator.value = " "
            state["message"] = None
            page.update()

        def insert_today_pair(e=None):
            key = (insert_key.value or "").strip()
            fmt = (insert_today_format.value or "").strip()

            if not key:
                fail("Indica la key destino")
                page.update()
                return

            try:
                current = json.loads(mapper_json.value or "{}")
                if not isinstance(current, dict):
                    raise ValueError("Mapper JSON debe ser un objeto JSON")
            except Exception:
                current = {}

            current[key] = f"__today__:{fmt}" if fmt else "__today__"
            mapper_json.value = json.dumps(current, ensure_ascii=False, indent=2)
            insert_key.value = ""
            insert_today_format.value = "%d/%m/%Y"
            state["message"] = None
            page.update()

        mapping_insert_card = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=12,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Text("Insertar regla del bloque", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text("Añade pares al diccionario del bloque: key destino → ruta origen del snapshot.", size=12, color=Q_MUTED),
                    ft.Row(
                        controls=[
                            insert_key,
                            insert_value,
                            primary_button("Insertar ruta", insert_mapping_pair),
                            secondary_button("Ver campos snapshot", lambda e: open_snapshot_fields_dialog()),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_static_value,
                            primary_button("Insertar estático", insert_static_pair),
                            ft.Text("Se guardará como __static__:valor", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_equals_source,
                            insert_equals_expected,
                            primary_button("Insertar equals", insert_equals_pair),
                            ft.Text("Se guardará como __equals__:ruta:valor", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_slice_source,
                            insert_slice_start,
                            insert_slice_end,
                            primary_button("Insertar slice", insert_slice_pair),
                            ft.Text("Se guardará como __slice__:ruta:inicio:fin", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_join_sources,
                            insert_join_separator,
                            primary_button("Insertar join", insert_join_pair),
                            ft.Text("Se guardará como __join__:separador:ruta1:ruta2", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            insert_today_format,
                            primary_button("Insertar hoy", insert_today_pair),
                            ft.Text("Se guardará como __today__:formato", size=12, color=Q_MUTED),
                        ],
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=8,
            ),
        )

        def save_block():
            data = {
                "codigo": codigo.value,
                "nombre": nombre.value,
                "descripcion": descripcion.value,
                "mapper_json": mapper_json.value,
                "required_fields_json": required_fields_json.value,
                "version": int(version.value or 1),
                "activo": _bool_to_int(activo.value),
            }

            if state.get("editing_mapper_block_id"):
                mapper_admin_service.update_mapper_block(state["editing_mapper_block_id"], data)
            else:
                mapper_admin_service.create_mapper_block(data)

            state["editing_mapper_block_id"] = None

        def start_edit_block(block_id):
            state["editing_mapper_block_id"] = block_id
            state["message"] = None
            refresh()

        def delete_block(block_id):
            mapper_admin_service.delete_mapper_block(block_id)
            state["editing_mapper_block_id"] = None

        form = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.VIEW_MODULE, size=18, color=Q_PRIMARY),
                                bgcolor="#EAF3FF",
                                border_radius=18,
                                width=36,
                                height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Editar bloque seleccionado" if state.get("editing_mapper_block_id") else "Alta de bloque",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        "Bloques reutilizables para construir mappers compuestos: cliente, domicilio, representante, empleador, contrato, arraigo...",
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([codigo, nombre, version, activo], wrap=True, spacing=10),
                    descripcion,
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Mapper del bloque", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Formato: campo_destino → ruta_origen_snapshot. Este bloque podrá reutilizarse después en varios mappers.", size=12, color=Q_MUTED),
                                mapping_insert_card,
                                mapper_json,
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Validación del bloque", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text("Lista JSON de campos destino obligatorios aportados por este bloque.", size=12, color=Q_MUTED),
                                required_fields_json,
                            ],
                            spacing=8,
                        ),
                    ),
                    ft.Row(
                        [
                            primary_button("Guardar bloque", lambda e: run_save(save_block, "Bloque mapper guardado")),
                            secondary_button("Ver campos snapshot", lambda e: open_snapshot_fields_dialog()),
                            secondary_button("Cancelar", lambda e: cancel_edit()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            ),
        )

        rows = []
        for b in blocks:
            active_color = "#027A48" if int(b.get("activo") or 0) else "#B42318"
            rows.append(
                [
                    _mapper_actions_menu(
                        on_edit=lambda e, bid=b["id"]: start_edit_block(bid),
                        on_delete=lambda e, bid=b["id"]: run_save(lambda: delete_block(bid), "Bloque eliminado"),
                    ),
                    b.get("codigo") or "-",
                    b.get("nombre") or "-",
                    b.get("version") or 1,
                    ft.Text("Sí" if b.get("activo") else "No", color=active_color, weight=ft.FontWeight.W_600),
                    b.get("updated_at") or b.get("created_at") or "-",
                ]
            )

        metrics = [
            _mini_metric("Blocks", len(blocks), ft.Icons.VIEW_MODULE),
            _mini_metric("Activos", len([b for b in blocks if int(b.get("activo") or 0)]), ft.Icons.CHECK_CIRCLE),
            _mini_metric("Reutilizables", len(blocks), ft.Icons.ACCOUNT_TREE),
        ]

        return _expediente_workspace(
            "Mapper Blocks",
            "Bloques reutilizables para componer mappers Mercurio, EX, PDF y OCR sin duplicar reglas.",
            ft.Column(
                controls=[
                    form,
                    _table(["Acciones", "Código", "Nombre", "Versión", "Activo", "Actualizado"], rows, height=340),
                ],
                spacing=14,
            ),
            metrics=metrics,
        )


    def build_tablas():
        """
        Configuración de columnas basada en tablas reales de SQLite.

        Objetivo:
        - No escribir campos manualmente.
        - Leer tablas y columnas de la base de datos.
        - Permitir configurar clientes ahora y expedientes/cobros/futuras tablas después.
        """
        db_tables = config_service.get_database_tables(include_config=False)

        if not db_tables:
            return config_section_card(
                "Tablas CRM",
                "Configuración de columnas visibles por tabla.",
                empty_state("No hay tablas operativas detectadas en la base de datos"),
            )

        selected_table = state.get("selected_table") or ("clientes" if "clientes" in db_tables else db_tables[0])
        if selected_table not in db_tables:
            selected_table = db_tables[0]
        state["selected_table"] = selected_table

        tabla_dropdown = select_input(
            "Tabla",
            db_tables,
            value=selected_table,
            width=260,
        )

        info_container = ft.Container()

        def change_table(e=None):
            state["selected_table"] = tabla_dropdown.value
            state["editing_id"] = None
            refresh()

        tabla_dropdown.on_change = change_table

        def sync_table(e=None):
            def do_sync():
                config_service.sync_columnas_tabla_from_db(state["selected_table"])
            run_save(do_sync, f"Columnas sincronizadas desde {state['selected_table']}")

        db_columns = config_service.get_database_columns(selected_table)
        configured_columns = config_service.get_columnas_tabla(selected_table)

        configured_by_field = {c["campo"]: c for c in configured_columns}

        missing_columns = [
            c["name"]
            for c in db_columns
            if c["name"] not in configured_by_field
        ]

        info_container.content = ft.Column(
            controls=[
                ft.Text(
                    f"Tabla seleccionada: {selected_table}",
                    size=13,
                    color=Q_PRIMARY_DARK,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f"Campos reales en base de datos: {len(db_columns)} · Campos configurados: {len(configured_columns)}",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Text(
                    "Primero sincroniza la tabla. Después podrás mostrar/ocultar columnas, ordenar y ajustar ancho.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Text(
                    f"Campos pendientes de sincronizar: {', '.join(missing_columns)}" if missing_columns else "Todos los campos reales están sincronizados.",
                    size=12,
                    color="#B54708" if missing_columns else "#027A48",
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=4,
        )

        rows = []
        for r in configured_columns:
            visible = select_input(
                "Visible",
                _bool_options(),
                value="Sí" if r["visible"] else "No",
                width=105,
            )
            orden = text_input("Orden", str(r["orden"]), width=90)
            ancho = text_input("Ancho", str(r["ancho"]), width=90)

            def save_column(e=None, record=r, visible_field=visible, orden_field=orden, ancho_field=ancho):
                def do_update():
                    config_service.update_columna_tabla(
                        record["id"],
                        {
                            "visible": _bool_to_int(visible_field.value),
                            "orden": int(orden_field.value or 0),
                            "ancho": int(ancho_field.value or 160),
                        },
                    )
                run_save(do_update, "Configuración de columna actualizada")

            db_meta = next((c for c in db_columns if c["name"] == r["campo"]), {})
            rows.append(
                [
                    r["campo"],
                    db_meta.get("type") or "-",
                    visible,
                    orden,
                    ancho,
                    primary_button("Guardar", save_column),
                ]
            )

        content_controls = [
            ft.Row(
                controls=[
                    tabla_dropdown,
                    primary_button("Sincronizar columnas", sync_table),
                ],
                spacing=10,
                wrap=True,
            ),
            info_container,
        ]

        if configured_columns:
            content_controls.append(
                _table(
                    ["Campo BD", "Tipo", "Visible", "Orden", "Ancho", "Acción"],
                    rows,
                    height=300,
                )
            )
        else:
            content_controls.append(
                empty_state("Pulsa 'Sincronizar columnas' para cargar los campos reales de esta tabla")
            )

        return config_section_card(
            "Tablas CRM",
            "Configuración dinámica de columnas basada en la base de datos real.",
            ft.Column(
                content_controls,
                spacing=16,
            ),
        )

    refresh()
    return content_area

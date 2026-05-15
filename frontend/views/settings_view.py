import flet as ft

from backend.services import config_service
from backend.services import expedient_dynamic_form_service as dynamic_form_service
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
        "message": None,
    }

    content_area = ft.Container(expand=True)

    try:
        config_service.initialize_config_schema()
        dynamic_form_service.initialize_dynamic_forms_schema()
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

        tab = state.get("expediente_tab") or "tipos"
        if tab == "subtipos":
            body = build_subtipos_tab()
        elif tab == "formularios":
            body = build_formularios_expediente()
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

    def build_documentos():
        editing = config_service.get_record("config_documentos_requeridos", state["editing_id"]) if state["editing_id"] else {}
        tipos_opts = tipo_options()
        subtipos = config_service.get_subtipos_expediente(active_only=True)
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

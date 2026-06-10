from pathlib import Path

PATH = Path('frontend/views/expedients_view.py')

if not PATH.exists():
    raise SystemExit(f'No existe {PATH}. Ejecuta este script desde la raíz del repositorio.')

text = PATH.read_text(encoding='utf-8')
start = text.find('    def _build_ex02_specific_content(')
end = text.find('\n    def build_specific_data_content(expediente_id):', start)

if start == -1 or end == -1:
    raise SystemExit('No se encontró el bloque _build_ex02_specific_content para reemplazar.')

new_function = r'''    def _build_ex02_specific_content(expediente_id, formulario, saved_values, tipo_label, subtipo_label):
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

        def register_person(prefix, details=None):
            details = details or {}
            defaults = {}
            for field in person_fields:
                defaults[field] = str(details.get(field) or "")
            defaults["nombre_completo"] = full_name_from_details(details)
            defaults["documento"] = document_from_details(details)
            defaults["via_completa"] = via_completa_from_details(details)
            for field in person_fields:
                code = f"{prefix}_{field}"
                _register_hidden_specific_control(code, _specific_field_value(saved_values, code, defaults.get(field, "")))

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
        register_person("reagrupado", cliente_details)
        # El reagrupante es el familiar/contacto residente que da derecho.
        register_person("reagrupante", {})
        register_presentador()

        # Campos visibles de solicitud EX02.
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
                    _forms_popup_menu(),
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
                    ],
                    spacing=10,
                    wrap=True,
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
                        _specific_info_row("Parentesco", _specific_field_value(saved_values, "reagrupante_parentesco", "-")),
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
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        secondary_button("Guardar datos", save_specific_data),
                        secondary_button("Generar snapshot", generate_snapshot),
                        primary_button("Generar EX02", generate_referenced_ex_form),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            icon=ft.Icons.CHECK_CIRCLE,
        )

        step_controls = [reagrupado_card, reagrupante_card, representante_card, solicitud_card, review_card]

        nav = ft.Row(
            controls=[
                secondary_button("Anterior", lambda e: _save_specific_and_go_step(current_step - 1)) if current_step > 0 else ft.Container(),
                primary_button("Siguiente", lambda e: _save_specific_and_go_step(current_step + 1)) if current_step < len(steps) - 1 else ft.Container(),
            ],
            spacing=10,
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

'''

updated = text[:start] + new_function + text[end:]
PATH.write_text(updated, encoding='utf-8')
print('OK: contrato EX02 corregido: reagrupado=cliente, reagrupante=contacto/familiar.')

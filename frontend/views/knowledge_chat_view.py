"""WO-KNOW-CHAT-01: vista «Chat Knowledge» (Flet, sección «Conocimiento»).

Consulta READ-ONLY sobre BOE / BOE consolidado con contexto opcional de
un expediente. Dos capas en un módulo, igual que la vista de Control
operativo Fabric:

* Capa de MODELO pura (``build_turn_model``) sin Flet: copia campos de
  ``KnowledgeChatResponse`` a un dict plano con las cuatro secciones
  separadas (FUNDAMENTO BOE, HECHOS DEL CRM, interpretación, evidencia
  insuficiente). No decide nada jurídico ni reformula textos.
* RENDERER Flet (``knowledge_chat_view``) con import perezoso de Flet y
  componentes existentes (``app_alert``, ``app_button``,
  ``app_empty_state``).

Decisiones:

* La vista no hace SQL ni HTTP: solo llama al servicio inyectado
  (``ask_from_input``, ``resolve_expedient``, ``corpus_status``) en
  segundo plano con ``page.run_thread`` para no bloquear el event loop.
* Historial temporal solo en memoria de la vista (máx. MAX_HISTORY
  turnos); «Nueva consulta» lo vacía. Nada se persiste.
* El contexto CRM exige: modo «BOE + expediente», expediente
  seleccionado (número exacto o handoff explícito desde navegación) y
  casilla de confirmación. Sin eso el servicio responde DENIED.
* Sin controles «Guardar criterio», «Enviar a cliente», «Presentar» ni
  «Crear escrito»: esta vista es solo consulta.
"""

from __future__ import annotations

VIEW_TITLE = "Chat Knowledge"

MODE_BOE = "BOE"
MODE_BOE_WITH_EXPEDIENT = "BOE_WITH_EXPEDIENT"

MODE_LABELS = {
    MODE_BOE: "BOE",
    MODE_BOE_WITH_EXPEDIENT: "BOE + expediente seleccionado",
}

MAX_HISTORY = 20

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#66788A"
Q_BORDER = "#E4E7EC"
Q_BOE_BG = "#EAF3FF"
Q_CRM_BG = "#FFF7E6"
Q_INFERENCE_BG = "#F2F4F7"
Q_MISSING_BG = "#FEF3F2"

KIND_TITLES = {
    "DOCUMENTARY": "Resultado documental (extractivo)",
    "INSUFFICIENT_EVIDENCE": "Evidencia insuficiente",
    "CORPUS_UNAVAILABLE": "Corpus Knowledge no disponible",
    "REJECTED": "Consulta rechazada",
}

CONTEXT_STATUS_LABELS = {
    "NOT_REQUESTED": "No solicitado (modo BOE)",
    "GRANTED": "Concedido",
    "DENIED": "DENEGADO",
    "NOT_FOUND": "No encontrado",
    "UNAVAILABLE": "No disponible",
}


def _value(obj, name, default=""):
    value = getattr(obj, name, default)
    value = getattr(value, "value", value)
    return default if value is None else value


def _date_text(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else ""


def _citation_model(citation) -> dict:
    effective = _date_text(_value(citation, "version_effective_from", None))
    published = _date_text(_value(citation, "version_published_on", None))
    version_bits = []

    if effective:
        version_bits.append(f"versión aplicable desde {effective}")

    if published:
        version_bits.append(f"publicada {published}")

    end_date = _date_text(_value(citation, "validity_end_date", None))
    validity = _value(citation, "validity_label")

    if end_date:
        validity = f"{validity} (fecha {end_date})"

    repealed_by = _value(citation, "repealed_by_external_id")

    if repealed_by:
        validity = f"{validity} · por {repealed_by}"

    return {
        "title": _value(citation, "document_title")
        or _value(citation, "external_id"),
        "external_id": _value(citation, "external_id"),
        "location": _value(citation, "block_title")
        or _value(citation, "block_id")
        or "Norma completa",
        "source_label": _value(citation, "source_label"),
        "official": bool(_value(citation, "is_official_primary", False)),
        "url": _value(citation, "url"),
        "official_url": _value(citation, "official_publication_url"),
        "official_note": _value(citation, "official_publication_note"),
        "validity_status": _value(citation, "validity_status"),
        "validity": validity,
        "version": " · ".join(version_bits) or "Fecha de versión no disponible",
        "match": _value(citation, "match_label"),
        "excerpt": _value(citation, "excerpt"),
    }


def build_turn_model(response) -> dict:
    """Dict plano de un turno; nunca reformula ni añade contenido."""

    crm = getattr(response, "crm_context", None)
    kind = _value(response, "kind")
    temporal = _value(response, "temporal_basis")
    as_of = _date_text(_value(response, "as_of", None))

    return {
        "question": _value(response, "question"),
        "kind": kind,
        "title": KIND_TITLES.get(kind, kind),
        "mode": MODE_LABELS.get(_value(response, "mode"), ""),
        "answer_label": _value(response, "answer_label"),
        "message": _value(response, "message"),
        "temporal": (
            f"Fecha de referencia {as_of}"
            if temporal == "AS_OF" and as_of
            else (
                "Última versión conocida en el corpus"
                if temporal == "LATEST_KNOWN"
                else ""
            )
        ),
        "search_terms": list(_value(response, "search_terms", ()) or ()),
        "fundamento": {
            "label": "FUNDAMENTO BOE",
            "text": _value(response, "documentary_text"),
            "citations": [
                _citation_model(citation)
                for citation in (_value(response, "citations", ()) or ())
            ],
            "truncated": bool(_value(response, "truncated", False)),
            "evidence_level": _value(response, "evidence_level"),
            "evidence_note": _value(response, "evidence_note"),
        },
        "crm": {
            "label": "HECHOS DEL CRM",
            "status": _value(crm, "status", "NOT_REQUESTED"),
            "status_label": CONTEXT_STATUS_LABELS.get(
                _value(crm, "status", "NOT_REQUESTED"),
                _value(crm, "status", ""),
            ),
            "notice": _value(crm, "notice"),
            "reason": _value(crm, "reason"),
            "basis": _value(crm, "authorization_basis"),
            "ref": _value(crm, "expediente_ref"),
            "facts": [
                (str(label), str(value))
                for label, value in (_value(crm, "facts", ()) or ())
            ],
            "events": [str(event) for event in (_value(crm, "events", ()) or ())],
            "events_truncated": bool(_value(crm, "events_truncated", False)),
        },
        "interpretation": {
            "label": "INTERPRETACIÓN / INFERENCIA",
            "text": _value(response, "interpretation_text"),
            "note": _value(response, "interpretation_note"),
            "synthesis_status": _value(response, "synthesis_status"),
            "synthesis_notice": _value(response, "synthesis_notice"),
        },
        "insufficient": list(
            _value(response, "insufficient_evidence", ()) or ()
        ),
        "limitations": list(_value(response, "limitations", ()) or ()),
        "notices": list(_value(response, "notices", ()) or ()),
    }


def corpus_status_text(status) -> str:
    if status is None:
        return "Comprobando corpus Knowledge…"

    if not _value(status, "available", False):
        return (
            "Corpus Knowledge no disponible: "
            + (_value(status, "reason") or "sin detalle")
        )

    counts = _value(status, "documents_by_source", ()) or ()
    parts = [f"{source}: {count} norma(s)" for source, count in counts]
    reason = _value(status, "reason")

    return " · ".join(
        part for part in ["Corpus Knowledge", *parts, reason] if part
    )


def _run_in_background(page, work) -> None:
    runner = getattr(page, "run_thread", None)

    if callable(runner):
        runner(work)
        return

    work()


def render_turn(ft, model: dict, components: dict, open_url) -> object:
    """Controles Flet de un turno con las cuatro secciones separadas."""

    def text(value, size=13, color=None, bold=False, selectable=True):
        return ft.Text(
            value,
            size=size,
            color=color,
            weight=ft.FontWeight.BOLD if bold else None,
            selectable=selectable,
        )

    def section(title, controls, bgcolor):
        return ft.Container(
            content=ft.Column(
                controls=[text(title, 13, Q_PRIMARY_DARK, True), *controls],
                spacing=6,
            ),
            padding=12,
            border_radius=10,
            bgcolor=bgcolor,
            border=ft.border.all(1, Q_BORDER),
        )

    def link(label, url):
        return ft.TextButton(
            content=ft.Text(label, color=Q_PRIMARY, size=12),
            on_click=lambda e, target=url: open_url(target),
            tooltip=url,
        )

    controls = [
        text(f"Pregunta: {model['question']}", 14, Q_PRIMARY_DARK, True),
        text(
            " · ".join(
                part
                for part in (model["title"], model["mode"], model["temporal"])
                if part
            ),
            12,
            Q_MUTED,
        ),
    ]

    if model["kind"] in ("REJECTED", "CORPUS_UNAVAILABLE"):
        controls.append(components["error_alert"](model["message"]))
    elif model["kind"] == "INSUFFICIENT_EVIDENCE":
        controls.append(
            components["warning_alert"](
                "Evidencia insuficiente: el corpus no contiene respaldo "
                "para esta consulta. No se responde desde memoria del "
                "modelo."
            )
        )

    if model["answer_label"] and model["kind"] == "DOCUMENTARY":
        controls.append(text(model["answer_label"], 12, Q_PRIMARY, True))

    if model["search_terms"]:
        controls.append(
            text(
                "Búsqueda adaptada: " + ", ".join(model["search_terms"]),
                11,
                Q_MUTED,
            )
        )

    # (i) FUNDAMENTO BOE
    fundamento = model["fundamento"]
    boe_controls = []

    for index, citation in enumerate(fundamento["citations"], start=1):
        boe_controls.append(
            text(
                f"[{index}] {citation['title']} ({citation['external_id']}) "
                f"· {citation['location']}",
                13,
                None,
                True,
            )
        )
        boe_controls.append(
            text(
                f"{citation['source_label']} · {citation['validity']} · "
                f"{citation['version']} · coincidencia: {citation['match']}",
                11,
                Q_MUTED,
            )
        )

        if citation["excerpt"]:
            boe_controls.append(text(f"«{citation['excerpt']}»", 12))

        links = []

        if citation["url"]:
            links.append(
                link(
                    "Abrir fuente "
                    + ("oficial" if citation["official"] else "consolidada"),
                    citation["url"],
                )
            )

        if citation["official_url"]:
            links.append(link("Abrir publicación oficial BOE", citation["official_url"]))

        if links:
            boe_controls.append(ft.Row(controls=links, wrap=True, spacing=6))
        else:
            boe_controls.append(
                text("Sin URL almacenada para esta cita.", 11, Q_MUTED)
            )

        if citation["official_note"] and not citation["official_url"]:
            boe_controls.append(text(citation["official_note"], 11, Q_MUTED))

    if fundamento["truncated"]:
        boe_controls.append(
            text("Hay más coincidencias no mostradas (límite).", 11, Q_MUTED)
        )

    if fundamento["evidence_level"]:
        boe_controls.append(
            text(
                f"Nivel evidencial: {fundamento['evidence_level']} · "
                f"{fundamento['evidence_note']}",
                11,
                Q_MUTED,
            )
        )

    controls.append(
        section(
            fundamento["label"],
            boe_controls
            or [text("Sin fundamento BOE recuperado.", 12, Q_MUTED)],
            Q_BOE_BG,
        )
    )

    # (ii) HECHOS DEL CRM
    crm = model["crm"]
    crm_controls = [
        text(f"Contexto: {crm['status_label']}", 12, None, True),
    ]

    if crm["reason"]:
        crm_controls.append(text(crm["reason"], 12, Q_MUTED))

    if crm["status"] == "GRANTED":
        crm_controls.append(text(crm["notice"], 11, Q_MUTED))

        if crm["basis"]:
            crm_controls.append(
                text(f"Base de autorización: {crm['basis']}", 11, Q_MUTED)
            )

        crm_controls.extend(
            text(f"{label}: {value}", 12) for label, value in crm["facts"]
        )

        if crm["events"]:
            crm_controls.append(text("Actuaciones recientes:", 12, None, True))
            crm_controls.extend(text(f"• {event}", 12) for event in crm["events"])

        if crm["events_truncated"]:
            crm_controls.append(text("Hay actuaciones anteriores no mostradas.", 11, Q_MUTED))

    controls.append(section(crm["label"], crm_controls, Q_CRM_BG))

    # (iii) INTERPRETACIÓN / INFERENCIA
    interpretation = model["interpretation"]
    controls.append(
        section(
            interpretation["label"],
            [
                text(
                    interpretation["text"]
                    or "No se genera interpretación en este modo.",
                    12,
                ),
                text(interpretation["note"], 11, Q_MUTED),
                text(interpretation["synthesis_notice"], 11, Q_MUTED),
            ],
            Q_INFERENCE_BG,
        )
    )

    # (iv) EVIDENCIA INSUFICIENTE
    if model["insufficient"]:
        controls.append(
            section(
                "EVIDENCIA INSUFICIENTE / AUSENTE",
                [text(f"• {item}", 12) for item in model["insufficient"]],
                Q_MISSING_BG,
            )
        )

    for notice in model["notices"] + model["limitations"]:
        controls.append(text(f"ⓘ {notice}", 11, Q_MUTED))

    return ft.Container(
        content=ft.Column(controls=controls, spacing=8),
        padding=14,
        border_radius=12,
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
    )


def knowledge_chat_view(
    page,
    service=None,
    current_user=None,
    initial_expediente_id=None,
):
    """Vista Flet del Chat Knowledge. ``service`` es KnowledgeChatService."""

    import flet as ft
    from frontend.components.app_alert import error_alert, warning_alert
    from frontend.components.app_button import primary_button, secondary_button
    from frontend.components.app_empty_state import empty_state

    components = {
        "error_alert": error_alert,
        "warning_alert": warning_alert,
    }

    state = {
        "turns": [],
        "pending": None,
        "sequence": 0,
        "expediente_id": None,
        "expediente_ref": "",
    }

    if (
        isinstance(initial_expediente_id, int)
        and not isinstance(initial_expediente_id, bool)
        and initial_expediente_id > 0
    ):
        state["expediente_id"] = initial_expediente_id
        state["expediente_ref"] = f"seleccionado desde navegación (id {initial_expediente_id})"

    def safe_update():
        try:
            page.update()
        except Exception:  # noqa: BLE001 - la vista puede estar desmontada
            pass

    def open_url(url):
        try:
            page.run_task(page.launch_url, url)
        except Exception:  # noqa: BLE001
            pass

    corpus_text = ft.Text(corpus_status_text(None), size=12, color=Q_MUTED)

    question_field = ft.TextField(
        label="Pregunta (español)",
        value="",
        hint_text="Ej.: ¿Qué dice el artículo 2 del Real Decreto 1155/2024?",
        expand=True,
        max_length=1000,
        on_submit=lambda e: send(e),
    )

    as_of_field = ft.TextField(
        label="Fecha de referencia (opcional)",
        value="",
        hint_text="AAAA-MM-DD",
        width=220,
    )

    mode_text = ft.Text(f"Modo: {MODE_LABELS[MODE_BOE]}", size=12, weight=ft.FontWeight.BOLD)

    context_checkbox = ft.Checkbox(
        label="Usar contexto de un expediente (BOE + expediente seleccionado)",
        value=state["expediente_id"] is not None,
    )

    expediente_field = ft.TextField(
        label="Número exacto de expediente",
        value="",
        width=260,
    )

    expediente_text = ft.Text(
        (
            f"Expediente: {state['expediente_ref']}"
            if state["expediente_id"]
            else "Ningún expediente seleccionado."
        ),
        size=12,
        color=Q_MUTED,
    )

    confirm_checkbox = ft.Checkbox(
        label=(
            "Confirmo usar el contexto de este expediente (solo lectura, "
            "datos mínimos, sin datos personales)"
        ),
        value=False,
    )

    context_warning = ft.Container(visible=False)

    progress = ft.ProgressRing(width=18, height=18, visible=False)

    history = ft.Column(controls=[], spacing=12)

    def current_mode():
        return MODE_BOE_WITH_EXPEDIENT if context_checkbox.value else MODE_BOE

    def refresh_context_panel():
        enabled = current_mode() == MODE_BOE_WITH_EXPEDIENT
        mode_text.value = f"Modo: {MODE_LABELS[current_mode()]}"
        context_panel.visible = enabled

        problems = []
        authenticated = (
            isinstance(current_user, dict)
            and bool(current_user.get("id"))
            and bool(current_user.get("username"))
        )

        if not authenticated:
            problems.append("No hay sesión ERP autenticada: el contexto CRM quedará DENEGADO.")

        if service is not None and not getattr(service, "context_supported", False):
            problems.append("El contexto CRM no está habilitado en este entorno.")

        context_warning.content = (
            warning_alert(" ".join(problems)) if problems else None
        )
        context_warning.visible = enabled and bool(problems)

    def on_mode_change(e=None):
        refresh_context_panel()
        safe_update()

    context_checkbox.on_change = on_mode_change

    def select_expedient(e=None):
        numero = str(expediente_field.value or "").strip()
        state["expediente_id"] = None
        state["expediente_ref"] = ""
        confirm_checkbox.value = False
        expediente_text.value = "Buscando expediente…"
        safe_update()

        def work():
            if service is None:
                selection = None
            else:
                try:
                    selection = service.resolve_expedient(current_user, numero)
                except Exception:  # noqa: BLE001
                    selection = None

            status = _value(selection, "status", "UNAVAILABLE")

            if status == "GRANTED":
                state["expediente_id"] = _value(selection, "expediente_id", None)
                state["expediente_ref"] = _value(selection, "expediente_ref")
                expediente_text.value = f"Expediente seleccionado: {state['expediente_ref']}"
            else:
                expediente_text.value = (
                    f"{CONTEXT_STATUS_LABELS.get(status, status)}: "
                    + (_value(selection, "reason") or "no se pudo seleccionar.")
                )

            safe_update()

        _run_in_background(page, work)

    def clear_expedient(e=None):
        state["expediente_id"] = None
        state["expediente_ref"] = ""
        confirm_checkbox.value = False
        expediente_field.value = ""
        expediente_text.value = "Ningún expediente seleccionado."
        safe_update()

    context_panel = ft.Container(
        visible=False,
        padding=12,
        border_radius=10,
        bgcolor=Q_CRM_BG,
        border=ft.border.all(1, Q_BORDER),
        content=ft.Column(
            controls=[
                ft.Text(
                    "Contexto de expediente (HECHOS DEL CRM, lectura)",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Row(
                    controls=[
                        expediente_field,
                        secondary_button("Seleccionar", select_expedient),
                        secondary_button("Quitar", clear_expedient),
                    ],
                    wrap=True,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                expediente_text,
                confirm_checkbox,
                context_warning,
            ],
            spacing=8,
        ),
    )

    def render_history():
        if state["turns"]:
            history.controls = [
                render_turn(ft, model, components, open_url)
                for model in reversed(state["turns"])
            ]
        else:
            history.controls = [
                empty_state(
                    "Sin consultas en esta sesión. El historial no se guarda."
                )
            ]

    def set_busy(busy):
        progress.visible = busy
        send_button.disabled = busy

    def send(e=None):
        if state["pending"] is not None:
            return

        question = str(question_field.value or "")
        state["sequence"] += 1
        token = state["sequence"]
        state["pending"] = token
        set_busy(True)
        safe_update()

        mode = current_mode()
        as_of_text = str(as_of_field.value or "")
        expediente_id = (
            state["expediente_id"] if mode == MODE_BOE_WITH_EXPEDIENT else None
        )
        confirmed = bool(confirm_checkbox.value) and expediente_id is not None

        def work():
            response = None

            if service is not None:
                try:
                    response = service.ask_from_input(
                        question=question,
                        mode=mode,
                        as_of_text=as_of_text,
                        current_user=current_user,
                        expediente_id=expediente_id,
                        context_confirmed=confirmed,
                    )
                except Exception:  # noqa: BLE001 - nunca excepción cruda
                    response = None

            if state["pending"] != token:
                return

            model = (
                build_turn_model(response)
                if response is not None
                else {
                    **build_turn_model(None),
                    "question": question,
                    "kind": "CORPUS_UNAVAILABLE",
                    "title": KIND_TITLES["CORPUS_UNAVAILABLE"],
                    "message": "El servicio Knowledge no está disponible.",
                }
            )

            state["turns"].append(model)
            del state["turns"][:-MAX_HISTORY]

            if model["kind"] != "REJECTED":
                question_field.value = ""

            state["pending"] = None
            set_busy(False)
            render_history()
            safe_update()

        _run_in_background(page, work)

    def new_conversation(e=None):
        state["turns"].clear()
        state["pending"] = None
        question_field.value = ""
        set_busy(False)
        render_history()
        safe_update()

    send_button = primary_button("Enviar", send)

    def load_corpus_status():
        try:
            status = service.corpus_status() if service is not None else None
        except Exception:  # noqa: BLE001
            status = None

        corpus_text.value = (
            corpus_status_text(status)
            if status is not None
            else "Corpus Knowledge no disponible: servicio no configurado."
        )
        safe_update()

    refresh_context_panel()
    render_history()

    header = ft.Column(
        controls=[
            ft.Text(VIEW_TITLE, size=24, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Text(
                "Consulta de solo lectura sobre BOE y BOE consolidado. "
                "Modo documental: extractos literales con fuente; no es "
                "una respuesta jurídica generada por IA ni criterio "
                "validado por abogado.",
                size=12,
                color=Q_MUTED,
            ),
            corpus_text,
        ],
        spacing=4,
    )

    composer = ft.Container(
        padding=14,
        border_radius=12,
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[mode_text, context_checkbox],
                    wrap=True,
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                context_panel,
                ft.Row(
                    controls=[question_field, as_of_field],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    controls=[
                        send_button,
                        secondary_button("Nueva consulta", new_conversation),
                        progress,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=10,
        ),
    )

    _run_in_background(page, load_corpus_status)

    return ft.Container(
        expand=True,
        padding=20,
        content=ft.Column(
            controls=[header, composer, history],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )

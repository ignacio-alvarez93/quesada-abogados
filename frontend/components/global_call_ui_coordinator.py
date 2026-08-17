import threading

import flet as ft

from frontend.components.app_dialog import (
    form_dialog,
)


class GlobalCallUICoordinator:
    """
    Popup global de llamadas.

    Consume únicamente eventos de presentación genéricos.

    No importa:
    - SQLite;
    - repositories;
    - Selenium;
    - WhatsAppConnector.
    """

    def __init__(
        self,
        *,
        page,
        on_accept=None,
        on_reject=None,
        on_save_post_call=None,
        reason_options=None,
    ):
        self.page = page

        self.on_accept = on_accept
        self.on_reject = on_reject

        self.on_save_post_call = (
            on_save_post_call
        )

        self.reason_options = tuple(
            reason_options
            or ()
        )

        self._lock = threading.Lock()

        self._event = None
        self._event_key = None
        self._dialog = None

        self._accept_button = None
        self._reject_button = None

        self._action_inflight = False

        self._dialog_open_count = 0
        self._duplicate_count = 0

        # CALL-UX-5 · clasificación humana posterior.
        self._post_call_event = None
        self._post_call_event_key = None
        self._post_call_dialog = None

        self._post_call_reason = None
        self._post_call_reason_detail = None
        self._post_call_notes = None
        self._post_call_error = None

        self._post_call_save_button = None
        self._post_call_skip_button = None

        self._post_call_save_inflight = False

        self._post_call_dialog_open_count = 0
        self._post_call_duplicate_count = 0

        # Una vez guardada u omitida una llamada, un evento
        # terminal repetido no debe volver a abrir el formulario.
        self._post_call_handled_keys = set()


    def debug_state(
        self,
    ):
        with self._lock:
            return {
                "event_key":
                    self._event_key,
                "dialog_open":
                    bool(
                        self._dialog is not None
                        and getattr(
                            self._dialog,
                            "open",
                            False,
                        )
                    ),
                "dialog_open_count":
                    self._dialog_open_count,
                "duplicate_count":
                    self._duplicate_count,
                "action_inflight":
                    self._action_inflight,
                "post_call_event_key":
                    self._post_call_event_key,
                "post_call_dialog_open":
                    bool(
                        self._post_call_dialog
                        is not None
                        and getattr(
                            self._post_call_dialog,
                            "open",
                            False,
                        )
                    ),
                "post_call_dialog_open_count":
                    self._post_call_dialog_open_count,
                "post_call_duplicate_count":
                    self._post_call_duplicate_count,
                "post_call_save_inflight":
                    self._post_call_save_inflight,
            }


    @staticmethod
    def _channel_label(
        value,
    ):
        normalized = str(
            value
            or ""
        ).strip().upper()

        return {
            "WHATSAPP":
                "WhatsApp",
            "PHONE":
                "Teléfono",
        }.get(
            normalized,
            normalized
            or "Llamada",
        )


    def _build_content(
        self,
        event,
    ):
        controls = [
            ft.Text(
                str(
                    event.display_name
                    or event.phone_number
                    or "Contacto desconocido"
                ),
                size=20,
                weight=ft.FontWeight.BOLD,
                color="#003B7A",
            ),
            ft.Text(
                str(
                    event.phone_number
                    or "Teléfono no disponible"
                ),
                size=13,
                color="#64748B",
            ),
            ft.Text(
                self._channel_label(
                    event.channel
                ),
                size=12,
                color="#0057B8",
                weight=ft.FontWeight.W_600,
            ),
        ]

        if event.client_id is not None:
            controls.append(
                ft.Text(
                    "Cliente CRM vinculado",
                    size=11,
                    color="#027A48",
                    weight=(
                        ft.FontWeight.W_600
                    ),
                )
            )

        return ft.Container(
            width=430,
            content=ft.Column(
                controls=controls,
                spacing=7,
                tight=True,
            ),
        )


    def _close_dialog_ui(
        self,
    ):
        with self._lock:
            dialog = self._dialog

            self._event = None
            self._event_key = None
            self._dialog = None

            self._accept_button = None
            self._reject_button = None

            self._action_inflight = False

        if dialog is None:
            return False

        try:
            dialog.open = False
        except Exception:
            pass

        try:
            self.page.update()
        except Exception:
            pass

        return True


    async def _finish_action(
        self,
        *,
        event_key,
        result,
    ):
        result = (
            dict(result)
            if isinstance(
                result,
                dict,
            )
            else {
                "ok": False,
                "clicked": False,
                "uncertain": True,
                "reason":
                    "CALL_ACTION_RESULT_INVALID",
            }
        )

        clicked = bool(
            result.get(
                "clicked"
            )
        )

        with self._lock:
            still_current = (
                self._event_key
                == event_key
            )

        if not still_current:
            return False

        # Si el side effect llegó a intentarse, nunca
        # ofrecemos un retry ciego desde el mismo popup.
        if clicked:
            self._close_dialog_ui()

            return True

        with self._lock:
            self._action_inflight = False

            accept_button = (
                self._accept_button
            )

            reject_button = (
                self._reject_button
            )

            event = self._event

        if (
            accept_button is not None
            and event is not None
        ):
            accept_button.disabled = not bool(
                event.can_accept
                and callable(
                    self.on_accept
                )
            )

        if (
            reject_button is not None
            and event is not None
        ):
            reject_button.disabled = not bool(
                event.can_reject
                and callable(
                    self.on_reject
                )
            )

        print(
            "[CALL-UI] action not executed:",
            result.get(
                "reason"
            ),
            flush=True,
        )

        try:
            self.page.update()
        except Exception:
            pass

        return False


    def _start_action(
        self,
        *,
        callback,
    ):
        if not callable(
            callback
        ):
            return False

        with self._lock:
            if (
                self._event is None
                or self._action_inflight
            ):
                return False

            self._action_inflight = True

            event = self._event
            event_key = self._event_key

            accept_button = (
                self._accept_button
            )

            reject_button = (
                self._reject_button
            )

        if accept_button is not None:
            accept_button.disabled = True

        if reject_button is not None:
            reject_button.disabled = True

        try:
            self.page.update()
        except Exception:
            pass

        def worker():
            try:
                result = callback(
                    event
                )

            except Exception as exc:
                result = {
                    "ok": False,
                    "clicked": False,
                    "uncertain": False,
                    "reason":
                        "CALL_ACTION_EXCEPTION",
                    "error_type":
                        type(exc).__name__,
                    "message":
                        str(exc),
                }

            self.page.run_task(
                self._finish_action,
                event_key=event_key,
                result=result,
            )

        self.page.run_thread(
            worker
        )

        return True


    def _on_accept_click(
        self,
        e=None,
    ):
        return self._start_action(
            callback=(
                self.on_accept
            )
        )


    def _on_reject_click(
        self,
        e=None,
    ):
        return self._start_action(
            callback=(
                self.on_reject
            )
        )


    def _build_dialog(
        self,
        event,
    ):
        self._reject_button = (
            ft.TextButton(
                "Rechazar",
                icon=ft.Icons.CALL_END,
                on_click=(
                    self._on_reject_click
                ),
                disabled=not bool(
                    event.can_reject
                    and callable(
                        self.on_reject
                    )
                ),
            )
        )

        self._accept_button = (
            ft.TextButton(
                "Atender",
                icon=ft.Icons.CALL,
                on_click=(
                    self._on_accept_click
                ),
                disabled=not bool(
                    event.can_accept
                    and callable(
                        self.on_accept
                    )
                ),
            )
        )

        return form_dialog(
            "Llamada entrante",
            self._build_content(
                event
            ),
            [
                self._reject_button,
                self._accept_button,
            ],
        )


    def _normalized_reason_options(
        self,
    ):
        normalized = []

        for option in self.reason_options:
            if isinstance(
                option,
                dict,
            ):
                code = str(
                    option.get(
                        "code"
                    )
                    or ""
                ).strip()

                label = str(
                    option.get(
                        "label"
                    )
                    or ""
                ).strip()

            elif (
                isinstance(
                    option,
                    (tuple, list),
                )
                and len(option) >= 2
            ):
                code = str(
                    option[0]
                    or ""
                ).strip()

                label = str(
                    option[1]
                    or ""
                ).strip()

            else:
                code = str(
                    getattr(
                        option,
                        "code",
                        "",
                    )
                    or ""
                ).strip()

                label = str(
                    getattr(
                        option,
                        "label",
                        "",
                    )
                    or ""
                ).strip()

            if not code or not label:
                continue

            normalized.append(
                (
                    code,
                    label,
                )
            )

        return tuple(
            normalized
        )


    def _close_post_call_dialog_ui(
        self,
        *,
        mark_handled=False,
    ):
        with self._lock:
            dialog = (
                self._post_call_dialog
            )

            event_key = (
                self._post_call_event_key
            )

            if (
                mark_handled
                and event_key
            ):
                self._post_call_handled_keys.add(
                    event_key
                )

            self._post_call_event = None
            self._post_call_event_key = None
            self._post_call_dialog = None

            self._post_call_reason = None
            self._post_call_reason_detail = None
            self._post_call_notes = None
            self._post_call_error = None

            self._post_call_save_button = None
            self._post_call_skip_button = None

            self._post_call_save_inflight = False

        if dialog is None:
            return False

        try:
            dialog.open = False
        except Exception:
            pass

        try:
            self.page.update()
        except Exception:
            pass

        return True


    def _build_post_call_content(
        self,
        event,
    ):
        options = (
            self._normalized_reason_options()
        )

        valid_codes = {
            code
            for code, _label
            in options
        }

        initial_reason = str(
            getattr(
                event,
                "reason_code",
                None,
            )
            or ""
        ).strip()

        if initial_reason not in valid_codes:
            initial_reason = None

        self._post_call_reason = (
            ft.Dropdown(
                label="Motivo *",
                value=initial_reason,
                width=460,
                dense=True,
                options=[
                    ft.DropdownOption(
                        key=code,
                        text=label,
                    )
                    for code, label
                    in options
                ],
            )
        )

        self._post_call_reason_detail = (
            ft.TextField(
                label=(
                    "Detalle del motivo "
                    "(opcional)"
                ),
                value=str(
                    getattr(
                        event,
                        "reason_detail",
                        None,
                    )
                    or ""
                ),
                width=460,
                dense=True,
                border_radius=10,
            )
        )

        self._post_call_notes = (
            ft.TextField(
                label="Notas",
                value=str(
                    getattr(
                        event,
                        "notes",
                        None,
                    )
                    or ""
                ),
                width=460,
                multiline=True,
                min_lines=3,
                max_lines=6,
                border_radius=10,
            )
        )

        self._post_call_error = ft.Text(
            "",
            size=11,
            color="#B42318",
            visible=False,
        )

        identity_controls = [
            ft.Text(
                str(
                    getattr(
                        event,
                        "display_name",
                        None,
                    )
                    or getattr(
                        event,
                        "phone_number",
                        None,
                    )
                    or "Contacto desconocido"
                ),
                size=18,
                weight=ft.FontWeight.BOLD,
                color="#003B7A",
            ),
            ft.Text(
                (
                    f"{self._channel_label(getattr(event, 'channel', None))}"
                    " · "
                    f"{getattr(event, 'phone_number', None) or 'Teléfono no disponible'}"
                ),
                size=12,
                color="#64748B",
            ),
        ]

        if (
            getattr(
                event,
                "client_id",
                None,
            )
            is not None
        ):
            identity_controls.append(
                ft.Text(
                    "Cliente CRM vinculado",
                    size=11,
                    color="#027A48",
                    weight=ft.FontWeight.W_600,
                )
            )

        return ft.Container(
            width=480,
            content=ft.Column(
                controls=[
                    *identity_controls,
                    ft.Divider(
                        height=18
                    ),
                    self._post_call_reason,
                    self._post_call_reason_detail,
                    self._post_call_notes,
                    self._post_call_error,
                ],
                spacing=10,
                tight=True,
            ),
        )


    async def _finish_post_call_save(
        self,
        *,
        event_key,
        result,
    ):
        normalized = (
            dict(result)
            if isinstance(
                result,
                dict,
            )
            else {
                "ok": False,
                "reason":
                    "POST_CALL_RESULT_INVALID",
            }
        )

        with self._lock:
            still_current = (
                self._post_call_event_key
                == event_key
            )

        if not still_current:
            return False

        if normalized.get(
            "ok"
        ) is True:
            self._close_post_call_dialog_ui(
                mark_handled=True
            )

            return True

        with self._lock:
            self._post_call_save_inflight = False

            save_button = (
                self._post_call_save_button
            )

            skip_button = (
                self._post_call_skip_button
            )

            error_control = (
                self._post_call_error
            )

        if save_button is not None:
            save_button.disabled = False

        if skip_button is not None:
            skip_button.disabled = False

        if error_control is not None:
            message = str(
                normalized.get(
                    "message"
                )
                or normalized.get(
                    "reason"
                )
                or "No se pudo guardar la llamada."
            ).strip()

            error_control.value = message
            error_control.visible = True

        try:
            self.page.update()
        except Exception:
            pass

        return False


    def _on_post_call_save_click(
        self,
        e=None,
    ):
        callback = (
            self.on_save_post_call
        )

        if not callable(
            callback
        ):
            return False

        with self._lock:
            if (
                self._post_call_event
                is None
                or self._post_call_save_inflight
            ):
                return False

            event = self._post_call_event
            event_key = (
                self._post_call_event_key
            )

            reason_control = (
                self._post_call_reason
            )

            detail_control = (
                self._post_call_reason_detail
            )

            notes_control = (
                self._post_call_notes
            )

            error_control = (
                self._post_call_error
            )

            save_button = (
                self._post_call_save_button
            )

            skip_button = (
                self._post_call_skip_button
            )

        reason_code = str(
            getattr(
                reason_control,
                "value",
                None,
            )
            or ""
        ).strip()

        if not reason_code:
            if error_control is not None:
                error_control.value = (
                    "Selecciona un motivo."
                )
                error_control.visible = True

            try:
                self.page.update()
            except Exception:
                pass

            return False

        if (
            getattr(
                event,
                "call_id",
                None,
            )
            in (
                None,
                "",
            )
        ):
            if error_control is not None:
                error_control.value = (
                    "La llamada no tiene "
                    "identidad persistida."
                )
                error_control.visible = True

            try:
                self.page.update()
            except Exception:
                pass

            return False

        reason_detail = str(
            getattr(
                detail_control,
                "value",
                "",
            )
            or ""
        ).strip()

        notes = str(
            getattr(
                notes_control,
                "value",
                "",
            )
            or ""
        ).strip()

        with self._lock:
            self._post_call_save_inflight = True

        if save_button is not None:
            save_button.disabled = True

        if skip_button is not None:
            skip_button.disabled = True

        if error_control is not None:
            error_control.value = ""
            error_control.visible = False

        try:
            self.page.update()
        except Exception:
            pass

        def worker():
            try:
                result = callback(
                    event,
                    reason_code=reason_code,
                    reason_detail=(
                        reason_detail
                        or None
                    ),
                    notes=(
                        notes
                        or None
                    ),
                )

            except Exception as exc:
                result = {
                    "ok": False,
                    "reason":
                        "POST_CALL_SAVE_EXCEPTION",
                    "message":
                        str(exc),
                    "error_type":
                        type(exc).__name__,
                }

            self.page.run_task(
                self._finish_post_call_save,
                event_key=event_key,
                result=result,
            )

        self.page.run_thread(
            worker
        )

        return True


    def _on_post_call_skip_click(
        self,
        e=None,
    ):
        with self._lock:
            if self._post_call_save_inflight:
                return False

        return (
            self._close_post_call_dialog_ui(
                mark_handled=True
            )
        )


    def _build_post_call_dialog(
        self,
        event,
    ):
        self._post_call_skip_button = (
            ft.TextButton(
                "Omitir",
                on_click=(
                    self._on_post_call_skip_click
                ),
            )
        )

        self._post_call_save_button = (
            ft.TextButton(
                "Guardar",
                icon=ft.Icons.SAVE,
                on_click=(
                    self._on_post_call_save_click
                ),
                disabled=not bool(
                    callable(
                        self.on_save_post_call
                    )
                    and getattr(
                        event,
                        "call_id",
                        None,
                    )
                    not in (
                        None,
                        "",
                    )
                ),
            )
        )

        return form_dialog(
            "Registrar llamada",
            self._build_post_call_content(
                event
            ),
            [
                self._post_call_skip_button,
                self._post_call_save_button,
            ],
        )


    def _show_post_call_dialog_ui(
        self,
        event,
    ):
        event_key = str(
            getattr(
                event,
                "event_key",
                "",
            )
            or ""
        ).strip()

        if not event_key:
            return False

        with self._lock:
            if (
                event_key
                in self._post_call_handled_keys
            ):
                return False

            duplicate = (
                self._post_call_event_key
                == event_key
                and self._post_call_dialog
                is not None
            )

            if duplicate:
                self._post_call_duplicate_count += 1

        if duplicate:
            return True

        self._close_post_call_dialog_ui(
            mark_handled=False
        )

        dialog = (
            self._build_post_call_dialog(
                event
            )
        )

        with self._lock:
            self._post_call_event = event
            self._post_call_event_key = (
                event_key
            )
            self._post_call_dialog = dialog
            self._post_call_save_inflight = False
            self._post_call_dialog_open_count += 1

        self.page.show_dialog(
            dialog
        )

        self.page.update()

        return True


    async def apply_event(
        self,
        event,
    ):
        if event is None:
            return False

        event_key = str(
            getattr(
                event,
                "event_key",
                "",
            )
            or ""
        ).strip()

        if not event_key:
            return False

        if bool(
            getattr(
                event,
                "incoming_ringing",
                False,
            )
        ):
            with self._lock:
                duplicate = (
                    self._event_key
                    == event_key
                    and self._dialog
                    is not None
                )

                if duplicate:
                    self._duplicate_count += 1
                    self._event = event

            if duplicate:
                return True

            self._close_dialog_ui()

            dialog = (
                self._build_dialog(
                    event
                )
            )

            with self._lock:
                self._event = event
                self._event_key = (
                    event_key
                )
                self._dialog = dialog
                self._dialog_open_count += 1
                self._action_inflight = False

            self.page.show_dialog(
                dialog
            )

            self.page.update()

            return True

        with self._lock:
            matches_current = (
                self._event_key
                == event_key
            )

        if matches_current:
            self._close_dialog_ui()

        if bool(
            getattr(
                event,
                "post_call_required",
                False,
            )
        ):
            return (
                self._show_post_call_dialog_ui(
                    event
                )
            )

        return matches_current


    def handle_event(
        self,
        event,
    ):
        """
        Entrada segura desde watcher/background.

        El watcher nunca muta directamente controles Flet.
        """
        self.page.run_task(
            self.apply_event,
            event,
        )

        return True

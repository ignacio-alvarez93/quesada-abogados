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
    ):
        self.page = page

        self.on_accept = on_accept
        self.on_reject = on_reject

        self._lock = threading.Lock()

        self._event = None
        self._event_key = None
        self._dialog = None

        self._accept_button = None
        self._reject_button = None

        self._action_inflight = False

        self._dialog_open_count = 0
        self._duplicate_count = 0


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

            return True

        return False


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

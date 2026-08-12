"""
Runtime persistente de WhatsApp para la aplicación.

Responsabilidades:
- mantener una única instancia de WhatsAppConnector;
- iniciar la sesión de forma perezosa;
- comprobar que WhatsApp Web está READY;
- exponer casos de uso de envío y sincronización;
- mantener vivos los servicios durante la sesión del ERP.

No contiene SQL.
No conoce Flet.
"""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_NEEDS_LOGIN,
    SESSION_STATUS_READY,
    WhatsAppConnector,
)
from backend.services.communication_service import (
    CommunicationService,
)
from backend.services.whatsapp_outbound_service import (
    WhatsAppOutboundService,
)
from backend.services.whatsapp_sync_service import (
    WhatsAppSyncService,
)


class WhatsAppRuntimeService:
    def __init__(
        self,
        *,
        profile_key="whatsapp_dev",
        headless=False,
        communication_service=None,
        connector_factory=None,
    ):
        self.profile_key = str(
            profile_key
            or "whatsapp_dev"
        ).strip()

        self.headless = bool(
            headless
        )

        self.communication_service = (
            communication_service
            or CommunicationService()
        )

        self.connector_factory = (
            connector_factory
            or WhatsAppConnector
        )

        self._connector = None
        self._outbound_service = None
        self._sync_service = None

        # SeleniumBase/CDP debe conservar afinidad
        # con un único hilo durante toda la vida
        # de la sesión WhatsApp.
        self._executor = None
        self._executor_lock = threading.Lock()
        self._worker_thread_id = None

        # Última conversación solicitada desde CRM.
        # Permite descartar navegaciones obsoletas cuando
        # varias selecciones llegan mientras el worker CDP
        # está ocupado.
        self._desired_thread_id = None
        self._desired_thread_lock = threading.Lock()

        # Última huella observada del chat activo.
        # Solo se lee/escribe dentro del worker SeleniumBase/CDP.
        self._active_chat_fingerprint = None

        # Watcher ligero del chat activo.
        #
        # Este hilo NO toca SeleniumBase/CDP directamente:
        # únicamente solicita observe_active_chat(), que
        # serializa toda operación de navegador en el worker
        # único del runtime.
        self._active_chat_watch_thread = None
        self._active_chat_watch_stop = None
        self._active_chat_watch_lock = threading.Lock()

        # Diagnóstico ligero del watcher.
        #
        # last_error conserva el último fallo observado
        # aunque una iteración posterior se recupere.
        #
        # last_sync conserva la última sincronización
        # automática completada correctamente.
        self._active_chat_watch_last_error = None
        self._active_chat_watch_last_sync = None

    def _get_executor(
        self,
    ):
        with self._executor_lock:
            if self._executor is None:
                self._executor = (
                    ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=(
                            "whatsapp-runtime"
                        ),
                    )
                )

            return self._executor

    def _execute_on_worker(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        self._worker_thread_id = (
            threading.get_ident()
        )

        return callable_(
            *args,
            **kwargs,
        )

    def _run_serialized(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        # Permite llamadas internas reentrantes sin
        # deadlock cuando ya estamos en el worker.
        if (
            self._worker_thread_id
            == threading.get_ident()
        ):
            return callable_(
                *args,
                **kwargs,
            )

        executor = (
            self._get_executor()
        )

        future = executor.submit(
            self._execute_on_worker,
            callable_,
            *args,
            **kwargs,
        )

        return future.result()

    @property
    def connector(self):
        return self._connector

    @property
    def started(self):
        return bool(
            self._connector
            and self._connector.browser
        )

    def _build_connector(
        self,
    ):
        if self._connector is None:
            self._connector = (
                self.connector_factory(
                    profile_key=(
                        self.profile_key
                    ),
                    headless=(
                        self.headless
                    ),
                )
            )

        return self._connector

    def _start_impl(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if not connector.browser:
            connector.start()

        return connector

    def start(
        self,
    ):
        return self._run_serialized(
            self._start_impl
        )

    def _get_status_impl(
        self,
    ):
        if not self.started:
            return "NOT_STARTED"

        return (
            self._connector
            .detect_session_status()
        )

    def get_status(
        self,
    ):
        return self._run_serialized(
            self._get_status_impl
        )

    def _ensure_ready_impl(
        self,
        *,
        wait_timeout=60,
        poll_interval=1,
    ):
        connector = self._start_impl()

        deadline = (
            time.time()
            + max(
                1,
                int(wait_timeout),
            )
        )

        last_status = None

        while time.time() < deadline:
            last_status = (
                connector
                .detect_session_status()
            )

            if (
                last_status
                == SESSION_STATUS_READY
            ):
                connector.dismiss_known_overlays()

                return connector

            if (
                last_status
                == SESSION_STATUS_NEEDS_LOGIN
            ):
                raise RuntimeError(
                    "WhatsApp Web requiere iniciar sesión"
                )

            time.sleep(
                max(
                    0.1,
                    float(
                        poll_interval
                    ),
                )
            )

        raise RuntimeError(
            "WhatsApp Web no alcanzó estado READY "
            f"(último estado: {last_status})"
        )

    def ensure_ready(
        self,
        *,
        wait_timeout=60,
        poll_interval=1,
    ):
        return self._run_serialized(
            self._ensure_ready_impl,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )

    def _get_outbound_service(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if self._outbound_service is None:
            self._outbound_service = (
                WhatsAppOutboundService(
                    connector=connector,
                    communication_service=(
                        self.communication_service
                    ),
                )
            )

        return self._outbound_service

    def _get_sync_service(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if self._sync_service is None:
            self._sync_service = (
                WhatsAppSyncService(
                    connector=connector,
                    communication_service=(
                        self.communication_service
                    ),
                )
            )

        return self._sync_service

    def _open_thread_impl(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Abre un chat sin inspeccionar el perfil del contacto."""
        connector = self._ensure_ready_impl(
            wait_timeout=wait_timeout,
        )

        thread = (
            self.communication_service
            .get_thread(
                thread_id
            )
        )

        if thread is None:
            raise ValueError(
                "Conversación no encontrada"
            )

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            raise ValueError(
                "La conversación no tiene "
                "teléfono WhatsApp verificable"
            )

        routing = (
            connector
            .open_chat_by_phone(
                phone,
                expected_display_name=(
                    thread.external_display_name
                ),
                verify_identity=False,
                timeout=routing_timeout,
            )
        )

        if not routing.get(
            "opened"
        ):
            reason = (
                routing.get(
                    "reason"
                )
                or "CHAT_OPEN_FAILED"
            )

            raise RuntimeError(
                "No se pudo abrir la "
                "conversación WhatsApp "
                f"({reason})"
            )

        return {
            "thread": thread,
            "routing": routing,
        }

    def _verify_and_open_thread_impl(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        connector = self._ensure_ready_impl(
            wait_timeout=wait_timeout,
        )

        thread = (
            self.communication_service
            .get_thread(
                thread_id
            )
        )

        if thread is None:
            raise ValueError(
                "Conversación no encontrada"
            )

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            raise ValueError(
                "La conversación no tiene "
                "teléfono WhatsApp verificable"
            )

        routing = (
            connector
            .open_chat_by_phone(
                phone,
                expected_display_name=(
                    thread.external_display_name
                ),
                timeout=routing_timeout,
            )
        )

        if not routing.get(
            "verified"
        ):
            reason = (
                routing.get(
                    "reason"
                )
                or
                "IDENTITY_UNVERIFIABLE"
            )

            raise RuntimeError(
                "No se pudo verificar el "
                "destinatario WhatsApp "
                f"({reason})"
            )

        return {
            "thread": thread,
            "routing": routing,
        }

    def _verify_and_open_latest_thread_impl(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        requested_thread_id = int(
            thread_id
        )

        with self._desired_thread_lock:
            desired_thread_id = (
                self._desired_thread_id
            )

        if (
            desired_thread_id
            != requested_thread_id
        ):
            return {
                "skipped": True,
                "reason": "STALE_SELECTION",
                "requested_thread_id":
                    requested_thread_id,
                "desired_thread_id":
                    desired_thread_id,
            }

        return self._open_thread_impl(
            requested_thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )

    def verify_and_open_thread(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        requested_thread_id = int(
            thread_id
        )

        with self._desired_thread_lock:
            self._desired_thread_id = (
                requested_thread_id
            )

        return self._run_serialized(
            self._verify_and_open_latest_thread_impl,
            requested_thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )

    def _send_text_message_impl(
        self,
        *,
        wait_timeout=60,
        routing_timeout=15,
        **kwargs,
    ):
        thread_id = kwargs.get(
            "thread_id"
        )

        if thread_id in (
            None,
            "",
        ):
            raise ValueError(
                "thread_id es obligatorio"
            )

        routing_result = (
            self._verify_and_open_thread_impl(
                thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=(
                    routing_timeout
                ),
            )
        )

        return (
            self._get_outbound_service()
            .send_text_message(
                **kwargs
            )
        )

    def send_text_message(
        self,
        *,
        wait_timeout=60,
        routing_timeout=15,
        **kwargs,
    ):
        return self._run_serialized(
            self._send_text_message_impl,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
            **kwargs,
        )

    def _observe_active_chat_impl(
        self,
        *,
        wait_timeout=60,
    ):
        connector = self._ensure_ready_impl(
            wait_timeout=wait_timeout,
        )

        current = (
            connector
            .get_active_chat_fingerprint()
        )

        previous = (
            self._active_chat_fingerprint
        )

        if previous is None:
            change_type = "INITIAL"
            changed = True

        elif (
            previous.chat_open
            != current.chat_open
        ):
            change_type = "CHAT_CHANGED"
            changed = True

        elif not current.chat_open:
            change_type = "UNCHANGED"
            changed = False

        elif (
            previous.active_identity
            != current.active_identity
        ):
            change_type = "CHAT_CHANGED"
            changed = True

        elif (
            previous.last_provider_message_id
            != current.last_provider_message_id
        ):
            change_type = "MESSAGE_CHANGED"
            changed = True

        elif (
            previous.visible_message_count
            != current.visible_message_count
        ):
            # Señal secundaria. WhatsApp puede virtualizar
            # mensajes sin cambiar el último provider id.
            change_type = "MESSAGE_WINDOW_CHANGED"
            changed = True

        else:
            change_type = "UNCHANGED"
            changed = False

        self._active_chat_fingerprint = (
            current
        )

        return {
            "changed": changed,
            "change_type": change_type,
            "previous": previous,
            "current": current,
        }

    def observe_active_chat(
        self,
        *,
        wait_timeout=60,
    ):
        return self._run_serialized(
            self._observe_active_chat_impl,
            wait_timeout=wait_timeout,
        )


    def _observe_and_sync_active_chat_impl(
        self,
        *,
        wait_timeout=60,
        sync_limit=200,
    ):
        result = (
            self._observe_active_chat_impl(
                wait_timeout=wait_timeout,
            )
        )

        result["resolution"] = None
        result["sync"] = None

        if (
            result.get(
                "change_type"
            )
            != "MESSAGE_CHANGED"
        ):
            return result

        current = result.get(
            "current"
        )

        if (
            current is None
            or not current.chat_open
            or not str(
                current.active_identity
                or ""
            ).strip()
        ):
            return result

        try:
            resolution = (
                self.communication_service
                .resolve_whatsapp_thread_by_identity(
                    current.active_identity
                )
            )

        except Exception as exc:
            result["resolution"] = {
                "matched": False,
                "ambiguous": False,
                "match_basis": None,
                "thread": None,
                "matches": [],
                "identity":
                    current.active_identity,
                "error": True,
                "error_type":
                    type(
                        exc
                    ).__name__,
                "reason":
                    "RESOLUTION_ERROR",
            }

            return result

        result["resolution"] = (
            resolution
        )

        if not resolution.get(
            "matched"
        ):
            return result

        if resolution.get(
            "ambiguous"
        ):
            return result

        thread = resolution.get(
            "thread"
        )

        if thread is None:
            return result

        thread_id = getattr(
            thread,
            "thread_id",
            None,
        )

        if thread_id in (
            None,
            "",
        ):
            result["sync"] = {
                "error": True,
                "error_type":
                    "ValueError",
                "reason":
                    "RESOLVED_THREAD_ID_MISSING",
            }

            return result

        try:
            result["sync"] = (
                self._get_sync_service()
                .sync_open_chat_messages(
                    thread_id=thread_id,
                    limit=sync_limit,
                    expected_active_identity=(
                        current.active_identity
                    ),
                    expected_last_provider_message_id=(
                        current.last_provider_message_id
                    ),
                )
            )

        except Exception as exc:
            result["sync"] = {
                "error": True,
                "error_type":
                    type(
                        exc
                    ).__name__,
                "reason":
                    "SYNC_ERROR",
            }

        return result


    def observe_and_sync_active_chat(
        self,
        *,
        wait_timeout=60,
        sync_limit=200,
    ):
        return self._run_serialized(
            self._observe_and_sync_active_chat_impl,
            wait_timeout=wait_timeout,
            sync_limit=sync_limit,
        )


    @property
    def active_chat_watch_last_error(
        self,
    ):
        with self._active_chat_watch_lock:
            return (
                self._active_chat_watch_last_error
            )


    @property
    def active_chat_watch_last_sync(
        self,
    ):
        with self._active_chat_watch_lock:
            return (
                self._active_chat_watch_last_sync
            )


    @property
    def active_chat_watch_running(
        self,
    ):
        with self._active_chat_watch_lock:
            thread = (
                self._active_chat_watch_thread
            )

            return bool(
                thread
                and thread.is_alive()
            )

    def _active_chat_watch_loop(
        self,
        *,
        stop_event,
        interval_seconds,
        wait_timeout,
        on_change,
    ):
        while not stop_event.is_set():
            try:
                result = (
                    self.observe_and_sync_active_chat(
                        wait_timeout=wait_timeout,
                    )
                )

                resolution = result.get(
                    "resolution"
                )

                sync_result = result.get(
                    "sync"
                )

                diagnostic_error = None

                if (
                    isinstance(
                        resolution,
                        dict,
                    )
                    and resolution.get(
                        "error"
                    )
                ):
                    diagnostic_error = {
                        "timestamp":
                            time.time(),
                        "stage":
                            "RESOLUTION",
                        "reason":
                            resolution.get(
                                "reason"
                            ),
                        "error_type":
                            resolution.get(
                                "error_type"
                            ),
                        "change_type":
                            result.get(
                                "change_type"
                            ),
                    }

                elif (
                    isinstance(
                        sync_result,
                        dict,
                    )
                    and sync_result.get(
                        "error"
                    )
                ):
                    diagnostic_error = {
                        "timestamp":
                            time.time(),
                        "stage":
                            "SYNC",
                        "reason":
                            sync_result.get(
                                "reason"
                            ),
                        "error_type":
                            sync_result.get(
                                "error_type"
                            ),
                        "change_type":
                            result.get(
                                "change_type"
                            ),
                    }

                with self._active_chat_watch_lock:
                    if diagnostic_error is not None:
                        self._active_chat_watch_last_error = (
                            diagnostic_error
                        )

                    if (
                        isinstance(
                            sync_result,
                            dict,
                        )
                        and not sync_result.get(
                            "error"
                        )
                        and not sync_result.get(
                            "aborted"
                        )
                    ):
                        self._active_chat_watch_last_sync = {
                            "timestamp":
                                time.time(),
                            "change_type":
                                result.get(
                                    "change_type"
                                ),
                            "sync":
                                sync_result,
                        }

                if (
                    result.get(
                        "changed"
                    )
                    and callable(
                        on_change
                    )
                ):
                    try:
                        on_change(
                            result
                        )
                    except Exception as exc:
                        # Un callback consumidor nunca debe
                        # matar la vigilancia del transporte.
                        with self._active_chat_watch_lock:
                            self._active_chat_watch_last_error = {
                                "timestamp":
                                    time.time(),
                                "stage":
                                    "CALLBACK",
                                "reason":
                                    "CALLBACK_ERROR",
                                "error_type":
                                    type(
                                        exc
                                    ).__name__,
                                "message":
                                    str(
                                        exc
                                    ),
                                "change_type":
                                    result.get(
                                        "change_type"
                                    ),
                            }

            except Exception as exc:
                # WhatsApp puede estar temporalmente
                # indisponible, re-renderizando o iniciando.
                # Un fallo aislado no mata el watcher,
                # pero queda diagnosticable.
                with self._active_chat_watch_lock:
                    self._active_chat_watch_last_error = {
                        "timestamp":
                            time.time(),
                        "stage":
                            "WATCH",
                        "reason":
                            "WATCH_ERROR",
                        "error_type":
                            type(
                                exc
                            ).__name__,
                        "message":
                            str(
                                exc
                            ),
                    }

            # Event.wait() permite despertar inmediatamente
            # al pedir stop, a diferencia de time.sleep().
            if stop_event.wait(
                interval_seconds
            ):
                break

    def start_active_chat_watch(
        self,
        *,
        interval_seconds=1.0,
        wait_timeout=5,
        on_change=None,
    ):
        interval = max(
            0.05,
            float(
                interval_seconds
            ),
        )

        effective_wait_timeout = max(
            1,
            float(
                wait_timeout
            ),
        )

        with self._active_chat_watch_lock:
            current = (
                self._active_chat_watch_thread
            )

            if (
                current is not None
                and current.is_alive()
            ):
                return current

            stop_event = (
                threading.Event()
            )

            self._active_chat_watch_last_error = None
            self._active_chat_watch_last_sync = None

            thread = threading.Thread(
                target=(
                    self._active_chat_watch_loop
                ),
                kwargs={
                    "stop_event":
                        stop_event,
                    "interval_seconds":
                        interval,
                    "wait_timeout":
                        effective_wait_timeout,
                    "on_change":
                        on_change,
                },
                name=(
                    "whatsapp-active-chat-watch"
                ),
                daemon=True,
            )

            self._active_chat_watch_stop = (
                stop_event
            )

            self._active_chat_watch_thread = (
                thread
            )

            thread.start()

            return thread

    def stop_active_chat_watch(
        self,
        *,
        join_timeout=5,
    ):
        with self._active_chat_watch_lock:
            thread = (
                self._active_chat_watch_thread
            )

            stop_event = (
                self._active_chat_watch_stop
            )

        if stop_event is not None:
            stop_event.set()

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=max(
                    0,
                    float(
                        join_timeout
                    ),
                )
            )

        with self._active_chat_watch_lock:
            if (
                self._active_chat_watch_thread
                is thread
            ):
                self._active_chat_watch_thread = None
                self._active_chat_watch_stop = None

        return bool(
            thread is not None
        )


    def _sync_open_chat_messages_impl(
        self,
        *,
        thread_id,
        limit=200,
        wait_timeout=60,
    ):
        self._ensure_ready_impl(
            wait_timeout=wait_timeout,
        )

        return (
            self._get_sync_service()
            .sync_open_chat_messages(
                thread_id=thread_id,
                limit=limit,
            )
        )

    def sync_open_chat_messages(
        self,
        *,
        thread_id,
        limit=200,
        wait_timeout=60,
    ):
        return self._run_serialized(
            self._sync_open_chat_messages_impl,
            thread_id=thread_id,
            limit=limit,
            wait_timeout=wait_timeout,
        )

    def _close_impl(
        self,
    ):
        connector = self._connector

        if connector is None:
            return False

        try:
            return bool(
                connector.close()
            )

        finally:
            self._connector = None
            self._outbound_service = None
            self._sync_service = None

    def close(
        self,
    ):
        # Impedimos nuevas observaciones antes de cerrar
        # connector y executor. Si una observación estaba en
        # curso, la serialización garantiza que termine antes
        # de que _close_impl use el mismo worker.
        self.stop_active_chat_watch()

        result = self._run_serialized(
            self._close_impl
        )

        with self._executor_lock:
            executor = self._executor
            self._executor = None

        if executor is not None:
            executor.shutdown(
                wait=True,
                cancel_futures=False,
            )

        self._worker_thread_id = None

        with self._desired_thread_lock:
            self._desired_thread_id = None

        self._active_chat_fingerprint = None

        return result

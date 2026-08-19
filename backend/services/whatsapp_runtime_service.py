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
from pathlib import Path
from datetime import datetime, timezone
import threading
import time

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_NEEDS_LOGIN,
    SESSION_STATUS_READY,
    WhatsAppConnector,
    diff_sidebar_chat_fingerprints,
)
from backend.services.communication_service import (
    CommunicationService,
)
from backend.services import (
    document_inbox_watch_service,
)
from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_STATUS_REJECTED,
    CALL_STATUS_RINGING,
)
from backend.automation.connectors.whatsapp_call_observer import (
    WHATSAPP_CALL_PHASE_ACTIVE,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_REPLACED,
    WhatsAppCallObservationTracker,
)
from backend.services.whatsapp_call_realtime_service import (
    WhatsAppCallRealtimeService,
)
from backend.services.whatsapp_outbound_service import (
    WhatsAppOutboundService,
)
from backend.services.whatsapp_sync_service import (
    WhatsAppSyncService,
)


def _default_call_clock():
    """
    Reloj de observación CRM.

    Devuelve tiempo UTC aware.
    No representa un timestamp afirmado por WhatsApp.
    """
    return datetime.now(
        timezone.utc
    )


class WhatsAppRuntimeService:
    def __init__(
        self,
        *,
        profile_key="whatsapp_dev",
        headless=False,
        communication_service=None,
        call_service=None,
        call_clock=None,
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

        if (
            call_clock is not None
            and not callable(
                call_clock
            )
        ):
            raise TypeError(
                "call_clock debe ser callable o None"
            )

        self.call_service = (
            call_service
        )

        self._call_clock = (
            call_clock
            or _default_call_clock
        )

        # Application service opcional.
        #
        # Nunca construye CommunicationCallService ni repository:
        # la composición productiva debe inyectar la dependencia.
        self._call_realtime_service = (
            WhatsAppCallRealtimeService(
                call_service=(
                    self.call_service
                )
            )
        )

        self._connector = None
        self._outbound_service = None
        self._sync_service = None

        # Memoria puramente observacional de la superficie
        # de llamada WhatsApp actualmente visible.
        #
        # No persiste ni clasifica outcomes de dominio.
        self._call_observation_tracker = (
            WhatsAppCallObservationTracker()
        )

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

        # Última fotografía ligera del sidebar de WhatsApp.
        #
        # Igual que la huella del chat activo, únicamente se
        # lee/escribe desde el worker único SeleniumBase/CDP.
        #
        # La primera lectura establece baseline y NO genera
        # falsos eventos SIDEBAR_THREAD_APPEARED.
        self._sidebar_chat_fingerprint = None

        # Último destinatario cuya identidad telefónica
        # fue verificada fuertemente antes de un envío.
        #
        # Esta cache NO sustituye la verificación fuerte:
        # únicamente permite reutilizarla mientras:
        # - se solicite el mismo thread;
        # - el teléfono persistido no haya cambiado;
        # - WhatsApp siga mostrando la misma identidad;
        # - esa identidad resuelva de forma única al mismo
        #   thread CRM.
        self._verified_send_thread_id = None
        self._verified_send_phone = None
        self._verified_send_identity = None

        # Watcher realtime de llamadas WhatsApp.
        #
        # Este hilo supervisor NO toca Selenium/CDP:
        # únicamente llama observe_and_sync_call(), cuya
        # implementación entra en el worker serializado.
        #
        # Es independiente del watcher del chat activo porque
        # una llamada puede existir aunque no haya chat abierto
        # ni vista Comunicaciones visible.
        self._call_watch_thread = None
        self._call_watch_stop = None
        self._call_watch_lock = threading.Lock()
        self._call_watch_on_change = None

        # Diagnóstico del watcher de llamadas.
        self._call_watch_last_error = None
        self._call_watch_last_result = None

        # Último resultado de la política de micrófono
        # aplicada a una llamada WhatsApp.
        #
        # La política automática se ejecuta únicamente
        # cuando una llamada entra realmente en ACTIVE.
        # No se re-ejecuta por cambios de temporizador
        # mientras la llamada permanece ACTIVE.
        self._call_microphone_last_result = None

        # Watcher ligero del chat activo.
        #
        # Este hilo NO toca SeleniumBase/CDP directamente:
        # únicamente solicita observe_active_chat(), que
        # serializa toda operación de navegador en el worker
        # único del runtime.
        self._active_chat_watch_thread = None
        self._active_chat_watch_stop = None
        self._active_chat_watch_lock = threading.Lock()
        self._active_chat_watch_on_change = None

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

    @staticmethod
    def _thread_allows_new_contact_fallback(
        thread,
    ):
        """Solo los threads iniciados manualmente por CRM.

        Un fallo de routing sobre cualquier conversación
        histórica nunca debe crear contactos automáticamente.
        """
        metadata = getattr(
            thread,
            "metadata",
            None,
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return False

        return (
            str(
                metadata.get(
                    "source"
                )
                or ""
            )
            .strip()
            == "crm_manual_outbound_start"
        )


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

        if self._thread_allows_new_contact_fallback(
            thread
        ):
            routing = (
                connector
                .open_or_create_manual_chat(
                    phone,
                    display_name=(
                        thread.external_display_name
                    ),
                    timeout=routing_timeout,
                )
            )
        else:
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

            # Un número que antes aparecía sin guardar puede
            # pasar a mostrarse bajo el nombre de un contacto.
            #
            # En ese caso el buscador general puede dejar de
            # devolver el teléfono aunque Nuevo chat sí pueda
            # resolverlo inequívocamente por número.
            #
            # Este fallback es EXISTING_ONLY:
            # un click normal nunca crea contactos.
            if (
                not routing.get(
                    "opened"
                )
                and routing.get(
                    "reason"
                )
                == "CHAT_SEARCH_NO_MATCHING_RESULT"
            ):
                routing = (
                    connector
                    .open_or_create_manual_chat(
                        phone,
                        display_name=(
                            thread.external_display_name
                            or phone
                        ),
                        timeout=routing_timeout,
                        allow_create=False,
                    )
                )

        if (
            routing.get(
                "opened"
            )
            and routing.get(
                "navigation"
            )
            == "NEW_CHAT_EXISTING"
        ):
            observed_name = str(
                routing.get(
                    "display_name"
                )
                or ""
            ).strip()

            current_name = str(
                thread.external_display_name
                or ""
            ).strip()

            phone_digits = "".join(
                char
                for char in phone
                if char.isdigit()
            )

            observed_digits = "".join(
                char
                for char in observed_name
                if char.isdigit()
            )

            observed_is_phone = bool(
                phone_digits
                and observed_digits
                and phone_digits
                == observed_digits
            )

            updater = getattr(
                self.communication_service,
                "update_whatsapp_thread_display_name",
                None,
            )

            if (
                observed_name
                and not observed_is_phone
                and observed_name != current_name
                and callable(
                    updater
                )
            ):
                try:
                    thread = updater(
                        int(
                            thread.id
                        ),
                        observed_name,
                    )

                    print(
                        "[WA-ROUTE] observed display name reconciled",
                        {
                            "thread_id":
                                int(thread.id),
                            "display_name":
                                observed_name,
                        },
                        flush=True,
                    )

                except Exception as exc:
                    print(
                        "[WA-ROUTE] observed display name reconciliation failed",
                        repr(exc),
                        flush=True,
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

        if self._thread_allows_new_contact_fallback(
            thread
        ):
            prepared = (
                connector
                .open_or_create_manual_chat(
                    phone,
                    display_name=(
                        thread.external_display_name
                    ),
                    timeout=routing_timeout,
                )
            )

            routing = prepared

            if prepared.get(
                "opened"
            ):
                # El chat ya fue seleccionado mediante
                # Nuevo chat. Para operación sensible solo
                # verificamos ahora la identidad activa.
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

                if routing.get(
                    "verified"
                ):
                    routing[
                        "navigation"
                    ] = (
                        prepared.get(
                            "navigation"
                        )
                        or "NEW_CHAT_FIRST"
                    )

        else:
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

    def _open_latest_thread_for_selection_impl(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Abre el último thread solicitado con ruta ligera.

        La selección explícita:
        1. invalida cualquier autorización del chat anterior;
        2. navega por teléfono con verify_identity=False;
        3. deja que el connector confirme compositor + cabecera;
        4. toma fingerprint del chat resultante;
        5. exige resolución inequívoca de esa identidad al
           mismo thread CRM.

        NO abre Información del contacto.
        NO ejecuta _verify_active_chat_phone().
        NO bloquea el worker con un profile-prewarm.

        Si el guard ligero no puede certificarse, el envío
        conserva el fallback telefónico fuerte histórico.
        """
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
                "reason":
                    "STALE_SELECTION",
                "requested_thread_id":
                    requested_thread_id,
                "desired_thread_id":
                    desired_thread_id,
            }

        # Nunca heredamos autorización de otro chat.
        self._clear_verified_send_route()

        result = (
            self._open_thread_impl(
                requested_thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=routing_timeout,
            )
        )

        with self._desired_thread_lock:
            desired_thread_id = (
                self._desired_thread_id
            )

        if (
            desired_thread_id
            != requested_thread_id
        ):
            self._clear_verified_send_route()

            return {
                "skipped": True,
                "reason":
                    "STALE_SELECTION_AFTER_OPEN",
                "requested_thread_id":
                    requested_thread_id,
                "desired_thread_id":
                    desired_thread_id,
            }

        routing = dict(
            result.get(
                "routing"
            )
            or {}
        )

        routing[
            "selection_light"
        ] = True

        thread = (
            result.get(
                "thread"
            )
            if isinstance(
                result,
                dict,
            )
            else None
        )

        connector = self._connector

        remembered = False

        if (
            thread is not None
            and connector is not None
        ):
            remembered = (
                self._remember_verified_send_route(
                    thread=thread,
                    connector=connector,
                )
            )

        routing[
            "send_preverified"
        ] = bool(
            remembered
        )

        routing[
            "send_route_basis"
        ] = (
            "EXPLICIT_SELECTION_IDENTITY"
            if remembered
            else None
        )

        result[
            "routing"
        ] = routing

        return result


    def _add_contact_and_open_impl(
        self,
        phone,
        *,
        display_name,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Añade explícitamente un contacto en WhatsApp Web.

        Esta operación:
        - NO es routing normal de conversaciones;
        - SIEMPRE ejecuta Nuevo chat -> Nuevo contacto;
        - SIEMPRE intenta Guardar contacto;
        - abre después la conversación resultante.
        """
        connector = self._ensure_ready_impl(
            wait_timeout=wait_timeout,
        )

        result = (
            connector
            .create_and_open_contact(
                phone,
                display_name=display_name,
                timeout=routing_timeout,
            )
        )

        if not result.get(
            "opened"
        ):
            try:
                connector.cancel_new_contact_flow(
                    timeout=min(
                        3,
                        routing_timeout,
                    ),
                )
            except Exception:
                pass

            reason = (
                result.get(
                    "reason"
                )
                or "ADD_CONTACT_FAILED"
            )

            raise RuntimeError(
                "No se pudo añadir el contacto "
                f"WhatsApp ({reason})"
            )

        return result

    def add_contact_and_open(
        self,
        phone,
        *,
        display_name,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Caso de uso público: añadir contacto WhatsApp."""
        return self._run_serialized(
            self._add_contact_and_open_impl,
            phone,
            display_name=display_name,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )


    def open_thread_for_selection(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Abre rápidamente un thread solicitado desde la UI.

        No sustituye verify_and_open_thread(): aquella operación
        continúa siendo la variante de verificación fuerte.
        """
        requested_thread_id = int(
            thread_id
        )

        with self._desired_thread_lock:
            self._desired_thread_id = (
                requested_thread_id
            )

        return self._run_serialized(
            self._open_latest_thread_for_selection_impl,
            requested_thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )


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

        # Optimización de routing de selección:
        # Selección CRM = navegar primero al destino mediante
        # la ruta ligera. No inspeccionamos el perfil del chat
        # anterior, porque sabemos que el usuario ha pedido
        # expresamente otro thread.
        result = (
            self._open_thread_impl(
                requested_thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=routing_timeout,
            )
        )

        with self._desired_thread_lock:
            desired_thread_id = (
                self._desired_thread_id
            )

        if (
            desired_thread_id
            != requested_thread_id
        ):
            self._clear_verified_send_route()

            return {
                "skipped": True,
                "reason": "STALE_SELECTION_AFTER_OPEN",
                "requested_thread_id":
                    requested_thread_id,
                "desired_thread_id":
                    desired_thread_id,
            }

        thread = (
            result.get(
                "thread"
            )
            if isinstance(
                result,
                dict,
            )
            else None
        )

        connector = self._connector

        if (
            thread is None
            or connector is None
        ):
            self._clear_verified_send_route()

            return result

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            self._clear_verified_send_route()

            return result

        # El destino ya está abierto. Ahora hacemos UNA única
        # verificación fuerte sobre ese chat activo.
        verification = (
            connector
            ._verify_active_chat_phone(
                phone,
                timeout=min(
                    8,
                    max(
                        1,
                        int(
                            routing_timeout
                        ),
                    ),
                ),
            )
        )

        with self._desired_thread_lock:
            desired_thread_id = (
                self._desired_thread_id
            )

        if (
            desired_thread_id
            != requested_thread_id
        ):
            self._clear_verified_send_route()

            return {
                "skipped": True,
                "reason":
                    "STALE_SELECTION_AFTER_VERIFY",
                "requested_thread_id":
                    requested_thread_id,
                "desired_thread_id":
                    desired_thread_id,
            }

        if not verification.get(
            "verified"
        ):
            self._clear_verified_send_route()

            reason = (
                verification.get(
                    "reason"
                )
                or "IDENTITY_UNVERIFIABLE"
            )

            raise RuntimeError(
                "No se pudo verificar el "
                "destinatario WhatsApp "
                f"({reason})"
            )

        routing = dict(
            result.get(
                "routing"
            )
            or {}
        )

        routing.update(
            verification
        )

        result[
            "routing"
        ] = routing

        remembered = (
            self._remember_verified_send_route(
                thread=thread,
                connector=connector,
            )
        )


        return result


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

    def _clear_verified_send_route(
        self,
    ):
        self._verified_send_thread_id = None
        self._verified_send_phone = None
        self._verified_send_identity = None

    @staticmethod
    def _resolved_thread_id(
        resolution,
    ):
        if not isinstance(
            resolution,
            dict,
        ):
            return None

        thread = resolution.get(
            "thread"
        )

        if thread is None:
            return None

        value = getattr(
            thread,
            "thread_id",
            None,
        )

        if value is None:
            value = getattr(
                thread,
                "id",
                None,
            )

        if value in (
            None,
            "",
        ):
            return None

        try:
            return int(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    def _remember_verified_send_route(
        self,
        *,
        thread,
        connector,
    ):
        """Recuerda una ruta de envío mientras siga siendo inequívoca.

        La autorización puede proceder de:
        - una verificación telefónica fuerte; o
        - una selección explícita que acaba de abrir el thread
          por teléfono y cuya identidad activa resuelve de
          forma única al mismo thread CRM.

        Esta cache nunca autoriza por sí sola un envío futuro:
        _can_reuse_verified_send_route() vuelve a comprobar
        fingerprint + identidad + resolución justo antes del
        transporte.
        """
        try:
            fingerprint = (
                connector
                .get_active_chat_fingerprint()
            )
        except Exception:
            self._clear_verified_send_route()
            return False

        identity = str(
            getattr(
                fingerprint,
                "active_identity",
                "",
            )
            or ""
        ).strip()

        if (
            not getattr(
                fingerprint,
                "chat_open",
                False,
            )
            or not identity
        ):
            self._clear_verified_send_route()
            return False

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            self._clear_verified_send_route()
            return False

        requested_thread_id = int(
            thread.id
        )

        # El nombre/identidad observable debe resolver de
        # forma inequívoca al mismo thread que acaba de ser
        # seleccionado por teléfono.
        try:
            resolution = (
                self.communication_service
                .resolve_whatsapp_thread_by_identity(
                    identity
                )
            )
        except Exception:
            self._clear_verified_send_route()
            return False

        if (
            not isinstance(
                resolution,
                dict,
            )
            or not resolution.get(
                "matched"
            )
            or resolution.get(
                "ambiguous"
            )
            or (
                self._resolved_thread_id(
                    resolution
                )
                != requested_thread_id
            )
        ):
            self._clear_verified_send_route()
            return False

        self._verified_send_thread_id = (
            requested_thread_id
        )

        self._verified_send_phone = phone

        self._verified_send_identity = (
            identity
        )

        return True


    def _can_reuse_verified_send_route(
        self,
        *,
        thread,
        connector,
    ):
        requested_thread_id = int(
            thread.id
        )

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if (
            self._verified_send_thread_id
            != requested_thread_id
            or self._verified_send_phone
            != phone
            or not self._verified_send_identity
        ):
            return False

        try:
            fingerprint = (
                connector
                .get_active_chat_fingerprint()
            )
        except Exception:
            self._clear_verified_send_route()
            return False

        current_identity = str(
            getattr(
                fingerprint,
                "active_identity",
                "",
            )
            or ""
        ).strip()

        if (
            not getattr(
                fingerprint,
                "chat_open",
                False,
            )
            or not current_identity
            or (
                current_identity
                != self._verified_send_identity
            )
        ):
            self._clear_verified_send_route()


            return False

        try:
            resolution = (
                self.communication_service
                .resolve_whatsapp_thread_by_identity(
                    current_identity
                )
            )
        except Exception:
            self._clear_verified_send_route()


            return False

        if (
            not isinstance(
                resolution,
                dict,
            )
            or not resolution.get(
                "matched"
            )
            or resolution.get(
                "ambiguous"
            )
            or (
                self._resolved_thread_id(
                    resolution
                )
                != requested_thread_id
            )
        ):
            self._clear_verified_send_route()


            return False

        return True

    def _prepare_verified_outbound_impl(
        self,
        *,
        thread_id,
        wait_timeout=60,
        routing_timeout=15,
    ):
        """Prepara una única ruta inequívoca para cualquier outbound.

        Texto y documentos comparten exactamente estas barreras:
        - Runtime READY;
        - thread CRM existente;
        - teléfono WhatsApp persistido;
        - cache de ruta todavía válida; o
        - verificación fuerte antes del transporte.

        No ejecuta el transporte.
        """
        if thread_id in (
            None,
            "",
        ):
            raise ValueError(
                "thread_id es obligatorio"
            )

        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        thread = (
            self.communication_service
            .get_thread(
                thread_id
            )
        )

        if thread is None:
            self._clear_verified_send_route()

            raise ValueError(
                "Conversación no encontrada"
            )

        phone = str(
            thread.external_address
            or ""
        ).strip()

        if not phone:
            self._clear_verified_send_route()

            raise ValueError(
                "La conversación no tiene "
                "teléfono WhatsApp verificable"
            )

        if not self._can_reuse_verified_send_route(
            thread=thread,
            connector=connector,
        ):
            routing_result = (
                self._verify_and_open_thread_impl(
                    thread_id,
                    wait_timeout=wait_timeout,
                    routing_timeout=(
                        routing_timeout
                    ),
                )
            )

            verified_thread = (
                routing_result[
                    "thread"
                ]
            )

            self._remember_verified_send_route(
                thread=verified_thread,
                connector=connector,
            )

            thread = verified_thread

        return thread


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

        self._prepare_verified_outbound_impl(
            thread_id=thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )

        return (
            self._get_outbound_service()
            .send_text_message(
                **kwargs
            )
        )


    def _send_document_message_impl(
        self,
        *,
        wait_timeout=60,
        routing_timeout=15,
        **kwargs,
    ):
        thread_id = kwargs.get(
            "thread_id"
        )

        self._prepare_verified_outbound_impl(
            thread_id=thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
        )

        return (
            self._get_outbound_service()
            .send_document_message(
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


    def send_document_message(
        self,
        *,
        wait_timeout=60,
        routing_timeout=15,
        **kwargs,
    ):
        """Envía un documento por la ruta serializada gobernada."""
        return self._run_serialized(
            self._send_document_message_impl,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
            **kwargs,
        )

    def _start_voice_call_for_thread_impl(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
        call_confirm_timeout=1.0,
    ):
        """Inicia llamada de voz hacia un thread CRM.

        Barreras:
        1. runtime READY;
        2. ninguna llamada ya presente;
        3. permiso de micrófono, cuando el connector
           expone diagnóstico explícito;
        4. routing + verificación FUERTE del destinatario;
        5. un único click de llamada de voz;
        6. nunca retry ciego tras el click.
        """
        requested_thread_id = int(
            thread_id
        )

        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        existing_call = (
            connector
            .read_call_snapshot()
        )

        if bool(
            getattr(
                existing_call,
                "present",
                False,
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "CALL_ALREADY_PRESENT",
                "thread_id":
                    requested_thread_id,
            }

        # CALL-UX-1 dejó el permiso configurado
        # durante start(). Si existe un diagnóstico
        # explícitamente negativo, hacemos un único
        # intento de recuperación antes de marcar.
        permission = getattr(
            connector,
            "call_media_permission_result",
            None,
        )

        if (
            isinstance(
                permission,
                dict,
            )
            and permission.get(
                "configured"
            )
            is False
        ):
            configure = getattr(
                connector,
                "configure_call_media_permissions",
                None,
            )

            if callable(
                configure
            ):
                permission = (
                    configure()
                )

            if (
                isinstance(
                    permission,
                    dict,
                )
                and permission.get(
                    "configured"
                )
                is False
            ):
                return {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "MICROPHONE_PERMISSION_NOT_READY",
                    "thread_id":
                        requested_thread_id,
                    "permission":
                        permission,
                }

        # Acción sensible:
        # NO usamos open_thread_for_selection().
        #
        # Esta ruta exige verificación fuerte del teléfono
        # antes de que el connector pueda pulsar "Llamada".
        routing_result = (
            self._verify_and_open_thread_impl(
                requested_thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=routing_timeout,
            )
        )

        thread = (
            routing_result[
                "thread"
            ]
        )

        call_result = (
            connector
            .start_voice_call(
                confirm_timeout=(
                    call_confirm_timeout
                )
            )
        )

        if not isinstance(
            call_result,
            dict,
        ):
            call_result = {
                "ok": False,
                "uncertain": True,
                "clicked": True,
                "reason":
                    "VOICE_CALL_RESULT_INVALID",
                "raw_result":
                    call_result,
            }

        result = dict(
            call_result
        )

        observed_snapshot = (
            result.pop(
                "_snapshot",
                None,
            )
        )

        result[
            "thread_id"
        ] = requested_thread_id

        result[
            "phone"
        ] = str(
            getattr(
                thread,
                "external_address",
                "",
            )
            or ""
        ).strip()

        result[
            "routing"
        ] = dict(
            routing_result.get(
                "routing"
            )
            or {}
        )

        # El snapshot observado por la propia acción no se
        # desperdicia: lo incorporamos al mismo tracker que
        # utiliza el watcher global.
        #
        # Si todavía es CONNECTING será no-actionable.
        # Si ya es DIALING podrá reconciliarse inmediatamente.
        # El watcher continuará después desde ese mismo estado.
        if (
            observed_snapshot is not None
            and bool(
                getattr(
                    observed_snapshot,
                    "present",
                    False,
                )
            )
        ):
            observation = (
                self
                ._call_observation_tracker
                .observe(
                    observed_snapshot
                )
            )

            self._maybe_ensure_active_call_microphone(
                observation
            )

            observed_at = None

            if (
                self
                ._call_realtime_service
                .enabled
            ):
                observed_at = (
                    self._call_observed_at()
                )

            realtime_result = (
                self
                ._call_realtime_service
                .process_observation(
                    observation,
                    observed_at=(
                        observed_at
                    ),
                )
            )

            result[
                "realtime_action"
            ] = getattr(
                realtime_result,
                "action",
                None,
            )

            result[
                "observed_phase"
            ] = getattr(
                observed_snapshot,
                "phase",
                None,
            )

            result[
                "provider_call_id"
            ] = getattr(
                observed_snapshot,
                "provider_call_id",
                None,
            )

        return result


    def start_voice_call_for_thread(
        self,
        thread_id,
        *,
        wait_timeout=60,
        routing_timeout=15,
        call_confirm_timeout=1.0,
    ):
        """API pública serializada de llamada saliente WhatsApp."""
        return self._run_serialized(
            self._start_voice_call_for_thread_impl,
            thread_id,
            wait_timeout=wait_timeout,
            routing_timeout=routing_timeout,
            call_confirm_timeout=(
                call_confirm_timeout
            ),
        )


    def _get_persisted_incoming_ringing_call(
        self,
        call_id,
    ):
        call_service = getattr(
            self._call_realtime_service,
            "call_service",
            None,
        )

        if call_service is None:
            return (
                None,
                {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "CALL_PERSISTENCE_DISABLED",
                },
            )

        try:
            normalized_call_id = int(
                call_id
            )

        except Exception:
            return (
                None,
                {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "CALL_ID_INVALID",
                },
            )

        call = (
            call_service.get_call(
                normalized_call_id
            )
        )

        if call is None:
            return (
                None,
                {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "CALL_NOT_FOUND",
                    "call_id":
                        normalized_call_id,
                },
            )

        if (
            str(
                getattr(
                    call,
                    "direction",
                    "",
                )
                or ""
            ).strip().upper()
            != CALL_DIRECTION_INBOUND
        ):
            return (
                None,
                {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "CALL_NOT_INBOUND",
                    "call_id":
                        normalized_call_id,
                },
            )

        if (
            str(
                getattr(
                    call,
                    "status",
                    "",
                )
                or ""
            ).strip().upper()
            != CALL_STATUS_RINGING
        ):
            return (
                None,
                {
                    "ok": False,
                    "uncertain": False,
                    "clicked": False,
                    "reason":
                        "CALL_NOT_RINGING",
                    "call_id":
                        normalized_call_id,
                    "status":
                        getattr(
                            call,
                            "status",
                            None,
                        ),
                },
            )

        return (
            call,
            None,
        )


    def _accept_incoming_call_impl(
        self,
        call_id,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        wait_timeout=60,
        confirm_timeout=2.0,
    ):
        call, error = (
            self
            ._get_persisted_incoming_ringing_call(
                call_id
            )
        )

        if error is not None:
            return error

        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout
            )
        )

        raw_result = (
            connector.accept_incoming_call(
                expected_provider_call_id=(
                    expected_provider_call_id
                ),
                expected_external_call_key=(
                    expected_external_call_key
                ),
                confirm_timeout=(
                    confirm_timeout
                ),
            )
        )

        result = (
            dict(raw_result)
            if isinstance(
                raw_result,
                dict,
            )
            else {
                "ok": False,
                "uncertain": True,
                "clicked": True,
                "reason":
                    "CALL_ACCEPT_RESULT_INVALID",
                "raw_result":
                    raw_result,
            }
        )

        snapshot = result.pop(
            "_snapshot",
            None,
        )

        result["call_id"] = int(
            call.id
        )

        if (
            snapshot is not None
            and bool(
                getattr(
                    snapshot,
                    "present",
                    False,
                )
            )
        ):
            observation = (
                self
                ._call_observation_tracker
                .observe(
                    snapshot
                )
            )

            self._maybe_ensure_active_call_microphone(
                observation
            )

            observed_at = None

            if (
                self
                ._call_realtime_service
                .enabled
            ):
                observed_at = (
                    self._call_observed_at()
                )

            realtime_result = (
                self
                ._call_realtime_service
                .process_observation(
                    observation,
                    observed_at=(
                        observed_at
                    ),
                )
            )

            result[
                "realtime_action"
            ] = getattr(
                realtime_result,
                "action",
                None,
            )

            persisted = getattr(
                realtime_result,
                "persisted_call",
                None,
            )

            if persisted is not None:
                result[
                    "persisted_status"
                ] = getattr(
                    persisted,
                    "status",
                    None,
                )

        return result


    def accept_incoming_call(
        self,
        call_id,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        wait_timeout=60,
        confirm_timeout=2.0,
    ):
        """
        Atiende una llamada entrante desde CRM.

        Toda interacción browser permanece en el worker único.
        """
        return self._run_serialized(
            self._accept_incoming_call_impl,
            call_id,
            expected_provider_call_id=(
                expected_provider_call_id
            ),
            expected_external_call_key=(
                expected_external_call_key
            ),
            wait_timeout=wait_timeout,
            confirm_timeout=(
                confirm_timeout
            ),
        )


    def _reject_incoming_call_impl(
        self,
        call_id,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        wait_timeout=60,
        confirm_timeout=2.0,
    ):
        call, error = (
            self
            ._get_persisted_incoming_ringing_call(
                call_id
            )
        )

        if error is not None:
            return error

        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout
            )
        )

        raw_result = (
            connector.reject_incoming_call(
                expected_provider_call_id=(
                    expected_provider_call_id
                ),
                expected_external_call_key=(
                    expected_external_call_key
                ),
                confirm_timeout=(
                    confirm_timeout
                ),
            )
        )

        result = (
            dict(raw_result)
            if isinstance(
                raw_result,
                dict,
            )
            else {
                "ok": False,
                "uncertain": True,
                "clicked": True,
                "reason":
                    "CALL_REJECT_RESULT_INVALID",
                "raw_result":
                    raw_result,
            }
        )

        result.pop(
            "_snapshot",
            None,
        )

        result["call_id"] = int(
            call.id
        )

        # Solo materializamos REJECTED cuando el provider
        # confirma inequívocamente el click.
        if (
            result.get("ok") is True
            and result.get("clicked") is True
            and result.get("uncertain") is False
        ):
            call_service = getattr(
                self._call_realtime_service,
                "call_service",
                None,
            )

            try:
                rejected = (
                    call_service
                    .apply_call_event(
                        int(call.id),
                        status=(
                            CALL_STATUS_REJECTED
                        ),
                        event_at=(
                            self._call_observed_at()
                        ),
                    )
                )

                result[
                    "crm_persisted"
                ] = True

                result[
                    "persisted_status"
                ] = getattr(
                    rejected,
                    "status",
                    None,
                )

                # Evita que la posterior desaparición de la
                # superficie vuelva a inferirse como MISSED.
                #
                # La intención explícita del operador ya es un
                # hecho más fuerte que la mera desaparición DOM.
                self._call_observation_tracker.reset()

                result[
                    "observation_tracker_reset"
                ] = True

            except Exception as exc:
                # El provider YA pudo haber ejecutado el rechazo.
                # Nunca convertimos un error posterior de DB
                # en autorización para volver a pulsar.
                result[
                    "crm_persisted"
                ] = False

                result[
                    "crm_persistence_error"
                ] = {
                    "error_type":
                        type(exc).__name__,
                    "message":
                        str(exc),
                }

        return result


    def reject_incoming_call(
        self,
        call_id,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        wait_timeout=60,
        confirm_timeout=2.0,
    ):
        """
        Rechaza una llamada entrante desde CRM.

        Un rechazo confirmado se persiste explícitamente
        como REJECTED antes de devolver control al watcher.
        """
        return self._run_serialized(
            self._reject_incoming_call_impl,
            call_id,
            expected_provider_call_id=(
                expected_provider_call_id
            ),
            expected_external_call_key=(
                expected_external_call_key
            ),
            wait_timeout=wait_timeout,
            confirm_timeout=(
                confirm_timeout
            ),
        )


    def _sync_call_history_impl(
        self,
        *,
        wait_timeout=60,
        navigation_timeout=5,
        dry_run=False,
    ):
        """
        Sincroniza historial WhatsApp en una sola operación
        gobernada por el worker.

        Secuencia:
        - verifica READY;
        - no navega si existe llamada activa;
        - captura pestaña actual;
        - abre Llamadas si es necesario;
        - extrae historial;
        - proyecta/reconcilia;
        - restaura Chats si estaba activa inicialmente.

        Ningún watcher puede intercalarse en el cambio temporal
        porque toda la operación vive dentro de _run_serialized().
        """
        from backend.services.whatsapp_call_history_sync_service import (
            apply_whatsapp_history_reconciliation_plan,
            build_whatsapp_history_reconciliation_plan,
        )

        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        current_call = (
            connector
            .read_call_snapshot()
        )

        if bool(
            getattr(
                current_call,
                "present",
                False,
            )
        ):
            return {
                "skipped":
                    True,
                "reason":
                    "ACTIVE_CALL",
                "dry_run":
                    bool(dry_run),
                "history":
                    None,
                "plan":
                    None,
                "execution":
                    None,
                "navigation":
                    None,
            }

        before = (
            connector
            .read_primary_navigation_state()
        )

        chats_was_active = (
            before.get(
                "chats_pressed"
            )
            == "true"
        )

        calls_was_active = (
            before.get(
                "calls_pressed"
            )
            == "true"
        )

        if not (
            chats_was_active
            or calls_was_active
        ):
            raise RuntimeError(
                "No se pudo determinar "
                "la pestaña WhatsApp activa"
            )

        opened_calls = False
        restore_result = None

        try:
            if not calls_was_active:
                (
                    connector
                    .open_calls_tab(
                        timeout=(
                            navigation_timeout
                        ),
                    )
                )

                opened_calls = True

            # aria-pressed confirma la navegación primaria,
            # pero React puede tardar unas décimas adicionales
            # en materializar las filas del historial.
            #
            # No usamos sleep fijo: esperamos evidencia funcional
            # real del reader (rows_scanned > 0) con timeout.
            history_deadline = (
                time.time()
                + max(
                    0.5,
                    float(
                        navigation_timeout
                    ),
                )
            )

            history = None
            materialization_attempts = 0

            while True:
                materialization_attempts += 1

                history = (
                    connector
                    .read_visible_call_history()
                )

                rows_scanned = int(
                    (
                        history.get(
                            "rows_scanned"
                        )
                        if isinstance(
                            history,
                            dict,
                        )
                        else 0
                    )
                    or 0
                )

                if rows_scanned > 0:
                    break

                if (
                    time.time()
                    >= history_deadline
                ):
                    raise TimeoutError(
                        "La pestaña Llamadas está activa "
                        "pero el historial no llegó a "
                        "materializar filas visibles"
                    )

                time.sleep(
                    0.1
                )

            plan = (
                build_whatsapp_history_reconciliation_plan(
                    history
                )
            )

            call_service = getattr(
                self,
                "call_service",
                None,
            )

            if (
                not dry_run
                and call_service is None
            ):
                raise RuntimeError(
                    "CommunicationCallService "
                    "no está configurado"
                )

            execution = (
                apply_whatsapp_history_reconciliation_plan(
                    plan,
                    call_service=(
                        call_service
                    ),
                    dry_run=(
                        dry_run
                    ),
                )
            )

        finally:
            if (
                opened_calls
                and chats_was_active
            ):
                restore_result = (
                    connector
                    .open_chats_tab(
                        timeout=(
                            navigation_timeout
                        ),
                    )
                )

        after = (
            connector
            .read_primary_navigation_state()
        )

        return {
            "skipped":
                False,

            "reason":
                None,

            "dry_run":
                bool(dry_run),

            "history":
                history,

            "plan":
                plan,

            "execution":
                execution,

            "navigation": {
                "before":
                    before,

                "opened_calls":
                    opened_calls,

                "materialization_attempts":
                    materialization_attempts,

                "restore_result":
                    restore_result,

                "after":
                    after,
            },
        }


    def submit_call_history_sync(
        self,
        *,
        wait_timeout=60,
        navigation_timeout=5,
        dry_run=False,
    ):
        """
        Envía una sincronización histórica al worker único
        WhatsApp sin bloquear al caller.

        La operación física sigue siendo exactamente
        _sync_call_history_impl(), por lo que:
        - conserva serialización CDP;
        - no crea otro navegador;
        - no crea otro worker de browser;
        - queda ordenada respecto al watcher realtime;
        - close() puede esperar al mismo executor gobernado.
        """
        executor = (
            self._get_executor()
        )

        return executor.submit(
            self._execute_on_worker,
            self._sync_call_history_impl,
            wait_timeout=wait_timeout,
            navigation_timeout=(
                navigation_timeout
            ),
            dry_run=dry_run,
        )


    def sync_call_history(
        self,
        *,
        wait_timeout=60,
        navigation_timeout=5,
        dry_run=False,
    ):
        """
        API pública serializada de sincronización histórica.
        """
        return self._run_serialized(
            self._sync_call_history_impl,
            wait_timeout=wait_timeout,
            navigation_timeout=(
                navigation_timeout
            ),
            dry_run=dry_run,
        )


    def _read_visible_call_history_impl(
        self,
        *,
        wait_timeout=60,
    ):
        """
        Lee pasivamente el historial visible de llamadas.

        No navega.
        No persiste.
        Toda interacción CDP permanece en el worker gobernado.
        """
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        return (
            connector
            .read_visible_call_history()
        )


    def read_visible_call_history(
        self,
        *,
        wait_timeout=60,
    ):
        """
        API pública serializada del historial visible de llamadas.
        """
        return self._run_serialized(
            self._read_visible_call_history_impl,
            wait_timeout=wait_timeout,
        )


    def _read_call_snapshot_impl(
        self,
        *,
        wait_timeout=60,
    ):
        """Lee pasivamente la llamada actual en el worker WhatsApp.

        No persiste.
        No interpreta lifecycle de dominio.
        No conoce CommunicationCallService.
        """
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        return (
            connector.read_call_snapshot()
        )


    def read_call_snapshot(
        self,
        *,
        wait_timeout=60,
    ):
        """Expone la fotografía VOIP respetando afinidad CDP."""
        return self._run_serialized(
            self._read_call_snapshot_impl,
            wait_timeout=wait_timeout,
        )


    def _observe_call_impl(
        self,
        *,
        wait_timeout=60,
    ):
        """Observa lifecycle provider sin persistir ni clasificar."""
        current = (
            self._read_call_snapshot_impl(
                wait_timeout=wait_timeout,
            )
        )

        return (
            self._call_observation_tracker
            .observe(
                current
            )
        )


    def observe_call(
        self,
        *,
        wait_timeout=60,
    ):
        """Observación stateful serializada de llamada WhatsApp."""
        return self._run_serialized(
            self._observe_call_impl,
            wait_timeout=wait_timeout,
        )


    def _call_observed_at(
        self,
    ):
        """
        Materializa el reloj CRM como ISO-8601.

        La validación definitiva de zona horaria permanece
        en el adapter puro.
        """
        value = (
            self._call_clock()
        )

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        return str(
            value
            or ""
        ).strip()


    @property
    def call_microphone_last_result(
        self,
    ):
        with self._call_watch_lock:
            value = (
                self._call_microphone_last_result
            )

            return (
                dict(value)
                if isinstance(
                    value,
                    dict,
                )
                else value
            )


    def _remember_call_microphone_result(
        self,
        result,
    ):
        value = (
            dict(result)
            if isinstance(
                result,
                dict,
            )
            else result
        )

        with self._call_watch_lock:
            self._call_microphone_last_result = (
                value
            )

        return value


    def _ensure_call_microphone_enabled_impl(
        self,
        *,
        wait_timeout=60,
        automatic=False,
    ):
        """Garantiza micro activo dentro del worker WhatsApp.

        No es un toggle ciego.

        WhatsAppConnector solo pulsa cuando observa
        inequívocamente mic-unmute y después verifica
        el estado ENABLED.
        """
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        result = (
            connector
            .ensure_call_microphone_enabled()
        )

        normalized = (
            dict(result)
            if isinstance(
                result,
                dict,
            )
            else {
                "ready": False,
                "changed": False,
                "reason":
                    "MICROPHONE_RESULT_INVALID",
                "raw_result":
                    result,
            }
        )

        normalized[
            "automatic"
        ] = bool(
            automatic
        )

        return (
            self
            ._remember_call_microphone_result(
                normalized
            )
        )


    def ensure_call_microphone_enabled(
        self,
        *,
        wait_timeout=60,
    ):
        """API pública serializada para garantizar micro activo."""
        return self._run_serialized(
            self._ensure_call_microphone_enabled_impl,
            wait_timeout=wait_timeout,
            automatic=False,
        )


    @staticmethod
    def _call_observation_enters_active(
        observation,
    ):
        """Detecta entrada real en fase ACTIVE.

        Casos admitidos:
        - primera observación ya ACTIVE;
        - transición desde cualquier fase no ACTIVE;
        - CALL_REPLACED cuyo nuevo active ya es ACTIVE.

        Permanecer ACTIVE no vuelve a disparar la política.
        """
        if observation is None:
            return False

        active = getattr(
            observation,
            "active",
            None,
        )

        if (
            active is None
            or not bool(
                getattr(
                    active,
                    "present",
                    False,
                )
            )
            or getattr(
                active,
                "phase",
                None,
            )
            != WHATSAPP_CALL_PHASE_ACTIVE
        ):
            return False

        if (
            getattr(
                observation,
                "change_type",
                None,
            )
            == CALL_OBSERVATION_REPLACED
        ):
            return True

        previous = getattr(
            observation,
            "previous",
            None,
        )

        if previous is None:
            return True

        return (
            getattr(
                previous,
                "phase",
                None,
            )
            != WHATSAPP_CALL_PHASE_ACTIVE
        )


    def _maybe_ensure_active_call_microphone(
        self,
        observation,
    ):
        """Aplica política default al entrar en ACTIVE.

        Este método se ejecuta ya dentro del worker único.
        Un fallo de micro nunca bloquea reconciliación ni
        persistencia del lifecycle de la llamada.
        """
        if not (
            self
            ._call_observation_enters_active(
                observation
            )
        ):
            return None

        active = getattr(
            observation,
            "active",
            None,
        )

        try:
            connector = self._connector

            if connector is None:
                raise RuntimeError(
                    "WhatsAppConnector no disponible"
                )

            result = (
                connector
                .ensure_call_microphone_enabled()
            )

            normalized = (
                dict(result)
                if isinstance(
                    result,
                    dict,
                )
                else {
                    "ready": False,
                    "changed": False,
                    "reason":
                        "MICROPHONE_RESULT_INVALID",
                    "raw_result":
                        result,
                }
            )

            normalized[
                "automatic"
            ] = True

            normalized[
                "trigger"
            ] = (
                "CALL_ENTERED_ACTIVE"
            )

            normalized[
                "provider_call_id"
            ] = getattr(
                active,
                "provider_call_id",
                None,
            )

            normalized[
                "external_call_key"
            ] = getattr(
                active,
                "external_call_key",
                None,
            )

            normalized[
                "participant_phone"
            ] = getattr(
                active,
                "participant_phone",
                None,
            )

        except Exception as exc:
            normalized = {
                "ready": False,
                "changed": False,
                "automatic": True,
                "trigger":
                    "CALL_ENTERED_ACTIVE",
                "reason":
                    "MICROPHONE_ENSURE_ERROR",
                "error_type":
                    type(
                        exc
                    ).__name__,
                "message":
                    str(
                        exc
                    ),
                "provider_call_id":
                    getattr(
                        active,
                        "provider_call_id",
                        None,
                    ),
                "external_call_key":
                    getattr(
                        active,
                        "external_call_key",
                        None,
                    ),
                "participant_phone":
                    getattr(
                        active,
                        "participant_phone",
                        None,
                    ),
            }

        return (
            self
            ._remember_call_microphone_result(
                normalized
            )
        )


    def _observe_and_sync_call_impl(
        self,
        *,
        wait_timeout=60,
    ):
        """
        Observa y reconcilia una llamada actionable.

        read_call_snapshot() y observe_call() siguen siendo
        rutas pasivas sin persistencia.
        """
        observation = (
            self._observe_call_impl(
                wait_timeout=wait_timeout,
            )
        )

        # Política UX independiente de la persistencia:
        # al entrar realmente en ACTIVE garantizamos una vez
        # que el micrófono no esté silenciado.
        #
        # Si WhatsApp ya lo tiene activo:
        #     0 clicks.
        #
        # Si está MUTED:
        #     1 click exacto sobre mic-unmute + verificación.
        #
        # Si falla:
        #     queda diagnóstico, pero la llamada continúa
        #     reconciliándose normalmente.
        self._maybe_ensure_active_call_microphone(
            observation
        )

        if not (
            self._call_realtime_service
            .enabled
        ):
            return (
                self
                ._call_realtime_service
                .process_observation(
                    observation,
                    observed_at=None,
                )
            )

        observed_at = (
            self._call_observed_at()
        )

        return (
            self
            ._call_realtime_service
            .process_observation(
                observation,
                observed_at=(
                    observed_at
                ),
            )
        )


    def observe_and_sync_call(
        self,
        *,
        wait_timeout=60,
    ):
        """
        API serializada de incorporación realtime de llamadas.
        """
        return self._run_serialized(
            self._observe_and_sync_call_impl,
            wait_timeout=wait_timeout,
        )


    def set_call_watch_callback(
        self,
        on_change,
    ):
        if (
            on_change is not None
            and not callable(
                on_change
            )
        ):
            raise TypeError(
                "on_change debe ser callable o None"
            )

        with self._call_watch_lock:
            self._call_watch_on_change = (
                on_change
            )

        return True


    @property
    def call_watch_last_error(
        self,
    ):
        with self._call_watch_lock:
            return (
                self._call_watch_last_error
            )


    @property
    def call_watch_last_result(
        self,
    ):
        with self._call_watch_lock:
            return (
                self._call_watch_last_result
            )


    @property
    def call_watch_running(
        self,
    ):
        with self._call_watch_lock:
            thread = (
                self._call_watch_thread
            )

            return bool(
                thread
                and thread.is_alive()
            )


    def _call_watch_loop(
        self,
        *,
        stop_event,
        interval_seconds,
        wait_timeout,
    ):
        """
        Supervisor realtime de llamadas.

        Nunca toca connector/browser directamente.
        Toda lectura WhatsApp pasa por
        observe_and_sync_call() -> _run_serialized().
        """
        while not stop_event.is_set():
            try:
                result = (
                    self.observe_and_sync_call(
                        wait_timeout=(
                            wait_timeout
                        ),
                    )
                )

                with self._call_watch_lock:
                    self._call_watch_last_result = (
                        result
                    )

                    on_change = (
                        self._call_watch_on_change
                    )

                observation = getattr(
                    result,
                    "observation",
                    None,
                )

                changed = bool(
                    getattr(
                        observation,
                        "changed",
                        False,
                    )
                )

                if (
                    changed
                    and callable(
                        on_change
                    )
                ):
                    try:
                        on_change(
                            result
                        )

                    except Exception as exc:
                        # El consumidor jamás puede matar
                        # la vigilancia del transporte.
                        with self._call_watch_lock:
                            self._call_watch_last_error = {
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
                            }

            except Exception as exc:
                # Un fallo transitorio de WhatsApp,
                # Selenium o persistencia no mata el watcher.
                with self._call_watch_lock:
                    self._call_watch_last_error = {
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

            # Despertar inmediato cuando se solicita stop.
            if stop_event.wait(
                interval_seconds
            ):
                break


    def start_call_watch(
        self,
        *,
        interval_seconds=0.25,
        wait_timeout=5,
        on_change=None,
    ):
        if (
            on_change is not None
            and not callable(
                on_change
            )
        ):
            raise TypeError(
                "on_change debe ser callable o None"
            )

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

        with self._call_watch_lock:
            self._call_watch_on_change = (
                on_change
            )

            current = (
                self._call_watch_thread
            )

            if (
                current is not None
                and current.is_alive()
            ):
                return current

            stop_event = (
                threading.Event()
            )

            self._call_watch_last_error = None
            self._call_watch_last_result = None

            thread = threading.Thread(
                target=(
                    self._call_watch_loop
                ),
                kwargs={
                    "stop_event":
                        stop_event,
                    "interval_seconds":
                        interval,
                    "wait_timeout":
                        effective_wait_timeout,
                },
                name=(
                    "whatsapp-call-watch"
                ),
                daemon=True,
            )

            self._call_watch_stop = (
                stop_event
            )

            self._call_watch_thread = (
                thread
            )

            thread.start()

            return thread


    def stop_call_watch(
        self,
        *,
        join_timeout=5,
    ):
        with self._call_watch_lock:
            thread = (
                self._call_watch_thread
            )

            stop_event = (
                self._call_watch_stop
            )

        if stop_event is not None:
            stop_event.set()

        if (
            thread is not None
            and thread.is_alive()
            and thread
            is not threading.current_thread()
        ):
            thread.join(
                timeout=max(
                    0,
                    float(
                        join_timeout
                    ),
                )
            )

        with self._call_watch_lock:
            if (
                self._call_watch_thread
                is thread
            ):
                self._call_watch_thread = None
                self._call_watch_stop = None

        return bool(
            thread is not None
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
            previous.last_provider_message_status
            != current.last_provider_message_status
        ):
            # El provider id puede permanecer idéntico mientras
            # WhatsApp avanza SENT -> DELIVERED -> READ.
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


    def _read_sidebar_chat_fingerprint_impl(
        self,
        *,
        wait_timeout=60,
    ):
        """Lee pasivamente el sidebar WhatsApp actual.

        No navega.
        No hace click.
        No modifica el baseline del watcher.
        No persiste.

        Permite que una nueva instancia Flet se hidrate aunque
        el watcher ya existiera antes de montar la vista.
        """
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        return (
            connector
            .get_sidebar_chat_fingerprint(
                viewport_only=True,
            )
        )


    def read_sidebar_chat_fingerprint(
        self,
        *,
        wait_timeout=60,
    ):
        """API pública serializada del snapshot lateral."""
        return self._run_serialized(
            self._read_sidebar_chat_fingerprint_impl,
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

        # ==================================================
        # REALTIME SIDEBAR
        # ==================================================
        #
        # Esta lectura:
        # - no navega;
        # - no hace click;
        # - no desplaza WhatsApp;
        # - no persiste;
        # - no cambia el chat activo.
        #
        # La primera iteración crea únicamente el baseline.
        sidebar_current = (
            self._connector
            .get_sidebar_chat_fingerprint(
                viewport_only=True,
            )
        )

        sidebar_previous = (
            self._sidebar_chat_fingerprint
        )

        sidebar_initial_available = False

        if sidebar_previous is None:
            sidebar_changes = []
            sidebar_change_type = (
                "SIDEBAR_INITIAL"
            )
            sidebar_changed = False

            # El primer fingerprint no representa un delta,
            # pero sí contiene estado útil que el consumidor
            # necesita hidratar: preview, hora y unread.
            sidebar_initial_available = bool(
                sidebar_current
            )
        else:
            sidebar_changes = (
                diff_sidebar_chat_fingerprints(
                    sidebar_previous,
                    sidebar_current,
                )
            )

            sidebar_changed = bool(
                sidebar_changes
            )

            sidebar_change_type = (
                "SIDEBAR_CHANGED"
                if sidebar_changed
                else "SIDEBAR_UNCHANGED"
            )

        self._sidebar_chat_fingerprint = (
            sidebar_current
        )

        result[
            "sidebar_previous"
        ] = sidebar_previous

        result[
            "sidebar"
        ] = sidebar_current

        result[
            "sidebar_changes"
        ] = sidebar_changes

        result[
            "sidebar_changed"
        ] = sidebar_changed

        result[
            "sidebar_change_type"
        ] = sidebar_change_type

        result[
            "sidebar_initial_available"
        ] = bool(
            sidebar_initial_available
        )

        # Descubrimiento pasivo de conversaciones telefónicas.
        #
        # INVARIANTE:
        # esta fase trabaja exclusivamente sobre el fingerprint
        # ya leído del sidebar. No abre chats, no hace click,
        # no desplaza WhatsApp y no abre perfiles.
        sidebar_discoveries = []

        discovery_candidates = []

        if sidebar_previous is None:
            # Al arrancar podemos encontrar ya un mensaje nuevo
            # esperando. No exigimos APPEARED porque el primer
            # fingerprint es baseline.
            discovery_candidates = [
                {
                    "change_type":
                        "SIDEBAR_INITIAL",
                    "identity":
                        identity,
                    "current":
                        current,
                }
                for identity, current
                in sidebar_current.items()
            ]
        else:
            discovery_candidates = list(
                sidebar_changes
            )

        for candidate in discovery_candidates:
            if not isinstance(
                candidate,
                dict,
            ):
                continue

            current_sidebar = candidate.get(
                "current"
            )

            if not isinstance(
                current_sidebar,
                dict,
            ):
                continue

            if bool(
                current_sidebar.get(
                    "ambiguous"
                )
            ):
                continue

            try:
                candidate_unread = max(
                    0,
                    int(
                        current_sidebar.get(
                            "unread_count"
                        )
                        or 0
                    ),
                )
            except Exception:
                candidate_unread = 0

            # Solo descubrimos automáticamente trabajo pendiente.
            # Una fila histórica visible sin unread puede ser mera
            # virtualización y no justifica persistencia nueva.
            if candidate_unread <= 0:
                continue

            identity = str(
                candidate.get(
                    "identity"
                )
                or current_sidebar.get(
                    "identity"
                )
                or ""
            ).strip()

            if not identity:
                continue

            try:
                discovery = (
                    self.communication_service
                    .discover_whatsapp_sidebar_thread(
                        identity=identity,
                        display_name=(
                            current_sidebar.get(
                                "display_name"
                            )
                        ),
                        preview=(
                            current_sidebar.get(
                                "preview"
                            )
                        ),
                        primary_detail=(
                            current_sidebar.get(
                                "primary_detail"
                            )
                        ),
                        unread_count=(
                            candidate_unread
                        ),
                    )
                )

            except Exception as exc:
                sidebar_discoveries.append(
                    {
                        "identity":
                            identity,
                        "discovered":
                            False,
                        "created":
                            False,
                        "reused":
                            False,
                        "reason":
                            "DISCOVERY_ERROR",
                        "error_type":
                            type(
                                exc
                            ).__name__,
                    }
                )
                continue

            if not isinstance(
                discovery,
                dict,
            ):
                continue

            thread = discovery.get(
                "thread"
            )

            thread_id = getattr(
                thread,
                "id",
                None,
            )

            sidebar_discoveries.append(
                {
                    "identity":
                        identity,
                    "discovered":
                        bool(
                            discovery.get(
                                "discovered"
                            )
                        ),
                    "created":
                        bool(
                            discovery.get(
                                "created"
                            )
                        ),
                    "reused":
                        bool(
                            discovery.get(
                                "reused"
                            )
                        ),
                    "reason":
                        discovery.get(
                            "reason"
                        ),
                    "thread_id":
                        (
                            int(thread_id)
                            if thread_id
                            not in (
                                None,
                                "",
                            )
                            else None
                        ),
                    "phone":
                        discovery.get(
                            "phone"
                        ),
                    "external_thread_key":
                        discovery.get(
                            "external_thread_key"
                        ),
                }
            )

        result[
            "sidebar_discoveries"
        ] = sidebar_discoveries

        # changed representa ahora cualquier modificación
        # observable que interese al consumidor del watcher.
        #
        # Mantiene compatibilidad:
        # - change_type continúa describiendo el chat activo;
        # - sidebar_* describe exclusivamente la bandeja.
        result["changed"] = bool(
            result.get(
                "changed"
            )
            or sidebar_changed
            or sidebar_initial_available
        )

        active_change_type = str(
            result.get(
                "change_type"
            )
            or ""
        ).strip()

        initial_desired_thread_id = None

        if (
            active_change_type
            == "INITIAL"
        ):
            # INITIAL continúa siendo baseline por defecto.
            #
            # Única excepción:
            # existe una selección CRM explícita pendiente/
            # vigente. En ese caso podemos intentar recuperar
            # la ventana ya materializada, pero únicamente si
            # la identidad activa resuelve después al mismo
            # thread solicitado.
            with self._desired_thread_lock:
                initial_desired_thread_id = (
                    self._desired_thread_id
                )

            if initial_desired_thread_id in (
                None,
                "",
            ):
                return result

        elif (
            active_change_type
            == "MESSAGE_WINDOW_CHANGED"
        ):
            previous_window = (
                result.get(
                    "previous"
                )
            )

            current_window = (
                result.get(
                    "current"
                )
            )

            # Una contracción puede ser simple
            # virtualización del DOM y no implica contenido
            # nuevo.
            #
            # Una expansión sí debe recuperar toda la ventana:
            # los nodos recién materializados pueden estar ANTES
            # del último provider id ya conocido.
            if (
                previous_window is None
                or current_window is None
                or int(
                    getattr(
                        current_window,
                        "visible_message_count",
                        0,
                    )
                    or 0
                )
                <= int(
                    getattr(
                        previous_window,
                        "visible_message_count",
                        0,
                    )
                    or 0
                )
            ):
                return result

            result[
                "message_window_expanded"
            ] = True

        elif (
            active_change_type
            not in (
                "MESSAGE_CHANGED",
                "CHAT_CHANGED",
            )
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

        if (
            active_change_type
            == "INITIAL"
        ):
            # La selección puede haber cambiado mientras
            # resolvíamos la identidad. Revalidamos el destino
            # bajo el mismo lock utilizado por el routing.
            with self._desired_thread_lock:
                current_desired_thread_id = (
                    self._desired_thread_id
                )

            try:
                initial_selection_matches = (
                    int(thread_id)
                    == int(
                        initial_desired_thread_id
                    )
                    == int(
                        current_desired_thread_id
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                initial_selection_matches = False

            if not initial_selection_matches:
                return result

            result[
                "initial_selection_recovery"
            ] = True

        after_provider_message_id = None

        if (
            result.get(
                "change_type"
            )
            == "MESSAGE_CHANGED"
            and result.get(
                "previous"
            )
            is not None
        ):
            after_provider_message_id = (
                result[
                    "previous"
                ].last_provider_message_id
            )

        # CHAT_CHANGED es deliberadamente FULL.
        #
        # Al abrir una conversación WhatsApp puede materializar
        # mensajes que faltan ANTES del último provider id que
        # ya existe en la base de datos.
        #
        # Usar ese último provider id como checkpoint provoca
        # un hueco irreversible en la ventana:
        #
        #   [29 mensajes nuevos/faltantes]
        #   [último provider ya persistido] <- anchor
        #
        # El sync incremental empezaría DESPUÉS del anchor y
        # nunca vería esos 29 mensajes anteriores.
        #
        # La ventana está acotada por sync_limit y la
        # persistencia por provider_message_id es idempotente,
        # por lo que FULL es el contrato seguro al cambiar de
        # conversación.

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
                    after_provider_message_id=(
                        after_provider_message_id
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


    def set_active_chat_watch_callback(
        self,
        on_change,
    ):
        if (
            on_change is not None
            and not callable(
                on_change
            )
        ):
            raise TypeError(
                "on_change debe ser callable o None"
            )

        with self._active_chat_watch_lock:
            self._active_chat_watch_on_change = (
                on_change
            )

        return True


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

                with self._active_chat_watch_lock:
                    on_change = (
                        self._active_chat_watch_on_change
                    )

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
        interval_seconds=0.5,
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
            self._active_chat_watch_on_change = (
                on_change
            )

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

    def _download_document_impl(
        self,
        *,
        thread_id,
        provider_message_id,
        watch_folder_id=None,
        wait_timeout=60,
        routing_timeout=15,
        download_timeout=30,
    ):
        """Descarga un documento WhatsApp a una carpeta vigilada.

        Contrato:
        - verifica fuertemente el thread CRM;
        - solo descarga dentro de una carpeta activa de
          Bandeja Documental;
        - por defecto usa la carpeta Descargas vigilada;
        - no importa directamente;
        - no duplica dedupe, SHA256 ni persistencia documental.
        """
        thread = (
            self._prepare_verified_outbound_impl(
                thread_id=thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=(
                    routing_timeout
                ),
            )
        )

        if watch_folder_id in (
            None,
            "",
        ):
            watch_folder = (
                document_inbox_watch_service
                .ensure_default_downloads_watch_folder()
            )
        else:
            watch_folder = (
                document_inbox_watch_service
                .get_watch_folder(
                    int(
                        watch_folder_id
                    )
                )
            )

        if not int(
            watch_folder.get(
                "is_active"
            )
            or 0
        ):
            raise ValueError(
                "La carpeta de destino "
                "no está activa en Bandeja Documental"
            )

        destination = Path(
            watch_folder[
                "folder_path"
            ]
        ).expanduser().resolve()

        if (
            not destination.exists()
            or not destination.is_dir()
        ):
            raise ValueError(
                "La carpeta vigilada de destino "
                "no existe"
            )

        connector = (
            self._build_connector()
        )

        result = (
            connector
            .download_visible_document(
                provider_message_id,
                download_dir=(
                    destination
                ),
                timeout=(
                    download_timeout
                ),
            )
        )

        return {
            **result,
            "thread_id": int(
                thread.id
            ),
            "client_id": (
                int(
                    thread.client_id
                )
                if thread.client_id
                is not None
                else None
            ),
            "watch_folder_id": int(
                watch_folder[
                    "id"
                ]
            ),
            "watch_folder_name": (
                watch_folder.get(
                    "name"
                )
            ),
            "watch_folder_path": str(
                destination
            ),
            "document_inbox_watch": True,
        }

    def download_document(
        self,
        *,
        thread_id,
        provider_message_id,
        watch_folder_id=None,
        wait_timeout=60,
        routing_timeout=15,
        download_timeout=30,
    ):
        return self._run_serialized(
            self._download_document_impl,
            thread_id=thread_id,
            provider_message_id=(
                provider_message_id
            ),
            watch_folder_id=(
                watch_folder_id
            ),
            wait_timeout=wait_timeout,
            routing_timeout=(
                routing_timeout
            ),
            download_timeout=(
                download_timeout
            ),
        )

    def _download_image_impl(
        self,
        *,
        thread_id,
        provider_message_id,
        watch_folder_id=None,
        wait_timeout=60,
        routing_timeout=15,
        download_timeout=30,
    ):
        """Descarga una imagen WhatsApp a carpeta vigilada."""
        thread = (
            self._prepare_verified_outbound_impl(
                thread_id=thread_id,
                wait_timeout=wait_timeout,
                routing_timeout=(
                    routing_timeout
                ),
            )
        )

        if watch_folder_id in (
            None,
            "",
        ):
            watch_folder = (
                document_inbox_watch_service
                .ensure_default_downloads_watch_folder()
            )
        else:
            watch_folder = (
                document_inbox_watch_service
                .get_watch_folder(
                    int(
                        watch_folder_id
                    )
                )
            )

        if not int(
            watch_folder.get(
                "is_active"
            )
            or 0
        ):
            raise ValueError(
                "La carpeta de destino "
                "no está activa en Bandeja Documental"
            )

        destination = Path(
            watch_folder[
                "folder_path"
            ]
        ).expanduser().resolve()

        if (
            not destination.exists()
            or not destination.is_dir()
        ):
            raise ValueError(
                "La carpeta vigilada de destino "
                "no existe"
            )

        connector = (
            self._build_connector()
        )

        result = (
            connector
            .download_visible_image(
                provider_message_id,
                download_dir=(
                    destination
                ),
                timeout=(
                    download_timeout
                ),
            )
        )

        return {
            **result,
            "thread_id":
                int(
                    thread.id
                ),
            "client_id":
                (
                    int(
                        thread.client_id
                    )
                    if thread.client_id
                    is not None
                    else None
                ),
            "watch_folder_id":
                int(
                    watch_folder[
                        "id"
                    ]
                ),
            "watch_folder_name":
                watch_folder.get(
                    "name"
                ),
            "watch_folder_path":
                str(
                    destination
                ),
            "document_inbox_watch":
                True,
        }


    def download_image(
        self,
        *,
        thread_id,
        provider_message_id,
        watch_folder_id=None,
        wait_timeout=60,
        routing_timeout=15,
        download_timeout=30,
    ):
        return self._run_serialized(
            self._download_image_impl,
            thread_id=thread_id,
            provider_message_id=(
                provider_message_id
            ),
            watch_folder_id=(
                watch_folder_id
            ),
            wait_timeout=wait_timeout,
            routing_timeout=(
                routing_timeout
            ),
            download_timeout=(
                download_timeout
            ),
        )


    def _download_today_documents_impl(
        self,
        *,
        watch_folder_id=None,
        wait_timeout=60,
        download_timeout=30,
        max_documents=100,
    ):
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        if watch_folder_id in (
            None,
            "",
        ):
            watch_folder = (
                document_inbox_watch_service
                .ensure_default_downloads_watch_folder()
            )

        else:
            watch_folder = (
                document_inbox_watch_service
                .get_watch_folder(
                    int(
                        watch_folder_id
                    )
                )
            )

        if not int(
            watch_folder.get(
                "is_active"
            )
            or 0
        ):
            raise ValueError(
                "La carpeta vigilada "
                "seleccionada está inactiva"
            )

        target_dir = Path(
            watch_folder[
                "folder_path"
            ]
        ).expanduser()

        if (
            not target_dir.exists()
            or not target_dir.is_dir()
        ):
            raise ValueError(
                "La carpeta vigilada "
                "no existe físicamente"
            )

        result = (
            connector
            .download_today_documents_from_media_hub(
                download_dir=target_dir,
                timeout=download_timeout,
                max_documents=max_documents,
            )
        )

        return {
            **dict(
                result
                or {}
            ),

            "watch_folder_id":
                int(
                    watch_folder[
                        "id"
                    ]
                ),

            "watch_folder_name":
                watch_folder.get(
                    "name"
                ),

            "watch_folder_path":
                str(
                    target_dir.resolve()
                ),

            "document_inbox_watch":
                True,
        }


    def download_today_documents(
        self,
        *,
        watch_folder_id=None,
        wait_timeout=60,
        download_timeout=30,
        max_documents=100,
    ):
        return self._run_serialized(
            self._download_today_documents_impl,
            watch_folder_id=watch_folder_id,
            wait_timeout=wait_timeout,
            download_timeout=download_timeout,
            max_documents=max_documents,
        )


    def _download_today_images_impl(
        self,
        *,
        watch_folder_id=None,
        wait_timeout=60,
        download_timeout=30,
        max_images=100,
    ):
        connector = (
            self._ensure_ready_impl(
                wait_timeout=wait_timeout,
            )
        )

        if watch_folder_id in (
            None,
            "",
        ):
            watch_folder = (
                document_inbox_watch_service
                .ensure_default_downloads_watch_folder()
            )

        else:
            watch_folder = (
                document_inbox_watch_service
                .get_watch_folder(
                    int(
                        watch_folder_id
                    )
                )
            )

        if not int(
            watch_folder.get(
                "is_active"
            )
            or 0
        ):
            raise ValueError(
                "La carpeta vigilada "
                "seleccionada está inactiva"
            )

        target_dir = Path(
            watch_folder[
                "folder_path"
            ]
        ).expanduser()

        if (
            not target_dir.exists()
            or not target_dir.is_dir()
        ):
            raise ValueError(
                "La carpeta vigilada "
                "no existe físicamente"
            )

        result = (
            connector
            .download_today_images_from_media_hub(
                download_dir=target_dir,
                timeout=download_timeout,
                max_images=max_images,
            )
        )

        return {
            **dict(
                result
                or {}
            ),

            "watch_folder_id":
                int(
                    watch_folder[
                        "id"
                    ]
                ),

            "watch_folder_name":
                watch_folder.get(
                    "name"
                ),

            "watch_folder_path":
                str(
                    target_dir.resolve()
                ),

            "document_inbox_watch":
                True,
        }


    def download_today_images(
        self,
        *,
        watch_folder_id=None,
        wait_timeout=60,
        download_timeout=30,
        max_images=100,
    ):
        return self._run_serialized(
            self._download_today_images_impl,
            watch_folder_id=watch_folder_id,
            wait_timeout=wait_timeout,
            download_timeout=download_timeout,
            max_images=max_images,
        )


    def _close_impl(
        self,
    ):
        connector = self._connector

        if connector is None:
            return False

        # El connector conserva BrowserSession/browser cuando
        # su shutdown no puede completarse.
        #
        # El runtime debe respetar ese ownership:
        # no puede olvidar el único controlador de una sesión
        # que potencialmente continúa viva.
        closed = bool(
            connector.close()
        )

        if not closed:
            return False

        self._connector = None
        self._outbound_service = None
        self._sync_service = None
        self._active_chat_fingerprint = None
        self._sidebar_chat_fingerprint = None
        self._call_observation_tracker.reset()

        with self._call_watch_lock:
            self._call_microphone_last_result = None

        return True

    def close(
        self,
    ):
        # Impedimos nuevas observaciones antes de cerrar
        # connector y executor. Si una observación estaba en
        # curso, la serialización garantiza que termine antes
        # de que _close_impl use el mismo worker.
        self.stop_call_watch()
        self.stop_active_chat_watch()

        result = self._run_serialized(
            self._close_impl
        )

        # Si todavía existe connector después del intento,
        # el cierre no se completó.
        #
        # Conservamos también el executor porque constituye
        # el único worker autorizado para volver a actuar sobre
        # esa sesión persistente y permite un retry gobernado.
        if (
            self._connector is not None
            and not result
        ):
            return False

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

        self._clear_verified_send_route()

        return result

"""
Sesión gobernada sobre la factoría SeleniumBase/CDP existente.

Primera fase del adapter:

- identidad lógica;
- startup;
- estado técnico;
- health;
- snapshot;
- historial de transiciones;
- profile resolution inyectable.

Deliberadamente NO implementa todavía:
- detach;
- kill;
- threads;
- runtime de watchers.

El shutdown CLOSE utiliza una topología owner-aware validada
sobre SeleniumBase 4.47.1 / sb_cdp.Chrome en Windows.

Ese cierre depende de capacidades internas observadas de
SeleniumBase/CDP. Por ello la compatibilidad se valida antes
de destruir recursos y cualquier cambio incompatible deberá
producir un error Python diagnosticable, nunca un fallback
silencioso a ``driver.stop()``.

No contiene lógica específica de WhatsApp, Mercurio ni DEHú.
"""

import asyncio
from uuid import uuid4

from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionConfigurationError,
    BrowserSessionHealth,
    BrowserSessionIdentity,
    BrowserSessionLifecycleError,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserSessionTransition,
    BrowserShutdownMode,
    BrowserShutdownResult,
)
from backend.automation.browser_session import (
    start_seleniumbase_chrome,
)


def _default_session_id():
    return (
        "browser-"
        + uuid4().hex
    )


class SeleniumBaseBrowserSession:
    """
    Primera implementación gobernada de una sesión SeleniumBase.

    La creación física continúa delegándose íntegramente en
    ``start_seleniumbase_chrome``.

    Por tanto, esta clase NO crea ``sb_cdp.Chrome`` directamente.

    ``browser_factory`` y ``profile_resolver`` son inyectables
    para permitir tests sin abrir Chrome real.
    """

    def __init__(
        self,
        *,
        config,
        browser_factory=None,
        profile_resolver=None,
        session_id_factory=None,
    ):
        if not isinstance(
            config,
            BrowserSessionConfig,
        ):
            raise BrowserSessionConfigurationError(
                "config debe ser BrowserSessionConfig"
            )

        self.config = config

        self._browser_factory = (
            browser_factory
            or start_seleniumbase_chrome
        )

        if not callable(
            self._browser_factory
        ):
            raise BrowserSessionConfigurationError(
                "browser_factory debe ser callable"
            )

        if (
            profile_resolver is not None
            and not callable(
                profile_resolver
            )
        ):
            raise BrowserSessionConfigurationError(
                "profile_resolver debe ser callable o None"
            )

        self._profile_resolver = (
            profile_resolver
        )

        self._session_id_factory = (
            session_id_factory
            or _default_session_id
        )

        if not callable(
            self._session_id_factory
        ):
            raise BrowserSessionConfigurationError(
                "session_id_factory debe ser callable"
            )

        session_id = (
            self._session_id_factory()
        )

        self.identity = (
            BrowserSessionIdentity.from_config(
                session_id=session_id,
                config=self.config,
            )
        )

        self._browser = None

        self._state = (
            BrowserSessionState.CREATED
        )

        self._last_error = ""

        self._last_shutdown_result = None

        self._transition_history = []

    @property
    def browser(
        self,
    ):
        """
        Browser físico actualmente asociado.

        Solo los adapters/connectors autorizados deberán
        depender de este objeto.
        """
        return self._browser

    @property
    def state(
        self,
    ):
        return self._state

    @property
    def transition_history(
        self,
    ):
        return tuple(
            self._transition_history
        )

    def _transition(
        self,
        new_state,
        *,
        reason="",
        detail="",
    ):
        transition = (
            BrowserSessionTransition(
                previous_state=self._state,
                current_state=new_state,
                reason=reason,
                detail=detail,
            )
        )

        self._state = (
            transition.current_state
        )

        self._transition_history.append(
            transition
        )

        return transition

    def _resolve_profile_dir(
        self,
    ):
        profile_key = (
            self.config.profile_key
        )

        if profile_key is None:
            return None

        if self._profile_resolver is None:
            raise BrowserSessionConfigurationError(
                "La sesión declara profile_key pero "
                "no dispone de profile_resolver"
            )

        resolved = (
            self._profile_resolver(
                profile_key
            )
        )

        if resolved is None:
            raise BrowserSessionConfigurationError(
                "profile_resolver no devolvió una ruta"
            )

        resolved_text = str(
            resolved
        ).strip()

        if not resolved_text:
            raise BrowserSessionConfigurationError(
                "profile_resolver devolvió una ruta vacía"
            )

        return resolved

    def _browser_factory_kwargs(
        self,
    ):
        kwargs = {
            "headless":
                self.config.headless,
        }

        profile_dir = (
            self._resolve_profile_dir()
        )

        if profile_dir is not None:
            kwargs[
                "user_data_dir"
            ] = profile_dir

        return kwargs

    def start(
        self,
    ):
        """
        Inicia la sesión técnica.

        Semántica actual:

        CREATED
            -> STARTING
            -> READY

        Si la factoría falla:

        CREATED
            -> STARTING
            -> FAILED

        READY es idempotente:
        un segundo ``start()`` devuelve el mismo browser.

        Todavía no se define restart/recovery desde FAILED.
        """

        if (
            self._state
            == BrowserSessionState.READY
            and self._browser is not None
        ):
            return self._browser

        if (
            self._state
            != BrowserSessionState.CREATED
        ):
            raise BrowserSessionLifecycleError(
                "No se puede iniciar una sesión "
                f"desde estado {self._state.value}"
            )

        # Resolver configuración física antes de mutar
        # lifecycle. Un profile_resolver ausente es un
        # problema de configuración, no un fallo de Chrome.
        kwargs = (
            self._browser_factory_kwargs()
        )

        self._transition(
            BrowserSessionState.STARTING,
            reason="start_requested",
        )

        try:
            browser = (
                self._browser_factory(
                    **kwargs
                )
            )

            if browser is None:
                raise RuntimeError(
                    "browser_factory devolvió None"
                )

        except Exception as exc:
            self._browser = None

            self._last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            self._transition(
                BrowserSessionState.FAILED,
                reason="start_failed",
                detail=self._last_error,
            )

            raise BrowserSessionLifecycleError(
                "No se pudo iniciar la sesión de navegador"
            ) from exc

        self._browser = browser
        self._last_error = ""

        self._transition(
            BrowserSessionState.READY,
            reason="browser_created",
        )

        return self._browser

    @staticmethod
    def _normalize_shutdown_mode(
        mode,
    ):
        if isinstance(
            mode,
            BrowserShutdownMode,
        ):
            return mode

        try:
            return BrowserShutdownMode(
                str(
                    mode
                    or ""
                )
                .strip()
                .upper()
            )
        except ValueError as exc:
            raise BrowserSessionConfigurationError(
                f"shutdown mode inválido: {mode!r}"
            ) from exc

    @staticmethod
    def _require_shutdown_attribute(
        obj,
        attribute_name,
        *,
        owner_label,
    ):
        """
        Exige una capacidad necesaria para el shutdown
        owner-aware.

        Estos guards aíslan cambios de layout interno de
        SeleniumBase y convierten una incompatibilidad en
        BrowserSessionLifecycleError diagnosticable.
        """

        if obj is None:
            raise BrowserSessionLifecycleError(
                "Shutdown topology incompatible: "
                f"{owner_label} no está disponible"
            )

        if not hasattr(
            obj,
            attribute_name,
        ):
            raise BrowserSessionLifecycleError(
                "Shutdown topology incompatible: "
                f"{owner_label} no expone "
                f"{attribute_name!r}"
            )

        return getattr(
            obj,
            attribute_name,
        )

    @classmethod
    def _validate_shutdown_topology(
        cls,
        browser,
    ):
        """
        Valida únicamente las capacidades estructurales
        mínimas necesarias para CLOSE.

        No ejecuta shutdown ni altera recursos.
        """

        driver = (
            cls._require_shutdown_attribute(
                browser,
                "driver",
                owner_label="browser",
            )
        )

        root_connection = (
            cls._require_shutdown_attribute(
                driver,
                "connection",
                owner_label="driver",
            )
        )

        process = (
            cls._require_shutdown_attribute(
                driver,
                "_process",
                owner_label="driver",
            )
        )

        if root_connection is not None:
            aclose = getattr(
                root_connection,
                "aclose",
                None,
            )

            if not callable(
                aclose
            ):
                raise BrowserSessionLifecycleError(
                    "Shutdown topology incompatible: "
                    "driver.connection no expone "
                    "aclose()"
                )

        if process is not None:
            transport = getattr(
                process,
                "_transport",
                None,
            )

            if transport is None:
                raise BrowserSessionLifecycleError(
                    "Shutdown topology incompatible: "
                    "Chrome process no expone _transport"
                )

            process_loop = getattr(
                transport,
                "_loop",
                None,
            )

            if process_loop is None:
                raise BrowserSessionLifecycleError(
                    "Shutdown topology incompatible: "
                    "Chrome process transport no expone "
                    "_loop"
                )

            if not callable(
                getattr(
                    process,
                    "wait",
                    None,
                )
            ):
                raise BrowserSessionLifecycleError(
                    "Shutdown topology incompatible: "
                    "Chrome process no expone wait()"
                )

        return (
            driver,
            root_connection,
            process,
        )

    @staticmethod
    def _connection_owner_loop(
        connection,
    ):
        if connection is None:
            return None

        websocket = getattr(
            connection,
            "websocket",
            None,
        )

        if websocket is None:
            return None

        return getattr(
            websocket,
            "loop",
            None,
        )

    @staticmethod
    def _connection_is_opened(
        connection,
    ):
        return (
            connection is not None
            and getattr(
                connection,
                "websocket",
                None,
            )
            is not None
        )

    @staticmethod
    def _collect_child_connections(
        browser,
        driver,
    ):
        """
        Devuelve conexiones de página/tab deduplicadas.

        La conexión browser-level ``driver.connection`` se
        gestiona separadamente y siempre se cierra al final.
        """

        root_connection = getattr(
            driver,
            "connection",
            None,
        )

        candidates = []

        def add(
            value,
        ):
            if value is not None:
                candidates.append(
                    value
                )

        add(
            getattr(
                browser,
                "page",
                None,
            )
        )

        add(
            getattr(
                driver,
                "page",
                None,
            )
        )

        add(
            getattr(
                driver,
                "main_tab",
                None,
            )
        )

        try:
            targets = list(
                getattr(
                    driver,
                    "targets",
                    (),
                )
                or ()
            )
        except Exception:
            targets = []

        for target in targets:
            add(
                target
            )

        try:
            tabs = list(
                getattr(
                    driver,
                    "tabs",
                    (),
                )
                or ()
            )
        except Exception:
            tabs = []

        for tab in tabs:
            add(
                tab
            )

        unique = []
        seen = set()

        for connection in candidates:
            if (
                connection
                is root_connection
            ):
                continue

            identifier = id(
                connection
            )

            if identifier in seen:
                continue

            seen.add(
                identifier
            )

            unique.append(
                connection
            )

        return tuple(
            unique
        )

    @classmethod
    def _close_connection_on_owner(
        cls,
        connection,
    ):
        """
        Cierra una Connection/Tab en el loop propietario
        de su WebSocket.

        Esta secuencia evita ejecutar ``aclose()`` desde
        un event loop ajeno al recurso.
        """

        if not cls._connection_is_opened(
            connection
        ):
            return False

        owner = (
            cls._connection_owner_loop(
                connection
            )
        )

        if owner is None:
            raise BrowserSessionLifecycleError(
                "No se pudo resolver el owner loop "
                "de una conexión CDP abierta"
            )

        if owner.is_closed():
            raise BrowserSessionLifecycleError(
                "El owner loop de la conexión CDP "
                "ya está cerrado"
            )

        aclose = getattr(
            connection,
            "aclose",
            None,
        )

        if not callable(
            aclose
        ):
            raise BrowserSessionLifecycleError(
                "Shutdown topology incompatible: "
                "la conexión CDP abierta no expone "
                "aclose()"
            )

        owner.run_until_complete(
            aclose()
        )

        # Permitir que cancelaciones y callbacks derivados
        # del cierre se liquiden sobre el mismo owner.
        owner.run_until_complete(
            asyncio.sleep(
                0.05
            )
        )

        return True

    @staticmethod
    def _process_owner_loop(
        process,
    ):
        if process is None:
            return None

        transport = getattr(
            process,
            "_transport",
            None,
        )

        return getattr(
            transport,
            "_loop",
            None,
        )

    @classmethod
    def _terminate_process_on_owner(
        cls,
        process,
        *,
        timeout=5.0,
    ):
        """
        Termina y espera al asyncio.subprocess.Process
        utilizando el loop donde fue creado.
        """

        if process is None:
            return None

        owner = (
            cls._process_owner_loop(
                process
            )
        )

        if owner is None:
            raise BrowserSessionLifecycleError(
                "No se pudo resolver el owner loop "
                "del proceso Chrome"
            )

        if owner.is_closed():
            raise BrowserSessionLifecycleError(
                "El owner loop del proceso Chrome "
                "ya está cerrado"
            )

        async def terminate_and_wait():
            if (
                process.returncode
                is None
            ):
                process.terminate()

            try:
                return await asyncio.wait_for(
                    process.wait(),
                    timeout=timeout,
                )

            except asyncio.TimeoutError:
                process.kill()

                return await asyncio.wait_for(
                    process.wait(),
                    timeout=timeout,
                )

        return owner.run_until_complete(
            terminate_and_wait()
        )

    def shutdown(
        self,
        mode=BrowserShutdownMode.CLOSE,
    ):
        """
        Finaliza de forma gobernada la sesión.

        En esta fase únicamente se implementa CLOSE.

        Orden probado para sb_cdp.Chrome:

        1. cerrar conexiones Page/Tab en su owner loop;
        2. cerrar driver.connection en su owner loop;
        3. terminar Chrome y esperar process.wait()
           en el owner loop del subprocess;
        4. liberar la referencia browser;
        5. marcar la sesión CLOSED.

        Deliberadamente NO utiliza ``driver.stop()``.
        """

        mode = (
            self._normalize_shutdown_mode(
                mode
            )
        )

        if (
            mode
            != BrowserShutdownMode.CLOSE
        ):
            raise BrowserSessionLifecycleError(
                "Solo BrowserShutdownMode.CLOSE "
                "está implementado actualmente"
            )

        if (
            self._state
            == BrowserSessionState.CLOSED
        ):
            if (
                self._last_shutdown_result
                is not None
            ):
                return (
                    self._last_shutdown_result
                )

            return BrowserShutdownResult(
                mode=mode,
                state_before=(
                    BrowserSessionState.CLOSED
                ),
                state_after=(
                    BrowserSessionState.CLOSED
                ),
                control_released=True,
                browser_closed=True,
                process_terminated=True,
            )

        state_before = (
            self._state
        )

        # Una sesión nunca arrancada puede cerrarse
        # limpiamente sin tocar SeleniumBase.
        if (
            self._state
            == BrowserSessionState.CREATED
            and self._browser is None
        ):
            self._transition(
                BrowserSessionState.CLOSED,
                reason="shutdown_without_start",
            )

            result = BrowserShutdownResult(
                mode=mode,
                state_before=state_before,
                state_after=(
                    BrowserSessionState.CLOSED
                ),
                control_released=True,
                browser_closed=True,
                process_terminated=True,
            )

            self._last_shutdown_result = (
                result
            )

            return result

        if (
            self._state
            != BrowserSessionState.READY
        ):
            raise BrowserSessionLifecycleError(
                "No se puede cerrar una sesión "
                f"desde estado {self._state.value}"
            )

        browser = (
            self._browser
        )

        if browser is None:
            raise BrowserSessionLifecycleError(
                "Sesión READY sin browser asociado"
            )

        self._transition(
            BrowserSessionState.STOPPING,
            reason="shutdown_requested",
        )

        try:
            (
                driver,
                root_connection,
                process,
            ) = self._validate_shutdown_topology(
                browser
            )

            child_connections = (
                self._collect_child_connections(
                    browser,
                    driver,
                )
            )

            for connection in child_connections:
                if not self._connection_is_opened(
                    connection
                ):
                    continue

                self._close_connection_on_owner(
                    connection
                )

            if self._connection_is_opened(
                root_connection
            ):
                self._close_connection_on_owner(
                    root_connection
                )

            process_code = (
                self._terminate_process_on_owner(
                    process
                )
                if process is not None
                else None
            )

        except Exception as exc:
            self._last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            self._transition(
                BrowserSessionState.FAILED,
                reason="shutdown_failed",
                detail=self._last_error,
            )

            result = BrowserShutdownResult(
                mode=mode,
                state_before=state_before,
                state_after=(
                    BrowserSessionState.FAILED
                ),
                control_released=False,
                browser_closed=None,
                process_terminated=None,
                error=self._last_error,
            )

            self._last_shutdown_result = (
                result
            )

            return result

        self._browser = None
        self._last_error = ""

        self._transition(
            BrowserSessionState.CLOSED,
            reason="shutdown_completed",
            detail=(
                ""
                if process_code is None
                else (
                    "Chrome process returncode="
                    f"{process_code}"
                )
            ),
        )

        result = BrowserShutdownResult(
            mode=mode,
            state_before=state_before,
            state_after=(
                BrowserSessionState.CLOSED
            ),
            control_released=True,
            browser_closed=True,
            process_terminated=(
                True
                if process is not None
                else None
            ),
            detail=(
                ""
                if process_code is None
                else (
                    "Chrome process returncode="
                    f"{process_code}"
                )
            ),
        )

        self._last_shutdown_result = (
            result
        )

        return result

    def health(
        self,
    ):
        browser_available = (
            self._browser is not None
        )

        control_available = (
            browser_available
            and self._state
            == BrowserSessionState.READY
        )

        return BrowserSessionHealth(
            state=self._state,
            browser_available=(
                browser_available
            ),
            control_available=(
                control_available
            ),
            worker_available=None,
            last_error=self._last_error,
        )

    def snapshot(
        self,
    ):
        return BrowserSessionSnapshot(
            identity=self.identity,
            health=self.health(),
        )

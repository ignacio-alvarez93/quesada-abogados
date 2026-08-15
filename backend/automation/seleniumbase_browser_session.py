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
- shutdown;
- detach;
- kill;
- threads;
- event loops;
- watchers.

No contiene lógica específica de WhatsApp, Mercurio ni DEHú.
"""

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

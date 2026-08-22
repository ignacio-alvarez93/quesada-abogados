from backend.automation.browser_actions import (
    open_url,
    safe_execute,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.browser_session import (
    get_session_dir,
)
from backend.automation.browser_profiles import (
    get_browser_profile_dir,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.automation.automation_logger import (
    write_log,
)


class MercurioConnector:
    """Conector base para Presentación Asistida Mercurio.

    Esta fase activa el conector como propietario de:
    - carpeta de sesión
    - arranque del navegador SeleniumBase CDP
    - apertura de URL
    - ejecución segura con logging

    La lógica específica de pasos Mercurio se conserva todavía en
    app.run_presentacion_asistida para no alterar EX01/EX01_FAMILIAR.
    """

    def __init__(
        self,
        session_dir=None,
        expediente_id="sin_id",
        profile_key=None,
        headless=False,
        browser_session_factory=None,
    ):
        self.session_dir = get_session_dir(
            session_dir,
            expediente_id=expediente_id,
        )
        self.expediente_id = (
            expediente_id
            or "sin_id"
        )

        self.profile_key = (
            None
            if profile_key is None
            else str(
                profile_key
            ).strip()
        )

        if (
            profile_key is not None
            and not self.profile_key
        ):
            raise ValueError(
                "profile_key de Mercurio vacío"
            )

        self.headless = bool(
            headless
        )

        self._browser_session_factory = (
            browser_session_factory
            or SeleniumBaseBrowserSession
        )

        if not callable(
            self._browser_session_factory
        ):
            raise TypeError(
                "browser_session_factory debe ser callable"
            )

        self._browser_session = None
        self.browser = None

    def _build_browser_session(
        self,
    ):
        if self._browser_session is None:
            config = BrowserSessionConfig(
                consumer="mercurio",
                mode=BrowserSessionMode.ASSISTED,
                headless=self.headless,
                profile_key=self.profile_key,
            )

            session_kwargs = {
                "config": config,
            }

            if self.profile_key is not None:
                session_kwargs[
                    "profile_resolver"
                ] = get_browser_profile_dir

            self._browser_session = (
                self._browser_session_factory(
                    **session_kwargs
                )
            )

        return self._browser_session

    def start_browser(
        self,
        url,
    ):
        """Inicia la sesión gobernada y abre la URL objetivo."""

        write_log(
            self.session_dir,
            "MercurioConnector: iniciando "
            "Chrome SeleniumBase CDP gobernado",
        )

        session = (
            self._build_browser_session()
        )

        self.browser = (
            session.start()
        )

        open_url(
            self.browser,
            url,
        )

        write_log(
            self.session_dir,
            f"MercurioConnector: URL abierta {url}",
        )

        return self.browser

    def safe_execute(self, label, func):
        """Ejecuta una función capturando errores sin cerrar Chrome."""
        return safe_execute(label, func, self.session_dir)

    def close_browser(
        self,
    ):
        """
        Cierra únicamente la sesión de navegador propia.

        Mercurio es ASSISTED durante su uso, pero la salida
        explícita del runner solicita un CLOSE real.

        Un browser inyectado externamente sin BrowserSession
        asociada no se destruye porque el connector no puede
        asumir ownership de un recurso que no creó.
        """

        session = (
            self._browser_session
        )

        if session is None:
            return False

        try:
            result = session.shutdown(
                BrowserShutdownMode.CLOSE
            )

        except Exception as exc:
            write_log(
                self.session_dir,
                "MercurioConnector: error en shutdown "
                f"gobernado: {repr(exc)}",
            )

            return False

        successful = bool(
            result is not None
            and not result.has_error
            and result.control_released
            is True
            and result.browser_closed
            is True
        )

        if successful:
            self.browser = None
            self._browser_session = None

            write_log(
                self.session_dir,
                "MercurioConnector: sesión gobernada cerrada",
            )

        else:
            write_log(
                self.session_dir,
                "MercurioConnector: shutdown gobernado "
                "incompleto; ownership conservado",
            )

        return successful

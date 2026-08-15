"""
Conector base de DEHú.

Esta primera versión es exclusivamente exploratoria:
- abre el portal;
- permite autenticación manual;
- captura HTML y pantalla;
- no abre notificaciones pendientes;
- no acepta ni rechaza comparecencias.
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from backend.automation.automation_artifacts import (
    save_page_source,
    save_screenshot,
)
from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.browser_session import (
    get_project_root,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.automation.automation_logger import (
    write_log,
)


DEHU_URL = "https://dehu.redsara.es/"


def normalize_dehu_portal_url(
    url=None,
):
    """
    Valida un destino que vaya a abrirse dentro del
    Chrome autenticado de DEHú.

    Solo se admite HTTPS contra el host oficial DEHú.
    """

    raw = str(
        url
        or DEHU_URL
    ).strip()

    if not raw:
        raw = DEHU_URL

    try:
        parsed = urlsplit(
            raw
        )
    except Exception as exc:
        raise ValueError(
            "URL DEHú inválida"
        ) from exc

    if (
        parsed.scheme.lower()
        != "https"
    ):
        raise ValueError(
            "DEHú solo admite URLs HTTPS"
        )

    hostname = str(
        parsed.hostname
        or ""
    ).strip().lower()

    if (
        hostname
        != "dehu.redsara.es"
    ):
        raise ValueError(
            "La URL no pertenece al dominio DEHú"
        )

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "La URL DEHú no puede contener credenciales"
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "Puerto inválido en URL DEHú"
        ) from exc

    if port not in (
        None,
        443,
    ):
        raise ValueError(
            "Puerto no permitido para DEHú"
        )

    return raw


def get_dehu_profile_dir(
    profile_key="dehu",
):
    clean_key = (
        str(
            profile_key
            or ""
        )
        .strip()
        .replace(
            "\\",
            "_",
        )
        .replace(
            "/",
            "_",
        )
    )

    if not clean_key:
        raise ValueError(
            "profile_key de DEHú vacío"
        )

    profile_dir = (
        get_project_root()
        / "data"
        / "browser_profiles"
        / clean_key
    )

    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return profile_dir


class DehuConnector:
    def __init__(
        self,
        *,
        session_dir=None,
        profile_key="dehu",
        headless=False,
        browser_session_factory=None,
    ):
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        self.session_dir = Path(
            session_dir
            or (
                get_project_root()
                / "exports"
                / "dehu_sessions"
                / timestamp
            )
        )

        (self.session_dir / "html").mkdir(
            parents=True,
            exist_ok=True,
        )
        (self.session_dir / "screenshots").mkdir(
            parents=True,
            exist_ok=True,
        )
        (self.session_dir / "logs").mkdir(
            parents=True,
            exist_ok=True,
        )

        self.profile_key = str(
            profile_key
            or "dehu"
        ).strip()

        if not self.profile_key:
            raise ValueError(
                "profile_key de DEHú vacío"
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
        if (
            self._browser_session
            is None
        ):
            config = BrowserSessionConfig(
                consumer="dehu",
                mode=(
                    BrowserSessionMode.PERSISTENT
                ),
                headless=self.headless,
                profile_key=self.profile_key,
            )

            self._browser_session = (
                self._browser_session_factory(
                    config=config,
                    profile_resolver=(
                        get_dehu_profile_dir
                    ),
                )
            )

        return self._browser_session

    def start(
        self,
    ):
        write_log(
            self.session_dir,
            "DEHú: iniciando navegador gobernado",
        )

        session = (
            self._build_browser_session()
        )

        self.browser = (
            session.start()
        )

        self.open_portal(
            DEHU_URL
        )

        return self.browser

    def open_portal(
        self,
        url=None,
    ):
        """
        Navega únicamente a destinos pertenecientes
        al portal oficial DEHú.
        """

        if not self.browser:
            raise RuntimeError(
                "El navegador DEHú no está iniciado"
            )

        target = (
            normalize_dehu_portal_url(
                url
            )
        )

        open_url(
            self.browser,
            target,
        )

        write_log(
            self.session_dir,
            f"DEHú: abierta URL {target}",
        )

        return target

    def capture(self, label):
        if not self.browser:
            raise RuntimeError(
                "El navegador DEHú no está iniciado"
            )

        safe_label = (
            str(label or "capture")
            .strip()
            .lower()
            .replace(" ", "_")
        )

        html_path = save_page_source(
            self.browser,
            self.session_dir,
            label=safe_label,
        )

        screenshot_path = (
            self.session_dir
            / "screenshots"
            / f"{safe_label}.png"
        )

        screenshot_ok = save_screenshot(
            self.browser,
            screenshot_path,
        )

        write_log(
            self.session_dir,
            (
                f"DEHú: captura {safe_label}; "
                f"html={html_path}; "
                f"screenshot={screenshot_ok}"
            ),
        )

        return {
            "label": safe_label,
            "html_path": str(html_path),
            "screenshot_path": (
                str(screenshot_path)
                if screenshot_ok
                else ""
            ),
        }

    def close(
        self,
    ):
        """
        Cierra únicamente la BrowserSession propia.

        El perfil Chrome permanece en disco para poder
        reutilizar cookies, estado y demás datos de sesión
        compatibles con el portal en futuras ejecuciones.

        Si ``browser`` fuese inyectado externamente sin
        BrowserSession asociada, el connector no asume
        ownership y no lo destruye.
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
                "DEHú: error en shutdown gobernado: "
                f"{exc!r}",
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
                "DEHú: sesión gobernada cerrada",
            )

        else:
            write_log(
                self.session_dir,
                "DEHú: shutdown incompleto; "
                "ownership conservado",
            )

        return successful

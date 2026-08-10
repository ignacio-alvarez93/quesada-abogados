"""
Conector base de WhatsApp Web.

Responsabilidades V1:
- resolver perfil Chrome persistente;
- abrir WhatsApp Web;
- identificar de forma conservadora si la sesión:
  * necesita autenticación;
  * está lista;
  * todavía está cargando;
- mantener el navegador bajo control del proceso externo.

No importa conversaciones todavía.
No envía mensajes todavía.
No contiene persistencia de negocio.
"""

from pathlib import Path

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_session import (
    get_project_root,
    start_seleniumbase_chrome,
)


WHATSAPP_WEB_URL = (
    "https://web.whatsapp.com/"
)

SESSION_STATUS_NEEDS_LOGIN = (
    "NEEDS_LOGIN"
)

SESSION_STATUS_READY = (
    "READY"
)

SESSION_STATUS_LOADING = (
    "LOADING"
)

SESSION_STATUS_UNKNOWN = (
    "UNKNOWN"
)


def get_whatsapp_profile_dir(
    profile_key="whatsapp_dev",
):
    clean_key = (
        str(profile_key or "")
        .strip()
        .replace("\\", "_")
        .replace("/", "_")
    )

    if not clean_key:
        raise ValueError(
            "profile_key de WhatsApp vacío"
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


class WhatsAppConnector:
    def __init__(
        self,
        *,
        profile_key="whatsapp_dev",
        headless=False,
    ):
        self.profile_key = str(
            profile_key
            or "whatsapp_dev"
        ).strip()

        self.profile_dir = (
            get_whatsapp_profile_dir(
                self.profile_key
            )
        )

        self.headless = bool(
            headless
        )

        self.browser = None

    def start(self):
        self.browser = (
            start_seleniumbase_chrome(
                headless=self.headless,
                user_data_dir=(
                    self.profile_dir
                ),
            )
        )

        open_url(
            self.browser,
            WHATSAPP_WEB_URL,
        )

        return self.browser

    def _page_text(self):
        if not self.browser:
            return ""

        try:
            return str(
                self.browser.get_text("body")
                or ""
            )
        except Exception:
            return ""

    def detect_session_status(self):
        if not self.browser:
            return SESSION_STATUS_UNKNOWN

        text = (
            self._page_text()
            .strip()
            .lower()
        )

        if not text:
            return SESSION_STATUS_LOADING

        login_markers = (
            "link with phone number",
            "use whatsapp on your computer",
            "scan this qr code",
            "vincular con el número de teléfono",
            "usar whatsapp en tu ordenador",
            "escanea el código qr",
        )

        if any(
            marker in text
            for marker in login_markers
        ):
            return SESSION_STATUS_NEEDS_LOGIN

        ready_markers = (
            "search or start new chat",
            "buscar un chat o iniciar uno nuevo",
            "search",
            "buscar",
        )

        if any(
            marker in text
            for marker in ready_markers
        ):
            return SESSION_STATUS_READY

        return SESSION_STATUS_UNKNOWN

    def close(self):
        """Finaliza únicamente el navegador de esta sesión WhatsApp.

        El wrapper sb_cdp.Chrome de la versión instalada no expone quit(),
        pero su driver interno sí dispone de stop()/quit(). Se utiliza
        driver.stop() para cerrar limpiamente el proceso Chrome y la conexión
        CDP, sin modificar el comportamiento de Mercurio ni DEHú.
        """
        if not self.browser:
            return False

        driver = getattr(
            self.browser,
            "driver",
            None,
        )

        stop = getattr(
            driver,
            "stop",
            None,
        )

        if not callable(stop):
            return False

        try:
            stop()
            return True
        except Exception:
            return False

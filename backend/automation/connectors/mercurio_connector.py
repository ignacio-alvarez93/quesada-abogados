from backend.automation.browser_actions import open_url, safe_execute
from backend.automation.browser_session import get_session_dir, start_seleniumbase_chrome
from backend.automation.automation_logger import write_log


class MercurioConnector:
    """Conector ligero para Presentación Asistida Mercurio.

    Fase inicial de la abstracción: centraliza creación de sesión y navegador,
    pero conserva el flujo histórico en app.run_presentacion_asistida para no
    cambiar comportamiento.
    """

    def __init__(self, session_dir=None, expediente_id="sin_id", headless=False):
        self.session_dir = get_session_dir(session_dir, expediente_id=expediente_id)
        self.headless = headless
        self.browser = None

    def start_browser(self, url):
        write_log(self.session_dir, "MercurioConnector: iniciando Chrome SeleniumBase CDP")
        self.browser = start_seleniumbase_chrome(headless=self.headless)
        open_url(self.browser, url)
        return self.browser

    def safe_execute(self, label, func):
        return safe_execute(label, func, self.session_dir)

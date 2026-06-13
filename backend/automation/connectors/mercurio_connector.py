from backend.automation.browser_actions import open_url, safe_execute
from backend.automation.browser_session import get_session_dir, start_seleniumbase_chrome
from backend.automation.automation_logger import write_log


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

    def __init__(self, session_dir=None, expediente_id="sin_id", headless=False):
        self.session_dir = get_session_dir(session_dir, expediente_id=expediente_id)
        self.expediente_id = expediente_id or "sin_id"
        self.headless = headless
        self.browser = None

    def start_browser(self, url):
        """Inicia Chrome SeleniumBase CDP y abre la URL objetivo."""
        write_log(self.session_dir, "MercurioConnector: iniciando Chrome SeleniumBase CDP")
        self.browser = start_seleniumbase_chrome(headless=self.headless)
        open_url(self.browser, url)
        write_log(self.session_dir, f"MercurioConnector: URL abierta {url}")
        return self.browser

    def safe_execute(self, label, func):
        """Ejecuta una función capturando errores sin cerrar Chrome."""
        return safe_execute(label, func, self.session_dir)

    def close_browser(self):
        """Cierra navegador solo cuando el usuario lo pide explícitamente."""
        if not self.browser:
            return False

        try:
            if hasattr(self.browser, "quit"):
                self.browser.quit()
                write_log(self.session_dir, "MercurioConnector: browser.quit() ejecutado")
                return True
            if hasattr(self.browser, "close"):
                self.browser.close()
                write_log(self.session_dir, "MercurioConnector: browser.close() ejecutado")
                return True
        except Exception as exc:
            write_log(self.session_dir, f"MercurioConnector: error cerrando navegador: {repr(exc)}")
            return False

        write_log(self.session_dir, "MercurioConnector: navegador sin método quit/close")
        return False

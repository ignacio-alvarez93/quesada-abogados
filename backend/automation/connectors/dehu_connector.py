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

from backend.automation.automation_artifacts import (
    save_page_source,
    save_screenshot,
)
from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_session import (
    get_project_root,
    start_seleniumbase_chrome,
)
from backend.automation.automation_logger import (
    write_log,
)


DEHU_URL = "https://dehu.redsara.es/"


class DehuConnector:
    def __init__(
        self,
        *,
        session_dir=None,
        headless=False,
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

        self.headless = bool(headless)
        self.browser = None

    def start(self):
        write_log(
            self.session_dir,
            "DEHú: iniciando navegador",
        )

        self.browser = start_seleniumbase_chrome(
            headless=self.headless
        )

        open_url(
            self.browser,
            DEHU_URL,
        )

        write_log(
            self.session_dir,
            f"DEHú: abierta URL {DEHU_URL}",
        )

        return self.browser

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

    def close(self):
        if not self.browser:
            return False

        try:
            if hasattr(self.browser, "quit"):
                self.browser.quit()
                return True

            if hasattr(self.browser, "close"):
                self.browser.close()
                return True

        except Exception as exc:
            write_log(
                self.session_dir,
                f"DEHú: error al cerrar: {exc!r}",
            )

        return False

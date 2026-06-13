from datetime import datetime
from pathlib import Path


def get_browser_source(browser):
    """Obtiene el HTML actual desde distintos wrappers Selenium/CDP."""
    if hasattr(browser, "get_page_source"):
        return browser.get_page_source()
    if hasattr(browser, "get_source"):
        return browser.get_source()
    if hasattr(browser, "page_source"):
        return browser.page_source
    if hasattr(browser, "driver") and hasattr(browser.driver, "page_source"):
        return browser.driver.page_source
    if hasattr(browser, "execute_script"):
        return browser.execute_script("return document.documentElement.outerHTML;")
    if hasattr(browser, "evaluate"):
        return browser.evaluate("document.documentElement.outerHTML")
    raise RuntimeError("No se pudo obtener HTML")


def save_page_source(browser, session_dir, label="page_source"):
    """Guarda HTML actual en session_dir/html y devuelve la ruta."""
    session_dir = Path(session_dir)
    html_dir = session_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = html_dir / f"{label}_{timestamp}.html"
    html_path.write_text(get_browser_source(browser) or "", encoding="utf-8")
    return html_path


def save_screenshot(browser, path):
    """Guarda captura si el wrapper de navegador lo soporta.

    Devuelve True si la captura se ha creado o el método indica éxito.
    """
    path = Path(path)

    for obj in (browser, getattr(browser, "driver", None)):
        if obj is None:
            continue
        method = getattr(obj, "save_screenshot", None)
        if callable(method):
            try:
                ok = method(str(path))
                if ok is not False and path.exists():
                    return True
            except Exception:
                pass

    for name in ("get_screenshot_as_file", "screenshot"):
        method = getattr(browser, name, None)
        if callable(method):
            try:
                result = method(str(path))
                if path.exists() or result is True:
                    return True
            except Exception:
                pass

    return False

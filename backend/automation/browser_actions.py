import json
import time

from backend.automation.automation_logger import write_log


def js(browser, code):
    """Ejecuta JavaScript en Selenium/CDP con una interfaz común."""
    if hasattr(browser, "execute_script"):
        return browser.execute_script(code)
    if hasattr(browser, "evaluate"):
        return browser.evaluate(code)
    raise RuntimeError("El navegador no soporta execute_script/evaluate")


def wait_for_js(browser, condition_js, timeout=30, interval=0.5):
    """Espera hasta que una condición JavaScript sea truthy."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if js(browser, f"return !!({condition_js});"):
                return True
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError(f"Timeout esperando condición JS: {condition_js}")


def field_exists(browser, field_id):
    """Comprueba si existe un elemento por id."""
    try:
        return bool(js(browser, f"return !!document.getElementById({json.dumps(field_id)});"))
    except Exception:
        return False


def click_js(browser, selector):
    """Click por querySelector sin depender de selectores Selenium."""
    script = f"""
    (function(){{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return false;
        el.click();
        return true;
    }})();
    """
    return js(browser, script)


def open_url(browser, url):
    """Abre una URL en cualquier wrapper compatible."""
    if hasattr(browser, "open"):
        browser.open(url)
    elif hasattr(browser, "get"):
        browser.get(url)
    else:
        raise RuntimeError("La instancia de navegador no tiene método open/get")


def safe_execute(label, func, session_dir):
    """Ejecuta una acción sin cerrar el navegador si falla."""
    try:
        return func()
    except Exception as exc:
        print(f"ERROR en {label}: {exc}")
        write_log(session_dir, f"ERROR en {label}: {repr(exc)}")
        return None

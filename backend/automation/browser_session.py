from pathlib import Path


def get_project_root():
    """Raíz del proyecto, asumiendo backend/automation/browser_session.py."""
    return Path(__file__).resolve().parents[2]


def get_session_dir(arg_session_dir=None, expediente_id="sin_id"):
    """Devuelve/crea la carpeta de sesión de una automatización."""
    if arg_session_dir:
        session_dir = Path(arg_session_dir)
    else:
        session_dir = get_project_root() / "exports" / "presentaciones_asistidas" / f"expediente_{expediente_id}"

    (session_dir / "html").mkdir(parents=True, exist_ok=True)
    (session_dir / "logs").mkdir(parents=True, exist_ok=True)
    return session_dir


def start_seleniumbase_chrome(
    headless=False,
    user_data_dir=None,
):
    """Crea Chrome SeleniumBase CDP.

    Import diferido para que el ERP pueda arrancar aunque SeleniumBase no esté
    instalado en entornos donde no se use automatización.

    ``user_data_dir`` permite reutilizar un perfil persistente cuando una
    automatización necesita conservar sesión entre ejecuciones, como WhatsApp
    Web. Las automatizaciones existentes pueden seguir llamando a esta función
    únicamente con ``headless``.
    """
    from seleniumbase import sb_cdp

    kwargs = {
        "headless": bool(headless),
    }

    if user_data_dir:
        kwargs["user_data_dir"] = str(
            Path(user_data_dir).resolve()
        )

    return sb_cdp.Chrome(**kwargs)

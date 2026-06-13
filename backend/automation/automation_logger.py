from datetime import datetime
from pathlib import Path


def write_log(session_dir, message, filename="presentacion.log"):
    """Escribe una línea de log en la carpeta de sesión.

    Mantiene el formato histórico de Presentación Asistida para no romper
    trazabilidad ni diagnósticos existentes.
    """
    session_dir = Path(session_dir)
    log_dir = session_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename
    stamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    return log_path

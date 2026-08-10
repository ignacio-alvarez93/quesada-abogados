"""
Servicio de lanzamiento de la sesión externa de WhatsApp Web.

No contiene Selenium directamente.
No contiene SQL.
No conoce Flet.
"""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

RUNNER_PATH = (
    PROJECT_ROOT
    / "app"
    / "run_whatsapp_session.py"
)


def start_whatsapp_session_external(
    *,
    profile_key="whatsapp_dev",
):
    if not RUNNER_PATH.exists():
        raise FileNotFoundError(
            "No existe el runner externo "
            f"de WhatsApp: {RUNNER_PATH}"
        )

    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--profile-key",
        str(
            profile_key
            or "whatsapp_dev"
        ),
    ]

    creationflags = 0

    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_CONSOLE
        )

    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
    )

    return {
        "process": process,
        "pid": process.pid,
        "profile_key": (
            str(
                profile_key
                or "whatsapp_dev"
            )
        ),
        "mode": (
            "external_whatsapp_sb_cdp"
        ),
    }

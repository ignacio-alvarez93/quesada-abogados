"""
Regresión: el worker externo de Presentación Asistida (Mercurio) no
debe abrir una consola visible en Windows, porque QCC es quien
presenta ahora el flujo de navegador gobernado.

Oculto no significa huérfano: el runner conserva su propia consola
real (mismo stdin/stdout, mismo menú/lifecycle interactivo de
siempre) y el servicio sigue devolviendo un ``subprocess.Popen``
supervisado (pid, poll()) exactamente como antes. Solo cambia la
visibilidad de la ventana.

No abre navegador real ni proceso real: ``subprocess.Popen`` se
sustituye por un doble de prueba.
"""

import os
import subprocess
from unittest import mock

from backend.services import presentation_assistant_service


SYNTHETIC_CONFIG = {
    "url_presentacion": "https://mercurio.synthetic.example/",
    "expediente_id": 10,
    "cliente_id": 1,
    "qcc_session_id": "qcc-mercurio-10-fake",
    "browser_profile_key": "qcc_assisted",
    "numero_expediente": "EXP-2026-001",
    "tipo_nombre": "EX01",
    "provincia_codigo": "33",
    "datos_mercurio_path": "/synthetic/presentacion/10/datos_mercurio.json",
    "presentacion_folder": "/synthetic/presentacion/10",
}


def test_windows_worker_launch_suppresses_visible_console_window():
    """I. En Windows la ventana de consola del worker queda oculta."""

    with mock.patch.object(
        presentation_assistant_service,
        "os",
    ) as os_module, mock.patch.object(
        presentation_assistant_service.subprocess,
        "Popen",
    ) as popen:
        os_module.name = "nt"
        os_module.path = os.path

        popen.return_value.pid = 1234

        presentation_assistant_service.start_presentation_external(
            SYNTHETIC_CONFIG,
            auto=True,
        )

    assert popen.call_count == 1
    _, kwargs = popen.call_args

    assert kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE

    startupinfo = kwargs["startupinfo"]
    assert startupinfo is not None
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


def test_non_windows_launch_does_not_set_window_flags():
    """Fuera de Windows no se fuerzan flags/startupinfo inexistentes."""

    with mock.patch.object(
        presentation_assistant_service,
        "os",
    ) as os_module, mock.patch.object(
        presentation_assistant_service.subprocess,
        "Popen",
    ) as popen:
        os_module.name = "posix"
        os_module.path = os.path

        popen.return_value.pid = 1234

        presentation_assistant_service.start_presentation_external(
            SYNTHETIC_CONFIG,
            auto=True,
        )

    _, kwargs = popen.call_args
    assert kwargs["creationflags"] == 0
    assert kwargs["startupinfo"] is None


def test_launch_remains_supervised_with_pid_and_poll():
    """J. El proceso sigue supervisado: pid y poll() disponibles."""

    with mock.patch.object(
        presentation_assistant_service.subprocess,
        "Popen",
    ) as popen:
        popen.return_value.pid = 9999
        popen.return_value.poll.return_value = None

        process = presentation_assistant_service.start_presentation_external(
            SYNTHETIC_CONFIG,
            auto=True,
        )

    assert process.pid == 9999
    assert process.poll() is None

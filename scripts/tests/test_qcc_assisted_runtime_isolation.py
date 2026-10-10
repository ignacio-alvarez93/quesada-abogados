"""
Regresión: aislamiento de runtime entre Presentación Asistida QCC y
AUTO TWIN/materializaciones.

Invariante arquitectónico:

    ASSISTED PRESENTATION
    -> exactamente una identidad de navegador gobernada requerida
    -> browser_profile_key = qcc_assisted

Presentación Asistida NO debe, implícitamente:

- iniciar/asegurar/recrear/enfocar/navegar/reiniciar un navegador Twin;
- iterar sitios materializados para arrancar sus runtimes;
- convertir inspección de metadata en arranque de navegador.

No abre navegador real ni toca Mercurio/Twin reales: el límite externo
(``subprocess.Popen``) y el navegador Twin runtime se sustituyen por
dobles de prueba o se auditan estáticamente (AST/código fuente), nunca
se ejecutan.
"""

import ast
import inspect
from pathlib import Path
from unittest import mock

from backend.services import presentation_assistant_service
from backend.services import qcc_presentation_context_service
from backend.services import twin_management_service
from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
    get_default_twin_browser_runtime_service,
)


SYNTHETIC_EXPEDIENTE = {
    "id": 11,
    "cliente_id": 2,
    "numero_expediente": "EXP-2026-002",
    "tipo_expediente_id": 6,
    "box_folder_path": "/synthetic/box/expediente",
}

SYNTHETIC_TIPO = {
    "id": 6,
    "codigo": "EX01",
    "nombre": "EX01 - Residencia temporal no lucrativa",
    "url_presentacion": "https://mercurio.synthetic.example/",
    "activo": 1,
}

SYNTHETIC_EXPORT = {
    "folder": Path("/synthetic/presentacion/11"),
    "datos_mercurio_path": Path(
        "/synthetic/presentacion/11/datos_mercurio.json"
    ),
    "datos_mercurio": {
        "presentacion": {
            "provincia_codigo": "33",
            "tipo_formulario_objetivo": "EX01",
            "mapper_codigo": "MERCURIO_EX01",
        }
    },
}


def _launch_once(popen_pid=1111):
    with mock.patch.object(
        presentation_assistant_service,
        "get_tipo_presentacion_config",
        return_value=dict(SYNTHETIC_TIPO),
    ), mock.patch.object(
        presentation_assistant_service,
        "validate_cliente_mercurio_ready",
        return_value=[],
    ), mock.patch.object(
        presentation_assistant_service.mercurio_mapper_service,
        "build_and_export",
        return_value=SYNTHETIC_EXPORT,
    ), mock.patch.object(
        presentation_assistant_service,
        "write_log",
    ), mock.patch.object(
        presentation_assistant_service.subprocess,
        "Popen",
    ) as popen:
        popen.return_value.pid = popen_pid

        context = (
            presentation_assistant_service
            .start_presentation_for_expediente(
                SYNTHETIC_EXPEDIENTE
            )
        )

    return context, popen


def _module_references_any(
    module_path,
    needles,
):
    """True si el módulo importa o referencia textualmente cualquier
    identificador de ``needles`` (AUTO TWIN/Twin runtime)."""

    source = Path(
        module_path
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(needle in module for needle in needles):
                return True
            for alias in node.names:
                if any(needle in alias.name for needle in needles):
                    return True

        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(needle in alias.name for needle in needles):
                    return True

    return any(needle in source for needle in needles)


AUTO_TWIN_RUNTIME_NEEDLES = (
    "backend.qcc.auto_twin",
    "twin_browser_runtime_service",
    "twin_management_service",
    "twin_discovery_runtime_service",
    "automatic_materialization",
    "TwinBrowserRuntimeService",
    "start_twin_browser",
    "start_discovery",
    "ensure_runtime",
)


# ---------------------------------------------------------------------
# A. Assisted Presentation requests qcc_assisted only.
# ---------------------------------------------------------------------
def test_assisted_presentation_requests_qcc_assisted_profile_only():
    context, popen = _launch_once()

    assert context["config"]["browser_profile_key"] == "qcc_assisted"
    assert (
        presentation_assistant_service
        .QCC_ASSISTED_BROWSER_PROFILE_KEY
    ) == "qcc_assisted"

    cmd = popen.call_args.args[0]
    assert "--browser-profile-key" in cmd
    assert (
        cmd[cmd.index("--browser-profile-key") + 1]
        == "qcc_assisted"
    )


# ---------------------------------------------------------------------
# B. Assisted Presentation does not invoke AUTO TWIN runtime
#    start/ensure/open/replay/discovery, anywhere along its own code
#    path (service, runner, connector, browser session factory).
# ---------------------------------------------------------------------
def test_assisted_presentation_code_path_never_references_auto_twin_runtime():
    assisted_path_modules = (
        "backend/services/presentation_assistant_service.py",
        "backend/services/mercurio_mapper_service.py",
        "backend/automation/connectors/mercurio_connector.py",
        "backend/automation/seleniumbase_browser_session.py",
        "backend/automation/browser_session.py",
        "backend/automation/browser_profiles.py",
        "app/run_presentacion_asistida.py",
    )

    offenders = [
        module_path
        for module_path in assisted_path_modules
        if _module_references_any(
            module_path,
            AUTO_TWIN_RUNTIME_NEEDLES,
        )
    ]

    assert not offenders, (
        "Código de Presentación Asistida referencia runtime "
        f"AUTO TWIN/Twin: {offenders}"
    )


def test_assisted_presentation_never_calls_twin_browser_runtime_service():
    """Doble explícito: ningún arranque/ensure/stop del runtime Twin
    ocurre como efecto de lanzar Presentación Asistida."""

    fake_twin_runtime = mock.create_autospec(
        TwinBrowserRuntimeService,
        instance=True,
    )

    with mock.patch(
        "backend.services.twin_browser_runtime_service"
        "._DEFAULT_SERVICE",
        fake_twin_runtime,
    ):
        _launch_once()

    fake_twin_runtime.start.assert_not_called()
    fake_twin_runtime.stop.assert_not_called()
    fake_twin_runtime.stop_all.assert_not_called()
    fake_twin_runtime.execute_script.assert_not_called()


# ---------------------------------------------------------------------
# C. Passive materialization metadata access (QCC presentation
#    context) does not start browser runtime.
# ---------------------------------------------------------------------
def test_presentation_context_resolution_never_references_auto_twin_runtime():
    context_modules = (
        "backend/services/qcc_presentation_context_service.py",
        "backend/qcc/context/presentation_context.py",
    )

    offenders = [
        module_path
        for module_path in context_modules
        if _module_references_any(
            module_path,
            AUTO_TWIN_RUNTIME_NEEDLES,
        )
    ]

    assert not offenders, (
        "QccPresentationContext referencia runtime AUTO TWIN/Twin: "
        f"{offenders}"
    )


def test_presentation_context_resolution_is_side_effect_free_read():
    """Leer el contexto de presentación resuelve datos de cliente,
    expediente y documentos; nunca inicia ningún BrowserSession."""

    fake_twin_runtime = mock.create_autospec(
        TwinBrowserRuntimeService,
        instance=True,
    )

    with mock.patch(
        "backend.services.twin_browser_runtime_service"
        "._DEFAULT_SERVICE",
        fake_twin_runtime,
    ):
        resolution = (
            qcc_presentation_context_service
            .resolve_presentation_context(
                11,
                client_resolver=(
                    lambda client_id: {
                        "display_name": "Cliente Sintetico",
                    }
                ),
                expedient_resolver=(
                    lambda expediente_id: {
                        "cliente_id": 1,
                        "tipo_expediente_nombre": "EX01",
                    }
                ),
                target_folder_resolver=(
                    lambda expediente_id, purpose: None
                ),
            )
        )

    assert resolution.status.value == "AVAILABLE"
    fake_twin_runtime.start.assert_not_called()


# ---------------------------------------------------------------------
# D. Existing qcc_assisted runtime is reused where the current
#    architecture supports reuse: every assisted launch resolves to
#    the exact same logical profile_key (and therefore the same
#    physical, persistent Chrome profile directory), which is the
#    precondition that lets Chrome/SeleniumBase reuse the browser
#    instead of creating a parallel, unrelated profile each time.
# ---------------------------------------------------------------------
def test_repeated_assisted_launches_resolve_to_the_same_profile_key():
    first_context, first_popen = _launch_once(popen_pid=1111)
    second_context, second_popen = _launch_once(popen_pid=2222)

    assert (
        first_context["config"]["browser_profile_key"]
        == second_context["config"]["browser_profile_key"]
        == "qcc_assisted"
    )

    first_cmd = first_popen.call_args.args[0]
    second_cmd = second_popen.call_args.args[0]

    assert (
        first_cmd[first_cmd.index("--browser-profile-key") + 1]
        == second_cmd[
            second_cmd.index("--browser-profile-key") + 1
        ]
    )


# ---------------------------------------------------------------------
# E. An independently running Twin runtime's lifecycle is never
#    touched by launching Assisted Presentation.
# ---------------------------------------------------------------------
def test_independent_twin_runtime_lifecycle_untouched_by_assisted_launch():
    fake_twin_runtime = mock.create_autospec(
        TwinBrowserRuntimeService,
        instance=True,
    )

    with mock.patch(
        "backend.services.twin_browser_runtime_service"
        "._DEFAULT_SERVICE",
        fake_twin_runtime,
    ):
        _launch_once()

        # La fábrica por defecto expuesta a otros consumidores (p.ej.
        # el entrypoint explícito de AUTO TWIN) sigue siendo el mismo
        # runtime Twin, no sustituido ni reiniciado por el lanzamiento
        # asistido.
        assert (
            get_default_twin_browser_runtime_service()
            is fake_twin_runtime
        )

    fake_twin_runtime.stop.assert_not_called()
    fake_twin_runtime.stop_all.assert_not_called()


# ---------------------------------------------------------------------
# F. Explicit Twin launch remains available through its dedicated
#    entrypoint.
# ---------------------------------------------------------------------
def test_explicit_twin_browser_entrypoint_still_wired_to_runtime_service():
    source = inspect.getsource(
        twin_management_service.TwinManagementService
        .start_twin_browser
    )

    assert "self.browser_runtime_service" in source
    assert ".start(" in source


# ---------------------------------------------------------------------
# H. qcc_assisted does not select a Twin/materialization profile.
# ---------------------------------------------------------------------
def test_qcc_assisted_profile_key_is_not_a_twin_profile_key():
    twin_profile_key = (
        TwinBrowserRuntimeService()
        ._profile_key(
            "mercurio"
        )
    )

    assert (
        presentation_assistant_service
        .QCC_ASSISTED_BROWSER_PROFILE_KEY
    ) != twin_profile_key

    assert not (
        presentation_assistant_service
        .QCC_ASSISTED_BROWSER_PROFILE_KEY
    ).startswith("twin_runtime_")

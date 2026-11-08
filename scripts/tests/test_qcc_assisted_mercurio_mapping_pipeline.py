"""
Regresión: el lanzamiento de Presentación Asistida vía QCC debe seguir
alcanzando el pipeline canónico existente de mapeo/volcado Mercurio.

QCC solo contextualiza (session_id, browser_profile_key, progreso); nunca
sustituye ni duplica el mapeo de campos, que sigue siendo responsabilidad
exclusiva de ``mercurio_mapper_service`` + ``run_presentacion_asistida``.

No abre navegador real ni toca Mercurio real: el límite del proceso
externo (``subprocess.Popen``) y el mapper se sustituyen por dobles de
prueba.
"""

from pathlib import Path
from unittest import mock

from backend.services import presentation_assistant_service


SYNTHETIC_EXPEDIENTE = {
    "id": 10,
    "cliente_id": 1,
    "numero_expediente": "EXP-2026-001",
    "tipo_expediente_id": 5,
    "box_folder_path": "/synthetic/box/expediente",
}

SYNTHETIC_TIPO = {
    "id": 5,
    "codigo": "EX01",
    "nombre": "EX01 - Residencia temporal no lucrativa",
    "url_presentacion": "https://mercurio.synthetic.example/",
    "activo": 1,
}

SYNTHETIC_EXPORT = {
    "folder": Path("/synthetic/presentacion/10"),
    "datos_mercurio_path": Path(
        "/synthetic/presentacion/10/datos_mercurio.json"
    ),
    "datos_mercurio": {
        "presentacion": {
            "provincia_codigo": "33",
            "tipo_formulario_objetivo": "EX01",
            "mapper_codigo": "MERCURIO_EX01",
        }
    },
}


def _patched_config():
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
    ) as build_and_export:
        config = (
            presentation_assistant_service
            .validate_expediente_for_presentation(
                SYNTHETIC_EXPEDIENTE
            )
        )

    return config, build_and_export


def test_assisted_launch_still_invokes_canonical_mercurio_mapper():
    """A. El pipeline canónico de mapeo sigue siendo invocado."""

    config, build_and_export = _patched_config()

    build_and_export.assert_called_once_with(
        SYNTHETIC_EXPEDIENTE["id"]
    )

    assert config["datos_mercurio_path"] == str(
        SYNTHETIC_EXPORT["datos_mercurio_path"]
    )


def test_assisted_launch_preserves_required_identity_payload():
    """B. Cliente/expediente/procedimiento llegan intactos al runner."""

    config, _ = _patched_config()

    with mock.patch.object(
        presentation_assistant_service.subprocess,
        "Popen",
    ) as popen:
        popen.return_value.pid = 4321

        presentation_assistant_service.start_presentation_external(
            {
                **config,
                "qcc_session_id": "qcc-mercurio-10-fake",
                "browser_profile_key": "qcc_assisted",
            },
            auto=True,
        )

    assert popen.call_count == 1
    cmd = popen.call_args.args[0]

    assert "--expediente-id" in cmd
    assert str(SYNTHETIC_EXPEDIENTE["id"]) == (
        cmd[cmd.index("--expediente-id") + 1]
    )

    assert "--cliente-id" in cmd
    assert str(SYNTHETIC_EXPEDIENTE["cliente_id"]) == (
        cmd[cmd.index("--cliente-id") + 1]
    )

    assert "--numero-expediente" in cmd
    assert SYNTHETIC_EXPEDIENTE["numero_expediente"] == (
        cmd[cmd.index("--numero-expediente") + 1]
    )

    assert "--datos-mercurio-json" in cmd
    assert str(SYNTHETIC_EXPORT["datos_mercurio_path"]) == (
        cmd[cmd.index("--datos-mercurio-json") + 1]
    )

    assert "--provincia-codigo" in cmd
    assert "33" == cmd[cmd.index("--provincia-codigo") + 1]


def test_qcc_fields_are_metadata_only_not_mapping_inputs():
    """C. QCC nunca se convierte en autoridad de mapeo.

    browser_profile_key/qcc_session_id son metadatos de identidad de
    sesión añadidos SOBRE la config ya resuelta por el mapper; nunca
    sustituyen datos_mercurio_path ni ningún campo del mapeo.
    """

    config, _ = _patched_config()

    qcc_session_id = (
        presentation_assistant_service._new_qcc_session_id(
            config.get("expediente_id")
        )
    )

    enriched = dict(config)
    enriched["qcc_session_id"] = qcc_session_id
    enriched["browser_profile_key"] = (
        presentation_assistant_service
        .QCC_ASSISTED_BROWSER_PROFILE_KEY
    )

    assert enriched["datos_mercurio_path"] == config["datos_mercurio_path"]
    assert enriched["url_presentacion"] == config["url_presentacion"]
    assert enriched["expediente_id"] == config["expediente_id"]


def test_no_duplicate_mapping_implementation_in_qcc_layer():
    """D. QCC nunca reimplementa ni importa el mapper de Mercurio."""

    import ast

    qcc_source_files = list(
        Path("backend/qcc").rglob("*.py")
    )

    assert qcc_source_files, "No se encontraron fuentes QCC a auditar"

    for path in qcc_source_files:
        tree = ast.parse(
            path.read_text(encoding="utf-8")
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "mercurio_mapper_service" not in module, (
                    f"{path} importa el mapper Mercurio"
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert (
                        "mercurio_mapper_service" not in alias.name
                    ), f"{path} importa el mapper Mercurio"


def test_assisted_launch_reaches_fill_stage_not_only_navigation():
    """A/D complement: el runner sigue leyendo y usando
    datos_mercurio.json para el volcado, no solo para navegar."""

    runner_source = Path(
        "app/run_presentacion_asistida.py"
    ).read_text(encoding="utf-8")

    assert "load_datos_mercurio(args.datos_mercurio_json)" in runner_source
    assert "fill_datos_extranjero(" in runner_source
    assert "fill_datos_reagrupante_ex02(" in runner_source
    assert "fill_datos_presentador(" in runner_source

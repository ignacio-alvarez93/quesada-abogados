from pathlib import Path
from types import SimpleNamespace
from unittest.mock import (
    Mock,
    patch,
)

import pytest

import app.run_presentacion_asistida as runner
from backend.services import (
    presentation_assistant_service,
)


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)

CONNECTOR_PATH = Path(
    "backend/automation/connectors/mercurio_connector.py"
)

SESSION_PATH = Path(
    "backend/automation/seleniumbase_browser_session.py"
)


def test_parent_command_passes_qcc_runtime_identity():
    config = {
        "url_presentacion":
            "https://example.invalid/mercurio",
        "expediente_id":
            1842,
        "cliente_id":
            321,
        "qcc_session_id":
            "qcc-mercurio-1842-test",
        "numero_expediente":
            "EXP-1842",
        "tipo_nombre":
            "Reagrupación familiar",
        "provincia_codigo":
            "33",
        "datos_mercurio_path":
            "datos.json",
        "presentacion_folder":
            "session",
    }

    fake_process = SimpleNamespace(
        pid=12345,
    )

    with patch.object(
        presentation_assistant_service
        .subprocess,
        "Popen",
        return_value=fake_process,
    ) as popen:
        result = (
            presentation_assistant_service
            .start_presentation_external(
                config,
                auto=True,
            )
        )

    assert result is fake_process

    command = popen.call_args.args[0]

    def value_after(flag):
        index = command.index(flag)

        return command[
            index + 1
        ]

    assert value_after(
        "--expediente-id"
    ) == "1842"

    assert value_after(
        "--cliente-id"
    ) == "321"

    assert value_after(
        "--qcc-session-id"
    ) == "qcc-mercurio-1842-test"

    assert "--auto" in command


def test_parent_generates_qcc_session_identity():
    validated = {
        "url_presentacion":
            "https://example.invalid",
        "expediente_id":
            1842,
        "cliente_id":
            321,
    }

    fake_process = SimpleNamespace(
        pid=12345,
    )

    captured = {}

    def fake_start(
        config,
        auto=True,
    ):
        captured.update(
            config
        )

        return fake_process

    with patch.object(
        presentation_assistant_service,
        "validate_expediente_for_presentation",
        return_value=dict(
            validated
        ),
    ):
        with patch.object(
            presentation_assistant_service,
            "start_presentation_external",
            side_effect=fake_start,
        ):
            context = (
                presentation_assistant_service
                .start_presentation_for_expediente(
                    {
                        "id": 1842,
                    }
                )
            )

    session_id = captured[
        "qcc_session_id"
    ]

    assert session_id.startswith(
        "qcc-mercurio-1842-"
    )

    assert (
        context["qcc_session_id"]
        == session_id
    )


def test_runner_qcc_reporter_is_optional(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id="",
        expediente_id="1842",
        cliente_id="321",
        tipo="TEST",
    )

    reporter = runner.build_qcc_reporter(
        args,
        str(tmp_path),
    )

    assert reporter is None


def test_runner_auto_envelope_reports_completion():
    reporter = Mock()

    with patch.object(
        runner,
        "run_auto",
        return_value="OK",
    ):
        result = (
            runner.run_auto_with_qcc(
                object(),
                "33",
                {},
                ".",
                reporter=reporter,
            )
        )

    assert result == "OK"

    reporter.automating.assert_called_once()

    reporter.completed.assert_called_once()

    reporter.error.assert_not_called()


def test_runner_auto_envelope_reports_error():
    reporter = Mock()

    with patch.object(
        runner,
        "run_auto",
        side_effect=RuntimeError(
            "test failure"
        ),
    ):
        with pytest.raises(
            RuntimeError,
            match="test failure",
        ):
            runner.run_auto_with_qcc(
                object(),
                "33",
                {},
                ".",
                reporter=reporter,
            )

    reporter.automating.assert_called_once()
    reporter.error.assert_called_once()
    reporter.completed.assert_not_called()


def test_runner_declares_qcc_identity_arguments():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert '"--cliente-id"' in source
    assert '"--qcc-session-id"' in source

    assert (
        "QccPresentationReporter"
        in source
    )


def test_browser_infrastructure_remains_qcc_agnostic():
    connector_source = (
        CONNECTOR_PATH.read_text(
            encoding="utf-8"
        )
    )

    session_source = (
        SESSION_PATH.read_text(
            encoding="utf-8"
        )
    )

    assert "backend.qcc" not in (
        connector_source
    )

    assert "backend.qcc" not in (
        session_source
    )

    assert "QccPresentation" not in (
        connector_source
    )

    assert "QccPresentation" not in (
        session_source
    )


def test_qcc_reporter_crosses_real_process_boundary():
    import json
    import os
    import subprocess
    import sys

    from backend.qcc.bridge.server import (
        QccBridgeServer,
    )

    server = QccBridgeServer(
        port=0,
    )
    server.start()

    try:
        code = r'''
import os

from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)

reporter = QccPresentationReporter(
    session_id="qcc-cross-process-001",
    expedient_id=1842,
    client_id=321,
    procedure="TEST_CROSS_PROCESS",
    provider="MERCURIO",
    runtime="SELENIUMBASE_ASSISTED",
    bridge_base_url=os.environ[
        "QCC_TEST_BRIDGE_URL"
    ],
)

ok = reporter.automating(
    step="CHILD_PROCESS",
    progress=37,
    message="Estado publicado desde proceso hijo",
)

raise SystemExit(
    0 if ok else 7
)
'''

        env = dict(
            os.environ
        )

        env[
            "QCC_TEST_BRIDGE_URL"
        ] = (
            f"http://{server.host}:"
            f"{server.port}"
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
            ],
            cwd=str(
                Path.cwd()
            ),
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert (
            completed.returncode
            == 0
        ), (
            completed.stdout
            + completed.stderr
        )

        snapshot = (
            server.context_store
            .snapshot()
        )

        active = snapshot[
            "active_session"
        ]

        assert active is not None

        assert (
            active["session_id"]
            == "qcc-cross-process-001"
        )

        assert (
            active["runtime"]
            == "SELENIUMBASE_ASSISTED"
        )

        assert (
            active["current_step"]
            == "CHILD_PROCESS"
        )

        assert (
            active["progress"]
            == 37
        )

    finally:
        server.close()

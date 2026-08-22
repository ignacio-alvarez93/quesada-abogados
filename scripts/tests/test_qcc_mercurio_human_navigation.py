from pathlib import Path
from unittest.mock import (
    Mock,
    patch,
)

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)

CONNECTOR_PATH = Path(
    "backend/automation/connectors/mercurio_connector.py"
)

SESSION_PATH = Path(
    "backend/automation/seleniumbase_browser_session.py"
)


def test_human_dom_wait_reports_full_qcc_transition(
    tmp_path,
):
    reporter = Mock()

    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ):
        result = (
            runner.wait_for_human_navigation(
                object(),
                str(tmp_path),
                "Datos del presentador",
                "true",
                qcc_reporter=reporter,
                qcc_step=(
                    "CONTINUE_TO_PRESENTER"
                ),
                qcc_progress=68,
            )
        )

    assert result["ok"] is True

    assert (
        result["mode"]
        == "human_dom_detected"
    )

    reporter.waiting_user.assert_called_once_with(
        step="CONTINUE_TO_PRESENTER",
        progress=68,
        message=(
            "Acción manual requerida: "
            "Datos del presentador"
        ),
    )

    reporter.user_action_detected.assert_called_once_with(
        step="CONTINUE_TO_PRESENTER",
        progress=68,
        message=(
            "Acción manual detectada: "
            "Datos del presentador"
        ),
    )

    reporter.resuming.assert_called_once_with(
        step="CONTINUE_TO_PRESENTER",
        progress=68,
        message=(
            "Reanudando tras: "
            "Datos del presentador"
        ),
    )


def test_human_dom_wait_keeps_working_without_qcc(
    tmp_path,
):
    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ):
        result = (
            runner.wait_for_human_navigation(
                object(),
                str(tmp_path),
                "Pantalla destino",
                "true",
                qcc_reporter=None,
                qcc_step="TEST",
                qcc_progress=50,
            )
        )

    assert result["ok"] is True

    assert (
        result["mode"]
        == "human_dom_detected"
    )


def test_human_fallback_reports_transition_when_dom_confirms(
    tmp_path,
):
    reporter = Mock()

    with patch.object(
        runner,
        "wait_for_js",
        side_effect=[
            RuntimeError(
                "initial timeout"
            ),
            True,
        ],
    ):
        with patch(
            "builtins.input",
            return_value="",
        ):
            result = (
                runner.wait_for_human_navigation(
                    object(),
                    str(tmp_path),
                    "Pantalla destino",
                    "true",
                    timeout=1,
                    qcc_reporter=reporter,
                    qcc_step="FALLBACK_TEST",
                    qcc_progress=40,
                )
            )

    assert result["ok"] is True

    assert (
        result["mode"]
        == "human_enter_fallback_confirmed"
    )

    reporter.waiting_user.assert_called_once()
    reporter.user_action_detected.assert_called_once()
    reporter.resuming.assert_called_once()


def test_run_auto_threads_reporter_into_dom_human_pauses():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "def run_auto("
        in source
    )

    assert (
        "reporter=reporter"
        in source
    )

    required_steps = (
        "CERTIFICATE_SELECTION",
        "PROCEDURE_SELECTION",
        "CONTINUE_TO_APPLICANT",
        "CONTINUE_TO_FAMILY_MEMBER",
        "CONTINUE_TO_PRESENTER",
    )

    for step in required_steps:
        assert step in source


def test_qcc_does_not_automate_sensitive_continue_actions():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    protected_text = (
        "El usuario pulsa CONTINUAR "
        "manualmente"
    )

    assert protected_text in source

    assert (
        "NO Selenium click"
        in source
    )

    assert (
        "NO CDP click"
        in source
    )


def test_browser_layers_remain_qcc_free():
    connector = (
        CONNECTOR_PATH.read_text(
            encoding="utf-8"
        )
    )

    session = (
        SESSION_PATH.read_text(
            encoding="utf-8"
        )
    )

    assert "backend.qcc" not in connector
    assert "backend.qcc" not in session

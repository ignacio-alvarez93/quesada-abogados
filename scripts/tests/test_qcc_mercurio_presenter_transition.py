from pathlib import Path
from unittest.mock import (
    Mock,
    patch,
)

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


def test_post_presenter_gate_is_structural():
    ready_js = (
        runner
        .POST_PRESENTER_NOTIFICATION_READY_JS
    )

    assert (
        "tab-datos_notificacion"
        in ready_js
    )

    assert (
        "btnConcluirSup"
        in ready_js
    )

    assert (
        "tab-datos_presentador"
        in ready_js
    )

    assert (
        "r-tabs-state-active"
        in ready_js
    )

    assert (
        "getComputedStyle"
        in ready_js
    )

    assert (
        "getClientRects"
        in ready_js
    )


def test_presenter_continue_waits_for_dom(
    tmp_path,
):
    reporter = Mock()

    expected = {
        "ok": True,
        "mode":
            "human_dom_detected",
    }

    with patch.object(
        runner,
        "wait_for_human_navigation",
        return_value=expected,
    ) as wait:
        result = (
            runner
            .click_continuar_presentador(
                object(),
                str(tmp_path),
                reporter=reporter,
            )
        )

    assert result is expected

    args = wait.call_args.args
    kwargs = wait.call_args.kwargs

    assert (
        args[2]
        == (
            "Domicilio de notificación / "
            "CONCLUIR"
        )
    )

    assert (
        args[3]
        == runner
        .POST_PRESENTER_NOTIFICATION_READY_JS
    )

    assert (
        kwargs["qcc_reporter"]
        is reporter
    )

    assert (
        kwargs["qcc_step"]
        == "CONTINUE_FROM_PRESENTER"
    )

    assert (
        kwargs["qcc_progress"]
        == 78
    )

    assert (
        kwargs["fallback_prompt"]
    )


def test_presenter_continue_contains_no_browser_click():
    source = (
        RUNNER_PATH.read_text(
            encoding="utf-8"
        )
    )

    start = source.index(
        "def click_continuar_presentador("
    )

    end = source.index(
        "\ndef pause_humana_final_presentacion(",
        start,
    )

    block = source[
        start:end
    ]

    forbidden = (
        "browser.click(",
        ".uc_click(",
        "execute_script(",
        "send_keys(",
    )

    for token in forbidden:
        assert token not in block

    assert "NO Selenium click" in block
    assert "NO CDP click" in block


def test_final_pause_exposes_waiting_user_to_qcc(
    tmp_path,
):
    reporter = Mock()

    with patch(
        "builtins.input",
        return_value="",
    ):
        runner.pause_humana_final_presentacion(
            object(),
            str(tmp_path),
            reporter=reporter,
        )

    reporter.waiting_user.assert_called_once_with(
        step="FINAL_REVIEW",
        progress=82,
        message=(
            "Revisa la solicitud y pulsa "
            "CONCLUIR manualmente en Mercurio"
        ),
    )

    reporter.resuming.assert_called_once_with(
        step="FINAL_REVIEW",
        progress=85,
        message=(
            "Finalización manual confirmada "
            "por el usuario"
        ),
    )


def test_final_pause_still_works_without_qcc(
    tmp_path,
):
    with patch(
        "builtins.input",
        return_value="",
    ):
        runner.pause_humana_final_presentacion(
            object(),
            str(tmp_path),
            reporter=None,
        )


def test_run_auto_threads_reporter_to_final_human_steps():
    source = (
        RUNNER_PATH.read_text(
            encoding="utf-8"
        )
    )

    start = source.index(
        "def run_auto("
    )

    end = source.index(
        "\ndef main(",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "click_continuar_presentador("
        in block
    )

    assert (
        "pause_humana_final_presentacion("
        in block
    )

    assert (
        block.count(
            "reporter=reporter"
        )
        >= 2
    )

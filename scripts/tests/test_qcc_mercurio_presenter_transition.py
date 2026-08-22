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

    ready_js = args[3]

    assert (
        runner
        .POST_PRESENTER_NOTIFICATION_READY_JS
        in ready_js
    )

    assert (
        "presentacionTelematicaDocumentacion.html"
        in ready_js
    )

    assert (
        "#listaIdsDocOb"
        in ready_js
    )

    assert (
        "#tabla_datos_adj"
        in ready_js
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


def test_final_pause_delegates_to_dom_wait(
    tmp_path,
):
    reporter = Mock()

    expected = {
        "ok": True,
        "mode": "human_dom_detected",
    }

    with patch.object(
        runner,
        "wait_for_human_navigation",
        return_value=expected,
    ) as wait:
        result = (
            runner.pause_humana_final_presentacion(
                object(),
                str(tmp_path),
                reporter=reporter,
            )
        )

    assert result is expected

    kwargs = wait.call_args.kwargs

    assert kwargs[
        "qcc_reporter"
    ] is reporter

    assert kwargs[
        "qcc_step"
    ] == "FINAL_REVIEW"

    assert kwargs[
        "qcc_progress"
    ] == 82


def test_final_pause_still_works_without_qcc(
    tmp_path,
):
    expected = {
        "ok": True,
        "mode": "human_dom_detected",
    }

    with patch.object(
        runner,
        "wait_for_human_navigation",
        return_value=expected,
    ):
        result = (
            runner.pause_humana_final_presentacion(
                object(),
                str(tmp_path),
                reporter=None,
            )
        )

    assert result is expected


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



def test_presenter_transition_accepts_downstream_document_page():
    ready_js = (
        runner
        ._presenter_transition_ready_js()
    )

    assert (
        runner
        .POST_PRESENTER_NOTIFICATION_READY_JS
        in ready_js
    )

    assert (
        "presentacionTelematicaDocumentacion.html"
        in ready_js
    )

    assert (
        "#docAdjuntarAdjuntos"
        in ready_js
    )

    assert (
        "#continuaNot"
        in ready_js
    )

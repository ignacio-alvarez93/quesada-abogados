from pathlib import Path
from unittest.mock import (
    Mock,
    patch,
)

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


def _preform_source():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "MERCURIO_MODE_ACCESS_READY_JS"
    )

    end = source.index(
        "\ndef pause_supuesto(",
        start,
    )

    return source[start:end]



def test_preform_restores_safe_automated_navigation():
    block = _preform_source()

    required = (
        'continuar(\'INI\');',
        'validarYEnviar(\'AB\');',
        'mostrarOpcion();',
        'irOpcion();',
        'click_js(',
        '".mdCer"',
    )

    for token in required:
        assert token in block


def test_start_continue_is_automatic(
    tmp_path,
):
    reporter = Mock()

    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ) as wait:
        with patch.object(
            runner,
            "js",
            return_value=True,
        ) as js_call:
            result = (
                runner.step_continuar_inicial(
                    object(),
                    str(tmp_path),
                    reporter=reporter,
                )
            )

    assert result["ok"] is True
    assert result["mode"] == "automated_js"

    wait.assert_called_once()

    assert (
        "typeof continuar"
        in wait.call_args.args[1]
    )

    js_call.assert_called_once()

    assert (
        "continuar('INI')"
        in js_call.call_args.args[1]
    )


def test_certificate_access_automates_abogacia_then_waits_human_certificate(
    tmp_path,
):
    reporter = Mock()

    expected = {
        "ok": True,
        "mode": "human_dom_detected",
    }

    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ) as wait_js:
        with patch.object(
            runner,
            "js",
            return_value=True,
        ) as js_call:
            with patch.object(
                runner,
                "wait_for_human_navigation",
                return_value=expected,
            ) as wait_human:
                result = runner.pause_certificado(
                    object(),
                    str(tmp_path),
                    reporter=reporter,
                )

    assert result is expected

    assert (
        "validarYEnviar"
        in wait_js.call_args.args[1]
    )

    assert (
        "validarYEnviar('AB')"
        in js_call.call_args.args[1]
    )

    args = wait_human.call_args.args
    kwargs = wait_human.call_args.kwargs

    assert (
        "entradaMercurio.html"
        in args[3]
    )

    assert (
        kwargs["qcc_step"]
        == "CERTIFICATE_SELECTION"
    )


def test_new_request_restores_safe_automatic_preform(
    tmp_path,
):
    reporter = Mock()
    browser = object()

    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ):
        with patch.object(
            runner,
            "js",
            return_value=True,
        ) as js_call:
            with patch.object(
                runner,
                "click_js",
                return_value=True,
            ) as click:
                with patch.object(
                    runner,
                    "save_page_source",
                    return_value="capture.html",
                ):
                    result = (
                        runner
                        .step_presentar_nueva_solicitud(
                            browser,
                            "33",
                            str(tmp_path),
                            reporter=reporter,
                        )
                    )

    assert result["ok"] is True
    assert (
        result["mode"]
        == "automated_preform"
    )

    scripts = [
        call.args[1]
        for call in js_call.call_args_list
    ]

    assert any(
        "mostrarOpcion()"
        in script
        for script in scripts
    )

    assert any(
        "bscIniciales"
        in script
        and "provincia"
        in script
        for script in scripts
    )

    assert any(
        "irOpcion()"
        in script
        for script in scripts
    )

    click.assert_called_once_with(
        browser,
        ".mdCer",
    )


def test_new_request_does_not_block_on_model_selection_after_continue(
    tmp_path,
):
    reporter = Mock()
    browser = object()

    with patch.object(
        runner,
        "wait_for_js",
        return_value=True,
    ) as wait:
        with patch.object(
            runner,
            "js",
            return_value=True,
        ):
            with patch.object(
                runner,
                "click_js",
                return_value=True,
            ):
                with patch.object(
                    runner,
                    "save_page_source",
                    return_value="capture.html",
                ):
                    result = (
                        runner
                        .step_presentar_nueva_solicitud(
                            browser,
                            "33",
                            str(tmp_path),
                            reporter=reporter,
                        )
                    )

    assert result["ok"] is True
    assert result["mode"] == "automated_preform"

    conditions = [
        call.args[1]
        for call in wait.call_args_list
        if len(call.args) >= 2
    ]

    assert not any(
        condition
        == runner.MERCURIO_MODEL_SELECTION_READY_JS
        for condition in conditions
    )

def test_run_auto_no_longer_calls_automated_abogacia_step():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def run_auto("
    )

    end = source.index(
        "\ndef main(",
        start,
    )

    block = source[start:end]

    assert (
        "step_continuar_abogacia("
        not in block
    )

    assert (
        "step_continuar_inicial("
        in block
    )

    assert (
        "pause_certificado("
        in block
    )

    assert (
        "step_presentar_nueva_solicitud("
        in block
    )

    assert (
        block.count(
            "reporter=reporter"
        )
        >= 5
    )



def test_run_auto_stops_when_initial_navigation_fails(
    tmp_path,
):
    blocked = {
        "ok": False,
        "mode": "human_enter_fallback_not_confirmed",
    }

    with patch.object(
        runner,
        "write_log",
    ):
        with patch.object(
            runner,
            "step_continuar_inicial",
            return_value=blocked,
        ):
            with patch.object(
                runner,
                "pause_certificado",
            ) as certificate:
                result = runner.run_auto(
                    object(),
                    "33",
                    {},
                    str(tmp_path),
                )

    assert result is blocked
    certificate.assert_not_called()


def test_run_auto_stops_when_certificate_navigation_fails(
    tmp_path,
):
    ok = {
        "ok": True,
        "mode": "human_dom_detected",
    }

    blocked = {
        "ok": False,
        "mode": "human_enter_fallback_not_confirmed",
    }

    with patch.object(
        runner,
        "write_log",
    ):
        with patch.object(
            runner,
            "step_continuar_inicial",
            return_value=ok,
        ):
            with patch.object(
                runner,
                "pause_certificado",
                return_value=blocked,
            ):
                with patch.object(
                    runner,
                    "step_presentar_nueva_solicitud",
                ) as presentation:
                    result = runner.run_auto(
                        object(),
                        "33",
                        {},
                        str(tmp_path),
                    )

    assert result is blocked
    presentation.assert_not_called()


def test_run_auto_stops_when_options_navigation_fails(
    tmp_path,
):
    ok = {
        "ok": True,
        "mode": "human_dom_detected",
    }

    blocked = {
        "ok": False,
        "mode": "human_enter_fallback_not_confirmed",
    }

    with patch.object(
        runner,
        "write_log",
    ):
        with patch.object(
            runner,
            "step_continuar_inicial",
            return_value=ok,
        ):
            with patch.object(
                runner,
                "pause_certificado",
                return_value=ok,
            ):
                with patch.object(
                    runner,
                    "step_presentar_nueva_solicitud",
                    return_value=blocked,
                ):
                    with patch.object(
                        runner,
                        "pause_supuesto",
                    ) as procedure:
                        result = runner.run_auto(
                            object(),
                            "33",
                            {},
                            str(tmp_path),
                        )

    assert result is blocked
    procedure.assert_not_called()

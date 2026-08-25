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


def test_preform_contains_no_automated_navigation():
    block = _preform_source()

    forbidden = (
        'js(browser, "continuar(\'INI\');")',
        'js(browser, "validarYEnviar(\'AB\');")',
        'js(browser, "mostrarOpcion();")',
        'js(browser, "irOpcion();")',
        'click_js(browser, ".mdCer")',
    )

    for token in forbidden:
        assert token not in block


def test_start_continue_delegates_to_human_wait(
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
        result = runner.step_continuar_inicial(
            object(),
            str(tmp_path),
            reporter=reporter,
        )

    assert result is expected

    args = wait.call_args.args
    kwargs = wait.call_args.kwargs

    assert (
        "modoAcceso.html"
        in args[3]
    )

    assert (
        kwargs["qcc_reporter"]
        is reporter
    )

    assert (
        kwargs["qcc_step"]
        == "CONTINUE_FROM_START"
    )


def test_certificate_access_waits_for_entry_page(
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
        result = runner.pause_certificado(
            object(),
            str(tmp_path),
            reporter=reporter,
        )

    assert result is expected

    args = wait.call_args.args
    kwargs = wait.call_args.kwargs

    assert (
        "entradaMercurio.html"
        in args[3]
    )

    assert (
        "mostrarOpcion"
        in args[3]
    )

    assert (
        kwargs["qcc_step"]
        == "CERTIFICATE_SELECTION"
    )


def test_new_request_only_automates_preparation(
    tmp_path,
):
    reporter = Mock()

    waits = [
        {
            "ok": True,
            "mode": "human_dom_detected",
        },
        {
            "ok": True,
            "mode": "human_dom_detected",
        },
    ]

    with patch.object(
        runner,
        "wait_for_human_navigation",
        side_effect=waits,
    ) as wait:
        with patch.object(
            runner,
            "js",
            return_value=True,
        ) as js_call:
            with patch.object(
                runner,
                "save_page_source",
                return_value="capture.html",
            ):
                result = (
                    runner
                    .step_presentar_nueva_solicitud(
                        object(),
                        "33",
                        str(tmp_path),
                        reporter=reporter,
                    )
                )

    assert result["ok"] is True

    assert wait.call_count == 2
    assert js_call.call_count == 1

    preparation = (
        js_call.call_args.args[1]
    )

    assert "bscIniciales" in preparation
    assert "provincia" in preparation

    assert "irOpcion()" not in preparation
    assert "mostrarOpcion()" not in preparation

    second_ready_js = (
        wait.call_args_list[1]
        .args[3]
    )

    assert 'input[name="datosForL"]' in second_ready_js
    assert ".mdCer" in second_ready_js


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

from pathlib import Path
from unittest.mock import (
    Mock,
    patch,
)

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


def test_document_ready_gate_uses_real_mercurio_controls():
    ready_js = (
        runner
        .DOCUMENT_UPLOAD_READY_JS
    )

    required = (
        "tbAdjuntos",
        "fileDocumentoAdjuntos",
        "addDou",
        "docAdjuntarAdjuntos",
        "getComputedStyle",
        "getClientRects",
    )

    for token in required:
        assert token in ready_js


def test_final_pause_waits_for_document_dom(
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
            .pause_humana_final_presentacion(
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
        == "Documentación de la solicitud"
    )

    assert (
        args[3]
        == runner.DOCUMENT_UPLOAD_READY_JS
    )

    assert (
        kwargs["qcc_reporter"]
        is reporter
    )

    assert (
        kwargs["qcc_step"]
        == "FINAL_REVIEW"
    )

    assert (
        kwargs["qcc_progress"]
        == 82
    )


def test_final_pause_leaves_qcc_waiting_for_documents(
    tmp_path,
):
    reporter = Mock()

    with patch.object(
        runner,
        "wait_for_human_navigation",
        return_value={
            "ok": True,
            "mode":
                "human_dom_detected",
        },
    ):
        runner.pause_humana_final_presentacion(
            object(),
            str(tmp_path),
            reporter=reporter,
        )

    reporter.waiting_user.assert_called_once_with(
        step="DOCUMENTS_READY",
        progress=88,
        message=(
            "Pantalla documental preparada; "
            "documentación pendiente"
        ),
    )


def test_final_pause_no_direct_input_remains():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def pause_humana_final_presentacion("
    )

    end = source.index(
        "# =============================================================================\n"
        "# SUBIDA DOCUMENTAL ASISTIDA - PARA PRESENTAR",
        start,
    )

    block = source[
        start:end
    ]

    assert "input(" not in block

    assert (
        "wait_for_human_navigation("
        in block
    )


def test_run_auto_does_not_start_document_upload():
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

    block = source[
        start:end
    ]

    assert (
        "upload_documentos_mercurio_asistido("
        not in block
    )


def test_auto_envelope_does_not_mark_presentation_completed():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def run_auto_with_qcc("
    )

    end = source.index(
        "\ndef normalize(",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        '"completed"'
        not in block
    )


def test_interactive_human_command_passes_qcc_reporter():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert '''pause_humana_final_presentacion(
                browser,
                session_dir,
                reporter=qcc_reporter,
            )''' in source



def test_final_pause_skips_wait_when_document_page_is_already_ready(
    tmp_path,
):
    from types import SimpleNamespace

    reporter = Mock()

    document_state = SimpleNamespace(
        page_detected=True,
        contract_compatible=True,
        documentation_complete=False,
    )

    with patch(
        (
            "backend.automation."
            "mercurio_document_dom_reader."
            "read_mercurio_document_state"
        ),
        return_value=document_state,
    ):
        with patch.object(
            runner,
            "wait_for_human_navigation",
        ) as wait:
            result = (
                runner
                .pause_humana_final_presentacion(
                    object(),
                    str(tmp_path),
                    reporter=reporter,
                )
            )

    wait.assert_not_called()

    assert result == {
        "ok": True,
        "mode":
            "document_dom_already_ready",
        "label":
            "Documentación de la solicitud",
    }

    reporter.waiting_user.assert_called_once_with(
        step="DOCUMENTS_READY",
        progress=88,
        message=(
            "Pantalla documental preparada; "
            "documentación pendiente"
        ),
    )


def test_document_page_fast_path_requires_full_dom_contract(
    tmp_path,
):
    from types import SimpleNamespace

    reporter = Mock()

    invalid_state = SimpleNamespace(
        page_detected=True,
        contract_compatible=False,
        documentation_complete=False,
    )

    expected = {
        "ok": True,
        "mode":
            "human_dom_detected",
    }

    with patch(
        (
            "backend.automation."
            "mercurio_document_dom_reader."
            "read_mercurio_document_state"
        ),
        return_value=invalid_state,
    ):
        with patch.object(
            runner,
            "wait_for_human_navigation",
            return_value=expected,
        ) as wait:
            result = (
                runner
                .pause_humana_final_presentacion(
                    object(),
                    str(tmp_path),
                    reporter=reporter,
                )
            )

    wait.assert_called_once()

    assert result is expected

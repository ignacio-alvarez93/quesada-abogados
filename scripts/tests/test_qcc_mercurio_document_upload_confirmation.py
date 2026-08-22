from pathlib import Path
from types import SimpleNamespace

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


def doc(
    filename,
    code,
    hash_value,
):
    return SimpleNamespace(
        filename=filename,
        code=code,
        hash_value=hash_value,
    )


def state(
    documents,
    *,
    page_detected=True,
    contract_compatible=True,
):
    return SimpleNamespace(
        page_detected=page_detected,
        contract_compatible=(
            contract_compatible
        ),
        uploaded_documents=tuple(
            documents
        ),
    )


def test_count_requires_filename_code_and_hash():
    current = state(
        [
            doc(
                "pasaporte.pdf",
                "1",
                "HASH-1",
            ),
            doc(
                "pasaporte.pdf",
                "39",
                "HASH-2",
            ),
            doc(
                "pasaporte.pdf",
                "1",
                "",
            ),
        ]
    )

    assert (
        runner
        ._count_confirmed_mercurio_uploads(
            current,
            filename="pasaporte.pdf",
            code="1",
        )
        == 1
    )


def test_count_normalizes_windows_path_to_filename():
    current = state(
        [
            doc(
                "seguro.pdf",
                "47",
                "HASH",
            )
        ]
    )

    assert (
        runner
        ._count_confirmed_mercurio_uploads(
            current,
            filename=(
                r"C:\pruebas\seguro.pdf"
            ),
            code="47",
        )
        == 1
    )


def test_wait_confirms_new_matching_row():
    current = state(
        [
            doc(
                "seguro.pdf",
                "47",
                "HASH",
            )
        ]
    )

    result = (
        runner
        .wait_for_mercurio_document_upload(
            object(),
            filename="seguro.pdf",
            code="47",
            baseline_count=0,
            timeout=0,
            poll_interval=0,
            state_reader=lambda browser:
                current,
        )
    )

    assert result["ok"] is True

    assert (
        result["mode"]
        == "document_dom_confirmed"
    )

    assert (
        result["current_count"]
        == 1
    )


def test_wait_does_not_accept_preexisting_matching_row():
    current = state(
        [
            doc(
                "seguro.pdf",
                "47",
                "HASH",
            )
        ]
    )

    result = (
        runner
        .wait_for_mercurio_document_upload(
            object(),
            filename="seguro.pdf",
            code="47",
            baseline_count=1,
            timeout=0,
            poll_interval=0,
            state_reader=lambda browser:
                current,
        )
    )

    assert result["ok"] is False

    assert (
        result["mode"]
        == "document_dom_timeout"
    )


def test_wait_ignores_optional_wrong_code():
    current = state(
        [
            doc(
                "seguro.pdf",
                "51",
                "HASH",
            )
        ]
    )

    result = (
        runner
        .wait_for_mercurio_document_upload(
            object(),
            filename="seguro.pdf",
            code="47",
            baseline_count=0,
            timeout=0,
            poll_interval=0,
            state_reader=lambda browser:
                current,
        )
    )

    assert result["ok"] is False


def test_wait_requires_nonempty_hash():
    current = state(
        [
            doc(
                "seguro.pdf",
                "47",
                "",
            )
        ]
    )

    result = (
        runner
        .wait_for_mercurio_document_upload(
            object(),
            filename="seguro.pdf",
            code="47",
            baseline_count=0,
            timeout=0,
            poll_interval=0,
            state_reader=lambda browser:
                current,
        )
    )

    assert result["ok"] is False


def test_wait_requires_document_contract():
    current = state(
        [
            doc(
                "seguro.pdf",
                "47",
                "HASH",
            )
        ],
        contract_compatible=False,
    )

    result = (
        runner
        .wait_for_mercurio_document_upload(
            object(),
            filename="seguro.pdf",
            code="47",
            baseline_count=0,
            timeout=0,
            poll_interval=0,
            state_reader=lambda browser:
                current,
        )
    )

    assert result["ok"] is False


def test_upload_flow_has_no_per_document_enter_confirmation():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def upload_documentos_mercurio_asistido("
    )

    end = source.index(
        "\ndef run_auto_and_documents_with_qcc(",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "Pulsa ENTER aquí cuando ESTE "
        "documento esté adjuntado"
        not in block
    )

    assert (
        "wait_for_mercurio_document_upload("
        in block
    )

    assert (
        "get_mercurio_document_upload_baseline("
        in block
    )


def test_confirmation_helper_has_no_browser_mutation():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def _count_confirmed_mercurio_uploads("
    )

    end = source.index(
        "\ndef upload_documentos_mercurio_asistido(",
        start,
    )

    block = source[
        start:end
    ]

    forbidden = (
        "click_js(",
        ".click(",
        "dispatchEvent(",
        "send_keys(",
        "execute_script(",
        "continuarPre(",
    )

    for token in forbidden:
        assert token not in block


def test_upload_flow_executes_dom_confirmation_path(
    tmp_path,
):
    from unittest.mock import (
        Mock,
        patch,
    )

    path = (
        tmp_path
        / "pasaporte_prueba.pdf"
    )

    reporter = Mock()

    action = {
        "action":
            "DOCUMENT_PREPARE",
        "payload": {
            "document_index":
                1,
        },
    }

    confirmation = {
        "ok": True,
        "mode":
            "document_dom_confirmed",
        "filename":
            path.name,
        "code":
            "1",
        "baseline_count":
            0,
        "current_count":
            1,
    }

    with patch.object(
        runner,
        "list_documentos_para_presentar",
        return_value=[
            path,
        ],
    ):
        with patch.object(
            runner,
            "wait_for_qcc_document_action",
            return_value=action,
        ):
            with patch.object(
                runner,
                "get_mercurio_document_upload_baseline",
                return_value=0,
            ):
                with patch.object(
                    runner,
                    "copy_text_to_clipboard",
                    return_value=True,
                ):
                    with patch.object(
                        runner,
                        "preparar_documento_mercurio",
                        return_value=True,
                    ):
                        with patch.object(
                            runner,
                            "wait_for_mercurio_document_upload",
                            return_value=confirmation,
                        ):
                            result = (
                                runner
                                .upload_documentos_mercurio_asistido(
                                    object(),
                                    tmp_path,
                                    {},
                                    str(
                                        tmp_path
                                    ),
                                    reporter=reporter,
                                    action_client=object(),
                                )
                            )

    assert result is True

    uploaded_calls = [
        call
        for call
        in reporter
        .user_action_detected
        .call_args_list
        if (
            call.kwargs.get(
                "step"
            )
            == "DOCUMENT_UPLOADED"
        )
    ]

    assert len(
        uploaded_calls
    ) == 1


def test_upload_flow_baseline_error_is_controlled(
    tmp_path,
):
    from unittest.mock import (
        Mock,
        patch,
    )

    path = (
        tmp_path
        / "pasaporte_prueba.pdf"
    )

    reporter = Mock()

    action = {
        "action":
            "DOCUMENT_PREPARE",
        "payload": {
            "document_index":
                1,
        },
    }

    with patch.object(
        runner,
        "list_documentos_para_presentar",
        return_value=[
            path,
        ],
    ):
        with patch.object(
            runner,
            "wait_for_qcc_document_action",
            return_value=action,
        ):
            with patch.object(
                runner,
                "get_mercurio_document_upload_baseline",
                side_effect=RuntimeError(
                    "offline baseline error"
                ),
            ):
                result = (
                    runner
                    .upload_documentos_mercurio_asistido(
                        object(),
                        tmp_path,
                        {},
                        str(
                            tmp_path
                        ),
                        reporter=reporter,
                        action_client=object(),
                    )
                )

    assert result is False

    reporter.error.assert_called_once()

    assert (
        reporter
        .error
        .call_args
        .kwargs[
            "step"
        ]
        == "DOCUMENT_BASELINE_ERROR"
    )


def test_upload_flow_uses_document_progress_not_undefined_progress():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def upload_documentos_mercurio_asistido("
    )

    end = source.index(
        "\ndef run_auto_and_documents_with_qcc(",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "document_progress = min("
        in block
    )

    assert (
        "progress=document_progress"
        in block
    )

    assert (
        "progress=progress"
        not in block
    )

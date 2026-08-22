from pathlib import Path
from types import SimpleNamespace
from unittest.mock import (
    Mock,
    patch,
)

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


class FakeActionClient:
    def __init__(
        self,
        actions,
    ):
        self.actions = list(
            actions
        )

    def consume_next(
        self,
    ):
        if not self.actions:
            return None

        return self.actions.pop(
            0
        )


def test_build_action_client_uses_session_id(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id="qcc-test-001"
    )

    client = (
        runner.build_qcc_action_client(
            args,
            str(tmp_path),
        )
    )

    assert client is not None

    assert (
        client.session_id
        == "qcc-test-001"
    )


def test_build_action_client_remains_optional(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id=""
    )

    assert (
        runner.build_qcc_action_client(
            args,
            str(tmp_path),
        )
        is None
    )


def test_waiter_consumes_documents_start(
    tmp_path,
):
    reporter = Mock()

    client = FakeActionClient(
        [
            {
                "action_id": 7,
                "session_id":
                    "qcc-test-001",
                "action":
                    "DOCUMENTS_START",
                "payload": {},
            }
        ]
    )

    result = (
        runner.wait_for_qcc_documents_start(
            client,
            str(tmp_path),
            reporter=reporter,
            poll_interval=0,
        )
    )

    assert (
        result["action"]
        == "DOCUMENTS_START"
    )

    reporter.user_action_detected.assert_called_once_with(
        step="DOCUMENTS_START",
        progress=89,
        message=(
            "Inicio documental solicitado "
            "desde QCC"
        ),
    )

    reporter.resuming.assert_called_once_with(
        step="DOCUMENTS_RUNNING",
        progress=90,
        message=(
            "Iniciando subida documental "
            "asistida"
        ),
    )


def test_waiter_ignores_unrelated_action(
    tmp_path,
):
    client = FakeActionClient(
        [
            {
                "action_id": 1,
                "action":
                    "DOCUMENT_SKIP",
                "payload": {
                    "document_index": 1,
                },
            },
            {
                "action_id": 2,
                "action":
                    "DOCUMENTS_START",
                "payload": {},
            },
        ]
    )

    result = (
        runner.wait_for_qcc_documents_start(
            client,
            str(tmp_path),
            poll_interval=0,
        )
    )

    assert result[
        "action_id"
    ] == 2


def test_start_confirmation_input_is_removed():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "Iniciar preparación asistida?"
        not in source
    )


def test_orchestrator_orders_auto_action_upload(
    tmp_path,
):
    order = []

    with (
        patch.object(
            runner,
            "run_auto_with_qcc",
            side_effect=lambda *a, **k: (
                order.append(
                    "auto"
                )
                or True
            ),
        ),
        patch.object(
            runner,
            "wait_for_qcc_documents_start",
            side_effect=lambda *a, **k: (
                order.append(
                    "action"
                )
                or {
                    "action":
                        "DOCUMENTS_START"
                }
            ),
        ),
        patch.object(
            runner,
            "upload_documentos_mercurio_asistido",
            side_effect=lambda *a, **k: (
                order.append(
                    "upload"
                )
                or True
            ),
        ),
    ):
        result = (
            runner
            .run_auto_and_documents_with_qcc(
                object(),
                "33",
                {},
                tmp_path,
                str(tmp_path),
                reporter=Mock(),
                action_client=Mock(),
            )
        )

    assert result is True

    assert order == [
        "auto",
        "action",
        "upload",
    ]


def test_orchestrator_does_not_upload_without_action_client(
    tmp_path,
):
    with (
        patch.object(
            runner,
            "run_auto_with_qcc",
            return_value="AUTO_OK",
        ),
        patch.object(
            runner,
            "upload_documentos_mercurio_asistido",
        ) as upload,
    ):
        result = (
            runner
            .run_auto_and_documents_with_qcc(
                object(),
                "33",
                {},
                tmp_path,
                str(tmp_path),
                action_client=None,
            )
        )

    assert result == "AUTO_OK"

    upload.assert_not_called()


def test_docs_command_is_removed():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        'print("  docs       -> '
        'subida documental asistida")'
        not in source
    )

    assert (
        'elif cmd in ("docs", "documentos", "upload"):'
        not in source
    )


def test_two_auto_paths_use_document_orchestrator():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "run_auto_and_documents_with_qcc("
        )
        == 3
    )

    assert (
        source.count(
            "action_client=qcc_action_client"
        )
        == 2
    )


def test_qcc_waiter_does_not_control_browser():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def wait_for_qcc_documents_start("
    )

    end = source.index(
        "# =============================================================================\n"
        "# SUBIDA DOCUMENTAL ASISTIDA",
        start,
    )

    block = source[
        start:end
    ]

    forbidden = (
        "click_js(",
        "execute_script",
        "browser.click",
        "SeleniumBaseBrowserSession",
    )

    for token in forbidden:
        assert token not in block


def test_main_resolves_documents_dir_before_auto():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    resolve_pos = source.index(
        "documentos_dir = resolve_para_presentar_dir("
    )

    auto_pos = source.index(
        "if args.auto:"
    )

    assert resolve_pos < auto_pos


def test_orchestrator_stops_when_documents_dir_missing(
    tmp_path,
):
    reporter = Mock()

    with (
        patch.object(
            runner,
            "run_auto_with_qcc",
            return_value="AUTO_OK",
        ),
        patch.object(
            runner,
            "wait_for_qcc_documents_start",
        ) as wait_action,
        patch.object(
            runner,
            "upload_documentos_mercurio_asistido",
        ) as upload,
    ):
        result = (
            runner
            .run_auto_and_documents_with_qcc(
                object(),
                "33",
                {},
                None,
                str(tmp_path),
                reporter=reporter,
                action_client=Mock(),
            )
        )

    assert result == "AUTO_OK"

    wait_action.assert_not_called()
    upload.assert_not_called()

    reporter.error.assert_called_once_with(
        step="DOCUMENTS_FOLDER_MISSING",
        progress=88,
        message=(
            "No se ha encontrado la carpeta "
            "PARA PRESENTAR"
        ),
    )

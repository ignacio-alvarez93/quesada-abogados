from pathlib import Path
from unittest.mock import Mock

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


def test_document_waiter_publishes_context_and_prepare(
    tmp_path,
):
    reporter = Mock()

    client = FakeActionClient(
        [
            {
                "action":
                    "DOCUMENT_PREPARE",
                "payload": {
                    "document_index": 2,
                },
            }
        ]
    )

    result = (
        runner.wait_for_qcc_document_action(
            client,
            document_index=2,
            document_total=6,
            document_name="pasaporte.pdf",
            proposed_code="1",
            session_dir=str(tmp_path),
            reporter=reporter,
            poll_interval=0,
        )
    )

    assert (
        result["action"]
        == "DOCUMENT_PREPARE"
    )

    reporter.waiting_user.assert_called_once()

    kwargs = (
        reporter
        .waiting_user
        .call_args
        .kwargs
    )

    assert (
        kwargs["step"]
        == "DOCUMENT_READY"
    )

    assert (
        kwargs["event_details"]
        == {
            "document_index": 2,
            "document_total": 6,
            "document_name":
                "pasaporte.pdf",
            "document_type_code":
                "1",
        }
    )


def test_document_waiter_accepts_skip(
    tmp_path,
):
    client = FakeActionClient(
        [
            {
                "action":
                    "DOCUMENT_SKIP",
                "payload": {
                    "document_index": 1,
                },
            }
        ]
    )

    result = (
        runner.wait_for_qcc_document_action(
            client,
            document_index=1,
            document_total=3,
            document_name="tasa.pdf",
            proposed_code="43",
            session_dir=str(tmp_path),
            poll_interval=0,
        )
    )

    assert (
        result["action"]
        == "DOCUMENT_SKIP"
    )


def test_document_waiter_accepts_force_type(
    tmp_path,
):
    client = FakeActionClient(
        [
            {
                "action":
                    "DOCUMENT_FORCE_TYPE",
                "payload": {
                    "document_index": 3,
                    "value": "30",
                },
            }
        ]
    )

    result = (
        runner.wait_for_qcc_document_action(
            client,
            document_index=3,
            document_total=4,
            document_name="certificado.pdf",
            proposed_code="999",
            session_dir=str(tmp_path),
            poll_interval=0,
        )
    )

    assert (
        result["payload"]["value"]
        == "30"
    )


def test_document_waiter_ignores_wrong_index(
    tmp_path,
):
    client = FakeActionClient(
        [
            {
                "action":
                    "DOCUMENT_SKIP",
                "payload": {
                    "document_index": 1,
                },
            },
            {
                "action":
                    "DOCUMENT_PREPARE",
                "payload": {
                    "document_index": 2,
                },
            },
        ]
    )

    result = (
        runner.wait_for_qcc_document_action(
            client,
            document_index=2,
            document_total=2,
            document_name="doc.pdf",
            proposed_code="999",
            session_dir=str(tmp_path),
            poll_interval=0,
        )
    )

    assert (
        result["action"]
        == "DOCUMENT_PREPARE"
    )


def test_console_document_decision_input_removed():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "Preparar este documento?"
        not in source
    )


def test_upload_accepts_qcc_dependencies():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def upload_documentos_mercurio_asistido("
    )

    block = source[
        start:start + 400
    ]

    assert "reporter=None" in block
    assert "action_client=None" in block


def test_document_waiter_has_no_browser_control():
    source = RUNNER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def wait_for_qcc_document_action("
    )

    end = source.index(
        "def upload_documentos_mercurio_asistido(",
        start,
    )

    block = source[
        start:end
    ]

    forbidden = (
        "click_js(",
        "browser.",
        "execute_script",
        "SeleniumBaseBrowserSession",
    )

    for token in forbidden:
        assert token not in block

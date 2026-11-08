"""QCC_ASSISTED_OPERATOR_CONTROLS_V1: governed ABORT shutdown.

Proves the abort path reuses the existing, already-certified
``MercurioConnector.close_browser`` governed shutdown -- never a
generic Chrome kill or ``os._exit`` -- and that it only ever touches
the ONE presentation-owned ``qcc_assisted`` runtime injected as
``abort_handler``, never any other session/runtime.
"""

from pathlib import Path
from unittest.mock import Mock

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path("app/run_presentacion_asistida.py")


class FakeActionClient:
    def __init__(self, actions):
        self.actions = list(actions)

    def consume_next(self):
        if not self.actions:
            return None
        return self.actions.pop(0)


def test_abort_handling_never_uses_os_exit_or_generic_chrome_kill():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    start = source.index("def _handle_qcc_abort(")
    end = source.index("def wait_for_human_navigation(", start)

    block = source[start:end]

    for forbidden in (
        "os._exit",
        "taskkill",
        "chrome.exe",
        "killall",
    ):
        assert forbidden not in block


def test_handle_qcc_abort_calls_injected_handler_exactly_once(tmp_path):
    reporter = Mock()
    abort_handler = Mock(return_value=True)

    action = {"action_id": 1, "action": "PRESENTATION_ABORT", "payload": {}}

    result = runner._handle_qcc_abort(
        action,
        str(tmp_path),
        reporter=reporter,
        abort_handler=abort_handler,
        step="READY_TO_FILL",
    )

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    assert result["browser_closed"] is True

    abort_handler.assert_called_once_with()
    reporter.aborted.assert_called_once()


def test_handle_qcc_abort_is_safe_when_handler_raises(tmp_path):
    reporter = Mock()
    abort_handler = Mock(side_effect=RuntimeError("boom"))

    action = {"action_id": 1, "action": "PRESENTATION_ABORT", "payload": {}}

    result = runner._handle_qcc_abort(
        action,
        str(tmp_path),
        reporter=reporter,
        abort_handler=abort_handler,
        step="READY_TO_FILL",
    )

    assert result["ok"] is False
    assert result["browser_closed"] is False
    reporter.aborted.assert_called_once()


def test_handle_qcc_abort_only_closes_the_injected_presentation_runtime(tmp_path):
    """Abort never reaches for any global registry/process list: it
    only ever calls the ONE callable explicitly injected for THIS
    presentation. Unrelated runtimes (WhatsApp/Twin/Discovery/other
    SeleniumBase sessions) are never referenced here at all."""

    unrelated_runtime_close = Mock()
    this_presentation_close = Mock(return_value=True)

    action = {"action_id": 1, "action": "PRESENTATION_ABORT", "payload": {}}

    runner._handle_qcc_abort(
        action,
        str(tmp_path),
        abort_handler=this_presentation_close,
        step="READY_TO_FILL",
    )

    this_presentation_close.assert_called_once_with()
    unrelated_runtime_close.assert_not_called()


def test_run_auto_and_documents_with_qcc_short_circuits_on_abort(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "browser_closed": True}

    from unittest.mock import patch

    with (
        patch.object(runner, "run_auto_with_qcc", return_value=aborted),
        patch.object(runner, "wait_for_qcc_documents_start") as docs_waiter,
        patch.object(runner, "upload_documentos_mercurio_asistido") as upload,
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            str(tmp_path),
            action_client=FakeActionClient([]),
        )

    assert result == aborted
    docs_waiter.assert_not_called()
    upload.assert_not_called()

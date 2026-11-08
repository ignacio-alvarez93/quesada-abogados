"""QCC_ASSISTED_POLICY_AUTOTWIN_V3: blocked field fill must preserve
presentation context.

Confirmed regression: when ``fill_section`` (via ``run_auto``) stops
on a DENIED/FAILED/HUMAN_HANDOFF governed write, the auto-flow
envelope previously ignored that outcome entirely, unconditionally
logged "QCC auto flow finalizado sin marcar COMPLETED" and advanced
straight to waiting for DOCUMENTS_START -- silently treating a BLOCKED
data-entry phase as if it had finished successfully.

These tests exercise the REAL ``run_auto_with_qcc`` /
``run_auto_and_documents_with_qcc`` envelopes (only ``run_auto`` itself
is stubbed, since its own internals are already covered by
``test_qcc_governed_presentation_writes.py``) together with the REAL
``QccPresentationReporter`` / ``QccPresentationSession`` contract, so
that whatever QCC state ends up resolvable is the actual certified
contract, not a test double.
"""

from pathlib import Path
from unittest.mock import patch

import app.run_presentacion_asistida as runner
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)
from backend.qcc.contracts.protocol import (
    QccPresentationStatus,
)


def _reporter():
    # The Bridge is never running in tests: ``_publish`` always fails
    # open (catches the connection error and returns False), but the
    # in-memory ``session`` is still updated for every transition.
    return QccPresentationReporter(
        session_id="qcc-test-session",
        expedient_id=1,
        client_id=1,
        procedure="MERCURIO",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        browser_profile_key="qcc_assisted",
        browser_session_mode="ASSISTED",
    )


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


BLOCKED_RESULT = {
    "ok": False,
    "label": "EXTRANJERO_BLOCKED",
    "detail": {
        "ok": False,
        "blocked_field": "extPasaporte",
        "blocked_outcome": "DENIED",
    },
}


# 1 & 3 & 4. blocked canonical write does not mark presentation
# completed; active session remains resolvable; Presentation Context
# remains AVAILABLE (WAITING_USER, not COMPLETED/ERROR).
def test_blocked_auto_flow_does_not_complete_and_retains_session(
    tmp_path,
):
    reporter = _reporter()
    session_dir = str(tmp_path)

    with patch.object(
        runner,
        "run_auto",
        return_value=BLOCKED_RESULT,
    ):
        result = runner.run_auto_with_qcc(
            object(),
            "33",
            {},
            session_dir,
            reporter=reporter,
        )

    assert result == BLOCKED_RESULT

    # Never COMPLETED/ERROR: the session stays resolvable and
    # explicitly flagged as requiring human action/correction.
    assert (
        reporter.session.status
        == QccPresentationStatus.WAITING_USER
    )
    assert reporter.session.requires_user_action is True
    assert reporter.session.session_id == "qcc-test-session"

    # 5. Retry/resume remains possible: the reporter is not left in a
    # terminal/unusable state -- a further transition still updates
    # the resolvable session (publishing itself is fail-open: no
    # Bridge is running in this test, so the HTTP POST is expected to
    # fail silently; only the in-memory session state is asserted).
    reporter.resuming(step="RETRY", progress=50)
    assert (
        reporter.session.status
        == QccPresentationStatus.RESUMING
    )

    log_text = _log_text(session_dir)
    assert "QCC auto flow BLOQUEADO" in log_text
    assert "campo=extPasaporte" in log_text
    assert "outcome=DENIED" in log_text
    assert "finalizado sin marcar COMPLETED" not in log_text


# 2. blocked canonical write does not advance to the document stage.
def test_blocked_auto_flow_never_advances_to_documents(tmp_path):
    reporter = _reporter()
    session_dir = str(tmp_path)

    with (
        patch.object(
            runner,
            "run_auto",
            return_value=BLOCKED_RESULT,
        ),
        patch.object(
            runner,
            "wait_for_qcc_documents_start",
        ) as waiter,
        patch.object(
            runner,
            "upload_documentos_mercurio_asistido",
        ) as upload,
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            session_dir,
            reporter=reporter,
            action_client=object(),
        )

    assert result == BLOCKED_RESULT
    waiter.assert_not_called()
    upload.assert_not_called()

    log_text = _log_text(session_dir)
    assert "DOCUMENTOS no iniciados" in log_text
    assert "bloqueado" in log_text


# 6. successful fill keeps the existing normal lifecycle untouched.
def test_successful_auto_flow_keeps_existing_lifecycle(tmp_path):
    reporter = _reporter()
    session_dir = str(tmp_path)

    with (
        patch.object(
            runner,
            "run_auto",
            return_value=None,
        ),
        patch.object(
            runner,
            "wait_for_qcc_documents_start",
            return_value={"action": "DOCUMENTS_START"},
        ) as waiter,
        patch.object(
            runner,
            "upload_documentos_mercurio_asistido",
            return_value=True,
        ) as upload,
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            session_dir,
            reporter=reporter,
            action_client=object(),
        )

    assert result is True
    waiter.assert_called_once()
    upload.assert_called_once()

    log_text = _log_text(session_dir)
    assert "finalizado sin marcar COMPLETED" in log_text
    assert "QCC auto flow BLOQUEADO" not in log_text

    # The envelope itself never marks COMPLETED (the documental phase
    # is a separate, later concern) -- unchanged from before this fix.
    assert (
        reporter.session.status
        != QccPresentationStatus.COMPLETED
    )

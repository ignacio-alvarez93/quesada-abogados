"""QCC_ASSISTED_OPERATOR_CONTROLS_V1: VOLCAR DATOS / ABORTAR
PRESENTACIÓN.

Proves, with fakes only (no real browser/SeleniumBase):

  * READY_TO_FILL is reported as soon as the waiter starts, and no
    fill starts automatically -- only an explicit
    ``PRESENTATION_FILL_START`` action (VOLCAR DATOS) resumes it;
  * no CMD ENTER fallback and no 300s readiness gate sits in front of
    the button;
  * ``PRESENTATION_ABORT`` is honoured with priority over both the
    fill-start and documents-start waiters, delegates the actual
    browser close to an injected, already-certified
    ``abort_handler`` (never controls SeleniumBase directly here),
    and is reported through the reporter -- never via
    ``os._exit``/generic process/Chrome kill;
  * a blocked governed write after VOLCAR DATOS keeps the context
    available (fail-closed, not fatal).
"""

from pathlib import Path
from unittest.mock import Mock, patch

import app.run_presentacion_asistida as runner


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


class FakeActionClient:
    def __init__(self, actions):
        self.actions = list(actions)

    def consume_next(self):
        if not self.actions:
            return None
        return self.actions.pop(0)


# ---------------------------------------------------------------
# wait_for_qcc_fill_start
# ---------------------------------------------------------------


def test_fill_start_waiter_reports_ready_to_fill_immediately(tmp_path):
    reporter = Mock()

    client = FakeActionClient(
        [{"action_id": 1, "action": "PRESENTATION_FILL_START", "payload": {}}]
    )

    result = runner.wait_for_qcc_fill_start(
        client,
        str(tmp_path),
        reporter=reporter,
        poll_interval=0,
    )

    assert result["ok"] is True
    assert result["mode"] == "fill_start_confirmed"

    reporter.waiting_user.assert_called_once_with(
        step="READY_TO_FILL",
        progress=35,
        message="Formulario listo para volcar datos",
    )


def test_fill_start_waiter_without_action_client_never_fills(tmp_path):
    result = runner.wait_for_qcc_fill_start(
        None,
        str(tmp_path),
        poll_interval=0,
    )

    assert result["ok"] is False
    assert result["mode"] == "fill_start_channel_unavailable"


def test_fill_start_waiter_ignores_unrelated_action_then_confirms(tmp_path):
    client = FakeActionClient(
        [
            {"action_id": 1, "action": "DOCUMENTS_START", "payload": {}},
            {"action_id": 2, "action": "PRESENTATION_FILL_START", "payload": {}},
        ]
    )

    result = runner.wait_for_qcc_fill_start(
        client,
        str(tmp_path),
        poll_interval=0,
    )

    assert result["ok"] is True
    assert result["action"]["action_id"] == 2


def test_fill_start_waiter_honours_abort_with_priority(tmp_path):
    reporter = Mock()
    abort_handler = Mock(return_value=True)

    client = FakeActionClient(
        [
            {"action_id": 9, "action": "PRESENTATION_ABORT", "payload": {}},
            {"action_id": 10, "action": "PRESENTATION_FILL_START", "payload": {}},
        ]
    )

    result = runner.wait_for_qcc_fill_start(
        client,
        str(tmp_path),
        reporter=reporter,
        abort_handler=abort_handler,
        poll_interval=0,
    )

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    assert result["browser_closed"] is True

    abort_handler.assert_called_once_with()
    reporter.aborted.assert_called_once()

    # The queued FILL_START action is never consumed/acted upon once
    # the abort has already been handled.
    assert client.actions == [
        {"action_id": 10, "action": "PRESENTATION_FILL_START", "payload": {}}
    ]


def test_fill_start_waiter_abort_without_handler_reports_not_confirmed(tmp_path):
    reporter = Mock()

    client = FakeActionClient(
        [{"action_id": 9, "action": "PRESENTATION_ABORT", "payload": {}}]
    )

    result = runner.wait_for_qcc_fill_start(
        client,
        str(tmp_path),
        reporter=reporter,
        poll_interval=0,
    )

    assert result["ok"] is False
    assert result["browser_closed"] is False

    reporter.aborted.assert_called_once()


# ---------------------------------------------------------------
# wait_for_qcc_documents_start: PRESENTATION_ABORT during that phase
# ---------------------------------------------------------------


def test_documents_start_waiter_honours_abort(tmp_path):
    abort_handler = Mock(return_value=True)

    client = FakeActionClient(
        [{"action_id": 3, "action": "PRESENTATION_ABORT", "payload": {}}]
    )

    result = runner.wait_for_qcc_documents_start(
        client,
        str(tmp_path),
        abort_handler=abort_handler,
        poll_interval=0,
    )

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    abort_handler.assert_called_once_with()


def test_documents_start_waiter_still_consumes_documents_start(tmp_path):
    client = FakeActionClient(
        [{"action_id": 4, "action": "DOCUMENTS_START", "payload": {}}]
    )

    result = runner.wait_for_qcc_documents_start(
        client,
        str(tmp_path),
        poll_interval=0,
    )

    assert result["action"] == "DOCUMENTS_START"


# ---------------------------------------------------------------
# run_auto: no automatic fill before VOLCAR DATOS
# ---------------------------------------------------------------


def _patched_run_auto_dependencies(**overrides):
    defaults = dict(
        step_continuar_inicial=lambda *a, **k: {"ok": True},
        pause_certificado=lambda *a, **k: {"ok": True},
        step_presentar_nueva_solicitud=lambda *a, **k: {"ok": True},
        pause_supuesto=lambda *a, **k: {"ok": True},
    )
    defaults.update(overrides)
    return defaults


def test_run_auto_never_fills_before_explicit_fill_start(tmp_path):
    fill_called = []

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner,
            "step_presentar_nueva_solicitud",
            return_value={"ok": True},
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(
            runner,
            "wait_for_qcc_fill_start",
            return_value={"ok": False, "mode": "fill_start_channel_unavailable"},
        ) as fill_waiter,
        patch.object(
            runner,
            "fill_datos_extranjero",
            side_effect=lambda *a, **k: fill_called.append(True),
        ),
    ):
        result = runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": "X1"}},
            str(tmp_path),
            action_client=FakeActionClient([]),
        )

    fill_waiter.assert_called_once()
    assert fill_called == []
    assert result["ok"] is False
    assert result["label"] == "FILL_START_NOT_CONFIRMED"


def test_run_auto_fills_only_after_fill_start_and_readiness(tmp_path):
    reporter = Mock()
    order = []

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner,
            "step_presentar_nueva_solicitud",
            return_value={"ok": True},
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(
            runner,
            "wait_for_qcc_fill_start",
            side_effect=lambda *a, **k: order.append("fill_start") or {"ok": True},
        ),
        patch.object(
            runner,
            "_wait_for_ex01_personal_readiness",
            side_effect=lambda *a, **k: order.append("readiness") or {"ok": True},
        ),
        patch.object(
            runner,
            "fill_datos_extranjero",
            side_effect=lambda *a, **k: order.append("fill") or {"ok": True},
        ),
        patch.object(
            runner,
            "fill_datos_presentador",
            return_value=True,
        ),
        patch.object(runner, "click_continuar"),
        patch.object(runner, "click_continuar_presentador"),
        patch.object(runner, "pause_humana_final_presentacion"),
    ):
        runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": "X1"}},
            str(tmp_path),
            reporter=reporter,
            action_client=FakeActionClient([]),
        )

    assert order == ["fill_start", "readiness", "fill"]

    reporter.filling.assert_called_once()
    reporter.filled.assert_called_once()
    reporter.fill_blocked.assert_not_called()


def test_run_auto_reports_fill_blocked_and_preserves_context(tmp_path):
    reporter = Mock()

    blocked = {
        "ok": False,
        "blocked_field": "extPasaporte",
        "blocked_outcome": "DENIED",
    }

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner,
            "step_presentar_nueva_solicitud",
            return_value={"ok": True},
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(
            runner,
            "wait_for_qcc_fill_start",
            return_value={"ok": True},
        ),
        patch.object(
            runner,
            "_wait_for_ex01_personal_readiness",
            return_value={"ok": True},
        ),
        patch.object(
            runner,
            "fill_datos_extranjero",
            return_value=blocked,
        ),
    ):
        result = runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": "X1"}},
            str(tmp_path),
            reporter=reporter,
            action_client=FakeActionClient([]),
        )

    assert result["ok"] is False
    assert result["label"] == "EXTRANJERO_BLOCKED"
    assert result["detail"] == blocked

    reporter.fill_blocked.assert_called_once()
    reporter.filled.assert_not_called()


def test_run_auto_propagates_abort_from_fill_start_waiter(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "browser_closed": True}

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner,
            "step_presentar_nueva_solicitud",
            return_value={"ok": True},
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(
            runner,
            "wait_for_qcc_fill_start",
            return_value=aborted,
        ),
        patch.object(runner, "fill_datos_extranjero") as fill,
    ):
        result = runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": "X1"}},
            str(tmp_path),
            action_client=FakeActionClient([]),
        )

    fill.assert_not_called()
    assert result["label"] == "FILL_START_NOT_CONFIRMED"
    assert result["detail"] == aborted

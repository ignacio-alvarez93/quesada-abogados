"""QCC_OPERATOR_ACTION_CONSUMPTION_FIX_V1.

Root cause: QUEUE_TO_RUNTIME / PHASE_LIMITED_ACTION_CONSUMPTION. The
Bridge accepted and queued ``PRESENTATION_ABORT`` correctly, but the
presentation runtime only consumed actions inside
``wait_for_qcc_fill_start`` / ``wait_for_qcc_documents_start``.

Proves, with fakes only (no real browser/SeleniumBase/Mercurio):

  * ABORT is serviced during PROCEDURE_SELECTION without any hidden
    ``input()``;
  * FILL_START followed by ABORT while EX01 readiness never succeeds
    is serviced between bounded readiness checks;
  * ABORT after AUTO_FLOW_BLOCKED remains serviceable;
  * READY_TO_FILL / DOCUMENTS_READY flows stay compatible;
  * double abort is safe;
  * the EX01 readiness timeout diagnostic is value-free.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import app.run_presentacion_asistida as runner


RUNNER_PATH = Path("app/run_presentacion_asistida.py")

PASSPORT_VALUE = "X1234567"
NIE_VALUE = "Y7654321Z"


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


class FakeActionClient:
    def __init__(self, actions):
        self.actions = list(actions)
        self.consumed = []

    def consume_next(self):
        if not self.actions:
            return None
        action = self.actions.pop(0)
        self.consumed.append(action)
        return action


def _abort(action_id=9):
    return {"action_id": action_id, "action": "PRESENTATION_ABORT", "payload": {}}


def _fill_start(action_id=1):
    return {"action_id": action_id, "action": "PRESENTATION_FILL_START", "payload": {}}


def _never_ready(*_args, **_kwargs):
    raise TimeoutError("never ready")


@pytest.fixture
def no_hidden_input(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("hidden input() must not be used with QCC")

    monkeypatch.setattr("builtins.input", _forbidden)


# ---------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------


def test_shared_helper_returns_none_without_client_or_action(tmp_path):
    assert runner._service_qcc_operator_action(
        None, str(tmp_path), step="X"
    ) is None

    assert runner._service_qcc_operator_action(
        FakeActionClient([]), str(tmp_path), step="X"
    ) is None


def test_shared_helper_routes_abort_through_governed_handler(tmp_path):
    abort_handler = Mock(return_value=True)
    reporter = Mock()

    result = runner._service_qcc_operator_action(
        FakeActionClient([_abort()]),
        str(tmp_path),
        reporter=reporter,
        abort_handler=abort_handler,
        step="EX01_READINESS",
    )

    assert runner._is_qcc_aborted_result(result)
    assert result["label"] == "EX01_READINESS"
    abort_handler.assert_called_once_with()
    reporter.aborted.assert_called_once()


def test_shared_helper_discards_unexpected_and_returns_expected(tmp_path):
    client = FakeActionClient(
        [
            {"action_id": 1, "action": "DOCUMENTS_START", "payload": {}},
            _fill_start(2),
        ]
    )

    first = runner._service_qcc_operator_action(
        client,
        str(tmp_path),
        step="READY_TO_FILL",
        expected_actions=("PRESENTATION_FILL_START",),
    )
    second = runner._service_qcc_operator_action(
        client,
        str(tmp_path),
        step="READY_TO_FILL",
        expected_actions=("PRESENTATION_FILL_START",),
    )

    assert first is None
    assert second["action_id"] == 2


def test_shared_helper_is_fail_open_when_transport_raises(tmp_path):
    client = Mock()
    client.consume_next.side_effect = RuntimeError("bridge down")

    assert runner._service_qcc_operator_action(
        client, str(tmp_path), step="X"
    ) is None


def test_abort_semantics_are_not_duplicated_across_phases():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    # Exactly one place routes a consumed PRESENTATION_ABORT into the
    # governed abort handler: the shared helper.
    assert source.count("return _handle_qcc_abort(") == 1

    for start_marker, end_marker in (
        ("def wait_for_qcc_fill_start(", "def wait_for_qcc_documents_start("),
        ("def wait_for_qcc_documents_start(", "# SUBIDA DOCUMENTAL ASISTIDA"),
        ("def wait_for_human_navigation(", "MERCURIO_MODE_ACCESS_READY_JS"),
    ):
        start = source.index(start_marker)
        block = source[start:source.index(end_marker, start)]
        assert ".consume_next()" not in block
        assert "_service_qcc_operator_action(" in block or (
            "_wait_for_js_with_qcc_control(" in block
        )


# ---------------------------------------------------------------
# 1. ABORT during PROCEDURE_SELECTION
# ---------------------------------------------------------------


def test_abort_during_procedure_selection_without_hidden_input(
    tmp_path, no_hidden_input
):
    reporter = Mock()
    abort_handler = Mock(return_value=True)
    client = FakeActionClient([None, _abort()])

    with patch.object(runner, "wait_for_js", side_effect=_never_ready):
        result = runner.pause_supuesto(
            object(),
            str(tmp_path),
            reporter=reporter,
            datos_mercurio={"extranjero": {"extPasaporte": PASSPORT_VALUE}},
            action_client=client,
            abort_handler=abort_handler,
        )

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    assert result["label"] == "PROCEDURE_SELECTION"
    abort_handler.assert_called_once_with()
    reporter.aborted.assert_called_once()


def test_human_navigation_with_qcc_times_out_without_hidden_input(
    tmp_path, no_hidden_input
):
    with patch.object(runner, "wait_for_js", side_effect=_never_ready):
        result = runner.wait_for_human_navigation(
            object(),
            str(tmp_path),
            "Datos del extranjero/a",
            "false",
            timeout=0.2,
            interval=0.01,
            action_client=FakeActionClient([]),
            qcc_step="PROCEDURE_SELECTION",
        )

    assert result["ok"] is False
    assert result["mode"] == "human_navigation_timeout"


def test_human_navigation_with_qcc_detects_screen(tmp_path, no_hidden_input):
    reporter = Mock()

    with patch.object(runner, "wait_for_js", return_value=True):
        result = runner.wait_for_human_navigation(
            object(),
            str(tmp_path),
            "Datos del extranjero/a",
            "true",
            action_client=FakeActionClient([]),
            qcc_reporter=reporter,
            qcc_step="PROCEDURE_SELECTION",
        )

    assert result["ok"] is True
    assert result["mode"] == "human_dom_detected"
    reporter.user_action_detected.assert_called_once()
    reporter.resuming.assert_called_once()


def test_human_navigation_waits_in_bounded_short_slices(tmp_path):
    with patch.object(
        runner, "wait_for_js", side_effect=_never_ready
    ) as wait:
        runner.wait_for_human_navigation(
            object(),
            str(tmp_path),
            "Datos del extranjero/a",
            "false",
            timeout=0.2,
            interval=0.01,
            action_client=FakeActionClient([]),
        )

    assert wait.call_count >= 1
    for call in wait.call_args_list:
        assert call.kwargs["timeout"] <= runner.QCC_CONTROL_CHECK_SLICE_SECONDS


def test_pause_certificado_threads_qcc_controls(tmp_path):
    client = FakeActionClient([])
    abort_handler = Mock()

    with (
        patch.object(runner, "wait_for_js", return_value=True),
        patch.object(runner, "js"),
        patch.object(
            runner,
            "wait_for_human_navigation",
            return_value={"ok": True},
        ) as navigation,
    ):
        runner.pause_certificado(
            object(),
            str(tmp_path),
            action_client=client,
            abort_handler=abort_handler,
        )

    assert navigation.call_args.kwargs["action_client"] is client
    assert navigation.call_args.kwargs["abort_handler"] is abort_handler


def test_run_auto_propagates_abort_from_procedure_selection(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "label": "PROCEDURE_SELECTION"}

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner, "step_presentar_nueva_solicitud", return_value={"ok": True}
        ),
        patch.object(runner, "pause_supuesto", return_value=aborted) as supuesto,
        patch.object(runner, "wait_for_qcc_fill_start") as fill_waiter,
    ):
        client = FakeActionClient([])
        handler = Mock()
        result = runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": PASSPORT_VALUE}},
            str(tmp_path),
            action_client=client,
            abort_handler=handler,
        )

    assert result == aborted
    assert supuesto.call_args.kwargs["action_client"] is client
    assert supuesto.call_args.kwargs["abort_handler"] is handler
    fill_waiter.assert_not_called()


# ---------------------------------------------------------------
# 2. FILL_START then ABORT while EX01 readiness never succeeds
# ---------------------------------------------------------------


def test_fill_start_then_abort_during_ex01_readiness(tmp_path, no_hidden_input):
    reporter = Mock()
    abort_handler = Mock(return_value=True)
    client = FakeActionClient([_fill_start(1), None, _abort(2)])

    with (
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner, "step_presentar_nueva_solicitud", return_value={"ok": True}
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(runner, "wait_for_js", side_effect=_never_ready) as wait,
        patch.object(runner, "fill_datos_extranjero") as fill,
    ):
        result = runner.run_auto_with_qcc(
            object(),
            "33",
            {"extranjero": {"extPasaporte": PASSPORT_VALUE}},
            str(tmp_path),
            reporter=reporter,
            action_client=client,
            abort_handler=abort_handler,
        )

    # FILL_START consumed, then readiness began, then ABORT consumed.
    assert [a["action"] for a in client.consumed if a] == [
        "PRESENTATION_FILL_START",
        "PRESENTATION_ABORT",
    ]
    assert wait.call_count >= 1

    reporter.automating.assert_any_call(
        step="EX01_READINESS",
        progress=30,
        message="Comprobando automáticamente Datos del extranjero/a",
    )

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    assert result["label"] == "EX01_READINESS"
    abort_handler.assert_called_once_with()
    fill.assert_not_called()

    # An abort is never re-reported as AUTO_FLOW_BLOCKED.
    for call in reporter.waiting_user.call_args_list:
        assert call.kwargs.get("step") != "AUTO_FLOW_BLOCKED"


def test_readiness_predicate_is_unchanged(tmp_path):
    datos = {"extranjero": {"extPasaporte": PASSPORT_VALUE}}

    with patch.object(runner, "wait_for_js", return_value=True) as wait:
        result = runner._wait_for_ex01_personal_readiness(
            object(),
            str(tmp_path),
            datos,
            action_client=FakeActionClient([]),
        )

    assert result["ok"] is True
    assert wait.call_args.args[1] == runner._ex01_personal_ready_js(datos)


def test_run_auto_and_documents_short_circuits_wrapped_abort(tmp_path):
    wrapped = {
        "ok": False,
        "label": "FILL_START_NOT_CONFIRMED",
        "detail": {"ok": False, "mode": "aborted"},
    }

    with (
        patch.object(runner, "run_auto", return_value=wrapped),
        patch.object(runner, "wait_for_qcc_operator_control") as control,
        patch.object(runner, "wait_for_qcc_documents_start") as docs,
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            str(tmp_path),
            action_client=FakeActionClient([]),
        )

    assert result == wrapped
    control.assert_not_called()
    docs.assert_not_called()


# ---------------------------------------------------------------
# 3. ABORT after AUTO_FLOW_BLOCKED
# ---------------------------------------------------------------


def test_abort_after_auto_flow_blocked_is_serviceable(tmp_path, no_hidden_input):
    reporter = Mock()
    abort_handler = Mock(return_value=True)
    client = FakeActionClient([None, _abort()])

    blocked = {
        "ok": False,
        "label": "EXTRANJERO_BLOCKED",
        "detail": {
            "ok": False,
            "blocked_field": "extPasaporte",
            "blocked_outcome": "DENIED",
        },
    }

    with (
        patch.object(runner, "run_auto", return_value=blocked),
        patch.object(runner, "wait_for_qcc_documents_start") as docs,
        patch.object(runner, "upload_documentos_mercurio_asistido") as upload,
        patch.object(runner.time, "sleep"),
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            str(tmp_path),
            reporter=reporter,
            action_client=client,
            abort_handler=abort_handler,
        )

    reporter.waiting_user.assert_any_call(
        step="AUTO_FLOW_BLOCKED",
        progress=50,
        message=(
            "Rellenado automático detenido: "
            "se requiere corrección o acción humana"
        ),
        event_details={
            "label": "EXTRANJERO_BLOCKED",
            "blocked_field": "extPasaporte",
            "blocked_outcome": "DENIED",
        },
    )

    assert result["mode"] == "aborted"
    assert result["label"] == "AUTO_FLOW_BLOCKED"
    abort_handler.assert_called_once_with()
    docs.assert_not_called()
    upload.assert_not_called()


def test_auto_flow_blocked_control_wait_is_bounded(tmp_path):
    result = runner.wait_for_qcc_operator_control(
        FakeActionClient([]),
        str(tmp_path),
        step="AUTO_FLOW_BLOCKED",
        timeout=0.05,
        poll_interval=0.01,
    )

    assert result["ok"] is False
    assert result["mode"] == "operator_control_timeout"


def test_auto_flow_blocked_without_client_keeps_blocked_result(tmp_path):
    blocked = {"ok": False, "label": "EXTRANJERO_BLOCKED"}

    with patch.object(runner, "run_auto", return_value=blocked):
        result = runner.run_auto_and_documents_with_qcc(
            object(),
            "33",
            {},
            str(tmp_path),
            str(tmp_path),
            action_client=None,
        )

    assert result == blocked


def test_control_wait_never_uses_os_exit_or_generic_chrome_kill():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    start = source.index("def _is_qcc_aborted_result(")
    end = source.index("def wait_for_human_navigation(", start)
    block = source[start:end]

    for forbidden in ("os._exit", "taskkill", "chrome.exe", "killall"):
        assert forbidden not in block


def test_main_skips_hidden_menu_after_abort():
    source = RUNNER_PATH.read_text(encoding="utf-8")

    start = source.index("\ndef main(")
    menu = source.index('print("MENÚ:")', start)

    assert "_is_qcc_aborted_result(" in source[start:menu]


# ---------------------------------------------------------------
# 4. READY_TO_FILL fill flow remains compatible
# ---------------------------------------------------------------


def test_ready_to_fill_flow_still_fills_after_fill_start(tmp_path):
    order = []
    client = FakeActionClient([_fill_start()])

    with (
        patch.object(runner._MapperPreload, "resume", return_value={"ok": True}),
        patch.object(runner, "step_continuar_inicial", return_value={"ok": True}),
        patch.object(runner, "pause_certificado", return_value={"ok": True}),
        patch.object(
            runner, "step_presentar_nueva_solicitud", return_value={"ok": True}
        ),
        patch.object(runner, "pause_supuesto", return_value={"ok": True}),
        patch.object(runner, "wait_for_js", return_value=True),
        patch.object(
            runner,
            "fill_datos_extranjero",
            side_effect=lambda *a, **k: order.append("fill") or {"ok": True},
        ),
        patch.object(runner, "fill_datos_presentador", return_value=True),
        patch.object(runner, "click_continuar"),
        patch.object(runner, "click_continuar_presentador"),
        patch.object(
            runner,
            "pause_humana_final_presentacion",
            return_value={"ok": True},
        ),
    ):
        runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": PASSPORT_VALUE}},
            str(tmp_path),
            action_client=client,
        )

    assert order == ["fill"]
    assert "EX01_READY" in _log_text(str(tmp_path))


# ---------------------------------------------------------------
# 5. DOCUMENTS_READY flow remains compatible
# ---------------------------------------------------------------


def test_documents_ready_flow_still_consumes_documents_start(tmp_path):
    client = FakeActionClient(
        [None, {"action_id": 4, "action": "DOCUMENTS_START", "payload": {}}]
    )

    with patch.object(runner.time, "sleep"):
        result = runner.wait_for_qcc_documents_start(
            client,
            str(tmp_path),
            poll_interval=0,
        )

    assert result["action"] == "DOCUMENTS_START"


def test_final_review_abort_stops_before_documents(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "label": "FINAL_REVIEW"}
    reporter = Mock()

    with (
        patch.object(runner, "_read_mercurio_document_page_state", return_value=None),
        patch.object(runner, "wait_for_human_navigation", return_value=aborted),
    ):
        result = runner.pause_humana_final_presentacion(
            object(),
            str(tmp_path),
            reporter=reporter,
            action_client=FakeActionClient([]),
        )

    assert result == aborted
    reporter.waiting_user.assert_not_called()


# ---------------------------------------------------------------
# 6. Double abort / idempotency
# ---------------------------------------------------------------


def test_double_abort_during_procedure_selection_closes_once(
    tmp_path, no_hidden_input
):
    abort_handler = Mock(return_value=True)
    client = FakeActionClient([_abort(1), _abort(2)])

    with patch.object(runner, "wait_for_js", side_effect=_never_ready):
        result = runner.wait_for_human_navigation(
            object(),
            str(tmp_path),
            "Datos del extranjero/a",
            "false",
            action_client=client,
            abort_handler=abort_handler,
            qcc_step="PROCEDURE_SELECTION",
        )

    assert result["mode"] == "aborted"
    abort_handler.assert_called_once_with()
    assert client.actions == [_abort(2)]


def test_repeated_abort_handling_is_safe_with_idempotent_handler(tmp_path):
    closed = []

    def _idempotent_close():
        if closed:
            return True
        closed.append(True)
        return True

    first = runner._service_qcc_operator_action(
        FakeActionClient([_abort(1)]),
        str(tmp_path),
        abort_handler=_idempotent_close,
        step="AUTO_FLOW_BLOCKED",
    )
    second = runner._service_qcc_operator_action(
        FakeActionClient([_abort(2)]),
        str(tmp_path),
        abort_handler=_idempotent_close,
        step="AUTO_FLOW_BLOCKED",
    )

    assert first["mode"] == second["mode"] == "aborted"
    assert closed == [True]


# ---------------------------------------------------------------
# 7. Value-free EX01 readiness timeout diagnostic
# ---------------------------------------------------------------


class _DiagnosticBrowser:
    """Readiness predicate never true. extPasaporte exists but is
    disabled; extNie does not exist. Every script is recorded so the
    probes themselves can be audited."""

    def __init__(self):
        self.scripts = []

    def execute_script(self, code):
        self.scripts.append(code)

        if '"extNie"' in code and "getElementById" in code:
            # Not present in the DOM: every probe is false.
            return False

        if '"extPasaporte"' in code and code.startswith("return !!((function()"):
            if "return !!el && !!(true)" in code:
                return True
            if "el.disabled" in code:
                return True
            return False

        # Composite readiness predicate (wait_for_js): never ready.
        return False


def test_readiness_timeout_emits_value_free_diagnostic(tmp_path):
    browser = _DiagnosticBrowser()
    datos = {
        "extranjero": {
            "extPasaporte": PASSPORT_VALUE,
            "extNie": NIE_VALUE,
            "extNombre": "MARIA",
        }
    }

    result = runner._wait_for_ex01_personal_readiness(
        browser,
        str(tmp_path),
        datos,
        timeout=0.05,
        interval=0.01,
        action_client=FakeActionClient([]),
    )

    assert result["ok"] is False
    assert result["mode"] == "ex01_readiness_timeout"

    diagnostic = result["diagnostic"]
    assert [entry["field"] for entry in diagnostic] == ["extPasaporte", "extNie"]

    allowed = set(runner.EX01_READINESS_DIAGNOSTIC_KEYS)
    for entry in diagnostic:
        assert set(entry) <= allowed
        for key, value in entry.items():
            if key != "field":
                assert value in (True, False, None)

    assert diagnostic[0] == {
        "field": "extPasaporte",
        "exists": True,
        "disabled": True,
        "display_none": False,
        "visibility_hidden": False,
        "aria_hidden": False,
        "hidden_ancestor": False,
        "zero_size": False,
        "interactable": False,
    }
    assert diagnostic[1] == {"field": "extNie", "exists": False}

    log_text = _log_text(str(tmp_path))
    assert (
        "EX01_READINESS_DIAGNOSTIC phase=timeout "
        "field=extPasaporte exists=True disabled=True"
    ) in log_text
    assert (
        "EX01_READINESS_DIAGNOSTIC phase=timeout field=extNie exists=False"
    ) in log_text

    serialized = json.dumps(result) + log_text
    for sensitive in (PASSPORT_VALUE, NIE_VALUE, "MARIA"):
        assert sensitive not in serialized

    probes = [
        s for s in browser.scripts if s.startswith("return !!((function()")
    ]
    assert probes
    for probe in probes:
        for sensitive in (PASSPORT_VALUE, NIE_VALUE, "MARIA"):
            assert sensitive not in probe
        assert ".value" not in probe
        assert "textContent" not in probe
        assert "innerText" not in probe


def test_readiness_diagnostic_covers_every_readiness_predicate():
    predicate = runner._field_readiness_js("extPasaporte")

    for _key, expression in runner.EX01_READINESS_DIAGNOSTIC_PROBES:
        for token in (
            "el.disabled",
            "display",
            "visibility",
            "aria-hidden",
            "display: none",
            "offsetWidth",
        ):
            if token in expression:
                assert token in predicate


def test_readiness_diagnostic_is_fail_open(tmp_path):
    browser = Mock()
    browser.execute_script.side_effect = RuntimeError("cdp gone")

    diagnostic = runner._ex01_readiness_diagnostic(
        browser,
        {"extranjero": {"extPasaporte": PASSPORT_VALUE}},
        str(tmp_path),
    )

    assert diagnostic == []
    assert PASSPORT_VALUE not in _log_text(str(tmp_path))


# ---------------------------------------------------------------
# 8. QCC_EX01_READINESS_IMMEDIATE_DIAGNOSTIC_V1: one value-free
#    snapshot at readiness start, before polling.
# ---------------------------------------------------------------


_DIAG_DATOS = {
    "extranjero": {
        "extPasaporte": PASSPORT_VALUE,
        "extNie": NIE_VALUE,
        "extNombre": "MARIA",
    }
}


def _diagnostic_lines(log_text, phase):
    prefix = f"EX01_READINESS_DIAGNOSTIC phase={phase} "
    return [line for line in log_text.splitlines() if prefix in line]


def test_initial_diagnostic_emitted_before_polling(tmp_path):
    order = []
    real_diagnostic = runner._ex01_readiness_diagnostic

    def _recording_diagnostic(*args, **kwargs):
        order.append(("diagnostic", kwargs.get("phase")))
        return real_diagnostic(*args, **kwargs)

    def _recording_wait(*_args, **_kwargs):
        order.append(("poll", None))
        return True

    with (
        patch.object(
            runner, "_ex01_readiness_diagnostic", side_effect=_recording_diagnostic
        ),
        patch.object(runner, "wait_for_js", side_effect=_recording_wait),
    ):
        result = runner._wait_for_ex01_personal_readiness(
            _DiagnosticBrowser(),
            str(tmp_path),
            _DIAG_DATOS,
            action_client=FakeActionClient([]),
        )

    assert result == {
        "ok": True,
        "mode": "ex01_readiness_automatic",
        "label": "Datos del extranjero/a",
    }
    # Exactly one initial snapshot, strictly before the first poll; no
    # timeout snapshot on success.
    assert order[0] == ("diagnostic", "initial")
    assert order[1] == ("poll", None)
    assert order.count(("diagnostic", "initial")) == 1
    assert ("diagnostic", "timeout") not in order

    log_text = _log_text(str(tmp_path))
    start = log_text.index("EX01_READINESS_START")
    initial = log_text.index("EX01_READINESS_DIAGNOSTIC phase=initial")
    ready = log_text.index("EX01_READY\n")
    assert start < initial < ready


def test_initial_diagnostic_uses_canonical_fields_and_is_value_free(tmp_path):
    browser = _DiagnosticBrowser()

    with patch.object(runner, "wait_for_js", return_value=True) as wait:
        result = runner._wait_for_ex01_personal_readiness(
            browser,
            str(tmp_path),
            _DIAG_DATOS,
            action_client=FakeActionClient([]),
        )

    # Predicate/result unchanged.
    assert result["ok"] is True
    assert wait.call_args.args[1] == runner._ex01_personal_ready_js(_DIAG_DATOS)

    log_text = _log_text(str(tmp_path))
    lines = _diagnostic_lines(log_text, "initial")

    canonical = list(runner._ex01_personal_canonical_write_fields(_DIAG_DATOS))
    assert canonical == ["extPasaporte", "extNie"]
    assert [line.split("field=")[1].split()[0] for line in lines] == canonical

    allowed = set(runner.EX01_READINESS_DIAGNOSTIC_KEYS)
    for line in lines:
        payload = line.split("EX01_READINESS_DIAGNOSTIC phase=initial ", 1)[1]
        pairs = dict(token.split("=", 1) for token in payload.split())
        assert set(pairs) <= allowed
        for key, value in pairs.items():
            if key == "field":
                assert value in canonical
            else:
                assert value in ("True", "False", "None")

    assert (
        "EX01_READINESS_DIAGNOSTIC phase=initial field=extPasaporte "
        "exists=True disabled=True display_none=False "
        "visibility_hidden=False aria_hidden=False hidden_ancestor=False "
        "zero_size=False interactable=False"
    ) in log_text
    assert "EX01_READINESS_DIAGNOSTIC phase=initial field=extNie exists=False" in log_text

    for sensitive in (PASSPORT_VALUE, NIE_VALUE, "MARIA"):
        assert sensitive not in log_text
        for script in browser.scripts:
            assert sensitive not in script
    for script in browser.scripts:
        if script.startswith("return !!((function()"):
            assert ".value" not in script


def test_timeout_emits_initial_and_timeout_diagnostics(tmp_path):
    result = runner._wait_for_ex01_personal_readiness(
        _DiagnosticBrowser(),
        str(tmp_path),
        _DIAG_DATOS,
        timeout=0.05,
        interval=0.01,
        action_client=FakeActionClient([]),
    )

    assert result["ok"] is False
    assert result["mode"] == "ex01_readiness_timeout"
    assert [e["field"] for e in result["diagnostic"]] == ["extPasaporte", "extNie"]

    log_text = _log_text(str(tmp_path))
    initial = _diagnostic_lines(log_text, "initial")
    timeout = _diagnostic_lines(log_text, "timeout")
    assert len(initial) == len(timeout) == 2
    assert log_text.index("phase=initial") < log_text.index(
        "EX01_READINESS_TIMEOUT"
    ) < log_text.index("phase=timeout")


def test_abort_during_readiness_still_serviced_after_initial_diagnostic(
    tmp_path, no_hidden_input
):
    abort_handler = Mock(return_value=True)
    client = FakeActionClient([_abort()])

    with patch.object(runner, "wait_for_js", side_effect=_never_ready):
        result = runner._wait_for_ex01_personal_readiness(
            _DiagnosticBrowser(),
            str(tmp_path),
            _DIAG_DATOS,
            action_client=client,
            abort_handler=abort_handler,
        )

    assert runner._is_qcc_aborted_result(result)
    assert result["label"] == "EX01_READINESS"
    abort_handler.assert_called_once_with()

    log_text = _log_text(str(tmp_path))
    assert _diagnostic_lines(log_text, "initial")
    assert not _diagnostic_lines(log_text, "timeout")


def test_initial_diagnostic_fail_open_does_not_change_readiness(tmp_path):
    browser = Mock()
    browser.execute_script.side_effect = RuntimeError("cdp gone")

    with patch.object(runner, "wait_for_js", return_value=True):
        result = runner._wait_for_ex01_personal_readiness(
            browser,
            str(tmp_path),
            {"extranjero": {"extPasaporte": PASSPORT_VALUE}},
            action_client=FakeActionClient([]),
        )

    assert result["ok"] is True
    log_text = _log_text(str(tmp_path))
    assert "EX01_READINESS_DIAGNOSTIC phase=initial field=extPasaporte no disponible" in log_text
    assert PASSPORT_VALUE not in log_text

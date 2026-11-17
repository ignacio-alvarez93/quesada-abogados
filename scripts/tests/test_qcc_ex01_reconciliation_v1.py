"""QCC EX01 R2 B -- governed presentation core reconciliation.

Proves, against the REAL governed chain (``_governed_write`` ->
``execute_state_aware_action`` -> Mercurio policy/profile/recognizer),
with only the physical browser faked by a STATEFUL double that really
holds each control's value/checked/selected option:

  * field-result control: INPUT/SELECT/CHECKBOX/RADIO are only ``OK``
    once the live control reads back the expected value -- a write the
    page did not keep, an unmatched/placeholder option or an
    unavailable read-back is never a false ``OK``;
  * section capture reuse only while page + active surface + selector
    are proven by a targeted probe; anything else re-captures and the
    unchanged gate decides (no write on an inactive panel/without
    evidence);
  * ``with_local_target_interaction`` derives, never asserts; the
    historical ``with_preloaded_target_interaction`` is NOT ported;
  * PRESENTATION_ABORT is serviced during every EX01 wait and
    propagates through ``run_auto``/envelopes;
  * the readiness diagnostic is structural and value-free;
  * automated pre-form steps vs EX01 form CONTINUAR/CONCLUIR
    (HUMAN_ONLY, observation only).
"""

import ast
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import app.run_presentacion_asistida as runner
from backend.automation.site_architecture import state_aware_execution as sae
from backend.automation.site_architecture.outcome_classification import (
    ACTION_DISPOSITION_CONFIRMED,
    ACTION_DISPOSITION_EFFECT_UNKNOWN,
)
from backend.automation.site_architecture.state_aware_execution import (
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    STATE_AWARE_POSTCONDITION_NOT_VERIFIED,
    STATE_AWARE_POSTCONDITION_VERIFIED,
    ActionIntent,
    CapturedSnapshot,
    with_local_target_interaction,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    build_mercurio_interaction_policy,
)


RUNNER_PATH = Path("app/run_presentacion_asistida.py")
MERCURIO_INICIO_PATH = "/mercurio/inicioMercurio.html"
_CAPTURE_SCRIPT_SIZE_THRESHOLD = 10000


# ---------------------------------------------------------------
# Stateful fake CDP browser
# ---------------------------------------------------------------


def _norm(value):
    value = unicodedata.normalize("NFD", str(value or "").strip().upper())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", value)


def _control(tag, element_type="", *, options=None, value="", checked=False,
             visible=True, disabled=False, sticky=True, panel_id=None,
             panel_active=True):
    return {
        "tag": tag,
        "type": element_type,
        "options": list(options or ()),
        "value": value,
        "checked": checked,
        "visible": visible,
        "disabled": disabled,
        # False: Mercurio-side handler resets the control right after
        # the write (the exact "executed but not kept" failure shape).
        "sticky": sticky,
        "panel_id": panel_id,
        "panel_active": panel_active,
    }


def _signals(in_viewport=True):
    return {
        "hidden": False,
        "aria_hidden": False,
        "aria_disabled": False,
        "readonly": False,
        "in_viewport": in_viewport,
        "opacity": "1",
        "pointer_events": "auto",
    }


def _capture_element(index, element_id, control):
    return {
        "index": index,
        "frame_path": "main",
        "tag": control["tag"],
        "id": element_id,
        "name": element_id,
        "type": control["type"],
        "role": "",
        "classes": [],
        "attributes": {
            "id": element_id,
            "name": element_id,
            "type": control["type"],
        },
        "text": "",
        "visible": control["visible"],
        "disabled": control["disabled"],
        "interaction_signals": _signals(),
        "shadow_root": False,
        "rect": {"x": 0, "y": 0, "width": 100, "height": 20},
    }


def _panel_element(index, panel_id, active):
    classes = ["r-tabs-panel"] + (["r-tabs-state-active"] if active else [])
    return {
        "index": index,
        "frame_path": "main",
        "tag": "div",
        "id": panel_id,
        "name": "",
        "type": "",
        "role": "",
        "classes": classes,
        "attributes": {"id": panel_id, "class": " ".join(classes)},
        "text": "",
        "visible": active,
        "disabled": False,
        "interaction_signals": _signals(),
        "shadow_root": False,
        "rect": {"x": 0, "y": 0, "width": 800, "height": 600},
    }


def _dom_capture_payload(*, origin, pathname, elements):
    url = origin + pathname
    counts = dict.fromkeys(
        ("forms", "inputs", "textareas", "selects", "buttons", "links", "tables"),
        0,
    )
    return {
        "schema_version": 1,
        "captured_at": "2024-01-01T00:00:00.000Z",
        "metadata": {
            "url": url,
            "origin": origin,
            "pathname": pathname,
            "title": "Mercurio",
            "ready_state": "complete",
            "content_type": "text/html",
            "character_set": "UTF-8",
        },
        "viewport": {
            "inner_width": 1280,
            "inner_height": 800,
            "client_width": 1280,
            "client_height": 800,
            "scroll_x": 0,
            "scroll_y": 0,
            "device_pixel_ratio": 1,
            "screen_x": 0,
            "screen_y": 0,
            "outer_width": 1280,
            "outer_height": 800,
        },
        "html": "<html></html>",
        "documents": [
            {
                "frame_path": "main",
                "url": url,
                "title": "Mercurio",
                "element_count": len(elements),
                **counts,
            }
        ],
        "elements": elements,
        "frames": [],
        "shadows": [],
        "counts": {
            "documents": 1,
            "elements": len(elements),
            **counts,
            "iframes": 0,
            "accessible_iframes": 0,
            "inaccessible_iframes": 0,
            "open_shadow_roots": 0,
        },
    }


_JSON_STRING = r'("(?:[^"\\]|\\.)*")'


class _StatefulMercurioBrowser:
    """CDP-style double whose controls keep real state. Read-back,
    local-probe and scroll scripts are recognised by their production
    markers; every other short script is treated as a DOM write."""

    def __init__(self, controls, *, origin=MERCURIO_LAB_ORIGIN,
                 pathname=MERCURIO_INICIO_PATH, readiness=True,
                 supports_readback=True, panels=None):
        self.controls = controls
        # r-tabs panel id -> active, as seen by the full DOM capture.
        self.panels = dict(panels or {})
        self.origin = origin
        self.pathname = pathname
        self.probe_pathname = pathname
        self.readiness = readiness
        self.supports_readback = supports_readback
        self.capture_calls = 0
        self.probe_calls = 0
        self.readback_calls = 0
        self.readiness_calls = 0
        self.writes = []

    # -- dispatch -------------------------------------------------
    def evaluate(self, script):
        if len(script) > _CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return _dom_capture_payload(
                origin=self.origin,
                pathname=self.pathname,
                elements=[
                    _capture_element(index, element_id, control)
                    for index, (element_id, control)
                    in enumerate(self.controls.items())
                ] + [
                    _panel_element(len(self.controls) + index, panel_id, active)
                    for index, (panel_id, active)
                    in enumerate(self.panels.items())
                ],
            )

        if script.startswith(runner._FIELD_READBACK_MARKER):
            self.readback_calls += 1
            if not self.supports_readback:
                return True
            return self._readback(self._field_id(script))

        if script.startswith(runner._FIELD_LOCAL_PROBE_MARKER):
            self.probe_calls += 1
            return self._probe(self._field_id(script))

        if script.startswith(runner._FIELD_SCROLL_MARKER):
            return True

        if script.startswith("return !!("):
            self.readiness_calls += 1
            return self.readiness

        self.writes.append(script)
        return self._apply(script)

    # -- helpers --------------------------------------------------
    @staticmethod
    def _field_id(script):
        match = re.search(r'getElementById\(\s*"([^"]+)"\s*\)', script)
        if match is None:
            match = re.search(r'const id = "([^"]+)"', script)
        return match.group(1) if match else None

    def _readback(self, field_id):
        control = self.controls.get(field_id)
        if control is None:
            return {"exists": False}
        index = next(
            (
                i for i, (value, _text) in enumerate(control["options"])
                if value == control["value"]
            ),
            -1,
        )
        selected = control["options"][index] if index >= 0 else None
        return {
            "exists": True,
            "tag": control["tag"],
            "type": control["type"],
            "value": control["value"],
            "checked": control["checked"],
            "selected_index": index if control["tag"] == "select" else -1,
            "selected_value": (
                selected[0] if control["tag"] == "select" and selected else None
            ),
            "selected_text": (
                selected[1] if control["tag"] == "select" and selected else None
            ),
        }

    def _probe(self, field_id):
        control = self.controls.get(field_id)
        page = {"origin": self.origin, "pathname": self.probe_pathname}
        if control is None:
            return {"exists": False, **page}
        panel_id = control["panel_id"]
        return {
            "exists": True,
            **page,
            "visible": control["visible"],
            "disabled": control["disabled"],
            "interaction_signals": _signals(),
            "panel_id": panel_id,
            "panel_active": bool(panel_id) and control["panel_active"],
            "panel_inactive": bool(panel_id) and not control["panel_active"],
        }

    def _set(self, control, **changes):
        if control["sticky"]:
            control.update(changes)

    def _apply(self, script):
        field_id = self._field_id(script)
        control = self.controls.get(field_id)
        if control is None:
            return True

        if "const wantedValue = " in script:
            wanted_value = json.loads(
                re.search(r"const wantedValue = " + _JSON_STRING, script).group(1)
            )
            wanted_text = json.loads(
                re.search(r"const wantedText = " + _JSON_STRING, script).group(1)
            )
            for value, text in control["options"]:
                if (wanted_value and value == wanted_value) or (
                    wanted_text and _norm(text) == wanted_text
                ):
                    self._set(control, value=value)
                    return {"ok": True, "value": value, "selected": text}
            return {"ok": False, "reason": "NO_MATCH"}

        match = re.search(r"el\.checked = (true|false);", script)
        if match:
            self._set(control, checked=match.group(1) == "true")
            return {"ok": True, "checked": control["checked"]}

        match = re.search(r"(?:el|provincia)\.value\s*=\s*" + _JSON_STRING, script)
        if match:
            self._set(control, value=json.loads(match.group(1)))
        return True


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


@pytest.fixture
def fast_dependency_wait(monkeypatch):
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(
        runner, "_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS", 0.02
    )


# ---------------------------------------------------------------
# 1. Field-result control: INPUT / SELECT / CHECKBOX / RADIO
# ---------------------------------------------------------------


def test_input_ok_only_after_live_readback_matches(tmp_path):
    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    outcome = runner.set_value(
        browser, "campoTexto", "ValorFicticio1", session_dir=str(tmp_path)
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    assert browser.controls["campoTexto"]["value"] == "ValorFicticio1"
    assert browser.readback_calls == 1
    assert "reason=POSTCONDITION_VERIFIED" in _log_text(tmp_path)


def test_input_not_kept_by_page_is_failed_never_ok(tmp_path):
    browser = _StatefulMercurioBrowser(
        {"campoTexto": _control("input", "text", sticky=False)}
    )

    outcome = runner.set_value(
        browser, "campoTexto", "ValorPerdido42", session_dir=str(tmp_path)
    )

    assert outcome == runner.GOVERNED_OUTCOME_FAILED
    log_text = _log_text(tmp_path)
    assert "reason=INPUT_VALUE_MISMATCH" in log_text
    assert f"reason={STATE_AWARE_POSTCONDITION_NOT_VERIFIED}" in log_text
    assert "ValorPerdido42" not in log_text


def test_readback_unavailable_is_never_a_false_ok(tmp_path):
    """A browser that answers ``True`` to every script (the legacy
    fake shape) cannot prove the value: FAILED, not OK."""

    browser = _StatefulMercurioBrowser(
        {"campoTexto": _control("input", "text")}, supports_readback=False
    )

    outcome = runner.set_value(
        browser, "campoTexto", "Valor", session_dir=str(tmp_path)
    )

    assert outcome == runner.GOVERNED_OUTCOME_FAILED
    assert "reason=READBACK_UNAVAILABLE" in _log_text(tmp_path)


def test_select_ok_only_when_option_is_selected(tmp_path):
    browser = _StatefulMercurioBrowser(
        {"campoSelect": _control("select", options=[("", "-"), ("OPT2", "Dos")])}
    )

    outcome = runner.select_by_text_or_value(
        browser, "campoSelect", value="OPT2", session_dir=str(tmp_path)
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    assert browser.controls["campoSelect"]["value"] == "OPT2"


@pytest.mark.parametrize(
    ("kwargs", "sticky", "reason"),
    [
        ({"value": "NO_EXISTE_OPT"}, True, "NO_MATCH"),
        ({"text": "Seleccione"}, True, "SELECT_PLACEHOLDER_ONLY"),
        ({"value": "OPT2"}, False, "SELECT_OPTION_NOT_SELECTED"),
    ],
)
def test_select_unmatched_placeholder_or_reset_is_failed(
    tmp_path, kwargs, sticky, reason
):
    browser = _StatefulMercurioBrowser(
        {
            "campoSelect": _control(
                "select",
                options=[("", "Seleccione"), ("OPT2", "Dos")],
                sticky=sticky,
            )
        }
    )

    outcome = runner.select_by_text_or_value(
        browser, "campoSelect", session_dir=str(tmp_path), **kwargs
    )

    assert outcome == runner.GOVERNED_OUTCOME_FAILED
    assert f"reason={reason}" in _log_text(tmp_path)


def test_checkbox_and_radio_verify_checked_state(tmp_path):
    browser = _StatefulMercurioBrowser(
        {
            "campoCheck": _control("input", "checkbox"),
            "campoRadio": _control("input", "radio"),
        }
    )

    assert runner.set_checkbox(
        browser, "campoCheck", value="SI", session_dir=str(tmp_path)
    ) == runner.GOVERNED_OUTCOME_OK
    assert runner.set_radio_checked(
        browser, "campoRadio", checked=True, session_dir=str(tmp_path)
    ) == runner.GOVERNED_OUTCOME_OK
    assert browser.controls["campoCheck"]["checked"] is True
    assert browser.controls["campoRadio"]["checked"] is True


@pytest.mark.parametrize(
    ("field_id", "element_type", "writer"),
    [
        ("campoCheck", "checkbox", lambda b, s: runner.set_checkbox(
            b, "campoCheck", value="SI", session_dir=s)),
        ("campoRadio", "radio", lambda b, s: runner.set_radio_checked(
            b, "campoRadio", checked=True, session_dir=s)),
    ],
)
def test_checked_state_not_kept_is_failed(tmp_path, field_id, element_type, writer):
    browser = _StatefulMercurioBrowser(
        {field_id: _control("input", element_type, sticky=False)}
    )

    assert writer(browser, str(tmp_path)) == runner.GOVERNED_OUTCOME_FAILED
    assert "_STATE_MISMATCH" in _log_text(tmp_path)


def test_piso_select_verified_against_selected_option(tmp_path):
    browser = _StatefulMercurioBrowser(
        {"extPiso": _control("select", options=[("", "-"), ("P05", "PISO 05")])}
    )

    # The fake does not run the piso matching JS: emulate its result
    # by pre-binding the apply output through a real stateful write.
    original_apply = browser._apply

    def _apply(script):
        if "NO_MATCH_PISO_NUMERICO" in script:
            browser._set(browser.controls["extPiso"], value="P05")
            return {"ok": True, "mode": "piso_exact", "selectedValue": "P05"}
        return original_apply(script)

    browser._apply = _apply

    outcome = runner.set_piso_mercurio(
        browser, "extPiso", value="5", session_dir=str(tmp_path)
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    assert "PISO 05" not in _log_text(tmp_path)


def test_executor_error_with_postcondition_is_failed(tmp_path):
    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    def _boom():
        raise ValueError("QCC_TEST_APPLY_FAILURE")

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=_boom,
        session_dir=str(tmp_path),
        verify=lambda: True,
    )

    assert result.executed is True
    assert result.reason == "EXECUTION_ERROR"
    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN
    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_FAILED


@pytest.mark.parametrize("verify", [lambda: False, Mock(side_effect=RuntimeError())])
def test_postcondition_false_or_raising_fails_closed(tmp_path, verify):
    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: None,
        session_dir=str(tmp_path),
        verify=verify,
    )

    assert result.reason == STATE_AWARE_POSTCONDITION_NOT_VERIFIED
    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN
    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_FAILED


def test_postcondition_true_is_confirmed(tmp_path):
    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: None,
        session_dir=str(tmp_path),
        verify=lambda: True,
    )

    assert result.reason == STATE_AWARE_POSTCONDITION_VERIFIED
    assert result.disposition == ACTION_DISPOSITION_CONFIRMED
    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_OK


def test_transition_write_failed_postcondition_is_never_ok(tmp_path):
    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: None,
        session_dir=str(tmp_path),
        expects_state_transition=True,
        verify=lambda: False,
    )

    assert runner._governed_outcome(result) != runner.GOVERNED_OUTCOME_OK


def test_form_control_write_without_postcondition_is_never_ok(tmp_path):
    """Executor success plus an unchanged fingerprint is only
    EXECUTION_ATTEMPTED: without an observed read-back it is not OK."""

    browser = _StatefulMercurioBrowser({"campoTexto": _control("input", "text")})

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: None,
        session_dir=str(tmp_path),
    )

    assert result.executed is True
    assert result.reason == STATE_AWARE_POSTCONDITION_NOT_VERIFIED
    assert result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN
    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_FAILED


def test_field_result_logs_never_contain_personal_values(tmp_path):
    browser = _StatefulMercurioBrowser(
        {
            "campoTexto": _control("input", "text", sticky=False),
            "campoSelect": _control(
                "select", options=[("OPC_SECRETA_77", "Opcion secreta")],
                sticky=False,
            ),
        }
    )

    runner.set_value(browser, "campoTexto", "NOMBRE_PERSONAL_9F", session_dir=str(tmp_path))
    runner.select_by_text_or_value(
        browser, "campoSelect", value="OPC_SECRETA_77", session_dir=str(tmp_path)
    )

    log_text = _log_text(tmp_path)
    assert "NOMBRE_PERSONAL_9F" not in log_text
    assert "OPC_SECRETA_77" not in log_text
    assert "Opcion secreta" not in log_text


# ---------------------------------------------------------------
# 2. Pre-form automation keeps real postconditions
# ---------------------------------------------------------------


def _run_preform(browser, tmp_path):
    with (
        patch.object(runner, "wait_for_js", return_value=True),
        patch.object(runner, "click_js", return_value=True),
        patch.object(runner, "save_page_source", return_value="capture.html"),
    ):
        return runner.step_presentar_nueva_solicitud(
            browser, "33", str(tmp_path), reporter=Mock()
        )


def test_preform_bi_and_provincia_are_verified(tmp_path):
    browser = _StatefulMercurioBrowser(
        {
            "bscIniciales": _control("input", "radio"),
            "provincia": _control("select", options=[("", "-"), ("33", "ASTURIAS")]),
        }
    )

    result = _run_preform(browser, tmp_path)

    assert result["ok"] is True
    assert result["radio_outcome"] == runner.GOVERNED_OUTCOME_OK
    assert result["provincia_outcome"] == runner.GOVERNED_OUTCOME_OK
    assert browser.controls["provincia"]["value"] == "33"


def test_preform_provincia_not_kept_is_not_ok(tmp_path):
    browser = _StatefulMercurioBrowser(
        {
            "bscIniciales": _control("input", "radio"),
            "provincia": _control(
                "select", options=[("", "-"), ("33", "ASTURIAS")], sticky=False
            ),
        }
    )

    result = _run_preform(browser, tmp_path)

    assert result["ok"] is False
    assert result["provincia_outcome"] == runner.GOVERNED_OUTCOME_FAILED


# ---------------------------------------------------------------
# 3. Section capture reuse: only with same page/surface/selector
# ---------------------------------------------------------------


def test_section_reuses_one_capture_for_ordinary_writes(tmp_path):
    browser = _StatefulMercurioBrowser(
        {
            "campoA": _control("input", "text"),
            "campoB": _control("input", "text"),
            "campoC": _control("input", "text"),
        }
    )

    result = runner.fill_section(
        browser,
        {"campoA": "uno", "campoB": "dos", "campoC": "tres"},
        str(tmp_path),
    )

    assert result["ok"] is True
    assert browser.capture_calls == 1
    assert browser.probe_calls == 2
    assert [c["value"] for c in browser.controls.values()] == ["uno", "dos", "tres"]
    assert "GOVERNED_SECTION_CLOSED label=fill_section" in _log_text(tmp_path)
    assert "reused_captures=2" in _log_text(tmp_path)


def test_section_page_change_forces_fresh_capture(tmp_path):
    browser = _StatefulMercurioBrowser(
        {"campoA": _control("input", "text"), "campoB": _control("input", "text")}
    )

    with runner.governed_section(browser, str(tmp_path), label="T"):
        assert runner.set_value(browser, "campoA", "uno", session_dir=str(tmp_path)) == "OK"
        browser.probe_pathname = "/mercurio/otraPagina.html"
        assert runner.set_value(browser, "campoB", "dos", session_dir=str(tmp_path)) == "OK"

    assert browser.capture_calls == 2


def test_section_reuses_capture_only_for_the_panel_it_saw_active(tmp_path):
    """Same page, every probed panel active, but the section capture
    recognized another panel: the functional state changed, so the
    capture is never reused for it."""

    browser = _StatefulMercurioBrowser(
        {
            "campoA": _control("input", "text", panel_id="tab-datos_personales"),
            "campoA2": _control("input", "text", panel_id="tab-datos_personales"),
            "campoB": _control("input", "text", panel_id="tab-datos_notificacion"),
        },
        panels={"tab-datos_personales": True, "tab-datos_notificacion": False},
    )
    session_dir = str(tmp_path)

    with runner.governed_section(browser, session_dir, label="T") as section:
        assert runner.set_value(browser, "campoA", "uno", session_dir=session_dir) == "OK"
        assert runner.set_value(browser, "campoA2", "dos", session_dir=session_dir) == "OK"
        assert browser.capture_calls == 1
        assert section.reused_count == 1

        browser.panels = {"tab-datos_personales": False, "tab-datos_notificacion": True}
        assert runner.set_value(browser, "campoB", "tres", session_dir=session_dir) == "OK"

    assert browser.capture_calls == 2
    assert section.reused_count == 1


def test_inactive_panel_control_is_never_written_from_reused_capture(
    tmp_path, fast_dependency_wait
):
    """The section capture saw ``campoB`` visible; by the time it is
    written its panel is inactive. The stale capture is never reused:
    a fresh capture is taken and the unchanged gate denies it."""

    browser = _StatefulMercurioBrowser(
        {
            "campoA": _control("input", "text", panel_id="tab-datos_personales"),
            "campoB": _control("input", "text", panel_id="tab-datos_notificacion"),
        }
    )

    with runner.governed_section(browser, str(tmp_path), label="T"):
        assert runner.set_value(browser, "campoA", "uno", session_dir=str(tmp_path)) == "OK"
        browser.controls["campoB"].update(visible=False, panel_active=False)
        outcome = runner.set_value(browser, "campoB", "dos", session_dir=str(tmp_path))

    assert outcome == runner.GOVERNED_OUTCOME_DENIED
    assert browser.controls["campoB"]["value"] == ""
    assert not any('"campoB"' in script for script in browser.writes)
    assert browser.capture_calls >= 2


def test_non_ordinary_write_never_reuses_section_capture(tmp_path):
    browser = _StatefulMercurioBrowser(
        {"campoA": _control("input", "text"), "btnFoo": _control("button")}
    )

    with runner.governed_section(browser, str(tmp_path), label="T"):
        runner.set_value(browser, "campoA", "uno", session_dir=str(tmp_path))
        captures_before = browser.capture_calls
        result = runner._governed_write(
            browser,
            action_kind="BUTTON",
            field_id="btnFoo",
            apply=lambda: pytest.fail("HUMAN_ONLY button must never run"),
            session_dir=str(tmp_path),
        )

    assert browser.capture_calls > captures_before
    assert result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN


# ---------------------------------------------------------------
# 4. with_local_target_interaction: derive, never assert
# ---------------------------------------------------------------


def _captured(kind="INPUT_VALUE", selector="#campo"):
    return CapturedSnapshot(
        snapshot={
            "page": {"url": MERCURIO_LAB_ORIGIN + MERCURIO_INICIO_PATH},
            "actions": [
                {
                    "kind": kind,
                    "selector": selector,
                    "frame_path": "main",
                    "interaction": {
                        "state": "INTERACTABLE",
                        "visible": True,
                        "interactable": True,
                        "disabled": False,
                    },
                }
            ],
        },
        captured_at=datetime.now(timezone.utc),
    )


def _local(**overrides):
    probe = {
        "exists": True,
        "visible": True,
        "disabled": False,
        "interaction_signals": _signals(),
        "panel_id": "tab-datos_personales",
        "panel_active": True,
        "panel_inactive": False,
    }
    probe.update(overrides)
    return probe


def _intent(kind="INPUT_VALUE", transition=False):
    return ActionIntent(
        action_kind=kind,
        action_selector="#campo",
        expects_state_transition=transition,
    )


def test_local_interaction_rederives_interactable_control():
    derived = with_local_target_interaction(_captured(), _intent(), _local())

    interaction = derived.snapshot["actions"][0]["interaction"]
    assert interaction["state"] == "INTERACTABLE"
    assert interaction["interactable"] is True


@pytest.mark.parametrize(
    ("overrides", "state"),
    [
        ({"visible": False}, "HIDDEN"),
        ({"disabled": True}, "DISABLED"),
        ({"interaction_signals": _signals(in_viewport=False)}, "OFF_VIEWPORT"),
    ],
)
def test_local_interaction_never_upgrades_a_blocked_control(overrides, state):
    derived = with_local_target_interaction(
        _captured(), _intent(), _local(**overrides)
    )

    interaction = derived.snapshot["actions"][0]["interaction"]
    assert interaction["state"] == state
    assert interaction["interactable"] is False


@pytest.mark.parametrize(
    ("captured_kind", "intent", "probe"),
    [
        ("INPUT_VALUE", _intent(), _local(panel_inactive=True, panel_active=False)),
        ("INPUT_VALUE", _intent(), _local(exists=False)),
        ("INPUT_VALUE", _intent(), _local(interaction_signals=None)),
        ("INPUT_VALUE", _intent(transition=True), _local()),
        ("BUTTON", _intent(kind="BUTTON"), _local()),
    ],
)
def test_local_interaction_refuses_without_evidence(captured_kind, intent, probe):
    assert with_local_target_interaction(
        _captured(kind=captured_kind), intent, probe
    ) is None


def test_preloaded_inactive_panel_exception_is_not_ported():
    assert not hasattr(sae, "with_preloaded_target_interaction")
    assert "with_preloaded_target_interaction" not in RUNNER_PATH.read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------
# 5. EX01 familiar surface recognition
# ---------------------------------------------------------------


def _family_snapshot(active_ids, pathname="/mercurio/nuevaSolicitud-EX01.html"):
    return {
        "page": {"url": MERCURIO_LAB_ORIGIN + pathname, "origin": MERCURIO_LAB_ORIGIN},
        "elements": [
            {"id": panel_id, "class": "r-tabs-panel r-tabs-state-active"}
            for panel_id in active_ids
        ],
    }


def test_family_surface_recognized_only_when_sole_active_panel():
    recognize = runner._ex01_family_surface_recognizer(lambda _s: None)

    assert recognize(_family_snapshot(["tab-datos_familiar"])) == (
        runner.EX01_FAMILY_FUNCTIONAL_STATE
    )
    assert recognize(
        _family_snapshot(["tab-datos_familiar", "tab-datos_personales"])
    ) is None
    assert recognize(_family_snapshot([])) is None
    assert recognize(
        _family_snapshot(["tab-datos_familiar"], "/mercurio/nuevaSolicitud-EX02.html")
    ) is None


def test_family_surface_never_overrides_recognized_state():
    recognize = runner._ex01_family_surface_recognizer(lambda _s: "EX01_PERSONAL")

    assert recognize(_family_snapshot(["tab-datos_familiar"])) == "EX01_PERSONAL"


# ---------------------------------------------------------------
# 6. PRESENTATION_ABORT serviced during waits
# ---------------------------------------------------------------


class FakeActionClient:
    def __init__(self, actions):
        self.actions = list(actions)

    def consume_next(self):
        if not self.actions:
            return None
        return self.actions.pop(0)


ABORT = {"action_id": 99, "action": "PRESENTATION_ABORT", "payload": {}}


@pytest.fixture
def no_console(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_k: pytest.fail("console ENTER fallback used under QCC"),
    )


def test_human_navigation_abort_is_serviced_during_wait(tmp_path, no_console):
    browser = _StatefulMercurioBrowser({}, readiness=False)
    abort_handler = Mock(return_value=True)
    reporter = Mock()

    result = runner.wait_for_human_navigation(
        browser,
        str(tmp_path),
        "Datos del presentador",
        "document.getElementById('preNombrePresentador')",
        timeout=5,
        interval=0.01,
        qcc_reporter=reporter,
        action_client=FakeActionClient([ABORT]),
        abort_handler=abort_handler,
    )

    assert result["mode"] == "aborted"
    assert result["browser_closed"] is True
    abort_handler.assert_called_once_with()
    reporter.aborted.assert_called_once()
    reporter.user_action_detected.assert_not_called()


def test_human_navigation_timeout_under_qcc_has_no_console_fallback(
    tmp_path, no_console
):
    browser = _StatefulMercurioBrowser({}, readiness=False)

    result = runner.wait_for_human_navigation(
        browser,
        str(tmp_path),
        "Datos del presentador",
        "document.getElementById('preNombrePresentador')",
        timeout=0.2,
        interval=0.02,
        action_client=FakeActionClient([]),
    )

    assert result["ok"] is False
    assert result["mode"] == "human_navigation_timeout"


def test_human_navigation_confirmed_under_qcc(tmp_path, no_console):
    browser = _StatefulMercurioBrowser({}, readiness=True)

    result = runner.wait_for_human_navigation(
        browser,
        str(tmp_path),
        "Datos del presentador",
        "document.getElementById(\n'preNombrePresentador'\n)",
        timeout=1,
        interval=0.01,
        action_client=FakeActionClient([]),
    )

    assert result == {
        "ok": True,
        "mode": "human_dom_detected",
        "label": "Datos del presentador",
    }


def test_one_line_js_collapses_multiline_predicates():
    assert runner._one_line_js("(a\n  && b)") == "(a && b)"
    assert runner._one_line_js("a // comment\n b") == "a // comment\n b"


def test_ex01_readiness_wait_services_abort(tmp_path):
    browser = _StatefulMercurioBrowser({}, readiness=False)
    abort_handler = Mock(return_value=True)

    result = runner._wait_for_ex01_personal_readiness(
        browser,
        str(tmp_path),
        {"extranjero": {"extPasaporte": "X0000000"}},
        timeout=5,
        interval=0.01,
        action_client=FakeActionClient([ABORT]),
        abort_handler=abort_handler,
    )

    assert result["mode"] == "aborted"
    abort_handler.assert_called_once_with()
    assert "EX01_READY\n" not in _log_text(tmp_path)


def test_operator_control_wait_returns_abort(tmp_path):
    abort_handler = Mock(return_value=False)

    result = runner.wait_for_qcc_operator_control(
        FakeActionClient([{"action_id": 1, "action": "DOCUMENTS_START"}, ABORT]),
        str(tmp_path),
        abort_handler=abort_handler,
        step="AUTO_FLOW_BLOCKED",
        poll_interval=0,
    )

    assert result["mode"] == "aborted"
    assert result["browser_closed"] is False
    assert "acción inesperada descartada DOCUMENTS_START" in _log_text(tmp_path)


def test_operator_control_wait_is_bounded_and_optional(tmp_path):
    assert runner.wait_for_qcc_operator_control(
        None, str(tmp_path), step="X"
    ) is None
    assert runner.wait_for_qcc_operator_control(
        object(), str(tmp_path), step="X"
    ) is None

    result = runner.wait_for_qcc_operator_control(
        FakeActionClient([]), str(tmp_path), step="X", timeout=0.05, poll_interval=0.01
    )
    assert result == {"ok": False, "mode": "operator_control_timeout", "label": "X"}


def test_fill_start_without_consumable_channel_never_polls_forever(tmp_path):
    result = runner.wait_for_qcc_fill_start(object(), str(tmp_path), poll_interval=0)

    assert result == {"ok": False, "mode": "fill_start_channel_unavailable"}


def _run_auto_patches(**overrides):
    ok = {"ok": True}
    defaults = {
        "step_continuar_inicial": ok,
        "pause_certificado": ok,
        "step_presentar_nueva_solicitud": ok,
        "pause_supuesto": ok,
        "wait_for_qcc_fill_start": ok,
        "_wait_for_ex01_personal_readiness": ok,
        "fill_datos_extranjero": ok,
        "click_continuar": ok,
        "fill_datos_presentador": True,
        "click_continuar_presentador": ok,
        "pause_humana_final_presentacion": ok,
    }
    defaults.update(overrides)
    return [
        patch.object(runner, name, return_value=value)
        for name, value in defaults.items()
    ]


def _run_auto(tmp_path, patches, action_client=None, abort_handler=None):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = {p.attribute: stack.enter_context(p) for p in patches}
        result = runner.run_auto(
            object(),
            "33",
            {"extranjero": {"extPasaporte": "X1"}},
            str(tmp_path),
            action_client=action_client,
            abort_handler=abort_handler,
        )
    return result, mocks


def test_run_auto_threads_controls_into_every_ex01_wait(tmp_path):
    client = FakeActionClient([])
    handler = Mock()

    _result, mocks = _run_auto(tmp_path, _run_auto_patches(), client, handler)

    for name in (
        "pause_certificado",
        "pause_supuesto",
        "_wait_for_ex01_personal_readiness",
        "click_continuar",
        "click_continuar_presentador",
        "pause_humana_final_presentacion",
    ):
        kwargs = mocks[name].call_args.kwargs
        assert kwargs["action_client"] is client, name
        assert kwargs["abort_handler"] is handler, name


def test_run_auto_propagates_abort_from_certificate_wait(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "browser_closed": True}

    result, mocks = _run_auto(
        tmp_path, _run_auto_patches(pause_certificado=aborted), FakeActionClient([])
    )

    assert result is aborted
    mocks["step_presentar_nueva_solicitud"].assert_not_called()


def test_run_auto_stops_when_human_continue_is_not_confirmed(tmp_path):
    timeout = {"ok": False, "mode": "human_navigation_timeout"}

    result, mocks = _run_auto(
        tmp_path, _run_auto_patches(click_continuar=timeout), FakeActionClient([])
    )

    assert result == {
        "ok": False,
        "label": "CONTINUE_TO_PRESENTER_NOT_CONFIRMED",
        "detail": timeout,
    }
    mocks["fill_datos_presentador"].assert_not_called()


def test_run_auto_returns_abort_from_human_continue_unwrapped(tmp_path):
    aborted = {"ok": False, "mode": "aborted", "browser_closed": True}

    result, mocks = _run_auto(
        tmp_path,
        _run_auto_patches(click_continuar_presentador=aborted),
        FakeActionClient([]),
    )

    assert result is aborted
    mocks["pause_humana_final_presentacion"].assert_not_called()


def test_run_auto_with_qcc_does_not_report_abort_as_blocked(tmp_path):
    aborted = {"ok": False, "label": "FILL_START_NOT_CONFIRMED",
               "detail": {"ok": False, "mode": "aborted"}}
    reporter = Mock()

    with patch.object(runner, "run_auto", return_value=aborted):
        result = runner.run_auto_with_qcc(
            object(), "33", {}, str(tmp_path), reporter=reporter
        )

    assert result is aborted
    assert all(
        call.kwargs.get("step") != "AUTO_FLOW_BLOCKED"
        for call in reporter.waiting_user.call_args_list
    )
    assert "QCC auto flow ABORTADO" in _log_text(tmp_path)


def test_blocked_flow_keeps_abort_serviceable(tmp_path):
    blocked = {"ok": False, "label": "EXTRANJERO_BLOCKED",
               "detail": {"ok": False, "blocked_field": "extNie",
                          "blocked_outcome": "FAILED"}}
    abort_handler = Mock(return_value=True)

    with (
        patch.object(runner, "run_auto_with_qcc", return_value=blocked),
        patch.object(runner, "wait_for_qcc_documents_start") as docs,
    ):
        result = runner.run_auto_and_documents_with_qcc(
            object(), "33", {}, str(tmp_path), str(tmp_path),
            action_client=FakeActionClient([ABORT]),
            abort_handler=abort_handler,
        )

    assert result["mode"] == "aborted"
    abort_handler.assert_called_once_with()
    docs.assert_not_called()


@pytest.mark.parametrize("closed", [True, False])
def test_finish_aborted_presentation_releases_only_confirmed_close(tmp_path, closed):
    connector = object()
    lifecycle = {"connector": connector}

    runner._finish_aborted_presentation(
        {"ok": False, "label": "FILL_START_NOT_CONFIRMED",
         "detail": {"ok": False, "mode": "aborted", "browser_closed": closed}},
        str(tmp_path),
        lifecycle,
    )

    assert lifecycle["connector"] is (None if closed else connector)


# ---------------------------------------------------------------
# 7. Readiness diagnostic: structural, value-free
# ---------------------------------------------------------------


def test_readiness_timeout_diagnostic_is_structural_without_pii(tmp_path):
    browser = _StatefulMercurioBrowser({}, readiness=False)
    datos = {"extranjero": {"extPasaporte": "PASAPORTE_PII_123", "extNie": "NIE_PII_9"}}

    result = runner._wait_for_ex01_personal_readiness(
        browser, str(tmp_path), datos, timeout=0.1, interval=0.02
    )

    assert result["ok"] is False
    assert result["mode"] == "ex01_readiness_timeout"
    assert [entry["field"] for entry in result["diagnostic"]] == [
        "extPasaporte", "extNie",
    ]
    for entry in result["diagnostic"]:
        assert set(entry) <= set(runner.EX01_READINESS_DIAGNOSTIC_KEYS)
        assert all(
            value is None or isinstance(value, bool)
            for key, value in entry.items()
            if key != "field"
        )

    log_text = _log_text(tmp_path)
    assert "EX01_READINESS_DIAGNOSTIC phase=initial" in log_text
    assert "EX01_READINESS_DIAGNOSTIC phase=timeout" in log_text
    assert "PASAPORTE_PII_123" not in log_text
    assert "NIE_PII_9" not in log_text
    assert "PASAPORTE_PII_123" not in json.dumps(result)


def test_readiness_diagnostic_probes_never_read_values():
    for _key, expression in runner.EX01_READINESS_DIAGNOSTIC_PROBES:
        script = runner._ex01_diagnostic_probe_js("extNie", expression)
        assert script.startswith("return !!(")
        assert ".value" not in script
        assert "textContent" not in script


def test_readiness_diagnostic_unreadable_dom_is_fail_open(tmp_path):
    class _Broken:
        def evaluate(self, script):
            raise RuntimeError("cdp gone")

    assert runner._ex01_readiness_diagnostic(
        _Broken(), {"extranjero": {"extNie": "Y"}}, str(tmp_path)
    ) == []


# ---------------------------------------------------------------
# 8. Automated pre-form vs EX01 form CONTINUAR/CONCLUIR HUMAN_ONLY
# ---------------------------------------------------------------


def _function_source(name):
    source = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    return ast.get_source_segment(source, node)


def test_preform_automates_only_native_preform_entry_points():
    automated = {
        "step_continuar_inicial": ("continuar('INI');",),
        "pause_certificado": ("validarYEnviar('AB');",),
        "step_presentar_nueva_solicitud": ("mostrarOpcion();", "irOpcion();", '".mdCer"'),
    }

    for name, tokens in automated.items():
        block = _function_source(name)
        for token in tokens:
            assert token in block, (name, token)
        assert "btnConcluir" not in block
        assert "btnContinuar" not in block


@pytest.mark.parametrize(
    "name",
    [
        "click_continuar",
        "click_continuar_extranjero_to_familiar",
        "click_continuar_familiar_to_presentador",
        "click_continuar_presentador",
        "pause_humana_final_presentacion",
    ],
)
def test_ex01_form_continue_and_conclude_stay_human_only(name):
    block = _function_source(name)

    for forbidden in (
        "click_js(",
        "execute_script",
        "_governed_write(",
        ".click(",
        "send_keys(",
        " js(",
        "continuar('",
        "btnConcluir",
    ):
        assert forbidden not in block, (name, forbidden)

    assert "wait_for_human_navigation(" in block
    assert "action_client=action_client" in block
    assert "abort_handler=abort_handler" in block


def test_mercurio_policy_keeps_form_buttons_human_only():
    rules = build_mercurio_interaction_policy().action_kind_rules

    assert rules["BUTTON"] == "HUMAN_ONLY"
    assert rules["SUBMIT"] == "HUMAN_ONLY"
    for kind in ("INPUT_VALUE", "SELECT", "CHECKBOX", "RADIO"):
        assert rules[kind] == "AUTOMATION_ALLOWED"

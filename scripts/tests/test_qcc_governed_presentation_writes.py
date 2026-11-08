"""Real end-to-end tests for QCC CLOSE2 governed presentation writes.

Exercises the ACTUAL production helpers in
``app.run_presentacion_asistida`` (``set_value``, ``select_by_text_or_value``,
``set_checkbox``, ``set_radio_checked``, ``set_piso_mercurio``,
``fill_section`` and ``_governed_write`` itself) through the real
``backend.automation.site_architecture`` state-aware execution chain
and Mercurio's already-certified site policy/profile/state recognizer.

Only the physical browser is faked (a CDP-style double exposing
``evaluate``, dispatching on script size like the existing CLOSE1
governed-input-value test): everything downstream of it is the real
code path. ``_governed_write`` is called directly in a few tests but
never replaced/mocked.
"""

from pathlib import Path

import app.run_presentacion_asistida as runner
from backend.automation.site_architecture.site_target import SiteEnvironment
from backend.automation.site_architecture.state_aware_execution import (
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
)


MERCURIO_INICIO_PATH = "/mercurio/inicioMercurio.html"

# The real DOM-capture IIFE (``backend.automation.dom_inspector``) is
# tens of thousands of characters; real action scripts (including the
# verbose SELECT-based ``select_by_text_or_value``/``set_piso_mercurio``
# matching logic) top out at a few thousand. 2000 was calibrated only
# against the short INPUT_VALUE/CHECKBOX/RADIO scripts and collided
# with those larger, but still legitimately small, action scripts.
_CAPTURE_SCRIPT_SIZE_THRESHOLD = 10000


def _interaction_signals():
    return {
        "hidden": False,
        "aria_hidden": False,
        "aria_disabled": False,
        "readonly": False,
        "in_viewport": True,
        "opacity": "1",
        "pointer_events": "auto",
    }


def _element(index, *, tag, element_id, element_type=""):
    return {
        "index": index,
        "frame_path": "main",
        "tag": tag,
        "id": element_id,
        "name": element_id,
        "type": element_type,
        "role": "",
        "classes": [],
        "attributes": {
            "id": element_id,
            "name": element_id,
            "type": element_type,
        },
        "text": "",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
        "shadow_root": False,
        "rect": {"x": 0, "y": 0, "width": 100, "height": 20},
    }


DEFAULT_ELEMENTS = [
    _element(0, tag="input", element_id="campoTexto", element_type="text"),
    _element(1, tag="select", element_id="campoSelect"),
    _element(2, tag="input", element_id="campoCheck", element_type="checkbox"),
    _element(3, tag="input", element_id="campoRadio", element_type="radio"),
    _element(4, tag="select", element_id="extPiso"),
    _element(5, tag="button", element_id="btnFoo"),
]

# QCC_ASSISTED_POLICY_AUTOTWIN_V3: reproduces the exact confirmed
# incident sequence (bscIniciales RADIO -> provincia SELECT ->
# extPasaporte INPUT_VALUE) with every element already
# visible/enabled/interactable, the same canonical shape a real
# Mercurio form-fill capture presents once the prerequisite controls
# have been set.
MERCURIO_SEQUENCE_ELEMENTS = [
    _element(0, tag="input", element_id="bscIniciales", element_type="radio"),
    _element(1, tag="select", element_id="provincia"),
    _element(2, tag="input", element_id="extPasaporte", element_type="text"),
]


def _dom_capture_payload(*, origin, pathname, elements):
    url = origin + pathname
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
                "forms": 0,
                "inputs": 0,
                "textareas": 0,
                "selects": 0,
                "buttons": 0,
                "links": 0,
                "tables": 0,
            }
        ],
        "elements": elements,
        "frames": [],
        "shadows": [],
        "counts": {
            "documents": 1,
            "elements": len(elements),
            "forms": 0,
            "inputs": 0,
            "textareas": 0,
            "selects": 0,
            "buttons": 0,
            "links": 0,
            "tables": 0,
            "iframes": 0,
            "accessible_iframes": 0,
            "inaccessible_iframes": 0,
            "open_shadow_roots": 0,
        },
    }


class _FakeCdpBrowser:
    """Duck-typed CDP-style browser: only exposes ``evaluate``.

    Dispatches on script size, same convention as the existing CLOSE1
    ``test_qcc_mercurio_governed_input_value.py`` fixture: the DOM
    capture IIFE is large, the executor's action scripts are small.
    """

    def __init__(self, *, origin, pathname=MERCURIO_INICIO_PATH, elements=None, raise_on_action=False):
        self.origin = origin
        self.pathname = pathname
        self.elements = elements if elements is not None else DEFAULT_ELEMENTS
        self.action_calls = []
        self.capture_calls = 0
        self.raise_on_action = raise_on_action

    def evaluate(self, script):
        if len(script) > _CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return _dom_capture_payload(
                origin=self.origin,
                pathname=self.pathname,
                elements=self.elements,
            )

        self.action_calls.append(script)

        if self.raise_on_action:
            raise RuntimeError("QCC_TEST_FORCED_EXECUTION_FAILURE")

        return True


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


# A. successful governed INPUT write.
def test_governed_input_write_success(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.set_value(
        browser, "campoTexto", "ValorDePrueba123", session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    assert len(browser.action_calls) == 1
    assert "ValorDePrueba123" in browser.action_calls[0]
    assert "campoTexto" in browser.action_calls[0]


# B. empty INPUT remains skipped.
def test_input_empty_value_remains_skipped(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.set_value(browser, "campoTexto", "", session_dir=session_dir)

    assert outcome == runner.GOVERNED_OUTCOME_SKIPPED
    assert browser.action_calls == []
    assert browser.capture_calls == 0


# C. successful governed SELECT and expected change event.
def test_governed_select_write_preserves_change_event_semantics(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.select_by_text_or_value(
        browser, "campoSelect", value="OPT2", session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    assert len(browser.action_calls) == 1
    script = browser.action_calls[0]
    assert "dispatchEvent(new Event('change'" in script
    assert "jQuery" in script


# D. governed CHECKBOX with empty value normalization.
def test_governed_checkbox_empty_value_normalization_preserved(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.set_checkbox(
        browser, "campoCheck", value="SI", session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    script = browser.action_calls[0]
    assert "el.value = 'true'" in script


# E. governed RADIO.
def test_governed_radio_checked(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.set_radio_checked(
        browser, "campoRadio", checked=True, session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    script = browser.action_calls[0]
    assert "el.checked = true" in script
    assert "dispatchEvent(new Event('change'" in script
    # QCC_ASSISTED_POLICY_AUTOTWIN_V3: RADIO must notify Mercurio's
    # jQuery-bound field-reveal handlers the same way CHECKBOX/SELECT
    # already do, so a dependent canonical field becomes visible
    # before QCC evaluates it for governance.
    assert "jQuery" in script


# QCC_ASSISTED_POLICY_AUTOTWIN_V3: canonical qcc_assisted form-fill
# regression -- reproduces the exact confirmed incident sequence
# (bscIniciales RADIO -> provincia SELECT -> extPasaporte INPUT_VALUE)
# through fill_section, proving every canonical mapper write,
# including the personal-data INPUT_VALUE field, resolves to
# EXECUTION_ALLOWED/OK end to end.
def test_canonical_mercurio_sequence_allows_personal_data_input_value(
    tmp_path,
):
    browser = _FakeCdpBrowser(
        origin=MERCURIO_LAB_ORIGIN,
        elements=MERCURIO_SEQUENCE_ELEMENTS,
    )
    session_dir = str(tmp_path)

    radio_outcome = runner.set_radio_checked(
        browser, "bscIniciales", checked=True, session_dir=session_dir
    )
    assert radio_outcome == runner.GOVERNED_OUTCOME_OK

    select_outcome = runner.select_by_text_or_value(
        browser, "provincia", value="OPT1", session_dir=session_dir
    )
    assert select_outcome == runner.GOVERNED_OUTCOME_OK

    result = runner.fill_section(
        browser,
        {"extPasaporte": "X1234567"},
        session_dir,
    )

    assert result["ok"] is True
    assert result["blocked_field"] is None
    assert result["blocked_outcome"] is None

    log_text = _log_text(session_dir)
    assert "decision=EXECUTION_ALLOWED" in log_text
    assert "field=extPasaporte" in log_text
    assert "INTERACTION_POLICY_DENY" not in log_text


# QCC_ASSISTED_REAL_SMOKE_V4: reproduces the REAL smoke's actual
# extPasaporte DENY. V3's canonical sequence test above already had
# every element interactable from the FIRST capture, which is exactly
# why it never caught this: in REAL Mercurio the dependent field can
# still be DISABLED in the capture taken immediately after the prior
# RADIO/SELECT write, only becoming interactable once Mercurio's own
# async reveal/enable handler finishes. extPasaporte starts disabled
# here and only becomes enabled once the production dependency-
# readiness wait has polled the live DOM a bounded number of times --
# never via a blind sleep.
class _DependencyTransitionFakeCdpBrowser:
    def __init__(self, *, origin, pathname=MERCURIO_INICIO_PATH, ready_after_ticks=2):
        self.origin = origin
        self.pathname = pathname
        self.action_calls = []
        self.capture_calls = 0
        self.probe_calls = 0
        self.ready_after_ticks = ready_after_ticks
        self._ticks = 0

    def _ext_pasaporte_ready(self):
        return self._ticks >= self.ready_after_ticks

    def _elements(self):
        ext_pasaporte = _element(
            2, tag="input", element_id="extPasaporte", element_type="text"
        )
        ext_pasaporte["disabled"] = not self._ext_pasaporte_ready()

        return [
            _element(0, tag="input", element_id="bscIniciales", element_type="radio"),
            _element(1, tag="select", element_id="provincia"),
            ext_pasaporte,
        ]

    def evaluate(self, script):
        if len(script) > _CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return _dom_capture_payload(
                origin=self.origin,
                pathname=self.pathname,
                elements=self._elements(),
            )

        # Deterministic, non-mutating readiness probe (the production
        # ``wait_for_js``-wrapped boolean condition): never contains a
        # DOM mutation/dispatch, unlike every real write/action script.
        if "dispatchEvent" not in script and "getElementById" in script:
            self.probe_calls += 1

            if "extPasaporte" in script:
                self._ticks += 1
                return self._ext_pasaporte_ready()

            return True

        self.action_calls.append(script)
        return True


def test_dependency_not_yet_interactable_field_waits_then_allows(tmp_path):
    browser = _DependencyTransitionFakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    radio_outcome = runner.set_radio_checked(
        browser, "bscIniciales", checked=True, session_dir=session_dir
    )
    assert radio_outcome == runner.GOVERNED_OUTCOME_OK

    select_outcome = runner.select_by_text_or_value(
        browser, "provincia", value="OPT1", session_dir=session_dir
    )
    assert select_outcome == runner.GOVERNED_OUTCOME_OK

    # extPasaporte is still disabled at this point: the FIRST governed
    # attempt must observe that live and get denied, never pretend it
    # was already ready.
    assert browser._ext_pasaporte_ready() is False

    result = runner.fill_section(
        browser,
        {"extPasaporte": "X1234567"},
        session_dir,
    )

    assert result["ok"] is True
    assert result["blocked_field"] is None
    assert result["blocked_outcome"] is None

    # The dependency readiness wait actually polled the live DOM more
    # than once (bounded, deterministic) before the retry succeeded.
    assert browser.probe_calls >= 2

    log_text = _log_text(session_dir)
    assert "governed_write_dependency_wait" in log_text
    assert "field=extPasaporte" in log_text
    assert "decision=EXECUTION_ALLOWED" in log_text


def test_dependency_never_ready_fails_closed_without_bypassing_governance(
    tmp_path, monkeypatch
):
    # Bounded means bounded: if Mercurio's dependency never resolves,
    # the write must still end up DENIED, never silently granted and
    # never retried forever.
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS", 0.05)

    browser = _DependencyTransitionFakeCdpBrowser(
        origin=MERCURIO_LAB_ORIGIN, ready_after_ticks=10_000
    )
    session_dir = str(tmp_path)

    outcome = runner.set_value(
        browser, "extPasaporte", "X1234567", session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_DENIED
    # Never executed against the live DOM.
    assert browser.action_calls == []

    log_text = _log_text(session_dir)
    assert "DEPENDENCY_READINESS_TIMEOUT" in log_text


# F. governed piso.
def test_governed_piso_write_preserves_formatting(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    outcome = runner.set_piso_mercurio(
        browser, "extPiso", value="5", session_dir=session_dir
    )

    assert outcome == runner.GOVERNED_OUTCOME_OK
    script = browser.action_calls[0]
    assert "PISO 05" in script


# G. DENIED result propagates and fill_section stops/does not claim success.
def test_fill_section_stops_on_denied_write(tmp_path):
    browser = _FakeCdpBrowser(origin="https://not-mercurio.example")
    session_dir = str(tmp_path)

    result = runner.fill_section(
        browser,
        {"campoTexto": "PrimerValorFicticio", "campoSelect": "OPT1"},
        session_dir,
    )

    assert result["ok"] is False
    assert result["blocked_field"] == "campoTexto"
    assert result["blocked_outcome"] == runner.GOVERNED_OUTCOME_DENIED
    # The second field must never be reached/written.
    assert browser.action_calls == []


# H. execution failure propagates.
def test_fill_section_stops_on_execution_failure(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN, raise_on_action=True)
    session_dir = str(tmp_path)

    result = runner.fill_section(
        browser,
        {"campoTexto": "SegundoValorFicticio"},
        session_dir,
    )

    assert result["ok"] is False
    assert result["blocked_outcome"] == runner.GOVERNED_OUTCOME_FAILED


# I. HUMAN_HANDOFF propagates.
def test_governed_write_human_handoff_propagates(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    result = runner._governed_write(
        browser,
        action_kind="BUTTON",
        field_id="btnFoo",
        apply=lambda: None,
        session_dir=session_dir,
    )

    assert result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN
    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_HUMAN_HANDOFF
    assert browser.action_calls == []


# J. actual REAL target is identified as REAL.
def test_actual_real_browser_target_identified_as_real(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_REAL_ORIGIN)
    session_dir = str(tmp_path)

    applied = []
    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: applied.append(True),
        session_dir=session_dir,
    )

    assert result.evidence.environment == "REAL"
    assert applied  # gate authorized execution against the real origin


# K. localhost/TWIN/LAB target is not confused with REAL.
def test_localhost_target_classified_as_lab_not_real(tmp_path):
    browser = _FakeCdpBrowser(origin="http://localhost:8767")
    session_dir = str(tmp_path)

    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: None,
        session_dir=session_dir,
    )

    assert result.evidence.environment == "LAB"
    assert result.evidence.environment != "REAL"


# L. environment mismatch fails closed.
def test_environment_mismatch_fails_closed(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    applied = []
    result = runner._governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id="campoTexto",
        apply=lambda: applied.append(True),
        session_dir=session_dir,
        environment=SiteEnvironment.REAL,
    )

    assert runner._governed_outcome(result) == runner.GOVERNED_OUTCOME_DENIED
    assert result.reason == "ENVIRONMENT_MISMATCH"
    assert not applied


# M. logs do not contain supplied secret/raw values.
def test_governed_logs_never_contain_raw_supplied_values(tmp_path):
    browser = _FakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    secret_value = "SECRETO_CONFIDENCIAL_9F8D7"
    secret_option = "OPCION_SECRETA_XYZ"

    runner.set_value(browser, "campoTexto", secret_value, session_dir=session_dir)
    runner.select_by_text_or_value(
        browser, "campoSelect", value=secret_option, session_dir=session_dir
    )
    runner.set_checkbox(browser, "campoCheck", value="SI", session_dir=session_dir)
    runner.set_radio_checked(browser, "campoRadio", checked=True, session_dir=session_dir)
    runner.set_piso_mercurio(browser, "extPiso", value="7", session_dir=session_dir)

    log_text = _log_text(session_dir)

    assert secret_value not in log_text
    assert secret_option not in log_text
    assert "PISO 07" not in log_text

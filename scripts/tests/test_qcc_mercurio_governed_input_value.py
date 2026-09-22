"""Live-integration test for the QCC V2 governed SeleniumBase path.

Exercises ``app.run_presentacion_asistida.governed_set_value`` end to
end through the REAL production collaborators: DOM capture shape
(``backend.automation.dom_inspector``), normalization
(``backend.automation.site_architecture.normalizer``), Mercurio's
already-certified site policy/profile and state recognizer, the
state-aware execution orchestrator, and the SeleniumBase executor
built on ``backend.automation.browser_actions``.

Only the physical browser is faked (a CDP-style double exposing
``evaluate``): everything downstream of it is the real code path.
"""

import json

import app.run_presentacion_asistida as runner
from backend.automation.site_architecture.state_aware_execution import (
    STATE_AWARE_EXECUTION_ALLOWED,
    STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE,
    STATE_AWARE_EXECUTION_BLOCKED_POLICY,
    STATE_AWARE_EXECUTION_BLOCKED_SELECTOR,
    STATE_AWARE_EXECUTION_BLOCKED_STATE,
    STATE_AWARE_EXECUTION_NOT_READY,
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    StateAwareExecutionResult,
)


_VALID_DECISIONS = {
    STATE_AWARE_EXECUTION_ALLOWED,
    STATE_AWARE_EXECUTION_BLOCKED_POLICY,
    STATE_AWARE_EXECUTION_BLOCKED_STATE,
    STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE,
    STATE_AWARE_EXECUTION_BLOCKED_SELECTOR,
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    STATE_AWARE_EXECUTION_NOT_READY,
}


def _raw_dom_capture_payload():
    return {
        "schema_version": 1,
        "captured_at": "2024-01-01T00:00:00.000Z",
        "metadata": {
            "url": "http://127.0.0.1:8767/mercurio/inicioMercurio.html",
            "origin": "http://127.0.0.1:8767",
            "pathname": "/mercurio/inicioMercurio.html",
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
                "url": "http://127.0.0.1:8767/mercurio/inicioMercurio.html",
                "title": "Mercurio",
                "element_count": 1,
                "forms": 0,
                "inputs": 1,
                "textareas": 0,
                "selects": 0,
                "buttons": 0,
                "links": 0,
                "tables": 0,
            }
        ],
        "elements": [
            {
                "index": 0,
                "frame_path": "main",
                "tag": "input",
                "id": "dni",
                "name": "dni",
                "type": "text",
                "role": "",
                "classes": [],
                "attributes": {
                    "id": "dni",
                    "name": "dni",
                    "type": "text",
                },
                "text": "",
                "visible": True,
                "disabled": False,
                "interaction_signals": {
                    "hidden": False,
                    "aria_hidden": False,
                    "aria_disabled": False,
                    "readonly": False,
                    "in_viewport": True,
                    "opacity": "1",
                    "pointer_events": "auto",
                },
                "shadow_root": False,
                "rect": {"x": 0, "y": 0, "width": 100, "height": 20},
            }
        ],
        "frames": [],
        "shadows": [],
        "counts": {
            "documents": 1,
            "elements": 1,
            "forms": 0,
            "inputs": 1,
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

    Dispatches on script size: the DOM-capture IIFE is large, the
    executor's action scripts are small.
    """

    _CAPTURE_SCRIPT_SIZE_THRESHOLD = 2000

    def __init__(self):
        self.action_calls = []
        self.capture_calls = 0

    def evaluate(self, script):
        if len(script) > self._CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return _raw_dom_capture_payload()

        self.action_calls.append(script)
        return True


def test_governed_set_value_runs_the_real_governed_chain(tmp_path):
    browser = _FakeCdpBrowser()

    result = runner.governed_set_value(
        browser,
        "dni",
        "12345678Z",
        session_dir=str(tmp_path),
    )

    assert isinstance(result, StateAwareExecutionResult)
    assert result.decision in _VALID_DECISIONS
    assert result.evidence.action_selector == "#dni"
    assert result.evidence.action_kind == "INPUT_VALUE"
    assert result.evidence.provider == "MERCURIO"

    # Hard invariant regardless of the governed outcome: the raw
    # value never leaks into evidence.
    payload = json.dumps(result.evidence.to_public_dict())
    assert "12345678Z" not in payload

    assert browser.capture_calls >= 1

    if result.executed:
        assert len(browser.action_calls) == 1
        assert "12345678Z" in browser.action_calls[0]
        assert "dni" in browser.action_calls[0]


def test_governed_set_value_never_called_by_existing_flows():
    """Existing certified Mercurio flows must remain byte-for-byte
    unaffected: ``governed_set_value`` is additive/opt-in only."""

    import inspect

    source = inspect.getsource(runner)

    calls = source.count("governed_set_value(")

    # Exactly one occurrence: the function's own definition line.
    assert calls == 1

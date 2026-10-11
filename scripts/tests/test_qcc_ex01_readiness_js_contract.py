"""QCC_ASSISTED_READINESS_JS_V6.

Regression for the confirmed production defect
(``MALFORMED_COMPOSED_READINESS_JS``): V5's
``app.run_presentacion_asistida._field_readiness_js`` returned a JS
IIFE CALL terminated with a statement semicolon (``})();``), while
``_ex01_personal_ready_js`` composes it as an EXPRESSION
(``(<helper>) && (<helper>)``). A statement sealed inside an
expression position is invalid JS -- REAL Mercurio evidence showed
EX01_READY never firing even with both fields visually active and
editable.

The existing fake-CDP-browser tests
(``test_qcc_ex01_personal_readiness.py``) never caught this: their
fake ``evaluate()`` only does Python substring matching, never
actually parses/runs the generated script. These tests instead shell
out to Node (same convention as
``test_qcc_human_listener_lifecycle.py``) to execute the REAL
production script text -- exactly as
``backend.automation.browser_actions.wait_for_js`` builds it -- with
a genuine JS parser, so a malformed composition fails the way a real
browser would.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import app.run_presentacion_asistida as runner


HARNESS = (
    Path(__file__).resolve().parent / "qcc_ex01_readiness_js_harness.js"
)

NODE = shutil.which("node")


def _condition_script(condition_js):
    """Exactly mirrors backend.automation.browser_actions.wait_for_js's
    ``js(browser, f"return !!({condition_js});")`` call."""

    return f"return !!({condition_js});"


def _ready_element():
    return {"disabled": False, "visible": True}


def _disabled_element():
    return {"disabled": True, "visible": True}


def _run_harness(script, elements):
    if NODE is None:
        pytest.skip("node is required for JS predicate contract tests")

    payload = json.dumps({"script": script, "elements": elements})

    return subprocess.run(
        [NODE, str(HARNESS), payload],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------
# OBJECTIVE 1: HELPER_CONTRACT=JAVASCRIPT_BOOLEAN_EXPRESSION
# ---------------------------------------------------------------


def test_field_readiness_js_has_no_trailing_statement_semicolon():
    for field_id in ("extPasaporte", "extNie"):
        helper = runner._field_readiness_js(field_id)
        stripped = helper.strip()

        assert stripped.endswith("})()"), stripped[-20:]
        assert not stripped.endswith(";"), stripped[-20:]


@pytest.mark.parametrize("field_id", ["extPasaporte", "extNie"])
def test_field_readiness_js_is_composable_and_syntactically_valid(field_id):
    helper = runner._field_readiness_js(field_id)
    composed = f"({helper}) && (true)"
    script = _condition_script(composed)

    completed = _run_harness(script, {field_id: _ready_element()})

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RESULT::true" in completed.stdout


def test_old_statement_shaped_helper_is_rejected_by_a_real_js_parser():
    """Reproduces the EXACT V5 defect: an IIFE call terminated with a
    statement semicolon, composed as an expression -- proves a real
    JS parser rejects it (confirming the REAL Mercurio evidence),
    while the current helper does not."""

    malformed_helper = "\n    (function(){\n        return true;\n    })();\n    "
    malformed_composed = f"({malformed_helper}) && (true)"
    malformed_script = _condition_script(malformed_composed)

    completed = _run_harness(malformed_script, {})
    assert completed.returncode != 0

    current_helper = runner._field_readiness_js("extPasaporte")
    current_composed = f"({current_helper}) && (true)"
    current_script = _condition_script(current_composed)

    completed = _run_harness(
        current_script, {"extPasaporte": _ready_element()}
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RESULT::true" in completed.stdout


# ---------------------------------------------------------------
# OBJECTIVE 2: composed EX01 page-level readiness predicate
# ---------------------------------------------------------------


def _dual_datos_mercurio():
    return {
        "extranjero": {
            "extPasaporte": "X1234567",
            "extNie": "Y1234567Z",
        }
    }


def test_composed_ex01_readiness_requires_both_declared_fields():
    fields = runner._ex01_personal_canonical_write_fields(
        _dual_datos_mercurio()
    )
    assert fields == ["extPasaporte", "extNie"]


def test_composed_ex01_readiness_both_fields_ready_passes():
    condition = runner._ex01_personal_ready_js(_dual_datos_mercurio())
    script = _condition_script(condition)

    elements = {
        "extNombre": _ready_element(),
        "extPasaporte": _ready_element(),
        "extNie": _ready_element(),
    }

    completed = _run_harness(script, elements)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RESULT::true" in completed.stdout


@pytest.mark.parametrize(
    "pending_field", ["extPasaporte", "extNie"]
)
def test_composed_ex01_readiness_either_field_disabled_fails(pending_field):
    condition = runner._ex01_personal_ready_js(_dual_datos_mercurio())
    script = _condition_script(condition)

    elements = {
        "extNombre": _ready_element(),
        "extPasaporte": _ready_element(),
        "extNie": _ready_element(),
    }
    elements[pending_field] = _disabled_element()

    completed = _run_harness(script, elements)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RESULT::false" in completed.stdout


def test_composed_ex01_readiness_has_no_invalid_statement_composition():
    condition = runner._ex01_personal_ready_js(_dual_datos_mercurio())
    collapsed = condition.replace(" ", "").replace("\n", "")

    # The confirmed V5 failure shape: an IIFE call statement sealed
    # inside the composed boolean expression.
    assert "});)" not in collapsed
    assert "})();" not in collapsed


# ---------------------------------------------------------------
# OBJECTIVE 2 bullet 6: V5 300s regression represented end-to-end
# (both fields ready must not remain pending) through the closest
# existing deterministic harness: pause_supuesto against a fake CDP
# browser exposing BOTH extPasaporte and extNie.
# ---------------------------------------------------------------


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


MERCURIO_INICIO_PATH = "/mercurio/inicioMercurio.html"

# Same calibration as test_qcc_ex01_personal_readiness.py: real
# action/readiness-probe scripts top out at a few thousand
# characters, the real DOM-capture IIFE is tens of thousands.
_CAPTURE_SCRIPT_SIZE_THRESHOLD = 10000


class _Ex01DualFieldFakeCdpBrowser:
    """Both extPasaporte and extNie start disabled and become ready
    independently after their own bounded number of polls -- exactly
    the REAL smoke shape (both fields visually active/editable, but
    EX01_READY previously never fired due to the malformed JS)."""

    def __init__(self, *, origin, pasaporte_ready_after=2, nie_ready_after=3):
        self.origin = origin
        self.pathname = MERCURIO_INICIO_PATH
        self.pasaporte_ready_after = pasaporte_ready_after
        self.nie_ready_after = nie_ready_after
        self._ticks = 0
        self.probe_calls = 0
        self.action_calls = []
        self.capture_calls = 0

    def _pasaporte_ready(self):
        return self._ticks >= self.pasaporte_ready_after

    def _nie_ready(self):
        return self._ticks >= self.nie_ready_after

    def _elements(self):
        ext_pasaporte = _element(
            1, tag="input", element_id="extPasaporte", element_type="text"
        )
        ext_pasaporte["disabled"] = not self._pasaporte_ready()

        ext_nie = _element(2, tag="input", element_id="extNie", element_type="text")
        ext_nie["disabled"] = not self._nie_ready()

        return [
            _element(0, tag="input", element_id="extNombre", element_type="text"),
            ext_pasaporte,
            ext_nie,
        ]

    def evaluate(self, script):
        if len(script) > _CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return _dom_capture_payload(
                origin=self.origin,
                pathname=self.pathname,
                elements=self._elements(),
            )

        if script.startswith("return !!("):
            self.probe_calls += 1
            self._ticks += 1

            # The composed EX01 page-level predicate ANDs BOTH
            # per-field readiness expressions in the SAME poll (real
            # JS `&&`): simulate that by ANDing whichever of the two
            # readiness markers are actually present in this exact
            # script, instead of assuming only one field is checked
            # per call.
            result = True
            if runner._field_readiness_js("extPasaporte") in script:
                result = result and self._pasaporte_ready()
            if runner._field_readiness_js("extNie") in script:
                result = result and self._nie_ready()

            return result

        self.action_calls.append(script)
        return True


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


def test_pause_supuesto_dual_field_readiness_does_not_remain_pending(tmp_path):
    from backend.automation.site_policies.mercurio import MERCURIO_LAB_ORIGIN

    browser = _Ex01DualFieldFakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    result = runner.pause_supuesto(
        browser,
        session_dir,
        datos_mercurio=_dual_datos_mercurio(),
    )

    assert result["ok"] is True
    assert result.get("mode") != "human_enter_fallback_not_confirmed"

    log_text = _log_text(session_dir)
    assert "EX01_READY" in log_text

    fill_result = runner.fill_datos_extranjero(
        browser, _dual_datos_mercurio(), session_dir
    )
    assert fill_result["ok"] is True

    assert any("extPasaporte" in call for call in browser.action_calls)
    assert any("extNie" in call for call in browser.action_calls)

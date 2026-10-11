"""QCC_ASSISTED_AUTO_READINESS_V5.

Regression for the confirmed REAL smoke failure: Mercurio's EX01
personal-data screen (``Datos del extranjero/a``) can inject its DOM
nodes (``extNombre``/``extNie``/``extPasaporte``) before its own
async reveal/enable handler has finished, leaving ``extPasaporte``
disabled/non-interactable for a bounded window.

The pre-fix (``pause_supuesto``'s old ``ready_js``) only checked
``document.getElementById(...)`` presence -- SCREEN_DETECTED, never
SCREEN_READY -- so it returned control to ``run_auto`` immediately,
racing ``fill_datos_extranjero``'s governed write against Mercurio's
own dependency transition. These tests exercise the real production
``pause_supuesto``/``fill_datos_extranjero`` call chain (only the CDP
browser is faked, same convention as
``test_qcc_governed_presentation_writes.py``) to prove:

  * ``pause_supuesto`` now blocks until the canonical EX01 personal
    document field is actually interactable (EX01_READY), not merely
    present (EX01_DETECTED);
  * once ready, the governed write for that exact field succeeds and
    the fill stage continues;
  * a candidate screen that never becomes ready fails closed, with no
    fill ever starting;
  * the NIE branch never waits on/requires the passport branch, and
    vice versa.
"""

from pathlib import Path

import app.run_presentacion_asistida as runner
from backend.automation.site_policies.mercurio import MERCURIO_LAB_ORIGIN


MERCURIO_INICIO_PATH = "/mercurio/inicioMercurio.html"

# Same calibration as test_qcc_governed_presentation_writes.py: real
# action/readiness-probe scripts top out at a few thousand characters,
# the real DOM-capture IIFE is tens of thousands.
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


class _Ex01PersonalScreenFakeCdpBrowser:
    """Simulates the EX01 personal-data screen exactly as the REAL
    smoke observed it: ``extNombre``/``extNie``/``extPasaporte`` are
    already in the DOM (SCREEN_DETECTED is immediately true), but
    ``extPasaporte`` stays disabled for a bounded number of polls
    (SCREEN_READY only becomes true once Mercurio's own dependency
    transition -- never a bypass/forced-enable here -- completes).

    When ``never_ready`` is set, extPasaporte never transitions: used
    to prove the bounded fail-closed path (no fill ever starts).
    """

    def __init__(
        self,
        *,
        origin,
        pathname=MERCURIO_INICIO_PATH,
        ready_after_ticks=3,
        never_ready=False,
    ):
        self.origin = origin
        self.pathname = pathname
        self.ready_after_ticks = ready_after_ticks
        self.never_ready = never_ready
        self._ticks = 0
        self.probe_calls = 0
        self.action_calls = []
        self.capture_calls = 0

    def _ext_pasaporte_ready(self):
        if self.never_ready:
            return False
        return self._ticks >= self.ready_after_ticks

    def _elements(self):
        ext_pasaporte = _element(
            2, tag="input", element_id="extPasaporte", element_type="text"
        )
        ext_pasaporte["disabled"] = not self._ext_pasaporte_ready()

        return [
            _element(0, tag="input", element_id="extNombre", element_type="text"),
            _element(1, tag="input", element_id="extNie", element_type="text"),
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

        # wait_for_js-style deterministic, non-mutating readiness
        # probe (``return !!(<condition>);``): never a write. The
        # exact production readiness-IIFE text for extPasaporte
        # (never a mere "extPasaporte" substring, which also appears
        # in the plain detection OR-chain) distinguishes a true
        # readiness probe from a presence/detection probe.
        if script.startswith("return !!("):
            self.probe_calls += 1

            if runner._field_readiness_js("extPasaporte") in script:
                self._ticks += 1
                return self._ext_pasaporte_ready()

            # Pure existence/detection checks (extNombre/extNie) --
            # the candidate screen is present from the very start.
            return True

        self.action_calls.append(script)
        return True


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8")


# Pre-fix regression check: the OLD ready_js (existence-only) would
# have reported the screen ready on the very FIRST probe, while
# extPasaporte is still disabled. This is exactly the bug V5 closes.
def test_legacy_presence_only_predicate_was_premature():
    browser = _Ex01PersonalScreenFakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)

    assert browser._ext_pasaporte_ready() is False

    legacy_ready_js = runner.EX01_PERSONAL_CANDIDATE_DETECTED_JS
    assert bool(browser.evaluate(f"return !!({legacy_ready_js});")) is True


# Mandatory test: candidate DOM exists, extPasaporte starts
# disabled, V5 readiness blocks until the real dependency transition
# happens, then FILL_STAGE_ENTERED/the governed write succeed.
def test_pause_supuesto_blocks_until_ex01_personal_readiness_then_fill_continues(
    tmp_path,
):
    browser = _Ex01PersonalScreenFakeCdpBrowser(
        origin=MERCURIO_LAB_ORIGIN, ready_after_ticks=3
    )
    session_dir = str(tmp_path)

    datos_mercurio = {
        "extranjero": {"extPasaporte": "X1234567"},
        "domicilio_extranjero": {},
        "notificacion": {},
    }

    assert browser._ext_pasaporte_ready() is False

    result = runner.pause_supuesto(
        browser,
        session_dir,
        datos_mercurio=datos_mercurio,
    )

    assert result["ok"] is True

    # The wait actually polled the live DOM more than once (bounded,
    # deterministic) before declaring EX01_READY -- never a blind
    # sleep, never granted on the very first (premature) probe.
    assert browser.probe_calls >= browser.ready_after_ticks

    log_text = _log_text(session_dir)
    assert "EX01_READY" in log_text

    fill_result = runner.fill_datos_extranjero(
        browser, datos_mercurio, session_dir
    )

    assert fill_result["ok"] is True
    assert fill_result["blocked_field"] is None

    log_text = _log_text(session_dir)
    assert "FILL_STAGE_ENTERED" in log_text
    assert "field=extPasaporte" in log_text
    assert "decision=EXECUTION_ALLOWED" in log_text
    assert "INTERACTION_POLICY_DENY" not in log_text

    # The write actually happened against the live DOM.
    assert any("extPasaporte" in call for call in browser.action_calls)


# Mandatory test: a candidate screen that exists forever but never
# becomes ready must fail closed -- no fill ever starts. Bounded to a
# short timeout (instead of the production 300s/10s defaults) so the
# test itself stays fast while exercising the exact fail-closed path.
def test_pause_supuesto_fails_closed_when_never_ready(tmp_path, monkeypatch):
    """Same fail-closed guarantee as above, bounded to a short
    timeout instead of relying on the 300s/10s production defaults,
    so the test itself stays fast and deterministic."""

    browser = _Ex01PersonalScreenFakeCdpBrowser(
        origin=MERCURIO_LAB_ORIGIN, never_ready=True
    )
    session_dir = str(tmp_path)

    datos_mercurio = {"extranjero": {"extPasaporte": "X1234567"}}

    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")

    original_wait_for_human_navigation = runner.wait_for_human_navigation

    def _bounded_wait_for_human_navigation(*args, **kwargs):
        kwargs["timeout"] = 0.3
        kwargs["interval"] = 0.05
        return original_wait_for_human_navigation(*args, **kwargs)

    monkeypatch.setattr(
        runner, "wait_for_human_navigation", _bounded_wait_for_human_navigation
    )

    # QCC_ASSISTED_READINESS_JS_V6: the EX01 candidate screen is
    # detected immediately (its DOM presence check never races the
    # field-level readiness probed below), so phase 1 above resolves
    # before this phase-2 bound even applies. Bounding it anyway
    # keeps this fail-closed path fast/deterministic instead of
    # relying on the 300s production default.
    original_wait_for_ex01_personal_readiness = (
        runner._wait_for_ex01_personal_readiness
    )

    def _bounded_wait_for_ex01_personal_readiness(*args, **kwargs):
        kwargs["timeout"] = 0.3
        kwargs["interval"] = 0.05
        return original_wait_for_ex01_personal_readiness(*args, **kwargs)

    monkeypatch.setattr(
        runner,
        "_wait_for_ex01_personal_readiness",
        _bounded_wait_for_ex01_personal_readiness,
    )

    result = runner.pause_supuesto(
        browser,
        session_dir,
        datos_mercurio=datos_mercurio,
    )

    assert result["ok"] is False
    assert browser.action_calls == []

    log_text = _log_text(session_dir)
    assert "EX01_READY" not in log_text


# Objective 3: NIE branch never requires/waits on the passport
# branch. A client with ONLY a NIE value must become ready based on
# extNie readiness alone, even while extPasaporte is (irrelevantly)
# disabled forever.
class _Ex01NieOnlyFakeCdpBrowser(_Ex01PersonalScreenFakeCdpBrowser):
    def __init__(self, *, origin, ready_after_ticks=2):
        super().__init__(origin=origin, ready_after_ticks=ready_after_ticks)

    def _elements(self):
        ext_nie = _element(1, tag="input", element_id="extNie", element_type="text")
        ext_nie["disabled"] = not self._ext_nie_ready()

        ext_pasaporte = _element(
            2, tag="input", element_id="extPasaporte", element_type="text"
        )
        # Irrelevant branch: stays disabled forever, must never block
        # a NIE-only client.
        ext_pasaporte["disabled"] = True

        return [
            _element(0, tag="input", element_id="extNombre", element_type="text"),
            ext_nie,
            ext_pasaporte,
        ]

    def _ext_nie_ready(self):
        return self._ticks >= self.ready_after_ticks

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

            if runner._field_readiness_js("extPasaporte") in script:
                # Never asked for an extPasaporte readiness check
                # when the client only carries a NIE value.
                raise AssertionError(
                    "NIE-only client must never require extPasaporte readiness"
                )

            if runner._field_readiness_js("extNie") in script:
                self._ticks += 1
                return self._ext_nie_ready()

            return True

        self.action_calls.append(script)
        return True


def test_nie_branch_does_not_require_passport_branch_readiness(tmp_path):
    browser = _Ex01NieOnlyFakeCdpBrowser(origin=MERCURIO_LAB_ORIGIN)
    session_dir = str(tmp_path)

    datos_mercurio = {
        "extranjero": {"extNie": "Y1234567Z"},
        "domicilio_extranjero": {},
        "notificacion": {},
    }

    fields = runner._ex01_personal_canonical_write_fields(datos_mercurio)
    assert fields == ["extNie"]

    result = runner.pause_supuesto(
        browser,
        session_dir,
        datos_mercurio=datos_mercurio,
    )

    assert result["ok"] is True

    fill_result = runner.fill_datos_extranjero(browser, datos_mercurio, session_dir)
    assert fill_result["ok"] is True

    # The disabled-forever extPasaporte branch was never written.
    assert not any("extPasaporte" in call for call in browser.action_calls)
    assert any("extNie" in call for call in browser.action_calls)


# Objective 3 (passport side): writes extPasaporte automatically,
# without ever requiring the (irrelevant, unused) NIE branch.
def test_passport_branch_writes_automatically_without_nie(tmp_path):
    fields = runner._ex01_personal_canonical_write_fields(
        {"extranjero": {"extPasaporte": "X1234567"}}
    )
    assert fields == ["extPasaporte"]


def test_run_auto_gates_fill_on_pause_supuesto_readiness():
    source = Path(
        "app/run_presentacion_asistida.py"
    ).read_text(encoding="utf-8")

    start = source.index("def run_auto(")
    end = source.index("def main(", start)
    block = source[start:end]

    assert "supuesto_result = pause_supuesto(" in block
    assert "if not supuesto_result.get(\"ok\"):" in block

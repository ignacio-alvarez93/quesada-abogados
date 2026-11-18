"""QCC-EX01-R11-FIX2: Titular 130 identity + Familiar 131 readiness.

Both REAL defects were invisible to the existing doubles:

* R11-A (130): REAL nuevaSolicitud-EX01 (39/39 REAL site_architecture
  captures) groups each supuesto list as ``div.dvGrSup`` > disabled
  ``input.optGrSup#gsup_*`` marker + sibling ``ul.ulSupuestos`` holding
  the datosForAut radios, inside ``tab-datos_autorizacion``. The marker
  is never an ANCESTOR of the radio, so the old
  ``closest('[id^="gsup_"]')`` was always null ->
  SUPUESTO_GROUP_UNOBSERVED. The doubles fabricated ``supuesto_group``.
* R11-B (131): ``wait_for_js`` sends ``return !!(<expr>);`` and the
  installed ``sb_cdp.Chrome.evaluate`` only strips a ``return`` on the
  LAST line. The multi-line ``_ex01_personal_ready_js`` left it on the
  first line, CDP ``Runtime.evaluate`` raised ``SyntaxError: Illegal
  return statement`` on every poll (silenced by ``wait_for_js``) and
  EX01_READY never fired. Node ``new Function`` accepts that script.

Part 1 runs the INSTALLED adapter code without a browser. Parts 2-4
drive the PRODUCTION adapter (``start_seleniumbase_chrome`` ->
``sb_cdp.Chrome``, headless, ephemeral) with fictitious data only,
against a local synthetic page mirroring the REAL skeleton and against
the local Mercurio LAB (read-only). The CDP tests are decisive and are
NEVER skipped: if Chrome/CDP or the LAB origin is unavailable they FAIL.
No CAPTCHA, no signature, no REAL site, no CONTINUAR/CONCLUIR clicks by
the runner (the test stands in for the HUMAN supuesto selection only).
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import app.run_presentacion_asistida as runner
from backend.automation.browser_actions import js, wait_for_js


EX01_PATH = "/mercurio/nuevaSolicitud-EX01.html"

# Fictitious identity data only.
FICTITIOUS = {
    "extPasaporte": "ZZ0000000",
    "extNie": "Z0000000T",
    "extNombre": "LABNOMBRE",
}
FICTITIOUS_PRESENTER = "LABPRESENTADOR"


def _datos(mapper_codigo, extranjero=None):
    return {
        "presentacion": {
            "tipo_formulario_objetivo": "EX01",
            "mapper_codigo": mapper_codigo,
        },
        "extranjero": dict(FICTITIOUS if extranjero is None else extranjero),
        "domicilio_extranjero": {},
        "notificacion": {},
        # Required by the canonical VOLCAR; deferred to its own surface.
        "representante": {"preNombrePresentador": FICTITIOUS_PRESENTER},
    }


DATOS_TITULAR = _datos("MERCURIO_EX01")
DATOS_FAMILIAR = _datos("MERCURIO_EX01_FAMILIAR")


def _legacy_ex01_personal_ready_js(datos_mercurio):
    """Exactly the pre-R11-FIX2 composition (multi-line)."""

    fields = runner._ex01_personal_canonical_write_fields(datos_mercurio)
    readiness = " && ".join(
        f"({runner._field_readiness_js(field_id)})" for field_id in fields
    )
    return f"{runner.EX01_PERSONAL_CANDIDATE_DETECTED_JS} && {readiness}"


def _log_text(session_dir):
    path = Path(session_dir) / "logs" / "presentacion.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _assert_no_pii(session_dir):
    log = _log_text(session_dir)
    for value in (*FICTITIOUS.values(), FICTITIOUS_PRESENTER):
        assert value not in log


# ---------------------------------------------------------------
# Part 1: installed sb_cdp adapter contract (no browser)
# ---------------------------------------------------------------


def _sb_cdp_sent_expression(script):
    """Runs the INSTALLED ``sb_cdp.Chrome.evaluate`` and returns the
    exact expression it hands to CDP ``Runtime.evaluate``."""

    from seleniumbase.core.sb_cdp import Chrome

    sent = []

    async def _evaluate(expression):
        sent.append(expression)
        return True

    loop = asyncio.new_event_loop()
    try:
        fake = SimpleNamespace(loop=loop, page=SimpleNamespace(evaluate=_evaluate))
        Chrome.evaluate(fake, script)
    finally:
        loop.close()

    return sent[0]


def test_sb_cdp_keeps_return_of_the_legacy_multi_line_ready_predicate():
    """Adapter semantics behind the REAL 131 defect."""

    legacy = _legacy_ex01_personal_ready_js(DATOS_FAMILIAR)

    assert "\n" in legacy
    assert _sb_cdp_sent_expression(f"return !!({legacy});").startswith("return !!(")


@pytest.mark.parametrize(
    "extranjero",
    [
        FICTITIOUS,
        {"extNie": "Z0000000T"},
        {"extPasaporte": "ZZ0000000"},
        {},
    ],
    ids=["dual", "nie_only", "passport_only", "fallback"],
)
def test_ready_predicate_reaches_cdp_as_an_expression(extranjero):
    condition = runner._ex01_personal_ready_js(_datos("MERCURIO_EX01_FAMILIAR", extranjero))

    assert "\n" not in condition and "//" not in condition
    sent = _sb_cdp_sent_expression(f"return !!({condition});")
    assert not sent.lstrip().startswith("return")


def test_identity_probe_reaches_cdp_unchanged():
    probe = runner._ex01_titular_identity_evidence_js()

    assert "\n" not in probe and "//" not in probe
    assert _sb_cdp_sent_expression(probe) == probe


# ---------------------------------------------------------------
# Shared CDP fixtures (decisive: never skipped)
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def cdp_browser():
    from backend.automation.browser_session import start_seleniumbase_chrome

    try:
        browser = start_seleniumbase_chrome(headless=True)
    except Exception as exc:  # decisive path: FAIL, never skip
        pytest.fail(f"SELENIUMBASE_CDP_BLOCKED: {type(exc).__name__}")

    try:
        assert type(browser).__module__ == "seleniumbase.core.sb_cdp"
        assert type(browser).__name__ == "Chrome"
        yield browser
    finally:
        try:
            browser.driver.stop()
        except Exception:
            pass


# REAL skeleton (structure only, no text/PII) of nuevaSolicitud-EX01
# after the HUMAN pressed CONTINUAR: authorization panel hidden but
# still in the DOM, personal panel active, pestFamiliar hidden.
REAL_SKELETON_PAGE = """<!doctype html><html><body><form>
<div id="tab-datos_autorizacion" class="mf-tabs--tab-content r-tabs-panel" style="display:none">
 <div class="fld ctlPptAut">
  <div class="dvGrSup"><input id="gsup_27" class="optGrSup" type="radio" disabled><span></span>
   <ul class="ma-tablelist ulSupuestos" name="datostipAut">
    <li><div class="ma-tablelist--label clAutIn"><input id="EX-01-1-01" class="chTipoSup" name="datosForAut" type="radio" value="128"></div></li>
    <li><div class="ma-tablelist--label clAutIn"><input id="EX-01-1-02" class="chTipoSup" name="datosForAut" type="radio" value="129"></div></li>
   </ul></div>
  <div class="dvGrSup"><input id="gsup_28" class="optGrSup" type="radio" disabled><span></span>
   <ul class="ma-tablelist ulSupuestos" name="datostipAut">
    <li><div class="ma-tablelist--label clAutIn"><input id="EX-01-2-01" class="chTipoSup" name="datosForAut" type="radio" value="130"></div></li>
    <li><div class="ma-tablelist--label clAutIn"><input id="EX-01-2-02" class="chTipoSup" name="datosForAut" type="radio" value="131"></div></li>
   </ul></div>
 </div>
</div>
<div id="tab-datos_personales" class="mf-tabs--tab-content r-tabs-panel r-tabs-state-active">
 <div id="wrapPas"><input id="extPasaporte" type="text"></div>
 <div id="wrapNie"><input id="extNie" type="text"></div>
 <input id="extNombre" type="text">
</div>
<div id="tab-datos_familiar" class="r-tabs-panel" style="display:none"></div>
<div id="tab-datos_presentador" class="r-tabs-panel" style="display:none"></div>
<a id="pestFamiliar" style="display:none"></a>
</form></body></html>"""


class _SkeletonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(REAL_SKELETON_PAGE.encode("utf-8"))

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def skeleton_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SkeletonHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}{EX01_PATH}"
    finally:
        server.shutdown()
        server.server_close()


def _open_skeleton(browser, url, supuesto_id="EX-01-2-01"):
    """Fresh page; the test stands in for the HUMAN selection."""

    browser.get(url)
    wait_for_js(browser, "document.getElementById('extNombre')", timeout=10, interval=0.1)
    if supuesto_id:
        js(browser, f"document.getElementById('{supuesto_id}').checked = true")


# ---------------------------------------------------------------
# Part 2: R11-B readiness through the production CDP adapter
# ---------------------------------------------------------------


def test_cdp_legacy_ready_predicate_raises_and_wait_for_js_swallows_it(
    cdp_browser, skeleton_url, tmp_path
):
    """Reproduces REAL 131: both fields interactable, yet never ready."""

    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")
    legacy = _legacy_ex01_personal_ready_js(DATOS_FAMILIAR)

    with pytest.raises(Exception) as excinfo:
        js(cdp_browser, f"return !!({legacy});")
    assert type(excinfo.value).__name__ == "ProtocolException"
    assert "SyntaxError" in str(excinfo.value)

    with pytest.raises(TimeoutError):
        wait_for_js(cdp_browser, legacy, timeout=1, interval=0.2)

    assert runner._ex01_readiness_predicate_probe(
        cdp_browser, legacy, str(tmp_path), "initial"
    ) == "error:ProtocolException:SyntaxError"
    assert (
        "EX01_READINESS_PREDICATE phase=initial "
        "result=error:ProtocolException:SyntaxError"
    ) in _log_text(tmp_path)


def test_cdp_fixed_ready_predicate_is_true_with_both_fields(cdp_browser, skeleton_url):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")

    condition = runner._ex01_personal_ready_js(DATOS_FAMILIAR)

    assert js(cdp_browser, f"return !!({condition});") is True
    assert wait_for_js(cdp_browser, condition, timeout=2, interval=0.1) is True


def test_cdp_readiness_passes_and_logs_true(cdp_browser, skeleton_url, tmp_path):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")

    result = runner._wait_for_ex01_personal_readiness(
        cdp_browser, str(tmp_path), DATOS_FAMILIAR, timeout=5, interval=0.1
    )

    assert result["ok"] is True
    log = _log_text(tmp_path)
    order = [
        "QCC_FILL_READINESS_START step=EX01_READINESS",
        "EX01_READINESS_PREDICATE phase=initial result=true",
        "EX01_READY\n",
        "QCC_FILL_READINESS_PASS step=EX01_READINESS",
    ]
    assert [log.index(m) for m in order] == sorted(log.index(m) for m in order)
    _assert_no_pii(tmp_path)


@pytest.mark.parametrize(
    "blocker",
    [
        "document.getElementById('extNie').disabled = true",
        "document.getElementById('extNie').style.display = 'none'",
        "document.getElementById('extNie').style.visibility = 'hidden'",
        "document.getElementById('extNie').setAttribute('aria-hidden', 'true')",
        "document.getElementById('wrapNie').style.display = 'none'",
        "document.getElementById('extNie').remove()",
        "document.getElementById('extPasaporte').disabled = true",
    ],
    ids=["disabled", "display_none", "visibility_hidden", "aria_hidden",
         "hidden_ancestor", "absent", "passport_disabled"],
)
def test_cdp_readiness_stays_fail_closed_on_a_genuine_false(
    cdp_browser, skeleton_url, tmp_path, blocker
):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")
    js(cdp_browser, f"(function(){{ {blocker}; }})()")

    result = runner._wait_for_ex01_personal_readiness(
        cdp_browser, str(tmp_path), DATOS_FAMILIAR, timeout=1, interval=0.2
    )

    assert result["ok"] is False
    assert result["mode"] == "ex01_readiness_timeout"
    log = _log_text(tmp_path)
    # A real false, not a swallowed evaluation error.
    assert "EX01_READINESS_PREDICATE phase=initial result=false" in log
    assert "EX01_READINESS_PREDICATE phase=timeout result=false" in log
    assert "EX01_READY\n" not in log
    assert "QCC_FILL_READINESS_FAIL step=EX01_READINESS" in log


def test_cdp_nie_only_client_never_waits_on_passport(cdp_browser, skeleton_url, tmp_path):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")
    js(cdp_browser, "document.getElementById('extPasaporte').disabled = true")

    result = runner._wait_for_ex01_personal_readiness(
        cdp_browser, str(tmp_path),
        _datos("MERCURIO_EX01_FAMILIAR", {"extNie": "Z0000000T"}),
        timeout=3, interval=0.1,
    )

    assert result["ok"] is True


class _Actions:
    """QCC action channel double: an explicit list, then ``None``."""

    def __init__(self, actions):
        self.actions = list(actions)

    def consume_next(self):
        return self.actions.pop(0) if self.actions else None


ABORT = {"action_id": 99, "action": "PRESENTATION_ABORT", "payload": {}}
FILL_START = {"action_id": 11, "action": "PRESENTATION_FILL_START", "payload": {}}


def test_cdp_abort_is_serviced_during_readiness_wait(cdp_browser, skeleton_url, tmp_path):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")
    js(cdp_browser, "document.getElementById('extNie').disabled = true")
    abort_handler = Mock(return_value=False)

    result = runner._wait_for_ex01_personal_readiness(
        cdp_browser, str(tmp_path), DATOS_FAMILIAR, timeout=30, interval=0.2,
        action_client=_Actions([ABORT]), abort_handler=abort_handler,
    )

    assert result["mode"] == "aborted"
    abort_handler.assert_called_once_with()
    assert "EX01_READY\n" not in _log_text(tmp_path)


# ---------------------------------------------------------------
# Part 3: R11-A identity on the REAL skeleton through CDP
# ---------------------------------------------------------------


def test_cdp_legacy_ancestor_lookup_is_null_on_real_structure(cdp_browser, skeleton_url):
    """Reproduces REAL SUPUESTO_GROUP_UNOBSERVED (datosForAut=130)."""

    _open_skeleton(cdp_browser, skeleton_url)

    assert js(
        cdp_browser,
        "return document.getElementById('EX-01-2-01')"
        ".closest('[id^=\"gsup_\"]') === null",
    ) is True


def test_cdp_titular_130_matches_at_selection_and_before_write(
    cdp_browser, skeleton_url, tmp_path
):
    _open_skeleton(cdp_browser, skeleton_url)

    result = runner.pause_supuesto(
        cdp_browser, str(tmp_path), tipo_formulario_objetivo="EX01",
        datos_mercurio=DATOS_TITULAR, action_client=_Actions([]),
    )
    assert result["ok"] is True

    fill_start = runner._verify_ex01_renovacion_titular_identity(
        cdp_browser, str(tmp_path), phase="FILL_START"
    )
    assert fill_start["ok"] is True

    log = _log_text(tmp_path)
    for phase in ("PROCEDURE_SELECTION", "FILL_START"):
        assert (
            f"EX01_TITULAR_IDENTITY phase={phase} status=MATCH "
            "reason=EX01_RENOVACION_TITULAR datosForAut=130 group=gsup_28 "
            "group_markers=1 panel=tab-datos_autorizacion familiar_tab=HIDDEN"
        ) in log
    assert "EX01_CANDIDATE_DETECTED" in log


def test_cdp_familiar_131_is_never_titular(cdp_browser, skeleton_url, tmp_path):
    _open_skeleton(cdp_browser, skeleton_url, "EX-01-2-02")

    result = runner._verify_ex01_renovacion_titular_identity(
        cdp_browser, str(tmp_path), phase="FILL_START"
    )

    assert result["ok"] is False
    assert result["reason"] == "SUPUESTO_FAMILIAR_131"
    assert "datosForAut=131 group=gsup_28" in _log_text(tmp_path)


_NEW_MARKER = (
    "const m = document.createElement('input');"
    "m.type = 'radio'; m.className = 'optGrSup'; m.disabled = true;"
)


@pytest.mark.parametrize(
    "mutation, status, reason",
    [
        ("document.getElementById('gsup_28').remove()",
         "AMBIGUOUS", "SUPUESTO_GROUP_UNOBSERVED"),
        (_NEW_MARKER + "m.id = 'gsup_99';"
         "document.getElementById('gsup_28').parentElement.appendChild(m)",
         "AMBIGUOUS", "SUPUESTO_GROUP_AMBIGUOUS"),
        (_NEW_MARKER + "m.id = 'gsup_28';"
         "document.getElementById('gsup_27').parentElement.appendChild(m);"
         "document.getElementById('gsup_27').remove()",
         "AMBIGUOUS", "SUPUESTO_GROUP_AMBIGUOUS"),
        ("document.getElementById('gsup_28').id = 'gsup_29'",
         "MISMATCH", "SUPUESTO_GROUP_MISMATCH"),
        # Radio relocated into the OTHER group's list.
        ("document.getElementById('EX-01-1-01').closest('ul')"
         ".appendChild(document.getElementById('EX-01-2-01').closest('li'))",
         "MISMATCH", "SUPUESTO_GROUP_MISMATCH"),
        # Marker nested, not a direct sibling of the list.
        ("const s = document.createElement('span');"
         "const g = document.getElementById('gsup_28');"
         "g.parentElement.insertBefore(s, g); s.appendChild(g)",
         "AMBIGUOUS", "SUPUESTO_GROUP_UNOBSERVED"),
        # Unproven ancestor hypothesis is NOT accepted as group proof.
        ("const d = document.createElement('div'); d.id = 'gsup_28';"
         "document.getElementById('gsup_28').remove();"
         "const r = document.getElementById('EX-01-2-01');"
         "r.parentElement.insertBefore(d, r); d.appendChild(r)",
         "AMBIGUOUS", "SUPUESTO_GROUP_UNOBSERVED"),
        # Foreign radio outside any dvGrSup, same panel.
        ("document.querySelector('.ctlPptAut')"
         ".appendChild(document.getElementById('EX-01-2-01'))",
         "AMBIGUOUS", "SUPUESTO_GROUP_UNOBSERVED"),
        # Wrong panel.
        ("document.getElementById('tab-datos_personales')"
         ".appendChild(document.getElementById('gsup_28').parentElement)",
         "MISMATCH", "SUPUESTO_PANEL_MISMATCH"),
        ("document.getElementById('pestFamiliar').style.display = ''",
         "MISMATCH", "FAMILIAR_CAPABILITY_VISIBLE"),
        # Outside the form it is another radio group: both checked.
        ("const d = document.createElement('input'); d.type = 'radio';"
         "d.name = 'datosForAut'; d.value = '131';"
         "document.body.appendChild(d); d.checked = true",
         "AMBIGUOUS", "SUPUESTO_SELECTION_AMBIGUOUS"),
        ("document.getElementById('EX-01-2-01').checked = false",
         "AMBIGUOUS", "SUPUESTO_SELECTION_AMBIGUOUS"),
        ("document.getElementById('EX-01-1-01').checked = true",
         "MISMATCH", "SUPUESTO_NOT_130"),
        ("document.getElementById('tab-datos_personales')"
         ".classList.remove('r-tabs-state-active')",
         "AMBIGUOUS", "ACTIVE_PANEL_AMBIGUOUS"),
    ],
    ids=["marker_absent", "marker_plural", "marker_duplicated",
         "group_mismatch", "radio_in_other_group", "marker_nested",
         "ancestor_hypothesis", "foreign_radio", "wrong_panel",
         "familiar_visible", "selection_ambiguous", "no_selection",
         "other_supuesto", "panel_inactive"],
)
def test_cdp_titular_identity_contradictions_block(
    cdp_browser, skeleton_url, tmp_path, mutation, status, reason
):
    _open_skeleton(cdp_browser, skeleton_url)
    js(cdp_browser, f"(function(){{ {mutation}; }})()")

    result = runner._verify_ex01_renovacion_titular_identity(
        cdp_browser, str(tmp_path), phase="FILL_START"
    )

    assert result["ok"] is False
    assert (result["status"], result["reason"]) == (status, reason)


# ---------------------------------------------------------------
# Part 4: governed run_auto smoke on the local LAB (130 and 131)
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def lab_origin():
    """Writes are gated to the canonical LAB origin: serve it there
    instead of relaxing the site gate. Read-only use of the Twin."""

    from urllib.parse import urlsplit

    from backend.automation.site_policies.mercurio import MERCURIO_LAB_ORIGIN
    from tools.mercurio_lab.server import MercurioLabHandler, MercurioLabServer

    port = urlsplit(MERCURIO_LAB_ORIGIN).port
    try:
        server = MercurioLabServer(("127.0.0.1", port), MercurioLabHandler)
    except OSError as exc:  # decisive path: FAIL, never skip
        pytest.fail(f"LAB_ORIGIN_BUSY: {MERCURIO_LAB_ORIGIN}: {type(exc).__name__}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield MERCURIO_LAB_ORIGIN
    finally:
        server.shutdown()
        server.server_close()


# Test harness only: the Twin renders the supuestos without the REAL
# dvGrSup/optGrSup grouping (separate WO). Rewrap the LAB's own gsup_28
# radios into the REAL skeleton so identity is proven on REAL structure.
_REAL_GROUPING_JS = " ".join((
    "(function(){",
    "const r1 = document.getElementById('EX-01-2-01');",
    "const r2 = document.getElementById('EX-01-2-02');",
    "const host = r1.closest('label').parentElement;",
    "const box = document.createElement('div'); box.className = 'dvGrSup';",
    "const m = document.createElement('input'); m.type = 'radio';",
    "m.className = 'optGrSup'; m.id = 'gsup_28'; m.disabled = true;",
    "m.style.display = 'none';",
    "const ul = document.createElement('ul'); ul.className = 'ulSupuestos';",
    "box.appendChild(m); box.appendChild(ul); host.appendChild(box);",
    "[r1, r2].forEach(function(r){",
    "const li = document.createElement('li');",
    "li.appendChild(r.closest('label')); ul.appendChild(li); });",
    "})()",
))


class _GatedActions:
    """The operator's VOLCAR DATOS only once READY_TO_FILL is shown;
    ABORT only after the mapper finished, i.e. while the runner waits
    on the HUMAN_ONLY CONTINUAR."""

    def __init__(self, session_dir):
        self.session_dir = session_dir
        self.fill_sent = False
        self.abort_sent = False

    def consume_next(self):
        log = _log_text(self.session_dir)
        if not self.fill_sent and "READY_TO_FILL: esperando" in log:
            self.fill_sent = True
            return dict(FILL_START)
        if self.fill_sent and not self.abort_sent and "QCC_FILL_COMPLETED" in log:
            self.abort_sent = True
            return dict(ABORT)
        return None


def _run_auto_on_lab(browser, origin, session_dir, datos, supuesto_id, real_grouping):
    browser.get(origin + EX01_PATH)
    wait_for_js(browser, "window.continuarTab", timeout=10, interval=0.1)
    if real_grouping:
        js(browser, _REAL_GROUPING_JS)
    # The test is the HUMAN: pick the supuesto and press CONTINUAR.
    js(browser, f"document.getElementById('{supuesto_id}').click()")
    js(browser, "window.continuarTab('autorizacionSup')")

    ok = {"ok": True}
    abort_handler = Mock(return_value=False)
    actions = _GatedActions(session_dir)
    with patch.object(runner, "step_continuar_inicial", return_value=ok), \
         patch.object(runner, "pause_certificado", return_value=ok), \
         patch.object(runner, "step_presentar_nueva_solicitud", return_value=ok), \
         patch.object(runner, "fill_datos_presentador") as presenter, \
         patch("builtins.input", side_effect=AssertionError("ENTER fallback")):
        result = runner.run_auto(
            browser, "33", datos, session_dir,
            action_client=actions, abort_handler=abort_handler,
        )
    presenter.assert_not_called()
    return result, abort_handler


_FILL_ORDER = (
    "READY_TO_FILL: esperando",
    "QCC_FILL_ACTION_CONSUMED action_id=11 step=READY_TO_FILL",
    "QCC_FILL_READINESS_START step=EX01_READINESS",
    "EX01_READINESS_PREDICATE phase=initial result=true",
    "EX01_READY\n",
    "QCC_FILL_READINESS_PASS step=EX01_READINESS",
    "QCC_FILL_MAPPER_START step=FILLING",
    "QCC_FILL_MAPPER_RESULT step=FILLING outcome=ok",
    "QCC_FILL_COMPLETED step=FILLED",
)


@pytest.mark.parametrize(
    "datos, supuesto_id, extra",
    [
        (DATOS_TITULAR, "EX-01-2-01",
         ("EX01_TITULAR_IDENTITY phase=FILL_START status=MATCH",)),
        (DATOS_FAMILIAR, "EX-01-2-02", ()),
    ],
    ids=["titular_130", "familiar_131"],
)
def test_lab_run_auto_fills_reads_back_and_stops_at_human_continue(
    cdp_browser, lab_origin, tmp_path, datos, supuesto_id, extra
):
    session_dir = str(tmp_path)

    result, abort_handler = _run_auto_on_lab(
        cdp_browser, lab_origin, session_dir, datos, supuesto_id, real_grouping=True
    )

    log = _log_text(session_dir)
    for marker in _FILL_ORDER + extra:
        assert marker in log, marker
    positions = [log.index(m) for m in _FILL_ORDER]
    assert positions == sorted(positions)
    if extra:
        fill_start_identity = log.index(extra[0])
        assert positions[5] < fill_start_identity < positions[6]
        assert "phase=PROCEDURE_SELECTION status=MATCH" in log

    # Readback of the fictitious values written by the real mapper.
    for field_id, value in FICTITIOUS.items():
        assert js(cdp_browser, f"return document.getElementById('{field_id}').value") == value
    # Presenter block deferred: never written on its hidden surface.
    assert js(
        cdp_browser, "return document.getElementById('preNombrePresentador').value"
    ) != FICTITIOUS_PRESENTER

    # HUMAN_ONLY: no CONTINUAR automated; ABORT serviced while waiting.
    assert runner._is_qcc_aborted_result(result) or result.get("mode") == "aborted" \
        or runner._is_qcc_aborted_result(result.get("detail"))
    abort_handler.assert_called_once_with()
    assert js(
        cdp_browser,
        "return document.getElementById('tab-datos_personales')"
        ".classList.contains('r-tabs-state-active')",
    ) is True
    _assert_no_pii(session_dir)


def test_lab_titular_without_real_grouping_fails_closed_before_fill(
    cdp_browser, lab_origin, tmp_path
):
    """The Twin lacks the REAL dvGrSup grouping: identity must block,
    never be inferred from datosForAut=130 alone."""

    session_dir = str(tmp_path)

    result, abort_handler = _run_auto_on_lab(
        cdp_browser, lab_origin, session_dir, DATOS_TITULAR, "EX-01-2-01",
        real_grouping=False,
    )

    assert result["ok"] is False
    assert result["reason"] == "SUPUESTO_GROUP_UNOBSERVED"
    log = _log_text(session_dir)
    assert "phase=PROCEDURE_SELECTION status=AMBIGUOUS" in log
    assert "READY_TO_FILL" not in log
    assert "QCC_FILL_MAPPER_START" not in log
    assert js(cdp_browser, "return document.getElementById('extPasaporte').value") == ""
    abort_handler.assert_not_called()

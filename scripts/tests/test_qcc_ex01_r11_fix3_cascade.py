"""QCC EX01 R11-FIX3: REAL domicile cascade and honest QCC fill state.

REAL 18-11-2026 (EX01 Titular 130): MAPPER_CASCADE_START, then
``WAIT_FAIL cascade extCodigoMunicipio`` -> DEFERRED_DEPENDENCY, and yet
``QCC_FILL_MAPPER_RESULT outcome=ok`` / ``QCC_FILL_COMPLETED step=FILLED``
with municipality and locality unselected on the ACTIVE surface.

Unlike the shared doubles (which answer every ``return !!(...)`` with
``True``), this double evaluates the cascade readiness predicate against
its live options: dependent lists start EMPTY and are only loaded (AJAX)
when the parent's ``change`` is dispatched by a governed write. Only the
physical browser is faked: the real runner, engine and Mercurio policy
run. Offline, fictitious values only.
"""

import json
import re
import shutil
import subprocess

import pytest

import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import (
    _TabbedMercurioBrowser, _datos, _run_full_mapper, _FakeActionClient,
    ALL_EX01_FIELDS, REPRESENTANTE, NOTIFICACION, _log_text,
)
from test_qcc_preloaded_full_mapper import mapper


PROVINCE, TOWN, LOCALITY = "extCodigoProvincia", "extCodigoMunicipio", "extCodigoLocalidad"
CASCADE = [PROVINCE, TOWN, LOCALITY]
PLACEHOLDER = ("", "--")
TOWN_OPTIONS = [PLACEHOLDER, ("001", "OVIEDO"), ("002", "AVILES")]
LOCALITY_OPTIONS = [PLACEHOLDER, ("0001", "OVIEDO")]
# Fictitious labels: never allowed in any log line.
LABELS = ("ASTURIAS", "OVIEDO", "AVILES")
_READY_SHAPE = "el.tagName !== 'SELECT'"


def _cascade_datos(mapper_codigo="MERCURIO_EX01"):
    datos = _datos(mapper_codigo)
    datos["domicilio_extranjero"].update({
        PROVINCE: "33", PROVINCE + "_text": "ASTURIAS",
        TOWN + "_text": "OVIEDO", LOCALITY + "_text": "OVIEDO",
    })
    return datos


class _AjaxCascadeBrowser(_TabbedMercurioBrowser):
    """Province -> municipality -> locality whose dependent lists are
    loaded by Mercurio only after the parent's ``change``.

    ``loads``: ``{parent: (child, options)}`` applied on that change;
    ``None`` options = the request never answers. ``late_polls``: the
    loaded list lands only after that many readiness polls of the child.
    ``preselected``: the province already holds its option on entry.
    """

    def __init__(self, *, loads=None, late_polls=0, preselected=True, **kwargs):
        options = {
            PROVINCE: [PLACEHOLDER, ("33", "ASTURIAS")],
            TOWN: [PLACEHOLDER], LOCALITY: [PLACEHOLDER],
        }
        super().__init__(fields=ALL_EX01_FIELDS + CASCADE, selects=CASCADE,
                         options=options, **kwargs)
        self.loads = {PROVINCE: (TOWN, TOWN_OPTIONS), TOWN: (LOCALITY, LOCALITY_OPTIONS)}
        self.loads.update(loads or {})
        self.late_polls = late_polls
        self.in_flight = {}
        self.polls = {}
        self.diagnostics = []
        self.changes = []
        self.on_poll = None
        self.on_diagnostic = None
        self._seen_events = 0
        if preselected:
            self.form.selects.add(PROVINCE)
            self.form.values[PROVINCE] = "33"

    # -- Mercurio AJAX ----------------------------------------------------

    def _land_changes(self):
        events = self.form.events[self._seen_events:]
        self._seen_events = len(self.form.events)
        for field_id, kind in events:
            if kind != "change":
                continue
            self.changes.append(field_id)
            child, options = self.loads.get(field_id, (None, None))
            if child is None:
                continue
            # A parent change rebuilds the child list (selection reset).
            self.form.options[child] = [PLACEHOLDER]
            self.form.values.pop(child, None)
            if options is not None:
                self.in_flight[child] = list(options)

    def _poll(self, field_id):
        self.polls[field_id] = self.polls.get(field_id, 0) + 1
        if self.on_poll is not None:
            self.on_poll(field_id)
        if field_id in self.in_flight and self.polls[field_id] > self.late_polls:
            self.form.options[field_id] = self.in_flight.pop(field_id)

    def _match(self, field_id, text):
        useful = [t for v, t in self.form.options.get(field_id, []) if v]
        exact = sum(runner.normalize(t) == text for t in useful)
        partial = sum(bool(text) and (runner.normalize(t) in text or text in runner.normalize(t))
                      for t in useful)
        if exact:
            return "EXACT"
        return {0: "NONE", 1: "PARTIAL"}.get(partial, "AMBIGUOUS")

    def _ready(self, script):
        field_id = re.search(r'getElementById\(("(?:[^"\\]|\\.)*")\)', script).group(1)
        field_id = json.loads(field_id)
        text = runner.normalize(json.loads(re.search(r'const text = norm\(("(?:[^"\\]|\\.)*")\)', script).group(1)))
        self._poll(field_id)
        probe = self.form.local_probe(field_id)
        return (probe["exists"] and probe["visible"] and not probe["disabled"]
                and self._match(field_id, text) in ("EXACT", "PARTIAL"))

    def _diagnostic(self, script):
        ids = json.loads(re.search(r"const ids = (\{.*?\});", script).group(1))
        text = runner.normalize(json.loads(re.search(r'const text = norm\(("(?:[^"\\]|\\.)*")\)', script).group(1)))
        child, parent = ids["child"], ids["parent"]
        self.diagnostics.append(child)
        if self.on_diagnostic is not None:
            self.on_diagnostic(child)
        probe = self.form.local_probe(child)
        return {
            "child_exists": probe["exists"], "child_disabled": child in self.form.disabled,
            "child_ready": probe["exists"] and probe["visible"] and child not in self.form.disabled,
            "useful_options": len([v for v, _t in self.form.options.get(child, []) if v]),
            "target_match": self._match(child, text),
            "parent_exists": bool(parent), "parent_disabled": parent in self.form.disabled,
            "parent_selected": bool(self.form.values.get(parent)), "jquery_active": 0,
        }

    def evaluate(self, script):
        if runner._MAPPER_CASCADE_DIAGNOSTIC_MARKER in script:
            return self._diagnostic(script)
        if _READY_SHAPE in script:
            return self._ready(script)
        result = super().evaluate(script)
        self._land_changes()
        return result


@pytest.fixture(autouse=True)
def bounded(monkeypatch):
    # Same contract, short windows: the predicate is still polled.
    monkeypatch.setattr(runner, "_CASCADE_OPTION_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)


def _assert_no_pii(log):
    for label in LABELS:
        assert label not in log, label


def _log(tmp_path):
    return _log_text(str(tmp_path))


def _reports():
    calls = []

    def report(_reporter, method_name, _session_dir, **kwargs):
        calls.append((method_name, kwargs.get("step")))
        return True

    return calls, report


# 1. Province already selected, municipal list empty until a legitimate
#    governed change: the AJAX list arrives, both levels are read back.
def test_preselected_province_governed_change_loads_and_verifies_cascade(tmp_path):
    browser = _AjaxCascadeBrowser()
    assert browser.form.options[TOWN] == [PLACEHOLDER]
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        result = runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))
        assert result["ok"] is True
        assert all(field in state.verified and state.verified[field]() for field in CASCADE)
        assert not set(CASCADE) & set(state.deferred)
    assert browser.writes.count(PROVINCE) == 1
    assert browser.writes.index(PROVINCE) < browser.writes.index(TOWN) < browser.writes.index(LOCALITY)
    assert [c for c in browser.changes if c in CASCADE] == CASCADE
    assert (browser.form.values[TOWN], browser.form.values[LOCALITY]) == ("001", "0001")
    log = _log(tmp_path)
    assert "MAPPER_CASCADE_LEVEL field=extCodigoProvincia outcome=OK change_event=DISPATCHED" in log
    assert "MAPPER_CASCADE_LEVEL field=extCodigoMunicipio outcome=OK change_event=DISPATCHED" in log
    assert "WAIT_FAIL" not in log and "MAPPER_CASCADE_BLOCKED" not in log
    _assert_no_pii(log)


# 2. Province fixed by Mercurio, municipality never offered: the parent is
#    never written, no success, no presenter, precise field and cause.
@pytest.mark.parametrize("preselected, cause, event", [
    (True, "PARENT_FIXED_NO_DEPENDENT_LOAD", "ALREADY_SATISFIED"),
    (False, "PARENT_NOT_SELECTED", "NOT_WRITTEN"),
])
def test_fixed_province_without_municipal_list_blocks_without_writing_parent(
    tmp_path, preselected, cause, event
):
    browser = _AjaxCascadeBrowser(preselected=preselected, disabled={PROVINCE})
    calls, report = _reports()
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(),
                                        extra={"qcc_report": report})
    log = _log(tmp_path)

    assert PROVINCE not in browser.writes and PROVINCE not in browser.changes
    assert TOWN not in browser.writes and LOCALITY not in browser.writes
    assert result["ok"] is False and result["label"] == "EXTRANJERO_BLOCKED"
    detail = result["detail"]
    assert (detail["blocked_field"], detail["cause"]) == (TOWN, cause)
    assert "MAPPER_CASCADE_LEVEL field=extCodigoProvincia outcome=" in log
    assert f"change_event={event}" in log
    assert "MAPPER_CASCADE_DIAGNOSTIC field=extCodigoMunicipio parent=extCodigoProvincia" in log
    assert "useful_options=0" in log and f"cause={cause}" in log
    assert f"QCC_FILL_MAPPER_RESULT step=FILLING outcome=blocked field={TOWN} cause={cause}" in log
    assert "QCC_FILL_COMPLETED" not in log and "MAPPER_FILL_COMPLETED" not in log
    assert ("fill_blocked", "FILL_BLOCKED") in calls and not any(c[0] == "filled" for c in calls)
    assert trace == [] and "preNombrePresentador" not in browser.writes
    _assert_no_pii(log)


def test_fixed_province_block_allows_controlled_human_recovery(tmp_path):
    browser = _AjaxCascadeBrowser(disabled={PROVINCE})
    datos = _cascade_datos()
    with mapper(browser, datos, tmp_path) as state:
        blocked = runner.fill_datos_extranjero(browser, datos, str(tmp_path))
        assert blocked["ok"] is False and blocked["blocked_field"] == TOWN
        # Context kept: the cascade stays pending for this same VOLCAR.
        assert {TOWN, LOCALITY} <= set(state.deferred)
        assert runner._mapper_preload_pending(browser, str(tmp_path))["ok"] is False
        # Human recovery on the page: Mercurio now offers the list.
        browser.form.options[TOWN] = list(TOWN_OPTIONS)
        recovered = runner.fill_datos_extranjero(browser, datos, str(tmp_path))
        assert recovered["ok"] is True
        assert (browser.form.values[TOWN], browser.form.values[LOCALITY]) == ("001", "0001")
        assert not set(CASCADE) & set(state.deferred)
    # The fixed parent is still never written.
    assert PROVINCE not in browser.writes


# 3. Late municipal list inside the bounded window: robust wait, success.
def test_municipality_offered_late_within_bounded_window(tmp_path):
    browser = _AjaxCascadeBrowser(late_polls=2)
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        assert runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))["ok"]
        assert all(field in state.verified for field in CASCADE)
    assert browser.polls[TOWN] > 2
    assert browser.form.values[TOWN] == "001"
    assert "WAIT_FAIL" not in _log(tmp_path)


def test_cascade_window_is_bounded_and_longer_than_historical():
    assert runner._CASCADE_OPTION_TIMEOUT_SECONDS == 1.0  # fixture
    import importlib
    source = importlib.util.find_spec("app.run_presentacion_asistida").origin
    text = open(source, encoding="utf-8").read()
    value = float(re.search(r"^_CASCADE_OPTION_TIMEOUT_SECONDS = ([0-9.]+)$", text, re.M).group(1))
    # Historical 1.2 s settle + 4 s wait, never unbounded.
    assert 5.2 < value <= 30


@pytest.mark.parametrize("options, cause", [
    ([PLACEHOLDER, ("002", "AVILES")], "TARGET_OPTION_MISSING"),
    ([PLACEHOLDER, ("001", "OVIEDO NORTE"), ("003", "OVIEDO SUR")], "TARGET_OPTION_AMBIGUOUS"),
])
def test_wrong_or_ambiguous_municipality_is_rejected_not_selected(tmp_path, options, cause):
    browser = _AjaxCascadeBrowser(loads={PROVINCE: (TOWN, options)})
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        result = runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))
        assert result["ok"] is False
        assert (result["blocked_field"], result["cause"]) == (TOWN, cause)
        assert TOWN not in state.verified
    assert TOWN not in browser.writes and TOWN not in browser.form.values
    log = _log(tmp_path)
    assert "change_event=DISPATCHED" in log and f"cause={cause}" in log
    _assert_no_pii(log)


# 4. Locality never offered after a verified municipality: blocked.
def test_missing_locality_after_municipality_blocks_without_filled(tmp_path):
    browser = _AjaxCascadeBrowser(loads={TOWN: (LOCALITY, None)})
    calls, report = _reports()
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(),
                                        extra={"qcc_report": report})
    log = _log(tmp_path)
    assert browser.form.values[TOWN] == "001" and LOCALITY not in browser.writes
    assert result["ok"] is False
    assert (result["detail"]["blocked_field"], result["detail"]["cause"]) == (
        LOCALITY, "DEPENDENT_OPTIONS_NOT_LOADED")
    assert "MAPPER_CASCADE_DIAGNOSTIC field=extCodigoLocalidad parent=extCodigoMunicipio" in log
    assert "QCC_FILL_COMPLETED" not in log
    assert not any(c[0] == "filled" for c in calls) and trace == []
    _assert_no_pii(log)


# 5. PRESENTATION_ABORT has priority and no write follows it.
@pytest.mark.parametrize("moment", ["wait", "diagnostic"])
def test_abort_has_priority_over_cascade_block(tmp_path, moment):
    browser = _AjaxCascadeBrowser(loads={PROVINCE: (TOWN, None)})
    client = _FakeActionClient()
    writes_at_abort = []

    def queue_abort(field_id):
        if field_id == TOWN and not writes_at_abort:
            writes_at_abort.append(len(browser.writes))
            client.actions.append({"action": "PRESENTATION_ABORT"})

    if moment == "wait":
        browser.on_poll = queue_abort
    else:
        browser.on_diagnostic = queue_abort
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(), action_client=client)
    log = _log(tmp_path)
    assert runner._is_qcc_aborted_result(result)
    assert len(browser.writes) == writes_at_abort[0]
    assert TOWN not in browser.writes and LOCALITY not in browser.writes
    assert "MAPPER_CASCADE_BLOCKED" not in log and "QCC_FILL_COMPLETED" not in log
    assert "QCC_FILL_MAPPER_RESULT step=FILLING outcome=aborted" in log
    if moment == "wait":
        assert TOWN not in browser.diagnostics
    assert trace == []


# 6. Later, unreached surfaces may stay DEFERRED; mandatory active ones not.
def test_unreached_presenter_and_notification_stay_deferred_without_blocking(tmp_path):
    browser = _AjaxCascadeBrowser()
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        result = runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))
        assert result["ok"] is True
        assert set(state.deferred) == set(REPRESENTANTE) | set(NOTIFICACION)
        assert state.pending_on(("extranjero", "domicilio_extranjero")) == {}


def test_active_ordinary_field_left_deferred_blocks_filled(tmp_path):
    browser = _AjaxCascadeBrowser()
    browser.form.options["extSexo"] = [PLACEHOLDER]  # intended option never offered
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        result = runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))
        assert result["ok"] is False
        assert (result["blocked_field"], result["cause"]) == ("extSexo", "ACTIVE_FIELD_PENDING")
        assert "extSexo" in state.deferred
    assert "MAPPER_ACTIVE_SURFACE_PENDING fields=['extSexo']" in _log(tmp_path)


# 7. QCC_FILL_COMPLETED only once the active surface is verified; the
#    CONTINUAR is still the human's (observed, never clicked).
def test_fill_completed_only_after_verified_active_surface(tmp_path):
    browser = _AjaxCascadeBrowser()
    calls, report = _reports()
    result, trace, navigation = _run_full_mapper(tmp_path, browser, _cascade_datos(),
                                                 extra={"qcc_report": report})
    log = _log(tmp_path)
    done = log.index("MAPPER_CASCADE_DONE block=domicilio_extranjero")
    assert "unverified=[]" in log[done:].splitlines()[0]
    assert done < log.index("QCC_FILL_MAPPER_RESULT step=FILLING outcome=ok") \
        < log.index("QCC_FILL_COMPLETED step=FILLED")
    assert ("filled", None) in calls and not any(c[0] == "fill_blocked" for c in calls)
    # Every CONTINUAR came from the observed human navigation wait.
    assert trace[0] == "CONTINUE:Datos del presentador" and trace[-1] == "FINAL_HUMAN_CONCLUIR"
    assert len(navigation) == len([t for t in trace if t.startswith("CONTINUE:")])
    assert result is None or result.get("ok") is not False
    _assert_no_pii(log)


# Familiar 131 shares the foreigner's domicile cascade: same honest block,
# never reaching the family surface.
def test_familiar_131_blocked_domicile_cascade_never_reaches_family(tmp_path):
    browser = _AjaxCascadeBrowser(disabled={PROVINCE})
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos("MERCURIO_EX01_FAMILIAR"))
    log = _log(tmp_path)
    assert result["ok"] is False and result["detail"]["blocked_field"] == TOWN
    assert trace == [] and "QCC_FILL_COMPLETED" not in log
    assert not any(field.startswith("rea") for field in browser.writes)


def test_cascade_diagnostic_javascript_reports_structure_only():
    node = shutil.which("node")
    # Never skipped: without Node the generated JavaScript is unverified.
    assert node, "Node.js required for generated JavaScript verification"
    harness = r'''
const child = {tagName:'SELECT', disabled:false, options:[{value:'',textContent:'--'}], offsetWidth:10,
  getAttribute: () => null, closest: () => null, getClientRects: () => [{}]};
const parent = {disabled:true, selectedIndex:1, value:'33'};
global.document = {getElementById: id => id === 'extCodigoMunicipio' ? child : parent};
global.window = {getComputedStyle: () => ({display:'block', visibility:'visible'})};
const script = SCRIPT;
const results = [eval(script)];
child.options = [{value:'',textContent:'--'},{value:'001',textContent:'Oviedo'}]; results.push(eval(script));
child.options = [{value:'1',textContent:'OVIEDO NORTE'},{value:'2',textContent:'OVIEDO SUR'}]; results.push(eval(script));
console.log(JSON.stringify(results));
'''.replace("SCRIPT", json.dumps(runner._mapper_cascade_diagnostic_js(TOWN, "ÓVIEDO", PROVINCE)))
    out = json.loads(subprocess.run([node, "-e", harness], capture_output=True, text=True,
                                    check=True).stdout)
    assert [(r["useful_options"], r["target_match"]) for r in out] == [
        (0, "NONE"), (1, "EXACT"), (2, "AMBIGUOUS")]
    assert out[0]["parent_disabled"] is True and out[0]["parent_selected"] is True
    assert out[1]["child_ready"] is True
    assert all(set(r) == {
        "child_exists", "child_disabled", "child_ready", "useful_options", "target_match",
        "parent_exists", "parent_disabled", "parent_selected", "jquery_active"} for r in out)

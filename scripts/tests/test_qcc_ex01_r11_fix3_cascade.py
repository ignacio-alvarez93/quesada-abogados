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

R11-FIX3B: a dependent absent from the DOM is never skipped as verified,
and FILLED requires every control mapped (with a value) on the active
foreigner surface to hold its verified postcondition live.
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
    (True, "DEPENDENT_EMPTY_PARENT_UNCHANGED", "ALREADY_SATISFIED"),
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
    # No bypass: the parent stays disabled, no option is injected.
    assert PROVINCE in browser.form.disabled and browser.form.options[TOWN] == [PLACEHOLDER]
    assert result["ok"] is False and result["label"] == "EXTRANJERO_BLOCKED"
    detail = result["detail"]
    assert (detail["blocked_field"], detail["cause"]) == (TOWN, cause)
    assert "MAPPER_CASCADE_LEVEL field=extCodigoProvincia outcome=" in log
    assert f"change_event={event}" in log
    assert "MAPPER_CASCADE_DIAGNOSTIC field=extCodigoMunicipio parent=extCodigoProvincia" in log
    assert "useful_options=0" in log and f"cause={cause} basis=OBSERVED" in log
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
    # One single FILLED, after the governed province change reached Mercurio.
    assert log.count("QCC_FILL_COMPLETED step=FILLED") == 1
    assert [c for c in calls if c[0] == "filled"] == [("filled", None)]
    assert browser.changes.index(PROVINCE) < browser.changes.index(TOWN)
    assert "MAPPER_ACTIVE_SURFACE_UNVERIFIED" not in log
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


# --- R11-FIX3B: absent dependents and integral verification --------------

def _assert_blocked_run(tmp_path, browser, datos, field, cause):
    calls, report = _reports()
    result, trace, _ = _run_full_mapper(tmp_path, browser, datos, extra={"qcc_report": report})
    log = _log(tmp_path)
    assert result["ok"] is False and result["label"] == "EXTRANJERO_BLOCKED"
    assert (result["detail"]["blocked_field"], result["detail"]["cause"]) == (field, cause)
    assert f"QCC_FILL_MAPPER_RESULT step=FILLING outcome=blocked field={field} cause={cause}" in log
    assert "QCC_FILL_COMPLETED" not in log
    assert ("fill_blocked", "FILL_BLOCKED") in calls and not any(c[0] == "filled" for c in calls)
    # No following navigation, no presenter write.
    assert trace == [] and "preNombrePresentador" not in browser.writes
    _assert_no_pii(log)
    return log


# 3. Municipality absent from the DOM after a dispatched province change:
#    bounded wait, then fail closed. R11-FIX3 skipped it (`continue`) and,
#    with the locality also absent, published FILLED.
@pytest.mark.parametrize("absent", [{TOWN}, {TOWN, LOCALITY}])
def test_absent_municipality_fails_closed_with_field_and_cause(tmp_path, absent):
    browser = _AjaxCascadeBrowser(absent=absent)
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), TOWN, "REQUIRED_DEPENDENT_MISSING")
    assert "change_event=DISPATCHED" in log and browser.polls[TOWN] >= 1
    assert "child_exists=False" in log and "cause=REQUIRED_DEPENDENT_MISSING" in log
    assert TOWN not in browser.writes and LOCALITY not in browser.writes


def test_absent_municipality_after_unchanged_parent_blocks_without_waiting(tmp_path):
    browser = _AjaxCascadeBrowser(disabled={PROVINCE}, absent={TOWN})
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), TOWN, "REQUIRED_DEPENDENT_MISSING")
    assert "MAPPER_CASCADE_DEPENDENT_ABSENT field=extCodigoMunicipio parent_event=ALREADY_SATISFIED wait=NO" in log
    assert TOWN not in browser.polls and PROVINCE not in browser.writes


# 4. Locality absent from the DOM after a verified municipality.
def test_absent_locality_after_verified_municipality_fails_closed(tmp_path):
    browser = _AjaxCascadeBrowser(absent={LOCALITY})
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), LOCALITY, "REQUIRED_DEPENDENT_MISSING")
    assert browser.form.values[TOWN] == "001" and LOCALITY not in browser.writes
    assert "MAPPER_CASCADE_DIAGNOSTIC field=extCodigoLocalidad parent=extCodigoMunicipio" in log


def test_absent_dependent_keeps_cascade_pending_for_final_gate(tmp_path):
    browser = _AjaxCascadeBrowser(absent={TOWN, LOCALITY})
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        result = runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))
        assert result["ok"] is False and result["blocked_field"] == TOWN
        assert state.deferred[TOWN] == runner.GOVERNED_OUTCOME_DEFERRED_NOT_PRESENT
        assert runner._mapper_preload_pending(browser, str(tmp_path))["ok"] is False


# A locality with no mapper value of its own (inherits the municipality
# text) keeps the historical tolerance when Mercurio does not render it.
def test_inherited_locality_absent_is_not_a_mapped_field(tmp_path):
    datos = _cascade_datos()
    del datos["domicilio_extranjero"][LOCALITY + "_text"]
    browser = _AjaxCascadeBrowser(absent={LOCALITY})
    with mapper(browser, datos, tmp_path) as state:
        assert runner.fill_datos_extranjero(browser, datos, str(tmp_path))["ok"] is True
        assert PROVINCE in state.verified and TOWN in state.verified
    log = _log(tmp_path)
    assert "MAPPER_CASCADE_LEVEL field=extCodigoLocalidad outcome=NOT_PRESENT own_value=NO" in log
    assert "MAPPER_CASCADE_BLOCKED" not in log


# 5. Late render / late list / timeout / locality target: postcondition only.
def test_municipality_rendered_late_within_bounded_window(tmp_path):
    browser = _AjaxCascadeBrowser(absent={TOWN})

    def render(field_id):
        if field_id == TOWN and browser.polls[TOWN] >= 2:
            browser.form.absent.discard(TOWN)

    browser.on_poll = render
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        assert runner.fill_datos_extranjero(browser, _cascade_datos(), str(tmp_path))["ok"] is True
        assert all(state.verified[field]() for field in CASCADE)
    assert (browser.form.values[TOWN], browser.form.values[LOCALITY]) == ("001", "0001")
    assert "MAPPER_CASCADE_DEPENDENT_ABSENT" not in _log(tmp_path)


def test_municipal_list_beyond_window_times_out_without_false_positive(tmp_path):
    browser = _AjaxCascadeBrowser(late_polls=10 ** 6)
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), TOWN, "DEPENDENT_OPTIONS_NOT_LOADED")
    assert "WAIT_FAIL cascade extCodigoMunicipio wait=TIMEOUT" in log
    assert TOWN not in browser.writes and TOWN not in browser.form.values


@pytest.mark.parametrize("options, cause", [
    ([PLACEHOLDER, ("0002", "AVILES")], "TARGET_OPTION_MISSING"),
    ([PLACEHOLDER, ("0001", "OVIEDO NORTE"), ("0003", "OVIEDO SUR")], "TARGET_OPTION_AMBIGUOUS"),
])
def test_wrong_or_ambiguous_locality_is_rejected_not_selected(tmp_path, options, cause):
    browser = _AjaxCascadeBrowser(loads={TOWN: (LOCALITY, options)})
    _assert_blocked_run(tmp_path, browser, _cascade_datos(), LOCALITY, cause)
    assert browser.form.values[TOWN] == "001"
    assert LOCALITY not in browser.writes and LOCALITY not in browser.form.values


# 6. ABORT while awaiting an absent dependent: no write, no diagnosis, no FILLED.
def test_abort_while_awaiting_absent_dependent(tmp_path):
    browser = _AjaxCascadeBrowser(absent={TOWN})
    client = _FakeActionClient()
    writes_at_abort = []

    def queue_abort(field_id):
        if field_id == TOWN and not writes_at_abort:
            writes_at_abort.append(len(browser.writes))
            client.actions.append({"action": "PRESENTATION_ABORT"})

    browser.on_poll = queue_abort
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(), action_client=client)
    log = _log(tmp_path)
    assert runner._is_qcc_aborted_result(result)
    assert len(browser.writes) == writes_at_abort[0] and TOWN not in browser.diagnostics
    assert "MAPPER_CASCADE_BLOCKED" not in log and "QCC_FILL_COMPLETED" not in log
    assert trace == []


# Integral verification: a mapped control of the active surface that was
# neither verified nor deferred (writer omitted it) blocks FILLED.
def test_unverified_mapped_field_blocks_filled_even_without_deferral(tmp_path, monkeypatch):
    original = runner.set_value

    def omitting(browser_arg, field_id, value, **kwargs):
        if field_id == "extNumero":
            return runner.GOVERNED_OUTCOME_SKIPPED
        return original(browser_arg, field_id, value, **kwargs)

    monkeypatch.setattr(runner, "set_value", omitting)
    browser = _AjaxCascadeBrowser()
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), "extNumero", "ACTIVE_FIELD_UNVERIFIED")
    assert "MAPPER_ACTIVE_SURFACE_UNVERIFIED fields=['extNumero']" in log
    assert "MAPPER_ACTIVE_SURFACE_PENDING" not in log


def test_denied_parent_not_holding_intended_option_blocks_filled(tmp_path):
    # Gate DENIES the province (never written); its dependents are offered
    # and verified, yet the province itself is not proven: no FILLED.
    browser = _AjaxCascadeBrowser(preselected=False, disabled={PROVINCE})
    browser.form.options[TOWN] = list(TOWN_OPTIONS)
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), PROVINCE, "ACTIVE_FIELD_UNVERIFIED")
    assert "CASCADE_PARENT_READ_ONLY_CHECK field=extCodigoProvincia verified=NO" in log
    assert PROVINCE not in browser.writes and PROVINCE not in browser.changes
    assert (browser.form.values[TOWN], browser.form.values[LOCALITY]) == ("001", "0001")


# --- R11-FIX3B RECOVERY-01: province fixed (disabled) by Mercurio ---------

def _fixed_province_browser(**kwargs):
    # REAL: Mercurio disables the province with its option already
    # selected and has already offered the municipal list for it.
    browser = _AjaxCascadeBrowser(disabled={PROVINCE}, **kwargs)
    browser.form.options[TOWN] = list(TOWN_OPTIONS)
    return browser


def _assert_province_untouched(browser, options_before):
    # Never written, never enabled, no synthetic change, no injected option.
    assert PROVINCE not in browser.writes and PROVINCE not in browser.changes
    assert PROVINCE in browser.form.disabled
    assert browser.form.options[PROVINCE] == options_before


# (a) Disabled province holding the intended option: verified by read-back
#     only, municipality and locality still verified, FILLED published.
def test_fixed_preselected_province_verified_read_only_and_fills(tmp_path):
    browser = _fixed_province_browser()
    options_before = list(browser.form.options[PROVINCE])
    calls, report = _reports()
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(),
                                        extra={"qcc_report": report})
    log = _log(tmp_path)

    assert result is None or result.get("ok") is not False
    _assert_province_untouched(browser, options_before)
    assert "GOVERNED_WRITE_ALREADY_SATISFIED field=extCodigoProvincia" in log
    assert "MAPPER_CASCADE_LEVEL field=extCodigoProvincia outcome=OK change_event=ALREADY_SATISFIED" in log
    assert not any("governed_write field=extCodigoProvincia " in line
                   and "INTERACTION_POLICY_DENY" in line for line in log.splitlines())
    # The dependents are still selected and read back, never inferred.
    assert browser.writes.index(TOWN) < browser.writes.index(LOCALITY)
    assert (browser.form.values[TOWN], browser.form.values[LOCALITY]) == ("001", "0001")
    done = log.index("MAPPER_CASCADE_DONE block=domicilio_extranjero")
    assert "unverified=[]" in log[done:].splitlines()[0]
    assert done < log.index("QCC_FILL_COMPLETED step=FILLED")
    assert ("filled", None) in calls and not any(c[0] == "fill_blocked" for c in calls)
    assert trace[-1] == "FINAL_HUMAN_CONCLUIR"
    _assert_no_pii(log)


# (b)/(c) Disabled province empty, holding another option, or a value whose
#     selected option is not read back unequivocally: never verified.
@pytest.mark.parametrize("value, selected", [
    (None, False), ("28", True), ("33", False),
], ids=["empty", "wrong", "no_selected_option"])
def test_fixed_province_not_holding_intended_option_blocks_filled(tmp_path, value, selected):
    browser = _fixed_province_browser(preselected=False)
    browser.form.options[PROVINCE] = [PLACEHOLDER, ("28", "MADRID"), ("33", "ASTURIAS")]
    if value is not None:
        browser.form.values[PROVINCE] = value
        if selected:
            browser.form.selects.add(PROVINCE)
    options_before = list(browser.form.options[PROVINCE])
    log = _assert_blocked_run(tmp_path, browser, _cascade_datos(), PROVINCE, "ACTIVE_FIELD_UNVERIFIED")
    _assert_province_untouched(browser, options_before)
    assert browser.form.values.get(PROVINCE) == value
    assert "CASCADE_PARENT_READ_ONLY_CHECK field=extCodigoProvincia verified=NO" in log
    assert "MAPPER_ACTIVE_SURFACE_UNVERIFIED fields=['extCodigoProvincia']" in log
    assert "GOVERNED_WRITE_ALREADY_SATISFIED field=extCodigoProvincia" not in log
    assert "MADRID" not in log


# (d) Correct fixed province, dependent level placeholder-only: blocked.
def test_fixed_preselected_province_with_placeholder_locality_blocks(tmp_path):
    browser = _fixed_province_browser(loads={TOWN: (LOCALITY, [PLACEHOLDER])})
    options_before = list(browser.form.options[PROVINCE])
    _assert_blocked_run(tmp_path, browser, _cascade_datos(), LOCALITY, "DEPENDENT_OPTIONS_NOT_LOADED")
    _assert_province_untouched(browser, options_before)
    assert LOCALITY not in browser.writes and LOCALITY not in browser.form.values


# (e) ABORT prevails over the read-only verified fixed province. The
#     municipal list is already offered, so the readiness poll that
#     carries the ABORT also succeeds: the ABORT still wins, no write.
def test_abort_prevails_after_fixed_preselected_province(tmp_path):
    browser = _fixed_province_browser()
    client = _FakeActionClient()
    writes_at_abort = []

    def queue_abort(field_id):
        if field_id == TOWN and not writes_at_abort:
            writes_at_abort.append(len(browser.writes))
            client.actions.append({"action": "PRESENTATION_ABORT"})

    browser.on_poll = queue_abort
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(), action_client=client)
    log = _log(tmp_path)
    assert runner._is_qcc_aborted_result(result)
    assert len(browser.writes) == writes_at_abort[0]
    assert PROVINCE not in browser.writes and TOWN not in browser.writes
    assert "QCC_FILL_COMPLETED" not in log and "MAPPER_CASCADE_BLOCKED" not in log
    assert trace == []


# (f) Same guarantee on the locality: an ABORT arriving in the poll that
#     finds the locality list ready prevails over that readiness.
def test_abort_prevails_while_locality_ready(tmp_path):
    browser = _fixed_province_browser()
    client = _FakeActionClient()
    writes_at_abort = []

    def queue_abort(field_id):
        if field_id == LOCALITY and not writes_at_abort:
            writes_at_abort.append(len(browser.writes))
            client.actions.append({"action": "PRESENTATION_ABORT"})

    browser.on_poll = queue_abort
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos(), action_client=client)
    log = _log(tmp_path)
    assert runner._is_qcc_aborted_result(result)
    assert browser.form.values[TOWN] == "001"
    assert len(browser.writes) == writes_at_abort[0] and LOCALITY not in browser.writes
    assert LOCALITY not in browser.diagnostics
    assert "QCC_FILL_COMPLETED" not in log and "MAPPER_CASCADE_BLOCKED" not in log
    assert "QCC_FILL_MAPPER_RESULT step=FILLING outcome=aborted" in log
    assert trace == []


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

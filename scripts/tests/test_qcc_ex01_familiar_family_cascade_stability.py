"""QCC_EX01_FAMILIAR_FAMILY_CASCADE_STABILITY_V1/V2/V4 regressions (R6 B adaptation).

REAL evidence: on "Datos del familiar" province -> municipality -> locality
were selected and postcondition-verified, but after the human CONTINUAR the
municipality was no longer selected and the family cascade was silently
re-run from the Presenter. Every select write dispatches ``change`` twice
(native + jQuery); Mercurio reloads the dependent list once per change and a
late reload rebuilds the municipality select, resetting the verified value.

Contract (adapted to ``select_municipio_localidad_familiar_ex01``):
  * each level waits (bounded) for the live family surface, its parent still
    holding the verified option and the target option really offered;
  * STABLE = settled AND every member re-verified; correct values while
    Mercurio is unsettled are re-awaited, never rewritten;
  * a lost member is reselected from its level on (parents kept), bounded by
    ``_FAMILY_CASCADE_MAX_ATTEMPTS``; a missing target is re-awaited only;
  * never stable -> FAMILIAR_EX01_BLOCKED before the Presenter;
  * after the human CONTINUAR a divergence is never repaired off-surface.

Only the physical browser (and the passing of time) is faked; the real
runner, engine, Mercurio policy and recognizer run. Values are fictitious.
"""

import inspect
import re

import pytest

import app.run_presentacion_asistida as runner
from qcc_fake_form_controls import (
    FAMILIAR, FAMILY_CASCADE, LOCALITY, PERSONAL, PRESENTER, PROVINCE, TOWN, FakeEx01Page,
)
from test_qcc_ex01_familiar_reuse import (
    ABORT, FAMILY_BLOCK, FULL_TRACE, FakeActionClient, _assert_blocked_before_presenter,
    _assert_reached_presenter, _datos, _log_text, _run, bounded,  # noqa: F401
)


VALUES = ["33", "044", "0001"]
MISSING_LOCALITY = "SAN TIRSO"  # fictitious: never offered for the municipality


def _rebuild_town(page):
    """Late municipality reload: the select is rebuilt, its value reset
    (and with it every dependent level)."""
    return lambda: page._set_value(TOWN, "")


def _late_reload_after(page, field, *, always=False):
    fired = []

    def hook(p):
        if always or not fired:
            fired.append(1)
            p.pending.append(_rebuild_town(p))
    page.after_write[field] = hook


def _never_stable_unsettled(log):
    return not [line for line in log.splitlines()
                if "FAMILY_CASCADE_STABLE" in line and "settled=False" in line]


def _settle_verdicts(monkeypatch, verdict):
    """Mercurio's settle verdict per family settle wait (``verdict(n)``)."""
    settles = []
    original = runner._wait_family_cascade_condition

    def wait(browser, condition, session_dir, control):
        if condition != runner._FAMILY_CASCADE_SETTLED_JS:
            return original(browser, condition, session_dir, control)
        settles.append(verdict(len(settles)))
        return settles[-1], None

    monkeypatch.setattr(runner, "_wait_family_cascade_condition", wait)
    return settles


# REAL DEFECT: LATE REBUILD AFTER VERIFICATION -----------------------------

def test_real_defect_municipality_invalidated_after_verification_is_stabilized_on_family(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    _late_reload_after(page, PROVINCE)
    run = _run(tmp_path, page)
    log = run.log

    _assert_reached_presenter(run, page)
    # Detected BEFORE leaving the family surface, retried from the municipality.
    lost = log.index(f"FAMILY_CASCADE_REVERIFY field={TOWN} verified=False reason=SELECT_OPTION_NOT_SELECTED")
    unstable = log.index(f"FAMILY_CASCADE_UNSTABLE attempt=1 lost={[TOWN, LOCALITY]} retry_from={TOWN}")
    stable = log.index(f"FAMILY_CASCADE_STABLE attempt=2 settled=True fields={list(FAMILY_CASCADE)}")
    leave = log.index("Espera humana asistida iniciada: Datos del presentador")
    assert lost < unstable < stable < leave
    assert _never_stable_unsettled(log)
    # Bounded retry of only the necessary part: province kept.
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == [PROVINCE, TOWN, LOCALITY, TOWN, LOCALITY]
    assert [page.values[f] for f in FAMILY_CASCADE] == VALUES
    # No family write after the surface was left; no off-surface repair.
    assert not set(FAMILY_CASCADE) & set(page.writes[run.writes_at["Datos del presentador"]:])
    assert "FAMILY_CASCADE_OFF_SURFACE_DIVERGENCE" not in log


def test_family_cascade_never_stable_blocks_before_presenter(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    _late_reload_after(page, TOWN, always=True)
    run = _run(tmp_path, page)

    _assert_blocked_before_presenter(run, page)
    assert runner._FAMILY_CASCADE_MAX_ATTEMPTS == 3
    assert run.log.count("FAMILY_CASCADE_UNSTABLE") == 2
    assert f"FAMILY_CASCADE_NEVER_STABLE attempts=3 lost={[TOWN, LOCALITY]}" in run.log
    assert page.writes.count(TOWN) == 3 and page.writes.count(PROVINCE) == 1
    assert run.result["detail"]["blocked_outcome"] == "FAMILY_CASCADE_NEVER_STABLE"
    assert "FAMILY_CASCADE_STABLE" not in run.log
    assert run.trace == ["Datos del familiar"]  # PRESENTER_AFTER_UNSTABLE_FAMILY=NO


# SETTLE CONTRACT: STABLE = SETTLED_TRUE AND ALL_POSTCONDITIONS_VERIFIED ------

def test_unsettled_values_present_is_never_stable_and_blocks_before_presenter(tmp_path, monkeypatch):
    settles = _settle_verdicts(monkeypatch, lambda n: False)
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    log = run.log

    # Values and postconditions correct, Mercurio never settled.
    assert [page.values[f] for f in FAMILY_CASCADE] == VALUES
    assert settles == [False] * runner._FAMILY_CASCADE_MAX_ATTEMPTS
    assert log.count("FAMILY_CASCADE_UNSETTLED") == runner._FAMILY_CASCADE_MAX_ATTEMPTS - 1
    assert "FAMILY_CASCADE_UNSTABLE" not in log and "FAMILY_CASCADE_STABLE" not in log
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == list(FAMILY_CASCADE)  # never rewritten
    assert (f"FAMILY_CASCADE_NEVER_STABLE attempts=3 lost=[] settled=False "
            f"unverified={list(FAMILY_CASCADE)}") in log
    _assert_blocked_before_presenter(run, page)
    assert run.trace == ["Datos del familiar"]


def test_eventual_settle_is_stable_only_once_settled_without_reselection(tmp_path, monkeypatch):
    settles = _settle_verdicts(monkeypatch, lambda n: n > 0)
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    log = run.log

    _assert_reached_presenter(run, page)
    assert settles == [False, True]
    unsettled = log.index(f"FAMILY_CASCADE_UNSETTLED attempt=1 fields={list(FAMILY_CASCADE)}")
    stable = log.index(f"FAMILY_CASCADE_STABLE attempt=2 settled=True fields={list(FAMILY_CASCADE)}")
    assert unsettled < stable
    assert "FAMILY_CASCADE_UNSTABLE" not in log
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == list(FAMILY_CASCADE)


# OFF SURFACE: DIVERGENCE AFTER CONTINUAR ---------------------------------------

def test_divergence_after_leaving_family_is_never_repaired_from_presenter(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))

    def human_continue_then_late_rebuild(p):
        p.show(PRESENTER)
        _rebuild_town(p)()

    run = _run(tmp_path, page, human={"Datos del presentador": human_continue_then_late_rebuild})

    assert run.trace == FULL_TRACE
    assert (f"FAMILY_CASCADE_OFF_SURFACE_DIVERGENCE block=familiar "
            f"fields={[TOWN, LOCALITY]} repair=NO") in run.log
    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_outcome"] == "FAMILY_CASCADE_OFF_SURFACE_DIVERGENCE"
    # OFF_SURFACE_FAMILY_REPAIR=NO
    assert not set(FAMILY_CASCADE) & set(page.writes[run.writes_at["Datos del presentador"]:])
    assert page.values[TOWN] == ""


# MID-CASCADE PARENT INVALIDATION / TARGET MISSING ------------------------------

def test_mid_cascade_parent_invalidation_is_recovered_from_the_municipality(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    _late_reload_after(page, TOWN)
    page.land_on_ready = LOCALITY
    run = _run(tmp_path, page)
    log = run.log

    _assert_reached_presenter(run, page)
    wait_fail = log.index(f"WAIT_FAIL cascade {LOCALITY}")
    diagnostic = log.index(f"FAMILY_CASCADE_READINESS_DIAGNOSTIC field={LOCALITY} parent={TOWN}")
    assert "parent_matches=False" in log[diagnostic:].splitlines()[0]
    assert "cause=PARENT_LOST" in log[diagnostic:].splitlines()[0]
    parent_lost = log.index(f"FAMILY_CASCADE_PARENT_LOST attempt=1 lost=['{TOWN}'] child={LOCALITY} "
                            f"stale_verification=INVALIDATED retry_from={TOWN}")
    stable = log.index(f"FAMILY_CASCADE_STABLE attempt=2 settled=True fields={list(FAMILY_CASCADE)}")
    assert wait_fail < diagnostic < parent_lost < stable
    # Retry from the municipality only: the province is never rewritten.
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == [PROVINCE, TOWN, TOWN, LOCALITY]
    assert [page.values[f] for f in FAMILY_CASCADE] == VALUES
    assert page.diagnostics == [LOCALITY]


def test_repeated_parent_invalidation_is_bounded_and_blocks_before_presenter(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    _late_reload_after(page, TOWN, always=True)
    page.land_on_ready = LOCALITY
    run = _run(tmp_path, page)
    log = run.log

    for attempt in (1, 2):
        assert (f"FAMILY_CASCADE_PARENT_LOST attempt={attempt} lost=['{TOWN}'] child={LOCALITY} "
                f"stale_verification=INVALIDATED retry_from={TOWN}") in log
    assert log.count("FAMILY_CASCADE_PARENT_LOST") == 2
    assert (f"FAMILY_CASCADE_NEVER_STABLE attempts=3 lost=['{TOWN}'] settled=True "
            f"unverified={[TOWN, LOCALITY]}") in log
    assert log.count(f"WAIT_FAIL cascade {LOCALITY}") == 3
    assert page.writes.count(TOWN) == 3 and page.writes.count(PROVINCE) == 1
    assert LOCALITY not in page.writes
    _assert_blocked_before_presenter(run, page)


def test_genuine_locality_target_missing_is_distinguished_and_never_rewrites_parents(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    datos = _datos(familiar={**FAMILY_BLOCK, LOCALITY + "_text": MISSING_LOCALITY})
    run = _run(tmp_path, page, datos=datos)
    log = run.log

    diagnostics = [line for line in log.splitlines() if "FAMILY_CASCADE_READINESS_DIAGNOSTIC" in line]
    assert len(diagnostics) == 3 and all("cause=TARGET_OPTION_MISSING" in d for d in diagnostics)
    assert all("parent_matches=True" in d and "target_option_present=False" in d for d in diagnostics)
    for attempt in (1, 2):
        assert (f"FAMILY_CASCADE_TARGET_PENDING attempt={attempt} field={LOCALITY} "
                f"cause=TARGET_OPTION_MISSING parent_rewrite=NO") in log
    assert "FAMILY_CASCADE_PARENT_LOST" not in log and "FAMILY_CASCADE_UNSTABLE" not in log
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == [PROVINCE, TOWN]
    assert (f"FAMILY_CASCADE_NEVER_STABLE attempts=3 lost=[] settled=True "
            f"unverified=['{LOCALITY}']") in log
    _assert_blocked_before_presenter(run, page)
    assert MISSING_LOCALITY not in log  # value-free diagnostics


def test_province_option_not_offered_never_writes_any_level(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,), options={PROVINCE: [("", "--"), ("28", "MADRID")]})
    run = _run(tmp_path, page)
    assert run.log.count(f"WAIT_FAIL cascade {PROVINCE}") == 3
    assert not set(FAMILY_CASCADE) & set(page.writes)
    assert run.result["detail"]["blocked_field"] == PROVINCE
    _assert_blocked_before_presenter(run, page)


def test_eventual_locality_ready_succeeds_without_unnecessary_rewrites(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    options_for = page.options_for
    # Mercurio offers the locality list only after the first failed wait
    # (it lands while the runner awaits the settle).
    page.options_for = lambda field: [] if field == LOCALITY and not page.settle_checks else options_for(field)
    run = _run(tmp_path, page)
    log = run.log

    _assert_reached_presenter(run, page)
    assert log.count(f"WAIT_FAIL cascade {LOCALITY}") == 1
    pending = log.index(f"FAMILY_CASCADE_TARGET_PENDING attempt=1 field={LOCALITY} "
                        f"cause=TARGET_OPTION_MISSING parent_rewrite=NO")
    stable = log.index(f"FAMILY_CASCADE_STABLE attempt=2 settled=True fields={list(FAMILY_CASCADE)}")
    assert pending < stable
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == list(FAMILY_CASCADE)
    assert [page.values[f] for f in FAMILY_CASCADE] == VALUES


# SURFACE / ABORT / BOUNDS -------------------------------------------------------

def test_surface_lost_mid_cascade_blocks_at_once_without_retry(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    page.after_write[PROVINCE] = lambda p: p.show(PERSONAL)  # tab switched meanwhile
    run = _run(tmp_path, page)

    assert "cause=SURFACE_LOST" in run.log
    assert run.result["detail"]["blocked_outcome"] == "FAMILY_CASCADE_SURFACE_LOST"
    assert run.log.count(f"WAIT_FAIL cascade {TOWN}") == 1
    assert TOWN not in page.writes and LOCALITY not in page.writes
    _assert_blocked_before_presenter(run, page)


def test_abort_during_family_settle_wait_is_serviced(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    client = FakeActionClient()
    page.after_write[LOCALITY] = lambda _p: client.actions.append(dict(ABORT))
    run = _run(tmp_path, page, client=client)

    assert runner._is_qcc_aborted_result(run.result) and run.closes == [1]
    assert "FAMILY_CASCADE_STABLE" not in run.log
    assert run.trace == ["Datos del familiar"]
    assert "fill_datos_presentador" not in run.calls


def test_genuine_wait_fail_never_writes_the_dependent(tmp_path, monkeypatch):
    session_dir = str(tmp_path)
    page = FakeEx01Page(active=(FAMILIAR,))
    selected = []
    original = runner.select_by_text_or_value
    monkeypatch.setattr(runner, "select_by_text_or_value",
                        lambda b, field, **k: selected.append(field) or original(b, field, **k))
    # The province is kept but Mercurio never loads its municipality list.
    options_for = page.options_for
    page.options_for = lambda field: [] if field == TOWN else options_for(field)

    result = runner.select_municipio_localidad_familiar_ex01(page, FAMILY_BLOCK, session_dir)

    log = _log_text(session_dir)
    assert result["ok"] is False and result["blocked_field"] == TOWN
    assert log.count(f"WAIT_FAIL cascade {TOWN}") == runner._FAMILY_CASCADE_MAX_ATTEMPTS
    assert selected == [PROVINCE]                      # the dependent is never written
    assert f"WAIT_FAIL cascade {LOCALITY}" not in log
    assert all(field != LOCALITY for field, _ in page.readiness_checks)


def test_aborted_cascade_wait_returns_the_abort_without_wait_fail(tmp_path):
    session_dir = str(tmp_path)
    page = FakeEx01Page(active=(FAMILIAR,))
    closes = []
    result = runner.select_municipio_localidad_familiar_ex01(
        page, FAMILY_BLOCK, session_dir, action_client=FakeActionClient([dict(ABORT)]),
        abort_handler=lambda: closes.append(1) or True,
    )
    assert runner._is_qcc_aborted_result(result) and closes == [1]
    assert page.writes == []                           # aborted before the province write
    log = _log_text(session_dir)
    assert "WAIT_FAIL" not in log and "FAMILY_CASCADE_STABLE" not in log


def test_happy_path_needs_no_arbitrary_sleep(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda *a: pytest.fail("No arbitrary sleeps"))
    page = FakeEx01Page(active=(FAMILIAR,))
    result = runner.select_municipio_localidad_familiar_ex01(page, FAMILY_BLOCK, str(tmp_path))
    assert result == {"ok": True, "blocked_field": None, "blocked_outcome": None,
                      "family_cascade": dict(zip(FAMILY_CASCADE, VALUES))}
    source = inspect.getsource(runner.select_municipio_localidad_familiar_ex01)
    assert "time.sleep" not in source and "_FAMILY_CASCADE_MAX_ATTEMPTS" in source


# PROBES ARE READ-ONLY, ONE LINE ------------------------------------------------

def test_cascade_readiness_requires_live_surface_and_the_parent_still_selected():
    script = runner._family_cascade_ready_js(TOWN, "", "OVIEDO", (PROVINCE, "33"))
    assert script.startswith(runner._FAMILY_CASCADE_READY_MARKER) and "\n" not in script and "//" not in script
    assert runner._ex01_sole_active_panel_js(FAMILIAR) in script
    assert "parent.selectedIndex < 0 || parent.value !== want.parent_value" in script
    assert '"parent_value": "33"' in script


def test_cascade_readiness_diagnostic_distinguishes_parent_lost_from_target_missing(tmp_path):
    session_dir = str(tmp_path)
    page = FakeEx01Page(active=(FAMILIAR,))
    page.values.update({PROVINCE: "33", TOWN: "044"})
    page.pending.append(lambda: None)  # one Mercurio request still in flight

    parent = (TOWN, "044")
    assert runner._diagnose_family_cascade_level(
        page, LOCALITY, "", MISSING_LOCALITY, parent, session_dir) == "TARGET_OPTION_MISSING"
    page._set_value(TOWN, "")  # the municipality select rebuilt
    assert runner._diagnose_family_cascade_level(
        page, LOCALITY, "", "OVIEDO", parent, session_dir) == "PARENT_LOST"
    page.show(PRESENTER)
    assert runner._diagnose_family_cascade_level(
        page, LOCALITY, "", "OVIEDO", parent, session_dir) == "SURFACE_LOST"

    log = _log_text(session_dir)
    assert log.count("FAMILY_CASCADE_READINESS_DIAGNOSTIC field=") == 3
    assert "jquery_active=1 cause=TARGET_OPTION_MISSING" in log
    assert MISSING_LOCALITY not in log and "OVIEDO" not in log
    assert page.writes == []  # read-only


def test_cascade_probes_never_write_and_other_cascades_are_unchanged():
    for script in (runner._family_cascade_diagnostic_js(LOCALITY, "", "OVIEDO", TOWN),
                   runner._family_cascade_ready_js(LOCALITY, "", "OVIEDO", (TOWN, "044")),
                   runner._FAMILY_CASCADE_SETTLED_JS):
        assert "\n" not in script
        assert not re.search(r"\.value\s*=[^=]", script)  # never assigns a control value
        for write in ("dispatchEvent", "trigger(", ".click(", "submit("):
            assert write not in script, write
    for other in (runner.select_municipio_localidad, runner.select_municipio_localidad_presentador,
                  runner.select_municipio_localidad_reagrupante):
        assert "_family_cascade" not in inspect.getsource(other)

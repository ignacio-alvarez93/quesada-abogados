"""QCC_EX01_FAMILIAR_FAMILY_CASCADE_STATE_V1 regressions (R6 B adaptation).

REAL evidence: after the human CONTINUAR to "Datos del familiar" the family
writes were gated EXECUTION_BLOCKED_STATE / DENIED / FUNCTIONAL_STATE_UNKNOWN
and the flow could still continue to the Presenter.

Root cause: on /mercurio/nuevaSolicitud-EX01.html the Mercurio recognizer
only maps the autorizacion/personales/presentador/notificacion r-tabs panels.
With tab-datos_familiar active it recognizes nothing -> functional_state None.

R6 adaptation: the historical preload wrote the ordinary family controls
while their tab was hidden; that exception is not ported, so every
``rea*Reagrupante`` control is written on its own surface under the same
narrow family state (EX01 path, family panel the SOLE active one). The
global recognizer stays untouched.

Only the physical browser is faked (synthetic single-page EX01 DOM); the
real runner, real engine, real Mercurio policy and real recognizer run.
All values are fictitious.
"""

import pytest

import app.run_presentacion_asistida as runner
from backend.automation.site_policies.mercurio import MERCURIO_REAL_ORIGIN
from backend.automation.site_recognizers.mercurio import (
    MERCURIO_EX01_NEW_REQUEST_PATH, recognize_mercurio_state,
)
from qcc_fake_form_controls import (
    AUTHORIZATION, EX01_PANELS, FAMILIAR, FAMILY_CASCADE, LOCALITY, NOTIFICATION, PERSONAL,
    PRESENTER, PROVINCE, TOWN, FakeEx01Page, _panel_element,
)
from test_qcc_ex01_familiar_reuse import (
    _assert_blocked_before_presenter, _assert_reached_presenter, _log_text, _run, bounded,  # noqa: F401
)


STATE_UNKNOWN = "decision=EXECUTION_BLOCKED_STATE status=BLOCKED outcome=DENIED"
VERIFIED = "decision=EXECUTION_ALLOWED status=SUCCESS outcome=OK reason=POSTCONDITION_VERIFIED"


def _snapshot(active, pathname=MERCURIO_EX01_NEW_REQUEST_PATH, origin=MERCURIO_REAL_ORIGIN):
    actives = {active} if isinstance(active, str) else set(active)
    return {
        "page": {"url": origin + pathname, "origin": origin},
        "elements": [_panel_element(i, p, p in actives) for i, p in enumerate(EX01_PANELS)],
    }


def _governed_log(log, field):
    return [line for line in log.splitlines() if f"governed_write field={field} kind=" in line]


# ROOT CAUSE ---------------------------------------------------------------

def test_root_cause_ex01_recognizer_has_no_family_surface():
    assert recognize_mercurio_state(_snapshot(PERSONAL)) == "EX01_PERSONAL"
    assert recognize_mercurio_state(_snapshot(PRESENTER)) == "EX01_PRESENTER"
    assert recognize_mercurio_state(_snapshot(NOTIFICATION)) == "EX01_NOTIFICATION"
    # Active "Datos del familiar": FUNCTIONAL_STATE_UNKNOWN for every write.
    assert recognize_mercurio_state(_snapshot(FAMILIAR)) is None
    # And the base recognizer ignores the family panel in an ambiguous set.
    assert recognize_mercurio_state(_snapshot((FAMILIAR, PERSONAL))) == "EX01_PERSONAL"


def test_family_surface_recognizer_is_narrow():
    recognize = runner._ex01_family_surface_recognizer(recognize_mercurio_state)
    assert recognize(_snapshot(FAMILIAR)) == runner.EX01_FAMILY_FUNCTIONAL_STATE
    # Never overrides a recognized state.
    for panel, state in ((PERSONAL, "EX01_PERSONAL"), (PRESENTER, "EX01_PRESENTER"),
                         (NOTIFICATION, "EX01_NOTIFICATION"), (AUTHORIZATION, "EX01_AUTHORIZATION")):
        assert recognize(_snapshot(panel)) == state
    # Ambiguity / absence / another page / another origin stay unknown.
    assert recognize(_snapshot((FAMILIAR, PRESENTER, NOTIFICATION))) is None
    assert recognize(_snapshot((FAMILIAR, PERSONAL))) is None  # never the other panel's state
    assert recognize(_snapshot(())) is None
    assert recognize(_snapshot(FAMILIAR, pathname="/mercurio/nuevaSolicitud-EX02.html")) is None
    assert recognize(_snapshot(FAMILIAR, origin="https://example.invalid")) is None
    # The global recognizer (AUTO TWIN, ingestion) is untouched.
    assert recognize_mercurio_state(_snapshot(FAMILIAR)) is None
    assert runner._FAMILY_CASCADE_FIELDS == set(FAMILY_CASCADE)
    # Field scope: family controls only.
    for field in (*FAMILY_CASCADE, "reaNombreReagrupante", "reaParentescoReagrupante"):
        assert runner._is_ex01_family_control(field), field
    for field in ("extNombre", "preNombrePresentador", "notNombreNotificacion", "reaNombre", ""):
        assert not runner._is_ex01_family_control(field), field


def test_family_controls_get_the_family_state_and_other_controls_do_not(tmp_path):
    page = FakeEx01Page(active=(FAMILIAR,))
    session_dir = str(tmp_path)
    with runner.governed_section(page, session_dir):
        assert runner.select_by_text_or_value(
            page, PROVINCE, value="33", text="ASTURIAS", session_dir=session_dir) == "OK"
        assert runner.set_value(page, "reaNombreReagrupante", "KARIM",
                                session_dir=session_dir) == "OK"
        # A Presenter control on the family surface: never authorized.
        assert runner.set_value(page, "preNombrePresentador", "X",
                                session_dir=session_dir) == runner.GOVERNED_OUTCOME_DENIED
    log = _log_text(tmp_path)
    assert f"field={PROVINCE} kind=SELECT {VERIFIED}" in log
    assert f"field=reaNombreReagrupante kind=INPUT_VALUE {VERIFIED}" in log
    assert "preNombrePresentador" not in page.writes
    assert "KARIM" not in log


@pytest.mark.parametrize("active", [(FAMILIAR, PERSONAL), (FAMILIAR, PRESENTER)],
                         ids=["family+personal", "family+presenter"])
def test_ambiguous_active_panels_never_authorize_a_family_write(tmp_path, active):
    page = FakeEx01Page(active=active)
    session_dir = str(tmp_path)
    assert runner.select_by_text_or_value(
        page, PROVINCE, value="33", text="ASTURIAS", session_dir=session_dir,
    ) == runner.GOVERNED_OUTCOME_DENIED
    assert PROVINCE not in page.writes and PROVINCE not in page.values
    assert f"field={PROVINCE} kind=SELECT {STATE_UNKNOWN} reason=FUNCTIONAL_STATE_UNKNOWN" in _log_text(tmp_path)


def test_stale_family_capture_is_never_evidence_after_the_panel_changed(tmp_path):
    page = FakeEx01Page(active=(FAMILIAR,))
    session_dir = str(tmp_path)
    with runner.governed_section(page, session_dir) as section:
        assert runner.set_value(page, "reaNombreReagrupante", "KARIM", session_dir=session_dir) == "OK"
        captures = page.capture_calls
        page.show(PRESENTER)  # human left the family surface meanwhile
        outcome = runner.set_value(page, "reaApellido1Reagrupante", "BENALI", session_dir=session_dir)
    assert outcome == runner.GOVERNED_OUTCOME_DENIED
    assert page.capture_calls == captures + 1  # fresh capture, never the stale one
    assert section.reused_count == 0
    assert "reaApellido1Reagrupante" not in page.writes


# REAL DEFECT REPRODUCTION ---------------------------------------------------

def test_pre_fix_real_path_reproduces_functional_state_unknown_and_now_fails_closed(
        tmp_path, monkeypatch):
    # Pre-fix recognition: the bare Mercurio recognizer for family controls.
    monkeypatch.setattr(runner, "_ex01_family_surface_recognizer", lambda recognizer: recognizer)
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)

    first = next(line for line in run.log.splitlines() if "governed_write field=rea" in line)
    assert STATE_UNKNOWN in first and "FUNCTIONAL_STATE_UNKNOWN" in first
    # Never continues as if it had been filled: blocked on the family surface.
    _assert_blocked_before_presenter(run, page)
    assert run.trace == ["Datos del familiar"]
    assert "Datos del familiar rellenados" not in run.log
    assert not set(FAMILY_CASCADE) & set(page.writes)
    assert "FAMILY_CASCADE_STABLE" not in run.log


def test_fixed_real_path_family_cascade_verified_once_in_order(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)

    _assert_reached_presenter(run, page)
    assert "FUNCTIONAL_STATE_UNKNOWN" not in run.log
    # province -> municipality -> locality, each governed and postcondition-verified.
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == list(FAMILY_CASCADE)
    for field in FAMILY_CASCADE:
        lines = _governed_log(run.log, field)
        assert len(lines) == 1 and lines[0].endswith(
            f"governed_write field={field} kind=SELECT {VERIFIED}"), lines
    assert [page.values[f] for f in FAMILY_CASCADE] == ["33", "044", "0001"]
    # Dependent options only became available after their parent was selected.
    assert (TOWN, True) in page.readiness_checks and (LOCALITY, True) in page.readiness_checks
    assert run.log.count("FAMILY_CASCADE_START") == 1


# FAIL CLOSED ------------------------------------------------------------------

@pytest.mark.parametrize("field", [PROVINCE, TOWN, LOCALITY])
def test_unverified_family_cascade_member_blocks_before_presenter(tmp_path, field):
    page = FakeEx01Page(active=(PERSONAL,), ignore_writes={field})
    run = _run(tmp_path, page)

    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_field"] == field
    assert (f"governed_write_postcondition field={field} kind=SELECT verified=False "
            "reason=SELECT_OPTION_NOT_SELECTED") in run.log
    assert f"FAMILY_CASCADE_BLOCKED field={field} outcome=FAILED" in run.log
    assert run.trace == ["Datos del familiar"]
    assert "FAMILY_CASCADE_STABLE" not in run.log
    # The cascade never wrote a level after the unverified one.
    later = FAMILY_CASCADE[FAMILY_CASCADE.index(field) + 1:]
    assert not set(later) & set(page.writes)


def test_family_cascade_without_province_is_incomplete_and_blocks(tmp_path):
    page = FakeEx01Page(active=(FAMILIAR,))
    values = {TOWN + "_text": "OVIEDO", LOCALITY + "_text": "OVIEDO"}
    result = runner.select_municipio_localidad_familiar_ex01(page, values, str(tmp_path))
    assert result["ok"] is False
    assert (result["blocked_field"], result["blocked_outcome"]) == (PROVINCE, "FAMILY_CASCADE_INCOMPLETE")
    assert page.writes == []

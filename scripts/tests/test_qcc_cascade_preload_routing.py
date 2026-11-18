"""MAPPER_PRELOAD address-cascade routing regressions.

REAL evidence: extCodigoProvincia NOT_INTERACTABLE -> DENIED stopped the
whole MAPPER_PRELOAD (MAPPER_SECTION_BLOCKED) before municipality,
locality, notification and presenter. Historically the specialized
cascade helpers discarded the province outcome and went on with
municipality / locality. Only the physical browser is faked.
"""
from collections import Counter

import pytest
import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import (
    _TabbedMercurioBrowser, _datos, _run_full_mapper, _FakeActionClient,
    ALL_EX01_FIELDS, PERSONAL, PRESENTER, NOTIFICATION, _log_text,
)
from test_qcc_preloaded_full_mapper import mapper


PROVINCE, TOWN, LOCALITY = "extCodigoProvincia", "extCodigoMunicipio", "extCodigoLocalidad"
PRE_PROVINCE, PRE_TOWN, PRE_LOCALITY = (
    "preCodigoProvinciaPresentador", "preCodigoMunicipioPresentador", "preCodigoLocalidadPresentador",
)
CASCADE = [PROVINCE, TOWN, LOCALITY]
PRE_CASCADE = [PRE_PROVINCE, PRE_TOWN, PRE_LOCALITY]
OPTIONS = {
    PROVINCE: [("33", "ASTURIAS")], TOWN: [("001", "OVIEDO")], LOCALITY: [("0001", "OVIEDO")],
    PRE_PROVINCE: [("33", "ASTURIAS")], PRE_TOWN: [("001", "OVIEDO")], PRE_LOCALITY: [("0001", "OVIEDO")],
}


def _cascade_datos():
    datos = _datos("MERCURIO_EX01")
    datos["domicilio_extranjero"].update({
        PROVINCE: "33", PROVINCE + "_text": "ASTURIAS",
        TOWN + "_text": "OVIEDO", LOCALITY + "_text": "OVIEDO",
    })
    datos["representante"].update({
        PRE_PROVINCE: "33", PRE_TOWN + "_text": "OVIEDO", PRE_LOCALITY + "_text": "OVIEDO",
        "ruta_box_dni_representante": "private/box/path",
    })
    return datos


def _browser(**kwargs):
    return _TabbedMercurioBrowser(
        fields=ALL_EX01_FIELDS + CASCADE + PRE_CASCADE, selects=CASCADE + PRE_CASCADE,
        options={k: list(v) for k, v in OPTIONS.items()}, **kwargs,
    )


@pytest.fixture
def fast(monkeypatch):
    # The engine's bounded dependency wait for the locked province ends
    # immediately; any fixed settle sleep in the cascade fails the test.
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)
    monkeypatch.setattr(runner.time, "sleep", lambda *a: pytest.fail("No arbitrary sleeps"))


def _preselect_province(browser, value="33"):
    # REAL: Mercurio fixes (disables) the province with its option selected.
    browser.form.selects.add(PROVINCE)
    browser.form.values[PROVINCE] = value


def test_denied_province_does_not_block_mapper_and_reaches_presenter(tmp_path, fast):
    # QCC_EX01_R11_FIX3B_CASCADE: the REAL fixed province is disabled AND
    # already holds the intended option; it is verified by read-back only.
    browser = _browser(disabled={PROVINCE})
    _preselect_province(browser)
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos())
    log = _log_text(str(tmp_path))

    # 1. The fixed province is not fatal to the mapper, and never written.
    assert "GOVERNED_WRITE_ALREADY_SATISFIED field=extCodigoProvincia" in log
    assert "MAPPER_CASCADE_LEVEL field=extCodigoProvincia outcome=OK change_event=ALREADY_SATISFIED" in log
    assert PROVINCE not in browser.writes and PROVINCE in browser.form.disabled
    assert (PROVINCE, "change") not in browser.form.events
    assert "MAPPER_SECTION_BLOCKED" not in log
    assert result is None or result.get("ok") is not False
    # 2./3. Municipality, then locality, attempted and verified.
    assert browser.writes.index(TOWN) < browser.writes.index(LOCALITY)
    assert browser.form.values[TOWN] == "001" and browser.form.values[LOCALITY] == "0001"
    # 4./5. The mapper continues past the cascade to the presenter block.
    after = browser.writes[browser.writes.index(LOCALITY) + 1:]
    assert "preNombrePresentador" in after
    assert trace[-1] == "FINAL_HUMAN_CONCLUIR"
    assert "MAPPER_FILL_COMPLETED" in log
    # The whole domicile cascade is verified, nothing left unverified.
    done = log.index("MAPPER_CASCADE_DONE block=domicilio_extranjero")
    assert "unverified=[]" in log[done:].splitlines()[0]
    assert "MAPPER_ACTIVE_SURFACE_UNVERIFIED" not in log
    # Metadata never reaches DOM selector resolution.
    assert "ruta_box_dni_representante" not in browser.writes + browser.form.local_probes


@pytest.mark.parametrize("value", [None, "28"], ids=["empty", "wrong"])
def test_disabled_province_without_intended_option_blocks_before_presenter(tmp_path, fast, value):
    # A fixed province that is empty (no option selected) or holds another
    # option is never written and never verified: no FILLED, no presenter.
    browser = _browser(disabled={PROVINCE})
    if value is not None:
        browser.form.options[PROVINCE] = OPTIONS[PROVINCE] + [("28", "MADRID")]
        _preselect_province(browser, value)
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos())
    log = _log_text(str(tmp_path))

    assert result["ok"] is False and result["label"] == "EXTRANJERO_BLOCKED"
    assert (result["detail"]["blocked_field"], result["detail"]["cause"]) == (
        PROVINCE, "ACTIVE_FIELD_UNVERIFIED")
    assert "field=extCodigoProvincia" in log and "INTERACTION_POLICY_DENY" in log
    assert "CASCADE_PARENT_READ_ONLY_CHECK field=extCodigoProvincia verified=NO" in log
    assert "unverified=['extCodigoProvincia']" in log
    assert PROVINCE not in browser.writes and browser.form.values.get(PROVINCE) == value
    assert (PROVINCE, "change") not in browser.form.events
    assert "QCC_FILL_COMPLETED" not in log and "MAPPER_FILL_COMPLETED" not in log
    assert "preNombrePresentador" not in browser.writes and trace == []


def test_cascade_fields_not_duplicated_by_generic_iterator(tmp_path, fast):
    browser = _browser()
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos())
    assert result is None or result.get("ok") is not False
    counts = Counter(browser.writes)
    assert all(counts[f] == 1 for f in CASCADE + PRE_CASCADE)
    assert max(counts.values()) == 1
    log = _log_text(str(tmp_path))
    assert log.count("MAPPER_CASCADE_START block=domicilio_extranjero") == 1
    assert log.count("MAPPER_CASCADE_START block=representante") == 1
    # Historical order: ordinary block controls first, then the cascade.
    assert browser.writes.index("extNumero") < browser.writes.index(PROVINCE)
    assert browser.writes.index(PROVINCE) < browser.writes.index(TOWN) < browser.writes.index(LOCALITY)


def test_generic_iterator_routes_cascade_to_specialized_helper(tmp_path, fast, monkeypatch):
    calls = []
    original = runner.select_municipio_localidad
    monkeypatch.setattr(runner, "select_municipio_localidad",
                        lambda b, v, s, prefix="ext": calls.append(prefix) or original(b, v, s, prefix=prefix))
    browser = _browser()
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
    assert calls == ["ext"]
    for field in CASCADE:
        assert field in state.verified


def test_unreached_block_cascade_waits_for_its_surface(tmp_path, fast):
    browser = _browser()
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        assert not set(PRE_CASCADE) & set(browser.writes)
        assert {state.deferred[f] for f in PRE_CASCADE} == {"DEFERRED_DEPENDENCY"}
        browser.form.active_panel = PRESENTER
        assert state.resume(("representante",))["ok"]
        assert not set(PRE_CASCADE) & set(state.deferred)
        assert browser.form.values[PRE_LOCALITY] == "0001"
        # QCC_EX01_R6_POSTFORM: Notification is only settled on its own
        # surface; then nothing at all is left deferred.
        browser.form.active_panel = NOTIFICATION
        assert state.resume(("notificacion",))["ok"]
        assert not state.deferred


def test_cascade_reruns_only_when_a_verified_member_is_cleared(tmp_path, fast):
    browser = _browser(disabled={PROVINCE})
    with mapper(browser, _cascade_datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        before = list(browser.writes)
        # DENIED province is never retried by itself.
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        assert browser.writes == before
        browser.form.values[TOWN] = ""
        assert state.resume(())["ok"]
        assert browser.writes == before + [TOWN, LOCALITY]


def test_unrelated_denied_ordinary_field_still_fails_closed(tmp_path, fast):
    browser = _browser(disabled={"extNombre"})
    result, trace, _ = _run_full_mapper(tmp_path, browser, _cascade_datos())
    assert result["ok"] is False
    assert "MAPPER_SECTION_BLOCKED" in _log_text(str(tmp_path))
    assert "preNombrePresentador" not in browser.writes
    assert "FINAL_HUMAN_CONCLUIR" not in trace


def test_abort_during_cascade_wait_stops_before_municipality(tmp_path, fast):
    browser = _browser()
    client = _FakeActionClient()
    evaluate = browser.evaluate

    def queue_abort(script):
        result = evaluate(script)
        if 'const wantedValue = "33"' in script and 'extCodigoProvincia"' in script:
            client.actions.append({"action": "PRESENTATION_ABORT"})
        return result

    browser.evaluate = queue_abort
    closed = []
    with mapper(browser, _cascade_datos(), tmp_path, action_client=client,
                abort_handler=lambda: closed.append(True) or True) as state:
        result = state.resume(("extranjero", "domicilio_extranjero"))
        assert runner._is_qcc_aborted_result(result)
        assert closed == [True]
        assert TOWN not in browser.writes and LOCALITY not in browser.writes
        assert "preNombrePresentador" not in browser.writes
        assert state.resume(()) == result

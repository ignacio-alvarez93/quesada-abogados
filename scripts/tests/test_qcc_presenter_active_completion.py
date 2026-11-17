"""QCC_PRESENTER_ACTIVE_COMPLETION_V1 regressions (QCC_EX01_R6_POSTFORM adapted: no
hidden-tab writes, each surface is completed once human navigation reaches it).

REAL evidence: the certificate-managed presenter name was deferred
(``DEFERRED_PRELOAD_UNPROVEN``) during the initial preload and, once
human navigation made Presenter active, its readonly control was DENIED,
so ``fill_section`` stopped (PRESENTADOR_BLOCKED) before the presenter
address cascade. Local captures show Mercurio renders the certificate
name surname-first while the mapper is given-name-first (same tokens).

Only the physical browser is faked; the real runner, real engine and
Mercurio's real policy run. All identity values are fictitious.
"""
from collections import Counter

import pytest
import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import _run_full_mapper, _log_text, PRESENTER, NOTIFICATION
from test_qcc_preloaded_full_mapper import mapper
from qcc_presenter_preload_doubles import (
    _browser, _presenter_datos, FIELDS, SELECTS, IDENTITY, NAME, DOC_TYPE, DOC,
    ADDRESS, EMAIL, PRE_PROVINCE, PRE_TOWN, PRE_LOCALITY, PRE_CASCADE,
)


MAPPER_NAME = "JUAN CARLOS GARCIA PEREZ"
LEGAL = (
    "preNombreRepresentantePresentador", "preTipodocumentoRepresentantePresentador",
    "preNieRepresentantePresentador", "preTituloRepresentantePresentador",
    "preTelefonoMovilRepLegalPresentador", "preEmailRepLegalPresentador",
)
LEGAL_DOC_TYPE = "preTipodocumentoRepresentantePresentador"
EMPTY_LEGAL = {field: "" for field in LEGAL}
CASCADE_OPTIONS = {PRE_PROVINCE: [("33", "ASTURIAS")], PRE_TOWN: [("001", "OVIEDO")],
                   PRE_LOCALITY: [("0001", "OVIEDO")]}
CASCADE_VALUES = {PRE_PROVINCE: "33", PRE_PROVINCE + "_text": "ASTURIAS",
                  PRE_TOWN + "_text": "OVIEDO", PRE_LOCALITY + "_text": "OVIEDO"}


def _certificate(name, doc=IDENTITY[DOC], **kwargs):
    """Mercurio double holding the certificate identity readonly."""
    return _browser(readonly={NAME, DOC}, pointer_none={DOC_TYPE},
                    certificate={NAME: name, DOC_TYPE: IDENTITY[DOC_TYPE], DOC: doc}, **kwargs)


def _datos(**extra):
    return _presenter_datos(**{NAME: MAPPER_NAME, **extra})


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)
    monkeypatch.setattr(runner.time, "sleep", lambda *a: pytest.fail("No arbitrary sleeps"))


# PHASE B · CERTIFICATE IDENTITY COMPARATOR ------------------------------

@pytest.mark.parametrize("live", [
    "JUAN CARLOS GARCIA PEREZ",        # 1. exact representation
    "juan  carlos garcía pérez",       # case / accents / whitespace
    "GARCIA PEREZ JUAN CARLOS",        # 2. Mercurio surname-first (REAL shape)
    "GARCÍA PÉREZ, JUAN CARLOS",       # surname-first with punctuation
])
def test_certificate_name_equivalent_is_verified_without_write(tmp_path, fast, live):
    browser = _certificate(live)
    with mapper(browser, _datos(), tmp_path) as state:
        result = state.resume(("extranjero", "domicilio_extranjero"))
    assert result["ok"]
    assert NAME in state.verified and NAME not in state.deferred
    assert browser.writes.count(NAME) == 0
    assert not [e for e in browser.form.events if e[0] in IDENTITY]
    log = _log_text(str(tmp_path))
    assert f"CERTIFICATE_IDENTITY_VERIFIED field={NAME}" in log
    assert live.split()[0] not in log  # value-free log


@pytest.mark.parametrize("live", [
    "PEDRO LOPEZ RUIZ",                    # another identity
    "GARCIA PEREZ JUAN",                   # missing token
    "GARCIA GARCIA PEREZ JUAN CARLOS",     # multiplicity preserved
])
def test_certificate_true_name_mismatch_fails_closed(tmp_path, fast, live):
    browser = _certificate(live)
    with mapper(browser, _datos(), tmp_path) as state:
        result = state.resume(("extranjero", "domicilio_extranjero"))
    assert result == {"ok": False, "label": "PRESENTADOR_BLOCKED", "blocked_field": NAME,
                      "blocked_outcome": "CERTIFICATE_IDENTITY_MISMATCH"}
    assert NAME not in state.verified
    assert browser.writes.count(NAME) == 0
    assert f"CERTIFICATE_IDENTITY_MISMATCH field={NAME}" in _log_text(str(tmp_path))


def test_certificate_nie_mismatch_fails_closed(tmp_path, fast):
    browser = _certificate(MAPPER_NAME, doc="X1111111H")
    with mapper(browser, _datos(), tmp_path) as state:
        result = state.resume(("extranjero", "domicilio_extranjero"))
    assert result["ok"] is False and result["blocked_field"] == DOC
    assert result["blocked_outcome"] == "CERTIFICATE_IDENTITY_MISMATCH"
    assert DOC not in browser.writes


def test_certificate_nie_is_exact_canonical_never_token_order():
    browser = _browser(fields=[DOC], selects=[], certificate={DOC: "x-0000000 t"})
    assert runner._certificate_identity_matches(browser, DOC, "X0000000T", "")
    browser.form.values[DOC] = "T X0000000"
    assert not runner._certificate_identity_matches(browser, DOC, "X0000000T", "")


def test_generic_input_comparison_stays_order_sensitive():
    browser = _browser(fields=[ADDRESS], selects=[], certificate={ADDRESS: "PEREZ GARCIA"})
    assert not runner._input_value_satisfied(browser, ADDRESS, "GARCIA PEREZ")
    # QCC_NOTIFICATION_CERTIFICATE_AUTHORITY_V1: Notification identity is
    # not a mapper comparison target; it only references the presenter.
    assert runner._CERTIFICATE_IDENTITY_FIELDS == {NAME, DOC, DOC_TYPE}


def test_writable_empty_identity_keeps_ordinary_path(tmp_path, fast):
    # Not certificate-held (editable): never treated as verification target.
    browser = _browser()
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
    assert "CERTIFICATE_IDENTITY_VERIFIED field=pre" not in _log_text(str(tmp_path))
    assert "CERTIFICATE_IDENTITY_MISMATCH" not in _log_text(str(tmp_path))


# PHASE C/D · ACTIVE PRESENTER COMPLETION --------------------------------

def _full_run(tmp_path, monkeypatch, browser, datos):
    calls, fill_starts = [], []
    original = runner.select_municipio_localidad_presentador

    def spy(b, values, session_dir):
        calls.append(browser.form.active_panel)
        return original(b, values, session_dir)

    monkeypatch.setattr(runner, "select_municipio_localidad_presentador", spy)

    def fill_start(*args, **kwargs):
        fill_starts.append(True)
        return {"ok": True, "mode": "fill_start_confirmed"}

    result, trace, _ = _run_full_mapper(tmp_path, browser, datos,
                                        extra={"wait_for_qcc_fill_start": fill_start})
    return result, trace, calls, fill_starts, _log_text(str(tmp_path))


def test_presenter_active_surface_completes_with_cascade(tmp_path, fast, monkeypatch):
    fields = FIELDS + PRE_CASCADE + list(LEGAL)
    selects = SELECTS + PRE_CASCADE + [LEGAL_DOC_TYPE]
    browser = _certificate("GARCIA PEREZ JUAN CARLOS", fields=fields, selects=selects,
                           options=CASCADE_OPTIONS)
    datos = _datos(**CASCADE_VALUES, **EMPTY_LEGAL, ruta_box_dni_representante="private/box/path")
    result, trace, calls, fill_starts, log = _full_run(tmp_path, monkeypatch, browser, datos)

    assert result is None or result.get("ok") is not False
    # 5. Verified certificate field never retried after human navigation.
    assert browser.writes.count(NAME) == 0
    assert log.count(f"CERTIFICATE_IDENTITY_VERIFIED field={NAME}") == 1
    assert f"field={NAME} kind=INPUT_VALUE" not in log
    assert "DENIED" not in log and "PRESENTADOR_BLOCKED" not in log
    # 6.-10. Specialized cascade reached on the active Presenter surface, once.
    assert calls == [PRESENTER]
    assert log.count("MAPPER_CASCADE_START block=representante") == 1
    assert browser.form.values[PRE_PROVINCE] == "33"
    assert browser.form.values[PRE_TOWN] == "001"
    assert browser.form.values[PRE_LOCALITY] == "0001"
    # 11. Cascade members never generic-double-written.
    writes = Counter(browser.writes)
    assert all(writes[f] == 1 for f in PRE_CASCADE)
    assert max(writes.values()) == 1
    # 12. Empty optional representante-legal group never attempted.
    assert not set(LEGAL) & set(browser.writes + browser.form.local_probes)
    assert "OPTIONAL_GROUP_NOT_APPLICABLE group=REPRESENTANTE_LEGAL_PRESENTADOR" in log
    # 16.-19. One VOLCAR, metadata filtered, HUMAN_ONLY final presentation.
    assert fill_starts == [True]
    assert "ruta_box_dni_representante" not in browser.writes + browser.form.local_probes
    assert "MAPPER_FILL_COMPLETED" in log
    assert trace[-1] == "FINAL_HUMAN_CONCLUIR"
    # 15. Ordinary presenter preload still written.
    assert ADDRESS in browser.writes and EMAIL in browser.writes


def test_certificate_verified_then_navigation_does_not_retry(tmp_path, fast):
    browser = _certificate("GARCIA PEREZ JUAN CARLOS")
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        probes_before = browser.form.local_probes.count(NAME)
        browser.form.active_panel = PRESENTER  # human navigation
        assert state.resume(("representante",))["ok"]
        browser.form.active_panel = NOTIFICATION  # human navigation
        assert state.resume(("notificacion",))["ok"]
        assert state.resume(())["ok"]
    assert browser.writes.count(NAME) == 0
    assert browser.form.local_probes.count(NAME) == probes_before
    assert not state.deferred
    assert "DENIED" not in _log_text(str(tmp_path))


def test_mismatch_on_active_surface_never_reaches_cascade(tmp_path, fast, monkeypatch):
    browser = _certificate("PEDRO LOPEZ RUIZ", fields=FIELDS + PRE_CASCADE,
                           selects=SELECTS + PRE_CASCADE, options=CASCADE_OPTIONS)
    result, trace, calls, _, log = _full_run(tmp_path, monkeypatch, browser, _datos(**CASCADE_VALUES))
    assert result["ok"] is False
    assert calls == [] and "FINAL_HUMAN_CONCLUIR" not in trace
    assert NAME not in browser.writes
    assert "CERTIFICATE_IDENTITY_MISMATCH" in log


# PHASE E · OPTIONAL REPRESENTANTE LEGAL GROUP ---------------------------

def test_empty_representante_legal_group_is_not_applicable(tmp_path):
    values = {**IDENTITY, **EMPTY_LEGAL, LEGAL_DOC_TYPE + "_text": ""}
    kept = runner._drop_inapplicable_optional_groups("representante", values, str(tmp_path))
    assert kept == IDENTITY
    assert "OPTIONAL_GROUP_NOT_APPLICABLE" in _log_text(str(tmp_path))
    # A lone document-type placeholder is not substantive data.
    values[LEGAL_DOC_TYPE] = "NIE"
    assert runner._drop_inapplicable_optional_groups("representante", values, str(tmp_path)) == IDENTITY


@pytest.mark.parametrize("field", sorted(set(LEGAL) - {LEGAL_DOC_TYPE}))
def test_real_representante_legal_data_keeps_group_applicable(tmp_path, field):
    values = {**IDENTITY, **EMPTY_LEGAL, field: "DATO"}
    assert runner._drop_inapplicable_optional_groups("representante", values, str(tmp_path)) == values
    assert "OPTIONAL_GROUP_NOT_APPLICABLE" not in _log_text(str(tmp_path))


def test_real_representante_legal_group_is_still_attempted(tmp_path, fast):
    browser = _certificate(MAPPER_NAME, fields=FIELDS + list(LEGAL), selects=SELECTS + [LEGAL_DOC_TYPE],
                           options={LEGAL_DOC_TYPE: [("NIE", "NIE")]})
    legal = {**EMPTY_LEGAL, "preNombreRepresentantePresentador": "REPRESENTANTE FICTICIO",
             LEGAL_DOC_TYPE: "NIE"}
    with mapper(browser, _datos(**legal), tmp_path) as state:
        assert LEGAL_DOC_TYPE in state.values["representante"]
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        # QCC_EX01_R6_POSTFORM: written on the presenter surface only.
        assert not set(LEGAL) & set(browser.writes)
        browser.form.active_panel = PRESENTER  # human navigation
        assert state.resume(("representante",))["ok"]
    assert "preNombreRepresentantePresentador" in browser.writes
    assert LEGAL_DOC_TYPE in browser.writes


def test_other_blocks_are_never_filtered(tmp_path):
    values = {"extNombre": "", "extNieRepresentante": ""}
    assert runner._drop_inapplicable_optional_groups("extranjero", values, str(tmp_path)) == values

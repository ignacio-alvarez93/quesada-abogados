"""QCC_EX01_FAMILIAR_REUSE_V1 regressions (R6 B adaptation).

EX01 Familiar (EX01_RENOVACION_FAMILIAR, Mercurio supuesto EX-01-2-02 /
``datosForAut=131``, ``mapper_codigo=MERCURIO_EX01_FAMILIAR``) reuses the
EX01 Titular core: same ``run_auto``, same common stage, same Presenter /
final human gate. The only family-specific surface is "Datos del familiar"
(``rea*Reagrupante``), fed by the canonical CRM relation through
``build_datos_familiar_ex01``.

Adapted to the current architecture (``fill_section`` + governed writes;
the historical ``_MapperPreload`` engine is NOT restored). Only the
physical browser (a SYNTHETIC single-page EX01 DOM) and the DB contact
lookup are faked; the real runner, real mapper, real governed engine and
Mercurio's real policy/recognizer run. Offline; fictitious values only.
"""

import inspect
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import app.run_presentacion_asistida as runner
import backend.services.mercurio_mapper_service as mapper_service
from qcc_fake_form_controls import (
    FAMILIAR, FAMILY_CASCADE, LOCALITY, PERSONAL, PRESENTER, PROVINCE, TOWN, FakeEx01Page,
)


REPO = Path(__file__).resolve().parents[2]

# CRM relation selected in Datos especificos (cliente_contactos row).
CONTACT_ID = 11
CONTACT = {
    "id": CONTACT_ID, "nombre": "KARIM", "primer_apellido": "BENALI", "segundo_apellido": "",
    "nie": "Y0000000Z", "sexo": "HOMBRE", "fecha_nacimiento": "1980-02-03", "estado_civil": "CASADO",
    "pais_nacimiento": "MARRUECOS", "nacionalidad": "MARRUECOS", "localidad_nacimiento": "TANGER",
    "nombre_padre": "PADRE", "nombre_madre": "MADRE", "domicilio_espana": "CALLE URIA 5",
    "provincia": "ASTURIAS", "localidad": "OVIEDO", "codigo_postal": "33001",
    "telefono": "600000001", "parentesco": "CONYUGE",
}
SNAPSHOT = {"datos_especificos": {"representante_legal": f"{CONTACT_ID} - KARIM BENALI"}}
APPLICANT = {"nombre": "AMINA", "primer_apellido": "BENALI", "nie": "Y2222222J"}
PII = ("KARIM", "BENALI", "Y0000000Z", "Y2222222J", "OVIEDO", "ASTURIAS", "URIA", "600000001")


def _familiar_block(contact=CONTACT, snapshot=SNAPSHOT, cliente=None):
    """The canonical EX01 Familiar block, built by the real mapper."""
    with patch.object(mapper_service, "_get_cliente_contacto",
                      lambda cid: dict(contact) if contact and cid == CONTACT_ID else None):
        return mapper_service.build_datos_familiar_ex01(cliente or {}, snapshot=snapshot)


FAMILY_BLOCK = _familiar_block()
FAMILY_WRITTEN = {
    k.removesuffix("_text") for k, v in FAMILY_BLOCK.items() if str(v).strip()
} - set(FAMILY_CASCADE)
FAMILY_EMPTY = {k for k, v in FAMILY_BLOCK.items() if not str(v).strip()} - {
    k.removesuffix("_text") for k, v in FAMILY_BLOCK.items() if str(v).strip()
}


def _datos(mapper_codigo="MERCURIO_EX01_FAMILIAR", familiar=None):
    datos = {
        "presentacion": {"tipo_formulario_objetivo": "EX01", "mapper_codigo": mapper_codigo},
        "extranjero": {"extNombre": APPLICANT["nombre"], "extNie": APPLICANT["nie"]},
        "domicilio_extranjero": {},
        "notificacion": {},
        "representante": {},
    }
    if mapper_codigo == "MERCURIO_EX01_FAMILIAR":
        datos["familiar"] = dict(FAMILY_BLOCK) if familiar is None else familiar
    return datos


ABORT = {"action_id": 7, "action": "PRESENTATION_ABORT", "payload": {}}


class FakeActionClient:
    def __init__(self, actions=()):
        self.actions = list(actions)

    def consume_next(self):
        return self.actions.pop(0) if self.actions else None


@pytest.fixture(autouse=True)
def bounded(monkeypatch):
    """Bounded waits (REAL: seconds) and never an ENTER fallback."""
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(runner, "_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: pytest.fail("ENTER fallback used"))


def _log_text(session_dir):
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in Path(session_dir).rglob("*") if p.is_file())


class _Run:
    pass


SHARED = ("fill_datos_extranjero", "fill_datos_presentador", "click_continuar_presentador",
          "pause_humana_final_presentacion")


def _run(tmp_path, page, *, datos=None, abort_at=None, human=None, client=None,
         wait_timeout=0.3):
    """REAL ``run_auto``. The common EX01 core stages (covered by the
    Titular suites) are recorded spies; the family stage, the human
    transition waits and the governed writes are the real ones. Every
    human CONTINUAR only moves the active panel (``human`` overrides)."""

    run = _Run()
    run.trace, run.calls, run.closes, run.writes_at = [], [], [], {}
    run.client = client or FakeActionClient()
    real_wait = runner.wait_for_human_navigation
    moves = {"Datos del familiar": (FAMILIAR,), "Datos del presentador": (PRESENTER,)}
    moves.update(human or {})

    def wait(browser, session_dir, label, ready_js, **kwargs):
        run.trace.append(label)
        run.writes_at[label] = len(page.writes)
        if abort_at == label:
            run.client.actions.append(dict(ABORT))
        move = moves.get(label)
        if callable(move):
            move(page)
        elif move is not None:
            page.show(*move)
        kwargs.update(timeout=wait_timeout, interval=0.01)
        return real_wait(browser, session_dir, label, ready_js, **kwargs)

    def spy(name, value):
        def recorded(*_a, **_k):
            run.calls.append(name)
            return value
        return recorded

    def traced(name):
        original = getattr(runner, name)

        def recorded(*a, **k):
            run.calls.append(name)
            return original(*a, **k)
        return recorded

    ok = {"ok": True}
    with patch.multiple(
        runner,
        step_continuar_inicial=lambda *a, **k: ok,
        pause_certificado=lambda *a, **k: ok,
        step_presentar_nueva_solicitud=lambda *a, **k: ok,
        pause_supuesto=lambda *a, **k: ok,
        wait_for_qcc_fill_start=lambda *a, **k: ok,
        _wait_for_ex01_personal_readiness=lambda *a, **k: ok,
        _verify_ex01_renovacion_titular_identity=lambda *a, **k: ok,
        wait_for_human_navigation=wait,
        fill_datos_extranjero=spy("fill_datos_extranjero", {"ok": True}),
        click_continuar=spy("click_continuar", ok),
        fill_datos_presentador=spy("fill_datos_presentador", True),
        click_continuar_presentador=spy("click_continuar_presentador", ok),
        pause_humana_final_presentacion=spy("pause_humana_final_presentacion", ok),
        fill_datos_familiar_ex01=traced("fill_datos_familiar_ex01"),
        select_municipio_localidad_familiar_ex01=traced("select_municipio_localidad_familiar_ex01"),
    ):
        run.result = runner.run_auto(
            page, "33", datos or _datos(), str(tmp_path), reporter=Mock(),
            action_client=run.client, abort_handler=lambda: run.closes.append(1) or True,
        )
    run.log = _log_text(tmp_path)
    run.family_writes = page.writes[run.writes_at.get("Datos del familiar", 0):
                                    run.writes_at.get("Datos del presentador", len(page.writes))]
    return run


FULL_TRACE = ["Datos del familiar", "Datos del presentador"]


def _assert_reached_presenter(run, page):
    assert run.trace == FULL_TRACE
    assert run.result is None or run.result.get("ok") is not False, run.result
    assert run.calls.count("fill_datos_presentador") == 1
    assert run.calls.count("pause_humana_final_presentacion") == 1
    assert "FAMILY_CASCADE_POST_CONTINUE_VERIFIED" in run.log
    assert page.unexpected == []


def _assert_blocked_before_presenter(run, page, label="FAMILIAR_EX01_BLOCKED"):
    assert run.result["ok"] is False and run.result["label"] == label, run.result
    assert "fill_datos_presentador" not in run.calls        # PRESENTER_EXECUTED=NO
    assert "pause_humana_final_presentacion" not in run.calls
    assert not [f for f in page.writes if f.startswith("pre")]


# PHASE A/B · BRANCH IDENTITY AND ROUTING ---------------------------------

def test_1_family_branch_recognized_independently_from_titular():
    familiar = runner.get_mercurio_mapper_mode(_datos())
    titular = runner.get_mercurio_mapper_mode(_datos("MERCURIO_EX01"))
    assert familiar["is_ex01_familiar"] and not familiar["is_ex01"]
    assert titular["is_ex01"] and not titular["is_ex01_familiar"]
    # Same tipo_formulario_objetivo: the branch comes from the procedure mapper.
    assert runner.get_tipo_formulario_objetivo(_datos()) == "EX01"
    assert runner.get_tipo_formulario_objetivo(_datos("MERCURIO_EX01")) == "EX01"


def test_2_procedure_identity_131_verified_from_evidence():
    from tools.mercurio_lab.ex01.contract import EX01_SUPUESTOS
    assert {"id": "EX-01-2-02", "value": "131", "enabled": True} in EX01_SUPUESTOS
    state = (REPO / "docs" / "ai" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "datosForAut=131\n= Renovación · Familiar" in state
    assert runner.EX01_RENOVACION_FAMILIAR_DATOS_FOR_AUT == "131"
    # 131 is never accepted as Titular 130 (node A gate stays bound).
    assert runner.EX01_RENOVACION_TITULAR_IDENTITY["datos_for_aut"] == "130"


# REUSE QUALITY · DUPLICATED_EX01_FULL_FLOW=NO ------------------------------

def test_no_second_ex01_flow_exists():
    assert not list((REPO / "app").glob("*familiar*.py"))
    assert sorted(n for n, f in inspect.getmembers(runner, inspect.isfunction)
                  if f.__module__ == runner.__name__ and "familiar" in n.lower()) == [
        "click_continuar_extranjero_to_familiar", "click_continuar_familiar_to_presentador",
        "fill_datos_familiar_ex01", "select_municipio_localidad_familiar_ex01",
    ]
    source = inspect.getsource(runner.run_auto)
    for shared in ("fill_datos_extranjero(", "fill_datos_presentador(", "click_continuar_presentador(",
                   "pause_humana_final_presentacion(", "click_continuar_extranjero_to_familiar(",
                   "fill_datos_familiar_ex01(", "click_continuar_familiar_to_presentador(",
                   "_ex01_family_cascade_divergence("):
        assert source.count(shared) == 1, shared
    # The family stage is the shared fill engine plus its own cascade only.
    family_source = inspect.getsource(runner.fill_datos_familiar_ex01)
    assert "fill_section(browser, familiar, session_dir)" in family_source
    assert "select_municipio_localidad_familiar_ex01(" in family_source
    assert "select_municipio_localidad_reagrupante(" not in family_source


def test_3_4_familiar_rejoins_the_same_titular_flow(tmp_path):
    titular_page = FakeEx01Page(active=(PERSONAL,))
    titular = _run(tmp_path / "titular", titular_page, datos=_datos("MERCURIO_EX01"))
    page = FakeEx01Page(active=(PERSONAL,))
    familiar = _run(tmp_path / "familiar", page)

    _assert_reached_presenter(familiar, page)
    # Familiar == Titular + exactly the family stage, same functions, same order.
    family_only = {"fill_datos_familiar_ex01", "select_municipio_localidad_familiar_ex01"}
    assert [c for c in familiar.calls if c not in family_only] == [
        c for c in titular.calls if c != "click_continuar"]
    assert "click_continuar" in titular.calls and "click_continuar" not in familiar.calls
    assert familiar.calls.count("fill_datos_familiar_ex01") == 1
    assert familiar.calls.count("select_municipio_localidad_familiar_ex01") == 1
    for name in SHARED:
        assert familiar.calls.count(name) == titular.calls.count(name) == 1, name
    # Titular never touches the family surface (its click_continuar is a spy here).
    assert titular.trace == [] and titular_page.writes == []
    assert "FAMILY_CASCADE" not in titular.log


# PHASE C · COMMON FIRST STAGE ----------------------------------------------

def test_5_common_stage_then_human_transition_to_family(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    _assert_reached_presenter(run, page)
    # The common stage ran before the human CONTINUAR; no family write before it.
    assert run.calls.index("fill_datos_extranjero") < run.calls.index("fill_datos_familiar_ex01")
    assert run.writes_at["Datos del familiar"] == 0
    assert run.trace[0] == "Datos del familiar"


# PHASE D · FAMILY STAGE ------------------------------------------------------

def test_6_7_family_mapper_from_canonical_crm_relation():
    assert all(k.startswith("rea") and k.removesuffix("_text").endswith("Reagrupante")
               for k in FAMILY_BLOCK)
    # Values come from the selected CRM contact, not from the client.
    assert FAMILY_BLOCK["reaNombreReagrupante"] == "KARIM"
    assert FAMILY_BLOCK["reaDocumentoReagrupante"] == "Y0000000Z"
    assert FAMILY_BLOCK["reaParentescoReagrupante"] == "CO"
    assert FAMILY_BLOCK[PROVINCE] == "33" and FAMILY_BLOCK[TOWN + "_text"] == "OVIEDO"
    # Legal family fields are kept (emitted empty, never dropped without evidence).
    for field in ("reaNombreRepresentanteReagrupante", "reaTipodocumentoRepresentanteReagrupante",
                  "reaNieRepresentanteReagrupante", "reaTituloRepresentanteReagrupante"):
        assert field in FAMILY_BLOCK


def test_7_8_family_fields_written_once_and_empty_never_written(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    _assert_reached_presenter(run, page)
    counts = Counter(f for f in page.writes if f.startswith("rea") and f not in FAMILY_CASCADE)
    assert set(counts) == FAMILY_WRITTEN
    assert all(n == 1 for n in counts.values()), counts
    assert not FAMILY_EMPTY & set(page.writes)
    for field in ("reaNombreReagrupante", "reaApellido1Reagrupante", "reaDocumentoReagrupante",
                  "reaFechaNacimientoReagrupante", "reaCodigoPostalReagrupante",
                  "reaTipoDocumentoReagrupante", "reaSexoReagrupante", "reaParentescoReagrupante"):
        assert page.values[field] == FAMILY_BLOCK[field], field
    # Every family write was postcondition-verified on the family surface.
    for field in FAMILY_WRITTEN:
        assert (f"governed_write field={field} " in run.log
                and f"field={field} kind=" in run.log), field
    assert "FUNCTIONAL_STATE_UNKNOWN" not in run.log and "DENIED" not in run.log


def test_9_to_13_family_cascade_selected_once_in_order(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    _assert_reached_presenter(run, page)
    assert [page.values[f] for f in FAMILY_CASCADE] == ["33", "044", "0001"]
    assert [f for f in run.family_writes if f in FAMILY_CASCADE] == list(FAMILY_CASCADE)
    assert all(page.writes.count(f) == 1 for f in FAMILY_CASCADE)
    assert run.calls.count("select_municipio_localidad_familiar_ex01") == 1
    assert f"FAMILY_CASCADE_STABLE attempt=1 settled=True fields={list(FAMILY_CASCADE)}" in run.log
    # Dependent options only became available after their parent was selected.
    assert (TOWN, True) in page.readiness_checks and (LOCALITY, True) in page.readiness_checks


def test_14_genuine_required_family_mismatch_fails_closed(tmp_path):
    field = "reaNombreReagrupante"
    page = FakeEx01Page(active=(PERSONAL,), ignore_writes={field})
    run = _run(tmp_path, page)
    _assert_blocked_before_presenter(run, page)
    assert run.trace == ["Datos del familiar"]
    assert run.result["detail"]["blocked_field"] == field
    assert f"governed_write_postcondition field={field} kind=INPUT_VALUE verified=False" in run.log
    assert not set(FAMILY_CASCADE) & set(page.writes)


def test_14b_required_family_control_absent_on_active_surface_fails_closed(tmp_path):
    field = "reaDocumentoReagrupante"
    page = FakeEx01Page(active=(PERSONAL,), absent={field})
    run = _run(tmp_path, page)
    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_field"] == field
    assert field not in page.writes


def test_14c_unmatched_required_family_select_never_reaches_presenter(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,),
                        options={"reaParentescoReagrupante": [("", "--"), ("AS", "ASCENDIENTE")]})
    run = _run(tmp_path, page)
    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_field"] == "reaParentescoReagrupante"
    assert "reaParentescoReagrupante" not in page.values


def test_15c_family_without_canonical_relation_is_not_fabricated(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page, datos=_datos(familiar={}))
    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_outcome"] == "FAMILY_BLOCK_EMPTY"
    assert not any(f.startswith("rea") for f in page.writes)


@pytest.mark.parametrize("contact,reason", [
    (None, "FAMILY_RELATION_MISSING"),
    ({**APPLICANT, "parentesco": "CONYUGE"}, "FAMILY_RELATION_IS_APPLICANT"),
], ids=["no_crm_contact", "crm_contact_is_the_applicant"])
def test_15d_mapper_fallback_to_the_applicant_is_never_a_family_member(tmp_path, contact, reason):
    # REAL mapper: without a selected CRM contact it falls back to the client.
    family = _familiar_block(contact=contact, cliente=APPLICANT)
    assert family["reaDocumentoReagrupante"] == APPLICANT["nie"]
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page, datos=_datos(familiar=family))
    _assert_blocked_before_presenter(run, page)
    assert run.result["detail"]["blocked_outcome"] == reason
    assert f"FAMILY_RELATION_BLOCKED reason={reason}" in run.log
    assert not any(f.startswith("rea") for f in page.writes)


# FAMILY SURFACE: LIVE, SOLE ACTIVE PANEL -----------------------------------

@pytest.mark.parametrize("panels", [
    (PERSONAL,),                    # human never pressed CONTINUAR (rea* nodes exist)
    (FAMILIAR, PRESENTER),          # ambiguous active panels
    (),                             # no active panel
], ids=["inactive", "ambiguous", "none"])
def test_family_surface_requires_the_sole_active_family_panel(tmp_path, panels):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page, human={"Datos del familiar": panels})
    assert run.result["ok"] is False
    assert run.result["label"] == "CONTINUE_TO_FAMILY_MEMBER_NOT_CONFIRMED"
    assert run.result["detail"]["mode"] == "human_navigation_timeout"
    assert "fill_datos_familiar_ex01" not in run.calls
    assert not any(f.startswith("rea") for f in page.writes)
    assert "fill_datos_presentador" not in run.calls


def test_family_fill_rereads_the_surface_live_before_writing(tmp_path):
    # The transition was confirmed earlier, but the panel changed since.
    page = FakeEx01Page(active=(PERSONAL,))
    result = runner.fill_datos_familiar_ex01(page, _datos(), str(tmp_path))
    assert result == {"ok": False, "blocked_field": None,
                      "blocked_outcome": "FAMILY_SURFACE_NOT_ACTIVE"}
    assert page.writes == []
    assert "FAMILY_SURFACE_NOT_ACTIVE outcome=BLOCKED" in _log_text(tmp_path)


def test_presenter_transition_requires_the_presenter_panel(tmp_path):
    # preNombrePresentador exists from the start in the single-page DOM.
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page, human={"Datos del presentador": (FAMILIAR,)})
    assert run.result["label"] == "CONTINUE_TO_PRESENTER_NOT_CONFIRMED"
    assert run.trace == FULL_TRACE
    assert "fill_datos_presentador" not in run.calls
    assert "FAMILY_CASCADE_POST_CONTINUE_VERIFIED" not in run.log


def test_family_transitions_have_no_enter_fallback_without_qcc(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    for name in ("click_continuar_extranjero_to_familiar", "click_continuar_familiar_to_presentador"):
        # No QCC channel: the plain bounded wait times out (REAL: 300 s).
        with patch.object(runner, "wait_for_js", side_effect=TimeoutError("synthetic")):
            result = getattr(runner, name)(page, str(tmp_path))
        assert result["ok"] is False and result["mode"] == "human_navigation_timeout", name
    assert "Fallback ENTER" not in _log_text(tmp_path)


# PHASE E · REJOIN SHARED PRESENTER --------------------------------------------

def test_16_family_reaches_shared_presenter_after_post_continue_reverification(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    _assert_reached_presenter(run, page)
    log = run.log
    assert (log.index("FAMILY_CASCADE_STABLE") < log.index("Espera humana asistida iniciada: Datos del presentador")
            < log.index("FAMILY_CASCADE_POST_CONTINUE_VERIFIED"))
    after_presenter = page.writes[run.writes_at["Datos del presentador"]:]
    assert not any(f.startswith("rea") for f in after_presenter)


# PHASE F/G · ABORT DURING EVERY FAMILY WAIT -----------------------------------

@pytest.mark.parametrize("abort_at,step", [
    ("Datos del familiar", "CONTINUE_TO_FAMILY_MEMBER"),
    ("Datos del presentador", "CONTINUE_TO_PRESENTER"),
])
def test_30_abort_is_governed_during_every_family_wait(tmp_path, abort_at, step):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page, abort_at=abort_at)
    assert runner._is_qcc_aborted_result(run.result)
    assert run.result["browser_closed"] is True and run.closes == [1]
    assert "fill_datos_presentador" not in run.calls
    if abort_at == "Datos del familiar":
        assert not any(f.startswith("rea") for f in page.writes)
        assert "FAMILY_CASCADE_START" not in run.log


def test_30b_abort_during_family_cascade_wait_stops_before_municipality(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    client = FakeActionClient()
    page.after_write[PROVINCE] = lambda _p: client.actions.append(dict(ABORT))
    run = _run(tmp_path, page, client=client)
    assert runner._is_qcc_aborted_result(run.result) and run.closes == [1]
    assert PROVINCE in page.writes
    assert TOWN not in page.writes and LOCALITY not in page.writes
    assert run.trace == ["Datos del familiar"]
    assert "fill_datos_presentador" not in run.calls


# QCC_EX01_FAMILIAR_VINCULO_V1 · REAL FIRST FORM ----------------------------
# The observed REAL ext* inventory (twin _EX01_OBSERVED_*_CLASSES,
# REPRESENTANTE LEGAL contract: Nombre / DNI-NIE-PAS / Numero / Titulo) has
# no extVinculoRepresentante: the mapper emitted a stale alias of
# extTituloRepresentante.

VINCULO = "extVinculoRepresentante"
EXT_REPRESENTATIVE = (
    "extNombreRepresentante", "extTipodocumentoRepresentante",
    "extNieRepresentante", "extTituloRepresentante",
)
REP_SNAPSHOT = {"datos_especificos": {
    "solicitante_representante_legal_nombre": "TUTOR EJEMPLO",
    "solicitante_representante_legal_tipo_documento": "TU",
    "solicitante_representante_legal_documento": "Y1111111H",
    "solicitante_representante_legal_titulo": "PADRE",
}}


def _ext_representative():
    with patch.object(mapper_service, "_get_cliente_contacto", lambda cid: None):
        return mapper_service.build_representante_legal_extranjero(snapshot=REP_SNAPSHOT)


def _first_form_page():
    """Only the observed REAL representative controls exist (no VINCULO)."""
    page = FakeEx01Page(active=(PERSONAL,), options={
        "extTipodocumentoRepresentante": [("", "--"), ("TU", "NIE")]})
    page.panels.update({f: PERSONAL for f in EXT_REPRESENTATIVE})
    page.selects.add("extTipodocumentoRepresentante")
    assert not page.exists(VINCULO)
    return page


def test_vinculo_is_not_an_observed_ex01_control():
    from tools.mercurio_lab.ex01 import pages
    observed = set(pages._EX01_OBSERVED_TEXT_CLASSES) | set(pages._EX01_OBSERVED_SELECT_CLASSES)
    assert set(EXT_REPRESENTATIVE) <= observed and VINCULO not in observed
    # The mapper emits exactly the observed representative controls.
    representative = _ext_representative()
    assert set(representative) == set(EXT_REPRESENTATIVE)
    assert representative["extTituloRepresentante"] == "PADRE"
    # Titular never emits the representative block.
    source = inspect.getsource(mapper_service.build_datos_mercurio)
    assert "if is_ex01_familiar:\n" in source
    assert "extranjero.update(build_representante_legal_extranjero(" in source


@pytest.mark.parametrize("stale", [False, True], ids=["mapper", "stale_persisted_payload"])
def test_first_form_representative_is_written_and_stale_vinculo_never_resolved(tmp_path, stale):
    representative = _ext_representative()
    if stale:  # datos_mercurio.json generated before the fix still carries the alias
        representative[VINCULO] = representative["extTituloRepresentante"]
    page = _first_form_page()
    result = runner.fill_section(page, representative, str(tmp_path))
    log = _log_text(tmp_path)

    assert result == {"ok": True, "blocked_field": None, "blocked_outcome": None}
    assert [f for f in page.writes if f.startswith("ext")] == list(EXT_REPRESENTATIVE)
    for field in EXT_REPRESENTATIVE:
        assert page.values[field] == representative[field]
    assert VINCULO not in page.writes and f"field={VINCULO}" not in log
    assert (f"NON_DOM_MAPPER_METADATA_SKIPPED key={VINCULO}" in log) is stale
    assert "PADRE" not in log and "TUTOR EJEMPLO" not in log and "Y1111111H" not in log


def test_genuine_representative_control_absent_on_first_form_still_fails_closed(tmp_path):
    field = "extTituloRepresentante"
    page = _first_form_page()
    page.absent.add(field)
    result = runner.fill_section(page, _ext_representative(), str(tmp_path))
    assert result["ok"] is False and result["blocked_field"] == field
    assert field not in page.writes


# PROTECTION · EX02 / HUMAN_ONLY / PII ----------------------------------------

def test_ex02_reagrupante_cascade_keeps_its_own_unchanged_helper():
    ex02 = inspect.getsource(runner.fill_datos_reagrupante_ex02)
    assert "select_municipio_localidad_reagrupante(browser, reagrupante, session_dir)" in ex02
    assert "familiar_ex01" not in ex02
    helper = inspect.getsource(runner.select_municipio_localidad_reagrupante)
    assert "_FAMILY_CASCADE" not in helper and "_wait_family_cascade_condition" not in helper
    # EX02 never takes the EX01 family branch.
    ex02_mode = runner.get_mercurio_mapper_mode({"presentacion": {"mapper_codigo": "MERCURIO_EX02"}})
    assert ex02_mode["is_ex02"] and not ex02_mode["is_ex01_familiar"]


def test_family_logs_are_value_free(tmp_path):
    page = FakeEx01Page(active=(PERSONAL,))
    run = _run(tmp_path, page)
    _assert_reached_presenter(run, page)
    for value in PII:
        assert value not in run.log, value

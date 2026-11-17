"""QCC EX01 R6 A -- EX01_RENOVACION_TITULAR / datosForAut=130.

Proves, offline and with a SYNTHETIC single-page EX01 DOM (no browser,
no network, no real Mercurio, fictitious data only), that the runner:

  * binds EX01 Titular to the precise supuesto EX-01-2-01
    (datosForAut=130) inside gsup_28, chosen by the HUMAN;
  * never treats 131 (Familiar) as 130, and blocks on ambiguity;
  * decides the EX01 screen from the concrete active panel read live,
    never from mere ext* node presence nor from an earlier capture;
  * keeps every write/cascade under its postcondition;
  * keeps CONTINUAR/CONCLUIR HUMAN_ONLY with no ENTER fallback;
  * services PRESENTATION_ABORT fail-closed.
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import app.run_presentacion_asistida as runner
from backend.automation.site_policies.mercurio import (
    build_mercurio_interaction_policy,
)


REPO = Path(__file__).resolve().parents[2]
EX01_PATH = "/mercurio/nuevaSolicitud-EX01.html"
PERSONAL = "tab-datos_personales"
AUTHORIZATION = "tab-datos_autorizacion"
FAMILY = "tab-datos_familiar"
PRESENTER = "tab-datos_presentador"

TITULAR_130 = {"id": "EX-01-2-01", "value": "130", "group": "gsup_28"}
FAMILIAR_131 = {"id": "EX-01-2-02", "value": "131", "group": "gsup_28"}

# Fictitious identity data only.
DATOS_TITULAR = {
    "presentacion": {
        "tipo_formulario_objetivo": "EX01",
        "mapper_codigo": "MERCURIO_EX01",
    },
    "extranjero": {"extPasaporte": "ZZ0000000"},
    "domicilio_extranjero": {},
    "notificacion": {},
}


# ---------------------------------------------------------------
# Synthetic live EX01 DOM (read-only double)
# ---------------------------------------------------------------


class _Ex01LiveDom:
    """Single-page EX01 like Mercurio: every r-tabs panel and its ext*/
    pre* nodes are always in the DOM; only the active panel, the
    checked datosForAut radio and the pestFamiliar visibility change.
    Answers ONLY the runner's read-only probes; any other script is
    recorded as unexpected (a write, click or submit attempt)."""

    def __init__(self, *, active=(PERSONAL,), checked=(TITULAR_130,),
                 familiar_tab="HIDDEN", pathname=EX01_PATH):
        self.active = list(active)
        self.checked = [dict(item) for item in checked]
        self.familiar_tab = familiar_tab
        self.pathname = pathname
        self.identity_probes = 0
        self.unexpected = []

    def show(self, *, active=None, checked=None, familiar_tab=None):
        if active is not None:
            self.active = list(active)
        if checked is not None:
            self.checked = [dict(item) for item in checked]
        if familiar_tab is not None:
            self.familiar_tab = familiar_tab

    def _evidence(self):
        sel = self.checked[0] if len(self.checked) == 1 else None
        return {
            "pathname": self.pathname,
            "active_panels": list(self.active),
            "checked_count": len(self.checked),
            "datos_for_aut": sel["value"] if sel else None,
            "supuesto_id": sel["id"] if sel else None,
            "supuesto_group": (sel.get("group") or None) if sel else None,
            "familiar_tab": self.familiar_tab,
        }

    def evaluate(self, script):
        if script.startswith(runner._EX01_TITULAR_IDENTITY_MARKER):
            self.identity_probes += 1
            return self._evidence()

        if script.startswith("return !!("):
            personal = runner._one_line_js(runner.EX01_TITULAR_PERSONAL_SURFACE_JS)
            presenter = runner._one_line_js(runner.EX01_TITULAR_PRESENTER_SURFACE_JS)
            if personal in script:
                return self.active == [PERSONAL]
            if presenter in script:
                return self.active == [PRESENTER]
            if runner.EX01_PERSONAL_CANDIDATE_DETECTED_JS in script:
                # Presence-only legacy predicate: ext* nodes always exist.
                return True

        self.unexpected.append(script[:120])
        return None


class FakeActionClient:
    def __init__(self, actions):
        self.actions = list(actions)

    def consume_next(self):
        if not self.actions:
            return None
        return self.actions.pop(0)


ABORT = {"action_id": 7, "action": "PRESENTATION_ABORT", "payload": {}}


@pytest.fixture
def no_console(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_k: pytest.fail("ENTER fallback used"),
    )


@pytest.fixture
def bounded_waits(monkeypatch):
    original = runner.wait_for_human_navigation

    def _bounded(*args, **kwargs):
        kwargs["timeout"] = 0.3
        kwargs["interval"] = 0.02
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "wait_for_human_navigation", _bounded)


def _log_text(session_dir):
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in Path(session_dir).rglob("*")
        if p.is_file()
    )


def _pause(browser, tmp_path, action_client=None, abort_handler=None):
    return runner.pause_supuesto(
        browser,
        str(tmp_path),
        tipo_formulario_objetivo="EX01",
        datos_mercurio=DATOS_TITULAR,
        action_client=action_client,
        abort_handler=abort_handler,
    )


# ---------------------------------------------------------------
# 1. Identity 130 + gsup_28 (source of truth)
# ---------------------------------------------------------------


def test_identity_130_gsup_28_matches_repository_sources_of_truth():
    from tools.mercurio_lab.ex01.contract import EX01_SUPUESTOS

    identity = runner.EX01_RENOVACION_TITULAR_IDENTITY
    assert identity == {
        "procedure": "EX01_RENOVACION_TITULAR",
        "tipo_formulario_objetivo": "EX01",
        "mapper_codigo": "MERCURIO_EX01",
        "supuesto_id": "EX-01-2-01",
        "datos_for_aut": "130",
        "supuesto_group": "gsup_28",
    }
    assert {"id": "EX-01-2-01", "value": "130", "enabled": True} in EX01_SUPUESTOS
    assert {"id": "EX-01-2-02", "value": "131", "enabled": True} in EX01_SUPUESTOS

    state = (REPO / "docs" / "ai" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "datosForAut=130\n= EX01_RENOVACION_TITULAR" in state

    titular = runner.get_mercurio_mapper_mode(DATOS_TITULAR)
    assert titular["is_ex01"] and not titular["is_ex01_familiar"]
    assert runner.get_tipo_formulario_objetivo(DATOS_TITULAR) == "EX01"


def test_pause_supuesto_accepts_live_130_in_gsup_28_without_writing(
    tmp_path, no_console, bounded_waits
):
    browser = _Ex01LiveDom()

    result = _pause(browser, tmp_path, action_client=FakeActionClient([]))

    assert result["ok"] is True
    assert result["mode"] == "human_dom_detected"
    assert browser.identity_probes == 1
    assert browser.unexpected == []

    log = _log_text(tmp_path)
    assert "EX01_TITULAR_IDENTITY phase=PROCEDURE_SELECTION status=MATCH" in log
    assert "datosForAut=130 group=gsup_28" in log
    assert "EX01_CANDIDATE_DETECTED" in log
    # Value-free: the fictitious passport never reaches the log.
    assert "ZZ0000000" not in log


# ---------------------------------------------------------------
# 2. 131 is never 130; ambiguity blocks
# ---------------------------------------------------------------


def test_pause_supuesto_never_treats_131_as_130(
    tmp_path, no_console, bounded_waits
):
    browser = _Ex01LiveDom(checked=(FAMILIAR_131,), familiar_tab="VISIBLE")

    result = _pause(browser, tmp_path, action_client=FakeActionClient([]))

    assert result["ok"] is False
    assert result["status"] == runner.EX01_TITULAR_IDENTITY_MISMATCH
    assert result["reason"] == "SUPUESTO_FAMILIAR_131"
    assert browser.unexpected == []
    assert "EX01_CANDIDATE_DETECTED" not in _log_text(tmp_path)


def _evidence(**overrides):
    evidence = {
        "pathname": EX01_PATH,
        "active_panels": [PERSONAL],
        "checked_count": 1,
        "datos_for_aut": "130",
        "supuesto_id": "EX-01-2-01",
        "supuesto_group": "gsup_28",
        "familiar_tab": "HIDDEN",
    }
    evidence.update(overrides)
    return evidence


@pytest.mark.parametrize(
    "overrides, status, reason",
    [
        ({}, "MATCH", "EX01_RENOVACION_TITULAR"),
        ({"familiar_tab": "ABSENT"}, "MATCH", "EX01_RENOVACION_TITULAR"),
        ({"datos_for_aut": "131", "supuesto_id": "EX-01-2-02"},
         "MISMATCH", "SUPUESTO_FAMILIAR_131"),
        ({"datos_for_aut": "131"}, "MISMATCH", "SUPUESTO_FAMILIAR_131"),
        ({"datos_for_aut": "128"}, "MISMATCH", "SUPUESTO_NOT_130"),
        ({"supuesto_id": "EX-01-2-02"}, "MISMATCH", "SUPUESTO_ID_MISMATCH"),
        ({"supuesto_group": "gsup_29"}, "MISMATCH", "SUPUESTO_GROUP_MISMATCH"),
        ({"familiar_tab": "VISIBLE"}, "MISMATCH", "FAMILIAR_CAPABILITY_VISIBLE"),
        ({"pathname": "/mercurio/nuevaSolicitud-EX02.html"},
         "MISMATCH", "NOT_EX01_FORM"),
        ({"active_panels": [FAMILY]}, "MISMATCH", "NOT_PERSONAL_SURFACE"),
        ({"active_panels": [AUTHORIZATION, PERSONAL]},
         "AMBIGUOUS", "ACTIVE_PANEL_AMBIGUOUS"),
        ({"active_panels": []}, "AMBIGUOUS", "ACTIVE_PANEL_AMBIGUOUS"),
        ({"checked_count": 0, "datos_for_aut": None},
         "AMBIGUOUS", "SUPUESTO_SELECTION_AMBIGUOUS"),
        ({"checked_count": 2}, "AMBIGUOUS", "SUPUESTO_SELECTION_AMBIGUOUS"),
        ({"supuesto_id": ""}, "AMBIGUOUS", "SUPUESTO_ID_UNOBSERVED"),
        ({"supuesto_group": None}, "AMBIGUOUS", "SUPUESTO_GROUP_UNOBSERVED"),
        ({"familiar_tab": None}, "AMBIGUOUS", "FAMILIAR_CAPABILITY_UNKNOWN"),
    ],
)
def test_identity_classification_blocks_mismatch_and_ambiguity(
    overrides, status, reason
):
    assert runner.classify_ex01_renovacion_titular_evidence(
        _evidence(**overrides)
    ) == (status, reason)


@pytest.mark.parametrize("evidence", [None, "", [], "MATCH", True])
def test_unreadable_identity_evidence_is_ambiguous(evidence):
    assert runner.classify_ex01_renovacion_titular_evidence(evidence) == (
        runner.EX01_TITULAR_IDENTITY_AMBIGUOUS,
        "EVIDENCE_UNREADABLE",
    )


def test_identity_probe_error_fails_closed(tmp_path):
    browser = Mock()
    browser.evaluate.side_effect = RuntimeError("cdp gone")
    del browser.execute_script

    result = runner._verify_ex01_renovacion_titular_identity(
        browser, str(tmp_path), phase="PROCEDURE_SELECTION"
    )

    assert result["ok"] is False
    assert result["reason"] == "EVIDENCE_UNREADABLE"
    assert "EX01_TITULAR_IDENTITY_PROBE_ERROR" in _log_text(tmp_path)


# ---------------------------------------------------------------
# 3. EX01 screen vs previous capture
# ---------------------------------------------------------------


def test_ext_nodes_on_authorization_panel_are_not_the_ex01_screen(
    tmp_path, no_console, bounded_waits
):
    # Human has picked 130 but not pressed CONTINUAR yet: ext* nodes
    # already exist (legacy presence-only predicate would accept).
    browser = _Ex01LiveDom(active=(AUTHORIZATION,))
    assert browser.evaluate(
        f"return !!({runner.EX01_PERSONAL_CANDIDATE_DETECTED_JS});"
    ) is True

    result = _pause(browser, tmp_path, action_client=FakeActionClient([]))

    assert result["ok"] is False
    assert result["mode"] == "human_navigation_timeout"
    assert browser.identity_probes == 0
    assert "EX01_CANDIDATE_DETECTED" not in _log_text(tmp_path)


def test_no_enter_fallback_for_titular_without_qcc(tmp_path, no_console, bounded_waits):
    browser = _Ex01LiveDom(active=(AUTHORIZATION,))

    result = _pause(browser, tmp_path, action_client=None)

    assert result["ok"] is False
    assert result["mode"] == "human_navigation_timeout"
    assert browser.identity_probes == 0


def _run_auto_patches(**overrides):
    ok = {"ok": True}
    defaults = {
        "step_continuar_inicial": ok,
        "pause_certificado": ok,
        "step_presentar_nueva_solicitud": ok,
        # Identity was MATCH at pause_supuesto (an earlier observation).
        "pause_supuesto": ok,
        "wait_for_qcc_fill_start": ok,
        "_wait_for_ex01_personal_readiness": ok,
        "fill_datos_extranjero": ok,
        "click_continuar": ok,
        "fill_datos_presentador": True,
        "click_continuar_presentador": ok,
        "pause_humana_final_presentacion": ok,
    }
    defaults.update(overrides)
    return [patch.object(runner, name, return_value=value)
            for name, value in defaults.items()]


def _run_auto(browser, tmp_path, patches):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = {p.attribute: stack.enter_context(p) for p in patches}
        result = runner.run_auto(
            browser, "33", DATOS_TITULAR, str(tmp_path),
            action_client=FakeActionClient([]), abort_handler=Mock(),
        )
    return result, mocks


def test_fill_start_rereads_identity_live_never_reuses_earlier_match(tmp_path):
    # After the earlier MATCH the page now shows the 131 branch.
    browser = _Ex01LiveDom(checked=(FAMILIAR_131,), familiar_tab="VISIBLE")

    result, mocks = _run_auto(browser, tmp_path, _run_auto_patches())

    assert result["ok"] is False
    assert result["phase"] == "FILL_START"
    assert result["reason"] == "SUPUESTO_FAMILIAR_131"
    assert browser.identity_probes == 1
    mocks["fill_datos_extranjero"].assert_not_called()
    mocks["click_continuar"].assert_not_called()


def test_fill_start_live_match_fills_then_waits_titular_presenter_surface(tmp_path):
    browser = _Ex01LiveDom()

    _result, mocks = _run_auto(browser, tmp_path, _run_auto_patches())

    assert browser.identity_probes == 1
    mocks["fill_datos_extranjero"].assert_called_once()
    assert mocks["click_continuar"].call_args.kwargs["ex01_titular"] is True
    assert browser.unexpected == []


# ---------------------------------------------------------------
# 4. Mandatory write postcondition (domicilio cascade)
# ---------------------------------------------------------------


DOMICILIO = {
    "extCodigoProvincia": "33",
    "extCodigoProvincia_text": "ASTURIAS",
    "extCodigoMunicipio_text": "MUNICIPIO FICTICIO",
    "extCodigoLocalidad_text": "LOCALIDAD FICTICIA",
}


@pytest.mark.parametrize(
    "failing_field, outcome",
    [
        ("extCodigoProvincia", runner.GOVERNED_OUTCOME_DENIED),
        ("extCodigoMunicipio", runner.GOVERNED_OUTCOME_FAILED),
        ("extCodigoLocalidad", runner.GOVERNED_OUTCOME_HUMAN_HANDOFF),
    ],
)
def test_cascade_stops_on_first_unverified_select(tmp_path, failing_field, outcome):
    attempted = []

    def _select(_browser, field_id, **_kwargs):
        attempted.append(field_id)
        return outcome if field_id == failing_field else runner.GOVERNED_OUTCOME_OK

    with patch.object(runner, "select_by_text_or_value", side_effect=_select), \
         patch.object(runner, "field_exists", return_value=True), \
         patch.object(runner, "wait_select_options", return_value=True), \
         patch.object(runner.time, "sleep"):
        result = runner.select_municipio_localidad(
            object(), DOMICILIO, str(tmp_path), prefix="ext"
        )

    assert result == {"ok": False, "blocked_field": failing_field,
                      "blocked_outcome": outcome}
    assert attempted[-1] == failing_field
    assert "MUNICIPIO FICTICIO" not in _log_text(tmp_path)


def test_titular_fill_never_completes_after_unverified_cascade(tmp_path):
    datos = dict(DATOS_TITULAR, domicilio_extranjero=DOMICILIO)
    ok_section = {"ok": True, "blocked_field": None, "blocked_outcome": None}

    def _select(_browser, field_id, **_kwargs):
        if field_id == "extCodigoMunicipio":
            return runner.GOVERNED_OUTCOME_FAILED
        return runner.GOVERNED_OUTCOME_OK

    with patch.object(runner, "wait_for_js", return_value=True), \
         patch.object(runner, "fill_section", return_value=ok_section) as fill, \
         patch.object(runner, "select_by_text_or_value", side_effect=_select), \
         patch.object(runner, "field_exists", return_value=True), \
         patch.object(runner, "wait_select_options", return_value=True), \
         patch.object(runner.time, "sleep"):
        result = runner.fill_datos_extranjero(object(), datos, str(tmp_path))

    assert result["ok"] is False
    assert result["blocked_field"] == "extCodigoMunicipio"
    # Notification section never started after the failed cascade.
    assert fill.call_count == 2
    assert "Datos completos rellenados" not in _log_text(tmp_path)


def test_all_cascade_selects_verified_returns_ok(tmp_path):
    with patch.object(runner, "select_by_text_or_value",
                      return_value=runner.GOVERNED_OUTCOME_OK), \
         patch.object(runner, "field_exists", return_value=True), \
         patch.object(runner, "wait_select_options", return_value=True), \
         patch.object(runner.time, "sleep"):
        result = runner.select_municipio_localidad(
            object(), DOMICILIO, str(tmp_path), prefix="ext"
        )

    assert result == {"ok": True, "blocked_field": None, "blocked_outcome": None}


# ---------------------------------------------------------------
# 5. CONTINUAR / CONCLUIR HUMAN_ONLY
# ---------------------------------------------------------------


def test_titular_presenter_transition_requires_the_presenter_panel(
    tmp_path, no_console, bounded_waits
):
    # preNombrePresentador exists in the single-page DOM, but the human
    # has not pressed CONTINUAR: still on Datos del extranjero/a.
    browser = _Ex01LiveDom(active=(PERSONAL,))

    result = runner.click_continuar(
        browser, str(tmp_path), action_client=FakeActionClient([]),
        abort_handler=Mock(), ex01_titular=True,
    )
    assert result["ok"] is False
    assert result["mode"] == "human_navigation_timeout"

    browser.show(active=(PRESENTER,))
    result = runner.click_continuar(
        browser, str(tmp_path), action_client=FakeActionClient([]),
        abort_handler=Mock(), ex01_titular=True,
    )
    assert result["ok"] is True
    assert browser.unexpected == []


def _function_source(name):
    source = (REPO / "app" / "run_presentacion_asistida.py").read_text(encoding="utf-8")
    node = next(
        n for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    return ast.get_source_segment(source, node)


@pytest.mark.parametrize(
    "name",
    [
        "pause_supuesto",
        "click_continuar",
        "_verify_ex01_renovacion_titular_identity",
        "classify_ex01_renovacion_titular_evidence",
        "_ex01_titular_identity_evidence_js",
        "_ex01_sole_active_panel_js",
    ],
)
def test_titular_paths_never_automate_continue_conclude_or_selection(name):
    block = _function_source(name)

    for forbidden in (
        "click_js(", "execute_script", "_governed_write(", ".click(",
        "send_keys(", "continuar('", "btnConcluir", "btnContinuar",
        "set_radio_checked(", ".checked =", "checked = true",
        "dispatchEvent", "submit(", "input(",
    ):
        assert forbidden not in block, (name, forbidden)


def test_identity_probe_is_read_only():
    probe = runner._ex01_titular_identity_evidence_js()

    for forbidden in (".click(", "dispatchEvent", ".value =", ".checked =",
                      "submit(", "\n", "//"):
        assert forbidden not in probe

    for predicate in (runner.EX01_TITULAR_PERSONAL_SURFACE_JS,
                      runner.EX01_TITULAR_PRESENTER_SURFACE_JS):
        assert "//" not in predicate and "\n" not in predicate


def test_mercurio_policy_keeps_buttons_and_submit_human_only():
    rules = build_mercurio_interaction_policy().action_kind_rules

    assert rules["BUTTON"] == "HUMAN_ONLY"
    assert rules["SUBMIT"] == "HUMAN_ONLY"


def test_familiar_and_ex02_paths_are_unchanged_by_titular_gate():
    # 131 keeps its own flow; the titular gate only binds MERCURIO_EX01.
    source = inspect.getsource(runner.run_auto)
    assert source.count("_verify_ex01_renovacion_titular_identity(") == 1
    assert 'if mapper_mode.get("is_ex01"):' in source
    assert "click_continuar_extranjero_to_familiar(" in source


# ---------------------------------------------------------------
# 6. Abort (fail-closed)
# ---------------------------------------------------------------


def test_abort_during_supuesto_wait_never_reads_identity(tmp_path, no_console):
    browser = _Ex01LiveDom(active=(AUTHORIZATION,))
    abort_handler = Mock(return_value=True)

    result = _pause(browser, tmp_path,
                    action_client=FakeActionClient([ABORT]),
                    abort_handler=abort_handler)

    assert result["ok"] is False
    assert result["mode"] == "aborted"
    assert result["browser_closed"] is True
    abort_handler.assert_called_once_with()
    assert browser.identity_probes == 0
    assert browser.unexpected == []


def test_abort_during_titular_presenter_transition(tmp_path, no_console):
    browser = _Ex01LiveDom(active=(PERSONAL,))
    abort_handler = Mock(return_value=False)

    result = runner.click_continuar(
        browser, str(tmp_path), action_client=FakeActionClient([ABORT]),
        abort_handler=abort_handler, ex01_titular=True,
    )

    assert result["mode"] == "aborted"
    assert result["browser_closed"] is False
    abort_handler.assert_called_once_with()


def test_run_auto_returns_identity_block_without_filling(tmp_path):
    browser = _Ex01LiveDom(checked=(), familiar_tab="HIDDEN")

    result, mocks = _run_auto(browser, tmp_path, _run_auto_patches())

    assert result["ok"] is False
    assert result["status"] == runner.EX01_TITULAR_IDENTITY_AMBIGUOUS
    mocks["fill_datos_extranjero"].assert_not_called()
    mocks["pause_humana_final_presentacion"].assert_not_called()

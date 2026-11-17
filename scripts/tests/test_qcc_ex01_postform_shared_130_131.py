"""QCC_EX01_R6_POSTFORM: one post-form continuation for EX01 130 and 131.

EX01 Titular (datosForAut=130) and Familiar (131) run the SAME VOLCAR
DATOS continuation after their own personal / family surfaces: Presenter
on its surface, Notification only once its tab is the active one, then
the HUMAN_ONLY CONCLUIR gate. Nothing is written on a hidden tab, ABORT is
serviced fail closed and a Notification surface never reached keeps the
VOLCAR incomplete.

The 131 family stage has its own suite (test_qcc_ex01_familiar_reuse);
here it is a recorded spy. Only the physical browser is faked; the real
runner, real engine and Mercurio's real policy run. Offline, fictitious
values only.
"""

import pytest

import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import (
    ALL_EX01_FIELDS, EXTRANJERO, DOMICILIO, FAMILIAR_BLOCK, NOTIFICACION,
    NOTIFICATION_IDENTITY, PRESENTER, REPRESENTANTE, _DESTINATION_PANELS, _FakeActionClient,
    _TabbedMercurioBrowser, _datos, _log_text, _run_full_mapper,
)


TO_PRESENTER = "Datos del presentador"
TO_NOTIFICATION = "Domicilio de notificación / CONCLUIR"
MODES = ["MERCURIO_EX01", "MERCURIO_EX01_FAMILIAR"]


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)
    monkeypatch.setattr(runner.time, "sleep", lambda *a: pytest.fail("No arbitrary sleeps"))


def _run(tmp_path, mode, *, lands_on=None, client=None, abort_on=None):
    """REAL ``run_auto``; ``lands_on`` = panel each human CONTINUAR shows."""

    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS + list(FAMILIAR_BLOCK))
    client = client or _FakeActionClient()
    writes_at, family_calls = {}, []
    panels = {**_DESTINATION_PANELS, **(lands_on or {})}

    def human(browser_arg, session_dir, label, ready_js, **kwargs):
        writes_at[label] = len(browser.writes)
        browser.form.active_panel = panels[label]
        if label == abort_on:
            client.actions.append({"action_id": 5, "action": "PRESENTATION_ABORT"})
        return {"ok": True, "mode": "human_dom_detected", "label": label}

    def family_stage(browser_arg, datos, session_dir, **kwargs):
        family_calls.append(list(browser.writes))
        return {"ok": True, "family_cascade": {}}

    extra = {"wait_for_human_navigation": human}
    datos = _datos(mode)
    if mode.endswith("FAMILIAR"):
        datos["familiar"] = dict(FAMILIAR_BLOCK)
        extra.update(fill_datos_familiar_ex01=family_stage,
                     _ex01_family_relation_problem=lambda *a, **k: None)
    result, trace, _ = _run_full_mapper(tmp_path, browser, datos, action_client=client, extra=extra)
    return browser, result, trace, writes_at, family_calls, _log_text(str(tmp_path))


@pytest.mark.parametrize("mode", MODES)
def test_same_postform_continuation_for_130_and_131(tmp_path, fast, mode):
    browser, result, trace, writes_at, family_calls, log = _run(tmp_path, mode)

    assert result is None or result.get("ok") is not False, result
    assert trace == ["FINAL_HUMAN_CONCLUIR"]
    personal = set(EXTRANJERO) | set(DOMICILIO)
    # Before the human reaches the presenter: only Datos del extranjero/a.
    assert set(browser.writes[:writes_at[TO_PRESENTER]]) == personal
    if family_calls:
        assert set(family_calls[0]) == personal
    # Presenter only on its own surface, Notification only on its own.
    presenter = browser.writes[writes_at[TO_PRESENTER]:writes_at[TO_NOTIFICATION]]
    notification = browser.writes[writes_at[TO_NOTIFICATION]:]
    assert presenter == list(REPRESENTANTE)
    assert notification == [f for f in NOTIFICACION if f not in NOTIFICATION_IDENTITY]
    # Certificate-held Notification identity is verified, never written.
    for field in NOTIFICATION_IDENTITY:
        assert f"CERTIFICATE_IDENTITY_VERIFIED field={field} source=PRESENTER_CERTIFICATE" in log
    assert "MAPPER_FILL_COMPLETED" in log
    assert "MAPPER_SECTION_BLOCKED" not in log and "outcome=DENIED" not in log
    for script in browser.action_scripts:  # CONTINUAR / CONCLUIR never automated
        assert ".click()" not in script and "btnConcluirSup" not in script


def test_130_and_131_write_the_identical_postform_sequence(tmp_path, fast):
    runs = {mode: _run(tmp_path / mode, mode) for mode in MODES}
    tails = {mode: run[0].writes[run[3][TO_PRESENTER]:] for mode, run in runs.items()}
    assert tails["MERCURIO_EX01"] == tails["MERCURIO_EX01_FAMILIAR"]
    assert runs["MERCURIO_EX01_FAMILIAR"][4]  # the 131 family stage ran
    assert not runs["MERCURIO_EX01"][4]


@pytest.mark.parametrize("mode", MODES)
def test_notification_surface_never_reached_never_reaches_concluir(tmp_path, fast, mode):
    # The CONTINUAR from the presenter was detected, but Notification is
    # not the active surface (e.g. still on the presenter tab).
    browser, result, trace, writes_at, _, log = _run(
        tmp_path, mode, lands_on={TO_NOTIFICATION: PRESENTER})

    assert result["ok"] is False and result["label"] == "MAPPER_FIELDS_DEFERRED"
    assert "FINAL_HUMAN_CONCLUIR" not in trace
    assert not [f for f in browser.writes if f.startswith("not")]
    assert "NOTIFICATION_SURFACE_NOT_ACTIVE writes=NO" in log
    assert "MAPPER_FILL_COMPLETED" not in log


@pytest.mark.parametrize("mode", MODES)
def test_abort_on_notification_surface_is_fail_closed(tmp_path, fast, mode):
    browser, result, trace, writes_at, _, log = _run(tmp_path, mode, abort_on=TO_NOTIFICATION)

    assert runner._is_qcc_aborted_result(result)
    assert browser.writes[writes_at[TO_NOTIFICATION]:] == []
    assert "FINAL_HUMAN_CONCLUIR" not in trace
    assert "MAPPER_FILL_COMPLETED" not in log
    assert "MAPPER_SECTION_BLOCKED" not in log  # an abort is never a block

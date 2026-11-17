"""QCC_NOTIFICATION_FINAL_GATE_V1 regressions.

REAL evidence: the preload wrote the Notification identity while its tab was
hidden (POSTCONDITION_VERIFIED). After the human CONTINUAR Mercurio locked the
block (``readonly`` + ``disableLnk``, same lock as the presenter certificate
identity) and re-hydrated it: the read-only revalidation failed
(INPUT_VALUE_MISMATCH), the rewrite hit ``initial_state=READONLY`` ->
INTERACTION_POLICY_DENY -> NOTIFICACION_BLOCKED -> AUTO_FLOW_BLOCKED (whose
generic progress=50 was only downstream evidence). The Notification address
controls were DEFERRED_NOT_PRESENT and no local capture ever rendered them.

QCC_NOTIFICATION_CERTIFICATE_AUTHORITY_V1: the Notification identity is
Mercurio-managed from the authenticated certificate. It is never written and
never compared with the client mapper identity; the verified Presenter
identity is its only reference.

QCC_EX01_R6_POSTFORM: Notification is deferred until its tab is the
active surface -- nothing of it is written, read nor compared while it is
hidden (the hidden-tab preload write above is the REAL defect). Scenarios
that relied on that write now reach the surface by human navigation.

Only the physical browser is faked; the real runner, real engine and
Mercurio's real policy run. All identity values are fictitious.
"""
from unittest.mock import Mock, patch

import pytest
import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import NOTIFICATION, PERSONAL, PRESENTER, _log_text
from test_qcc_preloaded_full_mapper import mapper
from qcc_presenter_preload_doubles import (
    _browser, _presenter_datos, FIELDS, SELECTS, IDENTITY, NAME, DOC_TYPE, DOC,
)


NOT_NAME, NOT_DOC_TYPE, NOT_DOC = "notNombreNotificacion", "notTipodocumentoNotificacion", "notNieNotificacion"
NOT_EMAIL, NOT_MOBILE = "notEmailNotificacion", "notTelefonoMovilNotificacion"
NOT_IDENTITY = (NOT_NAME, NOT_DOC_TYPE, NOT_DOC)
NOT_CONTACT = (NOT_EMAIL, NOT_MOBILE)
NOTIFICATION_FIELDS = NOT_IDENTITY + NOT_CONTACT
ADDRESS = (
    "notDomicilioNotificacion", "notTipoViaNotificacion", "notNumeroNotificacion",
    "notPisoNotificacion", "notCodigoPostalNotificacion", "notCodigoProvinciaNotificacion",
    "notCodigoMunicipioNotificacion", "notCodigoLocalidadNotificacion",
)
MAPPER_NAME = "AMINA BENALI SAIDI"           # client mapper identity, never a reference
NOTIFICACION = {
    NOT_NAME: MAPPER_NAME, NOT_DOC_TYPE: "TU", NOT_DOC: "Y0000000Z",
    NOT_MOBILE: "600000000", NOT_EMAIL: "n@example.invalid",
    "notDomicilioNotificacion": "URIA", "notTipoViaNotificacion": "CL",
    "notTipoViaNotificacion_text": "CALLE", "notNumeroNotificacion": "1",
    "notPisoNotificacion": "BJ", "notCodigoPostalNotificacion": "33001",
    "notCodigoProvinciaNotificacion": "33", "notCodigoProvinciaNotificacion_text": "ASTURIAS",
    "notCodigoMunicipioNotificacion_text": "OVIEDO", "notCodigoLocalidadNotificacion_text": "OVIEDO",
    "ruta_box_notificacion": "private/box/path",
}
ALL_FIELDS = [f for f in FIELDS if not f.startswith("not")] + list(NOTIFICATION_FIELDS)
ALL_SELECTS = SELECTS + [NOT_DOC_TYPE]


def _datos(**notification):
    datos = _presenter_datos(ruta_box_dni_representante="private/box/path")
    datos["notificacion"] = {**NOTIFICACION, **notification}
    return datos


def _mercurio(*, fields=ALL_FIELDS, absent=ADDRESS, **kwargs):
    """Presenter certificate identity held readonly, Notification writable
    until Mercurio locks it, address controls not on this surface."""
    browser = _browser(readonly={NAME, DOC}, pointer_none={DOC_TYPE}, certificate=IDENTITY,
                       fields=fields, selects=ALL_SELECTS, absent=set(absent), **kwargs)
    browser.writes_before_lock = None
    return browser


def _lock_notification(browser, **live):
    """What Mercurio does on the human CONTINUAR to Notification: the whole
    block is locked (readonly / pointer-events none) and re-hydrated."""
    browser.form.active_panel = NOTIFICATION
    browser.readonly |= {NOT_NAME, NOT_DOC, NOT_EMAIL, NOT_MOBILE}
    browser.pointer_none |= {NOT_DOC_TYPE}
    browser.form.values.update(live)
    browser.form.selects |= set(live) & set(ALL_SELECTS)
    browser.writes_before_lock = list(browser.writes)


def _new_writes(browser):
    return browser.writes[len(browser.writes_before_lock):]


def _to_notification(state, browser, **live):
    """Preload (personal) -> human CONTINUAR -> presenter -> human CONTINUAR."""
    assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
    browser.form.active_panel = PRESENTER
    assert state.resume(("representante",))["ok"]
    _lock_notification(browser, **live)
    events_before = list(browser.form.events)
    result = state.resume(("notificacion",))
    return result, browser.form.events[len(events_before):]


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)
    monkeypatch.setattr(runner.time, "sleep", lambda *a: pytest.fail("No arbitrary sleeps"))


# PHASE B · NOTIFICATION CERTIFICATE IDENTITY ---------------------------

# QCC_NOTIFICATION_CERTIFICATE_AUTHORITY_V1: the Notification identity is
# Mercurio-managed from the authenticated certificate. Its only reference is
# the verified Presenter identity (IDENTITY); the client mapper identity
# (NOTIFICACION) is never written nor compared.

PRESENTER_REORDERED = "EJEMPLO LETRADO"     # same certificate tokens


def _identity_writes(browser):
    return [f for f in browser.writes if f in NOT_IDENTITY]


def test_preload_never_writes_writable_hidden_notification_identity(tmp_path, fast):
    # QCC_EX01_R6_POSTFORM: the hidden Notification tab is neither written
    # nor read during the preload (contacts included); its identity is
    # verified against the Presenter only on its own active surface.
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        assert not [f for f in browser.writes if f.startswith("not")]
        assert set(NOTIFICATION_FIELDS) <= set(state.deferred)
        assert "source=PRESENTER_CERTIFICATE" not in _log_text(str(tmp_path))
        result, events = _to_notification(state, browser, **{NOT_NAME: PRESENTER_REORDERED})
        assert result["ok"] and events == []
    assert _identity_writes(browser) == []
    log = _log_text(str(tmp_path))
    for field in NOT_IDENTITY:
        assert f"CERTIFICATE_IDENTITY_VERIFIED field={field} source=PRESENTER_CERTIFICATE" in log


def test_hidden_identity_not_yet_hydrated_is_deferred_never_written(tmp_path, fast):
    browser = _mercurio()
    browser.form.values.update({NOT_NAME: "", NOT_DOC: ""})  # Mercurio not hydrated yet
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        assert {NOT_NAME, NOT_DOC} <= set(state.deferred)
        result, events = _to_notification(
            state, browser, **{NOT_NAME: PRESENTER_REORDERED, NOT_DOC: IDENTITY[DOC]})
        assert result["ok"] and state.resume(())["ok"]
    assert _identity_writes(browser) == [] and events == []
    assert not set(NOT_IDENTITY) & set(state.deferred)


@pytest.mark.parametrize("live", [PRESENTER_REORDERED, "letrado,  ejémplo", IDENTITY[NAME]])
def test_1_notification_name_matching_presenter_is_verified_without_write(tmp_path, fast, live):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, events = _to_notification(state, browser, **{NOT_NAME: live})
        assert result["ok"]
        assert state.resume(())["ok"]  # never retried
    assert _identity_writes(browser) == [] and _new_writes(browser) == [] and events == []
    assert NOT_NAME in state.verified and NOT_NAME not in state.deferred
    log = _log_text(str(tmp_path))
    assert "DENIED" not in log and "NOTIFICACION_BLOCKED" not in log
    assert "LETRADO" not in log and "BENALI" not in log  # value-free


def test_1b_client_mapper_name_is_never_the_reference(tmp_path, fast):
    # Live == client mapper identity, but it differs from the certificate.
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **{NOT_NAME: MAPPER_NAME})
    assert result == {"ok": False, "label": "NOTIFICACION_BLOCKED", "blocked_field": NOT_NAME,
                      "blocked_outcome": "CERTIFICATE_IDENTITY_MISMATCH"}
    assert _identity_writes(browser) == []


def test_1c_client_mapper_identity_values_are_irrelevant(tmp_path, fast):
    browser = _mercurio()
    datos = _datos(**{NOT_NAME: "OTRA PERSONA", NOT_DOC_TYPE: "PA", NOT_DOC: "Z9999999Z"})
    with mapper(browser, datos, tmp_path) as state:
        result, _ = _to_notification(state, browser, **{NOT_NAME: PRESENTER_REORDERED})
        assert result["ok"] and state.resume(())["ok"]
    assert _identity_writes(browser) == []
    assert set(NOT_IDENTITY) <= set(state.verified)


@pytest.mark.parametrize("live", [
    "PEDRO LOPEZ RUIZ",              # another identity
    "LETRADO",                       # missing token
    "LETRADO LETRADO EJEMPLO",       # multiplicity preserved
])
def test_2_true_notification_name_mismatch_fails_closed(tmp_path, fast, live):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **{NOT_NAME: live})
    assert result == {"ok": False, "label": "NOTIFICACION_BLOCKED", "blocked_field": NOT_NAME,
                      "blocked_outcome": "CERTIFICATE_IDENTITY_MISMATCH"}
    assert NOT_NAME not in state.verified
    assert _new_writes(browser) == [] and _identity_writes(browser) == []
    log = _log_text(str(tmp_path))
    assert f"CERTIFICATE_IDENTITY_MISMATCH field={NOT_NAME} source=PRESENTER_CERTIFICATE" in log


@pytest.mark.parametrize("live", ["X0000000T", "x-0000000 t"])
def test_3_notification_nie_matching_presenter_is_verified_without_write(tmp_path, fast, live):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, events = _to_notification(state, browser, **{NOT_DOC: live})
    assert result["ok"]
    assert NOT_DOC in state.verified and _new_writes(browser) == [] and events == []
    assert _identity_writes(browser) == []


@pytest.mark.parametrize("live", ["Y0000000Z", "T X0000000"])  # client NIE / token order
def test_4_notification_nie_mismatch_fails_closed(tmp_path, fast, live):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **{NOT_DOC: live})
    assert result["ok"] is False and result["label"] == "NOTIFICACION_BLOCKED"
    assert result["blocked_field"] == NOT_DOC
    assert result["blocked_outcome"] == "CERTIFICATE_IDENTITY_MISMATCH"
    assert _new_writes(browser) == [] and _identity_writes(browser) == []


def test_5_notification_doc_type_matching_presenter_is_verified_without_write(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, events = _to_notification(state, browser, **{NOT_DOC_TYPE: IDENTITY[DOC_TYPE]})
    assert result["ok"] and NOT_DOC_TYPE in state.verified
    assert _identity_writes(browser) == [] and events == []


def test_5b_doc_type_mismatch_fails_closed(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        # "TU" is the client mapper value: still a true presenter mismatch.
        result, _ = _to_notification(state, browser, **{NOT_DOC_TYPE: "TU"})
    assert result["blocked_field"] == NOT_DOC_TYPE
    assert result["blocked_outcome"] == "CERTIFICATE_IDENTITY_MISMATCH"
    assert _new_writes(browser) == [] and _identity_writes(browser) == []


def test_unverified_presenter_is_never_a_reference(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        # Live values are equal, but the Presenter was never verified.
        state.required_blocks.add("notificacion")
        assert state._notification_identity(NOT_NAME, "notificacion") == "CERTIFICATE_IDENTITY_MISMATCH"
        state.required_blocks.discard("notificacion")
        assert state._notification_identity(NOT_NAME, "notificacion") == "DEFERRED_DEPENDENCY"
    assert NOT_NAME not in state.verified and _identity_writes(browser) == []


def test_presenter_reference_comparator_is_scoped():
    browser = _browser(fields=[NAME, DOC, DOC_TYPE, *NOT_IDENTITY], selects=[DOC_TYPE, NOT_DOC_TYPE],
                       certificate={**IDENTITY, NOT_NAME: "ejemplo letrado", NOT_DOC: "x-0000000 t",
                                    NOT_DOC_TYPE: IDENTITY[DOC_TYPE]})
    for field in NOT_IDENTITY:
        assert runner._notification_identity_matches_presenter(browser, field)
    browser.form.values.update({NOT_NAME: "", NOT_DOC: "T X0000000", NOT_DOC_TYPE: "TU"})
    for field in NOT_IDENTITY:
        assert not runner._notification_identity_matches_presenter(browser, field)


def test_identity_locked_from_page_load_is_verified_never_written(tmp_path, fast):
    # 14/31 local captures: the block is already locked before VOLCAR.
    browser = _mercurio()
    _lock_notification(browser, **{NOT_NAME: PRESENTER_REORDERED, NOT_DOC_TYPE: IDENTITY[DOC_TYPE],
                                   NOT_DOC: IDENTITY[DOC],
                                   NOT_EMAIL: "n@example.invalid", NOT_MOBILE: "600000000"})
    browser.form.active_panel = PERSONAL
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        browser.form.active_panel = PRESENTER  # human navigation
        assert state.resume(("representante",))["ok"]
        browser.form.active_panel = NOTIFICATION
        assert state.resume(("notificacion",))["ok"]
        assert state.resume(())["ok"] and not state.deferred
    assert not set(NOTIFICATION_FIELDS) & set(browser.writes)


def test_generic_notification_input_comparison_stays_order_sensitive():
    browser = _browser(fields=[NOT_EMAIL], selects=[], certificate={NOT_EMAIL: "B A"})
    assert not runner._input_value_satisfied(browser, NOT_EMAIL, "A B")
    assert set(NOTIFICATION_FIELDS).isdisjoint(runner._CERTIFICATE_IDENTITY_FIELDS)
    assert runner._CERTIFICATE_NAME_FIELDS == {NAME}
    assert set(runner._NOTIFICATION_PRESENTER_IDENTITY) == set(NOT_IDENTITY)


# PHASE C · CONTACT FIELDS ----------------------------------------------

def test_6_contact_already_correct_is_not_rewritten(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **{
            NOT_EMAIL: "N@example.invalid ", NOT_MOBILE: "600000000"})
        assert result["ok"] and state.resume(())["ok"]
    assert _new_writes(browser) == []
    assert {NOT_EMAIL, NOT_MOBILE} <= set(state.verified)


@pytest.mark.parametrize("field,live", [(NOT_EMAIL, "otro@example.invalid"), (NOT_MOBILE, "699999999")])
def test_7_editable_contact_mismatch_uses_governed_write(tmp_path, fast, field, live):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **{field: live})
        browser.readonly.discard(field)  # Mercurio re-hydrated but left it editable
        result = state.resume(("notificacion",))
    assert result["ok"]
    assert _new_writes(browser).count(field) == 1
    assert browser.form.values[field] == NOTIFICACION[field]
    log = _log_text(str(tmp_path))
    assert f"governed_write field={field} kind=INPUT_VALUE decision=EXECUTION_ALLOWED" in log


# QCC_NOTIFICATION_LOCKED_CONTACT_V1 ------------------------------------
# REAL: notTelefonoMovilNotificacion re-hydrated + READONLY on the final
# Notification surface -> INPUT_VALUE_MISMATCH -> rewrite DENIED ->
# NOTIFICACION_BLOCKED -> AUTO_FLOW_BLOCKED. Local captures: the visible
# Notification surface locks email + mobile with the identity block.

LIVE_CONTACT = {NOT_EMAIL: "rehidratado@example.invalid", NOT_MOBILE: "611111111"}


@pytest.mark.parametrize("field", NOT_CONTACT)
def test_lc1_2_hidden_editable_contact_written_only_on_active_surface(tmp_path, fast, field):
    # QCC_EX01_R6_POSTFORM: the historical hidden-tab write of the contact
    # is exactly what Mercurio re-hydrated and locked (REAL). Deferred on
    # the hidden tab; an editable contact is written on the active surface.
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        assert field not in browser.writes and field in state.deferred
        browser.form.active_panel = PRESENTER
        assert state.resume(("representante",))["ok"]
        assert field not in browser.writes
        browser.form.active_panel = NOTIFICATION  # unlocked surface
        assert state.resume(("notificacion",))["ok"]
    assert browser.writes.count(field) == 1 and field in state.verified
    assert browser.form.values[field] == NOTIFICACION[field]
    log = _log_text(str(tmp_path))
    assert runner.NOTIFICATION_CONTACT_MERCURIO_MANAGED not in log


@pytest.mark.parametrize("field", NOT_CONTACT)
def test_lc3_4_locked_final_contact_is_preserved_never_rewritten(tmp_path, fast, field):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, events = _to_notification(state, browser, **{field: LIVE_CONTACT[field]})
        assert result["ok"] and not state.deferred
        assert state.resume(("notificacion",))["ok"] and state.resume(())["ok"]  # never retried
    assert _new_writes(browser) == [] and events == []
    assert browser.form.values[field] == LIVE_CONTACT[field]  # live Mercurio value preserved
    assert field in state.verified
    log = _log_text(str(tmp_path))
    assert log.count(f"NOTIFICATION_CONTACT_MERCURIO_MANAGED field={field} outcome=PRESERVED_LIVE") == 1
    assert "DENIED" not in log and "NOTIFICACION_BLOCKED" not in log
    assert "governed_write_dependency_wait" not in log


def test_lc5_contact_values_never_logged(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser, **LIVE_CONTACT)
        assert result["ok"]
    log = _log_text(str(tmp_path))
    for value in (*LIVE_CONTACT.values(), NOTIFICACION[NOT_EMAIL], NOTIFICACION[NOT_MOBILE]):
        assert value not in log
    assert "611111111" not in log and "600000000" not in log and "@example" not in log


@pytest.mark.parametrize("field", NOT_CONTACT)
def test_lc_locked_contact_is_not_settled_while_notification_inactive(tmp_path, fast, field):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        browser.form.active_panel = PRESENTER  # claimed, never proven active
        browser.readonly.add(field)
        browser.form.values[field] = LIVE_CONTACT[field]
        state.required_blocks.add("notificacion")
        assert state._notification_locked_contact(field, "notificacion") is False
        state.required_blocks.discard("notificacion")
        browser.form.active_panel = NOTIFICATION
        # Active surface but not reached by human navigation: still ordinary.
        assert state._notification_locked_contact(field, "notificacion") is False
    assert field not in state.verified
    assert runner.NOTIFICATION_CONTACT_MERCURIO_MANAGED not in _log_text(str(tmp_path))


def test_lc_settlement_is_revalidated_and_reopened_if_editable(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        assert _to_notification(state, browser, **{NOT_MOBILE: LIVE_CONTACT[NOT_MOBILE]})[0]["ok"]
        browser.readonly.discard(NOT_MOBILE)  # Mercurio released it: ordinary write again
        assert state.resume(("notificacion",))["ok"]
    assert _new_writes(browser).count(NOT_MOBILE) == 1
    assert browser.form.values[NOT_MOBILE] == NOTIFICACION[NOT_MOBILE]


def test_lc8_unrelated_readonly_notification_input_still_fails_closed(tmp_path, fast):
    present = "notDomicilioNotificacion"
    browser = _mercurio(fields=ALL_FIELDS + [present], absent=[f for f in ADDRESS if f != present])
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        browser.form.active_panel = PRESENTER
        assert state.resume(("representante",))["ok"]
        _lock_notification(browser, **{present: "OTRA CALLE"})
        browser.readonly.add(present)
        result = state.resume(("notificacion",))
    assert result["ok"] is False and result["label"] == "NOTIFICACION_BLOCKED"
    assert result["blocked_field"] == present and result["blocked_outcome"] == "DENIED"
    assert browser.form.values[present] == "OTRA CALLE"


def test_lc8b_unrelated_readonly_presenter_contact_still_fails_closed(tmp_path, fast):
    from qcc_presenter_preload_doubles import EMAIL
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        browser.form.active_panel = PRESENTER
        browser.readonly.add(EMAIL)
        browser.form.values[EMAIL] = "otro@example.invalid"
        result = state.resume(("representante",))
    assert result["ok"] is False and result["label"] == "PRESENTADOR_BLOCKED"
    assert result["blocked_field"] == EMAIL and result["blocked_outcome"] == "DENIED"


def test_lc_scope_is_exactly_the_two_contact_controls():
    assert runner._NOTIFICATION_LOCKED_CONTACT_FIELDS == {NOT_EMAIL, NOT_MOBILE}
    assert "chkConsentimientoNotificacion" not in runner._CANONICAL_DOM_FIELDS


# PHASE D · ABSENT NOTIFICATION ADDRESS CONTROLS ------------------------

def test_8_absent_address_controls_are_settled_not_applicable(tmp_path, fast, monkeypatch):
    cascades = []
    monkeypatch.setattr(runner, "_run_mapper_cascade", lambda block, *a: cascades.append(block))
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        assert state.resume(("extranjero", "domicilio_extranjero"))["ok"]
        # Not active yet: still only deferred, never settled prematurely.
        assert {"notDomicilioNotificacion", "notCodigoPostalNotificacion"} <= set(state.deferred)
        browser.form.active_panel = PRESENTER
        assert state.resume(("representante",))["ok"]
        _lock_notification(browser)
        assert state.resume(("notificacion",))["ok"]
        assert state.resume(())["ok"]
    assert not state.deferred
    assert not set(ADDRESS) & set(browser.writes)
    assert "notificacion" not in cascades
    log = _log_text(str(tmp_path))
    assert f"NOTIFICATION_FIELDS_ABSENT fields={sorted(ADDRESS)} outcome=NOT_APPLICABLE" in log
    assert "REQUIRED_ACTIVE_MISSING" not in log


def test_8b_absent_address_is_not_settled_while_notification_inactive(tmp_path, fast):
    browser = _mercurio()
    with mapper(browser, _datos(), tmp_path) as state:
        browser.form.active_panel = PRESENTER  # claimed active, but it is not
        result = state.resume(("notificacion",))
    assert result["ok"] is False and result["blocked_outcome"] != "OK"
    assert "NOTIFICATION_FIELDS_ABSENT" not in _log_text(str(tmp_path))


def test_8c_present_address_control_is_still_written(tmp_path, fast):
    present = "notDomicilioNotificacion"
    browser = _mercurio(fields=ALL_FIELDS + [present],
                        absent=[f for f in ADDRESS if f != present])
    with mapper(browser, _datos(), tmp_path) as state:
        _to_notification(state, browser)
        assert state.resume(())["ok"]
    assert present in browser.writes and present not in state.deferred
    assert present not in _log_text(str(tmp_path)).split("NOTIFICATION_FIELDS_ABSENT")[1].split("\n")[0]


@pytest.mark.parametrize("missing", [NOT_EMAIL, NOT_NAME])
def test_9_required_active_field_genuinely_absent_fails_closed(tmp_path, fast, missing):
    browser = _mercurio(absent=ADDRESS + (missing,))
    with mapper(browser, _datos(), tmp_path) as state:
        result, _ = _to_notification(state, browser)
    assert result["ok"] is False and result["label"] == "NOTIFICACION_BLOCKED"
    assert result["blocked_field"] == missing
    log = _log_text(str(tmp_path))
    assert f"field={missing}" in log and "REQUIRED_ACTIVE_MISSING" in log
    assert missing not in log.split("NOTIFICATION_FIELDS_ABSENT")[1].split("\n")[0]


# PHASE E · COMPLETE EX01 FLOW -> HUMAN-ONLY CONCLUIR GATE ----------------

class _FinalGateClient:
    """QCC action channel: an ABORT is only queued once the operator sees
    the final CONCLUIR gate."""

    def __init__(self, abort):
        self.abort, self.armed = abort, False

    def consume_next(self):
        if self.abort and self.armed:
            self.abort = False
            return {"action_id": 7, "action": "PRESENTATION_ABORT"}
        return None


def _run_ex01(tmp_path, browser, *, abort=False, live=None):
    reporter, fill_starts, trace, closes = Mock(), [], [], []
    client = _FinalGateClient(abort)
    real_wait = runner.wait_for_human_navigation
    live = live or {NOT_NAME: PRESENTER_REORDERED}

    def waiting_user(**kwargs):
        if kwargs.get("step") == "FINAL_REVIEW":
            client.armed = True

    reporter.waiting_user.side_effect = waiting_user

    def human(browser_arg, session_dir, label, ready_js, **kwargs):
        trace.append(label)
        if label == "Datos del presentador":
            browser.form.active_panel = PRESENTER
        elif label == "Domicilio de notificación / CONCLUIR":
            _lock_notification(browser, **live)
        else:  # The REAL final human gate (CONCLUIR is never clicked by QCC).
            return real_wait(browser_arg, session_dir, label, ready_js, **kwargs)
        return {"ok": True, "mode": "human_dom_detected", "label": label}

    with patch.multiple(
        runner,
        step_continuar_inicial=lambda *a, **k: {"ok": True},
        pause_certificado=lambda *a, **k: {"ok": True},
        step_presentar_nueva_solicitud=lambda *a, **k: {"ok": True},
        pause_supuesto=lambda *a, **k: {"ok": True},
        wait_for_qcc_fill_start=lambda *a, **k: fill_starts.append(1) or {"ok": True},
        _wait_for_ex01_personal_readiness=lambda *a, **k: {"ok": True},
        # R6 A pre-fill procedure identity gate (own suite).
        _verify_ex01_renovacion_titular_identity=lambda *a, **k: {"ok": True},
        _read_mercurio_document_page_state=lambda *a: None,
        wait_for_human_navigation=human,
    ):
        result = runner.run_auto(browser, "33", _datos(), str(tmp_path), reporter=reporter,
                                 action_client=client,
                                 abort_handler=lambda: closes.append(1) or True)
    return result, reporter, fill_starts, trace, closes


def _status_calls(reporter):
    return [(name, kw.get("step"), kw.get("progress")) for name, _, kw in reporter.method_calls]


def test_13_to_17_complete_ex01_reaches_human_only_concluir_gate(tmp_path, fast):
    browser = _mercurio()
    result, reporter, fill_starts, trace, _ = _run_ex01(tmp_path, browser)
    log = _log_text(str(tmp_path))

    # 13. Complete flow reaches the final gate; Notification reconciled.
    assert trace == ["Datos del presentador", "Domicilio de notificación / CONCLUIR",
                     "Documentación de la solicitud"]
    assert "MAPPER_FILL_COMPLETED" in log
    for field in NOT_IDENTITY:
        assert f"CERTIFICATE_IDENTITY_VERIFIED field={field} source=PRESENTER_CERTIFICATE" in log
        assert browser.writes.count(field) == 0
    assert "NOTIFICACION_BLOCKED" not in log and "DENIED" not in log
    # 14./15. Canonical HUMAN_ONLY gate state, not the blocked fallback.
    assert result is None or result.get("ok") is not False
    assert runner._extract_blocked_auto_detail(result) is None
    calls = _status_calls(reporter)
    assert ("waiting_user", "FINAL_REVIEW", 82) in calls
    assert calls[-1] == ("waiting_user", "DOCUMENTS_READY", 88)  # after the human CONCLUIR
    assert not any(name == "fill_blocked" or step == "AUTO_FLOW_BLOCKED" or progress == 50
                   for name, step, progress in calls)
    assert "AUTO_FLOW_BLOCKED" not in log
    # 16. CONCLUIR / submission never automated.
    for script in browser.action_scripts:
        assert "btnConcluirSup" not in script and "enviaDatosSup" not in script
        assert ".click()" not in script
    # 17. One VOLCAR only.
    assert fill_starts == [1]
    # 19. Metadata never reaches the DOM.
    for key in ("ruta_box_dni_representante", "ruta_box_notificacion"):
        assert key not in browser.writes + browser.form.local_probes
        assert f"NON_DOM_MAPPER_METADATA_SKIPPED key={key}" in log
    # Presenter regression on the same run.
    assert f"CERTIFICATE_IDENTITY_VERIFIED field={NAME}" in log
    assert NAME not in browser.writes


def test_18_abort_at_final_human_gate(tmp_path, fast):
    browser = _mercurio()
    result, reporter, _, trace, closes = _run_ex01(tmp_path, browser, abort=True)
    assert runner._is_qcc_aborted_result(result)
    assert result["browser_closed"] is True and closes == [1]
    calls = _status_calls(reporter)
    assert ("waiting_user", "FINAL_REVIEW", 82) in calls
    assert ("waiting_user", "DOCUMENTS_READY", 88) not in calls
    assert "MAPPER_FILL_COMPLETED" in _log_text(str(tmp_path))


def test_true_mismatch_never_reaches_final_gate(tmp_path, fast):
    browser = _mercurio()
    result, reporter, _, trace, _ = _run_ex01(tmp_path, browser, live={NOT_NAME: "PEDRO LOPEZ RUIZ"})
    assert result["ok"] is False and result["label"] == "NOTIFICACION_BLOCKED"
    assert "Documentación de la solicitud" not in trace
    assert ("waiting_user", "FINAL_REVIEW", 82) not in _status_calls(reporter)
    assert NOT_NAME not in _new_writes(browser)


def test_20_fast_path_one_capture_per_section(tmp_path, fast):
    browser = _mercurio()
    _run_ex01(tmp_path, browser)
    log = _log_text(str(tmp_path))
    assert "governed_write_dependency_wait" not in log
    assert browser.capture_calls <= 6


# QCC_NOTIFICATION_LOCKED_CONTACT_V1 · COMPLETE EX01 ----------------------

REAL_FINAL_SURFACE = {NOT_NAME: PRESENTER_REORDERED, **LIVE_CONTACT}


def test_lc15_17_locked_contacts_reach_human_only_concluir_gate(tmp_path, fast):
    browser = _mercurio()
    result, reporter, fill_starts, trace, _ = _run_ex01(tmp_path, browser, live=REAL_FINAL_SURFACE)
    log = _log_text(str(tmp_path))
    assert trace == ["Datos del presentador", "Domicilio de notificación / CONCLUIR",
                     "Documentación de la solicitud"]
    for field in NOT_CONTACT:
        assert f"NOTIFICATION_CONTACT_MERCURIO_MANAGED field={field} outcome=PRESERVED_LIVE" in log
        assert browser.form.values[field] == LIVE_CONTACT[field]
    assert _new_writes(browser) == []
    for field in NOT_IDENTITY:
        assert f"CERTIFICATE_IDENTITY_VERIFIED field={field} source=PRESENTER_CERTIFICATE" in log
    assert "MAPPER_FILL_COMPLETED" in log
    assert "NOTIFICACION_BLOCKED" not in log and "DENIED" not in log
    assert "AUTO_FLOW_BLOCKED" not in log
    assert runner._extract_blocked_auto_detail(result) is None
    calls = _status_calls(reporter)
    assert ("waiting_user", "FINAL_REVIEW", 82) in calls
    assert not any(name == "fill_blocked" or step == "AUTO_FLOW_BLOCKED" or progress == 50
                   for name, step, progress in calls)
    for script in browser.action_scripts:  # CONCLUIR never automated
        assert "btnConcluirSup" not in script and "enviaDatosSup" not in script
        assert ".click()" not in script
    assert fill_starts == [1]  # SECOND_VOLCAR_REQUIRED=NO
    for value in LIVE_CONTACT.values():
        assert value not in log


def test_lc18_abort_at_final_gate_with_locked_contacts(tmp_path, fast):
    browser = _mercurio()
    result, reporter, _, _, closes = _run_ex01(tmp_path, browser, abort=True, live=REAL_FINAL_SURFACE)
    assert runner._is_qcc_aborted_result(result)
    assert result["browser_closed"] is True and closes == [1]
    calls = _status_calls(reporter)
    assert ("waiting_user", "FINAL_REVIEW", 82) in calls
    assert ("waiting_user", "DOCUMENTS_READY", 88) not in calls


def test_lc20_fast_path_with_locked_contacts(tmp_path, fast):
    browser = _mercurio()
    _run_ex01(tmp_path, browser, live=REAL_FINAL_SURFACE)
    assert "governed_write_dependency_wait" not in _log_text(str(tmp_path))
    assert browser.capture_calls <= 6

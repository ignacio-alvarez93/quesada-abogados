"""Tabbed Mercurio double and REAL ``run_auto`` harness (QCC_EX01_R6_POSTFORM).

Extracted from the historical ``test_qcc_full_mapper_fast_path`` helpers
(read-only reference ``data/qcc_ex01_r2_reference``) so the restored
post-form EX01 suites share them without collecting that suite.

Adapted to the current runtime:

* the DOM capture carries the r-tabs panels on the EX01 form path, as the
  REAL page does (every panel and its controls are in the DOM, only the
  active one is displayed), so the section fast path can prove the active
  surface from the capture;
* the R6 A pre-fill procedure identity gate is simulated like the other
  pre-form steps (it has its own suite).

Only the physical browser is faked: the real runner helpers, the real
state-aware engine and Mercurio's real policy/profile/recognizer run.
Offline, fictitious values only.
"""

from pathlib import Path
from unittest.mock import patch

import app.run_presentacion_asistida as runner
from backend.automation.site_policies.mercurio import MERCURIO_REAL_ORIGIN
from backend.automation.site_recognizers.mercurio import MERCURIO_EX01_NEW_REQUEST_PATH
from qcc_fake_form_controls import (
    CAPTURE_SCRIPT_SIZE_THRESHOLD,
    EX01_PANELS,
    FakeFormControls,
    _capture_element,
    _field_id,
    _panel_element,
    dom_capture_payload,
)


PERSONAL = "tab-datos_personales"
FAMILIAR = "tab-datos_familiar"
PRESENTER = "tab-datos_presentador"
NOTIFICATION = "tab-datos_notificacion"


def _panel_of(field_id):
    if field_id.startswith("not"):
        return NOTIFICATION
    if field_id.startswith("pre"):
        return PRESENTER
    if field_id.startswith("rea"):
        return FAMILIAR
    return PERSONAL


SELECT_FIELDS = {"extSexo", "extEstadoCivil"}


class _TabbedMercurioBrowser:
    """CDP-style double of a tabbed Mercurio form: every section's
    controls are in the DOM, only the active r-tabs panel is shown."""

    def __init__(
        self,
        *,
        fields,
        active_panel=PERSONAL,
        panels=None,
        selects=(),
        checkboxes=(),
        **form_kwargs,
    ):
        self.fields = list(fields)
        self.selects = set(selects) | (SELECT_FIELDS & set(self.fields))
        self.checkboxes = set(checkboxes)
        self.form = FakeFormControls(
            panels=panels if panels is not None else {f: _panel_of(f) for f in self.fields},
            active_panel=active_panel,
            **form_kwargs,
        )
        self.form.page = (MERCURIO_REAL_ORIGIN, MERCURIO_EX01_NEW_REQUEST_PATH)
        # QCC_NOTIFICATION_CERTIFICATE_AUTHORITY_V1: Mercurio fills the
        # Notification identity from the authenticated presenter identity
        # unless a test sets its live value explicitly.
        readback = self.form.readback

        def certificate_readback(field_id):
            presenter = runner._NOTIFICATION_PRESENTER_IDENTITY.get(field_id)
            if field_id in self.form.absent:
                return {"exists": False}
            if presenter in self.fields and field_id not in self.form.values:
                return readback(presenter)
            return readback(field_id)

        self.form.readback = certificate_readback
        self.capture_calls = 0
        self.writes = []
        self.action_scripts = []

    def _elements(self):
        elements = []
        for index, field_id in enumerate(self.fields):
            if field_id in self.form.absent:
                continue
            if field_id in self.selects:
                tag, element_type = "select", ""
            elif field_id in self.checkboxes:
                tag, element_type = "input", "checkbox"
            else:
                tag, element_type = "input", "text"
            probe = self.form.local_probe(field_id)
            element = _capture_element(
                index, field_id, tag, element_type, probe["visible"], probe["disabled"]
            )
            element["interaction_signals"]["in_viewport"] = (
                probe["interaction_signals"]["in_viewport"]
            )
            elements.append(element)
        panels = sorted(set(EX01_PANELS) | set(self.form.panels.values()))
        elements += [
            _panel_element(len(self.fields) + i, panel, panel == self.form.active_panel)
            for i, panel in enumerate(panels)
        ]
        return elements

    def evaluate(self, script):
        if len(script) > CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            origin, pathname = self.form.page
            return dom_capture_payload(
                origin=origin, pathname=pathname, elements=self._elements()
            )

        if (script.startswith("return !!document.getElementById(")
                and _field_id(script) not in self.fields):
            return False  # Not a control of this page at all.

        handled, probe_result = self.form.handle_probe(script)
        if handled:
            return probe_result

        if "btnConcluirSup" in script and NOTIFICATION in script:
            return self.form.active_panel == NOTIFICATION

        if script.startswith("return !!("):
            return True

        self.action_scripts.append(script)
        self.writes.append(_field_id(script))
        return self.form.apply_write(script)


class _FakeActionClient:
    def __init__(self, actions=()):
        self.actions = list(actions)

    def consume_next(self):
        return self.actions.pop(0) if self.actions else None


def _log_text(session_dir):
    log_path = Path(session_dir) / "logs" / "presentacion.log"
    return log_path.read_text(encoding="utf-8") if log_path.exists() else ""


TEN_FIELDS = {
    "extPasaporte": "P1",
    "extApellido1": "A1",
    "extApellido2": "A2",
    "extNombre": "N",
    "extFechaNacimiento": "01/01/1990",
    "extPadre": "PA",
    "extMadre": "MA",
    "extSexo": "H",
    "extEstadoCivil": "S",
    "chkHijosCargo": "true",
}

EXTRANJERO = {"extPasaporte": "P1", "extNombre": "N", "extSexo": "H"}
DOMICILIO = {"extDomicilio": "CALLE", "extNumero": "1"}
NOTIFICACION = {
    "notNombreNotificacion": "N",
    "notNieNotificacion": "X1",
    "notEmailNotificacion": "e@example.invalid",
}
REPRESENTANTE = {
    "preNombrePresentador": "P", "preNiePresentador": "X1", "preEmailPresentador": "p@example.invalid",
}
# Certificate-held: Mercurio manages them, the mapper never writes them.
NOTIFICATION_IDENTITY = {"notNombreNotificacion", "notNieNotificacion"}
FAMILIAR_BLOCK = {"reaNombreReagrupante": "F", "reaDocumentoReagrupante": "D1"}


def _datos(mapper_codigo, **blocks):
    datos = {
        "presentacion": {"mapper_codigo": mapper_codigo},
        "extranjero": dict(EXTRANJERO),
        "domicilio_extranjero": dict(DOMICILIO),
        "notificacion": dict(NOTIFICACION),
        "representante": dict(REPRESENTANTE),
        "familiar": {},
        "reagrupante": {},
    }
    datos.update(blocks)
    return datos


# Human CONTINUAR, by destination label -> the panel Mercurio shows.
_DESTINATION_PANELS = {
    "Datos del familiar": FAMILIAR,
    "Datos del presentador": PRESENTER,
    "Domicilio de notificación / CONCLUIR": NOTIFICATION,
    "Datos del reagrupado/solicitante": PERSONAL,
}


def _run_full_mapper(tmp_path, browser, datos, *, action_client=None, extra=None):
    """Runs the REAL ``run_auto`` mapper orchestration. Only the
    pre-form steps and the human CONTINUAR clicks are simulated."""

    session_dir = str(tmp_path)
    action_client = action_client or _FakeActionClient()
    trace = []
    navigation_kwargs = []

    def _human_continue(browser_arg, session_dir_arg, label, ready_js, **kwargs):
        navigation_kwargs.append(kwargs)
        trace.append(f"CONTINUE:{label}")
        browser.form.active_panel = _DESTINATION_PANELS[label]
        return {"ok": True, "mode": "human_dom_detected", "label": label}

    def _final(*args, **kwargs):
        trace.append("FINAL_HUMAN_CONCLUIR")
        return {"ok": True, "mode": "human_dom_detected"}

    patches = dict(
        step_continuar_inicial=lambda *a, **k: {"ok": True},
        pause_certificado=lambda *a, **k: {"ok": True},
        step_presentar_nueva_solicitud=lambda *a, **k: {"ok": True},
        pause_supuesto=lambda *a, **k: {"ok": True},
        wait_for_qcc_fill_start=lambda *a, **k: {"ok": True, "mode": "fill_start_confirmed"},
        _wait_for_ex01_personal_readiness=lambda *a, **k: {"ok": True},
        _verify_ex01_renovacion_titular_identity=lambda *a, **k: {"ok": True},
        wait_for_human_navigation=_human_continue,
        pause_humana_final_presentacion=_final,
    )
    patches.update(extra or {})

    with patch.multiple(runner, **patches):
        result = runner.run_auto(
            browser,
            "33",
            datos,
            session_dir,
            action_client=action_client,
            abort_handler=lambda: True,
        )

    return result, trace, navigation_kwargs


ALL_EX01_FIELDS = (
    list(EXTRANJERO) + list(DOMICILIO) + list(NOTIFICACION) + list(REPRESENTANTE)
)

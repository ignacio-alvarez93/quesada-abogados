"""Shared fake native-control state for QCC presentation test doubles.

QCC_FILL_PERFORMANCE_NATIVE_CONTROLS_V1: governed form writes are only
``OK`` once their postcondition is read back from the live control. A
fake CDP browser that answers ``True`` to every script can no longer
prove that, so this helper interprets the runner's REAL write scripts,
records the resulting control state, and answers the runner's read-back,
local-probe, scroll and readiness probes from it.

QCC_EX01_R6_FAMILIAR_131 adaptation: one SYNTHETIC single-page EX01
(``nuevaSolicitud-EX01.html``) where every r-tabs panel and its controls
always exist and only the active panel changes, like Mercurio. The
family cascade (rea* province -> municipality -> locality) loads each
dependent list only once its parent is selected; a parent change rebuilds
the child (value reset). ``pending`` simulates Mercurio requests still in
flight (``jQuery.active``); ``tick()`` lands them.

Not a JS engine: it only recognises the exact script shapes the runner
emits; anything else is recorded in ``unexpected``. No browser, no
network, fictitious data only.
"""

from __future__ import annotations

import json
import re

import app.run_presentacion_asistida as runner
from backend.automation.site_policies.mercurio import MERCURIO_REAL_ORIGIN
from backend.automation.site_recognizers.mercurio import MERCURIO_EX01_NEW_REQUEST_PATH


_ID_RE = re.compile(r'getElementById\(\s*("(?:[^"\\]|\\.)*")\s*\)')
_JSON_STR = r'("(?:[^"\\]|\\.)*")'
CAPTURE_SCRIPT_SIZE_THRESHOLD = 10000

AUTHORIZATION = "tab-datos_autorizacion"
PERSONAL = "tab-datos_personales"
FAMILIAR = "tab-datos_familiar"
PRESENTER = "tab-datos_presentador"
NOTIFICATION = "tab-datos_notificacion"
EX01_PANELS = (AUTHORIZATION, PERSONAL, FAMILIAR, PRESENTER, NOTIFICATION)

PROVINCE, TOWN, LOCALITY = (
    "reaCodigoProvinciaReagrupante", "reaCodigoMunicipioReagrupante", "reaCodigoLocalidadReagrupante",
)
FAMILY_CASCADE = (PROVINCE, TOWN, LOCALITY)
# child -> (parent, parent value that loads it, options)
FAMILY_DEPENDENT_OPTIONS = {
    TOWN: (PROVINCE, "33", [("", "--"), ("044", "OVIEDO")]),
    LOCALITY: (TOWN, "044", [("", "--"), ("0001", "OVIEDO")]),
}
FAMILY_SELECT_OPTIONS = {
    PROVINCE: [("", "--"), ("33", "ASTURIAS")],
    "reaTipoDocumentoReagrupante": [("", "--"), ("TU", "NIE"), ("PA", "PASAPORTE")],
    "reaSexoReagrupante": [("", "--"), ("0", "HOMBRE"), ("1", "MUJER")],
    "reaEstadoCivilReagrupante": [("", "--"), ("S", "SOLTERO"), ("C", "CASADO")],
    "reaCodigoPaisNacimientoReagrupante": [("", "--"), ("348", "MARRUECOS")],
    "reaCodigoNacionalidadReagrupante": [("", "--"), ("348", "MARRUECOS")],
    "reaTipoViaReagrupante": [("", "--"), ("CL", "CALLE"), ("AV", "AVENIDA")],
    "reaTipodocumentoRepresentanteReagrupante": [("", "--"), ("TU", "NIE")],
    "reaParentescoReagrupante": [("", "--"), ("CO", "CONYUGE"), ("AS", "ASCENDIENTE")],
}
FAMILY_INPUTS = (
    "reaPasaporteReagrupante", "reaDocumentoReagrupante", "reaApellido1Reagrupante",
    "reaApellido2Reagrupante", "reaNombreReagrupante", "reaFechaNacimientoReagrupante",
    "reaLugarNacimientoReagrupante", "reaPadreReagrupante", "reaMadreReagrupante",
    "reaDomicilioReagrupante", "reaNumeroReagrupante", "reaPisoReagrupante",
    "reaLetraReagrupante", "reaEscaleraReagrupante", "reaBloqueReagrupante",
    "reaKilometroReagrupante", "reaHectometroReagrupante", "reaCodigoPostalReagrupante",
    "reaTelefonoReagrupante", "reaTelefonoMovilReagrupante", "reaEmailReagrupante",
    "reaNombreRepresentanteReagrupante", "reaNieRepresentanteReagrupante",
    "reaTituloRepresentanteReagrupante",
)


def _json_after(script, prefix):
    match = re.search(re.escape(prefix) + r"\s*" + _JSON_STR, script)
    return json.loads(match.group(1)) if match else None


def _json_object_after(script, prefix):
    match = re.search(re.escape(prefix) + r"\s*(\{.*?\});", script)
    return json.loads(match.group(1)) if match else None


def _field_id(script):
    match = _ID_RE.search(script)
    if match:
        return json.loads(match.group(1))
    return _json_after(script, "const id =")


def _signals(in_viewport=True):
    return {
        "hidden": False, "aria_hidden": False, "aria_disabled": False, "readonly": False,
        "in_viewport": in_viewport, "opacity": "1", "pointer_events": "auto",
    }


def _capture_element(index, element_id, tag, element_type, visible, disabled):
    return {
        "index": index, "frame_path": "main", "tag": tag, "id": element_id, "name": element_id,
        "type": element_type, "role": "", "classes": [],
        "attributes": {"id": element_id, "name": element_id, "type": element_type},
        "text": "", "visible": visible, "disabled": disabled,
        "interaction_signals": _signals(), "shadow_root": False,
        "rect": {"x": 0, "y": 0, "width": 100, "height": 20},
    }


def _panel_element(index, panel_id, active):
    classes = ["mf-tabs--tab-content", "r-tabs-panel",
               "r-tabs-state-active" if active else "r-tabs-state-default"]
    return {
        "index": index, "frame_path": "main", "tag": "div", "id": panel_id, "name": "",
        "type": "", "role": "", "classes": classes,
        "attributes": {"id": panel_id, "class": " ".join(classes)},
        "text": "", "visible": active, "disabled": False,
        "interaction_signals": _signals(), "shadow_root": False,
        "rect": {"x": 0, "y": 0, "width": 800, "height": 600},
    }


def dom_capture_payload(*, origin, pathname, elements):
    url = origin + pathname
    counts = dict.fromkeys(("forms", "inputs", "textareas", "selects", "buttons", "links", "tables"), 0)
    return {
        "schema_version": 1,
        "captured_at": "2024-01-01T00:00:00.000Z",
        "metadata": {
            "url": url, "origin": origin, "pathname": pathname, "title": "Mercurio",
            "ready_state": "complete", "content_type": "text/html", "character_set": "UTF-8",
        },
        "viewport": {
            "inner_width": 1280, "inner_height": 800, "client_width": 1280, "client_height": 800,
            "scroll_x": 0, "scroll_y": 0, "device_pixel_ratio": 1, "screen_x": 0, "screen_y": 0,
            "outer_width": 1280, "outer_height": 800,
        },
        "html": "<html></html>",
        "documents": [{"frame_path": "main", "url": url, "title": "Mercurio",
                       "element_count": len(elements), **counts}],
        "elements": elements,
        "frames": [],
        "shadows": [],
        "counts": {"documents": 1, "elements": len(elements), **counts, "iframes": 0,
                   "accessible_iframes": 0, "inaccessible_iframes": 0, "open_shadow_roots": 0},
    }


class FakeEx01Page:
    """Stateful single-page EX01 double (family panel + cascade).

    ``ignore_writes``: field ids whose write scripts "run" but leave the
    control unchanged (a widget that swallows the write).
    ``hidden``/``disabled``/``absent``: per-field live state.
    ``after_write``: ``{field_id: callable(page)}`` run after a kept write
    of that field (e.g. queue a late Mercurio rebuild).
    ``land_on_ready``: field whose cascade readiness wait is when the
    in-flight requests land (otherwise they land on the settle wait).
    """

    def __init__(self, *, active=(FAMILIAR,), origin=MERCURIO_REAL_ORIGIN,
                 pathname=MERCURIO_EX01_NEW_REQUEST_PATH, ignore_writes=(),
                 hidden=(), disabled=(), absent=(), options=None):
        self.active = set(active)
        self.origin = origin
        self.pathname = pathname
        self.ignore_writes = set(ignore_writes)
        self.hidden = set(hidden)
        self.disabled = set(disabled)
        self.absent = set(absent)
        self.options = {k: list(v) for k, v in FAMILY_SELECT_OPTIONS.items()}
        self.options.update(options or {})
        self.selects = set(self.options) | set(FAMILY_DEPENDENT_OPTIONS)
        self.panels = {f: FAMILIAR for f in (*self.selects, *FAMILY_INPUTS)}
        self.panels["preNombrePresentador"] = PRESENTER
        self.values = {}
        self.writes = []
        self.events = []
        self.pending = []
        self.after_write = {}
        self.land_on_ready = None
        self.readiness_checks = []
        self.diagnostics = []
        self.settle_checks = 0
        self.capture_calls = 0
        self.unexpected = []

    # -- page state ----------------------------------------------------

    def show(self, *panels):
        self.active = set(panels)

    def tick(self):
        while self.pending:
            self.pending.pop(0)()

    def exists(self, field_id):
        return field_id in self.panels and field_id not in self.absent

    def visible(self, field_id):
        panel = self.panels.get(field_id)
        return (self.exists(field_id) and field_id not in self.hidden
                and (panel is None or panel in self.active))

    def sole_active(self, panel_id):
        return self.active == {panel_id}

    def options_for(self, field_id):
        if field_id in FAMILY_DEPENDENT_OPTIONS:
            parent, value, options = FAMILY_DEPENDENT_OPTIONS[field_id]
            return list(options) if self.values.get(parent) == value else []
        return list(self.options.get(field_id) or [])

    def selected(self, field_id):
        value = self.values.get(field_id, "")
        options = self.options_for(field_id)
        index = next((i for i, (v, _t) in enumerate(options) if v == value), -1)
        return index, (options[index] if index >= 0 else None)

    def _set_value(self, field_id, value):
        previous = self.values.get(field_id)
        self.values[field_id] = value
        if previous != value:
            # Mercurio rebuilds every dependent list of a changed parent.
            for child, (parent, _v, _o) in FAMILY_DEPENDENT_OPTIONS.items():
                if parent == field_id:
                    self._set_value(child, "")

    # -- dispatch ------------------------------------------------------

    def evaluate(self, script):
        if len(script) > CAPTURE_SCRIPT_SIZE_THRESHOLD:
            self.capture_calls += 1
            return self._capture()
        if runner._FIELD_READBACK_MARKER in script:
            return self._readback(_field_id(script))
        if runner._FIELD_LOCAL_PROBE_MARKER in script:
            return self._probe(_field_id(script))
        if runner._FIELD_SCROLL_MARKER in script:
            return True
        if runner._FAMILY_CASCADE_READY_MARKER in script:
            return self._family_ready(script)
        if runner._FAMILY_CASCADE_DIAGNOSTIC_MARKER in script:
            return self._family_diagnostic(script)
        if "QCC_FAMILY_CASCADE_SETTLED" in script:
            # Time passes while the runner waits: in-flight requests land
            # now, so this poll still sees them active (not settled).
            self.settle_checks += 1
            busy = bool(self.pending)
            self.tick()
            return not busy
        if script.startswith("return !!document.getElementById("):
            return self.exists(_field_id(script))
        if script.startswith("return !!("):
            return self._predicate(script)
        return self._apply(script)

    # -- probes --------------------------------------------------------

    def _capture(self):
        elements = []
        for index, field_id in enumerate(sorted(f for f in self.panels if self.exists(f))):
            tag = "select" if field_id in self.selects else "input"
            elements.append(_capture_element(
                index, field_id, tag, "" if tag == "select" else "text",
                self.visible(field_id), field_id in self.disabled,
            ))
        elements += [_panel_element(len(elements) + i, p, p in self.active)
                     for i, p in enumerate(EX01_PANELS)]
        return dom_capture_payload(origin=self.origin, pathname=self.pathname, elements=elements)

    def _readback(self, field_id):
        if not self.exists(field_id):
            return {"exists": False}
        is_select = field_id in self.selects
        index, option = self.selected(field_id) if is_select else (-1, None)
        return {
            "exists": True,
            "tag": "select" if is_select else "input",
            "type": "select-one" if is_select else "text",
            "value": self.values.get(field_id, ""),
            "checked": False,
            "selected_index": index,
            "selected_value": option[0] if option else None,
            "selected_text": option[1] if option else None,
        }

    def _probe(self, field_id):
        page = {"origin": self.origin, "pathname": self.pathname}
        if not self.exists(field_id):
            return {"exists": False, **page}
        panel = self.panels.get(field_id)
        active = panel is not None and panel in self.active
        return {
            "exists": True, **page,
            "visible": self.visible(field_id),
            "disabled": field_id in self.disabled,
            "interaction_signals": _signals(),
            "panel_id": panel,
            "panel_active": active,
            "panel_inactive": panel is not None and not active,
            "hidden_within_panel": field_id in self.hidden,
        }

    def _target_present(self, field_id, value, text):
        options = self.options_for(field_id)
        if any((value and v == value) or (text and runner.normalize(t) == text) for v, t in options):
            return True
        partial = [t for _v, t in options
                   if runner.normalize(t) and (runner.normalize(t) in text or text in runner.normalize(t))]
        return bool(text) and len(partial) == 1

    def _family_ready(self, script):
        ids = _json_object_after(script, "const ids =")
        want = _json_object_after(script, "const want =")
        text = runner.normalize(json.loads(re.search(r"const text = norm\(" + _JSON_STR, script).group(1)))
        child, parent = ids["child"], ids["parent"]
        if child == self.land_on_ready:
            self.tick()  # a late Mercurio reload lands during this wait
        ready = (
            self.sole_active(FAMILIAR)
            and self.visible(child) and child not in self.disabled
            and (not parent or (self.selected(parent)[0] >= 0
                                and self.values.get(parent, "") == want["parent_value"]))
            and self._target_present(child, want["value"], text)
        )
        self.readiness_checks.append((child, ready))
        return ready

    def _family_diagnostic(self, script):
        ids = _json_object_after(script, "const ids =")
        want = _json_object_after(script, "const want =")
        text = runner.normalize(json.loads(re.search(r"const text = norm\(" + _JSON_STR, script).group(1)))
        child, parent = ids["child"], ids["parent"]
        self.diagnostics.append(child)
        return {
            "surface_active": self.sole_active(FAMILIAR),
            "child_exists": self.exists(child),
            "child_disabled": child in self.disabled,
            "child_option_count": len(self.options_for(child)),
            "target_option_present": self._target_present(child, want["value"], text),
            "parent_exists": bool(parent) and self.exists(parent),
            "parent_selected_index": self.selected(parent)[0] if parent else -1,
            "parent_selected_value": self.values.get(parent, "") if parent else None,
            "jquery_active": len(self.pending),
        }

    def _predicate(self, script):
        if runner._ex01_sole_active_panel_js(FAMILIAR) in script:
            return self.exists("reaNombreReagrupante") and self.sole_active(FAMILIAR)
        if runner._ex01_sole_active_panel_js(PRESENTER) in script:
            return self.exists("preNombrePresentador") and self.sole_active(PRESENTER)
        field_id = _field_id(script)
        if field_id is not None and "el.disabled" in script:  # _field_readiness_js
            return self.visible(field_id) and field_id not in self.disabled
        self.unexpected.append(script[:160])
        return False

    # -- writes --------------------------------------------------------

    def _apply(self, script):
        field_id = _field_id(script)
        if field_id is None or not self.exists(field_id):
            self.unexpected.append(script[:160])
            return None
        self.writes.append(field_id)
        ignored = field_id in self.ignore_writes

        if "const wantedValue =" in script and "const wantedText =" in script:
            wanted_value = _json_after(script, "const wantedValue =") or ""
            wanted_text = _json_after(script, "const wantedText =") or ""
            options = self.options_for(field_id)
            selected = next((v for v, _t in options if wanted_value and v == wanted_value), None)
            if selected is None and wanted_text:
                selected = next((v for v, t in options if runner.normalize(t) == wanted_text), None)
            if not selected:
                return {"ok": False, "reason": "NO_MATCH"}
            if not ignored:
                self._kept(field_id, selected)
            return {"ok": True, "value": selected, "selected": selected}

        value = _json_after(script, "el.value =")
        if value is not None:
            if not ignored:
                self._kept(field_id, value)
            return True

        self.unexpected.append(script[:160])
        return None

    def _kept(self, field_id, value):
        self._set_value(field_id, value)
        self.events.append((field_id, "change"))
        hook = self.after_write.get(field_id)
        if hook is not None:
            hook(self)

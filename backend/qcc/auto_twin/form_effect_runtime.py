"""Pure Form Effect Runtime — AUTO TWIN (UWT-6B3-1B).

Normalizes governed B2/B3-1A dynamic-form effect evidence into a
deterministic runtime payload, and generates a pure browser adapter
that replays the EXECUTABLE subset of that payload inside an already
rendered Twin page.

This module is PURE: it never captures DOM, never runs SeleniumBase,
never navigates and never accesses REAL. It reuses the effect kind
constants already owned by
``backend.automation.site_architecture.dynamic_form_effects`` instead
of forking a parallel taxonomy.

Trigger identity (UWT-6B3-1A structural mutation identity):

    (state_id, action.kind, action.selector, action.frame_path,
     mutation_identity)

Never derived from ``selected_value``, option text, typed/free text or
any other personal/runtime literal value.
"""

from __future__ import annotations

from backend.automation.site_architecture.dynamic_form_effects import (
    EFFECT_CHECKED_CHANGED,
    EFFECT_CONTROL_APPEARED,
    EFFECT_CONTROL_DISAPPEARED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_HAS_VALUE_CHANGED,
    EFFECT_INTERACTABLE_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_SELECTION_CHANGED,
    EFFECT_VISIBILITY_CHANGED,
)


FORM_EFFECT_RUNTIME_SCHEMA_VERSION = 1

FORM_EFFECT_RUNTIME_RECORD_TYPE = (
    "QCC_AUTO_TWIN_FORM_EFFECT_RUNTIME_PLAN"
)

MAIN_FRAME_PATH = "main"

ACTION_SELECT = "SELECT"
ACTION_CHECKBOX = "CHECKBOX"
ACTION_RADIO = "RADIO"

ALLOWED_ACTION_KINDS = frozenset({
    ACTION_SELECT,
    ACTION_CHECKBOX,
    ACTION_RADIO,
})

SELECTION_CHANGED_OWNER = "CATALOG_RUNTIME"

ROUTE_STATUS_EXECUTABLE = "EXECUTABLE"
ROUTE_STATUS_BLOCKED = "BLOCKED"

CONTEXTUAL_EFFECTS_V1 = "NO"

_READONLY_SEMANTIC_KINDS = frozenset({
    "TEXT_INPUT",
    "TEXTAREA",
})

EXECUTABLE_EFFECT_KINDS = frozenset({
    EFFECT_VISIBILITY_CHANGED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_CHECKED_CHANGED,
    EFFECT_CONTROL_DISAPPEARED,
})

DELEGATED_EFFECT_KINDS = frozenset({
    EFFECT_SELECTION_CHANGED,
})

BLOCKED_EFFECT_KINDS = frozenset({
    EFFECT_INTERACTABLE_CHANGED,
    EFFECT_HAS_VALUE_CHANGED,
    EFFECT_CONTROL_APPEARED,
})

_KNOWN_EFFECT_KINDS = (
    EXECUTABLE_EFFECT_KINDS
    | DELEGATED_EFFECT_KINDS
    | BLOCKED_EFFECT_KINDS
)

_BOOL_AFTER_EFFECT_KINDS = frozenset({
    EFFECT_VISIBILITY_CHANGED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_CHECKED_CHANGED,
})

# CONTEXTUAL_EFFECTS_V1=NO: current B2/B3-1A evidence carries no
# governed navigation_context/context_signature. Any evidence shaped
# with these keys is a future/foreign shape this V1 runtime must
# reject rather than silently route around.
_CONTEXTUAL_SHAPE_KEYS = frozenset({
    "context",
    "navigation_context",
    "context_signature",
})


class FormEffectRuntimeError(RuntimeError):
    """Fallo gobernado y determinista del Form Effect Runtime."""


def _text(value):
    return str(value or "").strip()


def _is_plain_bool(value):
    return isinstance(value, bool)


def _is_plain_int(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
    )


def _reject_contextual_shape(value):
    if (
        isinstance(value, dict)
        and (_CONTEXTUAL_SHAPE_KEYS & set(value))
    ):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_CONTEXTUAL_EFFECTS_NOT_SUPPORTED_V1"
        )


def _validate_state_id(state_id):
    text = _text(state_id)

    if not text:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_STATE_ID_REQUIRED"
        )

    return text


def _validate_action(action):
    if not isinstance(action, dict):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_ACTION_INVALID"
        )

    _reject_contextual_shape(action)

    kind = _text(action.get("kind")).upper()

    if kind not in ALLOWED_ACTION_KINDS:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_ACTION_KIND_NOT_ALLOWED:"
            + kind
        )

    selector = _text(action.get("selector"))

    if not selector:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_ACTION_SELECTOR_REQUIRED"
        )

    frame_path = (
        _text(action.get("frame_path"))
        or MAIN_FRAME_PATH
    )

    if frame_path != MAIN_FRAME_PATH:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_ACTION_FRAME_NOT_MAIN:"
            + frame_path
        )

    return {
        "kind": kind,
        "selector": selector,
        "frame_path": frame_path,
    }


def _validate_mutation_identity(action_kind, mutation_identity):
    if not isinstance(mutation_identity, dict):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_MUTATION_IDENTITY_INVALID"
        )

    _reject_contextual_shape(mutation_identity)

    kind = _text(mutation_identity.get("kind")).upper()

    if kind != action_kind:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_MUTATION_IDENTITY_KIND_MISMATCH"
        )

    if kind == ACTION_SELECT:
        if set(mutation_identity) != {"kind", "selected_index"}:
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_MUTATION_IDENTITY_FIELDS_INVALID"
            )

        selected_index = mutation_identity.get("selected_index")

        if (
            not _is_plain_int(selected_index)
            or selected_index < 0
        ):
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_SELECT_INVALID_SELECTED_INDEX"
            )

        return {
            "kind": ACTION_SELECT,
            "selected_index": selected_index,
        }

    if set(mutation_identity) != {"kind", "checked"}:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_MUTATION_IDENTITY_FIELDS_INVALID"
        )

    checked = mutation_identity.get("checked")

    if not _is_plain_bool(checked):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_CHECKED_INVALID"
        )

    if (
        kind == ACTION_RADIO
        and checked is not True
    ):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_RADIO_CHECKED_MUST_BE_TRUE"
        )

    return {
        "kind": kind,
        "checked": checked,
    }


def _mutation_identity_key(mutation_identity):
    if mutation_identity["kind"] == ACTION_SELECT:
        return (
            mutation_identity["kind"],
            mutation_identity["selected_index"],
        )

    return (
        mutation_identity["kind"],
        mutation_identity["checked"],
    )


def _validate_target(target):
    if not isinstance(target, dict):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_TARGET_INVALID"
        )

    _reject_contextual_shape(target)

    control_key = _text(target.get("control_key"))
    frame_path = _text(target.get("frame_path"))
    selector = _text(target.get("selector"))
    semantic_kind = _text(target.get("semantic_kind")).upper()

    if not (
        control_key
        and frame_path
        and selector
        and semantic_kind
    ):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_TARGET_MALFORMED"
        )

    if frame_path != MAIN_FRAME_PATH:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_TARGET_FRAME_NOT_MAIN:"
            + frame_path
        )

    return {
        "control_key": control_key,
        "frame_path": frame_path,
        "selector": selector,
        "semantic_kind": semantic_kind,
    }


def _validate_effect(effect):
    if not isinstance(effect, dict):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_EFFECT_INVALID"
        )

    _reject_contextual_shape(effect)

    kind = _text(effect.get("kind")).upper()

    if kind not in _KNOWN_EFFECT_KINDS:
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_EFFECT_KIND_UNKNOWN:"
            + kind
        )

    target = _validate_target(effect.get("target"))

    after = effect.get("after")

    if kind in BLOCKED_EFFECT_KINDS:
        return {
            "kind": kind,
            "target": target,
            "after": after,
        }

    if kind in _BOOL_AFTER_EFFECT_KINDS:
        if not _is_plain_bool(after):
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_EFFECT_AFTER_INVALID:"
                + kind
            )

        if (
            kind == EFFECT_READONLY_CHANGED
            and target["semantic_kind"]
            not in _READONLY_SEMANTIC_KINDS
        ):
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_READONLY_SEMANTIC_GUARD:"
                + target["semantic_kind"]
            )

        return {
            "kind": kind,
            "target": target,
            "after": after,
        }

    if kind == EFFECT_CONTROL_DISAPPEARED:
        return {
            "kind": kind,
            "target": target,
            "after": None,
        }

    # EFFECT_SELECTION_CHANGED: structural delegation only. Never
    # carries selected_value/selected_indexes into the runtime
    # payload.
    return {
        "kind": kind,
        "target": target,
        "owner": SELECTION_CHANGED_OWNER,
    }


def _canonical_effect_tuple(effect):
    target = effect["target"]

    if effect["kind"] == EFFECT_SELECTION_CHANGED:
        return (
            effect["kind"],
            target["control_key"],
            target["frame_path"],
            target["selector"],
            target["semantic_kind"],
        )

    return (
        effect["kind"],
        target["control_key"],
        target["frame_path"],
        target["selector"],
        target["semantic_kind"],
        effect.get("after"),
    )


def _build_route(entry):
    _reject_contextual_shape(entry)

    state_id = _validate_state_id(entry.get("state_id"))

    action = _validate_action(entry.get("action"))

    mutation_identity = _validate_mutation_identity(
        action["kind"],
        entry.get("mutation_identity"),
    )

    raw_effects = entry.get("effects") or ()

    if not isinstance(raw_effects, (list, tuple)):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_EFFECTS_INVALID"
        )

    effects = tuple(
        _validate_effect(effect)
        for effect in raw_effects
    )

    trigger_key = (
        state_id,
        action["kind"],
        action["selector"],
        action["frame_path"],
        _mutation_identity_key(mutation_identity),
    )

    canonical_result = tuple(
        sorted(
            _canonical_effect_tuple(effect)
            for effect in effects
        )
    )

    blocked_effect_kinds = tuple(
        sorted({
            effect["kind"]
            for effect in effects
            if effect["kind"] in BLOCKED_EFFECT_KINDS
        })
    )

    if blocked_effect_kinds:
        status = ROUTE_STATUS_BLOCKED
        executable_effects = ()
        delegated_effects = ()
    else:
        status = ROUTE_STATUS_EXECUTABLE

        executable_effects = tuple(
            {
                "kind": effect["kind"],
                "target": effect["target"],
                "after": effect["after"],
            }
            for effect in effects
            if effect["kind"] in EXECUTABLE_EFFECT_KINDS
        )

        delegated_effects = tuple(
            {
                "kind": effect["kind"],
                "owner": effect["owner"],
                "target": effect["target"],
            }
            for effect in effects
            if effect["kind"] in DELEGATED_EFFECT_KINDS
        )

    route = {
        "trigger": {
            "state_id": state_id,
            "action": action,
            "mutation_identity": mutation_identity,
        },

        "status": status,

        "blocked_effect_kinds": blocked_effect_kinds,

        "executable_effects": executable_effects,

        "delegated_effects": delegated_effects,
    }

    return trigger_key, canonical_result, route


def build_form_effect_runtime_payload(evidence_records) -> dict:
    """Construye el payload determinista de rutas del Form Effect Runtime.

    ``evidence_records`` es un iterable de entradas normalizadas de
    evidencia B2/B3-1A, cada una con ``state_id``, ``action``,
    ``mutation_identity`` y ``effects``. No ejecuta navegador alguno.
    """

    if not isinstance(evidence_records, (list, tuple)):
        raise FormEffectRuntimeError(
            "FORM_EFFECT_RUNTIME_EVIDENCE_RECORDS_INVALID"
        )

    routes_by_trigger = {}

    for entry in evidence_records:
        if not isinstance(entry, dict):
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_EVIDENCE_ENTRY_INVALID"
            )

        trigger_key, canonical_result, route = _build_route(
            entry
        )

        existing = routes_by_trigger.get(trigger_key)

        if existing is None:
            routes_by_trigger[trigger_key] = (
                canonical_result,
                route,
            )
            continue

        existing_canonical_result, _existing_route = existing

        if existing_canonical_result != canonical_result:
            raise FormEffectRuntimeError(
                "FORM_EFFECT_RUNTIME_CONFLICTING_TRIGGER"
            )

        # Identical evidence for an already known trigger: deduplicate.

    ordered_keys = sorted(
        routes_by_trigger,
        key=lambda key: tuple(
            str(part) for part in key
        ),
    )

    routes = tuple(
        routes_by_trigger[key][1]
        for key in ordered_keys
    )

    return {
        "schema_version":
            FORM_EFFECT_RUNTIME_SCHEMA_VERSION,

        "record_type":
            FORM_EFFECT_RUNTIME_RECORD_TYPE,

        "contextual_effects":
            CONTEXTUAL_EFFECTS_V1,

        "route_count":
            len(routes),

        "routes":
            routes,
    }


# ------------------------------------------------------------------
# Pure browser adapter (UWT-6B3-1B)
#
# Generic, payload-agnostic JavaScript. Reads a runtime payload built
# by ``build_form_effect_runtime_payload`` and replays its EXECUTABLE
# routes only. Never performs navigation or network access. Never
# removes elements from the DOM.
# ------------------------------------------------------------------

AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION = 1

AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER = (
    "data-qcc-auto-twin-form-effect-runtime"
)

AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID = (
    "qcc-auto-twin-form-effect-runtime-payload"
)

FORM_EFFECT_RUNTIME_ADAPTER_JS = r"""
(function () {
  "use strict";

  var STATUS_EXECUTABLE = "EXECUTABLE";

  var EFFECT_VISIBILITY_CHANGED = "VISIBILITY_CHANGED";
  var EFFECT_DISABLED_CHANGED = "DISABLED_CHANGED";
  var EFFECT_READONLY_CHANGED = "READONLY_CHANGED";
  var EFFECT_REQUIRED_CHANGED = "REQUIRED_CHANGED";
  var EFFECT_CHECKED_CHANGED = "CHECKED_CHANGED";
  var EFFECT_CONTROL_DISAPPEARED = "CONTROL_DISAPPEARED";

  var VISIBILITY_HIDDEN_ATTR =
    "data-qcc-auto-twin-form-effect-hidden";
  var VISIBILITY_FORCED_VISIBLE_ATTR =
    "data-qcc-auto-twin-form-effect-forced-visible";
  var STYLE_ELEMENT_ATTR =
    "data-qcc-auto-twin-form-effect-style";

  function ensureStyle() {
    if (document.querySelector("style[" + STYLE_ELEMENT_ATTR + "]")) {
      return;
    }

    var style = document.createElement("style");
    style.setAttribute(STYLE_ELEMENT_ATTR, "1");
    style.textContent =
      "[" + VISIBILITY_HIDDEN_ATTR + '="1"] {\n' +
      "  display: none !important;\n" +
      "  visibility: hidden !important;\n" +
      "}\n" +
      "[" + VISIBILITY_FORCED_VISIBLE_ATTR + '="1"] {\n' +
      "  display: revert !important;\n" +
      "  visibility: visible !important;\n" +
      "  opacity: 1 !important;\n" +
      "}\n";

    (document.head || document.documentElement).appendChild(style);
  }

  function resolveUnique(selector) {
    if (typeof selector !== "string" || selector === "") {
      return null;
    }

    var nodes;

    try {
      nodes = document.querySelectorAll(selector);
    } catch (error) {
      return null;
    }

    if (nodes.length !== 1) {
      return null;
    }

    return nodes[0];
  }

  function deriveSelectedIndex(element) {
    if (!element || typeof element.selectedIndex !== "number") {
      return null;
    }

    return element.selectedIndex;
  }

  function deriveChecked(element) {
    if (!element || typeof element.checked !== "boolean") {
      return null;
    }

    return element.checked;
  }

  function matchesTrigger(sourceElement, trigger) {
    var kind = trigger.action.kind;
    var identity = trigger.mutation_identity;

    if (kind === "SELECT") {
      var selectedIndex = deriveSelectedIndex(sourceElement);

      return (
        selectedIndex !== null &&
        selectedIndex === identity.selected_index
      );
    }

    var checked = deriveChecked(sourceElement);

    return checked !== null && checked === identity.checked;
  }

  function applyVisibilityChanged(targetElement, after) {
    ensureStyle();

    if (after === false) {
      targetElement.setAttribute(VISIBILITY_HIDDEN_ATTR, "1");
      targetElement.removeAttribute(VISIBILITY_FORCED_VISIBLE_ATTR);
      return;
    }

    targetElement.setAttribute(VISIBILITY_FORCED_VISIBLE_ATTR, "1");
    targetElement.removeAttribute(VISIBILITY_HIDDEN_ATTR);
  }

  function applyControlDisappeared(targetElement) {
    ensureStyle();
    targetElement.setAttribute(VISIBILITY_HIDDEN_ATTR, "1");
    targetElement.removeAttribute(VISIBILITY_FORCED_VISIBLE_ATTR);
  }

  function applyDisabledChanged(targetElement, after) {
    targetElement.disabled = after;
  }

  function applyReadonlyChanged(targetElement, after) {
    targetElement.readOnly = after;
  }

  function applyRequiredChanged(targetElement, after) {
    targetElement.required = after;
  }

  function applyCheckedChanged(targetElement, after) {
    if (targetElement.checked === after) {
      return;
    }

    targetElement.checked = after;

    var eventInit = { bubbles: true };

    targetElement.dispatchEvent(new Event("input", eventInit));
    targetElement.dispatchEvent(new Event("change", eventInit));
  }

  function applyExecutableEffect(effect) {
    var targetElement = resolveUnique(effect.target.selector);

    if (!targetElement) {
      return;
    }

    switch (effect.kind) {
      case EFFECT_VISIBILITY_CHANGED:
        applyVisibilityChanged(targetElement, effect.after);
        return;

      case EFFECT_CONTROL_DISAPPEARED:
        applyControlDisappeared(targetElement);
        return;

      case EFFECT_DISABLED_CHANGED:
        applyDisabledChanged(targetElement, effect.after);
        return;

      case EFFECT_READONLY_CHANGED:
        applyReadonlyChanged(targetElement, effect.after);
        return;

      case EFFECT_REQUIRED_CHANGED:
        applyRequiredChanged(targetElement, effect.after);
        return;

      case EFFECT_CHECKED_CHANGED:
        applyCheckedChanged(targetElement, effect.after);
        return;

      default:
        return;
    }
  }

  function applyRoute(route) {
    if (route.status !== STATUS_EXECUTABLE) {
      return;
    }

    var sourceElement = resolveUnique(route.trigger.action.selector);

    if (!sourceElement) {
      return;
    }

    if (!matchesTrigger(sourceElement, route.trigger)) {
      return;
    }

    var effects = route.executable_effects || [];

    for (var index = 0; index < effects.length; index += 1) {
      applyExecutableEffect(effects[index]);
    }
  }

  function readPayload() {
    var element = document.getElementById(
      "qcc-auto-twin-form-effect-runtime-payload"
    );

    if (!element) {
      return null;
    }

    try {
      return JSON.parse(element.textContent || "");
    } catch (error) {
      return null;
    }
  }

  function run() {
    var payload = readPayload();

    if (!payload || !Array.isArray(payload.routes)) {
      return;
    }

    for (var index = 0; index < payload.routes.length; index += 1) {
      applyRoute(payload.routes[index]);
    }
  }

  function bindSourceListeners() {
    var payload = readPayload();

    if (!payload || !Array.isArray(payload.routes)) {
      return;
    }

    var seenSelectors = {};

    payload.routes.forEach(function (route) {
      var selector = route.trigger.action.selector;

      if (seenSelectors[selector]) {
        return;
      }

      seenSelectors[selector] = true;

      var sourceElement = resolveUnique(selector);

      if (!sourceElement) {
        return;
      }

      sourceElement.addEventListener("change", run);
      sourceElement.addEventListener("input", run);
    });
  }

  function boot() {
    run();
    bindSourceListeners();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
"""


def form_effect_runtime_adapter_source():
    return (
        FORM_EFFECT_RUNTIME_ADAPTER_JS
        + "\n"
    )

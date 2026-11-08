"use strict";

/*
 * QCC_ASSISTED_READINESS_JS_V6: behavioural/syntax harness for the
 * EX01 personal-data readiness JS predicate
 * (``app.run_presentacion_asistida._field_readiness_js`` /
 * ``_ex01_personal_ready_js``).
 *
 * Executes the REAL production script text -- exactly as
 * ``backend.automation.browser_actions.wait_for_js``'s ``js()``
 * helper builds it (``return !!(<condition>);``) -- against a
 * minimal mocked live DOM, so a genuine JS parser (not a Python
 * substring check) proves the composed predicate is valid AND
 * behaves as expected.
 *
 *   node qcc_ex01_readiness_js_harness.js '<payload-json>'
 *
 * payload: {
 *   "script": "<full 'return !!(...);' script text>",
 *   "elements": { "<fieldId>": { "disabled": bool, "visible": bool } }
 * }
 *
 * On success prints "RESULT::true" or "RESULT::false" and exits 0.
 * A malformed (non-expression) script throws a SyntaxError at
 * `new Function(...)` construction time, which Node reports with a
 * non-zero exit code -- exactly what a real browser would do.
 */

const payload = JSON.parse(process.argv[2]);

function makeElement(spec) {
  const disabled = !!(spec && spec.disabled);
  const visible = !spec || spec.visible !== false;

  return {
    disabled,
    _visible: visible,
    offsetWidth: visible ? 100 : 0,
    offsetHeight: visible ? 20 : 0,
    getClientRects() {
      return visible ? [{}] : [];
    },
    getAttribute(name) {
      if (name === "aria-hidden") {
        return visible ? null : "true";
      }
      return null;
    },
    closest() {
      return null;
    },
  };
}

const elements = {};
for (const [id, spec] of Object.entries((payload && payload.elements) || {})) {
  elements[id] = makeElement(spec);
}

global.document = {
  getElementById(id) {
    return Object.prototype.hasOwnProperty.call(elements, id)
      ? elements[id]
      : null;
  },
};

global.window = {
  getComputedStyle(el) {
    return {
      display: el._visible ? "block" : "none",
      visibility: el._visible ? "visible" : "hidden",
    };
  },
};

const fn = new Function(payload.script);
const result = fn();

process.stdout.write("RESULT::" + JSON.stringify(!!result) + "\n");

"""Hidratación gobernada de formulario Twin — AUTO TWIN (UWT-6A2).

Responsabilidad:

    MaterializedRevision (states/registry.json)
        ↓
    qcc_capture.json persistido (source_capture_id)
        ↓
    build_form_runtime_hydration_plan()
        ↓
    navegador SeleniumBase gobernado ya abierto en el Twin
        ↓
    evidencia estructurada de ejecución

Este servicio:

- NO navega REAL;
- NO captura REAL;
- NO materializa;
- NO activa revisiones;
- NO crea branches;
- NO infiere valores de negocio;
- NO persiste valores de runtime en ningún lugar.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from backend.automation import browser_actions
from backend.automation.site_architecture import (
    adapt_qcc_extension_capture,
)
from backend.qcc.auto_twin.form_runtime_hydration import (
    RUNTIME_KIND_CHECKBOX,
    RUNTIME_KIND_FILE,
    RUNTIME_KIND_HIDDEN,
    RUNTIME_KIND_RADIO,
    RUNTIME_KIND_SELECT,
    RUNTIME_KIND_TEXT,
    RUNTIME_KIND_TEXTAREA,
    build_form_runtime_hydration_plan,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

DEFAULT_MATERIALIZED_ROOT = (
    PROJECT_ROOT
    / "data"
    / "qcc"
    / "auto_twin"
    / "materialized"
)

DEFAULT_SITE_ARCHITECTURE_ROOT = (
    PROJECT_ROOT
    / "data"
    / "qcc"
    / "site_architecture"
)


TWIN_FORM_RUNTIME_HYDRATION_RESULT_SCHEMA_VERSION = 1

RUNTIME_VALUES_PERSISTED = "NO"


_SAFE_SEGMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


_BOOL_CONSTRAINTS = (
    "required",
    "readonly",
    "disabled",
    "multiple",
)

_STRING_CONSTRAINTS = (
    "pattern",
    "min",
    "max",
    "step",
    "minlength",
    "maxlength",
    "placeholder",
    "autocomplete",
)


def _segment(value, *, error):
    value = str(value or "").strip()

    if not _SAFE_SEGMENT.fullmatch(value):
        raise ValueError(error)

    return value


def _read_json(path, *, error):
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )

    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc

    if not isinstance(value, dict):
        raise ValueError(error)

    return value


class TwinFormRuntimeService:
    """Owner de hidratación gobernada de formulario Twin."""

    def __init__(
        self,
        *,
        materialized_root=None,
        site_architecture_root=None,
    ):
        self.materialized_root = Path(
            materialized_root
            or DEFAULT_MATERIALIZED_ROOT
        )

        self.site_architecture_root = Path(
            site_architecture_root
            or DEFAULT_SITE_ARCHITECTURE_ROOT
        )

    # ------------------------------------------------------------
    # Evidence resolution + pure plan construction
    # ------------------------------------------------------------

    def _resolve_source_capture_id(
        self,
        *,
        twin_key,
        revision_id,
        state_id,
    ):
        twin_key = _segment(
            twin_key,
            error="QCC_TWIN_FORM_RUNTIME_TWIN_KEY_INVALID",
        )

        revision_id = _segment(
            revision_id,
            error="QCC_TWIN_FORM_RUNTIME_REVISION_ID_INVALID",
        )

        requested_state_id = str(
            state_id or ""
        ).strip()

        if not requested_state_id:
            raise ValueError(
                "QCC_TWIN_FORM_RUNTIME_STATE_ID_REQUIRED"
            )

        registry_path = (
            self.materialized_root
            / twin_key
            / revision_id
            / "runtime"
            / "registry.json"
        )

        if not registry_path.is_file():
            raise FileNotFoundError(
                "QCC_TWIN_FORM_RUNTIME_REGISTRY_NOT_FOUND:"
                + revision_id
            )

        registry = _read_json(
            registry_path,
            error="QCC_TWIN_FORM_RUNTIME_REGISTRY_INVALID",
        )

        states = registry.get("states")

        if not isinstance(states, list):
            raise ValueError(
                "QCC_TWIN_FORM_RUNTIME_REGISTRY_STATES_INVALID"
            )

        matches = [
            state
            for state in states
            if (
                isinstance(state, dict)
                and str(
                    state.get("state_id") or ""
                ).strip()
                == requested_state_id
            )
        ]

        if not matches:
            raise KeyError(
                "QCC_TWIN_FORM_RUNTIME_STATE_ID_NOT_FOUND:"
                + requested_state_id
            )

        if len(matches) != 1:
            raise ValueError(
                "QCC_TWIN_FORM_RUNTIME_STATE_ID_AMBIGUOUS:"
                + requested_state_id
            )

        source_capture_id = str(
            matches[0].get("source_capture_id") or ""
        ).strip()

        if not source_capture_id:
            raise ValueError(
                "QCC_TWIN_FORM_RUNTIME_SOURCE_CAPTURE_ID_MISSING"
            )

        return source_capture_id

    def load_hydration_plan(
        self,
        *,
        twin_key,
        revision_id,
        state_id,
    ) -> dict:
        """Resuelve evidencia qcc_capture inmutable y construye el plan."""

        source_capture_id = (
            self._resolve_source_capture_id(
                twin_key=twin_key,
                revision_id=revision_id,
                state_id=state_id,
            )
        )

        capture_path = (
            self.site_architecture_root
            / source_capture_id
            / "qcc_capture.json"
        )

        if not capture_path.is_file():
            raise FileNotFoundError(
                "QCC_TWIN_FORM_RUNTIME_CAPTURE_NOT_FOUND:"
                + source_capture_id
            )

        raw_capture = _read_json(
            capture_path,
            error="QCC_TWIN_FORM_RUNTIME_CAPTURE_INVALID",
        )

        dom_capture_payload = (
            adapt_qcc_extension_capture(
                raw_capture
            )
        )

        return build_form_runtime_hydration_plan(
            dom_capture_payload
        )

    # ------------------------------------------------------------
    # Governed SeleniumBase execution
    # ------------------------------------------------------------

    def _audit_constraints(self, *, browser, operation):
        constraints = (
            operation.get("form_constraints")
            or {}
        )

        bool_map = {
            name: True
            for name in _BOOL_CONSTRAINTS
            if constraints.get(name) is True
        }

        string_map = {
            name: constraints.get(name)
            for name in _STRING_CONSTRAINTS
            if constraints.get(name) is not None
        }

        if not bool_map and not string_map:
            return ()

        script = (
            "(function(){"
            "const el=document.querySelector("
            + json.dumps(operation["selector"])
            + ");"
            "if(!el)return [];"
            "const restored=[];"
            "const boolAttrs="
            + json.dumps(bool_map)
            + ";"
            "const stringAttrs="
            + json.dumps(string_map)
            + ";"
            "for(const name in boolAttrs){"
            "if(boolAttrs[name] && !el.hasAttribute(name)){"
            "el.setAttribute(name,'');"
            "restored.push(name);"
            "}"
            "}"
            "for(const name in stringAttrs){"
            "if(el.getAttribute(name)!==stringAttrs[name]){"
            "el.setAttribute(name,stringAttrs[name]);"
            "restored.push(name);"
            "}"
            "}"
            "return restored;"
            "})();"
        )

        result = browser_actions.js(
            browser,
            script,
        )

        if not isinstance(result, list):
            return ()

        return tuple(
            str(item) for item in result
        )

    def _apply_operation(
        self,
        *,
        browser,
        operation,
        runtime_values,
    ):
        """Returns (applied, captured_state_restored, runtime_value_applied)."""

        kind = operation["kind"]
        selector = operation["selector"]
        control_key = operation["control_key"]
        form_state = operation.get("form_state") or {}

        if kind in (
            RUNTIME_KIND_TEXT,
            RUNTIME_KIND_TEXTAREA,
        ):
            if operation.get("requires_runtime_value"):
                value = runtime_values.get(control_key)

                if value is not None:
                    browser.type(selector, str(value))
                    return True, False, True

            return False, False, False

        if kind == RUNTIME_KIND_HIDDEN:
            value = runtime_values.get(control_key)

            if value is not None:
                browser.set_value(selector, str(value))
                return True, False, True

            return False, False, False

        if kind == RUNTIME_KIND_CHECKBOX:
            target = form_state.get("checked")

            if target is True:
                browser.check_if_unchecked(selector)
                return True, True, False

            if target is False:
                browser.uncheck_if_checked(selector)
                return True, True, False

            return False, False, False

        if kind == RUNTIME_KIND_RADIO:
            target = form_state.get("checked")

            if target is True:
                if not browser.is_checked(selector):
                    browser.click(selector)

                return True, True, False

            return False, False, False

        if kind == RUNTIME_KIND_SELECT:
            selected_values = (
                form_state.get("selected_values")
                or ()
            )

            if not selected_values:
                return False, False, False

            for value in selected_values:
                browser.select_option_by_value(
                    selector,
                    value,
                )

            return True, True, False

        if kind == RUNTIME_KIND_FILE:
            if operation.get("requires_runtime_file"):
                path = runtime_values.get(control_key)

                if path:
                    element = browser.find_element(
                        selector
                    )

                    element.send_file(str(path))
                    return True, False, True

            return False, False, False

        return False, False, False

    def apply_hydration_plan(
        self,
        *,
        browser,
        plan,
        runtime_values=None,
        state_id=None,
    ) -> dict:
        """Ejecuta un plan ya construido contra un Twin ya abierto."""

        normalized_runtime_values = dict(
            runtime_values or {}
        )

        operations_applied = 0
        captured_state_restored = 0
        runtime_values_applied = 0

        unresolved = []
        errors = []

        for operation in plan.get("operations") or ():
            control_key = operation["control_key"]
            kind = operation["kind"]

            if not operation.get("addressable"):
                unresolved.append({
                    "control_key": control_key,
                    "kind": kind,
                    "reason": "SELECTOR_UNRESOLVED",
                })

                continue

            try:
                (
                    applied,
                    restored,
                    value_applied,
                ) = self._apply_operation(
                    browser=browser,
                    operation=operation,
                    runtime_values=(
                        normalized_runtime_values
                    ),
                )

                self._audit_constraints(
                    browser=browser,
                    operation=operation,
                )

            except Exception as exc:
                errors.append({
                    "control_key": control_key,
                    "kind": kind,
                    "error": type(exc).__name__,
                })

                continue

            if applied:
                operations_applied += 1

            if restored:
                captured_state_restored += 1

            if value_applied:
                runtime_values_applied += 1

        return {
            "schema_version":
                TWIN_FORM_RUNTIME_HYDRATION_RESULT_SCHEMA_VERSION,

            "state_id":
                state_id,

            "operations_total":
                int(
                    plan.get("operation_count")
                    or 0
                ),

            "operations_applied":
                operations_applied,

            "captured_state_restored":
                captured_state_restored,

            "runtime_values_applied":
                runtime_values_applied,

            "unresolved":
                tuple(unresolved),

            "errors":
                tuple(errors),
        }

    def hydrate(
        self,
        *,
        browser,
        twin_key,
        revision_id,
        state_id,
        runtime_values=None,
    ) -> dict:
        """Construye y ejecuta el plan de hidratación de un Twin abierto."""

        plan = self.load_hydration_plan(
            twin_key=twin_key,
            revision_id=revision_id,
            state_id=state_id,
        )

        return self.apply_hydration_plan(
            browser=browser,
            plan=plan,
            runtime_values=runtime_values,
            state_id=state_id,
        )


def get_default_twin_form_runtime_service():
    return TwinFormRuntimeService()

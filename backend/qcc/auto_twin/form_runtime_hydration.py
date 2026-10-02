"""Plan de hidratación de runtime de formulario — AUTO TWIN (UWT-6A2).

Proyección pura, determinista y neutral respecto al proveedor que
convierte evidencia QCC Site Architecture (form_state/form_constraints/
selectors/semantics) en un plan de operaciones de hidratación para un
navegador SeleniumBase gobernado.

No ejecuta SeleniumBase. No navega. No decide branching. No persiste
valores literales del cliente.
"""

from __future__ import annotations

import hashlib

from backend.automation.site_architecture import (
    normalize_dom_capture,
)
from backend.automation.site_architecture.form_state import (
    is_relevant_form_control,
)


FORM_RUNTIME_HYDRATION_PLAN_SCHEMA_VERSION = 1

FORM_RUNTIME_HYDRATION_PLAN_RECORD_TYPE = (
    "QCC_AUTO_TWIN_FORM_RUNTIME_HYDRATION_PLAN"
)

FORM_RUNTIME_HYDRATION_FRAME_SCOPE_MAIN = "MAIN"

MAIN_FRAME_PATH = "main"


RUNTIME_KIND_TEXT = "TEXT"
RUNTIME_KIND_TEXTAREA = "TEXTAREA"
RUNTIME_KIND_SELECT = "SELECT"
RUNTIME_KIND_CHECKBOX = "CHECKBOX"
RUNTIME_KIND_RADIO = "RADIO"
RUNTIME_KIND_FILE = "FILE"
RUNTIME_KIND_HIDDEN = "HIDDEN"


RUNTIME_POLICY_NONE = "NONE"
RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE = (
    "SUPPLY_SYNTHETIC_VALUE"
)
RUNTIME_POLICY_PRESERVE_EXISTING = (
    "PRESERVE_EXISTING"
)
RUNTIME_POLICY_RESTORE_CAPTURED_STATE = (
    "RESTORE_CAPTURED_STATE"
)
RUNTIME_POLICY_REQUIRE_EXTERNAL_FILE = (
    "REQUIRE_EXTERNAL_FILE"
)


_SEMANTIC_TO_KIND = {
    "TEXT_INPUT": RUNTIME_KIND_TEXT,
    "TEXTAREA": RUNTIME_KIND_TEXTAREA,
    "SELECT": RUNTIME_KIND_SELECT,
    "CHECKBOX": RUNTIME_KIND_CHECKBOX,
    "RADIO": RUNTIME_KIND_RADIO,
    "FILE_INPUT": RUNTIME_KIND_FILE,
    "HIDDEN_INPUT": RUNTIME_KIND_HIDDEN,
}

# Priority order when an element exposes more than one relevant
# semantic (should not normally happen, but resolution must stay
# deterministic rather than depend on set iteration order).
_KIND_PRIORITY = (
    "RADIO",
    "CHECKBOX",
    "FILE_INPUT",
    "SELECT",
    "HIDDEN_INPUT",
    "TEXTAREA",
    "TEXT_INPUT",
)


def _css_attribute_value(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def _element_frame_path(element):
    return str(
        element.get("frame_path")
        or MAIN_FRAME_PATH
    )


def _element_attributes(element):
    value = element.get("attributes") or {}

    if not isinstance(value, dict):
        return {}

    return value


def _attribute_text(element, name):
    text = str(
        _element_attributes(element).get(name)
        or ""
    ).strip()

    return text or None


def _element_kind(element):
    semantics = {
        str(value).strip().upper()
        for value in (
            element.get("semantics") or ()
        )
        if str(value).strip()
    }

    for semantic in _KIND_PRIORITY:
        if semantic in semantics:
            return _SEMANTIC_TO_KIND[semantic]

    return None


def _selector_profile(element):
    value = element.get("selectors") or {}

    if not isinstance(value, dict):
        return {}

    return value


def _control_key(
    *,
    frame_path,
    kind,
    selector,
    option_value,
):
    canonical = "|".join((
        "QCC_FORM_RUNTIME_CONTROL_KEY_V1",
        frame_path or MAIN_FRAME_PATH,
        kind or "",
        selector or "",
        option_value or "",
    ))

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _group_siblings(elements, *, frame_path, kind, name):
    for item in elements:
        if not isinstance(item, dict):
            continue

        if _element_frame_path(item) != frame_path:
            continue

        if _element_kind(item) != kind:
            continue

        if _attribute_text(item, "name") != name:
            continue

        yield item


def _resolve_group_selector(
    *,
    element,
    elements,
    frame_path,
    kind,
):
    """Permitted fallback for RADIO/CHECKBOX groups sharing one name.

    A shared group selector combined with this element's own option
    value may become addressable even when neither the group selector
    nor the option value is individually unique on the page. See
    WO QCC_UWT6A2_GOVERNED_FORM_RUNTIME_HYDRATION Section 8.
    """

    name = _attribute_text(element, "name")
    option_value = _attribute_text(element, "value")

    if not name or option_value is None:
        return None

    candidates = (
        _selector_profile(element).get("candidates")
        or ()
    )

    name_candidate = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("strategy") == "NAME"
        ),
        None,
    )

    if name_candidate is None:
        return None

    siblings_with_same_value = [
        sibling
        for sibling in _group_siblings(
            elements,
            frame_path=frame_path,
            kind=kind,
            name=name,
        )
        if _attribute_text(sibling, "value")
        == option_value
    ]

    if len(siblings_with_same_value) != 1:
        return None

    group_selector = str(
        name_candidate.get("selector") or ""
    ).strip()

    if not group_selector:
        return None

    compound_selector = (
        group_selector
        + '[value="'
        + _css_attribute_value(option_value)
        + '"]'
    )

    return {
        "selector": compound_selector,
        "selector_confidence": "MEDIUM",
        "option_value": option_value,
    }


def _resolve_addressability(
    *,
    element,
    elements,
    frame_path,
    kind,
):
    profile = _selector_profile(element)
    primary = profile.get("primary")

    if isinstance(primary, dict) and primary.get(
        "selector"
    ):
        return {
            "addressable": True,
            "selector": str(primary["selector"]),
            "selector_confidence": primary.get(
                "confidence"
            ),
            "option_value": (
                _attribute_text(element, "value")
                if kind in (
                    RUNTIME_KIND_RADIO,
                    RUNTIME_KIND_CHECKBOX,
                )
                else None
            ),
        }

    if kind in (
        RUNTIME_KIND_RADIO,
        RUNTIME_KIND_CHECKBOX,
    ):
        fallback = _resolve_group_selector(
            element=element,
            elements=elements,
            frame_path=frame_path,
            kind=kind,
        )

        if fallback is not None:
            return {
                "addressable": True,
                **fallback,
            }

    return {
        "addressable": False,
        "selector": None,
        "selector_confidence": None,
        "option_value": (
            _attribute_text(element, "value")
            if kind in (
                RUNTIME_KIND_RADIO,
                RUNTIME_KIND_CHECKBOX,
            )
            else None
        ),
    }


def _runtime_requirements(
    *,
    kind,
    form_state,
):
    requires_runtime_value = False
    requires_runtime_file = False
    runtime_policy = RUNTIME_POLICY_NONE

    if kind in (
        RUNTIME_KIND_TEXT,
        RUNTIME_KIND_TEXTAREA,
    ):
        if form_state.get("has_value") is True:
            requires_runtime_value = True
            runtime_policy = (
                RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE
            )

    elif kind == RUNTIME_KIND_HIDDEN:
        runtime_policy = (
            RUNTIME_POLICY_PRESERVE_EXISTING
        )

    elif kind == RUNTIME_KIND_FILE:
        if form_state.get("file_selected") is True:
            requires_runtime_file = True
            runtime_policy = (
                RUNTIME_POLICY_REQUIRE_EXTERNAL_FILE
            )

    elif kind in (
        RUNTIME_KIND_SELECT,
        RUNTIME_KIND_CHECKBOX,
        RUNTIME_KIND_RADIO,
    ):
        runtime_policy = (
            RUNTIME_POLICY_RESTORE_CAPTURED_STATE
        )

    return {
        "requires_runtime_value":
            requires_runtime_value,

        "requires_runtime_file":
            requires_runtime_file,

        "runtime_policy":
            runtime_policy,
    }


def _build_operation(*, element, elements, kind):
    frame_path = _element_frame_path(element)

    form_state = dict(
        element.get("form_state") or {}
    )

    form_constraints = dict(
        element.get("form_constraints") or {}
    )

    addressability = _resolve_addressability(
        element=element,
        elements=elements,
        frame_path=frame_path,
        kind=kind,
    )

    requirements = _runtime_requirements(
        kind=kind,
        form_state=form_state,
    )

    control_key = _control_key(
        frame_path=frame_path,
        kind=kind,
        selector=addressability["selector"],
        option_value=addressability["option_value"],
    )

    return {
        "control_key": control_key,

        "kind": kind,

        "frame_path": frame_path,

        "addressable":
            addressability["addressable"],

        "selector":
            addressability["selector"],

        "selector_confidence":
            addressability["selector_confidence"],

        "option_value":
            addressability["option_value"],

        "form_state": form_state,

        "form_constraints": form_constraints,

        **requirements,
    }


def _unsupported_frame_entry(element, kind):
    return {
        "frame_path": _element_frame_path(element),
        "kind": kind,
        "status": "UNSUPPORTED_FRAME",
    }


def build_form_runtime_hydration_plan(
    qcc_capture_payload,
) -> dict:
    """Construye un plan de hidratación determinista main-frame-only.

    ``qcc_capture_payload`` es el payload DOM_CAPTURE de QCC Site
    Architecture (el mismo formato que consume
    ``normalize_dom_capture``). Nunca ejecuta SeleniumBase ni decide
    identidad funcional/branching.
    """

    snapshot = normalize_dom_capture(
        qcc_capture_payload
    )

    elements = snapshot.elements

    operations = []
    unsupported_frame_controls = []

    for element in elements:
        if not isinstance(element, dict):
            continue

        if not is_relevant_form_control(element):
            continue

        kind = _element_kind(element)

        if kind is None:
            continue

        if (
            _element_frame_path(element)
            != MAIN_FRAME_PATH
        ):
            unsupported_frame_controls.append(
                _unsupported_frame_entry(
                    element,
                    kind,
                )
            )

            continue

        operations.append(
            _build_operation(
                element=element,
                elements=elements,
                kind=kind,
            )
        )

    return {
        "schema_version":
            FORM_RUNTIME_HYDRATION_PLAN_SCHEMA_VERSION,

        "record_type":
            FORM_RUNTIME_HYDRATION_PLAN_RECORD_TYPE,

        "frame_scope":
            FORM_RUNTIME_HYDRATION_FRAME_SCOPE_MAIN,

        "operation_count":
            len(operations),

        "operations":
            tuple(operations),

        "unsupported_frame_control_count":
            len(unsupported_frame_controls),

        "unsupported_frame_controls":
            tuple(unsupported_frame_controls),
    }

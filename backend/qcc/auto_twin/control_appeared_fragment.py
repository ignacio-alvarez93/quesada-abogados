"""CONTROL_APPEARED fragment extraction — AUTO TWIN runtime replay.

Extracts and minimizes ONLY the structural subtree that
``backend.automation.site_architecture.dynamic_form_effects`` already
reported as a ``CONTROL_APPEARED`` effect, addressed exclusively by
that effect's own already-resolved unique primary selector.

PURE: never opens a browser, never navigates and never captures DOM
itself. The raw REAL AFTER capture HTML (``document.documentElement
.outerHTML``) is supplied by the caller — this module never persists
that full document, only the single matched element's own subtree.

Reuses (READ ONLY) the existing Runtime Network Sterilization
authority (``runtime_network_sterilization.sterilize_runtime_html``)
instead of inventing a second execution/network safety engine.
"""

from __future__ import annotations

from lxml import html as lxml_html
from lxml.cssselect import CSSSelector

from .runtime_network_sterilization import sterilize_runtime_html


CONTROL_APPEARED_FRAGMENT_SCHEMA_VERSION = 1

FRAGMENT_STATUS_CAPTURED = "CAPTURED"
FRAGMENT_STATUS_UNRESOLVED = "UNRESOLVED"

# Input types whose "value" attribute is a static option/control
# identity (never a user-typed runtime literal) and therefore must be
# preserved for structural/selector fidelity rather than stripped.
_STATIC_VALUE_INPUT_TYPES = frozenset({
    "checkbox",
    "radio",
    "button",
    "submit",
    "reset",
    "image",
    "file",
})

_CHECKABLE_INPUT_TYPES = frozenset({
    "checkbox",
    "radio",
})


def _text(value):
    return str(value or "").strip()


def _unresolved():
    return {
        "status": FRAGMENT_STATUS_UNRESOLVED,
        "html": None,
    }


def _captured(html_text):
    return {
        "status": FRAGMENT_STATUS_CAPTURED,
        "html": html_text,
    }


def _select_unique_element(after_html, selector):
    try:
        tree = lxml_html.fromstring(after_html)
    except Exception:
        return None

    try:
        compiled_selector = CSSSelector(selector)
    except Exception:
        return None

    try:
        matches = compiled_selector(tree)
    except Exception:
        return None

    if len(matches) != 1:
        return None

    return matches[0]


def _minimize_element(element):
    """Strips observed REAL runtime values from ONE element, in place.

    Never touches structural identity (tag/id/name/class/other static
    attributes) — only the minimum mutable-runtime-value categories
    this slice must protect.
    """

    tag = (
        element.tag.lower()
        if isinstance(element.tag, str)
        else ""
    )

    if tag == "input":
        input_type = _text(element.get("type")).lower() or "text"

        if (
            input_type not in _STATIC_VALUE_INPUT_TYPES
            and element.get("value") is not None
        ):
            del element.attrib["value"]

        if (
            input_type in _CHECKABLE_INPUT_TYPES
            and element.get("checked") is not None
        ):
            del element.attrib["checked"]

    elif tag == "textarea":
        if element.text or len(element):
            element.text = ""

            for child in list(element):
                element.remove(child)

    elif tag == "option":
        if element.get("selected") is not None:
            del element.attrib["selected"]

    contenteditable = element.get("contenteditable")

    if (
        contenteditable is not None
        and _text(contenteditable).lower() != "false"
        and (element.text or len(element))
    ):
        element.text = ""

        for child in list(element):
            element.remove(child)


def _minimize_runtime_values(root_element):
    for element in root_element.iter():
        if not isinstance(element.tag, str):
            continue

        _minimize_element(element)


def build_control_appeared_fragment(*, after_html, selector):
    """Builds the privacy-safe, network-sterile CONTROL_APPEARED fragment.

    ``after_html`` is the raw, transient REAL AFTER capture document
    HTML. ``selector`` is the already-resolved unique primary CSS
    selector of the appeared control (the same selector persisted as
    ``target.selector`` by the structural effect evidence). Fails
    closed to ``FRAGMENT_STATUS_UNRESOLVED`` whenever the selector
    cannot be matched to EXACTLY ONE element — never guesses, never
    falls back to document order.
    """

    after_html_text = (
        after_html
        if isinstance(after_html, str)
        else ""
    )

    selector_text = _text(selector)

    if not after_html_text.strip() or not selector_text:
        return _unresolved()

    element = _select_unique_element(
        after_html_text,
        selector_text,
    )

    if element is None:
        return _unresolved()

    _minimize_runtime_values(element)

    minimized_html = lxml_html.tostring(
        element,
        encoding="unicode",
    )

    sterilized_html, _sterilization_stats = sterilize_runtime_html(
        minimized_html
    )

    return _captured(sterilized_html)

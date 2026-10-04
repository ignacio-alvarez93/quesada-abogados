"""Regression for QCC_AUTO_TWIN_NAVIGATION_ONCLICK_STRUCTURAL_IDENTITY_V1.

Root cause:

selectors.py deliberately strips onclick literal arguments into a
PII-free structural signature before it is ever persisted as a
navigation transition's action.selector (e.g. the physical attribute
onclick="continuar('INI');" becomes the durable selector
a[onclick="continuar();"] -- see QCC_ONCLICK_STRUCTURAL_SIGNATURE_V1
in backend/automation/site_architecture/selectors.py).

restore_navigation_action_identity() compared that structural selector
value against the RAW captured/materialized onclick attribute using
plain string equality. Any handler observed with a real literal
argument therefore never equalled its own stripped selector, so both
the QCC-evidence match and the runtime-DOM conflict check failed
closed as QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS /
QCC_AUTO_TWIN_NAVIGATION_RUNTIME_EVENT_CONFLICT -- even though exactly
one physical element genuinely owns the action.

Fix: onclick identity comparisons (both the QCC-evidence match and the
runtime-DOM existing-attribute conflict check) now compare structural
signatures for the onclick attribute specifically, reusing the exact
same transform selectors.py used to build the selector
(onclick_structural_signature()). Every other on* attribute keeps
exact literal comparison; a genuine mismatch (different handler, or
two distinct physical elements) still fails closed exactly as before.
"""

from backend.automation.site_architecture.selectors import (
    onclick_structural_signature,
)

import pytest

from backend.qcc.auto_twin.navigation_transition_runtime import (
    restore_navigation_action_identity,
)


# The real Mercurio selector/attribute pair from the confirmed
# operational evidence: a structural selector with the literal
# argument stripped, against a physical element whose onclick
# genuinely carries one.
STRUCTURAL_SELECTOR = 'a[onclick="continuar();"]'
PHYSICAL_ONCLICK = "continuar('INI');"


def test_onclick_structural_signature_strips_literal_argument():
    """Sanity: the selector value is indeed the structural form."""

    assert (
        onclick_structural_signature(PHYSICAL_ONCLICK)
        == "continuar();"
    )


def test_literal_argument_onclick_resolves_to_structural_selector():
    """A single physical element carrying the real literal argument
    resolves to exactly one evidence match and its identity is
    restored, instead of being excluded as ambiguous."""

    source_html = (
        "<html><body>"
        f'<a href="#" onclick="{PHYSICAL_ONCLICK}">Continuar</a>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "Continuar",
                            "attributes": {
                                "href": "#",
                                "onclick": PHYSICAL_ONCLICK,
                            },
                        },
                    ],
                },
            },
        ],
    }

    transitions = (
        {
            "action": {
                "selector": STRUCTURAL_SELECTOR,
            },
        },
    )

    restored = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    # The attribute already carries the literal argument: no conflict,
    # no fabricated rewrite, and the original literal is preserved.
    assert PHYSICAL_ONCLICK in restored

    # Idempotent: re-running restoration changes nothing further.
    restored_again = restore_navigation_action_identity(
        restored,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    assert restored_again == restored


def test_non_onclick_event_attribute_keeps_exact_literal_comparison():
    """Control: the structural relaxation is onclick-specific. A
    genuinely different onchange value must still fail closed as
    ambiguous, never silently accepted."""

    source_html = (
        '<html><body><select onchange="otraCosa();"></select>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "select",
                            "text": "",
                            "attributes": {
                                "onchange": "otraCosa();",
                            },
                        },
                    ],
                },
            },
        ],
    }

    transitions = (
        {
            "action": {
                "selector": 'select[onchange="cambiar();"]',
            },
        },
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS",
    ):
        restore_navigation_action_identity(
            source_html,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )


def test_two_distinct_onclick_literals_sharing_structural_signature_stay_ambiguous():
    """Two physically distinct elements whose onclick literals collapse
    to the SAME structural signature but are genuinely different
    physical controls must still fail closed -- the fix must never
    fabricate uniqueness that the evidence does not support."""

    source_html = (
        "<html><body>"
        '<a id="go1" onclick="continuar(\'INI\');">Continuar 1</a>'
        '<a id="go2" onclick="continuar(\'OTRA\');">Continuar 2</a>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "Continuar 1",
                            "attributes": {
                                "id": "go1",
                                "onclick": "continuar('INI');",
                            },
                        },
                        {
                            "tag": "a",
                            "text": "Continuar 2",
                            "attributes": {
                                "id": "go2",
                                "onclick": "continuar('OTRA');",
                            },
                        },
                    ],
                },
            },
        ],
    }

    transitions = (
        {
            "action": {
                "selector": STRUCTURAL_SELECTOR,
            },
        },
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS",
    ):
        restore_navigation_action_identity(
            source_html,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )


def test_runtime_onclick_literal_mismatch_still_conflicts():
    """Control: once exactly one QCC-evidence element is resolved, a
    materialized runtime DOM node whose onclick is a genuinely
    different handler (not just a different literal argument of the
    SAME handler) must still raise RUNTIME_EVENT_CONFLICT. The
    structural fallback must not blur distinct handlers together."""

    source_html = (
        "<html><body>"
        '<a href="#" onclick="otraFuncion();">Continuar</a>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "Continuar",
                            "attributes": {
                                "href": "#",
                                "onclick": PHYSICAL_ONCLICK,
                            },
                        },
                    ],
                },
            },
        ],
    }

    transitions = (
        {
            "action": {
                "selector": STRUCTURAL_SELECTOR,
            },
        },
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_NAVIGATION_RUNTIME_EVENT_CONFLICT",
    ):
        restore_navigation_action_identity(
            source_html,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )

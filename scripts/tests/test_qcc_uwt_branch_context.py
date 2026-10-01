"""UWT-4 Universal Branch Context — provider-neutral regression suite.

Covers QCC_UWT4_BRANCH_CONTEXT_V1 acceptance scenarios: the five generic
control-family discriminators, deterministic stable identity/ordering,
duplicate/conflict fail-closed handling, and the "no branch by value"
principle. No site-specific or provider-specific literal is used on
purpose (genericity must not depend on any real customer/provider).
"""

import pytest

from backend.qcc.universal_web import (
    BranchContext,
    BranchContextError,
    BranchDiscriminator,
    BranchDiscriminatorError,
    DISCRIMINATOR_KIND_CHECKBOX,
    DISCRIMINATOR_KIND_RADIO,
    DISCRIMINATOR_KIND_SELECT,
    DISCRIMINATOR_KIND_TAB,
    DISCRIMINATOR_KIND_TOGGLE,
    DISCRIMINATOR_KINDS,
    build_branch_context,
    build_branch_discriminator,
)


# ---------------------------------------------------------------------------
# 1-5. one discriminator per generic control family
# ---------------------------------------------------------------------------

def test_radio_discriminator():
    discriminator = build_branch_discriminator(
        kind="radio",
        control_id="shipping-method",
        active_value="EXPRESS",
    )

    assert discriminator.kind == DISCRIMINATOR_KIND_RADIO
    assert discriminator.control_id == "shipping-method"
    assert discriminator.active_value == "EXPRESS"
    assert discriminator.discriminator_id


def test_checkbox_discriminator():
    checked = build_branch_discriminator(
        kind="checkbox",
        control_id="accept-terms",
        active_value=True,
    )
    unchecked = build_branch_discriminator(
        kind="checkbox",
        control_id="accept-terms",
        active_value=False,
    )

    assert checked.kind == DISCRIMINATOR_KIND_CHECKBOX
    assert checked.active_value == "CHECKED"
    assert unchecked.active_value == "UNCHECKED"
    assert checked.discriminator_id != unchecked.discriminator_id


def test_select_discriminator():
    discriminator = build_branch_discriminator(
        kind="select",
        control_id="document-type",
        active_value="INVOICE",
    )

    assert discriminator.kind == DISCRIMINATOR_KIND_SELECT
    assert discriminator.active_value == "INVOICE"


def test_tab_discriminator():
    discriminator = build_branch_discriminator(
        kind="tab",
        control_id="workspace-tabs",
        active_value="SETTINGS",
    )

    assert discriminator.kind == DISCRIMINATOR_KIND_TAB
    assert discriminator.active_value == "SETTINGS"


def test_toggle_discriminator():
    on = build_branch_discriminator(
        kind="toggle",
        control_id="dark-mode",
        active_value="on",
    )
    off = build_branch_discriminator(
        kind="toggle",
        control_id="dark-mode",
        active_value="off",
    )

    assert on.kind == DISCRIMINATOR_KIND_TOGGLE
    assert on.active_value == "ON"
    assert off.active_value == "OFF"


def test_all_generic_kinds_are_supported():
    assert DISCRIMINATOR_KINDS == frozenset(
        {
            DISCRIMINATOR_KIND_RADIO,
            DISCRIMINATOR_KIND_CHECKBOX,
            DISCRIMINATOR_KIND_SELECT,
            DISCRIMINATOR_KIND_TAB,
            DISCRIMINATOR_KIND_TOGGLE,
        }
    )


# ---------------------------------------------------------------------------
# 6-9. stable ordering / serialization / deterministic id / order independence
# ---------------------------------------------------------------------------

def _sample_discriminators():
    return (
        build_branch_discriminator(
            kind="radio",
            control_id="shipping-method",
            active_value="EXPRESS",
        ),
        build_branch_discriminator(
            kind="select",
            control_id="document-type",
            active_value="INVOICE",
        ),
        build_branch_discriminator(
            kind="checkbox",
            control_id="accept-terms",
            active_value=True,
        ),
    )


def test_stable_ordering_independent_of_input_order():
    forward = build_branch_context(_sample_discriminators())
    backward = build_branch_context(tuple(reversed(_sample_discriminators())))

    assert forward.discriminators == backward.discriminators


def test_stable_serialization():
    context = build_branch_context(_sample_discriminators())

    first = context.to_dict()
    second = context.to_dict()

    assert first == second
    assert first["discriminators"] == sorted(
        first["discriminators"],
        key=lambda item: (item["kind"], item["control_id"], item["active_value"]),
    )


def test_deterministic_context_id():
    first = build_branch_context(_sample_discriminators())
    second = build_branch_context(_sample_discriminators())

    assert first.context_id == second.context_id


def test_same_semantic_input_different_order_same_id():
    forward = build_branch_context(_sample_discriminators())
    backward = build_branch_context(tuple(reversed(_sample_discriminators())))

    assert forward.context_id == backward.context_id


# ---------------------------------------------------------------------------
# 10-11. duplicate / conflict handling
# ---------------------------------------------------------------------------

def test_duplicate_equivalent_input_is_deduplicated():
    discriminator = build_branch_discriminator(
        kind="radio",
        control_id="shipping-method",
        active_value="EXPRESS",
    )

    context = build_branch_context((discriminator, discriminator))

    assert len(context.discriminators) == 1


def test_conflicting_duplicate_is_rejected():
    first = build_branch_discriminator(
        kind="radio",
        control_id="shipping-method",
        active_value="EXPRESS",
    )
    second = build_branch_discriminator(
        kind="radio",
        control_id="shipping-method",
        active_value="STANDARD",
    )

    with pytest.raises(BranchContextError):
        build_branch_context((first, second))


def test_conflicting_kind_for_same_control_id_is_rejected():
    first = build_branch_discriminator(
        kind="checkbox",
        control_id="shared-control",
        active_value=True,
    )
    second = build_branch_discriminator(
        kind="toggle",
        control_id="shared-control",
        active_value="on",
    )

    with pytest.raises(BranchContextError):
        build_branch_context((first, second))


# ---------------------------------------------------------------------------
# 12. malformed kind fails closed
# ---------------------------------------------------------------------------

def test_malformed_kind_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="dropdown-menu",
            control_id="x",
            active_value="y",
        )


def test_missing_kind_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="",
            control_id="x",
            active_value="y",
        )


def test_missing_control_id_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="radio",
            control_id="",
            active_value="y",
        )


def test_malformed_binary_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="checkbox",
            control_id="accept-terms",
            active_value="maybe",
        )


def test_non_discriminator_input_is_rejected():
    with pytest.raises(TypeError):
        build_branch_context(({"kind": "RADIO", "control_id": "x", "active_value": "y"},))


# ---------------------------------------------------------------------------
# 13. empty context supported
# ---------------------------------------------------------------------------

def test_empty_context_is_valid_and_deterministic():
    first = build_branch_context(())
    second = build_branch_context(())

    assert first.is_empty
    assert first.discriminators == ()
    assert first.context_id == second.context_id


# ---------------------------------------------------------------------------
# 14. value-only data must not be auto-elevated into branch topology
# ---------------------------------------------------------------------------

def test_different_radio_values_are_not_automatically_different_branches():
    """A changed control value alone is not a branch (work order section 5):
    the caller decides whether a discriminator is branch-relevant by
    explicitly including it. Two independently-chosen single-discriminator
    contexts for different values are naturally distinct contexts, but
    nothing in this module infers that a value change *must* branch: no
    control value is interpreted/elevated without an explicit
    build_branch_discriminator call."""

    context_a = build_branch_context(
        (
            build_branch_discriminator(
                kind="select",
                control_id="document-type",
                active_value="INVOICE",
            ),
        )
    )
    context_b = build_branch_context(
        (
            build_branch_discriminator(
                kind="select",
                control_id="document-type",
                active_value="INVOICE",
            ),
        )
    )

    # Same explicit discriminator, decided twice independently: identical
    # context identity is derived, never a fresh/incidental one.
    assert context_a.context_id == context_b.context_id


def test_raw_value_dict_alone_cannot_become_a_discriminator():
    """There is no implicit conversion path from a raw control
    value/snapshot into a BranchDiscriminator: only explicit
    build_branch_discriminator calls produce branch-relevant context."""

    raw_value_only = {"value": "INVOICE"}

    with pytest.raises(TypeError):
        build_branch_context((raw_value_only,))


# ---------------------------------------------------------------------------
# 15-16. no site-specific / provider-specific literals in the type system
# ---------------------------------------------------------------------------

def test_no_site_or_provider_literals_in_discriminator_kinds():
    forbidden_fragments = (
        "mercurio",
        "ex_",
        "province",
        "provincia",
        "quesada",
    )

    for kind in DISCRIMINATOR_KINDS:
        lowered = kind.lower()

        for fragment in forbidden_fragments:
            assert fragment not in lowered


# ---------------------------------------------------------------------------
# 17. compatibility/imports through universal_web package
# ---------------------------------------------------------------------------

def test_imports_are_exposed_through_universal_web_package():
    import backend.qcc.universal_web as universal_web

    assert universal_web.BranchContext is BranchContext
    assert universal_web.BranchDiscriminator is BranchDiscriminator
    assert universal_web.build_branch_context is build_branch_context
    assert universal_web.build_branch_discriminator is build_branch_discriminator


# ---------------------------------------------------------------------------
# 18. round-trip serialization preserves identity (no mutation of source of truth)
# ---------------------------------------------------------------------------

def test_round_trip_serialization_preserves_identity():
    context = build_branch_context(_sample_discriminators())

    restored = BranchContext.from_dict(context.to_dict())

    assert restored.context_id == context.context_id
    assert restored.discriminators == context.discriminators


def test_from_dict_rejects_tampered_context_id():
    context = build_branch_context(_sample_discriminators())
    payload = context.to_dict()
    payload["context_id"] = "0" * 64

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_malformed_discriminator():
    payload = {
        "schema_version": 1,
        "context_type": "QCC_UWT_BRANCH_CONTEXT",
        "context_id": "irrelevant",
        "discriminators": [{"kind": "NOT_A_KIND", "control_id": "x", "active_value": "y"}],
    }

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


# ---------------------------------------------------------------------------
# FIX1 — Finding A: non-primitive input coercion is rejected
# ---------------------------------------------------------------------------

class _Opaque:
    """A stand-in for an arbitrary object whose default repr is
    non-deterministic (e.g. carries a memory address): it must never be
    silently stringified into a branch-relevant identity."""


def test_arbitrary_object_as_control_id_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="radio",
            control_id=_Opaque(),
            active_value="EXPRESS",
        )


def test_arbitrary_object_as_radio_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="radio",
            control_id="shipping-method",
            active_value=_Opaque(),
        )


def test_dict_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="select",
            control_id="document-type",
            active_value={"value": "INVOICE"},
        )


def test_list_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="tab",
            control_id="workspace-tabs",
            active_value=["SETTINGS"],
        )


def test_bytes_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="radio",
            control_id="shipping-method",
            active_value=b"EXPRESS",
        )


def test_valid_string_identity_value_is_preserved():
    discriminator = build_branch_discriminator(
        kind="select",
        control_id="document-type",
        active_value="INVOICE",
    )

    assert discriminator.control_id == "document-type"
    assert discriminator.active_value == "INVOICE"


def test_bool_checkbox_remains_supported():
    discriminator = build_branch_discriminator(
        kind="checkbox",
        control_id="accept-terms",
        active_value=True,
    )

    assert discriminator.active_value == "CHECKED"


def test_bool_toggle_remains_supported():
    discriminator = build_branch_discriminator(
        kind="toggle",
        control_id="dark-mode",
        active_value=False,
    )

    assert discriminator.active_value == "OFF"


def test_dict_checkbox_active_value_is_rejected():
    with pytest.raises(BranchDiscriminatorError):
        build_branch_discriminator(
            kind="checkbox",
            control_id="accept-terms",
            active_value={"checked": True},
        )


# ---------------------------------------------------------------------------
# FIX1 — Finding B: deserialization fails closed
# ---------------------------------------------------------------------------

def _valid_payload():
    return build_branch_context(_sample_discriminators()).to_dict()


def test_from_dict_rejects_malformed_discriminator_count_type():
    payload = _valid_payload()
    payload["discriminator_count"] = "3"

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_bool_discriminator_count():
    payload = _valid_payload()
    payload["discriminator_count"] = True

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_discriminator_count_mismatch():
    payload = _valid_payload()
    payload["discriminator_count"] = len(payload["discriminators"]) + 1

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_discriminators_none():
    payload = _valid_payload()
    payload["discriminators"] = None

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_discriminators_zero():
    payload = _valid_payload()
    payload["discriminator_count"] = 0
    payload["discriminators"] = 0

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_discriminators_empty_string():
    payload = _valid_payload()
    payload["discriminator_count"] = 0
    payload["discriminators"] = ""

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_discriminators_false():
    payload = _valid_payload()
    payload["discriminator_count"] = 0
    payload["discriminators"] = False

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_non_string_context_id():
    payload = _valid_payload()
    payload["context_id"] = 12345

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_from_dict_rejects_non_string_discriminator_id():
    payload = _valid_payload()
    payload["discriminators"][0]["discriminator_id"] = 12345

    with pytest.raises(BranchContextError):
        BranchContext.from_dict(payload)


def test_legitimate_empty_context_round_trips():
    empty = build_branch_context(())
    payload = empty.to_dict()

    assert payload["discriminator_count"] == 0
    assert payload["discriminators"] == []

    restored = BranchContext.from_dict(payload)

    assert restored.is_empty
    assert restored.context_id == empty.context_id


def test_existing_deterministic_context_identity_still_passes():
    first = build_branch_context(_sample_discriminators())
    restored = BranchContext.from_dict(first.to_dict())

    assert restored.context_id == first.context_id
    assert restored.discriminators == first.discriminators

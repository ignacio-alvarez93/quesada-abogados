import json

import pytest

from backend.automation.site_architecture import (
    normalize_dom_capture,
)
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
    build_dynamic_form_effect_evidence,
)


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _payload(elements, catalogs=()):
    return {
        "schema_version": 1,
        "captured_at": "2026-10-02T10:00:00.000Z",

        "metadata": {
            "url": "https://example.test/form",
            "origin": "https://example.test",
            "pathname": "/form",
            "title": "Form test",
            "ready_state": "complete",
        },

        "documents": [],
        "frames": [],
        "shadows": [],
        "catalogs": list(catalogs),
        "counts": {},

        "elements": elements,
    }


def _snapshot(elements, catalogs=()):
    return normalize_dom_capture(
        _payload(elements, catalogs)
    )


def _action(**overrides):
    action = {
        "kind": "CLICK",
        "selector": "#trigger",
        "frame_path": "main",
        "policy": "STATE_CHANGE_CANDIDATE",
    }

    action.update(overrides)

    return action


def _text_input(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "field",
        "name": "field",
        "type": "text",
        "role": "",
        "attributes": {
            "id": "field",
            "name": "field",
            "type": "text",
        },
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


def _checkbox(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "accepts-terms",
        "name": "accepts-terms",
        "type": "checkbox",
        "role": "",
        "attributes": {
            "id": "accepts-terms",
            "name": "accepts-terms",
            "type": "checkbox",
        },
        "checked": False,
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


def _radio(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "option-a",
        "name": "option",
        "type": "radio",
        "role": "",
        "attributes": {
            "id": "option-a",
            "name": "option",
            "type": "radio",
        },
        "checked": False,
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


def _select(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "select",
        "id": "province",
        "name": "province",
        "type": "",
        "role": "",
        "attributes": {
            "id": "province",
            "name": "province",
        },
        "options": [
            {"value": "33", "text": "Asturias", "selected": False},
            {"value": "28", "text": "Madrid", "selected": False},
        ],
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


def _button(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "button",
        "id": "continue-action",
        "name": "",
        "type": "button",
        "role": "button",
        "attributes": {
            "id": "continue-action",
            "type": "button",
            "role": "button",
        },
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


def _effects_of_kind(result, kind):
    return tuple(
        effect
        for effect in result["form_effects"]
        if effect["kind"] == kind
    )


# ---------------------------------------------------------------------------
# 1. no observable effect
# ---------------------------------------------------------------------------

def test_no_observable_effect_returns_empty_record():
    element = _text_input(
        form_signals={"has_value": True},
    )

    before = _snapshot([element])
    after = _snapshot([element])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    assert result["effect_count"] == 0
    assert result["form_effects"] == ()
    assert result["inconclusive"] is False


# ---------------------------------------------------------------------------
# 2 / 3. visibility change
# ---------------------------------------------------------------------------

def test_visibility_false_to_true():
    before = _snapshot([
        _text_input(visible=False),
    ])

    after = _snapshot([
        _text_input(visible=True),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_VISIBILITY_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


def test_visibility_true_to_false():
    before = _snapshot([
        _text_input(visible=True),
    ])

    after = _snapshot([
        _text_input(visible=False),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_VISIBILITY_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is True
    assert effects[0]["after"] is False


# ---------------------------------------------------------------------------
# 4. interactable change
# ---------------------------------------------------------------------------

def test_interactable_change():
    before = _snapshot([
        _text_input(
            visible=True,
            interaction_signals={"in_viewport": False},
        ),
    ])

    after = _snapshot([
        _text_input(
            visible=True,
            interaction_signals={"in_viewport": True},
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_INTERACTABLE_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


# ---------------------------------------------------------------------------
# 5. disabled false -> true and reverse
# ---------------------------------------------------------------------------

def test_disabled_false_to_true():
    before = _snapshot([
        _text_input(disabled=False),
    ])

    after = _snapshot([
        _text_input(disabled=True),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_DISABLED_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


def test_disabled_true_to_false():
    before = _snapshot([
        _text_input(disabled=True),
    ])

    after = _snapshot([
        _text_input(disabled=False),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_DISABLED_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is True
    assert effects[0]["after"] is False


# ---------------------------------------------------------------------------
# 6. readonly false -> true
# ---------------------------------------------------------------------------

def test_readonly_false_to_true():
    before = _snapshot([
        _text_input(
            interaction_signals={"readonly": False},
        ),
    ])

    after = _snapshot([
        _text_input(
            interaction_signals={"readonly": True},
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_READONLY_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


# ---------------------------------------------------------------------------
# 7. required false -> true
# ---------------------------------------------------------------------------

def test_required_false_to_true():
    before = _snapshot([
        _text_input(
            form_signals={"required": False},
        ),
    ])

    after = _snapshot([
        _text_input(
            form_signals={"required": True},
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_REQUIRED_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


# ---------------------------------------------------------------------------
# 8. text has_value false -> true WITHOUT literal text
# ---------------------------------------------------------------------------

def test_has_value_false_to_true_without_literal_text():
    before = _snapshot([
        _text_input(
            form_signals={"has_value": False},
        ),
    ])

    after = _snapshot([
        _text_input(
            attributes={
                "id": "field",
                "name": "field",
                "type": "text",
                "value": "Juan Perez",
            },
            form_signals={"has_value": True},
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_HAS_VALUE_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True

    serialized = json.dumps(result)
    assert "Juan Perez" not in serialized


# ---------------------------------------------------------------------------
# 9. checkbox checked false -> true
# ---------------------------------------------------------------------------

def test_checkbox_checked_false_to_true():
    before = _snapshot([
        _checkbox(checked=False),
    ])

    after = _snapshot([
        _checkbox(checked=True),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_CHECKED_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


# ---------------------------------------------------------------------------
# 10. radio checked state change
# ---------------------------------------------------------------------------

def test_radio_checked_state_change():
    before = _snapshot([
        _radio(checked=False),
    ])

    after = _snapshot([
        _radio(checked=True),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_CHECKED_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is False
    assert effects[0]["after"] is True


# ---------------------------------------------------------------------------
# 11. select selection changes
# ---------------------------------------------------------------------------

def test_select_selection_changes():
    before = _snapshot([
        _select(
            options=[
                {"value": "33", "text": "Asturias", "selected": True},
                {"value": "28", "text": "Madrid", "selected": False},
            ],
        ),
    ])

    after = _snapshot([
        _select(
            options=[
                {"value": "33", "text": "Asturias", "selected": False},
                {"value": "28", "text": "Madrid", "selected": True},
            ],
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_SELECTION_CHANGED,
    )

    assert len(effects) == 1
    assert effects[0]["before"]["selected_values"] == ("33",)
    assert effects[0]["before"]["selected_indexes"] == (0,)
    assert effects[0]["after"]["selected_values"] == ("28",)
    assert effects[0]["after"]["selected_indexes"] == (1,)


# ---------------------------------------------------------------------------
# 12 / 13. control appeared / disappeared
# ---------------------------------------------------------------------------

def test_control_appeared():
    before = _snapshot([])

    after = _snapshot([
        _button(id="new-action"),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_CONTROL_APPEARED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is None
    assert effects[0]["after"] is True


def test_control_disappeared():
    before = _snapshot([
        _button(id="removed-action"),
    ])

    after = _snapshot([])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_CONTROL_DISAPPEARED,
    )

    assert len(effects) == 1
    assert effects[0]["before"] is True
    assert effects[0]["after"] is None


# ---------------------------------------------------------------------------
# 14. reordered element arrays do not create false appeared/disappeared
# ---------------------------------------------------------------------------

def test_reordered_elements_do_not_create_false_appeared_disappeared():
    control_a = _text_input(
        index=0,
        id="field-a",
        name="field-a",
        attributes={
            "id": "field-a",
            "name": "field-a",
            "type": "text",
        },
    )

    control_b = _text_input(
        index=1,
        id="field-b",
        name="field-b",
        attributes={
            "id": "field-b",
            "name": "field-b",
            "type": "text",
        },
    )

    before = _snapshot([control_a, control_b])
    after = _snapshot([control_b, control_a])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    assert result["effect_count"] == 0
    assert result["form_effects"] == ()


# ---------------------------------------------------------------------------
# 15. ambiguous/unaddressable controls are not falsely paired
# ---------------------------------------------------------------------------

def test_ambiguous_controls_are_not_falsely_paired():
    ambiguous_one = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "",
        "name": "shared",
        "type": "text",
        "role": "",
        "attributes": {
            "name": "shared",
            "type": "text",
        },
        "visible": True,
        "disabled": False,
        "form_signals": {"has_value": False},
    }

    ambiguous_two = dict(ambiguous_one)
    ambiguous_two["index"] = 1
    ambiguous_two["form_signals"] = {"has_value": True}

    before = _snapshot([ambiguous_one, ambiguous_two])
    after = _snapshot([ambiguous_one, ambiguous_two])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    assert result["effect_count"] == 0
    assert result["inconclusive"] is True
    assert len(result["unresolved"]) > 0


# ---------------------------------------------------------------------------
# 16. deterministic ordering
# ---------------------------------------------------------------------------

def test_deterministic_ordering():
    before = _snapshot([
        _checkbox(
            id="checkbox-z",
            name="checkbox-z",
            attributes={
                "id": "checkbox-z",
                "name": "checkbox-z",
                "type": "checkbox",
            },
            checked=False,
        ),
        _text_input(
            id="field-a",
            name="field-a",
            attributes={
                "id": "field-a",
                "name": "field-a",
                "type": "text",
            },
            disabled=False,
        ),
    ])

    after = _snapshot([
        _checkbox(
            id="checkbox-z",
            name="checkbox-z",
            attributes={
                "id": "checkbox-z",
                "name": "checkbox-z",
                "type": "checkbox",
            },
            checked=True,
        ),
        _text_input(
            id="field-a",
            name="field-a",
            attributes={
                "id": "field-a",
                "name": "field-a",
                "type": "text",
            },
            disabled=True,
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    keys = tuple(
        (effect["target"]["control_key"], effect["kind"])
        for effect in result["form_effects"]
    )

    assert keys == tuple(sorted(keys))
    assert len(keys) >= 2


# ---------------------------------------------------------------------------
# 17. repeated identical input gives equal result
# ---------------------------------------------------------------------------

def test_repeated_identical_input_gives_equal_result():
    before = _snapshot([
        _checkbox(checked=False),
    ])

    after = _snapshot([
        _checkbox(checked=True),
    ])

    first = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    second = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    assert first == second


# ---------------------------------------------------------------------------
# 18. action is mandatory
# ---------------------------------------------------------------------------

def test_action_is_mandatory():
    before = _snapshot([_text_input()])
    after = _snapshot([_text_input()])

    with pytest.raises(ValueError):
        build_dynamic_form_effect_evidence(
            before,
            after,
            action=None,
        )

    with pytest.raises(ValueError):
        build_dynamic_form_effect_evidence(
            before,
            after,
            action={},
        )


# ---------------------------------------------------------------------------
# 19. action value/free text is not projected
# ---------------------------------------------------------------------------

def test_action_free_text_is_not_projected():
    before = _snapshot([_text_input()])
    after = _snapshot([_text_input()])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(
            typed_value="SECRET_TYPED_CANARY",
            password="SECRET_PASSWORD_CANARY",
        ),
    )

    assert set(result["action"].keys()) == {
        "kind",
        "selector",
        "frame_path",
        "policy",
        "resolved",
    }

    serialized = json.dumps(result)
    assert "SECRET_TYPED_CANARY" not in serialized
    assert "SECRET_PASSWORD_CANARY" not in serialized


# ---------------------------------------------------------------------------
# 20. privacy canaries absent from serialized result
# ---------------------------------------------------------------------------

def test_privacy_canaries_absent_from_serialized_result():
    before = _snapshot([
        _text_input(
            id="person-name",
            name="person-name",
            attributes={
                "id": "person-name",
                "name": "person-name",
                "type": "text",
            },
            form_signals={"has_value": False},
        ),
        _text_input(
            id="person-nie",
            name="person-nie",
            attributes={
                "id": "person-nie",
                "name": "person-nie",
                "type": "text",
            },
            form_signals={"has_value": False},
        ),
        _text_input(
            id="person-password",
            name="person-password",
            type="password",
            attributes={
                "id": "person-password",
                "name": "person-password",
                "type": "password",
            },
            form_signals={"has_value": False},
        ),
    ])

    after = _snapshot([
        _text_input(
            id="person-name",
            name="person-name",
            attributes={
                "id": "person-name",
                "name": "person-name",
                "type": "text",
                "value": "PERSON_NAME_CANARY_92A",
            },
            form_signals={"has_value": True},
        ),
        _text_input(
            id="person-nie",
            name="person-nie",
            attributes={
                "id": "person-nie",
                "name": "person-nie",
                "type": "text",
                "value": "NIE_CANARY_X1234567",
            },
            form_signals={"has_value": True},
        ),
        _text_input(
            id="person-password",
            name="person-password",
            type="password",
            attributes={
                "id": "person-password",
                "name": "person-password",
                "type": "password",
                "value": "SECRET_PASSWORD_CANARY",
            },
            form_signals={"has_value": True},
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    assert result["effect_count"] == 3

    serialized = json.dumps(result)

    assert "PERSON_NAME_CANARY_92A" not in serialized
    assert "NIE_CANARY_X1234567" not in serialized
    assert "SECRET_PASSWORD_CANARY" not in serialized


# ---------------------------------------------------------------------------
# 21 / 22. source_catalog_key delegates to catalog_dynamics
# ---------------------------------------------------------------------------

def _catalog(key_selector, *, value, label, options):
    return {
        "frame_path": "main",
        "selector": key_selector,
        "element": {"id": key_selector.lstrip("#")},
        "state": {
            "selected_value": value,
            "selected_label": label,
            "selected_values": ([value] if value else []),
            "selected_index": 0,
        },
        "options": [
            {
                "value": option_value,
                "label": option_label,
                "disabled": False,
            }
            for (option_value, option_label) in options
        ],
    }


def test_source_catalog_key_delegates_to_catalog_dynamics():
    before_catalogs = [
        _catalog(
            "#parent",
            value="A",
            label="A",
            options=[("A", "A"), ("B", "B")],
        ),
        _catalog(
            "#child",
            value="1",
            label="Uno",
            options=[("1", "Uno"), ("2", "Dos")],
        ),
    ]

    after_catalogs = [
        _catalog(
            "#parent",
            value="B",
            label="B",
            options=[("A", "A"), ("B", "B")],
        ),
        _catalog(
            "#child",
            value="",
            label="--",
            options=[("", "--"), ("9", "Nueve")],
        ),
    ]

    before = _snapshot([], catalogs=before_catalogs)
    after = _snapshot([], catalogs=after_catalogs)

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
        source_catalog_key="main::#parent",
    )

    assert "catalog_dynamic_evidence" in result
    assert "catalog_causal_relations" in result

    dynamic_kinds = tuple(
        item["kind"]
        for item in result["catalog_dynamic_evidence"]
    )

    assert "SOURCE_SELECTION_CHANGED" in dynamic_kinds
    assert "CATALOG_OPTIONS_CHANGED" in dynamic_kinds

    relations = tuple(
        item["relation"]
        for item in result["catalog_causal_relations"]
    )

    assert "INFLUENCES" in relations
    assert "DEPENDS_ON" in relations


# ---------------------------------------------------------------------------
# 23. unchanged source catalog remains fail-closed
# ---------------------------------------------------------------------------

def test_unchanged_source_catalog_remains_fail_closed():
    catalogs = [
        _catalog(
            "#source",
            value="1",
            label="Uno",
            options=[("1", "Uno")],
        ),
    ]

    before = _snapshot([], catalogs=catalogs)
    after = _snapshot([], catalogs=catalogs)

    with pytest.raises(
        ValueError,
        match="CATALOG_DYNAMIC_SOURCE_UNCHANGED",
    ):
        build_dynamic_form_effect_evidence(
            before,
            after,
            action=_action(),
            source_catalog_key="main::#source",
        )


# ---------------------------------------------------------------------------
# 24. selected structural option codes may appear without branching
# ---------------------------------------------------------------------------

def test_selected_option_codes_do_not_create_branching_authority():
    before = _snapshot([
        _select(
            options=[
                {"value": "33", "text": "Asturias", "selected": True},
                {"value": "28", "text": "Madrid", "selected": False},
            ],
        ),
    ])

    after = _snapshot([
        _select(
            options=[
                {"value": "33", "text": "Asturias", "selected": False},
                {"value": "28", "text": "Madrid", "selected": True},
            ],
        ),
    ])

    result = build_dynamic_form_effect_evidence(
        before,
        after,
        action=_action(),
    )

    effects = _effects_of_kind(
        result,
        EFFECT_SELECTION_CHANGED,
    )

    assert effects[0]["after"]["selected_values"] == ("28",)

    assert "branch_context" not in result
    assert "functional_state" not in result
    assert "state_graph" not in result


# ---------------------------------------------------------------------------
# 25. provider / site neutrality
# ---------------------------------------------------------------------------

def test_dynamic_form_effects_module_has_no_site_specific_logic():
    source_path = (
        "backend/automation/site_architecture/dynamic_form_effects.py"
    )

    with open(source_path, encoding="utf-8") as handle:
        content = handle.read().lower()

    forbidden = (
        "mercurio",
        "ex01",
        "datosforaut",
        "gsup_",
        "red sara",
        "dehú",
        "dehu",
    )

    for token in forbidden:
        assert token not in content

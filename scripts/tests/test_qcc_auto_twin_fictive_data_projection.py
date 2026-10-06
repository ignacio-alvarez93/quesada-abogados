"""Regression for safe fictive-data projection — AUTO TWIN (UWT-8).

Proves the projector never needs, never reads and never reveals any
REAL captured literal, is fully deterministic (replay/test
reproducibility), always lands clearly outside the REAL network
(RFC 2606 ``.invalid`` email domain), and respects the generic
length constraints already captured by Site Architecture.
"""

import pytest

from backend.qcc.auto_twin.fictive_data_projection import (
    FICTIVE_EMAIL_DOMAIN,
    project_fictive_text_value,
)


def test_control_key_required():
    with pytest.raises(ValueError):
        project_fictive_text_value(
            control_key="",
            form_constraints=None,
        )


def test_deterministic_same_control_key_same_value():
    first = project_fictive_text_value(
        control_key="control-key-abc",
        form_constraints={"autocomplete": "given-name"},
    )

    second = project_fictive_text_value(
        control_key="control-key-abc",
        form_constraints={"autocomplete": "given-name"},
    )

    assert first == second


def test_distinct_control_keys_project_distinct_values():
    first = project_fictive_text_value(
        control_key="control-key-abc",
    )

    second = project_fictive_text_value(
        control_key="control-key-xyz",
    )

    assert first != second


def test_generic_value_never_empty_and_marked_fictive():
    value = project_fictive_text_value(
        control_key="control-key-generic",
    )

    assert value
    assert "fictive" in value.lower()


def test_email_category_uses_reserved_invalid_domain():
    value = project_fictive_text_value(
        control_key="control-key-email",
        form_constraints={"autocomplete": "email"},
    )

    assert value.endswith("@" + FICTIVE_EMAIL_DOMAIN)
    assert FICTIVE_EMAIL_DOMAIN == "twin.invalid"


def test_multi_token_autocomplete_uses_last_token():
    value = project_fictive_text_value(
        control_key="control-key-shipping-email",
        form_constraints={"autocomplete": "shipping email"},
    )

    assert value.endswith("@" + FICTIVE_EMAIL_DOMAIN)


def test_tel_category_projects_digits_only_payload():
    value = project_fictive_text_value(
        control_key="control-key-tel",
        form_constraints={"autocomplete": "tel"},
    )

    assert value.startswith("+0")
    assert value[2:].isdigit()


def test_date_category_projects_fixed_fictive_date():
    value = project_fictive_text_value(
        control_key="control-key-bday",
        form_constraints={"autocomplete": "bday"},
    )

    assert value == "1900-01-01"


def test_name_category_distinct_from_generic_category():
    name_value = project_fictive_text_value(
        control_key="control-key-name",
        form_constraints={"autocomplete": "given-name"},
    )

    generic_value = project_fictive_text_value(
        control_key="control-key-name",
        form_constraints=None,
    )

    assert name_value != generic_value
    assert "Twin Fictive" in name_value


def test_unknown_autocomplete_token_falls_back_to_generic():
    value = project_fictive_text_value(
        control_key="control-key-unknown-token",
        form_constraints={"autocomplete": "cc-number"},
    )

    assert "fictive" in value.lower()


def test_off_autocomplete_falls_back_to_generic():
    with_off = project_fictive_text_value(
        control_key="control-key-off",
        form_constraints={"autocomplete": "off"},
    )

    without_autocomplete = project_fictive_text_value(
        control_key="control-key-off",
        form_constraints=None,
    )

    assert with_off == without_autocomplete


def test_respects_maxlength_upper_bound():
    value = project_fictive_text_value(
        control_key="control-key-maxlength",
        form_constraints={"maxlength": "5"},
    )

    assert len(value) == 5


def test_respects_minlength_lower_bound():
    value = project_fictive_text_value(
        control_key="control-key-minlength",
        form_constraints={
            "autocomplete": "given-name",
            "minlength": "40",
        },
    )

    assert len(value) >= 40


def test_never_echoes_caller_supplied_real_looking_literal():
    # The projector has no parameter through which a REAL literal
    # could even be supplied -- it only ever derives from the opaque
    # control_key and generic shape constraints.
    value = project_fictive_text_value(
        control_key="control-key-no-literal-channel",
        form_constraints={
            "autocomplete": "family-name",
            "placeholder": "Introduzca su DNI real",
        },
    )

    assert "DNI" not in value
    assert "real" not in value.lower()

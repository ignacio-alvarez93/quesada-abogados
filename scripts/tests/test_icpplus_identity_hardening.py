from pathlib import Path


RUNNER = (
    Path(__file__)
    .resolve()
    .parents[1]
    / "icpplus_desktop_runner.py"
)


def test_identity_uses_verified_fields_and_autocomplete_barrier():
    text = RUNNER.read_text(
        encoding="utf-8"
    )

    identity_start = text.index(
        "STAGE = IDENTITY_FORM"
    )

    identity_end = text.index(
        "STAGE = IDENTITY_VALIDATED"
    )

    block = text[
        identity_start:
        identity_end
    ]

    assert (
        'control_key="identityNie"'
        in block
    )

    assert (
        'control_key="identityName"'
        in block
    )

    assert (
        "IDENTITY_AUTOCOMPLETE_BARRIER = ESC"
        in block
    )

    assert (
        'keyboard.press_and_release(\n'
        '        "esc"'
        in block
    )

    assert (
        "nationality_control"
        in block
    )

    name_index = block.index(
        'control_key="identityName"'
    )

    esc_index = block.index(
        "IDENTITY_AUTOCOMPLETE_BARRIER = ESC"
    )

    nationality_index = block.index(
        'description="NATIONALITY"'
    )

    assert (
        name_index
        < esc_index
        < nationality_index
    )


def test_nationality_must_be_confirmed_before_accept():
    text = RUNNER.read_text(
        encoding="utf-8"
    )

    identity_start = text.index(
        "STAGE = IDENTITY_FORM"
    )

    identity_end = text.index(
        "STAGE = IDENTITY_VALIDATED"
    )

    block = text[
        identity_start:
        identity_end
    ]

    expected_tokens = [
        "expected_nationality_value",
        "selectedValue",
        "NATIONALITY_SELECTION_CHECK",
        "NATIONALITY_SELECTION_RETRY = 1",
        "NATIONALITY_SELECTION_NOT_CONFIRMED",
        "NATIONALITY_SELECTION_VERIFIED = OK",
        "IDENTITY_ACCEPT = LIVE DOM",
    ]

    for token in expected_tokens:
        assert token in block

    verified_index = block.index(
        "NATIONALITY_SELECTION_VERIFIED = OK"
    )

    accept_index = block.index(
        "IDENTITY_ACCEPT = LIVE DOM"
    )

    assert (
        verified_index
        < accept_index
    )

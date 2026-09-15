from pathlib import Path


VIEW = Path(
    "frontend/views/twins_view.py"
)


def _card_source():
    source = VIEW.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def _twin_card("
    )

    end = source.index(
        "\ndef twins_view(",
        start,
    )

    return source[
        start:end
    ]


def test_empty_twin_uses_operational_discovery_card():
    source = _card_source()

    assert '"MATERIALIZED",' in source
    assert '"EMPTY",' in source

    assert (
        "Sin seed · Discovery desde cero"
        in source
    )


def test_empty_twin_cannot_start_localhost():
    source = _card_source()

    assert (
        'if status != "MATERIALIZED":'
        in source
    )

    assert (
        "start_button.disabled = True"
        in source
    )

    assert (
        "open_button.disabled = True"
        in source
    )


def test_twin_card_has_no_mercurio_specific_operational_copy():
    source = _card_source()

    assert (
        "Mercurio Discovery"
        not in source
    )

    assert (
        '"Mercurio completo"'
        not in source
    )

    assert (
        "recarga Mercurio"
        not in source
    )

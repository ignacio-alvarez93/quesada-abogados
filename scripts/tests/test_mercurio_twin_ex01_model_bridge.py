from pathlib import Path


ROOT = Path(__file__).parents[2]

GENERAL_JS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_general.js"
).read_text(
    encoding="utf-8"
)


def test_ex01_selection_enters_local_vertical():
    assert (
        'selected.value === "EX01"'
        in GENERAL_JS
    )

    assert (
        '"/mercurio/nuevaSolicitud-EX01.html"'
        in GENERAL_JS
    )

    assert (
        "window.location.assign"
        in GENERAL_JS
    )


def test_bridge_does_not_redirect_other_models():
    assert (
        '"Modelo "'
        in GENERAL_JS
    )

    assert (
        '" preparado en Mercurio Twin."'
        in GENERAL_JS
    )

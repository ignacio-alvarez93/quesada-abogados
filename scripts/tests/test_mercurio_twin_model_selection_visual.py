from pathlib import Path

from tools.mercurio_lab.general_pages import (
    render_general_page,
)


ROOT = Path(__file__).parents[2]

CSS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_general.css"
).read_text(
    encoding="utf-8"
)

JS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_general.js"
).read_text(
    encoding="utf-8"
)


def _html(province="33"):
    return render_general_page(
        f"/mercurio/seleccionModelo-{province}.html"
    ).decode("utf-8")


def test_model_selection_reproduces_17_observed_models():
    html = _html()

    assert (
        html.count('name="datosForL"')
        == 17
    )

    for model in (
        "EX00",
        "EX01",
        "EX02",
        "EX10",
        "EX19",
        "EX24",
        "EX26",
    ):
        assert (
            f'id="tini_{model}"'
            in html
        )

        assert (
            f'value="{model}"'
            in html
        )


def test_model_selection_preserves_real_automation_contract():
    html = _html()

    assert (
        html.count(
            'onclick="ocultaError()"'
        )
        == 17
    )

    assert 'id="btncont"' in html

    assert (
        'onclick="continuar(\'INI\');"'
        in html
    )


def test_model_selection_reproduces_real_labels():
    html = _html()

    assert (
        "EX01</strong>"
        in html
    )

    assert (
        "residencia temporal no lucrativa"
        in html
    )

    assert (
        "reagrupación familiar"
        in html
    )

    assert (
        "modificación de autorización"
        in html
    )


def test_model_selection_shows_selected_province():
    asturias = _html("33")
    madrid = _html("28")

    assert "ASTURIAS" in asturias
    assert "MADRID" in madrid


def test_model_selection_does_not_embed_real_identity():
    html = _html()

    assert "USUARIO LAB" in html
    assert 'data-lab-redacted="1"' in html


def test_model_selection_js_contract_exists():
    assert "window.ocultaError" in JS
    assert "window.continuar" in JS
    assert 'input[name="datosForL"]:checked' in JS


def test_model_selection_visual_tokens_exist():
    required = (
        ".mercurio-autofirma-notice",
        ".mercurio-model-heading",
        ".mercurio-model-list",
        ".mercurio-model-option",
        ".mercurio-model-actions",
    )

    for token in required:
        assert token in CSS

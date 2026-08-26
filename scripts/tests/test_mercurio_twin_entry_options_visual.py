from pathlib import Path

from tools.mercurio_lab.core.routes import (
    MERCURIO_ENTRADA_PATH,
)
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


def _html():
    return render_general_page(
        MERCURIO_ENTRADA_PATH
    ).decode("utf-8")


def test_options_reproduce_observed_dialog_structure():
    html = _html()

    assert 'id="twinEntryOptions"' in html
    assert "Opciones" in html
    assert "Cerrar" in html

    assert (
        'onclick="cerrarOpcion()"'
        in html
    )

    assert (
        'onclick="irOpcion()"'
        in html
    )


def test_options_preserve_real_automation_contract():
    html = _html()

    expected = (
        ("bscTran", "BT"),
        ("bscAdae", "BA"),
        ("bscRenovacion", "BR"),
        ("bscIniciales", "BI"),
        ("bscRecurso", "BREC"),
    )

    for element_id, value in expected:
        assert (
            f'id="{element_id}"'
            in html
        )

        assert (
            f'value="{value}"'
            in html
        )

    assert (
        html.count('name="opcion"')
        == 5
    )

    assert 'id="provincia"' in html
    assert 'name="provincia"' in html


def test_province_control_belongs_to_initial_request_option():
    html = _html()

    bi = html.index(
        'data-option-value="BI"'
    )

    province = html.index(
        'id="provincia"',
        bi,
    )

    brec = html.index(
        'data-option-value="BREC"'
    )

    assert bi < province < brec


def test_options_close_returns_to_idle():
    assert (
        "window.cerrarOpcion"
        in JS
    )

    assert (
        '"MERCURIO_ENTRY_IDLE"'
        in JS
    )


def test_options_visual_tokens_exist():
    required = (
        ".mercurio-options-overlay",
        ".mercurio-options-dialog",
        ".mercurio-options-dialog__header",
        ".mercurio-option__province",
        ".mercurio-options-dialog__footer",
    )

    for token in required:
        assert token in CSS

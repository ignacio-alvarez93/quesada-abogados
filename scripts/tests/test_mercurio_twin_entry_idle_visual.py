from pathlib import Path

from tools.mercurio_lab.core.routes import (
    MERCURIO_ENTRADA_PATH,
    MERCURIO_MODO_ACCESO_PATH,
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


def _html():
    return render_general_page(
        MERCURIO_ENTRADA_PATH
    ).decode("utf-8")


def test_entry_idle_reproduces_observed_content():
    html = _html()

    assert "V. 4.1.4" in html

    assert (
        "Seleccione la operación que desea realizar:"
        in html
    )

    assert (
        "CONSULTA DE SOLICITUD EXISTENTE"
        in html
    )

    assert "PRESENTACIÓN" in html
    assert "AUTOFIRMA" in html

    assert (
        "Información sobre el estado de"
        in html
    )


def test_entry_idle_preserves_existing_interaction_contract():
    html = _html()

    assert 'id="twinEntryInitial"' in html
    assert 'id="frmEntrada"' in html
    assert 'id="twinEntryOptions"' in html

    assert 'onclick="entrar(\'C\')"' in html

    assert (
        'onclick="mostrarOpcion()"'
        in html
    )

    assert (
        f'href="{MERCURIO_MODO_ACCESO_PATH}"'
        in html
    )


def test_entry_idle_does_not_embed_real_identity():
    html = _html()

    assert "USUARIO LAB" in html
    assert 'data-lab-redacted="1"' in html


def test_entry_idle_uses_visual_layout():
    required = (
        ".mercurio-entry-user",
        ".mercurio-entry-prompt",
        ".mercurio-entry-choice-list",
        ".mercurio-entry-choice",
        ".mercurio-entry-choice__button",
    )

    for token in required:
        assert token in CSS

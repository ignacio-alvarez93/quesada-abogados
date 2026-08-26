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
        MERCURIO_MODO_ACCESO_PATH
    ).decode("utf-8")


def test_modo_acceso_reproduces_observed_access_modes():
    html = _html()

    expected = {
        "IN": "INDIVIDUAL",
        "RP": "REPRESENTACIÓN",
        "RC": "COLABORADOR",
        "GA": "GESTORÍA",
        "GS": "GRADUADO",
        "AB": "ABOGACÍA",
        "FH": "FUNCIONARIO",
        "PC": "CORREOS",
    }

    for code, label in expected.items():
        assert (
            f'data-access-mode="{code}"'
            in html
        )
        assert label in html


def test_modo_acceso_preserves_observed_structure():
    html = _html()

    assert "V. 4.1.4" in html

    assert (
        "Presentación con certificado digital"
        in html
    )

    assert (
        "Información sobre certificados electrónicos"
        in html
    )

    assert "Requisitos Técnicos" in html
    assert "PLATAFORMA MERCURIO" in html
    assert "VOLVER" in html

    assert (
        html.count(
            f'href="{MERCURIO_ENTRADA_PATH}"'
        )
        == 8
    )


def test_modo_acceso_uses_visual_access_layout():
    required = (
        ".mercurio-access-list",
        ".mercurio-access-row",
        ".mercurio-access-description",
        ".mercurio-access-button",
    )

    for token in required:
        assert token in CSS

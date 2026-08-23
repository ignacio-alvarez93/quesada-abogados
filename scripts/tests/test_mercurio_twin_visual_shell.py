from pathlib import Path

from tools.mercurio_lab.core.routes import (
    MERCURIO_INICIO_PATH,
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


def test_general_pages_use_visual_shell():
    html = render_general_page(
        MERCURIO_INICIO_PATH
    ).decode("utf-8")

    assert (
        "/mercurio/resources/lab/"
        "mercurio_general.css"
        in html
    )

    assert 'class="mercurio-top"' in html
    assert 'class="mercurio-page"' in html
    assert "PROCEDIMIENTOS" in html
    assert "MIS EXPEDIENTES" in html
    assert "MIS NOTIFICACIONES" in html


def test_mercurio_inicio_matches_observed_structure():
    html = render_general_page(
        MERCURIO_INICIO_PATH
    ).decode("utf-8")

    assert "V. 4.1.4" in html
    assert "Autorizaciones de Extranjería" in html
    compact_html = "".join(
        html.split()
    )

    assert ">VOLVER<" in compact_html
    assert "PLATAFORMA MERCURIO" in html
    assert "CONTINUAR" in html
    assert "CONSULTAS Y SUGERENCIAS" in html


def test_visual_shell_has_core_mercurio_tokens():
    required = (
        "--mercurio-orange",
        ".mercurio-top",
        ".mercurio-page",
        ".mercurio-title",
        ".mercurio-button",
        ".mercurio-warning",
    )

    for token in required:
        assert token in CSS

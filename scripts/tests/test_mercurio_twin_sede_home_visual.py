from tools.mercurio_lab.core.routes import (
    SEDE_HOME_PATH,
)
from tools.mercurio_lab.general_pages import (
    render_general_page,
)


def test_sede_home_contains_main_shell():
    html = render_general_page(
        SEDE_HOME_PATH
    ).decode("utf-8")

    assert "Sede electrónica" in html
    assert "Procedimientos" in html
    assert "Utilidades" in html
    assert "Extranjería" in html
    assert '/procedimientos/index/categoria/34' in html


def test_sede_home_reproduces_real_upper_modules():
    html = render_general_page(
        SEDE_HOME_PATH
    ).decode("utf-8")

    assert "Bienvenido a la Sede Electrónica" in html
    assert "Destacados" in html
    assert "Mis expedientes" in html
    assert "¿Necesitas ayuda?" in html
    assert 'class="sede-home-top"' in html
    assert 'class="sede-home-bottom"' in html

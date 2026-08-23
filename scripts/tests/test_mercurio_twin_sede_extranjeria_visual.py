from tools.mercurio_lab.core.routes import (
    SEDE_EXTRANJERIA_PATH,
)
from tools.mercurio_lab.general_pages import (
    render_general_page,
)


def test_sede_extranjeria_contains_category_listing():
    html = render_general_page(
        SEDE_EXTRANJERIA_PATH
    ).decode("utf-8")

    assert "Extranjería" in html
    assert "7 procedimientos" in html
    assert "Inicio / Extranjería" in html
    assert "MERCURIO" in html
    assert '/pagina/index/directorio/mercurio2' in html


def test_sede_extranjeria_reproduces_seven_real_rows():
    html = render_general_page(
        SEDE_EXTRANJERIA_PATH
    ).decode("utf-8")

    assert (
        html.count(
            '<article\n    class="sede-category-item'
        )
        == 7
    )

    assert (
        "Solicitudes para la gestión colectiva "
        "de contrataciones en origen GECCO"
        in html
    )

    assert "/pagina/index/directorio/icpplus" in html
    assert "/pagina/index/directorio/infoext2" in html

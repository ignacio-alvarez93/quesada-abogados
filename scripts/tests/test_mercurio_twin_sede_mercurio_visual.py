from tools.mercurio_lab.core.routes import (
    SEDE_MERCURIO_PATH,
)
from tools.mercurio_lab.general_pages import (
    render_general_page,
)


def test_sede_mercurio_contains_access_cta():
    html = render_general_page(
        SEDE_MERCURIO_PATH
    ).decode("utf-8")

    assert "REQUISITOS TÉCNICOS DEL PROCEDIMIENTO" in html
    normalized = " ".join(html.split())

    assert (
        "Acceder a Solicitudes Telemáticas "
        "de Autorizaciones de Extranjería"
    ) in normalized
    assert '/mercurio/inicioMercurio.html' in html


def test_sede_mercurio_reproduces_real_information_flow():
    html = render_general_page(
        SEDE_MERCURIO_PATH
    ).decode("utf-8")

    normalized = " ".join(html.split())

    required = (
        "TÍTULO DEL PROCEDIMIENTO:",
        "SUMARIO:",
        "ÓRGANO RESPONSABLE:",
        "AYUDA:",
        "INSTRUCCIONES DEL PROCEDIMIENTO:",
        "Las autorizaciones iniciales",
        "Las renovaciones admitidas",
        "Pasos a seguir:",
        "REQUISITOS TÉCNICOS DEL PROCEDIMIENTO:",
        "Reglamento (UE) 2016/679",
    )

    for token in required:
        assert token in normalized

    assert 'id="submit"' in html

    assert (
        'value="Acceder a Solicitudes Telemáticas '
        'de Autorizaciones de Extranjería"'
        in html
    )

    assert (
        'action="/mercurio/inicioMercurio.html"'
        in html
    )

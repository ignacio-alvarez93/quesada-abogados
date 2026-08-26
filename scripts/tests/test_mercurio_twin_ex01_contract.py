from tools.mercurio_lab.ex01.pages import (
    render_ex01_page,
)
from tools.mercurio_lab.ex01.routes import (
    EX01_NEW_REQUEST_PATH,
)


def _html():
    return render_ex01_page(
        EX01_NEW_REQUEST_PATH
    ).decode("utf-8")


def test_ex01_route_exists():
    assert (
        EX01_NEW_REQUEST_PATH
        == "/mercurio/nuevaSolicitud-EX01.html"
    )


def test_ex01_reproduces_real_form_contract():
    html = _html()

    assert 'name="autorizacionMercurio"' in html

    assert (
        'action="/mercurio/salvarSolicitud.html"'
        in html
    )

    assert 'id="tipoFormulario"' in html
    assert 'value="EX01"' in html
    assert 'id="provincia"' in html
    assert 'value="33"' in html


def test_ex01_reproduces_observed_authorization_options():
    html = _html()

    expected = {
        "EX-01-1-01": "128",
        "EX-01-1-02": "129",
        "EX-01-2-01": "130",
        "EX-01-2-02": "131",
    }

    for element_id, value in expected.items():
        assert f'id="{element_id}"' in html
        assert f'value="{value}"' in html

    assert html.count('name="datosForAut"') == 4


def test_ex01_reproduces_real_tabs():
    html = _html()

    for element_id in (
        "tab-datos_autorizacion",
        "tab-datos_personales",
        "tab-datos_familiar",
        "tab-datos_presentador",
        "tab-datos_notificacion",
    ):
        assert f'id="{element_id}"' in html


def test_ex01_reproduces_automation_anchor_fields():
    html = _html()

    for element_id in (
        "extPasaporte",
        "extNie",
        "extNombre",
        "preNombrePresentador",
        "notNombreNotificacion",
        "btnConcluirSup",
    ):
        assert f'id="{element_id}"' in html


def test_ex01_does_not_embed_real_identity():
    html = _html()

    assert "USUARIO LAB" in html
    assert 'data-lab-redacted="1"' in html


def test_ex01_personal_controls_reproduce_observed_mercurio_classes():
    html = _html()

    expected = (
        'id="extPasaporte" class="mf-input__m cajaModf merval-upper"',
        'id="extNie" class="mf-input__m cajaModf merval-nie merval-upper"',
        'id="extFechaNacimiento" class="fecha mf-datepicker mf-input__m Obliga hasDatepicker merval-date"',
        'id="extLugarNacimiento" class="mf-input__l input_ll merval-upper"',
        'id="extCodigoProvincia" class="mf-input__m clConPrv disableLnk"',
        'id="extEmail" class="mf-input__m merval-mail"',
    )

    for fragment in expected:
        assert fragment in html


def test_ex01_personal_labels_are_independent_real_contract():
    html = _html()

    expected = (
        '<label for="extPasaporte">Pasaporte</label>',
        (
            '<label id="extNieSinToolTip" '
            'for="extNie">N.I.E.</label>'
        ),
        '<label for="extSexo">Sexo</label>',
        (
            '<label for="extFechaNacimiento">'
            'Fecha de nacimiento</label>'
        ),
        (
            '<label for="extPadre">'
            'Nombre del padre</label>'
        ),
        (
            '<label for="extMadre">'
            'Nombre de la madre</label>'
        ),
        (
            '<label for="extCodigoPostal">'
            'Código Postal</label>'
        ),
    )

    for fragment in expected:
        assert fragment in html

    assert 'class="ex01-field"' in html


def test_ex01_reproduces_real_tab_dom_contract():
    html = _html()

    required = (
        'id="merPestanero"',
        "r-tabs-nav ex01-tabs",
        'id="d-li-autorizacionSup"',
        'id="d-li-personales"',
        'id="pestPresentador"',
        'id="d-li-presentador"',
        'id="d-li-notificacion"',
        "DOMICILIO DE NOTIFICACIÓN",
    )

    for token in required:
        assert token in html


def test_ex01_reproduces_real_header_dom_contract():
    html = _html()

    required = (
        "mf-app-title",
        "Sede electrónica",
        "mf-window-header",
        "mf-app-title--container",
        'id="btVolver"',
        "mf-window-header--title",
        "Solicitud inicial",
        "VOLVER",
        "mf-layout--row",
        "mf-layout--module__xl",
        "mf-layout--column",
        "mf-paragraph-header",
        "subgrupo",
        "SOLICITUD INICIAL:",
        "ex01-shell-flow-spacer",
        'data-lab-redacted="1"',
    )

    for token in required:
        assert token in html


def test_ex01_uses_observed_mercurio_catalogs():
    html = _html()

    assert html.count(
        '<option value="401">AFGANISTAN</option>'
    ) == 2

    # ESPAÑA existe como país pero Mercurio
    # no la ofrece como nacionalidad extranjera.
    assert html.count(
        '<option value="109">ESPAÑA</option>'
    ) == 1

    assert (
        '<option value="15">A CORUÑA</option>'
        in html
    )

    assert (
        '<option value="33">ASTURIAS</option>'
        in html
    )

    assert (
        '<option value="1">ALLANDE</option>'
        in html
    )

    assert (
        '<option value="78">'
        'YERNES Y TAMEZA</option>'
        in html
    )

    for token in (
        'datlo="extCodigoLocalidad"',
        'datmu="extCodigoMunicipio"',
        'datpr="extCodigoProvincia"',
    ):
        assert token in html

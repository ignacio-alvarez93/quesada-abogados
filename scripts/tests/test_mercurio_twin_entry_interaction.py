from pathlib import Path

from tools.mercurio_lab.core.routes import (
    MERCURIO_ENTRADA_PATH,
)
from tools.mercurio_lab.general_pages import (
    render_general_page,
)


ROOT = Path(__file__).parents[2]

JS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_general.js"
).read_text(
    encoding="utf-8"
)


def _entry_html() -> str:
    body = render_general_page(
        MERCURIO_ENTRADA_PATH
    )

    assert body is not None

    return body.decode("utf-8")


def test_entry_starts_in_idle_state():
    html = _entry_html()

    assert (
        'data-mercurio-state="MERCURIO_ENTRY_IDLE"'
        in html
    )

    assert (
        "CONTINUAR CONSULTA DE SOLICITUD EXISTENTE"
        in html
    )

    assert "CONTINUAR PRESENTACIÓN" in html
    assert 'onclick="mostrarOpcion()"' in html


def test_entry_renders_observed_options_contract():
    html = _entry_html()

    assert html.count('name="opcion"') == 5

    assert 'id="bscTran"' in html
    assert 'value="BT"' in html

    assert 'id="bscAdae"' in html
    assert 'value="BA"' in html

    assert 'id="bscRenovacion"' in html
    assert 'value="BR"' in html

    assert 'id="bscIniciales"' in html
    assert 'value="BI"' in html

    assert 'id="bscRecurso"' in html
    assert 'value="BREC"' in html

    assert 'id="provincia"' in html
    assert 'value="33"' in html
    assert "ASTURIAS" in html

    assert 'onclick="irOpcion()"' in html


def test_entry_has_real_committed_hidden_contract():
    html = _entry_html()

    assert 'id="frmEntrada"' in html
    assert 'name="tipoSolicitud"' in html
    assert 'name="codProvincia"' in html


def test_entry_javascript_models_observed_transition():
    assert "mostrarOpcion" in JS
    assert "irOpcion" in JS

    assert (
        '"MERCURIO_ENTRY_OPTIONS"'
        in JS
    )

    assert (
        '"MERCURIO_ENTRY_SELECTION_COMMITTED"'
        in JS
    )

    assert (
        'byId("tipoSolicitud").value = "INI"'
        in JS
    )

    assert (
        'byId("codProvincia").value = province.value'
        in JS
    )

    assert 'selected.value !== "BI"' in JS

    assert (
        'province.value !== "33"'
        not in JS
    )

    assert (
        '"/mercurio/seleccionModelo-"'
        in JS
    )

    assert (
        "+ province.value"
        in JS
    )

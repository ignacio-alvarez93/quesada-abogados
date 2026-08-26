from tools.mercurio_lab.catalogs.reference import (
    country_options,
    locality_options,
    municipality_options,
    nationality_options,
    province_options,
)
from tools.mercurio_lab.ex01.pages import (
    render_ex01_page,
)
from tools.mercurio_lab.ex01.routes import (
    EX01_NEW_REQUEST_PATH,
)


def _html() -> str:
    page = render_ex01_page(
        EX01_NEW_REQUEST_PATH
    )

    assert page is not None

    return page.decode("utf-8")


def test_mercurio_reference_catalog_counts():
    assert len(country_options()) == 205
    assert len(nationality_options()) == 204
    assert len(province_options()) == 53
    assert len(
        municipality_options("33")
    ) == 79
    assert len(
        locality_options("33", "24")
    ) == 128


def test_spanish_nationality_is_not_offered():
    countries = dict(
        country_options()
    )

    nationalities = dict(
        nationality_options()
    )

    assert countries["109"] == "ESPAÑA"
    assert "109" not in nationalities


def test_gijon_reference_contract():
    municipalities = dict(
        municipality_options("33")
    )

    localities = dict(
        locality_options("33", "24")
    )

    assert municipalities["24"] == "GIJON"
    assert localities["030000"] == "CABUEÑES"


def test_ex01_embeds_runtime_catalog_contract():
    html = _html()

    assert (
        'id="mercurioTwinCatalogs"'
        in html
    )

    assert (
        'type="application/json"'
        in html
    )

    assert '"33:24":[' in html
    assert '"value":"030000"' in html
    assert '"label":"CABUEÑES"' in html

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


def test_general_geometry_uses_real_content_width():
    assert (
        "width: min(1200px, calc(100% - 32px));"
        in CSS
    )


def test_access_geometry_matches_real_grid():
    required = (
        "width: min(994px, 100%);",
        "grid-template-columns: repeat(6, 1fr);",
        "column-gap: 26px;",
        "grid-auto-rows: 280px;",
        "width: 314px;",
        "grid-column: 2 / span 2;",
        "grid-column: 4 / span 2;",
    )

    for token in required:
        assert token in CSS


def test_entry_idle_is_two_column_layout():
    assert (
        "grid-template-columns: repeat(2, minmax(0, 1fr));"
        in CSS
    )

    assert (
        "width: min(396px, 100%);"
        in CSS
    )


def test_options_geometry_matches_real_dialog():
    html = render_general_page(
        MERCURIO_ENTRADA_PATH
    ).decode("utf-8")

    assert (
        "Seleccione la opción que quiere realizar"
        in html
    )

    required = (
        "width: min(479px, calc(100% - 24px));",
        "height: 36px;",
        "min-height: 352px;",
        "height: 57px;",
        "width: 200px;",
        "height: 33px;",
    )

    for token in required:
        assert token in CSS


def test_model_geometry_uses_real_vertical_pitch():
    required = (
        "width: min(1069px, 100%);",
        "height: 30px;",
        "width: 13px;",
        "height: 13px;",
        "width: 594px;",
        "width: 135px;",
    )

    for token in required:
        assert token in CSS


def test_access_page_still_exposes_all_modes():
    html = render_general_page(
        MERCURIO_MODO_ACCESO_PATH
    ).decode("utf-8")

    assert (
        html.count(
            'class="mercurio-access-row"'
        )
        == 8
    )


def test_geo_1b_reproduces_sede_vertical_shell():
    html = render_general_page(
        MERCURIO_ENTRADA_PATH
    ).decode("utf-8")

    assert 'class="mercurio-sede-brand"' in html
    assert "Sede electrónica" in html
    assert "Administraciones Públicas" in html

    assert "height: 168px;" in CSS


def test_geo_1b_reserves_real_scrollbar_width():
    assert "overflow-y: scroll;" in CSS


def test_geo_1b_calibrates_entry_buttons():
    assert (
        ".mercurio-entry-choice:nth-child(2)"
        in CSS
    )

    assert "width: 249px;" in CSS


def test_geo_1b_calibrates_options_position():
    assert "left: 124px;" in CSS
    assert "padding: 42px 14px 14px;" in CSS
    assert "line-height: 28px;" in CSS


def test_geo_1b_calibrates_model_vertical_offset():
    assert "margin-bottom: 113px;" in CSS
    assert "margin-top: 36px;" in CSS


def test_geo_1c_calibrates_options_internal_geometry():
    assert "padding-top: 56px;" in CSS
    assert "left: 3px;" in CSS
    assert (
        "grid-template-columns: 203px 200px;"
        in CSS
    )
    assert "column-gap: 8px;" in CSS

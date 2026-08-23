from pathlib import Path


ROOT = Path(__file__).parents[2]

CSS = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "static"
    / "mercurio_ex01.css"
).read_text(
    encoding="utf-8"
)


def test_ex01_real_panel_vertical_alignment_is_frozen():
    assert "margin-top: 201.31px;" in CSS
    assert "height: 683.95px;" in CSS
    assert "height: 1401.06px;" in CSS


def test_ex01_real_input_geometry_is_frozen():
    assert "163.89px" in CSS
    assert "width: 280px;" in CSS
    assert "height: 33px;" in CSS


def test_ex01_real_row_pitch_is_frozen():
    assert "row-gap: 30.95px;" in CSS


def test_ex01_birthplace_real_width_is_frozen():
    assert (
        ".ex01-field:has(#extLugarNacimiento)"
        in CSS
    )
    assert "width: 420px;" in CSS


def test_ex01_real_section_gaps_are_frozen():
    assert (
        ".ex01-field:has(#extTipoVia)"
        in CSS
    )

    assert (
        ".ex01-field:has(#extCodigoProvincia)"
        in CSS
    )

    assert "margin-top: 63.95px;" in CSS


def test_ex01_real_authorization_geometry_is_frozen():
    assert (
        "#ex01AuthorizationOptions"
        in CSS
    )

    assert "padding-top: 72.27px;" in CSS

    assert (
        ".ex01-option:has(#EX-01-2-01)"
        in CSS
    )


def test_ex01_real_continue_button_geometry_is_frozen():
    assert "width: 135.23px;" in CSS
    assert "height: 38px;" in CSS

    assert "#btnConcluirSup" in CSS
    assert "width: 125.12px;" in CSS


def test_ex01_authorization_continue_bottom_gap_is_frozen():
    assert (
        "#tab-datos_autorizacion > .mf-layout--row.tc"
        in CSS
    )
    assert "bottom: 36.95px;" in CSS


def test_ex01_presenter_special_widths_are_frozen():
    assert "#preNombrePresentador" in CSS
    assert "889.55px" in CSS
    assert "#preTipodocumentoPresentador" in CSS
    assert "#preNiePresentador" in CSS


def test_ex01_presenter_real_section_offsets_are_frozen():
    assert "top: 24.20px;" in CSS
    assert "top: 152.14px;" in CSS
    assert "top: 152.19px;" in CSS
    assert "bottom: 36.93px;" in CSS


def test_ex01_notification_real_layout_is_frozen():
    assert "#notNombreNotificacion" in CSS
    assert "width: 420px;" in CSS
    assert "#notTipodocumentoNotificacion" in CSS
    assert "#notNieNotificacion" in CSS
    assert "left: -597.98px;" in CSS
    assert "left: 598.02px;" in CSS


def test_ex01_notification_actions_are_frozen():
    assert "#tab-datos_notificacion .ex01-check" in CSS
    assert "top: 76.83px;" in CSS
    assert "bottom: 26.97px;" in CSS



def test_ex01_personal_controls_use_real_visual_contract():
    css = (
        Path(
            "tools/mercurio_lab/static/"
            "mercurio_ex01.css"
        )
        .read_text(encoding="utf-8")
    )

    required = (
        "font-family: sans-serif;",
        "font-size: 14px;",
        "background-color: rgb(230, 244, 247);",
        "border-bottom-width: 1px;",
        "line-height: 18px;",
        "opacity: 0.5;",
        "pointer-events: none;",
        "padding-right: 28px;",
        "background-size:",
        "19px;",
    )

    for token in required:
        assert token in css


def test_ex01_birth_date_uses_local_calendar_asset():
    css = (
        Path(
            "tools/mercurio_lab/static/"
            "mercurio_ex01.css"
        )
        .read_text(encoding="utf-8")
    )

    assert (
        "#tab-datos_personales #extFechaNacimiento"
        in css
    )

    assert (
        'url("/mercurio/resources/lab/calendar.svg")'
        in css
    )

    assert "padding-right: 28px;" in css

    asset = Path(
        "tools/mercurio_lab/static/calendar.svg"
    )

    assert asset.exists()
    assert 'width="19"' in asset.read_text(
        encoding="utf-8"
    )

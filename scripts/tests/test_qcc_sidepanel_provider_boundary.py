from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SIDEPANEL = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
)

CORE = (
    SIDEPANEL
    / "sidepanel.js"
)

HTML = (
    SIDEPANEL
    / "index.html"
)

PROVIDER = (
    SIDEPANEL
    / "providers"
    / "mercurio.js"
)


def test_mercurio_provider_exists():
    assert PROVIDER.is_file()


def test_sidepanel_loads_core_before_provider():
    html = HTML.read_text(
        encoding="utf-8"
    )

    core_position = html.index(
        'src="sidepanel.js"'
    )

    provider_position = html.index(
        'src="providers/mercurio.js"'
    )

    assert (
        core_position
        < provider_position
    )


def test_sidepanel_core_has_no_provider_literals():
    core = CORE.read_text(
        encoding="utf-8"
    ).upper()

    forbidden = (
        "MERCURIO",
        "ICP_PLUS",
        "SELENIUMBASE_ASSISTED",
        "DESKTOP_GUI_ASSISTED",
    )

    for literal in forbidden:
        assert literal not in core


def test_mercurio_transport_lives_in_provider():
    provider = PROVIDER.read_text(
        encoding="utf-8"
    )

    required = (
        "handleMercurioRealCatalogHarvest",
        "handleMercurioRealCatalogProbe",
        "QCC_MERCURIO_REAL_CATALOG_STEP",
        "QCC_MERCURIO_REAL_CATALOG_RESTORE",
        "QCC_MERCURIO_REAL_CATALOG_PROBE",
    )

    for literal in required:
        assert literal in provider


def test_generic_catalog_button_has_generic_identity():
    html = HTML.read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-catalog-relation-harvest"'
        in html
    )

    assert (
        'id="tool-mercurio-real-harvest"'
        not in html
    )


def test_provider_does_not_reimplement_navigation_governance():
    provider = PROVIDER.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "renderLiveNavigation(",
        "navigationDecisionLabel(",
        "govern_navigation_plan",
        "AUTOMATION_ALLOWED",
        "HUMAN_ONLY",
    )

    for literal in forbidden:
        assert literal not in provider
